"""Fenced code blocks, opened and closed as CommonMark has it -- one rule.

Three readers split a document into code and prose: `code_spans` and
`sha_citations` in `tests/test_doc_truth.py`, and `_code_spans` in
`tests/install_check.py`. Each once had its own fence test, and the two that
used `startswith("```")` read `TASKS.md`'s prose line opening with five
backticks (an inline span of a fence) as a fence, and so read the rest of
the file as code. This module is the rule they share. It is stdlib only, so
`make install-check`, which imports `tests.gates` the same way, can import
it too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Literal

#: A fence line: up to three spaces, a run of three or more backticks, and no
#: backtick after it. A line *opening* with backticks that has another one
#: later is an inline span, not a fence.
FENCE = re.compile(r" {0,3}(?P<run>`{3,})[^`]*$")

Kind = Literal["fence", "code", "prose"]


def fence_kinds(lines: Iterable[str]) -> Iterator[tuple[str, Kind]]:
    """Each line with what it is: a fence line, a line inside a fence, or prose.

    A fence opens on a `FENCE` line and closes only on a `FENCE` line whose
    run is at least as long as the opener's, so a five-backtick fence stays
    open across a three-backtick line inside it. A fence left open runs to
    the end of the document. `lines` may keep their line breaks.
    """
    opener = 0
    for line in lines:
        fence = FENCE.match(line)
        if fence and (not opener or len(fence.group("run")) >= opener):
            opener = 0 if opener else len(fence.group("run"))
            yield line, "fence"
        else:
            yield line, "code" if opener else "prose"
