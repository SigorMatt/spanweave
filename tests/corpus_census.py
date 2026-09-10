"""The corpus census, counted from git's file list rather than from a walk.

Documents in this repository state the size of the corpus they measured
something over -- how many trace files, how many records, and then the number
that matters, which is almost always a **zero**. Those sentences are only worth
anything if a stranger can recompute them, and five commits of the September
2026 audit series stated a pair nobody could: `57 files / 177 records` was
measured on a **working tree** that held local capture output under
`capture/_scratch/`, which git ignores (`TASKS.md`, *September 2026 audit*
note 7). The tracked part of that scan was 43 files and 117 records. The
substance survived in every case -- the zero was the same either way -- but the
arithmetic could not be checked, and a claim that cannot be checked is not
evidence.

**So the file list comes from `git ls-files`, not from `rglob`.** That is the
whole point of this module and not an implementation detail: a walk of the
working tree counts whatever happens to be lying in it, so a scratch capture, a
half-finished fixture, or a downloaded trace silently moves a number a document
asserts. Git's list holds exactly what a `git clone` produces, so every figure
below recomputes identically from any clean checkout, on any machine.

**What counts as a corpus file** is what the library can read as a trace: every
tracked `*.jsonl` under `fixtures/`, plus every tracked `*.json` in a
scenario's `dialects/` directory -- the OTLP JSON container the audit series'
batch F2 added. It is deliberately *not* a `*.jsonl` glob: that is what the
sweep used until F2, at which point a corpus that grew by two files and eight
records would have gone on reporting the old number.

Run it: `uv run python -m tests.corpus_census`. `tests/test_doc_truth.py` is
what holds the documents to these numbers; this module only counts.
"""

from __future__ import annotations

import pathlib
import subprocess
from dataclasses import dataclass

from spanweave.adapters import MINIMUM_CONFIDENCE, registered
from spanweave.adapters.openinference import MARKER_PREFIX as OPENINFERENCE_MARKER
from spanweave.adapters.otel_genai import MARKER_PREFIX as OTEL_GENAI_MARKER
from spanweave.diagnostics import MALFORMED_RECORD
from spanweave.model import JsonValue
from spanweave.read import read_trace

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The marker prefix each adapter's `detect()` scans for, by adapter id. Used
#: only for the direct-scan cross-check `OPEN_QUESTIONS.md` §12(d) states.
MARKERS = {
    "openinference": OPENINFERENCE_MARKER,
    "otel_genai": OTEL_GENAI_MARKER,
}


@dataclass(frozen=True, slots=True)
class Census:
    """What the tracked corpus holds. Every field recomputes from a checkout."""

    #: Corpus files, in git's order, resolved against `ROOT`.
    paths: tuple[pathlib.Path, ...]
    #: Records read out of them, by `read_trace`, in file order.
    records: int
    #: How many adapters claimed each record, counted: `{claimants: records}`.
    #: `{1: n}` is every record claimed by exactly one adapter.
    claims: dict[int, int]
    #: Files carrying records of more than one dialect.
    mixed_files: int
    #: Files every one of whose records is claimed by that adapter alone,
    #: by adapter id. Sums with `mixed_files` to `files`.
    sole_dialect_files: dict[str, int]
    #: Records carrying a `span_id` at all (`SPEC.md` §3.6 rules 1 and 3).
    with_span_id: int
    #: Records whose `span_id` is unique within their file -- rule 1, the only
    #: rule under which no adapter id enters the node id.
    trace_unique_span_id: int
    #: Records where `detect([record])` and a direct marker scan disagree.
    marker_disagreements: int

    @property
    def files(self) -> int:
        return len(self.paths)

    @property
    def jsonl_files(self) -> int:
        return sum(1 for path in self.paths if path.suffix == ".jsonl")


def tracked_corpus_files(root: pathlib.Path = ROOT) -> tuple[pathlib.Path, ...]:
    """Every trace file the repository *carries*, from `git ls-files`.

    An untracked file under `fixtures/` -- and `capture/_scratch/`, which is
    not under `fixtures/` at all -- cannot appear here, which is the property
    every figure in this module rests on.
    """
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "fixtures"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = [name for name in listed.split("\0") if name]
    return tuple(
        sorted(
            root / name
            for name in names
            if name.endswith(".jsonl")
            or (
                name.endswith(".json")
                and pathlib.PurePosixPath(name).parent.name == "dialects"
            )
        )
    )


def _claimed_by(record: JsonValue) -> list[str]:
    """The adapters that claim this record, by the library's own rule."""
    return [
        adapter.id
        for adapter in registered()
        if adapter.detect([record]) >= MINIMUM_CONFIDENCE
    ]


def _scanned_markers(record: JsonValue) -> list[str]:
    """The same question asked of the record's keys directly.

    `OPEN_QUESTIONS.md` §12(d) claims `detect([record])` is a per-record
    classifier that agrees with a direct marker scan. Counting the two side by
    side is what makes that sentence recomputable rather than remembered.
    """
    if not isinstance(record, dict):
        return []
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return []
    return sorted(
        adapter_id
        for adapter_id, marker in MARKERS.items()
        if any(str(key).startswith(marker) for key in attributes)
    )


def census(root: pathlib.Path = ROOT) -> Census:
    """Count the tracked corpus, reading it the way the library reads it."""
    paths = tracked_corpus_files(root)
    records = 0
    claims: dict[int, int] = {}
    mixed_files = 0
    sole: dict[str, int] = {adapter.id: 0 for adapter in registered()}
    with_span_id = 0
    unique_span_id = 0
    disagreements = 0
    unreadable: list[str] = []
    for path in paths:
        stream = read_trace(path)
        found = list(stream)
        unreadable.extend(
            f"{path.relative_to(root)}: {diagnostic.message}"
            for diagnostic in stream.diagnostics.collected()
            if diagnostic.code == MALFORMED_RECORD
        )
        dialects: set[str] = set()
        span_ids: list[str] = []
        for record in found:
            records += 1
            claiming = _claimed_by(record)
            dialects.update(claiming)
            claims[len(claiming)] = claims.get(len(claiming), 0) + 1
            disagreements += sorted(claiming) != _scanned_markers(record)
            for adapter in registered():
                if adapter.id in claiming:
                    span_ids.extend(
                        span.span_id or "" for span in adapter.parse([record])
                    )
                    break
        # A file two adapters read is a different measurement from a record two
        # adapters claim: the first is the mixed-instrumentation shape, the
        # second is the ambiguity that shape is NOT (`SPEC.md` §6.1).
        mixed_files += len(dialects) > 1
        if len(dialects) == 1:
            sole[next(iter(dialects))] += 1
        with_span_id += sum(1 for span_id in span_ids if span_id)
        unique_span_id += sum(
            1 for span_id in span_ids if span_id and span_ids.count(span_id) == 1
        )
    if unreadable:
        raise AssertionError(
            "these corpus records are not JSON, so no adapter can be asked "
            "about them and this census cannot say what they carry: "
            + ", ".join(unreadable)
        )
    return Census(
        paths=paths,
        records=records,
        claims=claims,
        mixed_files=mixed_files,
        sole_dialect_files=sole,
        with_span_id=with_span_id,
        trace_unique_span_id=unique_span_id,
        marker_disagreements=disagreements,
    )


def main() -> None:
    """Print the figures the documents cite. Tracked files only."""
    counted = census()
    claimed = ", ".join(
        f"{count} record(s) claimed by {claimants} adapter(s)"
        for claimants, count in sorted(counted.claims.items())
    )
    print(
        f"corpus (tracked files only): {counted.files} files, {counted.records} records"
    )
    print(f"  of which `*.jsonl`: {counted.jsonl_files}")
    print(f"  dialect claims: {claimed}")
    print(f"  files carrying records of both dialects: {counted.mixed_files}")
    for adapter_id, count in sorted(counted.sole_dialect_files.items()):
        print(f"  files that are {adapter_id}-only: {count}")
    print(
        f"  detect() vs direct marker scan: {counted.marker_disagreements} "
        f"disagreement(s)"
    )
    print(f"  records carrying a span id: {counted.with_span_id}")
    print(
        f"  of which trace-unique (SPEC.md 3.6 rule 1): {counted.trace_unique_span_id}"
    )


if __name__ == "__main__":  # pragma: no cover -- `python -m tests.corpus_census`
    main()
