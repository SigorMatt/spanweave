"""The capture harness's one testable part (TASKS.md 1.9).

The harness itself is human-run and makes a real model call, so it cannot be
tested here — and must not be. What *can* be tested is the conversion from an
OTel span to the flat dialect the corpus uses, which is where a capture would
actually go wrong. It is duck-typed precisely so this test can exist without
opentelemetry installed.
"""

import json
from types import SimpleNamespace

import pytest

from capture.exporter import JsonlSpanExporter, record_of
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.model import NodeKind
from spanweave.seam import CallRole


def a_span(
    span_id=0x00000000000000A1,
    trace_id=0x000000000000000000000000000000B2,
    parent=None,
    name="Anthropic.messages",
    start=1_000_000_000_000_000_000,
    end=1_000_500_000_000_000_000,
    attributes=None,
    status=None,
    links=(),
):
    return SimpleNamespace(
        context=SimpleNamespace(trace_id=trace_id, span_id=span_id),
        parent=parent,
        name=name,
        start_time=start,
        end_time=end,
        attributes=attributes or {},
        status=status,
        links=links,
    )


def test_ids_become_fixed_width_hex():
    record = record_of(a_span())
    assert record["span_id"] == "00000000000000a1"
    assert record["trace_id"] == "000000000000000000000000000000b2"
    assert record["parent_id"] is None


def test_a_parent_reference_is_carried_across():
    record = record_of(a_span(parent=SimpleNamespace(span_id=0xB)))
    assert record["parent_id"] == "000000000000000b"


def test_nanoseconds_become_unix_seconds():
    record = record_of(a_span())
    assert record["start_time"] == 1_000_000_000.0
    assert record["end_time"] == 1_000_500_000.0


def test_a_span_still_running_has_no_end_time():
    assert record_of(a_span(end=None))["end_time"] is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [(SimpleNamespace(name="OK"), "OK"), (SimpleNamespace(name="ERROR"), "ERROR")],
)
def test_status_is_carried_across_by_name(code, expected):
    span = a_span(status=SimpleNamespace(status_code=code, description="boom"))
    record = record_of(span)
    assert record["status"] == expected
    assert record["status_message"] == "boom"


def test_a_span_with_no_status_is_unset():
    assert record_of(a_span())["status"] == "UNSET"


def test_attributes_pass_through_untouched():
    # The whole reason a captured trace is worth more than a hand-authored
    # one: whatever the instrumentor emitted is what the fixture contains.
    attributes = {
        "openinference.span.kind": "LLM",
        "llm.token_count.prompt": 42,
        "llm.output_messages.0.message.tool_calls.0.tool_call.id": "toolu_x",
    }
    assert record_of(a_span(attributes=attributes))["attributes"] == attributes


def test_sequence_attributes_survive_as_json():
    record = record_of(a_span(attributes={"llm.tools": ("a", "b")}))
    assert record["attributes"]["llm.tools"] == ["a", "b"]
    json.dumps(record)  # must be serializable, or it cannot be a fixture


def test_links_are_carried_across():
    link = SimpleNamespace(
        context=SimpleNamespace(trace_id=0xC, span_id=0xD), attributes={"why": "retry"}
    )
    record = record_of(a_span(links=[link]))
    assert record["links"][0]["span_id"] == "000000000000000d"
    assert record["links"][0]["attributes"] == {"why": "retry"}


def test_a_span_with_no_links_has_no_links_key():
    assert "links" not in record_of(a_span())


# --------------------------------------------------------------------------
# The join that matters: what the harness writes, the adapter must read
# --------------------------------------------------------------------------


LLM_ATTRIBUTES = {
    "openinference.span.kind": "LLM",
    "llm.model_name": "demo-model",
    "llm.token_count.prompt": 42,
    "llm.output_messages.0.message.tool_calls.0.tool_call.id": "toolu_x",
}


def test_what_the_harness_writes_is_what_the_adapter_reads():
    exporter = JsonlSpanExporter()
    exporter.export(
        [
            a_span(
                span_id=0xA1,
                start=1_000_200_000_000_000_000,
                attributes=LLM_ATTRIBUTES,
            ),
            a_span(
                span_id=0xA2,
                parent=SimpleNamespace(span_id=0xA1),
                start=1_000_100_000_000_000_000,
                name="get_weather",
                attributes={
                    "openinference.span.kind": "TOOL",
                    "tool.name": "get_weather",
                    "tool_call.id": "toolu_x",
                },
            ),
        ]
    )
    spans = list(OpenInferenceAdapter().parse(exporter.sorted_records()))
    assert [s.kind for s in spans] == [NodeKind.TOOL, NodeKind.LLM]
    # Sorted by start time, so the tool span (earlier here) comes first.
    assert spans[0].call_role is CallRole.FULFILLER
    assert spans[1].call_role is CallRole.REQUESTER
    assert spans[0].call_id == spans[1].call_id == "toolu_x"
    # And nothing the instrumentor emitted was left unaccounted for.
    assert all(span.unmapped == () for span in spans)


def test_the_exporter_orders_by_start_time_not_by_arrival():
    exporter = JsonlSpanExporter()
    exporter.export([a_span(span_id=0x2, start=200), a_span(span_id=0x1, start=100)])
    assert [r["span_id"][-1] for r in exporter.sorted_records()] == ["1", "2"]


def test_the_exporter_keeps_everything_it_is_given():
    exporter = JsonlSpanExporter()
    exporter.export([a_span(span_id=n) for n in range(5)])
    assert len(exporter.records) == 5
