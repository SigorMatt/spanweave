"""The builder: spans in, a graph out.

Below the seam nothing here knows a dialect exists (``DESIGN.md`` §3). The
builder is handed ``NormalizedSpan`` values and never an adapter object it
could interrogate; there is a CI gate for both halves of that sentence.

What it does is join and account: give every span an id, turn the relations
the telemetry **stated** into warranted edges, and record everything it could
not resolve as a diagnostic. What it never does is fill a gap with a plausible
guess. An unpaired call stays unpaired.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterable, Sequence

from spanweave import diagnostics as codes
from spanweave.diagnostics import DiagnosticCollector
from spanweave.graph import Graph
from spanweave.ids import assign
from spanweave.model import (
    AdapterInfo,
    DiagnosticLevel,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeId,
    Provenance,
    Warrant,
)
from spanweave.seam import CallRole, NormalizedSpan
from spanweave.version import SCHEMA_VERSION, __version__

PARENT_BASIS = "span.parent_span_id"
CALL_BASIS = "tool_call_id"
TEMPORAL_BASIS = "sibling start_time ordering"

#: When two siblings report the *same* start time, neither started first, and
#: the edge between them records a decision rather than an observation. It
#: still exists -- the order is deterministic and consumers need it -- but it
#: says so in its own basis, so a consumer can tell a tied edge from a strict
#: one by reading the graph instead of the documentation (`SPEC.md` §4.3).
TEMPORAL_TIED_BASIS = "sibling start_time ordering (tied, broken by node_id)"

#: The kinds a node's position is sorted over. `temporal` is deliberately not
#: among them: it is derived from the timestamps that already break ties, so
#: including it would let a computed relation decide the order that a stated
#: one should (`SPEC.md` §5.2).
ORDERING_KINDS = (EdgeKind.PARENT, EdgeKind.CALL_RESULT)


def build_graph(
    spans: Iterable[NormalizedSpan],
    *,
    adapter: AdapterInfo,
    collector: DiagnosticCollector | None = None,
    source_digest: str | None = None,
    temporal: bool = True,
) -> Graph:
    """Turn normalized spans into a graph.

    ``collector`` carries diagnostics raised before this point -- by the
    reader, typically -- so that a malformed line and an unpaired call end up
    in the same list. They are the same kind of statement about the input.

    ``temporal=False`` omits the one derived edge kind, for a consumer that
    wants only what the telemetry stated.
    """
    collected = collector if collector is not None else DiagnosticCollector()
    ordered = list(spans)

    trace_id = _trace_id_of(ordered)
    assignment = assign(ordered, adapter.id, trace_id)
    ids = assignment.ids
    for duplicated in assignment.duplicate_source_ids:
        collected.add(
            codes.DUPLICATE_SOURCE_ID,
            f"the dialect used the span id {duplicated!r} for more than one "
            f"record; both are kept, with ids derived from their source keys "
            f"instead",
            source=duplicated,
            adapter=adapter.id,
        )

    by_span_id = _span_id_index(ordered, ids)
    nodes = tuple(
        _node(span, node_id, adapter)
        for span, node_id in zip(ordered, ids, strict=True)
    )
    _report_span_diagnostics(ordered, ids, collected)
    _report_foreign_traces(ordered, ids, trace_id, collected, adapter)
    _report_nonmonotonic_time(ordered, ids, collected, adapter)

    edges = _explicit_edges(ordered, ids, by_span_id, collected, adapter)
    if temporal:
        edges = _deduplicated([*edges, *_temporal_edges(nodes, edges, collected)])

    nodes = _in_order(nodes, edges, collected)

    return Graph.of(
        trace_id=trace_id or "",
        nodes=nodes,
        edges=edges,
        diagnostics=collected.collected(),
        meta=Meta(
            schema_version=SCHEMA_VERSION,
            spanweave_version=__version__,
            adapters=(adapter,),
            source_digest=source_digest,
            node_count=len(nodes),
            edge_count=len(edges),
            diagnostic_count=len(collected),
        ),
    )


def _tie_break(node: Node) -> tuple[float, str]:
    """`(started_at or +inf, node_id)` -- a determinism invariant (§5.2)."""
    return (node.started_at if node.started_at is not None else float("inf"), node.id)


def _trace_id_of(spans: Sequence[NormalizedSpan]) -> str | None:
    """The trace this input is about: the most common id (`SPEC.md` §7).

    Ties break on the id itself, ascending. An arbitrary rule still has to be
    a *stated* one, or the same input could produce two different graphs.
    """
    counts: dict[str, int] = {}
    for span in spans:
        if span.trace_id is not None:
            counts[span.trace_id] = counts.get(span.trace_id, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda trace: (-counts[trace], trace))


def _span_id_index(
    spans: Sequence[NormalizedSpan], ids: Sequence[NodeId]
) -> dict[str, NodeId]:
    """Where a span id points, for resolving references between records."""
    index: dict[str, NodeId] = {}
    ambiguous: set[str] = set()
    for span, node_id in zip(spans, ids, strict=True):
        if span.span_id is None:
            continue
        if span.span_id in index:
            ambiguous.add(span.span_id)
            continue
        index[span.span_id] = node_id
    for span_id in ambiguous:
        # Two records claim this id and both survived (they had distinct
        # source keys). A reference to it cannot be resolved to one of them,
        # and picking either would be a guess.
        del index[span_id]
    return index


def _node(span: NormalizedSpan, node_id: NodeId, adapter: AdapterInfo) -> Node:
    return Node(
        id=node_id,
        kind=span.kind,
        name=span.name,
        operation=span.operation,
        started_at=span.started_at,
        ended_at=span.ended_at,
        status=span.status,
        status_note=span.status_note,
        inputs=span.inputs,
        outputs=span.outputs,
        usage=span.usage,
        attributes=span.attributes,
        raw=span.raw,
        provenance=Provenance(
            adapter_id=adapter.id,
            adapter_version=adapter.version,
            dialect_note=span.dialect_note,
        ),
    )


def _report_span_diagnostics(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    collected: DiagnosticCollector,
) -> None:
    """Attach the adapter's own diagnostics to the nodes they belong to."""
    for span, node_id in zip(spans, ids, strict=True):
        collected.extend(
            dataclasses.replace(diagnostic, node_id=node_id)
            for diagnostic in span.diagnostics
        )


def _report_foreign_traces(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    trace_id: str | None,
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> None:
    """Records from another trace are kept, and said so (`SPEC.md` §7)."""
    for span, node_id in zip(spans, ids, strict=True):
        if span.trace_id is None or span.trace_id == trace_id:
            continue
        collected.add(
            codes.MULTI_TRACE_INPUT,
            f"this record belongs to trace {span.trace_id!r}, not to "
            f"{trace_id!r}, which is the most common id in this input; the "
            f"record is kept. Splitting a multi-trace input is the "
            f"consumer's call",
            node_id=node_id,
            source=span.trace_id,
            adapter=adapter.id,
        )


def _report_nonmonotonic_time(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> None:
    for span, node_id in zip(spans, ids, strict=True):
        if span.started_at is None or span.ended_at is None:
            continue
        if span.ended_at >= span.started_at:
            continue
        # Reported, never repaired: a clock that ran backwards is a fact
        # about the trace, and correcting it here would hide it.
        collected.add(
            codes.NONMONOTONIC_TIME,
            f"ended_at ({span.ended_at}) precedes started_at "
            f"({span.started_at}); both are kept as reported",
            node_id=node_id,
            source=[span.started_at, span.ended_at],
            adapter=adapter.id,
        )


def _explicit_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    by_span_id: dict[str, NodeId],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> tuple[Edge, ...]:
    """Every relation the telemetry stated. Nothing it merely implied."""
    found: list[Edge] = []
    found.extend(_parent_edges(spans, ids, by_span_id, collected, adapter))
    found.extend(_call_result_edges(spans, ids, collected, adapter))
    found.extend(_link_edges(spans, ids, by_span_id, adapter))
    found.extend(_data_edges(spans, ids, by_span_id, adapter))
    return _deduplicated(found)


def _parent_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    by_span_id: dict[str, NodeId],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> list[Edge]:
    edges = []
    for span, node_id in zip(spans, ids, strict=True):
        if span.parent_id is None:
            continue
        parent = by_span_id.get(span.parent_id)
        if parent is None:
            # The node stays. A trace that starts mid-run is ordinary, and
            # dropping the record would lose more than the missing parent did.
            collected.add(
                codes.ORPHAN_PARENT,
                f"parent span {span.parent_id!r} is not in this input; the "
                f"node is kept and no parent edge is made",
                node_id=node_id,
                source=span.parent_id,
                adapter=adapter.id,
            )
            continue
        edges.append(
            Edge(
                src=parent,
                dst=node_id,
                kind=EdgeKind.PARENT,
                warrant=Warrant.EXPLICIT,
                basis=PARENT_BASIS,
                adapter=adapter.id,
            )
        )
    return edges


def _call_result_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> list[Edge]:
    """Join requester to fulfiller on the id the dialect carried.

    Never on name, proximity, or timing. A guessed pairing is
    indistinguishable from a real one downstream, which is exactly the harm
    the warrant system exists to prevent (`SPEC.md` §4.4).
    """
    requesters: dict[str, list[NodeId]] = {}
    fulfillers: dict[str, list[NodeId]] = {}
    for span, node_id in zip(spans, ids, strict=True):
        if not span.call_ids or span.call_role is None:
            continue
        side = requesters if span.call_role is CallRole.REQUESTER else fulfillers
        for call_id in span.call_ids:
            side.setdefault(call_id, []).append(node_id)

    edges = []
    for call_id in sorted(set(requesters) | set(fulfillers)):
        asked = sorted(requesters.get(call_id, ()))
        answered = sorted(fulfillers.get(call_id, ()))
        if not answered:
            for node_id in asked:
                collected.add(
                    codes.UNPAIRED_CALL,
                    f"call {call_id!r} was requested and no span in this input "
                    f"fulfils it; no edge is invented",
                    node_id=node_id,
                    source=call_id,
                    adapter=adapter.id,
                )
            continue
        if not asked:
            for node_id in answered:
                collected.add(
                    codes.UNPAIRED_RESULT,
                    f"call {call_id!r} was fulfilled but no span in this input "
                    f"requests it; no edge is invented",
                    node_id=node_id,
                    source=call_id,
                    adapter=adapter.id,
                )
            continue
        for source in asked:
            for target in answered:
                edges.append(
                    Edge(
                        src=source,
                        dst=target,
                        kind=EdgeKind.CALL_RESULT,
                        warrant=Warrant.EXPLICIT,
                        basis=CALL_BASIS,
                        adapter=adapter.id,
                    )
                )
    return edges


def _link_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    by_span_id: dict[str, NodeId],
    adapter: AdapterInfo,
) -> list[Edge]:
    """Links are transcribed even when they leave the trace (`SPEC.md` §4)."""
    edges = []
    for span, node_id in zip(spans, ids, strict=True):
        for link in span.links:
            edges.append(
                Edge(
                    src=node_id,
                    dst=by_span_id.get(link.span_id, link.span_id),
                    kind=EdgeKind.LINK,
                    warrant=Warrant.EXPLICIT,
                    basis=link.basis,
                    adapter=adapter.id,
                )
            )
    return edges


def _data_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    by_span_id: dict[str, NodeId],
    adapter: AdapterInfo,
) -> list[Edge]:
    """Only ever the ones the instrumentor declared (`SPEC.md` §4.2).

    Nothing here compares an output to an input. A `data` edge exists in this
    graph if and only if the source said so.
    """
    edges = []
    for span, _node_id in zip(spans, ids, strict=True):
        for declared in span.data_edges:
            edges.append(
                Edge(
                    src=by_span_id.get(declared.src, declared.src),
                    dst=by_span_id.get(declared.dst, declared.dst),
                    kind=EdgeKind.DATA,
                    warrant=Warrant.EXPLICIT,
                    basis=declared.basis,
                    adapter=adapter.id,
                )
            )
    return edges


def _deduplicated(edges: Sequence[Edge]) -> tuple[Edge, ...]:
    """Unique on `(src, dst, kind, basis)`, then totally ordered (§3.8, §5.2)."""
    unique: dict[tuple[str, str, str, str], Edge] = {}
    for edge in edges:
        unique.setdefault(edge.identity, edge)
    return tuple(sorted(unique.values(), key=lambda edge: edge.sort_key))


def _temporal_edges(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    collected: DiagnosticCollector,
) -> list[Edge]:
    """Consecutive siblings only (`SPEC.md` §4.3).

    An edge for every ordered pair would be O(n^2) and would tell a consumer
    nothing it could not compute: the transitive closure is available through
    ``graph.reachable(...)``, so materializing it here would trade memory for
    no information.

    Two siblings reporting the same start time still get an edge -- the order
    has to be total or the graph is not deterministic -- but it carries a
    different ``basis``, because "we put these in an order" and "this one
    started first" are different claims and only one of them is an
    observation.
    """
    parent_of = {edge.dst: edge.src for edge in edges if edge.kind is EdgeKind.PARENT}
    groups: dict[str, list[Node]] = {}
    for node in nodes:
        if node.started_at is None:
            # Excluded, and told: a consumer that sees no temporal edge on a
            # node should be able to tell "it was last" from "we never knew
            # when it started".
            collected.add(
                codes.MISSING_TIMESTAMP,
                "no start time, so this node takes part in no temporal edges",
                node_id=node.id,
                level=DiagnosticLevel.INFO,
            )
            continue
        # Nodes with no parent are siblings of each other at trace root --
        # and so is a node whose stated parent is not in this input, because
        # in *this* graph it has none.
        groups.setdefault(parent_of.get(node.id, ""), []).append(node)

    found = []
    for parent in sorted(groups):
        siblings = sorted(groups[parent], key=_tie_break)
        for earlier, later in itertools.pairwise(siblings):
            tied = earlier.started_at == later.started_at
            found.append(
                Edge(
                    src=earlier.id,
                    dst=later.id,
                    kind=EdgeKind.TEMPORAL,
                    warrant=Warrant.DERIVED,
                    basis=TEMPORAL_TIED_BASIS if tied else TEMPORAL_BASIS,
                )
            )
    return found


def _in_order(
    nodes: Sequence[Node], edges: Sequence[Edge], collected: DiagnosticCollector
) -> tuple[Node, ...]:
    """Kahn's topological sort, with an explicit tie-break (`SPEC.md` §5.2).

    Hand-rolled, and the tie-break is the point: a topological order is not
    unique, so without a stated rule for choosing among ready nodes the same
    input could produce two different orders on two machines.
    """
    by_id = {node.id: node for node in nodes}
    incoming: dict[NodeId, int] = dict.fromkeys(by_id, 0)
    outgoing: dict[NodeId, list[NodeId]] = {node_id: [] for node_id in by_id}
    for edge in edges:
        if edge.kind not in ORDERING_KINDS:
            continue
        if edge.src not in by_id or edge.dst not in by_id:
            continue
        outgoing[edge.src].append(edge.dst)
        incoming[edge.dst] += 1

    ready = sorted((by_id[i] for i in by_id if incoming[i] == 0), key=_tie_break)
    ordered: list[Node] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        released = []
        for target in outgoing[node.id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                released.append(by_id[target])
        if released:
            ready = sorted([*ready, *released], key=_tie_break)

    if len(ordered) == len(nodes):
        return tuple(ordered)

    # Malformed telemetry can state a cycle. The graph is still produced:
    # what is left is ordered by the tie-break alone, and the cycle is
    # reported rather than allowed to hang or crash the build.
    placed = {node.id for node in ordered}
    residual = sorted((node for node in nodes if node.id not in placed), key=_tie_break)
    named = ", ".join(node.id for node in residual)
    collected.add(
        codes.ORDERING_CYCLE,
        f"the parent/call_result edges contain a cycle; these nodes could not "
        f"be ordered topologically and are ordered by start time and id "
        f"instead: {named}",
        source=[node.id for node in residual],
    )
    return (*ordered, *residual)
