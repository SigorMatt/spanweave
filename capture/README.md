# capture/ — the capture harness

**Human-run only.** An autonomous agent must not run this and must not create
a file in `fixtures/captured/` (`AGENT.md` halt point).

```
make capture                              # uses whichever backend you configured
make capture ARGS="--backend openai"      # or name one
```

## Why this exists

A hand-authored fixture in `fixtures/conformance/` proves an adapter matches
**our understanding** of a dialect. Only a captured trace proves it matches
**the instrumentor**. Those are different claims, and the second is the one
that matters the moment someone points the library at their own stack
(`FIXTURES.md` §6).

That is also why the harness cannot certify itself: evidence about the outside
world that you generated from your own idea of the outside world is not
evidence.

## Why it lives outside the package

This directory may use the network, a model API, and framework dependencies —
and it is the only place in this repository that may (`ENVIRONMENT.md`,
network zones). Nothing under `spanweave/` imports anything from here, which
is what makes the library's "never touches the network" claim structural
rather than aspirational. The no-network gate scans `spanweave/`; this
directory is deliberately out of its blast radius, and out of the wheel.

## Two backends

Both are first-class. Neither replaced the other, and a capture from each is
worth more than two captures from one: two independent instrumentors emitting
the same semantic conventions is the only way to find out whether
"OpenInference" means one thing or two.

| Backend | SDK | Instrumentor | Credential | Endpoint | Model |
|---|---|---|---|---|---|
| `anthropic` | `anthropic` | `openinference-instrumentation-anthropic` | `ANTHROPIC_API_KEY` | fixed | `ANTHROPIC_MODEL`, default `claude-opus-5` |
| `openai` | `openai` | `openinference-instrumentation-openai` | `NEBIUS_API_KEY` | `NEBIUS_BASE_URL` | `NEBIUS_MODEL`, default `openai/gpt-oss-120b` |

### Which one runs

1. `--backend anthropic|openai` wins outright.
2. Otherwise, whichever backend's **credential is set** is used.
3. If **both** are set, or **neither** is, that is a **hard error** naming
   `--backend` and listing what it looked for.

The refusal is deliberate, and it is the same posture as the library's own
adapter selection (`SPEC.md` §6.1): a capture that quietly ran against the
backend you did not mean is a fixture whose provenance file is wrong, which is
worse than no fixture at all.

Model resolution, in order: `--model`, then `SPANWEAVE_CAPTURE_MODEL` (works
for either backend), then the backend's own variable, then its default.

### What to install

Only what your backend needs:

```bash
# openai backend — any OpenAI-compatible endpoint
uv pip install openai openinference-instrumentation-openai opentelemetry-sdk
export NEBIUS_API_KEY=...
export NEBIUS_BASE_URL=https://api.studio.nebius.com/v1/     # your endpoint
export NEBIUS_MODEL=openai/gpt-oss-120b                      # optional

# anthropic backend
uv pip install anthropic openinference-instrumentation-anthropic opentelemetry-sdk
export ANTHROPIC_API_KEY=...
```

None of these are in `pyproject.toml`, not even as an extra. Core has zero
runtime dependencies, and the lockfile that pins the build should not move for
a step that runs once, by hand, on your machine.

### The instrumentor patches the SDK, not the endpoint

`OpenAIInstrumentor` wraps the methods of the `openai.OpenAI` **client
object**. It neither knows nor cares what `base_url` points at, so it emits
identical spans against OpenAI, Nebius, vLLM, or anything else that speaks the
same protocol.

Two consequences, and the second is the one that belongs in the provenance
file:

- Any OpenAI-compatible provider works, with no code change here.
- **What the fixture demonstrates is `openinference-instrumentation-openai`**
  — not OpenAI, and not the provider that answered. "Captured against a real
  model" and "captured against OpenAI" are different claims, and only the
  first is true.

The harness uses `chat.completions` rather than the Responses API for the same
reason: it is the surface every OpenAI-compatible provider implements, and a
capture that only works against one provider is not the evidence this is for.

## Which spans come from where

**Only the `llm` spans come from the instrumentor.** The `agent` and `tool`
spans are emitted by `capture/backends.py`, using OpenInference conventions,
because executing a tool is **not an SDK call** — no instrumentor would record
it, since there is nothing for it to wrap.

Without them a capture would be two sibling root LLM spans: no containment, no
tool node, and **no `call_result` pairing at all** — which is the one relation
the whole harness exists to demonstrate. That is also what a real
application's trace looks like: the framework spans in any real trace are the
application's, not the instrumentor's.

It has to be said out loud in the provenance file, because "the trace came
from real instrumentation" is then true of some spans and not others, and that
difference is exactly what a captured fixture is for. The harness prints the
sentence to copy.

## What it does

Runs a two-turn tool-using conversation and converts the resulting OTel spans
into the flat JSONL dialect the corpus uses (`exporter.py`):

```
agent.run                     <- emitted here
├── ChatCompletion / Messages <- instrumentor; requests the tool call
├── tool.get_weather          <- emitted here; carries tool_call.id
└── ChatCompletion / Messages <- instrumentor; answers
```

That is the `llm_tool_llm` shape. Call/result pairing is the one relation a
dialect-aware adapter is uniquely able to recover, and the thing dialects
disagree about most (`SPEC.md` §4.4).

The tool is local, pure, and boring on purpose — no network, no clock, nothing
that would have to be redacted or explained.

## What it does **not** do

It does not write to `fixtures/captured/`. Output goes to
`capture/_scratch/<name>.local.jsonl`, which is gitignored. Promoting it to a
fixture is a human act with three parts, and the harness prints them when it
finishes:

1. **Read it.** It contains what the model and the instrumentation actually
   produced — your prompt and the response included.
2. **Redact it** if anything in it should not be public, and **record what you
   removed**. An unrecorded redaction is indistinguishable from none. If your
   endpoint URL embeds a credential, that is the one thing here that can carry
   a secret without looking like one.
3. **Move it and write its `<name>.provenance.md`** — instrumentor and exact
   version, SDK and version, model, endpoint, date, command, what was redacted
   and by whom, and **what this fixture may be used to claim**.

## Testing

`exporter.py` is duck-typed — it reads attributes off whatever it is handed
and imports nothing from opentelemetry — so the span-to-dialect conversion is
tested against stub spans with no SDK installed (`tests/test_capture.py`).
**It needed no change for the second instrumentor**, and that is structural
rather than lucky: it reads the OTel `ReadableSpan` surface, which is the same
class whichever instrumentor filled it, and copies the attribute keys
verbatim. The dialect lives in those keys.

The tests also cover backend selection, the attributes of the spans the
harness emits itself, and — the strongest claim available without a key — that
the shape `make capture` is designed to produce builds into exactly the
structure the `llm_tool_llm` scenario asserts, including the `call_result`
edge. There is a test for the negative case too: drop the harness's own two
spans and the pairing disappears.

The model call itself is not tested, and should not be.
