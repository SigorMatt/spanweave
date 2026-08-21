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
from collections.abc import Iterable, Iterator, Mapping, Sequence

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
from spanweave.seam import CallRole, DeclaredDataEdge, NormalizedSpan, SpanLink

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
        try:
            for record in sample:
                if not isinstance(record, dict):
                    continue
                attributes = record.get("attributes")
                if not isinstance(attributes, dict):
                    continue
                if any(str(key).startswith(MARKER_PREFIX) for key in attributes):
                    # A distinctive marker, and 0.9 rather than 1.0: certainty
                    # is not ours to declare (ADAPTERS.md §2).
                    return 0.9
        except Exception:  # pragma: no cover - detect() must never raise
            return 0.0
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
            source_key=str(index),
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

    span_id = _as_str(record.get("span_id"))
    source_key = span_id if span_id is not None else str(index)

    kind, normalized = _kind_of(attributes, consumed, diagnostics, record)
    inputs = _payload(attributes, INPUT_VALUE, INPUT_MIME, consumed, diagnostics)
    outputs = _payload(attributes, OUTPUT_VALUE, OUTPUT_MIME, consumed, diagnostics)
    usage = _usage(attributes, consumed)
    operation, model = _operation(attributes, consumed)
    if model is not None:
        normalized["model"] = model
    call_id, call_role = _call(attributes, outputs, consumed, diagnostics)
    status, status_note = _status(record)

    unmapped = sorted(
        [str(key) for key in attributes if str(key) not in consumed]
        + [f"<record>.{key}" for key in record if key not in KNOWN_RECORD_KEYS]
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
        parent_id=_as_str(record.get("parent_id")),
        trace_id=_as_str(record.get("trace_id")),
        kind=kind,
        name=_as_str(record.get("name")) or "",
        operation=operation,
        started_at=_as_time(record.get("start_time")),
        ended_at=_as_time(record.get("end_time")),
        status=status,
        status_note=status_note,
        inputs=inputs,
        outputs=outputs,
        usage=usage,
        call_id=call_id,
        call_role=call_role,
        links=_links(record),
        data_edges=_data_edges(record),
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
    consumed.add(SPAN_KIND)
    if reported is None:
        diagnostics.append(
            Diagnostic(
                code=UNKNOWN_SPAN_KIND,
                message=(
                    f"no {SPAN_KIND} attribute, so the kind is unknown; the "
                    f"span is kept and the record is preserved verbatim"
                ),
                source=record,
                adapter=ADAPTER_ID,
            )
        )
        return NodeKind.UNKNOWN, normalized

    text = str(reported)
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
    consumed.add(value_key)
    consumed.add(mime_key)
    if value_key not in attributes:
        # The instrumentor emitted nothing. Not the same as emitting nothing
        # *in* something (SPEC.md §3.3).
        return Payload.absent()

    mime = _as_str(attributes.get(mime_key))
    reported = attributes[value_key]
    text = reported if isinstance(reported, str) else json.dumps(reported)

    if text == REDACTED_MARKER:
        return Payload(state=PayloadState.REDACTED, mime=mime, raw=text)

    if mime is not None and "json" in mime.lower():
        try:
            value = json.loads(text)
        except ValueError as failure:
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
    """The tool / model / retriever name, when the dialect names one."""
    consumed.update({TOOL_NAME, LLM_MODEL, EMBEDDING_MODEL})
    tool = _as_str(attributes.get(TOOL_NAME))
    model = _as_str(attributes.get(LLM_MODEL)) or _as_str(
        attributes.get(EMBEDDING_MODEL)
    )
    if tool is not None:
        return tool, model
    return model, model


def _call(
    attributes: Mapping[str, JsonValue],
    outputs: Payload,
    consumed: set[str],
    diagnostics: list[Diagnostic],
) -> tuple[str | None, CallRole | None]:
    """Recover the call id the dialect carries. Never guess one.

    A span that *answers* a call carries ``tool_call.id``. A span that
    *requests* one states the id in its output messages -- either in the
    dotted message attributes, or inside the output payload when the
    instrumentor puts the raw response there. Both are the dialect stating an
    id; neither is a comparison of values (`SPEC.md` §4.2).
    """
    consumed.add(TOOL_CALL_ID)
    fulfilling = _as_str(attributes.get(TOOL_CALL_ID))
    if fulfilling is not None:
        return fulfilling, CallRole.FULFILLER

    requested: list[str] = []
    for key in sorted(str(k) for k in attributes):
        if key.endswith(".tool_call.id") or key.endswith(".tool_call_id"):
            consumed.add(key)
            found = _as_str(attributes[key])
            if found is not None and found not in requested:
                requested.append(found)
    for found in _call_ids_in(outputs.value):
        if found not in requested:
            requested.append(found)

    if not requested:
        return None, None
    if len(requested) > 1:
        # The seam holds one call id per span (SPEC.md §6). A span requesting
        # several is a real shape the model does not yet express, so the extra
        # ids are reported rather than dropped -- this is exactly what
        # `unmapped_attributes` is for.
        diagnostics.append(
            Diagnostic(
                code=UNMAPPED_ATTRIBUTES,
                message=(
                    "this span requests more than one tool call "
                    f"({', '.join(requested)}); the model carries one call id "
                    "per span, so only the first is paired and the rest are "
                    "reported here"
                ),
                source=list(requested[1:]),
                adapter=ADAPTER_ID,
            )
        )
    return requested[0], CallRole.REQUESTER


def _call_ids_in(value: JsonValue) -> list[str]:
    """Tool-call ids stated inside a parsed output payload."""
    if not isinstance(value, dict):
        return []
    calls = value.get("tool_calls")
    if not isinstance(calls, list):
        return []
    found = []
    for call in calls:
        if isinstance(call, dict):
            identifier = _as_str(call.get("id"))
            if identifier is not None:
                found.append(identifier)
    return found


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
                basis="span.link",
                attributes=attributes if isinstance(attributes, dict) else {},
            )
        )
    return tuple(links)


def _data_edges(record: Mapping[str, JsonValue]) -> tuple[DeclaredDataEdge, ...]:
    """OpenInference declares no producer -> consumer relation.

    So there is nothing to transcribe, and nothing is transcribed. Comparing
    an output to an input and concluding a flow is forbidden (`SPEC.md` §4.2),
    and it is what this empty tuple is refusing to do.
    """
    return ()


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


def _as_time(value: JsonValue) -> float | None:
    """Unix seconds, as reported. Never rescaled, never guessed at."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
