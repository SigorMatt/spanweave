"""The public entrypoint: a trace goes in, a graph comes out.

This is the top layer, above the seam and above the builder, and it is one of
only two modules allowed to reach the adapter registry (``DESIGN.md`` §2). It
does the wiring -- read, select a dialect, parse, build -- and nothing else.
"""

from __future__ import annotations

from spanweave.adapters import detect, get, partition
from spanweave.build import build_graph
from spanweave.graph import Graph
from spanweave.model import AdapterInfo
from spanweave.read import Source, read_trace


def build(
    source: Source, *, adapter: str | None = None, temporal: bool = True
) -> Graph:
    """Build a graph from a trace file, a path, ``"-"``, or raw bytes.

    ``adapter`` names a dialect and skips classification. Without it, every
    registered adapter is asked about every **record** -- a dialect is a
    property of a record, not of a file -- and an ambiguous answer is a hard
    error rather than a guess (`SPEC.md` §6.1).

    The partition happens here, above the seam and above the builder: nothing
    below learns that more than one adapter exists, let alone which.
    """
    stream = read_trace(source)
    records = list(stream)

    if adapter is not None:
        chosen = get(adapter)
        declared = None
    else:
        claims = partition(records).claims
        if len(claims) == 1:
            chosen, declared = get(claims[0].adapter_id), claims[0].declared_confidence
        else:
            # Nobody claimed anything, or more than one adapter did. Nobody is
            # refused by whole-input selection, which lists every declared
            # confidence. More than one is an input written in several
            # dialects: the records have sorted themselves cleanly, but the
            # builder does not yet accept spans from more than one adapter, so
            # the input is refused exactly as it was before classification
            # existed -- and that refusal names the way out (`SPEC.md` §6.1).
            chosen, declared = detect(records)

    return build_graph(
        chosen.parse(records),
        adapter=AdapterInfo(
            id=chosen.id, version=chosen.version, declared_confidence=declared
        ),
        collector=stream.diagnostics,
        source_digest=stream.digest,
        temporal=temporal,
    )
