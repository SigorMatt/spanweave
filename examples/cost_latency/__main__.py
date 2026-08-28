"""``python -m examples.cost_latency <trace> [<trace> ...]``.

Attributes tokens and seconds up the `parent` tree for each trace it is given,
priced by this consumer's own table. Reads files; opens no socket
(`ENVIRONMENT.md`: examples consume committed fixtures, so a stranger can
reproduce every line here).

``--format json`` is the machine form. ``--residency`` prints the P1
measurement — what a built graph costs in memory, and what the same graph
costs with every verbatim byte gone. ``--load`` generates a load input to check
that measurement's extrapolation; what it writes is **not** a fixture and
``examples/cost_latency/load.py`` says so at length.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Sequence
from typing import Any

from examples.cost_latency import (
    PLACES,
    PRICED,
    RATES,
    UNITS,
    Attribution,
    Peak,
    Refused,
    Step,
    attribute_all,
    measure_all,
    measure_peak,
    summarise,
)
from examples.cost_latency import load as load_module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.cost_latency",
        description=(
            "Roll spanweave token counts and durations up the parent tree, "
            "priced by this example's own table."
        ),
    )
    parser.add_argument(
        "traces",
        nargs="*",
        metavar="TRACE",
        help="one or more trace files (committed fixtures)",
    )
    parser.add_argument(
        "--adapter",
        default=None,
        help="name a dialect and skip detection (as `spanweave build` does)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text is for reading; json is for a rollup (default: text)",
    )
    parser.add_argument(
        "--residency",
        action="store_true",
        help="print the memory measurement instead of the attribution",
    )
    parser.add_argument(
        "--load",
        type=int,
        default=None,
        metavar="SPANS",
        help=(
            "generate a load input of SPANS spans, measure it, and print the "
            "result. GENERATED, not captured, and never written under "
            "fixtures/"
        ),
    )
    parser.add_argument(
        "--load-chars",
        type=int,
        default=1500,
        metavar="N",
        help="payload length in the generated load input (default: 1500)",
    )
    parser.add_argument(
        "--load-path",
        default=None,
        metavar="PATH",
        help="where to write the load input (default: under out/, gitignored)",
    )
    return parser


# -- the attribution report ------------------------------------------------


def _seconds(value: float | None) -> str:
    return "      ?" if value is None else f"{value:>6.3f}s"


def _money(value: float | None) -> str:
    """Fixed point, never scientific: two rows of a table must line up."""
    return "?" if value is None else f"{value:.{PLACES}f}"


def _step_lines(step: Step) -> list[str]:
    indent = "  " * step.depth
    lines = [
        f"  {indent}{step.kind}"
        f"{'' if step.operation is None else ' ' + step.operation}"
        f"   [{step.node_id}]  self {_seconds(step.self_seconds)}"
        f"  below: sum {_seconds(step.descendants_seconds_sum)}"
        f"  union {_seconds(step.descendants_seconds_union)}"
        f"  unattributed {_seconds(step.unattributed_seconds)}"
    ]
    if step.pricing == PRICED:
        lines.append(
            f"       {indent}tokens in {step.self_input} out {step.self_output}"
            f"   {_money(step.self_charge)} {UNITS}"
        )
    elif step.pricing != "no-usage-reported":
        lines.append(
            f"       {indent}tokens in {step.self_input} out {step.self_output}"
            f"   unpriced: no rate for {step.operation!r}"
        )
    if step.self_total_reported is not None:
        agrees = step.self_total_reported == step.self_total_derived
        lines.append(
            f"       {indent}total {step.self_total_reported} as reported"
            f" ({'agrees with' if agrees else 'DIFFERS from'} in+out"
            f" = {step.self_total_derived})"
        )
    elif step.pricing != "no-usage-reported":
        lines.append(
            f"       {indent}total {step.self_total_derived} derived here"
            f" (the dialect reported none)"
        )
    for key, count in sorted(step.self_extra.items()):
        lines.append(
            f"       {indent}extra {key}={count}  unpriced — the key is this "
            f"dialect's own spelling"
        )
    if step.subtree_nodes > 1:
        lines.append(
            f"       {indent}subtree of {step.subtree_nodes}: in "
            f"{step.subtree_input} out {step.subtree_output}"
            f"  {_money(step.subtree_charge)} {UNITS}"
            + (
                f"  (+{step.subtree_unrated_input}/"
                f"{step.subtree_unrated_output} unrated)"
                if step.subtree_unrated_input or step.subtree_unrated_output
                else ""
            )
            + (
                f"  ({step.subtree_unreported_llm} llm span(s) reported no usage)"
                if step.subtree_unreported_llm
                else ""
            )
        )
    if step.in_cycle:
        lines.append(f"       {indent}! this node is inside a `parent` cycle")
    return lines


def report(attribution: Attribution) -> str:
    lines = [
        f"trace {attribution.trace_id} — {len(attribution.steps)} step(s)"
        f"  [{attribution.source}]",
        f"  dialect-local: adapter={attribution.adapter}",
        f"  roots: {', '.join(attribution.roots) or '(none)'}",
    ]
    # Before the numbers, not after them: every one of these says a total
    # below is a floor rather than a total, and a reader who learns that
    # afterwards has read the total as a total.
    for limit in attribution.limits:
        lines.append(f"  limit: {limit}")
    lines.append("")
    for step in attribution.steps:
        lines.extend(_step_lines(step))
        lines.append("")
    lines.append(
        f"  trace totals: in {attribution.total_input} out "
        f"{attribution.total_output}   {_money(attribution.total_charge)} {UNITS}"
    )
    for key, count in attribution.total_extra.items():
        lines.append(f"                extra {key}={count} (unpriced)")
    lines.append("")
    return "\n".join(lines)


def _refusal(refused: Refused) -> str:
    return (
        f"{refused.source}: not attributed — "
        f"{refused.error} [{refused.code}] {refused.message}\n"
    )


# -- the residency report --------------------------------------------------


def residency_report(summary: dict[str, Any]) -> str:
    lines = [
        "resident bytes per built graph, and per graph with every verbatim",
        "byte dropped (payload `value`, payload `raw`, `RawRecord.source`).",
        "",
        "  Measured with sys.getsizeof, deduplicated by object identity, on",
        f"  {sys.implementation.name} {sys.version.split()[0]} — these figures",
        "  are comparable within this run and are not a portable constant.",
        "",
    ]
    for row in summary.get("measured", []):
        lines.append(
            f"  {row['source']}\n"
            f"      nodes {row['nodes']:>3}"
            f"  built {row['built_bytes']:>8}"
            f"  stripped {row['stripped_bytes']:>8}"
            f"  retained {row['retained_fraction']}"
        )
    for row in summary.get("refused", []):
        lines.append(f"  {row['source']}: refused — {row['error']} [{row['code']}]")
    if not summary.get("nodes"):
        return "\n".join(lines) + "\n"
    lines += [
        "",
        f"  over {summary['traces']} trace(s), {summary['nodes']} node(s):",
        f"      built     {summary['built_bytes']} B"
        f"  ({summary['built_bytes_per_node']} B/node)",
        f"      stripped  {summary['stripped_bytes']} B"
        f"  ({summary['stripped_bytes_per_node']} B/node)",
        f"      retained  {summary['retained_fraction']} of the built size",
        f"      of which  {summary['diagnostic_bytes']} B is `diagnostics`,"
        f" which the strip does not touch",
        "",
    ]
    extrapolation = summary["extrapolation"]
    lines += [
        f"  EXTRAPOLATION to {extrapolation['spans']} spans — not a measurement:",
        f"      built     ~{extrapolation['built_megabytes']} MB",
        f"      stripped  ~{extrapolation['stripped_megabytes']} MB",
        f"      {extrapolation['_note']}",
    ]
    return "\n".join(lines) + "\n"


def peak_report(peak: Peak) -> str:
    """The high-water reading, which is the one P1's option would move."""
    return (
        "\n  allocator high-water mark (tracemalloc), which is the reading a\n"
        "  `retain_payloads=False` build option would move and a post-build\n"
        "  strip cannot:\n"
        f"      after build      current {peak.after_build_current:>11}"
        f"   peak {peak.after_build_peak:>11}\n"
        f"      after strip      current {peak.after_strip_current:>11}"
        f"   peak {peak.after_strip_peak:>11}\n"
        "      `current` falls, `peak` does not. A consumer can drop the\n"
        "      verbatim bytes it does not need; it cannot avoid allocating\n"
        "      them, because `build()` returns only after it has.\n"
    )


def _load(args: argparse.Namespace) -> int:
    path = (
        pathlib.Path(args.load_path)
        if args.load_path
        else load_module.default_path(args.load, args.load_chars)
    )
    written = load_module.generate(path, spans=args.load, payload_chars=args.load_chars)
    summary = summarise(measure_all([str(written)], adapter=args.adapter))
    peak = measure_peak(str(written), adapter=args.adapter)
    if args.format == "json":
        sys.stdout.write(
            json.dumps(
                {
                    "generated_load_input": str(written),
                    "spans": args.load,
                    "payload_chars": args.load_chars,
                    "residency": summary,
                    "peak": peak.as_dict(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0
    sys.stdout.write(
        f"GENERATED load input (not a fixture, not captured): {written}\n"
        f"  {args.load} span(s), {args.load_chars}-char payloads.\n\n"
    )
    sys.stdout.write(residency_report(summary))
    sys.stdout.write(peak_report(peak))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.load is not None:
        return _load(args)

    if not args.traces:
        _parser().error("give at least one trace, or --load SPANS")

    if args.residency:
        summary = summarise(measure_all(args.traces, adapter=args.adapter))
        if args.format == "json":
            sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(residency_report(summary))
        return 0

    results = list(attribute_all(args.traces, adapter=args.adapter))
    if args.format == "json":
        sys.stdout.write(
            json.dumps(
                {
                    "rates": {
                        model: {
                            "input_per_mtok": rate.input_per_mtok,
                            "output_per_mtok": rate.output_per_mtok,
                        }
                        for model, rate in sorted(RATES.items())
                    },
                    "units": UNITS,
                    "traces": [
                        result.as_dict()
                        if isinstance(result, Attribution)
                        else {"refused": result.as_dict()}
                        for result in results
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0

    for result in results:
        if isinstance(result, Refused):
            sys.stdout.write(_refusal(result))
        else:
            sys.stdout.write(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
