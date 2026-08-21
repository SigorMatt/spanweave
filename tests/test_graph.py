"""The query surface and annotations (TASKS.md 1.7).

The queries exist so that a consumer can pick the structure it trusts rather
than accept the one we picked (`DESIGN.md` §1), so most of these tests are
about projections disagreeing with each other on purpose.
"""

import pytest

from spanweave.build import build_graph
from spanweave.model import AdapterInfo, EdgeKind, NodeKind, RawRecord, Warrant
from spanweave.seam import CallRole, NormalizedSpan, SpanLink

ADAPTER = AdapterInfo(id="some_dialect", version="0.1.0")


def a_span(span_id, parent=None, started=None, kind=NodeKind.CHAIN, **overrides):
    return NormalizedSpan(
        source_key=span_id,
        span_id=span_id,
        parent_id=parent,
        trace_id="t1",
        kind=kind,
        name=f"op.{span_id}",
        started_at=started,
        raw=RawRecord(source={"span_id": span_id}),
        **overrides,
    )


@pytest.fixture
def graph():
    """The worked example's shape: an agent, two llm calls, one tool."""
    return build_graph(
        [
            a_span("s0", started=1000.0, kind=NodeKind.AGENT),
            a_span(
                "s1",
                "s0",
                started=1000.2,
                kind=NodeKind.LLM,
                call_id="call_a",
                call_role=CallRole.REQUESTER,
            ),
            a_span(
                "s2",
                "s0",
                started=1001.2,
                kind=NodeKind.TOOL,
                call_id="call_a",
                call_role=CallRole.FULFILLER,
            ),
            a_span("s3", "s0", started=1002.2, kind=NodeKind.LLM),
        ],
        adapter=ADAPTER,
    )


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_nodes_returns_everything_in_the_graphs_order(graph):
    assert [n.id for n in graph.nodes()] == ["s0", "s1", "s2", "s3"]
    assert graph.topo_order == ("s0", "s1", "s2", "s3")


def test_nodes_filter_by_kind(graph):
    assert [n.id for n in graph.nodes(kind="llm")] == ["s1", "s3"]
    assert [n.id for n in graph.nodes(kind=NodeKind.TOOL)] == ["s2"]
    assert [n.id for n in graph.nodes(kind={"llm", "tool"})] == ["s1", "s2", "s3"]


def test_an_unknown_kind_filter_returns_nothing_rather_than_failing(graph):
    assert graph.nodes(kind="guardrail") == ()


def test_edges_filter_by_kind_and_by_warrant(graph):
    assert len(graph.edges(kind="parent")) == 3
    assert len(graph.edges(kind=EdgeKind.CALL_RESULT)) == 1
    # The distinction the whole design turns on: what was stated, and what we
    # computed (SPEC.md §4.1).
    assert all(e.warrant is Warrant.EXPLICIT for e in graph.edges(warrant="explicit"))
    assert {e.kind for e in graph.edges(warrant=Warrant.DERIVED)} == {EdgeKind.TEMPORAL}


def test_filters_compose(graph):
    assert graph.edges(kind="temporal", warrant="explicit") == ()


def test_node_lookup_returns_none_for_a_stranger(graph):
    assert graph.node("s0").kind is NodeKind.AGENT
    assert graph.node("nope") is None
    assert "s0" in graph and "nope" not in graph
    assert len(graph) == 4


# --------------------------------------------------------------------------
# Traversal
# --------------------------------------------------------------------------


def test_children_and_parents_walk_containment_by_default(graph):
    assert graph.children("s0") == ("s1", "s2", "s3")
    assert graph.parents("s2") == ("s0",)
    assert graph.parents("s0") == ()


def test_traversal_can_walk_any_kinds_asked_for(graph):
    assert graph.children("s1", edge_kinds="call_result") == ("s2",)
    assert graph.children("s1", edge_kinds={"call_result", "temporal"}) == ("s2", "s2")
    assert graph.parents("s2", edge_kinds=None) == ("s1", "s0", "s1")


def test_ancestors_and_descendants_are_transitive(graph):
    deep = build_graph(
        [
            a_span("a", started=1.0),
            a_span("b", "a", started=2.0),
            a_span("c", "b", started=3.0),
        ],
        adapter=ADAPTER,
    )
    assert deep.descendants("a") == ("b", "c")
    assert deep.ancestors("c") == ("b", "a")


def test_reachable_is_where_the_transitive_closure_lives(graph):
    # temporal edges connect consecutive siblings only, so "everything after
    # s1" is computed here rather than materialized in the edge set
    # (SPEC.md §4.3).
    assert graph.reachable("s1", edge_kinds="temporal") == ("s2", "s3")
    assert graph.edges(kind="temporal") != ()
    assert ("s1", "s3") not in [(e.src, e.dst) for e in graph.edges(kind="temporal")]


def test_traversal_terminates_on_a_cycle():
    cyclic = build_graph(
        [a_span("a", "b", started=1.0), a_span("b", "a", started=2.0)], adapter=ADAPTER
    )
    assert cyclic.reachable("a") == ("b",)
    assert cyclic.descendants("a") == ("b",)


def test_a_link_to_a_foreign_span_is_traversable_but_resolves_to_nothing():
    linked = build_graph(
        [
            a_span(
                "s0", started=1.0, links=(SpanLink(span_id="foreign", trace_id="t2"),)
            )
        ],
        adapter=ADAPTER,
    )
    assert linked.children("s0", edge_kinds="link") == ("foreign",)
    assert linked.node("foreign") is None


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def test_paths_finds_the_routes_between_two_nodes(graph):
    assert graph.paths("s0", "s2", edge_kinds="parent") == (("s0", "s2"),)
    both = graph.paths("s0", "s2", edge_kinds={"parent", "call_result"})
    assert set(both) == {("s0", "s2"), ("s0", "s1", "s2")}


def test_paths_are_empty_when_the_projection_disconnects_them(graph):
    # The same pair, unreachable once you only trust containment.
    assert graph.paths("s1", "s2", edge_kinds="parent") == ()
    assert graph.paths("s1", "s2", edge_kinds="call_result") == (("s1", "s2"),)


def test_paths_terminate_on_a_cycle():
    cyclic = build_graph(
        [
            a_span("a", "c", started=1.0),
            a_span("b", "a", started=2.0),
            a_span("c", "b", started=3.0),
        ],
        adapter=ADAPTER,
    )
    assert cyclic.paths("a", "c", edge_kinds="parent") == (("a", "b", "c"),)


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------


def test_subgraph_keeps_the_nodes_and_drops_the_edges_you_did_not_ask_for(graph):
    tree = graph.subgraph(edge_kinds={"parent"})
    assert [n.id for n in tree.nodes()] == [n.id for n in graph.nodes()]
    assert {e.kind for e in tree.edges()} == {EdgeKind.PARENT}


def test_the_three_projections_disagree_and_that_is_the_point(graph):
    tree = graph.subgraph(edge_kinds={"parent"})
    grounded = graph.subgraph(edge_kinds={"parent", "call_result"})
    timeline = graph.subgraph(edge_kinds={"temporal"})
    assert tree.paths("s1", "s2") == ()
    assert grounded.paths("s1", "s2", edge_kinds=None) == (("s1", "s2"),)
    assert timeline.children("s1", edge_kinds="temporal") == ("s2",)
    # Nobody is forced to accept an inference they did not ask for.
    assert timeline.edges(warrant="explicit") == ()


def test_a_subgraph_keeps_isolated_nodes():
    # Dropping them would be a judgement about which nodes matter, and that
    # belongs to whoever is doing the projecting.
    graph = build_graph([a_span("lonely", started=1.0)], adapter=ADAPTER)
    assert len(graph.subgraph(edge_kinds={"data"}).nodes()) == 1


def test_a_subgraph_keeps_the_diagnostics_and_meta(graph):
    tree = graph.subgraph(edge_kinds={"parent"})
    assert tree.diagnostics == graph.diagnostics
    assert tree.meta == graph.meta


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------


def test_annotating_returns_a_new_graph_and_leaves_the_original_alone(graph):
    annotated = graph.annotate("s2", "my_evals", "reviewed", True)
    assert annotated is not graph
    assert annotated.annotations_for("s2", "my_evals") == {"reviewed": True}
    # The original is untouched, which is what keeps pipelines composable.
    assert graph.annotations_for("s2", "my_evals") == {}
    assert len(graph.annotations) == 0


def test_annotations_are_namespaced_per_consumer(graph):
    annotated = graph.annotate("s2", "one", "label", "a").annotate(
        "s2", "two", "label", "b"
    )
    assert annotated.annotations_for("s2", "one") == {"label": "a"}
    assert annotated.annotations_for("s2", "two") == {"label": "b"}


def test_setting_the_same_key_twice_replaces_it(graph):
    annotated = graph.annotate("s2", "ns", "k", 1).annotate("s2", "ns", "k", 2)
    assert annotated.annotations_for("s2", "ns") == {"k": 2}
    assert len(annotated.annotations) == 1


def test_nodes_can_be_selected_by_annotation(graph):
    annotated = graph.annotate("s1", "ns", "looked_at", True).annotate(
        "s3", "ns", "looked_at", False
    )
    selected = annotated.nodes(annotated=("ns", "looked_at", True))
    assert [n.id for n in selected] == ["s1"]


def test_annotations_are_ordered_deterministically(graph):
    one = graph.annotate("s3", "b", "k", 1).annotate("s1", "a", "k", 2)
    other = graph.annotate("s1", "a", "k", 2).annotate("s3", "b", "k", 1)
    assert [e.sort_key for e in one.annotations] == [
        e.sort_key for e in other.annotations
    ]
    assert [e.sort_key for e in one.annotations] == [("a", "s1", "k"), ("b", "s3", "k")]


def test_the_library_namespace_is_reserved(graph):
    with pytest.raises(ValueError, match="reserved"):
        graph.annotate("s1", "spanweave", "kind", "special")


def test_an_annotation_must_be_json_serializable(graph):
    with pytest.raises(ValueError, match="JSON-serializable"):
        graph.annotate("s1", "ns", "k", {1, 2, 3})


def test_annotating_a_node_that_is_not_here_is_refused(graph):
    # Silently keeping it would mean nothing ever reads it.
    with pytest.raises(ValueError, match="no node"):
        graph.annotate("nope", "ns", "k", 1)


def test_an_annotation_never_changes_what_the_library_does(graph):
    annotated = graph.annotate("s1", "ns", "kind", "tool")
    # The library has no idea what is in there -- that is the entire point.
    assert [n.id for n in annotated.nodes(kind="tool")] == ["s2"]
    assert annotated.edges() == graph.edges()
    assert annotated.topo_order == graph.topo_order


def test_annotations_survive_a_projection(graph):
    annotated = graph.annotate("s1", "ns", "k", 1)
    assert annotated.subgraph(edge_kinds={"parent"}).annotations_for("s1", "ns") == {
        "k": 1
    }
