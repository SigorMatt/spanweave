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

**The same defect had a second family**, found after the first was fixed and
counted here for the same reason (batch R9): C3's *154 timestamp values*, D2's
*15 captured files / 24 `data` edges*, and F1's *64 of 64 `*.jsonl`* and *46
`malformed_record`* were measured over a working tree too, or over a file the
audit generated and never committed. Each recomputes from `git ls-files` now:
`Timestamps`, `Receipts`, `HeadScan` and `IndentedExport` below.

Run it: `uv run python -m tests.corpus_census`. `tests/test_doc_truth.py` is
what holds the documents to these numbers; this module only counts.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import re
import subprocess
from dataclasses import dataclass

import spanweave
from spanweave.adapters import MINIMUM_CONFIDENCE, registered
from spanweave.adapters.openinference import MARKER_PREFIX as OPENINFERENCE_MARKER
from spanweave.adapters.otel_genai import MARKER_PREFIX as OTEL_GENAI_MARKER
from spanweave.build import TIMESTAMP_UNIT_CEILING
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
    #: Timestamp literals over the whole tracked corpus.
    timestamps: Timestamps
    #: The same, over the captured subset alone -- real exporter output, which
    #: is the scope C3 and D2 meant and the scope a hand-authored fixture
    #: written to exercise a ceiling must not be counted into.
    captured_timestamps: Timestamps
    #: `data` edges over the captured subset (D2).
    captured_receipts: Receipts
    #: What every tracked `*.jsonl` in the tree begins with (F1 §16(k)).
    head_scan: HeadScan
    #: The tracked OTLP JSON documents, line-counted (F1 §16(a)).
    indented_exports: tuple[IndentedExport, ...]

    @property
    def files(self) -> int:
        return len(self.paths)

    @property
    def jsonl_files(self) -> int:
        return sum(1 for path in self.paths if path.suffix == ".jsonl")

    @property
    def captured(self) -> tuple[pathlib.Path, ...]:
        return captured_files(self.paths)


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


#: The four spellings a timestamp literal appears under across the corpus's
#: three container formats: the flat record's own two keys, and the two OTLP
#: JSON writes them as.
TIMESTAMP_KEYS = ("start_time", "end_time", "startTimeUnixNano", "endTimeUnixNano")

#: One timestamp literal, exactly as its file spells it. Read from the **text**
#: rather than from the parsed record, because half of what C3 asserted is
#: about the spelling -- whether the shortest float repr of a value differs
#: from the digits written down -- and parsing has already spent that.
TIMESTAMP_LITERAL = re.compile(
    '"(?:' + "|".join(TIMESTAMP_KEYS) + r')"\s*:\s*'
    r'("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|null)'
)

#: The first member key that makes an input an OTLP JSON document (`SPEC.md`
#: §7). Used only to find the indented exports `OPEN_QUESTIONS.md` §16(a)
#: counts diagnostics over.
OTLP_FIRST_KEY = "resourceSpans"


@dataclass(frozen=True, slots=True)
class Timestamps:
    """What the corpus's timestamp literals are, and what float64 does to them.

    `OPEN_QUESTIONS.md` §2 and C3's `CHANGELOG.md` entry state these over "the
    17 captured trace files (`fixtures/captured/`, `capture/_scratch/fleet/`)"
    -- a scope that names the git-ignored directory as half of itself, so the
    figure could not be recomputed from a checkout at all.
    """

    #: Timestamp literals found, counting a `null` as no literal.
    literals: int
    #: Literals above `TIMESTAMP_UNIT_CEILING`, which unix seconds cannot be.
    above_ceiling: int
    #: Literals whose shortest float repr is not the digits in the file. This
    #: is the loss C3 fixed, counted where it actually occurs.
    differing_from_shortest_repr: int
    #: Distinct literals that land on one float -- the collision that makes a
    #: `temporal` tie-break decide an order the telemetry did not.
    floats_carrying_two_literals: int
    #: Pairs of nodes that share a parent and both carry a `started_at`
    #: (`SPEC.md` §4.3: nodes with no parent are siblings at trace root).
    sibling_pairs: int
    #: The smallest gap between any such pair, in seconds; `None` if no pair.
    minimum_sibling_gap: float | None

    @property
    def minimum_sibling_gap_us(self) -> int | None:
        """The same gap in whole microseconds, which is how documents cite it."""
        if self.minimum_sibling_gap is None:
            return None
        return round(self.minimum_sibling_gap * 1_000_000)


@dataclass(frozen=True, slots=True)
class Receipts:
    """`data` edges over a set of traces -- D2's *15 captured files, 24 edges*.

    The number that carries the argument is the last one: a call id received by
    more than one span is the shape `SPEC.md` §4.2.1's rank exists for, and no
    captured trace has ever held one.
    """

    #: Files looked at.
    files: int
    #: Files producing at least one `data` edge.
    files_with_data_edges: int
    #: `data` edges over all of them.
    data_edges: int
    #: Call ids declared received by more than one span.
    redeclared_receipts: int


@dataclass(frozen=True, slots=True)
class HeadScan:
    """F1 §16(k)'s head-scan evidence, over every tracked `*.jsonl` in the tree.

    Not the corpus list: §16(k)'s claim is about every `*.jsonl` the repository
    carries anywhere, which is what has to be true for the OTLP buffering
    branch to be unreachable by an existing input.
    """

    files: int
    beginning_with_brace: int
    first_member_key_trace_id: int


@dataclass(frozen=True, slots=True)
class IndentedExport:
    """A tracked OTLP JSON document, and what a line reader makes of it.

    §16(a) states *46 `malformed_record` diagnostics and 0 nodes* for an
    indented export -- a file `probe1.py` wrote to a temporary directory and
    the repository does not carry, so 46 recomputes from nothing. The property
    it reports is per line and does recompute: every line of an indented JSON
    document is a line that is not itself JSON, so a line reader says so once
    per line.
    """

    #: Path relative to `ROOT`, in POSIX spelling.
    path: str
    lines: int
    lines_that_are_not_json: int


def captured_files(paths: tuple[pathlib.Path, ...]) -> tuple[pathlib.Path, ...]:
    """The captured subset: real exporter output, not hand-authored fixtures.

    `capture/_scratch/fleet/` is where the local fleet run drops its captures
    and git ignores all of it, so a checkout's captured corpus is whatever
    `fixtures/captured/` carries and nothing else.
    """
    return tuple(path for path in paths if "captured" in path.parts)


def timestamps(paths: tuple[pathlib.Path, ...]) -> Timestamps:
    """Count timestamp literals over `paths`, and the sibling gaps they make."""
    literals: list[str] = []
    for path in paths:
        for match in TIMESTAMP_LITERAL.finditer(path.read_text(encoding="utf-8")):
            written = match.group(1)
            if written == "null":
                continue
            parsed = json.loads(written) if written.startswith('"') else written
            literals.append(parsed if isinstance(parsed, str) else written)
    above = 0
    differing = 0
    spellings: dict[float, set[str]] = {}
    for written in literals:
        try:
            value = float(written)
        except ValueError:  # pragma: no cover -- a non-numeric literal
            continue
        above += value > TIMESTAMP_UNIT_CEILING
        differing += repr(value) != written
        spellings.setdefault(value, set()).add(written)
    pairs = 0
    smallest: float | None = None
    for path in paths:
        graph = spanweave.build(path)
        parent = {
            edge.dst: edge.src for edge in graph.edges() if edge.kind.value == "parent"
        }
        started = {node.id: node.started_at for node in graph.nodes()}
        groups: dict[str | None, list[str]] = {}
        for node_id in sorted(started):
            groups.setdefault(parent.get(node_id), []).append(node_id)
        for group in groups.values():
            for one, other in itertools.combinations(group, 2):
                if started[one] is None or started[other] is None:
                    continue
                pairs += 1
                gap = abs(started[one] - started[other])
                smallest = gap if smallest is None else min(smallest, gap)
    return Timestamps(
        literals=len(literals),
        above_ceiling=above,
        differing_from_shortest_repr=differing,
        floats_carrying_two_literals=sum(1 for s in spellings.values() if len(s) > 1),
        sibling_pairs=pairs,
        minimum_sibling_gap=smallest,
    )


def receipts(paths: tuple[pathlib.Path, ...]) -> Receipts:
    """Count `data` edges over `paths`, and re-declared receipts among them."""
    edges = 0
    with_edges = 0
    redeclared = 0
    for path in paths:
        graph = spanweave.build(path)
        data = [edge for edge in graph.edges() if edge.kind.value == "data"]
        edges += len(data)
        with_edges += bool(data)
        received: dict[str, int] = {}
        for edge in data:
            received[edge.src] = received.get(edge.src, 0) + 1
        redeclared += sum(1 for count in received.values() if count > 1)
    return Receipts(
        files=len(paths),
        files_with_data_edges=with_edges,
        data_edges=edges,
        redeclared_receipts=redeclared,
    )


def _tracked(root: pathlib.Path, pattern: str) -> tuple[pathlib.Path, ...]:
    """Every tracked file in the tree whose name ends `pattern`."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(
        sorted(
            root / name
            for name in listed.split("\0")
            if name and name.endswith(pattern)
        )
    )


def head_scan(root: pathlib.Path = ROOT) -> HeadScan:
    """F1 §16(k): what every tracked `*.jsonl` begins with."""
    paths = _tracked(root, ".jsonl")
    brace = 0
    trace_id = 0
    for path in paths:
        text = path.read_text(encoding="utf-8-sig").lstrip()
        brace += text.startswith("{")
        first = text.splitlines()[0] if text else ""
        try:
            record = json.loads(first)
        except ValueError:  # pragma: no cover -- no such file in the tree
            continue
        if isinstance(record, dict) and next(iter(record), None) == "trace_id":
            trace_id += 1
    return HeadScan(
        files=len(paths),
        beginning_with_brace=brace,
        first_member_key_trace_id=trace_id,
    )


def indented_exports(root: pathlib.Path = ROOT) -> tuple[IndentedExport, ...]:
    """Every tracked OTLP JSON document, and its non-JSON line count."""
    found: list[IndentedExport] = []
    for path in _tracked(root, ".json"):
        text = path.read_text(encoding="utf-8-sig")
        stripped = text.lstrip()
        if not stripped.startswith("{"):
            continue
        try:
            document = json.loads(text)
        except ValueError:
            continue
        if (
            not isinstance(document, dict)
            or next(iter(document), None) != OTLP_FIRST_KEY
        ):
            continue
        lines = text.splitlines()
        not_json = 0
        for line in lines:
            candidate = line.strip()
            if not candidate:
                continue
            try:
                json.loads(candidate)
            except ValueError:
                not_json += 1
        found.append(
            IndentedExport(
                path=path.relative_to(root).as_posix(),
                lines=len(lines),
                lines_that_are_not_json=not_json,
            )
        )
    return tuple(found)


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
        timestamps=timestamps(paths),
        captured_timestamps=timestamps(captured_files(paths)),
        captured_receipts=receipts(captured_files(paths)),
        head_scan=head_scan(root),
        indented_exports=indented_exports(root),
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
    whole = counted.timestamps
    print(
        f"  timestamp literals: {whole.literals}, of which "
        f"{whole.above_ceiling} above {TIMESTAMP_UNIT_CEILING}, "
        f"{whole.differing_from_shortest_repr} differ from their shortest "
        f"float repr, {whole.floats_carrying_two_literals} float(s) carry two"
    )
    captured = counted.captured_timestamps
    print(f"captured traces (tracked files only): {len(counted.captured)} files")
    print(
        f"  timestamp literals: {captured.literals}, of which "
        f"{captured.above_ceiling} above {TIMESTAMP_UNIT_CEILING}, "
        f"{captured.differing_from_shortest_repr} differ from their shortest "
        f"float repr, {captured.floats_carrying_two_literals} float(s) carry two"
    )
    print(
        f"  sibling pairs: {captured.sibling_pairs}, minimum gap "
        f"{captured.minimum_sibling_gap_us} us"
    )
    receipt = counted.captured_receipts
    print(
        f"  `data` edges: {receipt.data_edges} over "
        f"{receipt.files_with_data_edges} file(s), "
        f"{receipt.redeclared_receipts} re-declared receipt(s)"
    )
    scan = counted.head_scan
    print(
        f"tracked `*.jsonl` anywhere in the tree: {scan.files}, of which "
        f"{scan.beginning_with_brace} begin with a brace and "
        f"{scan.first_member_key_trace_id} open on `trace_id`"
    )
    for export in counted.indented_exports:
        print(
            f"  {export.path}: {export.lines} lines, "
            f"{export.lines_that_are_not_json} of them not JSON"
        )


if __name__ == "__main__":  # pragma: no cover -- `python -m tests.corpus_census`
    main()
