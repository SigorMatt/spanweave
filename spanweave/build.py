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

#: Span links are a record-level field of the underlying span data model,
#: common to every dialect that carries them rather than a property of any
#: one -- which is why both adapters reach it identically and neither has
#: anything of its own to say about it. So the builder names it, like the
#: other four.
#:
#: `SpanLink.basis` overrides this, and exists for a dialect that states *why*
#: a link exists. None observed does; the override has never been taken
#: (`TASKS.md` I1).
LINK_BASIS = "span.link"

#: Names the resolution, not just the field. The instrumentor declares the
#: relation about a **message** ("this input is the result of call X"); the
#: builder resolves it to the span that fulfilled X. A consumer auditing this
#: edge is entitled to know that a resolution happened and what it joined on
#: (`SPEC.md` §4.2).
DATA_BASIS = "tool_call_id in tool-result message"

#: A conversational protocol resends the whole history, so the same
#: tool-result message reappears in the request of every later span. Each
#: occurrence is a declaration that span makes about its own input, and every
#: one of them is transcribed -- what the graph adds is which came first
#: (`SPEC.md` §4.2.1).
#:
#: The third string says **only** that an earlier span declared the same
#: receipt. It deliberately does not say "echo": two spans genuinely consuming
#: one result produce the identical shape, and a protocol resending history is
#: a cause the builder cannot see (`CLAUDE.md` 1).
DATA_TIED_BASIS = (
    "tool_call_id in tool-result message (earliest tied, broken by node_id)"
)
DATA_LATER_BASIS = (
    "tool_call_id in tool-result message (not the earliest receiving span)"
)
TEMPORAL_BASIS = "sibling start_time ordering"

#: When two siblings report the *same* start time, neither started first, and
#: the edge between them records a decision rather than an observation. It
#: still exists -- the order is deterministic and consumers need it -- but it
#: says so in its own basis, so a consumer can tell a tied edge from a strict
#: one by reading the graph instead of the documentation (`SPEC.md` §4.3).
TEMPORAL_TIED_BASIS = "sibling start_time ordering (tied, broken by node_id)"

#: The line above which a `started_at`/`ended_at` cannot be unix seconds.
#: 1e11 seconds after the epoch is the year 5138, so no wall-clock time in
#: seconds reaches it, while *now* in milliseconds is ~1.8e12 and in
#: nanoseconds ~1.8e18. A value over the line is evidence about the **unit of
#: the field** -- a property of the encoding -- and never about the run: the
#: number is kept exactly as reported and every edge is still built from it
#: (`SPEC.md` §3.1). Strictly greater, so the bound itself is not suspect.
#: Written as an integer rather than `1e11` so the diagnostic that quotes it
#: prints the whole number instead of `100000000000.0`, which reads as a
#: float somebody chose rather than as the year-5138 bound it is. `int` and
#: `float` compare exactly in Python, so an integer timestamp is tested as
#: written.
TIMESTAMP_UNIT_CEILING = 100_000_000_000

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
            f"record; every one of them is kept, with ids derived from the "
            f"records themselves instead (SPEC.md 3.6 rule 3), and a "
            f"reference to that id resolves to none of them",
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
    _report_missing_trace_id(trace_id, collected, adapter)
    _report_nonmonotonic_time(ordered, ids, collected, adapter)
    _report_timestamp_unit_suspect(ordered, ids, collected, adapter)

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


def _tie_break(node: Node) -> tuple[int | float, str]:
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


def _report_missing_trace_id(
    trace_id: str | None,
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> None:
    """An input that identifies no trace says so (`SPEC.md` §7).

    Once per graph, not once per record. What is missing is a property of the
    input as a whole -- there is no node it belongs to, and repeating the same
    sentence for every span would add nothing on any repeat. Nothing is
    invented in its place: an unidentified trace stays unidentified.
    """
    if trace_id:
        return
    reported = (
        "no record in this input reported a trace id"
        if trace_id is None
        else "the trace id this input reported is the empty string"
    )
    collected.add(
        codes.MISSING_TRACE_ID,
        f"{reported}, so this graph reports none and its trace_id is empty",
        level=DiagnosticLevel.INFO,
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


def _report_timestamp_unit_suspect(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> None:
    """A reported time too large to be unix seconds (`SPEC.md` §3.1).

    **One per node**, not one per value: both endpoints of a span share one
    field encoding, so two reports would say one thing twice, and the fields
    that are over the line are named in `source` instead. It is per node
    rather than per graph because there is a node to point at, and because an
    input carrying seconds from one exporter and nanoseconds from another is
    exactly what a per-graph statement cannot express.

    Only the **reported** values are checked. A duration is something this
    module computed by subtracting two numbers, and whether one of those is
    plausible is a claim about the run rather than about the encoding.
    """
    for span, node_id in zip(spans, ids, strict=True):
        over = {
            field: value
            for field, value in (
                ("started_at", span.started_at),
                ("ended_at", span.ended_at),
            )
            if value is not None and value > TIMESTAMP_UNIT_CEILING
        }
        if not over:
            continue
        collected.add(
            codes.TIMESTAMP_UNIT_SUSPECT,
            f"{', '.join(f'{f} ({v})' for f, v in over.items())} "
            f"exceeds {TIMESTAMP_UNIT_CEILING}, which unix seconds cannot "
            f"reach; the field may be in milliseconds or nanoseconds. Every "
            f"value is kept exactly as reported and nothing is rescaled",
            node_id=node_id,
            source=over,
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
    requesters, fulfillers, call_names = _call_sides(spans, ids)
    found: list[Edge] = []
    found.extend(_parent_edges(spans, ids, by_span_id, collected, adapter))
    found.extend(
        _call_result_edges(requesters, fulfillers, call_names, collected, adapter)
    )
    found.extend(_link_edges(spans, ids, by_span_id, adapter))
    found.extend(_data_edges(spans, ids, by_span_id, fulfillers, adapter))
    return _deduplicated(found)


def _call_sides(
    spans: Sequence[NormalizedSpan], ids: Sequence[NodeId]
) -> tuple[dict[str, list[NodeId]], dict[str, list[NodeId]], dict[str, str | None]]:
    """Who asked for each call, who answered it, and what it was called.

    Built once: `call_result` joins the two sides, and a `data` edge joins the
    answering side to whoever was later given the answer (`SPEC.md` §4.2).

    The third value is the tool name per call id, for the two unpaired
    diagnostics (`SPEC.md` §3.7). It is `None` where no span named the call
    **and** where two spans named it differently -- disagreement is not
    something to resolve by picking, and picking would also make the result
    depend on input order, which `CLAUDE.md` 4 forbids outright.
    """
    requesters: dict[str, list[NodeId]] = {}
    fulfillers: dict[str, list[NodeId]] = {}
    claimed: dict[str, set[str]] = {}
    for span, node_id in zip(spans, ids, strict=True):
        if not span.call_ids or span.call_role is None:
            continue
        side = requesters if span.call_role is CallRole.REQUESTER else fulfillers
        for call_id in span.call_ids:
            side.setdefault(call_id, []).append(node_id)
            named = span.call_names.get(call_id)
            if named is not None:
                claimed.setdefault(call_id, set()).add(named)
    names: dict[str, str | None] = {
        call_id: next(iter(found)) if len(found) == 1 else None
        for call_id, found in claimed.items()
    }
    return requesters, fulfillers, names


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


def _unpaired_source(
    call_id: str, call_names: dict[str, str | None]
) -> dict[str, str | None]:
    """`source` for the two unpaired codes (`SPEC.md` §3.7, `source` per code).

    An object rather than the bare id, because a requested call that nothing
    fulfils has **no node** -- so `operation`, where a tool's name lives, has
    nowhere to be, and the tool a consumer asked about was unattributable from
    the graph. `operation` is the dialect's own word for the call, `None`
    where the dialect said none; nothing here infers one.
    """
    return {"call_id": call_id, "operation": call_names.get(call_id)}


def _call_result_edges(
    requesters: dict[str, list[NodeId]],
    fulfillers: dict[str, list[NodeId]],
    call_names: dict[str, str | None],
    collected: DiagnosticCollector,
    adapter: AdapterInfo,
) -> list[Edge]:
    """Join requester to fulfiller on the id the dialect carried.

    Never on name, proximity, or timing. A guessed pairing is
    indistinguishable from a real one downstream, which is exactly the harm
    the warrant system exists to prevent (`SPEC.md` §4.4).
    """
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
                    source=_unpaired_source(call_id, call_names),
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
                    source=_unpaired_source(call_id, call_names),
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
                    basis=link.basis or LINK_BASIS,
                    adapter=adapter.id,
                )
            )
    return edges


def _data_edges(
    spans: Sequence[NormalizedSpan],
    ids: Sequence[NodeId],
    by_span_id: dict[str, NodeId],
    fulfillers: dict[str, list[NodeId]],
    adapter: AdapterInfo,
) -> list[Edge]:
    """Only ever the ones the instrumentor declared (`SPEC.md` §4.2).

    One shape of declaration, and nothing here compares an output to an input:
    a span stating that it **received** the result of call X, joined to the
    span that fulfilled X. The relation is declared about a message and
    resolved to spans by id, which is a real step and is why the basis says so
    rather than naming a bare field.

    A received result whose producing span is not in this input yields no
    edge: there is nothing to point at. That gap is currently silent, and is
    recorded as such in `SPEC.md` §4.2.

    Several spans may declare receipt of the same call, because the protocol
    resends the history. All of them are kept -- each is a true statement the
    instrumentor made about that span's own input -- and the `basis` records
    which declaration came first, so a consumer can ask "which tool output did
    this turn act on" without the library deciding for it.
    """
    earliest, tied = _earliest_receivers(spans, ids)
    edges = []
    for span, node_id in zip(spans, ids, strict=True):
        for call_id in span.received_call_ids:
            if earliest.get(call_id) != node_id:
                basis = DATA_LATER_BASIS
            elif call_id in tied:
                basis = DATA_TIED_BASIS
            else:
                basis = DATA_BASIS
            for producer in sorted(fulfillers.get(call_id, ())):
                if producer == node_id:
                    # A span cannot feed itself. Malformed input rather than a
                    # relation, and a self-loop would be neither.
                    continue
                edges.append(
                    Edge(
                        src=producer,
                        dst=node_id,
                        kind=EdgeKind.DATA,
                        warrant=Warrant.EXPLICIT,
                        basis=basis,
                        adapter=adapter.id,
                    )
                )
    return edges


def _earliest_receivers(
    spans: Sequence[NormalizedSpan], ids: Sequence[NodeId]
) -> tuple[dict[str, NodeId], set[str]]:
    """Per call id: which span declared receipt first, and was it a tie.

    The spans declaring receipt of one call are a **set**, so ranking them is
    order-independent by construction (`CLAUDE.md` 4) -- input line order
    cannot reach the answer. The rank is `(started_at, node_id)`, the same
    total order §5.2 uses for node position and §4.3 for sibling temporal
    edges, with an untimed span sorted last: it is never the earliest unless
    no receiving span is timed at all, and it already draws
    `missing_timestamp`.

    A tie is reported separately because breaking it is a **decision**, not an
    observation, and §4.3 has already ruled that such an edge must say so in
    its own basis rather than pass as something the telemetry showed.
    """
    ranked: dict[str, list[tuple[int | float, NodeId]]] = {}
    for span, node_id in zip(spans, ids, strict=True):
        start = span.started_at if span.started_at is not None else float("inf")
        for call_id in set(span.received_call_ids):
            ranked.setdefault(call_id, []).append((start, node_id))
    earliest: dict[str, NodeId] = {}
    tied: set[str] = set()
    for call_id, receivers in ranked.items():
        receivers.sort()
        earliest[call_id] = receivers[0][1]
        if len(receivers) > 1 and receivers[0][0] == receivers[1][0]:
            tied.add(call_id)
    return earliest, tied


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
