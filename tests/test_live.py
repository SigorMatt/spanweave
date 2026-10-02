"""The incremental builder (`SPEC.md` §10) -- one record at a time.

Every test here is one shape of the same assertion: at version `k` the live
graph **is** `build(records[:k])`. Prefix consistency is the definition
(`OPEN_QUESTIONS.md` §18), so a test that asserts anything else about a live
graph would be inventing a second contract.

The cross-dialect corpus carries the same claim over every fixture
(`tests/test_conformance.py`, conformance gate 1). What is here is the cases
whose *arrival order* is the point -- a parent that arrives after its child, a
call fulfilled two records later, a receipt redeclared out of order -- because
a corpus file has one order and these need two.
"""

import copy
import inspect
import itertools
import json
import sys

import pytest

import spanweave
from spanweave import diagnostics as codes
from spanweave.adapters import REGISTRY, register
from spanweave.api import graph_from_records
from spanweave.build import DATA_BASIS, DATA_LATER_BASIS, DATA_TIED_BASIS
from spanweave.errors import AdapterSelectionError, DuplicateNodeIdError
from spanweave.ids import derive
from spanweave.model import EdgeKind, NodeKind, RawRecord
from spanweave.read import record_digest
from spanweave.seam import CallRole, NormalizedSpan
from spanweave.serialize import DELTA_ROOT_KEYS, ROOT_KEYS, dumps
from tests.delta_oracle import checkpoint_delta


def oi(span_id, parent=None, kind="TOOL", name="op", t0=1000.0, t1=1000.5, **attrs):
    """One OpenInference record, as flat as the dialect allows."""
    return {
        "trace_id": attrs.pop("trace_id", "t1"),
        "span_id": span_id,
        "parent_id": parent,
        "name": name,
        "start_time": t0,
        "end_time": t1,
        "status": "OK",
        "attributes": {"openinference.span.kind": kind, **attrs},
    }


def requester(span_id, call_id, **kw):
    """An LLM span that asks for one tool call."""
    return oi(
        span_id,
        kind="LLM",
        name="llm.plan",
        **{
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": call_id,
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "f",
            **kw,
        },
    )


def fulfiller(span_id, call_id, **kw):
    """A tool span that fulfils one call."""
    return oi(span_id, kind="TOOL", name="tool.f", **{"tool_call.id": call_id, **kw})


def receiver(span_id, call_id, t0, **kw):
    """An LLM span declaring that it was handed one call's result."""
    messages = [
        {
            "message.role": "tool",
            "message.tool_call_id": call_id,
            "message.content": "x",
        }
    ]
    flat = {}
    for index, message in enumerate(messages):
        for key, value in message.items():
            flat[f"llm.input_messages.{index}.{key}"] = value
    return oi(span_id, kind="LLM", name="llm.answer", t0=t0, t1=t0 + 0.1, **flat, **kw)


def replay(records, **kw):
    """Feed the records one at a time, comparing at every version.

    The whole contract, in five lines: the version is the arrival index, and
    the graph at that version equals the batch build of the same prefix --
    compared as a value *and* as the bytes it serializes to, since "byte for
    byte" is what `OPEN_QUESTIONS.md` §18 asked for and graph equality alone
    would not catch a field the writer orders differently.
    """
    builder = spanweave.Builder(**kw)
    assert builder.version == 0
    for index, record in enumerate(records, start=1):
        assert builder.feed(record) == index
        assert builder.version == index
        live = builder.graph()
        batch = graph_from_records(records[:index], **kw)
        assert live == batch, f"version {index} is not build(records[:{index}])"
        assert dumps(live) == dumps(batch)
    return builder


def codes_of(graph):
    return sorted(diagnostic.code for diagnostic in graph.diagnostics)


# --------------------------------------------------------------------------
# The API the decision fixed
# --------------------------------------------------------------------------


def test_feed_returns_the_new_version_as_an_int():
    builder = spanweave.Builder()
    first = builder.feed(oi("s1"))
    assert first == 1
    assert type(first) is int
    assert builder.feed(oi("s2")) == 2
    assert builder.version == 2


def test_feed_takes_no_delta_flag():
    """`WORKPLAN.md` §3, L1(4): every delta comes from `delta(since=v)`.

    Asserted on the signature rather than left to a comment, because "feed
    returns the new version and nothing else" is the part of the decision a
    later batch could quietly widen.
    """
    parameters = inspect.signature(spanweave.Builder.feed).parameters
    assert list(parameters) == ["self", "record"]


def test_the_builder_is_on_the_public_api():
    assert "Builder" in spanweave.__all__


# --------------------------------------------------------------------------
# Prefix consistency, where arrival order is the point
# --------------------------------------------------------------------------


def test_a_parent_that_arrives_after_its_child():
    """The case that makes arrival order and canonical order differ."""
    child = oi("s2", parent="s1", t0=1001.0)
    parent = oi("s1", kind="AGENT", name="agent", t0=1000.0)
    builder = replay([child, parent])
    graph = builder.graph()
    assert graph.topo_order == ("s1", "s2")
    assert [(e.src, e.dst) for e in graph.edges(kind=EdgeKind.PARENT)] == [("s1", "s2")]
    assert codes.ORPHAN_PARENT not in codes_of(graph)


def test_an_orphan_parent_is_true_while_it_is_true():
    """A diagnostic on a live graph is a statement about what has arrived."""
    builder = spanweave.Builder()
    builder.feed(oi("s2", parent="s1"))
    assert codes.ORPHAN_PARENT in codes_of(builder.graph())
    builder.feed(oi("s1", kind="AGENT", name="agent", t0=1000.0))
    assert codes.ORPHAN_PARENT not in codes_of(builder.graph())


def test_a_call_fulfilled_by_a_later_record():
    builder = replay([requester("s1", "call_a"), fulfiller("s2", "call_a", t0=1001.0)])
    graph = builder.graph()
    assert codes.UNPAIRED_CALL not in codes_of(graph)
    assert [(e.src, e.dst) for e in graph.edges(kind=EdgeKind.CALL_RESULT)] == [
        ("s1", "s2")
    ]


def test_a_result_that_arrives_before_the_span_that_asked_for_it():
    builder = replay([fulfiller("s2", "call_a", t0=1001.0), requester("s1", "call_a")])
    assert codes.UNPAIRED_RESULT not in codes_of(builder.graph())


def test_a_receipt_redeclared_out_of_order_rewrites_the_basis():
    """The later receiver arrives first, so `basis` moves when the earlier one
    lands (`SPEC.md` §4.2.1)."""
    records = [
        fulfiller("s1", "call_a", t0=1000.0),
        receiver("s3", "call_a", t0=1002.0),
        receiver("s2", "call_a", t0=1001.0),
    ]
    builder = replay(records)
    graph = builder.graph()
    bases = {edge.dst: edge.basis for edge in graph.edges(kind=EdgeKind.DATA)}
    assert "earliest" not in bases["s2"]
    assert "not the earliest" in bases["s3"]


def test_a_sibling_inserted_between_two_others():
    """Two temporal edges out, two in -- the middle record arrives last."""
    records = [
        oi("s0", kind="AGENT", name="agent", t0=1000.0),
        oi("s1", parent="s0", t0=1001.0),
        oi("s3", parent="s0", t0=1003.0),
        oi("s2", parent="s0", t0=1002.0),
    ]
    builder = replay(records)
    chain = [
        (edge.src, edge.dst) for edge in builder.graph().edges(kind=EdgeKind.TEMPORAL)
    ]
    assert chain == [("s1", "s2"), ("s2", "s3")]


def test_a_scrambled_sibling_group_is_the_batch_chain_at_every_prefix():
    """The chain is maintained rather than rebuilt, so every arrival position
    inside it is a case: front, back, and between two members already there.

    `replay` is the whole assertion -- the graph at each version is the batch
    build of that prefix, byte for byte -- and the shape is chosen so that the
    arrivals land all over the group instead of appending to it. The evens
    arrive in order and then every odd lands strictly inside, which is the
    insertion that has an edge to *remove* as well as two to add.
    """
    children = [index for index in range(0, 12, 2)] + [
        index for index in range(1, 12, 2)
    ]
    records = [oi("s0", kind="AGENT", name="agent", t0=1000.0)] + [
        oi(f"t{index:02d}", parent="s0", t0=1001.0 + index) for index in children
    ]
    builder = replay(records)
    chain = [
        (edge.src, edge.dst) for edge in builder.graph().edges(kind=EdgeKind.TEMPORAL)
    ]
    assert chain == [(f"t{i:02d}", f"t{i + 1:02d}") for i in range(11)]


def test_a_whole_root_group_moves_when_its_parent_arrives_last():
    """The arrival that moves every record at trace root at once (§10.1, §10.6).

    The companion of the test below, which keeps one record at trace root so the
    group is only *partly* emptied: here nothing else is there, so the arrival
    re-keys the group instead of moving child by child, and the two tests are the
    two halves of `_regroup_many`. `replay` is the whole assertion -- the graph
    at every version is the batch build of that prefix, which includes the
    version before the parent arrives, where all six are still at root.

    The children arrive scrambled, so the order the group is re-keyed *in* is
    not the order it was built in: the evens append and then every odd lands
    strictly inside, which is the insertion `_join` has an edge to remove for.
    """
    order = [index for index in range(0, 6, 2)] + [index for index in range(1, 6, 2)]
    records = [oi(f"c{index}", parent="s0", t0=1001.0 + index) for index in order]
    records.append(oi("s0", kind="AGENT", name="agent", t0=1000.0))
    builder = replay(records)
    assert chain_of(builder.graph()) == [(f"c{i}", f"c{i + 1}") for i in range(5)]


def test_several_children_regroup_when_their_parent_arrives_last():
    """A record given a parent leaves the root group for its parent's, and both
    chains have to be right afterwards -- the one it left as much as the one it
    joined (`SPEC.md` §4.3, §10.2)."""
    children = [oi(f"c{index}", parent="s0", t0=1001.0 + index) for index in range(5)]
    other = oi("r1", t0=999.0)
    records = [*children, other, oi("s0", kind="AGENT", name="agent", t0=1000.0)]
    builder = replay(records)
    chain = [
        (edge.src, edge.dst) for edge in builder.graph().edges(kind=EdgeKind.TEMPORAL)
    ]
    assert chain == [
        ("c0", "c1"),
        ("c1", "c2"),
        ("c2", "c3"),
        ("c3", "c4"),
        ("r1", "s0"),
    ]


def test_the_majority_trace_id_can_change_with_an_arrival():
    """Every derived id holds the trace id, so this one moves ids."""
    records = [
        oi("s1", trace_id="t1"),
        oi("s2", trace_id="t2"),
        oi("s3", trace_id="t2"),
    ]
    graph = replay(records).graph()
    assert graph.trace_id == "t2"
    assert codes.MULTI_TRACE_INPUT in codes_of(graph)


def test_a_dialect_span_id_that_stops_being_unique():
    """`SPEC.md` §3.6: the first record's id moves off rule 1 when the second
    claims the same span id."""
    records = [oi("s1", name="alpha"), oi("s1", name="beta", t0=1001.0)]
    builder = spanweave.Builder()
    builder.feed(records[0])
    assert builder.graph().topo_order == ("s1",)
    builder.feed(records[1])
    assert "s1" not in builder.graph().topo_order
    replay(records)


def test_a_record_no_adapter_claims():
    records = [oi("s1"), {"nothing": "recognizable"}]
    graph = replay(records).graph()
    assert codes.UNCLAIMED_RECORD in codes_of(graph)


def test_two_dialects_in_one_stream():
    genai = {
        "trace_id": "t1",
        "span_id": "g1",
        "parent_id": None,
        "name": "chat demo-model",
        "start_time": 1002.0,
        "end_time": 1002.5,
        "status": "OK",
        "attributes": {"gen_ai.operation.name": "chat", "gen_ai.request.model": "m"},
    }
    graph = replay([oi("s1"), genai]).graph()
    assert graph.meta is not None
    assert len(graph.meta.adapters) == 2


def test_temporal_false_is_carried_through():
    records = [oi("s1", t0=1000.0), oi("s2", t0=1001.0)]
    graph = replay(records, temporal=False).graph()
    assert graph.edges(kind=EdgeKind.TEMPORAL) == ()


def test_a_named_adapter_skips_classification():
    graph = replay([oi("s1")], adapter="openinference").graph()
    assert graph.meta is not None
    assert [a.id for a in graph.meta.adapters] == ["openinference"]
    assert graph.meta.adapters[0].declared_confidence is None


# --------------------------------------------------------------------------
# Refusals: a prefix the batch build refuses, the live builder refuses too
# --------------------------------------------------------------------------


def test_an_empty_builder_refuses_exactly_as_an_empty_input_does():
    builder = spanweave.Builder()
    with pytest.raises(AdapterSelectionError) as live:
        builder.graph()
    with pytest.raises(AdapterSelectionError) as batch:
        graph_from_records([])
    assert live.value.code == batch.value.code


def test_a_stream_nothing_claims_refuses_rather_than_building_unknowns():
    builder = spanweave.Builder()
    builder.feed({"nothing": "recognizable"})
    with pytest.raises(AdapterSelectionError):
        builder.graph()


def test_a_record_two_adapters_claim_names_its_arrival_index():
    both = oi("s1", **{"gen_ai.operation.name": "chat", "gen_ai.request.model": "m"})
    kept = oi("s0", kind="AGENT", name="agent", t0=999.0)
    builder = spanweave.Builder()
    builder.feed(kept)
    with pytest.raises(AdapterSelectionError) as refused:
        builder.feed(both)
    assert "record 2" in str(refused.value)
    # The refused record was not absorbed: nothing half-arrived.
    assert builder.version == 1
    assert dumps(builder.graph()) == dumps(unrefused([kept]))


def unrefused(records, **kw):
    """The graph a builder fed exactly `records` answers with.

    Taken from a *second* builder rather than from `graph()` before the
    refusal, because materializing caches the graph until the next `feed`
    (`SPEC.md` §10) -- so a builder left corrupt by a refusal would hand the
    cached answer back and the comparison would pass on a graph it can no
    longer produce. Equal to `graph_from_records(records)` by §10.1; the point
    of asking a builder is that it is the same code path under test.
    """
    builder = spanweave.Builder(**kw)
    for record in records:
        builder.feed(record)
    return builder.graph()


def test_a_refused_duplicate_node_id_leaves_the_builder_as_it_was():
    """`SPEC.md` §10.5, fourth bullet: refused as §3.6 refuses it, and refused
    means the record never arrived -- an exporter that resends one span does
    not cost the builder every version after it."""
    builder = spanweave.Builder()
    builder.feed(oi("s0"))
    before = dumps(unrefused([oi("s0")]))
    with pytest.raises(DuplicateNodeIdError) as refused:
        builder.feed(oi("s0"))
    assert refused.value.code == "duplicate_node_id"
    assert builder.version == 1
    assert dumps(builder.graph()) == before


def test_a_feed_after_a_refused_duplicate_is_the_build_without_the_refusal():
    """The version the refusal did not take is the version the next record
    does, and the graph at it is the batch build of the records that landed."""
    builder = spanweave.Builder()
    builder.feed(oi("s0"))
    with pytest.raises(DuplicateNodeIdError):
        builder.feed(oi("s0"))
    assert builder.feed(oi("s1", t0=1001.0)) == 2
    kept = [oi("s0"), oi("s1", t0=1001.0)]
    assert builder.graph() == graph_from_records(kept)
    assert dumps(builder.graph()) == dumps(graph_from_records(kept))


def test_a_refused_duplicate_moves_no_id_the_builder_had_given_out():
    """The refusal arrives on the path that restates every record (§10.2): a
    second claim on one source key moves ids already given out, and the id the
    arriving record would take is decided before any of them does."""
    builder = spanweave.Builder()
    builder.feed(requester("s0", "c1"))
    builder.feed(fulfiller("s1", "c1", t0=1001.0))
    before = dumps(unrefused([requester("s0", "c1"), fulfiller("s1", "c1", t0=1001.0)]))
    with pytest.raises(DuplicateNodeIdError):
        builder.feed(fulfiller("s1", "c1", t0=1001.0))
    assert builder.version == 2
    assert dumps(builder.graph()) == before
    assert [node.id for node in builder.graph().nodes()] == ["s0", "s1"]


def test_a_refused_duplicate_leaves_the_journal_where_it_was():
    """A refusal opens no journal entry, so a delta spanning it is the delta
    of the records that landed (`SPEC.md` §10.6)."""
    builder = spanweave.Builder()
    builder.feed(oi("s0"))
    with pytest.raises(DuplicateNodeIdError):
        builder.feed(oi("s0"))
    builder.feed(oi("s1", t0=1001.0))
    delta = builder.delta(since=1)
    assert delta.since == 1
    assert delta.until == 2
    assert [node.id for node in delta.nodes_added] == ["s1"]
    assert delta.nodes_removed == ()


def test_a_refused_record_leaves_a_refusing_builder_still_refusing():
    """`SPEC.md` §10.5: "left as it was" includes `graph()`'s own refusal.

    Classification is what the refused record moves here, not the absorber:
    an adapter claimed it, and `graph()` refuses exactly while **nothing** has
    been claimed (§6.1). So a record that is claimed and *then* refused must
    not turn "nothing here can read this" into a one-node graph.

    Reachable with the shipped adapters alone: the first record is one nobody
    claims, so its node id is derived from its own digest (§3.6 rule 2), and a
    second record stating that id as its `span_id` resolves to the same node.
    Contrived on purpose -- trace payloads are untrusted input
    (`SECURITY.md`) and the crafted value is the cheapest way to reach the
    path.
    """
    unclaimed = {"not": "any dialect"}
    colliding = {
        "span_id": derive(None, None, record_digest(unclaimed)),
        "attributes": {"openinference.span.kind": "LLM"},
    }
    builder = spanweave.Builder()
    builder.feed(unclaimed)
    with pytest.raises(AdapterSelectionError) as before:
        builder.graph()

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(colliding)

    assert builder.version == 1
    with pytest.raises(AdapterSelectionError) as after:
        builder.graph()
    assert after.value.code == before.value.code
    assert str(after.value) == str(before.value)
    # The three the refusal used to leave moved, named because two of them are
    # not observable through any shipped adapter (both `detect()`s answer the
    # same 0.9 on one marker, so sample composition cannot change the answer).
    assert builder._claimed == 0
    assert builder._sample == {}
    assert builder._unread == [unclaimed]


# --------------------------------------------------------------------------
# A record is absorbed whole or not at all (`SPEC.md` §10.5)
# --------------------------------------------------------------------------

TWO_SPAN_MARKER = "twospan.ids"

#: The parent every span of one `twospan` record states, where it states one.
#: Enough to put a `twospan` record in a sibling group other than trace root,
#: which is what a test about a *regrouping* refusal needs (`SPEC.md` §10.5).
TWO_SPAN_PARENT = "twospan.parent"

#: The call id every span of one `twospan` record fulfils, the call id they
#: declare receipt of, and the start time they share. All optional, and all
#: three exist for one reason: a refusal reached *after* a `data` basis was
#: rewritten needs a record of two spans whose first span declares a receipt
#: that outranks one already held (`SPEC.md` §4.2.1, §10.5).
TWO_SPAN_FULFILS = "twospan.fulfils"
TWO_SPAN_RECEIVES = "twospan.receives"
TWO_SPAN_START = "twospan.start"


class TwoSpanAdapter:
    """A test-local dialect whose records become **more than one** span.

    Both shipped adapters yield exactly one span per record, so the span loop
    inside `feed` never runs twice in the corpus. Cardinality is no part of the
    `Adapter` protocol (`spanweave/adapters/base.py`) and `register` is public,
    so a contributor's adapter reaches it -- which is why the atomicity
    `SPEC.md` §10.5 promises has to hold for a record of two spans as well.

    Each span's `source_key` is its own span id, so a record naming one id
    twice yields two spans that are equal in every field, and the second
    resolves to the node id the first already took (`SPEC.md` §3.6 rule 3,
    `spanweave/ids.py:collision`).
    """

    id = "twospan"
    version = "0"

    def detect(self, sample):
        for record in sample:
            if isinstance(record, dict) and TWO_SPAN_MARKER in record:
                return 0.9
        return 0.0

    def parse(self, records):
        for index, record in enumerate(records, start=1):
            raw = RawRecord(source=record, line_number=index)
            fulfils = record.get(TWO_SPAN_FULFILS)
            receives = record.get(TWO_SPAN_RECEIVES)
            start = record.get(TWO_SPAN_START, 1000.0)
            for span_id in record[TWO_SPAN_MARKER]:
                yield NormalizedSpan(
                    source_key=span_id,
                    kind=NodeKind.TOOL,
                    name=span_id,
                    raw=raw,
                    span_id=span_id,
                    parent_id=record.get(TWO_SPAN_PARENT),
                    started_at=start,
                    ended_at=start + 0.5,
                    call_ids=() if fulfils is None else (fulfils,),
                    call_role=None if fulfils is None else CallRole.FULFILLER,
                    received_call_ids=() if receives is None else (receives,),
                )


def ts(*span_ids, parent=None, fulfils=None, receives=None, start=None):
    """One `twospan` record, which becomes one span per id named."""
    record = {TWO_SPAN_MARKER: list(span_ids)}
    if parent is not None:
        record[TWO_SPAN_PARENT] = parent
    if fulfils is not None:
        record[TWO_SPAN_FULFILS] = fulfils
    if receives is not None:
        record[TWO_SPAN_RECEIVES] = receives
    if start is not None:
        record[TWO_SPAN_START] = start
    return record


@pytest.fixture
def two_span():
    """`TwoSpanAdapter`, registered for one test and then gone.

    Registered on the module-level registry because that is the one `Builder`
    asks (`spanweave/api.py`); the saved mapping is restored afterwards so no
    other test sees a third dialect.
    """
    kept = dict(REGISTRY._adapters)
    register(TwoSpanAdapter())
    try:
        yield
    finally:
        REGISTRY._adapters.clear()
        REGISTRY._adapters.update(kept)


def test_two_spans_of_one_record_both_arrive(two_span):
    """The adapter itself, before anything is refused: the record becomes two
    nodes at one version, and the live graph is the batch graph of it."""
    builder = spanweave.Builder()
    assert builder.feed(ts("a", "b")) == 1
    assert [node.id for node in builder.graph().nodes()] == ["a", "b"]
    assert dumps(builder.graph()) == dumps(graph_from_records([ts("a", "b")]))


def test_a_records_second_span_colliding_absorbs_neither(two_span):
    """The first arrival, half of it refused: `version` stays 0, so `graph()`
    refuses as an empty builder's does and `delta(since=0)` is the delta of an
    empty builder -- not a delta that presents a half-arrived node as having
    always been there (`SPEC.md` §10.5)."""
    builder = spanweave.Builder()
    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("c", "c"))

    assert builder.version == 0
    with pytest.raises(AdapterSelectionError) as live:
        builder.graph()
    with pytest.raises(AdapterSelectionError) as empty:
        spanweave.Builder().graph()
    assert live.value.code == empty.value.code
    assert not builder.delta(since=0).changed

    assert builder.feed(ts("d")) == 1
    assert dumps(builder.graph()) == dumps(graph_from_records([ts("d")]))
    assert [node.id for node in builder.delta(since=0).nodes_added] == ["d"]


def test_a_half_refused_record_leaves_the_builder_as_it_was(two_span):
    """The same refusal onto a builder that already holds a version: nothing
    the refused record's first span did survives it, in the graph, in the
    journal, or in the version counter (`SPEC.md` §10.5)."""
    kept = ts("a", "b")
    builder = spanweave.Builder()
    builder.feed(kept)
    before = dumps(unrefused([kept]))

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("c", "c"))

    assert builder.version == 1
    assert dumps(builder.graph()) == before
    assert [node.id for node in builder.delta(since=0).nodes_added] == ["a", "b"]

    landed = [kept, ts("d")]
    assert builder.feed(ts("d")) == 2
    assert dumps(builder.graph()) == dumps(graph_from_records(landed))
    assert [node.id for node in builder.delta(since=1).nodes_added] == ["d"]


def test_a_half_refused_restating_record_leaves_the_builder_as_it_was(two_span):
    """The same, where the refused record's first span *restates* everything:
    a second claim on a span id moves every id derived from it (§10.2), so the
    rollback has to put back a state the arrival rewrote rather than extended.
    """
    kept = [ts("a"), ts("b")]
    builder = spanweave.Builder()
    for record in kept:
        builder.feed(record)
    before = dumps(unrefused(kept))

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("a", "a"))

    assert builder.version == 2
    assert dumps(builder.graph()) == before
    assert [node.id for node in builder.delta(since=0).nodes_added] == ["a", "b"]

    landed = [*kept, ts("d")]
    assert builder.feed(ts("d")) == 3
    assert dumps(builder.graph()) == dumps(graph_from_records(landed))


def test_a_half_refused_record_puts_back_the_chain_edge_it_removed(two_span):
    """The rollback reaches per-edge chain traffic too.

    `ts("b", "b")`'s first span lands strictly between `a` and `c`, so the
    arrival hands the ledger one temporal edge to drop and two to add, one edge
    at a time rather than a whole key at once -- and then its second span is
    refused. The undo is therefore not "take back what the arrival added": the
    edge it *removed* has to come back, which is what makes `Ledger.rollback`'s
    snapshot the one mechanism rather than a per-site inverse (`SPEC.md` §10.5).

    The journal is checked and not only the graph: `graph()` is assembled from
    the absorber's own dicts, which a refusal re-derives from the survivors, so
    a ledger left holding `(a, b)` and `(b, c)` would show up in a `delta` and
    nowhere else.
    """
    kept = [ts("a"), ts("c")]
    builder = spanweave.Builder()
    for record in kept:
        builder.feed(record)
    before = dumps(builder.graph())
    assert chain_of(builder.graph()) == [("a", "c")]

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("b", "b"))

    assert builder.version == 2
    assert dumps(builder.graph()) == before
    assert chain_of(builder.graph()) == [("a", "c")]
    added = builder.delta(since=0).edges_added
    assert [(edge.src, edge.dst) for edge in added] == [("a", "c")]

    landed = [*kept, ts("b")]
    assert builder.feed(ts("b")) == 3
    assert dumps(builder.graph()) == dumps(graph_from_records(landed))
    assert chain_of(builder.graph()) == [("a", "b"), ("b", "c")]


def test_a_half_refused_record_that_regrouped_a_whole_group_puts_its_key_back(
    two_span,
):
    """The one regroup that hands the ledger nothing, undone (`SPEC.md` §10.5).

    Where the records a parent un-orphans are the whole of the group they leave,
    the absorber moves them by **re-keying** the group rather than by moving
    edges, so that arrival changes a chain's owner without a single
    `Ledger.add` or `drop` (§10.6). There is therefore nothing for a per-site
    inverse to take back, and the only thing that can put it right is
    `rollback_to` re-deriving from the survivors (`f04cbc8`) -- which is why this
    is the path worth a test of its own rather than a case of the one above.

    The record that trips it is the parent: its first span `p` un-orphans `a`
    and `b` and re-keys their group, and its second span is refused. The journal
    is checked as well as the graph, because the two are assembled from
    different state -- a `_group_of` left naming a group nobody holds would show
    up in a `delta` and nowhere else.
    """
    kept = [ts("a", parent="p"), ts("b", parent="p")]
    builder = spanweave.Builder()
    for record in kept:
        builder.feed(record)
    before = dumps(builder.graph())
    assert chain_of(builder.graph()) == [("a", "b")]
    assert codes.ORPHAN_PARENT in codes_of(builder.graph())

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("p", "p"))

    assert builder.version == 2
    assert dumps(builder.graph()) == before
    assert chain_of(builder.graph()) == [("a", "b")]
    added = builder.delta(since=0).edges_added
    assert [(edge.src, edge.dst) for edge in added] == [("a", "b")]

    landed = [*kept, ts("p")]
    assert builder.feed(ts("p")) == 3
    assert dumps(builder.graph()) == dumps(graph_from_records(landed))
    assert chain_of(builder.graph()) == [("a", "b")]
    assert codes.ORPHAN_PARENT not in codes_of(builder.graph())


def test_a_half_refused_record_puts_back_the_data_basis_it_rewrote(two_span):
    """The rollback reaches per-edge `data` traffic too (`SPEC.md` §10.5).

    The sibling-chain test above, on the other key an arrival amends edge by
    edge. `ts("r1", "r1")`'s first span declares receipt of `c` at a start that
    **outranks** the receipt already held, so the arrival hands the ledger the
    earlier receipt's edge to drop and two to add -- the same edge back with
    "not the earliest" in its basis, and its own -- and then its second span is
    refused.

    So what has to come back is an edge the arrival removed *and* a basis it
    rewrote, which is the case a per-site inverse would get subtly wrong: taking
    back what was added leaves `r2` with no `data` edge at all.
    """
    kept = [ts("f", fulfils="c"), ts("r2", receives="c", start=1002.0)]
    builder = spanweave.Builder()
    for record in kept:
        builder.feed(record)
    before = dumps(builder.graph())
    assert data_of(builder.graph()) == [("f", "r2", DATA_BASIS)]

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("r1", "r1", receives="c", start=1001.0))

    assert builder.version == 2
    assert dumps(builder.graph()) == before
    assert data_of(builder.graph()) == [("f", "r2", DATA_BASIS)]
    rewritten = builder.delta(since=0).basis_rewritten
    assert rewritten == (), "a refused arrival rewrote a basis after all"
    added = builder.delta(since=0).edges_added
    assert [(e.src, e.dst, e.basis) for e in added if e.kind is EdgeKind.DATA] == [
        ("f", "r2", DATA_BASIS)
    ]

    landed = [*kept, ts("r1", receives="c", start=1001.0)]
    assert builder.feed(ts("r1", receives="c", start=1001.0)) == 3
    assert dumps(builder.graph()) == dumps(graph_from_records(landed))
    assert data_of(builder.graph()) == [
        ("f", "r1", DATA_BASIS),
        ("f", "r2", DATA_LATER_BASIS),
    ]


def test_a_refused_record_leaves_no_whole_input_memo_behind(two_span):
    """A refusal on an **empty** builder, and then two records that arrive.

    The whole-input statements are derived behind a memo of what they were last
    derived from, so an ordinary arrival pays nothing for two diagnostics it
    cannot have changed (`spanweave/incremental.py:_restate_whole_input`). A
    refusal re-derives forward from the survivors, which *writes* that memo,
    while the tally's snapshot takes back only the diagnostics the derivation
    made -- so a memo left standing claims a statement the journal does not
    hold, and the next legitimate derivation short-circuits on it.

    `graph()` would not show it, because materializing re-derives from the
    absorber's own dicts; `delta()` is where it surfaces, because the journal
    does not. Hence the assertion: the diagnostics the delta from version 0
    opened are exactly the diagnostics the graph holds, which is `SPEC.md`
    §10.6's `delta(0, v) = graph(v) - graph(0)` and §10.5's "every later
    `graph()` and `delta()` answer exactly as they would have had the record
    never arrived".
    """
    builder = spanweave.Builder()
    with pytest.raises(DuplicateNodeIdError):
        builder.feed(ts("c", "c"))

    builder.feed({"not": "any dialect"})
    builder.feed(ts("q"))

    assert builder.version == 2
    graph = builder.graph()
    assert codes_of(graph) == [
        codes.MISSING_TIMESTAMP,
        codes.MISSING_TRACE_ID,
        codes.UNCLAIMED_RECORD,
    ]
    opened = builder.delta(since=0).diagnostics_opened
    assert [item.code for item in opened] == codes_of(graph)
    assert opened == graph.diagnostics
    assert dumps(builder.graph()) == dumps(
        graph_from_records([{"not": "any dialect"}, ts("q")])
    )


#: What `begin` writes on every arrival and `rollback_to` therefore cannot be
#: asked to restore: the value between arrivals is nobody's, which is what
#: `rollback_to`'s own comment says where it resets `_restated`. `_before` is
#: left describing an arrival that did not happen, unobservably, because
#: `begin` rewrites it before its only reader. Everything *else* a builder
#: holds is compared, `_whole_input_from` included -- the memo above is
#: derived state, not arrival state, so it is not on this list.
ARRIVAL_SCOPED = frozenset({"_absorber._before", "_absorber._whole_input_before"})

#: The five shapes a refusal can take, as `(label, kept, refused)`: on an empty
#: builder, after an arrival, where the refused record *restates* every id,
#: where its first span joins a chain mid-way, and where that span rewrites a
#: `data` basis. The last three are the tests above; this re-runs them against
#: every attribute rather than against the graph and the journal.
REFUSAL_SHAPES = [
    ("on an empty builder", [], ts("c", "c")),
    ("after an arrival", [ts("a", "b")], ts("c", "c")),
    ("restating every id", [ts("a"), ts("b")], ts("a", "a")),
    ("joining a chain mid-way", [ts("a"), ts("c")], ts("b", "b")),
    (
        "rewriting a data basis",
        [ts("f", fulfils="c"), ts("r2", receives="c", start=1002.0)],
        ts("r1", "r1", receives="c", start=1001.0),
    ),
]


def builder_state(builder):
    """Every value a builder holds, deep-copied, keyed by dotted path.

    The graph and the journal are what the tests above compare, and they are
    assembled from a *subset* of this: `graph()` re-derives from the absorber's
    dicts and a `delta` reads the tally, so a value that belongs to neither --
    a memo, a cache, a count -- can be left wrong by a refusal and show up in
    neither. This is the probe that closes that gap, and it names nothing: it
    walks the builder and the spanweave objects it holds, so an attribute added
    later is compared without anyone remembering to add it.
    """
    found, seen = {}, set()

    def walk(obj, prefix):
        for name, value in sorted(vars(obj).items()):
            path = f"{prefix}.{name}" if prefix else name
            held = type(value).__module__.startswith("spanweave")
            if held and hasattr(value, "__dict__") and id(value) not in seen:
                seen.add(id(value))
                walk(value, path)
            else:
                found[path] = copy.deepcopy(value)

    walk(builder, "")
    return {path: value for path, value in found.items() if path not in ARRIVAL_SCOPED}


@pytest.mark.parametrize(
    ("label", "kept", "refused"),
    REFUSAL_SHAPES,
    ids=[shape[0] for shape in REFUSAL_SHAPES],
)
def test_a_refused_record_moves_no_value_the_builder_holds(
    two_span, label, kept, refused
):
    """The builder is "left as it was" (`SPEC.md` §10.5), attribute by
    attribute, in all five shapes a refusal takes."""
    builder = spanweave.Builder()
    for record in kept:
        builder.feed(record)
    if kept:
        builder.graph()
    before = builder_state(builder)
    assert "_absorber._whole_input_from" in before

    with pytest.raises(DuplicateNodeIdError):
        builder.feed(refused)

    after = builder_state(builder)
    assert set(after) == set(before)
    moved = sorted(path for path in before if before[path] != after[path])
    assert moved == [], f"a refusal {label} moved {moved}"


def chain_of(graph):
    """One sibling group's chain, as `(src, dst)` pairs in canonical edge order."""
    return [(edge.src, edge.dst) for edge in graph.edges(kind=EdgeKind.TEMPORAL)]


def data_of(graph):
    """Every `data` edge as `(src, dst, basis)`, in canonical edge order."""
    return [
        (edge.src, edge.dst, edge.basis) for edge in graph.edges(kind=EdgeKind.DATA)
    ]


# --------------------------------------------------------------------------
# What the live graph does not carry
# --------------------------------------------------------------------------


def test_the_live_graph_reports_no_source_digest():
    """The builder is fed records, so the bytes of an input are not its to
    describe (`SPEC.md` §10)."""
    graph = replay([oi("s1")]).graph()
    assert graph.meta is not None
    assert graph.meta.source_digest is None


def test_materializing_twice_returns_the_same_graph():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    first = builder.graph()
    assert builder.graph() is first
    builder.feed(oi("s2", t0=1001.0))
    assert builder.graph() is not first


def test_a_record_is_what_the_reader_yields_and_not_a_line_of_text():
    """Feeding the *line* rather than the record is not silently parsed.

    A JSON string is a record no adapter claims, so it becomes an `unknown`
    node carrying it verbatim -- which is what a batch build of the same thing
    does. Nothing here re-reads it, and the mistake is visible in the graph
    rather than absorbed by it.
    """
    line = json.dumps(oi("s2"))
    graph = replay([oi("s1"), line]).graph()
    assert codes.UNCLAIMED_RECORD in codes_of(graph)
    assert len(graph.nodes()) == 2
    assert line in [node.raw.source for node in graph.nodes()]


# --------------------------------------------------------------------------
# The journal and deltas (`SPEC.md` §10.6-§10.9)
# --------------------------------------------------------------------------


def graphs_of(records, **kw):
    """Every prefix graph, indexed by version. Index 0 is `None`.

    `graph()` at version 0 refuses, as `build` of an empty input does
    (`SPEC.md` §10.5), so the version-0 slot holds no graph and the oracle is
    handed `None` for it.
    """
    builder = spanweave.Builder(**kw)
    found = [None]
    for record in records:
        builder.feed(record)
        found.append(builder.graph())
    return builder, found


def oracle_delta(built, since, until, restated):
    return checkpoint_delta(
        built[since], built[until], since=since, until=until, restated=restated
    )


def test_the_delta_surface_is_public():
    for name in ("Delta", "DeltaUnavailableError", "delta_dumps", "delta_to_document"):
        assert name in spanweave.__all__


def test_the_delta_error_carries_the_registered_code():
    from spanweave.errors import ERROR_CODES

    assert spanweave.DeltaUnavailableError.code in ERROR_CODES


def test_a_delta_since_the_current_version_is_empty():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    delta = builder.delta(since=builder.version)
    assert delta.since == delta.until == 1
    assert delta.nodes_added == delta.nodes_removed == ()
    assert delta.edges_added == delta.edges_removed == ()
    assert delta.diagnostics_opened == delta.diagnostics_resolved == ()
    assert delta.order_changed is False
    assert delta.restated is False
    assert delta.changed is False


def test_a_delta_is_the_difference_between_its_two_versions():
    records = [
        oi("s0", kind="AGENT", name="agent", t0=1000.0),
        oi("s1", parent="s0", t0=1001.0),
        oi("s2", parent="s0", t0=1002.0),
    ]
    builder, built = graphs_of(records)
    for since in range(0, 4):
        actual = builder.delta(since=since)
        assert actual == oracle_delta(built, since, 3, actual.restated)


def test_a_delta_from_version_zero_adds_everything():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    delta = builder.delta(since=0)
    assert delta.trace_id_before == ""
    assert delta.adapters_before == ()
    assert [node.id for node in delta.nodes_added] == ["s1"]
    assert delta.nodes_removed == ()


def test_an_opened_and_resolved_diagnostic_cancels_over_a_wide_window():
    """The fold must cancel (`OPEN_QUESTIONS.md` §18): a diagnostic that opened
    and closed inside the window is in neither endpoint graph, so it is in
    neither collection."""
    records = [
        oi("s0", kind="AGENT", name="agent", t0=999.0),
        requester("s1", "call_a"),
        fulfiller("s2", "call_a", t0=1001.0),
    ]
    builder, built = graphs_of(records)
    assert codes.UNPAIRED_CALL in codes_of(built[2])
    assert codes.UNPAIRED_CALL not in codes_of(built[3])

    narrow = builder.delta(since=1)
    opened = [d.code for d in narrow.diagnostics_opened]
    resolved = [d.code for d in narrow.diagnostics_resolved]
    assert codes.UNPAIRED_CALL not in opened
    assert codes.UNPAIRED_CALL not in resolved
    assert narrow == oracle_delta(built, 1, 3, narrow.restated)


def test_the_per_record_delta_keeps_the_history_the_wide_one_cancels():
    records = [
        oi("s0", kind="AGENT", name="agent", t0=999.0),
        requester("s1", "call_a"),
        fulfiller("s2", "call_a", t0=1001.0),
    ]
    builder = spanweave.Builder()
    seen = []
    for record in records:
        version = builder.feed(record)
        delta = builder.delta(since=version - 1)
        seen.append(
            (
                [d.code for d in delta.diagnostics_opened],
                [d.code for d in delta.diagnostics_resolved],
            )
        )
    assert codes.UNPAIRED_CALL in seen[1][0]
    assert codes.UNPAIRED_CALL in seen[2][1]


def test_a_basis_rewrite_is_one_edge_out_one_in_and_named_as_a_pair():
    records = [
        fulfiller("s1", "call_a", t0=1000.0),
        receiver("s3", "call_a", t0=1002.0),
        receiver("s2", "call_a", t0=1001.0),
    ]
    builder = spanweave.Builder()
    for record in records[:2]:
        builder.feed(record)
    builder.feed(records[2])
    delta = builder.delta(since=2)
    rewritten = delta.basis_rewritten
    assert [(r.src, r.dst) for r in rewritten] == [("s1", "s3")]
    assert "earliest" not in rewritten[0].before
    assert "not the earliest" in rewritten[0].after
    # The view is over the edge sets, not a fact of its own.
    removed = [(e.src, e.dst, e.basis) for e in delta.edges_removed]
    added = [(e.src, e.dst, e.basis) for e in delta.edges_added]
    assert ("s1", "s3", rewritten[0].before) in removed
    assert ("s1", "s3", rewritten[0].after) in added


def test_order_changed_is_about_the_nodes_both_versions_hold():
    """A new sibling slotted between two others moves neither of them, so the
    flag is `False`; a late parent that drags its child past a root moves one,
    so it is `True` (`SPEC.md` §10.6)."""
    inserted = spanweave.Builder()
    inserted.feed(oi("s0", kind="AGENT", name="agent", t0=1000.0))
    inserted.feed(oi("s3", parent="s0", t0=1003.0))
    inserted.feed(oi("s2", parent="s0", t0=1002.0))
    assert inserted.graph().topo_order == ("s0", "s2", "s3")
    assert inserted.delta(since=2).order_changed is False

    late = spanweave.Builder()
    late.feed(oi("s2", parent="s9", t0=1002.0))
    late.feed(oi("s3", t0=1005.0))
    assert late.graph().topo_order == ("s2", "s3")
    late.feed(oi("s9", kind="AGENT", name="agent", t0=1009.0))
    assert late.graph().topo_order == ("s3", "s9", "s2")
    assert late.delta(since=2).order_changed is True


# -- folding ---------------------------------------------------------------


def test_folding_the_per_record_delta_reproduces_the_next_graph():
    records = [
        oi("s0", kind="AGENT", name="agent", t0=1000.0),
        oi("s2", parent="s0", t0=1002.0),
        requester("s1", "call_a", parent="s0", t0=1001.0),
        fulfiller("s4", "call_a", parent="s0", t0=1004.0),
    ]
    builder = spanweave.Builder()
    previous = None
    for record in records:
        version = builder.feed(record)
        current = builder.graph()
        if previous is not None:
            folded = builder.delta(since=version - 1).fold(previous)
            assert dumps(folded) == dumps(current)
            assert folded == current
        previous = current


def test_folding_a_wide_delta_reproduces_the_current_graph():
    records = [
        oi("s0", kind="AGENT", name="agent", t0=1000.0),
        requester("s1", "call_a", parent="s0", t0=1001.0),
        fulfiller("s2", "call_a", parent="s0", t0=1002.0),
        receiver("s3", "call_a", t0=1003.0, parent="s0"),
    ]
    builder, built = graphs_of(records)
    for since in range(1, 5):
        folded = builder.delta(since=since).fold(built[since])
        assert dumps(folded) == dumps(built[4])


def test_folding_preserves_the_annotations_of_the_graph_it_is_handed():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    annotated = builder.graph().annotate("s1", "mine", "label", "yes")
    builder.feed(oi("s2", t0=1001.0))
    folded = builder.delta(since=1).fold(annotated)
    assert folded.annotations_for("s1", "mine") == {"label": "yes"}
    assert set(folded.topo_order) == {"s1", "s2"}


def test_folding_onto_the_wrong_graph_refuses_rather_than_lying():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    first = builder.graph()
    builder.feed(oi("s2", t0=1001.0))
    delta = builder.delta(since=1)
    assert delta.fold(first) == builder.graph()
    # The same delta applied twice: the node it adds is already there.
    with pytest.raises(ValueError, match="already"):
        delta.fold(delta.fold(first))


# -- restatement -----------------------------------------------------------


def test_an_ordinary_arrival_is_not_restated():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    builder.feed(oi("s2", t0=1001.0))
    assert builder.delta(since=1).restated is False


def test_a_majority_trace_id_change_is_a_restated_entry():
    builder = spanweave.Builder()
    builder.feed(oi("s1", trace_id="t1"))
    builder.feed(oi("s2", trace_id="t2", t0=1001.0))
    builder.feed(oi("s3", trace_id="t2", t0=1002.0))
    assert builder.delta(since=2).restated is True
    assert builder.delta(since=2).trace_id_before == "t1"
    assert builder.delta(since=2).trace_id_after == "t2"


def test_a_span_id_that_stops_being_unique_moves_ids_in_the_delta():
    builder = spanweave.Builder()
    builder.feed(oi("s1", name="alpha"))
    builder.feed(oi("s1", name="beta", t0=1001.0))
    delta = builder.delta(since=1)
    assert delta.restated is True
    assert [node.id for node in delta.nodes_removed] == ["s1"]
    assert [node.id for node in delta.nodes_added] != ["s1"]
    assert len(delta.nodes_added) == 2


def test_meta_can_move_without_an_id_moving():
    """A second dialect joins the stream: `meta.adapters` grows and no id does,
    which is why the adapter tuple is carried in its own right rather than
    folded into the meaning of `restated` (`SPEC.md` §10.7)."""
    genai = {
        "trace_id": "t1",
        "span_id": "g1",
        "parent_id": None,
        "name": "chat demo-model",
        "start_time": 1002.0,
        "end_time": 1002.5,
        "status": "OK",
        "attributes": {"gen_ai.operation.name": "chat", "gen_ai.request.model": "m"},
    }
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    builder.feed(genai)
    delta = builder.delta(since=1)
    assert delta.restated is False
    assert [a.id for a in delta.adapters_before] == ["openinference"]
    assert [a.id for a in delta.adapters_after] == ["openinference", "otel_genai"]


def test_the_adapter_tuples_are_the_two_graphs_own():
    """`declared_confidence` is declared over a sample that grows
    (`SPEC.md` §6.1), so `meta` can move between versions with nothing else
    moving. Neither *registered* adapter's declaration actually moves with the
    sample today -- both answer 0.9 to any sample holding a record they claim --
    so what is asserted is the mechanism that would carry it: the delta's
    adapter tuples are the endpoint graphs' `meta.adapters`, whatever they say.
    """
    records = [oi("s1"), oi("s2", t0=1001.0), oi("s3", t0=1002.0)]
    builder, built = graphs_of(records)
    for since in (1, 2):
        delta = builder.delta(since=since)
        assert delta.adapters_before == built[since].meta.adapters
        assert delta.adapters_after == built[3].meta.adapters


# -- retention -------------------------------------------------------------


def test_the_default_retention_keeps_everything():
    builder = spanweave.Builder()
    for index in range(5):
        builder.feed(oi(f"s{index}", t0=1000.0 + index))
    assert builder.delta(since=0).until == 5


def test_retaining_n_versions_drops_what_is_older():
    builder = spanweave.Builder()
    builder.retain(versions=2)
    for index in range(5):
        builder.feed(oi(f"s{index}", t0=1000.0 + index))
    assert builder.delta(since=3).since == 3
    with pytest.raises(spanweave.DeltaUnavailableError) as dropped:
        builder.delta(since=2)
    assert dropped.value.code == "delta_unavailable"


def test_retaining_nothing_leaves_only_the_current_version():
    builder = spanweave.Builder()
    builder.retain(versions=0)
    builder.feed(oi("s1"))
    builder.feed(oi("s2", t0=1001.0))
    assert builder.delta(since=2).changed is False
    with pytest.raises(spanweave.DeltaUnavailableError):
        builder.delta(since=1)


def test_retain_applies_at_once_rather_than_at_the_next_feed():
    builder = spanweave.Builder()
    for index in range(4):
        builder.feed(oi(f"s{index}", t0=1000.0 + index))
    builder.retain(versions=1)
    with pytest.raises(spanweave.DeltaUnavailableError):
        builder.delta(since=2)
    assert builder.delta(since=3).until == 4


def test_a_since_that_is_not_a_version_is_a_caller_error():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    for wrong in (-1, 2, 99):
        with pytest.raises(ValueError):
            builder.delta(since=wrong)


def test_an_unknown_retention_policy_is_refused():
    builder = spanweave.Builder()
    with pytest.raises(ValueError):
        builder.retain(versions=-1)
    with pytest.raises(ValueError):
        builder.retain(versions="some")


# -- the document form -----------------------------------------------------


def test_the_delta_document_is_its_own_top_level_shape():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    builder.feed(oi("s2", t0=1001.0))
    document = spanweave.delta_to_document(builder.delta(since=1))
    assert document["kind"] == "delta"
    assert document["schema_version"] == spanweave.SCHEMA_VERSION
    assert sorted(document) == list(DELTA_ROOT_KEYS)
    assert document["nodes_added"][0]["id"] == "s2"
    assert document["since"] == 1
    assert document["until"] == 2


def test_the_delta_document_writes_nodes_the_way_a_graph_does():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    graph_node = spanweave.to_document(builder.graph())["nodes"][0]
    builder.feed(oi("s2", t0=1001.0))
    delta_node = spanweave.delta_to_document(builder.delta(since=1))["nodes_added"][0]
    assert sorted(graph_node) == sorted(delta_node)


def test_the_delta_bytes_are_canonical():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    builder.feed(oi("s2", t0=1001.0))
    written = spanweave.delta_dumps(builder.delta(since=1))
    assert written.endswith(b"\n")
    assert written == spanweave.delta_dumps(builder.delta(since=1))
    assert json.loads(written)["kind"] == "delta"


def test_the_graph_document_gains_no_key_for_the_delta_feature():
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    assert sorted(spanweave.to_document(builder.graph())) == list(ROOT_KEYS)


# -- what each path sorts --------------------------------------------------


@pytest.fixture
def sorts(monkeypatch):
    """Every canonical-order sort a call performs, by the size it was given.

    `spanweave.build` is patched through `sys.modules` rather than through the
    package, because the package attribute of that name is the `build()`
    *function* (`spanweave/__init__.py`) while `spanweave.incremental` and
    `spanweave.delta` both hold the module. Patching the module reaches both.
    """
    module = sys.modules["spanweave.build"]
    original = module.in_order
    counted = []

    def counting(nodes, *args, **kwargs):
        counted.append(len(nodes))
        return original(nodes, *args, **kwargs)

    monkeypatch.setattr(module, "in_order", counting)
    return counted


def test_feeding_sorts_nothing_and_the_other_paths_sort_a_stated_number_of_times(
    sorts,
):
    """The premise under §10.6's cost statement, and under `tests/live_cost.py`.

    Canonical order is computed when a graph is materialized and when a delta is
    folded, and **never** while feeding. That is why no incrementally maintained
    order could make `feed` faster -- it has nothing there to replace -- and why
    the measurement that dropped `WORKPLAN.md` L5 compared the sort against
    `delta()` rather than against feeding.

    The counts are the shape of the cost, not an implementation detail: one sort
    per materialization, **two** per delta because a delta recovers order at
    both of its endpoints (`SPEC.md` §10.6), and one per fold because a delta
    carries no order for the fold to trust.
    """
    builder = spanweave.Builder()
    builder.feed(oi("s1"))
    builder.feed(oi("s2", t0=1001.0))
    assert sorts == [], "feeding sorted; `SPEC.md` §10.6 says only the other paths do"

    before = builder.graph()
    assert sorts == [2], "materializing sorts exactly once, over every node"
    builder.graph()
    assert sorts == [2], "a materialized graph is kept until the next feed"

    builder.feed(oi("s3", "s1", t0=1002.0))
    assert sorts == [2], "feeding sorted after all"

    sorts.clear()
    change = builder.delta(since=2)
    assert sorts == [3, 2], (
        "a delta sorts both of its endpoints: the current one, then `since`"
    )

    sorts.clear()
    folded = change.fold(before)
    assert sorts == [3], "folding sorts once, over the nodes it has just applied"
    sorts.clear()
    assert dumps(folded) == dumps(builder.graph())


# -- what each arrival builds ----------------------------------------------


@pytest.fixture
def edges_built(monkeypatch):
    """Every `Edge` allocated while the fixture is in place.

    The companion of `sorts`, and the same argument: what an arrival costs is
    not readable from a wall clock on a shared machine, but it *is* readable
    from how many edge objects the arrival had to make. An edge the arrival
    reused is an edge it did not allocate, so this counts exactly the work a
    maintained chain removes (`SPEC.md` §10.6).

    The class is patched rather than `spanweave.build`'s callers, because
    `build` names `Edge` directly and so does every other module that makes
    one; there is one class object and this is it.

    The edges themselves are collected rather than counted, so that a test
    about the sibling *chain* can say `kind` and not be answered by the
    `parent` edges an arrival makes at the same time. `len()` is still the
    count.
    """
    model = sys.modules["spanweave.model"]
    original = model.Edge.__init__
    counted = []

    def counting(self, *args, **kwargs):
        original(self, *args, **kwargs)
        counted.append(self)

    monkeypatch.setattr(model.Edge, "__init__", counting)
    return counted


#: Two widths an order of magnitude apart in the product of the group size, so
#: that "linear in `n`" and "quadratic in `n`" are not the same number twice.
WIDE_SIBLINGS = (200, 800)


def wide_group(width):
    """One root and `width` children of it: one sibling group holding them all.

    `tests/live_cost.py`'s `wide` workload, at a size a test can afford.
    """
    return [oi("s0", kind="AGENT", name="agent", t0=1000.0)] + [
        oi(f"t{index:04d}", parent="s0", t0=1001.0 + index) for index in range(width)
    ]


def test_feeding_a_wide_sibling_group_builds_edges_linearly_in_the_records(
    edges_built,
):
    """The cost of a sibling group's chain is the arrival, not the group.

    A chain rebuilt per arrival allocates the group's whole chain again --
    `m - 1` edges for a group of `m`, so `n**2 / 2` over the feed, and
    `SPEC.md` §10.6 said that is what a key restated in full costs. A chain
    *maintained* replaces only the edges adjacent to where the arrival lands,
    so the feed allocates a bounded number per record and the total is linear.

    Asserted twice over, because either alone is weaker than it looks: a bound
    per width catches a quadratic at one size, and the ratio between the two
    widths catches a constant factor that happens to be generous at the small
    one.
    """
    counts = {}
    for width in WIDE_SIBLINGS:
        edges_built.clear()
        builder = spanweave.Builder()
        for record in wide_group(width):
            builder.feed(record)
        counts[width] = len(edges_built)

    for width, built in counts.items():
        assert built <= 4 * (width + 1), (
            f"feeding {width + 1} records built {built} edges; a maintained "
            "chain builds a bounded number per arrival"
        )
    small, large = WIDE_SIBLINGS
    growth = counts[large] / counts[small]
    assert growth <= 1.5 * large / small, (
        f"{large / small:.0f}x the records built {growth:.1f}x the edges; "
        "linear in the records is the promise"
    )


def test_no_arrival_rebuilds_the_sibling_chain_it_lands_inside(edges_built):
    """One edge out and two in, whatever the group already holds (§4.3).

    The per-arrival half of the test above, and on the harder shape: the evens
    append, then every odd lands *between* two members already chained, which
    is the only insertion with an edge to remove. Three edges covers the two
    the chain gains plus the record's own `parent`.
    """
    width = 120
    children = [index for index in range(0, width, 2)] + [
        index for index in range(1, width, 2)
    ]
    builder = spanweave.Builder()
    builder.feed(oi("s0", kind="AGENT", name="agent", t0=1000.0))
    for arrival, index in enumerate(children, start=1):
        before = len(edges_built)
        builder.feed(oi(f"t{index:04d}", parent="s0", t0=1001.0 + index))
        built = len(edges_built) - before
        assert built <= 3, (
            f"arrival {arrival} into a group of {arrival - 1} built {built} edges"
        )


def test_a_late_parent_moves_every_waiting_child_without_building_a_chain_edge(
    edges_built,
):
    """One arrival, one move, however many records it un-orphaned (§10.6).

    Fed children-first, every child sits at trace root waiting for a parent that
    has not arrived, so the root group holds the whole input -- and then the
    parent arrives and all of them change group inside a **single** `feed`. Moved
    one at a time, that arrival pays a search and up to three chain edges per
    child; moved together, the chain they had is the chain they keep, so the
    group is re-keyed and no `temporal` edge is built at all.

    `parent` edges are excluded by `kind` rather than absorbed into a bound,
    because every child genuinely gains one: a bound loose enough to admit
    `width` parent edges would be loose enough to admit a chain moved per child
    as well, and then the test would pass on either implementation.

    Both widths, because the arrival is still asserted to be *correct* at each --
    the chain afterwards is the whole group in §4.3's order -- and the two
    together say the count does not follow the width.
    """
    moved = {}
    for width in WIDE_SIBLINGS:
        builder = spanweave.Builder()
        for index in range(width):
            builder.feed(oi(f"t{index:04d}", parent="s0", t0=1001.0 + index))
        edges_built.clear()
        builder.feed(oi("s0", kind="AGENT", name="agent", t0=1000.0))
        moved[width] = [edge for edge in edges_built if edge.kind is EdgeKind.TEMPORAL]
        assert chain_of(builder.graph()) == [
            (f"t{index:04d}", f"t{index + 1:04d}") for index in range(width - 1)
        ]

    for width, built in moved.items():
        assert built == [], (
            f"the parent of {width} waiting children built {len(built)} chain "
            "edges; the chain they had is the chain they keep"
        )


#: Two turn counts, because a cube and a square are the same number once.
ECHO_TURNS = (20, 40)


def echo_loop(turns):
    """`tests/live_cost.py`'s `echo` workload, at a size a test can afford.

    One agent, and per turn an LLM span that asks for a tool call and resends
    every tool result it has already been given, then the tool span that answers
    it. `turns` turns carry `turns * (turns - 1) / 2` declared receipts, which is
    what §4.2.1 says a protocol resending its history states -- and so is the
    number of `data` edges the graph holds.
    """
    records = [oi("s0", kind="AGENT", name="agent", t0=1000.0, t1=1000.0 + turns)]
    for turn in range(turns):
        resent = {"llm.input_messages.0.message.role": "user"}
        for earlier in range(turn):
            resent[f"llm.input_messages.{earlier + 1}.message.role"] = "tool"
            resent[f"llm.input_messages.{earlier + 1}.message.tool_call_id"] = (
                f"c{earlier:04d}"
            )
        start = 1000.0 + turn
        records.append(
            oi(
                f"l{turn:04d}",
                parent="s0",
                kind="LLM",
                name="llm",
                t0=start + 0.1,
                t1=start + 0.4,
                **{
                    "llm.output_messages.0.message.tool_calls.0.tool_call.id": (
                        f"c{turn:04d}"
                    ),
                    **resent,
                },
            )
        )
        records.append(
            oi(
                f"t{turn:04d}",
                parent="s0",
                kind="TOOL",
                name="tool",
                t0=start + 0.5,
                t1=start + 0.9,
                **{"tool_call.id": f"c{turn:04d}"},
            )
        )
    return records


def test_feeding_an_echo_loop_builds_one_data_edge_per_declared_receipt(edges_built):
    """A call id's `data` edges are the arrival's, not the call id's (§10.6).

    The receipts of one call id grow with the conversation, and which of them
    ranks first decides a `basis` (§4.2.1) -- so the whole set was restated per
    receipt, and a loop resending its history paid for every declaration it had
    already made on every turn. Three nested sizes, which is **cubic** in turns:
    the receipts are quadratic and each was re-emitted once per later turn.

    A receipt *amended* in is one edge per span that answered the call, and the
    graph holds exactly one `data` edge per declared receipt, so the feed builds
    as many `data` edges as the answer has and the work is linear in the receipts
    rather than in their square. The edge set is still quadratic in the turns --
    §4.2.1 says the input declares that many relations and none is suppressed --
    so what this pins is that nothing is built *twice*, which is the whole of the
    claim and all §10.6 promises.

    Asserted twice, as the wide-group test is: a bound per size catches a cube at
    one size, and the ratio between the two sizes catches a bound that is merely
    generous at the small one.
    """
    built = {}
    held = {}
    for turns in ECHO_TURNS:
        edges_built.clear()
        builder = spanweave.Builder()
        for record in echo_loop(turns):
            builder.feed(record)
        built[turns] = len([e for e in edges_built if e.kind is EdgeKind.DATA])
        held[turns] = len(builder.graph().edges(kind=EdgeKind.DATA))
        assert held[turns] == turns * (turns - 1) // 2, (
            "the workload does not carry the receipts §4.2.1 describes"
        )

    for turns, made in built.items():
        assert made <= 1.5 * held[turns], (
            f"{turns} turns hold {held[turns]} `data` edges and building them "
            f"took {made}; a receipt amended in is built once"
        )
    small, large = ECHO_TURNS
    growth = built[large] / built[small]
    declared = held[large] / held[small]
    assert growth <= 1.5 * declared, (
        f"{large / small:.0f}x the turns declared {declared:.1f}x the receipts "
        f"and built {growth:.1f}x the edges; linear in the receipts is the promise"
    )


def test_a_receipt_that_outranks_the_first_rewrites_only_that_one(edges_built):
    """The rewrite half, and the per-arrival bound on it (`SPEC.md` §4.2.1).

    Every receiver arrives *earlier* than the one before it, so every arrival
    outranks the receipt that ranked first and every arrival rewrites a basis --
    the worst order there is for this key, and the one a restated key charges the
    whole set for. What a rewrite costs is one removal and one addition per edge
    of the **one** receipt that stopped being the earliest: every other receipt
    was already "not the earliest" and no arrival can change that.

    Three edges covers its own, the one rewritten, and the room a `temporal` edge
    would need if this bound were ever read as a kind-blind one; the `data`
    filter means it is not.
    """
    builder = spanweave.Builder()
    builder.feed(fulfiller("f", "call_a", t0=1000.0))
    for arrival in range(40):
        before = len(edges_built)
        builder.feed(receiver(f"r{arrival:04d}", "call_a", t0=2000.0 - arrival))
        made = [e for e in edges_built[before:] if e.kind is EdgeKind.DATA]
        assert len(made) <= 3, (
            f"receipt {arrival + 1} of {arrival + 1} built {len(made)} `data` "
            "edges; a rewrite moves the first receipt's edges and no other's"
        )
    bases = [basis for _, _, basis in data_of(builder.graph())]
    assert bases.count(DATA_BASIS) == 1, "exactly one receipt is the earliest"


def test_a_scrambled_set_of_receipts_is_the_batch_bases_at_every_prefix():
    """Correctness under every arrival order, ties included (§4.2.1).

    The ranking is a fact about a *set*, so the three bases must not depend on
    which receipt arrived first -- and two receipts sharing a start time are the
    case the maintained ranking has to get right in both directions: a receipt
    that outranks the first demotes it, and one that merely *ties* with the first
    turns "earliest" into "earliest tied" without displacing it.

    `replay` compares against the batch build at every prefix, so each
    permutation is four assertions and not one.
    """
    records = [
        fulfiller("f", "call_a", t0=1000.0),
        receiver("r1", "call_a", t0=1001.0),
        receiver("r2", "call_a", t0=1001.0),
        receiver("r3", "call_a", t0=1002.0),
    ]
    for order in itertools.permutations(range(4)):
        builder = replay([records[index] for index in order])
        assert data_of(builder.graph()) == [
            ("f", "r1", DATA_TIED_BASIS),
            ("f", "r2", DATA_LATER_BASIS),
            ("f", "r3", DATA_LATER_BASIS),
        ], f"arrival order {order} did not agree with the batch bases"


# --------------------------------------------------------------------------
# The receiver's path: bytes in flight, records to a builder (§19, §7)
# --------------------------------------------------------------------------


def otlp(span_id, parent="", t0=1700000000000000000):
    """One OTLP span, in the dialect `otel_genai` reads."""
    return {
        "traceId": "t1",
        "spanId": span_id,
        "parentSpanId": parent,
        "name": "chat",
        "startTimeUnixNano": str(t0),
        "endTimeUnixNano": str(t0 + 500000000),
        "status": {"code": 1},
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}
        ],
    }


def export(*spans):
    """The body an OTLP/HTTP exporter POSTs, as bytes."""
    document = {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}
    return json.dumps(document).encode("utf-8")


def test_an_export_in_flight_feeds_a_builder_and_is_the_graph_of_its_bytes():
    """The whole of what `OPEN_QUESTIONS.md` §19 asks spanweave for.

    A receiver holds bytes and a `Builder`: `read_records` turns the first into
    records and `feed` absorbs them one at a time. The claim is that nothing is
    lost between the two doors -- the live graph of an export's records is the
    graph `build` produces from the very same bytes, **except** for the facts
    §10.4 says a builder cannot carry, which is the digest of an input it never
    saw.
    """
    data = export(otlp("s0"), otlp("s1", parent="s0"), otlp("s2", parent="s0"))
    records = list(spanweave.read_records(data))
    assert len(records) == 3

    live = replay(records).graph()
    batch = spanweave.build(data)
    assert [node.id for node in live.nodes()] == [node.id for node in batch.nodes()]
    assert live.nodes() == batch.nodes()
    assert live.edges() == batch.edges()
    assert codes_of(live) == codes_of(batch)
    assert live.meta is not None and batch.meta is not None
    assert live.meta.source_digest is None
    assert batch.meta.source_digest is not None


def test_a_file_of_one_export_per_line_arrives_as_one_record_per_span():
    """What a collector's file exporter writes, read the way a tail reads it.

    Each line is a whole export, so a receiver can hand the reader one line or
    the pair and get the same records either way -- which is the property a
    tail needs, and it is the container rules' rather than the receiver's.
    """
    first, second = export(otlp("s0")), export(otlp("s1"))
    together = list(spanweave.read_records(first + b"\n" + second + b"\n"))
    apart = [*spanweave.read_records(first), *spanweave.read_records(second)]
    assert together == apart
    assert [record["span_id"] for record in together] == ["s0", "s1"]
    replay(together)
