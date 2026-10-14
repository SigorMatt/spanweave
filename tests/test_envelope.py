"""The OTLP envelope is public, and an unclaimed record is keyed and placed by it.

Batch T1 of the stranger's-trace series (`OPEN_QUESTIONS.md` §20, option 1;
`SPEC.md` §3.6 rule 1, §6.1, §7). Answers the zoo's S1, S2 and S12 on Z4's real
capture: the root span `concierge.conversation` is claimed by no adapter, and
its four `llm` children state it as their parent. While the unclaimed node was
keyed by its digest the children found no node with the id they named, and the
graph reported four orphans of a parent it was holding.

The envelope is the nine keys the reader renamed out of an OTLP span (§7):
the transport's statement, made before any adapter was asked. A record the
reader did not unpack carries no envelope, whatever keys it happens to have.
"""

from __future__ import annotations

import collections
import json

import pytest

import spanweave
from spanweave.api import graph_from_records
from spanweave.ids import derive
from spanweave.model import EdgeKind, NodeKind, Status
from spanweave.read import record_digest
from tests import zoo_census

Z4 = next(c for c in zoo_census.CAPTURES if c.run == "z4/2026-10-12-real")
ROOT_SPAN = "3013a003149d6951"
ROOT_NAME = "concierge.conversation"
# The root's `startTimeUnixNano` / `endTimeUnixNano` in 0002.json, record 2,
# read by SPEC.md §3.1's rule for a numeric string and, because the field
# declares nanoseconds, converted to unix seconds (batch T2). The strings the
# export wrote stay verbatim in `raw.source`.
ROOT_STATED = ("1791811595970001116", "1791811600669457537")
ROOT_STARTED = 1791811595970001116 / 1_000_000_000
ROOT_ENDED = 1791811600669457537 / 1_000_000_000


def _z4() -> list[spanweave.model.JsonValue]:
    """All five records of Z4's real capture, both bodies, in body order."""
    return [r.record for r in zoo_census.records(Z4)]


def _codes(graph: spanweave.Graph) -> collections.Counter[str]:
    return collections.Counter(d.code for d in graph.diagnostics)


def test_every_z4_record_has_an_envelope_and_they_share_one_trace():
    envelopes = [spanweave.envelope(record) for record in _z4()]
    assert len(envelopes) == 5
    assert {e.trace_id for e in envelopes} == {Z4.trace_id}
    root = next(e for e in envelopes if e.span_id == ROOT_SPAN)
    assert root.parent_id is None
    assert root.name == ROOT_NAME
    assert (root.started_at, root.ended_at) == (ROOT_STARTED, ROOT_ENDED)
    assert root.status is Status.UNSET
    assert root.status_note is None
    children = [e for e in envelopes if e.span_id != ROOT_SPAN]
    assert {e.parent_id for e in children} == {ROOT_SPAN}


def test_the_unclaimed_root_is_keyed_and_placed_by_its_envelope():
    graph = graph_from_records(_z4())
    nodes = graph.nodes()
    edges = collections.Counter(edge.kind for edge in graph.edges())
    codes = _codes(graph)
    assert len(nodes) == 5
    assert edges[EdgeKind.PARENT] == 4
    assert codes["orphan_parent"] == 0
    assert codes["unclaimed_record"] == 1
    assert codes["missing_timestamp"] == 0

    unknown = [n for n in nodes if n.kind is NodeKind.UNKNOWN]
    assert len(unknown) == 1
    (root,) = unknown
    assert root.id == ROOT_SPAN
    assert root.name == ROOT_NAME
    assert graph.trace_id == Z4.trace_id
    assert (root.started_at, root.ended_at) == (ROOT_STARTED, ROOT_ENDED)
    assert (root.raw.source["start_time"], root.raw.source["end_time"]) == ROOT_STATED
    assert root.provenance.adapter_id is None
    assert root.provenance.adapter_version is None
    assert {e.src for e in graph.edges() if e.kind is EdgeKind.PARENT} == {ROOT_SPAN}
    assert all(
        e.warrant is spanweave.Warrant.EXPLICIT
        for e in graph.edges()
        if e.kind is EdgeKind.PARENT
    )
    (said,) = [d for d in graph.diagnostics if d.code == "unclaimed_record"]
    assert said.node_id == ROOT_SPAN
    assert "attributes" in said.message


def test_the_whole_capture_builds_the_same_batch_incremental_and_shuffled():
    feed = _z4()
    batch, incremental = zoo_census.batch_and_incremental(feed)
    assert batch == incremental
    assert spanweave.dumps(graph_from_records(list(reversed(feed)))) == batch


def test_an_orphan_still_names_the_parent_it_stated():
    """S12: without the root, each child's `orphan_parent` carries its id."""
    children = [r for r in _z4() if spanweave.envelope(r).span_id != ROOT_SPAN]
    graph = graph_from_records(children)
    orphans = [d for d in graph.diagnostics if d.code == "orphan_parent"]
    assert len(orphans) == 4
    assert {d.source for d in orphans} == {ROOT_SPAN}


def test_a_flat_record_with_a_span_id_key_is_not_an_envelope():
    """A key named `span_id` in a file that declared no envelope is not one."""
    flat = {"trace_id": "t1", "span_id": "abc", "name": "x", "start_time": 1.0}
    with pytest.raises(spanweave.EnvelopeError) as raised:
        spanweave.envelope(flat)
    assert raised.value.code == "not_an_envelope"

    read = spanweave.read_records(json.dumps(flat).encode() + b"\n")
    (record,) = read.records
    with pytest.raises(spanweave.EnvelopeError):
        spanweave.envelope(record)

    # Claimed by no adapter, so §6.1's verbatim rendering, keyed by digest.
    claimed = {
        "trace_id": "t1",
        "span_id": "s1",
        "attributes": {"openinference.span.kind": "LLM"},
    }
    graph = graph_from_records([claimed, record])
    (unknown,) = [n for n in graph.nodes() if n.kind is NodeKind.UNKNOWN]
    assert unknown.id == derive(None, graph.trace_id, record_digest(flat))
    assert unknown.id.startswith("sw_")
    assert unknown.name == ""
    assert unknown.started_at is None


def test_the_mark_survives_reading_and_does_not_survive_a_copy_through_json():
    (record, *_) = _z4()
    assert spanweave.envelope(record).trace_id == Z4.trace_id
    with pytest.raises(spanweave.EnvelopeError):
        spanweave.envelope(json.loads(json.dumps(record)))


def _export(span: dict[str, object]) -> bytes:
    return json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}).encode()


def test_an_unpacked_record_missing_an_id_raises_and_its_node_falls_back():
    read = spanweave.read_records(
        _export({"traceId": "t1", "name": "no id", "startTimeUnixNano": "5"})
    )
    (record,) = read.records
    with pytest.raises(spanweave.EnvelopeError) as raised:
        spanweave.envelope(record)
    assert raised.value.code == "not_an_envelope"
    assert "span_id" in str(raised.value)

    claimed = {
        "trace_id": "t1",
        "span_id": "s1",
        "attributes": {"openinference.span.kind": "LLM"},
    }
    graph = graph_from_records([claimed, record])
    (unknown,) = [n for n in graph.nodes() if n.kind is NodeKind.UNKNOWN]
    assert unknown.id == derive(None, graph.trace_id, record_digest(record))
    assert unknown.name == ""


def test_an_envelope_level_with_no_spans_has_no_envelope():
    read = spanweave.read_records(
        json.dumps({"resourceSpans": [{"resource": {"attributes": []}}]}).encode()
    )
    (record,) = read.records
    with pytest.raises(spanweave.EnvelopeError):
        spanweave.envelope(record)


def test_an_envelope_reads_status_and_an_empty_parent_as_the_record_states():
    read = spanweave.read_records(
        _export(
            {
                "traceId": "t1",
                "spanId": "s9",
                "parentSpanId": "",
                "name": "n",
                "startTimeUnixNano": "1700000000000000000",
                "endTimeUnixNano": "1700000001000000000",
                "status": {"code": 2, "message": "boom"},
            }
        )
    )
    (record,) = read.records
    envelope = spanweave.envelope(record)
    assert envelope.parent_id is None
    assert envelope.status is Status.ERROR
    assert envelope.status_note == "boom"
    # The field declares nanoseconds, so the envelope reads seconds (T2).
    assert (envelope.started_at, envelope.ended_at) == (1700000000.0, 1700000001.0)


def test_an_envelope_field_of_the_wrong_type_raises():
    read = spanweave.read_records(
        _export({"traceId": "t1", "spanId": "s9", "name": 42})
    )
    (record,) = read.records
    with pytest.raises(spanweave.EnvelopeError) as raised:
        spanweave.envelope(record)
    assert "name" in str(raised.value)


def test_an_unpacked_record_and_an_equal_flat_one_are_two_records_in_either_order():
    """SPEC.md §7: they parse equal, and only one of them carries an envelope.

    Collapsing them as duplicates would keep whichever came first, and the
    unclaimed node's id would then depend on which line was first (§5.2).
    """
    span = {"traceId": "t1", "spanId": "s9", "name": "n"}
    (unpacked,) = spanweave.read_records(_export(span)).records
    flat = json.dumps(dict(unpacked)).encode()
    claimed = json.dumps(
        {
            "trace_id": "t1",
            "span_id": "s1",
            "attributes": {"openinference.span.kind": "LLM"},
        }
    ).encode()
    lines = [_export(span), flat, claimed]
    built = []
    for order in (lines, list(reversed(lines))):
        read = spanweave.read_records(b"\n".join(order) + b"\n")
        assert len(read.records) == 3
        assert not [d for d in read.diagnostics if d.code == "duplicate_record"]
        built.append(spanweave.dumps(graph_from_records(list(read.records))))
    assert built[0] == built[1]
    graph = graph_from_records(
        list(spanweave.read_records(b"\n".join(lines) + b"\n").records)
    )
    ids = sorted(n.id for n in graph.nodes() if n.kind is NodeKind.UNKNOWN)
    assert len(ids) == 2
    assert "s9" in ids
