"""The capture harness's one testable part (TASKS.md 1.9).

The harness itself is human-run and makes a real model call, so it cannot be
tested here — and must not be. What *can* be tested is the conversion from an
OTel span to the flat dialect the corpus uses, which is where a capture would
actually go wrong. It is duck-typed precisely so this test can exist without
opentelemetry installed.
"""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from capture import backends, fleet, run
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


# --------------------------------------------------------------------------
# The scratch fleet (TASKS.md 2.2)
# --------------------------------------------------------------------------
#
# The fleet is human-run and makes N real model calls, so what is testable
# here is the same half as everywhere else in this file: the logic around the
# call, verified against stub spans. In particular the coverage report -- the
# thing that tells a human whether the fleet they just paid for actually
# contains the shapes P5 needs -- is pure and is tested end to end, span to
# verdict.


class StubSpan:
    """Enough of an OTel span for the harness's own emitting code."""

    def __init__(self, name, attributes):
        self.name = name
        self.attributes = dict(attributes)
        self.exited_with = None

    def set_attribute(self, key, value):
        self.attributes[key] = value


class StubTracer:
    """Records the spans the harness emits, and how each one ended."""

    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name, attributes=None):
        span = StubSpan(name, attributes or {})
        self.spans.append(span)

        class _Scope:
            def __enter__(self):
                return span

            def __exit__(self, kind, value, traceback):
                span.exited_with = kind
                return False  # never swallow: the tracer must see the failure

        return _Scope()


def a_tool_span(tool="get_weather", call_id="call_1", status=None, span_id=0xA2):
    return a_span(
        span_id=span_id,
        name=f"tool.{tool}",
        status=status,
        attributes=backends.tool_span_attributes(
            backends.ToolCall(call_id, tool, {"city": "Paris"})
        ),
    )


def an_llm_span(span_id=0xA1):
    return a_span(
        span_id=span_id,
        name="ChatCompletion",
        attributes={"openinference.span.kind": "LLM"},
    )


ERROR_STATUS = SimpleNamespace(
    status_code=SimpleNamespace(name="ERROR"), description="no such flight"
)


def records_of(*spans):
    """Stub spans -> the dialect records a fleet file would actually hold."""
    exporter = JsonlSpanExporter()
    exporter.export(list(spans))
    return exporter.sorted_records()


# -- the four required shapes, each read back off records ------------------


def test_an_ordinary_run_shows_a_tool_call_and_nothing_else():
    shapes = fleet.shapes_of(records_of(an_llm_span(), a_tool_span()))
    assert shapes == frozenset({fleet.TOOL_CALL})


def test_a_run_with_no_tool_span_is_no_tool_call_not_an_empty_result():
    # The distinction matters: "the model answered directly" is one of the
    # shapes P5 needs, not a failed capture.
    shapes = fleet.shapes_of(records_of(an_llm_span()))
    assert fleet.NO_TOOL_CALL in shapes
    assert fleet.TOOL_CALL not in shapes


def test_two_tool_spans_in_one_trace_are_parallel_calls():
    trace = records_of(
        an_llm_span(),
        a_tool_span(call_id="call_1", span_id=0xA2),
        a_tool_span(tool="get_population", call_id="call_2", span_id=0xA3),
    )
    assert fleet.PARALLEL_TOOL_CALLS in fleet.shapes_of(trace)


def test_a_failed_tool_span_is_the_error_shape():
    trace = records_of(
        an_llm_span(), a_tool_span(tool="lookup_flight", status=ERROR_STATUS)
    )
    assert fleet.TOOL_ERROR in fleet.shapes_of(trace)


def test_an_error_on_a_non_tool_span_is_not_the_tool_error_shape():
    # Otherwise a failed LLM call would quietly satisfy the requirement for a
    # failing *tool*, and the fleet would be missing a shape it claims to have.
    llm = a_span(
        name="ChatCompletion",
        status=ERROR_STATUS,
        attributes={"openinference.span.kind": "LLM"},
    )
    assert fleet.TOOL_ERROR not in fleet.shapes_of(records_of(llm, a_tool_span()))


# -- varied tools is a property of the fleet, not of a trace ---------------


def test_one_trace_can_never_show_varied_tools():
    assert fleet.VARIED_TOOLS not in fleet.shapes_of(
        records_of(an_llm_span(), a_tool_span())
    )


def test_varied_tools_appears_only_once_two_runs_used_different_tools():
    same = [records_of(an_llm_span(), a_tool_span()) for _ in range(2)]
    assert fleet.VARIED_TOOLS not in fleet.coverage(same)

    varied = [
        records_of(an_llm_span(), a_tool_span(tool="get_weather")),
        records_of(an_llm_span(), a_tool_span(tool="convert_currency")),
    ]
    assert fleet.coverage(varied)[fleet.VARIED_TOOLS] == (1, 2)


# -- the coverage verdict --------------------------------------------------


def a_complete_fleet():
    """One trace per required shape, as records."""
    return [
        records_of(an_llm_span(), a_tool_span()),
        records_of(an_llm_span()),
        records_of(
            an_llm_span(),
            a_tool_span(call_id="call_1", span_id=0xA2),
            a_tool_span(tool="get_population", call_id="call_2", span_id=0xA3),
        ),
        records_of(
            an_llm_span(), a_tool_span(tool="lookup_flight", status=ERROR_STATUS)
        ),
    ]


def test_a_complete_fleet_is_missing_nothing():
    assert fleet.missing(fleet.coverage(a_complete_fleet())) == ()


def test_a_fleet_of_only_the_reference_run_is_missing_three_shapes():
    dull = [records_of(an_llm_span(), a_tool_span()) for _ in range(8)]
    assert set(fleet.missing(fleet.coverage(dull))) == {
        fleet.VARIED_TOOLS,
        fleet.NO_TOOL_CALL,
        fleet.PARALLEL_TOOL_CALLS,
        fleet.TOOL_ERROR,
    }


def test_the_report_names_the_missing_shapes_and_refuses_the_shortcut():
    dull = [records_of(an_llm_span(), a_tool_span())]
    found = fleet.coverage(dull)
    text = fleet.report(found, fleet.missing(found))
    assert "MISSING" in text
    for shape in fleet.missing(found):
        assert shape in text
    # The one thing a human under timebox pressure might otherwise do.
    assert "edit an exported span" in text
    assert "SCRATCH" in text


def test_a_complete_fleets_report_says_it_is_usable():
    found = fleet.coverage(a_complete_fleet())
    assert "MISSING" not in fleet.report(found, fleet.missing(found))


# -- the specs themselves --------------------------------------------------


def test_the_fleet_is_steered_at_every_required_shape():
    # A tripwire: delete or reword a spec and the fleet can silently stop
    # aiming at a shape, which would show up only as a missing shape after a
    # run that cost real money.
    intended = fleet.intended_shapes(fleet.FLEET)
    assert set(fleet.REQUIRED) <= intended


def test_every_spec_names_tools_that_exist():
    for spec in fleet.FLEET:
        for name in spec.tools:
            assert name in backends.TOOLS, f"{spec.id} wants unknown tool {name}"


def test_specs_cycle_and_are_deterministic():
    over = len(fleet.FLEET)
    assert fleet.specs(3) == fleet.FLEET[:3]
    assert fleet.specs(over + 2)[over:] == fleet.FLEET[:2]
    assert fleet.specs(5) == fleet.specs(5)


def test_a_fleet_needs_at_least_one_run():
    with pytest.raises(ValueError):
        fleet.specs(0)


# -- the tools, and the one that fails -------------------------------------


def test_the_new_tools_reach_nothing_and_invent_nothing():
    # Same rule as get_weather: a capture is evidence about an instrumentor,
    # so no clock, no network, nothing that would need redacting.
    for name in ("get_population", "convert_currency"):
        tool = backends.TOOLS[name]
        arguments = {"city": "Oslo", "amount": 100, "currency": "EUR", "into": "NOK"}
        assert tool.run(arguments) == tool.run(arguments)


def test_the_failing_tool_fails_the_same_way_every_time():
    with pytest.raises(backends.ToolFailure):
        backends.TOOLS["lookup_flight"].run({"flight": "BA117"})


def test_a_tool_failure_escapes_its_span_before_it_is_caught():
    # This is what makes the tracer mark the span ERROR and record the
    # exception. Catching inside the span would produce an OK span describing
    # a failure -- a trace that lies.
    tracer = StubTracer()
    call = backends.ToolCall("call_1", "lookup_flight", {"flight": "BA117"})
    result = backends._run_tool(tracer, call)

    assert tracer.spans[0].exited_with is backends.ToolFailure
    # ...and the model is still told what happened, so the run has a second turn.
    assert "error" in result


def test_a_successful_tool_leaves_its_span_clean():
    tracer = StubTracer()
    call = backends.ToolCall("call_1", "get_weather", {"city": "Paris"})
    result = backends._run_tool(tracer, call)

    assert tracer.spans[0].exited_with is None
    assert tracer.spans[0].attributes["output.mime_type"] == "application/json"
    assert result["city"] == "Paris"


# -- converse, driven against a stub backend -------------------------------


def a_stub_backend(script):
    """A Backend whose `request` replays a scripted list of (history, calls)."""
    seen = []

    def request(client, model, messages, tools, parallel=False):
        seen.append(
            SimpleNamespace(
                model=model, messages=list(messages), tools=tools, parallel=parallel
            )
        )
        return script[len(seen) - 1]

    backend = backends.Backend(
        id="stub",
        packages=("stub",),
        api_key_env="STUB_KEY",
        base_url_env=None,
        model_env="STUB_MODEL",
        default_model="stub-1",
        instrument=lambda provider: None,
        client=lambda base_url=None: SimpleNamespace(base_url=base_url),
        request=request,
        results=backends._openai_results,
    )
    return backend, seen


def test_converse_defaults_to_the_reference_conversation_unchanged():
    # 2.6's matched pair differs only in the instrumentor, so the default
    # prompt and inventory must not drift when the fleet varies them.
    call = backends.ToolCall("call_1", "get_weather", {"city": "Paris"})
    backend, seen = a_stub_backend([("assistant", [call]), ("assistant", [])])
    assert backends.converse(backend, "stub-1", StubTracer()) is True

    assert seen[0].messages[0]["content"] == backends.QUESTION
    assert tuple(tool.name for tool in seen[0].tools) == backends.DEFAULT_TOOLS
    # And it does not enable parallel tool calls. Sending that parameter
    # changes `llm.invocation_parameters`, so a reference capture taken with
    # it would differ from 2.6's GenAI capture by more than the instrumentor
    # and the matched pair would be matched on nothing.
    assert all(turn.parallel is False for turn in seen)


def test_converse_passes_a_specs_prompt_and_inventory_through():
    spec = next(s for s in fleet.FLEET if len(s.tools) > 1)
    backend, seen = a_stub_backend([("assistant", []), ("assistant", [])])
    backends.converse(backend, "stub-1", StubTracer(), spec.prompt, spec.tools)

    assert seen[0].messages[0]["content"] == spec.prompt
    assert tuple(tool.name for tool in seen[0].tools) == spec.tools


def test_a_turn_with_no_tool_call_ends_the_run_without_a_tool_span():
    tracer = StubTracer()
    backend, seen = a_stub_backend([("assistant", [])])
    assert backends.converse(backend, "stub-1", tracer, "hello", ("get_weather",)) is (
        False
    )
    assert [span.name for span in tracer.spans] == ["agent.run"]
    assert len(seen) == 1  # no second turn to make


def test_a_failing_tool_still_produces_a_second_turn():
    tracer = StubTracer()
    call = backends.ToolCall("call_9", "lookup_flight", {"flight": "BA117"})
    backend, seen = a_stub_backend([("assistant", [call]), ("assistant", [])])
    backends.converse(backend, "stub-1", tracer, "look it up", ("lookup_flight",))

    assert [span.name for span in tracer.spans] == ["agent.run", "tool.lookup_flight"]
    assert len(seen) == 2
    assert json.loads(seen[1].messages[-1]["content"])["error"]


def test_parallel_calls_produce_one_tool_span_each():
    tracer = StubTracer()
    calls = [
        backends.ToolCall("call_1", "get_weather", {"city": "Paris"}),
        backends.ToolCall("call_2", "get_population", {"city": "Paris"}),
    ]
    backend, _ = a_stub_backend([("assistant", calls), ("assistant", [])])
    backends.converse(
        backend, "stub-1", tracer, "both please", ("get_weather", "get_population")
    )
    assert [span.name for span in tracer.spans] == [
        "agent.run",
        "tool.get_weather",
        "tool.get_population",
    ]


# -- one trace per file ----------------------------------------------------


def test_the_exporter_can_be_drained_between_runs():
    # One trace is one graph (SPEC.md §7). Without draining, run 2's file
    # would contain run 1's spans and the fleet would not be a fleet.
    exporter = JsonlSpanExporter()
    exporter.export([an_llm_span()])
    assert len(exporter.records) == 1
    exporter.drain()
    assert exporter.records == []
    exporter.export([a_tool_span()])
    assert len(exporter.sorted_records()) == 1


class ScriptedExporter:
    """An exporter that hands back prepared traces, one per drained run."""

    def __init__(self, traces):
        self.traces = list(traces)
        self.current = []
        self.drains = 0

    def drain(self):
        self.drains += 1
        self.current = self.traces.pop(0) if self.traces else []

    def sorted_records(self):
        return self.current


def _fleet_over(traces, tmp_path, monkeypatch):
    monkeypatch.setattr(run, "FLEET_SCRATCH", tmp_path / "fleet")
    backend, _ = a_stub_backend([("assistant", [])] * (len(traces) * 2))
    return run._fleet(
        len(traces), backend, "stub-1", StubTracer(), ScriptedExporter(traces)
    )


def test_the_fleet_writes_one_file_per_run(tmp_path, monkeypatch):
    # One trace is one graph, so one trace is one file. A single file holding
    # eight runs would be a multi-trace input, which is a different question
    # (SPEC.md §7) and not the one 2.3 is asking.
    code = _fleet_over(a_complete_fleet(), tmp_path, monkeypatch)
    written = sorted(p.name for p in (tmp_path / "fleet").iterdir())
    assert len(written) == 4
    assert written[0].startswith("01_")
    assert all(name.endswith(".local.jsonl") for name in written)
    assert code == 0


def test_a_fleet_missing_a_required_shape_exits_non_zero(tmp_path, monkeypatch):
    # Deliberate: a partial fleet is a real problem to fix by re-running, and
    # an exit code is harder to skim past than a paragraph of output.
    dull = [records_of(an_llm_span(), a_tool_span()) for _ in range(3)]
    assert _fleet_over(dull, tmp_path, monkeypatch) == 1
    # The traces still exist -- the human re-runs, they do not edit these.
    assert len(list((tmp_path / "fleet").iterdir())) == 3


def test_each_fleet_file_is_one_trace_worth_of_jsonl(tmp_path, monkeypatch):
    _fleet_over(a_complete_fleet(), tmp_path, monkeypatch)
    for path in (tmp_path / "fleet").iterdir():
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines and all(json.loads(line)["span_id"] for line in lines)


# -- enabling parallel tool calls (fleet only) -----------------------------


class Rejected(Exception):
    """An endpoint refusing a parameter it does not implement."""

    status_code = 400


class StubClient:
    """A chat.completions client that records requests, and may refuse one."""

    def __init__(self, reject_parallel=False):
        self.requests = []

        def create(**request):
            self.requests.append(request)
            if reject_parallel and "parallel_tool_calls" in request:
                raise Rejected("unknown parameter")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))]
            )

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def test_the_openai_backend_asks_the_api_to_permit_parallel_calls():
    # Enabling a capability, not steering toward an outcome. Before this the
    # spans recorded llm.invocation_parameters as {"model": ...} alone, so
    # "the model does not make parallel calls" was a claim about a question
    # nobody had asked.
    client = StubClient()
    backends._openai_request(
        client, "m", [], (backends.TOOLS["get_weather"],), parallel=True
    )
    assert client.requests[0]["parallel_tool_calls"] is True


def test_it_is_not_sent_unless_asked_for():
    client = StubClient()
    backends._openai_request(client, "m", [], (backends.TOOLS["get_weather"],))
    assert "parallel_tool_calls" not in client.requests[0]


def test_an_endpoint_that_rejects_the_parameter_does_not_lose_the_run(capsys):
    # An OpenAI-compatible endpoint is not the OpenAI API. A fleet is a
    # credentialed run with a budget of attempts; losing all of it to one
    # unsupported keyword would be expensive.
    client = StubClient(reject_parallel=True)
    backends._openai_request(
        client, "m", [], (backends.TOOLS["get_weather"],), parallel=True
    )
    assert len(client.requests) == 2
    assert "parallel_tool_calls" not in client.requests[1]
    # Reported, never silent: the next fleet's parallel calls, if any, are
    # then the model's own doing and the provenance of the claim differs.
    assert "rejected parallel_tool_calls" in capsys.readouterr().err


def test_a_failure_that_is_not_a_rejected_parameter_is_not_retried():
    class Broken(Exception):
        status_code = 500

    client = StubClient()

    def explode(**request):
        client.requests.append(request)
        raise Broken("upstream")

    client.chat.completions.create = explode
    with pytest.raises(Broken):
        backends._openai_request(
            client, "m", [], (backends.TOOLS["get_weather"],), parallel=True
        )
    assert len(client.requests) == 1


def test_the_fleet_enables_it_and_the_reference_run_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "FLEET_SCRATCH", tmp_path / "fleet")
    backend, seen = a_stub_backend([("assistant", [])] * 8)
    run._fleet(2, backend, "stub-1", StubTracer(), ScriptedExporter(a_complete_fleet()))
    assert seen and all(turn.parallel is True for turn in seen)

    other, reference = a_stub_backend([("assistant", [])])
    backends.converse(other, "stub-1", StubTracer())
    assert all(turn.parallel is False for turn in reference)


def test_the_anthropic_backend_accepts_the_flag_and_sends_nothing_extra():
    # Anthropic permits parallel tool use by default, so there is no
    # capability to enable -- and a tool_choice sent anyway would change
    # llm.invocation_parameters for no gain.
    sent = {}

    def create(**request):
        sent.update(request)
        return SimpleNamespace(content=[])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    backends._anthropic_request(
        client, "m", [], (backends.TOOLS["get_weather"],), parallel=True
    )
    assert "tool_choice" not in sent


# -- a fleet that spans models (TASKS.md 2.2) ------------------------------


def test_the_fleet_names_at_most_two_models_beyond_the_default():
    # The bound is the line between changing the setup and selecting an
    # answer. Adding a third model to chase a shape is selection, and this is
    # what says so before the temptation arrives rather than after.
    assert len(fleet.extra_models()) <= fleet.MAX_EXTRA_MODELS


def test_only_the_parallel_aimed_specs_name_another_model():
    # Varying the model is for the one shape the default model would not
    # produce. Varying it everywhere would make every other finding harder to
    # attribute for no gain.
    for spec in fleet.FLEET:
        if spec.model:
            assert fleet.PARALLEL_TOOL_CALLS in spec.intends


def test_a_model_on_another_endpoint_says_which_variable_holds_it():
    for spec in fleet.FLEET:
        if spec.model == fleet.KIMI:
            assert spec.endpoint_env == fleet.KIMI_ENDPOINT


def test_specs_beyond_the_requested_count_are_named_not_silently_dropped():
    # The multi-model specs sit at the end, so a habitual --fleet 8 skips
    # every one of them. A silent cap reads as "we covered everything".
    assert fleet.unreached(len(fleet.FLEET)) == ()
    assert "two_cities_qwen" in fleet.unreached(8)


def test_every_fleet_trace_records_which_model_produced_it(tmp_path, monkeypatch):
    # A fleet that mixes models without saying which is worse than a
    # single-model fleet: every finding it produces is unattributable.
    monkeypatch.setattr(run, "FLEET_SCRATCH", tmp_path / "fleet")
    tracer = StubTracer()
    backend, _ = a_stub_backend([("assistant", [])] * 8)
    run._fleet(2, backend, "stub-1", tracer, ScriptedExporter(a_complete_fleet()))

    agents = [span for span in tracer.spans if span.name == "agent.run"]
    assert agents
    for span in agents:
        assert json.loads(span.attributes["metadata"])["model"] == "stub-1"
    # ...and in the filename too, so it is legible without parsing anything.
    assert all("__stub-1" in p.name for p in (tmp_path / "fleet").iterdir())


def test_the_reference_capture_is_not_stamped(tmp_path):
    # 2.6's matched pair differs only in the instrumentor. An extra metadata
    # attribute on the agent span would be one more difference.
    tracer = StubTracer()
    backend, _ = a_stub_backend([("assistant", [])])
    backends.converse(backend, "stub-1", tracer)
    assert "metadata" not in tracer.spans[0].attributes


def test_a_run_whose_endpoint_is_unset_is_skipped_not_misrouted(
    tmp_path, monkeypatch, capsys
):
    # Sending a model to the wrong endpoint produces a trace whose provenance
    # is wrong, which is worse than a trace you do not have (SPEC.md §6.1's
    # posture, applied to the harness).
    monkeypatch.setattr(run, "FLEET_SCRATCH", tmp_path / "fleet")
    monkeypatch.delenv(fleet.KIMI_ENDPOINT, raising=False)
    kimi = next(s for s in fleet.FLEET if s.endpoint_env == fleet.KIMI_ENDPOINT)
    monkeypatch.setattr(fleet, "FLEET", (fleet.FLEET[0], kimi))

    backend, seen = a_stub_backend([("assistant", [])] * 4)
    code = run._fleet(
        2,
        backend,
        "stub-1",
        StubTracer(),
        ScriptedExporter([records_of(an_llm_span(), a_tool_span())]),
    )

    # One trace written, and the skipped run made no request at all.
    assert len(list((tmp_path / "fleet").iterdir())) == 1
    assert all(turn.model != fleet.KIMI for turn in seen)
    assert code == 1  # the fleet is short of required shapes, and says so
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert fleet.KIMI_ENDPOINT in out


def a_recording_backend(script):
    """A stub backend that also records the base_url its client was built with."""
    backend, seen = a_stub_backend(script)
    urls = []

    def client(base_url=None):
        urls.append(base_url)
        return SimpleNamespace(base_url=base_url)

    return replace(backend, client=client), seen, urls


def test_a_named_endpoint_reaches_the_client(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "FLEET_SCRATCH", tmp_path / "fleet")
    monkeypatch.setenv(fleet.KIMI_ENDPOINT, "https://example.invalid/v1/")
    kimi = next(s for s in fleet.FLEET if s.endpoint_env == fleet.KIMI_ENDPOINT)
    monkeypatch.setattr(fleet, "FLEET", (kimi,))

    backend, seen, urls = a_recording_backend([("assistant", [])] * 2)
    run._fleet(
        1,
        backend,
        "stub-1",
        StubTracer(),
        ScriptedExporter([records_of(an_llm_span(), a_tool_span())]),
    )
    assert urls == ["https://example.invalid/v1/"]
    # ...and the run used the spec's model, not the configured default.
    assert seen[0].model == fleet.KIMI
