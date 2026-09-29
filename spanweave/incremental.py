"""The incremental builder's state: one record absorbed at a time.

The contract is one sentence (``SPEC.md`` §10): after absorbing the first `k`
spans of a stream, ``materialize()`` returns the graph the batch builder
returns for those same `k` spans, byte for byte. Everything here exists to
make that true cheaply, and nothing here is allowed to make it *almost* true.

So this module holds no rules of its own. Every edge, every diagnostic and
every id comes from the same function the batch path calls -- in
``spanweave.build`` and ``spanweave.ids`` -- applied to the keys an arriving
record touches instead of to the whole input. What is new is the bookkeeping:
which keys a record touches, and which of them stop being local.

Three facts are properties of the **whole** input rather than of any record,
and an arriving record can change all three: the most common trace id, whether
a dialect span id is unique, and whether a source key is. The first is in the
material of every derived node id (``SPEC.md`` §3.6 rule 2) and the other two
decide which rule an id comes from at all -- so a record that changes one of
them moves ids that were already given out, and with them every edge and
diagnostic that names one. Those three restate everything; every other arrival
touches only the record's own facts, the references it makes, the call ids it
names, and the sibling group it joins.

Absorbing also writes the journal. Each arrival opens an entry (``begin``),
touches the keys it touches, and closes it (``finish``) with exactly what
changed in the three collections a graph holds -- which ``spanweave.delta``
then folds into a `Delta` on demand (``SPEC.md`` §10.6-§10.7). A restating
arrival clears every key, so its entry describes the whole state and says so,
rather than looking like a small diff.

Below the seam, like the builder: this module is handed ``NormalizedSpan``
values and never learns that a dialect exists (``DESIGN.md`` §3). Feeding it
*records* -- classifying, parsing, numbering -- is the top layer's job, in
``spanweave.api``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeVar

from spanweave import build
from spanweave.delta import Change, Facts, Tally
from spanweave.diagnostics import DiagnosticCollector
from spanweave.graph import Graph
from spanweave.ids import collision, identify
from spanweave.model import AdapterInfo, Diagnostic, Edge, Meta, Node, NodeId
from spanweave.seam import CallRole, NormalizedSpan
from spanweave.version import SCHEMA_VERSION, __version__

#: The sibling group of a node with no parent in this graph (`SPEC.md` §4.3).
#: Trace root is a group like any other, and a node whose stated parent has not
#: arrived is in it -- because in *this* graph it has no parent.
ROOT_GROUP = ""

#: The tally's key for the statements that are about the **whole input** and so
#: have no record and no call id to hang on: `duplicate_source_id` and
#: `missing_trace_id` (`SPEC.md` §3.7, §7).
WHOLE_INPUT = ("whole_input",)

_Key = TypeVar("_Key", int, str)


def _flattened(edges: Mapping[_Key, tuple[Edge, ...]]) -> list[Edge]:
    """Every edge under every key, the keys in order.

    The order does not reach the graph -- `deduplicated` sorts, and two edges
    sharing one identity carry the same value, because both ends decide the
    `adapter` field. It is stated anyway: a mapping iterated in insertion order
    is exactly how a dependence on arrival order gets in (`CLAUDE.md` 4).
    """
    found: list[Edge] = []
    for key in sorted(edges):
        found.extend(edges[key])
    return found


class SpanAbsorber:
    """The prefix state: absorb spans, materialize the graph they make.

    Absorbing is cheap and mutable; materializing is a frozen `Graph` built on
    demand. The split is the point of the class -- an ingest loop that never
    materializes pays only for the bookkeeping, and a consumer that
    materializes after every record gets the same graph either way.

    Keyed by **position** (the record's arrival index) and by **call id**, not
    by node id, because a node id is one of the things an arrival can move.
    """

    def __init__(
        self,
        *,
        temporal: bool = True,
        source_digest: str | None = None,
        skipped_records: int = 0,
    ) -> None:
        self.temporal = temporal
        # Facts about the input the absorber was never shown, carried so that a
        # caller who *did* read the input can state them (`SPEC.md` §10.4). They
        # sit here rather than on `materialize` because the journal needs the
        # same answers between materializations, and a fact that arrives late
        # would make two versions disagree about one input.
        self._source_digest = source_digest
        self._skipped_records = skipped_records
        #: The journal's accounting of the three collections a graph holds.
        self._tally = Tally()
        #: True while the arrival being absorbed restated everything (§10.2).
        self._restated = False
        self._before = Facts()
        # The input, in arrival order.
        self._spans: list[NormalizedSpan] = []
        self._producers: list[AdapterInfo | None] = []
        #: The distinct producers, for the one adapter a statement about the
        #: whole input may name. A dict rather than a set: nothing here may
        #: depend on set iteration order (`CLAUDE.md` 4).
        self._adapter_ids: dict[str | None, None] = {}
        # The newest statement of each producer, by `(id, version)`. Newest
        # rather than first because `declared_confidence` is declared over a
        # sample that grows as records arrive, so the latest statement is the
        # one that describes what has been read (`SPEC.md` §6.1, §10).
        self._producer_latest: dict[tuple[str, str], AdapterInfo] = {}
        # The three whole-input counts, and what the first of them resolves to.
        self._trace_counts: dict[str, int] = {}
        self._span_id_counts: dict[str, int] = {}
        self._source_key_counts: dict[str, int] = {}
        #: How many span ids the dialect used more than once -- one
        #: `duplicate_source_id` each, and the only whole-input statement whose
        #: count can grow (`SPEC.md` §3.6 rule 3).
        self._duplicated = 0
        self._trace_id: str | None = None
        self._forget()

    def _forget(self) -> None:
        """Clear everything derived. The counts above survive; nothing else."""
        #: What the whole-input statements were last derived from. `None` means
        #: "not derived yet", which is what a cleared tally needs to hear.
        self._whole_input_from: tuple[str | None, int, str | None] | None = None
        self._ids: list[NodeId] = []
        self._nodes: list[Node] = []
        self._by_node: dict[NodeId, str | None] = {}
        self._position_of: dict[NodeId, int] = {}
        self._by_span_id: dict[str, NodeId] = {}
        # Per record.
        self._record_diagnostics: dict[int, tuple[Diagnostic, ...]] = {}
        self._parent_edges: dict[int, Edge] = {}
        self._parent_diagnostics: dict[int, tuple[Diagnostic, ...]] = {}
        self._link_edges: dict[int, tuple[Edge, ...]] = {}
        self._missing_timestamp: dict[int, tuple[Diagnostic, ...]] = {}
        # Per call id.
        self._call_edges: dict[str, tuple[Edge, ...]] = {}
        self._call_diagnostics: dict[str, tuple[Diagnostic, ...]] = {}
        self._data_edges: dict[str, tuple[Edge, ...]] = {}
        # Per sibling group.
        self._temporal_edges: dict[str, tuple[Edge, ...]] = {}
        # The indexes the keys above are restated from.
        self._requesters: dict[str, list[NodeId]] = {}
        self._fulfillers: dict[str, list[NodeId]] = {}
        self._call_names: dict[str, set[str]] = {}
        self._receipts: dict[str, list[tuple[int | float, NodeId]]] = {}
        # Records that named a span id and are waiting for it. A parent that
        # arrives after its child, and a link whose target arrives later, are
        # the two relations an arrival completes for a record already absorbed.
        self._awaiting_parent: dict[str, set[int]] = {}
        self._awaiting_link: dict[str, set[int]] = {}
        self._group_of: dict[int, str] = {}
        self._groups: dict[str, set[int]] = {}

    # ----------------------------------------------------------------------
    # Absorbing
    # ----------------------------------------------------------------------

    def begin(self) -> None:
        """Open a journal entry: one arrival, however many spans it became."""
        self._tally.begin()
        self._restated = False
        self._before = self.facts()

    def finish(self) -> Change:
        """Close the entry the last `begin` opened (`SPEC.md` §10.7)."""
        return self._tally.end(self._before, self.facts(), self._restated)

    def facts(self) -> Facts:
        """What the graph says that none of its collections hold (§10.6)."""
        return Facts(
            trace_id=self._trace_id or "",
            adapters=tuple(
                self._producer_latest[key] for key in sorted(self._producer_latest)
            ),
            whole_input=self.whole_input,
        )

    @property
    def whole_input(self) -> str | None:
        """The one adapter a statement about the whole input may name (§3.7)."""
        return build.whole_input_adapter(self._adapter_ids, self._skipped_records)

    def current_nodes(self) -> tuple[Node, ...]:
        """The node set as the journal accounts for it. Order is not the point."""
        return tuple(self._tally.nodes.items())

    def current_edges(self) -> tuple[Edge, ...]:
        """The edge set as the journal accounts for it, deduplicated as §3.8."""
        return build.deduplicated(self._tally.edges.items())

    def absorb(self, span: NormalizedSpan, producer: AdapterInfo | None) -> None:
        """Take one span into the state.

        Local unless the span changes one of the three whole-input facts, in
        which case every record's facts are restated from the counts. Both
        paths do the same per-record work, so the second is the first run `n`
        times and cannot disagree with it.
        """
        position = len(self._spans)
        self._spans.append(span)
        self._producers.append(producer)
        self._adapter_ids.setdefault(producer.id if producer is not None else None)
        if producer is not None:
            self._producer_latest[producer.sort_key] = producer

        restate = False
        if span.trace_id is not None:
            self._trace_counts[span.trace_id] = (
                self._trace_counts.get(span.trace_id, 0) + 1
            )
        if span.span_id is not None:
            claims = self._span_id_counts.get(span.span_id, 0) + 1
            self._span_id_counts[span.span_id] = claims
            # The second claim is what moves the first record off rule 1; a
            # third moves nobody, because the first two are already derived.
            restate = restate or claims == 2
            if claims == 2:
                self._duplicated += 1
        keys = self._source_key_counts.get(span.source_key, 0) + 1
        self._source_key_counts[span.source_key] = keys
        restate = restate or keys == 2

        trace_id = build.majority_trace_id(self._trace_counts)
        if trace_id != self._trace_id:
            self._trace_id = trace_id
            restate = True

        if restate:
            self._restated = True
            self._restate_every_record()
        else:
            self._absorb_at(position)
        self._restate_whole_input()

    def _restate_every_record(self) -> None:
        """Throw everything derived away and derive it again from the counts.

        What the three whole-input facts are worth: when one of them moves,
        so can every id -- and an id is what every edge and diagnostic is keyed
        by. It is O(n) for the arrival that trips it, and `SPEC.md` §10 says so
        rather than implying every absorb is local.
        """
        self._tally.clear()
        self._forget()
        for position in range(len(self._spans)):
            self._absorb_at(position)

    def _restate_whole_input(self) -> None:
        """The statements about the whole input, as they stand now.

        Three inputs and no more: the trace id, how many span ids the dialect
        reused, and which adapter -- if one -- may be named for a statement
        about everything that arrived. Skipped when none of them moved, so an
        ordinary arrival pays nothing for two diagnostics it cannot have
        changed.
        """
        whole_input = self.whole_input
        derived_from = (self._trace_id, self._duplicated, whole_input)
        if derived_from == self._whole_input_from:
            return
        self._whole_input_from = derived_from
        collector = DiagnosticCollector()
        for duplicated in sorted(
            span_id for span_id, count in self._span_id_counts.items() if count > 1
        ):
            build.report_duplicate_source_id(duplicated, collector, whole_input)
        build.report_missing_trace_id(self._trace_id, collector, whole_input)
        self._tally.set_diagnostics(WHOLE_INPUT, collector.collected())

    def _absorb_at(self, position: int) -> None:
        """Everything one record contributes, and everything it completes."""
        span = self._spans[position]
        producer = self._producers[position]
        adapter = producer.id if producer is not None else None
        unique_span_id = (
            span.span_id is not None and self._span_id_counts[span.span_id] == 1
        )
        node_id = identify(
            span,
            adapter,
            self._trace_id,
            span_id_is_unique=unique_span_id,
            source_key_is_unique=self._source_key_counts[span.source_key] == 1,
        )
        if node_id in self._position_of:
            raise collision(node_id, self._spans[self._position_of[node_id]], span)

        self._ids.append(node_id)
        node = build.node_of(span, node_id, producer)
        self._nodes.append(node)
        self._tally.add_node(node)
        self._by_node[node_id] = adapter
        self._position_of[node_id] = position
        if span.span_id is not None and unique_span_id:
            self._by_span_id[span.span_id] = node_id

        collector = DiagnosticCollector()
        build.report_record(span, node_id, self._trace_id, collector, adapter)
        self._record_diagnostics[position] = collector.collected()
        self._tally.set_diagnostics(
            ("record", str(position)), self._record_diagnostics[position]
        )

        if span.parent_id is not None:
            self._awaiting_parent.setdefault(span.parent_id, set()).add(position)
        self._restate_parent(position)
        for link in span.links:
            self._awaiting_link.setdefault(link.span_id, set()).add(position)
        self._restate_links(position)

        # What this record completes for records already absorbed: a reference
        # to its span id that could not be resolved before it arrived.
        if span.span_id is not None and self._by_span_id.get(span.span_id) == node_id:
            for other in sorted(self._awaiting_parent.get(span.span_id, ())):
                if other != position:
                    self._restate_parent(other)
            for other in sorted(self._awaiting_link.get(span.span_id, ())):
                if other != position:
                    self._restate_links(other)

        self._restate_calls(self._index_calls(span, node_id))
        self._place(position)

    def _index_calls(self, span: NormalizedSpan, node_id: NodeId) -> set[str]:
        """Index the call ids this record names, and return which they were.

        Both sides and the receipts, because all three feed the same two keys:
        one call id's `call_result` edges and its `data` edges are decided by
        that call id's requesters, fulfillers and receivers and by nothing else
        (`SPEC.md` §4.2, §4.4).
        """
        touched: set[str] = set()
        if span.call_ids and span.call_role is not None:
            side = (
                self._requesters
                if span.call_role is CallRole.REQUESTER
                else self._fulfillers
            )
            for call_id in span.call_ids:
                side.setdefault(call_id, []).append(node_id)
                named = span.call_names.get(call_id)
                if named is not None:
                    self._call_names.setdefault(call_id, set()).add(named)
                touched.add(call_id)
        start = span.started_at if span.started_at is not None else float("inf")
        for call_id in set(span.received_call_ids):
            self._receipts.setdefault(call_id, []).append((start, node_id))
            touched.add(call_id)
        return touched

    def _restate_parent(self, position: int) -> None:
        """One record's `parent` edge and `orphan_parent`, as they stand now."""
        collector = DiagnosticCollector()
        edge = build.parent_edge(
            self._spans[position],
            self._ids[position],
            self._by_span_id,
            collector,
            self._by_node,
        )
        self._parent_diagnostics[position] = collector.collected()
        self._tally.set_diagnostics(
            ("parent", str(position)), self._parent_diagnostics[position]
        )
        if edge is None:
            self._parent_edges.pop(position, None)
        else:
            self._parent_edges[position] = edge
        self._tally.set_edges(
            ("parent", str(position)), () if edge is None else (edge,)
        )
        # A record just given a parent leaves the root group for its parent's.
        # Only a record already placed moves: the arriving one is placed after.
        if position in self._group_of:
            self._regroup(position)

    def _restate_links(self, position: int) -> None:
        self._link_edges[position] = tuple(
            build.link_edges(
                self._spans[position],
                self._ids[position],
                self._by_span_id,
                self._by_node,
            )
        )
        self._tally.set_edges(("link", str(position)), self._link_edges[position])

    def _restate_calls(self, call_ids: Iterable[str]) -> None:
        for call_id in sorted(call_ids):
            collector = DiagnosticCollector()
            self._call_edges[call_id] = tuple(
                build.call_result_edges(
                    call_id,
                    self._requesters.get(call_id, ()),
                    self._fulfillers.get(call_id, ()),
                    {call_id: self._sole_name(call_id)},
                    collector,
                    self._by_node,
                )
            )
            self._call_diagnostics[call_id] = collector.collected()
            self._data_edges[call_id] = tuple(
                build.data_edges(
                    call_id,
                    self._receipts.get(call_id, ()),
                    self._fulfillers.get(call_id, ()),
                    self._by_node,
                )
            )
            self._tally.set_edges(("call", call_id), self._call_edges[call_id])
            self._tally.set_diagnostics(
                ("call", call_id), self._call_diagnostics[call_id]
            )
            self._tally.set_edges(("data", call_id), self._data_edges[call_id])

    def _sole_name(self, call_id: str) -> str | None:
        """The name one call id was given, or `None` where two disagree.

        The batch builder's `_call_sides`, spelled for one call id:
        disagreement is not something to resolve by picking, and picking would
        make the result depend on which record arrived first.
        """
        named = self._call_names.get(call_id, set())
        return next(iter(named)) if len(named) == 1 else None

    # -- sibling groups, and the chains over them --------------------------

    def _place(self, position: int) -> None:
        """Put a record in its sibling group and restate that chain."""
        if not self.temporal:
            return
        node = self._nodes[position]
        if node.started_at is None:
            collector = DiagnosticCollector()
            build.report_missing_timestamp(node.id, collector, self._by_node[node.id])
            self._missing_timestamp[position] = collector.collected()
            self._tally.set_diagnostics(
                ("no_start_time", str(position)), self._missing_timestamp[position]
            )
            return
        group = self._group_key(position)
        self._group_of[position] = group
        self._groups.setdefault(group, set()).add(position)
        self._restate_chain(group)

    def _regroup(self, position: int) -> None:
        was = self._group_of[position]
        now = self._group_key(position)
        if now == was:
            return
        self._groups[was].discard(position)
        self._restate_chain(was)
        self._group_of[position] = now
        self._groups.setdefault(now, set()).add(position)
        self._restate_chain(now)

    def _group_key(self, position: int) -> str:
        edge = self._parent_edges.get(position)
        return edge.src if edge is not None else ROOT_GROUP

    def _restate_chain(self, group: str) -> None:
        members = self._groups.get(group, set())
        if not members:
            self._groups.pop(group, None)
            self._temporal_edges.pop(group, None)
            self._tally.set_edges(("temporal", group), ())
            return
        self._temporal_edges[group] = tuple(
            build.temporal_chain(self._nodes[position] for position in members)
        )
        self._tally.set_edges(("temporal", group), self._temporal_edges[group])

    # ----------------------------------------------------------------------
    # Materializing
    # ----------------------------------------------------------------------

    def materialize(self) -> Graph:
        """The graph the spans absorbed so far make (`SPEC.md` §10).

        O(n): the node order is a fresh topological sort and the index a
        `Graph` builds is a fresh index. Only the rules are incremental, and
        deliberately -- an arriving record can move the position of every node,
        so an order kept between arrivals would have to be recomputed anyway.
        """
        collected = DiagnosticCollector()
        whole_input = self.whole_input
        for duplicated in sorted(
            span_id for span_id, count in self._span_id_counts.items() if count > 1
        ):
            build.report_duplicate_source_id(duplicated, collected, whole_input)
        build.report_missing_trace_id(self._trace_id, collected, whole_input)
        for position in range(len(self._spans)):
            collected.extend(self._record_diagnostics[position])
            collected.extend(self._parent_diagnostics[position])
            collected.extend(self._missing_timestamp.get(position, ()))
        for call_id in sorted(self._call_diagnostics):
            collected.extend(self._call_diagnostics[call_id])

        edges = build.deduplicated(
            [
                *(self._parent_edges[key] for key in sorted(self._parent_edges)),
                *_flattened(self._call_edges),
                *_flattened(self._link_edges),
                *_flattened(self._data_edges),
            ]
        )
        if self.temporal:
            edges = build.deduplicated([*edges, *_flattened(self._temporal_edges)])
        nodes = build.in_order(tuple(self._nodes), edges, collected, whole_input)

        return Graph.of(
            trace_id=self._trace_id or "",
            nodes=nodes,
            edges=edges,
            diagnostics=collected.collected(),
            meta=Meta(
                schema_version=SCHEMA_VERSION,
                spanweave_version=__version__,
                adapters=tuple(
                    self._producer_latest[key] for key in sorted(self._producer_latest)
                ),
                source_digest=self._source_digest,
                node_count=len(nodes),
                edge_count=len(edges),
                diagnostic_count=len(collected),
            ),
        )
