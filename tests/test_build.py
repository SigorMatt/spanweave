"""The builder: nodes and explicit edges (TASKS.md 1.5).

The builder's whole job is to state what the telemetry stated and to account
for what it could not. So the tests come in pairs: an edge that gets built,
and the same shape one field short, which produces a diagnostic and no edge.
"""

import dataclasses

import pytest

from spanweave import diagnostics as codes
from spanweave.build import build_graph
from spanweave.diagnostics import DiagnosticCollector
from spanweave.model import (
    AdapterInfo,
    Diagnostic,
    EdgeKind,
    NodeKind,
    Payload,
    PayloadState,
    RawRecord,
    Warrant,
)
from spanweave.seam import CallRole, DeclaredDataEdge, NormalizedSpan, SpanLink

ADAPTER = AdapterInfo(id="some_dialect", version="0.1.0", confidence=0.9)


def a_span(span_id, parent=None, *, trace="t1", line=1, **overrides):
    return NormalizedSpan(
        source_key=span_id,
        span_id=span_id,
        parent_id=parent,
        trace_id=trace,
        kind=overrides.pop("kind", NodeKind.CHAIN),
        name=overrides.pop("name", f"op.{span_id}"),
        raw=RawRecord(source={"span_id": span_id}, source_id=span_id, line_number=line),
        **overrides,
    )


def build(spans, **kwargs):
    # Explicit edges only. Derived temporal edges -- and the
    # `missing_timestamp` diagnostics that explain the nodes they skip -- are
    # 1.6's subject and are exercised in `test_ordering.py`. Switching them
    # off here keeps these assertions exact rather than filtered.
    kwargs.setdefault("temporal", False)
    return build_graph(spans, adapter=ADAPTER, **kwargs)


def edges_of(graph, kind):
    return [(e.src, e.dst) for e in graph.edges() if e.kind is kind]


def codes_of(graph):
    return [d.code for d in graph.diagnostics]


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


def test_every_span_becomes_a_node_carrying_its_source():
    graph = build([a_span("s0"), a_span("s1", "s0", line=2)])
    assert [n.id for n in graph.nodes()] == ["s0", "s1"]
    assert graph.nodes()[0].raw.source == {"span_id": "s0"}
    assert graph.nodes()[0].provenance.adapter_id == "some_dialect"


def test_the_node_reports_what_the_span_reported_and_nothing_more():
    span = a_span(
        "s0",
        operation="lookup",
        started_at=1000.0,
        ended_at=1001.0,
        inputs=Payload(state=PayloadState.EMPTY, mime="text/plain", value="", raw=""),
    )
    node = build([span]).nodes()[0]
    assert node.operation == "lookup"
    assert node.inputs.state is PayloadState.EMPTY
    # Never invented on the way through.
    assert node.outputs.state is PayloadState.ABSENT
    assert node.usage is None


def test_an_empty_input_builds_an_empty_graph_rather_than_failing():
    graph = build([])
    assert graph.nodes() == () and graph.edges() == ()
    assert graph.meta.node_count == 0


def test_the_adapters_own_diagnostics_are_attached_to_their_node():
    span = a_span(
        "s0",
        diagnostics=(Diagnostic(code=codes.UNKNOWN_SPAN_KIND, message="odd kind"),),
    )
    graph = build([span])
    assert graph.diagnostics[0].node_id == "s0"


# --------------------------------------------------------------------------
# parent
# --------------------------------------------------------------------------


def test_parent_edges_come_from_the_stated_parent_id():
    graph = build([a_span("s0"), a_span("s1", "s0"), a_span("s2", "s0")])
    assert edges_of(graph, EdgeKind.PARENT) == [("s0", "s1"), ("s0", "s2")]
    parent = graph.edges()[0]
    assert parent.warrant is Warrant.EXPLICIT
    assert parent.basis == "span.parent_span_id"


def test_a_parent_that_is_not_here_is_diagnosed_and_the_node_is_kept():
    graph = build([a_span("s1", "missing")])
    assert edges_of(graph, EdgeKind.PARENT) == []
    assert codes_of(graph) == [codes.ORPHAN_PARENT]
    assert graph.diagnostics[0].node_id == "s1"
    # A trace that starts mid-run is ordinary; dropping the record would lose
    # more than the missing parent did.
    assert len(graph.nodes()) == 1


def test_a_parent_edge_is_never_derived():
    # parent is explicit-only (SPEC.md §4.1) and the model refuses otherwise;
    # this asserts the builder does not try.
    graph = build([a_span("s0"), a_span("s1", "s0")])
    assert all(e.warrant is Warrant.EXPLICIT for e in graph.edges())


# --------------------------------------------------------------------------
# call_result
# --------------------------------------------------------------------------


def test_a_call_and_its_result_are_joined_by_the_id_the_dialect_carried():
    graph = build(
        [
            a_span("s1", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("call_a",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2")]
    assert graph.edges()[0].basis == "tool_call_id"
    assert codes_of(graph) == []


def test_the_pairing_is_independent_of_the_parent_relation():
    # Frequently the two are different relations entirely (SPEC.md §4.4).
    graph = build(
        [
            a_span("s0"),
            a_span("s1", "s0", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", "s0", call_ids=("call_a",), call_role=CallRole.FULFILLER),
        ]
    )
    assert ("s1", "s2") in edges_of(graph, EdgeKind.CALL_RESULT)
    assert ("s1", "s2") not in edges_of(graph, EdgeKind.PARENT)


def test_a_call_nobody_answered_is_diagnosed_not_invented():
    graph = build(
        [
            a_span("s1", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", name="tool.lookup"),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []
    assert codes_of(graph) == [codes.UNPAIRED_CALL]
    assert "no edge is invented" in graph.diagnostics[0].message


def test_a_result_nobody_asked_for_is_diagnosed_too():
    graph = build([a_span("s2", call_ids=("call_a",), call_role=CallRole.FULFILLER)])
    assert codes_of(graph) == [codes.UNPAIRED_RESULT]


def test_pairing_never_falls_back_to_name_or_proximity():
    # Two spans that obviously belong together, with no id between them.
    graph = build(
        [
            a_span("s1", name="llm.plan", started_at=1.0),
            a_span("s2", name="tool.lookup", started_at=2.0),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []
    assert codes_of(graph) == []


def test_two_spans_fulfilling_one_call_produce_two_explicit_edges():
    graph = build(
        [
            a_span("s1", call_ids=("c",), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("c",), call_role=CallRole.FULFILLER),
            a_span("s3", call_ids=("c",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2"), ("s1", "s3")]


def test_one_span_can_request_several_calls():
    # The shape current agent frameworks emit constantly: one model turn
    # asking for several tools at once.
    graph = build(
        [
            a_span("s1", call_ids=("a", "b"), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("a",), call_role=CallRole.FULFILLER),
            a_span("s3", call_ids=("b",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2"), ("s1", "s3")]
    assert codes_of(graph) == []


def test_one_unanswered_call_among_several_is_diagnosed_on_its_own():
    graph = build(
        [
            a_span("s1", call_ids=("a", "b"), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("a",), call_role=CallRole.FULFILLER),
        ]
    )
    # The answered one still pairs; only the unanswered one is reported.
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2")]
    assert codes_of(graph) == [codes.UNPAIRED_CALL]
    assert "'b'" in graph.diagnostics[0].message


def test_a_call_id_without_a_role_pairs_with_nothing():
    graph = build([a_span("s1", call_ids=("c",)), a_span("s2", call_ids=("c",))])
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []


# --------------------------------------------------------------------------
# link and data
# --------------------------------------------------------------------------


def test_a_link_within_the_trace_points_at_the_node():
    graph = build([a_span("s0", links=(SpanLink(span_id="s1"),)), a_span("s1")])
    assert edges_of(graph, EdgeKind.LINK) == [("s0", "s1")]


def test_a_cross_trace_link_is_still_transcribed():
    # Links routinely leave the trace; requiring the target to be present
    # would make the kind useless for the case it exists for (SPEC.md §4).
    graph = build([a_span("s0", links=(SpanLink(span_id="foreign", trace_id="t2"),))])
    assert edges_of(graph, EdgeKind.LINK) == [("s0", "foreign")]
    assert graph.node("foreign") is None


def test_a_declared_data_edge_is_transcribed_with_the_declared_basis():
    graph = build(
        [
            a_span("s1"),
            a_span(
                "s2",
                data_edges=(
                    DeclaredDataEdge(src="s1", dst="s2", basis="framework.produced_by"),
                ),
            ),
        ]
    )
    assert edges_of(graph, EdgeKind.DATA) == [("s1", "s2")]
    edge = next(e for e in graph.edges() if e.kind is EdgeKind.DATA)
    assert edge.warrant is Warrant.EXPLICIT
    assert edge.basis == "framework.produced_by"


def test_no_data_edge_appears_from_matching_values():
    # The output of s1 is the input of s2, and the graph says nothing about
    # it. That restraint is the library's central claim (SPEC.md §4.2).
    produced = Payload(state=PayloadState.PRESENT, value={"order": "A-1"})
    graph = build(
        [
            a_span("s1", outputs=produced),
            a_span("s2", inputs=produced),
        ]
    )
    assert edges_of(graph, EdgeKind.DATA) == []


# --------------------------------------------------------------------------
# Edge set hygiene
# --------------------------------------------------------------------------


def test_duplicate_edges_collapse():
    graph = build(
        [
            a_span("s0", links=(SpanLink(span_id="s1"), SpanLink(span_id="s1"))),
            a_span("s1"),
        ]
    )
    assert len(edges_of(graph, EdgeKind.LINK)) == 1


def test_the_same_pair_may_carry_several_kinds_of_edge():
    graph = build(
        [
            a_span("s0"),
            a_span("s1", "s0", call_ids=("c",), call_role=CallRole.FULFILLER),
            a_span("s0b", call_ids=("c",), call_role=CallRole.REQUESTER),
        ]
    )
    assert ("s0", "s1") in edges_of(graph, EdgeKind.PARENT)
    assert ("s0b", "s1") in edges_of(graph, EdgeKind.CALL_RESULT)


def test_edges_are_sorted_by_kind_then_endpoints_then_basis():
    graph = build([a_span("s0"), a_span("s2", "s0"), a_span("s1", "s0")])
    assert [e.sort_key for e in graph.edges()] == sorted(
        e.sort_key for e in graph.edges()
    )


# --------------------------------------------------------------------------
# Trace identity and honest degradation
# --------------------------------------------------------------------------


def test_the_most_common_trace_id_wins_and_the_rest_are_kept_and_diagnosed():
    graph = build([a_span("s0"), a_span("s1"), a_span("s9", trace="t2")])
    assert graph.trace_id == "t1"
    assert len(graph.nodes()) == 3  # the foreign record is kept
    assert codes_of(graph) == [codes.MULTI_TRACE_INPUT]
    assert graph.diagnostics[0].node_id == "s9"


def test_a_tie_between_trace_ids_is_broken_by_the_id_itself():
    # Arbitrary, but *stated*: otherwise one input could build two graphs.
    first = build([a_span("s0", trace="t2"), a_span("s1", trace="t1")])
    second = build([a_span("s1", trace="t1"), a_span("s0", trace="t2")])
    assert first.trace_id == second.trace_id == "t1"


def test_an_input_with_no_trace_id_still_builds():
    graph = build([a_span("s0", trace=None)])
    assert graph.trace_id == ""
    assert len(graph.nodes()) == 1


def test_a_backwards_clock_is_reported_and_left_alone():
    graph = build([a_span("s0", started_at=1002.0, ended_at=1000.0)])
    assert codes_of(graph) == [codes.NONMONOTONIC_TIME]
    # Reported, never repaired: the skew is a fact about the trace.
    assert graph.nodes()[0].started_at == 1002.0
    assert graph.nodes()[0].ended_at == 1000.0


def test_a_zero_length_span_is_not_skew():
    graph = build([a_span("s0", started_at=1000.0, ended_at=1000.0)])
    assert codes_of(graph) == []


def test_a_span_id_used_twice_with_distinct_source_keys_is_reported():
    spans = [
        NormalizedSpan(
            source_key=key,
            span_id="s1",
            trace_id="t1",
            kind=NodeKind.CHAIN,
            name="op",
            raw=RawRecord(source={}, source_id="s1", line_number=index),
        )
        for index, key in enumerate(["a", "b"], start=1)
    ]
    graph = build(spans)
    assert codes_of(graph) == [codes.DUPLICATE_SOURCE_ID]
    assert len(graph.nodes()) == 2


def test_a_reference_to_an_ambiguous_span_id_is_not_guessed():
    spans = [
        NormalizedSpan(
            source_key=key,
            span_id="s1",
            trace_id="t1",
            kind=NodeKind.CHAIN,
            name="op",
            raw=RawRecord(source={}, line_number=index),
        )
        for index, key in enumerate(["a", "b"], start=1)
    ]
    graph = build([*spans, a_span("s2", "s1")])
    # Two records claim 's1'. Picking one of them to be the parent would be a
    # guess, so there is no parent edge and there is a diagnostic.
    assert edges_of(graph, EdgeKind.PARENT) == []
    assert codes.ORPHAN_PARENT in codes_of(graph)


# --------------------------------------------------------------------------
# The builder knows nothing about dialects
# --------------------------------------------------------------------------


def test_the_builder_works_on_spans_from_a_dialect_it_has_never_heard_of():
    graph = build(
        [
            a_span("x1", kind=NodeKind.UNKNOWN, name="whatever"),
            a_span("x2", "x1", kind=NodeKind.EMBEDDING),
        ],
    )
    assert [n.kind for n in graph.nodes()] == [NodeKind.UNKNOWN, NodeKind.EMBEDDING]
    assert edges_of(graph, EdgeKind.PARENT) == [("x1", "x2")]


def test_diagnostics_raised_before_the_build_are_carried_through():
    collector = DiagnosticCollector()
    collector.add(codes.MALFORMED_RECORD, "line 2 is not valid JSON")
    graph = build([a_span("s0")], collector=collector)
    # A malformed line and an unpaired call are the same kind of statement
    # about the input, and end up in the same list.
    assert codes_of(graph) == [codes.MALFORMED_RECORD]
    assert graph.meta.diagnostic_count == 1


def test_meta_records_the_adapter_and_the_digest_but_no_environment():
    graph = build([a_span("s0")], source_digest="abc123")
    assert graph.meta.adapters == (ADAPTER,)
    assert graph.meta.source_digest == "abc123"
    assert graph.meta.spanweave_version
    # Nothing that would break byte-identical determinism or leak the
    # operator's environment (SPEC.md §3.9).
    assert not hasattr(graph.meta, "built_at")


@pytest.mark.parametrize("field", ["_nodes", "_edges", "diagnostics", "trace_id"])
def test_the_graph_is_immutable(field):
    graph = build([a_span("s0")])
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(graph, field, ())
