"""Fenced code blocks, opened and closed as CommonMark has it -- one rule.

Every reader here that finds a fence in a document reads it through this
module: `fence_kinds` labels each line, and `fenced_blocks` gives each
block's info string and body. Each reader once had its own fence test, and
the two that used `startswith("```")` read `TASKS.md`'s prose line opening
with five backticks (an inline span of a fence) as a fence, and so read the
rest of the file as code; the others closed a fence on the first three
backticks, whatever opened it.

The rule is CommonMark 0.31's for a fence at the top level of a document. A
fence opens on up to three spaces of indent and a run of three or more
backticks or three or more tildes; a backtick run's info string may hold no
backtick. It closes on a line with up to three spaces of indent, a run of
the same character at least as long as the opener's, and nothing after it
but spaces or tabs: a closing fence carries no info string.

**Not modelled, stated rather than silently carried:** containers. A fence
inside a list item or a blockquote is read as if it stood at the top level,
so a list item's indent counts against the three spaces, and a blockquote's
`>` makes the line prose. A body is its lines verbatim; the opener's own
indent is not removed from them, as CommonMark would.

It is stdlib only, so `make install-check`, which imports `tests.gates` the
same way, can import it too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal

#: A fence line: up to three spaces, then a run of three or more backticks
#: with no backtick after it, or a run of three or more tildes. A line
#: *opening* with backticks that has another one later is an inline span, not
#: a fence. `info` is the rest of the line, its line break excluded.
FENCE = re.compile(r" {0,3}(?P<run>`{3,}(?=[^`]*$)|~{3,})(?P<info>.*)$")

Kind = Literal["fence", "code", "prose"]


def _closes(run: str, info: str, opener: str) -> bool:
    """Whether a fence line with this run and info string closes `opener`."""
    return run[0] == opener[0] and len(run) >= len(opener) and not info.strip(" \t\r")


def fence_kinds(lines: Iterable[str]) -> Iterator[tuple[str, Kind]]:
    """Each line with what it is: a fence line, a line inside a fence, or prose.

    A fence opens on a `FENCE` line and closes only as the module docstring
    says, so a five-backtick fence stays open across a three-backtick line
    inside it, and a tilde fence across a backtick one. A fence left open
    runs to the end of the document. `lines` may keep their line breaks.
    """
    opener = ""
    for line in lines:
        fence = FENCE.match(line)
        if not opener:
            if fence:
                opener = fence.group("run")
                yield line, "fence"
            else:
                yield line, "prose"
        elif fence and _closes(fence.group("run"), fence.group("info"), opener):
            opener = ""
            yield line, "fence"
        else:
            yield line, "code"


@dataclass(frozen=True, slots=True)
class FencedBlock:
    """One fenced block: its info string, stripped, and its body.

    The body is the lines between the fences with their line breaks, so a
    block holding one line `x` has the body `"x\\n"`.
    """

    info: str
    body: str


def fenced_blocks(text: str) -> list[FencedBlock]:
    """Every fenced block in `text`, in order, by `fence_kinds`' rule.

    A fence left open is a block to the end of `text`, as CommonMark has it.
    """
    blocks: list[FencedBlock] = []
    info: str | None = None
    body: list[str] = []
    for line, kind in fence_kinds(text.splitlines(keepends=True)):
        if kind == "code":
            body.append(line)
        elif kind == "fence" and info is None:
            fence = FENCE.match(line)
            assert fence is not None
            info, body = fence.group("info").strip(), []
        elif kind == "fence":
            assert info is not None
            blocks.append(FencedBlock(info, "".join(body)))
            info = None
    if info is not None:
        blocks.append(FencedBlock(info, "".join(body)))
    return blocks
