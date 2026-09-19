"""The OpenInference dialect.

OpenInference rides on OTel spans and carries its meaning in flat, dotted
attribute keys: ``openinference.span.kind``, ``llm.token_count.prompt``,
``input.value`` and its ``input.mime_type``, ``tool_call.id``.

This file is the only place in the library that knows any of that
(``DESIGN.md`` §3). It transcribes; it does not interpret. Every place the
dialect is silent, the answer here is ``None``, ``absent``, or a diagnostic --
never a plausible guess (``ADAPTERS.md`` §1).

Two things it deliberately does **not** do:

* It never pairs a tool call with a result by name, timing, or proximity.
  Pairing happens only through an id the dialect itself carries, because a
  guessed pairing is indistinguishable from a real one downstream.
* It never marks a payload ``truncated``. OpenInference signals redaction
  (with a literal marker string) but has no truncation signal, so that state
  is simply never produced here. Inventing one would be claiming the
  instrumentor said something it did not.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence

from spanweave import jsoncodec
from spanweave.diagnostics import (
    PAYLOAD_PARSE_FAILED,
    UNKNOWN_SPAN_KIND,
    UNMAPPED_ATTRIBUTES,
)
from spanweave.model import (
    Diagnostic,
    DiagnosticLevel,
    JsonValue,
    NodeKind,
    Payload,
    PayloadState,
    RawRecord,
    Status,
    Usage,
)
from spanweave.read import record_digest
from spanweave.seam import (
    CallRole,
    NormalizedSpan,
    SpanLink,
    parent_ref,
    span_ref,
    unreadable_fields,
)

ADAPTER_ID = "openinference"
ADAPTER_VERSION = "0.1.0"

# The marker key. Distinctive: no other dialect emits it, and its absence is
# not something to be optimistic about (ADAPTERS.md §2).
MARKER_PREFIX = "openinference."
SPAN_KIND = "openinference.span.kind"

# openinference-instrumentation replaces a hidden payload with this literal
# string rather than omitting the attribute, which is why `redacted` and
# `absent` stay distinguishable here.
REDACTED_MARKER = "__REDACTED__"

KINDS: Mapping[str, NodeKind] = {
    "AGENT": NodeKind.AGENT,
    "LLM": NodeKind.LLM,
    "TOOL": NodeKind.TOOL,
    "RETRIEVER": NodeKind.RETRIEVER,
    "EMBEDDING": NodeKind.EMBEDDING,
    "CHAIN": NodeKind.CHAIN,
}

INPUT_VALUE = "input.value"
INPUT_MIME = "input.mime_type"
OUTPUT_VALUE = "output.value"
OUTPUT_MIME = "output.mime_type"
TOOL_NAME = "tool.name"
TOOL_CALL_ID = "tool_call.id"

# A requested call id, and ONLY from the span's own output. The dialect marks
# who spoke in the message-list prefix -- `output_messages` is what the model
# said, `input_messages` is what was shown to it -- and a follow-up turn
# carries the previous turn's tool call in its input, because the protocol
# requires the history to be resent. Matching the suffix alone would read that
# echo as a second request (see `tool_call_history_echo`).
OUTPUT_MESSAGES = "llm.output_messages."
CALL_ID_SUFFIX = ".tool_call.id"
#: Beside the id, on the same requested call. Read only so that a call
#: nothing fulfils can still be attributed to the tool it named
#: (`SPEC.md` §3.7): the requested call has no node, so this is the only
#: place the name can be carried.
CALL_NAME_SUFFIX = ".tool_call.function.name"

# A tool RESULT the span was given, as opposed to a call it requested. The
# dialect renders an OpenAI tool-result message -- {"role": "tool",
# "tool_call_id": ...} -- as a flat `.message.tool_call_id` under
# `llm.input_messages.*`, with `.message.role == "tool"`. Two things separate
# it from the assistant echo alongside it: the role, and the attribute form
# (the echo nests under `.message.tool_calls.N.tool_call.id`).
INPUT_MESSAGES = "llm.input_messages."
RESULT_ID_SUFFIX = ".message.tool_call_id"
ROLE_SUFFIX = ".message.role"
TOOL_ROLE = "tool"
LLM_MODEL = "llm.model_name"
EMBEDDING_MODEL = "embedding.model_name"
TOKEN_PREFIX = "llm.token_count."

# The token counts the model has fields for; anything else counted goes to
# `Usage.extra` rather than being dropped or renamed.
TOKEN_FIELDS = {
    "prompt": "input_tokens",
    "completion": "output_tokens",
    "total": "total_tokens",
}

# Record keys this adapter reads. Anything else at the top level is reported
# in `unmapped` -- including `events`, which Phase 1 does not model.
KNOWN_RECORD_KEYS = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_id",
        "name",
        "start_time",
        "end_time",
        "status",
        "status_message",
        "attributes",
        "links",
    }
)

STATUSES: Mapping[str, Status] = {
    "OK": Status.OK,
    "ERROR": Status.ERROR,
    "UNSET": Status.UNSET,
}


class OpenInferenceAdapter:
    """Translates OpenInference spans into ``NormalizedSpan``."""

    id = ADAPTER_ID
    version = ADAPTER_VERSION

    def detect(self, sample: Sequence[JsonValue]) -> float:
        """Total by construction: every branch is an ``isinstance`` guard.

        There is deliberately **no** blanket ``except`` here. One would turn a
        broken adapter into a confident ``0.0`` and let a different adapter win
        unopposed -- the silent-wrong-graph outcome the registry exists to
        prevent -- whereas an escaping exception is caught by
        ``AdapterRegistry.confidences`` and reported as ``adapter_detect_failed``
        naming this adapter (`TASKS.md` 2.12).
        """
        for record in sample:
            if not isinstance(record, dict):
                continue
            attributes = record.get("attributes")
            if not isinstance(attributes, dict):
                continue
            if any(str(key).startswith(MARKER_PREFIX) for key in attributes):
                # A distinctive marker, and 0.9 rather than 1.0: certainty is
                # not ours to declare (ADAPTERS.md §2).
                return 0.9
        return 0.0

    def parse(self, records: Iterable[JsonValue]) -> Iterator[NormalizedSpan]:
        for index, record in enumerate(records, start=1):
            yield _parse_record(index, record)


def _parse_record(index: int, record: JsonValue) -> NormalizedSpan:
    raw = RawRecord(source=record, line_number=index)
    if not isinstance(record, dict):
        # Not a span-shaped thing at all. It is still kept, as an `unknown`
        # node carrying the record verbatim: "we did not understand it" is a
        # reportable outcome, "it vanished" is a bug.
        return NormalizedSpan(
            source_key=record_digest(record),
            kind=NodeKind.UNKNOWN,
            name="",
            raw=raw,
            diagnostics=(
                Diagnostic(
                    code=UNKNOWN_SPAN_KIND,
                    message=(
                        "record is not a JSON object, so it carries no span "
                        "kind; kept as an unknown node"
                    ),
                    source=record,
                    adapter=ADAPTER_ID,
                ),
            ),
        )

    attributes = record.get("attributes")
    attributes = attributes if isinstance(attributes, dict) else {}
    consumed: set[str] = set()
    diagnostics: list[Diagnostic] = []

    # `span_ref` rather than `_as_str`, because `""` is not a span id: a
    # record that states one is stating no id, exactly as one that omits the
    # field is (`SPEC.md` §3.6). It is read at the seam so the two adapters
    # cannot drift, and so the *reference* rule `parent_ref` applies below
    # keeps the ground it stands on -- no node can be named `""`.
    span_id = span_ref(record.get("span_id"))
    # The dialect's own id where there is one, and otherwise the record's
    # canonical digest -- content, never position. The index is right there
    # and it is wrong: it would bind the node id to where the record sat in
    # the file, and a re-export with the lines swapped would rename every
    # span (`SPEC.md` §3.6 rule 2).
    source_key = span_id if span_id is not None else record_digest(record)

    kind, normalized = _kind_of(attributes, consumed, diagnostics, record)
    inputs = _payload(attributes, INPUT_VALUE, INPUT_MIME, consumed, diagnostics)
    outputs = _payload(attributes, OUTPUT_VALUE, OUTPUT_MIME, consumed, diagnostics)
    usage = _usage(attributes, consumed)
    operation, model = _operation(attributes, consumed)
    if model is not None:
        normalized["model"] = model
    call_ids, call_role, call_names = _call(attributes, consumed, operation)
    # Before `unmapped` is computed, because this reads attributes and marks
    # what it read: a key consumed after the tally is a key still reported.
    received_call_ids = _received_results(attributes, consumed)
    status, status_note = _status(record)

    started_at, ended_at, unreadable_times = _timestamps(record)

    unmapped = sorted(
        [str(key) for key in attributes if str(key) not in consumed]
        + [f"<record>.{key}" for key in record if key not in KNOWN_RECORD_KEYS]
        + unreadable_times
        + unreadable_fields(record)
    )
    if unmapped:
        diagnostics.append(
            Diagnostic(
                code=UNMAPPED_ATTRIBUTES,
                message=(
                    "attributes this adapter does not normalize, kept verbatim "
                    f"in raw: {', '.join(unmapped)}"
                ),
                level=DiagnosticLevel.INFO,
                # Keys only. The values are already in `raw`, and copying
                # payload content into a diagnostic is an exposure surface
                # with no benefit (SPEC.md §3.7).
                source=list(unmapped),
                adapter=ADAPTER_ID,
            )
        )

    return NormalizedSpan(
        source_key=source_key,
        span_id=span_id,
        parent_id=parent_ref(record.get("parent_id")),
        trace_id=_as_str(record.get("trace_id")),
        kind=kind,
        name=_as_str(record.get("name")) or "",
        operation=operation,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        status_note=status_note,
        inputs=inputs,
        outputs=outputs,
        usage=usage,
        call_ids=call_ids,
        call_role=call_role,
        call_names=call_names,
        links=_links(record),
        received_call_ids=received_call_ids,
        attributes=normalized,
        unmapped=tuple(unmapped),
        raw=RawRecord(source=record, source_id=span_id, line_number=index),
        diagnostics=tuple(diagnostics),
    )


def _kind_of(
    attributes: Mapping[str, JsonValue],
    consumed: set[str],
    diagnostics: list[Diagnostic],
    record: JsonValue,
) -> tuple[NodeKind, dict[str, JsonValue]]:
    normalized: dict[str, JsonValue] = {}
    reported = attributes.get(SPAN_KIND)
    if reported is None:
        # `get` answers `None` twice over -- for a key the span never carried
        # and for one carrying `null` -- and those are different facts. The
        # kind is unknown either way, but only the second is something the
        # adapter was told and could not read, so only the second is a key
        # that decided nothing and stays reported (`SPEC.md` §3.7). The
        # message says which one happened, because one that says "no
        # attribute" of a key that was sent is untrue.
        diagnostics.append(
            Diagnostic(
                code=UNKNOWN_SPAN_KIND,
                message=(
                    f"{SPAN_KIND} was reported as null, so the kind is "
                    f"unknown; the span is kept, the record is preserved "
                    f"verbatim, and the key stays reported as unmapped"
                    if SPAN_KIND in attributes
                    else f"no {SPAN_KIND} attribute, so the kind is unknown; "
                    f"the span is kept and the record is preserved verbatim"
                ),
                source=record,
                adapter=ADAPTER_ID,
            )
        )
        return NodeKind.UNKNOWN, normalized

    # Anything else was read: `str` renders it -- the library's rendering,
    # which writes a long integer whole on every interpreter setting -- and
    # whatever it renders is kept verbatim as `reported_kind` below when it
    # maps to no `NodeKind`.
    consumed.add(SPAN_KIND)
    text = jsoncodec.python_text(reported)
    mapped = KINDS.get(text.upper())
    if mapped is not None:
        return mapped, normalized

    # Never force a near-miss into a neighbouring kind: a wrong kind is worse
    # than an honest `unknown`, because `unknown` is visible and a wrong kind
    # is not (ADAPTERS.md §3).
    normalized["reported_kind"] = text
    diagnostics.append(
        Diagnostic(
            code=UNKNOWN_SPAN_KIND,
            message=(
                f"{SPAN_KIND}={text!r} does not map to a NodeKind; kept as "
                f"unknown, with the reported kind preserved in attributes"
            ),
            source=text,
            adapter=ADAPTER_ID,
        )
    )
    return NodeKind.UNKNOWN, normalized


def _payload(
    attributes: Mapping[str, JsonValue],
    value_key: str,
    mime_key: str,
    consumed: set[str],
    diagnostics: list[Diagnostic],
) -> Payload:
    if value_key not in attributes:
        # The instrumentor emitted nothing. Not the same as emitting nothing
        # *in* something (SPEC.md §3.3). An `absent` payload carries no mime
        # either, so a mime type stated beside no value is never read here and
        # is not consumed: it stays reported (`SPEC.md` §3.7).
        return Payload.absent()

    consumed.add(value_key)
    mime = _as_str(attributes.get(mime_key))
    if mime is not None:
        # Consumed where it is READ. A mime the adapter cannot read as a
        # string types nothing -- the payload is `present` with no mime,
        # exactly as if the key had never been sent -- so it decided nothing
        # and stays reported (`SPEC.md` §3.7).
        consumed.add(mime_key)
    reported = attributes[value_key]
    text = _as_text(reported)
    if text is None:
        # The value arrived structured -- an exporter that can carry nested
        # attributes -- and nests deeper than `json.dumps` will descend, so
        # there is no text to keep. Reported rather than raised, for the same
        # reason the parse failure below is (`SPEC.md` §7); the value itself
        # still survives verbatim in the node's raw record (§3.5), which is
        # the only place it was ever going to.
        diagnostics.append(
            Diagnostic(
                code=PAYLOAD_PARSE_FAILED,
                message=(
                    f"{value_key} was reported as a structured value that "
                    f"nests deeper than the JSON encoder will descend, so no "
                    f"text form of it could be produced; it survives verbatim "
                    f"on the node's raw record"
                ),
                adapter=ADAPTER_ID,
            )
        )
        return Payload(state=PayloadState.PRESENT, mime=mime, value=None, raw=None)

    if text == REDACTED_MARKER:
        return Payload(state=PayloadState.REDACTED, mime=mime, raw=text)

    if mime is not None and "json" in mime.lower():
        try:
            value = jsoncodec.loads(text)
        # RecursionError is `json`'s answer to nesting it will not descend.
        # A payload that cannot be read is `present` either way (`SPEC.md` §7);
        # letting one of the two escape would take the whole build down.
        except (ValueError, RecursionError) as failure:
            diagnostics.append(
                Diagnostic(
                    code=PAYLOAD_PARSE_FAILED,
                    message=(
                        f"{value_key} declares {mime} but did not parse "
                        f"({failure}); the text is kept verbatim"
                    ),
                    adapter=ADAPTER_ID,
                )
            )
            # State stays `present`: something was reported, we just could not
            # read it. `raw` is where it survives.
            return Payload(state=PayloadState.PRESENT, mime=mime, value=None, raw=text)
        return Payload(state=_state_of(value), mime=mime, value=value, raw=text)

    return Payload(state=_state_of(text), mime=mime, value=text, raw=text)


def _as_text(reported: JsonValue) -> str | None:
    """The reported value as text, or ``None`` when it cannot be rendered.

    `json.dumps` answers nesting it will not descend with ``RecursionError``,
    the mirror image of what `json.loads` does to a too-deep string, and it is
    not a ``ValueError``. An adapter never raises on a payload (`SPEC.md` §7),
    so the failure comes back as a value the caller reports.
    """
    if isinstance(reported, str):
        return reported
    try:
        return jsoncodec.encode(reported, json.dumps)
    except RecursionError:
        return None


def _state_of(value: JsonValue) -> PayloadState:
    if value in ("", {}, [], None):
        return PayloadState.EMPTY
    return PayloadState.PRESENT


def _usage(attributes: Mapping[str, JsonValue], consumed: set[str]) -> Usage | None:
    counts: dict[str, int] = {}
    extra: dict[str, int] = {}
    for key, value in attributes.items():
        name = str(key)
        if not name.startswith(TOKEN_PREFIX):
            continue
        consumed.add(name)
        number = _as_int(value)
        if number is None:
            consumed.discard(name)  # not a count; report it as unmapped
            continue
        suffix = name[len(TOKEN_PREFIX) :]
        field = TOKEN_FIELDS.get(suffix)
        if field is not None:
            counts[field] = number
        else:
            extra[suffix] = number
    if not counts and not extra:
        return None
    # total_tokens stays absent unless the dialect reported one. Adding
    # prompt and completion would state a fact the telemetry did not.
    return Usage(**counts, extra=extra)


def _operation(
    attributes: Mapping[str, JsonValue], consumed: set[str]
) -> tuple[str | None, str | None]:
    """The tool / model / retriever name, when the dialect names one.

    Each key is consumed where it is READ, not before (`SPEC.md` §3.7): a name
    the adapter cannot read as a string decided nothing -- `operation` and
    `model` stay `None` -- so it stays in `unmapped` rather than being claimed
    as mapped. All three are read even though at most two are used, because a
    readable name that merely lost to another key was still read and acted on.
    """
    tool = _as_str(attributes.get(TOOL_NAME))
    llm = _as_str(attributes.get(LLM_MODEL))
    embedding = _as_str(attributes.get(EMBEDDING_MODEL))
    consumed.update(
        key
        for key, value in (
            (TOOL_NAME, tool),
            (LLM_MODEL, llm),
            (EMBEDDING_MODEL, embedding),
        )
        if value is not None
    )
    model = llm or embedding
    if tool is not None:
        return tool, model
    return model, model


def _call(
    attributes: Mapping[str, JsonValue], consumed: set[str], operation: str | None
) -> tuple[tuple[str, ...], CallRole | None, dict[str, str]]:
    """Recover the call ids the dialect carries. Never guess one.

    A span that *answers* a call carries ``tool_call.id``. A span that
    *requests* one -- or several, which is the common case -- states the ids
    in **its own output messages**. Both are the dialect stating an id.

    The `output_messages` prefix is load-bearing, not decoration. The same id
    reappears on the *next* turn's span under `input_messages`, because the
    protocol requires the whole conversation to be resent -- so a rule that
    matched the id anywhere would make a span that requested nothing look like
    a requester, and the builder would emit a `call_result` edge with
    `warrant=explicit` for a relation the telemetry never stated. An echo of a
    reference is not the reference (`SPEC.md` §4.4).

    Ids echoed in input context are left unconsumed, so they surface in
    `unmapped` and are reported rather than dropped. They are evidence of
    context, and the library has no edge kind for that.

    An id the adapter cannot read is not an id: it states no call, and it is
    consumed only where it is read (`SPEC.md` §3.7), so it stays reported like
    any other key read and not usable.
    """
    fulfilling = _as_str(attributes.get(TOOL_CALL_ID))
    if fulfilling is not None:
        consumed.add(TOOL_CALL_ID)
        # A fulfiller's own `operation` already names the tool; carrying it
        # here too is what lets both unpaired codes share one `source` shape.
        named = {fulfilling: operation} if operation is not None else {}
        return (fulfilling,), CallRole.FULFILLER, named

    requested: list[str] = []
    names: dict[str, str] = {}
    for key in sorted(str(k) for k in attributes):
        if not key.startswith(OUTPUT_MESSAGES) or not key.endswith(CALL_ID_SUFFIX):
            continue
        found = _as_str(attributes[key])
        if found is None:
            # Nothing was recovered here, so nothing was mapped: the key that
            # stated an unreadable id stays reported (`SPEC.md` §3.7).
            continue
        consumed.add(key)
        if found in requested:
            # Read and acted on -- the id is already recorded once -- so the
            # second key stating it is not a gap.
            continue
        requested.append(found)
        # The name sits beside the id under the same `...tool_calls.M.` stem,
        # so it is located by construction rather than by scanning.
        stem = key[: -len(CALL_ID_SUFFIX)]
        name_key = stem + CALL_NAME_SUFFIX
        stated = _as_str(attributes.get(name_key))
        if stated is not None:
            consumed.add(name_key)
            names[found] = stated

    if not requested:
        return (), None, {}
    return tuple(requested), CallRole.REQUESTER, names


def _status(record: Mapping[str, JsonValue]) -> tuple[Status, str | None]:
    reported = record.get("status")
    note = _as_str(record.get("status_message"))
    if isinstance(reported, dict):
        note = note or _as_str(reported.get("message"))
        reported = reported.get("code")
    text = _as_str(reported)
    if text is None:
        return Status.UNSET, note
    return STATUSES.get(text.upper(), Status.UNSET), note


def _links(record: Mapping[str, JsonValue]) -> tuple[SpanLink, ...]:
    reported = record.get("links")
    if not isinstance(reported, list):
        return ()
    links = []
    for link in reported:
        if not isinstance(link, dict):
            continue
        span_id = _as_str(link.get("span_id"))
        if span_id is None:
            continue
        attributes = link.get("attributes")
        links.append(
            SpanLink(
                span_id=span_id,
                trace_id=_as_str(link.get("trace_id")),
                attributes=attributes if isinstance(attributes, dict) else {},
            )
        )
    return tuple(links)


def _received_results(
    attributes: Mapping[str, JsonValue], consumed: set[str]
) -> tuple[str, ...]:
    """Call ids whose results this span was **given** (`SPEC.md` §4.2).

    A tool-result message in this span's input is the instrumentor stating
    that the output of the span which fulfilled that call became an input
    here. It is a declaration, joined by an id: nothing compares an output
    string to an input string, so none of §4.2's objections -- threshold,
    normalization rule, encoding policy -- has anything to apply to.

    The role is what makes it safe. `role == "tool"` is a result the span
    received; the assistant message beside it carries the same id under a
    different attribute form and is only an echo of the *request*
    (`tool_call_history_echo`). Reading either as the other is a mistake in
    opposite directions.

    A role the adapter could READ is consumed along with the id it decided
    about, because it was read and acted on and `unmapped` names what the
    adapter did **not** map (`SPEC.md` §3.7). Reporting it said the adapter had
    failed to understand the key it decided with -- once per echoed message per
    turn, which is quadratic in a resent conversation: at 400 turns the
    September 2026 audit measured 13.19 MB of `unmapped_attributes`
    diagnostics, nearly all of them these two keys.

    A role it could not read decided nothing, and stays reported: the id below
    it is then left reported by the default rather than by a decision, and a
    `role` never becomes a field, so the report is the only trace that an
    unreadable one arrived.
    """
    received: list[str] = []
    for key in sorted(str(k) for k in attributes):
        if not (key.startswith(INPUT_MESSAGES) and key.endswith(RESULT_ID_SUFFIX)):
            continue
        role_key = key[: -len(RESULT_ID_SUFFIX)] + ROLE_SUFFIX
        role = _as_str(attributes.get(role_key))
        if role is None:
            # No role, or one that is not a string: nothing was decided here,
            # so nothing is consumed. An absent key is not reported; a present
            # but unreadable one is, like any key read and not usable.
            continue
        consumed.add(role_key)
        if role != TOOL_ROLE:
            # The id was not mapped, so it stays reported. The role that
            # decided so was.
            continue
        found = _as_str(attributes[key])
        if found is None:
            # Read and unusable, which is a real gap: leave it reported.
            continue
        consumed.add(key)
        if found not in received:
            received.append(found)
    return tuple(received)


def _as_str(value: JsonValue) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    return None


def _as_int(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


#: A JSON number literal, exactly as RFC 8259 writes one. The rule for a
#: quoted timestamp is *the string, unquoted, would be a valid JSON number*
#: (`SPEC.md` §3.1) rather than a list of tolerated spellings: OTLP JSON
#: encodes 64-bit integers as decimal strings, so a quoted timestamp is a
#: real exporter's output -- but every tolerated spelling beyond that is a
#: small normalization, and a library that trims whitespace here has started
#: deciding what the telemetry meant.
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")

#: The integer subset of the above: no fraction, no exponent. §3.1 reads an
#: integer literal as an `int` and every other literal as a `float`, and the
#: rule is about the *literal* rather than the value, so a quoted timestamp
#: is typed by the same test as an unquoted one.
_JSON_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")


def _finite(value: int | float) -> int | float | None:
    """`value`, unless it is `inf` or `nan` -- neither of which is a time.

    Python's JSON parser produces those for the non-standard `NaN` /
    `Infinity` tokens and for a literal no float64 can hold (`1e400`), and a
    library that carried one would write it back out as a bare `Infinity`
    that no strict JSON parser will read (`SPEC.md` §3.1, §7).

    The `isinstance` is the guard rather than a style choice: an `int` is
    always finite, and `math.isfinite` on one too large for a float raises
    `OverflowError` instead of answering.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _as_time(value: JsonValue) -> int | float | None:
    """Unix seconds, as reported. Never rescaled, never guessed at.

    An integer literal is kept as an `int` (`SPEC.md` §3.1). float64's
    spacing at epoch-nanosecond magnitude is 256 ns, so `float()` here would
    spend digits the exporter wrote and merge spans a record kept apart.
    Keeping them is not a unit conversion: nothing is scaled, and the adapter
    still does not know what unit the field is in.

    Returns `None` both for a field the record omits and for one in a
    rendering this adapter does not read; `_timestamps` is what tells the two
    apart, because only the second is something to report.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # `json.loads` already draws §3.1's line: an `int` for an integer
        # literal, a `float` for one with a fraction or an exponent.
        return _finite(value)
    if isinstance(value, str) and _JSON_NUMBER.fullmatch(value):
        # Read as the identical value the same literal would have produced
        # unquoted: `"1700000000"` and `1700000000` are one timestamp, and
        # `"1e9"` is the same float `1e9` is.
        try:
            parsed: int | float = (
                jsoncodec.parse_integer(value)
                if _JSON_INTEGER.fullmatch(value)
                else float(value)
            )
        except ValueError:
            # Longer than the library's digit limit (`SPEC.md` §5.3): a
            # constant, and the digits are counted before anything converts
            # them, so this answer does not depend on how the interpreter's
            # own limit is set. An unquoted literal that long never gets
            # here -- the reader refuses the line -- but a *quoted* one is an
            # ordinary JSON string until this call (`SPEC.md` §3.1).
            return None
        return _finite(parsed)
    return None


def _timestamps(
    record: Mapping[str, JsonValue],
) -> tuple[int | float | None, int | float | None, list[str]]:
    """`(started_at, ended_at, the time fields this adapter could not read)`.

    A value in a rendering §3.1 does not accept must never become a silent
    `None`: it stays verbatim in `raw`, and its field is named among the
    unmapped ones, which is `unmapped_attributes`' whole job. A field the
    record omits -- or reports as `null`, which is how both dialects say "no
    start time" -- is an absence and is not named: there is nothing the
    adapter failed to read.
    """
    times: list[int | float | None] = []
    refused: list[str] = []
    for field in ("start_time", "end_time"):
        reported = record.get(field)
        parsed = _as_time(reported)
        times.append(parsed)
        if parsed is None and reported is not None:
            refused.append(f"<record>.{field}")
    return times[0], times[1], refused
