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

import json

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


#: Where the doubling search gives up looking for a ceiling. A test that
#: steps *past* a ceiling is vacuous if there is no ceiling to step past, so
#: the search says so rather than running until the machine swaps: 2,000,000
#: is an order of magnitude past the deepest ceiling ever measured here
#: (CPython 3.14.6, lists, ~74,500) and small enough to build in under a
#: second.
SEARCH_CAP = 2_000_000


def deepest_accepted(attempt, cap=SEARCH_CAP):
    """The deepest nesting `attempt` survives, found by bisection.

    Measured, never hard-coded: the ceiling belongs to the interpreter's C
    recursion budget, not to this library, and it differs between builds and
    between embedders (`SPEC.md` §7).

    Fails rather than returns if nothing under `cap` is refused: every caller
    here uses the answer to build something that must be *too deep*, and a
    search that quietly returned its own cap would hand each of them a depth
    the interpreter is happy with.
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
        assert high <= cap, (
            f"nesting {low} deep is accepted here and the search stops at "
            f"{cap}: this platform has no recursion ceiling a test can reach, "
            f"so anything asserted about a depth past one would pass vacuously"
        )
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

#: How far *below* the writer's ceiling a probe that answers the same question
#: from a deeper call path is allowed to sit. Not `MEASUREMENT_NOISE`: that one
#: is the distance between two processes, this one is the distance between two
#: stack positions in the *same* process. On CPython 3.11 the C encoder's
#: recursion counts against the Python recursion limit, so a probe called from
#: a few frames further in gives out a few levels sooner -- measured in CI on
#: 3.11, `annotate` accepted 946 where `dumps` wrote 948. Below the writer is
#: the safe direction; arbitrarily far below it is a probe quietly refusing
#: values the graph file would have carried, which is why the distance is
#: bounded rather than ignored.
CALL_PATH_SLACK = 64

_too_deep_for_nested_lists = []


def too_deep_for_nested_lists():
    """A nesting of **lists** that `json` will not take in this process.

    Deeper than both ceilings measured here -- `json.dumps` of a nested list
    and `json.loads` of one written out as text -- plus `MEASUREMENT_NOISE`,
    so a test that needs "too deep to render" gets a depth that is too deep
    whichever of the two the code under test reaches, on whatever interpreter
    is running. A constant cannot do this job: the same 100,000 that is 100x
    the ceiling on CPython 3.11 (991) is *under* it on 3.14.6 (74,481 for
    lists), where the check is against the real C stack pointer and a runner
    with a larger stack moves it again.

    Measured once per process, because the four call sites ask one question
    and bisecting it four times would answer it four times over.
    """
    if not _too_deep_for_nested_lists:
        encoder = deepest_accepted(lambda depth: json.dumps(nested_lists(depth)))
        parser = deepest_accepted(lambda depth: json.loads(lists_text(depth)))
        _too_deep_for_nested_lists.append(max(encoder, parser) + MEASUREMENT_NOISE)
    return _too_deep_for_nested_lists[0]
