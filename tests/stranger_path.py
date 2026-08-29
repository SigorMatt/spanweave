"""`make stranger` — walk the path a stranger walks, and time it (`TASKS.md` 3.9).

`ROADMAP.md`'s Phase 3 exit says *"a stranger can build a graph from their own
trace in ~60 seconds."* That is a claim about a human's first minute, and the
only honest way to hold it is to walk the path and look at a clock. This does
that, from a directory that is not this repository, with nothing preinstalled.

**What it walks, and why it is the checkout path.** `TASKS.md` 3.9 says *"from
a clean venv, install the wheel 3.6 built"*. Since 3.8 that is no longer the
only path and no longer the first one a stranger meets: there is no
`pip install spanweave` until 3.10, so what a stranger actually has is a clone.
So this walks the README's **From a checkout** block -- and it reads those
steps out of the README rather than restating them, because a timing harness
that walks its own idea of the path measures nothing about the document.

**The one substitution, named rather than hidden.** `git clone` from GitHub is
network zone 1's neighbour and this harness has no network, so the clone source
is swapped for this repository on disk. Everything else -- the fresh venv, the
`pip install .`, the console script, the fixture path -- is untouched. The
substitution makes the measurement an **underestimate**: a real clone over a
network costs seconds this does not count, and the report says so rather than
quietly banking the difference.

**No assertion about the duration.** A wall-clock threshold in an automated
check is a flake that gets tuned until it means nothing. This prints; a human
reads. What *is* asserted is that every step succeeds and that the steps are
the ones the README documents -- both of which fail loudly.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

REPO = pathlib.Path(__file__).resolve().parent.parent

#: `ROADMAP.md`'s Phase 3 exit criterion, in seconds. Reported against, never
#: asserted on.
CLAIMED_SECONDS = 60


@dataclass
class Timing:
    steps: list[tuple[str, float]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def record(self, label: str, seconds: float) -> None:
        self.steps.append((label, seconds))
        print(f"  {seconds:6.2f}s  {label}")

    @property
    def total(self) -> float:
        return sum(seconds for _, seconds in self.steps)


def _checkout_steps() -> list[str]:
    """The README's `From a checkout` block, read rather than restated."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    start = readme.index("From a checkout:")
    block = re.search(r"```\n(.*?)```", readme[start:], re.S)
    if block is None:
        raise SystemExit("README's `From a checkout:` block has no fenced commands")
    return [line[2:] for line in block.group(1).splitlines() if line.startswith("$ ")]


def _first_quickstart_command() -> str:
    from tests.readme_quickstart import shell_steps

    steps = shell_steps()
    if not steps:
        raise SystemExit("the README's quickstart contains no shell command")
    return steps[0].command


def _run(argv: list[str], *, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def _timed(
    timing: Timing, label: str, argv: list[str], *, cwd: pathlib.Path
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    result = _run(argv, cwd=cwd)
    timing.record(label, time.monotonic() - started)
    if result.returncode != 0:
        timing.failures.append(f"{label}: exit {result.returncode}\n{result.stdout}")
    return result


def walk(sandbox: pathlib.Path, *, show_output: bool = True) -> Timing:
    timing = Timing()
    documented = _checkout_steps()
    print(f"  README's checkout path: {documented}")
    if len(documented) != 3 or not documented[0].startswith("git clone"):
        raise SystemExit(
            f"the README's checkout path is no longer clone/cd/install: "
            f"{documented}. Update this harness deliberately, in the same "
            f"change, rather than letting it time a path nobody documents."
        )
    install_command = shlex.split(documented[2])
    if install_command[:2] != ["pip", "install"]:
        raise SystemExit(f"expected `pip install ...`, README says {documented[2]!r}")

    clone = sandbox / "spanweave"
    # Step 1, substituted: the clone source is this repo on disk, not GitHub.
    _timed(
        timing,
        f"git clone  (local stand-in for `{documented[0]}`)",
        ["git", "clone", "--quiet", str(REPO), str(clone)],
        cwd=sandbox,
    )
    if timing.failures:
        return timing

    venv = sandbox / "venv"
    _timed(
        timing,
        "python3 -m venv  (not in the README; a stranger needs one)",
        [sys.executable, "-m", "venv", str(venv)],
        cwd=sandbox,
    )
    if timing.failures:
        return timing

    pip = venv / "bin" / "pip"
    _timed(
        timing,
        f"$ {documented[2]}",
        [str(pip), "install", "--quiet", *install_command[2:]],
        cwd=clone,
    )
    if timing.failures:
        return timing

    command = _first_quickstart_command()
    result = _timed(
        timing,
        f"$ {command}",
        [str(venv / "bin" / shlex.split(command)[0]), *shlex.split(command)[1:]],
        cwd=clone,
    )
    if show_output and result.returncode == 0:
        print(
            "\n  --- what the stranger sees first -------------------------------------"
        )
        for line in result.stdout.splitlines():
            print(f"  | {line}")
        print(
            "  ----------------------------------"
            "-------------------------------------\n"
        )
    return timing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeat", type=int, default=1, help="walk the path N times (default 1)"
    )
    parser.add_argument("--quiet", action="store_true", help="omit the transcript")
    args = parser.parse_args(argv)

    totals: list[float] = []
    failures: list[str] = []
    for run in range(args.repeat):
        print(f"\nrun {run + 1} of {args.repeat}")
        scratch = tempfile.mkdtemp(prefix="spanweave-stranger-")
        try:
            timing = walk(pathlib.Path(scratch), show_output=not args.quiet)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        totals.append(timing.total)
        failures.extend(timing.failures)
        print(f"  {timing.total:6.2f}s  TOTAL")

    print()
    if failures:
        for failure in failures:
            print(f"FAILED {failure}")
        print(f"\nstranger path FAILED: {len(failures)} step(s)")
        return 1

    best, worst = min(totals), max(totals)
    print(
        f"stranger path green: {len(totals)} walk(s), "
        f"{best:.2f}s best, {worst:.2f}s worst"
    )
    print(
        f"  ROADMAP.md's exit criterion is ~{CLAIMED_SECONDS}s. This number "
        f"EXCLUDES a real network clone\n  and excludes the human -- reading, "
        f"typing, and deciding what to point it at."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
