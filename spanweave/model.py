"""The data model: nodes, edges, diagnostics, and the things they carry.

Everything here is a frozen dataclass or a closed enum, and nothing here does
any I/O. The model is the vocabulary the rest of the library speaks in; it is
deliberately small, and it says only what the telemetry observed and how that
was established (``SPEC.md`` §3-§4).

Two properties are enforced rather than documented:

* **Closed enums.** ``NodeKind`` and ``EdgeKind`` are closed sets. Extending
  either is a spec change and a halt point (``AGENT.md``), so a test asserts
  their exact membership.
* **The warrant table.** ``parent``, ``call_result``, ``data`` and ``link``
  are explicit-only; ``temporal`` is derived-only. ``Edge`` refuses to be
  constructed otherwise, because a derived relation quietly acquiring an
  explicit warrant is the one failure a consumer downstream could never
  detect (``CLAUDE.md`` 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# A JSON document, as parsed by the stdlib. Deliberately loose: the library
# preserves whatever the trace contained, including shapes it has no opinion
# about.
JsonValue = Any

# Node ids are strings -- either the dialect's own span id or a derived one
# (SPEC.md §3.6). The alias exists to make signatures read honestly, not to
# add type safety the runtime does not have.
NodeId = str


class NodeKind(StrEnum):
    """What kind of operation a node describes. **Closed** (`SPEC.md` §3.2)."""

    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    RETRIEVER = "retriever"
    EMBEDDING = "embedding"
    CHAIN = "chain"
    #: A first-class outcome, not a failure: the dialect reported a kind we do
    #: not map. It always arrives with a diagnostic naming the original string.
    #: An honest `unknown` is visible; a wrong kind is not.
    UNKNOWN = "unknown"


class EdgeKind(StrEnum):
    """What relation an edge asserts. **Closed** (`SPEC.md` §4)."""

    PARENT = "parent"
    CALL_RESULT = "call_result"
    DATA = "data"
    LINK = "link"
    TEMPORAL = "temporal"


class Warrant(StrEnum):
    """How an edge's relation was established (`SPEC.md` §4.1)."""

    #: The telemetry asserted it. The adapter transcribed, it did not reason.
    EXPLICIT = "explicit"
    #: spanweave computed it from a stated rule over the data.
    DERIVED = "derived"


class Status(StrEnum):
    """The operation's outcome, as reported (`SPEC.md` §3.1)."""

    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


class PayloadState(StrEnum):
    """Why a payload does or does not have content (`SPEC.md` §3.3).

    ``ABSENT`` and ``EMPTY`` must never be collapsed: "we weren't told" and
    "there was nothing" are different statements about the world, and a
    consumer that cannot tell them apart reports the same thing for both.
    """

    PRESENT = "present"
    EMPTY = "empty"
    ABSENT = "absent"
    REDACTED = "redacted"
    TRUNCATED = "truncated"


class DiagnosticLevel(StrEnum):
    """How loudly to report a mapping gap. Never "error": errors raise.

    This grades the report, not the trace (`SPEC.md` §3.7).
    """

    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Payload:
    """An input or an output, and the reason it looks the way it does."""

    state: PayloadState
    mime: str | None = None
    value: JsonValue = None
    #: The unparsed source string, always kept when there was one. Survives a
    #: parse failure, which is exactly when it matters most.
    raw: str | None = None

    @classmethod
    def absent(cls) -> Payload:
        """The instrumentor emitted no payload attribute at all."""
        return cls(state=PayloadState.ABSENT)

    @property
    def has_content(self) -> bool:
        """Is there anything here to look at?

        True for ``present`` and for ``truncated`` -- a truncated payload
        carries content, just not all of it. False for ``absent``, ``empty``
        and ``redacted``, which is three different reasons for the same answer,
        and ``state`` is where a consumer reads which one.
        """
        return self.state in (PayloadState.PRESENT, PayloadState.TRUNCATED)


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts, and nothing else.

    Counts only. No money, no currency, no rate tables: those are consumer
    policy, and they change (`SPEC.md` §9). The gate that guards this file
    cannot tell a denial from an assertion, which is why even the denial is
    phrased without the banned word.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Never computed from the other two. If the dialect did not report a
    #: total, there is no total: deriving one would state a fact the telemetry
    #: did not.
    total_tokens: int | None = None
    #: Cache reads, reasoning tokens, and any other counted thing a dialect
    #: reports. Copied on construction; treat as read-only.
    extra: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", dict(self.extra))


@dataclass(frozen=True, slots=True)
class RawRecord:
    """The verbatim source of a node. Losslessness lives here."""

    #: The source record, unmodified. Round-tripping this through the
    #: serializer reproduces the input record (`SPEC.md` §3.5).
    source: JsonValue
    source_id: str | None = None
    #: 1-based, for file-based dialects. Held in memory for diagnostics; it is
    #: not serialized, because it depends on input order and the graph must
    #: not (`SPEC.md` §3.5, §5.2).
    line_number: int | None = None


@dataclass(frozen=True, slots=True)
class Provenance:
    """Which adapter, at which version, produced a node."""

    adapter_id: str
    adapter_version: str
    #: Anything the adapter wants a human to know about this record.
    dialect_note: str | None = None


@dataclass(frozen=True, slots=True)
class Node:
    """One observed operation (`SPEC.md` §3.1)."""

    id: NodeId
    kind: NodeKind
    #: As reported. Never prettified, title-cased, or rewritten.
    name: str
    raw: RawRecord
    provenance: Provenance
    operation: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    status: Status = Status.UNSET
    #: The error message as reported, verbatim.
    status_note: str | None = None
    inputs: Payload = field(default_factory=Payload.absent)
    outputs: Payload = field(default_factory=Payload.absent)
    usage: Usage | None = None
    #: A normalized, typed subset -- only what the model itself consumes.
    #: Everything else stays in ``raw`` (`OPEN_QUESTIONS.md` §5).
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", dict(self.attributes))


#: The binding warrant table (`SPEC.md` §4.1). A rule that ever infers a
#: relation of an explicit-only kind does not become that kind -- it becomes a
#: new kind, through a spec change.
ALLOWED_WARRANTS: Mapping[EdgeKind, frozenset[Warrant]] = {
    EdgeKind.PARENT: frozenset({Warrant.EXPLICIT}),
    EdgeKind.CALL_RESULT: frozenset({Warrant.EXPLICIT}),
    EdgeKind.DATA: frozenset({Warrant.EXPLICIT}),
    EdgeKind.LINK: frozenset({Warrant.EXPLICIT}),
    EdgeKind.TEMPORAL: frozenset({Warrant.DERIVED}),
}


@dataclass(frozen=True, slots=True)
class Edge:
    """A typed, warranted relation between two nodes (`SPEC.md` §3.8)."""

    src: NodeId
    dst: NodeId
    kind: EdgeKind
    warrant: Warrant
    #: The exact rule or field that produced this edge, named so a consumer
    #: can audit it instead of trusting it: "span.parent_span_id",
    #: "tool_call_id", "sibling start_time ordering".
    basis: str
    #: Who asserted it, when the adapter did.
    adapter: str | None = None

    def __post_init__(self) -> None:
        allowed = ALLOWED_WARRANTS[self.kind]
        if self.warrant not in allowed:
            permitted = ", ".join(sorted(w.value for w in allowed))
            raise ValueError(
                f"{self.kind.value} edges are {permitted}-only; refusing to "
                f"build one with warrant {self.warrant.value!r} "
                f"(SPEC.md §4.1). A computed relation never becomes an "
                f"explicit one."
            )

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        """The total order edges are serialized in (`SPEC.md` §5.2)."""
        return (self.kind.value, self.src, self.dst, self.basis)

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Edges are unique on ``(src, dst, kind, basis)``; duplicates collapse."""
        return (self.src, self.dst, self.kind.value, self.basis)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Something the library could not confidently map (`SPEC.md` §3.7).

    Diagnostics are part of the output, not log noise. They are the
    alternative to guessing.
    """

    code: str
    message: str
    level: DiagnosticLevel = DiagnosticLevel.WARNING
    node_id: NodeId | None = None
    #: The offending fragment, verbatim.
    source: JsonValue = None
    adapter: str | None = None

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """The total order diagnostics are serialized in (`SPEC.md` §5.2)."""
        return (self.code, self.node_id or "", self.message)


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    """An adapter that contributed to a graph."""

    id: str
    version: str
    #: The detection confidence, when the adapter was detected rather than
    #: named with ``--adapter`` (`SPEC.md` §6.1).
    confidence: float | None = None

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.id, self.version)


@dataclass(frozen=True, slots=True)
class Meta:
    """What produced this graph (`SPEC.md` §3.9).

    Never a build timestamp, a hostname, a username, or a file path: those
    would break byte-identical determinism and leak the operator's
    environment.
    """

    schema_version: str
    spanweave_version: str
    adapters: tuple[AdapterInfo, ...] = ()
    #: sha256 of the input bytes, when built from a file. A fingerprint of the
    #: input, not of the graph -- shuffling the input changes it while the
    #: graph stays identical.
    source_digest: str | None = None
    node_count: int = 0
    edge_count: int = 0
    diagnostic_count: int = 0
