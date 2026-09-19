"""Integers in JSON, read and written the same way on every interpreter.

CPython refuses to convert an integer *string* longer than
``sys.get_int_max_str_digits()``, in both directions: ``int("9" * 5000)``
raises, and so does ``str()`` of the integer it would have produced. That
limit is a per-process setting -- 4300 digits by default, anything from 640
upward, or none at all, moved by ``PYTHONINTMAXSTRDIGITS``,
``-X int_max_str_digits`` or ``sys.set_int_max_str_digits`` -- and every
``json.loads``, ``json.dumps``, ``int()`` and f-string that meets a long
integer asks it. Left to the interpreter, the same trace bytes therefore
built different graphs under different settings, which `CLAUDE.md` invariant
4 does not allow.

So the library owns the limit (`SPEC.md` §5.3): ``DIGIT_LIMIT`` below, applied
by **counting digits** before any conversion, and every conversion this
library performs on an integer that could be longer than the lowest possible
interpreter limit goes through a path that limit does not govern
(``decimal.Decimal``, which converts between text and integers by arithmetic
rather than through ``int``'s string conversion). The interpreter's setting is
**never** changed: it is process-wide, it may have been chosen deliberately by
the host, and a library that moved it on import would change every unrelated
line of code in that process.

This is the bottom of the stack: it imports nothing from the package but the
``JsonValue`` alias, and everything that reads or writes JSON imports it.
"""

from __future__ import annotations

import decimal
import json
from collections.abc import Callable, Mapping

from spanweave.model import JsonValue

#: The longest integer literal, in digits, the library reads. A longer one is
#: refused exactly as an unconvertible literal always was on a stock
#: interpreter: an unquoted one makes its line unreadable JSON, a quoted
#: timestamp is not read (`SPEC.md` §3.1), and an OTLP `intValue` is carried
#: as its decimal string (§7). 4300 is CPython's default limit, chosen so
#: that no graph a stock interpreter produced before this constant existed
#: changes -- but it is this library's number now, not the interpreter's.
DIGIT_LIMIT = 4300

#: An integer of at most this many digits converts under *any* interpreter
#: setting, because no setting other than "none" is lower than 640
#: (`sys.int_info.str_digits_check_threshold`). Below it the plain `int()` and
#: `str()` are used, which is the common case and the fast one.
_ALWAYS_CONVERTIBLE = 600

#: `bit_length()` below which an integer has at most `_ALWAYS_CONVERTIBLE`
#: digits: 2**1993 < 10**600.
_ALWAYS_CONVERTIBLE_BITS = 1993


def digit_count(literal: str) -> int:
    """How many digits an integer literal carries, its sign not counted."""
    return len(literal) - 1 if literal.startswith(("-", "+")) else len(literal)


def parse_integer(literal: str) -> int:
    """The integer a JSON integer literal writes, or ``ValueError``.

    Refused when it carries more than ``DIGIT_LIMIT`` digits -- counted, so
    the answer is the same under every interpreter setting. A literal inside
    the limit is converted through ``decimal.Decimal`` when it is long enough
    that ``int()`` might meet a lowered interpreter limit: ``Decimal`` parses
    text without that limit, and converting a ``Decimal`` with no fraction to
    ``int`` is exact arithmetic, not string conversion.
    """
    digits = digit_count(literal)
    if digits > DIGIT_LIMIT:
        raise ValueError(
            f"an integer literal of {digits} digits is longer than the "
            f"{DIGIT_LIMIT} digits spanweave reads (`SPEC.md` §5.3)"
        )
    if digits <= _ALWAYS_CONVERTIBLE:
        return int(literal)
    return int(decimal.Decimal(literal))


def integer_text(value: int) -> str:
    """``str(value)``, under every interpreter setting."""
    if value.bit_length() < _ALWAYS_CONVERTIBLE_BITS:
        return str(value)
    # `Decimal(int)` is exact whatever the context's precision, and rendering
    # a `Decimal` with a zero exponent writes its digits with no exponent.
    return str(decimal.Decimal(value))


def number_text(value: int | float) -> str:
    """``str(value)`` for a number, under every interpreter setting."""
    if isinstance(value, int) and not isinstance(value, bool):
        return integer_text(value)
    return str(value)


def python_text(value: object) -> str:
    """``str(value)`` for a parsed JSON value, under every interpreter setting.

    ``str`` is tried first, and on every setting that can render the integers
    ``value`` holds -- which includes the default, for every integer the
    library reads -- it is the answer. Where a lowered setting refuses one,
    the value is rendered as ``str`` would render it on a setting that did
    not: the same text, reached without asking the interpreter to convert the
    integer.
    """
    try:
        return str(value)
    except ValueError:
        if isinstance(value, str):
            raise
        return _repr_of(value)


def _repr_of(value: object) -> str:
    """``repr`` of a parsed JSON value, integers written whole."""
    if isinstance(value, bool) or value is None or isinstance(value, float | str):
        return repr(value)
    if isinstance(value, int):
        return integer_text(value)
    if isinstance(value, list):
        return "[" + ", ".join(_repr_of(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{_repr_of(key)}: {_repr_of(item)}" for key, item in value.items())
        return "{" + ", ".join(pairs) + "}"
    # Nothing the parser produces is anything else; a value that is still
    # meets `repr` and whatever it answers.
    return repr(value)


def loads(text: str | bytes, **options: JsonValue) -> JsonValue:
    """``json.loads``, with integers read by ``parse_integer``."""
    return json.loads(text, parse_int=parse_integer, **options)


def _is_long_integer(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value.bit_length() >= _ALWAYS_CONVERTIBLE_BITS
    )


def encode(value: JsonValue, dump: Callable[[JsonValue], str]) -> str:
    """``dump(value)``, with every integer written whole.

    ``dump`` is a ``json.dumps`` call with whatever arguments its caller
    states. It is tried as it is first, which is every value that holds no
    long integer and every value at all under a setting that can write the
    ones it holds. If it raises ``ValueError``, each integer too long for
    *some* setting is swapped for a placeholder string, ``dump`` runs again on
    the same structure -- so depth, key order and every other value are
    decided by the identical encoder -- and the placeholders are replaced by
    the integers' digits. A ``ValueError`` that was not about integers raises
    again from the second attempt, unchanged.
    """
    try:
        return dump(value)
    except ValueError:
        pass
    marker = _unused_marker(value)
    found: list[int] = []
    swapped = _swap_long_integers(value, marker, found)
    if not found:
        return dump(value)
    text = dump(swapped)
    # Each placeholder was written by the same encoder as a JSON string, and
    # `marker` occurs in no string of `value`, so the encoded placeholder
    # occurs in `text` only where a long integer stood.
    for index, number in enumerate(found):
        text = text.replace(
            json.dumps(f"{marker}{index}\x00", ensure_ascii=False),
            integer_text(number),
        )
    return text


def _strings_in(value: JsonValue) -> list[str]:
    """Every string in ``value``, keys included. Iterative, cycle-safe."""
    found: list[str] = []
    seen: set[int] = set()
    stack: list[JsonValue] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            found.append(current)
            continue
        if isinstance(current, Mapping):
            inside: list[JsonValue] = [*current, *current.values()]
        elif isinstance(current, list | tuple):
            inside = list(current)
        else:
            continue
        if id(current) in seen:
            continue
        seen.add(id(current))
        stack.extend(inside)
    return found


def _unused_marker(value: JsonValue) -> str:
    """A placeholder prefix no string in ``value`` contains. Deterministic."""
    strings = _strings_in(value)
    attempt = 0
    while True:
        marker = f"\x00spanweave-integer-{attempt}:"
        if not any(marker in text for text in strings):
            return marker
        attempt += 1


def _swap_long_integers(value: JsonValue, marker: str, found: list[int]) -> JsonValue:
    """A copy of ``value`` with each long integer replaced by a placeholder.

    Iterative, so that it meets no depth ceiling the encoder would not; and a
    container met twice is copied once, so a value that refers back to itself
    still does in the copy, and the encoder refuses it as it would have.
    """
    copies: dict[int, JsonValue] = {}

    def replacement(item: JsonValue) -> JsonValue:
        if _is_long_integer(item):
            found.append(item)
            return f"{marker}{len(found) - 1}\x00"
        if isinstance(item, Mapping | list | tuple):
            if id(item) not in copies:
                copies[id(item)] = {} if isinstance(item, Mapping) else []
                pending.append(item)
            return copies[id(item)]
        return item

    pending: list[JsonValue] = []
    root = replacement(value)
    while pending:
        original = pending.pop()
        copy = copies[id(original)]
        if isinstance(original, Mapping):
            for key, item in original.items():
                copy[key] = replacement(item)
        else:
            copy.extend(replacement(item) for item in original)
    return root
