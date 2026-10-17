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
`null`; a message carrying fields the schema does not define is read, and
reported as `unknown_fields`; a `doubleValue` is a float, which no pair checks.

The tests that need the proto runtime skip without the `otlp` extra, saying
so; CI's `otlp` job installs it and sets `SPANWEAVE_REQUIRE_OTLP`, under which
a missing runtime is a failure rather than a skip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

import spanweave
from spanweave.api import graph_from_records
from spanweave.diagnostics import DiagnosticCollector
from tests import zoo_census
from tests.zoo_census import CAPTURES, ROOT

PAIRS = [
    (capture.run, json_body, raw_body)
    for capture in CAPTURES
    for json_body, raw_body in zoo_census.pairs(capture)
]
PAIR_IDS = [f"{run}/{json_body.stem}" for run, json_body, _ in PAIRS]

#: What CI's `otlp` job sets: there, a proto runtime that will not import is a
#: broken job, not a reason to skip.
REQUIRE = "SPANWEAVE_REQUIRE_OTLP"


def _pb2() -> ModuleType:
    """The `ExportTraceServiceRequest` module, or a skip naming the extra."""
    name = "opentelemetry.proto.collector.trace.v1.trace_service_pb2"
    if os.environ.get(REQUIRE):
        __import__(name)
        return sys.modules[name]
    return pytest.importorskip(
        name, reason="the `otlp` extra is not installed: pip install spanweave[otlp]"
    )


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
        "fields": [{"number": 99, "wire_type": 0}],
    }

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
        {"path": "", "fields": [{"number": 100, "wire_type": 0}]},
        {
            "path": "resourceSpans[0]",
            "fields": [
                {"number": 99, "wire_type": 0},
                {"number": 99, "wire_type": 0},
            ],
        },
    ]


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
    twin = spanweave.read_records(json.dumps(_rendered(request)).encode())
    assert spanweave.read_protobuf(request.SerializeToString()) == twin


#: `bytesValue` is proto3 JSON's `bytes`: standard base64, padded. The bytes
#: are chosen so base64 and hex differ and the alphabet's `+` and `/` appear.
BYTES = bytes([0x00, 0xFB, 0xFF, 0x10])


def test_bytes_array_and_kvlist_values_render_as_the_otlp_json_spec_writes_them():
    """Spec, not pair: the zoo's AnyValues are `stringValue`, `intValue` and
    `boolValue` only (the guard below)."""
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
        {"key": "bytes", "value": {"bytesValue": "APv/EA=="}},
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
                        {"key": "b", "value": {"bytesValue": "APv/EA=="}},
                    ]
                }
            },
        },
    ]
    twin = spanweave.read_records(json.dumps(_rendered(request)).encode())
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

    span = trace_pb2.Span(
        trace_id=bytes(16), span_id=bytes(8), name="s", kind=0, flags=0
    )
    assert not span.HasField("status")
    request = _request(pb2, span)
    (rendered,) = _spans(_rendered(request))
    assert rendered == {"traceId": "00" * 16, "spanId": "00" * 8, "name": "s"}

    (record,) = spanweave.read_protobuf(request.SerializeToString()).records
    assert not {"kind", "status", "flags"} & set(record)


def test_the_zoo_holds_none_of_what_the_hand_made_requests_hold():
    """The day a pair carries one, this fails, and that row of `SPEC.md` §7's
    table becomes the pairs' to check."""
    kinds: set[str] = set()
    for run, json_body, raw_body in PAIRS:
        document = json.loads(json_body.read_bytes())
        # Every span is looked at, not a subset: as many as the reader reads.
        records = spanweave.read_records(json_body.read_bytes()).records
        assert len(_spans(document)) == len(records), run
        for span in _spans(document):
            assert "links" not in span, run
            assert {"kind", "status", "flags"} <= set(span), run
            for attribute in span.get("attributes", []):
                kinds.update(attribute["value"])
        request = _pb2().ExportTraceServiceRequest.FromString(raw_body.read_bytes())
        for resource_entry in request.resource_spans:
            for scope_entry in resource_entry.scope_spans:
                for span in scope_entry.spans:
                    # A `status` stated in the JSON was a message on the wire.
                    assert span.HasField("status"), run
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
        "fields": [{"number": n, "wire_type": 0} for n in order],
    }


def test_two_resources_and_two_scopes_unpack_in_document_order():
    pb2 = _pb2()
    from opentelemetry.proto.common.v1 import common_pb2
    from opentelemetry.proto.resource.v1 import resource_pb2
    from opentelemetry.proto.trace.v1 import trace_pb2

    def span(name: str, n: int) -> Any:
        return trace_pb2.Span(
            trace_id=bytes(16), span_id=bytes([n] * 8), name=name, kind=2
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
        assert record["trace_id"] == "00" * 16
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
