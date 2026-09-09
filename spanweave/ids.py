"""Node identity.

Determinism is not a nice property here -- it is the reason a downstream tool
can diff two runs, cache a result, or gate CI on a graph (``DESIGN.md`` §4).
So ids are computed the same way on every machine, in every process, forever:

1. the dialect's own span id, when it is unique within the trace;
2. otherwise ``sw_`` + the first 16 hex characters of a SHA-256 over the
   adapter id, the trace id, and the adapter's stable source key;
3. and when two records share that source key -- which is what a dialect
   that reused a span id looks like from here -- the record's own canonical
   digest joins the material, so the two get two ids and both are kept.

Rule 3 disambiguates on **content, never on position**. Numbering the
records that share a key would make an id depend on where its record sat in
the file, and input order must not affect the result (``CLAUDE.md`` 4). It is
total because the reader has already collapsed records that are the same
record (``SPEC.md`` §7), so two survivors sharing a key differ somewhere.

Python's built-in ``hash()`` is forbidden anywhere near this file. It is
salted per process, so a graph built twice would not be the same graph -- and
the breakage would be invisible inside any single run. A CI gate enforces the
ban rather than trusting anyone to remember it (``TASKS.md`` 0.4).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from spanweave.errors import DuplicateNodeIdError
from spanweave.model import NodeId
from spanweave.read import record_digest
from spanweave.seam import NormalizedSpan

DERIVED_PREFIX = "sw_"
DERIVED_LENGTH = 16
_SEPARATOR = "\x00"


@dataclass(frozen=True, slots=True)
class Assignment:
    """The ids for a set of spans, plus what was odd about getting them."""

    #: One id per span, in the order the spans were given.
    ids: tuple[NodeId, ...]
    #: Source ids claimed by more than one record. These did not collide as
    #: node ids -- a collision is a hard error -- but the duplication is worth
    #: reporting, because it means the dialect's own ids are not unique.
    duplicate_source_ids: tuple[str, ...] = ()


def derive(
    adapter_id: str,
    trace_id: str | None,
    source_key: str,
    record: str | None = None,
) -> NodeId:
    """A stable id for a span the dialect did not give a unique one to.

    SHA-256 rather than anything faster because it is stable across
    processes and versions, which is the only property that matters here.

    ``record`` is the canonical digest of the source record, and it is
    supplied only for rule 3 -- a source key two records share. Passing it is
    what separates them; omitting it leaves rule 2's material exactly as it
    has always been, so no id that exists today moves.
    """
    parts = (adapter_id, trace_id or "", source_key)
    material = _SEPARATOR.join(parts if record is None else (*parts, record))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{DERIVED_PREFIX}{digest[:DERIVED_LENGTH]}"


def assign(
    spans: Sequence[NormalizedSpan], adapter_id: str, trace_id: str | None
) -> Assignment:
    """Give every span an id, or refuse because two of them are the same."""
    seen: dict[str, int] = {}
    keys: dict[str, int] = {}
    for span in spans:
        if span.span_id is not None:
            seen[span.span_id] = seen.get(span.span_id, 0) + 1
        keys[span.source_key] = keys.get(span.source_key, 0) + 1

    ids: list[NodeId] = []
    for span in spans:
        # A span id that is not unique within the trace does not qualify under
        # rule 1, so it falls through to a derived id. Because the adapter's
        # source key is normally that same id, those records also share a
        # source key -- rule 3's case, where the record's own digest is what
        # tells them apart. Both are kept; the duplication is reported below.
        if span.span_id is not None and seen[span.span_id] == 1:
            ids.append(span.span_id)
        elif keys[span.source_key] == 1:
            ids.append(derive(adapter_id, trace_id, span.source_key))
        else:
            ids.append(
                derive(
                    adapter_id,
                    trace_id,
                    span.source_key,
                    record_digest(span.raw.source),
                )
            )

    _refuse_collisions(ids, spans)
    duplicates = tuple(sorted(key for key, count in seen.items() if count > 1))
    return Assignment(ids=tuple(ids), duplicate_source_ids=duplicates)


def _refuse_collisions(ids: Sequence[NodeId], spans: Sequence[NormalizedSpan]) -> None:
    positions: dict[NodeId, int] = {}
    for index, node_id in enumerate(ids):
        first = positions.get(node_id)
        if first is None:
            positions[node_id] = index
            continue
        # A silent overwrite would drop a record, and losslessness is not
        # negotiable. Better to refuse the whole graph than to publish one
        # that is quietly missing a span (SPEC.md §3.6).
        #
        # No trace file reaches here: rule 3 separates two records that share
        # a source key, and the reader has already collapsed the case where
        # they do not differ at all. What is left is a SHA-256 collision, or a
        # caller that built two identical spans itself -- and for those two
        # there is still nothing to derive a second id from.
        raise DuplicateNodeIdError(
            f"two records resolve to the node id {node_id!r}: "
            f"source keys {spans[first].source_key!r} (record "
            f"{spans[first].raw.line_number}) and "
            f"{spans[index].source_key!r} (record "
            f"{spans[index].raw.line_number}). Refusing to overwrite one with "
            f"the other."
        )
