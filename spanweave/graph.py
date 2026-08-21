"""The graph: nodes, edges, diagnostics, meta -- and nothing that judges them.

The output object, and the whole consumer surface. Immutable, deterministically
ordered, and free of any opinion about what any of it means (``SPEC.md`` §3.9).

The queries are the answer to the shape problem (``DESIGN.md`` §1). One
consumer wants a containment tree, the next wants a linear trajectory, the
next wants a dataflow DAG -- so rather than pick one, the graph carries all of
them at once, each edge labelled with its kind and its warrant, and lets the
consumer project out the structure it trusts:

    tree     = graph.subgraph(edge_kinds={"parent"})
    grounded = graph.subgraph(edge_kinds={"parent", "call_result"})
    timeline = graph.subgraph(edge_kinds={"temporal"})

Every downstream disagreement about "what an edge means" becomes a selection
over ``EdgeKind`` x ``Warrant``, rather than a fork of the library.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from spanweave import annotate as annotations_module
from spanweave.annotate import AnnotationStore
from spanweave.model import (
    Diagnostic,
    Edge,
    EdgeKind,
    JsonValue,
    Meta,
    Node,
    NodeId,
    NodeKind,
    Warrant,
)

#: The edges a consumer walks when it wants relations the telemetry actually
#: stated. Offered as a name because "parent plus call_result" is the single
#: most common projection, not because the library prefers it.
STATED_KINDS = frozenset({EdgeKind.PARENT, EdgeKind.CALL_RESULT})

Kinds = Iterable[EdgeKind | str] | EdgeKind | str | None


def _once(ids: Iterable[NodeId]) -> tuple[NodeId, ...]:
    """Each id once, in first-appearance order.

    Node-returning queries answer "which nodes", so a node reached by two
    kinds of edge is still one node -- `len(children(x))` must be a count of
    nodes, not of relations. Ask `edges()` when you want one result per
    relation. Order comes from the edge tuple, which is already totally
    ordered, so deduplicating here keeps determinism intact.
    """
    seen: dict[NodeId, None] = {}
    for node_id in ids:
        seen.setdefault(node_id, None)
    return tuple(seen)


def _kinds(selector: Kinds) -> frozenset[str] | None:
    if selector is None:
        return None
    if isinstance(selector, EdgeKind | str):
        return frozenset({str(selector)})
    return frozenset(str(kind) for kind in selector)


def _node_kinds(
    selector: Iterable[NodeKind | str] | NodeKind | str | None,
) -> frozenset[str] | None:
    if selector is None:
        return None
    if isinstance(selector, NodeKind | str):
        return frozenset({str(selector)})
    return frozenset(str(kind) for kind in selector)


@dataclass(frozen=True, slots=True)
class Graph:
    """One trace, normalized."""

    trace_id: str
    #: In deterministic order: a topological sort over `parent` and
    #: `call_result`, tie-broken by `(started_at or +inf, node_id)`. Private
    #: because the public surface is the accessor `graph.nodes(...)`, which a
    #: field of the same name cannot coexist with. Build one with `Graph.of`.
    _nodes: tuple[Node, ...] = ()
    #: Sorted by `(kind, src, dst, basis)`. See `_nodes` for the underscore.
    _edges: tuple[Edge, ...] = ()
    #: Sorted by `(code, node_id, message)`.
    diagnostics: tuple[Diagnostic, ...] = ()
    meta: Meta | None = None
    annotations: AnnotationStore = field(default_factory=AnnotationStore)
    _index: Mapping[NodeId, Node] = field(default_factory=dict, repr=False)
    _out: Mapping[NodeId, tuple[Edge, ...]] = field(default_factory=dict, repr=False)
    _in: Mapping[NodeId, tuple[Edge, ...]] = field(default_factory=dict, repr=False)

    @classmethod
    def of(
        cls,
        trace_id: str,
        nodes: tuple[Node, ...] = (),
        edges: tuple[Edge, ...] = (),
        diagnostics: tuple[Diagnostic, ...] = (),
        meta: Meta | None = None,
        annotations: AnnotationStore | None = None,
    ) -> Graph:
        """Build a graph by the names the specs use."""
        return cls(
            trace_id=trace_id,
            _nodes=nodes,
            _edges=edges,
            diagnostics=diagnostics,
            meta=meta,
            annotations=annotations if annotations is not None else AnnotationStore(),
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {node.id: node for node in self._nodes})
        out: dict[NodeId, list[Edge]] = {}
        incoming: dict[NodeId, list[Edge]] = {}
        # Built from the edge tuple, which is already totally ordered, so every
        # traversal below inherits that order rather than inventing one.
        for edge in self._edges:
            out.setdefault(edge.src, []).append(edge)
            incoming.setdefault(edge.dst, []).append(edge)
        object.__setattr__(self, "_out", {k: tuple(v) for k, v in out.items()})
        object.__setattr__(self, "_in", {k: tuple(v) for k, v in incoming.items()})

    # -- lookup ------------------------------------------------------------

    def node(self, node_id: NodeId) -> Node | None:
        """The node with this id, or ``None``.

        ``None`` rather than an exception because a `link` edge may legally
        point at a span that has no node here (`SPEC.md` §4): asking about a
        foreign target is a normal thing to do, not an error.

        **This is the contract, and traversal relies on it.** ``children``,
        ``parents``, ``descendants``, ``ancestors``, ``reachable`` and
        ``paths`` report ids exactly as the edges name them, including a
        cross-trace link target that has no node here. The edge exists and
        names its target; dropping the id would hide a relation the telemetry
        stated. So a consumer resolving ids must expect ``None`` --
        ``graph.node(i).kind`` is the line that will bite, and
        ``[n for i in ids if (n := graph.node(i))]`` is the fix.
        """
        return self._index.get(node_id)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._index

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def topo_order(self) -> tuple[NodeId, ...]:
        """Node ids in the graph's canonical order."""
        return tuple(node.id for node in self._nodes)

    # -- selection ---------------------------------------------------------

    def nodes(
        self,
        kind: Iterable[NodeKind | str] | NodeKind | str | None = None,
        annotated: tuple[str, str, JsonValue] | None = None,
    ) -> tuple[Node, ...]:
        """The nodes, optionally filtered. Always in the graph's order."""
        wanted = _node_kinds(kind)
        matching = (
            self.annotations.nodes_with(*annotated) if annotated is not None else None
        )
        return tuple(
            node
            for node in self._nodes
            if (wanted is None or str(node.kind) in wanted)
            and (matching is None or node.id in matching)
        )

    def edges(
        self, kind: Kinds = None, warrant: Warrant | str | None = None
    ) -> tuple[Edge, ...]:
        """The edges, optionally filtered by kind and by warrant."""
        wanted = _kinds(kind)
        return tuple(
            edge
            for edge in self._edges
            if (wanted is None or str(edge.kind) in wanted)
            and (warrant is None or str(edge.warrant) == str(warrant))
        )

    # -- traversal ---------------------------------------------------------

    def children(
        self, node_id: NodeId, edge_kinds: Kinds = EdgeKind.PARENT
    ) -> tuple[NodeId, ...]:
        """Ids this node points at, over the chosen kinds. Each once."""
        return _once(edge.dst for edge in self._select(self._out, node_id, edge_kinds))

    def parents(
        self, node_id: NodeId, edge_kinds: Kinds = EdgeKind.PARENT
    ) -> tuple[NodeId, ...]:
        """Ids that point at this node, over the chosen kinds. Each once."""
        return _once(edge.src for edge in self._select(self._in, node_id, edge_kinds))

    def _select(
        self,
        adjacency: Mapping[NodeId, tuple[Edge, ...]],
        node_id: NodeId,
        edge_kinds: Kinds,
    ) -> tuple[Edge, ...]:
        wanted = _kinds(edge_kinds)
        return tuple(
            edge
            for edge in adjacency.get(node_id, ())
            if wanted is None or str(edge.kind) in wanted
        )

    def descendants(
        self, node_id: NodeId, edge_kinds: Kinds = EdgeKind.PARENT
    ) -> tuple[NodeId, ...]:
        return self._walk(node_id, edge_kinds, forwards=True)

    def ancestors(
        self, node_id: NodeId, edge_kinds: Kinds = EdgeKind.PARENT
    ) -> tuple[NodeId, ...]:
        return self._walk(node_id, edge_kinds, forwards=False)

    def reachable(
        self, node_id: NodeId, edge_kinds: Kinds = None
    ) -> tuple[NodeId, ...]:
        """Everything downstream, over any kinds asked for.

        This is where the transitive closure lives, rather than in the edge
        set: `temporal` edges connect consecutive siblings only, and a
        consumer that wants "everything after this" computes it here
        (`SPEC.md` §4.3).
        """
        return self._walk(node_id, edge_kinds, forwards=True)

    def _walk(
        self, node_id: NodeId, edge_kinds: Kinds, *, forwards: bool
    ) -> tuple[NodeId, ...]:
        wanted = _kinds(edge_kinds)
        adjacency = self._out if forwards else self._in
        seen: list[NodeId] = []
        found: set[NodeId] = set()
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            for edge in adjacency.get(current, ()):
                if wanted is not None and str(edge.kind) not in wanted:
                    continue
                nxt = edge.dst if forwards else edge.src
                # A cycle in malformed telemetry must not hang a query any
                # more than it may hang a build.
                if nxt in found or nxt == node_id:
                    continue
                found.add(nxt)
                seen.append(nxt)
                queue.append(nxt)
        return tuple(seen)

    def paths(
        self, src: NodeId, dst: NodeId, edge_kinds: Kinds = None
    ) -> tuple[tuple[NodeId, ...], ...]:
        """Every simple path from `src` to `dst`, in a deterministic order.

        Simple: a node appears at most once, so a cycle bounds the search
        instead of unbounding it.
        """
        found: list[tuple[NodeId, ...]] = []

        def walk(current: NodeId, trail: tuple[NodeId, ...]) -> None:
            if current == dst and len(trail) > 0:
                found.append((*trail, current))
                return
            # Unique next ids, not unique edges: two kinds may connect the
            # same pair, and walking both would return the same path twice.
            for nxt in _once(
                edge.dst for edge in self._select(self._out, current, edge_kinds)
            ):
                if nxt in trail or nxt == current:
                    continue
                walk(nxt, (*trail, current))

        walk(src, ())
        return tuple(found)

    # -- projection --------------------------------------------------------

    def subgraph(self, edge_kinds: Kinds) -> Graph:
        """The same nodes, only the edges you trust.

        Nodes are kept whole: dropping the ones a projection leaves isolated
        would be a judgement about which nodes matter, and that belongs to the
        consumer doing the projecting.
        """
        return Graph.of(
            trace_id=self.trace_id,
            nodes=self._nodes,
            edges=self.edges(kind=edge_kinds),
            diagnostics=self.diagnostics,
            meta=self.meta,
            annotations=self.annotations,
        )

    # -- annotation --------------------------------------------------------

    def annotate(
        self, node_id: NodeId, namespace: str, key: str, value: JsonValue
    ) -> Graph:
        """Attach a namespaced consumer fact, returning a **new** graph."""
        return annotations_module.annotate(self, node_id, namespace, key, value)

    def annotations_for(
        self, node_id: NodeId, namespace: str
    ) -> Mapping[str, JsonValue]:
        return self.annotations.for_node(node_id, namespace)
