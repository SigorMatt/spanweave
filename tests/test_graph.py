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
                call_ids=("call_a",),
                call_role=CallRole.REQUESTER,
            ),
            a_span(
                "s2",
                "s0",
                started=1001.2,
                kind=NodeKind.TOOL,
                call_ids=("call_a",),
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
    # s1 reaches s2 by call_result AND by temporal, and s2 is still one node.
    assert graph.children("s1", edge_kinds={"call_result", "temporal"}) == ("s2",)
    assert graph.parents("s2", edge_kinds=None) == ("s1", "s0")


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


@pytest.fixture
def linked():
    """s0 -> s1 by parent AND link; s1 -> foreign by link only."""
    return build_graph(
        [
            a_span("s0", started=1.0, links=(SpanLink(span_id="s1"),)),
            a_span(
                "s1",
                "s0",
                started=2.0,
                links=(SpanLink(span_id="foreign", trace_id="t2"),),
            ),
        ],
        adapter=ADAPTER,
    )


def test_a_link_to_a_foreign_span_is_traversable_but_resolves_to_nothing(linked):
    assert linked.children("s1", edge_kinds="link") == ("foreign",)
    # The contract, not a bug: the edge exists and names its target, so the id
    # is reported; it simply does not resolve (SPEC.md §4.0).
    assert linked.node("foreign") is None
    assert "foreign" not in linked


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("descendants", ("foreign",)),
        ("reachable", ("foreign",)),
        # s0 links to s1 as well as parenting it, so s1's link-ancestor is s0.
        ("ancestors", ("s0",)),
    ],
)
def test_traversal_reports_a_foreign_target_rather_than_hiding_it(
    linked, query, expected
):
    assert getattr(linked, query)("s1", edge_kinds="link") == expected


def test_reachable_from_the_root_includes_the_foreign_target(linked):
    assert linked.reachable("s0") == ("s1", "foreign")


def test_paths_can_end_at_a_foreign_target(linked):
    assert linked.paths("s0", "foreign") == (("s0", "s1", "foreign"),)


def test_parents_of_a_foreign_target_names_the_span_that_linked_it(linked):
    assert linked.parents("foreign", edge_kinds="link") == ("s1",)


def test_a_subgraph_keeps_a_dangling_link_edge(linked):
    only_links = linked.subgraph(edge_kinds={"link"})
    assert ("s1", "foreign") in [(e.src, e.dst) for e in only_links.edges()]
    # The foreign span is still not a node, in the projection or out of it.
    assert [n.id for n in only_links.nodes()] == ["s0", "s1"]


def test_topological_order_excludes_a_foreign_target(linked):
    assert linked.topo_order == ("s0", "s1")


def test_the_documented_way_to_resolve_ids_survives_a_foreign_target(linked):
    # The line that bites is `graph.node(i).kind`; this is the fix the
    # docstring names, and it must actually work.
    resolved = [n for i in linked.reachable("s0") if (n := linked.node(i))]
    assert [n.id for n in resolved] == ["s1"]


def test_a_dangling_parent_behaves_the_opposite_way(linked):
    # The asymmetry SPEC.md §4.0 exists to state: a parent reference to an
    # absent span produces NO edge and a diagnostic; a link produces an edge
    # and no diagnostic.
    orphaned = build_graph([a_span("kid", "gone", started=1.0)], adapter=ADAPTER)
    assert orphaned.edges(kind="parent") == ()
    assert [d.code for d in orphaned.diagnostics] == ["orphan_parent"]
    assert linked.edges(kind="link") != ()
    assert [d.code for d in linked.diagnostics] == []


def test_a_node_reached_by_two_kinds_of_edge_is_still_one_node(linked):
    # s0 -> s1 exists as BOTH parent and link. len(children(x)) is a count of
    # nodes; one result per relation is what edges() is for.
    assert linked.children("s0", edge_kinds=None) == ("s1",)


def test_paths_are_not_repeated_once_per_edge(linked):
    assert linked.paths("s0", "s1", edge_kinds=None) == (("s0", "s1"),)


def test_the_edge_set_still_reports_every_relation(linked):
    both = [(e.kind, e.src, e.dst) for e in linked.edges() if e.dst == "s1"]
    assert len(both) == 2  # one parent, one link


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


def test_an_annotation_too_deep_to_encode_is_refused_not_a_traceback(graph):
    # The same finding as the reader's (September 2026 audit, finding 3, batch
    # A6): `json.dumps` answers nesting it will not descend with
    # RecursionError, which is not a ValueError, so this check -- whose whole
    # job is "will this survive the graph file?" -- let it through and the
    # traceback surfaced later, from the writer.
    value = []
    for _ in range(100_000):
        value = [value]
    with pytest.raises(ValueError, match="JSON-serializable"):
        graph.annotate("s1", "ns", "k", value)


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


# --------------------------------------------------------------------------
# What annotating copies, and what it shares
#
# Annotating rebuilt the node index and both adjacency maps every time, so
# labeling a graph cost O(nodes + edges) per label -- 2,000 annotations on a
# 3,001-node graph took tens of seconds, and the work was pure waste: nodes
# and edges are the one thing an annotation cannot change. These tests hold
# the structural property (the indexes are shared, so the per-annotation work
# does not grow with the graph) rather than a wall-clock number, which would
# be a flake. The measurement lives in the commit message.
# --------------------------------------------------------------------------


def test_annotating_shares_the_node_and_edge_indexes(graph):
    annotated = graph.annotate("s2", "ns", "k", 1)
    # Same nodes, same edges -- so the same lookup structures, not copies of
    # them. This identity is what makes annotating O(1) in the graph's size.
    assert annotated._index is graph._index
    assert annotated._out is graph._out
    assert annotated._in is graph._in
    assert annotated._nodes is graph._nodes
    assert annotated._edges is graph._edges


def test_a_shared_index_carries_nothing_between_graphs(graph):
    # The sharing must not become a channel: annotating one graph must be
    # invisible from every other graph that shares its indexes.
    first = graph.annotate("s1", "ns", "k", 1)
    second = first.annotate("s2", "ns", "k", 2)
    third = first.annotate("s3", "ns", "k", 3)

    assert len(graph.annotations) == 0
    assert graph.annotations_for("s1", "ns") == {}
    assert [e.sort_key for e in first.annotations] == [("ns", "s1", "k")]
    assert first.annotations_for("s2", "ns") == {}
    assert first.annotations_for("s3", "ns") == {}
    assert second.annotations_for("s3", "ns") == {}
    assert third.annotations_for("s2", "ns") == {}
    # The annotation stores are separate objects with separate indexes; only
    # the node/edge structures are shared.
    assert second.annotations is not third.annotations
    assert second.annotations._index is not third.annotations._index
    # And the queries that read the shared structures still agree everywhere.
    for other in (first, second, third):
        assert other.topo_order == graph.topo_order
        assert other.edges() == graph.edges()
        assert other.children("s0") == graph.children("s0")
        assert other.node("s2") == graph.node("s2")


def test_an_annotated_graph_carries_every_field_a_built_one_has(graph):
    # The shared-index copy sets each field explicitly; a field added to Graph
    # later must not silently go missing from an annotated graph.
    import dataclasses

    annotated = graph.annotate("s1", "ns", "k", 1)
    for graph_field in dataclasses.fields(graph):
        if graph_field.name == "annotations":
            continue
        assert getattr(annotated, graph_field.name) == getattr(
            graph, graph_field.name
        ), graph_field.name


def test_the_work_of_annotating_does_not_grow_with_the_graph(graph):
    # The audit's case (probe2 E) in structural form: many annotations, one
    # shared set of indexes throughout, and the last graph still correct.
    annotated = graph
    for index in range(200):
        annotated = annotated.annotate("s2", "ns", f"k{index}", index)
        assert annotated._index is graph._index
        assert annotated._out is graph._out
        assert annotated._in is graph._in
    assert len(annotated.annotations) == 200
    assert annotated.annotations_for("s2", "ns")["k199"] == 199
    assert len(graph.annotations) == 0


# --------------------------------------------------------------------------
# annotate_many
# --------------------------------------------------------------------------


def test_annotate_many_equals_annotating_one_at_a_time(graph):
    entries = [
        ("s3", "b", "k", 1),
        ("s1", "a", "k", 2),
        ("s1", "a", "other", 3),
        ("s2", "a", "k", 4),
    ]
    batched = graph.annotate_many(entries)
    sequential = graph
    for entry in entries:
        sequential = sequential.annotate(*entry)
    assert batched.annotations.entries == sequential.annotations.entries
    assert [e.sort_key for e in batched.annotations] == [
        e.sort_key for e in sequential.annotations
    ]


def test_annotate_many_lets_the_later_entry_win_on_the_same_key(graph):
    # Same rule as annotating the same key twice, because the batch is
    # *defined* as that sequence (`SPEC.md` §8).
    entries = [("s2", "ns", "k", 1), ("s2", "ns", "k", 2)]
    batched = graph.annotate_many(entries)
    sequential = graph.annotate(*entries[0]).annotate(*entries[1])
    assert batched.annotations_for("s2", "ns") == {"k": 2}
    assert batched.annotations.entries == sequential.annotations.entries
    assert len(batched.annotations) == 1


def test_annotate_many_returns_a_new_graph_and_shares_the_indexes(graph):
    batched = graph.annotate_many([("s1", "ns", "k", 1), ("s2", "ns", "k", 2)])
    assert batched is not graph
    assert len(graph.annotations) == 0
    assert batched._index is graph._index
    assert batched._out is graph._out
    assert batched._in is graph._in


def test_annotate_many_accepts_an_empty_batch(graph):
    batched = graph.annotate_many([])
    assert batched is not graph
    assert len(batched.annotations) == 0
    assert batched.topo_order == graph.topo_order


def test_annotate_many_takes_any_iterable(graph):
    batched = graph.annotate_many(("s1", "ns", "k", i) for i in range(3))
    assert batched.annotations_for("s1", "ns") == {"k": 2}


def test_annotate_many_refuses_a_bad_entry_and_applies_nothing(graph):
    with pytest.raises(ValueError, match="no node"):
        graph.annotate_many([("s1", "ns", "k", 1), ("nope", "ns", "k", 2)])
    with pytest.raises(ValueError, match="reserved"):
        graph.annotate_many([("s1", "spanweave", "k", 1)])
    with pytest.raises(ValueError, match="JSON-serializable"):
        graph.annotate_many([("s1", "ns", "k", {1, 2, 3})])
    # The refusal costs the caller the batch, not half of it: nothing was
    # written anywhere the caller can see.
    assert len(graph.annotations) == 0


def test_annotate_many_is_insensitive_to_nothing_but_its_order(graph):
    one = graph.annotate_many([("s3", "b", "k", 1), ("s1", "a", "k", 2)])
    other = graph.annotate_many([("s1", "a", "k", 2), ("s3", "b", "k", 1)])
    assert one.annotations.entries == other.annotations.entries
    assert [e.sort_key for e in one.annotations] == [("a", "s1", "k"), ("b", "s3", "k")]


def test_annotate_many_never_changes_what_the_library_does(graph):
    batched = graph.annotate_many([("s1", "ns", "kind", "tool")])
    assert [n.id for n in batched.nodes(kind="tool")] == ["s2"]
    assert batched.edges() == graph.edges()
    assert batched.topo_order == graph.topo_order
    assert [n.id for n in batched.nodes(annotated=("ns", "kind", "tool"))] == ["s1"]
