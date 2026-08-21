"""Determinism and losslessness, as reusable property checks.

Four properties, stated once and pointed at anything that can produce a graph
(``TASKS.md`` 0.6):

1. building the same input twice is byte-identical;
2. **shuffling the input records changes nothing** — the single most valuable
   determinism check, because it catches every accidental reliance on file
   order (`DESIGN.md` §4);
3. every input record is accounted for: it became a node, or a diagnostic
   explains why it did not. Nothing vanishes (`CLAUDE.md` 2);
4. the writer emits canonical JSON — sorted keys, compact separators,
   non-ASCII preserved, trailing newline — asserted on the writer's *output*
   rather than read off its call site.

They take plain callables and plain JSON, so each one can be watched failing
against a deliberately broken fake before the real pipeline exists, and then
pointed at the real pipeline unchanged.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from typing import Any

JsonValue = Any
GraphJson = dict[str, Any]


class PropertyFailed(AssertionError):
    """A determinism or losslessness property did not hold."""


def assert_repeatable(build: Callable[[], bytes], *, rounds: int = 3) -> None:
    """Property 1: same input, same bytes, every time."""
    first = build()
    for round_number in range(2, rounds + 1):
        again = build()
        if again != first:
            raise PropertyFailed(
                f"build #{round_number} differs from build #1: the same input "
                f"produced different bytes, so nothing downstream can diff, "
                f"cache, or gate on this graph (CLAUDE.md 4)"
            )


def _shuffles(records: Sequence[JsonValue], count: int) -> list[list[JsonValue]]:
    # A fixed seed: the shuffles are arbitrary but the test is not. A property
    # test that fails only on unlucky Tuesdays teaches nobody anything.
    generator = random.Random(20260821)
    orderings = []
    for _ in range(count):
        shuffled = list(records)
        generator.shuffle(shuffled)
        orderings.append(shuffled)
    return orderings


def assert_order_independent(
    records: Sequence[JsonValue],
    build: Callable[[Sequence[JsonValue]], GraphJson],
    *,
    rounds: int = 5,
) -> None:
    """Property 2: input line order is not significant (`SPEC.md` §5.2)."""
    expected = build(list(records))
    for ordering in _shuffles(records, rounds):
        if build(ordering) != expected:
            raise PropertyFailed(
                "reordering the input records changed the graph; input line "
                "order MUST NOT be significant (SPEC.md §5.2). Do not fix this "
                "by sorting the expectation (AGENT.md)"
            )


def assert_every_record_accounted_for(
    records: Sequence[JsonValue], graph: GraphJson
) -> None:
    """Property 3: a record becomes a node, or a diagnostic says why not."""
    kept = [node.get("raw", {}).get("source") for node in graph.get("nodes", ())]
    explained = [
        diagnostic.get("source") for diagnostic in graph.get("diagnostics", ())
    ]
    for position, record in enumerate(records, start=1):
        if record in kept or record in explained:
            continue
        raise PropertyFailed(
            f"input record {position} is neither a node's verbatim source nor "
            f"the source of any diagnostic: it was silently dropped. "
            f"'We did not understand it' is a reportable outcome; "
            f"'it vanished' is a bug (CLAUDE.md 2). Record: {record!r}"
        )


_UNSORTED = {"zeta": 1, "alpha": {"zulu": True, "alpha": None}, "mu": [3, 2, 1]}
_NON_ASCII = {"note": "ünïcödé — kept as text"}


def assert_canonical_json(dumps: Callable[[JsonValue], bytes]) -> None:
    """Property 4: the writer itself is canonical (`SPEC.md` §5.2)."""
    written = dumps(_UNSORTED).decode("utf-8")

    if written.index('"alpha"') > written.index('"zeta"'):
        raise PropertyFailed(
            "keys are not sorted: the writer must use sort_keys=True, or two "
            "runs that agree on content can still disagree on bytes"
        )
    if '"alpha": ' in written or ", " in written:
        raise PropertyFailed(
            'separators are not compact: expected (",", ":") with no spaces'
        )
    if not written.endswith("\n"):
        raise PropertyFailed("output does not end in a trailing newline")
    if written.count("\n") != 1:
        raise PropertyFailed("output is not a single line plus its newline")

    unicode_written = dumps(_NON_ASCII).decode("utf-8")
    if "\\u" in unicode_written:
        raise PropertyFailed(
            "non-ASCII was escaped: expected ensure_ascii=False so payload "
            "text survives as text"
        )

    # And it must still be JSON, not merely canonical-looking.
    if json.loads(written) != _UNSORTED:
        raise PropertyFailed("the writer's output does not round-trip as JSON")
