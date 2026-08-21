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
from collections.abc import Iterable, Sequence

from spanweave import diagnostics as codes
from spanweave.diagnostics import DiagnosticCollector
from spanweave.graph import Graph
from spanweave.ids import assign
from spanweave.model import (
    AdapterInfo,
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


def build_graph(
    spans: Iterable[NormalizedSpan],
    *,
    adapter: AdapterInfo,
    collector: DiagnosticCollector | None = None,
    source_digest: str | None = None,
) -> Graph:
    """Turn normalized spans into a graph.

    ``collector`` carries diagnostics raised before this point -- by the
    reader, typically -- so that a malformed line and an unpaired call end up
    in the same list. They are the same kind of statement about the input.
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

    # Ordering proper -- a topological sort over parent and call_result -- is
    # task 1.6. Until then nodes come out in the tie-break order that sort
    # falls back to, which is already total and already deterministic.
    nodes = tuple(sorted(nodes, key=_tie_break))

    return Graph(
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
        if span.call_id is None or span.call_role is None:
            continue
        side = requesters if span.call_role is CallRole.REQUESTER else fulfillers
        side.setdefault(span.call_id, []).append(node_id)

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
