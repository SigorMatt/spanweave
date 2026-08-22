"""``python -m examples.fleet_aggregate <trace> [<trace> ...]``.

Prints a rollup over every trace it is given. Reads files; opens no socket
(`ENVIRONMENT.md`: examples consume committed fixtures, so a stranger can
reproduce every number here).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from examples.fleet_aggregate import Fleet, aggregate

USAGE = "one or more trace files (a shell glob over the corpus is the usual way)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.fleet_aggregate",
        description="Roll many spanweave graphs up into one set of counts.",
    )
    parser.add_argument("traces", nargs="+", metavar="TRACE", help=USAGE)
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text is for reading; json is for a fleet dashboard (default: text)",
    )
    return parser


def _table(title: str, counts: dict[str, int], *, width: int) -> list[str]:
    if not counts:
        return [f"{title}: none", ""]
    lines = [f"{title}:"]
    lines += [f"  {name:<{width}} {count:>6}" for name, count in counts.items()]
    lines.append("")
    return lines


def report(fleet: Fleet) -> str:
    """The human rollup. Same input, same bytes -- nothing here reads a clock."""
    rollup = fleet.as_dict()
    traces = rollup["traces"]
    named = (
        *rollup["tools"],
        *rollup["diagnostics"],
        *rollup["models"],
        *rollup["unfulfilled_calls"]["by_model"],
    )
    width = max([10, *(len(name) for name in named)])

    lines = [
        f"{traces['built']} of {traces['given']} traces built"
        f" ({traces['unbuildable']} unbuildable),"
        f" {traces['distinct_trace_ids']} distinct trace_id(s)",
        "",
    ]

    if traces["distinct_trace_ids"] != traces["built"]:
        lines += [
            "note: trace_id does not identify a trace here -- "
            f"{traces['built']} graphs share {traces['distinct_trace_ids']}"
            " id(s), so this rollup is keyed on the inputs it was handed.",
            "",
        ]

    lines += _table("node kinds", rollup["node_kinds"], width=width)
    lines += _table("diagnostics", rollup["diagnostics"], width=width)

    if rollup["tools"]:
        lines.append("tools:")
        header = f"{'calls':>6} {'error':>6} {'ok':>6} {'unset':>6}"
        lines.append(f"  {'name':<{width}} {header}")
        for name, counts in rollup["tools"].items():
            lines.append(
                f"  {name:<{width}} {counts['calls']:>6} {counts['errors']:>6}"
                f" {counts['ok']:>6} {counts['unset']:>6}"
            )
        lines.append("")
    else:
        lines += ["tools: none", ""]

    lines += _table("models", rollup["models"], width=width)

    unfulfilled = rollup["unfulfilled_calls"]
    lines += [
        f"calls requested and never fulfilled: {unfulfilled['total']}",
        f"results with no matching call:       {rollup['unfulfilled_results']}",
        "",
    ]
    if unfulfilled["total"]:
        lines += _table(
            "  ...by the model that asked", unfulfilled["by_model"], width=width
        )
        lines += ["  ...by the tool it asked for: not available (see limit below)", ""]

    if rollup["unbuildable"]:
        lines.append("unbuildable:")
        for failure in rollup["unbuildable"]:
            lines.append(f"  {failure['source']}")
            lines.append(
                f"    {failure['error']} [{failure['code']}] {failure['message']}"
            )
        lines.append("")

    for limit in rollup["limits"]:
        lines += [f"limit: {limit}", ""]

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fleet = aggregate(args.traces)
    if args.format == "json":
        # sort_keys for the same reason the library does it: a rollup you
        # cannot diff between two runs is not a rollup.
        sys.stdout.write(json.dumps(fleet.as_dict(), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(report(fleet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
