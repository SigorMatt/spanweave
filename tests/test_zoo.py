"""The zoo's captures are a fixture, and the audit's census is a gate.

Two claims, each re-derived on every run (`make conformance` runs this file):

* `fixtures/zoo/` is the zoo's record, byte for byte: every body's sha256 is
  the one its capture's sealed manifest gives, every manifest's seal is the one
  its own claims compute to and the one `fixtures/zoo/README.md` pins, and the
  copy holds exactly the `json/` bodies the manifests list -- none missing,
  none added. The README's seal is what makes the first two more than
  self-consistency: a body rewritten with its manifest sha and its seal
  recomputed to match agrees with itself, and not with the pinned value.
* The counts the zoo's audit reported (`tests/zoo_census.py`, each citing its
  report) are what this library builds from those bytes, batch and incremental
  alike, with the records fed in the exporter's order: child before parent
  (`PROBES.md` S15), grouped by instrumentation scope (S21). Both orders are
  asserted of the bytes, not assumed: no record of any capture follows the
  record of its parent, and each body's records are contiguous by scope.
* The README's instrumentation column and its Collector version are each
  manifest's `project_manifest.instrumentation` and `collector_version`, and
  its census paragraph names `Census`'s fields, their number and what Z4's
  whole capture adds as the census holds them.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields

import pytest

import spanweave
from spanweave.adapters import classify
from spanweave.api import graph_from_records
from spanweave.model import JsonValue
from tests import zoo_census
from tests.zoo_census import (
    CAPTURES,
    STRUCTURES,
    WHOLE_STRUCTURES,
    ZOO,
    ZOO_BODY_DIR,
    Capture,
    Census,
)

IDS = [capture.run for capture in CAPTURES]


def _listed_bodies(capture: Capture) -> dict[str, str]:
    """`NNNN.json` -> sha256 for every `json/` body the manifest lists."""
    document = zoo_census.manifest(capture)
    entries = document["bodies"]
    assert isinstance(entries, list)
    listed: dict[str, str] = {}
    for entry in entries:
        assert isinstance(entry, dict)
        directory, _, name = str(entry["file"]).partition("/")
        if directory == ZOO_BODY_DIR:
            listed[name] = str(entry["sha256"])
    return listed


def test_the_copy_holds_the_twelve_captures_and_nothing_else():
    on_disk = sorted(
        str(path.relative_to(ZOO)) for path in ZOO.rglob("*") if path.is_file()
    )
    expected = sorted(
        ["README.md"]
        + [f"{c.run}/MANIFEST.json" for c in CAPTURES]
        + [f"{c.run}/{name}" for c in CAPTURES for name in _listed_bodies(c)]
    )
    assert on_disk == expected
    assert len(CAPTURES) == 12
    # PROBES.md "The captures": 29 bodies across the twelve.
    assert sum(len(c.records_per_body) for c in CAPTURES) == 29


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_every_body_is_the_zoo_s_byte_for_byte(capture):
    listed = _listed_bodies(capture)
    assert [path.name for path in zoo_census.bodies(capture)] == sorted(listed)
    for path in zoo_census.bodies(capture):
        assert zoo_census.sha256(path) == listed[path.name], path


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_every_manifest_carries_the_seal_its_claims_compute_to(capture):
    document = zoo_census.manifest(capture)
    assert document["seal"] == zoo_census.seal_of(document)


#: A capture's row of the README's table: its run, first; its seal, last.
_README_ROW = re.compile(r"^\| `(z\d/[^`]+)` \|.*\| `([0-9a-f]{64})` \|$")


def _readme_seals() -> dict[str, str]:
    """Capture run -> the seal `fixtures/zoo/README.md` pins for it."""
    seals: dict[str, str] = {}
    for line in (ZOO / "README.md").read_text(encoding="utf-8").splitlines():
        match = _README_ROW.match(line)
        if match is not None:
            run, seal = match.groups()
            assert run not in seals, run
            seals[run] = seal
    return seals


def test_the_readme_pins_one_seal_for_each_of_the_twelve_captures():
    assert sorted(_readme_seals()) == sorted(IDS)


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_every_seal_is_the_one_the_readme_pins(capture):
    """The seal recomputed from the manifest beside the bodies is the README's.

    With `test_every_body_is_the_zoo_s_byte_for_byte` (each body's sha256 is the
    manifest's) this ties every byte of the copy to a value written down at the
    pin, outside the files it checks.
    """
    pinned = _readme_seals()[capture.run]
    document = zoo_census.manifest(capture)
    assert zoo_census.seal_of(document) == pinned, capture.run
    assert document["seal"] == pinned, capture.run


#: A capture's row of the README's table, its instrumentation column.
_README_INSTRUMENTATION = re.compile(r"^\| `(z\d/[^`]+)` \| [^|]+ \| ([^|]+) \|")


def _readme_instrumentation() -> dict[str, list[str]]:
    """Capture run -> the instrumentation the README's table names for it."""
    return _instrumentation_of((ZOO / "README.md").read_text(encoding="utf-8"))


def _instrumentation_of(readme: str) -> dict[str, list[str]]:
    """Capture run -> the instrumentation a README table names for it.

    "as above" is the row before's, as the table writes it.
    """
    named: dict[str, list[str]] = {}
    previous: list[str] | None = None
    for line in readme.splitlines():
        match = _README_INSTRUMENTATION.match(line)
        if match is None:
            continue
        run, cell = match.group(1), match.group(2).strip()
        if cell == "as above":
            assert previous is not None, run
            packages = previous
        else:
            packages = [item.strip().strip("`") for item in cell.split(",")]
        assert run not in named, run
        named[run] = packages
        previous = packages
    return named


def test_the_readme_names_instrumentation_for_each_of_the_twelve_captures():
    assert sorted(_readme_instrumentation()) == sorted(IDS)


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_readme_s_instrumentation_is_the_manifest_s(capture):
    project = zoo_census.manifest(capture)["project_manifest"]
    assert isinstance(project, dict)
    stated = project["instrumentation"]
    assert _readme_instrumentation()[capture.run] == stated, capture.run


def test_as_above_is_the_row_before_s_even_when_that_row_says_as_above():
    """R-3 (decisions log D24): the README never has two "as above"
    rows in a row, so the helper is held here by a hand-made table that does,
    with a stated row after them to show a new value takes over."""
    table = "\n".join(
        [
            "| `z9/a` | Z9 | `pkg-one`, `pkg-two` | 1 (1) | `x` |",
            "| `z9/b` | Z9 | as above | 1 (1) | `x` |",
            "| `z9/c` | Z9 | as above | 1 (1) | `x` |",
            "| `z9/d` | Z9 | `pkg-three` | 1 (1) | `x` |",
            "| `z9/e` | Z9 | as above | 1 (1) | `x` |",
        ]
    )
    assert _instrumentation_of(table) == {
        "z9/a": ["pkg-one", "pkg-two"],
        "z9/b": ["pkg-one", "pkg-two"],
        "z9/c": ["pkg-one", "pkg-two"],
        "z9/d": ["pkg-three"],
        "z9/e": ["pkg-three"],
    }


def test_the_readme_s_collector_is_every_manifest_s():
    readme = (ZOO / "README.md").read_text(encoding="utf-8")
    named = re.findall(r"Collector (\d+\.\d+\.\d+)", readme)
    assert named == ["0.162.0"]
    for capture in CAPTURES:
        stated = zoo_census.manifest(capture)["collector_version"]
        assert stated == named[0], capture.run


#: The counts the README's census paragraph spells, as words.
_SPELLED = {
    word: value
    for value, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}


def _census_paragraph(readme: str) -> str:
    """The README's paragraph that opens `**The census.**`, its lines joined.

    It runs to the next blank line or the end of the file; exactly one."""
    paragraphs = [" ".join(block.split()) for block in readme.split("\n\n")]
    found = [p for p in paragraphs if p.startswith("**The census.**")]
    assert len(found) == 1, found
    return found[0]


def _census_fields(paragraph: str) -> list[str]:
    """The counts the paragraph lists between its two dashes, in its order.

    Each item is a count's name, backticked or (`nodes`) bare, and maybe a noun
    after it ("`parent` and `temporal` edges"): the name is its first word."""
    listed = re.search(r"for each capture — (.+?) — and", paragraph)
    assert listed, paragraph
    items = re.split(r", | and ", listed.group(1))
    return [item.split()[0].strip("`") for item in items]


def _spelled_before(paragraph: str, pattern: str) -> list[int]:
    """Each count the paragraph spells as the word `pattern`'s group 1 matches."""
    return [_SPELLED[word] for word in re.findall(pattern, paragraph)]


def test_the_census_paragraph_parser_reads_a_bare_name_and_a_trailing_noun():
    """A hand-made paragraph: the bare first name and the nouns after a name
    are read as the README writes them, and a name the list drops is gone."""
    paragraph = (
        "**The census.** It holds two counts for each capture — nodes and"
        " `parent` edges — and, beside them, more."
    )
    assert _census_fields(paragraph) == ["nodes", "parent"]
    assert _spelled_before(paragraph, r"\bholds (\w+) counts\b") == [2]
    assert _census_fields(paragraph.replace(" and `parent` edges", "")) == ["nodes"]


def test_the_readme_s_census_paragraph_lists_census_s_fields_exactly():
    """R-20 (decisions log D24): the paragraph says it lists `Census`'s counts,
    and how many. Both are held to the dataclass, so a field added, dropped or
    renamed there, or a name or the number changed here, is red."""
    paragraph = _census_paragraph((ZOO / "README.md").read_text(encoding="utf-8"))
    names = [field.name for field in fields(Census)]
    assert _census_fields(paragraph) == names
    assert _spelled_before(paragraph, r"\bholds (\w+) counts\b") == [len(names)]


def test_the_readme_s_census_paragraph_says_what_the_whole_capture_adds():
    """R-20 (decisions log D24): "Z4's whole capture, one record more than the
    audit fed". The captures with a whole census are the project it names, and
    each holds that many records more than its audit feed."""
    paragraph = _census_paragraph((ZOO / "README.md").read_text(encoding="utf-8"))
    named = re.findall(r"\bZ(\d)'s whole capture\b", paragraph)
    whole = [capture for capture in CAPTURES if capture.whole is not None]
    assert {f"z{n}" for n in named} == {c.run.split("/")[0] for c in whole}
    more = _spelled_before(paragraph, r"\b(\w+) records? more than the audit fed\b")
    assert len(more) == 1, paragraph
    for capture in whole:
        extra = len(zoo_census.records(capture)) - len(zoo_census.audit_feed(capture))
        assert extra == more[0], capture.run


def test_the_readme_s_census_paragraph_states_when_the_census_moves():
    """R-20 (decisions log D24): the rule a change that moves a count follows
    is a sentence, not a count, so it is held as written."""
    paragraph = _census_paragraph((ZOO / "README.md").read_text(encoding="utf-8"))
    assert (
        "A change that moves a count updates the census in the commit that moves"
        " it, with the reason."
    ) in paragraph


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_every_child_s_record_comes_before_its_parent_s(capture):
    """`PROBES.md` S15: the exporter writes a span when it ends, so a child's
    record precedes its parent's. Not one pair in any capture runs the other
    way, and every stated parent the capture holds is such a pair: as many as
    the whole capture's `parent` edges."""
    before, after = zoo_census.exporter_order(capture)
    assert after == 0, capture.run
    whole = capture.whole if capture.whole is not None else capture.census
    assert before == whole.parent > 0, capture.run


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_each_body_s_records_are_contiguous_by_scope(capture):
    """`PROBES.md` S21: within a body, records are grouped by instrumentation
    scope, not interleaved in end order. Each scope is one run per body."""
    runs = zoo_census.scope_runs(capture)
    assert list(runs) == [path.name for path in zoo_census.bodies(capture)]
    for body, names in runs.items():
        assert len(names) == len(set(names)), (capture.run, body, names)
    assert {name for names in runs.values() for name in names} == capture.scopes


def test_scope_grouping_is_asserted_where_a_body_states_two_scopes():
    """Not vacuous: Z3, Z4 and Z6 each have a body with two scopes in it."""
    two = {
        capture.run.split("/")[0]
        for capture in CAPTURES
        if any(len(names) > 1 for names in zoo_census.scope_runs(capture).values())
    }
    assert two == {"z3", "z4", "z6"}


def _hand_made_body(*scopes: str) -> list[JsonValue]:
    """One OTLP body, a `scopeSpans` entry of one span per scope name given."""
    entries = [
        {
            "scope": {"name": name},
            "spans": [
                {
                    "traceId": "0" * 31 + "1",
                    "spanId": f"{index:016x}",
                    "name": f"span-{index}",
                }
            ],
        }
        for index, name in enumerate(scopes, start=1)
    ]
    body = json.dumps({"resourceSpans": [{"scopeSpans": entries}]}).encode()
    read = spanweave.read_records(body)
    assert not read.diagnostics and not read.skipped_records
    return list(read.records)


def test_scope_runs_splits_a_scope_that_comes_back_within_a_body():
    """R-3 (decisions log D24): `scope_runs` had no test of its own,
    so the contiguity test above was only as good as it. A body stating
    scopes A, B, A is three runs, not two; the next body starts afresh."""
    read = [
        zoo_census.Record(body, index, record)
        for body, scopes in (("0001.json", "ABA"), ("0002.json", "A"))
        for index, record in enumerate(_hand_made_body(*scopes), start=1)
    ]
    assert zoo_census.scope_runs_of(read) == {
        "0001.json": ["A", "B", "A"],
        "0002.json": ["A"],
    }


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_bodies_hold_the_records_and_the_trace_probes_md_names(capture):
    by_body: dict[str, int] = {}
    for record in zoo_census.records(capture):
        by_body[record.body] = by_body.get(record.body, 0) + 1
        assert isinstance(record.record, dict)
        assert record.record["trace_id"] == capture.trace_id
    assert tuple(by_body.values()) == capture.records_per_body


def test_the_census_places_every_capture_and_each_whole_it_counts_apart():
    assert list(STRUCTURES) == IDS
    assert list(WHOLE_STRUCTURES) == [c.run for c in CAPTURES if c.whole is not None]


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_audit_s_census_holds_batch_and_incremental(capture):
    feed = zoo_census.audit_feed(capture)
    batch, incremental = zoo_census.batch_and_incremental(feed)
    assert batch == incremental
    graph = graph_from_records(feed)
    assert graph.trace_id == capture.trace_id
    assert zoo_census.count(graph) == capture.census, capture.report
    # Where each node sits, and each edge with its basis (R-10): the bytes
    # above make the `Builder`'s graph this one, so both are held.
    assert zoo_census.structure(graph) == STRUCTURES[capture.run], capture.run


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_every_record_the_audit_left_out_is_one_no_adapter_claims(capture):
    """The records the audit's feed omits, and what the whole capture builds to.

    Z4's root span is claimed by no adapter (`PROBES.md` S1) and was routed to
    no trace (L2), so the audit's graph lacks it. Fed with the rest, `SPEC.md`
    §6.1 makes it one `unknown` node keyed and placed by its OTLP envelope
    (§3.6 rule 1, batch T1), and `Capture.whole` holds the counts that gives,
    each move from the audit's explained there.
    """
    every = zoo_census.records(capture)
    left_out = [r for r in every if (r.body, r.index) in set(capture.unrouted)]
    assert len(left_out) == len(capture.unrouted)
    assert all(classify(r.record) == () for r in left_out)
    assert all(classify(r.record) != () for r in every if r not in left_out)

    feed = [r.record for r in every]
    batch, incremental = zoo_census.batch_and_incremental(feed)
    assert batch == incremental
    graph = graph_from_records(feed)
    whole = capture.whole if capture.whole is not None else capture.census
    assert (capture.whole is None) == (not capture.unrouted)
    assert zoo_census.count(graph) == whole, capture.run
    placed = WHOLE_STRUCTURES.get(capture.run, STRUCTURES[capture.run])
    assert zoo_census.structure(graph) == placed, capture.run
    assert sum(d.code == "unclaimed_record" for d in graph.diagnostics) == len(left_out)


# --- A declared unit is not a suspicion (batch T2, `PROBES.md` S3) -----------

Z1 = next(c for c in CAPTURES if c.run == "z1/2026-10-13-recorded")


def test_a_declared_nanosecond_time_is_read_in_seconds_and_kept_verbatim():
    """Z1's capture: every span's unit is declared by `startTimeUnixNano`.

    The audit counted 31 `timestamp_unit_suspect` on 31 nodes -- the format,
    reported once per span. `SPEC.md` §3.1 (batch T2): a time whose field
    declares nanoseconds is read in unix seconds, the integer the export wrote
    stays verbatim in `raw.source`, and the suspicion is kept for a value whose
    unit nothing declared.
    """
    graph = graph_from_records(zoo_census.audit_feed(Z1))
    assert len(graph.nodes()) == 31
    assert [d for d in graph.diagnostics if d.code == "timestamp_unit_suspect"] == []
    for node in graph.nodes():
        source = node.raw.source
        assert isinstance(source, dict)
        for field, value in (
            ("start_time", node.started_at),
            ("end_time", node.ended_at),
        ):
            stated = source[field]
            # The nanosecond string, verbatim: nothing is lost.
            assert isinstance(stated, str) and stated.isdigit(), (node.id, field)
            # ... and the field holds unix seconds, the nearest float to it.
            assert isinstance(value, float), (node.id, field)
            assert value == int(stated) / 1_000_000_000, (node.id, field)
            assert 1e9 < value < 1e11, (node.id, field)


# --- The envelope is not an unmapped attribute (batch T3, `PROBES.md` S4, S7,
# S8, S10; S6 and S21 by the envelope) -------------------------------------

Z3 = next(c for c in CAPTURES if c.run == "z3/2026-10-13-real")
ENVELOPE_KEYS = {
    "<record>.flags",
    "<record>.kind",
    "<record>.resource_spans",
    "<record>.scope_spans",
}


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_scopes_are_read_from_each_record_s_envelope(capture):
    assert zoo_census.scope_names(capture) == capture.scopes


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_no_node_reports_its_envelope_as_unmapped(capture):
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    for diagnostic in graph.diagnostics:
        if diagnostic.code == "unmapped_attributes":
            named = set(diagnostic.source)
            assert not named & ENVELOPE_KEYS, diagnostic.node_id
            assert "<record>.droppedAttributesCount" not in named, diagnostic.node_id
    # ... and every key is still in the record, verbatim (SPEC.md §7).
    for node in graph.nodes():
        source = node.raw.source
        assert isinstance(source, dict)
        assert {"resource_spans", "scope_spans", "kind"} <= set(source), node.id


def test_z3_reports_75_unmapped_and_18_dropped_counts_the_export_states():
    """Z3's real capture: two instrumentors, 102 spans, 18 dropped counts.

    The audit counted 102 `unmapped_attributes`, one per node, each naming the
    four envelope keys; 27 named nothing else. Since T3 those 27 report
    nothing, and the 18 spans whose export says attributes were dropped carry
    an `attributes_dropped` warning stating the count, which names none.
    """
    feed = zoo_census.audit_feed(Z3)
    graph = graph_from_records(feed)
    unmapped = [d for d in graph.diagnostics if d.code == "unmapped_attributes"]
    assert len(unmapped) == 75
    dropped = [d for d in graph.diagnostics if d.code == "attributes_dropped"]
    assert len(dropped) == 18
    nodes = {node.id: node for node in graph.nodes()}
    for diagnostic in dropped:
        assert diagnostic.level == "warning"
        assert diagnostic.node_id is not None
        source = nodes[diagnostic.node_id].raw.source
        assert isinstance(source, dict)
        assert diagnostic.source == {"count": source["droppedAttributesCount"]}
    carrying = {
        node.id
        for node in graph.nodes()
        if isinstance(node.raw.source, dict)
        and node.raw.source.get("droppedAttributesCount")
    }
    assert {d.node_id for d in dropped} == carrying
    # S10: a model the span does not state stays absent; the dropped count is
    # not a reason to look for one anywhere else.
    without_a_model = [
        nodes[node_id]
        for node_id in carrying
        if "llm.model_name" not in nodes[node_id].raw.source["attributes"]
    ]
    assert len(without_a_model) == 9
    assert all("model" not in node.attributes for node in without_a_model)


def test_z3_states_two_scopes_on_one_graph():
    assert zoo_census.scope_names(Z3) == {
        "openinference.instrumentation.openai_agents",
        "openinference.instrumentation.openai",
    }


# --- A span's events are reported (batch T4, `PROBES.md` S11, S17) ----------
#
# `OPEN_QUESTIONS.md` §22, option 2; `SPEC.md` §3.7, §7. Each OTLP span event
# is an `info` diagnostic on its node -- `exception_event` for the OpenTelemetry
# API's `exception` event, `span_event` for any other -- and the events stay
# verbatim in `raw.source`. The failure stays where the telemetry put it: the
# node's `status`.

Z5S = [c for c in CAPTURES if c.run.startswith("z5/")]
Z2S = [c for c in CAPTURES if c.run.startswith("z2/")]
NS = 1_000_000_000


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_no_unpacked_node_reports_its_events_as_unmapped(capture):
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    for diagnostic in graph.diagnostics:
        if diagnostic.code == "unmapped_attributes":
            assert not any(
                key.startswith("<record>.events") for key in diagnostic.source
            ), diagnostic.node_id


@pytest.mark.parametrize("capture", Z5S, ids=[c.run for c in Z5S])
def test_z5_s_two_exceptions_are_info_diagnostics_on_the_two_failed_tool_nodes(
    capture,
):
    graph = graph_from_records(zoo_census.audit_feed(capture))
    nodes = {node.id: node for node in graph.nodes()}
    raised = [d for d in graph.diagnostics if d.code == "exception_event"]
    assert len(raised) == 2
    failed = {
        node.id
        for node in graph.nodes()
        if node.name == "http_get" and node.status == "error"
    }
    assert len(failed) == 2
    assert {d.node_id for d in raised} == failed
    messages = []
    for diagnostic in raised:
        assert diagnostic.level == "info"
        assert diagnostic.adapter == nodes[diagnostic.node_id].provenance.adapter_id
        source = diagnostic.source
        assert isinstance(source, dict)
        # Four keys: the stacktrace is not copied, it stays in `raw.source`.
        assert set(source) == {"type", "message", "escaped", "time"}
        assert source["type"] == "ConnectionError"
        assert source["escaped"] == "False"  # as the attribute states it
        (event,) = nodes[diagnostic.node_id].raw.source["events"]
        assert source["time"] == int(event["timeUnixNano"]) / NS
        assert isinstance(source["time"], float)
        assert any(a["key"] == "exception.stacktrace" for a in event["attributes"])
        messages.append(source["message"])
    assert sorted(m[-len("(attempt 1)") :] for m in messages) == [
        "(attempt 1)",
        "(attempt 2)",
    ]
    assert not [d for d in graph.diagnostics if d.code == "span_event"]


@pytest.mark.parametrize("capture", Z2S, ids=[c.run for c in Z2S])
def test_z2_s_first_token_events_are_kept_as_reported_after_the_span_ended(capture):
    graph = graph_from_records(zoo_census.audit_feed(capture))
    nodes = {node.id: node for node in graph.nodes()}
    events = [d for d in graph.diagnostics if d.code == "span_event"]
    assert len(events) == 2
    for diagnostic in events:
        assert diagnostic.level == "info"
        assert diagnostic.source["name"] == "First Token Stream Event"
        assert set(diagnostic.source) == {"name", "time"}
        node = nodes[diagnostic.node_id]
        assert node.ended_at is not None
        # After the node's end, as the export states it; nothing is repaired.
        assert diagnostic.source["time"] > node.ended_at
    assert not [d for d in graph.diagnostics if d.code == "exception_event"]


def test_z2_states_four_first_token_events_over_its_two_captures():
    total = 0
    for capture in Z2S:
        graph = graph_from_records(zoo_census.audit_feed(capture))
        total += sum(d.code == "span_event" for d in graph.diagnostics)
    assert total == 4


# --- Siblings are grouped by the parent the record states (batch T5) ---------
#
# `PROBES.md` S18: the zoo's exporters send a child before its parent (S15), so
# every prefix of a capture is a partial input. A sibling group is the parent
# the record **states** (`SPEC.md` §4.3) -- `""` for a root, the stated id for
# every other node, present or not -- so a prefix orders an orphan only against
# nodes stating the same parent, and asserts no order the whole capture withdraws.

Z2_REAL = next(c for c in CAPTURES if c.run == "z2/2026-10-14-real")


def test_z2_s_first_body_alone_orders_only_the_two_that_state_one_parent():
    first = [r.record for r in zoo_census.records(Z2_REAL) if r.body == "0001.json"]
    assert len(first) == 3
    graph = graph_from_records(first)
    assert sum(d.code == "orphan_parent" for d in graph.diagnostics) == 3
    stated = sorted(str(stated_parent(graph, node.id)) for node in graph.nodes())
    assert stated == ["539a254a824d5e2a", "86a464c4b18af821", "86a464c4b18af821"]
    (edge,) = graph.edges(kind="temporal")
    assert edge.basis.startswith("sibling start_time ordering")
    assert stated_parent(graph, edge.src) == "86a464c4b18af821"
    assert stated_parent(graph, edge.dst) == "86a464c4b18af821"


def stated_parent(graph, node_id):
    """The parent a node's record states, read from its OTLP envelope."""
    node = graph.node(node_id)
    assert node is not None
    return spanweave.envelope(node.raw.source).parent_id


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_no_prefix_orders_two_nodes_the_whole_capture_leaves_unordered(capture):
    """Every `temporal` edge of every arrival-order prefix is an order the whole
    capture's graph also states, through its own chain (`SPEC.md` §4.3, §10.1)."""
    feed = [r.record for r in zoo_census.records(capture)]
    whole = graph_from_records(feed)
    after = {
        node.id: set(whole.reachable(node.id, edge_kinds="temporal"))
        for node in whole.nodes()
    }
    for k in range(1, len(feed)):
        for edge in graph_from_records(feed[:k]).edges(kind="temporal"):
            if edge.src in after and edge.dst in after:
                assert edge.dst in after[edge.src], (k, edge.src, edge.dst)
