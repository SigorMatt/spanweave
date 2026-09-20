"""The library's own digit limit, and the paths that keep it the library's.

Batch S8, `SPEC.md` §5.3. `tests/test_determinism.py` measures the claim end
to end, across interpreter settings in separate processes. These pin the
pieces in-process, where the interpreter's own limit is whatever this run was
started with -- so nothing here converts a long integer through `int()` or
`str()`, and the placeholder path of `encode` is driven by a `dump` that
refuses long integers the way a lowered interpreter setting would.
"""

import decimal
import json

import pytest

from spanweave import jsoncodec
from tests import digit_limit


def _whole(literal):
    """The integer a literal writes, without asking the interpreter's limit."""
    return int(decimal.Decimal(literal))


def _refusing_dump(value):
    """`json.dumps`, as an interpreter set to its lowest limit would run it."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif (
            isinstance(current, int)
            and not isinstance(current, bool)
            and current.bit_length() > 2000
        ):
            raise ValueError("Exceeds the limit for integer string conversion")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_the_limit_is_4300_digits():
    # The number `SPEC.md` §5.3 states. Written down exactly once, here, so
    # that moving it is a visible change to the spec rather than a quiet one.
    assert jsoncodec.DIGIT_LIMIT == 4300


def test_a_literal_at_the_limit_is_read_and_one_past_it_is_refused():
    assert jsoncodec.parse_integer(digit_limit.inside()) == _whole(digit_limit.inside())
    with pytest.raises(ValueError, match="spanweave reads"):
        jsoncodec.parse_integer(digit_limit.past())


def test_the_sign_is_not_a_digit():
    negative = "-" + digit_limit.inside()
    assert jsoncodec.parse_integer(negative) == -_whole(digit_limit.inside())
    with pytest.raises(ValueError):
        jsoncodec.parse_integer("-" + digit_limit.past())


def test_the_parser_applies_the_limit_to_an_unquoted_literal():
    assert jsoncodec.loads(f"[{digit_limit.inside()}]") == [
        _whole(digit_limit.inside())
    ]
    with pytest.raises(ValueError):
        jsoncodec.loads(f"[{digit_limit.past()}]")


@pytest.mark.parametrize("literal", ["0", "-1", "1700000000", "1234567890" * 60])
def test_integer_text_is_str(literal):
    number = jsoncodec.parse_integer(literal)
    assert jsoncodec.integer_text(number) == literal == str(number)


def test_integer_text_writes_a_long_integer_whole():
    for literal in (digit_limit.inside(), "-" + digit_limit.inside()):
        assert jsoncodec.integer_text(_whole(literal)) == literal


def test_number_text_leaves_a_float_to_str():
    assert jsoncodec.number_text(1.5) == "1.5"
    assert jsoncodec.number_text(True) == "True"


def test_encode_writes_the_long_integers_a_refusing_encoder_would_not():
    long = digit_limit.above_the_floor()
    value = {"b": [_whole(long), "x", 1], "a": {"n": -_whole(long)}, "c": 2.5}
    assert jsoncodec.encode(value, _refusing_dump) == (
        f'{{"a":{{"n":-{long}}},"b":[{long},"x",1],"c":2.5}}'
    )


def test_encode_is_the_encoder_itself_when_nothing_is_refused():
    value = {"b": [1, "x"], "a": None}
    assert jsoncodec.encode(value, _refusing_dump) == _refusing_dump(value)


def test_a_string_that_looks_like_a_placeholder_stays_a_string():
    # The placeholder prefix is chosen so that no string in the value contains
    # it; a value that holds the first candidate gets the second.
    long = digit_limit.above_the_floor()
    impostor = "\x00spanweave-integer-0:0\x00"
    value = [impostor, _whole(long)]
    assert jsoncodec.encode(value, _refusing_dump) == (
        f"[{json.dumps(impostor)},{long}]"
    )


def test_a_container_met_twice_is_written_twice():
    long = digit_limit.above_the_floor()
    shared = [_whole(long)]
    assert jsoncodec.encode({"a": shared, "b": shared}, _refusing_dump) == (
        f'{{"a":[{long}],"b":[{long}]}}'
    )


def test_a_value_that_refers_back_to_itself_is_still_refused():
    looped: list[object] = [_whole(digit_limit.above_the_floor())]
    looped.append(looped)
    # The copy keeps the loop, so the encoder refuses it for the same reason
    # it would have refused the original.
    with pytest.raises(ValueError, match=r"[Cc]ircular"):
        jsoncodec.encode(looped, json.dumps)


def test_a_refusal_that_is_not_about_integers_is_raised_unchanged():
    def strict(value):
        return json.dumps(value, allow_nan=False)

    with pytest.raises(ValueError, match="JSON compliant"):
        jsoncodec.encode([float("nan"), 1], strict)


def test_python_text_is_str_for_everything_str_can_render():
    value = {"a": [1, 2.5, None, True, "x"], "b": {"c": "d"}}
    assert jsoncodec.python_text(value) == str(value)
    assert jsoncodec.python_text("text") == "text"


def test_the_fallback_rendering_is_the_one_str_gives():
    # The fallback runs only where the interpreter refuses to render an
    # integer, which this process may not; its output is pinned against the
    # text `str` produces for the same shape with a short integer in place.
    long = digit_limit.above_the_floor()
    value = {"a": [_whole(long), 2.5, None, True, "x'y"], "b": {"c": "d"}}
    short = {"a": [7, 2.5, None, True, "x'y"], "b": {"c": "d"}}
    assert jsoncodec._repr_of(value) == str(short).replace("7", long, 1)
