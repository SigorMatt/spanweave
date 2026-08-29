"""The README's quickstart, parsed into something that can be run and compared.

`TASKS.md` 3.9: *"The README's Python and shell blocks are the script. If they
do not run as written, the README is wrong -- fix the README, not the test."*
They were wrong. Both blocks read `trace.jsonl`, a file no stranger has and
this repository does not contain, so the opening example of the project's front
door raised `FileNotFoundError` on the first line a reader would paste.

That is the `TASKS.md` 3.8 failure mode in its purest form. The blocks were
illustrative when written -- `trace.jsonl` standing in for *your trace here* --
and nothing ever ran them, so nobody found out that the illustration had become
the only instruction a stranger gets.

**What this module does.** It reads the quickstart as a transcript: shell lines
beginning `$ ` are commands, everything after one is that command's expected
stdout, and a Python block's expected stdout is the unlabelled fence that
follows it. Then a caller runs it -- against the source tree in `make check`,
and against the *installed wheel* in `make install-check` -- and compares.

**Why the output is compared and not merely the exit code.** A quickstart that
runs but prints something other than what it shows is still lying, and the
thing it shows here is load-bearing: the `inspect` transcript is where the
warrant vocabulary (`explicit` / `derived`), the `absent` payload state and the
diagnostic count are first put in front of a reader. If any of those changes,
the README must change in the same commit or this fails.

Nothing here executes anything. Parsing is separated from running so that the
same transcript drives two very different harnesses.
"""

from __future__ import annotations

import pathlib
import re
import shlex
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

#: The quickstart is everything above the Install heading: what a reader meets
#: before they have decided anything.
QUICKSTART_ENDS_AT = "\n## Install"

FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)


@dataclass(frozen=True)
class ShellStep:
    """One `$ ` line and the stdout the README shows underneath it."""

    command: str
    expected: str

    @property
    def argv(self) -> list[str]:
        return shlex.split(self.command)


@dataclass(frozen=True)
class PythonBlock:
    """A ```python fence and the unlabelled fence that follows it."""

    source: str
    expected: str


def quickstart_text(readme: str | None = None) -> str:
    text = readme if readme is not None else README.read_text(encoding="utf-8")
    return text[: text.index(QUICKSTART_ENDS_AT)]


def _fences(text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in FENCE.finditer(text)]


def _is_transcript(body: str) -> bool:
    return body.lstrip().startswith("$ ")


def shell_steps(readme: str | None = None) -> list[ShellStep]:
    """Every `$ ` command in the quickstart, with its shown output."""
    steps: list[ShellStep] = []
    for language, body in _fences(quickstart_text(readme)):
        if language or not _is_transcript(body):
            continue
        command: str | None = None
        output: list[str] = []
        for line in body.splitlines():
            if line.startswith("$ "):
                if command is not None:
                    steps.append(ShellStep(command, "\n".join(output).strip("\n")))
                command, output = line[2:], []
            elif command is not None:
                output.append(line)
        if command is not None:
            steps.append(ShellStep(command, "\n".join(output).strip("\n")))
    return steps


def python_blocks(readme: str | None = None) -> list[PythonBlock]:
    """Every ```python fence, paired with the output fence that follows it."""
    fences = _fences(quickstart_text(readme))
    blocks: list[PythonBlock] = []
    for index, (language, body) in enumerate(fences):
        if language != "python":
            continue
        expected = ""
        if index + 1 < len(fences):
            following_language, following_body = fences[index + 1]
            if not following_language and not _is_transcript(following_body):
                expected = following_body.strip("\n")
        blocks.append(PythonBlock(body, expected))
    return blocks


def normalize(text: str) -> str:
    """Trailing whitespace and the final newline are not part of the claim."""
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())
