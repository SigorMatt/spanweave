"""What a live build costs, measured rather than reasoned about.

Run: ``make bench``, which runs ``uv run python -m tests.live_cost --only echo``
and then ``--only wide``, one shape per process (see "One column, one process"
below), optionally with
``ARGS="--turns 400 --wide 20000 --segments 4 --count-edges"``,
``ARGS="--only wide --root-last --wide 2000"``, or ``ARGS="--smoke"`` -- the last
being the form ``make check`` runs, through the Makefile's ``bench-smoke``
target, which asserts shape and times nothing.

`SPEC.md` §10.6 states what each live path costs as a **promise**; this module is
where that section's numbers come from, which is why §10.6 cites it rather than
carrying a machine's ratios in its prose. It measures, separately:

- what `feed` costs per record and across the stream, and how many canonical
  sorts feeding makes (the answer is none, and it is **counted** here rather than
  read off the code);
- how many `Edge` objects feeding builds, against the edges the prefix holds --
  a count, not a duration, and the one that says whether a key is amended or
  restated (``--count-edges``);
- what a materialization costs and how much of it is the canonical sort;
- what `delta(since=v)` costs, split into the four parts it is made of:
  assembling the held node and edge sets, rewinding them to `since`, and the
  **two** `ordering()` calls -- one per endpoint, timed one at a time, because
  they sort two different node sets and nothing says they cost the same.

It asserts nothing about wall-clock time, deliberately and for the reason the
`stranger` target states: a duration threshold in an automated check is a flake
that gets tuned until it means nothing. It prints numbers; a human reads them.
``--smoke`` is the one part a gate runs, and it keeps that rule -- it asserts
counts, sort counts and bytes, and nothing whatever about elapsed time.

The two workloads, both from ``tests/audit/probe2.py``:

- **echo** (case B), the agent loop that resends its history. `turns` turns make
  `2*turns + 1` records and `turns*(turns - 1)/2` `data` edges, so: few nodes,
  an edge set quadratic in them.
- **wide** (case C), one root with `n` tool children: a large node set, a linear
  edge set, and one sibling group holding all of it.

Measured at `0718ba8` on 2026-10-02, CPython 3.14.6, on one machine, from this
module's own output (`WORKPLAN.md` L18, which re-took every number here after
L15-L17 fixed the three superlinear `feed` sites). The absolute values are that
machine's and will not reproduce elsewhere; what reproduces is the shape, which
``--smoke`` asserts and `SPEC.md` §10.6 states as a promise.

**One column, one process.** Each column below was taken with ``--only``, and
`make bench` now runs the two shapes as two processes for that reason: in one
process the echo shape's 81,799 edges are still held when the wide shape's
`delta()` runs, and the wide `delta()` and its two `ordering()` calls then read
well above the figures in this table -- so the default run would not reproduce
the table it documents (review B.2, 2026-10-02).

| | echo, 400 turns | wide, 20,000 |
|---|---|---|
| records / nodes / edges | 801 / 801 / 81,799 | 20,001 / 20,001 / 39,999 |
| `feed`, all records | 961.9 ms (1.2009 ms each) | 2,395.9 ms (0.1198 ms each) |
| — canonical sorts while feeding | 0 | 0 |
| — `Edge` objects built, per edge held | 81,799 = **1.000** | 39,999 = **1.000** |
| `graph()` cold | 249.9 ms | 298.7 ms |
| — of which the materialize sort | 18.0 ms (7.2%) | 86.9 ms (29.1%) |
| `delta(since=version - 1)` | 245.8 ms | 293.2 ms |
| — assembling the held sets | 161.5 ms (65.7%) | 77.8 ms (26.6%) |
| — the rewind to `since` | 44.3 ms (18.0%) | 26.1 ms (8.9%) |
| — `ordering()`, current endpoint | 18.5 ms (7.5%) | 91.2 ms (31.1%) |
| — `ordering()`, the `since` endpoint | 18.7 ms (7.6%) | 82.5 ms (28.1%) |
| `feed` + per-record `delta`, all | 61.6 s | not run (hours) |

The last row is from a second run of the echo shape at the same commit, whose
`feed` came out at 970.1 ms against the 961.9 above -- the spread between two
runs on one machine, printed here rather than hidden, because it is the size of
difference this instrument can and cannot see.

What those numbers say. **`feed` does not sort at all** -- `build.in_order` is
reached from the batch build, from `SpanAbsorber.materialize` and from
`delta.ordering` (twice per `delta()`, once per `fold`), and feeding is none of
them, so an incrementally maintained canonical order has nothing there to
replace and could only add to it. **Each edge is built once**: 1.000 `Edge`
object per edge the prefix holds, on both shapes, which is what §10.6's "the key
is amended, not restated" buys. **The wide shape's `feed` is flat** in the
records already arrived -- 0.1139 ms/record at 1,000 against 0.1136 at 8,000 --
and the echo shape's is not, because its *answer* is not (see `--segments`
below). Inside `delta()` the split is the shape's: on the echo shape the two
sorts are a seventh of the call and assembling and rewinding the 81,799 edges is
five sixths of it, while on the wide shape, whose edge set is linear and whose
node set is not small, the two sorts are **three fifths**. One
`delta(since=version - 1)` at the far end of the 20,000-span trace costs 293.2 ms
against the 0.1198 ms `feed` that produced it, so a consumer asking for a delta
after every record pays some two thousand times what feeding costs -- which is
`SPEC.md` §10.6's "a delta is O(n + e), not O(the changes)" in milliseconds.

**History, and labelled as such.** The table above replaces one taken at
`1d7ba8f` on 2026-09-30 (same machine, same interpreter), where the same two
shapes fed in **75.5 s** (94.2 ms/record) and **1,449 s** (72.4 ms/record)
against the 961.9 ms and 2,395.9 ms above. Three superlinear `feed` sites were
the difference and all three are fixed (`WORKPLAN.md` L15-L17): a sibling
group's temporal chain was rebuilt on every arrival, a call id's `data` edge set
was rebuilt for every receipt echoed at it -- 10,748,399 `Edge` objects for the
81,799 the echo shape holds, where it is now 81,799 -- and a late parent
regrouped its waiting children one at a time. One more thing was measured in
that session and is **not** reproducible from this tree: a Kahn sort with a heap
in place of `in_order`'s ``sorted(...)`` + ``pop(0)``, which emitted the same
sequence and ran at about twice the speed, moving `delta()` by about 3% on the
echo shape -- **measured in the batch session; harness not retained**. So it is
recorded as session history, here and in `CHANGELOG.md`, and `SPEC.md` states it
nowhere: a library cannot promise a number nothing in its tree reproduces.

What the echo shape's per-record cost does **not** become is flat, and
``--segments`` is how that is read rather than argued. Its edge set is quadratic
in its turns because §4.2.1 says the input declares that many relations and that
none is suppressed, so a turn carrying 350 declarations cannot cost what a turn
carrying 25 does. Measured over 400 turns in four stretches: 0.3784, 0.8133,
1.5593 and 2.0567 ms/record. The right thing to compare that rise against is not
1 but the **work itself**, which ``--segments`` now prints beside each stretch
rather than leaving to this docstring's arithmetic: turns 1-100 declare 4,950
receipts over 201 records (the root span folded into the first stretch) and turns
301-400 declare 34,950 over 200 -- 24.6 against 174.8 per record, so the declared
work rises **7.1x**, which bounds the ms/record rise from **above** and not from
below.

That direction is the whole of the comparison. With a per-record
cost of `F + c*d` -- `F` the fixed work of classifying and absorbing a span, `c`
the cost of one declaration, `d` the declarations the record carries --
`(F + c*d2)/(F + c*d1) <= d2/d1`, with equality only at `F = 0`. So the measured
5.43x being *under* 7.1x is what a non-zero `F` looks like and not a surprise:
those two stretch figures put `c` near 11 us per declaration and `F` near 0.10 ms
per record. Nothing bounds the ratio from **below** at all -- raising `F`, i.e.
being uniformly slower per span, drives it toward 1 -- so a ratio is a reading
rather than a target, and the 1.5x figure these stretches were once judged
against needed an edge some 30x cheaper to build (`c` near 0.37 us). That is an
empirical claim about this implementation's constants, not a consequence of
§4.2.1. What §4.2.1 does settle is that no declaration may be dropped to get
there (review A1, 2026-10-02, which found the earlier wording here calling 7.1x
a *floor* that the measurement then undercut).

A third site no table of totals can show is the **arrival order** of one record,
and ``--root-last`` is that measurement: the wide shape fed children-first makes
the root's arrival regroup the whole input inside a single `feed`. Measured at
2,000: 220.7 ms root-first against 235.9 ms root-last, of which the root's own
arrival is 19.9 ms -- a ratio of 1.07x on the same records in two orders. The
same arrival cost 15.4 s before the chain was maintained and 38 ms before the
whole group moved at once (`WORKPLAN.md` L16, history), so what is now left of it
is linear in the children.
"""

from __future__ import annotations

import argparse
import contextlib
import cProfile
import sys
import time
from collections.abc import Callable, Iterator, Sequence

from spanweave import api, dumps
from spanweave.api import Builder
from spanweave.model import Edge, EdgeKind, JsonValue

#: The `spanweave.build` **module**, which the attribute of that name is not:
#: `spanweave/__init__.py` exports the batch-build *function* as
#: `spanweave.build`, so the module object comes from `sys.modules` -- the same
#: route `tests/test_live.py` takes to `Edge`. `in_order` is looked up on this
#: object by every caller, which is what makes it timeable in place.
build = sys.modules["spanweave.build"]

#: What `--smoke` runs, and what the Makefile's `bench-smoke` target is.
SMOKE_TURNS = 5
SMOKE_WIDE = 5


def echo_records(turns: int) -> list[JsonValue]:
    """`tests/audit/probe2.py` case B: an agent loop that resends its history.

    The same shape `tests/test_openinference.py::_echo_loop_trace` builds, kept
    here rather than imported because a test module is collected and this one is
    not, and a benchmark that imports a test file makes the test file's
    fixtures load whenever the benchmark runs.
    """
    records: list[JsonValue] = [
        {
            "trace_id": "t1",
            "span_id": "s0",
            "parent_id": None,
            "name": "agent",
            "start_time": 1000.0,
            "end_time": 1000.0 + turns,
            "attributes": {"openinference.span.kind": "AGENT"},
        }
    ]
    for turn in range(turns):
        attributes: dict[str, JsonValue] = {
            "openinference.span.kind": "LLM",
            "llm.input_messages.0.message.role": "user",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": f"c{turn}",
        }
        for earlier in range(turn):
            attributes[f"llm.input_messages.{earlier + 1}.message.role"] = "tool"
            attributes[f"llm.input_messages.{earlier + 1}.message.tool_call_id"] = (
                f"c{earlier}"
            )
        start = 1000.0 + turn
        records.append(
            {
                "trace_id": "t1",
                "span_id": f"l{turn}",
                "parent_id": "s0",
                "name": "llm",
                "start_time": start + 0.1,
                "end_time": start + 0.4,
                "attributes": attributes,
            }
        )
        records.append(
            {
                "trace_id": "t1",
                "span_id": f"t{turn}",
                "parent_id": "s0",
                "name": "tool",
                "start_time": start + 0.5,
                "end_time": start + 0.9,
                "attributes": {
                    "openinference.span.kind": "TOOL",
                    "tool.name": "t",
                    "tool_call.id": f"c{turn}",
                    "output.value": "{}",
                },
            }
        )
    return records


def wide_records(width: int) -> list[JsonValue]:
    """`tests/audit/probe2.py` case C: one root, `width` tool children."""

    def span(span_id: str, parent: str | None, kind: str, start: float) -> JsonValue:
        return {
            "trace_id": "t1",
            "span_id": span_id,
            "parent_id": parent,
            "name": kind.lower(),
            "start_time": start,
            "end_time": start + 0.5,
            "status": "OK",
            "attributes": {"openinference.span.kind": kind},
        }

    return [span("s0", None, "AGENT", 0.0)] + [
        span(f"t{i}", "s0", "TOOL", float(i + 1)) for i in range(width)
    ]


def _elapsed(label: str, start: float) -> float:
    seconds = time.perf_counter() - start
    print(f"  {label:<36} {seconds * 1000:9.1f} ms")
    return seconds


def _share(label: str, seconds: float, whole: float) -> None:
    """One part of a call, as milliseconds and as a share of the whole call."""
    print(
        f"  {label:<36} {seconds * 1000:9.1f} ms"
        f"{seconds / whole * 100 if whole else 0.0:7.1f} % of it"
    )


def _count(label: str, number: int) -> None:
    print(f"  {label:<36} {number:9d}")


def _ratio(label: str, number: float) -> None:
    print(f"  {label:<36} {number:9.3f} x")


@contextlib.contextmanager
def _watch(target: object, name: str, into: list[float]) -> Iterator[None]:
    """Time every call to one function for as long as the block runs.

    The three costs §10.6 attributes separately -- the sort a materialization
    does, the rewind to the `since` endpoint, and the **two** `ordering()` calls
    one `delta()` makes -- are reachable from no public surface, and re-running
    them outside the call would time a *second* run over warm caches rather than
    the one the library made. So the function is wrapped for the duration of the
    block and restored after it: each number is a call that actually happened,
    recorded in the order it happened, and a count of the calls comes free.

    Restoring in a `finally` matters because this module patches library
    internals: a wrapper left installed would make every later measurement a
    measurement of the wrapper.
    """
    original: Callable[..., object] = getattr(target, name)

    def timed(*args: object, **kwargs: object) -> object:
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            into.append(time.perf_counter() - start)

    setattr(target, name, timed)
    try:
        yield
    finally:
        setattr(target, name, original)


def _edges_built(records: Sequence[JsonValue]) -> tuple[int, int]:
    """`Edge` objects built while feeding, against edges the prefix holds.

    What an arrival costs is not readable from a wall clock on a shared machine,
    but it *is* readable from how many edge objects the arrival had to make: an
    edge a maintained key reused is an edge nothing rebuilt. Two keys grow with
    the stream rather than with the record (§10.6), so "built once per edge held"
    is the whole of what maintaining them buys, and it is a count rather than a
    duration.

    Read from `cProfile.Profile.getstats()` rather than from `pstats`, and that
    is not a preference: every frozen dataclass compiles its `__init__` from a
    string, so `pstats` merges `Edge`, `Node`, `Diagnostic` and the rest under
    one `<string>:2 __init__` row and the count is unreadable there. A raw entry
    carries the **code object**, so the one belonging to `Edge.__init__` is
    identifiable by identity (`WORKPLAN.md` L15's note to this batch).
    """
    builder = Builder()
    profile = cProfile.Profile()
    profile.enable()
    for record in records:
        builder.feed(record)
    profile.disable()
    code = Edge.__init__.__code__
    built = sum(
        entry.callcount
        for entry in profile.getstats()
        if getattr(entry, "code", None) is code
    )
    return built, len(builder.graph().edges())


def _declared_receipts(record: JsonValue) -> int:
    """How many receipts of a call this one record declares (§4.2.1).

    Counted off the record rather than computed from the workload's closed
    form, because the comparison §10.6 draws -- ms/record against the work the
    input declares -- is only a measurement if **both** sides of it are read
    from the same records. The arithmetic is still available as a check, and
    ``--smoke`` holds this counter to §4.2.1's `n(n-1)/2` so a counter that
    drifted could not quietly flatter the ratio it feeds.

    The key is the OpenInference spelling the two workloads here are written
    in; a record of some other dialect declares nothing this reads, and the
    wide shape declares none at all, which is why the print below states the
    count beside the ratio instead of only the ratio.
    """
    if not isinstance(record, dict):
        return 0
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return 0
    return sum(1 for key in attributes if key.endswith(".message.tool_call_id"))


def _per_segment(
    cuts: Sequence[int],
    marks: Sequence[float],
    opened: float,
    declarations: Sequence[int],
) -> None:
    """ms/record over each stretch of the stream, against what it declares.

    A total says what a workload cost; it does not say whether the cost per
    record is **flat**, and that is the question a superlinear `feed` is asked
    (`SPEC.md` §10.6). So the one feed loop is marked at the cut points the
    caller names and each stretch reported on its own: a per-record cost that
    rises across the stream is a `feed` whose price depends on how much has
    already arrived, whatever the total looks like.

    Each stretch is printed with the receipts its records declare and the
    denominator those receipts are divided by, because the rise that means
    something is ms/record against **declarations/record** and not against 1 --
    and the declaration ratio bounds the ms ratio from above, so both have to be
    output of the same run to be compared at all (review A1).

    The cuts are the caller's rather than an equal split of the records, because
    a segment boundary that falls mid-turn compares unlike work on a workload
    whose turns are two records each.
    """
    was = opened
    first = last = 0.0
    first_density = last_density = 0.0
    for index, (cut, mark) in enumerate(zip(cuts, marks, strict=True), start=1):
        started = 1 if index == 1 else cuts[index - 2] + 1
        held = cut - started + 1
        each = (mark - was) * 1000 / held
        receipts = sum(declarations[started - 1 : cut])
        density = receipts / held
        print(f"  {f'records {started}-{cut}':<36} {each:9.4f} ms/record")
        print(
            f"  {'  declaring':<36} {receipts:9d} receipts over {held} "
            f"records = {density:.3f}/record"
        )
        first, last, was = (each if index == 1 else first), each, mark
        first_density, last_density = (
            (density if index == 1 else first_density),
            density,
        )
    if first:
        print(f"  {'last segment / first segment':<36} {last / first:9.2f} x")
    if first_density:
        print(
            f"  {'  declarations/record, last / first':<36} "
            f"{last_density / first_density:9.2f} x"
        )
        print(
            "    the second bounds the first from above, with equality only at "
            "zero fixed per-record cost"
        )


def measure(
    label: str,
    records: Sequence[JsonValue],
    *,
    per_record: bool,
    cuts: Sequence[int] = (),
    count_edges: bool = False,
) -> None:
    """Feed the workload, then time each path at the version where n and e peak.

    Each of the three things `SPEC.md` §10.6 attributes a cost to is timed on its
    own and inside the call that makes it: the sort a materialization does, the
    rewind to the `since` endpoint, and the two `ordering()` calls of one
    `delta()`, separately, because they are sorts of two different node sets and
    nothing says they cost the same. The sorts `feed` makes are counted too --
    the claim is that there are none, and a share of a call is only as good as
    the claim about what is outside it.
    """
    print(f"{label}: {len(records)} records")
    builder = Builder()
    marks: list[float] = []
    pending = list(cuts)
    fed_sorts: list[float] = []
    with _watch(build, "in_order", fed_sorts):
        start = time.perf_counter()
        for index, record in enumerate(records, start=1):
            builder.feed(record)
            if pending and index == pending[0]:
                marks.append(time.perf_counter())
                pending.pop(0)
        feed = _elapsed("feed, all records", start)
    print(f"  {'feed, per record':<36} {feed * 1000 / len(records):9.4f} ms")
    _count("feed, canonical sorts", len(fed_sorts))
    if marks:
        _per_segment(cuts, marks, start, [_declared_receipts(r) for r in records])
    if count_edges:
        built, holding = _edges_built(records)
        _count("Edge objects built while feeding", built)
        _ratio("  per edge the prefix holds", built / holding if holding else 0.0)

    sorts: list[float] = []
    with _watch(build, "in_order", sorts):
        start = time.perf_counter()
        graph = builder.graph()
        cold = _elapsed("graph() cold", start)
    for seconds in sorts:
        _share("  of which the materialize sort", seconds, cold)
    nodes, edges = graph.nodes(), graph.edges()
    print(f"  nodes={len(nodes)} edges={len(edges)}")

    # Reaching inside is the point: the shares are what L5 turned on, no public
    # surface reports them, and §10.6 names these parts rather than the total.
    absorber = builder._absorber
    sorts.clear()
    rewinds: list[float] = []
    held: list[float] = []
    with (
        _watch(build, "in_order", sorts),
        _watch(api, "_rewound_nodes", rewinds),
        _watch(api, "_rewound_edges", rewinds),
        _watch(absorber, "current_nodes", held),
        _watch(absorber, "current_edges", held),
    ):
        start = time.perf_counter()
        builder.delta(since=builder.version - 1)
        whole = _elapsed("delta(since=version-1)", start)
    _share("  of which the held node/edge sets", sum(held), whole)
    _share("  of which the rewind to `since`", sum(rewinds), whole)
    for which, seconds in zip(("current", "`since`"), sorts, strict=False):
        _share(f"  of which ordering(), {which}", seconds, whole)
    _share("  of which both ordering() calls", sum(sorts), whole)

    if per_record:
        replay = Builder()
        start = time.perf_counter()
        for record in records:
            replay.delta(since=replay.feed(record) - 1)
        _elapsed("feed + delta per record, all", start)


def arrival_order(width: int) -> None:
    """The wide shape fed root-first and root-last, and the ratio of the two.

    Where one record arrives is a cost case of its own, and the only one the two
    `measure` workloads cannot show: a parent that arrives after its children
    gives **all** of them a parent inside a single `feed` (`SPEC.md` §10.2,
    §10.6), so the whole of the shape's regrouping happens in one call instead of
    being spread one record at a time over the stream. Both orders build the same
    graph -- that is §10.1, and `tests/test_live.py` asserts it rather than this
    module, which times things and asserts nothing.

    Printed as a ratio against the same records fed root-first, because that is
    the comparison that says whether the arrival order matters, and the absolute
    numbers are one machine's.
    """
    records = wide_records(width)
    print(f"wide, {width}: the root fed first against the root fed last")
    builder = Builder()
    start = time.perf_counter()
    for record in records:
        builder.feed(record)
    first = _elapsed("feed, root first", start)

    builder = Builder()
    start = time.perf_counter()
    for record in records[1:]:
        builder.feed(record)
    children = time.perf_counter() - start
    start = time.perf_counter()
    builder.feed(records[0])
    single = time.perf_counter() - start
    last = children + single
    print(f"  {'feed, root last':<36} {last * 1000:9.1f} ms")
    print(f"  {'  of which the root arrival':<36} {single * 1000:9.1f} ms")
    ratio = last / first if first else 0.0
    print(f"  {'root last / root first':<36} {ratio:9.2f} x")


def _require(ok: bool, said: str, problems: list[str]) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {said}")
    if not ok:
        problems.append(said)


def smoke(turns: int = SMOKE_TURNS, width: int = SMOKE_WIDE) -> None:
    """Every mode of this module over a handful of records, asserting *shape*.

    `make check` runs this, through the Makefile's `bench-smoke` target, and it
    asserts nothing about the clock -- for the reason `make stranger` and this
    module both already state: a duration threshold in an automated check is a
    flake that gets tuned until it means nothing. What it asserts instead is the
    **shape** of the cost, which is what §10.6's promises are actually made of
    and what a wall clock cannot report at a size the fast gate can afford:

    - the closed form §4.2.1 promises -- `n` turns declare `n(n-1)/2` receipts
      and every one of them is an edge, none suppressed;
    - **one `Edge` built per edge the prefix holds**, on both shapes. That is
      what "the key is amended, not restated" means for the two keys that grow
      with the stream, so a regression in any of the three sites `WORKPLAN.md`
      L15-L17 fixed shows up here as an edge built more than once -- at eleven
      records, in milliseconds, instead of in a benchmark nobody runs;
    - `feed` sorts **nothing**, a materialization sorts once and a `delta()`
      twice, which is the premise under every share this module prints;
    - the root fed last builds the same bytes as the root fed first, which is
      §10.1 across the arrival order this module times separately.

    The timings this module exists for are still printed by `make bench`; what
    runs in the gate is only the part that can be true or false.
    """
    print(f"smoke: echo {turns} turns, wide {width}, asserting shape and not time")
    problems: list[str] = []

    sorts: list[float] = []
    builder = Builder()
    with _watch(build, "in_order", sorts):
        for record in echo_records(turns):
            builder.feed(record)
        fed = len(sorts)
        graph = builder.graph()
        materialized = len(sorts) - fed
        builder.delta(since=builder.version - 1)
        delta_sorts = len(sorts) - fed - materialized

    declared = turns * (turns - 1) // 2
    data = [edge for edge in graph.edges() if edge.kind is EdgeKind.DATA]
    _require(
        len(data) == declared,
        f"echo {turns} turns holds {len(data)} `data` edges for the "
        f"{declared} receipts §4.2.1 says it declares",
        problems,
    )
    counted = sum(_declared_receipts(record) for record in echo_records(turns))
    _require(
        counted == declared,
        f"the per-segment receipt counter reads {counted} declarations off the "
        f"records where §4.2.1's closed form says {declared}, and `--segments` "
        f"divides the measured ms/record by that count",
        problems,
    )
    _require(
        fed == 0, f"feeding made {fed} canonical sorts, and §10.6 says 0", problems
    )
    _require(
        materialized == 1,
        f"materializing made {materialized} canonical sorts, and §10.6 says 1",
        problems,
    )
    _require(
        delta_sorts == 2,
        f"delta() made {delta_sorts} canonical sorts, and §10.6 says 2 -- one "
        f"per endpoint",
        problems,
    )

    wide = wide_records(width)
    for label, records in (
        (f"echo {turns} turns", echo_records(turns)),
        (f"wide {width}", wide),
        # The same records with the root last, because that is the third site
        # (§10.6's late parent) and the only one a root-first feed cannot show:
        # the arrival that gives every waiting child a parent moves the whole
        # group, and a group that moves whole keeps the chain it had.
        (f"wide {width}, root last", [*wide[1:], wide[0]]),
    ):
        built, holding = _edges_built(records)
        _require(
            built == holding,
            f"{label} built {built} `Edge` objects for the {holding} edges it "
            f"holds, and §10.6 promises each key is amended rather than restated",
            problems,
        )

    records = wide_records(width)
    root_first = Builder()
    for record in records:
        root_first.feed(record)
    root_last = Builder()
    for record in records[1:]:
        root_last.feed(record)
    root_last.feed(records[0])
    _require(
        dumps(root_first.graph()) == dumps(root_last.graph()),
        "the wide shape fed root-last serializes to the same bytes as root-first "
        "(§10.1), so the arrival order this module times changes cost and not "
        "the answer",
        problems,
    )

    if problems:
        raise SystemExit(
            f"the live-cost harness measures something other than what "
            f"`SPEC.md` §10.6 promises: {len(problems)} check(s) failed"
        )
    print("smoke: every check green")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=400, help="echo workload turns")
    parser.add_argument("--wide", type=int, default=20_000, help="wide workload width")
    parser.add_argument(
        "--per-record",
        action="store_true",
        help="also replay the whole workload asking for a delta after every "
        "record. Quadratic on both workloads; minutes, not seconds.",
    )
    parser.add_argument(
        "--only",
        choices=("echo", "wide"),
        help="run one workload. `make bench` passes one of these per process, "
        "because the table in this module's docstring was taken that way and a "
        "single process running both does not reproduce it.",
    )
    parser.add_argument(
        "--segments",
        type=int,
        default=0,
        help="split the feed into this many equal stretches of the stream and "
        "print ms/record for each, plus the last against the first. Whether the "
        "per-record cost is flat is what a superlinear `feed` is asked, and a "
        "total cannot answer it (`SPEC.md` §10.6).",
    )
    parser.add_argument(
        "--root-last",
        action="store_true",
        help="for the wide workload, feed it twice -- root first and root last "
        "-- and print the ratio, instead of timing `graph()` and `delta()`. "
        "What the arrival order of one record costs (`SPEC.md` §10.6).",
    )
    parser.add_argument(
        "--count-edges",
        action="store_true",
        help="also feed each workload under `cProfile` and report how many "
        "`Edge` objects it built per edge the prefix holds. A count, not a "
        "duration, and the one that says whether a key is amended or restated.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=f"the form `make check` runs (--turns {SMOKE_TURNS} --wide "
        f"{SMOKE_WIDE}): assert the SHAPE this module's numbers are about -- "
        f"the declared-receipt count, one `Edge` per edge held, where the sorts "
        f"are, and that the arrival order changes no bytes -- and assert "
        f"nothing whatever about elapsed time. Exits non-zero on a failure.",
    )
    args = parser.parse_args(argv)
    if args.smoke:
        smoke(SMOKE_TURNS, SMOKE_WIDE)
        return
    if args.only != "wide":
        # Turn-aligned, because one echo turn is two records after the root: a
        # boundary anywhere else would put a turn's LLM span in one segment and
        # its tool span in the next, and those two cost nothing like each other.
        per = args.turns // args.segments if args.segments else 0
        measure(
            f"echo, {args.turns} turns",
            echo_records(args.turns),
            per_record=args.per_record,
            cuts=[1 + 2 * per * index for index in range(1, args.segments + 1)]
            if per
            else (),
            count_edges=args.count_edges,
        )
    if args.only == "echo":
        return
    if args.root_last:
        arrival_order(args.wide)
    else:
        width = args.wide
        measure(
            f"wide, {width}",
            wide_records(width),
            per_record=args.per_record,
            cuts=[
                1 + width * index // args.segments
                for index in range(1, args.segments + 1)
            ]
            if args.segments
            else (),
            count_edges=args.count_edges,
        )


if __name__ == "__main__":
    main()
