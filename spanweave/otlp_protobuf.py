"""The OTLP protobuf wire format, read into the records its JSON reads as.

The fourth way of packing the same container (`SPEC.md` §7): an
``ExportTraceServiceRequest`` sent as ``application/x-protobuf``, which is how
the stock OTLP/HTTP exporter sends every export (the zoo's L1). It is the
**reader's**, not a dialect's and not a receiver's: the envelope is a container
the reader owns, and a second encoding of the same container is the same
ownership (`TASKS.md`, decisions log D28; `OPEN_QUESTIONS.md` §16).

**It is held to its JSON twin, and ends in it.** The body is parsed by the
protobuf runtime, rendered as the OTLP/JSON the Collector writes for the same
export, and handed to `read_records` -- the one reader every graph this
library has built went through -- so nothing about unpacking an export is
written twice. Where the Collector's rendering differs from the runtime's
``MessageToDict`` default, the Collector's is used, because the zoo's 29 pairs
say it is the JSON (`SPEC.md` §7 lists each place): span and link ids are
lowercase hex rather than base64, and enums (`kind`, `status.code`) are their
numbers rather than their names. Everything else already agrees: 64-bit
integers as decimal strings, defaults omitted.

**Where the pairs are silent, the container's rules decide** (`OPEN_QUESTIONS.md`
§23). A body that will not parse is one ``malformed_record`` with no
``source`` -- JSON cannot write the bytes, which is ``undecodable_bytes``'s
precedent -- and it never raises. A message carrying fields the installed
schema does not define is read without them and reported, one
``unknown_fields`` per message: ``MessageToDict`` drops them without a word,
and carried through that would be a silent discard (`CLAUDE.md` 2). A
``doubleValue`` is ``MessageToDict``'s float, which no pair checks.

**The extra is optional because nothing imports it until it is used.** This is
the one module allowed the ``otlp`` extra's packages, and only inside the
function (`tests/gates.py`, ``OPTIONAL_EXTRA_MODULE``): ``import spanweave``
needs neither, and without them ``read_protobuf`` raises a ``SpanweaveError``
whose code names the extra.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from spanweave import diagnostics as codes
from spanweave.diagnostics import DiagnosticCollector
from spanweave.errors import OTLP_EXTRA_NOT_INSTALLED, SpanweaveError
from spanweave.model import JsonValue
from spanweave.read import Records, _as_bytes, read_records

#: The id fields the Collector writes as lowercase hex where the protobuf
#: runtime writes base64 (`SPEC.md` §7) -- a span's, and a link's.
_SPAN_IDS = ("traceId", "spanId", "parentSpanId")
_LINK_IDS = ("traceId", "spanId")


def read_protobuf(data: bytes | bytearray | memoryview) -> Records:
    """Read the records of one OTLP protobuf export, and build nothing.

    ``data`` is the bytes of one ``ExportTraceServiceRequest`` -- an OTLP/HTTP
    body sent as ``application/x-protobuf`` -- in any buffer `read_records`
    takes, copied once here for the same reason. What comes back is the
    `Records` `read_records` returns for the same export written as OTLP/JSON:
    the same records, marked as unpacked, the same diagnostics, the same
    ``skipped_records`` (`SPEC.md` §7) -- plus one ``unknown_fields`` for each
    message that carried fields the installed schema does not define.

    It raises nothing an unreadable body can cause: a body that is not a
    protobuf ``ExportTraceServiceRequest`` is one ``malformed_record``. It
    raises `SpanweaveError` (``otlp_extra_not_installed``) when the ``otlp``
    extra is not installed, and ``TypeError`` for what `read_records` refuses.
    """
    body = _as_bytes(data, "read_protobuf")
    try:
        # Every name the reading needs, so a runtime too old for one of them
        # is the same refusal as no runtime at all, and not a traceback later.
        from google.protobuf import json_format, unknown_fields  # noqa: F401
        from google.protobuf.message import DecodeError
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
    except ImportError as missing:
        raise SpanweaveError(
            f"reading the OTLP protobuf wire format needs the `otlp` extra, "
            f"which is not installed ({missing}): pip install spanweave[otlp]. "
            f"OTLP/JSON needs nothing -- spanweave.read_records reads it",
            code=OTLP_EXTRA_NOT_INSTALLED,
        ) from missing

    collector = DiagnosticCollector()
    try:
        request = trace_service_pb2.ExportTraceServiceRequest.FromString(body)
    except DecodeError as failure:
        collector.add(
            codes.MALFORMED_RECORD,
            f"the body could not be read as an OTLP protobuf "
            f"ExportTraceServiceRequest ({failure}); no records were read, and "
            f"its bytes are not carried here because JSON has no way to write "
            f"them (`SPEC.md` §3.7)",
        )
        return Records(records=(), diagnostics=collector.collected(), skipped_records=1)

    for path, fields in _unknown_fields(request, ""):
        collector.add(
            codes.UNKNOWN_FIELDS,
            f"the message at {path or 'the root of the request'} carries "
            f"{len(fields)} field(s) the OTLP schema this reader was installed "
            f"with does not define; it was read without them. Their numbers "
            f"and wire types are here and their bytes are not -- they have no "
            f"name and no type to write them by (`SPEC.md` §3.7)",
            source={"path": path, "fields": fields},
        )

    document = _rendered(request)
    # `ensure_ascii`: the text is an intermediate, read straight back by the
    # JSON reader, and an escape reads back as the character it stands for.
    # `MessageToDict` writes a non-finite double as the string the OTLP/JSON
    # mapping gives it ("NaN"), so `allow_nan=False` refuses nothing it makes.
    text = json.dumps(document, ensure_ascii=True, allow_nan=False)
    read = read_records(text.encode("ascii"))
    collector.extend(read.diagnostics)
    return Records(
        records=read.records,
        diagnostics=collector.collected(),
        skipped_records=read.skipped_records,
    )


def _rendered(request: Any) -> dict[str, Any]:  # noqa: ANN401 -- see `_unknown_fields`
    """The request as the OTLP/JSON the Collector writes for it (`SPEC.md` §7).

    ``MessageToDict`` with the two places the zoo's pairs show the Collector
    differs from its defaults: enums as their numbers, and ids as hex. On
    every pair this is the Collector's JSON document, parsed, exactly
    (`tests/test_protobuf.py`).
    """
    from google.protobuf import json_format

    document: dict[str, Any] = json_format.MessageToDict(
        request, use_integers_for_enums=True
    )
    # An empty request writes `{}`: the one field, at its default, is omitted.
    # Its JSON twin states the empty list, and reads as no records.
    resource_spans = document.setdefault("resourceSpans", [])
    for resource_entry in resource_spans:
        for scope_entry in resource_entry.get("scopeSpans", []):
            for span in scope_entry.get("spans", []):
                _hex(span, _SPAN_IDS)
                for link in span.get("links", []):
                    _hex(link, _LINK_IDS)
    return document


def _hex(entry: dict[str, Any], keys: tuple[str, ...]) -> None:
    """Each id ``MessageToDict`` wrote in base64, as the hex the Collector writes.

    Proto3 omits an empty ``bytes`` field, so an id the span does not state
    stays absent, as it does in the Collector's JSON.
    """
    for key in keys:
        if key in entry:
            entry[key] = _base64_to_hex(entry[key])


def _base64_to_hex(value: str) -> str:
    try:
        return base64.b64decode(value, validate=True).hex()
    except binascii.Error as failure:  # pragma: no cover -- the runtime wrote it
        raise AssertionError(f"MessageToDict wrote {value!r} as bytes") from failure


def _unknown_fields(
    # A protobuf message. `Any` because its type lives in the extra, which this
    # module may not import at module level -- not even for a type checker.
    message: Any,  # noqa: ANN401
    path: str,
) -> list[tuple[str, list[JsonValue]]]:
    """``(path, fields)`` for every message, this one first, carrying unknown fields.

    ``path`` is the message's place in the request in the OTLP/JSON field
    names (``resourceSpans[0].scopeSpans[0].spans[3]``; ``""`` is the request
    itself). ``fields`` is each unknown field's number and wire type, in the
    order the runtime reports them -- the order they arrived -- one entry per
    occurrence. Visited in field-number order, so the walk is the schema's
    order and not the input's.
    """
    from google.protobuf import unknown_fields
    from google.protobuf.message import Message

    found: list[tuple[str, list[JsonValue]]] = []
    unknown = [
        {"number": field.field_number, "wire_type": field.wire_type}
        for field in unknown_fields.UnknownFieldSet(message)
    ]
    if unknown:
        found.append((path, list[JsonValue](unknown)))
    for descriptor, value in message.ListFields():
        if descriptor.type != descriptor.TYPE_MESSAGE:
            continue
        name = f"{path}.{descriptor.json_name}" if path else descriptor.json_name
        if isinstance(value, Message):
            found.extend(_unknown_fields(value, name))
        else:
            for index, item in enumerate(value):
                found.extend(_unknown_fields(item, f"{name}[{index}]"))
    return found
