"""The model backends the capture harness can drive, and the run it drives.

Three backends, deliberately kept side by side:

* **anthropic** — the Anthropic SDK, instrumented by
  ``openinference-instrumentation-anthropic``.
* **openai** — the OpenAI SDK, instrumented by
  ``openinference-instrumentation-openai``, pointed at any OpenAI-compatible
  endpoint through ``base_url``.
* **genai** — the *same* SDK, the *same* endpoint and the *same* model as
  ``openai``, instrumented instead by ``opentelemetry-instrumentation-genai-openai``
  so the spans speak **OTel GenAI** rather than OpenInference (`TASKS.md` 2.5).

The first two exist for the same reason the library has adapters: two
independent instrumentors emitting the same semantic conventions is the only
way to find out whether "OpenInference" means one thing or two. A capture from
one proves that one instrumentor's output parses. A capture from each proves
rather more.

**``genai`` exists for the opposite reason.** It is deliberately identical to
``openai`` in every respect except the instrumentor, so that the two traces are
a **matched pair**: same SDK, same endpoint, same model, same prompt, same tool
inventory, same conversation. The cross-dialect equivalence test (`FIXTURES.md`
§4) claims that two dialects of one scenario produce one canonical graph. A pair
that differed by more than the instrumentor could not attribute a failure of
that claim to the dialect, and the comparison would be worth nothing. Every
default below that looks redundant with ``openai`` is redundant on purpose.

**The instrumentor patches the SDK client, not the endpoint.** It wraps
``openai.OpenAI``'s methods, so it emits identical spans whichever
OpenAI-compatible service ``base_url`` points at. What a fixture captured this
way demonstrates is therefore *the OpenAI instrumentor*, not the provider
behind it -- and the provenance file has to say so, because "captured against
a real model" and "captured against OpenAI" are different claims.

The **fleet** (``TASKS.md`` 2.2) drives the same backend and the same model
repeatedly with different prompts and different tool inventories, so that the
runs differ *as runs*. What varies is steered through the prompt and the stub
tools and nothing else: a shape manufactured by editing an exported span
afterwards would make the fleet synthetic again while looking real, which is
the failure the whole capture harness exists to avoid.

Nothing here is imported by ``spanweave``. Network, SDKs and API keys live in
this directory and only here (``ENVIRONMENT.md``).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, NamedTuple

# OpenInference semantic conventions, written out because this file is one of
# the two places allowed to know a dialect -- and unlike the adapter, this one
# is *emitting* rather than reading.
SPAN_KIND = "openinference.span.kind"
TOOL_NAME = "tool.name"
TOOL_CALL_ID = "tool_call.id"
INPUT_VALUE = "input.value"
INPUT_MIME = "input.mime_type"
OUTPUT_VALUE = "output.value"
OUTPUT_MIME = "output.mime_type"
METADATA = "metadata"
JSON_MIME = "application/json"
TEXT_MIME = "text/plain"

# OTel GenAI semantic conventions, for the same reason and with one difference
# worth stating: these attribute names are, as of the versions pinned in
# `capture/README.md`, marked *"Deprecated: moved to the OpenTelemetry GenAI
# semantic conventions repository"* in `opentelemetry-semantic-conventions`.
# The names are unchanged; the conventions moved house. They are written out
# here rather than imported so that the harness has no dependency on which
# house they are currently in -- and so that a future rename is a visible diff
# in this file rather than a silent change of behaviour underneath it.
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_TYPE = "gen_ai.tool.type"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"
INVOKE_AGENT = "invoke_agent"
EXECUTE_TOOL = "execute_tool"

#: Where the fleet's model/spec stamp goes on a GenAI trace. **Not** a
#: ``gen_ai.*`` key, and deliberately not: GenAI defines no free-form metadata
#: attribute, and minting a plausible-looking ``gen_ai.`` name for one would
#: put a key in the file that the conventions do not define while looking as
#: though they did. An adapter will report it as unmapped, which is the honest
#: outcome (`SPEC.md` §3.7).
CAPTURE_NOTE = "spanweave.capture.note"

#: The two attributes that decide whether a GenAI capture is worth anything.
#: Without content capture there are no messages, so no tool-call ids, so no
#: ``call_result`` edge and no §4.2.1 declaration -- the two relations the
#: second dialect exists to test (`TASKS.md` 2.5).
GEN_AI_MESSAGE_KEYS = (GEN_AI_INPUT_MESSAGES, GEN_AI_OUTPUT_MESSAGES)

#: Content capture is **opt-in**, and the harness sets it explicitly rather
#: than hoping for an ambient default. ``span_only`` because the harness
#: exports spans: the ``event_only`` mode puts the messages in log records,
#: which never reach the JSONL and would produce a trace that looks captured
#: and carries nothing.
CONTENT_CAPTURE_ENV = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
CONTENT_CAPTURE_MODE = "span_only"

#: The modes that actually put message content on a **span**. ``true`` is not
#: one of them -- it is not a valid value at all on this path, and setting it
#: is accepted with a warning on stderr and silently downgraded to
#: ``NO_CONTENT``. That is precisely why `enable` below re-reads the resolved
#: mode instead of trusting that the assignment worked.
CONTENT_ON_SPANS = ("SPAN_ONLY", "SPAN_AND_EVENT")


class CaptureError(Exception):
    """Something the human has to fix before a capture can run."""


QUESTION = "What is the weather in Paris? Use the tool."

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "City name"}},
    "required": ["city"],
    "additionalProperties": False,
}

CITY_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "City name"}},
    "required": ["city"],
    "additionalProperties": False,
}

MONEY_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": {"type": "number", "description": "How much to convert"},
        "currency": {"type": "string", "description": "Three-letter code, e.g. EUR"},
        "into": {"type": "string", "description": "Three-letter code, e.g. NOK"},
    },
    "required": ["amount", "currency", "into"],
    "additionalProperties": False,
}

FLIGHT_SCHEMA = {
    "type": "object",
    "properties": {"flight": {"type": "string", "description": "Flight number"}},
    "required": ["flight"],
    "additionalProperties": False,
}


class ToolFailure(Exception):
    """A tool that fails on purpose, so a fleet contains a failing tool span.

    Raised, not returned: the exception has to escape the tool's span for the
    tracer to mark that span ERROR the way a real failure would. Catching it
    inside and returning a tidy error object would produce an OK span
    describing a failure, which is a trace that lies.
    """


def get_weather(arguments: dict[str, Any]) -> dict[str, Any]:
    """The tool. Local, pure, and boring on purpose.

    A capture is evidence about an **instrumentor**, so the tool must not add
    anything of its own -- no network, no clock, nothing that would have to be
    redacted or explained in the provenance file. Every tool below keeps that
    rule, including the one that fails.
    """
    return {"city": arguments.get("city"), "celsius": 18, "summary": "clear"}


def get_population(arguments: dict[str, Any]) -> dict[str, Any]:
    """A second tool, so per-tool rollup in a consumer has something to roll up."""
    table = {"paris": 2_100_000, "oslo": 700_000, "lisbon": 545_000}
    city = str(arguments.get("city", ""))
    return {"city": arguments.get("city"), "people": table.get(city.lower())}


def convert_currency(arguments: dict[str, Any]) -> dict[str, Any]:
    """A third tool, with a fixed rate table -- no clock, no market, no network."""
    rates = {("EUR", "NOK"): 11.5, ("USD", "EUR"): 0.92, ("EUR", "USD"): 1.09}
    currency = str(arguments.get("currency", "")).upper()
    into = str(arguments.get("into", "")).upper()
    rate = rates.get((currency, into))
    amount = arguments.get("amount")
    converted = None
    if rate is not None and isinstance(amount, (int, float)):
        converted = round(amount * rate, 2)
    return {"amount": amount, "from": currency, "into": into, "converted": converted}


def lookup_flight(arguments: dict[str, Any]) -> dict[str, Any]:
    """The tool that fails, every time, deterministically.

    A fleet with no failures exercises only the half of the model where
    everything worked, and `Status` and the error-side diagnostics would never
    be populated by anything real.
    """
    raise ToolFailure(f"no such flight: {arguments.get('flight')!r}")


@dataclass(frozen=True)
class Tool:
    """One stub tool: what the model is told about it, and what it does."""

    name: str
    description: str
    schema: dict[str, Any]
    run: Any = field(repr=False)


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "get_weather",
            "Get the current weather for a city.",
            WEATHER_SCHEMA,
            get_weather,
        ),
        Tool(
            "get_population",
            "Get the population of a city.",
            CITY_SCHEMA,
            get_population,
        ),
        Tool(
            "convert_currency",
            "Convert an amount between two currencies.",
            MONEY_SCHEMA,
            convert_currency,
        ),
        Tool(
            "lookup_flight",
            "Look up the status of a flight by number.",
            FLIGHT_SCHEMA,
            lookup_flight,
        ),
    )
}

#: The single capture's inventory. Unchanged, deliberately: the matched pair
#: 2.6 needs differs only in the instrumentor, so the reference conversation
#: must not drift (`TASKS.md` 2.5).
DEFAULT_TOOLS: tuple[str, ...] = ("get_weather",)


class ToolCall(NamedTuple):
    """One requested call, in whichever shape the SDK reported it."""

    id: str
    name: str
    arguments: dict[str, Any]


# --------------------------------------------------------------------------
# The spans the harness emits itself, and the dialect they speak
# --------------------------------------------------------------------------
#
# Only the `llm` spans come from an instrumentor. The `agent` and `tool` spans
# are emitted here, because executing a tool is not an SDK call and there is
# nothing for an instrumentor to wrap (Phase 1 review).
#
# Which means they have to speak the SAME dialect as the instrumentor that
# produced the rest of the file. Emitting OpenInference keys beside GenAI ones
# would produce a mixed-dialect trace that no adapter honestly reads: detection
# would see both, one adapter would win, and whichever lost would take its
# spans' meaning with it. So the emitted keys are a property of the backend,
# selected alongside the instrumentor and never independently of it.


def agent_span_attributes(
    prompt: str, note: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The `agent.run` span, in OpenInference."""
    attributes: dict[str, Any] = {
        SPAN_KIND: "AGENT",
        INPUT_VALUE: prompt,
        INPUT_MIME: TEXT_MIME,
    }
    if note:
        attributes[METADATA] = json.dumps(note, sort_keys=True)
    return attributes


def tool_span_attributes(call: ToolCall) -> dict[str, Any]:
    """The attributes a tool span needs for the adapter to pair it.

    ``tool_call.id`` is the whole point: it is what lets the builder join this
    span to the LLM span that requested it. Without it the capture would show
    a tool that ran and nothing connecting it to the call -- and the library
    would be right to refuse to guess.
    """
    return {
        SPAN_KIND: "TOOL",
        TOOL_NAME: call.name,
        TOOL_CALL_ID: call.id,
        INPUT_VALUE: json.dumps(call.arguments),
        INPUT_MIME: JSON_MIME,
    }


def tool_result_attributes(payload: Any) -> dict[str, Any]:
    """What a *successful* tool span records on the way out, in OpenInference."""
    return {OUTPUT_VALUE: json.dumps(payload), OUTPUT_MIME: JSON_MIME}


def _genai_message(role: str, parts: list[dict[str, Any]]) -> str:
    """One `gen_ai.*.messages` value, encoded the way the instrumentor encodes it.

    Matching the instrumentor's encoding is not cosmetic. These attributes sit
    on the harness's spans beside the instrumentor's, and an adapter reading
    the file should not have to know which of the two wrote a given line.
    """
    return json.dumps([{"role": role, "parts": parts}], separators=(",", ":"))


def genai_agent_span_attributes(
    prompt: str, note: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The `agent.run` span, in OTel GenAI.

    GenAI names this operation: ``invoke_agent``. Unlike the tool span below
    the *attributes* are a judgement call -- the conventions describe an agent
    invocation but the harness is not an agent framework -- so it carries the
    operation, a name, and the prompt in the same message encoding the
    instrumentor uses for the LLM spans, and nothing else.
    """
    attributes: dict[str, Any] = {
        GEN_AI_OPERATION: INVOKE_AGENT,
        GEN_AI_AGENT_NAME: "agent.run",
        GEN_AI_INPUT_MESSAGES: _genai_message(
            "user", [{"content": prompt, "type": "text"}]
        ),
    }
    if note:
        attributes[CAPTURE_NOTE] = json.dumps(note, sort_keys=True)
    return attributes


def genai_tool_span_attributes(call: ToolCall) -> dict[str, Any]:
    """The `execute_tool` span, in OTel GenAI.

    **GenAI defines this span; OpenInference does not.** ``execute_tool`` is a
    named operation in the conventions, with ``gen_ai.tool.name`` and
    ``gen_ai.tool.call.id`` on it. So on this side of the pair the tool span is
    *convention-defined* even though it is still the harness that emits it --
    which is a real difference between the two traces, and one the provenance
    file has to state rather than let a reader infer symmetry that is not there.

    ``gen_ai.tool.call.id`` does the same job ``tool_call.id`` does on the
    OpenInference side: it is what lets the builder join this span to the LLM
    span that requested it.
    """
    return {
        GEN_AI_OPERATION: EXECUTE_TOOL,
        GEN_AI_TOOL_NAME: call.name,
        GEN_AI_TOOL_TYPE: "function",
        GEN_AI_TOOL_CALL_ID: call.id,
        GEN_AI_TOOL_CALL_ARGUMENTS: json.dumps(call.arguments),
    }


def genai_tool_result_attributes(payload: Any) -> dict[str, Any]:
    """What a *successful* `execute_tool` span records on the way out."""
    return {GEN_AI_TOOL_CALL_RESULT: json.dumps(payload)}


class Check(NamedTuple):
    """One line of a verification checklist: what was asked, and the answer.

    ``detail`` carries what the answer was read off, so a human confirming the
    claim against the file knows where to look rather than being asked to take
    a tick on trust.
    """

    question: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class SpanDialect:
    """How the harness writes its **own** spans, for one backend.

    Not an abstraction for its own sake: it is the seam that keeps a trace
    single-dialect. Add an instrumentor and you must answer, here, what the
    agent and tool spans it never emits should say.
    """

    id: str
    #: The key prefix that identifies this dialect in an exported record. Used
    #: by the tests that assert a capture is not a mixture of two.
    prefix: str
    agent_span_name: str
    agent: Any = field(repr=False)
    tool_span_name: Any = field(repr=False)
    tool: Any = field(repr=False)
    tool_result: Any = field(repr=False)
    #: One sentence for the provenance file, about the spans the harness emits.
    provenance_note: str = ""


OPENINFERENCE = SpanDialect(
    id="openinference",
    prefix="openinference.",
    agent_span_name="agent.run",
    agent=agent_span_attributes,
    tool_span_name=lambda call: f"tool.{call.name}",
    tool=tool_span_attributes,
    tool_result=tool_result_attributes,
    provenance_note=(
        "OpenInference defines no tool-execution span, so `agent.run` and the "
        "tool span are this harness's own convention, not the dialect's."
    ),
)

GENAI_DIALECT = SpanDialect(
    id="otel_genai",
    prefix="gen_ai.",
    agent_span_name=f"{INVOKE_AGENT} agent.run",
    agent=genai_agent_span_attributes,
    tool_span_name=lambda call: f"{EXECUTE_TOOL} {call.name}",
    tool=genai_tool_span_attributes,
    tool_result=genai_tool_result_attributes,
    provenance_note=(
        "GenAI DOES define a tool-execution span (`execute_tool`), so unlike "
        "the OpenInference trace the tool span here is convention-defined -- "
        "still emitted by this harness, but named and shaped by the "
        "conventions rather than by us. The `invoke_agent` span's attributes "
        "remain a judgement call."
    ),
)


@dataclass(frozen=True)
class Backend:
    """What the harness needs to know to drive one SDK."""

    id: str
    #: What to install. Printed when an import fails, so it must be exact.
    packages: tuple[str, ...]
    #: The credential that decides whether this backend is configured at all.
    api_key_env: str
    #: Where the model runs. `None` for a backend with a fixed endpoint.
    base_url_env: str | None
    model_env: str
    default_model: str
    note: str = ""
    # The four things a backend has to be able to do. Plain functions held in
    # fields, not methods: each backend is data plus four callables, and there
    # is nothing to subclass.
    instrument: Any = field(default=None, repr=False)
    client: Any = field(default=None, repr=False)
    request: Any = field(default=None, repr=False)
    results: Any = field(default=None, repr=False)
    #: What the harness's OWN spans say. Defaults to OpenInference, which is
    #: what the two Phase 1 backends emit and must keep emitting unchanged.
    dialect: SpanDialect = OPENINFERENCE
    #: Optional. `(environ) -> tuple[str, ...]` of notices, run before
    #: instrumenting; raises `CaptureError` if a required option did not take.
    enable: Any = field(default=None, repr=False)
    #: Optional. `(records) -> tuple[str, ...]` of reasons this trace is not
    #: worth writing at all.
    require: Any = field(default=None, repr=False)
    #: Optional. `(records) -> tuple[Check, ...]`, printed after the trace is
    #: written and answered against the file the human is about to read.
    checklist: Any = field(default=None, repr=False)

    def configured(self, environ: dict[str, str]) -> bool:
        return bool(environ.get(self.api_key_env))

    def model(self, environ: dict[str, str], explicit: str | None = None) -> str:
        """`--model` beats the env beats the default. Stated, so it is checkable."""
        return (
            explicit
            or environ.get("SPANWEAVE_CAPTURE_MODEL")
            or environ.get(self.model_env)
            or self.default_model
        )


# --------------------------------------------------------------------------
# anthropic
# --------------------------------------------------------------------------


def _anthropic_instrument(provider: Any) -> None:
    from openinference.instrumentation.anthropic import AnthropicInstrumentor

    AnthropicInstrumentor().instrument(tracer_provider=provider)


def _anthropic_client(base_url: str | None = None) -> Any:
    import anthropic

    # Accepted for one signature across backends; Anthropic's endpoint is
    # fixed, so there is nothing to override.
    del base_url
    return anthropic.Anthropic()


def _anthropic_tool(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.schema,
    }


def _anthropic_request(
    client: Any,
    model: str,
    messages: list[Any],
    tools: tuple[Tool, ...],
    parallel: bool = False,
) -> tuple[Any, list[ToolCall]]:
    # `parallel` is accepted and deliberately not acted on. Anthropic permits
    # parallel tool use by default (`tool_choice.disable_parallel_tool_use`
    # defaults false), so there is no capability to enable here -- and sending
    # a `tool_choice` anyway would change what the instrumentor records in
    # `llm.invocation_parameters` for no gain.
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        tools=[_anthropic_tool(tool) for tool in tools],
        messages=messages,
    )
    # The whole content, not just the text: thinking blocks must be echoed
    # back unchanged on the same model.
    history = {"role": "assistant", "content": response.content}
    calls = [
        ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
        for block in response.content
        if block.type == "tool_use"
    ]
    return history, calls


def _anthropic_results(calls: list[ToolCall], payloads: list[Any]) -> list[Any]:
    # Every tool_result in ONE user message: splitting them teaches the model
    # to stop making parallel calls.
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload),
                }
                for call, payload in zip(calls, payloads, strict=True)
            ],
        }
    ]


# --------------------------------------------------------------------------
# openai (any OpenAI-compatible endpoint)
# --------------------------------------------------------------------------


def _openai_instrument(provider: Any) -> None:
    from openinference.instrumentation.openai import OpenAIInstrumentor

    OpenAIInstrumentor().instrument(tracer_provider=provider)


def _openai_client(base_url: str | None = None) -> Any:
    import openai

    # base_url is what makes this backend point anywhere. The instrumentor
    # neither knows nor cares -- it patches this client object. The override
    # exists because a fleet may span models that live on different regional
    # endpoints (`fleet.py`); the default is unchanged.
    return openai.OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url=base_url or os.environ.get("NEBIUS_BASE_URL"),
    )


def _openai_tool(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.schema,
        },
    }


def _openai_request(
    client: Any,
    model: str,
    messages: list[Any],
    tools: tuple[Tool, ...],
    parallel: bool = False,
) -> tuple[Any, list[ToolCall]]:
    # chat.completions rather than responses: it is the surface every
    # OpenAI-compatible provider implements, and a capture that only works
    # against one provider is not the evidence this harness is for.
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [_openai_tool(tool) for tool in tools],
    }
    if parallel:
        # ENABLING a capability, not steering toward an outcome -- which is
        # why this is allowed here at all (`capture/fleet.py`). The fleet
        # needs runs where the model requested several calls at once, and
        # until this is sent there is no evidence about whether the API was
        # ever asked to permit that: the first fleet produced no parallel
        # call, but its spans recorded `llm.invocation_parameters` as
        # `{"model": ...}` alone -- so the question had not been put. Sending
        # it turns "the model would not" into a claim that can be made.
        #
        # It may still change nothing. vLLM-served endpoints -- which is what
        # `openai/gpt-oss-120b` is behind Nebius -- do not reliably honour
        # this parameter, and a model that prefers sequential calls will make
        # them anyway. That is a finding, and it is a *different* finding from
        # "we never asked".
        request["parallel_tool_calls"] = True
    response = _create(client, request)
    message = response.choices[0].message
    calls = [
        ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=json.loads(call.function.arguments or "{}"),
        )
        for call in (message.tool_calls or [])
    ]
    return message, calls


def _create(client: Any, request: dict[str, Any]) -> Any:
    """One chat.completions call, surviving an endpoint that rejects a param.

    An OpenAI-compatible endpoint is not the OpenAI API, and some reject a
    parameter they do not implement with a 400 rather than ignoring it. A
    fleet is a credentialed run with a budget of attempts, so losing all of it
    to one unsupported keyword would be expensive.

    The retry is **reported, never silent**, and it drops only the parameter
    that is optional by construction. Detection is on the status *code*, not
    on message text -- the same rule the library applies to its own errors
    (`SPEC.md` §3.10), because a message is not a matching surface.
    """
    try:
        return client.chat.completions.create(**request)
    except Exception as failure:
        rejected = getattr(failure, "status_code", None) == 400
        if not (rejected and "parallel_tool_calls" in request):
            raise
        print(
            "capture: the endpoint rejected parallel_tool_calls (400); retrying "
            "without it. Any parallel calls are then the model's own doing.",
            file=sys.stderr,
        )
        without = {k: v for k, v in request.items() if k != "parallel_tool_calls"}
        return client.chat.completions.create(**without)


def _openai_results(calls: list[ToolCall], payloads: list[Any]) -> list[Any]:
    # One message per call here, unlike Anthropic's single user message. The
    # SDKs genuinely disagree about this, which is a small reminder of why the
    # library has adapters at all.
    return [
        {"role": "tool", "tool_call_id": call.id, "content": json.dumps(payload)}
        for call, payload in zip(calls, payloads, strict=True)
    ]


# --------------------------------------------------------------------------
# genai (the same SDK and endpoint, a different instrumentor)
# --------------------------------------------------------------------------
#
# WHICH PACKAGE. `opentelemetry-instrumentation-openai-v2`, in
# `opentelemetry-python-contrib`, was the first OTel-official OpenAI
# instrumentation; the work has since moved to
# `opentelemetry-instrumentation-genai-openai` in the newer
# `open-telemetry/opentelemetry-python-genai` repository. Both still publish to
# PyPI, so "which one" is not answerable from the names.
#
# It was settled by installing both and running them, not by reading. Against
# `openai` 3.3.1, `opentelemetry-instrumentation-openai-v2` 2.4b0 **does not
# import at all**: it does `from httpx import URL`, and `openai` 3.x depends on
# `httpx2` rather than `httpx`, so the module is simply absent unless something
# else dragged it in. That is a hard blocker, not a preference. Install `httpx`
# alongside and it works, and then emits the same message attributes as the new
# package (both delegate to `opentelemetry-util-genai`) minus `server.address`,
# `server.port` and `gen_ai.tool.definitions`.
#
# So: the newer package, and the disagreement recorded rather than tidied away.
# `capture/README.md` carries the full comparison, and the harness prints the
# exact installed version into the provenance template so the fixture names
# what actually ran (`TASKS.md` 2.5).


def _genai_enable(environ: Any) -> tuple[str, ...]:
    """Turn message-content capture on, then check that it took.

    **This is the difference between a useful capture and a useless one.**
    Content capture is opt-in. Without it there is no `gen_ai.input.messages`
    and no `gen_ai.output.messages`, which means no payloads and no tool-call
    ids -- so no `call_result` edge and no `SPEC.md` §4.2.1 declaration, which
    are the two relations the second dialect exists to test.

    The re-read is not defensive habit. Setting the variable to ``true`` is
    what the older package's own documentation tells you to do, and on this
    path it is not a valid value: it is rejected with a line on stderr and
    **silently downgraded to NO_CONTENT**. A run that trusted the assignment
    would spend a credential and produce a trace with no messages in it. So the
    value is set, and then the resolved mode is read back from the library that
    will act on it.
    """
    notices = []
    previous = environ.get(CONTENT_CAPTURE_ENV)
    if previous is not None and previous != CONTENT_CAPTURE_MODE:
        notices.append(
            f"{CONTENT_CAPTURE_ENV} was {previous!r}; overriding with "
            f"{CONTENT_CAPTURE_MODE!r}. This harness exports spans, and any "
            f"other mode puts the messages somewhere the JSONL never sees."
        )
    environ[CONTENT_CAPTURE_ENV] = CONTENT_CAPTURE_MODE

    from opentelemetry.util.genai.utils import get_content_capturing_mode

    mode = get_content_capturing_mode()
    if mode.name not in CONTENT_ON_SPANS:
        raise CaptureError(
            f"content capture did not take: {CONTENT_CAPTURE_ENV} is set to "
            f"{CONTENT_CAPTURE_MODE!r} but the instrumentation resolved it to "
            f"{mode.name}. Without message content the trace has no payloads "
            f"and no tool-call ids, so it cannot show call/result pairing or "
            f"the SPEC.md 4.2.1 declaration -- which is the whole reason for "
            f"this capture. Refusing to spend a model call on it."
        )
    notices.append(f"message content capture: {CONTENT_CAPTURE_ENV}={mode.name}")
    return tuple(notices)


def _genai_instrument(provider: Any) -> None:
    from opentelemetry.instrumentation.genai.openai import OpenAIInstrumentor

    OpenAIInstrumentor().instrument(tracer_provider=provider)


def _messages_in(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every exported record carrying either message attribute."""
    return [
        record
        for record in records
        if any(key in record["attributes"] for key in GEN_AI_MESSAGE_KEYS)
    ]


def _genai_require(records: list[dict[str, Any]]) -> tuple[str, ...]:
    """Refuse to write a trace with no message content in it at all."""
    if _messages_in(records):
        return ()
    return (
        "not one exported span carries "
        + " or ".join(GEN_AI_MESSAGE_KEYS)
        + ". Content capture was requested and verified before the run, so "
        "either the instrumentor did not attach or it changed behaviour. "
        "The trace would contain no payloads, no tool-call ids, no pairing "
        "and no data declaration -- nothing this capture exists to show.",
    )


def _parts(value: Any) -> list[dict[str, Any]]:
    """Every message part in a `gen_ai.*.messages` value, flattened.

    Tolerant on purpose: this reads back what an instrumentor wrote, and a
    checklist that crashed on an unexpected shape would be worse than one that
    reports nothing found. Reporting nothing found is itself the answer the
    human needs.
    """
    try:
        messages = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(messages, list):
        return []
    parts = []
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("parts"), list):
            parts.extend(part for part in message["parts"] if isinstance(part, dict))
    return parts


def _ids_of(records: list[dict[str, Any]], key: str, part_type: str) -> set[str]:
    found = set()
    for record in records:
        for part in _parts(record["attributes"].get(key)):
            if part.get("type") == part_type and isinstance(part.get("id"), str):
                found.add(part["id"])
    return found


def _genai_checklist(records: list[dict[str, Any]]) -> tuple[Check, ...]:
    """`TASKS.md` 2.6's three verifications, answered against the exported records.

    The harness answers them so the human is checking a claim rather than
    hunting through JSON, and the human still confirms them against the file:
    a checklist that both produces the trace and certifies it is not evidence
    (`capture/README.md`).
    """
    requested = _ids_of(records, GEN_AI_OUTPUT_MESSAGES, "tool_call")
    fulfilled = {
        record["attributes"][GEN_AI_TOOL_CALL_ID]
        for record in records
        if isinstance(record["attributes"].get(GEN_AI_TOOL_CALL_ID), str)
    }
    declared = _ids_of(records, GEN_AI_INPUT_MESSAGES, "tool_call_response")
    with_messages = _messages_in(records)

    return (
        Check(
            "content capture really was on",
            bool(with_messages),
            f"{len(with_messages)} of {len(records)} spans carry "
            f"{' / '.join(GEN_AI_MESSAGE_KEYS)}",
        ),
        Check(
            "tool-call ids on the requesting AND the fulfilling span",
            bool(requested and requested & fulfilled),
            f"requested {sorted(requested)}; fulfilled {sorted(fulfilled)}; "
            f"both {sorted(requested & fulfilled)}",
        ),
        Check(
            "the follow-up turn declares the tool result with the same id "
            "(SPEC.md 4.2.1)",
            bool(declared and declared & requested),
            f"declared {sorted(declared)}; matching a requested id "
            f"{sorted(declared & requested)}",
        ),
    )


ANTHROPIC = Backend(
    id="anthropic",
    packages=("anthropic", "openinference-instrumentation-anthropic"),
    api_key_env="ANTHROPIC_API_KEY",
    base_url_env=None,
    model_env="ANTHROPIC_MODEL",
    default_model="claude-opus-5",
    instrument=_anthropic_instrument,
    client=_anthropic_client,
    request=_anthropic_request,
    results=_anthropic_results,
)

OPENAI = Backend(
    id="openai",
    packages=("openai", "openinference-instrumentation-openai"),
    api_key_env="NEBIUS_API_KEY",
    base_url_env="NEBIUS_BASE_URL",
    model_env="NEBIUS_MODEL",
    default_model="openai/gpt-oss-120b",
    note=(
        "the instrumentor patches the SDK client, not the endpoint, so this "
        "captures the OpenAI instrumentor against whatever base_url names"
    ),
    instrument=_openai_instrument,
    client=_openai_client,
    request=_openai_request,
    results=_openai_results,
)

GENAI = Backend(
    id="genai",
    packages=("openai", "opentelemetry-instrumentation-genai-openai"),
    # The same credential, the same endpoint variable, the same model. That is
    # what makes the two traces a matched pair -- and it is also why plain
    # `make capture` now refuses as ambiguous when NEBIUS_API_KEY is set: two
    # backends really can run, and guessing which one you meant would produce a
    # fixture whose provenance file names the wrong instrumentor.
    api_key_env="NEBIUS_API_KEY",
    base_url_env="NEBIUS_BASE_URL",
    model_env="NEBIUS_MODEL",
    default_model="openai/gpt-oss-120b",
    note=(
        "the OTel GenAI half of the matched pair: identical to `openai` in "
        "SDK, endpoint, model, prompt and tools -- only the instrumentor "
        "differs, which is what lets an equivalence failure be attributed to "
        "the dialect"
    ),
    instrument=_genai_instrument,
    client=_openai_client,
    request=_openai_request,
    results=_openai_results,
    dialect=GENAI_DIALECT,
    enable=_genai_enable,
    require=_genai_require,
    checklist=_genai_checklist,
)

BACKENDS = {backend.id: backend for backend in (ANTHROPIC, GENAI, OPENAI)}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def converse(
    backend: Backend,
    model: str,
    tracer: Any,
    prompt: str = QUESTION,
    tool_names: tuple[str, ...] = DEFAULT_TOOLS,
    parallel: bool = False,
    note: dict[str, Any] | None = None,
    base_url: str | None = None,
) -> bool:
    """One two-turn tool-using conversation: agent -> [llm, tool, llm].

    ``prompt`` and ``tool_names`` default to the reference conversation, so a
    plain ``make capture`` is byte-for-byte the run it always was -- 2.6's
    matched pair depends on that not drifting. The fleet (`fleet.py`) varies
    them, and varies **only** them plus ``parallel``: same backend, same
    model, same instrumentor.

    ``parallel`` defaults **off**, and that default is load-bearing rather
    than cautious. Sending ``parallel_tool_calls`` changes what the
    instrumentor records in ``llm.invocation_parameters``, so a reference
    capture taken with it would no longer differ from 2.6's GenAI capture only
    in the instrumentor -- the matched pair would be matched on nothing. The
    fleet sets it; the reference conversation must not.

    ``note`` is stamped onto the ``agent.run`` span as OpenInference
    ``metadata``, and the fleet uses it to say **which model produced this
    trace**. A fleet that spans models without recording which is worse than a
    single-model fleet: every finding it produces is unattributable. The
    reference capture passes nothing, so its spans are unchanged.

    **The agent and tool spans are emitted here, by this file.** Only the
    ``llm`` spans come from the instrumentor, because an instrumentor wraps an
    SDK client and executing a tool is not an SDK call -- so nothing would
    otherwise record that the tool ran, and the capture would be two sibling
    root LLM spans with no containment and no ``call_result`` pairing at all.
    That is what an application does too: the framework spans in any real
    trace are the application's, not the instrumentor's.

    It has to be said out loud in the provenance file, because "the trace
    came from real instrumentation" is then true of some spans and not
    others, and the difference is exactly what a captured fixture is for.
    """
    client = backend.client(base_url)
    tools = tuple(TOOLS[name] for name in tool_names)
    dialect = backend.dialect

    # `note` is not mapped by any adapter, and that is fine: the library
    # reports it as an unmapped attribute and keeps it verbatim in `raw`, so
    # the attribution survives without the model pretending to understand it.
    attributes = dialect.agent(prompt, note)

    with tracer.start_as_current_span(dialect.agent_span_name, attributes=attributes):
        messages: list[Any] = [{"role": "user", "content": prompt}]

        history, calls = backend.request(client, model, messages, tools, parallel)
        messages.append(history)
        if not calls:
            # Not a failure. A turn the model answered directly is one of the
            # shapes a fleet needs (`TASKS.md` 2.2); it is only a weak result
            # for the *single* capture, and run.py says so there.
            return False

        payloads = []
        for call in calls:
            payloads.append(_run_tool(tracer, call, dialect))
        messages.extend(backend.results(calls, payloads))

        backend.request(client, model, messages, tools, parallel)
    return True


def _run_tool(tracer: Any, call: ToolCall, dialect: SpanDialect = OPENINFERENCE) -> Any:
    """Execute one tool call inside a span the corpus would recognize.

    A `ToolFailure` is deliberately allowed to **escape the span** before it is
    caught: that is what makes the tracer mark the span ERROR and record the
    exception, exactly as a real failing tool would. The error is then handed
    back to the model as the tool's result, which is what a real application
    does and what keeps the conversation going for a second turn.
    """
    try:
        with tracer.start_as_current_span(
            dialect.tool_span_name(call), attributes=dialect.tool(call)
        ) as span:
            payload = TOOLS[call.name].run(call.arguments)
            for key, value in dialect.tool_result(payload).items():
                span.set_attribute(key, value)
            return payload
    except ToolFailure as failure:
        return {"error": str(failure)}
