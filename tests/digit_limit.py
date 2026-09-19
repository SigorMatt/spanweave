"""The library's integer digit limit, as a test must read it.

`SPEC.md` §5.3. spanweave reads an integer literal of at most
`spanweave.jsoncodec.DIGIT_LIMIT` digits and refuses a longer one, and it
decides that by counting digits rather than by asking the interpreter. The
interpreter has a limit of its own -- `sys.get_int_max_str_digits()`, 4300 by
default, anything from `sys.int_info.str_digits_check_threshold` (640) upward,
or none at all -- and since batch S8 that setting changes nothing a graph
says. So every boundary a test draws is derived from the library's constant,
never from the interpreter's setting, and never written down as a number:
a test that wrote 4300 would stop testing the rule the day the constant moved.

`above_the_floor()` is the one number derived from the interpreter, and it is
derived from the one thing about it that is not a setting: the lowest limit
any interpreter may be configured with. A literal that long is one the library
reads and a minimally configured interpreter would refuse to convert, which is
exactly the range batch S8 made the library's business.
"""

from __future__ import annotations

import sys

from spanweave.jsoncodec import DIGIT_LIMIT

#: The lowest integer-string digit limit an interpreter can be configured with.
FLOOR = sys.int_info.str_digits_check_threshold


def inside(limit: int = DIGIT_LIMIT) -> str:
    """The longest integer string the library reads."""
    return "9" * limit


def past(limit: int = DIGIT_LIMIT) -> str:
    """The shortest integer string the library refuses to read."""
    return "9" * (limit + 1)


def above_the_floor() -> str:
    """An integer string the library reads and the lowest setting would refuse."""
    return "9" * (FLOOR + 1)
