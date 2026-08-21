"""The public entrypoint: a trace goes in, a graph comes out.

This is the top layer, above the seam and above the builder, and it is one of
only two modules allowed to reach the adapter registry (``DESIGN.md`` §2). It
does the wiring -- read, select a dialect, parse, build -- and nothing else.
"""

from __future__ import annotations

from spanweave.adapters import detect, get
from spanweave.build import build_graph
from spanweave.graph import Graph
from spanweave.model import AdapterInfo
from spanweave.read import Source, read_trace


def build(
    source: Source, *, adapter: str | None = None, temporal: bool = True
) -> Graph:
    """Build a graph from a trace file, a path, ``"-"``, or raw bytes.

    ``adapter`` names a dialect and skips detection. Without it, the
    registered adapters are asked how confident they are, and an ambiguous
    answer is a hard error rather than a guess (`SPEC.md` §6.1).
    """
    stream = read_trace(source)
    records = list(stream)

    if adapter is not None:
        chosen = get(adapter)
        declared = None
    else:
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
