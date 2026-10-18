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
say it is the JSON (`SPEC.md` §7 lists each place): span ids are lowercase hex
rather than base64, and enums (`kind`, `status.code`) are their numbers rather
than their names. Everything else already agrees: 64-bit integers as decimal
strings, defaults omitted. A link's ids are hex by the same rule, which is the
OTLP/JSON specification's and not a pair's -- no pair carries a link (`SPEC.md`
§7 lists what the pairs do not cover, and what holds each instead). An id of
the length the schema gives it -- 16 bytes for a trace id, 8 for a span id --
whose bytes are all zero, a span's or a link's, is omitted as an empty one is,
because the Collector treats it as empty -- its rule, and not a pair's either.
An id of any other length is hex as stated, all zero or not: the Collector
holds no such id, and the JSON path carries a hex string of any length.

**Where the pairs are silent, the container's rules decide** (`OPEN_QUESTIONS.md`
§23). A body that will not parse is one ``malformed_record`` with no
``source`` -- JSON cannot write the bytes, which is ``undecodable_bytes``'s
precedent -- and it never raises. A message carrying fields the installed
schema does not define is read without them and reported, one
``unknown_fields`` per message: ``MessageToDict`` drops them without a word,
and carried through that would be a silent discard (`CLAUDE.md` 2). The
runtime puts a field the schema *does* define there too when it arrives with
another wire type, so each is reported as the one or the other: a malformed
body is not blamed on the schema's age. A
finite ``doubleValue`` is ``MessageToDict``'s float, and a non-finite one the
string proto3 JSON spells it (``"NaN"``), as on the JSON path; no pair checks
either.

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

#: The length in bytes the schema gives each of those ids, a span's or a
#: link's alike: a trace id is 16 bytes, a span id 8 (`trace.proto`). Only an
#: id of its own length can be the Collector's empty one (`_hex`).
_ID_LENGTH = {"traceId": 16, "spanId": 8, "parentSpanId": 8}

#: The wire type each field type is written with, by the protobuf encoding's
#: rules, keyed by ``FieldDescriptor.type`` -- the numbers of
#: ``FieldDescriptorProto.Type``, which are part of the descriptor format and do
#: not move. What ``unknown_fields`` says the installed schema expects of a
#: number it defines (`SPEC.md` §3.7).
_WIRE_TYPE_OF_FIELD_TYPE = {
    1: 1,  # double: 64-bit
    2: 5,  # float: 32-bit
    3: 0,  # int64: varint
    4: 0,  # uint64
    5: 0,  # int32
    6: 1,  # fixed64: 64-bit
    7: 5,  # fixed32: 32-bit
    8: 0,  # bool: varint
    9: 2,  # string: length-delimited
    10: 3,  # group: start-group
    11: 2,  # message: length-delimited
    12: 2,  # bytes: length-delimited
    13: 0,  # uint32: varint
    14: 0,  # enum: varint
    15: 5,  # sfixed32: 32-bit
    16: 1,  # sfixed64: 64-bit
    17: 0,  # sint32: varint
    18: 0,  # sint64: varint
}


def read_protobuf(data: bytes | bytearray | memoryview) -> Records:
    """Read the records of one OTLP protobuf export, and build nothing.

    ``data`` is the bytes of one ``ExportTraceServiceRequest`` -- an OTLP/HTTP
    body sent as ``application/x-protobuf`` -- in any buffer `read_records`
    takes, copied once here for the same reason. What comes back is the
    `Records` `read_records` returns for the same export written as OTLP/JSON:
    the same records, marked as unpacked, the same diagnostics, the same
    ``skipped_records`` (`SPEC.md` §7) -- plus one ``unknown_fields`` for each
    message that carried fields the installed schema does not define, or
    defines with another wire type than the one they arrived with.

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
            _unknown_fields_message(path, fields),
            source={"path": path, "fields": fields},
        )

    document = _rendered(request)
    # `ensure_ascii`: the text is an intermediate, read straight back by the
    # JSON reader, and an escape reads back as the character it stands for.
    # `MessageToDict` writes a non-finite double as the string the OTLP/JSON
    # mapping gives it ("NaN"), so `allow_nan=False` refuses nothing it makes.
    # `sort_keys`, as the graph and the record digest are written: the order
    # the runtime happens to write a message's fields in is then not the order
    # a record's keys are read in. Nothing downstream reads that order -- key
    # order never reaches a node (`SPEC.md` §7) -- so the graph is the same
    # bytes either way.
    text = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False)
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
    stays absent, as it does in the Collector's JSON. **An id of its own
    length whose bytes are all zero is omitted too**: the Collector holds a
    trace id as a 16-byte array and a span id as an 8-byte one, and treats
    the all-zero one as empty, so its JSON leaves it out, and a root span
    whose exporter wrote eight zero bytes for its parent is a root there
    (`SPEC.md` §7 -- the Collector's rule, not a pair). It takes both: an id
    with any byte not zero is hex, as every other, wherever that byte is;
    and an id of any other length is hex as stated, all zero or not, as the
    JSON path carries a hex string of any length. The Collector would refuse
    a request carrying one rather than write JSON for it (not verified --
    spec, not pair), so it has no rule here to follow, and the reader refuses
    no body for one id.
    """
    for key in keys:
        if key in entry:
            raw = _base64_bytes(entry[key])
            if len(raw) == _ID_LENGTH[key] and not any(raw):
                del entry[key]
            else:
                entry[key] = raw.hex()


def _base64_bytes(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as failure:  # pragma: no cover -- the runtime wrote it
        raise AssertionError(f"MessageToDict wrote {value!r} as bytes") from failure


def _unknown_fields_message(path: str, fields: list[JsonValue]) -> str:
    """What one ``unknown_fields`` says: how many of each kind, the defined first.

    A message carrying both kinds is one diagnostic still, and its message
    counts each; one carrying a single kind counts only that one. What
    follows the counts is the same whatever the message carries: its closing
    sentences, on the wire type the schema expects and on why no field's
    bytes are carried, speak of both kinds.
    """
    defined = sum(1 for field in fields if isinstance(field, dict) and field["defined"])
    kinds = []
    if defined:
        kinds.append(
            f"{defined} not readable as the installed schema defines it (a "
            f"number it defines on this message, with a wire type other than "
            f"the one it expects -- a malformed body)"
        )
    if len(fields) - defined:
        kinds.append(
            f"{len(fields) - defined} not defined by the installed schema (a "
            f"newer OTLP, or an extension)"
        )
    return (
        f"the message at {path or 'the root of the request'} carries "
        f"{len(fields)} field(s) not read into it by the OTLP schema this "
        f"reader was installed with: {', and '.join(kinds)}; it was read without "
        f"them. Their numbers and wire types are here, with the wire type the "
        f"schema expects where it defines the number, and their bytes are not "
        f"-- a field it does not define has no name and no type to write it "
        f"by, and one it does was not written in its type (`SPEC.md` §3.7)"
    )


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
    occurrence, with whether this message's schema defines the number and, if
    it does, the wire type it expects (``null`` if not): the runtime keeps a
    defined field that arrived with another wire type here too. Visited in
    field-number order, so the walk is the schema's order and not the input's.
    """
    from google.protobuf import unknown_fields
    from google.protobuf.message import Message

    defined = message.DESCRIPTOR.fields_by_number
    found: list[tuple[str, list[JsonValue]]] = []
    unknown = [
        {
            "number": field.field_number,
            "wire_type": field.wire_type,
            "defined": field.field_number in defined,
            "expected_wire_type": (
                _WIRE_TYPE_OF_FIELD_TYPE[defined[field.field_number].type]
                if field.field_number in defined
                else None
            ),
        }
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
