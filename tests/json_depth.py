"""Where `json` gives out, measured rather than assumed.

Shared by `tests/test_serialize.py` (the write side) and `tests/test_read.py`
(the reader's digest), because both ask the same question of the interpreter
and the answer must be one measurement rather than two. Three consecutive
attempts to state this quantity as a fact about the library -- A6, the run-2
review, R6 -- each measured one interpreter and wrote a universal, and R6's
pin was green on CPython 3.14 only because it nested **lists** where a graph
document nests **dicts** (run-3 review F1). So the shape is named in every
helper here, and nothing in this module asserts a direction.
"""

from __future__ import annotations

import spanweave


def nested_lists(depth):
    """A list nested `depth` deep, built without recursing to build it."""
    value = []
    for _ in range(depth):
        value = [value]
    return value


def nested_dicts(depth):
    """An object nested `depth` deep -- the shape a graph document has.

    Every level of a graph document is an object: `nodes`, the node, `raw`,
    `source`, `attributes`. Measuring lists instead is how the limit pin came
    to be green on an interpreter where the sentence it pinned is false
    (run-3 review F1), so the shape is named in the helper rather than left to
    whoever edits the test next.
    """
    value = {}
    for _ in range(depth):
        value = {"a": value}
    return value


def lists_text(depth):
    return "[" * depth + "1" + "]" * depth


def dicts_text(depth):
    """`depth` nested JSON objects as *text*, never through `json.dumps`.

    Built by concatenation on purpose: the encoder has a ceiling of its own
    and that ceiling is what is being measured, so a harness that reached the
    input through `json.dumps` would cap the measurement with itself.
    """
    return '{"a":' * depth + "1" + "}" * depth


def deepest_accepted(attempt):
    """The deepest nesting `attempt` survives, found by bisection.

    Measured, never hard-coded: the ceiling belongs to the interpreter's C
    recursion budget, not to this library, and it differs between builds and
    between embedders (`SPEC.md` §7).
    """

    def survives(depth):
        try:
            attempt(depth)
        # The encoder reports depth as this library's own refusal, the parser
        # reports it as the interpreter's `RecursionError`. Same fact.
        except (RecursionError, spanweave.GraphNotSerializableError):
            return False
        return True

    low, high = 1, 2
    while survives(high):
        low, high = high, high * 2
        assert high < 10**7, "no depth this interpreter refuses"
    while high - low > 1:
        middle = (low + high) // 2
        if survives(middle):
            low = middle
        else:
            high = middle
    return low


#: How far past a ceiling measured in *this* process a test steps before
#: treating it as passed. Bisection makes each ceiling exact in the measuring
#: process, so the margin is not for that process: CPython 3.14 tests the
#: actual C stack pointer, so the same measurement in a fresh process lands
#: tens of levels away (measured 2026-09-11: ~25 levels between runs, ~170
#: when the environment block grew), and a margin below that would make the
#: test a report on the machine it ran on.
MEASUREMENT_NOISE = 256
