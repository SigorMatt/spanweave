"""Reading a trace file into JSON records.

The bottom layer: bytes in, ``JsonValue`` records out, plus the diagnostics
produced along the way (``DESIGN.md`` §2). It knows two container formats and
no dialects -- what the records *mean* is the adapter's problem, one layer up.

Two things this layer must get right:

* **It never raises on malformed input.** A trace is untrusted, frequently
  truncated, and often has one bad line in the middle (`SECURITY.md`). A bad
  line becomes a ``malformed_record`` diagnostic carrying its text, and the
  read continues. The library that gives up on line 4,000 of 10,000 is worse
  than useless in a pipeline. "Malformed" includes *nested deeper than the
  parser will recurse*, which ``json`` reports as a ``RecursionError`` rather
  than a ``ValueError`` -- a different exception for the same fact, and one
  that escaped this guard until ``SPEC.md`` §7 said so out loud.
* **It is tolerant about the wrapping, never about the content.** A UTF-8 BOM
  at the head of the stream is skipped and LF, CRLF and CR-only line endings
  are each one terminator (``SPEC.md`` §7) -- both are facts about how a file
  was written, not about what it says. Neither tolerance reaches a record:
  those same bytes anywhere else are content and are passed through verbatim.
* **It is an iterator.** Nothing here requires the whole input as a
  precondition, which is the entire premium paid toward a possible future
  tail mode (`DESIGN.md` §6). The JSON-array form is the exception the format
  itself forces: an array cannot be known complete until its closing bracket.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from collections.abc import Iterator

from spanweave import diagnostics as codes
from spanweave.diagnostics import DiagnosticCollector
from spanweave.model import JsonValue

#: A path, a path-like, ``"-"`` for stdin, or the bytes themselves.
Source = bytes | str | os.PathLike[str]

STDIN = "-"


class RecordStream:
    """Lazily yields the records of one trace input.

    ``diagnostics`` and ``digest`` are complete once iteration has finished;
    reading them earlier gives what is known so far. That is the honest
    consequence of streaming, and the builder consumes the stream fully before
    it asks.
    """

    def __init__(self, name: str, chunks: Iterator[bytes]) -> None:
        self._name = name
        self._chunks = chunks
        self._collector = DiagnosticCollector()
        self._hash = hashlib.sha256()
        self._consumed = False

    @property
    def name(self) -> str:
        """Where this came from, for messages. Never put in the output."""
        return self._name

    @property
    def diagnostics(self) -> DiagnosticCollector:
        return self._collector

    @property
    def digest(self) -> str | None:
        """sha256 of the input bytes, once they have all been read."""
        return self._hash.hexdigest() if self._consumed else None

    def __iter__(self) -> Iterator[JsonValue]:
        chunks = self._hashed(self._chunks)

        # Decide the container format from the first non-whitespace byte,
        # pulling only as far as it takes to see one -- after skipping a
        # leading BOM, which is an encoding artifact and not a byte of the
        # first record (§7).
        head = b""
        is_array = False
        settled = False
        for chunk in chunks:
            head += chunk
            if not settled:
                if head.startswith(_BOM):
                    head = head[len(_BOM) :]
                elif _BOM.startswith(head):
                    # Still ambiguous: every byte so far agrees with a BOM.
                    # A chunk boundary inside those three bytes must not
                    # decide the question early.
                    continue
                settled = True
            verdict = _first_non_space(head)
            if verdict is not None:
                is_array = verdict == "["
                break

        if is_array:
            # The one place laziness is impossible: an array is not a record
            # until its closing bracket arrives. The format forces this, not
            # the design.
            yield from self._read_array(b"".join([head, *chunks]))
        else:
            yield from self._read_lines(head, chunks)

    def _hashed(self, chunks: Iterator[bytes]) -> Iterator[bytes]:
        for chunk in chunks:
            self._hash.update(chunk)
            yield chunk
        self._consumed = True

    def _read_array(self, data: bytes) -> Iterator[JsonValue]:
        text = data.decode("utf-8", errors="replace")
        try:
            document = json.loads(text)
        # RecursionError is how `json` reports nesting it will not descend;
        # unreadable is unreadable, and neither may leave this layer (§7).
        except (ValueError, RecursionError) as failure:
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"the input begins with '[' but could not be read as a JSON "
                f"array ({failure}); no records were read",
                source=text,
            )
            return
        if not isinstance(document, list):
            self._collector.add(
                codes.MALFORMED_RECORD,
                "the input begins with '[' but did not parse to an array",
                source=document,
            )
            return
        yield from document

    def _read_lines(self, head: bytes, chunks: Iterator[bytes]) -> Iterator[JsonValue]:
        number = 0
        buffered = head
        exhausted = False
        while True:
            # Everything already buffered comes out before more is pulled --
            # otherwise the first record would wait on the second chunk, and
            # "lazy" would be a claim rather than a behavior.
            while (found := _line_break(buffered)) is not None:
                start, end = found
                if (
                    not exhausted
                    and end == len(buffered)
                    and buffered[start:end] == b"\r"
                ):
                    # A CR at the very end of what has arrived might yet be
                    # the first half of a CRLF. Waiting for the next byte is
                    # what keeps a chunk boundary from inventing a blank line
                    # and shifting every line number after it.
                    break
                line, buffered = buffered[:start], buffered[end:]
                number += 1
                yield from self._read_line(number, line)
            if exhausted:
                break
            try:
                buffered += next(chunks)
            except StopIteration:
                exhausted = True
        number += 1
        yield from self._read_line(number, buffered)

    def _read_line(self, number: int, raw_line: bytes) -> Iterator[JsonValue]:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            # A blank line is not a record, and losing it drops nothing.
            return
        try:
            yield json.loads(line)
        # RecursionError: see `_read_array`. Deep nesting is a bad record,
        # not a bad interpreter, and it is reported as one.
        except (ValueError, RecursionError) as failure:
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"line {number} could not be read as JSON ({failure}); it was "
                f"skipped, and its text is kept here because there is nowhere "
                f"else for it to survive",
                source=line,
            )


#: The UTF-8 encoding of U+FEFF. Editors and Windows tooling write it at the
#: head of a file; `str.strip()` does not remove it, so left in place it rides
#: into the parser and costs the file its FIRST record (`SPEC.md` §7).
_BOM = b"\xef\xbb\xbf"


def _line_break(data: bytes) -> tuple[int, int] | None:
    """Where the first line terminator starts and ends, or None.

    LF, CRLF and CR alone are each *one* terminator: three conventions for the
    same fact, and a reader that knows only the first one turns a CR-only file
    into a single unreadable line.
    """
    newline = data.find(b"\n")
    carriage = data.find(b"\r")
    if carriage < 0 or (0 <= newline < carriage):
        return None if newline < 0 else (newline, newline + 1)
    if data[carriage + 1 : carriage + 2] == b"\n":
        return (carriage, carriage + 2)
    return (carriage, carriage + 1)


def _first_non_space(data: bytes) -> str | None:
    """The first non-whitespace character, or None if there is not one yet."""
    for byte in data:
        character = chr(byte)
        if not character.isspace():
            return character
    return None


def _chunks_of_file(path: pathlib.Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            yield chunk


def _chunks_of_stdin() -> Iterator[bytes]:
    while chunk := sys.stdin.buffer.read(65536):
        yield chunk


def read_trace(source: Source) -> RecordStream:
    """Open a trace: bytes, a path, or ``"-"`` for stdin.

    A ``str`` is always a path (or ``"-"``), never trace content. Content is
    passed as ``bytes``. Guessing between the two would be exactly the kind of
    convenience that turns into a bug report about a file named ``{``.
    """
    if isinstance(source, bytes):
        return RecordStream("<bytes>", iter((source,)))
    if isinstance(source, str) and source == STDIN:
        return RecordStream("<stdin>", _chunks_of_stdin())
    path = pathlib.Path(source)
    return RecordStream(str(path), _chunks_of_file(path))
