"""The OpenInference adapter (TASKS.md 1.3).

Most of what an adapter must get right is what it refuses to invent, so most
of these assert a `None`, an `absent`, or a diagnostic.
"""

import json
import pathlib

import pytest

from spanweave import diagnostics as codes
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.model import NodeKind, PayloadState, Status
from spanweave.read import read_trace
from spanweave.seam import CallRole

FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
)

ADAPTER = OpenInferenceAdapter()


def span_of(attributes=None, **record):
    full = {"span_id": "s1", "name": "op", **record}
    if attributes is not None:
        full["attributes"] = attributes
    return next(iter(ADAPTER.parse([full])))


def codes_of(span):
    return [d.code for d in span.diagnostics]


# --------------------------------------------------------------------------
# The seeded scenario
# --------------------------------------------------------------------------


def test_the_worked_example_parses_exactly_as_the_scenario_describes():
    spans = list(ADAPTER.parse(read_trace(FIXTURE)))
    assert [s.source_key for s in spans] == ["s0", "s1", "s2", "s3"]
    assert [s.kind for s in spans] == [
        NodeKind.AGENT,
        NodeKind.LLM,
        NodeKind.TOOL,
        NodeKind.LLM,
    ]
    assert [s.operation for s in spans] == [None, "demo-model", "lookup", "demo-model"]
    # Payload states, per FIXTURES.md §7: absent is not empty.
    assert [s.inputs.state for s in spans] == [
        PayloadState.PRESENT,
        PayloadState.ABSENT,
        PayloadState.PRESENT,
        PayloadState.ABSENT,
    ]
    assert [s.outputs.state for s in spans] == [
        PayloadState.ABSENT,
        PayloadState.PRESENT,
        PayloadState.PRESENT,
        PayloadState.PRESENT,
    ]
    # Usage on the two llm spans only, and no invented total.
    assert [s.usage is None for s in spans] == [True, False, True, False]
    assert spans[1].usage.total_tokens is None
    # The pairing the whole scenario exists for.
    assert (spans[1].call_ids, spans[1].call_role) == (("call_a",), CallRole.REQUESTER)
    assert (spans[2].call_ids, spans[2].call_role) == (("call_a",), CallRole.FULFILLER)
    # The clean case: nothing unmapped, nothing diagnosed.
    assert all(s.unmapped == () for s in spans)
    assert all(s.diagnostics == () for s in spans)


def test_every_record_keeps_its_verbatim_source():
    records = list(read_trace(FIXTURE))
    spans = list(ADAPTER.parse(records))
    assert [s.raw.source for s in spans] == records
    assert [s.raw.line_number for s in spans] == [1, 2, 3, 4]


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def test_detection_keys_on_the_distinctive_marker():
    assert ADAPTER.detect(list(read_trace(FIXTURE))) == 0.9


def test_detection_is_honest_rather_than_defensive():
    # Not 1.0: certainty is not ours to declare, and an inflated claim turns
    # selection into a race (ADAPTERS.md §2).
    assert ADAPTER.detect(list(read_trace(FIXTURE))) < 1.0


def test_a_generic_span_shape_is_not_claimed():
    assert ADAPTER.detect([{"span_id": "s0", "name": "x", "start_time": 1.0}]) == 0.0


@pytest.mark.parametrize(
    "sample", [[], [None], ["text"], [{"attributes": "not a mapping"}], [[1, 2]]]
)
def test_detection_never_raises(sample):
    assert ADAPTER.detect(sample) == 0.0


# --------------------------------------------------------------------------
# Payload states -- the part adapters get wrong
# --------------------------------------------------------------------------


def test_no_attribute_at_all_is_absent():
    span = span_of({"openinference.span.kind": "TOOL"})
    assert span.inputs.state is PayloadState.ABSENT
    assert span.inputs.raw is None


def test_an_emitted_but_empty_value_is_empty_not_absent():
    span = span_of(
        {
            "openinference.span.kind": "TOOL",
            "input.value": "",
            "input.mime_type": "text/plain",
        }
    )
    assert span.inputs.state is PayloadState.EMPTY
    assert span.inputs.raw == ""


@pytest.mark.parametrize("body", ["{}", "[]"])
def test_an_empty_json_document_is_empty(body):
    span = span_of(
        {
            "openinference.span.kind": "TOOL",
            "input.value": body,
            "input.mime_type": "application/json",
        }
    )
    assert span.inputs.state is PayloadState.EMPTY


def test_a_source_signalled_redaction_is_redacted_and_untouched():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "input.value": "__REDACTED__",
            "input.mime_type": "text/plain",
        }
    )
    assert span.inputs.state is PayloadState.REDACTED
    # We mark what the source marked; we never redact anything ourselves.
    assert span.inputs.raw == "__REDACTED__"
    assert span.inputs.value is None


def test_json_is_parsed_and_the_source_text_is_kept():
    span = span_of(
        {
            "openinference.span.kind": "TOOL",
            "output.value": '{"status":"shipped"}',
            "output.mime_type": "application/json",
        }
    )
    assert span.outputs.value == {"status": "shipped"}
    assert span.outputs.raw == '{"status":"shipped"}'


def test_unparseable_json_stays_present_and_is_diagnosed():
    span = span_of(
        {
            "openinference.span.kind": "TOOL",
            "output.value": "{not json",
            "output.mime_type": "application/json",
        }
    )
    # Present: something WAS reported. We just could not read it.
    assert span.outputs.state is PayloadState.PRESENT
    assert span.outputs.value is None
    assert span.outputs.raw == "{not json"
    assert codes_of(span) == [codes.PAYLOAD_PARSE_FAILED]


def test_a_non_json_mime_keeps_the_text_as_the_value():
    span = span_of(
        {
            "openinference.span.kind": "AGENT",
            "input.value": "Look up the order status.",
            "input.mime_type": "text/plain",
        }
    )
    assert span.inputs.value == "Look up the order status."


def test_this_adapter_never_marks_anything_truncated():
    # OpenInference signals redaction but has no truncation signal. Producing
    # `truncated` here would claim the instrumentor said something it did not
    # -- so the state exists in the model and is simply never reached from
    # this dialect. That is honest degradation, not a gap.
    records = list(read_trace(FIXTURE))
    for span in ADAPTER.parse(records):
        assert span.inputs.state is not PayloadState.TRUNCATED
        assert span.outputs.state is not PayloadState.TRUNCATED


# --------------------------------------------------------------------------
# Kinds
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("AGENT", NodeKind.AGENT),
        ("LLM", NodeKind.LLM),
        ("TOOL", NodeKind.TOOL),
        ("RETRIEVER", NodeKind.RETRIEVER),
        ("EMBEDDING", NodeKind.EMBEDDING),
        ("CHAIN", NodeKind.CHAIN),
        ("llm", NodeKind.LLM),
    ],
)
def test_known_kinds_map(reported, expected):
    assert span_of({"openinference.span.kind": reported}).kind is expected


def test_an_unmapped_kind_becomes_unknown_plus_a_diagnostic():
    span = span_of({"openinference.span.kind": "GUARDRAIL"})
    assert span.kind is NodeKind.UNKNOWN
    assert codes_of(span) == [codes.UNKNOWN_SPAN_KIND]
    # The original string survives in both places (OPEN_QUESTIONS.md §1).
    assert span.attributes["reported_kind"] == "GUARDRAIL"
    assert span.diagnostics[0].source == "GUARDRAIL"


def test_a_near_miss_is_never_forced_into_a_neighbouring_kind():
    # "RERANKER" is retriever-ish. A wrong kind is worse than an honest
    # unknown, because unknown is visible and a wrong kind is not.
    assert span_of({"openinference.span.kind": "RERANKER"}).kind is NodeKind.UNKNOWN


def test_a_span_with_no_kind_attribute_is_unknown_and_kept():
    span = span_of({"input.value": "x", "input.mime_type": "text/plain"})
    assert span.kind is NodeKind.UNKNOWN
    assert codes.UNKNOWN_SPAN_KIND in codes_of(span)
    assert span.raw.source["attributes"]["input.value"] == "x"


def test_a_record_that_is_not_an_object_is_kept_as_an_unknown_node():
    span = next(iter(ADAPTER.parse(["just a string"])))
    assert span.kind is NodeKind.UNKNOWN
    assert span.raw.source == "just a string"
    assert codes_of(span) == [codes.UNKNOWN_SPAN_KIND]


# --------------------------------------------------------------------------
# Usage
# --------------------------------------------------------------------------


def test_token_counts_map_and_extras_are_kept_not_dropped():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 42,
            "llm.token_count.completion": 17,
            "llm.token_count.total": 59,
            "llm.token_count.prompt_details.cache_read": 8,
        }
    )
    assert span.usage.input_tokens == 42
    assert span.usage.output_tokens == 17
    assert span.usage.total_tokens == 59
    assert span.usage.extra == {"prompt_details.cache_read": 8}


def test_a_total_is_never_computed():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 42,
            "llm.token_count.completion": 17,
        }
    )
    assert span.usage.total_tokens is None


def test_no_counts_means_no_usage_rather_than_a_row_of_zeroes():
    assert span_of({"openinference.span.kind": "LLM"}).usage is None


def test_a_token_count_that_is_not_a_count_is_reported_as_unmapped():
    span = span_of({"openinference.span.kind": "LLM", "llm.token_count.prompt": "many"})
    assert span.usage is None
    assert "llm.token_count.prompt" in span.unmapped


# --------------------------------------------------------------------------
# Call pairing -- ids only, never guesses
# --------------------------------------------------------------------------


def test_a_tool_span_carrying_a_call_id_is_the_fulfiller():
    span = span_of({"openinference.span.kind": "TOOL", "tool_call.id": "call_a"})
    assert (span.call_ids, span.call_role) == (("call_a",), CallRole.FULFILLER)


def test_a_requester_is_recognized_from_the_dotted_message_attribute():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call_a",
        }
    )
    assert (span.call_ids, span.call_role) == (("call_a",), CallRole.REQUESTER)


def test_a_requester_is_recognized_from_an_id_stated_in_the_output_payload():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "output.value": json.dumps({"tool_calls": [{"id": "call_a"}]}),
            "output.mime_type": "application/json",
        }
    )
    assert (span.call_ids, span.call_role) == (("call_a",), CallRole.REQUESTER)


def test_a_span_with_no_id_gets_no_pairing_at_all():
    # Not by name, not by proximity, not by timing (SPEC.md §4.4).
    span = span_of({"openinference.span.kind": "TOOL", "tool.name": "lookup"})
    assert span.call_ids == ()
    assert span.call_role is None


def test_several_requested_calls_are_all_carried():
    # One LLM span requesting several tools at once is how current agent
    # frameworks work, not an edge case. All of the ids travel, and nothing
    # has to be reported as unmapped to avoid dropping one.
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "output.value": json.dumps(
                {"tool_calls": [{"id": "call_a"}, {"id": "call_b"}]}
            ),
            "output.mime_type": "application/json",
        }
    )
    assert span.call_ids == ("call_a", "call_b")
    assert span.call_role is CallRole.REQUESTER
    assert codes_of(span) == []


def test_duplicate_ids_across_the_two_sources_are_not_repeated():
    span = span_of(
        {
            "openinference.span.kind": "LLM",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call_a",
            "output.value": json.dumps({"tool_calls": [{"id": "call_a"}]}),
            "output.mime_type": "application/json",
        }
    )
    assert span.call_ids == ("call_a",)


# --------------------------------------------------------------------------
# Losslessness: unmapped keys are reported, not lost
# --------------------------------------------------------------------------


def test_unrecognized_attributes_are_reported_by_key_and_kept_in_raw():
    span = span_of(
        {"openinference.span.kind": "LLM", "llm.invocation_parameters": '{"top_p":1}'}
    )
    assert span.unmapped == ("llm.invocation_parameters",)
    assert codes_of(span) == [codes.UNMAPPED_ATTRIBUTES]
    # Keys only in the diagnostic -- the value is already in raw, and copying
    # payload content into a diagnostic is exposure with no benefit.
    assert span.diagnostics[0].source == ["llm.invocation_parameters"]
    assert span.raw.source["attributes"]["llm.invocation_parameters"] == '{"top_p":1}'


def test_unrecognized_record_keys_are_reported_too():
    span = span_of({"openinference.span.kind": "LLM"}, events=[{"name": "retry"}])
    assert span.unmapped == ("<record>.events",)


def test_the_clean_case_reports_nothing():
    span = span_of(
        {
            "openinference.span.kind": "TOOL",
            "tool.name": "lookup",
            "tool_call.id": "call_a",
            "input.value": "{}",
            "input.mime_type": "application/json",
        }
    )
    assert span.unmapped == ()
    assert span.diagnostics == ()


# --------------------------------------------------------------------------
# Status, time, links, data edges
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [("OK", Status.OK), ("ERROR", Status.ERROR), ("UNSET", Status.UNSET)],
)
def test_status_maps(reported, expected):
    assert span_of({"openinference.span.kind": "TOOL"}, status=reported) is not None
    assert (
        span_of({"openinference.span.kind": "TOOL"}, status=reported).status is expected
    )


def test_a_missing_status_is_unset_not_ok():
    assert span_of({"openinference.span.kind": "TOOL"}).status is Status.UNSET


def test_an_otel_style_status_object_is_understood_and_its_message_kept():
    span = span_of(
        {"openinference.span.kind": "TOOL"},
        status={"code": "ERROR", "message": "connection reset"},
    )
    assert span.status is Status.ERROR
    assert span.status_note == "connection reset"


def test_timestamps_are_taken_as_reported_and_never_rescaled():
    span = span_of(
        {"openinference.span.kind": "TOOL"}, start_time=1000.2, end_time=1001
    )
    assert (span.started_at, span.ended_at) == (1000.2, 1001.0)


def test_an_unreadable_timestamp_becomes_none_rather_than_a_guess():
    span = span_of(
        {"openinference.span.kind": "TOOL"}, start_time="2026-08-21T00:00:00Z"
    )
    assert span.started_at is None


def test_span_links_are_transcribed_including_cross_trace_ones():
    span = span_of(
        {"openinference.span.kind": "AGENT"},
        links=[{"span_id": "s9", "trace_id": "t2"}],
    )
    assert span.links[0].span_id == "s9"
    assert span.links[0].trace_id == "t2"
    assert span.links[0].basis == "span.link"


def test_this_dialect_declares_no_data_edges_so_none_are_produced():
    # OpenInference states no producer -> consumer relation. Comparing an
    # output to an input to manufacture one is forbidden (SPEC.md §4.2).
    for span in ADAPTER.parse(read_trace(FIXTURE)):
        assert span.data_edges == ()


# --------------------------------------------------------------------------
# Never raises
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        None,
        5,
        [],
        {"attributes": None},
        {"attributes": {"openinference.span.kind": None}},
        {"attributes": {"openinference.span.kind": "TOOL", "tool_call.id": 5}},
        {"span_id": 5, "attributes": {"openinference.span.kind": "TOOL"}},
        {"attributes": {"openinference.span.kind": "TOOL"}, "links": "nope"},
        {"attributes": {"openinference.span.kind": "TOOL"}, "status": 7},
    ],
)
def test_parsing_hostile_records_never_raises(record):
    spans = list(ADAPTER.parse([record]))
    assert len(spans) == 1
    assert spans[0].raw.source == record


def test_parsing_is_lazy():
    pulled = []

    def records():
        for record in read_trace(FIXTURE):
            pulled.append(record)
            yield record

    spans = ADAPTER.parse(records())
    assert pulled == []
    next(spans)
    assert len(pulled) == 1
