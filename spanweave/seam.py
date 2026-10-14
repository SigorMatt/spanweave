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

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from spanweave import jsoncodec
from spanweave.diagnostics import (
    ATTRIBUTES_DROPPED,
    EXCEPTION_EVENT,
    SPAN_EVENT,
    UNCLAIMED_RECORD,
)
from spanweave.errors import EnvelopeError
from spanweave.model import (
    Diagnostic,
    DiagnosticLevel,
    JsonValue,
    NodeKind,
    Payload,
    RawRecord,
    Status,
    Usage,
)
from spanweave.read import Unpacked, folded_attributes, record_digest


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
    #: Unix seconds. An integer literal stays an `int` and a fractional one a
    #: `float` -- float64 cannot hold epoch nanoseconds (`SPEC.md` §3.1). A
    #: field that declares no unit is never rescaled; one that declares
    #: nanoseconds is carried as the `float` seconds it converts to.
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


#: A JSON number literal, exactly as RFC 8259 writes one. The rule for a
#: quoted timestamp is *the string, unquoted, would be a valid JSON number*
#: (`SPEC.md` §3.1) rather than a list of tolerated spellings: OTLP JSON
#: encodes 64-bit integers as decimal strings, so a quoted timestamp is a
#: real exporter's output -- but every tolerated spelling beyond that is a
#: small normalization, and a library that trims whitespace here has started
#: deciding what the telemetry meant.
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")

#: The integer subset of the above: no fraction, no exponent. §3.1 reads an
#: integer literal as an `int` and every other literal as a `float`, and the
#: rule is about the *literal* rather than the value, so a quoted timestamp
#: is typed by the same test as an unquoted one.
_JSON_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")


def _finite(value: int | float) -> int | float | None:
    """`value`, unless it is `inf` or `nan` -- neither of which is a time.

    Python's JSON parser produces those for the non-standard `NaN` /
    `Infinity` tokens and for a literal no float64 can hold (`1e400`), and a
    library that carried one would write it back out as a bare `Infinity`
    that no strict JSON parser will read (`SPEC.md` §3.1, §7).

    The `isinstance` is the guard rather than a style choice: an `int` is
    always finite, and `math.isfinite` on one too large for a float raises
    `OverflowError` instead of answering.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def stated_time(value: JsonValue) -> int | float | None:
    """A reported time, read by `SPEC.md` §3.1's rendering rule. Never guessed at.

    An integer literal is kept as an `int` (`SPEC.md` §3.1). float64's
    spacing at epoch-nanosecond magnitude is 256 ns, so `float()` here would
    spend digits the exporter wrote and merge spans a record kept apart.
    Nothing is scaled here: a unit is applied only where a field declares one,
    by `record_time`, which every reader of a record's times goes through.

    Returns `None` both for a field the record omits and for one in a
    rendering §3.1 does not read; the caller is what tells the two apart,
    because only the second is something to report.

    It lives at the seam for `parent_ref`'s reason: both adapters held a
    byte-identical copy of it, and the envelope (`envelope`, below) reads the
    same two fields by the same rule -- a third copy is how a rule drifts in
    one of them.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # `json.loads` already draws §3.1's line: an `int` for an integer
        # literal, a `float` for one with a fraction or an exponent.
        return _finite(value)
    if isinstance(value, str) and _JSON_NUMBER.fullmatch(value):
        # Read as the identical value the same literal would have produced
        # unquoted: `"1700000000"` and `1700000000` are one timestamp, and
        # `"1e9"` is the same float `1e9` is.
        try:
            parsed: int | float = (
                jsoncodec.parse_integer(value)
                if _JSON_INTEGER.fullmatch(value)
                else float(value)
            )
        except ValueError:
            # Longer than the library's digit limit (`SPEC.md` §5.3): a
            # constant, and the digits are counted before anything converts
            # them, so this answer does not depend on how the interpreter's
            # own limit is set. An unquoted literal that long never gets
            # here -- the reader refuses the line -- but a *quoted* one is an
            # ordinary JSON string until this call (`SPEC.md` §3.1).
            return None
        return _finite(parsed)
    return None


#: Nanoseconds in a second: the divisor for a time whose field declares
#: nanoseconds (`record_time`).
_NANOSECONDS_PER_SECOND = 1_000_000_000


def declares_nanoseconds(record: Mapping[str, JsonValue]) -> bool:
    """Whether the record's `start_time` / `end_time` declare nanoseconds.

    They do exactly when the reader unpacked the record from an OTLP export
    (`spanweave.read.Unpacked`, `SPEC.md` §7): those two keys are then the
    reader's renaming of `startTimeUnixNano` / `endTimeUnixNano`, whose names
    state the unit. Any other record's `start_time` declares nothing -- a
    flat file names no unit, and none is inferred from a magnitude.
    """
    return isinstance(record, Unpacked)


def record_time(record: Mapping[str, JsonValue], field: str) -> int | float | None:
    """`started_at` / `ended_at` from a record's `start_time` / `end_time`.

    Unix seconds (`SPEC.md` §3.1). The reported value is read by
    `stated_time`; where its field declares nanoseconds (`declares_nanoseconds`)
    it is then converted to seconds -- the nearest float to the reported
    count divided by 1e9, which Python's true division of two integers rounds
    correctly, so the result is the same on every machine. The reported
    string stays verbatim in `raw.source`, so no digit is lost from the graph;
    what the float cannot keep is an order between two times closer than its
    spacing (~238 ns today), and §3.1 says so.

    Returns `None` for a field the record omits and for one §3.1 does not
    read -- including a declared count too large for a float once divided --
    so the caller's "reported but not read" check is the same for both.
    """
    read = stated_time(record.get(field))
    if read is None or not declares_nanoseconds(record):
        return read
    return _in_seconds(read)


def _in_seconds(nanoseconds: int | float) -> int | float | None:
    """A declared nanosecond count as unix seconds, by §3.1's one division.

    `None` for a count no float holds once divided -- a time §3.1 does not
    read. Shared by `record_time` and a span event's `timeUnixNano`
    (`span_events`), so the two readings of a declared unit cannot drift.
    """
    try:
        return _finite(nanoseconds / _NANOSECONDS_PER_SECOND)
    except OverflowError:
        return None


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


#: The status names the reader writes for an OTLP `Status.code` (`SPEC.md` §7).
#: Any other value is carried verbatim by the reader and read as `UNSET` here,
#: exactly as §7 states it.
_ENVELOPE_STATUSES: Mapping[JsonValue, Status] = {
    "UNSET": Status.UNSET,
    "OK": Status.OK,
    "ERROR": Status.ERROR,
}


@dataclass(frozen=True, slots=True)
class Envelope:
    """What the OTLP transport stated about one span (`SPEC.md` §7).

    The nine keys the reader renamed out of an export, read as the transport
    states them: two ids it requires, the parent it names, the span's name,
    its two times and its status. Nothing here is a dialect's: no attribute is
    read, and no field is interpreted beyond §3.6's empty-id rule, §3.1's
    timestamp rule and §7's status rule -- the same three readings every
    adapter applies to the same fields.
    """

    trace_id: str
    span_id: str
    #: `None` where the span states no parent: the key omitted, `null`, or the
    #: empty string a proto3 marshaler writes for an unset `bytes` (§3.6).
    parent_id: str | None
    #: The empty string where the span omits `name`, which is proto3's default
    #: for the field rather than an absence.
    name: str
    #: §3.1's reading of the reported value: unix seconds, converted from
    #: the nanoseconds the field declares (`record_time`). `None` where the
    #: span omits the field.
    started_at: int | float | None
    ended_at: int | float | None
    status: Status
    status_note: str | None
    #: The record's `ResourceSpans` level without its `scopeSpans`, and its
    #: `ScopeSpans` level without its `spans` -- the objects the reader
    #: attached as `resource_spans` and `scope_spans`, as the record carries
    #: them (the same objects, not copies, as `RawRecord.source` is the
    #: record), and `{}` where the export states nothing at that level, as
    #: proto3 JSON omits a default. Per span, not per graph: one export can
    #: carry two instrumentation scopes (batch T3, `OPEN_QUESTIONS.md` §21).
    #: Excluded from the hash, as a JSON object cannot be hashed.
    resource: dict[str, JsonValue] = field(hash=False)
    scope: dict[str, JsonValue] = field(hash=False)


def envelope(record: JsonValue) -> Envelope:
    """The OTLP envelope of a record the reader unpacked (`SPEC.md` §7).

    **Only a record the reader unpacked from an export has one.** The reader
    marks such a record (`spanweave.read.Unpacked`), and this function reads
    nothing else: a key named `span_id` in a flat file is a key, not the
    transport's statement, and treating it as one would put the transport's
    authority behind a statement nobody made.

    Raises `EnvelopeError` (`not_an_envelope`) on any other record; on an
    unpacked record that states no `trace_id` or no `span_id` -- the two
    fields OTLP requires of every span, which an envelope level with no spans
    does not have -- and on a field present in a type the envelope cannot hold
    (an id or `name` that is not a string, a time §3.1 does not read, a status
    message that is not a string). Never a partial answer: an `Envelope` with
    a guessed field would be indistinguishable from one the export stated.

    Pure and total over its input: it reads the record and returns a value,
    and calling it twice gives the same value twice. It is the routing key a
    receiver needs -- every record of one trace has one `trace_id` here,
    whether or not any adapter can read it.
    """
    if not isinstance(record, Unpacked):
        raise EnvelopeError(
            "this record was not unpacked from an OTLP export, so it carries "
            "no envelope; a key named span_id in a flat record is not one"
        )
    ids: dict[str, str] = {}
    for key in ("trace_id", "span_id"):
        reported = record.get(key)
        if reported is not None and not isinstance(reported, str):
            raise EnvelopeError(f"the envelope's {key} is not a string")
        stated = span_ref(reported)
        if stated is None:
            raise EnvelopeError(f"the envelope states no {key}")
        ids[key] = stated
    reported_parent = record.get("parent_id")
    if reported_parent is not None and not isinstance(reported_parent, str):
        raise EnvelopeError("the envelope's parent_id is not a string")
    name = record.get("name", "")
    if not isinstance(name, str):
        raise EnvelopeError("the envelope's name is not a string")
    times: list[int | float | None] = []
    for key in ("start_time", "end_time"):
        reported_time = record.get(key)
        read = record_time(record, key)
        if read is None and reported_time is not None:
            raise EnvelopeError(f"the envelope's {key} is not a time §3.1 reads")
        times.append(read)
    note = record.get("status_message")
    if note is not None and not isinstance(note, str):
        raise EnvelopeError("the envelope's status_message is not a string")
    reported_status = record.get("status")
    status = (
        _ENVELOPE_STATUSES.get(reported_status, Status.UNSET)
        if isinstance(reported_status, str)
        else Status.UNSET
    )
    levels: list[dict[str, JsonValue]] = []
    for key in ("resource_spans", "scope_spans"):
        level = record.get(key, {})
        if not isinstance(level, dict):
            raise EnvelopeError(f"the envelope's {key} is not an object")
        levels.append(level)
    return Envelope(
        trace_id=ids["trace_id"],
        span_id=ids["span_id"],
        parent_id=parent_ref(reported_parent),
        name=name,
        started_at=times[0],
        ended_at=times[1],
        status=status,
        status_note=note,
        resource=levels[0],
        scope=levels[1],
    )


#: The keys of an unpacked record that are its OTLP envelope rather than the
#: span's attributes (`SPEC.md` §7): the span's `flags` and `kind`, carried
#: under their own OTLP names, and the two levels the reader attached. They
#: stay verbatim in `raw.source`, and `unmapped_attributes` does not name them
#: -- every span of every export carries them, so naming them reported the
#: transport, once per span, rather than anything an adapter left unread.
ENVELOPE_LEVEL_KEYS = ("flags", "kind", "resource_spans", "scope_spans")

#: OTLP's count of the span's attributes dropped before export (`SPEC.md` §7).
DROPPED_ATTRIBUTES_KEY = "droppedAttributesCount"

#: A `uint32` in proto3 JSON's string rendering: decimal digits, no sign.
_UINT32_STRING = re.compile(r"[0-9]{1,10}")
_UINT32_MAX = 2**32 - 1


def _dropped_count(reported: JsonValue) -> int | None:
    """`droppedAttributesCount` as the `uint32` it is, else `None`.

    proto3 JSON writes a `uint32` as a number and accepts it as a decimal
    string; `null` is its default, zero. Anything else -- a sign, a fraction,
    a boolean, a value no `uint32` holds -- is not a count, and is not read.
    """
    if reported is None:
        return 0
    if isinstance(reported, bool):
        return None
    if isinstance(reported, str):
        if _UINT32_STRING.fullmatch(reported) is None:
            return None
        reported = int(reported)
    if isinstance(reported, int) and 0 <= reported <= _UINT32_MAX:
        return reported
    return None


def envelope_keys(record: JsonValue) -> frozenset[str]:
    """The top-level keys of `record` that its OTLP envelope stated and were read.

    Only a record the reader unpacked has an envelope (`envelope`): in a flat
    file a key named `kind` is a key, and stays reported. On an unpacked
    record these are the four `ENVELOPE_LEVEL_KEYS` it carries, and
    `droppedAttributesCount` where it reads as a count -- which
    `attributes_dropped` then reports, so the count is acted on rather than
    left unread. A count that does not read stays an unmapped key (`SPEC.md`
    §3.7: a key read and not usable is reported).
    """
    if not isinstance(record, Unpacked):
        return frozenset()
    keys = {key for key in ENVELOPE_LEVEL_KEYS if key in record}
    if (
        DROPPED_ATTRIBUTES_KEY in record
        and _dropped_count(record[DROPPED_ATTRIBUTES_KEY]) is not None
    ):
        keys.add(DROPPED_ATTRIBUTES_KEY)
    # The span's events, where they are a list (or proto3's `null` default):
    # each is then read by `span_events`, which names any entry it cannot
    # read as `<record>.events[<i>]`. Anything else is no list of events and
    # stays the unmapped `<record>.events` (batch T4).
    if EVENTS_KEY in record and (
        record[EVENTS_KEY] is None or isinstance(record[EVENTS_KEY], list)
    ):
        keys.add(EVENTS_KEY)
    return frozenset(keys)


def attributes_dropped(
    record: JsonValue, adapter: str | None
) -> tuple[Diagnostic, ...]:
    """`attributes_dropped` where the export says attributes are missing (§3.7).

    The export states how many of the span's attributes it dropped and names
    none, so the report is the count, `source: {"count": n}`, and nothing is
    reconstructed: no attribute absent from the record -- a model name, say --
    is looked for anywhere else. Made from the envelope rather than from any
    dialect, so a claimed span and an unclaimed one report it alike; `adapter`
    is whoever read the record, `None` where nobody did (§6.1).
    """
    if not isinstance(record, Unpacked) or DROPPED_ATTRIBUTES_KEY not in record:
        return ()
    count = _dropped_count(record[DROPPED_ATTRIBUTES_KEY])
    if count is None or count == 0:
        return ()
    return (
        Diagnostic(
            code=ATTRIBUTES_DROPPED,
            message=(
                f"the export states that {count} of this span's attributes "
                "were dropped before export, and names none of them; what "
                "the span carries is all there is to read"
            ),
            source={"count": count},
            adapter=adapter,
        ),
    )


#: OTLP's list of a span's events (`SPEC.md` §7), carried by the reader under
#: its own name and verbatim, entries and their attribute lists unfolded.
EVENTS_KEY = "events"

#: The event name the OpenTelemetry API's `record_exception` writes, and the
#: attributes it writes on it (`SPEC.md` §7). The SDK's convention rather than
#: an instrumentor's, so it is read here, below the seam, for every dialect
#: alike -- no adapter branches on it. Each pair is (attribute, `source` key).
EXCEPTION_EVENT_NAME = "exception"
EXCEPTION_ATTRIBUTES = (
    ("exception.type", "type"),
    ("exception.message", "message"),
    ("exception.escaped", "escaped"),
)


def _event_time(entry: Mapping[str, JsonValue]) -> tuple[bool, int | float | None]:
    """An event's `timeUnixNano` in unix seconds: (readable, value).

    The field declares nanoseconds in its name, as a span's times do, so it
    is read by `stated_time` and converted by `_in_seconds` -- T2's rule, the
    one `record_time` applies (`SPEC.md` §3.1). Omitted or `null` is no time
    stated, `None`; a value §3.1 does not read is not readable.
    """
    reported = entry.get("timeUnixNano")
    if reported is None:
        return True, None
    read = stated_time(reported)
    seconds = None if read is None else _in_seconds(read)
    return seconds is not None, seconds


def _event_diagnostic(
    entry: JsonValue, index: int, adapter: str | None
) -> Diagnostic | None:
    """One event entry as its diagnostic, or `None` where it cannot be read."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name", "")
    if name is None:
        name = ""
    if not isinstance(name, str):
        return None
    readable, time = _event_time(entry)
    if not readable:
        return None
    if name != EXCEPTION_EVENT_NAME:
        return Diagnostic(
            code=SPAN_EVENT,
            message=(
                f"the span states event {index}, {name!r}; the graph has no "
                "field for a span event, so it is reported here and kept "
                "verbatim in raw"
            ),
            level=DiagnosticLevel.INFO,
            source={"name": name, "time": time},
            adapter=adapter,
        )
    reported = entry.get("attributes")
    attributes, unfolded = folded_attributes([] if reported is None else reported)
    if unfolded or not isinstance(attributes, dict):
        return None
    source: dict[str, JsonValue] = {
        key: attributes.get(attribute) for attribute, key in EXCEPTION_ATTRIBUTES
    }
    source["time"] = time
    return Diagnostic(
        code=EXCEPTION_EVENT,
        message=(
            f"the span states event {index}, an exception recorded by the "
            f"OpenTelemetry API ({source['type']!r}); the graph has no field "
            "for it, so it is reported here, its stacktrace kept verbatim in "
            "raw with the whole event. Whether the span failed is its status"
        ),
        level=DiagnosticLevel.INFO,
        source=source,
        adapter=adapter,
    )


def span_events(
    record: JsonValue, adapter: str | None
) -> tuple[tuple[Diagnostic, ...], list[str]]:
    """A span's OTLP events as `info` diagnostics, and the entries not read (§3.7).

    Only a record the reader unpacked has OTLP events: in a flat file a key
    named `events` is a key, and stays reported. Each event entry is one
    diagnostic, in the order the span lists them: `exception_event` for the
    OpenTelemetry API's `exception` event, `source: {type, message, escaped,
    time}` -- the three `exception.*` attributes as the event states them,
    `null` where it states none, and never `exception.stacktrace`, which stays
    in `raw.source` with the whole event -- and `span_event`, `source: {name,
    time}`, for any other. `time` is in unix seconds and kept as reported,
    after the span's end or not. Level `info`: an event is a fact the
    transport stated and the model has no field for, not a gap in the
    mapping, and the level grades the report, never the trace -- a failure is
    the node's `status`, where the telemetry put it.

    An entry that is not an object, or names itself or states its time in a
    rendering the reading cannot hold -- or an `exception` event whose
    attributes do not fold (`folded_attributes`) -- is not read and is named
    as `<record>.events[<i>]`, the second value, for the adapter's
    `unmapped_attributes`. Made from the envelope rather than a dialect, so a
    span no adapter claimed reports its events too, `adapter` `None`.
    """
    if not isinstance(record, Unpacked):
        return (), []
    reported = record.get(EVENTS_KEY)
    if not isinstance(reported, list):
        return (), []
    diagnostics: list[Diagnostic] = []
    unread: list[str] = []
    for index, entry in enumerate(reported):
        diagnostic = _event_diagnostic(entry, index, adapter)
        if diagnostic is None:
            unread.append(f"<record>.{EVENTS_KEY}[{index}]")
        else:
            diagnostics.append(diagnostic)
    return tuple(diagnostics), unread


def unclaimed_span(record: JsonValue, line_number: int | None = None) -> NormalizedSpan:
    """The seam value for a record **no adapter claimed** (`SPEC.md` §6.1).

    Not a dialect's translation of the record, because no dialect offered
    one: an `unknown` node carrying the record verbatim, and an
    `unclaimed_record` warning saying nobody recognized it.

    **Where the reader unpacked the record from an OTLP export, its envelope
    keys and places it** -- id, parent, trace, name, times and status, the
    nine keys the reader renamed (`envelope`, §7). Reading them here is not
    deciding what a span looks like on behalf of an adapter that declined it:
    it is reading what the transport stated before any adapter was asked. What
    no dialect read is the span's `attributes`, and that is what
    `unclaimed_record` then says. So a root span no adapter claims is the
    parent its children name, by the `explicit` edge the telemetry stated,
    rather than the absent parent of four orphans (`OPEN_QUESTIONS.md` §20).

    Everywhere else -- a flat record, or an unpacked one whose envelope cannot
    be read (`EnvelopeError`) -- everything a dialect would have supplied is
    left as it is left whenever the library was not told: absent, `None`,
    empty. `source_key` is then the record's canonical digest -- content,
    never position, the key `SPEC.md` §3.6 rule 2 uses for a record whose
    dialect states no span id.

    It lives at the seam rather than above or below it because it belongs to
    neither side: no adapter produced it, and the builder must not learn that
    such a thing exists as a category. The dispatcher hands it over the seam
    like any other span (`DESIGN.md` §3).
    """
    try:
        stated = envelope(record)
    except EnvelopeError:
        return NormalizedSpan(
            source_key=record_digest(record),
            kind=NodeKind.UNKNOWN,
            name="",
            raw=RawRecord(source=record, line_number=line_number),
            diagnostics=(
                Diagnostic(
                    code=UNCLAIMED_RECORD,
                    message=(
                        "no registered adapter recognized this record, so "
                        "nothing read it; it is kept as an unknown node "
                        "carrying the record verbatim, with no adapter on its "
                        "provenance"
                    ),
                    source=record,
                ),
                *attributes_dropped(record, None),
                *span_events(record, None)[0],
            ),
        )
    return NormalizedSpan(
        source_key=stated.span_id,
        span_id=stated.span_id,
        parent_id=stated.parent_id,
        trace_id=stated.trace_id,
        kind=NodeKind.UNKNOWN,
        name=stated.name,
        started_at=stated.started_at,
        ended_at=stated.ended_at,
        status=stated.status,
        status_note=stated.status_note,
        raw=RawRecord(source=record, source_id=stated.span_id, line_number=line_number),
        diagnostics=(
            Diagnostic(
                code=UNCLAIMED_RECORD,
                message=(
                    "no registered adapter recognized this record, so no "
                    "dialect read its attributes; it is kept as an unknown "
                    "node carrying the record verbatim, keyed and placed by "
                    "the OTLP envelope it was unpacked from (span id, parent, "
                    "trace, name, times, status), with no adapter on its "
                    "provenance"
                ),
                source=record,
            ),
            *attributes_dropped(record, None),
            *span_events(record, None)[0],
        ),
    )
