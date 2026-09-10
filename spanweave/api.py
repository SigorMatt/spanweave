"""The public entrypoint: a trace goes in, a graph comes out.

This is the top layer, above the seam and above the builder, and it is one of
only two modules allowed to reach the adapter registry (``DESIGN.md`` §2). It
does the wiring -- read, classify, parse, build -- and nothing else.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from spanweave.adapters import Partition, detect, get, partition
from spanweave.build import Contribution, build_contributed_graph
from spanweave.graph import Graph
from spanweave.model import AdapterInfo, JsonValue
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
    """
    stream = read_trace(source)
    records = list(stream)

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
        collector=stream.diagnostics,
        source_digest=stream.digest,
        temporal=temporal,
    )


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

    An adapter numbers what it is given (`ADAPTERS.md` §3), and under
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
