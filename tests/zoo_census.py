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
order, child before parent as the exporter wrote them and grouped by scope
within each body (`PROBES.md` S15, S21; `exporter_order` and `scope_runs`
count both, and `tests/test_zoo.py` holds them) -- except, on Z4, the root
span `concierge.conversation`, which no adapter claims and which the receiver
routed to no trace (`PROBES.md` S1, L2). That record is named in
`Capture.unrouted`, and `Capture.whole` holds what the **whole** capture
builds to beside it -- the `unknown` node `SPEC.md` §6.1 makes of a
record no adapter claims, keyed and placed by its OTLP envelope since batch T1
(§3.6 rule 1, `OPEN_QUESTIONS.md` §20). The whole capture is not a number any
report gives; it is this library's own count, each move from the audit's
explained where it is stated, and it is kept separate so neither is mistaken
for the other.

**The census is the instrument, not the verdict.** A later change that moves a
count updates `CAPTURES` in its own commit and says why there; one that moves
a node's position, an edge or its basis updates `STRUCTURES` (or
`WHOLE_STRUCTURES`) the same way. The diff of this file across a series is
that series' effect on a stranger's trace.

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
    #: Since batch T3, which moved it on Z2 and Z3 (`_Z2`, `_Z3`): the report's
    #: count, less the nodes that reported nothing but the OTLP envelope.
    unmapped_attributes: int
    #: Since batch T3: one per span whose export states a dropped-attribute
    #: count above zero. No report counts it -- the code did not exist.
    attributes_dropped: int
    #: Since batch T4: one per OTLP span event the export states, by its
    #: name -- `exception_event` for an `exception` event, `span_event` for any
    #: other. No report counts either: the codes did not exist, and the
    #: events were one unmapped `<record>.events` key, never the only one.
    exception_event: int
    span_event: int


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
    #: The instrumentation scope names the capture's records state, every
    #: record of every body, each read from the record's OTLP envelope
    #: (`spanweave.envelope(record).scope`, batch T3; `PROBES.md` S6, S21).
    #: A set and not a value: Z3, Z4 and Z6 state two each.
    scopes: frozenset[str]
    #: `(body, record)` (1-based, as the reports number them) of each record the
    #: audit's step 3 did not feed to the trace, with the probe that says why.
    unrouted: tuple[tuple[str, int], ...] = ()
    #: What every record of every body builds to, where the audit fed fewer
    #: (`unrouted`). Not a report's number: this library's, with each count
    #: that differs from `census` explained beside it.
    whole: Census | None = None


@dataclass(frozen=True)
class Structure:
    """One graph's node order and its edges, each with its basis.

    What `Census` counts, it does not place: a batch that kept every count could
    still move a node, an edge or a basis. This holds each, in the order
    `Graph.nodes()` and `Graph.edges()` give them (`SPEC.md` §5.2), so a change
    that moves one has to say so here (decisions 2026-10-14g, R-10).
    """

    nodes: tuple[str, ...]
    #: `(kind, src, dst, basis)`: the warrant follows the kind (`SPEC.md` §4).
    edges: tuple[tuple[str, str, str, str], ...]


def _structure(nodes: str, edges: str) -> Structure:
    """A `Structure` from its text: node ids by whitespace; one edge per line,
    `kind src dst basis`, the basis being the rest of the line verbatim."""
    parsed: list[tuple[str, str, str, str]] = []
    for line in edges.strip().splitlines():
        kind, src, dst, basis = line.strip().split(" ", 3)
        parsed.append((kind, src, dst, basis))
    return Structure(tuple(nodes.split()), tuple(parsed))


def _report(run: str) -> str:
    return "audit/" + run.replace("/", "-") + ".md"


def _capture(
    run: str,
    trace_id: str,
    records_per_body: tuple[int, ...],
    census: Census,
    scopes: frozenset[str],
    unrouted: tuple[tuple[str, int], ...] = (),
    whole: Census | None = None,
) -> Capture:
    return Capture(
        run, _report(run), trace_id, records_per_body, census, scopes, unrouted, whole
    )


# Each `Census(...)` is the step 4 `inspect` block of the report its `Capture`
# names: `nodes`, `parent (explicit)`, `temporal (derived)`, and the
# diagnostics `orphan_parent`, `unpaired_call`, `timestamp_unit_suspect` and the
# node kind `unknown` -- a count the block does not list is 0 there. Two
# captures of one project whose reports give the same block share a line.
#
# **One count no longer is the report's: `timestamp_unit_suspect`.** Every
# report counts one per node -- every span of every capture is an OTLP span
# whose `startTimeUnixNano` / `endTimeUnixNano` were read as reported, past
# §3.1's 1e11 line. Since batch T2 (`SPEC.md` §3.1, §7; `PROBES.md` S3) a time
# whose field declares nanoseconds is read in unix seconds -- the string the
# export wrote stays verbatim in `raw.source` -- and the suspicion is kept for
# a value whose unit nothing declared, so every capture here draws 0. Each
# line keeps the report's number beside it. Nothing else moved: on all twelve
# captures, audit feed and whole, the edges (with their bases) and the node
# order are the same as before T2, with no tied `temporal` edge. That was a
# hand check at T2 (R-10 repeated it); since decisions 2026-10-14g commit 7
# `STRUCTURES` and `WHOLE_STRUCTURES` (below) hold all three, every run.
#
# **Two counts joined at batch T3, and one of them moved: `unmapped_attributes`.**
# The report's block lists it, and every unpacked node of every capture named
# the four keys of its OTLP envelope there -- `<record>.flags`, `.kind`,
# `.resource_spans`, `.scope_spans` -- with Z3's 18 spans that state a
# `droppedAttributesCount` naming that too. Since T3 (`SPEC.md` §3.7, §7;
# `PROBES.md` S4, S7, S8) the four are the envelope rather than unmapped span
# keys, so they stay in `raw.source` and are named nowhere, and a dropped count
# is the `attributes_dropped` warning instead. A node whose diagnostic named
# nothing else loses it: Z2 23 -> 9, Z3 102 -> 75. On the other eight captures
# every node also left a span key unmapped, so the count holds while each
# diagnostic names four keys fewer. `attributes_dropped` is new with the code,
# and only Z3's export states a count above zero.
#
# **Two more joined at batch T4: `exception_event` and `span_event`.** An OTLP
# span's `events` were one unmapped `<record>.events` key; since T4 (`SPEC.md`
# §3.7, §7; `OPEN_QUESTIONS.md` §22, option 2; `PROBES.md` S11, S17) each
# event is an `info` diagnostic on its node and the key is no longer named.
# Only Z2 and Z5 state events, and on neither was `<record>.events` the only
# key a node left unmapped, so `unmapped_attributes` holds on both. Z2's two
# `First Token Stream Event`s per capture (`-real`: one each in 0002 and 0003;
# `-recorded`: two in 0001) are `span_event`s; Z5's two `exception` events,
# one on each failed `http_get`, are `exception_event`s.
#
# **One count moved at batch T5: `temporal`, on Z5 only.** A sibling group is
# the parent a record *states* (`SPEC.md` §4.3; `PROBES.md` S18): a root's
# group is "no parent", an orphan's is the id it named. Z5's feed holds no root:
# `fetch` names one absent parent and the second `http_get` another, and both
# sat at trace root, chained -- an order between two nodes the telemetry puts
# under different parents. They are now two groups of one, so Z5 2 -> 1 on both
# captures. Every other count holds: no other feed holds orphans naming
# different parents (Z4's audit feed has four, all naming the absent root), so
# no other group moved.
_Z1 = Census(  # audit/z1-2026-10-13-{real,recorded}.md, step 4
    nodes=31,
    parent=30,
    temporal=16,
    orphan_parent=0,
    unpaired_call=1,
    unknown=2,
    timestamp_unit_suspect=0,  # report: 31; 0 since T2 (above)
    unmapped_attributes=31,  # the report's; each names four keys fewer since T3
    attributes_dropped=0,
    exception_event=0,
    span_event=0,
)
_Z2 = Census(  # audit/z2-2026-10-14-{real,recorded}.md, step 4
    nodes=23,
    parent=22,
    temporal=14,
    orphan_parent=0,
    unpaired_call=3,
    unknown=0,
    timestamp_unit_suspect=0,  # report: 23; 0 since T2 (above)
    # report: 23; 9 since T3 (above) -- 14 nodes reported only the envelope.
    unmapped_attributes=9,
    attributes_dropped=0,
    exception_event=0,
    # 2 since T4 (above): the two `First Token Stream Event`s.
    span_event=2,
)
_Z3 = Census(  # audit/z3-2026-10-13-{real,recorded}.md, step 4
    nodes=102,
    parent=101,
    temporal=48,
    orphan_parent=0,
    unpaired_call=48,
    unknown=0,
    timestamp_unit_suspect=0,  # report: 102; 0 since T2 (above)
    # report: 102; 75 since T3 (above) -- 27 nodes reported only the envelope,
    # none of them a span that states a dropped count.
    unmapped_attributes=75,
    # 18 since T3: the spans whose `droppedAttributesCount` is above zero.
    attributes_dropped=18,
    exception_event=0,
    span_event=0,
)
_Z4 = Census(  # audit/z4-2026-10-12-{real,recorded}.md, step 4
    nodes=4,
    parent=0,
    temporal=3,
    orphan_parent=4,
    unpaired_call=1,
    unknown=0,
    timestamp_unit_suspect=0,  # report: 4; 0 since T2 (above)
    unmapped_attributes=4,  # the report's; each names four keys fewer since T3
    attributes_dropped=0,
    exception_event=0,
    span_event=0,
)
# Z4's whole capture: the audit's four records plus the root span
# `concierge.conversation`, which no adapter claims. Moved at batch T1, when an
# unclaimed OTLP record became keyed and placed by its envelope (SPEC.md §3.6
# rule 1, §6.1; OPEN_QUESTIONS.md §20, option 1; PROBES.md S1, S2, S12):
_Z4_WHOLE = Census(
    nodes=5,  # the audit's 4 + the root, an `unknown` node (§6.1)
    # 0 -> 4: the root's node id is its span id `3013a003149d6951` (was a
    # derived `sw_` id), which is the parent each of the four `llm` spans
    # states -- four `explicit` edges the telemetry stated.
    parent=4,
    # 3, unchanged in number: the four children are still the one sibling
    # group, now under the root rather than at trace root; the root has no
    # sibling, so it adds none.
    temporal=3,
    # 4 -> 0: the parent the four children name is the root, and it is here.
    orphan_parent=0,
    unpaired_call=1,  # unchanged: an `llm` span's, not the root's
    unknown=1,  # the root
    # 4 -> 5 at T1: the root gained the times its envelope states, read by
    # §3.1 as every other span's are, so it drew the same
    # `timestamp_unit_suspect` (§7) -- and its `missing_timestamp` was gone.
    # 5 -> 0 at T2, with every other capture's (above).
    timestamp_unit_suspect=0,
    # The audit's 4: the root is unclaimed, and an unclaimed node reports
    # `unclaimed_record`, never `unmapped_attributes` (§6.1).
    unmapped_attributes=4,
    attributes_dropped=0,
    exception_event=0,
    span_event=0,
)
_Z5 = Census(  # audit/z5-2026-10-13-{real,recorded}.md, step 4
    nodes=4,
    parent=2,
    # Report: 2; 1 since T5 (above): the edge between `fetch` and the second
    # `http_get` is gone -- both are orphans, stating different absent parents.
    temporal=1,
    orphan_parent=2,
    unpaired_call=0,
    unknown=0,
    timestamp_unit_suspect=0,  # report: 4; 0 since T2 (above)
    unmapped_attributes=4,  # the report's; each names four keys fewer since T3
    attributes_dropped=0,
    # 2 since T4 (above): the two `ConnectionError`s, one per failed `http_get`.
    exception_event=2,
    span_event=0,
)

#: The instrumentation scopes the captures state (`Capture.scopes`).
_LANGCHAIN = "openinference.instrumentation.langchain"
_LLAMA_INDEX = "openinference.instrumentation.llama_index"
_OPENAI = "openinference.instrumentation.openai"
_OPENAI_AGENTS = "openinference.instrumentation.openai_agents"
_CREWAI = "openinference.instrumentation.crewai"
_GENAI = "opentelemetry.util.genai.handler"
_Z1_SCOPES = frozenset({_LANGCHAIN})
_Z2_SCOPES = frozenset({_LLAMA_INDEX})
# Two instrumentors on one client (`PROBES.md` S6): the agents SDK's spans and
# the OpenAI client's beneath them, on one graph.
_Z3_SCOPES = frozenset({_OPENAI_AGENTS, _OPENAI})
# The GenAI handler's four `llm` spans, and the root span the application
# opened itself under a tracer it named after itself -- the one no adapter
# claims (S1), so the audit's feed carries only the first.
_Z4_SCOPES = frozenset({_GENAI, "streaming-concierge"})
_Z5_SCOPES = frozenset({_LANGCHAIN})
_Z6_SCOPES = frozenset({_CREWAI, _OPENAI})

CAPTURES: tuple[Capture, ...] = (
    _capture(
        "z1/2026-10-13-real",
        "40e8f3f6ace0600a1255ec9030397af7",
        (22, 9),
        _Z1,
        _Z1_SCOPES,
    ),
    _capture(
        "z1/2026-10-13-recorded",
        "a97e57e66afeaad79303a015a945515c",
        (31,),
        _Z1,
        _Z1_SCOPES,
    ),
    _capture(
        "z2/2026-10-14-real",
        "666cfbfe677c2822ddc8ee532d0903e6",
        (3, 15, 5),
        _Z2,
        _Z2_SCOPES,
    ),
    _capture(
        "z2/2026-10-14-recorded",
        "4af82ff37ed7031332c5112ccdfcdf39",
        (23,),
        _Z2,
        _Z2_SCOPES,
    ),
    _capture(
        "z3/2026-10-13-real",
        "7a93d1ee6fc28e193585910fc2ce5906",
        (24, 32, 32, 14),
        _Z3,
        _Z3_SCOPES,
    ),
    _capture(
        "z3/2026-10-13-recorded",
        "87d538e303fcbd1860df2b8c2fbb58f4",
        (102,),
        _Z3,
        _Z3_SCOPES,
    ),
    # The root span, record 2 of the second body: claimed by no adapter and
    # routed to no trace (PROBES.md S1, L2; the report's step 3 lists it under
    # `(no trace id)`).
    _capture(
        "z4/2026-10-12-real",
        "612628c796e094bd26041bf735576133",
        (3, 2),
        _Z4,
        _Z4_SCOPES,
        unrouted=(("0002.json", 2),),
        whole=_Z4_WHOLE,
    ),
    # The same root span, record 5 of the one body (PROBES.md S1, L2).
    _capture(
        "z4/2026-10-12-recorded",
        "9264505bc6b829dd4330b31460bef36f",
        (5,),
        _Z4,
        _Z4_SCOPES,
        unrouted=(("0001.json", 5),),
        whole=_Z4_WHOLE,
    ),
    _capture(
        "z5/2026-10-13-real", "3072629a56dca029bd8c19818bbebbc4", (4,), _Z5, _Z5_SCOPES
    ),
    _capture(
        "z5/2026-10-13-recorded",
        "88167a239e683f6a5db73ac739bce4fe",
        (4,),
        _Z5,
        _Z5_SCOPES,
    ),
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
            timestamp_unit_suspect=0,  # report: 26; 0 since T2 (above)
            unmapped_attributes=26,  # the report's; four keys fewer since T3
            attributes_dropped=0,
            exception_event=0,
            span_event=0,
        ),
        _Z6_SCOPES,
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
            timestamp_unit_suspect=0,  # report: 16; 0 since T2 (above)
            unmapped_attributes=16,  # the report's; four keys fewer since T3
            attributes_dropped=0,
            exception_event=0,
            span_event=0,
        ),
        _Z6_SCOPES,
    ),
)

# Each capture's audit-feed graph, placed (`Structure`), keyed by `Capture.run`:
# the census above counts, this holds where each node sits and what each edge
# joins and on what basis. Re-derived from the bodies on every run and held
# batch and incremental alike (`tests/test_zoo.py`). Not a report's: no report
# lists edges. Taken from this library's output at decisions 2026-10-14g
# commit 7, where it equals the hand check R-10 records (node order, every edge
# and basis, the same before and after batch T2), so from here "nothing moved"
# is a gate, not a claim. A change that moves one moves it here, with the reason.
STRUCTURES: dict[str, Structure] = {
    "z1/2026-10-13-real": _structure(
        """
        bd08a2148df084bc 73e3edd2fc491888 bc88f958b4e7b638 8e751fd2050f46d4
        bf207c306c0f583c 8f54deb409dad9d7 9833521556552bed b920656c39cb92a4
        4f986f6c18a578ca ce4c613ecbaac15c 0096022f69c80b94 df4e7bd70f4edf20
        41e08f653dcd9619 84d26cf1c3cbfe61 c8f9b88d62e9a54b 3d5d28bf3a41c2d2
        4b2bac1184d8aac9 877813bb1f19dc5e 808dc173888615de 6c17e931ae4a5989
        de9709a4a4be62f2 64171e698a5f787d c27097b50658e7c6 e7cde30149b4895b
        898632359c6f7de1 fb5a00c15fff11d1 e0e1f2785bd03602 04704daf4e5e5376
        a778a3843333fc78 6f62178fc7c680fb d21a27763ae7b79a
        """,
        """
        parent 3d5d28bf3a41c2d2 4b2bac1184d8aac9 span.parent_span_id
        parent 4b2bac1184d8aac9 808dc173888615de span.parent_span_id
        parent 4b2bac1184d8aac9 877813bb1f19dc5e span.parent_span_id
        parent 4f986f6c18a578ca ce4c613ecbaac15c span.parent_span_id
        parent 6f62178fc7c680fb d21a27763ae7b79a span.parent_span_id
        parent 73e3edd2fc491888 bc88f958b4e7b638 span.parent_span_id
        parent 808dc173888615de 64171e698a5f787d span.parent_span_id
        parent 808dc173888615de 6c17e931ae4a5989 span.parent_span_id
        parent 808dc173888615de c27097b50658e7c6 span.parent_span_id
        parent 808dc173888615de de9709a4a4be62f2 span.parent_span_id
        parent 808dc173888615de e7cde30149b4895b span.parent_span_id
        parent 8e751fd2050f46d4 bf207c306c0f583c span.parent_span_id
        parent 8f54deb409dad9d7 898632359c6f7de1 span.parent_span_id
        parent 8f54deb409dad9d7 9833521556552bed span.parent_span_id
        parent 8f54deb409dad9d7 b920656c39cb92a4 span.parent_span_id
        parent 8f54deb409dad9d7 c8f9b88d62e9a54b span.parent_span_id
        parent 8f54deb409dad9d7 fb5a00c15fff11d1 span.parent_span_id
        parent b920656c39cb92a4 4f986f6c18a578ca span.parent_span_id
        parent bd08a2148df084bc 6f62178fc7c680fb span.parent_span_id
        parent bd08a2148df084bc 73e3edd2fc491888 span.parent_span_id
        parent bd08a2148df084bc 8e751fd2050f46d4 span.parent_span_id
        parent bf207c306c0f583c 8f54deb409dad9d7 span.parent_span_id
        parent c8f9b88d62e9a54b 3d5d28bf3a41c2d2 span.parent_span_id
        parent ce4c613ecbaac15c 0096022f69c80b94 span.parent_span_id
        parent ce4c613ecbaac15c 41e08f653dcd9619 span.parent_span_id
        parent ce4c613ecbaac15c 84d26cf1c3cbfe61 span.parent_span_id
        parent ce4c613ecbaac15c df4e7bd70f4edf20 span.parent_span_id
        parent fb5a00c15fff11d1 04704daf4e5e5376 span.parent_span_id
        parent fb5a00c15fff11d1 a778a3843333fc78 span.parent_span_id
        parent fb5a00c15fff11d1 e0e1f2785bd03602 span.parent_span_id
        temporal 0096022f69c80b94 df4e7bd70f4edf20 sibling start_time ordering
        temporal 04704daf4e5e5376 a778a3843333fc78 sibling start_time ordering
        temporal 41e08f653dcd9619 84d26cf1c3cbfe61 sibling start_time ordering
        temporal 64171e698a5f787d c27097b50658e7c6 sibling start_time ordering
        temporal 6c17e931ae4a5989 de9709a4a4be62f2 sibling start_time ordering
        temporal 73e3edd2fc491888 8e751fd2050f46d4 sibling start_time ordering
        temporal 877813bb1f19dc5e 808dc173888615de sibling start_time ordering
        temporal 898632359c6f7de1 fb5a00c15fff11d1 sibling start_time ordering
        temporal 8e751fd2050f46d4 6f62178fc7c680fb sibling start_time ordering
        temporal 9833521556552bed b920656c39cb92a4 sibling start_time ordering
        temporal b920656c39cb92a4 c8f9b88d62e9a54b sibling start_time ordering
        temporal c27097b50658e7c6 e7cde30149b4895b sibling start_time ordering
        temporal c8f9b88d62e9a54b 898632359c6f7de1 sibling start_time ordering
        temporal de9709a4a4be62f2 64171e698a5f787d sibling start_time ordering
        temporal df4e7bd70f4edf20 41e08f653dcd9619 sibling start_time ordering
        temporal e0e1f2785bd03602 04704daf4e5e5376 sibling start_time ordering
        """,
    ),
    "z1/2026-10-13-recorded": _structure(
        """
        19b58c36ccca6627 9c03f3ce7255adfa d65c8a757c33a1ea 8b5b194ed47af936
        4b292064ede9bc73 a41396e97d813486 21fa969bc0ad80d7 3ae6300e59d0a2af
        2a4182552911d55f 3d0acb7a98994867 b1946cac4f53b3f1 03003a0f0472b46a
        3d9306c56b6df716 1c647f30113f92f0 b7ed6e5e5e65d4ca ee7620204588929c
        c7ff52369038097c 092d40e1c03be725 7b90b1fcac623421 e45c892523a79c1d
        abcb7d0757343e5e cc4974dc8958fc1a 898fcb1d05870a55 99a24b115380d828
        6bdc2e4cd01860a0 f0106dfcaca83836 ce2ca6162ca67c60 eddf6a6b5613c8b0
        f0d64f953a8e8562 8771765b60702688 61574cf253b78605
        """,
        """
        parent 19b58c36ccca6627 8771765b60702688 span.parent_span_id
        parent 19b58c36ccca6627 8b5b194ed47af936 span.parent_span_id
        parent 19b58c36ccca6627 9c03f3ce7255adfa span.parent_span_id
        parent 2a4182552911d55f 3d0acb7a98994867 span.parent_span_id
        parent 3ae6300e59d0a2af 2a4182552911d55f span.parent_span_id
        parent 3d0acb7a98994867 03003a0f0472b46a span.parent_span_id
        parent 3d0acb7a98994867 1c647f30113f92f0 span.parent_span_id
        parent 3d0acb7a98994867 3d9306c56b6df716 span.parent_span_id
        parent 3d0acb7a98994867 b1946cac4f53b3f1 span.parent_span_id
        parent 4b292064ede9bc73 a41396e97d813486 span.parent_span_id
        parent 7b90b1fcac623421 898fcb1d05870a55 span.parent_span_id
        parent 7b90b1fcac623421 99a24b115380d828 span.parent_span_id
        parent 7b90b1fcac623421 abcb7d0757343e5e span.parent_span_id
        parent 7b90b1fcac623421 cc4974dc8958fc1a span.parent_span_id
        parent 7b90b1fcac623421 e45c892523a79c1d span.parent_span_id
        parent 8771765b60702688 61574cf253b78605 span.parent_span_id
        parent 8b5b194ed47af936 4b292064ede9bc73 span.parent_span_id
        parent 9c03f3ce7255adfa d65c8a757c33a1ea span.parent_span_id
        parent a41396e97d813486 21fa969bc0ad80d7 span.parent_span_id
        parent a41396e97d813486 3ae6300e59d0a2af span.parent_span_id
        parent a41396e97d813486 6bdc2e4cd01860a0 span.parent_span_id
        parent a41396e97d813486 b7ed6e5e5e65d4ca span.parent_span_id
        parent a41396e97d813486 f0106dfcaca83836 span.parent_span_id
        parent b7ed6e5e5e65d4ca ee7620204588929c span.parent_span_id
        parent c7ff52369038097c 092d40e1c03be725 span.parent_span_id
        parent c7ff52369038097c 7b90b1fcac623421 span.parent_span_id
        parent ee7620204588929c c7ff52369038097c span.parent_span_id
        parent f0106dfcaca83836 ce2ca6162ca67c60 span.parent_span_id
        parent f0106dfcaca83836 eddf6a6b5613c8b0 span.parent_span_id
        parent f0106dfcaca83836 f0d64f953a8e8562 span.parent_span_id
        temporal 03003a0f0472b46a 3d9306c56b6df716 sibling start_time ordering
        temporal 092d40e1c03be725 7b90b1fcac623421 sibling start_time ordering
        temporal 21fa969bc0ad80d7 3ae6300e59d0a2af sibling start_time ordering
        temporal 3ae6300e59d0a2af b7ed6e5e5e65d4ca sibling start_time ordering
        temporal 3d9306c56b6df716 1c647f30113f92f0 sibling start_time ordering
        temporal 6bdc2e4cd01860a0 f0106dfcaca83836 sibling start_time ordering
        temporal 898fcb1d05870a55 99a24b115380d828 sibling start_time ordering
        temporal 8b5b194ed47af936 8771765b60702688 sibling start_time ordering
        temporal 9c03f3ce7255adfa 8b5b194ed47af936 sibling start_time ordering
        temporal abcb7d0757343e5e cc4974dc8958fc1a sibling start_time ordering
        temporal b1946cac4f53b3f1 03003a0f0472b46a sibling start_time ordering
        temporal b7ed6e5e5e65d4ca 6bdc2e4cd01860a0 sibling start_time ordering
        temporal cc4974dc8958fc1a 898fcb1d05870a55 sibling start_time ordering
        temporal ce2ca6162ca67c60 eddf6a6b5613c8b0 sibling start_time ordering
        temporal e45c892523a79c1d abcb7d0757343e5e sibling start_time ordering
        temporal eddf6a6b5613c8b0 f0d64f953a8e8562 sibling start_time ordering
        """,
    ),
    "z2/2026-10-14-real": _structure(
        """
        86a464c4b18af821 c53d458dde4e4a12 315ed06c6c80d472 539a254a824d5e2a
        013c6a9b437679a2 da6c5422d132ace1 55d6988ab7075459 90f9213ae011b800
        0b76f56ee6e637fb 2f42891bc379dbb4 6610971780590a14 1d1e1964ed3f7c4e
        00889eb3593de58c 20788a74b1c43ece a6dd7bd6e5d950e6 6fcbcc8fb5ba60dd
        d1cced78669c290b c617d3f115e8801c 727933145969a7fe 716ca47344fbdff2
        659be38850f33552 db1c06636eb889b0 5c531cad185e514e
        """,
        """
        parent 00889eb3593de58c 20788a74b1c43ece span.parent_span_id
        parent 0b76f56ee6e637fb 2f42891bc379dbb4 span.parent_span_id
        parent 539a254a824d5e2a 013c6a9b437679a2 span.parent_span_id
        parent 539a254a824d5e2a da6c5422d132ace1 span.parent_span_id
        parent 659be38850f33552 db1c06636eb889b0 span.parent_span_id
        parent 6610971780590a14 1d1e1964ed3f7c4e span.parent_span_id
        parent 727933145969a7fe 659be38850f33552 span.parent_span_id
        parent 727933145969a7fe 716ca47344fbdff2 span.parent_span_id
        parent 86a464c4b18af821 00889eb3593de58c span.parent_span_id
        parent 86a464c4b18af821 0b76f56ee6e637fb span.parent_span_id
        parent 86a464c4b18af821 315ed06c6c80d472 span.parent_span_id
        parent 86a464c4b18af821 539a254a824d5e2a span.parent_span_id
        parent 86a464c4b18af821 5c531cad185e514e span.parent_span_id
        parent 86a464c4b18af821 6610971780590a14 span.parent_span_id
        parent 86a464c4b18af821 6fcbcc8fb5ba60dd span.parent_span_id
        parent 86a464c4b18af821 727933145969a7fe span.parent_span_id
        parent 86a464c4b18af821 90f9213ae011b800 span.parent_span_id
        parent 86a464c4b18af821 a6dd7bd6e5d950e6 span.parent_span_id
        parent 86a464c4b18af821 c53d458dde4e4a12 span.parent_span_id
        parent 86a464c4b18af821 c617d3f115e8801c span.parent_span_id
        parent 86a464c4b18af821 d1cced78669c290b span.parent_span_id
        parent da6c5422d132ace1 55d6988ab7075459 span.parent_span_id
        temporal 00889eb3593de58c a6dd7bd6e5d950e6 sibling start_time ordering
        temporal 013c6a9b437679a2 da6c5422d132ace1 sibling start_time ordering
        temporal 0b76f56ee6e637fb 6610971780590a14 sibling start_time ordering
        temporal 315ed06c6c80d472 539a254a824d5e2a sibling start_time ordering
        temporal 539a254a824d5e2a 90f9213ae011b800 sibling start_time ordering
        temporal 6610971780590a14 00889eb3593de58c sibling start_time ordering
        temporal 6fcbcc8fb5ba60dd d1cced78669c290b sibling start_time ordering
        temporal 716ca47344fbdff2 659be38850f33552 sibling start_time ordering
        temporal 727933145969a7fe 5c531cad185e514e sibling start_time ordering
        temporal 90f9213ae011b800 0b76f56ee6e637fb sibling start_time ordering
        temporal a6dd7bd6e5d950e6 6fcbcc8fb5ba60dd sibling start_time ordering
        temporal c53d458dde4e4a12 315ed06c6c80d472 sibling start_time ordering
        temporal c617d3f115e8801c 727933145969a7fe sibling start_time ordering
        temporal d1cced78669c290b c617d3f115e8801c sibling start_time ordering
        """,
    ),
    "z2/2026-10-14-recorded": _structure(
        """
        3d0d2a04012f771a 3c8d26586cf5803e eff2d4d5bb876aba b23d6d368337fc12
        7c3a092d29ac7325 496114e460d83551 da618221c331ae9b d216248babaac9bb
        c0023fa62b353993 dbe920d1658b385c e6c9873d9b1d5dcb 253264b8d31b6e8d
        8ba9e9b994b4ebde 4a08209acab845ee 6d6aa1c01cf72ec5 740d00c85ac7a84c
        395808b5fae2f3bb 3a47eff257b192a0 a72533f7cab14151 6b718438ea4429d2
        f0af299579ec4d5e 72dca99b6ea6d9b6 95ed9c15c9113db9
        """,
        """
        parent 3d0d2a04012f771a 395808b5fae2f3bb span.parent_span_id
        parent 3d0d2a04012f771a 3a47eff257b192a0 span.parent_span_id
        parent 3d0d2a04012f771a 3c8d26586cf5803e span.parent_span_id
        parent 3d0d2a04012f771a 6d6aa1c01cf72ec5 span.parent_span_id
        parent 3d0d2a04012f771a 740d00c85ac7a84c span.parent_span_id
        parent 3d0d2a04012f771a 8ba9e9b994b4ebde span.parent_span_id
        parent 3d0d2a04012f771a 95ed9c15c9113db9 span.parent_span_id
        parent 3d0d2a04012f771a a72533f7cab14151 span.parent_span_id
        parent 3d0d2a04012f771a b23d6d368337fc12 span.parent_span_id
        parent 3d0d2a04012f771a c0023fa62b353993 span.parent_span_id
        parent 3d0d2a04012f771a d216248babaac9bb span.parent_span_id
        parent 3d0d2a04012f771a e6c9873d9b1d5dcb span.parent_span_id
        parent 3d0d2a04012f771a eff2d4d5bb876aba span.parent_span_id
        parent 496114e460d83551 da618221c331ae9b span.parent_span_id
        parent 8ba9e9b994b4ebde 4a08209acab845ee span.parent_span_id
        parent a72533f7cab14151 6b718438ea4429d2 span.parent_span_id
        parent a72533f7cab14151 f0af299579ec4d5e span.parent_span_id
        parent b23d6d368337fc12 496114e460d83551 span.parent_span_id
        parent b23d6d368337fc12 7c3a092d29ac7325 span.parent_span_id
        parent c0023fa62b353993 dbe920d1658b385c span.parent_span_id
        parent e6c9873d9b1d5dcb 253264b8d31b6e8d span.parent_span_id
        parent f0af299579ec4d5e 72dca99b6ea6d9b6 span.parent_span_id
        temporal 395808b5fae2f3bb 3a47eff257b192a0 sibling start_time ordering
        temporal 3a47eff257b192a0 a72533f7cab14151 sibling start_time ordering
        temporal 3c8d26586cf5803e eff2d4d5bb876aba sibling start_time ordering
        temporal 6b718438ea4429d2 f0af299579ec4d5e sibling start_time ordering
        temporal 6d6aa1c01cf72ec5 740d00c85ac7a84c sibling start_time ordering
        temporal 740d00c85ac7a84c 395808b5fae2f3bb sibling start_time ordering
        temporal 7c3a092d29ac7325 496114e460d83551 sibling start_time ordering
        temporal 8ba9e9b994b4ebde 6d6aa1c01cf72ec5 sibling start_time ordering
        temporal a72533f7cab14151 95ed9c15c9113db9 sibling start_time ordering
        temporal b23d6d368337fc12 d216248babaac9bb sibling start_time ordering
        temporal c0023fa62b353993 e6c9873d9b1d5dcb sibling start_time ordering
        temporal d216248babaac9bb c0023fa62b353993 sibling start_time ordering
        temporal e6c9873d9b1d5dcb 8ba9e9b994b4ebde sibling start_time ordering
        temporal eff2d4d5bb876aba b23d6d368337fc12 sibling start_time ordering
        """,
    ),
    "z3/2026-10-13-real": _structure(
        """
        448817e27ad9f3b1 44c37d1babb13ad6 688d0f87480817ad 887955e8a795154a
        7fcda7be6e333e37 f1cefb8fb89bcd86 cca878b6ea70211d 2521eae5c590a03f
        72d7873eed87a902 c9ba3fa79c7d99fc d7bfaf6170ace63d 51efd36f1d62b407
        634c89a6a084ddd0 0c06cb7d271d3078 f76bce43066356af d49ebf7507abce82
        e6eeca5ea8cbf348 fc864884950f371f 8a37b272a2facf97 f9504762f4a5f835
        214b0c00a8aa6716 3199a3434bb85b38 61dab2219b9001e1 073b28329995bf54
        c746db169a73863f 369faba861788c7f 581ea87efe26916d 32061189de158286
        da6c0ee070aa97c2 a80acb601c6083dc 468225a1bea00365 f4b312bcd0672256
        903b929484df0324 4db0bf5370207e5a 9a7a0336849397e3 b890eb22c9ee4d5e
        6867a209850a499c 43a7a53f9d4e7294 6b0cdd3cef3049b2 657b87e74926326e
        1d8d0728c0dff4e8 a442401e5fedb478 ccb5980106ff4f57 50f52020622f785b
        460d69c6c7fe1ccc 3af5a83ecaae2528 8d9e853b8ceb78a7 6d5e28b265007a6a
        55afa169ace73622 f606a5075ecb0717 010622a3ac8b0c63 d2cc94dfeceae8a6
        3f78810cdcf26db0 fa1566b104fd1305 119753a458493317 009c5d16e2593d6c
        502ce0d01243a0f5 3a75bab045c14615 df972b1cd5b8fe6a 41cc81781c59fba4
        26689c88d5f48680 7d58af9bdfa57920 2acc78efe7df8ca3 504d0bb3fd4b304c
        41abf789c1218fd8 db2fd395adc7fa44 874d232728aa0f5d 51e91e6d930626d8
        c6bc024ad4607d9a 4c8396cb80547646 2db4195712a6940f f83e585239ffd87e
        5112a2447e921d30 35e963d43f71d47e 28994deeebe3b68e f871d753bbc565cb
        0d6f01ac2714806e 6b98257cccda3437 e84ef645b245eb6f 8008c58793c4efc3
        249c262c37ead871 0005d5f3ba309c36 c75201f95333f51d 891b2072a1c703d7
        5b73f090b2022ee2 895f299535b7554f c64e09057203df3a 4296b77698c5de2a
        831dc77c4c633832 c896453b44e79288 7d5f417eb72103ca b16a40647fb2f11c
        2f06d92b746998d9 edee9fc114a0a814 8331e62511a1b339 2e7887dee3c60d63
        cb2c60109926d416 6526be83b349ab80 9efecde8b93daf42 3d118c4943190fde
        9ba382d983e377cc abc456bd1503ec60
        """,
        """
        parent 009c5d16e2593d6c 502ce0d01243a0f5 span.parent_span_id
        parent 009c5d16e2593d6c df972b1cd5b8fe6a span.parent_span_id
        parent 073b28329995bf54 581ea87efe26916d span.parent_span_id
        parent 073b28329995bf54 c746db169a73863f span.parent_span_id
        parent 0d6f01ac2714806e 6b98257cccda3437 span.parent_span_id
        parent 1d8d0728c0dff4e8 a442401e5fedb478 span.parent_span_id
        parent 214b0c00a8aa6716 3199a3434bb85b38 span.parent_span_id
        parent 249c262c37ead871 0005d5f3ba309c36 span.parent_span_id
        parent 2521eae5c590a03f 72d7873eed87a902 span.parent_span_id
        parent 2521eae5c590a03f d7bfaf6170ace63d span.parent_span_id
        parent 26689c88d5f48680 7d58af9bdfa57920 span.parent_span_id
        parent 2e7887dee3c60d63 9efecde8b93daf42 span.parent_span_id
        parent 2e7887dee3c60d63 cb2c60109926d416 span.parent_span_id
        parent 2f06d92b746998d9 edee9fc114a0a814 span.parent_span_id
        parent 32061189de158286 468225a1bea00365 span.parent_span_id
        parent 32061189de158286 da6c0ee070aa97c2 span.parent_span_id
        parent 3d118c4943190fde 9ba382d983e377cc span.parent_span_id
        parent 3f78810cdcf26db0 fa1566b104fd1305 span.parent_span_id
        parent 41abf789c1218fd8 db2fd395adc7fa44 span.parent_span_id
        parent 41cc81781c59fba4 26689c88d5f48680 span.parent_span_id
        parent 41cc81781c59fba4 2acc78efe7df8ca3 span.parent_span_id
        parent 4296b77698c5de2a 7d5f417eb72103ca span.parent_span_id
        parent 4296b77698c5de2a 831dc77c4c633832 span.parent_span_id
        parent 448817e27ad9f3b1 44c37d1babb13ad6 span.parent_span_id
        parent 44c37d1babb13ad6 688d0f87480817ad span.parent_span_id
        parent 460d69c6c7fe1ccc 3af5a83ecaae2528 span.parent_span_id
        parent 502ce0d01243a0f5 3a75bab045c14615 span.parent_span_id
        parent 504d0bb3fd4b304c 41abf789c1218fd8 span.parent_span_id
        parent 504d0bb3fd4b304c 874d232728aa0f5d span.parent_span_id
        parent 50f52020622f785b 460d69c6c7fe1ccc span.parent_span_id
        parent 50f52020622f785b 8d9e853b8ceb78a7 span.parent_span_id
        parent 5112a2447e921d30 35e963d43f71d47e span.parent_span_id
        parent 51e91e6d930626d8 2db4195712a6940f span.parent_span_id
        parent 51e91e6d930626d8 c6bc024ad4607d9a span.parent_span_id
        parent 51efd36f1d62b407 634c89a6a084ddd0 span.parent_span_id
        parent 51efd36f1d62b407 f76bce43066356af span.parent_span_id
        parent 55afa169ace73622 f606a5075ecb0717 span.parent_span_id
        parent 5b73f090b2022ee2 895f299535b7554f span.parent_span_id
        parent 634c89a6a084ddd0 0c06cb7d271d3078 span.parent_span_id
        parent 657b87e74926326e 1d8d0728c0dff4e8 span.parent_span_id
        parent 657b87e74926326e ccb5980106ff4f57 span.parent_span_id
        parent 6867a209850a499c 43a7a53f9d4e7294 span.parent_span_id
        parent 688d0f87480817ad 009c5d16e2593d6c span.parent_span_id
        parent 688d0f87480817ad 073b28329995bf54 span.parent_span_id
        parent 688d0f87480817ad 2521eae5c590a03f span.parent_span_id
        parent 688d0f87480817ad 2e7887dee3c60d63 span.parent_span_id
        parent 688d0f87480817ad 32061189de158286 span.parent_span_id
        parent 688d0f87480817ad 3d118c4943190fde span.parent_span_id
        parent 688d0f87480817ad 41cc81781c59fba4 span.parent_span_id
        parent 688d0f87480817ad 4296b77698c5de2a span.parent_span_id
        parent 688d0f87480817ad 504d0bb3fd4b304c span.parent_span_id
        parent 688d0f87480817ad 50f52020622f785b span.parent_span_id
        parent 688d0f87480817ad 51e91e6d930626d8 span.parent_span_id
        parent 688d0f87480817ad 51efd36f1d62b407 span.parent_span_id
        parent 688d0f87480817ad 657b87e74926326e span.parent_span_id
        parent 688d0f87480817ad 6d5e28b265007a6a span.parent_span_id
        parent 688d0f87480817ad 8008c58793c4efc3 span.parent_span_id
        parent 688d0f87480817ad 887955e8a795154a span.parent_span_id
        parent 688d0f87480817ad 891b2072a1c703d7 span.parent_span_id
        parent 688d0f87480817ad b16a40647fb2f11c span.parent_span_id
        parent 688d0f87480817ad b890eb22c9ee4d5e span.parent_span_id
        parent 688d0f87480817ad d2cc94dfeceae8a6 span.parent_span_id
        parent 688d0f87480817ad d49ebf7507abce82 span.parent_span_id
        parent 688d0f87480817ad f4b312bcd0672256 span.parent_span_id
        parent 688d0f87480817ad f83e585239ffd87e span.parent_span_id
        parent 688d0f87480817ad f871d753bbc565cb span.parent_span_id
        parent 688d0f87480817ad f9504762f4a5f835 span.parent_span_id
        parent 6d5e28b265007a6a 010622a3ac8b0c63 span.parent_span_id
        parent 6d5e28b265007a6a 55afa169ace73622 span.parent_span_id
        parent 72d7873eed87a902 c9ba3fa79c7d99fc span.parent_span_id
        parent 7fcda7be6e333e37 f1cefb8fb89bcd86 span.parent_span_id
        parent 8008c58793c4efc3 249c262c37ead871 span.parent_span_id
        parent 8008c58793c4efc3 c75201f95333f51d span.parent_span_id
        parent 831dc77c4c633832 c896453b44e79288 span.parent_span_id
        parent 887955e8a795154a 7fcda7be6e333e37 span.parent_span_id
        parent 887955e8a795154a cca878b6ea70211d span.parent_span_id
        parent 891b2072a1c703d7 5b73f090b2022ee2 span.parent_span_id
        parent 891b2072a1c703d7 c64e09057203df3a span.parent_span_id
        parent 903b929484df0324 4db0bf5370207e5a span.parent_span_id
        parent 9ba382d983e377cc abc456bd1503ec60 span.parent_span_id
        parent b16a40647fb2f11c 2f06d92b746998d9 span.parent_span_id
        parent b16a40647fb2f11c 8331e62511a1b339 span.parent_span_id
        parent b890eb22c9ee4d5e 6867a209850a499c span.parent_span_id
        parent b890eb22c9ee4d5e 6b0cdd3cef3049b2 span.parent_span_id
        parent c6bc024ad4607d9a 4c8396cb80547646 span.parent_span_id
        parent c746db169a73863f 369faba861788c7f span.parent_span_id
        parent cb2c60109926d416 6526be83b349ab80 span.parent_span_id
        parent d2cc94dfeceae8a6 119753a458493317 span.parent_span_id
        parent d2cc94dfeceae8a6 3f78810cdcf26db0 span.parent_span_id
        parent d49ebf7507abce82 8a37b272a2facf97 span.parent_span_id
        parent d49ebf7507abce82 e6eeca5ea8cbf348 span.parent_span_id
        parent da6c0ee070aa97c2 a80acb601c6083dc span.parent_span_id
        parent e6eeca5ea8cbf348 fc864884950f371f span.parent_span_id
        parent f4b312bcd0672256 903b929484df0324 span.parent_span_id
        parent f4b312bcd0672256 9a7a0336849397e3 span.parent_span_id
        parent f83e585239ffd87e 28994deeebe3b68e span.parent_span_id
        parent f83e585239ffd87e 5112a2447e921d30 span.parent_span_id
        parent f871d753bbc565cb 0d6f01ac2714806e span.parent_span_id
        parent f871d753bbc565cb e84ef645b245eb6f span.parent_span_id
        parent f9504762f4a5f835 214b0c00a8aa6716 span.parent_span_id
        parent f9504762f4a5f835 61dab2219b9001e1 span.parent_span_id
        temporal 009c5d16e2593d6c 41cc81781c59fba4 sibling start_time ordering
        temporal 073b28329995bf54 32061189de158286 sibling start_time ordering
        temporal 0d6f01ac2714806e e84ef645b245eb6f sibling start_time ordering
        temporal 1d8d0728c0dff4e8 ccb5980106ff4f57 sibling start_time ordering
        temporal 214b0c00a8aa6716 61dab2219b9001e1 sibling start_time ordering
        temporal 249c262c37ead871 c75201f95333f51d sibling start_time ordering
        temporal 2521eae5c590a03f 51efd36f1d62b407 sibling start_time ordering
        temporal 26689c88d5f48680 2acc78efe7df8ca3 sibling start_time ordering
        temporal 2e7887dee3c60d63 3d118c4943190fde sibling start_time ordering
        temporal 2f06d92b746998d9 8331e62511a1b339 sibling start_time ordering
        temporal 32061189de158286 f4b312bcd0672256 sibling start_time ordering
        temporal 3f78810cdcf26db0 119753a458493317 sibling start_time ordering
        temporal 41abf789c1218fd8 874d232728aa0f5d sibling start_time ordering
        temporal 41cc81781c59fba4 504d0bb3fd4b304c sibling start_time ordering
        temporal 4296b77698c5de2a b16a40647fb2f11c sibling start_time ordering
        temporal 460d69c6c7fe1ccc 8d9e853b8ceb78a7 sibling start_time ordering
        temporal 502ce0d01243a0f5 df972b1cd5b8fe6a sibling start_time ordering
        temporal 504d0bb3fd4b304c 51e91e6d930626d8 sibling start_time ordering
        temporal 50f52020622f785b 6d5e28b265007a6a sibling start_time ordering
        temporal 5112a2447e921d30 28994deeebe3b68e sibling start_time ordering
        temporal 51e91e6d930626d8 f83e585239ffd87e sibling start_time ordering
        temporal 51efd36f1d62b407 d49ebf7507abce82 sibling start_time ordering
        temporal 55afa169ace73622 010622a3ac8b0c63 sibling start_time ordering
        temporal 5b73f090b2022ee2 c64e09057203df3a sibling start_time ordering
        temporal 634c89a6a084ddd0 f76bce43066356af sibling start_time ordering
        temporal 657b87e74926326e 50f52020622f785b sibling start_time ordering
        temporal 6867a209850a499c 6b0cdd3cef3049b2 sibling start_time ordering
        temporal 6d5e28b265007a6a d2cc94dfeceae8a6 sibling start_time ordering
        temporal 72d7873eed87a902 d7bfaf6170ace63d sibling start_time ordering
        temporal 7fcda7be6e333e37 cca878b6ea70211d sibling start_time ordering
        temporal 8008c58793c4efc3 891b2072a1c703d7 sibling start_time ordering
        temporal 831dc77c4c633832 7d5f417eb72103ca sibling start_time ordering
        temporal 887955e8a795154a 2521eae5c590a03f sibling start_time ordering
        temporal 891b2072a1c703d7 4296b77698c5de2a sibling start_time ordering
        temporal 903b929484df0324 9a7a0336849397e3 sibling start_time ordering
        temporal b16a40647fb2f11c 2e7887dee3c60d63 sibling start_time ordering
        temporal b890eb22c9ee4d5e 657b87e74926326e sibling start_time ordering
        temporal c6bc024ad4607d9a 2db4195712a6940f sibling start_time ordering
        temporal c746db169a73863f 581ea87efe26916d sibling start_time ordering
        temporal cb2c60109926d416 9efecde8b93daf42 sibling start_time ordering
        temporal d2cc94dfeceae8a6 009c5d16e2593d6c sibling start_time ordering
        temporal d49ebf7507abce82 f9504762f4a5f835 sibling start_time ordering
        temporal da6c0ee070aa97c2 468225a1bea00365 sibling start_time ordering
        temporal e6eeca5ea8cbf348 8a37b272a2facf97 sibling start_time ordering
        temporal f4b312bcd0672256 b890eb22c9ee4d5e sibling start_time ordering
        temporal f83e585239ffd87e f871d753bbc565cb sibling start_time ordering
        temporal f871d753bbc565cb 8008c58793c4efc3 sibling start_time ordering
        temporal f9504762f4a5f835 073b28329995bf54 sibling start_time ordering
        """,
    ),
    "z3/2026-10-13-recorded": _structure(
        """
        e5cd88a577106085 832842ad77882770 3f096acabac306dc ee82e8438cd5494e
        5dc16ee519480eee 10ed24eda137ec3d c75df378b889e5f1 254102d97695d41c
        ce371cfca290a353 e5c7cef9d10cc0ad 3f59dd52a1770553 e6a6683d857b531c
        2805221264211fbb 911c42f568523eb2 3e67eef9837de56b 44b9487d9f1ebd72
        ce3a1d3dcd7667f6 f1e801e2164a8000 2aac550629021a52 ca2f17d97a5ba2a0
        51699718f728b098 aa3d684976c9dd4c 51cf9cf14fdf91bc 533d76123d787564
        2d1fde727341a475 bb93aedca84099ed a86caa949dbf1a0a 9b2a48396eff05c9
        82e42132ae6945a7 7abadc2da6eb0518 583f111cc9af3fe9 0427bb201189b951
        f0aad381fc2c4911 f4ac847abcbce2c7 233c1608445f861f 67464f1f6045beeb
        1a8b5a93d38aff0d b7969c241cd506c7 91b192dd6757d2d0 c17c697fa9bcee8a
        69cc827e4bf65d7a 85fc7ed109a54255 2a6316841a7447ad eb3fed8ce145b73b
        12429bc4ff1d4ead 3a64640a88d5e16e 6bac3c895d6763e3 237c1272cb30956a
        66d00132dddb9714 c379ba558474ddf3 1dc5d7318ea75c46 04a9dc2d09c18a16
        61dca4e41e17eb93 de4dfd648fe3998c 2320acf5a64ac25e c90c7784a4e18923
        9f7b454a3e4a4663 f397b1d4f472bc4f 116f4644ec2c3efe 6328057859662d2c
        7dfaecb0d7c78ec2 d99b5b70fdaeffb8 b1a613cb29f6e466 74d45430d87e230d
        37298811d1a4a02d 6d4953ff9a87f3a8 2fc09537cf179703 742f29a0c74dfe99
        bca4b37a7c99fd30 8fe68e7c9592c32c f792af86cc8a8a8b e024f2b5253bb79f
        16582590c40abeba f4637a057bf9d1e4 436dbccdca9bb286 b079a410bbda9dd7
        fe76e4de807c1cf7 b5a2b6b98376f8c6 30cc1086cae67e80 fb4f90c99122c055
        a97d66c04625834e 6452efaf4a6e04ac bd24df96218b4fde c690fc075a78a667
        4c6226693e758c7a 2c3dedc3cca51456 c9ff442501ce4c67 a383f4209e70fe6b
        1724d81dad50c400 49995b020bc7b63a b6b5455b8856c817 0590cc482d6a8683
        abfc8dad22f47257 2f45d554aac0aea6 b2c5eb3c0baf68c5 aa52f5519eb40b1d
        5193db0965426c97 0605f70921bd5675 998dd73d4917699c d22df0e639ca45c5
        4feb2fa9b583d910 181957d46e2096c9
        """,
        """
        parent 0427bb201189b951 233c1608445f861f span.parent_span_id
        parent 0427bb201189b951 f0aad381fc2c4911 span.parent_span_id
        parent 04a9dc2d09c18a16 2320acf5a64ac25e span.parent_span_id
        parent 04a9dc2d09c18a16 61dca4e41e17eb93 span.parent_span_id
        parent 0590cc482d6a8683 abfc8dad22f47257 span.parent_span_id
        parent 0590cc482d6a8683 b2c5eb3c0baf68c5 span.parent_span_id
        parent 12429bc4ff1d4ead 3a64640a88d5e16e span.parent_span_id
        parent 16582590c40abeba f4637a057bf9d1e4 span.parent_span_id
        parent 1724d81dad50c400 49995b020bc7b63a span.parent_span_id
        parent 1a8b5a93d38aff0d b7969c241cd506c7 span.parent_span_id
        parent 237c1272cb30956a 1dc5d7318ea75c46 span.parent_span_id
        parent 237c1272cb30956a 66d00132dddb9714 span.parent_span_id
        parent 254102d97695d41c 3f59dd52a1770553 span.parent_span_id
        parent 254102d97695d41c ce371cfca290a353 span.parent_span_id
        parent 2805221264211fbb 911c42f568523eb2 span.parent_span_id
        parent 2d1fde727341a475 bb93aedca84099ed span.parent_span_id
        parent 37298811d1a4a02d 6d4953ff9a87f3a8 span.parent_span_id
        parent 3f096acabac306dc 0427bb201189b951 span.parent_span_id
        parent 3f096acabac306dc 04a9dc2d09c18a16 span.parent_span_id
        parent 3f096acabac306dc 0590cc482d6a8683 span.parent_span_id
        parent 3f096acabac306dc 237c1272cb30956a span.parent_span_id
        parent 3f096acabac306dc 254102d97695d41c span.parent_span_id
        parent 3f096acabac306dc 44b9487d9f1ebd72 span.parent_span_id
        parent 3f096acabac306dc 533d76123d787564 span.parent_span_id
        parent 3f096acabac306dc 6328057859662d2c span.parent_span_id
        parent 3f096acabac306dc 67464f1f6045beeb span.parent_span_id
        parent 3f096acabac306dc 742f29a0c74dfe99 span.parent_span_id
        parent 3f096acabac306dc 74d45430d87e230d span.parent_span_id
        parent 3f096acabac306dc 9b2a48396eff05c9 span.parent_span_id
        parent 3f096acabac306dc a383f4209e70fe6b span.parent_span_id
        parent 3f096acabac306dc aa52f5519eb40b1d span.parent_span_id
        parent 3f096acabac306dc b079a410bbda9dd7 span.parent_span_id
        parent 3f096acabac306dc c17c697fa9bcee8a span.parent_span_id
        parent 3f096acabac306dc c690fc075a78a667 span.parent_span_id
        parent 3f096acabac306dc c90c7784a4e18923 span.parent_span_id
        parent 3f096acabac306dc ca2f17d97a5ba2a0 span.parent_span_id
        parent 3f096acabac306dc d22df0e639ca45c5 span.parent_span_id
        parent 3f096acabac306dc e024f2b5253bb79f span.parent_span_id
        parent 3f096acabac306dc e6a6683d857b531c span.parent_span_id
        parent 3f096acabac306dc eb3fed8ce145b73b span.parent_span_id
        parent 3f096acabac306dc ee82e8438cd5494e span.parent_span_id
        parent 3f096acabac306dc fb4f90c99122c055 span.parent_span_id
        parent 44b9487d9f1ebd72 2aac550629021a52 span.parent_span_id
        parent 44b9487d9f1ebd72 ce3a1d3dcd7667f6 span.parent_span_id
        parent 4c6226693e758c7a 2c3dedc3cca51456 span.parent_span_id
        parent 4feb2fa9b583d910 181957d46e2096c9 span.parent_span_id
        parent 51699718f728b098 aa3d684976c9dd4c span.parent_span_id
        parent 5193db0965426c97 0605f70921bd5675 span.parent_span_id
        parent 533d76123d787564 2d1fde727341a475 span.parent_span_id
        parent 533d76123d787564 a86caa949dbf1a0a span.parent_span_id
        parent 5dc16ee519480eee 10ed24eda137ec3d span.parent_span_id
        parent 61dca4e41e17eb93 de4dfd648fe3998c span.parent_span_id
        parent 6328057859662d2c 7dfaecb0d7c78ec2 span.parent_span_id
        parent 6328057859662d2c b1a613cb29f6e466 span.parent_span_id
        parent 66d00132dddb9714 c379ba558474ddf3 span.parent_span_id
        parent 67464f1f6045beeb 1a8b5a93d38aff0d span.parent_span_id
        parent 67464f1f6045beeb 91b192dd6757d2d0 span.parent_span_id
        parent 69cc827e4bf65d7a 85fc7ed109a54255 span.parent_span_id
        parent 742f29a0c74dfe99 bca4b37a7c99fd30 span.parent_span_id
        parent 742f29a0c74dfe99 f792af86cc8a8a8b span.parent_span_id
        parent 74d45430d87e230d 2fc09537cf179703 span.parent_span_id
        parent 74d45430d87e230d 37298811d1a4a02d span.parent_span_id
        parent 7dfaecb0d7c78ec2 d99b5b70fdaeffb8 span.parent_span_id
        parent 82e42132ae6945a7 7abadc2da6eb0518 span.parent_span_id
        parent 832842ad77882770 3f096acabac306dc span.parent_span_id
        parent 9b2a48396eff05c9 583f111cc9af3fe9 span.parent_span_id
        parent 9b2a48396eff05c9 82e42132ae6945a7 span.parent_span_id
        parent 9f7b454a3e4a4663 f397b1d4f472bc4f span.parent_span_id
        parent a383f4209e70fe6b 1724d81dad50c400 span.parent_span_id
        parent a383f4209e70fe6b b6b5455b8856c817 span.parent_span_id
        parent a97d66c04625834e 6452efaf4a6e04ac span.parent_span_id
        parent aa52f5519eb40b1d 5193db0965426c97 span.parent_span_id
        parent aa52f5519eb40b1d 998dd73d4917699c span.parent_span_id
        parent abfc8dad22f47257 2f45d554aac0aea6 span.parent_span_id
        parent b079a410bbda9dd7 30cc1086cae67e80 span.parent_span_id
        parent b079a410bbda9dd7 fe76e4de807c1cf7 span.parent_span_id
        parent bca4b37a7c99fd30 8fe68e7c9592c32c span.parent_span_id
        parent c17c697fa9bcee8a 2a6316841a7447ad span.parent_span_id
        parent c17c697fa9bcee8a 69cc827e4bf65d7a span.parent_span_id
        parent c690fc075a78a667 4c6226693e758c7a span.parent_span_id
        parent c690fc075a78a667 c9ff442501ce4c67 span.parent_span_id
        parent c90c7784a4e18923 116f4644ec2c3efe span.parent_span_id
        parent c90c7784a4e18923 9f7b454a3e4a4663 span.parent_span_id
        parent ca2f17d97a5ba2a0 51699718f728b098 span.parent_span_id
        parent ca2f17d97a5ba2a0 51cf9cf14fdf91bc span.parent_span_id
        parent ce371cfca290a353 e5c7cef9d10cc0ad span.parent_span_id
        parent ce3a1d3dcd7667f6 f1e801e2164a8000 span.parent_span_id
        parent d22df0e639ca45c5 4feb2fa9b583d910 span.parent_span_id
        parent e024f2b5253bb79f 16582590c40abeba span.parent_span_id
        parent e024f2b5253bb79f 436dbccdca9bb286 span.parent_span_id
        parent e5cd88a577106085 832842ad77882770 span.parent_span_id
        parent e6a6683d857b531c 2805221264211fbb span.parent_span_id
        parent e6a6683d857b531c 3e67eef9837de56b span.parent_span_id
        parent eb3fed8ce145b73b 12429bc4ff1d4ead span.parent_span_id
        parent eb3fed8ce145b73b 6bac3c895d6763e3 span.parent_span_id
        parent ee82e8438cd5494e 5dc16ee519480eee span.parent_span_id
        parent ee82e8438cd5494e c75df378b889e5f1 span.parent_span_id
        parent f0aad381fc2c4911 f4ac847abcbce2c7 span.parent_span_id
        parent fb4f90c99122c055 a97d66c04625834e span.parent_span_id
        parent fb4f90c99122c055 bd24df96218b4fde span.parent_span_id
        parent fe76e4de807c1cf7 b5a2b6b98376f8c6 span.parent_span_id
        temporal 0427bb201189b951 67464f1f6045beeb sibling start_time ordering
        temporal 04a9dc2d09c18a16 c90c7784a4e18923 sibling start_time ordering
        temporal 0590cc482d6a8683 aa52f5519eb40b1d sibling start_time ordering
        temporal 12429bc4ff1d4ead 6bac3c895d6763e3 sibling start_time ordering
        temporal 16582590c40abeba 436dbccdca9bb286 sibling start_time ordering
        temporal 1724d81dad50c400 b6b5455b8856c817 sibling start_time ordering
        temporal 1a8b5a93d38aff0d 91b192dd6757d2d0 sibling start_time ordering
        temporal 237c1272cb30956a 04a9dc2d09c18a16 sibling start_time ordering
        temporal 254102d97695d41c e6a6683d857b531c sibling start_time ordering
        temporal 2805221264211fbb 3e67eef9837de56b sibling start_time ordering
        temporal 2d1fde727341a475 a86caa949dbf1a0a sibling start_time ordering
        temporal 37298811d1a4a02d 2fc09537cf179703 sibling start_time ordering
        temporal 44b9487d9f1ebd72 ca2f17d97a5ba2a0 sibling start_time ordering
        temporal 4c6226693e758c7a c9ff442501ce4c67 sibling start_time ordering
        temporal 51699718f728b098 51cf9cf14fdf91bc sibling start_time ordering
        temporal 5193db0965426c97 998dd73d4917699c sibling start_time ordering
        temporal 533d76123d787564 9b2a48396eff05c9 sibling start_time ordering
        temporal 5dc16ee519480eee c75df378b889e5f1 sibling start_time ordering
        temporal 61dca4e41e17eb93 2320acf5a64ac25e sibling start_time ordering
        temporal 6328057859662d2c 74d45430d87e230d sibling start_time ordering
        temporal 66d00132dddb9714 1dc5d7318ea75c46 sibling start_time ordering
        temporal 67464f1f6045beeb c17c697fa9bcee8a sibling start_time ordering
        temporal 69cc827e4bf65d7a 2a6316841a7447ad sibling start_time ordering
        temporal 742f29a0c74dfe99 e024f2b5253bb79f sibling start_time ordering
        temporal 74d45430d87e230d 742f29a0c74dfe99 sibling start_time ordering
        temporal 7dfaecb0d7c78ec2 b1a613cb29f6e466 sibling start_time ordering
        temporal 82e42132ae6945a7 583f111cc9af3fe9 sibling start_time ordering
        temporal 9b2a48396eff05c9 0427bb201189b951 sibling start_time ordering
        temporal 9f7b454a3e4a4663 116f4644ec2c3efe sibling start_time ordering
        temporal a383f4209e70fe6b 0590cc482d6a8683 sibling start_time ordering
        temporal a97d66c04625834e bd24df96218b4fde sibling start_time ordering
        temporal aa52f5519eb40b1d d22df0e639ca45c5 sibling start_time ordering
        temporal abfc8dad22f47257 b2c5eb3c0baf68c5 sibling start_time ordering
        temporal b079a410bbda9dd7 fb4f90c99122c055 sibling start_time ordering
        temporal bca4b37a7c99fd30 f792af86cc8a8a8b sibling start_time ordering
        temporal c17c697fa9bcee8a eb3fed8ce145b73b sibling start_time ordering
        temporal c690fc075a78a667 a383f4209e70fe6b sibling start_time ordering
        temporal c90c7784a4e18923 6328057859662d2c sibling start_time ordering
        temporal ca2f17d97a5ba2a0 533d76123d787564 sibling start_time ordering
        temporal ce371cfca290a353 3f59dd52a1770553 sibling start_time ordering
        temporal ce3a1d3dcd7667f6 2aac550629021a52 sibling start_time ordering
        temporal e024f2b5253bb79f b079a410bbda9dd7 sibling start_time ordering
        temporal e6a6683d857b531c 44b9487d9f1ebd72 sibling start_time ordering
        temporal eb3fed8ce145b73b 237c1272cb30956a sibling start_time ordering
        temporal ee82e8438cd5494e 254102d97695d41c sibling start_time ordering
        temporal f0aad381fc2c4911 233c1608445f861f sibling start_time ordering
        temporal fb4f90c99122c055 c690fc075a78a667 sibling start_time ordering
        temporal fe76e4de807c1cf7 30cc1086cae67e80 sibling start_time ordering
        """,
    ),
    "z4/2026-10-12-real": _structure(
        """
        a700993010700621 317657789bb0f148 a90c8b9b28c8e710 17eb31438da683f1
        """,
        """
        temporal 317657789bb0f148 a90c8b9b28c8e710 sibling start_time ordering
        temporal a700993010700621 317657789bb0f148 sibling start_time ordering
        temporal a90c8b9b28c8e710 17eb31438da683f1 sibling start_time ordering
        """,
    ),
    "z4/2026-10-12-recorded": _structure(
        """
        1c22728149a3ec83 afa87e72e4b4c576 30498d48d228299f 08800207f04dcccd
        """,
        """
        temporal 1c22728149a3ec83 afa87e72e4b4c576 sibling start_time ordering
        temporal 30498d48d228299f 08800207f04dcccd sibling start_time ordering
        temporal afa87e72e4b4c576 30498d48d228299f sibling start_time ordering
        """,
    ),
    "z5/2026-10-13-real": _structure(
        """
        ffc7f15f81138f70 225a4ec7cea5d25f d6a1ef700699850b b72cc2b1cb801793
        """,
        """
        parent ffc7f15f81138f70 225a4ec7cea5d25f span.parent_span_id
        parent ffc7f15f81138f70 d6a1ef700699850b span.parent_span_id
        temporal 225a4ec7cea5d25f d6a1ef700699850b sibling start_time ordering
        """,
    ),
    "z5/2026-10-13-recorded": _structure(
        """
        0e13631e1bbd0b71 fb78514dc6557db1 4081011c8c1021f9 cd8b2a400dc4e7bb
        """,
        """
        parent 0e13631e1bbd0b71 4081011c8c1021f9 span.parent_span_id
        parent 0e13631e1bbd0b71 fb78514dc6557db1 span.parent_span_id
        temporal fb78514dc6557db1 4081011c8c1021f9 sibling start_time ordering
        """,
    ),
    "z6/2026-10-14-real": _structure(
        """
        34c04caf3b53b381 71ee0eb62d8023e8 82b91a5716d22f21 44a06c2c9b1ec84d
        fb7f2c9c41599f56 0cc839c55998fd72 0884dce9cf77f5bf 961eb676dd44c052
        89e56db8cdd3d86d b4124d7613da7f5f b766491b4639277e 853c794192f0bb63
        05fee439adbecf19 c1327ee777985a43 19479c5226b20980 1ea3866d607d7dda
        a20b4dfd274d45e2 344735450e29f7e9 c10e9a6784aaba52 60c3a731d82052d6
        c7ea7e80682a9781 ca55b967aa976a9b b9bffcf46a373332 f0875d0f89b39ea8
        2c84764622e9f462 e1d461bf2f9c7f14
        """,
        """
        parent 0cc839c55998fd72 0884dce9cf77f5bf span.parent_span_id
        parent 34c04caf3b53b381 0cc839c55998fd72 span.parent_span_id
        parent 34c04caf3b53b381 71ee0eb62d8023e8 span.parent_span_id
        parent 34c04caf3b53b381 961eb676dd44c052 span.parent_span_id
        parent 71ee0eb62d8023e8 44a06c2c9b1ec84d span.parent_span_id
        parent 71ee0eb62d8023e8 82b91a5716d22f21 span.parent_span_id
        parent 71ee0eb62d8023e8 fb7f2c9c41599f56 span.parent_span_id
        parent 853c794192f0bb63 05fee439adbecf19 span.parent_span_id
        parent 961eb676dd44c052 19479c5226b20980 span.parent_span_id
        parent 961eb676dd44c052 1ea3866d607d7dda span.parent_span_id
        parent 961eb676dd44c052 2c84764622e9f462 span.parent_span_id
        parent 961eb676dd44c052 60c3a731d82052d6 span.parent_span_id
        parent 961eb676dd44c052 853c794192f0bb63 span.parent_span_id
        parent 961eb676dd44c052 89e56db8cdd3d86d span.parent_span_id
        parent 961eb676dd44c052 a20b4dfd274d45e2 span.parent_span_id
        parent 961eb676dd44c052 b4124d7613da7f5f span.parent_span_id
        parent 961eb676dd44c052 b766491b4639277e span.parent_span_id
        parent 961eb676dd44c052 c10e9a6784aaba52 span.parent_span_id
        parent 961eb676dd44c052 c1327ee777985a43 span.parent_span_id
        parent 961eb676dd44c052 c7ea7e80682a9781 span.parent_span_id
        parent 961eb676dd44c052 ca55b967aa976a9b span.parent_span_id
        parent 961eb676dd44c052 e1d461bf2f9c7f14 span.parent_span_id
        parent 961eb676dd44c052 f0875d0f89b39ea8 span.parent_span_id
        parent a20b4dfd274d45e2 344735450e29f7e9 span.parent_span_id
        parent ca55b967aa976a9b b9bffcf46a373332 span.parent_span_id
        temporal 0cc839c55998fd72 961eb676dd44c052 sibling start_time ordering
        temporal 19479c5226b20980 1ea3866d607d7dda sibling start_time ordering
        temporal 1ea3866d607d7dda a20b4dfd274d45e2 sibling start_time ordering
        temporal 2c84764622e9f462 e1d461bf2f9c7f14 sibling start_time ordering
        temporal 44a06c2c9b1ec84d fb7f2c9c41599f56 sibling start_time ordering
        temporal 60c3a731d82052d6 c7ea7e80682a9781 sibling start_time ordering
        temporal 71ee0eb62d8023e8 0cc839c55998fd72 sibling start_time ordering
        temporal 82b91a5716d22f21 44a06c2c9b1ec84d sibling start_time ordering
        temporal 853c794192f0bb63 c1327ee777985a43 sibling start_time ordering
        temporal 89e56db8cdd3d86d b4124d7613da7f5f sibling start_time ordering
        temporal a20b4dfd274d45e2 c10e9a6784aaba52 sibling start_time ordering
        temporal b4124d7613da7f5f b766491b4639277e sibling start_time ordering
        temporal b766491b4639277e 853c794192f0bb63 sibling start_time ordering
        temporal c10e9a6784aaba52 60c3a731d82052d6 sibling start_time ordering
        temporal c1327ee777985a43 19479c5226b20980 sibling start_time ordering
        temporal c7ea7e80682a9781 ca55b967aa976a9b sibling start_time ordering
        temporal ca55b967aa976a9b f0875d0f89b39ea8 sibling start_time ordering
        temporal f0875d0f89b39ea8 2c84764622e9f462 sibling start_time ordering
        """,
    ),
    "z6/2026-10-14-recorded": _structure(
        """
        4f7e2c35179f73b8 71750936a554dcb9 132f7e74ebc46897 03471fad20735e02
        6e7c369cc0093562 57c6f190d0fb9c2c 352f2741a0f408b2 a3a68dce2fcf0c67
        d75d12a521e25ed6 d28bd9bca14ba144 3fd13b3397e24527 449398542054a6e1
        d713a1c08b316e89 767f523f64b84f0a e7fac4350f673105 cd2db9d095212dbd
        """,
        """
        parent 449398542054a6e1 d713a1c08b316e89 span.parent_span_id
        parent 4f7e2c35179f73b8 57c6f190d0fb9c2c span.parent_span_id
        parent 4f7e2c35179f73b8 71750936a554dcb9 span.parent_span_id
        parent 4f7e2c35179f73b8 a3a68dce2fcf0c67 span.parent_span_id
        parent 57c6f190d0fb9c2c 352f2741a0f408b2 span.parent_span_id
        parent 71750936a554dcb9 03471fad20735e02 span.parent_span_id
        parent 71750936a554dcb9 132f7e74ebc46897 span.parent_span_id
        parent 71750936a554dcb9 6e7c369cc0093562 span.parent_span_id
        parent a3a68dce2fcf0c67 3fd13b3397e24527 span.parent_span_id
        parent a3a68dce2fcf0c67 449398542054a6e1 span.parent_span_id
        parent a3a68dce2fcf0c67 767f523f64b84f0a span.parent_span_id
        parent a3a68dce2fcf0c67 cd2db9d095212dbd span.parent_span_id
        parent a3a68dce2fcf0c67 d28bd9bca14ba144 span.parent_span_id
        parent a3a68dce2fcf0c67 d75d12a521e25ed6 span.parent_span_id
        parent a3a68dce2fcf0c67 e7fac4350f673105 span.parent_span_id
        temporal 03471fad20735e02 6e7c369cc0093562 sibling start_time ordering
        temporal 132f7e74ebc46897 03471fad20735e02 sibling start_time ordering
        temporal 3fd13b3397e24527 449398542054a6e1 sibling start_time ordering
        temporal 449398542054a6e1 767f523f64b84f0a sibling start_time ordering
        temporal 57c6f190d0fb9c2c a3a68dce2fcf0c67 sibling start_time ordering
        temporal 71750936a554dcb9 57c6f190d0fb9c2c sibling start_time ordering
        temporal 767f523f64b84f0a e7fac4350f673105 sibling start_time ordering
        temporal d28bd9bca14ba144 3fd13b3397e24527 sibling start_time ordering
        temporal d75d12a521e25ed6 d28bd9bca14ba144 sibling start_time ordering
        temporal e7fac4350f673105 cd2db9d095212dbd sibling start_time ordering
        """,
    ),
}

# The whole capture's graph, placed, where the audit fed fewer (`Capture.whole`):
# Z4's, its root `unknown` node first and the parent of the four `llm` spans.
# Every other capture's whole graph is its audit feed's, so it is `STRUCTURES`'.
WHOLE_STRUCTURES: dict[str, Structure] = {
    "z4/2026-10-12-real": _structure(
        """
        3013a003149d6951 a700993010700621 317657789bb0f148 a90c8b9b28c8e710
        17eb31438da683f1
        """,
        """
        parent 3013a003149d6951 17eb31438da683f1 span.parent_span_id
        parent 3013a003149d6951 317657789bb0f148 span.parent_span_id
        parent 3013a003149d6951 a700993010700621 span.parent_span_id
        parent 3013a003149d6951 a90c8b9b28c8e710 span.parent_span_id
        temporal 317657789bb0f148 a90c8b9b28c8e710 sibling start_time ordering
        temporal a700993010700621 317657789bb0f148 sibling start_time ordering
        temporal a90c8b9b28c8e710 17eb31438da683f1 sibling start_time ordering
        """,
    ),
    "z4/2026-10-12-recorded": _structure(
        """
        b76075f9bc47a92b 1c22728149a3ec83 afa87e72e4b4c576 30498d48d228299f
        08800207f04dcccd
        """,
        """
        parent b76075f9bc47a92b 08800207f04dcccd span.parent_span_id
        parent b76075f9bc47a92b 1c22728149a3ec83 span.parent_span_id
        parent b76075f9bc47a92b 30498d48d228299f span.parent_span_id
        parent b76075f9bc47a92b afa87e72e4b4c576 span.parent_span_id
        temporal 1c22728149a3ec83 afa87e72e4b4c576 sibling start_time ordering
        temporal 30498d48d228299f 08800207f04dcccd sibling start_time ordering
        temporal afa87e72e4b4c576 30498d48d228299f sibling start_time ordering
        """,
    ),
}


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
        unmapped_attributes=codes["unmapped_attributes"],
        attributes_dropped=codes["attributes_dropped"],
        exception_event=codes["exception_event"],
        span_event=codes["span_event"],
    )


def structure(graph: spanweave.Graph) -> Structure:
    """The structure of one graph: its node ids and its edges, in its order."""
    return Structure(
        tuple(node.id for node in graph.nodes()),
        tuple(
            (edge.kind.value, edge.src, edge.dst, edge.basis) for edge in graph.edges()
        ),
    )


def scope_names(capture: Capture) -> frozenset[str]:
    """The scope name each record's OTLP envelope states, every record of the capture.

    Read through `spanweave.envelope`, never through the record's keys: which
    instrumentor wrote a span is a fact the transport stated, per span
    (`SPEC.md` §7; `PROBES.md` S6, S21).
    """
    names: set[str] = set()
    for record in records(capture):
        scope = spanweave.envelope(record.record).scope.get("scope")
        assert isinstance(scope, dict), (capture.run, record.body, record.index)
        name = scope.get("name")
        assert isinstance(name, str), (capture.run, record.body, record.index)
        names.add(name)
    return frozenset(names)


def exporter_order(capture: Capture) -> tuple[int, int]:
    """`(child before parent, parent before child)` over the capture's records.

    Each pair is a record and the record whose span id is the parent it states,
    both in the capture, counted by where each sits in body order (every record
    of every body, `records`). Ids are read from each record's OTLP envelope,
    as the transport stated them (`spanweave.envelope`); no graph is built.
    """
    envelopes = [spanweave.envelope(r.record) for r in records(capture)]
    at = {e.span_id: i for i, e in enumerate(envelopes)}
    before = after = 0
    for i, e in enumerate(envelopes):
        if e.parent_id is not None and e.parent_id in at:
            if at[e.parent_id] > i:
                before += 1
            else:
                after += 1
    return before, after


def scope_runs(capture: Capture) -> dict[str, list[str]]:
    """Body -> the scope names its records state, one entry per run of equal names.

    A body whose records are contiguous by scope lists each name once.
    """
    runs: dict[str, list[str]] = {}
    for record in records(capture):
        scope = spanweave.envelope(record.record).scope.get("scope")
        assert isinstance(scope, dict), (capture.run, record.body, record.index)
        name = scope.get("name")
        assert isinstance(name, str), (capture.run, record.body, record.index)
        body = runs.setdefault(record.body, [])
        if not body or body[-1] != name:
            body.append(name)
    return runs


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
