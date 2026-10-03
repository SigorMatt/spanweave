"""The public entrypoint: a trace goes in, a graph comes out.

This is the top layer, above the seam and above the builder, and it is one of
only two modules allowed to reach the adapter registry (``DESIGN.md`` §2). It
does the wiring -- read, classify, parse, build -- and nothing else.

Two entry points, one wiring. ``build`` reads a whole input and builds once;
``Builder`` takes the records one at a time and builds the prefix graph on
demand (``SPEC.md`` §10). They share ``graph_from_records`` and the
classification below it, because "the live graph at version k **is** the batch
graph of the first k records" is only a contract worth having if there is one
implementation of the wiring behind it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from typing import Literal

from spanweave.adapters import (
    DETECTION_SAMPLE_SIZE,
    Partition,
    ambiguous_claim,
    classify,
    declared,
    detect,
    get,
    partition,
)
from spanweave.build import Contribution, build_contributed_graph
from spanweave.delta import (
    Delta,
    Journal,
    Retention,
    order_moved,
    ordering,
)
from spanweave.diagnostics import DiagnosticCollector
from spanweave.errors import AdapterSelectionError
from spanweave.graph import Graph
from spanweave.incremental import SpanAbsorber
from spanweave.model import AdapterInfo, Diagnostic, Edge, JsonValue, Node
from spanweave.read import Source, read_trace
from spanweave.seam import NormalizedSpan, unclaimed_span


def build(
    source: Source, *, adapter: str | None = None, temporal: bool = True
) -> Graph:
    """Build a graph from a trace file, a path, ``"-"``, or raw bytes.

    ``adapter`` names a dialect and skips classification. Without it, every
    registered adapter is asked about every **record** -- a dialect is a
    property of a record, not of a file -- each adapter parses the records it
    claimed, and the builder receives all of their spans together. An
    ambiguous answer about one record is a hard error rather than a guess, and
    a record no adapter claims is kept as an `unknown` node with an
    `unclaimed_record` diagnostic (`SPEC.md` §6.1).

    The partition happens here, above the seam and above the builder: nothing
    below learns that more than one adapter exists, let alone which.

    A record the reader could not read at all never reaches the partition, so
    how many of those there were travels to the builder beside the digest. It
    is the one fact about the input that no `Contribution` can carry, and a
    statement about the whole input needs it (`SPEC.md` §3.7).
    """
    stream = read_trace(source)
    records = list(stream)
    return graph_from_records(
        records,
        adapter=adapter,
        temporal=temporal,
        collector=stream.diagnostics,
        source_digest=stream.digest,
        skipped_records=stream.skipped_records,
    )


def graph_from_records(
    records: Sequence[JsonValue],
    *,
    adapter: str | None = None,
    temporal: bool = True,
    collector: DiagnosticCollector | None = None,
    source_digest: str | None = None,
    skipped_records: int = 0,
) -> Graph:
    """Build a graph from records already read out of an input.

    ``build``'s second half, and the definition `Builder` is held to: the live
    graph at version `k` is this function's result for the first `k` records
    (`SPEC.md` §10). Internal -- the public records-in API is a separate
    decision (`OPEN_QUESTIONS.md` §19) -- but the same code, so the two paths
    cannot drift.
    """
    if adapter is not None:
        chosen = get(adapter)
        contributions = [
            Contribution(
                adapter=AdapterInfo(id=chosen.id, version=chosen.version),
                spans=tuple(chosen.parse(records)),
            )
        ]
    else:
        sorted_out = partition(records)
        if not sorted_out.claims:
            # No record claimed by anybody. Refused exactly as whole-input
            # selection always refused it, listing every declared confidence
            # (`SPEC.md` §6.1) -- building a graph of nothing but `unknown`
            # nodes would be a plausible-looking answer to "can you read
            # this?" when the answer is no. `detect()` is what raises; it
            # cannot return here, because a return would mean some adapter
            # reached the threshold and so would have claimed a record.
            detect(records)
        contributions = _contributions(sorted_out, records)

    return build_contributed_graph(
        contributions,
        collector=collector,
        source_digest=source_digest,
        skipped_records=skipped_records,
        temporal=temporal,
    )


class Builder:
    """Build the graph of a stream that has not finished arriving.

    ``feed`` absorbs one record and returns the new version -- an `int`, the
    count of records absorbed, and never a graph or a delta. ``graph``
    materializes the graph of everything absorbed so far, and that graph **is**
    the batch graph of those records: at version `k` it equals
    ``graph_from_records(records[:k])`` byte for byte (`SPEC.md` §10). Arrival
    order indexes versions; inside a version the order is canonical, as it
    always is.

    What it deliberately does not carry: a digest of an input it never saw,
    and the reader's facts about bytes -- a malformed line, a record sent
    twice. Those belong to whoever read the records (`SPEC.md` §7).

    One builder per trace. Records of two traces in one builder are kept and
    reported exactly as a multi-trace file is, and partitioning a live stream
    by trace is the caller's (`OPEN_QUESTIONS.md` §19).
    """

    def __init__(self, *, adapter: str | None = None, temporal: bool = True) -> None:
        self._named = adapter
        self._absorber = SpanAbsorber(temporal=temporal)
        self._journal = Journal()
        self._version = 0
        self._claimed = 0
        #: Kept only while **nothing** has been claimed, for the refusal that
        #: an input nobody can read earns. Cleared on the first claim, so a
        #: long stream holds no second copy of its records.
        self._unread: list[JsonValue] = []
        #: Up to `DETECTION_SAMPLE_SIZE` claimed records per adapter, because
        #: `declared_confidence` is declared over exactly that sample and so
        #: changes while it fills (`SPEC.md` §6.1).
        self._sample: dict[str, list[JsonValue]] = {}
        self._graph: Graph | None = None

    @property
    def version(self) -> int:
        """How many records have been absorbed. The version index (`§10`)."""
        return self._version

    def feed(self, record: JsonValue) -> int:
        """Absorb one record; return the version it produced.

        The record is classified on its own, as every record in a batch build
        is (`SPEC.md` §6.1): two adapters claiming it is refused rather than
        guessed, and nobody claiming it makes an `unknown` node carrying the
        record verbatim. A refused record is **not** absorbed and the version
        does not move -- there is no half-arrival. That holds for every refusal
        `feed` can raise, the node-id collision of `SPEC.md` §3.6 included: the
        builder is left as it was, so the next `feed` and every later `graph()`
        and `delta()` answer as they would have had the record never arrived
        (`SPEC.md` §10.5).

        A record becomes **however many spans** its adapter yields, and they
        arrive together: translating writes nothing, the spans are absorbed,
        and only then is anything committed. Both ends of that are necessary --
        a refusal raised after `_translate` had written would leave `_claimed`
        moved, and `_claimed` is what `graph()`'s own refusal is gated on; a
        refusal raised on the second span of a record would leave the first
        absorbed, which is the same promise broken quietly instead of loudly.
        """
        position = self._version + 1
        staged = self._translate(record, position)
        absorbed = self._absorber.span_count()
        self._absorber.begin()
        try:
            for span in staged.spans:
                self._absorber.absorb(span, staged.producer)
        except BaseException:
            # Re-raised unchanged; the rollback is what the caller is promised
            # on the way out, not a different outcome. `BaseException` because
            # an interrupt between two spans of one record leaves the same
            # half-arrival a refusal would.
            self._absorber.rollback_to(absorbed)
            raise
        self._journal.record(position, self._absorber.finish())
        self._version = position
        self._commit(record, staged)
        self._graph = None
        return self._version

    def retain(self, versions: Retention = "all") -> None:
        """How much journal to keep: `N` versions, `0`, or `"all"` (§10.8).

        The caller's policy, because only the caller knows how far behind its
        consumers run. It applies at once rather than at the next `feed`, so
        narrowing it frees the entries now.
        """
        self._journal.retain(versions, self._version)

    def delta(self, *, since: int) -> Delta:
        """What changed between version ``since`` and now (`SPEC.md` §10.6).

        The per-record mode is ``delta(since=version - 1)``; `feed` itself
        returns the new version and never this. ``since=0`` is the difference
        from an empty builder, so everything absorbed so far is an addition --
        and there is no graph at version 0 to fold it onto, because an empty
        builder refuses (§10.5).

        Raises `DeltaUnavailableError` when retention has dropped `since`, and
        `ValueError` when `since` is not a version this builder has reached.
        """
        if not 0 <= since <= self._version:
            raise ValueError(
                f"since={since} is not a version this builder has reached: it "
                f"is at version {self._version}, so `since` runs from 0 to "
                f"{self._version} (`SPEC.md` §10.6)"
            )
        self._journal.held(since, self._version)
        change = self._journal.fold(since, self._version, self._absorber.facts())

        nodes_now = self._absorber.current_nodes()
        edges_now = self._absorber.current_edges()
        nodes_then = _rewound_nodes(nodes_now, change.nodes_added, change.nodes_removed)
        edges_then = _rewound_edges(edges_now, change.edges_added, change.edges_removed)
        order_now, cycle_now = ordering(nodes_now, edges_now, change.after.whole_input)
        order_then, cycle_then = ordering(
            nodes_then, edges_then, change.before.whole_input
        )
        return Delta(
            since=since,
            until=self._version,
            nodes_added=change.nodes_added,
            nodes_removed=change.nodes_removed,
            edges_added=change.edges_added,
            edges_removed=change.edges_removed,
            diagnostics_opened=(
                *change.diagnostics_opened,
                *_missing(cycle_now, cycle_then),
            ),
            diagnostics_resolved=(
                *change.diagnostics_resolved,
                *_missing(cycle_then, cycle_now),
            ),
            trace_id_before=change.before.trace_id,
            trace_id_after=change.after.trace_id,
            adapters_before=change.before.adapters,
            adapters_after=change.after.adapters,
            order_changed=order_moved(order_then, order_now),
            restated=change.restated,
        )

    def graph(self) -> Graph:
        """The graph of the records absorbed so far.

        Materialized on demand and kept until the next `feed`, so asking twice
        builds once. Refuses where the batch build refuses: no record claimed by
        any adapter is not a graph of `unknown` nodes, it is "nothing here can
        read this" (`SPEC.md` §6.1), and that is as true of an empty stream as
        of an unreadable one.
        """
        if self._graph is None:
            if self._named is None and self._claimed == 0:
                detect(self._unread)
            self._graph = self._absorber.materialize()
        return self._graph

    def _translate(self, record: JsonValue, position: int) -> _Staged:
        """One record, over the seam: who read it, what it became, and what
        absorbing it would commit. It writes **nothing** (`SPEC.md` §10.5)."""
        if self._named is not None:
            chosen = get(self._named)
            return _Staged(
                producer=AdapterInfo(id=chosen.id, version=chosen.version),
                spans=_numbered(chosen.parse([record]), position),
                claimed=self._claimed + 1,
                unread="keep",
            )
        claimants = classify(record)
        if len(claimants) > 1:
            raise AdapterSelectionError(ambiguous_claim(position, record, claimants))
        if not claimants:
            return _Staged(
                producer=None,
                spans=(unclaimed_span(record, position),),
                claimed=self._claimed,
                unread="append" if self._claimed == 0 else "keep",
            )
        chosen = get(claimants[0])
        held: Sequence[JsonValue] = self._sample.get(chosen.id, ())
        joins = len(held) < DETECTION_SAMPLE_SIZE
        return _Staged(
            producer=AdapterInfo(
                id=chosen.id,
                version=chosen.version,
                # Declared over the sample **with** this record in it, which is
                # what it was declared over when the append came first. Bounded
                # by `DETECTION_SAMPLE_SIZE`, so the copy costs nothing that
                # grows with the stream.
                declared_confidence=declared(
                    chosen, [*held, record] if joins else held
                ),
            ),
            spans=_numbered(chosen.parse([record]), position),
            claimed=self._claimed + 1,
            unread="clear",
            sampled=chosen.id if joins else None,
        )

    def _commit(self, record: JsonValue, staged: _Staged) -> None:
        """Write what the arrival earned, now that every span of it landed."""
        self._claimed = staged.claimed
        if staged.unread == "append":
            self._unread.append(record)
        elif staged.unread == "clear":
            self._unread.clear()
        if staged.sampled is not None:
            self._sample.setdefault(staged.sampled, []).append(record)


@dataclasses.dataclass(frozen=True, slots=True)
class _Staged:
    """One record translated, and what absorbing it would commit above the seam.

    `_translate` used to write these three as it went, and a refusal raised
    afterwards left them moved -- `_claimed` among them, which is what
    `graph()`'s own refusal is gated on, so a record that was claimed and then
    refused could turn "nothing here can read this" into a one-node graph
    (`SPEC.md` §10.5). Staged here and written by `_commit` once every span of
    the record has been absorbed.
    """

    producer: AdapterInfo | None
    spans: tuple[NormalizedSpan, ...]
    #: `_claimed` as it stands once this record has arrived.
    claimed: int
    #: What the arrival does to the records kept while nothing has claimed one.
    unread: Literal["keep", "append", "clear"]
    #: The adapter whose detection sample this record joins, where it joins one.
    sampled: str | None = None


def _rewound_nodes(
    now: Sequence[Node], added: Sequence[Node], removed: Sequence[Node]
) -> tuple[Node, ...]:
    """The node set as it stood at `since`: undo what the window did to it.

    Rewinding rather than keeping a copy per version, because a copy per
    version is a graph per version and the whole point of a delta is not
    paying that (`OPEN_QUESTIONS.md` §18).
    """
    kept = {node.id: node for node in now}
    for node in added:
        kept.pop(node.id, None)
    for node in removed:
        kept[node.id] = node
    return tuple(kept.values())


def _rewound_edges(
    now: Sequence[Edge], added: Sequence[Edge], removed: Sequence[Edge]
) -> tuple[Edge, ...]:
    kept = {edge.identity: edge for edge in now}
    for edge in added:
        kept.pop(edge.identity, None)
    for edge in removed:
        kept[edge.identity] = edge
    return tuple(kept.values())


def _missing(
    these: Sequence[Diagnostic], those: Sequence[Diagnostic]
) -> tuple[Diagnostic, ...]:
    """The ones `those` does not account for. Both are 0 or 1 item long."""
    return tuple(item for item in these if item not in those)


def _numbered(
    spans: Iterator[NormalizedSpan] | Sequence[NormalizedSpan], position: int
) -> tuple[NormalizedSpan, ...]:
    """Put each span's `line_number` where its record arrived.

    `_renumbered`'s rule for a partition of exactly one record: an adapter
    numbers what it is given (`ADAPTERS.md` §2), it was given one record, so
    the number it can have written is 1 -- and 1 points at the wrong record for
    every arrival after the first. Anything else the adapter chose to write is
    left alone (`SPEC.md` §3.5).
    """
    restored = []
    for span in spans:
        if span.raw.line_number == 1 and position != 1:
            restored.append(
                dataclasses.replace(
                    span, raw=dataclasses.replace(span.raw, line_number=position)
                )
            )
        else:
            restored.append(span)
    return tuple(restored)


def _contributions(
    sorted_out: Partition, records: Sequence[JsonValue]
) -> list[Contribution]:
    """Each adapter's spans from the records it claimed, plus the leftovers.

    An adapter is handed only its own records, so nothing it did not claim
    reaches its `parse()`. The records no adapter claimed are not handed to
    anyone: they become `unknown` nodes carrying the record verbatim, because
    giving them to a designated adapter would put a dialect's name on a node
    on the strength of that dialect having said nothing about the record
    (`SPEC.md` §6.1).
    """
    positions = _positions(records)
    contributions = [
        Contribution(
            adapter=AdapterInfo(
                id=claim.adapter_id,
                version=get(claim.adapter_id).version,
                declared_confidence=claim.declared_confidence,
            ),
            spans=_renumbered(
                tuple(get(claim.adapter_id).parse(claim.records)),
                claim.records,
                positions,
            ),
        )
        for claim in sorted_out.claims
    ]
    if sorted_out.unclaimed:
        contributions.append(
            Contribution(
                adapter=None,
                spans=tuple(
                    unclaimed_span(record, positions.get(id(record)))
                    for record in sorted_out.unclaimed
                ),
            )
        )
    return contributions


def _positions(records: Sequence[JsonValue]) -> dict[int, int]:
    """Where each record sat in the input, 1-based, by identity.

    By identity rather than by value because two records can be equal and
    still be two records (`SPEC.md` §7 collapses only the ones that are the
    same record). `partition()` hands back the very objects the reader
    yielded, so identity is exact here and is never used for anything else.
    """
    return {id(record): position for position, record in enumerate(records, start=1)}


def _renumbered(
    spans: tuple[NormalizedSpan, ...],
    claimed: Sequence[JsonValue],
    positions: dict[int, int],
) -> tuple[NormalizedSpan, ...]:
    """Put each span's `line_number` back where its record was in the input.

    An adapter numbers what it is given (`ADAPTERS.md` §2), and under
    per-record dispatch it is given a subset -- so its numbering counts that
    subset. `RawRecord.line_number` is what a diagnostic points a human at,
    and a number that counts a partition nobody can see points at nothing
    (`SPEC.md` §3.5, §6.1). It is not serialized, so no graph moves with it.

    Only a number that indexes the records this adapter was handed is
    translated; anything else the adapter chose to write is left alone.
    """
    restored = []
    for span in spans:
        inside = span.raw.line_number
        if inside is None or not 1 <= inside <= len(claimed):
            restored.append(span)
            continue
        where = positions.get(id(claimed[inside - 1]))
        if where is None or where == inside:
            restored.append(span)
            continue
        restored.append(
            dataclasses.replace(
                span, raw=dataclasses.replace(span.raw, line_number=where)
            )
        )
    return tuple(restored)
