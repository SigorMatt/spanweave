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


def get_weather(arguments: dict[str, Any]) -> dict[str, Any]:
    """The tool. Local, pure, and boring on purpose.

    A capture is evidence about an **instrumentor**, so the tool must not add
    anything of its own -- no network, no clock, nothing that would have to be
    redacted or explained in the provenance file.
    """
    return {"city": arguments.get("city"), "celsius": 18, "summary": "clear"}


TOOLS = {"get_weather": get_weather}


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


ANTHROPIC_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": WEATHER_SCHEMA,
}


def _anthropic_request(
    client: Any, model: str, messages: list[Any]
) -> tuple[Any, list[ToolCall]]:
    response = client.messages.create(
        model=model, max_tokens=16000, tools=[ANTHROPIC_TOOL], messages=messages
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


OPENAI_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": WEATHER_SCHEMA,
    },
}


def _openai_request(
    client: Any, model: str, messages: list[Any]
) -> tuple[Any, list[ToolCall]]:
    # chat.completions rather than responses: it is the surface every
    # OpenAI-compatible provider implements, and a capture that only works
    # against one provider is not the evidence this harness is for.
    response = client.chat.completions.create(
        model=model, messages=messages, tools=[OPENAI_TOOL]
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


def converse(backend: Backend, model: str, tracer: Any) -> bool:
    """One two-turn tool-using conversation: agent -> [llm, tool, llm].

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

    with tracer.start_as_current_span(
        "agent.run",
        attributes={
            SPAN_KIND: "AGENT",
            INPUT_VALUE: QUESTION,
            INPUT_MIME: TEXT_MIME,
        },
    ):
        messages: list[Any] = [{"role": "user", "content": QUESTION}]

        history, calls = backend.request(client, model, messages)
        messages.append(history)
        if not calls:
            return False

        payloads = []
        for call in calls:
            payloads.append(_run_tool(tracer, call))
        messages.extend(backend.results(calls, payloads))

        backend.request(client, model, messages)
    return True


def _run_tool(tracer: Any, call: ToolCall) -> Any:
    """Execute one tool call inside a span the corpus would recognize."""
    with tracer.start_as_current_span(
        f"tool.{call.name}", attributes=tool_span_attributes(call)
    ) as span:
        payload = TOOLS[call.name](call.arguments)
        span.set_attribute(OUTPUT_VALUE, json.dumps(payload))
        span.set_attribute(OUTPUT_MIME, JSON_MIME)
        return payload


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
