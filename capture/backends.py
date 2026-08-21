"""The model backends the capture harness can drive, and the run it drives.

Two backends, deliberately kept side by side:

* **anthropic** — the Anthropic SDK, instrumented by
  ``openinference-instrumentation-anthropic``.
* **openai** — the OpenAI SDK, instrumented by
  ``openinference-instrumentation-openai``, pointed at any OpenAI-compatible
  endpoint through ``base_url``.

They exist for the same reason the library has adapters: two independent
instrumentors emitting the same semantic conventions is the only way to find
out whether "OpenInference" means one thing or two. A capture from one proves
that one instrumentor's output parses. A capture from each proves rather more.

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
JSON_MIME = "application/json"
TEXT_MIME = "text/plain"

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


def _anthropic_client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _anthropic_tool(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.schema,
    }


def _anthropic_request(
    client: Any, model: str, messages: list[Any], tools: tuple[Tool, ...]
) -> tuple[Any, list[ToolCall]]:
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


def _openai_client() -> Any:
    import openai

    # base_url is what makes this backend point anywhere. The instrumentor
    # neither knows nor cares -- it patches this client object.
    return openai.OpenAI(
        api_key=os.environ["NEBIUS_API_KEY"],
        base_url=os.environ.get("NEBIUS_BASE_URL"),
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
    client: Any, model: str, messages: list[Any], tools: tuple[Tool, ...]
) -> tuple[Any, list[ToolCall]]:
    # chat.completions rather than responses: it is the surface every
    # OpenAI-compatible provider implements, and a capture that only works
    # against one provider is not the evidence this harness is for.
    response = client.chat.completions.create(
        model=model, messages=messages, tools=[_openai_tool(tool) for tool in tools]
    )
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


def _openai_results(calls: list[ToolCall], payloads: list[Any]) -> list[Any]:
    # One message per call here, unlike Anthropic's single user message. The
    # SDKs genuinely disagree about this, which is a small reminder of why the
    # library has adapters at all.
    return [
        {"role": "tool", "tool_call_id": call.id, "content": json.dumps(payload)}
        for call, payload in zip(calls, payloads, strict=True)
    ]


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

BACKENDS = {backend.id: backend for backend in (ANTHROPIC, OPENAI)}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def converse(
    backend: Backend,
    model: str,
    tracer: Any,
    prompt: str = QUESTION,
    tool_names: tuple[str, ...] = DEFAULT_TOOLS,
) -> bool:
    """One two-turn tool-using conversation: agent -> [llm, tool, llm].

    ``prompt`` and ``tool_names`` default to the reference conversation, so a
    plain ``make capture`` is byte-for-byte the run it always was -- 2.6's
    matched pair depends on that not drifting. The fleet (`fleet.py`) varies
    them, and varies **only** them: same backend, same model, same
    instrumentor.

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
    client = backend.client()
    tools = tuple(TOOLS[name] for name in tool_names)

    with tracer.start_as_current_span(
        "agent.run",
        attributes={
            SPAN_KIND: "AGENT",
            INPUT_VALUE: prompt,
            INPUT_MIME: TEXT_MIME,
        },
    ):
        messages: list[Any] = [{"role": "user", "content": prompt}]

        history, calls = backend.request(client, model, messages, tools)
        messages.append(history)
        if not calls:
            # Not a failure. A turn the model answered directly is one of the
            # shapes a fleet needs (`TASKS.md` 2.2); it is only a weak result
            # for the *single* capture, and run.py says so there.
            return False

        payloads = []
        for call in calls:
            payloads.append(_run_tool(tracer, call))
        messages.extend(backend.results(calls, payloads))

        backend.request(client, model, messages, tools)
    return True


def _run_tool(tracer: Any, call: ToolCall) -> Any:
    """Execute one tool call inside a span the corpus would recognize.

    A `ToolFailure` is deliberately allowed to **escape the span** before it is
    caught: that is what makes the tracer mark the span ERROR and record the
    exception, exactly as a real failing tool would. The error is then handed
    back to the model as the tool's result, which is what a real application
    does and what keeps the conversation going for a second turn.
    """
    try:
        with tracer.start_as_current_span(
            f"tool.{call.name}", attributes=tool_span_attributes(call)
        ) as span:
            payload = TOOLS[call.name].run(call.arguments)
            span.set_attribute(OUTPUT_VALUE, json.dumps(payload))
            span.set_attribute(OUTPUT_MIME, JSON_MIME)
            return payload
    except ToolFailure as failure:
        return {"error": str(failure)}


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
