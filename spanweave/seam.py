"""``NormalizedSpan`` -- the seam between an adapter and the builder.

Everything above this type is dialect-specific and lives in an adapter;
everything below it is dialect-agnostic and lives in the builder
(``DESIGN.md`` §3). The type sits in its own module precisely because it
belongs to *neither* side: the builder must be able to name it without
importing anything from ``adapters/``, and an adapter must be able to fill it
without importing the builder.

**This is not a public contract.** The *graph* is. The seam is dumpable for
debugging and is free to be refactored; publishing two schemas would double
the versioning burden for no consumer benefit (``DESIGN.md`` §3.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from spanweave.model import (
    Diagnostic,
    JsonValue,
    NodeKind,
    Payload,
    RawRecord,
    Status,
    Usage,
)


class CallRole(StrEnum):
    """Which end of a call/result pair a span sits at (`SPEC.md` §4.4)."""

    #: The span that asked for the call.
    REQUESTER = "requester"
    #: The span that answered it.
    FULFILLER = "fulfiller"


@dataclass(frozen=True, slots=True)
class SpanLink:
    """A span link, transcribed from the source (`SPEC.md` §4).

    Links are the one relation that routinely points **outside** the trace,
    so the linked span may have no node here. The adapter transcribes what the
    source said either way; deciding what to do about a foreign target is the
    builder's business, not a reason to drop the link.
    """

    span_id: str
    trace_id: str | None = None
    #: The source field this came from, carried onto the edge.
    basis: str = "span.link"
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeclaredDataEdge:
    """A producer -> consumer relation the **instrumentor itself** declared.

    Only ever transcribed, never computed. `spanweave` does not compare an
    output to an input and conclude a flow: that needs a threshold, a
    normalization rule and an encoding policy, none of them opinion-free
    (`SPEC.md` §4.2).
    """

    #: The producing span's id.
    src: str
    #: The consuming span's id.
    dst: str
    #: The source field that declared it. Required: an edge nobody can audit
    #: is an edge nobody should trust.
    basis: str


@dataclass(frozen=True, slots=True)
class NormalizedSpan:
    """One source record, translated out of its dialect (`SPEC.md` §6)."""

    #: Stable within this input. The dialect's span id where there is one,
    #: else the 1-based record index. Never synthesized by the adapter --
    #: node ids are `spanweave/ids.py`'s business.
    source_key: str
    kind: NodeKind
    #: As reported. Never prettified.
    name: str
    raw: RawRecord
    span_id: str | None = None
    parent_id: str | None = None
    trace_id: str | None = None
    operation: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    status: Status = Status.UNSET
    status_note: str | None = None
    inputs: Payload = field(default_factory=Payload.absent)
    outputs: Payload = field(default_factory=Payload.absent)
    usage: Usage | None = None
    #: For `call_result` pairing. Empty when the dialect carries no id:
    #: pairing by name, proximity or timing is forbidden, because a guessed
    #: pairing is indistinguishable from a real one downstream (`SPEC.md` §4.4).
    #:
    #: A tuple because one span routinely requests **several** tool calls at
    #: once, which is how current agent frameworks work. All of them share
    #: this span's `call_role`.
    call_ids: tuple[str, ...] = ()
    call_role: CallRole | None = None
    links: tuple[SpanLink, ...] = ()
    data_edges: tuple[DeclaredDataEdge, ...] = ()
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)
    #: Attribute **keys** the adapter saw and did not normalize. Keys only:
    #: the values are already in `raw`.
    unmapped: tuple[str, ...] = ()
    #: Anything the adapter wants a human to know about this record. Ends up
    #: on the node's `Provenance` (`SPEC.md` §3.5).
    dialect_note: str | None = None
    #: What the adapter could not map confidently. The seam carries these
    #: because `parse()` returns spans and has nowhere else to put them.
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", dict(self.attributes))
