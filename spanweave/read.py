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
  at the head of the stream is skipped (``SPEC.md`` §7): that is a fact about
  how the file was written, not about what it says, and the tolerance reaches
  exactly the head -- those same bytes anywhere else are content and are
  passed through verbatim. Line endings are LF and CRLF. A **lone CR is not a
  terminator**, because a lone CR is legal JSON whitespace *inside* a record
  (RFC 8259): splitting on it would take a record that parses and break it in
  two, which is the tolerance reaching content -- the one thing this bullet
  forbids.
* **It reads each record once.** At-least-once export and collector retries
  put the same record in a file twice, and two nodes for one operation is an
  *invented* span -- worse than a missing one, because nothing downstream can
  tell. A repeat is skipped and reported as ``duplicate_record`` (`SPEC.md`
  §7). Sameness is decided on the **parsed** record, because the parsed record
  is what the library preserves; whitespace and key order never reach a node,
  so collapsing two lines that parse equal loses nothing.
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
from spanweave.model import DiagnosticLevel, JsonValue

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
        yield from self._deduplicated(self._records())

    def _deduplicated(self, records: Iterator[JsonValue]) -> Iterator[JsonValue]:
        """Each distinct record once, with the repeats reported (`SPEC.md` §7).

        Only the *first* copy is yielded. Which one that is cannot be seen in
        the graph -- the copies are equal as parsed records, and the one field
        that separates them, ``line_number``, is not serialized -- so stating
        the rule is free and leaves nothing to accident.

        What is held is one digest per distinct record, and the record itself
        only for the ones that turned out to be duplicated. Streaming is not
        given up: nothing here waits for a later record to yield an earlier
        one.
        """
        seen: set[str] = set()
        repeated: dict[str, list[JsonValue]] = {}
        for record in records:
            digest = record_digest(record)
            if digest in seen:
                entry = repeated.setdefault(digest, [record, 1])
                entry[1] += 1
                continue
            seen.add(digest)
            yield record
        # Reported in digest order rather than in the order the repeats
        # arrived: the collector's sort is stable, so insertion order decides
        # ties, and insertion order would otherwise be input order.
        for digest in sorted(repeated):
            record, copies = repeated[digest]
            self._collector.add(
                codes.DUPLICATE_RECORD,
                f"this record appears {copies} times in the input; one copy "
                f"is kept and the rest are skipped, because they are the same "
                f"record and two nodes for one operation would be a span that "
                f"never happened",
                level=DiagnosticLevel.INFO,
                source=record,
            )

    def _records(self) -> Iterator[JsonValue]:
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
        while True:
            # Everything already buffered comes out before more is pulled --
            # otherwise the first record would wait on the second chunk, and
            # "lazy" would be a claim rather than a behavior.
            #
            # The terminator is the LF, and a CRLF is one line because the CR
            # ahead of it goes with the whitespace `_read_line` strips. A CR
            # on its own is left where it is: it is whitespace *within* a
            # record (`SPEC.md` §7), and a reader that split on it would break
            # a record that parses.
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


def record_digest(record: JsonValue) -> str:
    """The canonical digest of a parsed record (`SPEC.md` §3.6).

    One fingerprint, two callers: the reader collapses records that share it,
    and `spanweave/ids.py` uses it to tell apart two records a dialect gave
    one span id. Both need the *same* answer to the same question -- "is this
    the same record?" -- so it is computed in one place.

    Canonical because the digest must not depend on how the record was
    written: sorted keys and compact separators, over the parsed value rather
    than the bytes. `hash()` is forbidden here for the usual reason
    (`CLAUDE.md` 4); SHA-256 is stable across processes and versions.
    """
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: The UTF-8 encoding of U+FEFF. Editors and Windows tooling write it at the
#: head of a file; `str.strip()` does not remove it, so left in place it rides
#: into the parser and costs the file its FIRST record (`SPEC.md` §7).
_BOM = b"\xef\xbb\xbf"


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
