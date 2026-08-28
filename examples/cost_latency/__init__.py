"""A cost & latency attributor: one graph in, tokens and seconds rolled up the
`parent` tree, priced by a table that lives here and nowhere else.

This is the second Phase 3 **confirmatory** consumer (`TASKS.md` 3.4), and it
is `PREDICTIONS.md` P1's only test. P1 predicts that mandatory losslessness is
*pure cost* to a consumer that needs `usage` and timestamps and nothing else,
and that such a consumer will want ``retain_payloads=False`` or
``retain_raw=False``.

So this module is written to *apply that pressure*, not to demonstrate an
attributor. Two things follow from that, and they are the whole design:

* **It reads a deliberately narrow slice of the model**, listed in ``READS``
  and ``NEVER_READ`` below and pinned by a test. If the slice is narrow enough,
  a graph with every verbatim byte removed attributes **identically** to the
  graph it was built from — which is P1's question asked as a measurement
  rather than as an opinion (``residency`` section, and
  ``measure_residency``).
* **Its price table is its own.** The rates live in this file. `spanweave` has
  no opinion about money and must never acquire one (`SPEC.md` §9,
  `CLAUDE.md` 1); the word is banned under the package by a gate, and
  `examples/` is where it is allowed to be said.

Three rules it keeps, the first two for the reasons `examples/fleet_aggregate`
keeps them:

* **Public API only** — exactly what ``spanweave/__init__.py`` exports, plus
  stdlib ``dataclasses.replace`` applied to those public frozen types.
* **Dialect-neutral** — it reads the *model* and never a dialect's payload
  shape. Where a dialect's vocabulary reaches it anyway it says so in
  ``limits`` rather than absorbing it (see ``EXTRA_UNPRICED``, which is the
  sharpest finding this consumer has).
* **A lower bound is stated as one.** Every number this consumer cannot
  complete — an unrated model, an unreported `usage`, a missing timestamp, a
  token count under a key nothing states — is reported *beside* the total it
  was left out of, never folded into it.

Committed fixtures only, no network, nothing under ``spanweave/`` changed.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from spanweave import (
    EdgeKind,
    Graph,
    Node,
    NodeKind,
    Payload,
    RawRecord,
    SpanweaveError,
    build,
)

# -- what this consumer reads, and what it does not ------------------------

#: Every `Node` field the attribution touches. Written down because P1's claim
#: is about the fields it *doesn't* touch, and a claim about absence is worth
#: nothing unless the presence list is checked. `tests/` asserts this against
#: the source.
#:
#: `operation` is on the list and P1's sketch does not mention it: a price
#: table is keyed by the model, and the model's name is `operation`
#: (`SPEC.md` §3.1, §3.2). "usage and timestamps and nothing else" is one field
#: short of what pricing actually needs, and that is a correction to the
#: prediction's premise rather than a finding about the model — `operation` is
#: a short string and costs nothing to retain.
READS: tuple[str, ...] = ("id", "kind", "operation", "started_at", "ended_at", "usage")

#: Every `Node` field it never reads. The first three are where losslessness
#: lives (`CLAUDE.md` 2), and they are the whole of P1's question.
NEVER_READ: tuple[str, ...] = (
    "inputs",
    "outputs",
    "raw",
    "name",
    "status",
    "status_note",
    "attributes",
    "provenance",
)

# -- the price table, which belongs to this consumer -----------------------


@dataclass(frozen=True)
class Rate:
    """What one model is charged at, per million tokens, in ``UNITS``."""

    input_per_mtok: float
    output_per_mtok: float


#: Deliberately **not** a currency. These numbers are illustrative and are not
#: a claim about what any vendor charges: a rate table in a repository rots the
#: day it is written, and the thing under test here is whether the *model* can
#: express what pricing needs — not whether the arithmetic matches a price
#: list. Naming the unit rather than a currency keeps that honest.
UNITS = "demo-units"

#: Keyed on `Node.operation`, which is where a dialect puts the model name.
#: A model with no row here is **not** priced at a guess: its tokens are
#: counted into `unrated_input` / `unrated_output` and named in `limits`, for
#: the reason `fleet_aggregate` buckets under `(dialect named no tool)` — a
#: rollup that silently drops what it cannot label reports a confident wrong
#: number instead of an honest incomplete one.
RATES: Mapping[str, Rate] = {
    "demo-model": Rate(input_per_mtok=0.50, output_per_mtok=1.50),
    "openai/gpt-oss-120b": Rate(input_per_mtok=0.10, output_per_mtok=0.50),
}

#: Money is rounded here and nowhere else, so two runs of the same input agree
#: to the byte. Seconds use the same figure, matching what a duration can
#: actually carry (`SPEC.md` §3.1 timestamps are unix seconds as floats).
PLACES = 6


def charge(
    operation: str | None, input_tokens: int, output_tokens: int
) -> float | None:
    """What this table says those tokens are worth, or ``None`` for no row."""
    rate = RATES.get(operation) if operation is not None else None
    if rate is None:
        return None
    return round(
        input_tokens * rate.input_per_mtok / 1_000_000
        + output_tokens * rate.output_per_mtok / 1_000_000,
        PLACES,
    )


# -- one node's own numbers ------------------------------------------------

#: `usage` was reported and this table has a rate for the model.
PRICED = "priced"
#: `usage` was reported and this table has no rate for `operation`. The counts
#: are kept and reported unpriced; they are never charged at a default.
UNRATED = "unrated"
#: The dialect reported no `usage` on this node at all. Distinct from zero
#: tokens, and the two must not be spelled alike — the same argument
#: `SPEC.md` §3.3 makes about `absent` vs `empty`, one field over.
UNREPORTED = "no-usage-reported"


def _tokens(node: Node) -> tuple[int, int]:
    """Input and output counts, treating an unreported count as zero here.

    Only ever called where ``node.usage is not None``. A `Usage` whose
    `input_tokens` is None reported *some* counts and not that one; folding
    the missing one to zero understates the total, so ``partial_counts``
    counts those nodes and ``limits`` says so.
    """
    usage = node.usage
    assert usage is not None
    return (usage.input_tokens or 0, usage.output_tokens or 0)


def _seconds(node: Node) -> float | None:
    """Elapsed seconds, or ``None`` where a timestamp is missing.

    ``None`` rather than 0.0: a step of unknown length and a step of no length
    are different facts, and a sum that quietly treats the first as the second
    reports a lower bound as a total.
    """
    if node.started_at is None or node.ended_at is None:
        return None
    return round(node.ended_at - node.started_at, PLACES)


# -- the attribution -------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One node, with its own numbers and its `parent` subtree's."""

    node_id: str
    kind: str
    operation: str | None
    depth: int

    # -- what this node itself reported
    pricing: str
    self_input: int
    self_output: int
    #: `usage.total_tokens` exactly as reported, or ``None``. **Never derived**
    #: — the library refuses to add the other two (`SPEC.md` §3.4) and a
    #: consumer that quietly did so here would erase the distinction it is
    #: preserving. `derived_total` is the sum, carried separately.
    self_total_reported: int | None
    self_total_derived: int
    #: Counts the dialect reported under keys no document states
    #: (`Usage.extra`). Carried, never priced — see ``EXTRA_UNPRICED``.
    self_extra: Mapping[str, int]
    self_seconds: float | None
    self_charge: float | None

    # -- rolled up over this node and its `parent` descendants
    subtree_nodes: int
    subtree_input: int
    subtree_output: int
    subtree_extra: Mapping[str, int]
    #: The sum of the priced portion only. `unrated_*` and `unreported` say
    #: what was left out, so the number is a floor with its gap named.
    subtree_charge: float
    subtree_unrated_input: int
    subtree_unrated_output: int
    #: Nodes in the subtree the dialect reported no `usage` for, and the
    #: subset of those that are `llm` spans — which is the only place this
    #: consumer reads `kind`. A `tool` span with no token counts is normal; an
    #: `llm` span with none is a hole in the telemetry.
    subtree_unreported: int
    subtree_unreported_llm: int
    #: Seconds do not roll up the way tokens do, and this is the whole of why
    #: this consumer carries three numbers where it carries one for tokens.
    #: Adding a node's own interval to its children's double-counts, because
    #: the children run *inside* it; adding sibling intervals double-counts
    #: again where they run at the same time. So:
    #:
    #: * ``descendants_seconds_sum`` — the work done below this node: every
    #:   descendant's own interval, added. Exceeds the union under concurrency.
    #: * ``descendants_seconds_union`` — the length of the union of those
    #:   intervals, overlaps merged. What a caller actually waited for below.
    #: * ``unattributed_seconds`` — ``self_seconds`` minus that union: the time
    #:   inside this span that no descendant accounts for. **Negative is a
    #:   real answer**, not a bug: it means a descendant ran outside its
    #:   parent's own interval, and clamping it would hide the trace saying so.
    descendants_seconds_sum: float | None
    descendants_seconds_union: float | None
    unattributed_seconds: float | None
    subtree_seconds_unknown: int
    #: True where this node is reachable from one of its own `parent`
    #: children — the roll-up's tree assumption, checked rather than assumed.
    in_cycle: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "operation": self.operation,
            "depth": self.depth,
            "self": {
                "pricing": self.pricing,
                "input_tokens": self.self_input,
                "output_tokens": self.self_output,
                "total_tokens_reported": self.self_total_reported,
                "total_tokens_derived": self.self_total_derived,
                "extra_tokens": dict(sorted(self.self_extra.items())),
                "seconds": self.self_seconds,
                "charge": self.self_charge,
            },
            "subtree": {
                "nodes": self.subtree_nodes,
                "input_tokens": self.subtree_input,
                "output_tokens": self.subtree_output,
                "extra_tokens": dict(sorted(self.subtree_extra.items())),
                "charge": self.subtree_charge,
                "unrated_input_tokens": self.subtree_unrated_input,
                "unrated_output_tokens": self.subtree_unrated_output,
                "unreported_usage_nodes": self.subtree_unreported,
                "unreported_usage_llm_nodes": self.subtree_unreported_llm,
                "descendants_seconds_sum": self.descendants_seconds_sum,
                "descendants_seconds_union": self.descendants_seconds_union,
                "unattributed_seconds": self.unattributed_seconds,
                "seconds_unknown": self.subtree_seconds_unknown,
            },
            "in_parent_cycle": self.in_cycle,
        }


@dataclass(frozen=True)
class Attribution:
    """One trace, attributed."""

    source: str
    trace_id: str
    adapter: str
    steps: tuple[Step, ...]
    #: Ids with no incoming `parent` edge. **Empty is a finding**, not a
    #: formality: a `parent` graph that is entirely a cycle has no root, and a
    #: trace total taken over roots would then be silently zero.
    roots: tuple[str, ...]
    limits: tuple[str, ...]

    @property
    def total_input(self) -> int:
        return sum(step.self_input for step in self.steps)

    @property
    def total_output(self) -> int:
        return sum(step.self_output for step in self.steps)

    @property
    def total_charge(self) -> float:
        return round(sum(step.self_charge or 0.0 for step in self.steps), PLACES)

    @property
    def total_extra(self) -> dict[str, int]:
        counts: collections.Counter[str] = collections.Counter()
        for step in self.steps:
            counts.update(step.self_extra)
        return {key: counts[key] for key in sorted(counts)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "trace_id": self.trace_id,
            # Grouped under one heading, as `fleet_aggregate` and the
            # trajectory dumper both do: which adapter read the file is not a
            # property of the run.
            "dialect_local": {"adapter": self.adapter},
            "units": UNITS,
            "steps": [step.as_dict() for step in self.steps],
            "roots": list(self.roots),
            "totals": {
                "input_tokens": self.total_input,
                "output_tokens": self.total_output,
                "extra_tokens": self.total_extra,
                "charge": self.total_charge,
            },
            "limits": list(self.limits),
        }


def _union_seconds(bounds: Sequence[tuple[float, float]]) -> float | None:
    """Total length of a set of intervals, overlaps merged.

    ``None`` for no intervals at all, which is not the same as ``0.0``. An
    interval whose end precedes its start is kept as reported and contributes
    its (negative) length only through ``sum``; here it is normalized so the
    union stays a length, and ``BACKWARDS`` says the trace contained one.
    """
    if not bounds:
        return None
    total = 0.0
    current_start, current_end = None, None
    for start, end in sorted((min(a, b), max(a, b)) for a, b in bounds):
        if current_end is None or start > current_end:
            if current_end is not None and current_start is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_end is not None and current_start is not None:
        total += current_end - current_start
    return round(total, PLACES)


def _adapter_of(graph: Graph) -> str:
    if graph.meta is None or not graph.meta.adapters:
        return "(none recorded)"
    return ", ".join(sorted(a.id for a in graph.meta.adapters))


def attribute(source: str, *, adapter: str | None = None) -> Attribution:
    """Build the graph and attribute it. Raises what ``build`` raises."""
    return attribute_graph(source, build(source, adapter=adapter))


def attribute_graph(source: str, graph: Graph) -> Attribution:
    """The attribution of an already-built graph.

    Separated from ``attribute`` because the residency measurement needs to run
    this over a graph it has already stripped, and comparing the two outputs is
    P1's question in its executable form.
    """
    nodes = graph.nodes()
    partial = 0
    derived_totals = 0
    reported_totals_agreeing = 0
    reported_totals_disagreeing = 0

    steps: list[Step] = []
    for node in nodes:
        usage = node.usage
        if usage is None:
            pricing, self_in, self_out = UNREPORTED, 0, 0
            extra: Mapping[str, int] = {}
            self_charge = None
        else:
            self_in, self_out = _tokens(node)
            extra = dict(usage.extra)
            if usage.input_tokens is None or usage.output_tokens is None:
                partial += 1
            self_charge = charge(node.operation, self_in, self_out)
            pricing = PRICED if self_charge is not None else UNRATED
            if usage.total_tokens is None:
                derived_totals += 1
            elif usage.total_tokens == self_in + self_out:
                reported_totals_agreeing += 1
            else:
                reported_totals_disagreeing += 1

        rolled = _roll(
            graph, node, graph.descendants(node.id, edge_kinds=EdgeKind.PARENT)
        )
        steps.append(
            Step(
                node_id=node.id,
                kind=str(node.kind),
                operation=node.operation,
                depth=len(graph.ancestors(node.id, edge_kinds=EdgeKind.PARENT)),
                pricing=pricing,
                self_input=self_in,
                self_output=self_out,
                self_total_reported=None if usage is None else usage.total_tokens,
                self_total_derived=self_in + self_out,
                self_extra=extra,
                self_seconds=_seconds(node),
                self_charge=self_charge,
                in_cycle=any(
                    node.id in graph.descendants(child, edge_kinds=EdgeKind.PARENT)
                    for child in graph.children(node.id, edge_kinds=EdgeKind.PARENT)
                ),
                **rolled,
            )
        )

    roots = tuple(
        node.id
        for node in nodes
        if not graph.parents(node.id, edge_kinds=EdgeKind.PARENT)
    )
    return Attribution(
        source=source,
        trace_id=graph.trace_id,
        adapter=_adapter_of(graph),
        steps=tuple(steps),
        roots=roots,
        limits=_limits(
            steps,
            roots=roots,
            node_count=len(nodes),
            partial=partial,
            derived_totals=derived_totals,
            disagreeing_totals=reported_totals_disagreeing,
        ),
    )


def _roll(graph: Graph, node: Node, descendants: Sequence[str]) -> dict[str, Any]:
    """Roll one node's `parent` subtree up.

    **Tokens are summed over the node and its descendants**; each node's counts
    are its own, so nothing is counted twice. **Seconds are not summed with the
    node's own interval at all** — see `Step`. The descendants' intervals are
    summed *and* unioned, and the node's own interval is compared with the
    union rather than added to it.
    """
    total_in = total_out = 0
    unrated_in = unrated_out = 0
    unreported = unreported_llm = 0
    seconds_sum = 0.0
    seconds_known = 0
    seconds_unknown = 0 if _seconds(node) is not None else 1
    charged = 0.0
    extra: collections.Counter[str] = collections.Counter()
    bounds: list[tuple[float, float]] = []

    for index, node_id in enumerate((node.id, *descendants)):
        current = graph.node(node_id)
        # `parent` edges name only spans in this trace, but `Graph.node`
        # returns None for an id the graph does not hold and the contract says
        # a consumer must expect it (`SPEC.md` §4.0). Skipped rather than
        # crashed, and it has never happened on the committed corpus.
        if current is None:
            continue
        if index:  # descendants only: the node's own seconds are not rolled in
            elapsed = _seconds(current)
            if elapsed is None:
                seconds_unknown += 1
            else:
                seconds_sum += elapsed
                seconds_known += 1
                assert current.started_at is not None and current.ended_at is not None
                bounds.append((current.started_at, current.ended_at))

        usage = current.usage
        if usage is None:
            unreported += 1
            if current.kind is NodeKind.LLM:
                unreported_llm += 1
            continue
        node_in, node_out = _tokens(current)
        total_in += node_in
        total_out += node_out
        extra.update(usage.extra)
        node_charge = charge(current.operation, node_in, node_out)
        if node_charge is None:
            unrated_in += node_in
            unrated_out += node_out
        else:
            charged += node_charge

    union = _union_seconds(bounds)
    own = _seconds(node)
    return {
        "subtree_nodes": 1 + len(descendants),
        "subtree_input": total_in,
        "subtree_output": total_out,
        "subtree_extra": {key: extra[key] for key in sorted(extra)},
        "subtree_charge": round(charged, PLACES),
        "subtree_unrated_input": unrated_in,
        "subtree_unrated_output": unrated_out,
        "subtree_unreported": unreported,
        "subtree_unreported_llm": unreported_llm,
        "descendants_seconds_sum": round(seconds_sum, PLACES)
        if seconds_known
        else None,
        "descendants_seconds_union": union,
        "unattributed_seconds": (
            None if own is None or union is None else round(own - union, PLACES)
        ),
        "subtree_seconds_unknown": seconds_unknown,
    }


# -- the limits, which are the honest half of every total ------------------

NO_ROOT = (
    "no node is without a `parent` parent, so this trace has no root to total "
    "from: the `parent` edges form a cycle rather than a tree. Every subtree "
    "figure below is therefore a walk over a cycle, not a containment total."
)

IN_CYCLE = (
    "at least one node is reachable from its own `parent` child, so its "
    "subtree figures include nodes that also count it. Roll-up assumes a tree "
    "and this trace does not give one."
)

NO_TIMESTAMPS = (
    "some steps report no duration: the dialect omitted a timestamp, so a "
    "`seconds_sum` that includes them is a lower bound and not a total "
    "(`SPEC.md` §3.1)."
)

BACKWARDS = (
    "some steps report a negative duration: the instrumentor gave an "
    "`ended_at` before its `started_at`, and the library reports what it was "
    "told rather than clamping it. The sums below carry it unclamped."
)

OVERLAPPING = (
    "for at least one node the descendants' `seconds_sum` exceeds their "
    "`seconds_union`: spans below it ran at the same time. Latency does not "
    "add — `sum` is the work done and `union` is the time it took — and a "
    "figure that added them would report concurrency as slowness."
)

OUTSIDE_PARENT = (
    "for at least one node `unattributed_seconds` is negative: spans below it "
    "cover more wall time than the node's own interval, so a descendant ran "
    "outside its parent. Reported unclamped, because clamping it would hide "
    "the trace saying so."
)

UNRATED_TOKENS = (
    "some token counts are unpriced: this consumer's table has no rate for "
    "the model in `operation`, and pricing them at a default would state a "
    "number the table does not have. They are counted in `unrated_*` and "
    "excluded from `charge`."
)

UNREPORTED_USAGE = (
    "some `llm` spans report no `usage` at all: the dialect emitted no token "
    "attributes on them. That is a hole in the telemetry, not zero tokens, so "
    "the totals below are a floor and `unreported_usage_llm_nodes` says how "
    "many spans are missing from it."
)

PARTIAL_COUNTS = (
    "some spans report one token count and not the other. The missing count "
    "is treated as zero in the sums, which understates them."
)

EXTRA_UNPRICED = (
    "some token counts arrived in `Usage.extra` and are **not priced**. The "
    "keys there are each adapter's own attribute suffix carried verbatim "
    "(`prompt_details.cache_read` in one dialect, `cache_read_input_tokens` "
    "in another for the same concept), and no document states the vocabulary "
    "(`SPEC.md` §3.4's comment is an illustration, not a key list). A rate "
    "keyed on one of those spellings would be a rate keyed on one dialect, "
    "which is what this consumer must not become — so the counts are reported "
    "by key and left out of `charge`."
)

DERIVED_TOTALS = (
    "some spans report no `total_tokens`: the library never adds the other "
    "two, because that would state a figure the telemetry did not "
    "(`SPEC.md` §3.4). `total_tokens_derived` is this consumer's own sum and "
    "is labelled as such."
)

DISAGREEING_TOTALS = (
    "some spans report a `total_tokens` that is not the sum of the reported "
    "input and output counts. Both are carried as reported; neither is "
    "corrected."
)


def _limits(
    steps: Sequence[Step],
    *,
    roots: Sequence[str],
    node_count: int,
    partial: int,
    derived_totals: int,
    disagreeing_totals: int,
) -> tuple[str, ...]:
    limits: list[str] = []
    if node_count and not roots:
        limits.append(NO_ROOT)
    if any(step.in_cycle for step in steps):
        limits.append(IN_CYCLE)
    if any(step.self_seconds is None for step in steps):
        limits.append(NO_TIMESTAMPS)
    if any(step.self_seconds is not None and step.self_seconds < 0 for step in steps):
        limits.append(BACKWARDS)
    if any(
        step.descendants_seconds_sum is not None
        and step.descendants_seconds_union is not None
        and step.descendants_seconds_sum > step.descendants_seconds_union
        for step in steps
    ):
        limits.append(OVERLAPPING)
    if any(
        step.unattributed_seconds is not None and step.unattributed_seconds < 0
        for step in steps
    ):
        limits.append(OUTSIDE_PARENT)
    if any(step.pricing == UNRATED for step in steps):
        limits.append(UNRATED_TOKENS)
    if any(
        step.pricing == UNREPORTED and step.kind == str(NodeKind.LLM) for step in steps
    ):
        limits.append(UNREPORTED_USAGE)
    if partial:
        limits.append(PARTIAL_COUNTS)
    if any(step.self_extra for step in steps):
        limits.append(EXTRA_UNPRICED)
    if derived_totals:
        limits.append(DERIVED_TOTALS)
    if disagreeing_totals:
        limits.append(DISAGREEING_TOTALS)
    # De-duplicated in first-appearance order: a limit is a statement about the
    # trace, not a count of the rows that triggered it.
    return tuple(dict.fromkeys(limits))


# -- running over many sources ---------------------------------------------


@dataclass(frozen=True)
class Refused:
    """A trace the library refused. Reported, never raised out of a sweep."""

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


def attribute_all(
    sources: Iterable[str], *, adapter: str | None = None
) -> Iterator[Attribution | Refused]:
    """Attribute each source in turn; a refusal is a result, not an exit."""
    for source in sources:
        try:
            yield attribute(source, adapter=adapter)
        # Broad for the reason `examples/fleet_aggregate` gives: one unreadable
        # file must not cost the rest of a sweep, and trace payloads are
        # untrusted input (`SECURITY.md`). `SpanweaveError` is what says whether
        # the library refused the trace or something else went wrong.
        except Exception as error:
            yield Refused(
                source=source,
                error=type(error).__name__,
                code=error.code if isinstance(error, SpanweaveError) else None,
                message=str(error),
            )


# -- residency: P1's question, measured ------------------------------------
#
# P1 predicts this consumer wants `retain_payloads=False` / `retain_raw=False`.
# The library offers neither, so the measurement is done the only way a
# consumer can do it today: build the graph, then rebuild it with the verbatim
# bytes gone, and size both. What that *cannot* measure is peak — see
# `TASKS.md` 3.4's record.


def deep_bytes(obj: object, seen: set[int] | None = None) -> int:
    """Resident bytes of an object and everything it holds, each counted once.

    Deduplicated by identity, because two nodes sharing an interned string or
    the same `StrEnum` member cost that string once. Walks frozen dataclasses
    by their declared fields, which is the only way in: the model's types use
    ``slots=True`` and have no ``__dict__``.

    **Interpreter-dependent by construction.** ``sys.getsizeof`` reports what
    this build of CPython allocates, so the figures are comparable *within* a
    run and are not a portable constant. The consumer's own output does not
    contain them, so nothing this module prints by default depends on the
    platform; the record that quotes them names the interpreter.
    """
    if seen is None:
        seen = set()
    marker = id(obj)
    if marker in seen:
        return 0
    seen.add(marker)
    total = sys.getsizeof(obj)
    if isinstance(obj, str | bytes | bytearray | int | float | bool | type(None)):
        return total
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            total += deep_bytes(key, seen) + deep_bytes(value, seen)
        return total
    if isinstance(obj, list | tuple | set | frozenset):
        for item in obj:
            total += deep_bytes(item, seen)
        return total
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for field in dataclasses.fields(obj):
            total += deep_bytes(getattr(obj, field.name), seen)
        return total
    contents = getattr(obj, "__dict__", None)
    if contents:
        total += deep_bytes(contents, seen)
    return total


def without_verbatim(graph: Graph) -> Graph:
    """The same graph with every verbatim byte dropped, through the public API.

    Payload **state** and `mime` survive; `value` and `raw` do not, and
    `RawRecord.source` does not. That is the honest strip — `state` is a
    separate field from `value`, so a stripped graph still says *why* a payload
    has no content and does not have to pretend the instrumentor sent nothing.

    One thing it cannot say, and the record reports it: after the strip a
    payload reads `state=present, value=None, raw=None`, which `SPEC.md` §3.3
    already assigns a meaning — *declared JSON and did not parse*. The two are
    the same bytes. This consumer never hands the stripped graph to anything,
    so it does not need them told apart; a library option that returned such a
    graph would.
    """
    stripped = tuple(
        dataclasses.replace(
            node,
            inputs=Payload(state=node.inputs.state, mime=node.inputs.mime),
            outputs=Payload(state=node.outputs.state, mime=node.outputs.mime),
            raw=RawRecord(
                source=None,
                source_id=node.raw.source_id,
                line_number=node.raw.line_number,
            ),
        )
        for node in graph.nodes()
    )
    return Graph.of(
        trace_id=graph.trace_id,
        nodes=stripped,
        edges=graph.edges(),
        diagnostics=graph.diagnostics,
        meta=graph.meta,
        annotations=graph.annotations,
    )


@dataclass(frozen=True)
class Peak:
    """Allocated bytes around a build, from ``tracemalloc``.

    ``getsizeof`` answers *what does the graph weigh once I hold it*. This
    answers the question P1 is actually about: **what was the high-water mark**.
    The two readings are taken at the same point in ``tracemalloc``'s life, so
    ``peak`` is monotonic across them by construction — which is not a defect
    of the measurement, it is the finding. A consumer stripping a graph *after*
    ``build`` returns has already paid the peak, and no amount of dropping
    afterwards can un-pay it.
    """

    #: Traced bytes still held after the build, and the high-water mark reached.
    after_build_current: int
    after_build_peak: int
    #: The same two readings after the stripped graph replaces the built one
    #: and the original is released.
    after_strip_current: int
    after_strip_peak: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "after_build_current": self.after_build_current,
            "after_build_peak": self.after_build_peak,
            "after_strip_current": self.after_strip_current,
            "after_strip_peak": self.after_strip_peak,
            "_note": (
                "tracemalloc. `peak` is a high-water mark and cannot fall: "
                "that is the point of the reading, not a limitation of it. A "
                "post-build strip lowers `current` and leaves `peak` where it "
                "was, so it buys steady-state residency and buys nothing at "
                "the moment a build would run out of memory."
            ),
        }


def measure_peak(source: str, *, adapter: str | None = None) -> Peak:
    """Build, then strip, watching the allocator rather than the result."""
    import gc
    import tracemalloc

    gc.collect()
    tracemalloc.start()
    try:
        graph = build(source, adapter=adapter)
        built_current, built_peak = tracemalloc.get_traced_memory()
        stripped = without_verbatim(graph)
        del graph
        gc.collect()
        strip_current, strip_peak = tracemalloc.get_traced_memory()
        del stripped
    finally:
        tracemalloc.stop()
    return Peak(
        after_build_current=built_current,
        after_build_peak=built_peak,
        after_strip_current=strip_current,
        after_strip_peak=strip_peak,
    )


@dataclass(frozen=True)
class Residency:
    """What one built graph costs in memory, whole and stripped."""

    source: str
    nodes: int
    #: The graph as `build()` returns it.
    built_bytes: int
    #: The same graph with payload values, payload `raw`, and
    #: `RawRecord.source` dropped.
    stripped_bytes: int
    #: The part of `stripped_bytes` that is `diagnostics`. Called out because
    #: `Diagnostic.source` also holds verbatim fragments and **neither of P1's
    #: two option names covers it**.
    diagnostic_bytes: int

    @property
    def saved_bytes(self) -> int:
        return self.built_bytes - self.stripped_bytes

    @property
    def retained_fraction(self) -> float:
        return (
            round(self.stripped_bytes / self.built_bytes, 4)
            if self.built_bytes
            else 0.0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "nodes": self.nodes,
            "built_bytes": self.built_bytes,
            "stripped_bytes": self.stripped_bytes,
            "diagnostic_bytes": self.diagnostic_bytes,
            "saved_bytes": self.saved_bytes,
            "retained_fraction": self.retained_fraction,
            "built_bytes_per_node": round(self.built_bytes / self.nodes, 1)
            if self.nodes
            else None,
            "stripped_bytes_per_node": round(self.stripped_bytes / self.nodes, 1)
            if self.nodes
            else None,
        }


def measure(source: str, *, adapter: str | None = None) -> Residency:
    """Size one trace's graph, whole and stripped."""
    graph = build(source, adapter=adapter)
    stripped = without_verbatim(graph)
    return Residency(
        source=source,
        nodes=len(graph.nodes()),
        built_bytes=deep_bytes(graph),
        stripped_bytes=deep_bytes(stripped),
        diagnostic_bytes=deep_bytes(stripped.diagnostics),
    )


#: P1 states its case at this size. Every figure derived from it is an
#: **extrapolation** from graphs three orders of magnitude smaller, and is
#: labelled as one everywhere it appears.
P1_SPANS = 100_000


def measure_all(
    sources: Iterable[str], *, adapter: str | None = None
) -> list[Residency | Refused]:
    results: list[Residency | Refused] = []
    for source in sources:
        try:
            results.append(measure(source, adapter=adapter))
        except Exception as error:
            results.append(
                Refused(
                    source=source,
                    error=type(error).__name__,
                    code=error.code if isinstance(error, SpanweaveError) else None,
                    message=str(error),
                )
            )
    return results


def summarise(results: Sequence[Residency | Refused]) -> dict[str, Any]:
    """The corpus figure, and P1's 100k extrapolation named as one."""
    measured = [r for r in results if isinstance(r, Residency)]
    refused = [r.as_dict() for r in results if isinstance(r, Refused)]
    nodes = sum(r.nodes for r in measured)
    built = sum(r.built_bytes for r in measured)
    stripped = sum(r.stripped_bytes for r in measured)
    diagnostics = sum(r.diagnostic_bytes for r in measured)
    if not nodes:
        return {
            "measured": [r.as_dict() for r in measured],
            "refused": refused,
            "traces": len(measured),
            "nodes": 0,
        }
    built_per_node = built / nodes
    stripped_per_node = stripped / nodes
    return {
        "measured": [r.as_dict() for r in measured],
        "refused": refused,
        "traces": len(measured),
        "nodes": nodes,
        "built_bytes": built,
        "stripped_bytes": stripped,
        "diagnostic_bytes": diagnostics,
        "built_bytes_per_node": round(built_per_node, 1),
        "stripped_bytes_per_node": round(stripped_per_node, 1),
        "retained_fraction": round(stripped / built, 4),
        "extrapolation": {
            "_note": (
                "An EXTRAPOLATION, not a measurement: bytes-per-node measured "
                "on the traces above, multiplied out to the size "
                "`PREDICTIONS.md` P1 states. Bytes-per-node is dominated by "
                "payload length, so this figure is only as representative as "
                "the traces it was measured on — the committed corpus is one "
                "to nine spans each with short payloads and understates it. "
                "`--load` checks it at a chosen span count and payload size, "
                "with an input that is generated and is not a fixture."
            ),
            "spans": P1_SPANS,
            "built_megabytes": round(built_per_node * P1_SPANS / 1_000_000, 1),
            "stripped_megabytes": round(stripped_per_node * P1_SPANS / 1_000_000, 1),
        },
    }


def dumps(attribution: Attribution) -> str:
    """The machine form. ``sort_keys`` for the library's own reason."""
    return json.dumps(attribution.as_dict(), indent=2, sort_keys=True)
