"""The zoo's captures are a fixture, and the audit's census is a gate.

Two claims, each re-derived on every run (`make conformance` runs this file):

* `fixtures/zoo/` is the zoo's record, byte for byte: every body's sha256 is
  the one its capture's sealed manifest gives, every manifest's seal is the one
  its own claims compute to, and the copy holds exactly the `json/` bodies the
  manifests list -- none missing, none added (`fixtures/zoo/README.md`).
* The counts the zoo's audit reported (`tests/zoo_census.py`, each citing its
  report) are what this library builds from those bytes, batch and incremental
  alike, with the records fed in the exporter's order: child before parent
  (`PROBES.md` S15), grouped by instrumentation scope (S21).
"""

from __future__ import annotations

import pytest

from spanweave.adapters import classify
from spanweave.api import graph_from_records
from tests import zoo_census
from tests.zoo_census import CAPTURES, ZOO, ZOO_BODY_DIR, Capture

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


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_bodies_hold_the_records_and_the_trace_probes_md_names(capture):
    by_body: dict[str, int] = {}
    for record in zoo_census.records(capture):
        by_body[record.body] = by_body.get(record.body, 0) + 1
        assert isinstance(record.record, dict)
        assert record.record["trace_id"] == capture.trace_id
    assert tuple(by_body.values()) == capture.records_per_body


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_the_audit_s_census_holds_batch_and_incremental(capture):
    feed = zoo_census.audit_feed(capture)
    batch, incremental = zoo_census.batch_and_incremental(feed)
    assert batch == incremental
    graph = graph_from_records(feed)
    assert graph.trace_id == capture.trace_id
    assert zoo_census.count(graph) == capture.census, capture.report


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
