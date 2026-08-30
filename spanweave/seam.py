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
    #: **Normally `None`, and then the builder supplies the basis.** `basis`
    #: describes how an edge came to be, and the builder is what brings edges
    #: into being, so the vocabulary is its account to give (`SPEC.md` §4.0).
    #: This field is the single reserved exception: a dialect that states
    #: *why* a link exists -- not merely that it does -- may say so here, and
    #: the builder carries the reason verbatim onto the edge.
    #:
    #: **No observed dialect does.** Both adapters leave it `None` and every
    #: `link` edge in the corpus carries the builder's `LINK_BASIS`. It is
    #: kept -- where `DeclaredDataEdge` was removed -- because the evidence
    #: differs: that type was never populated *and* the case it existed for
    #: had demonstrably arrived and been routed elsewhere, while here the case
    #: has never arrived at all. Two dialects that both read the same
    #: record-level `links` field cannot tell those apart (`TASKS.md` I1).
    basis: str | None = None
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)


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
    #: Call id -> the name the dialect gave that call's tool, for the ids in
    #: `call_ids`. Empty where the dialect names none; never inferred.
    #:
    #: Only reason it exists: a requested call that no span fulfils has **no
    #: node**, so `operation` -- where a tool's name lives (`SPEC.md` §3.2) --
    #: has nowhere to be, and the tool a fleet asked for and never ran was
    #: unattributable from the graph (`SPEC.md` §3.7, `source` per code). It is
    #: read by `unpaired_call` / `unpaired_result` and nothing else.
    call_names: Mapping[str, str] = field(default_factory=dict)
    links: tuple[SpanLink, ...] = ()
    #: Call ids whose **results this span was given** -- the dialect declaring
    #: that some other span's output became this span's input.
    #:
    #: This is how a declared `data` relation reaches the graph, and it is the
    #: **only** way: an adapter cannot name the producer, because it sees one
    #: span and the span says only "I received the result of call X".
    #: Resolving X to the span that fulfilled it needs the whole trace, so the
    #: builder does it -- exactly the division of labour `call_ids` already
    #: uses for `call_result` (`SPEC.md` §4.2).
    #:
    #: A `DeclaredDataEdge` seam type once let an adapter name both ends and
    #: supply the edge's `basis` itself. No adapter ever populated it; when
    #: the real case arrived it came in this shape instead, because a span is
    #: not a vantage point from which the other end is visible. Removed at
    #: `TASKS.md` I1.
    received_call_ids: tuple[str, ...] = ()
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
        object.__setattr__(self, "call_names", dict(self.call_names))
