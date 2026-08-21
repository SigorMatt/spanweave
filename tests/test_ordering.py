"""Temporal edges and node ordering (TASKS.md 1.6).

Two properties are load-bearing here. The temporal rule is narrow on purpose
-- consecutive siblings, nothing else -- and the topological order is
tie-broken by a stated rule, because a topological order is not unique and an
unstated choice is a determinism bug waiting for a second machine.
"""

from spanweave import diagnostics as codes
from spanweave.build import build_graph
from spanweave.model import AdapterInfo, EdgeKind, NodeKind, RawRecord, Warrant
from spanweave.seam import CallRole, NormalizedSpan

ADAPTER = AdapterInfo(id="some_dialect", version="0.1.0")


def a_span(span_id, parent=None, started=None, **overrides):
    return NormalizedSpan(
        source_key=span_id,
        span_id=span_id,
        parent_id=parent,
        trace_id="t1",
        kind=NodeKind.CHAIN,
        name=f"op.{span_id}",
        started_at=started,
        raw=RawRecord(source={"span_id": span_id}),
        **overrides,
    )


def build(spans, **kwargs):
    return build_graph(spans, adapter=ADAPTER, **kwargs)


def temporal_of(graph):
    return [(e.src, e.dst) for e in graph.edges() if e.kind is EdgeKind.TEMPORAL]


def order_of(graph):
    return [n.id for n in graph.nodes()]


def codes_of(graph):
    return [d.code for d in graph.diagnostics]


# --------------------------------------------------------------------------
# The temporal rule
# --------------------------------------------------------------------------


def test_consecutive_siblings_only():
    graph = build(
        [
            a_span("s0", started=1000.0),
            a_span("s1", "s0", started=1000.2),
            a_span("s2", "s0", started=1001.2),
            a_span("s3", "s0", started=1002.2),
        ]
    )
    # s1 -> s3 is not there: the transitive closure is available through
    # graph.reachable(...) and materializing it would cost memory for no
    # information (SPEC.md §4.3).
    assert temporal_of(graph) == [("s1", "s2"), ("s2", "s3")]


def test_temporal_edges_are_always_derived():
    graph = build([a_span("a", started=1.0), a_span("b", started=2.0)])
    edge = next(e for e in graph.edges() if e.kind is EdgeKind.TEMPORAL)
    assert edge.warrant is Warrant.DERIVED
    assert edge.basis == "sibling start_time ordering"


def test_nodes_with_no_parent_are_siblings_at_the_root():
    graph = build([a_span("b", started=2.0), a_span("a", started=1.0)])
    assert temporal_of(graph) == [("a", "b")]


def test_siblings_under_different_parents_are_never_joined():
    graph = build(
        [
            a_span("p1", started=1.0),
            a_span("p2", started=2.0),
            a_span("c1", "p1", started=3.0),
            a_span("c2", "p2", started=4.0),
        ]
    )
    assert ("c1", "c2") not in temporal_of(graph)
    assert ("p1", "p2") in temporal_of(graph)


def test_an_orphan_is_a_root_sibling_because_here_it_has_no_parent():
    graph = build([a_span("a", started=1.0), a_span("b", "gone", started=2.0)])
    assert temporal_of(graph) == [("a", "b")]
    assert codes.ORPHAN_PARENT in codes_of(graph)


def test_equal_start_times_are_broken_by_node_id():
    # The tie-break is a determinism invariant, not a convenience.
    graph = build([a_span("b", started=1000.0), a_span("a", started=1000.0)])
    assert temporal_of(graph) == [("a", "b")]


def test_a_node_with_no_start_time_is_excluded_and_said_so():
    graph = build([a_span("a", started=1.0), a_span("b"), a_span("c", started=2.0)])
    assert temporal_of(graph) == [("a", "c")]
    assert codes.MISSING_TIMESTAMP in codes_of(graph)
    missing = next(d for d in graph.diagnostics if d.code == codes.MISSING_TIMESTAMP)
    assert missing.node_id == "b"
    # The node itself is kept, of course.
    assert "b" in order_of(graph)


def test_a_lone_sibling_produces_no_temporal_edge():
    assert temporal_of(build([a_span("a", started=1.0)])) == []


def test_no_temporal_omits_them_and_says_nothing_about_timestamps():
    spans = [a_span("a", started=1.0), a_span("b")]
    graph = build(spans, temporal=False)
    assert temporal_of(graph) == []
    # missing_timestamp explains an omitted temporal edge; with the whole kind
    # switched off there is nothing to explain.
    assert codes.MISSING_TIMESTAMP not in codes_of(graph)


def test_no_temporal_leaves_the_stated_relations_untouched():
    spans = [a_span("s0", started=1.0), a_span("s1", "s0", started=2.0)]
    with_derived = build(spans)
    without = build(spans, temporal=False)
    explicit = [e for e in with_derived.edges() if e.warrant is Warrant.EXPLICIT]
    assert list(without.edges()) == explicit


# --------------------------------------------------------------------------
# Node ordering
# --------------------------------------------------------------------------


def test_a_child_comes_after_its_parent():
    graph = build(
        [
            a_span("c", "b", started=3.0),
            a_span("b", "a", started=2.0),
            a_span("a", started=1.0),
        ]
    )
    assert order_of(graph) == ["a", "b", "c"]


def test_a_fulfiller_comes_after_its_requester_even_when_it_started_first():
    graph = build(
        [
            a_span("s2", started=1.0, call_id="c", call_role=CallRole.FULFILLER),
            a_span("s1", started=9.0, call_id="c", call_role=CallRole.REQUESTER),
        ]
    )
    # call_result is an ordering edge: the pairing outranks the clock.
    assert order_of(graph) == ["s1", "s2"]


def test_independent_nodes_are_ordered_by_start_time_then_id():
    graph = build(
        [a_span("z", started=1.0), a_span("a", started=2.0), a_span("b", started=2.0)]
    )
    assert order_of(graph) == ["z", "a", "b"]


def test_nodes_with_no_start_time_sort_last_but_are_not_dropped():
    graph = build([a_span("b"), a_span("a", started=5.0)])
    assert order_of(graph) == ["a", "b"]


def test_order_does_not_depend_on_input_order():
    spans = [
        a_span("s0", started=1000.0),
        a_span("s1", "s0", started=1000.2),
        a_span("s2", "s0", started=1001.2),
        a_span("s3", "s0", started=1002.2),
    ]
    expected = order_of(build(spans))
    for rotation in range(len(spans)):
        shuffled = spans[rotation:] + spans[:rotation]
        assert order_of(build(shuffled)) == expected


def test_temporal_edges_do_not_decide_the_order():
    # They are derived from the timestamps that already break ties; letting
    # them into the sort would give a computed relation the last word.
    spans = [a_span("a", started=2.0), a_span("b", started=1.0)]
    assert order_of(build(spans)) == order_of(build(spans, temporal=False))


# --------------------------------------------------------------------------
# Cycles: still a graph, never a hang
# --------------------------------------------------------------------------


def test_a_parent_cycle_still_produces_a_graph():
    graph = build(
        [
            a_span("a", "b", started=1.0),
            a_span("b", "c", started=2.0),
            a_span("c", "a", started=3.0),
        ]
    )
    assert set(order_of(graph)) == {"a", "b", "c"}
    assert codes.ORDERING_CYCLE in codes_of(graph)


def test_a_cycle_is_ordered_by_the_tie_break_alone():
    graph = build([a_span("b", "a", started=2.0), a_span("a", "b", started=1.0)])
    assert order_of(graph) == ["a", "b"]


def test_a_self_parenting_span_does_not_hang():
    graph = build([a_span("a", "a", started=1.0)])
    assert order_of(graph) == ["a"]
    assert codes.ORDERING_CYCLE in codes_of(graph)


def test_a_cycle_does_not_take_the_rest_of_the_graph_with_it():
    graph = build(
        [
            a_span("root", started=1.0),
            a_span("kid", "root", started=2.0),
            a_span("a", "b", started=3.0),
            a_span("b", "a", started=4.0),
        ]
    )
    assert order_of(graph)[:2] == ["root", "kid"]
    assert set(order_of(graph)) == {"root", "kid", "a", "b"}


def test_the_cycle_diagnostic_names_the_nodes_involved():
    graph = build([a_span("a", "b", started=1.0), a_span("b", "a", started=2.0)])
    cycle = next(d for d in graph.diagnostics if d.code == codes.ORDERING_CYCLE)
    assert cycle.source == ["a", "b"]


def test_a_cycle_through_call_result_is_caught_too():
    graph = build(
        [
            a_span("a", "b", started=1.0, call_id="c", call_role=CallRole.REQUESTER),
            a_span("b", started=2.0, call_id="c", call_role=CallRole.FULFILLER),
        ]
    )
    assert set(order_of(graph)) == {"a", "b"}
    assert codes.ORDERING_CYCLE in codes_of(graph)
