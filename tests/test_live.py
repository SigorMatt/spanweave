"""The incremental builder (`SPEC.md` §10) -- one record at a time.

Every test here is one shape of the same assertion: at version `k` the live
graph **is** `build(records[:k])`. Prefix consistency is the definition
(`OPEN_QUESTIONS.md` §18), so a test that asserts anything else about a live
graph would be inventing a second contract.

The cross-dialect corpus carries the same claim over every fixture
(`tests/test_conformance.py`, conformance gate 1). What is here is the cases
whose *arrival order* is the point -- a parent that arrives after its child, a
call fulfilled two records later, a receipt redeclared out of order -- because
a corpus file has one order and these need two.
"""

import inspect
import json

import pytest

import spanweave
from spanweave import diagnostics as codes
from spanweave.api import graph_from_records
from spanweave.errors import AdapterSelectionError
from spanweave.model import EdgeKind
from spanweave.serialize import dumps


def oi(span_id, parent=None, kind="TOOL", name="op", t0=1000.0, t1=1000.5, **attrs):
    """One OpenInference record, as flat as the dialect allows."""
    return {
        "trace_id": attrs.pop("trace_id", "t1"),
        "span_id": span_id,
        "parent_id": parent,
        "name": name,
        "start_time": t0,
        "end_time": t1,
        "status": "OK",
        "attributes": {"openinference.span.kind": kind, **attrs},
    }


def requester(span_id, call_id, **kw):
    """An LLM span that asks for one tool call."""
    return oi(
        span_id,
        kind="LLM",
        name="llm.plan",
        **{
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": call_id,
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "f",
            **kw,
        },
    )


def fulfiller(span_id, call_id, **kw):
    """A tool span that fulfils one call."""
    return oi(span_id, kind="TOOL", name="tool.f", **{"tool_call.id": call_id, **kw})


def receiver(span_id, call_id, t0, **kw):
    """An LLM span declaring that it was handed one call's result."""
    messages = [
        {
            "message.role": "tool",
            "message.tool_call_id": call_id,
            "message.content": "x",
        }
    ]
    flat = {}
    for index, message in enumerate(messages):
        for key, value in message.items():
            flat[f"llm.input_messages.{index}.{key}"] = value
    return oi(span_id, kind="LLM", name="llm.answer", t0=t0, t1=t0 + 0.1, **flat, **kw)


def replay(records, **kw):
    """Feed the records one at a time, comparing at every version.

    The whole contract, in five lines: the version is the arrival index, and
    the graph at that version equals the batch build of the same prefix --
    compared as a value *and* as the bytes it serializes to, since "byte for
    byte" is what `OPEN_QUESTIONS.md` §18 asked for and graph equality alone
    would not catch a field the writer orders differently.
    """
    builder = spanweave.Builder(**kw)
    assert builder.version == 0
    for index, record in enumerate(records, start=1):
        assert builder.feed(record) == index
        assert builder.version == index
        live = builder.graph()
        batch = graph_from_records(records[:index], **kw)
        assert live == batch, f"version {index} is not build(records[:{index}])"
        assert dumps(live) == dumps(batch)
    return builder


def codes_of(graph):
    return sorted(diagnostic.code for diagnostic in graph.diagnostics)


# --------------------------------------------------------------------------
# The API the decision fixed
# --------------------------------------------------------------------------


def test_feed_returns_the_new_version_as_an_int():
    builder = spanweave.Builder()
    first = builder.feed(oi("s1"))
    assert first == 1
    assert type(first) is int
    assert builder.feed(oi("s2")) == 2
    assert builder.version == 2


def test_feed_takes_no_delta_flag():
    """`WORKPLAN.md` §3, L1(4): every delta comes from `delta(since=v)`.

    Asserted on the signature rather than left to a comment, because "feed
    returns the new version and nothing else" is the part of the decision a
    later batch could quietly widen.
    """
    parameters = inspect.signature(spanweave.Builder.feed).parameters
    assert list(parameters) == ["self", "record"]


def test_the_builder_is_on_the_public_api():
    assert "Builder" in spanweave.__all__


# --------------------------------------------------------------------------
# Prefix consistency, where arrival order is the point
# --------------------------------------------------------------------------


def test_a_parent_that_arrives_after_its_child():
    """The case that makes arrival order and canonical order differ."""
    child = oi("s2", parent="s1", t0=1001.0)
    parent = oi("s1", kind="AGENT", name="agent", t0=1000.0)
    builder = replay([child, parent])
    graph = builder.graph()
    assert graph.topo_order == ("s1", "s2")
    assert [(e.src, e.dst) for e in graph.edges(kind=EdgeKind.PARENT)] == [("s1", "s2")]
    assert codes.ORPHAN_PARENT not in codes_of(graph)


def test_an_orphan_parent_is_true_while_it_is_true():
    """A diagnostic on a live graph is a statement about what has arrived."""
    builder = spanweave.Builder()
    builder.feed(oi("s2", parent="s1"))
    assert codes.ORPHAN_PARENT in codes_of(builder.graph())
    builder.feed(oi("s1", kind="AGENT", name="agent", t0=1000.0))
    assert codes.ORPHAN_PARENT not in codes_of(builder.graph())


def test_a_call_fulfilled_by_a_later_record():
    builder = replay([requester("s1", "call_a"), fulfiller("s2", "call_a", t0=1001.0)])
    graph = builder.graph()
    assert codes.UNPAIRED_CALL not in codes_of(graph)
    assert [(e.src, e.dst) for e in graph.edges(kind=EdgeKind.CALL_RESULT)] == [
        ("s1", "s2")
    ]


def test_a_result_that_arrives_before_the_span_that_asked_for_it():
    builder = replay([fulfiller("s2", "call_a", t0=1001.0), requester("s1", "call_a")])
    assert codes.UNPAIRED_RESULT not in codes_of(builder.graph())


def test_a_receipt_redeclared_out_of_order_rewrites_the_basis():
    """The later receiver arrives first, so `basis` moves when the earlier one
    lands (`SPEC.md` §4.2.1)."""
    records = [
        fulfiller("s1", "call_a", t0=1000.0),
        receiver("s3", "call_a", t0=1002.0),
        receiver("s2", "call_a", t0=1001.0),
    ]
    builder = replay(records)
    graph = builder.graph()
    bases = {edge.dst: edge.basis for edge in graph.edges(kind=EdgeKind.DATA)}
    assert "earliest" not in bases["s2"]
    assert "not the earliest" in bases["s3"]


def test_a_sibling_inserted_between_two_others():
    """Two temporal edges out, two in -- the middle record arrives last."""
    records = [
        oi("s0", kind="AGENT", name="agent", t0=1000.0),
        oi("s1", parent="s0", t0=1001.0),
        oi("s3", parent="s0", t0=1003.0),
        oi("s2", parent="s0", t0=1002.0),
    ]
    builder = replay(records)
    chain = [
        (edge.src, edge.dst) for edge in builder.graph().edges(kind=EdgeKind.TEMPORAL)
    ]
    assert chain == [("s1", "s2"), ("s2", "s3")]


def test_the_majority_trace_id_can_change_with_an_arrival():
    """Every derived id holds the trace id, so this one moves ids."""
    records = [
        oi("s1", trace_id="t1"),
        oi("s2", trace_id="t2"),
        oi("s3", trace_id="t2"),
    ]
    graph = replay(records).graph()
    assert graph.trace_id == "t2"
    assert codes.MULTI_TRACE_INPUT in codes_of(graph)


def test_a_dialect_span_id_that_stops_being_unique():
    """`SPEC.md` §3.6: the first record's id moves off rule 1 when the second
    claims the same span id."""
    records = [oi("s1", name="alpha"), oi("s1", name="beta", t0=1001.0)]
    builder = spanweave.Builder()
    builder.feed(records[0])
    assert builder.graph().topo_order == ("s1",)
    builder.feed(records[1])
    assert "s1" not in builder.graph().topo_order
    replay(records)


def test_a_record_no_adapter_claims():
    records = [oi("s1"), {"nothing": "recognizable"}]
    graph = replay(records).graph()
    assert codes.UNCLAIMED_RECORD in codes_of(graph)


def test_two_dialects_in_one_stream():
    genai = {
        "trace_id": "t1",
        "span_id": "g1",
        "parent_id": None,
        "name": "chat demo-model",
        "start_time": 1002.0,
        "end_time": 1002.5,
        "status": "OK",
        "attributes": {"gen_ai.operation.name": "chat", "gen_ai.request.model": "m"},
    }
    graph = replay([oi("s1"), genai]).graph()
    assert graph.meta is not None
    assert len(graph.meta.adapters) == 2


def test_temporal_false_is_carried_through():
    records = [oi("s1", t0=1000.0), oi("s2", t0=1001.0)]
    graph = replay(records, temporal=False).graph()
    assert graph.edges(kind=EdgeKind.TEMPORAL) == ()


def test_a_named_adapter_skips_classification():
    graph = replay([oi("s1")], adapter="openinference").graph()
    assert graph.meta is not None
    assert [a.id for a in graph.meta.adapters] == ["openinference"]
    assert graph.meta.adapters[0].declared_confidence is None


# --------------------------------------------------------------------------
# Refusals: a prefix the batch build refuses, the live builder refuses too
# --------------------------------------------------------------------------


def test_an_empty_builder_refuses_exactly_as_an_empty_input_does():
    builder = spanweave.Builder()
    with pytest.raises(AdapterSelectionError) as live:
        builder.graph()
    with pytest.raises(AdapterSelectionError) as batch:
        graph_from_records([])
    assert live.value.code == batch.value.code


def test_a_stream_nothing_claims_refuses_rather_than_building_unknowns():
    builder = spanweave.Builder()
    builder.feed({"nothing": "recognizable"})
    with pytest.raises(AdapterSelectionError):
        builder.graph()


def test_a_record_two_adapters_claim_names_its_arrival_index():
    both = oi("s1", **{"gen_ai.operation.name": "chat", "gen_ai.request.model": "m"})
    builder = spanweave.Builder()
    builder.feed(oi("s0", kind="AGENT", name="agent", t0=999.0))
    with pytest.raises(AdapterSelectionError) as refused:
        builder.feed(both)
    assert "record 2" in str(refused.value)
    # The refused record was not absorbed: nothing half-arrived.
    assert builder.version == 1


# --------------------------------------------------------------------------
# What the live graph does not carry
# --------------------------------------------------------------------------


def test_the_live_graph_reports_no_source_digest():
    """The builder is fed records, so the bytes of an input are not its to
    describe (`SPEC.md` §10)."""
    graph = replay([oi("s1")]).graph()
    assert graph.meta is not None
    assert graph.meta.source_digest is None


def test_materializing_twice_returns_the_same_graph():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    first = builder.graph()
    assert builder.graph() is first
    builder.feed(oi("s2", t0=1001.0))
    assert builder.graph() is not first


def test_a_record_is_what_the_reader_yields_and_not_a_line_of_text():
    """Feeding the *line* rather than the record is not silently parsed.

    A JSON string is a record no adapter claims, so it becomes an `unknown`
    node carrying it verbatim -- which is what a batch build of the same thing
    does. Nothing here re-reads it, and the mistake is visible in the graph
    rather than absorbed by it.
    """
    line = json.dumps(oi("s2"))
    graph = replay([oi("s1"), line]).graph()
    assert codes.UNCLAIMED_RECORD in codes_of(graph)
    assert len(graph.nodes()) == 2
    assert line in [node.raw.source for node in graph.nodes()]
