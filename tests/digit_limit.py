"""The interpreter's integer-string digit limit, as a test must read it.

CPython refuses to convert an integer *string* longer than
`sys.get_int_max_str_digits()`. That limit is a runtime setting rather than a
property of the language — 4300 digits by default, anything from
`sys.int_info.str_digits_check_threshold` (640) upward, or disabled entirely
with `0`, via `PYTHONINTMAXSTRDIGITS`, `-X int_max_str_digits` or
`sys.set_int_max_str_digits`. `SPEC.md` §5.3 states what that means for the
library: the limit is an input to the graph, and the library reads it rather
than setting it.

It follows that a test which hard-codes 4300 as *the* limit — or 5000 digits
as *past* it — is a test about one configuration wearing the name of a rule.
Batch R1 wrote seven such tests and every one of them goes red on a legally
configured interpreter: under `PYTHONINTMAXSTRDIGITS=0` a 5000-digit literal
is one the interpreter reads, so five tests asserting it is refused fail,
and under `PYTHONINTMAXSTRDIGITS=640` two more raise `ValueError` inside the
test body from their own `int("9" * 4300)`. Batch R14 derives both sides of
every such boundary from here instead.

`enforced()` is the second half of that. Under a *disabled* limit there is no
boundary at all, and a test that skipped there would be absent in exactly the
configuration where the behaviour it pins does not happen — `CONTRIBUTING.md`'s
bar in its purest form, a test green where it cannot catch anything. So a
limit is installed for the duration and the ambient one restored afterwards:
every configuration exercises the same boundary, and the boundary is still the
interpreter's line rather than a number this suite invented.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

#: What `sys.get_int_max_str_digits()` returns when there is no limit at all.
DISABLED = 0


@contextmanager
def enforced() -> Iterator[int]:
    """Yield a digit limit that is genuinely in force, restoring the ambient one.

    Yields the interpreter's own limit where it has one, and the lowest limit
    the interpreter will accept where it does not.
    """
    ambient = sys.get_int_max_str_digits()
    if ambient != DISABLED:
        yield ambient
        return
    floor = sys.int_info.str_digits_check_threshold
    sys.set_int_max_str_digits(floor)
    try:
        yield floor
    finally:
        sys.set_int_max_str_digits(ambient)


@contextmanager
def disabled() -> Iterator[None]:
    """Run with no digit limit at all, restoring the ambient one."""
    ambient = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(DISABLED)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(ambient)


def inside(limit: int) -> str:
    """The longest integer string this interpreter will convert."""
    return "9" * limit


def past(limit: int) -> str:
    """The shortest integer string this interpreter refuses to convert."""
    return "9" * (limit + 1)
