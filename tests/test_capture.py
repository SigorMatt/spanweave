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

from capture import backends, run
from capture.backends import ANTHROPIC, BACKENDS, OPENAI
from capture.exporter import JsonlSpanExporter, record_of
from spanweave import diagnostics as codes
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.build import build_graph
from spanweave.model import AdapterInfo, NodeKind
from spanweave.seam import CallRole

ADAPTER = OpenInferenceAdapter()


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
    spans = list(ADAPTER.parse(exporter.sorted_records()))
    assert [s.kind for s in spans] == [NodeKind.TOOL, NodeKind.LLM]
    # Sorted by start time, so the tool span (earlier here) comes first.
    assert spans[0].call_role is CallRole.FULFILLER
    assert spans[1].call_role is CallRole.REQUESTER
    assert spans[0].call_ids == spans[1].call_ids == ("toolu_x",)
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


# --------------------------------------------------------------------------
# Backend selection (TASKS.md — Phase 1 review follow-up)
# --------------------------------------------------------------------------


def test_both_backends_are_registered_and_neither_replaced_the_other():
    assert sorted(BACKENDS) == ["anthropic", "openai"]


def test_the_openai_backend_reads_its_endpoint_and_model_from_the_environment():
    assert OPENAI.api_key_env == "NEBIUS_API_KEY"
    assert OPENAI.base_url_env == "NEBIUS_BASE_URL"
    assert OPENAI.model_env == "NEBIUS_MODEL"
    assert OPENAI.default_model == "openai/gpt-oss-120b"
    assert OPENAI.packages == ("openai", "openinference-instrumentation-openai")


def test_the_anthropic_backend_is_unchanged_by_the_addition():
    assert ANTHROPIC.api_key_env == "ANTHROPIC_API_KEY"
    assert ANTHROPIC.base_url_env is None
    assert ANTHROPIC.packages[-1] == "openinference-instrumentation-anthropic"


@pytest.mark.parametrize(
    ("environ", "explicit", "expected"),
    [
        ({"NEBIUS_API_KEY": "k"}, None, "openai"),
        ({"ANTHROPIC_API_KEY": "k"}, None, "anthropic"),
        # An explicit choice wins even against a configured other one.
        ({"ANTHROPIC_API_KEY": "k"}, "openai", "openai"),
        ({}, "anthropic", "anthropic"),
    ],
)
def test_the_configured_backend_is_the_one_selected(environ, explicit, expected):
    assert run.select(explicit, environ).id == expected


def test_two_configured_backends_are_a_hard_error_naming_the_way_out():
    # Same posture as the library's adapter selection (SPEC.md §6.1): a
    # capture that quietly ran against the backend you did not mean is a
    # fixture whose provenance file is wrong.
    with pytest.raises(run.CaptureError) as failure:
        run.select(None, {"NEBIUS_API_KEY": "k", "ANTHROPIC_API_KEY": "k"})
    message = str(failure.value)
    assert "ambiguous" in message
    assert "--backend" in message
    assert "anthropic" in message and "openai" in message


def test_no_configured_backend_says_exactly_what_to_export():
    with pytest.raises(run.CaptureError) as failure:
        run.select(None, {})
    message = str(failure.value)
    assert "NEBIUS_API_KEY" in message
    assert "ANTHROPIC_API_KEY" in message
    assert "NEBIUS_BASE_URL" in message


def test_an_unknown_backend_lists_the_known_ones():
    with pytest.raises(run.CaptureError, match="anthropic, openai"):
        run.select("nebius", {})


@pytest.mark.parametrize(
    ("environ", "explicit", "expected"),
    [
        ({}, None, "openai/gpt-oss-120b"),
        ({"NEBIUS_MODEL": "zai-org/GLM-4.6"}, None, "zai-org/GLM-4.6"),
        ({"SPANWEAVE_CAPTURE_MODEL": "any/model"}, None, "any/model"),
        ({"NEBIUS_MODEL": "from-env"}, "from-flag", "from-flag"),
    ],
)
def test_model_resolution_is_flag_then_env_then_default(environ, explicit, expected):
    assert OPENAI.model(environ, explicit) == expected


# --------------------------------------------------------------------------
# The spans the harness emits itself
# --------------------------------------------------------------------------


def test_a_tool_span_carries_what_the_adapter_needs_to_pair_it():
    call = backends.ToolCall(
        id="call_1", name="get_weather", arguments={"city": "Oslo"}
    )
    attributes = backends.tool_span_attributes(call)
    assert attributes["openinference.span.kind"] == "TOOL"
    assert attributes["tool.name"] == "get_weather"
    # Without this the capture would show a tool that ran and nothing
    # connecting it to the call -- and the library would be right to refuse to
    # guess (SPEC.md §4.4).
    assert attributes["tool_call.id"] == "call_1"
    assert json.loads(attributes["input.value"]) == {"city": "Oslo"}


def test_the_tool_itself_reaches_nothing_and_invents_nothing():
    # A capture is evidence about an instrumentor; a tool with a clock or a
    # network call would put something in the fixture that has to be
    # explained or redacted.
    assert backends.get_weather({"city": "Oslo"}) == backends.get_weather(
        {"city": "Oslo"}
    )
    assert backends.get_weather({"city": "Oslo"})["city"] == "Oslo"


# --------------------------------------------------------------------------
# The OpenAI instrumentor's spans, as stubs
# --------------------------------------------------------------------------

# What openinference-instrumentation-openai puts on a chat.completions span.
# Some of it this library normalizes; the rest must be REPORTED as unmapped,
# not quietly lost -- which is the property being checked below.
OPENAI_LLM_ATTRIBUTES = {
    "openinference.span.kind": "LLM",
    "llm.model_name": "openai/gpt-oss-120b",
    "llm.provider": "openai",
    "llm.system": "openai",
    "llm.token_count.prompt": 61,
    "llm.token_count.completion": 24,
    "llm.token_count.total": 85,
    "llm.input_messages.0.message.role": "user",
    "llm.input_messages.0.message.content": "What is the weather in Paris?",
    "llm.output_messages.0.message.role": "assistant",
    "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call_1",
    "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "get_weather",
    "llm.invocation_parameters": '{"tools":[{"type":"function"}]}',
    "output.value": '{"choices":[{"message":{"tool_calls":[{"id":"call_1"}]}}]}',
    "output.mime_type": "application/json",
}


def test_an_openai_instrumentor_span_reads_as_an_llm_node():
    span = next(
        iter(ADAPTER.parse([record_of(a_span(attributes=OPENAI_LLM_ATTRIBUTES))]))
    )
    assert span.kind is NodeKind.LLM
    assert span.operation == "openai/gpt-oss-120b"
    assert span.usage.input_tokens == 61
    assert span.usage.total_tokens == 85
    # The pairing id, recovered from the dotted message attribute.
    assert span.call_ids == ("call_1",)
    assert span.call_role is CallRole.REQUESTER


def test_what_the_openai_instrumentor_emits_and_we_do_not_map_is_reported():
    span = next(
        iter(ADAPTER.parse([record_of(a_span(attributes=OPENAI_LLM_ATTRIBUTES))]))
    )
    assert "llm.provider" in span.unmapped
    assert "llm.input_messages.0.message.content" in span.unmapped
    # Keys only. The values are already in raw.
    assert codes.UNMAPPED_ATTRIBUTES in [d.code for d in span.diagnostics]
    assert span.raw.source["attributes"]["llm.provider"] == "openai"


def test_the_exporter_needs_no_change_for_the_second_instrumentor():
    # record_of reads the OTel ReadableSpan surface -- context, parent, name,
    # timestamps, status, attributes, links -- which is the same class
    # whichever instrumentor filled it. The dialect lives in the attribute
    # KEYS, and those are copied verbatim. So the same function handles both,
    # and the two records differ only where the instrumentors differ.
    anthropic_like = record_of(a_span(attributes=LLM_ATTRIBUTES))
    openai_like = record_of(a_span(attributes=OPENAI_LLM_ATTRIBUTES))
    assert set(anthropic_like) - {"attributes"} == set(openai_like) - {"attributes"}
    assert anthropic_like["span_id"] == openai_like["span_id"]


# --------------------------------------------------------------------------
# The whole intended shape, without a network
# --------------------------------------------------------------------------


def a_capture():
    """The spans one `make capture` run is meant to produce.

    Two from the instrumentor (`llm`), two from `capture/backends.py`
    (`agent`, `tool`) -- because executing a tool is not an SDK call, so no
    instrumentor would record it and the trace would otherwise be two sibling
    root LLM spans with no containment and no pairing at all.
    """
    agent = 0xA0
    return [
        a_span(
            span_id=agent,
            name="agent.run",
            start=1_000_000_000_000_000_000,
            end=1_000_004_000_000_000_000,
            attributes={
                "openinference.span.kind": "AGENT",
                "input.value": backends.QUESTION,
                "input.mime_type": "text/plain",
            },
        ),
        a_span(
            span_id=0xA1,
            parent=SimpleNamespace(span_id=agent),
            name="ChatCompletion",
            start=1_000_000_200_000_000_000,
            end=1_000_001_000_000_000_000,
            attributes=OPENAI_LLM_ATTRIBUTES,
        ),
        a_span(
            span_id=0xA2,
            parent=SimpleNamespace(span_id=agent),
            name="tool.get_weather",
            start=1_000_001_200_000_000_000,
            end=1_000_002_000_000_000_000,
            attributes={
                **backends.tool_span_attributes(
                    backends.ToolCall("call_1", "get_weather", {"city": "Paris"})
                ),
                "output.value": '{"celsius":18}',
                "output.mime_type": "application/json",
            },
        ),
        a_span(
            span_id=0xA3,
            parent=SimpleNamespace(span_id=agent),
            name="ChatCompletion",
            start=1_000_002_200_000_000_000,
            end=1_000_003_000_000_000_000,
            attributes={
                "openinference.span.kind": "LLM",
                "llm.model_name": "openai/gpt-oss-120b",
                "output.value": "It is 18C and clear in Paris.",
                "output.mime_type": "text/plain",
            },
        ),
    ]


def test_the_intended_capture_builds_into_the_reference_scenario_shape():
    # The strongest claim available without a key: what `make capture` is
    # designed to emit is exactly the shape `llm_tool_llm` asserts -- 1 agent,
    # 2 llm, 1 tool; 3 parent, 1 call_result, 2 temporal.
    exporter = JsonlSpanExporter()
    exporter.export(a_capture())
    graph = build_graph(
        ADAPTER.parse(exporter.sorted_records()),
        adapter=AdapterInfo(id=ADAPTER.id, version=ADAPTER.version),
    )
    assert [n.kind.value for n in graph.nodes()] == ["agent", "llm", "tool", "llm"]
    assert len(graph.edges(kind="parent")) == 3
    assert len(graph.edges(kind="temporal")) == 2

    pairing = graph.edges(kind="call_result")
    assert len(pairing) == 1
    assert pairing[0].basis == "tool_call_id"
    # The relation the whole harness exists to demonstrate, recovered from a
    # real instrumentor's attribute joined to our own tool span's id.
    llm, tool = graph.nodes()[1], graph.nodes()[2]
    assert (pairing[0].src, pairing[0].dst) == (llm.id, tool.id)


def test_the_intended_capture_reports_rather_than_drops_what_it_cannot_map():
    exporter = JsonlSpanExporter()
    exporter.export(a_capture())
    graph = build_graph(
        ADAPTER.parse(exporter.sorted_records()),
        adapter=AdapterInfo(id=ADAPTER.id, version=ADAPTER.version),
    )
    # A real instrumentor emits more than this library normalizes, and that
    # is fine -- as long as it is visible. Nothing else should be diagnosed.
    assert {d.code for d in graph.diagnostics} == {codes.UNMAPPED_ATTRIBUTES}


def test_without_the_harnesss_own_spans_there_would_be_no_pairing_at_all():
    # Why backends.py emits the agent and tool spans: an instrumentor wraps an
    # SDK client, and executing a tool is not an SDK call. Drop those two
    # spans and the capture proves almost nothing.
    llm_only = [span for span in a_capture() if "ChatCompletion" in span.name]
    exporter = JsonlSpanExporter()
    exporter.export(llm_only)
    graph = build_graph(
        ADAPTER.parse(exporter.sorted_records()),
        adapter=AdapterInfo(id=ADAPTER.id, version=ADAPTER.version),
    )
    assert graph.edges(kind="call_result") == ()
    assert graph.edges(kind="parent") == ()
    assert codes.UNPAIRED_CALL in {d.code for d in graph.diagnostics}
