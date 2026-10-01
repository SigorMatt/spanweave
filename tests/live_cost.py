"""What a live build costs, measured rather than reasoned about.

Run: ``make bench`` (``uv run python -m tests.live_cost``), optionally with
``ARGS="--turns 400 --wide 20000"``,
``ARGS="--only wide --root-last --wide 2000"`` or
``ARGS="--only echo --turns 400 --segments 4"``.

`SPEC.md` §10.6 states the cost of the two live paths: a `feed` is O(the keys
the arrival touched) and a `delta(since=v)` is O(n + e), because it sorts both
endpoints to recover canonical order and the `ordering_cycle` that the same
sort reports. This module measures those two paths on the two workloads the
September 2026 audit used, and — the reason it exists — it measures the **share
of each that the canonical-order sort actually is**, because that share is what
decides whether making the sort incremental would pay.

It asserts nothing about wall-clock time, deliberately and for the reason the
`stranger` target states: a duration threshold in an automated check is a flake
that gets tuned until it means nothing. It prints numbers; a human reads them.

The two workloads, both from ``tests/audit/probe2.py``:

- **echo** (case B), the agent loop that resends its history. `turns` turns make
  `2*turns + 1` records and `turns*(turns - 1)/2` `data` edges, so: few nodes,
  an edge set quadratic in them.
- **wide** (case C), one root with `n` tool children: a large node set, a linear
  edge set, and one sibling group holding all of it.

Recorded baseline, 2026-09-30, CPython 3.14.6, at `1d7ba8f` — the numbers
`SPEC.md` §10.6's cost paragraph rests on and the ones WORKPLAN L5 turned on.
The *ratios* are the finding; the absolute values are one machine's and will not
reproduce elsewhere.

| | echo, 400 turns | wide, 20,000 |
|---|---|---|
| records / nodes / edges | 801 / 801 / 81,799 | 20,001 / 20,001 / 39,999 |
| `feed`, all records | 75.5 s (94.2 ms each) | 1,449 s (72.4 ms each) |
| `graph()` cold | 312 ms | 391 ms |
| `delta(since=version - 1)` | 229 ms | 295 ms |
| — its two `ordering()` calls | 32.4 ms (**14%**) | 176.6 ms (**60%**) |
| — its endpoint node/edge sets | 140 ms | 77 ms |
| `feed` + per-record `delta`, all | 166 s | not run (hours) |

What those say, and what WORKPLAN L5 dropped on them. **`feed` does not sort at
all**: `build.in_order` is reached from three places — the batch build,
`SpanAbsorber.materialize`, and `delta.ordering` (twice per `delta()`, once per
`fold`) — and feeding is none of them, so an incrementally maintained canonical
order has nothing there to replace and could only add to it. Inside `delta()` the
two sorts are a seventh of the call on the echo shape, where assembling and
rewinding the endpoints' 81,799 edges is the bulk, but **three fifths** of it on
the wide shape, where the edge set is linear and the 20,001-node sort is not. So
the sort is worth removing on one of the two shapes — and removing it means
*not sorting*, which means carrying canonical order and `ordering_cycle` between
versions rather than computing them from the sets. `SPEC.md` §10.6 explains why
that is a spec conversation and not an optimization.

Two things measured on the way, recorded so they are not re-derived. **A faster
sort is not the lever**: Kahn with a heap in place of `in_order`'s
``sorted(...)`` + ``pop(0)`` emits the same sequence by construction and was
measured identical on both shapes, at 6.5 ms against 13.8 ms (echo) and 73.8 ms
against 93.5 ms (wide) — so even at 2.1x it moves `delta()` by 3% on the echo
shape. And **what is superlinear in `feed` is not ordering**: eight times the
records of a wide trace cost a hundred and sixteen times the feed (12.5 s at
2,500), because the wide shape restates its one sibling group's whole temporal
chain on every arrival and the echo shape restates a call id's whole `data` edge
set for every receipt echoed at it. Each was a key restated in full, which is
what `SPEC.md` §10.6 said an arrival costs.

**Both of those two sites are since fixed, so every `feed` number above is
history.** A sibling group's chain is now maintained in §4.3's order and an
arrival replaces only the edges adjacent to where it lands, so the wide shape's
`feed` is linear in its records: re-measured on one machine at 0.109 ms/record at
1,000 and 0.112 ms/record at 8,000, against 1.875 and 20.918 at the commit this
header's table was taken from. A call id's `data` edges are now amended per
declared receipt rather than restated, so the echo shape's `feed` is linear in the
receipts the input declares instead of cubic in its turns: 400 turns re-measured
on one machine at **958 ms against 75,171 ms**, with `Edge.__init__` called 81,799
times against 10,748,399 -- one `data` edge built per declared receipt, where
before each was rebuilt once per later turn. The table and the shares above are
left as the record of what was measured when; they are re-taken wholesale, with
provenance, by `WORKPLAN.md` L18.

What the echo shape's per-record cost does **not** become is flat, and `--segments`
is how that is read rather than argued. Its edge set is quadratic in its turns
because §4.2.1 says the input declares that many relations, so a turn carrying 350
declarations cannot cost what a turn carrying 25 does: measured over the same 400
turns in four stretches, 0.3746 ms/record over turns 1-100 against 2.0393 over
turns 301-400, a ratio of **5.44x** where the same measurement on the cubic site
gave 52.18x (4.3547 against 227.2158). The floor is the work itself -- those two
stretches declare 24.6 and 174.8 receipts per record, a ratio of 7.1x -- so 5.44x
is *below* the growth of the answer, the difference being the fixed per-record
cost of classifying and absorbing a span at all.

A third site the audit's table cannot show is the **arrival order** of one
record, and `--root-last` is that measurement: the wide shape fed children-first
makes the root's arrival regroup the whole input in a single `feed`. Maintaining
the chain fixed most of it — 15.4 s for that one arrival at 2,000 before,
38 ms after — and moving the whole group *at once* rather than child by child
took the rest, to 16 ms, which makes the arrival linear in the children rather
than `n log n`. Measured on one machine at 2,000: root-last total within 1.07x
of root-first, where before the chain was maintained it was far outside it.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from spanweave.api import Builder
from spanweave.delta import ordering
from spanweave.model import JsonValue


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
    print(f"  {label:<34} {seconds * 1000:9.1f} ms")
    return seconds


def _per_segment(cuts: Sequence[int], marks: Sequence[float], opened: float) -> None:
    """ms/record over each stretch of the stream, and the last against the first.

    A total says what a workload cost; it does not say whether the cost per
    record is **flat**, and that is the question a superlinear `feed` is asked
    (`SPEC.md` §10.6). So the one feed loop is marked at the cut points the
    caller names and each stretch reported on its own: a per-record cost that
    rises across the stream is a `feed` whose price depends on how much has
    already arrived, whatever the total looks like.

    The cuts are the caller's rather than an equal split of the records, because
    a segment boundary that falls mid-turn compares unlike work on a workload
    whose turns are two records each.
    """
    was = opened
    first = last = 0.0
    for index, (cut, mark) in enumerate(zip(cuts, marks, strict=True), start=1):
        started = 1 if index == 1 else cuts[index - 2] + 1
        each = (mark - was) * 1000 / (cut - started + 1)
        print(f"  {f'records {started}-{cut}':<34} {each:9.4f} ms/record")
        first, last, was = (each if index == 1 else first), each, mark
    if first:
        print(f"  {'last segment / first segment':<34} {last / first:9.2f} x")


def measure(
    label: str,
    records: Sequence[JsonValue],
    *,
    per_record: bool,
    cuts: Sequence[int] = (),
) -> None:
    """Feed the workload, then time each path at the version where n and e peak."""
    print(f"{label}: {len(records)} records")
    builder = Builder()
    marks: list[float] = []
    pending = list(cuts)
    start = time.perf_counter()
    for index, record in enumerate(records, start=1):
        builder.feed(record)
        if pending and index == pending[0]:
            marks.append(time.perf_counter())
            pending.pop(0)
    feed = _elapsed("feed, all records", start)
    print(f"  {'feed, per record':<34} {feed * 1000 / len(records):9.1f} ms")
    if marks:
        _per_segment(cuts, marks, start)

    start = time.perf_counter()
    graph = builder.graph()
    _elapsed("graph() cold", start)
    nodes, edges = graph.nodes(), graph.edges()
    print(f"  nodes={len(nodes)} edges={len(edges)}")

    start = time.perf_counter()
    builder.delta(since=builder.version - 1)
    whole = _elapsed("delta(since=version-1)", start)

    # The absorber's own two halves, to say how much of `delta()` each is. A
    # benchmark reaching inside is the point: the shares are what L5 turned on,
    # and no public surface reports them.
    absorber = builder._absorber
    start = time.perf_counter()
    held_nodes, held_edges = absorber.current_nodes(), absorber.current_edges()
    _elapsed("  of which the edge/node sets", start)
    start = time.perf_counter()
    ordering(held_nodes, held_edges, None)
    one = _elapsed("  of which one ordering()", start)
    share = 2 * one / whole * 100 if whole else 0.0
    print(f"  {'  the two ordering() calls are':<34} {share:8.1f} % of delta()")

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
    print(f"  {'feed, root last':<34} {last * 1000:9.1f} ms")
    print(f"  {'  of which the root arrival':<34} {single * 1000:9.1f} ms")
    ratio = last / first if first else 0.0
    print(f"  {'root last / root first':<34} {ratio:9.2f} x")


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
        help="run one workload. The wide one's `feed` is quadratic in its own "
        "right (see this module's docstring), so 20,000 takes tens of minutes.",
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
    args = parser.parse_args(argv)
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
        )


if __name__ == "__main__":
    main()
