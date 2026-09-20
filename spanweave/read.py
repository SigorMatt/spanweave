"""Reading a trace file into JSON records.

The bottom layer: bytes in, ``JsonValue`` records out, plus the diagnostics
produced along the way (``DESIGN.md`` §2). It knows three container formats
and no dialects -- what the records *mean* is the adapter's problem, one layer
up.

Two things this layer must get right:

* **It never raises on malformed input.** A trace is untrusted, frequently
  truncated, and often has one bad line in the middle (`SECURITY.md`). A bad
  line becomes a ``malformed_record`` diagnostic carrying its text, and the
  read continues. The library that gives up on line 4,000 of 10,000 is worse
  than useless in a pipeline. "Malformed" includes *nested deeper than the
  parser will recurse*, which ``json`` reports as a ``RecursionError`` rather
  than a ``ValueError`` -- a different exception for the same fact, and one
  that escaped this guard until ``SPEC.md`` §7 said so out loud. The
  *encoder* has a ceiling of its own, and this layer meets it too: every
  record is digested for the duplicate check (`record_digest`), so where the
  encoder is the shallower of the two the reader meets it first. That is the
  library's own named refusal, ``graph_not_serializable`` -- never a bare
  ``RecursionError``.
* **It is tolerant about the wrapping, never about the content.** A UTF-8 BOM
  at the head of the stream is skipped (``SPEC.md`` §7): that is a fact about
  how the file was written, not about what it says, and the tolerance reaches
  exactly the head -- those same bytes anywhere else are content and are
  passed through verbatim. Line endings are LF and CRLF. A **lone CR is not a
  terminator**, because a lone CR is legal JSON whitespace *inside* a record
  (RFC 8259): splitting on it would take a record that parses and break it in
  two, which is the tolerance reaching content -- the one thing this bullet
  forbids.
* **A transport envelope is a container, not a dialect.** An OTLP JSON export
  is an object whose ``resourceSpans`` is a list, and the spans inside it are
  in whatever dialect their instrumentor speaks -- possibly two dialects in
  one export, because two instrumentors sharing a tracer provider share an
  export. So it is unpacked *here*, into one record per span, and the records
  that come out are classified per record like any others (`SPEC.md` §7,
  `OPEN_QUESTIONS.md` §16). An adapter would have had to answer the dialect
  question for a whole file, one level below the only place that can answer it
  at all. The unpacking renames nine keys and folds one, and **never drops a
  key and never invents one**: everything else is carried under its own name,
  where the adapters report it as unmapped.
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
import re
import sys
from collections.abc import Iterator

from spanweave import diagnostics as codes
from spanweave import jsoncodec
from spanweave.diagnostics import DiagnosticCollector
from spanweave.errors import GraphNotSerializableError
from spanweave.model import DiagnosticLevel, JsonValue

#: A path, a path-like, ``"-"`` for stdin, or the bytes themselves.
Source = bytes | str | os.PathLike[str]

STDIN = "-"


class RecordStream:
    """Lazily yields the records of one trace input.

    ``diagnostics``, ``digest`` and ``skipped_records`` are complete once
    iteration has finished; reading them earlier gives what is known so far.
    That is the honest consequence of streaming, and the builder consumes the
    stream fully before it asks.
    """

    def __init__(self, name: str, chunks: Iterator[bytes]) -> None:
        self._name = name
        self._chunks = chunks
        self._collector = DiagnosticCollector()
        self._hash = hashlib.sha256()
        self._consumed = False
        self._skipped = 0

    @property
    def name(self) -> str:
        """Where this came from, for messages. Never put in the output."""
        return self._name

    @property
    def diagnostics(self) -> DiagnosticCollector:
        return self._collector

    @property
    def skipped_records(self) -> int:
        """How much of the input never became a record, once read.

        One per ``malformed_record``: a line that would not parse, and a whole
        container that would not parse, which counts as **one** because how
        many records it held is precisely what could not be read. So the
        number is a lower bound on records lost, and its one honest use is the
        question `build_contributed_graph` asks of it -- was any record of this
        input never read at all (`SPEC.md` §3.7). Complete once iteration has
        finished, like ``diagnostics``.

        A ``duplicate_record`` is deliberately not counted. That copy is
        skipped, but an identical one was read, so nothing about its contents
        is unknown (`SPEC.md` §7).
        """
        return self._skipped

    @property
    def digest(self) -> str | None:
        """sha256 of the input bytes, once they have all been read."""
        return self._hash.hexdigest() if self._consumed else None

    def __iter__(self) -> Iterator[JsonValue]:
        # Expansion sits *above* deduplication so that an at-least-once export
        # which repeated a whole envelope still produces one record per span.
        yield from self._deduplicated(self._expanded(self._records()))

    def _expanded(self, records: Iterator[JsonValue]) -> Iterator[JsonValue]:
        """An OTLP export becomes the spans it carries (`SPEC.md` §7).

        Applied to every record whatever container produced it, so a file of
        one export per line and an array of exports need no rules of their
        own. The trigger is a **list-valued** ``resourceSpans`` and no other
        key: ``ExportTraceServiceRequest`` has exactly one field, so an object
        with a second is not one, and unpacking it would have to decide where
        that second key went -- which is how a reader starts dropping things.
        """
        for record in records:
            if _is_an_export(record):
                assert isinstance(record, dict)  # narrowed by `_is_an_export`
                yield from _unpack(record[_OTLP_ROOT])
            else:
                yield record

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
        verdict: str | None = None
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
            return
        if verdict == "{":
            head, opens_an_export = _opens_an_export(head, chunks)
            if opens_an_export:
                yield from self._read_document(b"".join([head, *chunks]))
                return
        yield from self._read_lines(head, chunks)

    def _hashed(self, chunks: Iterator[bytes]) -> Iterator[bytes]:
        for chunk in chunks:
            self._hash.update(chunk)
            yield chunk
        self._consumed = True

    def _read_array(self, data: bytes) -> Iterator[JsonValue]:
        text = data.decode("utf-8", errors="replace")
        try:
            document = jsoncodec.loads(text)
        # RecursionError is how `json` reports nesting it will not descend;
        # unreadable is unreadable, and neither may leave this layer (§7).
        except (ValueError, RecursionError) as failure:
            self._skipped += 1
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"the input begins with '[' but could not be read as a JSON "
                f"array ({failure}); no records were read",
                source=text,
            )
            return
        if not isinstance(document, list):
            self._skipped += 1
            self._collector.add(
                codes.MALFORMED_RECORD,
                "the input begins with '[' but did not parse to an array",
                source=document,
            )
            return
        yield from document

    def _read_document(self, data: bytes) -> Iterator[JsonValue]:
        """One JSON document, buffered for the array form's own reason.

        A document is not a record until its closing brace, and the head scan
        that got us here read one member key rather than the whole input, so
        being wrong is expected rather than exceptional: a file of one export
        per line begins with exactly these bytes. When the buffered input is
        not a single document it is read line by line, which is byte for byte
        what this input did before this branch existed -- including its
        diagnostics, which is why none is emitted here.
        """
        text = data.decode("utf-8", errors="replace")
        try:
            document = jsoncodec.loads(text)
        # RecursionError: see `_read_array`. The line reader reports it.
        except (ValueError, RecursionError):
            yield from self._read_lines(data, iter(()))
            return
        yield document

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
            yield jsoncodec.loads(line)
        # RecursionError: see `_read_array`. Nesting the parser will not
        # descend is a property of the record, and is reported as one.
        except (ValueError, RecursionError) as failure:
            self._skipped += 1
            self._collector.add(
                codes.MALFORMED_RECORD,
                f"line {number} could not be read as JSON ({failure}); it was "
                f"skipped, and its text is kept here because there is nowhere "
                f"else for it to survive",
                source=line,
            )


def _canonical_text(record: JsonValue) -> str:
    """The exact canonicalization `SPEC.md` §3.6 states, and nothing else.

    Its own function so that the call stays on one line at one indent: a
    reimplementation has to land on the same bytes, so `tests/test_doc_truth.py`
    checks this spelling against the spec's character for character.
    """
    return jsoncodec.encode(record, _stdlib_canonical_text)


def _stdlib_canonical_text(record: JsonValue) -> str:
    # `jsoncodec.encode` runs this and, where the interpreter's own digit
    # limit refuses an integer the library reads, runs it again with that
    # integer written whole: the digest is of the same text on every
    # interpreter setting (`SPEC.md` §5.3).
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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

    **This is an encode, and it is contained like every other one.** The
    reader's guards contain what the *parser* will not descend; this call is
    the one place the reader meets the **encoder**, which has a ceiling of its
    own and, on an interpreter where that ceiling is the lower of the two,
    meets a record the parser was willing to read (`SPEC.md` §7 measures
    both). Uncontained it escaped `spanweave.build` as a bare
    ``RecursionError`` -- an interpreter's traceback where §3.10 promises a
    routable code.

    It is the *same* refusal the write side raises, because it is the same
    fact about the same value: a record too deep to digest is too deep to
    write, so no graph carrying it was ever publishable, and nothing may be
    dropped to get past it -- a record with no digest has no identity (§3.6),
    and the record is the input rather than a rendering of it (`CLAUDE.md` 2).
    Which depth this begins at belongs to the interpreter; that the outcome is
    `graph_not_serializable` and never a traceback does not.
    """
    try:
        text = _canonical_text(record)
    # `json` answers nesting it will not descend with `RecursionError` rather
    # than `ValueError` -- a different exception for the same fact, and the
    # one this guard exists for (`SPEC.md` §7).
    except RecursionError as failure:
        raise GraphNotSerializableError(
            f"a record could not be digested: it nests deeper than this "
            f"interpreter's JSON encoder will descend ({failure}). The digest "
            f"is the record's identity and its duplicate check (`SPEC.md` "
            f"§3.6), so there is no graph to publish; nothing was dropped to "
            f"try, and the same record could not have been written either"
        ) from failure
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: The one key that makes an object an OTLP export (`SPEC.md` §7). It is also
#: the only thing the new branches are gated on, which is what makes the claim
#: "no existing input changes" checkable rather than hopeful: measured over the
#: tree at the time this landed, 0 files under `fixtures/`, `capture/` or
#: `examples/` contained it, and 64 of 64 `*.jsonl` opened with `trace_id`.
_OTLP_ROOT = "resourceSpans"

#: The same key as it appears in the bytes, for the head scan. Deliberately
#: not built from `_OTLP_ROOT` at import time: what the scan matches is a
#: literal run of bytes, and writing it out is how a reader checks it.
_OTLP_ROOT_BYTES = b'"resourceSpans"'

#: Span keys that become the record shape the adapters read. Renaming, not
#: interpreting: each has exactly one destination and no value is touched.
_RENAMED_SPAN_KEYS = {
    "traceId": "trace_id",
    "spanId": "span_id",
    "parentSpanId": "parent_id",
    "name": "name",
    "startTimeUnixNano": "start_time",
    "endTimeUnixNano": "end_time",
}

#: The same, for a span link.
_RENAMED_LINK_KEYS = {"traceId": "trace_id", "spanId": "span_id"}

#: proto3 JSON writes an enum as its name or its number, so both are read.
#: Anything else is carried verbatim: the record keeps it, and `Status` has an
#: honest `UNSET` for a value it does not recognize.
_STATUS_CODES: dict[str | int, str] = {
    0: "UNSET",
    1: "OK",
    2: "ERROR",
    "STATUS_CODE_UNSET": "UNSET",
    "STATUS_CODE_OK": "OK",
    "STATUS_CODE_ERROR": "ERROR",
}

#: What a `Status` that writes no `code` is carrying. proto3 gives every scalar
#: field a default rather than an absence, so an omitted `code` is this number
#: and not a missing field (`SPEC.md` §7). Kept as the number the format
#: defines, and spelled by `_STATUS_CODES` above like any other code, so the
#: two cannot drift.
_DEFAULT_STATUS_CODE = 0

#: An integer literal, the same subset of RFC 8259 the adapters apply to a
#: quoted timestamp -- and applied here for the opposite reason. A timestamp
#: field states only a *name*, so its owner reads it (`SPEC.md` §3.1); an
#: `intValue` states a **type**, and honouring a stated type is decoding.
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")


class _Unfoldable:
    """The value of an attribute entry this reader will not guess at."""


#: Returned instead of a folded value, which sends the whole entry to
#: `attributes_unfolded` rather than into the dict. A sentinel rather than
#: `None`, because `None` is a value an `AnyValue` can legitimately hold.
_UNFOLDABLE = _Unfoldable()


def _is_an_export(record: JsonValue) -> bool:
    """Is this one `ExportTraceServiceRequest`? (`SPEC.md` §7.)"""
    return (
        isinstance(record, dict)
        and set(record) == {_OTLP_ROOT}
        and isinstance(record[_OTLP_ROOT], list)
    )


def _opens_an_export(head: bytes, chunks: Iterator[bytes]) -> tuple[bytes, bool]:
    """`(head, whether the input's first member key is the export key)`.

    A head scan rather than a parse, and it stops at the first key: the whole
    input has to be buffered to read an export, and buffering every input that
    merely begins with ``{`` would end streaming for JSONL, which is most of
    them. Pulls only as many chunks as the key needs, and gives up rather than
    grow: giving up is free, because the caller then reads lines, which is what
    it would have done anyway.
    """
    while True:
        verdict = _scan_for_export_key(head)
        if verdict is not None:
            return head, verdict
        try:
            head += next(chunks)
        except StopIteration:
            return head, False


def _scan_for_export_key(data: bytes) -> bool | None:
    """True, False, or None for "not enough bytes to say yet"."""
    index = _past_space(data, 0)
    if index == len(data):
        return None
    if data[index] != ord("{"):
        return False
    index = _past_space(data, index + 1)
    if index == len(data):
        return None
    rest = data[index:]
    if len(rest) < len(_OTLP_ROOT_BYTES):
        return None if _OTLP_ROOT_BYTES.startswith(rest) else False
    return rest.startswith(_OTLP_ROOT_BYTES)


def _past_space(data: bytes, index: int) -> int:
    while index < len(data) and chr(data[index]).isspace():
        index += 1
    return index


def _unpack(resource_spans: list[JsonValue]) -> Iterator[JsonValue]:
    """One export's `resourceSpans` as flat records (`SPEC.md` §7).

    Nothing here is ever a discard. A level that carries no spans is yielded
    as a record of its own, so the resource that owned them survives as an
    `unknown` node; a level that is not an object at all is yielded exactly as
    it was found, and the adapters' existing "not a span-shaped thing" path
    makes a node of it.
    """
    for resource_entry in resource_spans:
        if not isinstance(resource_entry, dict):
            yield resource_entry
            continue
        resource_level = _without(resource_entry, "scopeSpans")
        scope_entries = resource_entry.get("scopeSpans")
        if not isinstance(scope_entries, list) or not scope_entries:
            yield _levels_only(resource_level, {})
            continue
        for scope_entry in scope_entries:
            if not isinstance(scope_entry, dict):
                yield scope_entry
                continue
            scope_level = _without(scope_entry, "spans")
            spans = scope_entry.get("spans")
            if not isinstance(spans, list) or not spans:
                yield _levels_only(resource_level, scope_level)
                continue
            for span in spans:
                if not isinstance(span, dict):
                    yield span
                    continue
                yield _flattened(span, resource_level, scope_level)


def _without(entry: dict[str, JsonValue], child: str) -> dict[str, JsonValue]:
    """An envelope level with its span-bearing child removed."""
    return {key: value for key, value in entry.items() if key != child}


def _levels_only(
    resource_level: dict[str, JsonValue], scope_level: dict[str, JsonValue]
) -> JsonValue:
    record: dict[str, JsonValue] = {}
    _attach_levels(record, resource_level, scope_level)
    return record


def _attach_levels(
    record: dict[str, JsonValue],
    resource_level: dict[str, JsonValue],
    scope_level: dict[str, JsonValue],
) -> None:
    """Resource and scope, preserved beside the span rather than inside it.

    **Not** merged into the span's attributes, for two reasons and the second
    is decisive: it would fabricate attributes no instrumentor wrote, and a
    resource attribute could change which adapter claims the span (`SPEC.md`
    §6.1). Verbatim rather than folded, because nothing reads them and a fold
    would invent a representation nothing has agreed on. Omitted when the
    level carries nothing but its children -- absent, not empty.
    """
    if resource_level:
        record["resource_spans"] = resource_level
    if scope_level:
        record["scope_spans"] = scope_level


def _flattened(
    span: dict[str, JsonValue],
    resource_level: dict[str, JsonValue],
    scope_level: dict[str, JsonValue],
) -> JsonValue:
    """One OTLP span as one flat record. Never drops a key, never invents one."""
    record: dict[str, JsonValue] = {}
    for key, value in span.items():
        renamed = _RENAMED_SPAN_KEYS.get(key)
        if renamed is not None:
            record[renamed] = value
        elif key == "attributes":
            _attach_attributes(record, "attributes", value)
        elif key == "links":
            record["links"] = _flattened_links(value)
        elif key == "status" and _is_a_plain_status(value):
            assert isinstance(value, dict)  # narrowed by `_is_a_plain_status`
            # A `Status` that writes no `code` is carrying proto3's default for
            # the field, which is 0 -- `UNSET`, not an absence. Reading it as
            # anything else drops the span's `status` key entirely, and a record
            # with no `status` is what a span that carried no `status` at all
            # produces: the two become indistinguishable, which is a silent
            # discard of a field the export wrote (`CLAUDE.md` 2).
            # `message` has no default worth inventing -- there is no string a
            # `Status` that wrote none can be said to have stated -- so an
            # absent one stays absent and no `status_message` is made up.
            record["status"] = _status_code(value.get("code", _DEFAULT_STATUS_CODE))
            if "message" in value:
                record["status_message"] = value["message"]
        else:
            # Everything else under its own OTLP name, where the adapters
            # report it as unmapped. `kind` is the one that looks mappable and
            # is not: no dialect reads an OTLP span kind, and mapping one onto
            # a `NodeKind` would be an interpretation made below the seam.
            record[key] = value
    _attach_levels(record, resource_level, scope_level)
    return record


def _is_a_plain_status(value: JsonValue) -> bool:
    """A `Status` with nothing in it but the two fields `Status` has.

    Anything else is carried verbatim rather than half-read -- the adapters
    already accept a `{"code", "message"}` object, so verbatim loses nothing.
    """
    return isinstance(value, dict) and set(value) <= {"code", "message"}


def _status_code(code: JsonValue) -> JsonValue:
    if isinstance(code, bool) or not isinstance(code, (str, int)):
        return code
    return _STATUS_CODES.get(code, code)


def _flattened_links(reported: JsonValue) -> JsonValue:
    """A span link, flattened by the span's own rules."""
    if not isinstance(reported, list):
        return reported
    links: list[JsonValue] = []
    for link in reported:
        if not isinstance(link, dict):
            links.append(link)
            continue
        flat: dict[str, JsonValue] = {}
        for key, value in link.items():
            renamed = _RENAMED_LINK_KEYS.get(key)
            if renamed is not None:
                flat[renamed] = value
            elif key == "attributes":
                _attach_attributes(flat, "attributes", value)
            else:
                flat[key] = value
        links.append(flat)
    return links


def _attach_attributes(
    record: dict[str, JsonValue], key: str, reported: JsonValue
) -> None:
    folded, unfolded = _folded_attributes(reported)
    record[key] = folded
    if unfolded:
        record[f"{key}_unfolded"] = unfolded


def _folded_attributes(reported: JsonValue) -> tuple[JsonValue, list[JsonValue]]:
    """OTLP's `[{"key", "value"}]` list as an object, plus what would not fold.

    A repeated key keeps the **last** and keeps **both** copies in the
    remainder: a fold that silently kept one of two values would be the reader
    deciding which of them the telemetry meant. The remainder is omitted
    entirely when there is nothing to put in it, so the ordinary case carries
    no trace of this rule.
    """
    if not isinstance(reported, list):
        return reported, []
    folded: dict[str, JsonValue] = {}
    first_seen: dict[str, JsonValue] = {}
    duplicated: set[str] = set()
    unfolded: list[JsonValue] = []
    for entry in reported:
        if not isinstance(entry, dict):
            unfolded.append(entry)
            continue
        key = entry.get("key")
        if not isinstance(key, str):
            unfolded.append(entry)
            continue
        value = _any_value(entry.get("value"))
        if isinstance(value, _Unfoldable):
            unfolded.append(entry)
            continue
        if key in folded:
            if key not in duplicated:
                unfolded.append(first_seen[key])
                duplicated.add(key)
            unfolded.append(entry)
        else:
            first_seen[key] = entry
        folded[key] = value
    return folded, unfolded


def _any_value(value: JsonValue) -> JsonValue | _Unfoldable:
    """An OTLP `AnyValue`, unwrapped by the tag it carries.

    The tag is the format stating a type, which is why this reads it at all --
    and why `intValue`, which proto3 JSON writes as a decimal string because
    that is how it writes every `int64`, comes back as an integer. A string
    that is not an integer literal is carried verbatim rather than forced.
    """
    if not isinstance(value, dict):
        return _UNFOLDABLE
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return _int_value(value["intValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "bytesValue" in value:
        # Base64, and it stays base64: JSON has no bytes, so decoding it would
        # produce a value the output could not hold.
        return value["bytesValue"]
    if "arrayValue" in value:
        return _array_value(value["arrayValue"])
    if "kvlistValue" in value:
        return _kvlist_value(value["kvlistValue"])
    # An `AnyValue` with no field set is proto3's absent value.
    return None if not value else _UNFOLDABLE


def _int_value(reported: JsonValue) -> JsonValue:
    if isinstance(reported, str) and _INTEGER.fullmatch(reported):
        try:
            return jsoncodec.parse_integer(reported)
        except ValueError:
            # Longer than the library's digit limit (`SPEC.md` §5.3) -- a
            # constant, counted before any conversion, so the answer is the
            # same on every interpreter setting. No `int64` is that long, but
            # a file can say one is. The decimal string is carried verbatim
            # instead, which is what every value the reader cannot decode
            # does (`SPEC.md` §7).
            return reported
    return reported


def _array_value(reported: JsonValue) -> JsonValue | _Unfoldable:
    if not isinstance(reported, dict) or not isinstance(reported.get("values"), list):
        return _UNFOLDABLE
    values = reported["values"]
    assert isinstance(values, list)  # narrowed above
    unwrapped: list[JsonValue] = []
    for item in values:
        value = _any_value(item)
        if isinstance(value, _Unfoldable):
            return _UNFOLDABLE
        unwrapped.append(value)
    return unwrapped


def _kvlist_value(reported: JsonValue) -> JsonValue | _Unfoldable:
    if not isinstance(reported, dict) or not isinstance(reported.get("values"), list):
        return _UNFOLDABLE
    folded, unfolded = _folded_attributes(reported["values"])
    return _UNFOLDABLE if unfolded else folded


#: The UTF-8 encoding of U+FEFF. Editors and Windows tooling write it at the
#: head of a file; `str.strip()` does not remove it, so left in place it rides
#: into the parser and leaves the file's FIRST record unparseable
#: (`SPEC.md` §7).
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
