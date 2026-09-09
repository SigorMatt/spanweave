"""The builder: nodes and explicit edges (TASKS.md 1.5).

The builder's whole job is to state what the telemetry stated and to account
for what it could not. So the tests come in pairs: an edge that gets built,
and the same shape one field short, which produces a diagnostic and no edge.
"""

import dataclasses

import pytest

from spanweave import diagnostics as codes
from spanweave.build import LINK_BASIS, TIMESTAMP_UNIT_CEILING, build_graph
from spanweave.diagnostics import DiagnosticCollector
from spanweave.model import (
    AdapterInfo,
    Diagnostic,
    DiagnosticLevel,
    EdgeKind,
    NodeKind,
    Payload,
    PayloadState,
    RawRecord,
    Warrant,
)
from spanweave.seam import CallRole, NormalizedSpan, SpanLink

ADAPTER = AdapterInfo(id="some_dialect", version="0.1.0", declared_confidence=0.9)


def a_span(span_id, parent=None, *, trace="t1", line=1, **overrides):
    return NormalizedSpan(
        source_key=span_id,
        span_id=span_id,
        parent_id=parent,
        trace_id=trace,
        kind=overrides.pop("kind", NodeKind.CHAIN),
        name=overrides.pop("name", f"op.{span_id}"),
        raw=RawRecord(source={"span_id": span_id}, source_id=span_id, line_number=line),
        **overrides,
    )


def build(spans, **kwargs):
    # Explicit edges only. Derived temporal edges -- and the
    # `missing_timestamp` diagnostics that explain the nodes they skip -- are
    # 1.6's subject and are exercised in `test_ordering.py`. Switching them
    # off here keeps these assertions exact rather than filtered.
    kwargs.setdefault("temporal", False)
    return build_graph(spans, adapter=ADAPTER, **kwargs)


def edges_of(graph, kind):
    return [(e.src, e.dst) for e in graph.edges() if e.kind is kind]


def codes_of(graph):
    return [d.code for d in graph.diagnostics]


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


def test_every_span_becomes_a_node_carrying_its_source():
    graph = build([a_span("s0"), a_span("s1", "s0", line=2)])
    assert [n.id for n in graph.nodes()] == ["s0", "s1"]
    assert graph.nodes()[0].raw.source == {"span_id": "s0"}
    assert graph.nodes()[0].provenance.adapter_id == "some_dialect"


def test_the_node_reports_what_the_span_reported_and_nothing_more():
    span = a_span(
        "s0",
        operation="lookup",
        started_at=1000.0,
        ended_at=1001.0,
        inputs=Payload(state=PayloadState.EMPTY, mime="text/plain", value="", raw=""),
    )
    node = build([span]).nodes()[0]
    assert node.operation == "lookup"
    assert node.inputs.state is PayloadState.EMPTY
    # Never invented on the way through.
    assert node.outputs.state is PayloadState.ABSENT
    assert node.usage is None


def test_an_empty_input_builds_an_empty_graph_rather_than_failing():
    graph = build([])
    assert graph.nodes() == () and graph.edges() == ()
    assert graph.meta.node_count == 0


def test_the_adapters_own_diagnostics_are_attached_to_their_node():
    span = a_span(
        "s0",
        diagnostics=(Diagnostic(code=codes.UNKNOWN_SPAN_KIND, message="odd kind"),),
    )
    graph = build([span])
    assert graph.diagnostics[0].node_id == "s0"


# --------------------------------------------------------------------------
# parent
# --------------------------------------------------------------------------


def test_parent_edges_come_from_the_stated_parent_id():
    graph = build([a_span("s0"), a_span("s1", "s0"), a_span("s2", "s0")])
    assert edges_of(graph, EdgeKind.PARENT) == [("s0", "s1"), ("s0", "s2")]
    parent = graph.edges()[0]
    assert parent.warrant is Warrant.EXPLICIT
    assert parent.basis == "span.parent_span_id"


def test_a_parent_that_is_not_here_is_diagnosed_and_the_node_is_kept():
    graph = build([a_span("s1", "missing")])
    assert edges_of(graph, EdgeKind.PARENT) == []
    assert codes_of(graph) == [codes.ORPHAN_PARENT]
    assert graph.diagnostics[0].node_id == "s1"
    # A trace that starts mid-run is ordinary; dropping the record would lose
    # more than the missing parent did.
    assert len(graph.nodes()) == 1


def test_a_parent_edge_is_never_derived():
    # parent is explicit-only (SPEC.md §4.1) and the model refuses otherwise;
    # this asserts the builder does not try.
    graph = build([a_span("s0"), a_span("s1", "s0")])
    assert all(e.warrant is Warrant.EXPLICIT for e in graph.edges())


# --------------------------------------------------------------------------
# call_result
# --------------------------------------------------------------------------


def test_a_call_and_its_result_are_joined_by_the_id_the_dialect_carried():
    graph = build(
        [
            a_span("s1", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("call_a",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2")]
    assert graph.edges()[0].basis == "tool_call_id"
    assert codes_of(graph) == []


def test_the_pairing_is_independent_of_the_parent_relation():
    # Frequently the two are different relations entirely (SPEC.md §4.4).
    graph = build(
        [
            a_span("s0"),
            a_span("s1", "s0", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", "s0", call_ids=("call_a",), call_role=CallRole.FULFILLER),
        ]
    )
    assert ("s1", "s2") in edges_of(graph, EdgeKind.CALL_RESULT)
    assert ("s1", "s2") not in edges_of(graph, EdgeKind.PARENT)


def test_a_call_nobody_answered_is_diagnosed_not_invented():
    graph = build(
        [
            a_span("s1", call_ids=("call_a",), call_role=CallRole.REQUESTER),
            a_span("s2", name="tool.lookup"),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []
    assert codes_of(graph) == [codes.UNPAIRED_CALL]
    assert "no edge is invented" in graph.diagnostics[0].message


def test_a_result_nobody_asked_for_is_diagnosed_too():
    graph = build([a_span("s2", call_ids=("call_a",), call_role=CallRole.FULFILLER)])
    assert codes_of(graph) == [codes.UNPAIRED_RESULT]


def test_pairing_never_falls_back_to_name_or_proximity():
    # Two spans that obviously belong together, with no id between them.
    graph = build(
        [
            a_span("s1", name="llm.plan", started_at=1.0),
            a_span("s2", name="tool.lookup", started_at=2.0),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []
    assert codes_of(graph) == []


def test_two_spans_fulfilling_one_call_produce_two_explicit_edges():
    graph = build(
        [
            a_span("s1", call_ids=("c",), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("c",), call_role=CallRole.FULFILLER),
            a_span("s3", call_ids=("c",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2"), ("s1", "s3")]


def test_one_span_can_request_several_calls():
    # The shape current agent frameworks emit constantly: one model turn
    # asking for several tools at once.
    graph = build(
        [
            a_span("s1", call_ids=("a", "b"), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("a",), call_role=CallRole.FULFILLER),
            a_span("s3", call_ids=("b",), call_role=CallRole.FULFILLER),
        ]
    )
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2"), ("s1", "s3")]
    assert codes_of(graph) == []


def test_one_unanswered_call_among_several_is_diagnosed_on_its_own():
    graph = build(
        [
            a_span("s1", call_ids=("a", "b"), call_role=CallRole.REQUESTER),
            a_span("s2", call_ids=("a",), call_role=CallRole.FULFILLER),
        ]
    )
    # The answered one still pairs; only the unanswered one is reported.
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s1", "s2")]
    assert codes_of(graph) == [codes.UNPAIRED_CALL]
    assert "'b'" in graph.diagnostics[0].message


def test_a_call_id_without_a_role_pairs_with_nothing():
    graph = build([a_span("s1", call_ids=("c",)), a_span("s2", call_ids=("c",))])
    assert edges_of(graph, EdgeKind.CALL_RESULT) == []


# --------------------------------------------------------------------------
# link and data
# --------------------------------------------------------------------------


def test_a_link_within_the_trace_points_at_the_node():
    graph = build([a_span("s0", links=(SpanLink(span_id="s1"),)), a_span("s1")])
    assert edges_of(graph, EdgeKind.LINK) == [("s0", "s1")]


def test_a_cross_trace_link_is_still_transcribed():
    # Links routinely leave the trace; requiring the target to be present
    # would make the kind useless for the case it exists for (SPEC.md §4).
    graph = build([a_span("s0", links=(SpanLink(span_id="foreign", trace_id="t2"),))])
    assert edges_of(graph, EdgeKind.LINK) == [("s0", "foreign")]
    assert graph.node("foreign") is None


def test_a_link_edge_carries_the_builders_basis_not_the_adapters():
    # The seam states no reason for the link; the builder names the relation.
    # Removing `DeclaredDataEdge` left this the only adapter-supplied basis,
    # and it is a reserved override that no observed dialect takes
    # (`TASKS.md` I1).
    graph = build([a_span("s0", links=(SpanLink(span_id="s1"),)), a_span("s1")])
    edge = next(e for e in graph.edges() if e.kind is EdgeKind.LINK)
    assert edge.warrant is Warrant.EXPLICIT
    assert edge.basis == LINK_BASIS


def test_a_dialect_that_states_a_links_reason_has_it_carried_verbatim():
    # The override exists so that a dialect saying *why* a link exists is not
    # silently overwritten by the builder's constant. Nothing populates it
    # today; this pins the behaviour the field is kept for.
    graph = build(
        [
            a_span("s0", links=(SpanLink(span_id="s1", basis="retry.of"),)),
            a_span("s1"),
        ]
    )
    edge = next(e for e in graph.edges() if e.kind is EdgeKind.LINK)
    assert edge.basis == "retry.of"


def test_no_data_edge_appears_from_matching_values():
    # The output of s1 is the input of s2, and the graph says nothing about
    # it. That restraint is the library's central claim (SPEC.md §4.2).
    produced = Payload(state=PayloadState.PRESENT, value={"order": "A-1"})
    graph = build(
        [
            a_span("s1", outputs=produced),
            a_span("s2", inputs=produced),
        ]
    )
    assert edges_of(graph, EdgeKind.DATA) == []


# --------------------------------------------------------------------------
# Edge set hygiene
# --------------------------------------------------------------------------


def test_duplicate_edges_collapse():
    graph = build(
        [
            a_span("s0", links=(SpanLink(span_id="s1"), SpanLink(span_id="s1"))),
            a_span("s1"),
        ]
    )
    assert len(edges_of(graph, EdgeKind.LINK)) == 1


def test_the_same_pair_may_carry_several_kinds_of_edge():
    graph = build(
        [
            a_span("s0"),
            a_span("s1", "s0", call_ids=("c",), call_role=CallRole.FULFILLER),
            a_span("s0b", call_ids=("c",), call_role=CallRole.REQUESTER),
        ]
    )
    assert ("s0", "s1") in edges_of(graph, EdgeKind.PARENT)
    assert ("s0b", "s1") in edges_of(graph, EdgeKind.CALL_RESULT)


def test_edges_are_sorted_by_kind_then_endpoints_then_basis():
    graph = build([a_span("s0"), a_span("s2", "s0"), a_span("s1", "s0")])
    assert [e.sort_key for e in graph.edges()] == sorted(
        e.sort_key for e in graph.edges()
    )


# --------------------------------------------------------------------------
# Trace identity and honest degradation
# --------------------------------------------------------------------------


def test_the_most_common_trace_id_wins_and_the_rest_are_kept_and_diagnosed():
    graph = build([a_span("s0"), a_span("s1"), a_span("s9", trace="t2")])
    assert graph.trace_id == "t1"
    assert len(graph.nodes()) == 3  # the foreign record is kept
    assert codes_of(graph) == [codes.MULTI_TRACE_INPUT]
    assert graph.diagnostics[0].node_id == "s9"


def test_a_tie_between_trace_ids_is_broken_by_the_id_itself():
    # Arbitrary, but *stated*: otherwise one input could build two graphs.
    first = build([a_span("s0", trace="t2"), a_span("s1", trace="t1")])
    second = build([a_span("s1", trace="t1"), a_span("s0", trace="t2")])
    assert first.trace_id == second.trace_id == "t1"


def test_an_input_with_no_trace_id_still_builds():
    graph = build([a_span("s0", trace=None)])
    assert graph.trace_id == ""
    assert len(graph.nodes()) == 1


# `trace_id == ""` used to be the one degradation the builder did not report:
# the graph said "no trace" and nothing said why. The September 2026 audit
# (batch A4) found it; these hold the answer in place.


def test_an_input_with_no_trace_id_says_so():
    graph = build([a_span("s0", trace=None)])
    assert codes_of(graph) == [codes.MISSING_TRACE_ID]
    reported = graph.diagnostics[0]
    assert reported.level is DiagnosticLevel.INFO
    # No node to point at and no fragment to carry: the absence being
    # reported is the graph's own empty `trace_id` (`SPEC.md` §3.7).
    assert reported.node_id is None
    assert reported.source is None
    assert reported.adapter == "some_dialect"


def test_the_missing_trace_id_is_reported_once_for_the_input_not_once_per_span():
    # Per record, a 10,000-span trace would repeat one sentence 10,000 times
    # and add nothing on any repeat (`SPEC.md` §7).
    graph = build([a_span(f"s{index}", trace=None) for index in range(10)])
    assert codes_of(graph) == [codes.MISSING_TRACE_ID]
    assert len(graph.nodes()) == 10


def test_a_trace_id_that_is_the_empty_string_is_no_trace_id():
    # The dialect reported the field and reported it empty. The graph is in
    # exactly the state it is in when no record reported one at all, so it
    # owes the same answer.
    graph = build([a_span("s0", trace=""), a_span("s1", trace="")])
    assert graph.trace_id == ""
    assert codes_of(graph) == [codes.MISSING_TRACE_ID]


def test_an_input_with_no_records_reports_no_trace_id_either():
    graph = build([])
    assert graph.trace_id == ""
    assert codes_of(graph) == [codes.MISSING_TRACE_ID]
    assert graph.meta.diagnostic_count == 1


def test_a_trace_that_reports_its_id_is_not_diagnosed():
    assert codes_of(build([a_span("s0")])) == []


def test_one_record_short_of_a_trace_id_is_not_a_missing_trace_id():
    # The graph has a trace id, so nothing about it is missing. The record
    # that carried none is not foreign either -- it claims no other trace.
    graph = build([a_span("s0"), a_span("s1", trace=None)])
    assert graph.trace_id == "t1"
    assert codes_of(graph) == []


def test_the_audit_case_end_to_end_a_real_record_with_no_trace_id(tmp_path):
    # The reproduction from tests/audit/probe1.py, which printed a graph with
    # `trace=''` and no diagnostic at all.
    import json

    import spanweave

    record = {
        "span_id": "s0",
        "parent_id": None,
        "name": "a",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": {"openinference.span.kind": "AGENT"},
    }
    path = tmp_path / "no_trace_id.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    graph = spanweave.build(path)
    assert graph.trace_id == ""
    assert [d.code for d in graph.diagnostics if d.code == codes.MISSING_TRACE_ID] == [
        codes.MISSING_TRACE_ID
    ]


def test_a_backwards_clock_is_reported_and_left_alone():
    graph = build([a_span("s0", started_at=1002.0, ended_at=1000.0)])
    assert codes_of(graph) == [codes.NONMONOTONIC_TIME]
    # Reported, never repaired: the skew is a fact about the trace.
    assert graph.nodes()[0].started_at == 1002.0
    assert graph.nodes()[0].ended_at == 1000.0


def test_a_zero_length_span_is_not_skew():
    graph = build([a_span("s0", started_at=1000.0, ended_at=1000.0)])
    assert codes_of(graph) == []


# --------------------------------------------------------------------------
# A timestamp that cannot be in seconds (batch C1, audit finding 5)
# --------------------------------------------------------------------------
#
# 1e11 seconds after the epoch is the year 5138, so a wall-clock time in
# seconds never reaches it -- while *now* in milliseconds is ~1.8e12 and in
# nanoseconds ~1.8e18. A value above the line says something about the UNIT
# of the field and nothing about the run, so it is reported and the number is
# left exactly as it arrived (`SPEC.md` §3.1).


def suspects(graph):
    return [d for d in graph.diagnostics if d.code == codes.TIMESTAMP_UNIT_SUSPECT]


def test_a_nanosecond_timestamp_is_reported_and_left_alone():
    graph = build([a_span("s0", started_at=1.7e18, ended_at=1.7000000002e18)])
    found = suspects(graph)
    assert len(found) == 1
    assert found[0].level is DiagnosticLevel.WARNING
    assert found[0].node_id == "s0"
    # Never rescaled: the whole point is that the library does not convert.
    assert graph.nodes()[0].started_at == 1.7e18
    assert graph.nodes()[0].ended_at == 1.7000000002e18


def test_one_span_gets_one_diagnostic_however_many_of_its_fields_are_over():
    # Both endpoints of a span share one field encoding, so two diagnostics
    # would say one thing twice. The fields are named in `source` instead.
    graph = build([a_span("s0", started_at=1.7e18, ended_at=1.8e18)])
    found = suspects(graph)
    assert len(found) == 1
    assert found[0].source == {"started_at": 1.7e18, "ended_at": 1.8e18}


def test_only_the_field_that_is_over_the_line_is_named():
    graph = build([a_span("s0", started_at=1000.0, ended_at=1.7e18)])
    assert suspects(graph)[0].source == {"ended_at": 1.7e18}


def test_it_is_one_diagnostic_per_node_not_one_per_graph():
    # Unlike `missing_trace_id` there is a node to point at, and the case the
    # answer changes is the mixed one: one exporter in seconds, one in
    # nanoseconds, in a single input.
    graph = build(
        [
            a_span("s0", started_at=1000.0, ended_at=1005.0),
            a_span("s1", started_at=1.7e18, ended_at=1.7000000002e18),
            a_span("s2", started_at=1.8e18, ended_at=1.8000000002e18),
        ]
    )
    assert [d.node_id for d in suspects(graph)] == ["s1", "s2"]


def test_the_threshold_is_strictly_greater_so_the_bound_itself_is_not_suspect():
    assert suspects(build([a_span("s0", started_at=1e11, ended_at=1e11)])) == []
    assert len(suspects(build([a_span("s0", started_at=1e11 + 1.0)]))) == 1


def test_a_duration_is_not_checked_only_the_reported_values_are():
    # A duration is something the library computed by subtracting, and a
    # claim about whether one is plausible is a claim about the run. Both
    # endpoints here are ordinary seconds; the span merely lasts forever.
    graph = build([a_span("s0", started_at=0.0, ended_at=1e10)])
    assert suspects(graph) == []


def test_a_span_with_no_timestamps_is_not_suspect():
    assert suspects(build([a_span("s0")])) == []


def test_the_reported_value_the_diagnostic_shows_is_the_one_the_record_wrote():
    # C1's message says every value is kept exactly as reported. Batch C3 is
    # what makes that true of the message itself: an integer time reaches the
    # node as an `int`, so both `source` and the printed text carry the digits
    # the record wrote rather than the nearest float64 to them.
    reported = 1700000000100000100
    found = suspects(build([a_span("s0", started_at=reported)]))
    assert found[0].source == {"started_at": reported}
    assert str(reported) in found[0].message


def test_the_ceiling_is_printed_as_the_whole_number_it_is():
    # `1e11` printed as `100000000000.0`, which reads as a float somebody
    # chose rather than the year-5138 bound it is (C1 handoff, batch C3).
    message = suspects(build([a_span("s0", started_at=1.7e18)]))[0].message
    assert "exceeds 100000000000," in message
    assert isinstance(TIMESTAMP_UNIT_CEILING, int)


def test_a_span_id_used_twice_with_distinct_source_keys_is_reported():
    spans = [
        NormalizedSpan(
            source_key=key,
            span_id="s1",
            trace_id="t1",
            kind=NodeKind.CHAIN,
            name="op",
            raw=RawRecord(source={}, source_id="s1", line_number=index),
        )
        for index, key in enumerate(["a", "b"], start=1)
    ]
    graph = build(spans)
    assert codes_of(graph) == [codes.DUPLICATE_SOURCE_ID]
    assert len(graph.nodes()) == 2


def test_a_reference_to_an_ambiguous_span_id_is_not_guessed():
    spans = [
        NormalizedSpan(
            source_key=key,
            span_id="s1",
            trace_id="t1",
            kind=NodeKind.CHAIN,
            name="op",
            raw=RawRecord(source={}, line_number=index),
        )
        for index, key in enumerate(["a", "b"], start=1)
    ]
    graph = build([*spans, a_span("s2", "s1")])
    # Two records claim 's1'. Picking one of them to be the parent would be a
    # guess, so there is no parent edge and there is a diagnostic.
    assert edges_of(graph, EdgeKind.PARENT) == []
    assert codes.ORPHAN_PARENT in codes_of(graph)


# --------------------------------------------------------------------------
# The builder knows nothing about dialects
# --------------------------------------------------------------------------


def test_the_builder_works_on_spans_from_a_dialect_it_has_never_heard_of():
    graph = build(
        [
            a_span("x1", kind=NodeKind.UNKNOWN, name="whatever"),
            a_span("x2", "x1", kind=NodeKind.EMBEDDING),
        ],
    )
    assert [n.kind for n in graph.nodes()] == [NodeKind.UNKNOWN, NodeKind.EMBEDDING]
    assert edges_of(graph, EdgeKind.PARENT) == [("x1", "x2")]


def test_diagnostics_raised_before_the_build_are_carried_through():
    collector = DiagnosticCollector()
    collector.add(codes.MALFORMED_RECORD, "line 2 is not valid JSON")
    graph = build([a_span("s0")], collector=collector)
    # A malformed line and an unpaired call are the same kind of statement
    # about the input, and end up in the same list.
    assert codes_of(graph) == [codes.MALFORMED_RECORD]
    assert graph.meta.diagnostic_count == 1


def test_meta_records_the_adapter_and_the_digest_but_no_environment():
    graph = build([a_span("s0")], source_digest="abc123")
    assert graph.meta.adapters == (ADAPTER,)
    assert graph.meta.source_digest == "abc123"
    assert graph.meta.spanweave_version
    # Nothing that would break byte-identical determinism or leak the
    # operator's environment (SPEC.md §3.9).
    assert not hasattr(graph.meta, "built_at")


@pytest.mark.parametrize("field", ["_nodes", "_edges", "diagnostics", "trace_id"])
def test_the_graph_is_immutable(field):
    graph = build([a_span("s0")])
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(graph, field, ())


# --------------------------------------------------------------------------
# `source` on the two unpaired codes (SPEC.md 3.7, `source` per code)
# --------------------------------------------------------------------------
#
# A requested call that nothing fulfils has NO NODE, so `operation` -- where a
# tool's name lives -- has nowhere to be, and the tool a consumer asked about
# was unattributable from the graph (`PREDICTIONS.md` O1). The name rides on
# the diagnostic instead. These pin the shape, because until this change
# nothing in the suite asserted `source` for either code at all.


def _source_of(graph, code):
    return [d.source for d in graph.diagnostics if d.code == code]


def _asking(span_id, call_id, name=None):
    return a_span(
        span_id,
        kind=NodeKind.LLM,
        call_ids=(call_id,),
        call_role=CallRole.REQUESTER,
        call_names={call_id: name} if name else {},
    )


def _answering(span_id, call_id, name=None):
    return a_span(
        span_id,
        kind=NodeKind.TOOL,
        operation=name,
        call_ids=(call_id,),
        call_role=CallRole.FULFILLER,
        call_names={call_id: name} if name else {},
    )


def test_an_unpaired_call_names_the_tool_it_asked_for():
    graph = build([_asking("s0", "call_a", "lookup")])
    assert _source_of(graph, codes.UNPAIRED_CALL) == [
        {"call_id": "call_a", "operation": "lookup"}
    ]


def test_an_unpaired_result_carries_the_same_shape():
    # Redundant there -- the fulfiller HAS a node whose `operation` says it --
    # and carried anyway, so a consumer reading both codes never has to branch
    # on which one it is holding to know what `source` is.
    graph = build([_answering("s0", "call_b", "other")])
    assert _source_of(graph, codes.UNPAIRED_RESULT) == [
        {"call_id": "call_b", "operation": "other"}
    ]


def test_a_dialect_that_names_no_tool_says_so_rather_than_guessing():
    graph = build([_asking("s0", "call_a")])
    assert _source_of(graph, codes.UNPAIRED_CALL) == [
        {"call_id": "call_a", "operation": None}
    ]


def test_a_paired_call_produces_no_diagnostic_to_carry_a_name():
    graph = build([_asking("s0", "call_a", "lookup"), _answering("s1", "call_a", "x")])
    assert _source_of(graph, codes.UNPAIRED_CALL) == []
    assert edges_of(graph, EdgeKind.CALL_RESULT) == [("s0", "s1")]


def test_two_spans_naming_one_call_differently_name_it_at_all():
    # Disagreement is not resolved by picking. Picking would also make the
    # answer depend on input order, which CLAUDE.md 4 forbids outright.
    spans = [_asking("s0", "call_a", "lookup"), _asking("s1", "call_a", "other")]
    assert _source_of(build(spans), codes.UNPAIRED_CALL) == [
        {"call_id": "call_a", "operation": None},
        {"call_id": "call_a", "operation": None},
    ]
    # ...and reversing them says the same thing, which is the point.
    assert _source_of(build(spans), codes.UNPAIRED_CALL) == _source_of(
        build(list(reversed(spans))), codes.UNPAIRED_CALL
    )


def test_call_names_are_copied_out_of_the_caller_s_dict():
    # `NormalizedSpan` is frozen; a mapping passed in must not stay reachable.
    mutable = {"call_a": "lookup"}
    span = _asking("s0", "call_a")
    span = dataclasses.replace(span, call_names=mutable)
    mutable["call_a"] = "something else"
    assert span.call_names == {"call_a": "lookup"}


# --------------------------------------------------------------------------
# Two records claiming one span id (audit finding 2, batch A3)
# --------------------------------------------------------------------------
#
# The whole file used to be refused for this, and SPEC.md 3.7 has always
# described the diagnostic that fires instead. The reproduction below is
# probe1's `duplicate_ids` case, run through the public API.


def _duplicated_span_id_trace():
    import json

    def record(span_id, name, kind, t0, t1, parent=None, tool=None):
        attributes = {"openinference.span.kind": kind}
        if tool is not None:
            attributes["tool.name"] = tool
        return {
            "trace_id": "t1",
            "span_id": span_id,
            "parent_id": parent,
            "name": name,
            "start_time": t0,
            "end_time": t1,
            "status": "OK",
            "attributes": attributes,
        }

    lines = [
        record("s0", "a", "AGENT", 1.0, 3.0),
        record("s1", "t", "TOOL", 1.1, 1.5, parent="s0", tool="t"),
        record("s1", "t2", "TOOL", 1.6, 1.9, parent="s0", tool="t2"),
    ]
    return b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)


def test_a_duplicated_span_id_keeps_both_records_and_says_so():
    import spanweave

    graph = spanweave.build(_duplicated_span_id_trace())
    assert len(graph) == 3
    reported = [d for d in graph.diagnostics if d.code == codes.DUPLICATE_SOURCE_ID]
    assert [d.source for d in reported] == ["s1"]
    assert sorted(node.operation or node.name for node in graph.nodes()) == [
        "a",
        "t",
        "t2",
    ]


def test_a_reference_to_a_duplicated_span_id_resolves_to_neither():
    # Both records answer to `s1`, so a child pointing at it cannot be
    # resolved to one of them, and picking either would be a guess. The child
    # is kept and the unresolved reference is reported.
    import json

    import spanweave

    child = {
        "trace_id": "t1",
        "span_id": "s2",
        "parent_id": "s1",
        "name": "c",
        "start_time": 1.7,
        "end_time": 1.8,
        "status": "OK",
        "attributes": {"openinference.span.kind": "CHAIN"},
    }
    trace = _duplicated_span_id_trace() + json.dumps(child).encode("utf-8") + b"\n"
    graph = spanweave.build(trace)
    assert len(graph) == 4
    assert [d.source for d in graph.diagnostics if d.code == codes.ORPHAN_PARENT] == [
        "s1"
    ]
    assert ("s1", "s2") not in edges_of(graph, EdgeKind.PARENT)


def test_a_duplicated_span_id_builds_the_same_graph_in_any_order():
    import json

    import spanweave

    lines = _duplicated_span_id_trace().splitlines()

    def document(order):
        graph = spanweave.build(b"".join(line + b"\n" for line in order))
        return json.dumps([(n.id, n.name) for n in graph.nodes()], sort_keys=True)

    assert document(lines) == document(list(reversed(lines)))
