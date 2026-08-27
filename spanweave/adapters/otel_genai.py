"""The OTel GenAI dialect.

OpenTelemetry's ``gen_ai.*`` semantic conventions, as emitted by
``opentelemetry-instrumentation-genai-openai`` (see
``fixtures/captured/genai_tool_call.provenance.md`` for the exact version this
was written against). Like every adapter, this file is the only place in the
library that knows any of it (``DESIGN.md`` §3).

Where it differs from OpenInference, and why the differences are the
interesting part:

* **The conversation, not the request.** OpenInference records an LLM span's
  whole request envelope in ``input.value`` and the whole provider response in
  ``output.value``. This dialect records a normalized message list in
  ``gen_ai.input.messages`` / ``gen_ai.output.messages``. Neither is a
  re-encoding of the other, so the corpus declares those payloads
  dialect-varying rather than pretending they agree (``FIXTURES.md`` §4.4).

* **Requested versus received is a part `type`, not an attribute prefix.**
  OpenInference separates what the model said from what it was shown by which
  message list an attribute sits under. Here both lists have the same shape and
  the discriminator is inside: a ``tool_call`` part is a request, a
  ``tool_call_response`` part is a result the span was given. The rule
  (``SPEC.md`` §4.4) is unchanged -- a requester id comes only from what the
  span itself **produced**, so only ``gen_ai.output.messages`` is read for one.
  A follow-up turn carries the previous turn's ``tool_call`` part in its
  *input* list, and reading that as a request is the defect
  ``tool_call_history_echo`` exists to catch.

* **The dialect declares §4.2.1.** A ``tool_call_response`` part names the call
  whose result this span was given. That is a producer -> consumer relation
  stated by the instrumentor, at message granularity, joined by an id --
  exactly what ``received_call_ids`` is for. Nothing here compares an output
  string to an input string.

**A mime the dialect defines but does not emit** (``ADAPTERS.md`` §3, which is
where the rule lives -- this is its worked example, not its only statement).
This dialect carries no content-type attribute anywhere. But the convention
*defines* ``gen_ai.input.messages``, ``gen_ai.output.messages``,
``gen_ai.tool.call.arguments`` and ``gen_ai.tool.call.result`` as structured
values, which the OTLP exporter serializes to JSON strings because span
attributes cannot hold nested data. So this adapter reports
``application/json`` for those four keys and parses them, and a parse failure
stays honest -- ``present``, ``value=None``, ``raw`` kept, and a
``payload_parse_failed`` diagnostic.

The third condition of that rule is that a reader of the **fixture** can find
this out without reading the adapter, so it is also stated in the affected
scenarios' cross-dialect notes and in the ``reason`` of every
``expected/comparison.json`` that declares a payload dialect-varying.
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
from spanweave.seam import CallRole, NormalizedSpan, SpanLink

ADAPTER_ID = "otel_genai"
ADAPTER_VERSION = "0.1.0"

# The marker prefix. Distinctive: no other dialect this library reads namespaces
# its keys this way, and OpenInference traces carry none of them.
MARKER_PREFIX = "gen_ai."
OPERATION = "gen_ai.operation.name"

#: `gen_ai.operation.name` is a normative enum in the convention, so this is
#: the convention's own vocabulary rather than a reading of instrumentor
#: behaviour. Three of these are confirmed by the captured trace --
#: `invoke_agent`, `chat`, `execute_tool`; the rest are the convention's and
#: are claims awaiting a capture. An operation not here becomes `unknown` plus
#: a diagnostic, never a near-miss forced into a neighbouring kind.
#:
#: The convention defines **nine** values (`opentelemetry-semantic-conventions`
#: 0.65b0, the version the captured trace was produced under). Eight are here.
#: The ninth, `invoke_workflow`, is **deliberately absent** -- see below.
OPERATIONS: Mapping[str, NodeKind] = {
    "chat": NodeKind.LLM,
    "text_completion": NodeKind.LLM,
    "generate_content": NodeKind.LLM,
    "embeddings": NodeKind.EMBEDDING,
    "retrieval": NodeKind.RETRIEVER,
    "execute_tool": NodeKind.TOOL,
    "invoke_agent": NodeKind.AGENT,
    "create_agent": NodeKind.AGENT,
}

#: `invoke_workflow` is the one convention value this adapter does not map, and
#: the omission is a decision rather than an oversight (`TASKS.md` 2.11).
#:
#: Every other entry above is a **name match**: the convention's word and the
#: model's word denote the same thing, and the convention's own description
#: confirms it -- `retrieval` is "Retrieval operation such as ... Search Vector
#: Store", which is `NodeKind.retriever` and nothing else. `invoke_workflow` is
#: described only as "Invoke GenAI workflow". Mapping it to `chain` --
#: `SPEC.md` §3.2's "a composite step with no more specific kind" -- would be a
#: **judgement** about what a workflow is, not a match, and this library's rule
#: is that reaching for an inference is the signal to stop (`AGENT.md`).
#:
#: It is not free. Three conformance scenarios pin `kind: chain` and are
#: therefore declared unrenderable in this dialect -- `cyclic_parents`,
#: `retriever_and_embedding` and `span_links` -- and `span_links` is the only
#: scenario carrying `EdgeKind.link`. One captured GenAI trace containing an
#: `invoke_workflow` span retires all three declarations at once, which makes
#: it the highest-value capture outstanding (`TASKS.md` 2.14).
UNMAPPED_BY_DECISION = ("invoke_workflow",)

INPUT_MESSAGES = "gen_ai.input.messages"
OUTPUT_MESSAGES = "gen_ai.output.messages"
TOOL_ARGUMENTS = "gen_ai.tool.call.arguments"
TOOL_RESULT = "gen_ai.tool.call.result"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
REQUEST_MODEL = "gen_ai.request.model"
USAGE_PREFIX = "gen_ai.usage."

#: The content type the convention fixes for the four structured attributes.
#: See the module docstring: this is a statement about the dialect, not about
#: a span.
STRUCTURED_MIME = "application/json"

#: Inside a message list. `type` is what separates a call the model *made*
#: from a result it was *given* -- see the module docstring.
PART_TYPE = "type"
TOOL_CALL_PART = "tool_call"
TOOL_RESPONSE_PART = "tool_call_response"
PART_ID = "id"
PART_NAME = "name"
PARTS = "parts"

# The token counts the model has fields for; anything else counted goes to
# `Usage.extra` rather than being dropped or renamed. The convention reports no
# total, so `total_tokens` stays absent -- adding the two would state a fact the
# telemetry did not.
TOKEN_FIELDS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
}

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


class OtelGenAiAdapter:
    """Translates OTel GenAI spans into ``NormalizedSpan``."""

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
                    # 0.9, not 1.0: certainty is not ours to declare
                    # (ADAPTERS.md §2).
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
        return NormalizedSpan(
            source_key=str(index),
            kind=NodeKind.UNKNOWN,
            name="",
            raw=raw,
            diagnostics=(
                Diagnostic(
                    code=UNKNOWN_SPAN_KIND,
                    message=(
                        "record is not a JSON object, so it carries no "
                        "gen_ai.operation.name; kept as an unknown node"
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
    inputs, outputs = _payloads(kind, attributes, consumed, diagnostics)
    usage = _usage(attributes, consumed)
    operation, model = _operation(kind, attributes, consumed)
    if model is not None:
        normalized["model"] = model
    call_ids, call_role, call_names = _call(attributes, outputs, consumed, operation)
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
                # Keys only: the values are already in `raw`, and copying
                # payload content into a diagnostic is an exposure surface with
                # no benefit (SPEC.md §3.7).
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
        call_ids=call_ids,
        call_role=call_role,
        call_names=call_names,
        links=_links(record),
        data_edges=_data_edges(record),
        received_call_ids=_received_results(inputs),
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
    reported = attributes.get(OPERATION)
    consumed.add(OPERATION)
    if reported is None:
        diagnostics.append(
            Diagnostic(
                code=UNKNOWN_SPAN_KIND,
                message=(
                    f"no {OPERATION} attribute, so the kind is unknown; the "
                    f"span is kept and the record is preserved verbatim"
                ),
                source=record,
                adapter=ADAPTER_ID,
            )
        )
        return NodeKind.UNKNOWN, normalized

    text = str(reported)
    mapped = OPERATIONS.get(text)
    if mapped is not None:
        return mapped, normalized

    normalized["reported_kind"] = text
    diagnostics.append(
        Diagnostic(
            code=UNKNOWN_SPAN_KIND,
            message=(
                f"{OPERATION}={text!r} does not map to a NodeKind; kept as "
                f"unknown, with the reported operation preserved in attributes"
            ),
            source=text,
            adapter=ADAPTER_ID,
        )
    )
    return NodeKind.UNKNOWN, normalized


def _payloads(
    kind: NodeKind,
    attributes: Mapping[str, JsonValue],
    consumed: set[str],
    diagnostics: list[Diagnostic],
) -> tuple[Payload, Payload]:
    """The two attribute pairs this dialect uses, chosen by span kind.

    A tool span states its call's arguments and result; everything else states
    a message list. Only the pair actually read is marked consumed, so a span
    carrying both would report the other pair in `unmapped` rather than have it
    silently preferred away.
    """
    if kind is NodeKind.TOOL:
        keys = (TOOL_ARGUMENTS, TOOL_RESULT)
    else:
        keys = (INPUT_MESSAGES, OUTPUT_MESSAGES)
    return tuple(  # type: ignore[return-value]
        _payload(attributes, key, consumed, diagnostics) for key in keys
    )


def _payload(
    attributes: Mapping[str, JsonValue],
    key: str,
    consumed: set[str],
    diagnostics: list[Diagnostic],
) -> Payload:
    consumed.add(key)
    if key not in attributes:
        # The instrumentor emitted nothing. Not the same as emitting nothing
        # *in* something (SPEC.md §3.3).
        return Payload.absent()

    reported = attributes[key]
    if not isinstance(reported, str):
        # Already structured -- an exporter that can carry nested attributes.
        text = json.dumps(reported)
        return Payload(
            state=_state_of(reported),
            mime=STRUCTURED_MIME,
            value=reported,
            raw=text,
        )

    try:
        value = json.loads(reported)
    except ValueError as failure:
        diagnostics.append(
            Diagnostic(
                code=PAYLOAD_PARSE_FAILED,
                message=(
                    f"{key} is defined by the convention as a structured value "
                    f"but did not parse ({failure}); the text is kept verbatim"
                ),
                adapter=ADAPTER_ID,
            )
        )
        # State stays `present`: something was reported, we just could not read
        # it. `raw` is where it survives.
        return Payload(
            state=PayloadState.PRESENT, mime=STRUCTURED_MIME, value=None, raw=reported
        )
    return Payload(
        state=_state_of(value), mime=STRUCTURED_MIME, value=value, raw=reported
    )


def _state_of(value: JsonValue) -> PayloadState:
    if value in ("", {}, [], None):
        return PayloadState.EMPTY
    return PayloadState.PRESENT


def _usage(attributes: Mapping[str, JsonValue], consumed: set[str]) -> Usage | None:
    counts: dict[str, int] = {}
    extra: dict[str, int] = {}
    for key, value in attributes.items():
        name = str(key)
        if not name.startswith(USAGE_PREFIX):
            continue
        consumed.add(name)
        number = _as_int(value)
        if number is None:
            consumed.discard(name)  # not a count; report it as unmapped
            continue
        suffix = name[len(USAGE_PREFIX) :]
        field = TOKEN_FIELDS.get(suffix)
        if field is not None:
            counts[field] = number
        else:
            extra[suffix] = number
    if not counts and not extra:
        return None
    return Usage(**counts, extra=extra)


def _operation(
    kind: NodeKind, attributes: Mapping[str, JsonValue], consumed: set[str]
) -> tuple[str | None, str | None]:
    """The tool or model name, when the dialect names one.

    ``gen_ai.agent.name`` is deliberately **not** read here. `operation` is the
    tool / model / retriever name (`SPEC.md` §3.2); an agent's name is not one
    of those, and mapping it would put a value in a field OpenInference leaves
    empty on the same span. It surfaces in `unmapped` and is reported.
    """
    consumed.update({TOOL_NAME, REQUEST_MODEL})
    tool = _as_str(attributes.get(TOOL_NAME))
    model = _as_str(attributes.get(REQUEST_MODEL))
    if kind is NodeKind.TOOL and tool is not None:
        return tool, model
    return model, model


def _call(
    attributes: Mapping[str, JsonValue],
    outputs: Payload,
    consumed: set[str],
    operation: str | None,
) -> tuple[tuple[str, ...], CallRole | None, dict[str, str]]:
    """Recover the call ids the dialect carries. Never guess one.

    A span that *answers* a call carries ``gen_ai.tool.call.id``. A span that
    *requests* one -- or several -- states the ids as ``tool_call`` parts in
    **its own output messages**, which is what ``outputs`` holds by the time
    this runs.

    Reading only the output list is load-bearing, not tidiness. The same
    ``tool_call`` part reappears in the *next* turn's ``gen_ai.input.messages``,
    because the protocol requires the whole conversation to be resent; a rule
    that matched a part anywhere would make a span that requested nothing look
    like a requester, and the builder would state a `call_result` relation the
    telemetry never asserted (`SPEC.md` §4.4). Those echoed ids stay inside the
    input payload, where a consumer can still see them.
    """
    consumed.add(TOOL_CALL_ID)
    fulfilling = _as_str(attributes.get(TOOL_CALL_ID))
    if fulfilling is not None:
        # A fulfiller's own `operation` already names the tool; carrying it
        # here too is what lets both unpaired codes share one `source` shape.
        named = {fulfilling: operation} if operation is not None else {}
        return (fulfilling,), CallRole.FULFILLER, named

    requested = _requested(outputs)
    if not requested:
        return (), None, {}
    return requested, CallRole.REQUESTER, _requested_names(outputs)


def _requested(outputs: Payload) -> tuple[str, ...]:
    """Ids of calls this span's own output messages asked for."""
    return _ids_of_type(outputs.value, TOOL_CALL_PART)


def _requested_names(outputs: Payload) -> dict[str, str]:
    """The `name` beside each requested `tool_call` part's `id`.

    Same part, same walk as `_requested` -- the convention puts the two in one
    object, so the name is located by construction rather than searched for.
    Read only so a call nothing fulfils can still be attributed to the tool it
    named (`SPEC.md` §3.7); a call that IS fulfilled has a node that says it.
    """
    return _names_of_type(outputs.value, TOOL_CALL_PART)


def _received_results(inputs: Payload) -> tuple[str, ...]:
    """Call ids whose results this span was **given** (`SPEC.md` §4.2.1).

    A ``tool_call_response`` part is the instrumentor stating that the output
    of the span which fulfilled that call became an input here. It is a
    declaration, joined by an id: nothing compares an output string to an input
    string, so none of §4.2's objections has anything to apply to.
    """
    return _ids_of_type(inputs.value, TOOL_RESPONSE_PART)


def _names_of_type(messages: JsonValue, part_type: str) -> dict[str, str]:
    """Part `id` -> part `name`, for one part `type`, first mention winning.

    As tolerant as `_ids_of_type` and for the same reason: a message list the
    convention would not recognize yields nothing rather than raising.
    """
    found: dict[str, str] = {}
    for part in _parts_of_type(messages, part_type):
        identifier = _as_str(part.get(PART_ID))
        named = _as_str(part.get(PART_NAME))
        if identifier is not None and named is not None:
            found.setdefault(identifier, named)
    return found


def _ids_of_type(messages: JsonValue, part_type: str) -> tuple[str, ...]:
    """Every part `id` of one `type`, in message order, deduplicated.

    Tolerant by construction: a message list that is not shaped the way the
    convention describes yields nothing rather than raising. The payload is
    still `present` and still in `raw`, so the content is not lost -- only the
    relation this adapter declines to claim.
    """
    found: list[str] = []
    for part in _parts_of_type(messages, part_type):
        identifier = _as_str(part.get(PART_ID))
        if identifier is not None and identifier not in found:
            found.append(identifier)
    return tuple(found)


def _parts_of_type(
    messages: JsonValue, part_type: str
) -> Iterator[Mapping[str, JsonValue]]:
    """Every part of one `type`, in message order. One walk, two readers.

    Shared so that the id and the name can never come from different parts:
    they are two fields of one object, and reading them apart is how a call
    would end up labelled with another call's tool.
    """
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        parts = message.get(PARTS)
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and part.get(PART_TYPE) == part_type:
                yield part


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


def _data_edges(record: Mapping[str, JsonValue]) -> tuple[()]:
    """This dialect never names **both** ends of a relation on one span.

    What it does declare -- that this span was given the result of call X --
    is carried in `received_call_ids` instead, because only the builder can
    resolve X to the span that produced it.
    """
    del record
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
