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

from spanweave.diagnostics import UNCLAIMED_RECORD
from spanweave.model import (
    Diagnostic,
    JsonValue,
    NodeKind,
    Payload,
    RawRecord,
    Status,
    Usage,
)
from spanweave.read import record_digest


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
    #: else the record's canonical digest (`spanweave.read.record_digest`) --
    #: content, never the record's position, because a key that moves when
    #: the file is re-exported names nothing (`SPEC.md` §3.6 rule 2). Never
    #: synthesized by the adapter -- node ids are `spanweave/ids.py`'s
    #: business.
    source_key: str
    kind: NodeKind
    #: As reported. Never prettified.
    name: str
    raw: RawRecord
    span_id: str | None = None
    parent_id: str | None = None
    trace_id: str | None = None
    operation: str | None = None
    #: Unix seconds, as reported. An integer literal stays an `int` and a
    #: fractional one a `float` -- float64 cannot hold epoch nanoseconds
    #: (`SPEC.md` §3.1). Never rescaled, never converted between the two.
    started_at: int | float | None = None
    ended_at: int | float | None = None
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


def _stated_id(value: JsonValue) -> str | None:
    """A span id a record states, or ``None`` where it states none.

    **The empty string is not a span id.** It names nothing at either end of
    a relation, so a record states no id by omitting the field, by reporting
    it ``null``, or by reporting it ``""`` -- three spellings of one fact
    (`SPEC.md` §3.6, §4.0). A value that is not a string at all is not an id
    either, and it is *reported* as well as ignored: that is
    `unreadable_fields`' business, not this function's.

    **Exactly the empty string.** ``" "`` and ``"0000000000000000"`` are ids
    like any other, because trimming or decoding one would be deciding what
    the telemetry meant. Nothing is lost either way: the record is in ``raw``
    verbatim, so which rendering the exporter used is still readable on the
    node (`CLAUDE.md` 2).

    Private because a caller should say which field it is reading -- the
    three public readers below are the same rule seen from each end of a
    relation, and having them share a body is the point: an identity rule and
    a reference rule that can drift apart is exactly the defect batch S3
    closed, and a third field left reading ``""`` is the one S10 closed.
    """
    if not isinstance(value, str) or value == "":
        return None
    return value


def span_ref(value: JsonValue) -> str | None:
    """The id a record gives **itself**, or ``None`` when it states none.

    An empty ``span_id`` is no id, so the record falls to `SPEC.md` §3.6 rule
    2 and is keyed by its content -- the identical answer an absent ``span_id``
    gets, because they are the identical statement.

    **This is what makes `parent_ref`'s reasoning true.** That rule normalizes
    an empty parent reference away on the ground that the empty string names a
    span no input can contain; while `""` was still accepted as an *identity*
    an input could contain exactly that span, and the `parent` edge between the
    two records -- `explicit`, and stated by the telemetry -- was dropped with
    no diagnostic at all. One end of a rule is not a rule.

    Nothing is reported, for `derived_ids`' reason: the record stated no id,
    rule 2 is the honest answer to that rather than a defect, and the empty
    string itself is still on the node's ``raw.source`` verbatim (§3.5).
    """
    return _stated_id(value)


def parent_ref(value: JsonValue) -> str | None:
    """The parent a record states, or ``None`` when it states none.

    A record spells "no parent" **two** ways, and they are the same statement
    (`SPEC.md` §4.0): the field is absent, or the field is present and empty.
    The second is the ordinary one rather than an edge case -- an OTLP
    `parentSpanId` is a proto3 ``bytes`` field, an unset one is the empty
    string, and a marshaler that emits defaults writes ``""`` on every root
    span of every export (`SPEC.md` §7).

    Read as a *reference*, that empty string names a span no input can
    contain -- which `span_ref` above is what makes true -- so every root drew
    an `orphan_parent`, the diagnostic that means "this trace is incomplete",
    reported on the one span that proves it is not. So it is normalized here,
    at the seam, and the builder goes on testing presence: an id that is not
    an id must not reach the layer that has no way to tell.

    It lives here rather than in each adapter because two dialects disagreeing
    about one root is a cross-dialect equivalence claim, not a detail: the
    same run exported twice must produce the same graph, and a rule copied
    into two modules is a rule that can drift in one of them.
    """
    return _stated_id(value)


def link_ref(value: JsonValue) -> str | None:
    """The span a link **targets**, or ``None`` when it names none.

    The third reference field, and the same rule as the other two: a link
    target is the far end of a relation, and the empty string is not a span
    id at either end of one (`SPEC.md` §3.6). Batch S3 applied the rule to
    `span_ref` and `parent_ref` and left this field reading ``""`` as a
    target, so a link stating ``span_id: ""`` became an ``explicit`` `link`
    edge whose ``dst`` was ``""`` -- a span `span_ref` had just made sure no
    input can contain (run-5 review 3.1). Absent, ``null`` and ``""`` are one
    statement here too, and exactly ``""``: ``" "`` is a target like any other.
    """
    return _stated_id(value)


def span_links(
    record: Mapping[str, JsonValue],
) -> tuple[tuple[SpanLink, ...], list[str]]:
    """A record's span links, and `<record>.<field>` for each it could not state.

    **A link entry that names no span is no link, and it is reported.** Its
    target is read by `link_ref`, so an entry whose ``span_id`` is absent,
    ``null`` or ``""`` states no target -- and one that is not a string, or an
    entry that is not an object at all, states none the adapter can read. None
    of them becomes a `SpanLink`: a link to nothing is not a relation, and an
    edge whose ``dst`` is ``""`` would be an ``explicit`` claim the telemetry
    never made.

    Where the other two fields are *not* reported, this one is, and the
    difference is what the reading leaves behind. A record with no ``span_id``
    is still a node, and a record with no parent is still a root: the
    statement is complete. A link entry exists only to name a span, so one
    that names none becomes **nothing**, and its ``trace_id`` and
    ``attributes`` would vanish between ``raw`` and the graph. Saying so is
    `unmapped_attributes`' job for a record field recognized and not read
    (`SPEC.md` §3.7), so the entry is named -- ``<record>.links[<i>]``, its
    place in *this record's* list, never the record's place in the file -- and
    its content stays in ``raw`` verbatim, keys only in the report.

    A ``links`` field that is present, not ``null`` and not a list states no
    entry the adapter can read, and is reported as ``<record>.links``.

    It lives at the seam for `parent_ref`'s reason: the two adapters' copies of
    this loop were identical, and a rule copied into two modules is a rule
    that can drift in one of them.
    """
    reported = record.get("links")
    if reported is None:
        return (), []
    if not isinstance(reported, list):
        return (), ["<record>.links"]
    links: list[SpanLink] = []
    unread: list[str] = []
    for index, entry in enumerate(reported):
        target = link_ref(entry.get("span_id")) if isinstance(entry, dict) else None
        if target is None:
            unread.append(f"<record>.links[{index}]")
            continue
        assert isinstance(entry, dict)  # narrowed by `target`
        trace_id = entry.get("trace_id")
        attributes = entry.get("attributes")
        links.append(
            SpanLink(
                span_id=target,
                trace_id=trace_id if isinstance(trace_id, str) else None,
                attributes=attributes if isinstance(attributes, dict) else {},
            )
        )
    return tuple(links), unread


#: The record fields every adapter reads as a plain string: the three ids and
#: the span's name. The timestamps are read by `SPEC.md` §3.1's own rule and
#: report themselves; `status`, `links` and `attributes` are read through
#: compound logic and are not held to this here.
IDENTITY_FIELDS = ("span_id", "parent_id", "trace_id", "name")


def unreadable_fields(record: Mapping[str, JsonValue]) -> list[str]:
    """`<record>.<field>` for each identity field stated unreadably.

    The `unmapped_attributes` rule for record fields (`SPEC.md` §3.7), applied
    where `_timestamps` already applies it: a field the adapter recognizes but
    cannot read is **not** normalized, and saying so is what keeps it from
    vanishing between the raw record and a `None`. A `name` reported as `42`
    became `""` and a `parent_id` reported as `42` became no parent, each as
    silently as if the record had carried neither.

    Two renderings are read rather than refused, and both are absences rather
    than exceptions: a field the record omits, and one reported as `null` --
    which is how a record says "no parent" and "no name". The third is the
    empty string, which `span_ref` and `parent_ref` read as *no id stated*
    (§3.6, §4.0) rather than failing to read: it is a string, so it never
    reaches here.

    It lives at the seam rather than in each adapter for `parent_ref`'s
    reason: two dialects reporting one unreadable id differently is a
    cross-dialect equivalence claim, and a rule copied into two modules is a
    rule that can drift in one of them.
    """
    return [
        f"<record>.{field}"
        for field in IDENTITY_FIELDS
        if field in record
        and record[field] is not None
        and not isinstance(record[field], str)
    ]


def unclaimed_span(record: JsonValue, line_number: int | None = None) -> NormalizedSpan:
    """The seam value for a record **no adapter claimed** (`SPEC.md` §6.1).

    Not a dialect's translation of the record, because no dialect offered
    one: an `unknown` node carrying the record verbatim, and an
    `unclaimed_record` warning saying nobody recognized it. Everything a
    dialect would have supplied is left as it is left whenever the library
    was not told -- absent, `None`, empty -- and that is the honest shape.
    Reading the record's own fields here would be this module deciding what a
    span envelope looks like on behalf of an adapter that declined it.

    It lives at the seam rather than above or below it because it belongs to
    neither side: no adapter produced it, and the builder must not learn that
    such a thing exists as a category. The dispatcher hands it over the seam
    like any other span (`DESIGN.md` §3).

    `source_key` is the record's canonical digest -- content, never position,
    the same key `SPEC.md` §3.6 rule 2 uses for a record whose dialect states
    no span id.
    """
    return NormalizedSpan(
        source_key=record_digest(record),
        kind=NodeKind.UNKNOWN,
        name="",
        raw=RawRecord(source=record, line_number=line_number),
        diagnostics=(
            Diagnostic(
                code=UNCLAIMED_RECORD,
                message=(
                    "no registered adapter recognized this record, so nothing "
                    "read it; it is kept as an unknown node carrying the "
                    "record verbatim, with no adapter on its provenance"
                ),
                source=record,
            ),
        ),
    )
