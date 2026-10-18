"""Determinism + losslessness gates (TASKS.md 0.6), each watched failing.

The four properties live in `tests/determinism.py`. Here they are pointed at
deliberately broken fakes, so that every one is seen failing for the reason it
exists.

**Not yet pointed at the real pipeline.** There is none at Phase 0 — no
reader, no builder, no serializer. Task 1.8 wires these same four checks to
`spanweave build` over the worked example, unchanged. Writing them first is
deliberate: a determinism property invented *after* the code it judges tends
to describe the code.
"""

import itertools
import json

import pytest

from tests import determinism

RECORDS = [
    {"span_id": "s0", "name": "agent.run"},
    {"span_id": "s1", "name": "llm.plan"},
    {"span_id": "s2", "name": "tool.lookup"},
]


def _graph_of(records):
    """A minimal well-behaved graph: every record kept, verbatim, sorted."""
    nodes = [{"id": r["span_id"], "raw": {"source": r}} for r in records]
    return {"nodes": sorted(nodes, key=lambda n: n["id"]), "diagnostics": []}


def _canonical_dumps(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# 1. Build twice -> byte-identical
# --------------------------------------------------------------------------


def test_repeatable_holds_for_a_pure_build():
    determinism.assert_repeatable(lambda: _canonical_dumps(_graph_of(RECORDS)))


def test_repeatable_fails_when_a_counter_leaks_into_the_output():
    counter = itertools.count()

    def build():
        return _canonical_dumps({"build": next(counter)})

    with pytest.raises(determinism.PropertyFailed, match="differs from build #1"):
        determinism.assert_repeatable(build)


# --------------------------------------------------------------------------
# 2. Shuffle the input -> byte-identical graph
# --------------------------------------------------------------------------


def test_order_independence_holds_when_the_builder_sorts():
    determinism.assert_order_independent(RECORDS, _graph_of)


def test_order_independence_fails_when_the_builder_trusts_file_order():
    def build(records):
        # The classic bug: nodes emitted in arrival order.
        return {"nodes": [{"id": r["span_id"]} for r in records], "diagnostics": []}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


def test_order_independence_fails_when_dict_insertion_order_decides_it():
    def build(records):
        # The subtler bug, and the one this project is most exposed to: a
        # group-by whose output is emitted in dict insertion order. Sorted
        # *within* each group, arbitrary *between* them.
        groups: dict[str, list[str]] = {}
        for record in records:
            groups.setdefault(record["name"].split(".")[0], []).append(
                record["span_id"]
            )
        return {"nodes": [{"group": g, "ids": sorted(i)} for g, i in groups.items()]}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


# --------------------------------------------------------------------------
# 3. Every input record accounted for
# --------------------------------------------------------------------------


def test_losslessness_holds_when_every_record_is_a_node():
    determinism.assert_every_record_accounted_for(RECORDS, _graph_of(RECORDS))


def test_losslessness_holds_when_a_diagnostic_explains_the_gap():
    graph = {
        "nodes": [],
        "diagnostics": [{"code": "unknown_span_kind", "source": r} for r in RECORDS],
    }
    determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_on_a_silently_dropped_record():
    graph = _graph_of(RECORDS[:-1])
    with pytest.raises(determinism.PropertyFailed, match="silently dropped"):
        determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_when_a_record_is_prettified_on_the_way_in():
    # Losslessness is verbatim-ness, not merely presence: a node whose raw
    # source has been normalized has lost the thing raw exists to keep.
    tidied = [{"span_id": r["span_id"], "name": r["name"].title()} for r in RECORDS]
    with pytest.raises(determinism.PropertyFailed):
        determinism.assert_every_record_accounted_for(RECORDS, _graph_of(tidied))


# --------------------------------------------------------------------------
# 4. The writer is canonical
# --------------------------------------------------------------------------


def test_canonical_writer_passes():
    determinism.assert_canonical_json(_canonical_dumps)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"sort_keys": False}, "not sorted"),
        ({"sort_keys": True, "separators": (", ", ": ")}, "not compact"),
        ({"sort_keys": True, "ensure_ascii": True}, "escaped"),
    ],
)
def test_canonical_writer_fails_on_a_planted_violation(kwargs, expected):
    settings = {"ensure_ascii": False, "separators": (",", ":"), **kwargs}

    def dumps(value):
        return (json.dumps(value, **settings) + "\n").encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match=expected):
        determinism.assert_canonical_json(dumps)


def test_canonical_writer_fails_without_a_trailing_newline():
    def dumps(value):
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match="trailing newline"):
        determinism.assert_canonical_json(dumps)


# --------------------------------------------------------------------------
# The same four properties, now pointed at the real pipeline (TASKS.md 1.8)
# --------------------------------------------------------------------------
#
# This is the half 0.6 could not do: at Phase 0 there was no reader, builder
# or serializer to judge. The checks below are the ones above, unchanged.

import pathlib  # noqa: E402

import spanweave  # noqa: E402
from spanweave.serialize import canonical_bytes  # noqa: E402

WORKED_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
)
WORKED_RECORDS = [
    json.loads(line)
    for line in WORKED_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def _bytes_of(records):
    return b"".join(json.dumps(record).encode("utf-8") + b"\n" for record in records)


def _document_of(records):
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    # source_digest fingerprints the INPUT BYTES, not the graph (SPEC.md
    # §3.9). Shuffling the input changes the bytes by definition; that it
    # changes nothing else is exactly what is being tested here, and the
    # digest's own behavior is asserted separately below.
    document["meta"].pop("source_digest")
    return document


def test_building_the_worked_example_twice_is_byte_identical():
    determinism.assert_repeatable(
        lambda: spanweave.dumps(spanweave.build(WORKED_EXAMPLE))
    )


def test_shuffling_the_worked_example_changes_nothing():
    determinism.assert_order_independent(WORKED_RECORDS, _document_of)


def test_shuffling_produces_identical_bytes_too():
    ordered = canonical_bytes(_document_of(WORKED_RECORDS))
    reversed_input = canonical_bytes(_document_of(list(reversed(WORKED_RECORDS))))
    assert ordered == reversed_input


def test_the_digest_does_change_when_the_bytes_do():
    # Proof that popping it above hides nothing: it is a real fingerprint of
    # a real difference, and it is the only thing that differs.
    forwards = spanweave.build(_bytes_of(WORKED_RECORDS))
    backwards = spanweave.build(_bytes_of(list(reversed(WORKED_RECORDS))))
    assert forwards.meta.source_digest != backwards.meta.source_digest


def test_every_record_of_the_worked_example_is_accounted_for():
    document = spanweave.to_document(spanweave.build(WORKED_EXAMPLE))
    determinism.assert_every_record_accounted_for(WORKED_RECORDS, document)


def test_a_record_the_library_cannot_map_is_still_accounted_for():
    # Losslessness under duress: an unmappable record and a malformed line.
    records = [*WORKED_RECORDS, {"span_id": "s9", "attributes": {"nonsense": 1}}]
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    determinism.assert_every_record_accounted_for(records, document)


def test_the_shipped_writer_is_canonical():
    determinism.assert_canonical_json(canonical_bytes)


def test_the_graph_file_is_one_line_and_ends_in_a_newline():
    written = spanweave.dumps(spanweave.build(WORKED_EXAMPLE))
    assert written.endswith(b"\n")
    assert written.count(b"\n") == 1


# --------------------------------------------------------------------------
# The same properties over records the dialect gives NO span id (batch A5)
# --------------------------------------------------------------------------
#
# Everything above runs on `WORKED_RECORDS`, and every one of those -- like all
# 177 records the corpus held at the time -- carries a span id, so a node id is
# a string the dialect supplied and file order cannot reach it. The one path
# where file order CAN reach an id is the derived one (`SPEC.md` §3.6 rule 2),
# and it was unwatched: the fallback key was the record's 1-based index, so a
# file of span-id-less records rebound its ids when its lines were swapped.
#
# Byte-identity alone does not catch that. Ids are assigned in node order, so
# the two documents matched byte for byte while each id named a different
# record in each -- which is why the binding is asserted separately below.

DERIVED_ID_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/derived_ids/dialects/openinference.jsonl"
)
DERIVED_ID_RECORDS = [
    json.loads(line)
    for line in DERIVED_ID_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_the_span_id_less_records_really_carry_no_span_id():
    # Otherwise everything below is a second run of the tests above.
    assert DERIVED_ID_RECORDS
    assert not any("span_id" in record for record in DERIVED_ID_RECORDS)


def test_shuffling_span_id_less_records_changes_nothing():
    determinism.assert_order_independent(DERIVED_ID_RECORDS, _document_of)


def test_shuffling_span_id_less_records_does_not_rebind_their_ids():
    def binding(records):
        graph = spanweave.build(_bytes_of(records))
        return {node.id: node.raw.source["name"] for node in graph.nodes()}

    forwards = binding(DERIVED_ID_RECORDS)
    assert all(node_id.startswith("sw_") for node_id in forwards)
    assert forwards == binding(list(reversed(DERIVED_ID_RECORDS)))


def test_every_span_id_less_record_is_accounted_for():
    document = spanweave.to_document(spanweave.build(DERIVED_ID_EXAMPLE))
    determinism.assert_every_record_accounted_for(DERIVED_ID_RECORDS, document)


# --------------------------------------------------------------------------
# The same properties over a trace TWO adapters read (batch E3)
# --------------------------------------------------------------------------
#
# Everything above runs on a file one adapter reads whole. Under per-record
# dispatch the records are partitioned before they are parsed, and a partition
# is built by walking the input -- which is a second place file order could
# reach the result, and the only one the shuffle checks above cannot see.

MIXED_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/mixed_instrumentation/dialects"
    / "openinference+otel_genai.jsonl"
)
MIXED_RECORDS = [
    json.loads(line)
    for line in MIXED_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_the_mixed_records_really_come_from_two_dialects():
    # Otherwise everything below is a third run of the tests above.
    from spanweave.adapters import classify

    assert sorted({classify(record) for record in MIXED_RECORDS}) == [
        ("openinference",),
        ("otel_genai",),
    ]


def test_shuffling_a_mixed_trace_changes_nothing():
    determinism.assert_order_independent(MIXED_RECORDS, _document_of)


def test_shuffling_a_mixed_trace_does_not_rebind_its_ids():
    # A5's lesson, applied to the new mechanism: byte-identity alone would not
    # catch a rebinding, because ids are assigned in node order.
    def binding(records):
        graph = spanweave.build(_bytes_of(records))
        return {
            node.id: (node.raw.source["name"], node.provenance.adapter_id)
            for node in graph.nodes()
        }

    forwards = binding(MIXED_RECORDS)
    assert len(forwards) == 4
    assert forwards == binding(list(reversed(MIXED_RECORDS)))


def test_every_record_of_a_mixed_trace_is_accounted_for():
    document = spanweave.to_document(spanweave.build(MIXED_EXAMPLE))
    determinism.assert_every_record_accounted_for(MIXED_RECORDS, document)


def test_a_record_no_adapter_claims_is_accounted_for_too():
    # Losslessness where it is least automatic: nobody parsed this record, so
    # nothing but the dispatcher could have kept it (`SPEC.md` §6.1).
    records = [*MIXED_RECORDS, {"span_id": "s9", "attributes": {"nonsense": 1}}]
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    determinism.assert_every_record_accounted_for(records, document)
    determinism.assert_order_independent(records, _document_of)


# --------------------------------------------------------------------------
# Two lines that parse equal, and a payload's key order
# --------------------------------------------------------------------------
#
# Two lines that parse equal are one record, and the reader keeps the first
# (`SPEC.md` §7). Which line is first is file order, so that rule is only
# order-free if nothing the two lines spell differently reaches a node. A
# structured payload's text did: both adapters rendered it in the key order
# the line wrote, so swapping the lines swapped the payload's text (the
# scoped review of 2026-10-18, R-8). Its text is written with sorted keys
# (`SPEC.md` §3.3), and these pairs hold that the graph is the same either
# way round.

#: Per dialect, one span's record twice, differing only in the key order of
#: one structured payload -- `{"a": 2, "b": 1}` against `{"b": 1, "a": 2}`.
KEY_ORDER_TWINS = {
    "openinference": [
        {
            "trace_id": "t1",
            "span_id": "s1",
            "name": "op",
            "attributes": {"openinference.span.kind": "TOOL", "input.value": value},
        }
        for value in ({"a": 2, "b": 1}, {"b": 1, "a": 2})
    ],
    "otel_genai": [
        {
            "trace_id": "t1",
            "span_id": "s1",
            "name": "op",
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.input.messages": value,
            },
        }
        for value in ({"a": 2, "b": 1}, {"b": 1, "a": 2})
    ],
}


@pytest.mark.parametrize("dialect", sorted(KEY_ORDER_TWINS))
def test_two_lines_differing_only_in_a_payload_s_key_order_build_one_graph(dialect):
    first, second = KEY_ORDER_TWINS[dialect]
    # One record, as far as the reader is concerned -- and two lines, as far as
    # the bytes are.
    assert first == second
    assert _bytes_of([first, second]) != _bytes_of([second, first])

    forwards = spanweave.build(_bytes_of([first, second]))
    backwards = spanweave.build(_bytes_of([second, first]))
    for graph in (forwards, backwards):
        assert [d.code for d in graph.diagnostics].count("duplicate_record") == 1
        (node,) = graph.nodes()
        assert node.provenance.adapter_id == dialect

    # `dumps`, less `meta.source_digest`: the one field §5.2 exempts, because
    # it fingerprints the input bytes, which the swap changes by definition.
    # That it does change is asserted too, so the exclusion hides nothing.
    assert canonical_bytes(_document_of([first, second])) == canonical_bytes(
        _document_of([second, first])
    )
    assert forwards.meta.source_digest != backwards.meta.source_digest
    # The same graph, and it is the one with the keys sorted, whichever line
    # was kept.
    for graph in (forwards, backwards):
        (node,) = graph.nodes()
        assert node.inputs.raw == '{"a": 2, "b": 1}'


# --------------------------------------------------------------------------
# No key order reaches a graph (decisions log D38)
# --------------------------------------------------------------------------
#
# The pair above holds one site with one input. The class is wider: wherever
# an adapter turns a value a record states into text, the order the record
# wrote an object's keys in is in that text unless something sorts it -- and
# a span kind (`openinference.span.kind`) or operation
# (`gen_ai.operation.name`) stated as an object was such a site after the pair
# above was fixed. So the gate is a property over inputs, not a pair: every
# input the repository holds, and hand-made ones stating a structured value
# wherever an adapter reads a value, each re-fed with every object's members
# reordered at every depth (`tests/key_order.py`), once reversed and once by a
# fixed-seed shuffle. Each must build the graph the input as written builds.

from dataclasses import replace  # noqa: E402

from spanweave.errors import SpanweaveError  # noqa: E402
from tests import key_order  # noqa: E402
from tests.test_protobuf import PAIRS, _built, _pb2  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The shuffle's seed. Any constant: the reordering is arbitrary, the test is
#: not.
KEY_ORDER_SEED = 20261018

#: Each reordering, made fresh for each input, so every input is reordered
#: the same way whichever others run.
ORDERS = {
    "reversed": lambda: key_order.reversal,
    "shuffled": lambda: key_order.shuffle(KEY_ORDER_SEED),
}

#: A structured value: keys out of sorted order, an object inside an object,
#: objects inside arrays, an object inside an array inside an array, and two
#: keys that differ only by case, the lowercase written first. By code point,
#: as `sort_keys` sorts, `"Ab"` comes before `"ab"`; a sort that folded case
#: would keep whichever the input wrote first, so its two orders would read
#: as two texts (the scoped review of 2026-10-18b, R-4).
STRUCTURED = {
    "zeta": 1,
    "alpha": {"mu": [{"yy": 2, "xx": 1}], "beta": True},
    "eta": [3, {"q": None, "p": "s"}],
    "nu": [[{"kk": 2, "jj": 1}, 4]],
    "case": {"ab": 1, "Ab": 2},
}


def _lines(*records):
    return b"".join(json.dumps(record).encode("utf-8") + b"\n" for record in records)


def _openinference_everywhere():
    """One span stating the structured value at every key the adapter reads,
    the span kind among them."""
    value = STRUCTURED
    return {
        "trace_id": "t1",
        "span_id": "s1",
        "parent_id": value,
        "name": value,
        "start_time": value,
        "end_time": value,
        "status": value,
        "status_message": value,
        "links": [{"span_id": "s2", "trace_id": "t1", "attributes": value}, value],
        "attributes": {
            "openinference.span.kind": value,
            "input.value": value,
            "input.mime_type": value,
            "output.value": value,
            "output.mime_type": "application/json",
            "tool.name": value,
            "llm.model_name": value,
            "embedding.model_name": value,
            "tool_call.id": value,
            "llm.token_count.prompt": value,
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": value,
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": (
                value
            ),
            "llm.input_messages.0.message.role": value,
            "llm.input_messages.0.message.tool_call_id": value,
            "x.unmapped": value,
        },
        "x_unmapped": value,
    }


def _otel_genai_everywhere():
    """The same for OTel GenAI, the operation among them."""
    value = STRUCTURED
    return {
        "trace_id": "t1",
        "span_id": "g1",
        "parent_id": value,
        "name": value,
        "start_time": value,
        "end_time": value,
        "status": value,
        "status_message": value,
        "links": [{"span_id": "g2", "attributes": value}, value],
        "attributes": {
            "gen_ai.operation.name": value,
            "gen_ai.input.messages": value,
            "gen_ai.output.messages": value,
            "gen_ai.tool.call.arguments": value,
            "gen_ai.tool.call.result": value,
            "gen_ai.retrieval.query.text": value,
            "gen_ai.retrieval.documents": value,
            "gen_ai.tool.name": value,
            "gen_ai.tool.call.id": value,
            "gen_ai.request.model": value,
            "gen_ai.usage.input_tokens": value,
            "gen_ai.agent.name": value,
        },
        "x_unmapped": value,
    }


def _span(span_id, attributes, **fields):
    return {
        "trace_id": "t1",
        "span_id": span_id,
        "parent_id": "s1",
        "name": span_id,
        "start_time": 1700000001,
        "end_time": 1700000002,
        **fields,
        "attributes": attributes,
    }


def _any_value(value):
    """``value`` as OTLP/JSON writes an attribute's `AnyValue`."""
    if isinstance(value, dict):
        return {"kvlistValue": {"values": _key_values(value)}}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_any_value(item) for item in value]}}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, str):
        return {"stringValue": value}
    return {}


def _key_values(attributes):
    return [{"value": _any_value(v), "key": k} for k, v in attributes.items()]


def _otlp_export():
    """An OTLP/JSON export stating the structured value where each dialect
    reads one, as the `kvlistValue` it is on the wire -- a kind, an operation,
    payloads, a link's and an event's attributes -- beside a status, a resource
    and a scope, each an object of more than one member."""
    value = STRUCTURED
    times = {"startTimeUnixNano": "1700000000000000000"}
    spans = [
        {
            "traceId": "5b8efff798038103d269b633813fc60c",
            "spanId": "eee19b7ec3c1b174",
            "name": "oi",
            **times,
            "attributes": _key_values(
                {"openinference.span.kind": value, "input.value": value, "x.y": value}
            ),
            "status": {"message": "m", "code": "STATUS_CODE_ERROR"},
            "links": [
                {
                    "traceId": "5b8efff798038103d269b633813fc60c",
                    "spanId": "eee19b7ec3c1b175",
                    "attributes": _key_values({"x": value}),
                }
            ],
            "events": [
                {
                    "timeUnixNano": "1700000000500000000",
                    "name": "exception",
                    "attributes": _key_values(
                        {"exception.type": value, "exception.message": "boom"}
                    ),
                },
                {"timeUnixNano": "1700000000600000000", "name": "note"},
            ],
            "kind": 1,
            "droppedAttributesCount": 2,
        },
        {
            "traceId": "5b8efff798038103d269b633813fc60c",
            "spanId": "eee19b7ec3c1b175",
            "parentSpanId": "eee19b7ec3c1b174",
            "name": "ge",
            **times,
            "attributes": _key_values(
                {"gen_ai.operation.name": value, "gen_ai.input.messages": value}
            ),
        },
        {
            "traceId": "5b8efff798038103d269b633813fc60c",
            "spanId": "eee19b7ec3c1b176",
            "parentSpanId": "eee19b7ec3c1b174",
            "name": "retrieval",
            **times,
            "attributes": _key_values(
                {
                    "gen_ai.retrieval.query.text": value,
                    "gen_ai.operation.name": "retrieval",
                    "gen_ai.retrieval.documents": value,
                }
            ),
        },
    ]
    export = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {"spans": spans, "scope": {"version": "1", "name": "hand"}}
                ],
                "resource": {"attributes": _key_values({"service.name": value})},
            }
        ]
    }
    return json.dumps(export).encode("utf-8")


#: Inputs made by hand, one per dialect and one OTLP export, each stating a
#: structured value wherever an adapter reads a value: every payload key of
#: each dialect under a kind that maps, and the ones read under a kind that
#: does not; the span kind and the operation; and every other key either
#: adapter reads, the record's own fields among them. The span stating it
#: everywhere is in its file twice, so a reordering that writes the two copies
#: differently is a file holding one record twice in two key orders -- the
#: pair above, at every site.
HAND_MADE = {
    "openinference": _lines(
        _openinference_everywhere(),
        _span(
            "s2",
            {
                "openinference.span.kind": "LLM",
                "input.value": STRUCTURED,
                "output.value": STRUCTURED,
                "output.mime_type": "application/json",
                "llm.model_name": "m",
            },
            status={"message": "m", "code": "ERROR"},
        ),
        _span(
            "s3",
            {
                "openinference.span.kind": "TOOL",
                "input.value": [STRUCTURED, STRUCTURED],
                "output.value": STRUCTURED,
                "output.mime_type": "text/plain",
                "tool.name": "f",
            },
        ),
        _openinference_everywhere(),
    ),
    "otel_genai": _lines(
        _otel_genai_everywhere(),
        _span(
            "g2",
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.input.messages": [
                    {"role": "user", "parts": [{"type": "text", "content": "q"}]},
                    {
                        "role": "tool",
                        "parts": [
                            {
                                "type": "tool_call_response",
                                "id": "c0",
                                "response": STRUCTURED,
                            }
                        ],
                    },
                ],
                "gen_ai.output.messages": [
                    {
                        "role": "assistant",
                        "parts": [
                            {
                                "type": "tool_call",
                                "id": "c1",
                                "name": "f",
                                "arguments": STRUCTURED,
                            }
                        ],
                    }
                ],
                "gen_ai.request.model": "m",
            },
        ),
        _span(
            "g3",
            {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.call.arguments": STRUCTURED,
                "gen_ai.tool.call.result": STRUCTURED,
                "gen_ai.tool.name": "f",
                "gen_ai.tool.call.id": "c1",
            },
        ),
        _span(
            "g4",
            {
                "gen_ai.operation.name": "retrieval",
                "gen_ai.retrieval.query.text": STRUCTURED,
                "gen_ai.retrieval.documents": STRUCTURED,
            },
        ),
        _otel_genai_everywhere(),
    ),
    "otlp_export": _otlp_export(),
}

#: Every trace file the repository holds -- every conformance rendering, the
#: captured traces, and the zoo's JSON bodies, found as the oracle finds them
#: -- and the hand-made inputs, as (id, path or bytes).
KEY_ORDER_TEXTS = [
    *(
        (f"conformance/{path.parent.parent.name}/{path.name}", path)
        for path in sorted(ROOT.glob("fixtures/conformance/*/dialects/*"))
    ),
    *(
        (f"captured/{path.name}", path)
        for path in sorted(ROOT.glob("fixtures/captured/*.jsonl"))
    ),
    *((f"zoo/{run}/{json_body.name}", json_body) for run, json_body, _ in PAIRS),
    *((f"hand-made/{name}", data) for name, data in HAND_MADE.items()),
]


def _protobuf_read(raw_body):
    _pb2()
    return spanweave.read_protobuf(raw_body.read_bytes())


#: The records `read_protobuf` reads out of the zoo's raw bodies, and the
#: records the hand-made inputs read as, as (id, a function reading them).
KEY_ORDER_RECORDS = [
    *(
        (f"zoo/{run}/{raw_body.name}", lambda body=raw_body: _protobuf_read(body))
        for run, _, raw_body in PAIRS
    ),
    *(
        (f"hand-made/{name}", lambda data=data: spanweave.read_records(data))
        for name, data in HAND_MADE.items()
    ),
]


def _bytes(source):
    return source.read_bytes() if isinstance(source, pathlib.Path) else source


def _outcome(data):
    """What ``data`` builds: its document less `meta.source_digest`, as the
    writer writes it, and that digest -- or, where it is refused, the refusal."""
    try:
        graph = spanweave.build(data)
    except SpanweaveError as refusal:
        return (type(refusal).__name__, refusal.code, str(refusal)), None
    document = spanweave.to_document(graph)
    digest = document["meta"].pop("source_digest")
    return canonical_bytes(document), digest


def _differences(written, again, path="", found=None):
    """Where two parsed documents differ, as `path: one | other`, at most six."""
    found = [] if found is None else found
    if len(found) >= 6:
        return found
    if isinstance(written, dict) and isinstance(again, dict):
        for key in sorted(set(written) | set(again)):
            _differences(written.get(key), again.get(key), f"{path}/{key}", found)
    elif isinstance(written, list) and isinstance(again, list):
        if len(written) != len(again):
            found.append(f"{path}: {len(written)} items | {len(again)} items")
        for index, pair in enumerate(zip(written, again, strict=False)):
            _differences(*pair, f"{path}/{index}", found)
    elif written != again:
        found.append(f"{path}: {written!r} | {again!r}")
    return found


def _parsed(text):
    # `parse_int=str`: whatever the digit limit this process runs under.
    return json.loads(text, parse_int=str)


@pytest.mark.parametrize("order", sorted(ORDERS))
@pytest.mark.parametrize(
    ("name", "source"), KEY_ORDER_TEXTS, ids=[name for name, _ in KEY_ORDER_TEXTS]
)
def test_no_key_order_reaches_a_graph(name, source, order):
    """Decisions log D38, on the text path: every input, every object's
    members reordered at every depth, builds the graph the input as written
    builds, or the same refusal.

    `dumps` less `meta.source_digest`, the one field §5.2 exempts: it
    fingerprints the input **bytes** (`SPEC.md` §3.9), which a reordering
    changes by definition. That it does change is asserted wherever the bytes
    did, so the exclusion hides nothing; every other byte is compared.

    The permuter feeds unchanged, and names, what it cannot reorder
    (`tests/key_order.py` says why): a line the library's parser refuses, and
    a line that is not UTF-8. The reader does read the second, so its objects
    would reach the build in their written order and the case would hold
    nothing of them; each case asserts it was named none, so the inputs hold
    no such line (the scoped review of 2026-10-18b, R-6). And an input with
    any object of two or more members is asserted to have changed, so no input
    passes by being left as it was; how far down it changed is held by
    `test_the_key_order_gate_reorders_objects_at_every_depth`."""
    data = _bytes(source)
    tally = key_order.Tally()
    reordered, unread = key_order.input_reordered(data, ORDERS[order](), tally)
    assert unread == [], f"{name}: fed unchanged, {unread}"
    if tally.permuted:
        assert reordered != data, name
    written, digest = _outcome(data)
    again, digest_again = _outcome(reordered)
    if isinstance(written, bytes) and isinstance(again, bytes) and written != again:
        pytest.fail(
            f"{name}, members {order}: the graph changed --\n  "
            + "\n  ".join(_differences(_parsed(written), _parsed(again)))
        )
    assert again == written, name
    if digest is not None and reordered != data:
        assert digest_again != digest, name


@pytest.mark.parametrize("order", sorted(ORDERS))
@pytest.mark.parametrize(
    ("name", "read"), KEY_ORDER_RECORDS, ids=[name for name, _ in KEY_ORDER_RECORDS]
)
def test_no_key_order_reaches_a_graph_built_from_records(name, read, order):
    """Decisions log D38, on the records path: the records `read_protobuf`
    reads -- which have no text of their own to reorder -- and the hand-made
    inputs' records, every object's keys reordered at every depth, each
    container's type kept, build the bytes the records as read build, through
    the build the oracle uses (`tests/test_protobuf.py`'s `_built`). A record
    read from an export is folded, so here a structured attribute is an object
    whose keys are reordered, where in the text it is a list that is not.
    Built from records, a graph has no digest, so nothing is exempt."""
    records = read()
    tally = key_order.Tally()
    reorder = ORDERS[order]()
    reordered = tuple(
        key_order.records_reordered(record, reorder, tally)
        for record in records.records
    )
    assert reordered == records.records, name
    assert [type(record) for record in reordered] == [
        type(record) for record in records.records
    ]
    if tally.permuted:
        assert [json.dumps(record) for record in reordered] != [
            json.dumps(record) for record in records.records
        ], name
    written = _built(records)
    again = _built(replace(records, records=reordered))
    if written != again:
        pytest.fail(
            f"{name}, keys {order}: the graph changed --\n  "
            + "\n  ".join(_differences(_parsed(written), _parsed(again)))
        )


# How far down the gate reordered, measured on what it made: each input as
# written and as reordered, walked in step, not the tally `tests/key_order.py`
# keeps about itself, which a reordering that stopped short could still fill
# in. Its floor is each input's own deepest object, not a depth fixed for all
# (the scoped review of 2026-10-18b, R-5).


class _Members(tuple):
    """An object as `json.loads` read it: its ``(key, value)`` pairs in the
    order the text writes them, a key stated twice kept twice."""


def _values_written(data):
    """The JSON values an input's text holds, each object a `_Members`: the
    input as one document, or failing that one per line that holds one. Read
    here rather than by the permuter's own split, and strictly: the gate
    asserts no input holds a line that is not UTF-8."""
    text = data.decode("utf-8").removeprefix("\ufeff")
    options = {"object_pairs_hook": _Members, "parse_int": str}
    try:
        return [json.loads(text, **options)]
    except ValueError:
        return [
            json.loads(line, **options) for line in text.split("\n") if line.strip()
        ]


def _member_orders(written, again, depth=1, in_array=False, found=None):
    """``(movable, moved)``: where ``written`` holds an object a reordering
    can move -- two or more members, no key stated twice -- and where
    ``again``, the same value with its objects' members reordered, lists an
    object's members in another order. Each a set of ``(depth, in_array)``,
    a top-level value at depth 1 and each object or array one deeper than
    its container; ``in_array`` is whether that container is an array. An
    object is a dict (a record) or a `_Members` (a text read here)."""
    movable, moved = (set(), set()) if found is None else found
    if isinstance(written, list):
        assert isinstance(again, list) and len(again) == len(written)
        for item, item_again in zip(written, again, strict=True):
            _member_orders(item, item_again, depth + 1, True, (movable, moved))
        return movable, moved
    if not isinstance(written, dict | _Members):
        return movable, moved
    assert isinstance(again, dict | _Members)
    pairs = list(written.items() if isinstance(written, dict) else written)
    pairs_again = list(again.items() if isinstance(again, dict) else again)
    keys = [key for key, _ in pairs]
    keys_again = [key for key, _ in pairs_again]
    assert sorted(keys_again) == sorted(keys), f"members lost at depth {depth}"
    if keys_again != keys:
        moved.add((depth, in_array))
    if len(set(keys)) < len(keys):
        # Its copies have no key of their own to pair them by. Left as
        # written, each is the one at the same position; moved, which is
        # already recorded above, its values are walked for what they hold.
        own = [value for _, value in pairs]
        stated = [value for _, value in pairs_again] if keys_again == keys else own
        values = zip(own, stated, strict=True)
    else:
        if len(keys) >= 2:
            movable.add((depth, in_array))
        stated = dict(pairs_again)
        values = ((value, stated[key]) for key, value in pairs)
    for value, value_again in values:
        _member_orders(value, value_again, depth + 1, False, (movable, moved))
    return movable, moved


def _short_of_every_depth(name, order, movable, moved):
    """Why one input's reordering fell short, or None where it did not."""
    if not movable:
        return f"{name}: no object of two or more members to move"
    if moved != movable:
        return (
            f"{name}, {order}: objects to move at {sorted(movable)}, "
            f"moved at {sorted(moved)}"
        )
    return None


def test_the_key_order_gate_reorders_objects_at_every_depth():
    """Decisions log D38's text half, in each input, changes the member order
    of an object at every depth the input holds one a reordering can move --
    two or more members, no key stated twice -- down to the deepest it holds,
    and of one inside an array at every depth it holds one there: measured on
    the input as written and as reordered, by `_member_orders`. The floor is
    each input's own deepest object, and each input must hold one. Each is
    held alone, so the hand-made inputs are not what makes it so for the
    repository's, and no input is what makes it so for another."""
    groups = {name.split("/")[0] for name, _ in KEY_ORDER_TEXTS}
    assert groups == {"conformance", "captured", "zoo", "hand-made"}
    short = []
    for name, source in KEY_ORDER_TEXTS:
        data = _bytes(source)
        for order, make in sorted(ORDERS.items()):
            reordered, _ = key_order.input_reordered(data, make(), key_order.Tally())
            found = (set(), set())
            for pair in zip(
                _values_written(data), _values_written(reordered), strict=True
            ):
                _member_orders(*pair, found=found)
            short.append(_short_of_every_depth(name, order, *found))
    assert [why for why in short if why] == []


def test_the_key_order_gate_reorders_records_at_every_depth():
    """The same for the records half: the records `read_protobuf` reads out
    of the zoo, and the hand-made inputs' records, each record as read
    against reordered."""
    short = []
    for name, read in KEY_ORDER_RECORDS:
        records = read().records
        for order, make in sorted(ORDERS.items()):
            reorder = make()
            found = (set(), set())
            for record in records:
                again = key_order.records_reordered(record, reorder, key_order.Tally())
                _member_orders(record, again, found=found)
            short.append(_short_of_every_depth(name, order, *found))
    assert [why for why in short if why] == []


def test_the_reach_is_measured_where_member_order_changed():
    # `_member_orders` against reorderings made by hand: every object moved,
    # the top one alone, the deepest alone, and an object stating a key twice,
    # which is never one to move and is seen if it moves.
    text = '{"b": 1, "a": [{"d": 1, "c": [{"f": 1, "e": 2}]}], "g": {"i": 1, "h": 2}}'
    every = {(1, False), (2, False), (3, True), (5, True)}
    (written,) = _values_written(text.encode("utf-8"))
    for again, moved in [
        (
            '{"g": {"h": 2, "i": 1}, "a": [{"c": [{"e": 2, "f": 1}], "d": 1}], "b": 1}',
            every,
        ),
        (
            '{"g": {"i": 1, "h": 2}, "a": [{"d": 1, "c": [{"f": 1, "e": 2}]}], "b": 1}',
            {(1, False)},
        ),
        (
            '{"b": 1, "a": [{"d": 1, "c": [{"e": 2, "f": 1}]}], "g": {"i": 1, "h": 2}}',
            {(5, True)},
        ),
        (text, set()),
    ]:
        (reordered,) = _values_written(again.encode("utf-8"))
        assert _member_orders(written, reordered) == (every, moved), again
    (twice,) = _values_written(b'{"a": 1, "b": {"y": 1, "x": 2}, "a": 2}')
    (left,) = _values_written(b'{"a": 1, "b": {"x": 2, "y": 1}, "a": 2}')
    (moved_too,) = _values_written(b'{"b": {"y": 1, "x": 2}, "a": 1, "a": 2}')
    assert _member_orders(twice, left) == ({(2, False)}, {(2, False)})
    assert _member_orders(twice, moved_too) == ({(2, False)}, {(1, False)})


# The reordering itself, held to what `tests/key_order.py` says it does.


def test_the_reordering_moves_each_member_whole_and_keeps_every_token():
    # Numbers a JSON round trip would respell (`1.50`, `1e5`, `-0`) and one
    # longer than a float holds, a string that holds JSON, an escape, and
    # whitespace inside and between members: each kept as it is written.
    text = (
        '{ "b" : 1.50 ,"a":[{"d":1e5,"c":-0}, "x\\"y"] , '
        '"e": {"g": "{\\"k\\": 1, \\"j\\": 2}", "f": 123456789012345678901234567890}}'
    )
    tally = key_order.Tally()
    assert key_order.reordered(text, key_order.reversal, tally) == (
        '{ "e": {"f": 123456789012345678901234567890, "g": "{\\"k\\": 1, \\"j\\": 2}"} '
        ',"a":[{"c":-0,"d":1e5}, "x\\"y"] , "b" : 1.50}'
    )
    assert tally == key_order.Tally(
        objects=3, permuted=3, deepest=3, nested=2, in_arrays=1
    )


def test_the_reordering_reversed_twice_is_the_input():
    for _, source in KEY_ORDER_TEXTS:
        data = _bytes(source)
        tally = key_order.Tally()
        once, _ = key_order.input_reordered(data, key_order.reversal, tally)
        twice, _ = key_order.input_reordered(once, key_order.reversal, tally)
        assert twice == data


def test_an_object_stating_a_key_twice_is_left_as_written():
    # Which copy a parser keeps depends on the order, so this object is not
    # reordered; the object inside it is.
    tally = key_order.Tally()
    text = '{"a": 1, "b": {"y": 1, "x": 2}, "a": 2}'
    assert key_order.reordered(text, key_order.reversal, tally) == (
        '{"a": 1, "b": {"x": 2, "y": 1}, "a": 2}'
    )
    assert (tally.duplicated, tally.permuted) == (1, 1)


def test_an_input_is_split_as_the_reader_splits_it():
    tally = key_order.Tally()
    lines = b'{"b":1,"a":2}\n{not json\n\n\xff\xfe\r\n  {"d":1,"c":2}  \r\n'
    assert key_order.input_reordered(lines, key_order.reversal, tally) == (
        b'{"a":2,"b":1}\n{not json\n\n\xff\xfe\r\n  {"c":2,"d":1}  \r\n',
        ["line 2: JSONDecodeError", "line 4: not UTF-8"],
    )
    bom = b"\xef\xbb\xbf"
    assert key_order.input_reordered(
        bom + b'[{"b":1,"a":2},\n{"d":1,"c":2}]', key_order.reversal, tally
    ) == (bom + b'[{"a":2,"b":1},\n{"c":2,"d":1}]', [])
    export = b'{"resourceSpans": [{"b": 1,\n "a": 2}]}\n'
    assert key_order.input_reordered(export, key_order.reversal, tally) == (
        b'{"resourceSpans": [{"a": 2,\n "b": 1}]}\n',
        [],
    )


def test_the_shuffle_is_seeded_and_never_the_written_order():
    first, second = key_order.shuffle(1), key_order.shuffle(1)
    for count in [2, 3, 2, 5, 2, 4] * 20:
        drawn = first(count)
        assert drawn == second(count)
        assert sorted(drawn) == list(range(count)) != drawn


def test_records_are_reordered_with_their_types_kept():
    (record,) = spanweave.read_records(_otlp_export()).records[:1]
    tally = key_order.Tally()
    reordered = key_order.records_reordered(record, key_order.reversal, tally)
    assert type(reordered) is type(record) is not dict
    assert reordered == record
    assert list(reordered) == list(reversed(record))
    assert tally.nested and tally.in_arrays


# --------------------------------------------------------------------------
# Where an export is found, and a kvlist's text (decisions log D39)
# --------------------------------------------------------------------------
#
# Two orders the gate above could not hold. The reader found an export by its
# FIRST member key, so a document written over several lines whose object
# states `resourceSpans` beside another member was one record with it first
# and every line `malformed_record` with it after: the gate splits an input as
# the reader does, so it fed the second unchanged, as lines it could not read.
# And the `exception_event` message wrote an `exception.type` stated as a
# `kvlistValue` in the order the list gives its entries, which is a list's
# order, not a member's, so no reordering of an object reached it. Each is
# held here by one pair, both orders, and the content each must keep.


#: The span inside the export the object states.
_INNER_SPAN = {"traceId": "t1", "spanId": "s2", "name": "inner"}


def _beside_another_member(resource_spans_first, members):
    """One object over several lines, ``resourceSpans`` first or last."""
    stated = [("resourceSpans", [{"scopeSpans": [{"spans": [_INNER_SPAN]}]}])]
    ordered = [*stated, *members] if resource_spans_first else [*members, *stated]
    lines = [f"  {json.dumps(key)}: {json.dumps(value)}" for key, value in ordered]
    return ("{\n" + ",\n".join(lines) + "\n}\n").encode("utf-8")


#: Beside `resourceSpans`: a flat record's members, so the object is a record
#: an adapter claims and the pair builds a graph; and one member, as
#: `tests/test_read.py`'s second-key case states it, which no adapter claims.
BESIDE_RESOURCE_SPANS = {
    "a flat record": [
        ("trace_id", "t1"),
        ("span_id", "s1"),
        ("name", "carried"),
        ("start_time", 1700000001),
        ("attributes", {"openinference.span.kind": "LLM"}),
    ],
    "one other member": [("somethingElse", 1)],
}


@pytest.mark.parametrize("beside", sorted(BESIDE_RESOURCE_SPANS))
def test_an_export_is_found_wherever_resource_spans_stands(beside):
    """Decisions log D39: presence, not position, decides whether the reader
    reads a document whole (`SPEC.md` §7). With `resourceSpans` first or last,
    the document is one record -- the whole object, carried verbatim, its
    other members with it, not unpacked, since `ExportTraceServiceRequest` has
    one field -- and the two build one graph (or the same refusal), by the
    gate's comparator: `dumps` less `meta.source_digest`."""
    members = BESIDE_RESOURCE_SPANS[beside]
    first = _beside_another_member(True, members)
    last = _beside_another_member(False, members)
    assert first != last and len(first.splitlines()) == len(members) + 3
    stated = json.loads(first)
    assert json.loads(last) == stated
    assert next(iter(stated)) == "resourceSpans" != next(iter(json.loads(last)))
    for data in (first, last):
        read = spanweave.read_records(data)
        assert read.records == (stated,), "not the whole object, as one record"
        assert type(read.records[0]) is dict, "an object of two members unpacked"
        assert (read.diagnostics, read.skipped_records) == ((), 0)
    written, digest = _outcome(first)
    again, digest_again = _outcome(last)
    if beside == "a flat record":
        assert isinstance(written, bytes), "the flat record built no graph"
        (node,) = json.loads(written)["nodes"]
        assert node["raw"]["source"] == stated
        assert digest_again != digest
    if isinstance(written, bytes) and isinstance(again, bytes) and written != again:
        pytest.fail(
            f"{beside}, resourceSpans first and last: the graph changed --\n  "
            + "\n  ".join(_differences(_parsed(written), _parsed(again)))
        )
    assert again == written


def _kvlists_reversed(value):
    """``value`` with every `kvlistValue`'s entries listed the other way round,
    at every depth: the same map, in the other list order. Its own inverse."""
    if isinstance(value, list):
        return [_kvlists_reversed(item) for item in value]
    if not isinstance(value, dict):
        return value
    copy = {key: _kvlists_reversed(item) for key, item in value.items()}
    listed = copy.get("kvlistValue")
    if isinstance(listed, dict) and isinstance(listed.get("values"), list):
        copy["kvlistValue"] = {**listed, "values": listed["values"][::-1]}
    return copy


def _exception_export(stated_type=STRUCTURED):
    """An export whose span records an exception, its `exception.type` the
    structured value as the nested `kvlistValue` OTLP/JSON writes it."""
    event = {
        "timeUnixNano": "1700000000500000000",
        "name": "exception",
        "attributes": _key_values(
            {"exception.type": stated_type, "exception.message": "boom"}
        ),
    }
    span = {
        "traceId": "5b8efff798038103d269b633813fc60c",
        "spanId": "eee19b7ec3c1b174",
        "name": "failed",
        "startTimeUnixNano": "1700000000000000000",
        "attributes": _key_values({"openinference.span.kind": "LLM"}),
        "events": [event],
    }
    return {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}


def test_a_kvlist_rendered_to_text_is_rendered_as_a_map():
    """Decisions log D39: an `exception.type` stated as a `kvlistValue` is
    written in the `exception_event` message as the map it stands for, its
    keys sorted at every level (`SPEC.md` §3.3, §7), so the map listed in two
    orders gives one message. A list's order is the input's and reaches
    `raw.source` verbatim, so the two graphs differ there, and only there:
    with the second's entries listed back, it is the first, byte for byte, by
    the gate's comparator."""
    written = _exception_export()
    listed_back = _kvlists_reversed(written)
    assert listed_back != written
    assert _kvlists_reversed(listed_back) == written
    first, other = (
        json.dumps(export).encode("utf-8") for export in (written, listed_back)
    )
    for data in (first, other):
        graph = spanweave.build(data)
        (event,) = [d for d in graph.diagnostics if d.code == "exception_event"]
        assert event.message == (
            "the span states event 0, an exception recorded by the OpenTelemetry "
            "API ({'alpha': {'beta': True, 'mu': [{'xx': 1, 'yy': 2}]}, "
            "'case': {'Ab': 2, 'ab': 1}, 'eta': [3, {'p': 's', 'q': None}], "
            "'nu': [[{'jj': 1, 'kk': 2}, 4]], 'zeta': 1}); the graph has no "
            "field for it, so it is reported here, its stacktrace kept verbatim "
            "in raw with the whole event. Whether the span failed is its status"
        )
        assert event.source == {
            "type": STRUCTURED,
            "message": "boom",
            "escaped": None,
            "time": 1700000000.5,
        }
    one, digest = _outcome(first)
    two, digest_two = _outcome(other)
    assert isinstance(one, bytes) and isinstance(two, bytes)
    assert one != two, "the list's order did not reach raw.source"
    again = canonical_bytes(_kvlists_reversed(json.loads(two)))
    if again != one:
        pytest.fail(
            "the kvlist listed in two orders: the graph changed --\n  "
            + "\n  ".join(_differences(_parsed(one), _parsed(again)))
        )
    assert digest_two != digest


#: An `exception.type` that is not a map, and its text in the message:
#: `repr`'s, as before (`SPEC.md` §7), a map inside a list sorted.
EXCEPTION_TYPE_TEXTS = {
    "a string": ("ValueError", "'ValueError'"),
    "an integer": (7, "7"),
    "a list holding a map": (["b", {"d": 1, "c": 2}], "['b', {'c': 2, 'd': 1}]"),
}


@pytest.mark.parametrize("stated", sorted(EXCEPTION_TYPE_TEXTS))
def test_an_exception_type_is_written_in_repr_s_spelling(stated):
    """Decisions log D39 sorts a map's keys and nothing else: every other
    `exception.type` reads in the message as `repr` writes it, a string
    quoted, as it did before."""
    value, text = EXCEPTION_TYPE_TEXTS[stated]
    graph = spanweave.build(json.dumps(_exception_export(value)).encode("utf-8"))
    (event,) = [d for d in graph.diagnostics if d.code == "exception_event"]
    assert event.message.startswith(
        "the span states event 0, an exception recorded by the OpenTelemetry "
        f"API ({text}); the graph has no field for it"
    )
    assert event.source["type"] == value


# --------------------------------------------------------------------------
# The digit limit is the library's, not the interpreter's (batch S8)
# --------------------------------------------------------------------------
#
# `SPEC.md` §5.3. CPython refuses to convert an integer string longer than
# `sys.get_int_max_str_digits()`, and that limit is a per-interpreter setting:
# 4300 by default, 640 at its lowest, or none at all. Batch R14 named it as an
# input to the graph and measured the two graphs one file produced under two
# settings. Batch S8 removed the input instead: the library owns the limit
# (`DIGIT_LIMIT`, 4300) and applies it by counting digits before any
# conversion, so the same bytes produce the same graph under every setting --
# which is `CLAUDE.md` invariant 4 as written, with no condition on it.
#
# Measured in separate processes, because the setting is process-wide and a
# test that moved it in-process would leave it moved for every test after.

#: Builds the trace at `argv[1]` and writes the graph's bytes to stdout.
_BUILD_AND_WRITE = (
    "import sys, spanweave\n"
    "sys.stdout.buffer.write(spanweave.dumps(spanweave.build(sys.argv[1])))\n"
)

#: Unset, disabled, and the lowest limit the interpreter accepts.
_DIGIT_SETTINGS = (None, "0", "640")


def _digit_limit_trace():
    """Every place an integer literal meets the library, at every boundary.

    Written as text rather than through `json.dumps`, because this process may
    itself be running under the lowest limit, where encoding the literals
    below would raise before any of them reached the library.
    """
    from tests import digit_limit

    past, inside, floor = (
        digit_limit.past(),
        digit_limit.inside(),
        digit_limit.above_the_floor(),
    )
    kind = '"openinference.span.kind":"AGENT"'
    lines = [
        # Quoted, past the library's limit: not read.
        f'{{"trace_id":"t1","span_id":"s0","name":"op","start_time":"{past}",'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
        # Quoted, exactly at it: read, and rendered into two messages.
        f'{{"trace_id":"t1","span_id":"s1","name":"op","start_time":"{inside}",'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
        # Unquoted, past the interpreter's lowest limit and inside the
        # library's: in a span kind, an unmapped attribute and a JSON payload.
        f'{{"trace_id":"t1","span_id":"s2","name":"op","start_time":1700000000,'
        f'"end_time":1700000001,"attributes":{{"openinference.span.kind":{floor},'
        f'"x.count":{inside},"input.mime_type":"application/json",'
        f'"input.value":"{{\\"n\\":{floor}}}"}}}}',
        # Unquoted, past the library's limit: the line is not JSON it reads.
        f'{{"trace_id":"t1","span_id":"s3","name":"op","start_time":{past}}}',
        # Unquoted, exactly at it: read.
        f'{{"trace_id":"t1","span_id":"s4","name":"op","start_time":{inside},'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
    ]
    return ("\n".join(lines) + "\n").encode()


def _digit_limit_export():
    """An OTLP export whose `intValue`s sit either side of the limit."""
    from tests import digit_limit

    past, inside = digit_limit.past(), digit_limit.inside()
    attributes = (
        f'{{"key":"gen_ai.operation.name","value":{{"stringValue":"chat"}}}},'
        f'{{"key":"past","value":{{"intValue":"{past}"}}}},'
        f'{{"key":"inside","value":{{"intValue":"{inside}"}}}}'
    )
    span = (
        f'{{"traceId":"t1","spanId":"s0","name":"chat",'
        f'"startTimeUnixNano":"{inside}","endTimeUnixNano":"1700000000",'
        f'"attributes":[{attributes}]}}'
    )
    return f'{{"resourceSpans":[{{"scopeSpans":[{{"spans":[{span}]}}]}}]}}'.encode()


def _built_under(setting, path):
    import os
    import subprocess
    import sys

    environment = dict(os.environ)
    environment.pop("PYTHONINTMAXSTRDIGITS", None)
    if setting is not None:
        environment["PYTHONINTMAXSTRDIGITS"] = setting
    finished = subprocess.run(
        [sys.executable, "-c", _BUILD_AND_WRITE, str(path)],
        capture_output=True,
        env=environment,
        check=False,
    )
    assert finished.returncode == 0, (setting, finished.stderr.decode()[-2000:])
    return finished.stdout


@pytest.mark.parametrize(
    "trace", [_digit_limit_trace, _digit_limit_export], ids=["jsonl", "otlp"]
)
def test_the_digit_limit_setting_does_not_change_the_graph(tmp_path, trace):
    path = tmp_path / "trace.json"
    path.write_bytes(trace())
    built = {setting: _built_under(setting, path) for setting in _DIGIT_SETTINGS}
    assert built[None] == built["0"] == built["640"], (
        "the same bytes built different graphs under different "
        "PYTHONINTMAXSTRDIGITS settings (`SPEC.md` §5.3)"
    )


def test_the_graph_every_setting_agrees_on_is_the_librarys_limit(tmp_path):
    # Identity alone would pass if every setting agreed on the wrong graph.
    # This pins which one: the library's limit, applied as §3.1 and §7 state.
    from tests import digit_limit

    path = tmp_path / "trace.jsonl"
    path.write_bytes(_digit_limit_trace())
    # `parse_int=str` so that reading the result back cannot meet the limit
    # this process may be running under.
    document = json.loads(_built_under("640", path), parse_int=str)
    nodes = {node["raw"]["source"]["span_id"]: node for node in document["nodes"]}
    assert sorted(nodes) == ["s0", "s1", "s2", "s4"]
    assert nodes["s0"]["started_at"] is None
    assert nodes["s0"]["raw"]["source"]["start_time"] == digit_limit.past()
    assert nodes["s1"]["started_at"] == digit_limit.inside()
    assert nodes["s4"]["started_at"] == digit_limit.inside()
    assert nodes["s2"]["attributes"]["reported_kind"] == digit_limit.above_the_floor()
    assert nodes["s2"]["inputs"]["value"] == {"n": digit_limit.above_the_floor()}
    by_code = {}
    for item in document["diagnostics"]:
        by_code.setdefault(item["code"], []).append(item)
    assert "missing_timestamp" in by_code
    assert [item["source"] for item in by_code["malformed_record"]] == [
        f'{{"trace_id":"t1","span_id":"s3","name":"op",'
        f'"start_time":{digit_limit.past()}}}'
    ]
    assert any(
        digit_limit.inside() in item["message"] for item in by_code["nonmonotonic_time"]
    )

    export = tmp_path / "export.json"
    export.write_bytes(_digit_limit_export())
    (node,) = json.loads(_built_under("640", export), parse_int=str)["nodes"]
    assert node["raw"]["source"]["attributes"]["past"] == digit_limit.past()
    assert node["raw"]["source"]["attributes"]["inside"] == digit_limit.inside()
    # Read inside the limit, and then -- its field declares nanoseconds -- a
    # count no float holds once divided into seconds, so not a time §3.1 reads
    # (batch T2). The digits stay verbatim in the record.
    assert node["started_at"] is None
    assert node["raw"]["source"]["start_time"] == digit_limit.inside()


def test_the_guarantee_holds_past_the_digit_limit_in_process():
    determinism.assert_repeatable(
        lambda: spanweave.dumps(spanweave.build(_digit_limit_trace()))
    )


#: Per dialect, for `KEY_ORDER_TWINS`' record written as text: the member
#: stating the span kind or operation, the payload's key, and whether the
#: adapter's `value` is the text (OpenInference, with no JSON mime) or the
#: value as reported (OTel GenAI's already-structured branch).
_LONG_INTEGER_PAYLOADS = {
    "openinference": ('"openinference.span.kind":"TOOL"', "input.value", True),
    "otel_genai": ('"gen_ai.operation.name":"chat"', "gen_ai.input.messages", False),
}


@pytest.mark.parametrize("dialect", sorted(_LONG_INTEGER_PAYLOADS))
def test_a_payload_holding_a_long_integer_is_written_sorted_under_the_lowest_setting(
    tmp_path, dialect
):
    # The pair `KEY_ORDER_TWINS` holds, its payload holding an integer the
    # lowest setting will not write. There `json.dumps` raises, and `encode`'s
    # retry writes the integer whole (`SPEC.md` §5.3) -- of the same sorted
    # value, so the order the kept line wrote is not in the text there either
    # (§3.3). A retry of the value as written passed every test, all of them
    # run at this process's setting, and built two graphs here (the scoped
    # review of 2026-10-18b, R-1). Written as text, as `_digit_limit_trace`
    # is, and for its reason.
    from tests import digit_limit

    long = digit_limit.above_the_floor()
    member, key, value_is_text = _LONG_INTEGER_PAYLOADS[dialect]
    first, second = (
        f'{{"trace_id":"t1","span_id":"s1","name":"op",'
        f'"attributes":{{{member},"{key}":{payload}}}}}'
        for payload in (f'{{"a":"x","b":{long}}}', f'{{"b":{long},"a":"x"}}')
    )
    text = f'{{"a": "x", "b": {long}}}'
    documents = []
    for name, lines in (("forwards", (first, second)), ("backwards", (second, first))):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        # `parse_int=str`, as above: reading the graph back cannot meet the
        # limit this process may be running under.
        document = json.loads(_built_under(str(digit_limit.FLOOR), path), parse_int=str)
        found = [item["code"] for item in document["diagnostics"]]
        assert found.count("duplicate_record") == 1
        (node,) = document["nodes"]
        assert node["provenance"]["adapter_id"] == dialect
        assert node["inputs"]["raw"] == text
        assert node["inputs"]["value"] == (
            text if value_is_text else {"a": "x", "b": long}
        )
        documents.append(document)
    # The same graph, less `meta.source_digest`, which the swap changes by
    # definition -- and does, so the exclusion hides nothing.
    forwards, backwards = (
        document["meta"].pop("source_digest") for document in documents
    )
    assert forwards != backwards
    assert documents[0] == documents[1]
