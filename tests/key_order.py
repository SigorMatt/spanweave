"""Every JSON object's members reordered, and nothing else (decisions log D38).

RFC 8259 §4 calls an object an *unordered* collection of members, so two
inputs that differ only in the order an object's members are written in are
one input, and `CLAUDE.md` invariant 4 says one input builds one graph. This
module makes the second input out of the first, for the gate in
`tests/test_determinism.py` that holds it.

It works on the **text**, token by token, and never through `json.loads` and
`json.dumps`: a round trip would also respell numbers (`1.50`, `1e5`, `-0`),
string escapes (`\\u00e9`, `\\/`) and whitespace, and an input respelled is
a different input, not a reordered one. Here every scalar token keeps its
exact text; each member -- its key, its colon and its value, the whitespace
between them included -- moves whole; and the text between members, the
commas and the whitespace around them, stays where it was. A string is a
value: JSON written inside one is never touched.

An object that states one key twice is left in the order it was written, and
counted: which copy a parser keeps depends on that order (`json.loads` keeps
the last), so reordering it would make a different input, not a reordered
one. Its members' values are still reordered inside.

`records_reordered` does the same to records already parsed -- the protobuf
path's, which have no text of their own -- keeping each container's type, so
a record the reader unpacked from an export (`spanweave.read.Unpacked`, whose
mark is its type) is still one.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from spanweave import jsoncodec
from spanweave.read import _first_non_space, _scan_for_export_key

#: A permutation of `range(count)` for an object of `count` members, `count`
#: at least 2: the members' new order, as indices into their written order.
Order = Callable[[int], list[int]]

_SPACE = re.compile(r"[ \t\n\r]*")
_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"')
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")
#: RFC 8259's three, and the three more Python's parser reads.
_LITERAL = re.compile(r"true|false|null|NaN|Infinity|-Infinity")


class NotJson(ValueError):
    """The text is not one JSON value this module can tokenize."""


@dataclass
class Tally:
    """What a reordering met, summed over everything it is handed."""

    #: Every object, of any size.
    objects: int = 0
    #: Objects of at least two members, all keys distinct: each reordered.
    permuted: int = 0
    #: Objects that state a key twice: left as written.
    duplicated: int = 0
    #: The greatest depth a reordered object sat at; a top-level value is 1.
    deepest: int = 0
    #: Reordered objects at depth 2 or more: inside another object or array.
    nested: int = 0
    #: Reordered objects whose container is an array.
    in_arrays: int = 0

    def count(self, depth: int, in_array: bool) -> None:
        self.permuted += 1
        self.deepest = max(self.deepest, depth)
        self.nested += depth >= 2
        self.in_arrays += in_array


def reversal(count: int) -> list[int]:
    """The members in reverse: never their written order, for two or more."""
    return list(range(count - 1, -1, -1))


def shuffle(seed: int) -> Order:
    """A fixed-seed shuffle, redrawn until it is not the written order.

    Seeded, so the reordering is arbitrary and the test is not; redrawn, so
    every object of two or more members is moved, and an input whose only
    such object drew the identity cannot pass for one that was reordered.
    """
    generator = random.Random(seed)

    def order(count: int) -> list[int]:
        written = list(range(count))
        drawn = list(written)
        while drawn == written:
            generator.shuffle(drawn)
        return drawn

    return order


def reordered(text: str, order: Order, tally: Tally) -> str:
    """``text``, one JSON value with whitespace around it, members reordered."""
    start = _space(text, 0)
    rebuilt, end = _Permuter(text, order, tally).value(start, 1, False)
    if _space(text, end) != len(text):
        raise NotJson(f"text after the value, at {_space(text, end)}")
    return text[:start] + rebuilt + text[end:]


def input_reordered(data: bytes, order: Order, tally: Tally) -> tuple[bytes, list[str]]:
    """A trace file's bytes, every object of every record reordered; and what
    was fed unchanged, and why.

    Split as the reader splits it (`SPEC.md` §7), by its own head scan: a
    leading BOM is kept; an array, or a document whose first object states
    `resourceSpans`, is one value and is reordered whole; anything else is
    read line by line, an LF ending each, whatever `str.strip` removes kept
    around it. What this cannot reorder is kept as it is and named, for one of
    two reasons. Text the library's own parser refuses is not read: the reader
    reports it as `malformed_record`, its text the `source` (`SPEC.md` §3.7),
    so reordering that text would change what the input *is*, and the graph
    with it. Bytes that are not UTF-8 are another matter: the reader does read
    such a line, or such a document, with U+FFFD where each sequence would not
    decode, and its `undecodable_bytes` carries no source. This is kept as it
    is only because a permuter of text cannot tokenize what does not decode,
    so its objects would reach the build in their written order; the gate
    asserts that the inputs it feeds hold none (`tests/test_determinism.py`,
    the scoped review of 2026-10-18b, R-6). A blank line is kept as it is and
    not named: it is not a record.
    """
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    body = data[len(bom) :]
    first = _first_non_space(body)
    if first == "[" or (first == "{" and _scan_for_export_key(body)):
        try:
            whole = body.decode("utf-8")
        except UnicodeDecodeError:
            return data, ["the input: not UTF-8"]
        try:
            jsoncodec.loads(whole)
        except (ValueError, RecursionError) as failure:
            if first == "[":
                return data, [f"the array: {type(failure).__name__}"]
            # Not one document: the reader reads it line by line, as below.
        else:
            return bom + reordered(whole, order, tally).encode("utf-8"), []
    lines: list[bytes] = []
    unread: list[str] = []
    for number, line in enumerate(body.split(b"\n"), start=1):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            lines.append(line)
            unread.append(f"line {number}: not UTF-8")
            continue
        stated = text.strip()
        if not stated:
            lines.append(line)
            continue
        try:
            jsoncodec.loads(stated)
        except (ValueError, RecursionError) as failure:
            lines.append(line)
            unread.append(f"line {number}: {type(failure).__name__}")
            continue
        at = text.index(stated)
        rebuilt = reordered(stated, order, tally)
        lines.append((text[:at] + rebuilt + text[at + len(stated) :]).encode("utf-8"))
    return bom + b"\n".join(lines), unread


def records_reordered(value: Any, order: Order, tally: Tally) -> Any:
    """Parsed records, every object's keys reordered, each container's type kept."""
    return _value_reordered(value, order, tally, 1, False)


def _value_reordered(
    value: Any, order: Order, tally: Tally, depth: int, in_array: bool
) -> Any:
    if isinstance(value, list):
        return [_value_reordered(item, order, tally, depth + 1, True) for item in value]
    if not isinstance(value, dict):
        return value
    tally.objects += 1
    keys = list(value)
    if len(keys) >= 2:
        keys = [keys[index] for index in order(len(keys))]
        tally.count(depth, in_array)
    copy = type(value)()
    for key in keys:
        copy[key] = _value_reordered(value[key], order, tally, depth + 1, False)
    return copy


def _space(text: str, index: int) -> int:
    found = _SPACE.match(text, index)
    assert found is not None  # `*` matches the empty string
    return found.end()


class _Permuter:
    """One value's text, rebuilt with every object's members reordered."""

    def __init__(self, text: str, order: Order, tally: Tally) -> None:
        self.text = text
        self.order = order
        self.tally = tally

    def value(self, index: int, depth: int, in_array: bool) -> tuple[str, int]:
        """(the value at ``index``, rebuilt; the index just past it)"""
        text = self.text
        if text.startswith("{", index):
            return self.object(index, depth, in_array)
        if text.startswith("[", index):
            return self.array(index, depth)
        for token in (_STRING, _LITERAL, _NUMBER):
            found = token.match(text, index)
            if found is not None:
                return found.group(), found.end()
        raise NotJson(f"no JSON value at {index}")

    def object(self, index: int, depth: int, in_array: bool) -> tuple[str, int]:
        text = self.text
        self.tally.objects += 1
        at = _space(text, index + 1)
        if text.startswith("}", at):
            return text[index : at + 1], at + 1
        # `gaps[k]` is the text before member `k` -- the brace, or a comma and
        # its whitespace -- and the last is the text after the last member,
        # the closing brace included. Members move; gaps do not.
        gaps: list[str] = []
        members: list[str] = []
        keys: list[str] = []
        gap_from = index
        while True:
            key = _STRING.match(text, at)
            if key is None:
                raise NotJson(f"no member key at {at}")
            gaps.append(text[gap_from:at])
            colon = _space(text, key.end())
            if not text.startswith(":", colon):
                raise NotJson(f"no colon at {colon}")
            start = _space(text, colon + 1)
            rebuilt, end = self.value(start, depth + 1, False)
            members.append(text[at:start] + rebuilt)
            keys.append(json.loads(key.group()))
            gap_from = end
            after = _space(text, end)
            if text.startswith(",", after):
                at = _space(text, after + 1)
                continue
            if text.startswith("}", after):
                gaps.append(text[gap_from : after + 1])
                break
            raise NotJson(f"no comma or closing brace at {after}")
        if len(set(keys)) < len(keys):
            self.tally.duplicated += 1
        elif len(members) >= 2:
            members = [members[position] for position in self.order(len(members))]
            self.tally.count(depth, in_array)
        rebuilt_object = gaps[0] + "".join(
            member + gap for member, gap in zip(members, gaps[1:], strict=True)
        )
        return rebuilt_object, after + 1

    def array(self, index: int, depth: int) -> tuple[str, int]:
        text = self.text
        at = _space(text, index + 1)
        if text.startswith("]", at):
            return text[index : at + 1], at + 1
        parts = [text[index:at]]
        while True:
            rebuilt, end = self.value(at, depth + 1, True)
            parts.append(rebuilt)
            after = _space(text, end)
            if text.startswith(",", after):
                at = _space(text, after + 1)
                parts.append(text[end:at])
                continue
            if text.startswith("]", after):
                parts.append(text[end : after + 1])
                return "".join(parts), after + 1
            raise NotJson(f"no comma or closing bracket at {after}")
