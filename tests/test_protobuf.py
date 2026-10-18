"""The OTLP protobuf wire format, held to its JSON twin (batch W1, `PROBES.md` L1).

`spanweave.read_protobuf` takes the bytes of an `ExportTraceServiceRequest` and
hands back the records `spanweave.read_records` hands back for the same export
written as OTLP/JSON (`SPEC.md` §7). **The oracle is the zoo's pairs**: every
JSON body under `fixtures/zoo/` is the Collector's re-encoding of one raw body
the exporter sent (`tests/zoo_census.py` `pairs`), and on every pair the two
readings are held equal record by record, mark included, and as the bytes of
the graph each builds.

Where the pairs are silent the container's own rules decide (`OPEN_QUESTIONS.md`
§23): a body that will not parse is one `malformed_record` with `source`
`null`; a message carrying fields the schema does not define, or defines with
another wire type, is read, and reported as `unknown_fields`, which says of each
field which it is; a finite `doubleValue` is a float and a non-finite one the
string proto3 JSON spells it, which no pair checks.

The tests that need the proto runtime skip without the `otlp` extra, saying
so; CI's `check` matrix and `otlp` job (the latter at the extra's floors) install
it and set `SPANWEAVE_REQUIRE_OTLP`, under which a missing runtime is a failure
rather than a skip.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

import spanweave
from spanweave.api import graph_from_records
from spanweave.diagnostics import DiagnosticCollector
from tests import zoo_census
from tests.schema_shape import diagnostic_source_shapes
from tests.zoo_census import CAPTURES, ROOT

PAIRS = [
    (capture.run, json_body, raw_body)
    for capture in CAPTURES
    for json_body, raw_body in zoo_census.pairs(capture)
]
PAIR_IDS = [f"{run}/{json_body.stem}" for run, json_body, _ in PAIRS]

#: What CI's `check` and `otlp` jobs set: there, a proto runtime that will not
#: import is a broken job, not a reason to skip.
REQUIRE = "SPANWEAVE_REQUIRE_OTLP"


#: The skip's reason, where the runtime is missing and nothing requires it.
NO_EXTRA = "the `otlp` extra is not installed: pip install spanweave[otlp]"


def _pb2() -> ModuleType:
    """The `ExportTraceServiceRequest` module, or a skip naming the extra.

    The module is imported by name, not by a computed one: `tests/gates.py`
    bans the latter under `spanweave/` and under `tests/` alike. What is caught
    is what `pytest.importorskip` catches from pytest 9.1 on,
    `ModuleNotFoundError`, and the import is the module's full dotted name, not
    `from ... import`: on a partial install, where the packages down to
    `...trace.v1` import and the module does not, the first raises
    `ModuleNotFoundError` and the second a plain `ImportError`, which would be
    an error where it should be a skip.
    """
    try:
        import opentelemetry.proto.collector.trace.v1.trace_service_pb2 as pb2
    except ModuleNotFoundError:
        if os.environ.get(REQUIRE):
            raise
        pytest.skip(NO_EXTRA)
    return pb2


def _built(read: spanweave.Records) -> bytes:
    """The graph a read builds, its own diagnostics included, as bytes."""
    collector = DiagnosticCollector()
    collector.extend(read.diagnostics)
    return spanweave.dumps(
        graph_from_records(
            list(read.records),
            collector=collector,
            skipped_records=read.skipped_records,
        )
    )


# --- The oracle: 29 pairs ----------------------------------------------------


def test_the_zoo_seals_twenty_nine_pairs():
    """The number the series cites (`TASKS.md`, *The wire series*; `PROBES.md` L1)."""
    assert len(PAIRS) == 29


@pytest.mark.parametrize(("run", "json_body", "raw_body"), PAIRS, ids=PAIR_IDS)
def test_a_raw_body_reads_as_the_records_its_json_twin_reads_as(
    run, json_body, raw_body
):
    _pb2()
    from_json = spanweave.read_records(json_body.read_bytes())
    from_raw = spanweave.read_protobuf(raw_body.read_bytes())
    assert from_json.records, run
    assert len(from_raw.records) == len(from_json.records), run
    for got, want in zip(from_raw.records, from_json.records, strict=True):
        assert got == want, run
        # The mark is the record's type (`spanweave.read.Unpacked`), and an
        # equal plain dict would compare equal without it.
        assert type(got) is type(want), run
        # Python's `1 == 1.0` would hide a number read as the other kind; the
        # canonical text does not.
        assert json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)
    assert from_raw.diagnostics == from_json.diagnostics, run
    assert from_raw.skipped_records == from_json.skipped_records == 0, run


@pytest.mark.parametrize(("run", "json_body", "raw_body"), PAIRS, ids=PAIR_IDS)
def test_a_raw_body_builds_the_bytes_its_json_twin_builds(run, json_body, raw_body):
    _pb2()
    from_json = _built(spanweave.read_records(json_body.read_bytes()))
    from_raw = _built(spanweave.read_protobuf(raw_body.read_bytes()))
    assert from_raw == from_json, run


def _message_to_dict(raw: bytes, **options: Any) -> dict[str, Any]:
    pb2 = _pb2()
    from google.protobuf import json_format

    request = pb2.ExportTraceServiceRequest.FromString(raw)
    return json_format.MessageToDict(request, **options)


@pytest.mark.parametrize(("run", "json_body", "raw_body"), PAIRS, ids=PAIR_IDS)
def test_the_rendering_is_the_collector_s_json_document_exactly(
    run, json_body, raw_body
):
    """`SPEC.md` §7's table: before the JSON reader sees anything, the
    rendered request *is* the Collector's document, parsed."""
    from spanweave.otlp_protobuf import _rendered

    request = _pb2().ExportTraceServiceRequest.FromString(raw_body.read_bytes())
    assert _rendered(request) == json.loads(json_body.read_bytes()), run


def _hex_ids(document: dict[str, Any]) -> dict[str, Any]:
    from spanweave.otlp_protobuf import _LINK_IDS, _SPAN_IDS, _hex

    for resource_entry in document.get("resourceSpans", []):
        for scope_entry in resource_entry.get("scopeSpans", []):
            for span in scope_entry.get("spans", []):
                _hex(span, _SPAN_IDS)
                for link in span.get("links", []):
                    _hex(link, _LINK_IDS)
    return document


def test_the_collector_differs_from_message_to_dict_in_exactly_two_places():
    """`SPEC.md` §7 says two -- ids and enums -- and each is needed on every
    pair: undo either and no pair's document is the Collector's."""
    for run, json_body, raw_body in PAIRS:
        raw = raw_body.read_bytes()
        want = json.loads(json_body.read_bytes())
        assert _hex_ids(_message_to_dict(raw, use_integers_for_enums=True)) == want
        assert _hex_ids(_message_to_dict(raw)) != want, f"{run}: enums"
        assert _message_to_dict(raw, use_integers_for_enums=True) != want, run


def _levels(value: Any, at: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every object in a parsed document, outermost first, each with its
    level: the keys on the way to it, a list's items one level whatever their
    index (``resourceSpans[].scopeSpans[].spans[]``). The document's is ``""``."""
    if isinstance(value, dict):
        inner = [
            found
            for key, item in value.items()
            for found in _levels(item, f"{at}.{key}" if at else key)
        ]
        return [(at, value), *inner]
    if isinstance(value, list):
        return [found for item in value for found in _levels(item, f"{at}[]")]
    return []


def _what_no_pair_carries(pb2: ModuleType) -> Any:
    """One span carrying, beside what some pairs do -- an event, a status with
    a message, a scope entry's `schemaUrl` -- what none does (the scoped
    review of 2026-10-18, R-9): a link with a `traceState` and attributes, a
    resource entry's `schemaUrl`, and attributes on the scope; and an array
    and a kvlist among its attributes, which no pair carries either (the zoo
    guard below)."""
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.resource.v1 import resource_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    def attribute(key: str, **value: Any) -> Any:
        return common_pb2.KeyValue(key=key, value=common_pb2.AnyValue(**value))

    array = common_pb2.ArrayValue(values=[common_pb2.AnyValue(int_value=1)])
    kvlist = common_pb2.KeyValueList(values=[attribute("t", bool_value=True)])
    span = trace_pb2.Span(
        trace_id=TRACE,
        span_id=SPAN,
        parent_span_id=bytes([0xC0] * 8),
        name="s",
        kind=3,
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        attributes=[
            attribute("s", string_value="v"),
            attribute("a", array_value=array),
            attribute("k", kvlist_value=kvlist),
        ],
        events=[
            trace_pb2.Span.Event(
                time_unix_nano=1, name="e", attributes=[attribute("e", int_value=2)]
            )
        ],
        links=[
            trace_pb2.Span.Link(
                trace_id=bytes([0xAB] * 16),
                span_id=bytes([0xC1] * 8),
                trace_state="k=v",
                attributes=[attribute("l", bool_value=True)],
            )
        ],
        status=trace_pb2.Status(message="m", code=2),
    )
    scope = common_pb2.InstrumentationScope(
        name="x", version="1", attributes=[attribute("c", string_value="v")]
    )
    return pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                resource=resource_pb2.Resource(
                    attributes=[attribute("service.name", string_value="r")]
                ),
                scope_spans=[
                    trace_pb2.ScopeSpans(
                        scope=scope, spans=[span], schema_url="https://example/s"
                    )
                ],
                schema_url="https://example/r",
            )
        ]
    )


_SPAN_LEVEL = "resourceSpans[].scopeSpans[].spans[]"

#: Every level of `_what_no_pair_carries`'s request, and whether
#: `MessageToDict` -- the runtime, not the library -- writes some object's keys
#: there out of sorted order. Where it does, field-number order is not
#: alphabetical: `resource`, `scopeSpans`, `schemaUrl`; `scope`, `spans`,
#: `schemaUrl`; `name`, `version`, `attributes`; a span's `traceId` before its
#: `spanId`; `timeUnixNano`, `name`; `traceId`, `spanId`, `traceState`;
#: `message`, `code`. Where it does not, the runtime's order is sorted already
#: -- the document's one key, a resource's `attributes`, each attribute's
#: `key` and `value`, each AnyValue's one key (a oneof), an array's or a
#: kvlist's `values` -- so sorting there changes nothing, and the request
#: cannot show whether the writer sorts that level. Nor could any other
#: request at the document, a resource, an AnyValue, an array or a kvlist:
#: there field-number order is alphabetical, or the object has one key. An
#: attribute could be written unsorted only by stating a `keyStrindex` (after
#: `value`), which the extra's floor, opentelemetry-proto 1.28, does not define.
EVERY_LEVEL = {
    "": False,
    "resourceSpans[]": True,
    "resourceSpans[].resource": False,
    "resourceSpans[].resource.attributes[]": False,
    "resourceSpans[].resource.attributes[].value": False,
    "resourceSpans[].scopeSpans[]": True,
    "resourceSpans[].scopeSpans[].scope": True,
    "resourceSpans[].scopeSpans[].scope.attributes[]": False,
    "resourceSpans[].scopeSpans[].scope.attributes[].value": False,
    _SPAN_LEVEL: True,
    f"{_SPAN_LEVEL}.attributes[]": False,
    f"{_SPAN_LEVEL}.attributes[].value": False,
    f"{_SPAN_LEVEL}.attributes[].value.arrayValue": False,
    f"{_SPAN_LEVEL}.attributes[].value.arrayValue.values[]": False,
    f"{_SPAN_LEVEL}.attributes[].value.kvlistValue": False,
    f"{_SPAN_LEVEL}.attributes[].value.kvlistValue.values[]": False,
    f"{_SPAN_LEVEL}.attributes[].value.kvlistValue.values[].value": False,
    f"{_SPAN_LEVEL}.events[]": True,
    f"{_SPAN_LEVEL}.events[].attributes[]": False,
    f"{_SPAN_LEVEL}.events[].attributes[].value": False,
    f"{_SPAN_LEVEL}.links[]": True,
    f"{_SPAN_LEVEL}.links[].attributes[]": False,
    f"{_SPAN_LEVEL}.links[].attributes[].value": False,
    f"{_SPAN_LEVEL}.status": True,
}


def test_the_document_read_back_is_written_with_sorted_keys(monkeypatch):
    """The text `read_protobuf` hands `read_records` is written with sorted
    keys at every level, as the graph and the record digest are, and not in
    the order the runtime writes a message's fields in (Qodo's review of
    PR #6, finding 4). Nothing reads that order, so no other test can see it.

    Every object in the text is walked -- the document, each `resourceSpans[]`
    entry and its resource, each scope entry and its scope, each span, its
    events, links and status, and every attribute and AnyValue -- on the 29
    pairs and on a request carrying the levels the pairs lack (the scoped
    review of 2026-10-18, R-9). Where the runtime's own order is not sorted
    is read from `MessageToDict` on that request, level by level, and not from
    the library: the test cannot pass by accident of the input, and holds
    wherever in the library the sorting is done."""
    pb2 = _pb2()
    from google.protobuf import json_format

    from spanweave import otlp_protobuf

    texts: list[bytes] = []

    def read_back(data: bytes) -> spanweave.Records:
        texts.append(bytes(data))
        return spanweave.read_records(data)

    def read_back_by(body: bytes) -> Any:
        texts.clear()
        spanweave.read_protobuf(body)
        (text,) = texts
        # `json.loads` keeps the order the text wrote the keys in.
        return json.loads(text)

    monkeypatch.setattr(otlp_protobuf, "read_records", read_back)
    request = _what_no_pair_carries(pb2)
    documents = [
        (run, read_back_by(raw_body.read_bytes())) for run, _, raw_body in PAIRS
    ]
    documents.append(
        ("the hand-made request", read_back_by(request.SerializeToString()))
    )
    for run, document in documents:
        for level, entry in _levels(document):
            assert list(entry) == sorted(entry), f"{run}: {level or 'the document'}"

    # The hand-made request's text has every level the table names; the
    # runtime writes the same levels, and at each the table marks, and only
    # there, its own order is not sorted.
    _, hand_made = documents[-1]
    assert {level for level, _ in _levels(hand_made)} == set(EVERY_LEVEL)
    runtime = json_format.MessageToDict(request, use_integers_for_enums=True)
    unsorted: dict[str, bool] = {}
    for level, entry in _levels(runtime):
        unsorted[level] = unsorted.get(level, False) or list(entry) != sorted(entry)
    assert unsorted == EVERY_LEVEL


# --- Where no pair can show anything (`OPEN_QUESTIONS.md` §23) -----------------


def _zoo_raw() -> bytes:
    return PAIRS[0][2].read_bytes()


@pytest.mark.parametrize(
    "body",
    [b"\xff\xff\xff", "truncated"],
    ids=["not-a-message", "a-zoo-body-less-its-last-byte"],
)
def test_a_body_that_will_not_parse_is_one_malformed_record_with_no_source(body):
    """1A: `undecodable_bytes`'s precedent -- JSON cannot write the bytes."""
    _pb2()
    data = _zoo_raw()[:-1] if body == "truncated" else body
    read = spanweave.read_protobuf(data)
    assert read.records == ()
    assert read.skipped_records == 1
    assert [d.code for d in read.diagnostics] == ["malformed_record"]
    (diagnostic,) = read.diagnostics
    assert diagnostic.source is None
    assert diagnostic.node_id is None
    assert diagnostic.level is spanweave.DiagnosticLevel.WARNING


def test_an_empty_body_is_an_empty_request_and_reads_as_its_json_does():
    _pb2()
    read = spanweave.read_protobuf(b"")
    assert read == spanweave.read_records(b'{"resourceSpans": []}')
    assert read.records == () and read.diagnostics == () and not read.skipped_records


#: Field 99, wire type 0 (varint), value 42: a tag `ResourceSpans`, `Span` and
#: every other OTLP message leaves undefined.
UNKNOWN_VARINT = bytes([0x98, 0x06, 0x2A])


def _undefined(number: int, wire_type: int = 0) -> dict[str, Any]:
    """An `unknown_fields` entry for a number the installed schema does not define."""
    return {
        "number": number,
        "wire_type": wire_type,
        "defined": False,
        "expected_wire_type": None,
    }


def _with_an_unknown_field_on_span(raw: bytes, resource: int, scope: int, span: int):
    pb2 = _pb2()
    request = pb2.ExportTraceServiceRequest.FromString(raw)
    target = request.resource_spans[resource].scope_spans[scope].spans[span]
    target.ParseFromString(target.SerializeToString() + UNKNOWN_VARINT)
    return request.SerializeToString()


def test_an_unknown_field_is_read_and_reported_never_dropped():
    """2B: the spans are kept, and the loss is said, with the path and number."""
    run, json_body, raw_body = PAIRS[0]
    raw = _with_an_unknown_field_on_span(raw_body.read_bytes(), 0, 0, 1)
    from_json = spanweave.read_records(json_body.read_bytes())
    from_raw = spanweave.read_protobuf(raw)

    assert from_raw.records == from_json.records, run
    assert from_raw.skipped_records == 0
    (diagnostic,) = from_raw.diagnostics
    assert diagnostic.code == "unknown_fields"
    assert diagnostic.level is spanweave.DiagnosticLevel.WARNING
    assert diagnostic.node_id is None and diagnostic.adapter is None
    assert diagnostic.source == {
        "path": "resourceSpans[0].scopeSpans[0].spans[1]",
        "fields": [_undefined(99)],
    }
    assert "99" not in diagnostic.message  # the numbers are in `source`
    assert "1 not defined by the installed schema" in diagnostic.message
    assert "not readable" not in diagnostic.message

    # The graph differs from the pair's by that diagnostic and nothing else.
    with_it = json.loads(_built(from_raw))
    without_it = json.loads(_built(from_json))
    assert with_it != without_it
    reported = [d for d in with_it["diagnostics"] if d["code"] == "unknown_fields"]
    assert len(reported) == 1
    with_it["diagnostics"].remove(reported[0])
    # ... and by the count `meta` keeps of the diagnostics, which is that one.
    assert with_it["meta"]["diagnostic_count"] == len(with_it["diagnostics"]) + 1
    with_it["meta"]["diagnostic_count"] -= 1
    assert with_it == without_it


def test_each_message_carrying_unknown_fields_is_one_report():
    pb2 = _pb2()
    request = pb2.ExportTraceServiceRequest.FromString(_zoo_raw())
    level = request.resource_spans[0]
    level.ParseFromString(level.SerializeToString() + UNKNOWN_VARINT + UNKNOWN_VARINT)
    raw = request.SerializeToString() + bytes([0xA0, 0x06, 0x07])  # field 100
    read = spanweave.read_protobuf(raw)
    sources = sorted(
        (d.source for d in read.diagnostics if d.code == "unknown_fields"),
        key=json.dumps,
    )
    assert sources == [
        {"path": "", "fields": [_undefined(100)]},
        {"path": "resourceSpans[0]", "fields": [_undefined(99), _undefined(99)]},
    ]


def _span_with_tail(pb2: ModuleType, tail: bytes) -> bytes:
    """A one-span request whose span ends in ``tail``, as bytes on the wire."""
    from opentelemetry.proto.trace.v1 import trace_pb2

    span = trace_pb2.Span(trace_id=bytes([1] * 16), span_id=bytes([2] * 8))
    request = _request(pb2, span)
    target = request.resource_spans[0].scope_spans[0].spans[0]
    target.ParseFromString(target.SerializeToString() + tail)
    return request.SerializeToString()


#: A span field the schema defines, sent with a wire type other than its own:
#: ``(name, number, tail on the wire, wire type sent, wire type expected)``.
#: One for each wire type the schema expects of a `Span` field -- one per wire
#: type, not one per row of the table, which is keyed by field type: a span's
#: ids (`bytes`), its `dropped_*_count`s (`uint32`) and its message fields
#: (`message`) are looked up in rows these do not reach. Every row a field
#: reachable from the request uses is held further down, by
#: test_every_reachable_field_is_expected_with_the_wire_type_the_runtime_writes.
_MISTYPED_SPAN_FIELDS = [
    # `name` (5, a string) as the varint 5.
    ("name", 5, bytes([5 << 3 | 0, 0x05]), 0, 2),
    # `kind` (6, an enum) as a length-delimited "\x02".
    ("kind", 6, bytes([6 << 3 | 2, 0x01, 0x02]), 2, 0),
    # `start_time_unix_nano` (7, fixed64) as the varint 1.
    ("start_time_unix_nano", 7, bytes([7 << 3 | 0, 0x01]), 0, 1),
    # `flags` (16, fixed32) as the varint 1: a two-byte tag.
    ("flags", 16, bytes([0x80, 0x01, 0x01]), 0, 5),
]


@pytest.mark.parametrize(
    ("name", "number", "tail", "sent", "expected"),
    _MISTYPED_SPAN_FIELDS,
    ids=[row[0] for row in _MISTYPED_SPAN_FIELDS],
)
def test_a_defined_field_with_another_wire_type_is_reported_as_defined(
    name, number, tail, sent, expected
):
    """Qodo's review of PR #6, finding 7: the runtime keeps a known number
    that arrived with the wrong wire type with the unknown ones, and leaves the
    field at its default. The report names it as defined, with the wire type
    the schema expects, and does not blame the schema's age."""
    pb2 = _pb2()
    raw = _span_with_tail(pb2, tail)
    request = pb2.ExportTraceServiceRequest.FromString(raw)
    span = request.resource_spans[0].scope_spans[0].spans[0]
    assert not getattr(span, name)  # left at its default

    read = spanweave.read_protobuf(raw)
    (diagnostic,) = (d for d in read.diagnostics if d.code == "unknown_fields")
    assert diagnostic.level is spanweave.DiagnosticLevel.WARNING
    assert diagnostic.source == {
        "path": "resourceSpans[0].scopeSpans[0].spans[0]",
        "fields": [
            {
                "number": number,
                "wire_type": sent,
                "defined": True,
                "expected_wire_type": expected,
            }
        ],
    }
    assert "1 not readable as the installed schema defines it" in diagnostic.message
    assert "not defined by the installed schema" not in diagnostic.message


def test_defined_is_looked_up_on_the_message_that_carries_the_field():
    """Field 2 is `spanId` on a `Span` and `scopeSpans` on a `ResourceSpans`,
    and field 5 is defined on a `Span` and on no message above it: each is
    judged by its own message's schema, not by the request's or the span's."""
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    span = trace_pb2.Span(trace_id=bytes([1] * 16), span_id=bytes([2] * 8))
    request = _request(pb2, span)
    resource = request.resource_spans[0]
    # On the resource: field 5 (undefined there) and field 2 (`scopeSpans`) as
    # a varint, after the resource's own bytes.
    resource.ParseFromString(
        resource.SerializeToString() + bytes([5 << 3 | 0, 0x01, 2 << 3 | 0, 0x01])
    )
    read = spanweave.read_protobuf(request.SerializeToString())
    (diagnostic,) = (d for d in read.diagnostics if d.code == "unknown_fields")
    assert diagnostic.source == {
        "path": "resourceSpans[0]",
        "fields": [
            _undefined(5),
            {"number": 2, "wire_type": 0, "defined": True, "expected_wire_type": 2},
        ],
    }


def test_a_message_carrying_both_kinds_is_one_report_counting_each():
    """One diagnostic per message stays; its message counts the defined
    fields and the undefined ones, the defined first, and the entries keep the
    order the fields arrived in. The message is held whole, so how the two
    counts are joined is held too (the scoped review of 2026-10-18, R-6)."""
    pb2 = _pb2()
    # Field 99 (undefined) twice, then `name` (5) as a varint.
    raw = _span_with_tail(pb2, UNKNOWN_VARINT + UNKNOWN_VARINT + bytes([0x28, 0x05]))
    read = spanweave.read_protobuf(raw)
    (diagnostic,) = (d for d in read.diagnostics if d.code == "unknown_fields")
    assert diagnostic.source == {
        "path": "resourceSpans[0].scopeSpans[0].spans[0]",
        "fields": [
            _undefined(99),
            _undefined(99),
            {"number": 5, "wire_type": 0, "defined": True, "expected_wire_type": 2},
        ],
    }
    assert diagnostic.message == (
        "the message at resourceSpans[0].scopeSpans[0].spans[0] carries 3 "
        "field(s) not read into it by the OTLP schema this reader was installed "
        "with: 1 not readable as the installed schema defines it (a number it "
        "defines on this message, with a wire type other than the one it "
        "expects -- a malformed body), and 2 not defined by the installed "
        "schema (a newer OTLP, or an extension); it was read without them. "
        "Their numbers and wire types are here, with the wire type the schema "
        "expects where it defines the number, and their bytes are not -- a "
        "field it does not define has no name and no type to write it by, and "
        "one it does was not written in its type (`SPEC.md` §3.7)"
    )


def _source_keys(shape: str) -> tuple[list[str], list[str]]:
    """The keys a `source` shape names: its own, and its per-field entry's
    (the object in ``[{...}, ...]``)."""
    entry = re.search(r"\[\{(.*)\}, \.\.\.\]", shape)
    assert entry, f"no per-field entry in {shape!r}"
    key = re.compile(r'"(\w+)":')
    return key.findall(shape.replace(entry[0], "")), key.findall(entry[1])


def test_unknown_fields_source_carries_the_keys_the_spec_s_row_names():
    """The scoped review of 2026-10-18, R-6: `SPEC.md` §3.7's `source` row
    for `unknown_fields`, read as `make shape` reads it into the shape
    artifact (`tests/schema_shape.py`), names the keys the reader's diagnostic
    carries -- the source's own, and each field entry's, a defined field's and
    an undefined one's. A key renamed in the row and the artifact regenerated
    is red here, where nothing else reads the row against the code."""
    pb2 = _pb2()
    top, per_field = _source_keys(diagnostic_source_shapes()["unknown_fields"])
    # Field 99 (undefined), then `name` (5) as a varint.
    raw = _span_with_tail(pb2, UNKNOWN_VARINT + bytes([0x28, 0x05]))
    read = spanweave.read_protobuf(raw)
    (source,) = (d.source for d in read.diagnostics if d.code == "unknown_fields")
    assert isinstance(source, dict)
    assert sorted(source) == sorted(top)
    assert [entry["defined"] for entry in source["fields"]] == [False, True]
    for entry in source["fields"]:
        assert sorted(entry) == sorted(per_field)


def _varint(value: int) -> bytes:
    """``value`` as a protobuf varint: seven bits a byte, the low ones first."""
    out = bytearray()
    while True:
        low, value = value & 0x7F, value >> 7
        out.append(low | 0x80 if value else low)
        if not value:
            return bytes(out)


def _tag(data: bytes) -> tuple[int, int]:
    """The field number and the wire type of the tag ``data`` starts with."""
    tag = shift = 0
    for byte in data:
        tag |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return tag >> 3, tag & 7
    raise AssertionError(f"no tag in {data.hex()}")


def _reachable(root: Any) -> dict[str, Any]:
    """Every message type reachable from ``root`` through its message fields,
    singular or repeated, at any depth: an empty instance of each, by its full
    name, ``root`` first."""
    from google.protobuf.message import Message

    found: dict[str, Any] = {}
    todo = [root]
    while todo:
        message = todo.pop(0)
        if message.DESCRIPTOR.full_name in found:
            continue
        found[message.DESCRIPTOR.full_name] = message
        for field in message.DESCRIPTOR.fields:
            if field.type == field.TYPE_MESSAGE:
                held = getattr(type(message)(), field.name)
                todo.append(held if isinstance(held, Message) else held.add())
    return found


def _written(message_type: Any, field: Any) -> int:
    """The wire type the runtime writes ``field`` with: the field set alone on
    an empty message, the message serialized, and its one tag read back."""
    from google.protobuf.message import Message

    message = message_type()
    held = getattr(message, field.name)
    if isinstance(held, Message):
        held.SetInParent()
    elif field.type == field.TYPE_MESSAGE:
        held.add()
    else:
        # A value of the Python kind the field takes; an integer, but for these.
        value = {
            field.TYPE_STRING: "a",
            field.TYPE_BYTES: b"a",
            field.TYPE_BOOL: True,
            field.TYPE_DOUBLE: 0.5,
            field.TYPE_FLOAT: 0.5,
        }.get(field.type, 1)
        if isinstance(held, int | float | str | bytes):
            setattr(message, field.name, value)
        else:  # a repeated scalar
            held.append(value)
    number, wire_type = _tag(message.SerializeToString())
    assert number == field.number, field.full_name
    return wire_type


def test_every_reachable_field_is_expected_with_the_wire_type_the_runtime_writes():
    """The scoped review of 2026-10-18, R-5: for a number the schema defines,
    `unknown_fields` names the wire type the field's type is written with
    (`SPEC.md` §3.7), from the reader's table of field type to wire type. The
    runtime is the oracle here: for every field of every message reachable
    from the request, the wire type it writes that field with, against the
    `expected_wire_type` the reader reports when the same number arrives with
    another one. So every row of the table a reachable field uses is held,
    whichever message uses it.

    What the runtime writes, and not `type_checkers.FIELD_TYPE_TO_WIRE_TYPE`:
    that is the pure-Python implementation's table, in an internal module,
    while the backend the runtime runs on (upb) writes by its own; and what the
    spec's row says is how the field is written. A repeated number field would
    be written packed (2), where the table names its type's unpacked wire type
    (2066828's judgement): none is reachable, and the day one is, this fails
    on it."""
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    from spanweave.otlp_protobuf import _unknown_fields

    reachable = _reachable(pb2.ExportTraceServiceRequest())
    written: dict[str, Any] = {}
    reported: dict[str, Any] = {}
    for instance in reachable.values():
        for field in instance.DESCRIPTOR.fields:
            where = f"{field.full_name} (field type {field.type})"
            wire_type = _written(type(instance), field)
            # The same number with another wire type: a varint 1 for a field
            # written otherwise, an empty length-delimited one for a varint.
            sent = 2 if wire_type == 0 else 0
            mistyped = type(instance)()
            mistyped.ParseFromString(
                _varint(field.number << 3 | sent) + bytes([0 if sent else 1])
            )
            entry = {
                "number": field.number,
                "wire_type": sent,
                "defined": True,
                "expected_wire_type": wire_type,
            }
            written[where] = [("", [entry])]
            reported[where] = _unknown_fields(mistyped, "")
    assert reported == written

    # The walk is whole: every message a walked field holds was walked too, so
    # it stopped short of none; and it reached a span, every field of it.
    for instance in reachable.values():
        for field in instance.DESCRIPTOR.fields:
            if field.type == field.TYPE_MESSAGE:
                assert field.message_type.full_name in reachable, field.full_name
    span = trace_pb2.Span.DESCRIPTOR
    assert span.full_name in reachable
    assert {f"{f.full_name} (field type {f.type})" for f in span.fields} <= set(written)


def _attribute(pb2: ModuleType, **value: Any) -> bytes:
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    span = trace_pb2.Span(
        trace_id=bytes(range(16)),
        span_id=bytes(range(8)),
        name="s",
        attributes=[common_pb2.KeyValue(key="k", value=common_pb2.AnyValue(**value))],
    )
    request = pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(scope_spans=[trace_pb2.ScopeSpans(spans=[span])])
        ]
    )
    return request.SerializeToString()


@pytest.mark.parametrize("number", [1.0, 1.5, -0.0])
def test_a_double_value_reads_as_a_float(number):
    """3C: `MessageToDict`'s float -- the one place no pair checks."""
    read = spanweave.read_protobuf(_attribute(_pb2(), double_value=number))
    (record,) = read.records
    value = record["attributes"]["k"]
    assert type(value) is float
    assert value == number


#: Each non-finite double, and the string proto3 JSON spells it as -- which is
#: what the Collector writes too.
NON_FINITE = {
    "NaN": float("nan"),
    "Infinity": float("inf"),
    "-Infinity": float("-inf"),
}


@pytest.mark.parametrize("spelling", list(NON_FINITE))
def test_a_non_finite_double_value_reads_as_its_json_spelling_on_both_paths(spelling):
    """Qodo's review of PR #6, finding 5, pinned (`SPEC.md` §7): a non-finite
    `doubleValue` is the string proto3 JSON spells it, on both paths, with no
    diagnostic. A graph cannot carry a float NaN (`allow_nan=False`), and the
    JSON path reads the string as a string, so the protobuf body and its JSON
    spelling -- written here, not rendered -- yield equal records and the same
    graph bytes. Whether it should draw a diagnostic is an open thread
    (`TASKS.md`); this holds what it reads as until that is decided."""
    pb2 = _pb2()
    from opentelemetry.proto.common.v1 import common_pb2

    from spanweave.otlp_protobuf import _rendered

    def request(**value: Any) -> Any:
        built = _root(pb2)
        built.resource_spans[0].scope_spans[0].spans[0].attributes.append(
            common_pb2.KeyValue(key="k", value=common_pb2.AnyValue(**value))
        )
        return built

    body = request(double_value=NON_FINITE[spelling]).SerializeToString()
    document = _rendered(_root(pb2))
    _spans(document)[0]["attributes"].append(
        {"key": "k", "value": {"doubleValue": spelling}}
    )
    text = json.dumps(document, sort_keys=True, allow_nan=False).encode()

    from_protobuf = spanweave.read_protobuf(body)
    from_json = spanweave.read_records(text)
    assert from_protobuf == from_json
    assert _built(from_protobuf) == _built(from_json)
    for read in (from_protobuf, from_json):
        (record,) = read.records
        value = record["attributes"]["k"]
        assert type(value) is str
        assert value == spelling
        assert read.diagnostics == ()
        assert read.skipped_records == 0
    # Nothing in the graph is about the number: it draws what a finite one does.
    finite = spanweave.read_protobuf(request(double_value=1.5).SerializeToString())
    assert _codes(from_protobuf) == _codes(finite)


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value))
    return set()


def test_the_zoo_holds_no_double_value_so_no_pair_checks_one():
    """The day a pair carries one, this fails and the float claim is checkable.

    `SPEC.md` §7 states the float as unchecked by the pairs; a zoo capture
    with a `doubleValue` re-encoded by a Collector would decide `1` against
    `1.0` (`OPEN_QUESTIONS.md` §23, 3C).
    """
    for _, json_body, _ in PAIRS:
        assert "doubleValue" not in _keys(json.loads(json_body.read_bytes()))


# --- What the pairs do not cover, a hand-made request does (`SPEC.md` §7) -----
#
# The OTLP/JSON specification's rule is proto3's JSON mapping with three
# exceptions: lowerCamelCase keys, trace and span ids as hex rather than base64,
# and enums as integers. So a `bytes` field other than an id is standard
# base64, a message is an object of its set fields, a repeated field is an
# array, and a field at its default -- a zero enum, a zero integer, a message
# absent from the wire -- is omitted. Each test below holds the rendering to
# that rule where no pair can; each is **spec, not pair**, as `doubleValue` is,
# and the guard after them fails the day a zoo body carries one.


def _spans(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        span
        for resource_entry in document.get("resourceSpans", [])
        for scope_entry in resource_entry.get("scopeSpans", [])
        for span in scope_entry.get("spans", [])
    ]


def _request(pb2: ModuleType, *spans: Any) -> Any:
    from opentelemetry.proto.trace.v1 import trace_pb2

    return pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(scope_spans=[trace_pb2.ScopeSpans(spans=spans)])
        ]
    )


def test_a_link_s_ids_render_as_lowercase_hex():
    """Spec, not pair: no zoo span has a link. Two links, so each is rendered
    and not only the first; bytes above 0x9 in each id, so uppercase shows."""
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    from spanweave.otlp_protobuf import _rendered

    links = [
        trace_pb2.Span.Link(trace_id=bytes([0xAB] * 16), span_id=bytes([0xC0] * 8)),
        trace_pb2.Span.Link(trace_id=bytes(range(16)), span_id=bytes([0xFE] * 8)),
    ]
    span = trace_pb2.Span(
        trace_id=bytes([0x0D] * 16), span_id=bytes([0xE1] * 8), name="s", links=links
    )
    request = _request(pb2, span)
    (rendered,) = _spans(_rendered(request))
    assert rendered["links"] == [
        {"traceId": "ab" * 16, "spanId": "c0" * 8},
        {"traceId": "000102030405060708090a0b0c0d0e0f", "spanId": "fe" * 8},
    ]

    (record,) = spanweave.read_protobuf(request.SerializeToString()).records
    assert record["links"] == [
        {"trace_id": "ab" * 16, "span_id": "c0" * 8},
        {"trace_id": "000102030405060708090a0b0c0d0e0f", "span_id": "fe" * 8},
    ]
    # ... which is what the same span written as OTLP/JSON reads as.
    twin = spanweave.read_records(
        json.dumps(_rendered(request), sort_keys=True).encode()
    )
    assert spanweave.read_protobuf(request.SerializeToString()) == twin


#: `bytesValue` is proto3 JSON's `bytes`: standard base64, padded. The bytes
#: are chosen so base64 and hex differ and the alphabet's `+` and `/` appear
#: (the test asserts both of its own fixture).
BYTES = bytes([0x00, 0x0F, 0xBF, 0x10])


def test_bytes_array_and_kvlist_values_render_as_the_otlp_json_spec_writes_them():
    """Spec, not pair: the zoo's AnyValues are `stringValue`, `intValue` and
    `boolValue` only (the guard below)."""
    # URL-safe base64 differs from standard in exactly these two characters,
    # so the fixture must show both, and must not read the same as hex.
    standard = base64.b64encode(BYTES).decode("ascii")
    assert "+" in standard and "/" in standard and standard != BYTES.hex()
    pb2 = _pb2()
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    from spanweave.otlp_protobuf import _rendered

    value = common_pb2.AnyValue
    nested = common_pb2.KeyValue(key="b", value=value(bytes_value=BYTES))
    attributes = [
        common_pb2.KeyValue(key="bytes", value=value(bytes_value=BYTES)),
        common_pb2.KeyValue(
            key="array",
            value=value(
                array_value=common_pb2.ArrayValue(
                    values=[value(string_value="x"), value(int_value=3), value()]
                )
            ),
        ),
        common_pb2.KeyValue(
            key="kvlist",
            value=value(
                kvlist_value=common_pb2.KeyValueList(
                    values=[
                        common_pb2.KeyValue(key="t", value=value(bool_value=True)),
                        nested,
                    ]
                )
            ),
        ),
    ]
    span = trace_pb2.Span(
        trace_id=bytes(16), span_id=bytes(8), name="s", attributes=attributes
    )
    request = _request(pb2, span)
    (rendered,) = _spans(_rendered(request))
    assert rendered["attributes"] == [
        {"key": "bytes", "value": {"bytesValue": "AA+/EA=="}},
        {
            "key": "array",
            "value": {
                "arrayValue": {"values": [{"stringValue": "x"}, {"intValue": "3"}, {}]}
            },
        },
        {
            "key": "kvlist",
            "value": {
                "kvlistValue": {
                    "values": [
                        {"key": "t", "value": {"boolValue": True}},
                        {"key": "b", "value": {"bytesValue": "AA+/EA=="}},
                    ]
                }
            },
        },
    ]
    twin = spanweave.read_records(
        json.dumps(_rendered(request), sort_keys=True).encode()
    )
    assert spanweave.read_protobuf(request.SerializeToString()) == twin


def test_kind_zero_no_status_and_flags_zero_render_omitted():
    """Spec, not pair: every zoo span states `kind`, `status` and `flags`.

    Proto3's JSON mapping omits a zero enum, a zero integer and a message
    absent from the wire, and so does the rendering. Whether a Collector
    writes an absent `status` as `{}` -- which its JSON twin would read as
    `UNSET` -- no pair shows (`SPEC.md` §7).
    """
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    from spanweave.otlp_protobuf import _rendered

    # Ids not all zero: an all-zero one is omitted too, and that is another
    # test's (`test_an_all_zero_id_reads_as_an_unset_one`).
    span = trace_pb2.Span(
        trace_id=bytes([0x0D] * 16),
        span_id=bytes([0xE1] * 8),
        name="s",
        kind=0,
        flags=0,
    )
    assert not span.HasField("status")
    request = _request(pb2, span)
    (rendered,) = _spans(_rendered(request))
    assert rendered == {"traceId": "0d" * 16, "spanId": "e1" * 8, "name": "s"}

    (record,) = spanweave.read_protobuf(request.SerializeToString()).records
    assert not {"kind", "status", "flags"} & set(record)


#: Ids with every byte above 0x9 and none zero, so the zero rule cannot reach
#: them and uppercase hex would show.
TRACE = bytes([0x0D] * 16)
SPAN = bytes([0xE1] * 8)


def _root(pb2: ModuleType, **fields: Any) -> Any:
    """A request of one root span with one link, every id but the parent's
    stated unless ``fields`` says otherwise (``None`` leaves a field unset).
    An OpenInference span, so a graph builds from it."""
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    kind = common_pb2.KeyValue(
        key="openinference.span.kind", value=common_pb2.AnyValue(string_value="LLM")
    )
    link = {"trace_id": bytes([0xAB] * 16), "span_id": bytes([0xC0] * 8)}
    span = {"trace_id": TRACE, "span_id": SPAN, "name": "root", "attributes": [kind]}
    for key, value in fields.items():
        owner, name = key.split(".")
        target = link if owner == "link" else span
        if value is None:
            target.pop(name, None)
        else:
            target[name] = value
    return _request(pb2, trace_pb2.Span(links=[trace_pb2.Span.Link(**link)], **span))


def _codes(read: spanweave.Records) -> list[str]:
    return [d["code"] for d in json.loads(_built(read))["diagnostics"]]


def test_a_root_whose_parent_span_id_is_eight_zero_bytes_is_a_root():
    """The Collector's rule, not a pair (`SPEC.md` §7): it treats an all-zero
    id as empty and omits it, so the root is a root, with no `orphan_parent`,
    and its records are those of the same request with the field unset."""
    pb2 = _pb2()
    from spanweave.otlp_protobuf import _rendered

    zero = _root(pb2, **{"span.parent_span_id": bytes(8)})
    unset = _root(pb2)
    # The zero bytes are on the wire: proto3 writes a non-empty `bytes` field.
    assert zero.SerializeToString() != unset.SerializeToString()
    (rendered,) = _spans(_rendered(zero))
    assert "parentSpanId" not in rendered

    read = spanweave.read_protobuf(zero.SerializeToString())
    assert read == spanweave.read_protobuf(unset.SerializeToString())
    (record,) = read.records
    assert "parent_id" not in record
    assert "orphan_parent" not in _codes(read)
    assert _built(read) == _built(spanweave.read_protobuf(unset.SerializeToString()))


def test_an_all_zero_trace_id_is_no_trace_id():
    """It yields the record the unset one yields, and the graph says what the
    JSON path says for an omitted id: `missing_trace_id`."""
    pb2 = _pb2()
    from spanweave.otlp_protobuf import _rendered

    zero = spanweave.read_protobuf(
        _root(pb2, **{"span.trace_id": bytes(16)}).SerializeToString()
    )
    unset = spanweave.read_protobuf(
        _root(pb2, **{"span.trace_id": None}).SerializeToString()
    )
    assert zero == unset
    (record,) = zero.records
    assert "trace_id" not in record
    assert "missing_trace_id" in _codes(zero)
    graph = json.loads(_built(zero))
    assert graph["trace_id"] == ""
    # ... as the same span's JSON with the id omitted reads.
    document = _rendered(_root(pb2))
    del _spans(document)[0]["traceId"]
    assert spanweave.read_records(json.dumps(document, sort_keys=True).encode()) == zero


#: Each id the rendering hexes, with the length in bytes the schema gives it.
ID_FIELDS = {
    "span.trace_id": ("traceId", 16),
    "span.span_id": ("spanId", 8),
    "span.parent_span_id": ("parentSpanId", 8),
    "link.trace_id": ("traceId", 16),
    "link.span_id": ("spanId", 8),
}

#: Where the JSON reader puts each id in a record (`SPEC.md` §7).
RECORD_KEYS = {"traceId": "trace_id", "spanId": "span_id", "parentSpanId": "parent_id"}


def _owner(entry: dict[str, Any], field: str) -> dict[str, Any]:
    """The span, or its one link, that ``field`` is on: in a rendered span or
    in a record, which nest a link alike."""
    return entry["links"][0] if field.startswith("link.") else entry


def _stated(read: spanweave.Records, field: str) -> Any:
    """The id ``field`` names, as the one record ``read`` holds states it."""
    key, _ = ID_FIELDS[field]
    (record,) = read.records
    return _owner(record, field).get(RECORD_KEYS[key])


@pytest.mark.parametrize("field", list(ID_FIELDS))
def test_an_all_zero_id_reads_as_an_unset_one(field):
    """Every id the rendering hexes, a span's and a link's: all zero at the
    length the schema gives it is omitted, as an empty one is, and nothing
    else in the request moves."""
    pb2 = _pb2()
    from spanweave.otlp_protobuf import _rendered

    key, width = ID_FIELDS[field]
    zero = _root(pb2, **{field: bytes(width)})
    unset = _root(pb2, **{field: None})
    assert _rendered(zero) == _rendered(unset)
    (rendered,) = _spans(_rendered(zero))
    assert key not in _owner(rendered, field)
    assert spanweave.read_protobuf(zero.SerializeToString()) == spanweave.read_protobuf(
        unset.SerializeToString()
    )


#: Each id, with its one byte not zero at every position the id has.
ONE_BYTE_NOT_ZERO = [
    (field, at) for field, (_, width) in ID_FIELDS.items() for at in range(width)
]


@pytest.mark.parametrize(
    ("field", "at"),
    ONE_BYTE_NOT_ZERO,
    ids=[f"{field}-{at}" for field, at in ONE_BYTE_NOT_ZERO],
)
def test_an_id_with_one_byte_not_zero_is_hex(field, at):
    """All zero, not any zero, and every byte counts: one byte 1 and the rest
    zero is an id wherever that byte is -- the first, the last, either half
    of a trace id -- so a rule that reads only part of the id is caught."""
    pb2 = _pb2()
    from spanweave.otlp_protobuf import _rendered

    key, width = ID_FIELDS[field]
    raw = bytes(at) + b"\x01" + bytes(width - 1 - at)
    request = _root(pb2, **{field: raw})
    (rendered,) = _spans(_rendered(request))
    assert _owner(rendered, field)[key] == raw.hex()
    read = spanweave.read_protobuf(request.SerializeToString())
    assert _stated(read, field) == raw.hex()
    if field == "span.parent_span_id":
        # A stated parent no input contains: the root is an orphan, as the
        # Collector's JSON of this body would make it.
        assert "orphan_parent" in _codes(read)


#: For each id, lengths the schema does not give it: shorter than any id,
#: longer than any, and the other id's own -- so the length is the key's, not
#: "8 or 16".
OTHER_LENGTHS = {16: (4, 8, 17), 8: (4, 16, 17)}
WRONG_LENGTH = [
    (field, length)
    for field, (_, width) in ID_FIELDS.items()
    for length in OTHER_LENGTHS[width]
]


@pytest.mark.parametrize(
    ("field", "length"),
    WRONG_LENGTH,
    ids=[f"{field}-{length}" for field, length in WRONG_LENGTH],
)
def test_an_all_zero_id_of_another_length_is_carried_as_stated(field, length):
    """The Collector's rule is for an id of the length the schema gives it
    (`SPEC.md` §7). At any other length the Collector writes no JSON to match
    -- it would refuse the request -- so the id is hex, all zero too, as the
    JSON path carries a hex string of any length, and it is a stated id."""
    pb2 = _pb2()
    from spanweave.otlp_protobuf import _rendered

    key, _ = ID_FIELDS[field]
    request = _root(pb2, **{field: bytes(length)})
    (rendered,) = _spans(_rendered(request))
    assert _owner(rendered, field)[key] == "00" * length
    read = spanweave.read_protobuf(request.SerializeToString())
    assert _stated(read, field) == "00" * length
    # ... as the same span's JSON stating the id, written by the test, reads.
    document = _rendered(_root(pb2))
    _owner(_spans(document)[0], field)[key] = "00" * length
    assert spanweave.read_records(json.dumps(document, sort_keys=True).encode()) == read
    if field == "span.parent_span_id":
        assert "orphan_parent" in _codes(read)
    if field == "span.trace_id":
        assert "missing_trace_id" not in _codes(read)


def _attribute_lists(document: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """Every attribute list an OTLP/JSON trace document can hold, by path:
    the resource's, the scope's, the span's, each event's and each link's."""
    found: list[tuple[str, list[Any]]] = []
    for r, resource_entry in enumerate(document.get("resourceSpans", [])):
        at = f"resourceSpans[{r}]"
        found.append((f"{at}.resource", resource_entry.get("resource", {})))
        for s, scope_entry in enumerate(resource_entry.get("scopeSpans", [])):
            at_scope = f"{at}.scopeSpans[{s}]"
            found.append((f"{at_scope}.scope", scope_entry.get("scope", {})))
            for n, span in enumerate(scope_entry.get("spans", [])):
                at_span = f"{at_scope}.spans[{n}]"
                found.append((at_span, span))
                for key in ("events", "links"):
                    for e, entry in enumerate(span.get(key, [])):
                        found.append((f"{at_span}.{key}[{e}]", entry))
    return [(path, owner.get("attributes", [])) for path, owner in found]


def _any_value_kinds(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Each AnyValue's kind with its path, in document order: every attribute
    list, and every value nested in an `arrayValue` or a `kvlistValue`."""
    kinds: list[tuple[str, str]] = []

    def walk(path: str, value: dict[str, Any]) -> None:
        for kind in value:
            kinds.append((path, kind))
        for i, item in enumerate(value.get("arrayValue", {}).get("values", [])):
            walk(f"{path}.arrayValue[{i}]", item)
        for entry in value.get("kvlistValue", {}).get("values", []):
            walk(f"{path}.kvlistValue.{entry['key']}", entry["value"])

    for path, attributes in _attribute_lists(document):
        for attribute in attributes:
            walk(f"{path}.{attribute['key']}", attribute["value"])
    return kinds


def test_the_any_value_census_reads_every_attribute_list_and_every_nested_value():
    """The guard below is only as wide as this walk: a kind planted in each
    place an AnyValue can sit is found there, and nowhere else."""

    def attributes(key: str, value: dict[str, Any]) -> dict[str, Any]:
        return {"attributes": [{"key": key, "value": value}]}

    array = {"arrayValue": {"values": [{"intValue": "1"}, {}]}}
    kvlist = {"kvlistValue": {"values": [{"key": "t", "value": {"boolValue": True}}]}}
    span_entry = {
        "attributes": [{"key": "a", "value": array}, {"key": "k", "value": kvlist}],
        "events": [attributes("e", {"stringValue": "v"})],
        "links": [attributes("l", {"intValue": "2"})],
    }
    scope_entry = {
        "scope": {"name": "x", **attributes("c", {"bytesValue": "AA=="})},
        "spans": [span_entry],
    }
    resource_entry = {
        "resource": attributes("r", {"doubleValue": 1.5}),
        "scopeSpans": [scope_entry],
    }
    document = {"resourceSpans": [resource_entry]}
    span = "resourceSpans[0].scopeSpans[0].spans[0]"
    assert _any_value_kinds(document) == [
        ("resourceSpans[0].resource.r", "doubleValue"),
        ("resourceSpans[0].scopeSpans[0].scope.c", "bytesValue"),
        (f"{span}.a", "arrayValue"),
        (f"{span}.a.arrayValue[0]", "intValue"),
        (f"{span}.k", "kvlistValue"),
        (f"{span}.k.kvlistValue.t", "boolValue"),
        (f"{span}.events[0].e", "stringValue"),
        (f"{span}.links[0].l", "intValue"),
    ]


def _wire_ids(request: Any) -> list[tuple[str, bytes, int]]:
    """Every id a request carries on the wire, by path, with the length in
    bytes the schema gives it: each span's `traceId`, `spanId` and
    `parentSpanId`, and each of its links' `traceId` and `spanId`. An unset
    one is there too, as the empty bytes proto3 reads it as."""
    ids: list[tuple[str, bytes, int]] = []
    for r, resource_entry in enumerate(request.resource_spans):
        for s, scope_entry in enumerate(resource_entry.scope_spans):
            for n, span in enumerate(scope_entry.spans):
                at = f"resourceSpans[{r}].scopeSpans[{s}].spans[{n}]"
                ids.append((f"{at}.traceId", span.trace_id, 16))
                ids.append((f"{at}.spanId", span.span_id, 8))
                ids.append((f"{at}.parentSpanId", span.parent_span_id, 8))
                for k, link in enumerate(span.links):
                    ids.append((f"{at}.links[{k}].traceId", link.trace_id, 16))
                    ids.append((f"{at}.links[{k}].spanId", link.span_id, 8))
    return ids


def test_the_wire_id_census_reads_every_span_s_ids_and_every_link_s():
    """The guard below reads ids on the wire only as widely as this walk: an
    id planted in each place one can sit is found there, with its length,
    and nowhere else -- a link's two as well as a span's three, each link of
    a span and each span, scope and resource, not the first only."""
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    root = trace_pb2.Span(trace_id=bytes([1] * 16), span_id=bytes([2] * 8))
    child = trace_pb2.Span(
        trace_id=bytes([3] * 16),
        span_id=bytes([4] * 8),
        parent_span_id=bytes([2] * 8),
        links=[
            trace_pb2.Span.Link(trace_id=bytes([5] * 16), span_id=bytes([6] * 8)),
            trace_pb2.Span.Link(trace_id=bytes([7] * 4), span_id=bytes(8)),
        ],
    )
    other = trace_pb2.Span(trace_id=bytes([8] * 16), span_id=bytes([9] * 8))
    request = pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                scope_spans=[trace_pb2.ScopeSpans(spans=[root, child])]
            ),
            trace_pb2.ResourceSpans(
                scope_spans=[
                    trace_pb2.ScopeSpans(),
                    trace_pb2.ScopeSpans(spans=[other]),
                ]
            ),
        ]
    )
    first = "resourceSpans[0].scopeSpans[0].spans[0]"
    second = "resourceSpans[0].scopeSpans[0].spans[1]"
    third = "resourceSpans[1].scopeSpans[1].spans[0]"
    assert _wire_ids(request) == [
        (f"{first}.traceId", bytes([1] * 16), 16),
        (f"{first}.spanId", bytes([2] * 8), 8),
        (f"{first}.parentSpanId", b"", 8),
        (f"{second}.traceId", bytes([3] * 16), 16),
        (f"{second}.spanId", bytes([4] * 8), 8),
        (f"{second}.parentSpanId", bytes([2] * 8), 8),
        (f"{second}.links[0].traceId", bytes([5] * 16), 16),
        (f"{second}.links[0].spanId", bytes([6] * 8), 8),
        (f"{second}.links[1].traceId", bytes([7] * 4), 16),
        (f"{second}.links[1].spanId", bytes(8), 8),
        (f"{third}.traceId", bytes([8] * 16), 16),
        (f"{third}.spanId", bytes([9] * 8), 8),
        (f"{third}.parentSpanId", b"", 8),
    ]


def test_the_zoo_holds_none_of_what_the_hand_made_requests_hold():
    """The day a pair carries one, this fails, and that row of `SPEC.md` §7's
    table becomes the pairs' to check. Every AnyValue is read: the resource's,
    the scope's, the span's, each event's and each link's attributes, and the
    values nested in an `arrayValue` or a `kvlistValue` (the walk's own test
    above). Every id on the wire is read too, each span's and each of its
    links' (that walk's own test above): no JSON body has a link, but the
    wire is what the rendering reads."""
    kinds: set[str] = set()
    for run, json_body, raw_body in PAIRS:
        document = json.loads(json_body.read_bytes())
        # Every span is looked at, not a subset: as many as the reader reads.
        records = spanweave.read_records(json_body.read_bytes()).records
        assert len(_spans(document)) == len(records), run
        for span in _spans(document):
            assert "links" not in span, run
            assert {"kind", "status", "flags"} <= set(span), run
        kinds.update(kind for _, kind in _any_value_kinds(document))
        request = _pb2().ExportTraceServiceRequest.FromString(raw_body.read_bytes())
        for resource_entry in request.resource_spans:
            for scope_entry in resource_entry.scope_spans:
                for span in scope_entry.spans:
                    # A `status` stated in the JSON was a message on the wire.
                    assert span.HasField("status"), run
        # No id on the wire, a span's or a link's, is all zero bytes, nor of
        # a length the schema does not give it: an unset one is empty, and
        # neither the Collector's omission nor an id carried as stated at
        # another length is ever shown.
        for path, value, length in _wire_ids(request):
            if value:
                assert len(value) == length and any(value), (
                    f"{run}: {path} is {value.hex()!r} on the wire"
                )
    assert kinds == {"stringValue", "intValue", "boolValue"}


@pytest.mark.parametrize(
    "order", [(99, 100), (100, 99)], ids=["ascending", "descending"]
)
def test_distinct_unknown_fields_are_reported_in_the_order_they_arrived(order):
    """Not in field-number order, and not reversed: both orders, so neither a
    sort nor a reversal can pass."""
    pb2 = _pb2()
    from opentelemetry.proto.trace.v1 import trace_pb2

    span = trace_pb2.Span(trace_id=bytes(16), span_id=bytes(8), name="s")
    # Field n, wire type 0, value 1: a two-byte tag for 16 <= n < 2048.
    tail = b"".join(bytes([((n << 3) & 0x7F) | 0x80, n >> 4, 0x01]) for n in order)
    raw = _request(pb2, span).SerializeToString()
    target = pb2.ExportTraceServiceRequest.FromString(raw)
    message = target.resource_spans[0].scope_spans[0].spans[0]
    message.ParseFromString(message.SerializeToString() + tail)
    read = spanweave.read_protobuf(target.SerializeToString())
    (diagnostic,) = read.diagnostics
    assert diagnostic.source == {
        "path": "resourceSpans[0].scopeSpans[0].spans[0]",
        "fields": [_undefined(n) for n in order],
    }


def test_two_resources_and_two_scopes_unpack_in_document_order():
    pb2 = _pb2()
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.resource.v1 import resource_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    def span(name: str, n: int) -> Any:
        return trace_pb2.Span(
            trace_id=bytes([0xAB] * 16), span_id=bytes([n] * 8), name=name, kind=2
        )

    def resource(name: str) -> Any:
        return resource_pb2.Resource(
            attributes=[
                common_pb2.KeyValue(
                    key="service.name", value=common_pb2.AnyValue(string_value=name)
                )
            ]
        )

    request = pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                resource=resource(r),
                scope_spans=[
                    trace_pb2.ScopeSpans(
                        scope=common_pb2.InstrumentationScope(name=f"{r}.{s}"),
                        spans=[span(f"{r}.{s}.{x}", 1 + i) for i, x in enumerate("ab")],
                    )
                    for s in ("s0", "s1")
                ],
            )
            for r in ("r0", "r1")
        ]
    )
    read = spanweave.read_protobuf(request.SerializeToString())
    assert not read.diagnostics
    names = [record["name"] for record in read.records]
    assert names == [
        f"{r}.{s}.{x}" for r in ("r0", "r1") for s in ("s0", "s1") for x in "ab"
    ]
    for record in read.records:
        r, s, _ = record["name"].split(".")
        envelope = spanweave.envelope(record)
        assert envelope.scope["scope"] == {"name": f"{r}.{s}"}
        assert envelope.resource["resource"]["attributes"][0]["value"] == {
            "stringValue": r
        }
        # The Collector's encodings (`SPEC.md` §7): ids as lowercase hex, the
        # times as decimal strings, `kind` as its number.
        assert record["trace_id"] == "ab" * 16
        assert record["kind"] == 2
        assert "start_time" not in record  # proto3's default is omitted


# --- Without the extra --------------------------------------------------------


def test_without_the_extra_it_raises_a_code_that_names_the_extra(monkeypatch):
    for name in ("google.protobuf", "opentelemetry", "opentelemetry.proto"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(spanweave.SpanweaveError) as raised:
        spanweave.read_protobuf(b"")
    assert raised.value.code == "otlp_extra_not_installed"
    assert "spanweave[otlp]" in str(raised.value)


def _hide_the_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every package on the way to the module reads as not installed."""
    for name in (
        "opentelemetry",
        "opentelemetry.proto",
        "opentelemetry.proto.collector",
        "opentelemetry.proto.collector.trace",
        "opentelemetry.proto.collector.trace.v1",
        "opentelemetry.proto.collector.trace.v1.trace_service_pb2",
    ):
        monkeypatch.setitem(sys.modules, name, None)


def _a_partial_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """The packages down to `...trace.v1` import; the module itself does not.

    Each is a package with nothing in it (an empty `__path__`), so the module
    is found nowhere (scoped review of 2026-10-18, R-12).
    """
    parts = ["opentelemetry", "proto", "collector", "trace", "v1"]
    for depth in range(1, len(parts) + 1):
        package = ModuleType(".".join(parts[:depth]))
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.delitem(
        sys.modules,
        "opentelemetry.proto.collector.trace.v1.trace_service_pb2",
        raising=False,
    )


#: The two ways the runtime is missing that `_pb2` answers alike: none of it
#: installed, and all of it but the module.
MISSING = {"absent": _hide_the_runtime, "partial": _a_partial_install}


@pytest.mark.parametrize("missing", list(MISSING.values()), ids=list(MISSING))
def test_where_the_runtime_is_required_a_missing_one_is_a_failure(monkeypatch, missing):
    """What CI's `check` and `otlp` jobs rely on: `_pb2` raises, never skips."""
    missing(monkeypatch)
    monkeypatch.setenv(REQUIRE, "1")
    with pytest.raises(ModuleNotFoundError):
        # A skip is not an exception `pytest.raises` catches: uncaught, it
        # would skip this test, the very outcome it is here to forbid.
        try:
            _pb2()
        except pytest.skip.Exception as skipped:
            pytest.fail(f"skipped where the runtime is required: {skipped}")


@pytest.mark.parametrize("missing", list(MISSING.values()), ids=list(MISSING))
def test_where_it_is_not_a_missing_runtime_is_a_skip_naming_the_extra(
    monkeypatch, missing
):
    missing(monkeypatch)
    monkeypatch.delenv(REQUIRE, raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        _pb2()
    assert str(skipped.value) == NO_EXTRA
    # The extra by its name, not only by the constant, which is equal to itself
    # whatever it says (scoped review of 2026-10-18, R-12).
    assert "spanweave[otlp]" in str(skipped.value)


#: What `_as_bytes` refuses: a path-like `str`, any other type, a memoryview of
#: items wider than a byte, and a strided one.
REFUSED = {
    "str": "trace.bin",
    "int": 4,
    "list": [1, 2],
    "wide-memoryview": memoryview(bytes(8)).cast("I"),
    "strided-memoryview": memoryview(bytes(8))[::2],
}


@pytest.mark.parametrize("data", list(REFUSED.values()), ids=list(REFUSED))
def test_it_refuses_what_read_records_refuses_by_the_same_error(data):
    """Needs no extra: the refusal comes before the runtime is imported."""
    with pytest.raises(TypeError) as by_records:
        spanweave.read_records(data)
    with pytest.raises(TypeError) as by_protobuf:
        spanweave.read_protobuf(data)
    # The reader's name leads the message; the rest is the same words.
    assert str(by_protobuf.value) == str(by_records.value).replace(
        "read_records", "read_protobuf", 1
    )
    assert str(by_protobuf.value).startswith("read_protobuf reads ")


def test_importing_spanweave_imports_no_proto_package():
    """The extra is optional because nothing loads it until it is used."""
    probe = (
        "import sys, spanweave; "
        "print(sorted(m for m in sys.modules "
        "if m.split('.')[0] in ('google', 'opentelemetry')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    assert result.stdout.strip() == "[]"
