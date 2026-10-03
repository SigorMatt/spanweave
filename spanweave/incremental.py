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

import bisect
from collections.abc import Iterable, Mapping, Sequence
from typing import TypeVar

from spanweave import build, ids
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


def _flattened(edges: Mapping[_Key, Sequence[Edge]]) -> list[Edge]:
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
        #: The `_whole_input_from` memo as the arrival being absorbed found it.
        #: Snapshotted by `begin` and put back by `rollback_to`, because that
        #: memo is the one piece of derived state neither half of the rollback
        #: reaches: `_restate_every_record` re-derives it *forward* from the
        #: survivors, and `Tally.rollback` takes back the diagnostics it
        #: derived but not the note saying they were derived (`SPEC.md` §10.5).
        self._whole_input_before: tuple[str | None, int, str | None] | None = None
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
        # Per call id, and keyed inside by the span that declared receipt: the
        # `data` edges that receipt contributes. Keyed that way because a receipt
        # is what an arrival adds and what a basis rewrite moves, so the one
        # receipt whose basis changed is reached without walking the rest
        # (`SPEC.md` §4.2.1, §10.6).
        self._data_edges: dict[str, dict[NodeId, tuple[Edge, ...]]] = {}
        # Per sibling group: the group's members in `SPEC.md` §4.3's order, and
        # the chain over them, held as lists because both are *amended* by an
        # arrival rather than rebuilt -- `_temporal_edges[group][j]` is the edge
        # from `_groups[group][j]` to the member after it.
        self._temporal_edges: dict[str, list[Edge]] = {}
        # The indexes the keys above are restated from.
        self._requesters: dict[str, list[NodeId]] = {}
        self._fulfillers: dict[str, list[NodeId]] = {}
        self._call_names: dict[str, set[str]] = {}
        # Held in `(started_at, node_id)` order -- §4.2.1's ranking -- because
        # which receipt ranks first is the only thing a `data` edge's basis turns
        # on, and a sorted list makes an arrival's effect on that a comparison
        # rather than a re-ranking of the whole set.
        self._receipts: dict[str, list[tuple[int | float, NodeId]]] = {}
        # Records that named a span id and are waiting for it. A parent that
        # arrives after its child, and a link whose target arrives later, are
        # the two relations an arrival completes for a record already absorbed.
        self._awaiting_parent: dict[str, set[int]] = {}
        self._awaiting_link: dict[str, set[int]] = {}
        self._group_of: dict[int, str] = {}
        self._groups: dict[str, list[int]] = {}

    # ----------------------------------------------------------------------
    # Absorbing
    # ----------------------------------------------------------------------

    def begin(self) -> None:
        """Open a journal entry: one arrival, however many spans it became."""
        self._tally.begin()
        self._restated = False
        self._before = self.facts()
        self._whole_input_before = self._whole_input_from

    def finish(self) -> Change:
        """Close the entry the last `begin` opened (`SPEC.md` §10.7)."""
        return self._tally.end(self._before, self.facts(), self._restated)

    def span_count(self) -> int:
        """How many spans have been absorbed -- a point to roll back to."""
        return len(self._spans)

    def rollback_to(self, spans: int) -> None:
        """Undo every span absorbed since there were `spans`, tally included.

        The other half of `feed`'s atomicity. `absorb` decides its refusal
        before it writes, so a record that became **one** span needs nothing
        here -- but a record can become several (`SPEC.md` §10.5), and then the
        second of them can be refused with the first already absorbed. "The
        builder is left as it was" is this.

        Two halves, and only one is a recomputation:

        * The **tally** is put back exactly, from the snapshot `begin` opened.
          Every `add`, `drop` and `clear` it saw is reversed, whatever order
          they came in -- which is what makes this the one rollback, and why
          finer-grained ledger traffic later needs no second one.
        * The absorber's own derived state is **re-derived from the
          survivors**, because an arrival can restate every record (§10.2) and
          undoing that span by span would be a second implementation of rules
          this module is careful to hold only one copy of.

        One value belongs to neither half, and is the exception that proves why
        both are needed: `_whole_input_from`, the memo that says what the
        whole-input statements were last derived from. Re-deriving forward
        *writes* it, and the tally's snapshot takes back the diagnostics that
        derivation made but not the memo recording that they were made -- which
        would leave the memo claiming a statement the journal does not hold, and
        short-circuit the next legitimate derivation. So it is restored from the
        snapshot `begin` took, after the tally, so that the two agree.

        O(n) and paid on refusals only; nothing is added to the accepted path.
        """
        if len(self._spans) != spans:
            del self._spans[spans:]
            del self._producers[spans:]
            self._recount()
            self._restate_every_record(
                list(ids.assign(self._spans, self._adapters(), self._trace_id).ids)
            )
            self._restate_whole_input()
        self._tally.rollback()
        self._whole_input_from = self._whole_input_before
        # `begin` sets this on every arrival, so its value between arrivals is
        # nobody's; it is written here anyway rather than left describing an
        # arrival that did not happen.
        self._restated = False

    def _recount(self) -> None:
        """The three whole-input counts, and the producers, from the spans held.

        Re-counted rather than decremented: a count walked backwards has to
        reverse `_duplicated`'s "the *second* claim is what counts" and the
        majority trace id's tie-break, and the arithmetic that undoes a rule is
        a second statement of it. Over the survivors in arrival order, so
        `_adapter_ids` and `_producer_latest` hold what an absorb of exactly
        those spans would have left (`SPEC.md` §3.7, §6.1).
        """
        self._adapter_ids = {}
        self._producer_latest = {}
        self._trace_counts = {}
        self._span_id_counts = {}
        self._source_key_counts = {}
        self._duplicated = 0
        for span, producer in zip(self._spans, self._producers, strict=True):
            adapter = producer.id if producer is not None else None
            self._adapter_ids.setdefault(adapter)
            if producer is not None:
                self._producer_latest[producer.sort_key] = producer
            if span.trace_id is not None:
                self._trace_counts[span.trace_id] = (
                    self._trace_counts.get(span.trace_id, 0) + 1
                )
            if span.span_id is not None:
                claims = self._span_id_counts.get(span.span_id, 0) + 1
                self._span_id_counts[span.span_id] = claims
                if claims == 2:
                    self._duplicated += 1
            self._source_key_counts[span.source_key] = (
                self._source_key_counts.get(span.source_key, 0) + 1
            )
        self._trace_id = build.majority_trace_id(self._trace_counts)

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

        The one refusal this can raise -- two records resolving to one node id
        (`SPEC.md` §3.6) -- is decided **before** anything moves, so a refused
        span leaves the state exactly as it was and the next `absorb` and every
        `materialize` answer as they would have (`SPEC.md` §10.5). That is why
        the counts below are read here and written only in the second half: a
        span appended before its id was checked is a span the rest of the state
        has no entry for, and every later arrival trips over it.

        One span, though: a *record* can become several, and then the refusal
        of a later one has earlier ones to undo. `rollback_to` is that, and it
        is the caller's to ask for, because only the caller knows where the
        record began.
        """
        adapter = producer.id if producer is not None else None
        # What the three whole-input facts would say with this span in them,
        # read without writing any of them.
        claims = (
            0 if span.span_id is None else self._span_id_counts.get(span.span_id, 0) + 1
        )
        keys = self._source_key_counts.get(span.source_key, 0) + 1
        trace_id = self._trace_id_with(span.trace_id)
        # The second claim on a span id is what moves the first record off rule
        # 1; a third moves nobody, because the first two are already derived.
        # The same for a source key, and the trace id moves every derived id.
        restate = claims == 2 or keys == 2 or trace_id != self._trace_id

        decided = self._decided(span, adapter, trace_id, restate, claims, keys)

        # Nothing below refuses.
        position = len(self._spans)
        self._spans.append(span)
        self._producers.append(producer)
        self._adapter_ids.setdefault(adapter)
        if producer is not None:
            self._producer_latest[producer.sort_key] = producer
        if span.trace_id is not None:
            self._trace_counts[span.trace_id] = (
                self._trace_counts.get(span.trace_id, 0) + 1
            )
        if span.span_id is not None:
            self._span_id_counts[span.span_id] = claims
            if claims == 2:
                self._duplicated += 1
        self._source_key_counts[span.source_key] = keys
        self._trace_id = trace_id

        if isinstance(decided, list):
            self._restated = True
            self._restate_every_record(decided)
        else:
            self._absorb_at(position, decided)
        self._restate_whole_input()

    def _trace_id_with(self, arriving: str | None) -> str | None:
        """The majority trace id the counts would give with `arriving` in them.

        A span that states no trace id changes no count, so the answer is the
        one that stands. Otherwise the tie is broken exactly as the batch path
        breaks it, on a reading of the counts rather than on the counts
        themselves, because this is asked before the arriving span is absorbed.
        """
        if arriving is None:
            return self._trace_id
        counts = dict(self._trace_counts)
        counts[arriving] = counts.get(arriving, 0) + 1
        return build.majority_trace_id(counts)

    def _decided(
        self,
        span: NormalizedSpan,
        adapter: str | None,
        trace_id: str | None,
        restate: bool,
        claims: int,
        keys: int,
    ) -> list[NodeId] | NodeId:
        """The ids the arriving span implies, or the refusal it earns.

        The ids, not just a yes: they are what the absorb then uses, so the
        check and the answer are one computation and cannot disagree. A
        restating arrival can move an id already given out, so there the whole
        assignment is recomputed -- by the same `assign` the batch path calls,
        on the same spans, raising the same refusal; the list it returns is one
        per position. An ordinary arrival moves no id, so only its own is new
        and only a clash with an id already given out is possible -- one id
        back, and no list, because copying the ids on every arrival would make
        an ordinary absorb walk the whole stream to place one span.
        """
        if restate:
            return list(
                ids.assign(
                    [*self._spans, span], [*self._adapters(), adapter], trace_id
                ).ids
            )
        node_id = identify(
            span,
            adapter,
            trace_id,
            span_id_is_unique=span.span_id is not None and claims == 1,
            source_key_is_unique=keys == 1,
        )
        if node_id in self._position_of:
            raise collision(node_id, self._spans[self._position_of[node_id]], span)
        return node_id

    def _adapters(self) -> list[str | None]:
        """The adapter that read each span absorbed so far, in arrival order."""
        return [
            producer.id if producer is not None else None
            for producer in self._producers
        ]

    def _restate_every_record(self, assigned: list[NodeId]) -> None:
        """Throw everything derived away and derive it again from the counts.

        What the three whole-input facts are worth: when one of them moves,
        so can every id -- and an id is what every edge and diagnostic is keyed
        by. It is O(n) for the arrival that trips it, and `SPEC.md` §10 says so
        rather than implying every absorb is local.
        """
        self._tally.clear()
        self._forget()
        for position in range(len(self._spans)):
            self._absorb_at(position, assigned[position])

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

    def _absorb_at(self, position: int, node_id: NodeId) -> None:
        """Everything one record contributes, and everything it completes.

        `node_id` is the id `absorb` already derived for this position, under
        the counts that now stand. It is passed in rather than derived again
        because deriving it is the check that decides the refusal, and that
        check has to happen before any of this runs (`SPEC.md` §10.5).
        """
        span = self._spans[position]
        producer = self._producers[position]
        adapter = producer.id if producer is not None else None
        unique_span_id = (
            span.span_id is not None and self._span_id_counts[span.span_id] == 1
        )

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
            given = [
                other
                for other in sorted(self._awaiting_parent.get(span.span_id, ()))
                if other != position
            ]
            for other in given:
                self._restate_parent(other)
            # Every one of them in one move, not one move each: in the shape
            # where a trace's root arrives after its children, `given` is the
            # whole input (`SPEC.md` §10.6).
            self._regroup_many(given)
            for other in sorted(self._awaiting_link.get(span.span_id, ())):
                if other != position:
                    self._restate_links(other)

        self._restate_calls(self._index_calls(span, node_id))
        self._place(position)

    def _index_calls(self, span: NormalizedSpan, node_id: NodeId) -> set[str]:
        """Index the call ids this record names; answer whose *sides* moved.

        Two keys per call id and they are no longer restated together. A call
        id's `call_result` edges are decided by its requesters and fulfillers
        (§4.4), so only a span on one of those sides moves them, and the answer
        is which call ids those were. Its `data` edges are decided by its
        fulfillers and the spans declaring receipt (§4.2), and those are
        *amended* here, as the sibling chain is: a receipt that declares what
        every earlier one already declared is one edge per fulfiller and not the
        call id's whole set (`SPEC.md` §10.6).

        Sorted, both loops. Nothing here may turn on how a set iterates
        (`CLAUDE.md` 4) -- the edges an arrival makes do not depend on the order
        it names its call ids in, and sorting says so rather than relying on it.

        The role is compared by **value**, as `build._call_sides` compares it:
        `CallRole` is a `StrEnum`, so an adapter may hand over the plain string
        `"fulfiller"`, and reading that as a requester here while the batch
        build reads it as a fulfiller would be a §10.1 divergence with no
        diagnostic to show for it.
        """
        sides: set[str] = set()
        if span.call_ids and span.call_role is not None:
            fulfils = span.call_role == CallRole.FULFILLER
            side = self._fulfillers if fulfils else self._requesters
            for call_id in sorted(set(span.call_ids)):
                side.setdefault(call_id, []).append(node_id)
                named = span.call_names.get(call_id)
                if named is not None:
                    self._call_names.setdefault(call_id, set()).add(named)
                sides.add(call_id)
                if fulfils:
                    self._fulfilled(call_id, node_id)
        start = span.started_at if span.started_at is not None else float("inf")
        for call_id in sorted(set(span.received_call_ids)):
            self._received(call_id, (start, node_id))
        return sides

    def _fulfilled(self, call_id: str, producer: NodeId) -> None:
        """A span that answered this call: one `data` edge to every receipt.

        A producer arriving after the spans that declared receipt of it completes
        a relation each of them already stated, so each is a *new* edge and the
        arrival is linear in the receipts -- which is the size of the answer and
        not a restatement of it. No basis moves: ranking receipts is §4.2.1's and
        a fulfiller is not in that ranking.
        """
        receipts = self._receipts.get(call_id)
        if not receipts:
            return
        held = self._data_edges.setdefault(call_id, {})
        added: list[Edge] = []
        for receipt in receipts:
            edges = build.data_edges_of(
                receipt[1],
                (producer,),
                build.data_basis(receipt, receipts),
                self._by_node,
            )
            if edges:
                held[receipt[1]] = (*held.get(receipt[1], ()), *edges)
                added.extend(edges)
        self._tally.amend_edges((), added)

    def _received(self, call_id: str, receipt: tuple[int | float, NodeId]) -> None:
        """One declared receipt into a call id, and only the edges it moved.

        The ranking §4.2.1 states is a fact about the whole set of receipts, so
        restating the key was how the live builder kept it true -- and that made a
        protocol resending its history pay for every declaration it had already
        made, on every turn. What the ranking actually turns on is narrower: the
        receipt that ranks **first**, and whether the second ties with it. So the
        receipts are kept in that order and an arrival moves at most two of them:

        * its own, which is new, at one edge per span that answered the call;
        * the one that ranked first before, if this arrival outranks it (now "not
          the earliest") or ties with it (now "earliest tied") -- one removal and
          one addition per edge, which is what `SPEC.md` §10.6 says a basis
          rewrite is and what `Delta.basis_rewritten` reports.

        Every other receipt was already "not the earliest" and stays so, whatever
        arrives: no arrival can make a receipt that is not first become first
        except by being first itself. The edges are the ones a batch build of the
        same prefix emits -- `data_basis` is the only spelling of the rule -- and
        that is §10.1.
        """
        receipts = self._receipts.setdefault(call_id, [])
        was_first = receipts[0] if receipts else None
        bisect.insort(receipts, receipt)
        held = self._data_edges.setdefault(call_id, {})
        answered = sorted(self._fulfillers.get(call_id, ()))
        removed: list[Edge] = []
        added: list[Edge] = []
        if was_first is not None:
            # Every edge of one receipt carries that receipt's basis, so the
            # first of them says what the ranking said when they were made.
            stale = held.get(was_first[1], ())
            fresh = build.data_basis(was_first, receipts)
            if stale and stale[0].basis != fresh:
                removed.extend(stale)
                rewritten = build.data_edges_of(
                    was_first[1], answered, fresh, self._by_node
                )
                held[was_first[1]] = tuple(rewritten)
                added.extend(rewritten)
        mine = build.data_edges_of(
            receipt[1], answered, build.data_basis(receipt, receipts), self._by_node
        )
        if mine:
            held[receipt[1]] = tuple(mine)
            added.extend(mine)
        self._tally.amend_edges(removed, added)

    def _restate_parent(self, position: int) -> None:
        """One record's `parent` edge and `orphan_parent`, as they stand now.

        The sibling group a record belongs to follows from this edge, but the
        move is **not** made here. One arrival can give a parent to every record
        waiting on it, and `_regroup_many` moves all of them in one operation
        rather than one each, which is what makes a late parent O(n) in the
        records it un-orphans instead of O(n log n) (`SPEC.md` §10.6). The
        arriving record is not moved at all: it has not been placed yet, and
        `_place` reads the same edge.
        """
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
        """One call id's `call_result` edges and its pairing diagnostics (§4.4).

        Restated in full, and small enough to be: the key is the requesters and
        the fulfillers of one call, which is one span each in every shape anyone
        has captured. A call id's `data` edges are *not* here -- they are amended
        per receipt by `_received`, because the spans declaring receipt of one
        call grow with the conversation while its two sides do not
        (`SPEC.md` §10.6).
        """
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
            self._tally.set_edges(("call", call_id), self._call_edges[call_id])
            self._tally.set_diagnostics(
                ("call", call_id), self._call_diagnostics[call_id]
            )

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
        """Put a record in its sibling group, between the two it belongs between."""
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
        self._join(group, position)

    def _regroup_many(self, positions: Sequence[int]) -> None:
        """Every record one arrival gave a parent, moved to its group **once**.

        A record's group follows from its `parent` edge, so an arrival that
        resolves a reference moves every record that was waiting on it -- and
        where that reference is a trace's root arriving after its children, the
        records waiting on it are the whole input, moved inside a single `feed`
        (`SPEC.md` §10.2, §10.6). Moving them one at a time is correct, and is
        what the second half below does; moving them together is what the first
        half does instead, and the difference is the whole of this method.

        The case it is worth separating is that the records moving are **all** of
        the group they leave and the group they join holds nothing yet -- the
        orphaned children of one parent, with nothing else at trace root. Then
        the chain they had *is* the chain they keep. A `temporal` edge names its
        two endpoints and the group they sit in is not one of its fields, and
        their order inside the group cannot have moved either, because §4.3's key
        is `(started_at, node_id)` and a regroup changes neither. So the group is
        **re-keyed** and no edge moves at all: no ledger traffic, nothing to roll
        back, and -- the reason this is the bulk move rather than a chain rebuilt
        once per arrival -- no second spelling of §4.3's rule.

        Otherwise the records leave and join one at a time, one `_leave` and one
        `_join` each, because a group that keeps some of its members ends up with
        a chain that has holes in it and the edges bridging those holes are
        exactly the ones `_leave` already makes.

        A record that was never placed is never moved: one with no `started_at`
        is in no group (§4.3), and the arriving record is put in its group by
        `_place`, after this, from the same edge.
        """
        moves: dict[tuple[str, str], list[int]] = {}
        for position in positions:
            was = self._group_of.get(position)
            if was is None:
                continue
            now = self._group_key(position)
            if now != was:
                moves.setdefault((was, now), []).append(position)
        # Sorted rather than in insertion order: nothing here may turn on how a
        # dict iterates (`CLAUDE.md` 4). Where two moves name one group, which of
        # them goes first decides which takes the re-key and never the chains
        # either leaves behind, so the order is a tie-break and not a rule.
        for was, now in sorted(moves):
            movers = moves[(was, now)]
            if len(movers) == len(self._groups[was]) and now not in self._groups:
                self._groups[now] = self._groups.pop(was)
                self._temporal_edges[now] = self._temporal_edges.pop(was)
                for position in movers:
                    self._group_of[position] = now
                continue
            for position in movers:
                self._leave(was, position)
                self._group_of[position] = now
                self._join(now, position)

    def _group_key(self, position: int) -> str:
        edge = self._parent_edges.get(position)
        return edge.src if edge is not None else ROOT_GROUP

    def _rank(self, position: int) -> tuple[int | float, str]:
        """Where this record sits in its group's order -- §4.3's tie-break key.

        The *same* key the batch path sorts a group by (`build.tie_break`), and
        it has to be: this is what `bisect` below searches on, so a second
        spelling of it would put an arrival in a place the batch build does not,
        which is a determinism bug and not a slow path (`CLAUDE.md` 4).

        It is **unique** within a group and **stable** while a record is in one,
        which together are what let `_leave` find a member by searching for it
        rather than by scanning: unique because the key ends in a node id and two
        records resolving to one id is refused (§3.6), and stable because the key
        is read off a node built once in `_absorb_at` and the one thing that can
        move a node id -- a whole-input fact changing (§10.2) -- throws every
        group away and rebuilds it.
        """
        return build.tie_break(self._nodes[position])

    def _join(self, group: str, position: int) -> None:
        """One record into a group, and only the chain edges next to it (§4.3).

        The group's members are held in §4.3's order, so the record's place is a
        `bisect` and the chain around it is three edges at most: the one that
        joined its new neighbours to each other goes, and the two that join it to
        each of them arrive. A group of `m` is `m - 1` edges and `m - 2` of them
        are untouched, so they are *reused* rather than rebuilt -- which is the
        difference between this and restating the key (`SPEC.md` §10.6).

        The three cases are the three ends: at the front and at the back there is
        no edge to remove and one to add, and in the middle there is one of each
        way. The slice assignment is all three, because the chain's index `j` is
        the edge from member `j` to member `j + 1` and that stays true on both
        sides of the splice.
        """
        members = self._groups.setdefault(group, [])
        chain = self._temporal_edges.setdefault(group, [])
        index = bisect.bisect_left(members, self._rank(position), key=self._rank)
        members.insert(index, position)
        before = (
            build.temporal_edge(self._nodes[members[index - 1]], self._nodes[position])
            if index > 0
            else None
        )
        after = (
            build.temporal_edge(self._nodes[position], self._nodes[members[index + 1]])
            if index + 1 < len(members)
            else None
        )
        added = [edge for edge in (before, after) if edge is not None]
        cut = max(index - 1, 0)
        stop = cut + (1 if before is not None and after is not None else 0)
        removed = chain[cut:stop]
        chain[cut:stop] = added
        self._tally.amend_edges(removed, added)

    def _leave(self, group: str, position: int) -> None:
        """One record out of a group: its two chain edges for the one that
        bridges the neighbours it was between. The inverse of `_join`, down to
        the same slice."""
        members = self._groups[group]
        chain = self._temporal_edges[group]
        index = bisect.bisect_left(members, self._rank(position), key=self._rank)
        before = chain[index - 1] if index > 0 else None
        after = chain[index] if index + 1 < len(members) else None
        removed = [edge for edge in (before, after) if edge is not None]
        added = (
            [
                build.temporal_edge(
                    self._nodes[members[index - 1]], self._nodes[members[index + 1]]
                )
            ]
            if before is not None and after is not None
            else []
        )
        cut = max(index - 1, 0)
        chain[cut : cut + len(removed)] = added
        members.pop(index)
        if not members:
            self._groups.pop(group, None)
            self._temporal_edges.pop(group, None)
        self._tally.amend_edges(removed, added)

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
                *(
                    edge
                    for call_id in sorted(self._data_edges)
                    for edge in _flattened(self._data_edges[call_id])
                ),
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
