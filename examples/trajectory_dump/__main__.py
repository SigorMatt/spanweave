"""``python -m examples.trajectory_dump <trace> [<trace> ...]``.

Prints an ordered call/result transcript for each trace it is given. Reads
files; opens no socket (`ENVIRONMENT.md`: examples consume committed fixtures,
so a stranger can reproduce every line here).

``--format json`` is the machine form. ``--states`` prints the P2 record — the
payload-state decision table, which pairs of states this consumer actually
separates, and which states the traces it was given ever contained.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from examples.trajectory_dump import (
    CONTENT,
    ORDERING_CODES,
    STATE_RENDERINGS,
    Transcript,
    Unbuildable,
    coverage,
    distinctions,
    transcribe_all,
)

#: Content is elided in the text form at this width. The *consumer* is doing
#: the eliding, which is not what `PayloadState.TRUNCATED` means -- that is the
#: instrumentor saying it cut a value short. The marker names which one
#: happened, because a transcript that spelled them alike would report a
#: display setting as a fact about the run. `--format json` elides nothing.
WIDTH = 96


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.trajectory_dump",
        description="Flatten spanweave graphs into ordered call/result transcripts.",
    )
    parser.add_argument(
        "traces",
        nargs="+",
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
        help="text is for reading; json is for an eval harness (default: text)",
    )
    parser.add_argument(
        "--states",
        action="store_true",
        help="print the payload-state record instead of the transcripts",
    )
    return parser


def _content(value: object) -> str:
    text = json.dumps(value, sort_keys=True)
    if len(text) <= WIDTH:
        return text
    return f"{text[:WIDTH]}… (+{len(text) - WIDTH} chars, elided by this dumper)"


def report(transcript: Transcript) -> str:
    """The human transcript. Same input, same bytes -- nothing reads a clock."""
    lines = [
        f"trace {transcript.trace_id} — {len(transcript.steps)} step(s)"
        f"  [{transcript.source}]",
        f"  dialect-local: adapter={transcript.adapter}",
    ]
    # Before the steps, not after them. Every one of these qualifies what
    # follows -- and one of them says the order itself is not the run's, which
    # a reader who has already read the transcript has read too late.
    if transcript.qualifiers:
        lines.append(
            f"  qualifies this whole transcript: {', '.join(transcript.qualifiers)}"
        )
    for limit in transcript.limits:
        lines.append(f"  limit: {limit}")
    lines.append("")
    for step in transcript.steps:
        indent = "  " * step.depth
        elapsed = "     ?" if step.duration is None else f"{step.duration:>6.3f}s"
        lines.append(
            f"{step.index:>3}  {indent}{step.label}"
            f"   [{step.node_id}] {step.status} {elapsed}"
        )
        if step.status_note:
            lines.append(f"       {indent}note: {step.status_note}")
        for line in step.lines:
            body = (
                _content(line.content)
                if line.availability == CONTENT
                else f"({line.reason})"
            )
            mark = "" if line.complete else "  ← cut short by the instrumentor"
            lines.append(f"       {indent}{line.side:<3} {line.state:<9} {body}{mark}")
        if step.fulfilled_by:
            lines.append(
                f"       {indent}→ fulfilled by {', '.join(step.fulfilled_by)}"
            )
        if step.fulfils:
            lines.append(f"       {indent}← fulfils {', '.join(step.fulfils)}")
        if step.feeds:
            lines.append(f"       {indent}⇒ feeds {', '.join(step.feeds)} (declared)")
        for target in step.links_to:
            outside = " — not in this trace" if target in step.links_outside else ""
            lines.append(f"       {indent}⇢ links to {target}{outside}")
        for tool in step.unfulfilled:
            lines.append(f"       {indent}! asked for {tool} — nothing ran")
        if step.unrequested:
            lines.append(f"       {indent}! no call in this trace asked for this")
        for note in step.notes:
            marker = "!" if note in ORDERING_CODES else "-"
            lines.append(f"       {indent}{marker} {note}")
        local = f"name={step.name!r}"
        if step.reported_kind is not None:
            local += f", reported_kind={step.reported_kind!r}"
        lines.append(f"       {indent}dialect-local: {local}")
        lines.append("")

    return "\n".join(lines)


def _refusal(refused: Unbuildable) -> str:
    return (
        f"{refused.source}: not transcribed — "
        f"{refused.error} [{refused.code}] {refused.message}\n"
    )


def states_report() -> str:
    """The P2 record: the table, and what it separates."""
    lines = ["payload state → what the transcript says:", ""]
    width = max(len(str(state)) for state in STATE_RENDERINGS)
    for state, rendering in sorted(STATE_RENDERINGS.items(), key=lambda kv: str(kv[0])):
        cut = "" if rendering.complete else "  (complete=False)"
        lines.append(
            f"  {state!s:<{width}}  {rendering.availability:<11}"
            f"  {rendering.reason}{cut}"
        )
    lines += [
        "",
        "pairs of states, and what separates them here:",
        "  verdict  = they put a reader on different branches",
        "  wording  = only the printed explanation differs",
        "",
    ]
    for row in distinctions():
        first, second = row["states"]
        lines.append(
            f"  {first:<9} vs {second:<9}  {row['kind']:<8}"
            f"  ({', '.join(row['separated_by'])})"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    results = list(transcribe_all(args.traces, adapter=args.adapter))

    if args.states:
        payload = {"table": states_report(), "coverage": coverage(results)}
        if args.format == "json":
            sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(states_report())
            sys.stdout.write("\nwhat these traces contained:\n")
            sys.stdout.write(
                json.dumps(coverage(results)["states_seen"], indent=2, sort_keys=True)
                + "\n"
            )
        return 0

    if args.format == "json":
        sys.stdout.write(
            json.dumps(
                [
                    result.as_dict()
                    if isinstance(result, Transcript)
                    else {"unbuildable": result.as_dict()}
                    for result in results
                ],
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0

    for result in results:
        if isinstance(result, Unbuildable):
            sys.stdout.write(_refusal(result))
        else:
            sys.stdout.write(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
