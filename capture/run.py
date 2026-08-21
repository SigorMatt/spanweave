"""Capture a real trace from real instrumentation. **Human-run only.**

    make capture

This is the step an autonomous agent must not take (``AGENT.md``). Everything
else in this repository can be verified by running it; this one produces
evidence about the *outside world*, and evidence you generated yourself is not
evidence. A hand-authored fixture proves the adapter matches **our
understanding** of a dialect. Only a captured one proves it matches **the
instrumentor** -- and that is the claim that matters the moment someone points
the library at their own stack (``FIXTURES.md`` §6).

What it does: runs a small two-turn tool-using conversation through the
Anthropic SDK with OpenInference instrumentation attached, exports the
resulting spans as flat JSONL in the dialect the corpus uses, and writes them
to a scratch file **outside** ``fixtures/captured/``.

What it deliberately does **not** do: put anything into ``fixtures/captured/``.
That is a human act, performed after reading the trace, redacting whatever
needs redacting, and writing the provenance file. The harness prints exactly
what remains to be done.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

from capture.exporter import JsonlSpanExporter

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRATCH = REPO / "capture/_scratch"

# Not a downgrade for cost: the point is a real trace from a real model call,
# and any current model produces one. Override with SPANWEAVE_CAPTURE_MODEL.
DEFAULT_MODEL = "claude-opus-5"

INSTALL_HINT = """
This harness needs framework dependencies that the library itself must never
have. Install them in your own environment:

    uv pip install anthropic opentelemetry-sdk \\
        openinference-instrumentation-anthropic

and set ANTHROPIC_API_KEY. Core has zero runtime dependencies and these are
never added to it (ENVIRONMENT.md).
"""

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
        "additionalProperties": False,
    },
}


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _instrument(exporter):
    """Attach OpenInference instrumentation to the Anthropic SDK."""
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    AnthropicInstrumentor().instrument(tracer_provider=provider)
    return provider


def _converse(model: str) -> None:
    """A two-turn tool-using conversation: llm -> tool -> llm.

    Chosen because it is the shape the corpus cares most about. It is the only
    relation a dialect-aware adapter is uniquely able to recover, and the one
    dialects disagree about most (`SPEC.md` §4.4).
    """
    import anthropic

    client = anthropic.Anthropic()
    messages = [
        {"role": "user", "content": "What is the weather in Paris? Use the tool."}
    ]

    first = client.messages.create(
        model=model, max_tokens=16000, tools=[WEATHER_TOOL], messages=messages
    )
    # Append the whole content, not just the text: thinking blocks must be
    # echoed back unchanged on the same model.
    messages.append({"role": "assistant", "content": first.content})

    results = [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps({"city": block.input.get("city"), "c": 18}),
        }
        for block in first.content
        if block.type == "tool_use"
    ]
    if not results:
        print(
            "the model answered without calling the tool; the capture will have "
            "no tool span. Re-run, or accept a trace without call pairing.",
            file=sys.stderr,
        )
        return

    # Every tool_result in ONE user message: splitting them teaches the model
    # to stop making parallel calls.
    messages.append({"role": "user", "content": results})
    client.messages.create(
        model=model, max_tokens=16000, tools=[WEATHER_TOOL], messages=messages
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make capture",
        description="Capture a real instrumented trace. Human-run only.",
    )
    parser.add_argument(
        "--name", default="anthropic_tool_call", help="base name for the output file"
    )
    parser.add_argument(
        "--model", default=os.environ.get("SPANWEAVE_CAPTURE_MODEL", DEFAULT_MODEL)
    )
    args = parser.parse_args(argv)

    try:
        exporter = JsonlSpanExporter()
        provider = _instrument(exporter)
    except ImportError as failure:
        return _fail(f"missing dependency: {failure}\n{INSTALL_HINT}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _fail(
            "ANTHROPIC_API_KEY is not set. This step makes a real model call, "
            "which is exactly why it is human-run.\n" + INSTALL_HINT
        )

    try:
        _converse(args.model)
    finally:
        provider.shutdown()

    if not exporter.records:
        return _fail("no spans were exported; the instrumentation did not attach")

    SCRATCH.mkdir(parents=True, exist_ok=True)
    captured = SCRATCH / f"{args.name}.local.jsonl"
    captured.write_text(
        "".join(
            json.dumps(record, separators=(",", ":")) + "\n"
            for record in exporter.sorted_records()
        ),
        encoding="utf-8",
    )

    today = datetime.date.today().isoformat()
    print(_next_steps(captured, args.name, args.model, today, len(exporter.records)))
    return 0


def _next_steps(captured, name, model, today, count):
    return f"""
Captured {count} spans -> {captured}

This file is NOT a fixture yet, and nothing has been committed. Three things
remain, and all three are yours (FIXTURES.md §6):

1. READ IT. It contains whatever the model and the instrumentation actually
   produced, including the prompt and the response.

2. REDACT IT, if anything in it should not be public -- then record what you
   removed, and that you removed it. Redaction is a human act performed before
   commit, and an unrecorded redaction is indistinguishable from none.

3. MOVE AND DOCUMENT IT:

     mv {captured} fixtures/captured/{name}.jsonl

   and write fixtures/captured/{name}.provenance.md recording:

     - instrumentor: openinference-instrumentation-anthropic <exact version>
     - SDK: anthropic <exact version>; opentelemetry-sdk <exact version>
     - model: {model}
     - captured: {today}
     - command: make capture --name {name}
     - redacted: <what, by whom> (or: nothing, and why that was safe)
     - this fixture may be used to claim: <what it actually demonstrates>

Then check that it builds, and that what it says about itself is true:

     uv run spanweave inspect fixtures/captured/{name}.jsonl
     uv run spanweave build fixtures/captured/{name}.jsonl -o /dev/null

If the captured trace and a hand-authored fixture disagree, the captured one
is right and the adapter is wrong (FIXTURES.md §6).
"""


if __name__ == "__main__":
    sys.exit(main())
