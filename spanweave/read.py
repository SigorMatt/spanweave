"""Reading a trace file into JSON records.

The bottom layer: bytes in, ``JsonValue`` records out, plus the diagnostics
produced along the way (``DESIGN.md`` §2). It knows two container formats and
no dialects -- what the records *mean* is the adapter's problem, one layer up.

Two things this layer must get right:

* **It never raises on malformed input.** A trace is untrusted, frequently
  truncated, and often has one bad line in the middle (`SECURITY.md`). A bad
  line becomes a ``malformed_record`` diagnostic carrying its text, and the
  read continues. The library that gives up on line 4,000 of 10,000 is worse
  than useless in a pipeline.
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
        # pulling only as far as it takes to see one.
        head = b""
        is_array = False
        for chunk in chunks:
            head += chunk
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
        except ValueError as failure:
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"the input begins with '[' but is not a valid JSON array "
                f"({failure}); no records were read",
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
        while True:
            # Everything already buffered comes out before more is pulled --
            # otherwise the first record would wait on the second chunk, and
            # "lazy" would be a claim rather than a behavior.
            while b"\n" in buffered:
                line, buffered = buffered.split(b"\n", 1)
                number += 1
                yield from self._read_line(number, line)
            try:
                buffered += next(chunks)
            except StopIteration:
                break
        number += 1
        yield from self._read_line(number, buffered)

    def _read_line(self, number: int, raw_line: bytes) -> Iterator[JsonValue]:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            # A blank line is not a record, and losing it drops nothing.
            return
        try:
            yield json.loads(line)
        except ValueError as failure:
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"line {number} is not valid JSON ({failure}); it was skipped, "
                f"and its text is kept here because there is nowhere else for "
                f"it to survive",
                source=line,
            )


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
