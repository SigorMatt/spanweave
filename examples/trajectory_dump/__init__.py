"""A trajectory dumper: one graph in, one ordered call/result transcript out.

This is the Phase 3 **confirmatory** consumer (`TASKS.md` 3.3). Unlike the
Phase 2b aggregator it is not trying to break anything: it is the shape of
consumer the library was built for, written to find out whether the model can
actually express what it needs. Every want it has is a finding, and in this
phase a want is the gate failing rather than a cheap patch (`AGENT.md`).

It exists to test `PREDICTIONS.md` P2 — *the five payload states are
over-specified; most consumers collapse them to "did I get a string or not"*.
So the one thing it must not do is wave a payload state through. It decides,
per state, what a transcript line says, and `distinctions()` reports which of
those decisions actually change anything.

Three rules it keeps, for the reasons `examples/fleet_aggregate` keeps the
first two:

* **Public API only** — exactly what ``spanweave/__init__.py`` exports.
* **Dialect-neutral** — it reads the *model* and never a dialect's payload
  shape. In particular it names an unfulfilled call's tool from
  ``Diagnostic.source["operation"]`` (`SPEC.md` §3.7) and walks no payload to
  get there; that is the whole point of the O1 remedy, and a consumer that
  reached into ``outputs.value[...]`` instead would mean the remedy did not
  land (`TASKS.md` 3.3, blocker 2).
* **Portable label** — a step is labelled by ``kind`` and ``operation``, never
  by ``Node.name``. `name` is what two instrumentors are least likely to agree
  on: 16 of the 17 scenarios rendered in two dialects declare it dialect-varying
  and the corpus has therefore never compared it (`CONTRACTS.md` F-B). A
  transcript keyed on it would read identically and *be* dialect-specific, so
  `name` is carried as a field that says so rather than used as the key.

Committed fixtures only, no network, nothing under ``spanweave/`` changed.
"""

from __future__ import annotations

import collections
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from spanweave import (
    Diagnostic,
    EdgeKind,
    Graph,
    Node,
    Payload,
    PayloadState,
    SpanweaveError,
    build,
)

# -- what a payload state means to a transcript ----------------------------

#: There is content on this line to read.
CONTENT = "content"
#: There is no content, and the telemetry says that is the truth of the run.
NONE = "none"
#: There is no content, and the telemetry does not say the run had none.
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Rendering:
    """What a transcript line says about one payload.

    Split deliberately into a field a harness *branches on* and a field it
    *prints*, because that is the only way to answer P2 without inflating the
    answer. Two states that differ only in ``reason`` are two spellings of one
    decision; two that differ in ``availability`` or ``complete`` are two
    decisions, and collapsing those changes what a reader of the transcript
    concludes about the run.
    """

    #: The branch: `content`, `none`, or `unavailable`. An eval harness that
    #: scores an agent reads this and nothing else to decide whether the step
    #: is scoreable at all.
    availability: str
    #: The explanation, printed beside it. Never the branch.
    reason: str
    #: False only where the instrumentor said the value was cut short.
    complete: bool = True


#: The decision table. One row per `PayloadState`, written out rather than
#: reached by `Payload.has_content`, because `has_content` is the collapse P2
#: predicts: it answers True for `present` and `truncated` and False for the
#: other three, which is exactly "did I get a string or not".
#:
#: `absent` vs `empty` is the distinction `SPEC.md` §3.3 says must never
#: collapse, and it is the one that changes a verdict here: a tool that
#: returned nothing failed to answer, and a tool whose output the instrumentor
#: never recorded is a hole in the *telemetry*. Scoring those the same scores
#: the tracing setup as if it were the agent.
STATE_RENDERINGS: Mapping[PayloadState, Rendering] = {
    PayloadState.PRESENT: Rendering(CONTENT, "reported"),
    PayloadState.TRUNCATED: Rendering(
        CONTENT, "reported; the instrumentor cut it short", complete=False
    ),
    PayloadState.EMPTY: Rendering(NONE, "reported, and genuinely empty"),
    PayloadState.ABSENT: Rendering(
        UNAVAILABLE, "the instrumentor emitted no payload attribute"
    ),
    PayloadState.REDACTED: Rendering(
        UNAVAILABLE, "the instrumentor signalled redaction"
    ),
}

#: A sixth rendering, and **not** a sixth state. `SPEC.md` §3.3: when a payload
#: declares JSON and does not parse, `state` stays `present`, `value` is None
#: and `raw` keeps the text. A transcript must not print that as content, so it
#: is rendered apart -- reached from an existing state plus an existing field,
#: which is why it is a rendering the model already permits and not something
#: the model cannot say.
UNREADABLE = Rendering(
    UNAVAILABLE, "reported, and did not parse; only the source text survives"
)


def render(payload: Payload) -> Rendering:
    """What this payload's line says. The whole of P2's exam, in one function."""
    if payload.state is PayloadState.PRESENT and payload.value is None:
        return UNREADABLE
    return STATE_RENDERINGS[payload.state]


# -- the transcript --------------------------------------------------------


@dataclass(frozen=True)
class Line:
    """One payload, as a transcript reads it."""

    side: str
    state: str
    availability: str
    reason: str
    complete: bool
    mime: str | None
    content: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            # Kept beside the rendering rather than replaced by it: a harness
            # that disagrees with this consumer's table can read the state and
            # decide for itself, which it could not do if the transcript had
            # already collapsed it.
            "state": self.state,
            "availability": self.availability,
            "reason": self.reason,
            "complete": self.complete,
            "mime": self.mime,
            "content": self.content,
        }


@dataclass(frozen=True)
class Step:
    """One observed operation, in the order the graph puts it in."""

    index: int
    node_id: str
    kind: str
    operation: str | None
    depth: int
    status: str
    status_note: str | None
    duration: float | None
    lines: tuple[Line, ...]
    #: Ids of the results this step's call produced (`call_result`, explicit).
    fulfilled_by: tuple[str, ...]
    #: Ids of the calls this step fulfils.
    fulfils: tuple[str, ...]
    #: `data` edges the *telemetry declared* (`SPEC.md` §4.2). Read, never
    #: inferred: this consumer never compares two values to decide that one
    #: flowed into the other, and never wanted to (`PREDICTIONS.md` P3).
    feeds: tuple[str, ...]
    #: `link` edges. A target may legitimately not be in this graph (§4.0), so
    #: it is reported as an id and marked, never resolved and dropped.
    links_to: tuple[str, ...]
    #: The subset of `links_to` this graph holds no node for.
    links_outside: tuple[str, ...]
    #: Tools this step asked for that never ran, named off the diagnostic.
    unfulfilled: tuple[str, ...]
    #: True where this step is a result no call in the trace asked for.
    unrequested: bool
    #: Every other diagnostic the library scoped to this node, by code.
    #: Codes only: a diagnostic's `message` is prose an adapter wrote, and two
    #: dialects describing the same gap word it differently.
    notes: tuple[str, ...]
    #: Dialect-local, and labelled as such. Never the key of anything.
    name: str
    #: Also dialect-local, and necessarily so: `attributes.reported_kind` is by
    #: definition the dialect's own token for a kind the library could not map
    #: (`SPEC.md` §3.2, `FIXTURES.md` §4.5). It is the escape hatch §3.2 points
    #: a consumer at, so a transcript that hid it would leave `unknown` steps
    #: unreadable -- and it belongs beside `name` rather than in the body.
    reported_kind: str | None

    @property
    def label(self) -> str:
        """The portable label: kind, plus what was operated on when stated."""
        return self.kind if self.operation is None else f"{self.kind} {self.operation}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "node_id": self.node_id,
            "kind": self.kind,
            "operation": self.operation,
            "depth": self.depth,
            "status": self.status,
            "status_note": self.status_note,
            "duration": self.duration,
            "lines": [line.as_dict() for line in self.lines],
            "fulfilled_by": list(self.fulfilled_by),
            "fulfils": list(self.fulfils),
            "feeds": list(self.feeds),
            "links_to": list(self.links_to),
            "links_outside": list(self.links_outside),
            "unfulfilled": list(self.unfulfilled),
            "unrequested": self.unrequested,
            "notes": list(self.notes),
            "dialect_local": {
                "name": self.name,
                "reported_kind": self.reported_kind,
            },
        }


@dataclass(frozen=True)
class Transcript:
    """A run, flattened."""

    source: str
    trace_id: str
    adapter: str
    steps: tuple[Step, ...]
    #: Diagnostics the library scoped to no node, by code. They qualify the
    #: whole transcript, and `ORDERING_CODES` says which of them qualify the
    #: one thing a transcript *is* -- its order.
    qualifiers: tuple[str, ...]
    limits: tuple[str, ...]

    def states_seen(self) -> dict[str, int]:
        """How many payloads of each state this transcript actually read.

        Every state, including the zeros: a state nothing exercised is the
        finding, and a dict that simply omits it hides it.
        """
        counts: collections.Counter[str] = collections.Counter()
        for step in self.steps:
            for line in step.lines:
                counts[line.state] += 1
        return {str(state): counts[str(state)] for state in sorted(PayloadState)}

    def renderings_seen(self) -> dict[str, int]:
        """The same count over *renderings*, which is one more than states."""
        counts: collections.Counter[str] = collections.Counter()
        for step in self.steps:
            for line in step.lines:
                counts[f"{line.availability}/{line.reason}"] += 1
        return {key: counts[key] for key in sorted(counts)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "trace_id": self.trace_id,
            # Dialect-local by construction, and grouped with `name` under the
            # same heading so a cross-dialect diff of two transcripts has one
            # place to look rather than two.
            "dialect_local": {"adapter": self.adapter},
            "steps": [step.as_dict() for step in self.steps],
            "qualifiers": list(self.qualifiers),
            "states_seen": self.states_seen(),
            "renderings_seen": self.renderings_seen(),
            "limits": list(self.limits),
        }


# -- building it -----------------------------------------------------------


def _asked_for(diagnostic: Diagnostic) -> str | None:
    """Which tool an unfulfilled call asked for (`SPEC.md` §3.7).

    **One line, and the same line in every dialect** — that is the O1 remedy's
    claim (`TASKS.md` 3.3, blocker 2), and this consumer is where it is either
    true or not. No payload is walked to reach the name.

    Defensive about the shape and not about the path: `Diagnostic.source` is
    `JsonValue`, so a library older than the §3.7 table would put a bare id
    string here. That degrades to an unnamed call, never to a dropped one.
    """
    source = diagnostic.source
    if not isinstance(source, dict):
        return None
    named = source.get("operation")
    return named if isinstance(named, str) else None


UNNAMED_TOOL = "(dialect named no tool)"

#: The two codes this consumer reads as structure rather than as a note: they
#: are what an unfulfilled call and an unrequested result look like on a
#: transcript line.
PAIRING_CODES = frozenset({"unpaired_call", "unpaired_result"})

#: The codes that bear on the *order*, which is the one thing a transcript is.
#: `ordering_cycle` says the ordering edges contain a cycle and the graph was
#: built anyway (`SPEC.md` §3.7, §5.2), so the sequence below is a sequence and
#: not a trajectory; `missing_timestamp` says a node was left out of the
#: temporal ordering, and `nonmonotonic_time` says a reported interval runs
#: backwards.
#:
#: **This set was read out of §3.7's prose, not off a field.** Nothing on a
#: `Diagnostic` says what it bears on, and nothing says which codes are
#: node-scoped and which are graph-scoped -- `node_id is None` is where this
#: consumer learns the difference, by observation. That is `TASKS.md` 2.4's F7,
#: met independently by a second consumer (`CONTRACTS.md`, `diagnostics[].node_id`).
ORDERING_CODES = frozenset(("ordering_cycle", "missing_timestamp", "nonmonotonic_time"))


def _reported_kind(node: Node) -> str | None:
    """The dialect's own token for a kind the library did not map (§3.2)."""
    reported = node.attributes.get("reported_kind")
    return reported if isinstance(reported, str) else None


def _lines(node: Node) -> tuple[Line, ...]:
    lines: list[Line] = []
    for side, payload in (("in", node.inputs), ("out", node.outputs)):
        rendering = render(payload)
        lines.append(
            Line(
                side=side,
                state=str(payload.state),
                availability=rendering.availability,
                reason=rendering.reason,
                complete=rendering.complete,
                mime=payload.mime,
                content=payload.value if rendering.availability == CONTENT else None,
            )
        )
    return tuple(lines)


def _duration(node: Node) -> float | None:
    """Elapsed seconds, or None.

    None rather than 0.0 where a dialect omits a timestamp: a step of unknown
    length and a step of no length are different facts, which is the same
    argument §3.3 makes about payloads one level up.
    """
    if node.started_at is None or node.ended_at is None:
        return None
    return round(node.ended_at - node.started_at, 6)


def transcribe(source: str, *, adapter: str | None = None) -> Transcript:
    """Build the graph and flatten it. Raises what `build` raises."""
    return flatten(source, build(source, adapter=adapter))


def flatten(source: str, graph: Graph) -> Transcript:
    """The transcript of an already-built graph."""
    by_node: dict[str, list[Diagnostic]] = {}
    unscoped: list[str] = []
    for diagnostic in graph.diagnostics:
        if diagnostic.node_id is None:
            unscoped.append(diagnostic.code)
        else:
            by_node.setdefault(diagnostic.node_id, []).append(diagnostic)

    limits: list[str] = []
    steps: list[Step] = []
    for index, node in enumerate(graph.nodes(), start=1):
        diagnostics = by_node.get(node.id, ())
        unfulfilled: list[str] = []
        notes: list[str] = []
        unrequested = False
        for diagnostic in diagnostics:
            if diagnostic.code not in PAIRING_CODES:
                notes.append(diagnostic.code)
            if diagnostic.code == "unpaired_call":
                named = _asked_for(diagnostic)
                if named is None:
                    limits.append(UNNAMED_CALLS)
                unfulfilled.append(named or UNNAMED_TOOL)
            elif diagnostic.code == "unpaired_result":
                unrequested = True

        links = graph.children(node.id, edge_kinds=EdgeKind.LINK)
        steps.append(
            Step(
                index=index,
                node_id=node.id,
                kind=str(node.kind),
                operation=node.operation,
                depth=len(graph.ancestors(node.id, edge_kinds=EdgeKind.PARENT)),
                status=str(node.status),
                status_note=node.status_note,
                duration=_duration(node),
                lines=_lines(node),
                fulfilled_by=graph.children(node.id, edge_kinds=EdgeKind.CALL_RESULT),
                fulfils=graph.parents(node.id, edge_kinds=EdgeKind.CALL_RESULT),
                feeds=graph.children(node.id, edge_kinds=EdgeKind.DATA),
                links_to=links,
                # `Graph.node` returns None for an id the graph does not hold,
                # and §4.0 says that is normal for a link rather than an error.
                # Named rather than filtered out: dropping the id would hide a
                # relation the telemetry stated.
                links_outside=tuple(t for t in links if graph.node(t) is None),
                # Sorted, not in diagnostic order, so two dialects that emit
                # the same set in a different order still transcribe alike.
                unfulfilled=tuple(sorted(unfulfilled)),
                unrequested=unrequested,
                # Sorted and de-duplicated for the same reason: the *set* of
                # gaps on a node is the portable fact; how many times an
                # adapter said it, and in what words, is not.
                notes=tuple(sorted(set(notes))),
                name=node.name,
                reported_kind=_reported_kind(node),
            )
        )

    if any(step.duration is None for step in steps):
        limits.append(NO_DURATION)
    if any(step.duration is not None and step.duration < 0 for step in steps):
        limits.append(BACKWARDS)
    qualifiers = tuple(sorted(set(unscoped)))
    if set(qualifiers) & ORDERING_CODES or any(
        set(step.notes) & ORDERING_CODES for step in steps
    ):
        limits.append(UNTRUSTED_ORDER)

    return Transcript(
        source=source,
        trace_id=graph.trace_id,
        adapter=_adapter_of(graph),
        steps=tuple(steps),
        qualifiers=qualifiers,
        # De-duplicated in first-appearance order: a limit is a statement about
        # the run, not a count of the rows that triggered it.
        limits=tuple(dict.fromkeys(limits)),
    )


UNNAMED_CALLS = (
    "some unfulfilled calls are shown as `(dialect named no tool)`: the "
    "diagnostic carried `operation: null`, meaning the instrumentor stated an "
    "id and no name. That is a gap in the trace, not in the transcript."
)

NO_DURATION = (
    "some steps show no duration: the dialect omitted a timestamp, so the "
    "step's length is unknown rather than zero (`SPEC.md` §3.1)."
)

BACKWARDS = (
    "some steps show a negative duration: the instrumentor reported an "
    "`ended_at` before its `started_at`, and the library reports what it was "
    "told rather than clamping it (`nonmonotonic_time`, `SPEC.md` §3.7)."
)

UNTRUSTED_ORDER = (
    "the order below is the graph's order and not necessarily the run's: at "
    "least one step carries a diagnostic that bears on ordering "
    "(`ordering_cycle`, `missing_timestamp`, `nonmonotonic_time`). A "
    "transcript is an ordering, so this qualifies the whole of it."
)


def _adapter_of(graph: Graph) -> str:
    if graph.meta is None or not graph.meta.adapters:
        return "(none recorded)"
    return ", ".join(sorted(a.id for a in graph.meta.adapters))


# -- what the consumer used ------------------------------------------------


def distinctions() -> list[dict[str, Any]]:
    """Every pair of payload states, and what separates them *here*.

    This is the P2 record, computed from the table rather than asserted about
    it. `verdict` means the two states put a reader on different branches;
    `wording` means the transcript explains them differently and a harness
    that reads `availability` cannot tell them apart.
    """
    states = sorted(PayloadState)
    rows: list[dict[str, Any]] = []
    for i, first in enumerate(states):
        for second in states[i + 1 :]:
            left, right = STATE_RENDERINGS[first], STATE_RENDERINGS[second]
            differs = []
            if left.availability != right.availability:
                differs.append("availability")
            if left.complete != right.complete:
                differs.append("complete")
            if left.reason != right.reason:
                differs.append("reason")
            rows.append(
                {
                    "states": [str(first), str(second)],
                    "separated_by": differs,
                    "kind": "verdict"
                    if differs and differs[0] != "reason"
                    else ("wording" if differs else "collapsed"),
                }
            )
    return rows


# -- running over many sources ---------------------------------------------


@dataclass(frozen=True)
class Unbuildable:
    """A fixture the library refused. Reported, never raised out of a sweep."""

    source: str
    error: str
    code: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "error": self.error,
            "code": self.code,
            "message": self.message,
        }


def transcribe_all(
    sources: Iterable[str], *, adapter: str | None = None
) -> Iterator[Transcript | Unbuildable]:
    """Transcribe each source in turn; a refusal is a result, not an exit."""
    for source in sources:
        try:
            yield transcribe(source, adapter=adapter)
        # Broad for `examples/fleet_aggregate`'s reason: one unreadable file
        # must not cost the rest of a sweep. `SpanweaveError` is what says
        # whether the library refused the trace or something else went wrong.
        except Exception as error:
            yield Unbuildable(
                source=source,
                error=type(error).__name__,
                code=error.code if isinstance(error, SpanweaveError) else None,
                message=str(error),
            )


def coverage(results: Sequence[Transcript | Unbuildable]) -> dict[str, Any]:
    """What a sweep actually read — the bound on what it can prove."""
    states: collections.Counter[str] = collections.Counter()
    renderings: collections.Counter[str] = collections.Counter()
    read: list[str] = []
    refused: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Unbuildable):
            refused.append(result.as_dict())
            continue
        read.append(result.source)
        for key, count in result.states_seen().items():
            states[key] += count
        for key, count in result.renderings_seen().items():
            renderings[key] += count
    return {
        "sources_read": read,
        "sources_refused": refused,
        "payloads": sum(states.values()),
        "states_seen": {
            str(state): states[str(state)] for state in sorted(PayloadState)
        },
        "renderings_seen": {key: renderings[key] for key in sorted(renderings)},
        "states_never_seen": [
            str(state) for state in sorted(PayloadState) if not states[str(state)]
        ],
    }


def dumps(transcript: Transcript) -> str:
    """The machine form. `sort_keys` for the library's own reason."""
    return json.dumps(transcript.as_dict(), indent=2, sort_keys=True)
