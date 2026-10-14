"""The zoo census: what the audit counted on a stranger's trace, re-derived.

`fixtures/zoo/` is a byte-for-byte copy of the twelve captures'
`json/NNNN.json` bodies of `SigorMatt/spanweave-zoo` at `ZOO_PIN`, with each
capture's sealed `MANIFEST.json` beside them (`fixtures/zoo/README.md`). Six
agents, built by implementers who knew nothing about this library, under stock
instrumentation (each manifest's `project_manifest.instrumentation`).

This module holds the numbers the zoo's audit reported for each capture and
the code that recounts them; `tests/test_zoo.py` asserts the two agree, and
`make conformance` runs it. **Every number cites its report**: the per-body
record counts and the trace id come from `PROBES.md` "The captures" at the pin,
and every graph count from the report's step 4 (`spanweave inspect` on the
graph the audit wrote) in `audit/<project>-<run-id>.md` at the pin. Nothing in
`CAPTURES` was copied from this library's own output.

**What the audit fed is what is counted.** The audit built each trace from the
records `spanweave_live.Endpoint` routed to it, in the order its step 3 lists
("Records of `<trace>`, in the order fed"): every record of every body, in body
order, child before parent as the exporter wrote them (`PROBES.md` S15, S21) --
except, on Z4, the root span `concierge.conversation`, which no adapter claims
and which the receiver routed to no trace (`PROBES.md` S1, L2). That record is
named in `Capture.unrouted`, and `tests/test_zoo.py` holds what the **whole**
capture builds to beside it: the audit's counts, plus that one record as the
`unknown` node `SPEC.md` §6.1 makes of a record no adapter claims. The whole
capture is not a number any report gives; it is the audit's number and §6.1's
rule, and it is kept separate so neither is mistaken for the other.

**The census is the instrument, not the verdict.** A later change that moves a
count updates `CAPTURES` in its own commit and says why there. The diff of
this file across a series is that series' effect on a stranger's trace.

Run it: `uv run python -m tests.zoo_census` prints the recount beside the
census.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
from dataclasses import dataclass, fields

import spanweave
from spanweave.api import graph_from_records
from spanweave.model import JsonValue

ROOT = pathlib.Path(__file__).resolve().parent.parent
ZOO = ROOT / "fixtures" / "zoo"

#: `SigorMatt/spanweave-zoo` at the merge of its PR #2, which `PROBES.md` and
#: the twelve `audit/*.md` were written at.
ZOO_PIN = "7eb5b6944ccef34861dbaf92e8f0acb0b7edaf99"

#: Where a body sits in the zoo's capture directory, and so in its manifest.
ZOO_BODY_DIR = "json"


@dataclass(frozen=True)
class Census:
    """The counts the census holds for one graph, as `spanweave inspect` names them."""

    nodes: int
    parent: int
    temporal: int
    orphan_parent: int
    unpaired_call: int
    unknown: int
    timestamp_unit_suspect: int


@dataclass(frozen=True)
class Capture:
    """One zoo capture and what its audit report counted."""

    #: `<project>/<run-id>`, under `fixtures/zoo/` here and `captures/` there.
    run: str
    #: The audit report every graph count below cites, at `ZOO_PIN`.
    report: str
    #: `PROBES.md` "The captures", Trace.
    trace_id: str
    #: `PROBES.md` "The captures", Bodies (records), in body order.
    records_per_body: tuple[int, ...]
    #: The report's step 4 `inspect` block, over the records its step 3 fed.
    census: Census
    #: `(body, record)` (1-based, as the reports number them) of each record the
    #: audit's step 3 did not feed to the trace, with the probe that says why.
    unrouted: tuple[tuple[str, int], ...] = ()


def _report(run: str) -> str:
    return "audit/" + run.replace("/", "-") + ".md"


def _capture(
    run: str,
    trace_id: str,
    records_per_body: tuple[int, ...],
    census: Census,
    unrouted: tuple[tuple[str, int], ...] = (),
) -> Capture:
    return Capture(run, _report(run), trace_id, records_per_body, census, unrouted)


# Each `Census(...)` is the step 4 `inspect` block of the report its `Capture`
# names: `nodes`, `parent (explicit)`, `temporal (derived)`, and the
# diagnostics `orphan_parent`, `unpaired_call`, `timestamp_unit_suspect` and the
# node kind `unknown` -- a count the block does not list is 0 there. Two
# captures of one project whose reports give the same block share a line.
_Z1 = Census(  # audit/z1-2026-10-13-{real,recorded}.md, step 4
    nodes=31,
    parent=30,
    temporal=16,
    orphan_parent=0,
    unpaired_call=1,
    unknown=2,
    timestamp_unit_suspect=31,
)
_Z2 = Census(  # audit/z2-2026-10-14-{real,recorded}.md, step 4
    nodes=23,
    parent=22,
    temporal=14,
    orphan_parent=0,
    unpaired_call=3,
    unknown=0,
    timestamp_unit_suspect=23,
)
_Z3 = Census(  # audit/z3-2026-10-13-{real,recorded}.md, step 4
    nodes=102,
    parent=101,
    temporal=48,
    orphan_parent=0,
    unpaired_call=48,
    unknown=0,
    timestamp_unit_suspect=102,
)
_Z4 = Census(  # audit/z4-2026-10-12-{real,recorded}.md, step 4
    nodes=4,
    parent=0,
    temporal=3,
    orphan_parent=4,
    unpaired_call=1,
    unknown=0,
    timestamp_unit_suspect=4,
)
_Z5 = Census(  # audit/z5-2026-10-13-{real,recorded}.md, step 4
    nodes=4,
    parent=2,
    temporal=2,
    orphan_parent=2,
    unpaired_call=0,
    unknown=0,
    timestamp_unit_suspect=4,
)

CAPTURES: tuple[Capture, ...] = (
    _capture("z1/2026-10-13-real", "40e8f3f6ace0600a1255ec9030397af7", (22, 9), _Z1),
    _capture("z1/2026-10-13-recorded", "a97e57e66afeaad79303a015a945515c", (31,), _Z1),
    _capture("z2/2026-10-14-real", "666cfbfe677c2822ddc8ee532d0903e6", (3, 15, 5), _Z2),
    _capture("z2/2026-10-14-recorded", "4af82ff37ed7031332c5112ccdfcdf39", (23,), _Z2),
    _capture(
        "z3/2026-10-13-real", "7a93d1ee6fc28e193585910fc2ce5906", (24, 32, 32, 14), _Z3
    ),
    _capture("z3/2026-10-13-recorded", "87d538e303fcbd1860df2b8c2fbb58f4", (102,), _Z3),
    # The root span, record 2 of the second body: claimed by no adapter and
    # routed to no trace (PROBES.md S1, L2; the report's step 3 lists it under
    # `(no trace id)`).
    _capture(
        "z4/2026-10-12-real",
        "612628c796e094bd26041bf735576133",
        (3, 2),
        _Z4,
        unrouted=(("0002.json", 2),),
    ),
    # The same root span, record 5 of the one body (PROBES.md S1, L2).
    _capture(
        "z4/2026-10-12-recorded",
        "9264505bc6b829dd4330b31460bef36f",
        (5,),
        _Z4,
        unrouted=(("0001.json", 5),),
    ),
    _capture("z5/2026-10-13-real", "3072629a56dca029bd8c19818bbebbc4", (4,), _Z5),
    _capture("z5/2026-10-13-recorded", "88167a239e683f6a5db73ac739bce4fe", (4,), _Z5),
    _capture(
        "z6/2026-10-14-real",
        "a5e74188438ca56d4f12f94d2651b49b",
        (2, 2, 4, 1, 2, 2, 3, 3, 2, 2, 3),
        Census(  # audit/z6-2026-10-14-real.md, step 4
            nodes=26,
            parent=25,
            temporal=18,
            orphan_parent=0,
            unpaired_call=8,
            unknown=0,
            timestamp_unit_suspect=26,
        ),
    ),
    _capture(
        "z6/2026-10-14-recorded",
        "8766332238a4971b8dc6ffef5b6fb97c",
        (16,),
        Census(  # audit/z6-2026-10-14-recorded.md, step 4
            nodes=16,
            parent=15,
            temporal=10,
            orphan_parent=0,
            unpaired_call=4,
            unknown=0,
            timestamp_unit_suspect=16,
        ),
    ),
)


@dataclass(frozen=True)
class Record:
    """One record `read_records` yielded, and where it sat."""

    body: str
    index: int
    record: JsonValue


def bodies(capture: Capture) -> list[pathlib.Path]:
    """The capture's bodies, in body order (`NNNN.json`)."""
    return sorted((ZOO / capture.run).glob("[0-9][0-9][0-9][0-9].json"))


def records(capture: Capture) -> list[Record]:
    """Every record of every body, in body order, as `read_records` yields it.

    A body the reader could not read whole is a failure here, not a smaller
    census: each read's diagnostics are returned to the caller to assert on.
    """
    out: list[Record] = []
    for body in bodies(capture):
        read = spanweave.read_records(body.read_bytes())
        if read.diagnostics or read.skipped_records:
            raise AssertionError(f"{capture.run}/{body.name}: {read.diagnostics}")
        out.extend(
            Record(body.name, index, record)
            for index, record in enumerate(read.records, start=1)
        )
    return out


def audit_feed(capture: Capture) -> list[JsonValue]:
    """The records the audit fed the trace's build, in the order it fed them."""
    skip = set(capture.unrouted)
    return [r.record for r in records(capture) if (r.body, r.index) not in skip]


def count(graph: spanweave.Graph) -> Census:
    """The census of one graph."""
    edges = collections.Counter(edge.kind for edge in graph.edges())
    codes = collections.Counter(d.code for d in graph.diagnostics)
    return Census(
        nodes=len(graph.nodes()),
        parent=edges[spanweave.EdgeKind.PARENT],
        temporal=edges[spanweave.EdgeKind.TEMPORAL],
        orphan_parent=codes["orphan_parent"],
        unpaired_call=codes["unpaired_call"],
        unknown=sum(n.kind is spanweave.NodeKind.UNKNOWN for n in graph.nodes()),
        timestamp_unit_suspect=codes["timestamp_unit_suspect"],
    )


def batch_and_incremental(feed: list[JsonValue]) -> tuple[bytes, bytes]:
    """The batch graph of a feed and the `Builder`'s, each as canonical bytes.

    The `Builder` is fed one record at a time in the order given -- the
    exporter's, child before parent (`PROBES.md` S15) -- and is held to the
    batch graph of the same records (`SPEC.md` §10.1).
    """
    builder = spanweave.Builder()
    for record in feed:
        builder.feed(record)
    return spanweave.dumps(graph_from_records(feed)), spanweave.dumps(builder.graph())


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(capture: Capture) -> dict[str, object]:
    document = json.loads((ZOO / capture.run / "MANIFEST.json").read_bytes())
    assert isinstance(document, dict)
    return document


def seal_of(document: dict[str, object]) -> str:
    """The seal a zoo manifest carries: the zoo's `SPEC.md` §5, "The seal"."""
    unsealed = {key: value for key, value in document.items() if key != "seal"}
    text = json.dumps(
        unsealed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def main() -> None:  # pragma: no cover -- `python -m tests.zoo_census`
    names = [field.name for field in fields(Census)]
    print("capture", *names, sep="\t")
    for capture in CAPTURES:
        graph = graph_from_records(audit_feed(capture))
        found = count(graph)
        print(capture.run, *(getattr(found, n) for n in names), sep="\t")
        if found != capture.census:
            print("  census:", *(getattr(capture.census, n) for n in names), sep="\t")


if __name__ == "__main__":  # pragma: no cover
    main()
