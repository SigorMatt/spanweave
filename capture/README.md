# capture/ — the capture harness

**Human-run only.** An autonomous agent must not run this and must not create
a file in `fixtures/captured/` (`AGENT.md` halt point).

```
make capture                              # uses whichever backend you configured
make capture ARGS="--backend openai"      # or name one
make capture ARGS="--backend genai"       # the OTel GenAI half of the pair
make capture ARGS="--fleet 8"             # the scratch fleet -- see below
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

## Three backends

All are first-class. None replaced another, and a capture from each is worth
more than three captures from one: two independent instrumentors emitting the
same semantic conventions is the only way to find out whether "OpenInference"
means one thing or two.

| Backend | SDK | Instrumentor | Emits | Credential | Endpoint | Model |
|---|---|---|---|---|---|---|
| `anthropic` | `anthropic` | `openinference-instrumentation-anthropic` | OpenInference | `ANTHROPIC_API_KEY` | fixed | `ANTHROPIC_MODEL`, default `claude-opus-5` |
| `openai` | `openai` | `openinference-instrumentation-openai` | OpenInference | `NEBIUS_API_KEY` | `NEBIUS_BASE_URL` | `NEBIUS_MODEL`, default `openai/gpt-oss-120b` |
| `genai` | `openai` | `opentelemetry-instrumentation-genai-openai` | OTel GenAI | `NEBIUS_API_KEY` | `NEBIUS_BASE_URL` | `NEBIUS_MODEL`, default `openai/gpt-oss-120b` |

### `genai` is not a third dialect to collect — it is the other half of a pair

`openai` and `genai` are **deliberately identical** in SDK, credential,
endpoint, model, prompt, tool inventory and conversation. The only thing that
differs is the instrumentor. That identity is the point: the cross-dialect
equivalence test (`FIXTURES.md` §4) claims two dialects of one scenario produce
one canonical graph, and a pair differing by more than the instrumentor could
not attribute a failure of that claim to the dialect. A test pins every shared
field, so the pair cannot drift quietly.

If the GenAI instrumentor ever requires something that would change what the
`openai` half records, that is a finding to report — **not** a change to absorb
into both sides.

### Which one runs

1. `--backend anthropic|genai|openai` wins outright.
2. Otherwise, whichever backend's **credential is set** is used.
3. If **more than one** is set, or **none** is, that is a **hard error** naming
   `--backend` and listing what it looked for.

The refusal is deliberate, and it is the same posture as the library's own
adapter selection (`SPEC.md` §6.1): a capture that quietly ran against the
backend you did not mean is a fixture whose provenance file is wrong, which is
worse than no fixture at all.

**One consequence, stated because it changes an old habit:** `genai` shares
`NEBIUS_API_KEY` with `openai`, so exporting that one variable now configures
**two** backends and a bare `make capture` refuses as ambiguous. Name the one
you mean. This is the right refusal to be given — the two differ only in the
instrumentor, so a wrong guess produces a trace that looks entirely plausible
beside a provenance file naming the wrong dialect.

Model resolution, in order: `--model`, then `SPANWEAVE_CAPTURE_MODEL` (works
for any backend), then the backend's own variable, then its default.

### What to install

Only what your backend needs:

```bash
# openai backend — any OpenAI-compatible endpoint
uv pip install openai openinference-instrumentation-openai opentelemetry-sdk
export NEBIUS_API_KEY=...
export NEBIUS_BASE_URL=https://api.studio.nebius.com/v1/     # your endpoint
export NEBIUS_MODEL=openai/gpt-oss-120b                      # optional

# genai backend — the same endpoint and model, a different instrumentor
uv pip install openai opentelemetry-instrumentation-genai-openai opentelemetry-sdk

# anthropic backend
uv pip install anthropic openinference-instrumentation-anthropic opentelemetry-sdk
export ANTHROPIC_API_KEY=...
```

### Which GenAI package — settled by running both, not by reading

`opentelemetry-instrumentation-openai-v2`, in `opentelemetry-python-contrib`,
was the first OTel-official OpenAI instrumentation. The work has since moved to
`opentelemetry-instrumentation-genai-openai` in the newer
`open-telemetry/opentelemetry-python-genai` repository. Both still publish to
PyPI, so "which one" is not answerable from the names, and the answer will
change again — record the version you used, and do not trust this section past
its date.

Checked on **2026-08-22**, by installing each into a throwaway environment and
driving a two-turn tool-calling conversation through it:

| | `…-genai-openai` 1.1b0 | `…-openai-v2` 2.4b0 |
|---|---|---|
| Imports against `openai` 3.3.1 | yes | **no** — `from httpx import URL`, and `openai` 3.x depends on `httpx2`, so `httpx` is absent unless something else pulled it in |
| With `httpx` installed alongside | — | works |
| `gen_ai.input.messages` / `gen_ai.output.messages` | identical (both delegate to `opentelemetry-util-genai`) | identical |
| Also emits | `server.address`, `server.port`, `gen_ai.tool.definitions` | — |
| Content flag values | `span_only` / `event_only` / `span_and_event` | same, **plus** its docs say `true`, which is not a valid value and is silently downgraded |

So: the newer package, because the older one does not import against a current
`openai` without an extra install its metadata does not ask for. The
disagreement is recorded rather than tidied away, which is what `TASKS.md` 2.5
asks for.

One more thing that is moving underneath all of this: in
`opentelemetry-semantic-conventions` 0.65b0 the whole `gen_ai.*` attribute set
is marked *"Deprecated: moved to the OpenTelemetry GenAI semantic conventions
repository"*. The **names are unchanged**; the conventions moved house. That is
why `capture/backends.py` writes the attribute names out as string literals
instead of importing the constants — a future rename should be a visible diff
in one file, not a silent change of behaviour underneath the harness.

### Content capture is opt-in, and without it the capture is worthless

GenAI does not record prompts, completions, tool arguments or tool results
unless you ask. Without them there is no `gen_ai.input.messages` and no
`gen_ai.output.messages` — so no payloads, **no tool-call ids**, no
`call_result` edge and no `SPEC.md` §4.2.1 declaration. Those two relations are
the entire reason the second dialect is being captured.

The backend therefore sets
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=span_only` **explicitly**
rather than relying on an ambient default, and then **reads the resolved mode
back** from the library that will act on it. The read-back is not a habit: on
this path `true` — which the older package's own documentation tells you to set
— is not a valid value. It is rejected with one line on stderr and silently
downgraded to `NO_CONTENT`, and the run then spends a credential producing a
trace with no messages in it. If the mode does not resolve to a span-capturing
one, the harness refuses **before the model call**.

`span_only` and not `event_only`, because this harness exports spans: the event
modes put the messages in log records that never reach the JSONL.

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
spans are emitted by `capture/backends.py`, because executing a tool is **not
an SDK call** — no instrumentor would record it, since there is nothing for it
to wrap.

**They speak the backend's dialect, not a fixed one.** The emitted keys are a
property of the backend, chosen alongside the instrumentor and never
independently of it (`SpanDialect` in `backends.py`). Emitting OpenInference
keys into a GenAI trace would produce a **mixed-dialect file that no adapter
reads honestly**: detection would see both, one adapter would win, and
whichever lost would take its spans' meaning with it.

One asymmetry between the two halves, and it belongs in both provenance files:
**OpenInference defines no tool-execution span, and GenAI does.** On the
OpenInference side `agent.run` and `tool.<name>` are this harness's own
convention. On the GenAI side the tool span is `execute_tool <name>` with
`gen_ai.tool.name` and `gen_ai.tool.call.id` — still emitted by us, but *named
and shaped by the conventions*. The `invoke_agent` span's attributes remain a
judgement call on both sides.

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

## The scratch fleet (`--fleet N`)

A different job with the same rules, only harder. `TASKS.md` 2.2 needs **many**
traces for the Phase 2b adversarial consumer, because `PREDICTIONS.md` P5 is
*"one trace = one graph"*: run over the committed corpus, an aggregator tests
**the aggregator**; run over a real heterogeneous fleet, it tests **the
claim**.

```bash
make capture ARGS="--fleet 14"    # -> capture/_scratch/fleet/01_weather__....jsonl
```

One file per run, because one trace is one graph (`SPEC.md` §7). The backend
and the instrumentor are **fixed**. What varies is the shape of the run —
steered by the prompt and the tool inventory — and, for some runs, **the
model** (`capture/fleet.py`).

**Why the model varies.** A fleet drawn from one model is a batch, not a fleet.
Real fleets span models, so a multi-model fleet is closer to what a fleet
aggregator actually meets, which is what P5 needs. Swapping the model changes
the setup; it does not select an answer, which is what the steering rule below
prohibits. The bound is stated instead: **at most two models beyond the
configured default**, pinned by a test, because past that it *is* selection.

Every trace records which model produced it — as OpenInference `metadata` on
its `agent.run` span, and in its filename. A fleet that mixes models without
saying which is worse than a single-model fleet: every finding it produces is
unattributable.

The multi-model specs sit at the end of the list, so `--fleet 8` never reaches
them and the harness says which specs it did not reach. A model on a different
regional endpoint names the environment variable holding it
(`NEBIUS_BASE_URL_EU_WEST2` for Kimi); if that is unset the run is **skipped
and reported**, never sent to the default endpoint — a trace whose provenance
is wrong is worse than one you do not have.

**None of this touches the reference capture.** `TASKS.md` 2.6 pins the matched
pair to `openai/gpt-oss-120b`; that pin belongs to the pair, never to the
fleet.

**Why it is harder.** Eight traces nobody reads carefully are a better hiding
place than one fixture under review. So the rules are stated rather than
assumed: these are **scratch** — gitignored, no provenance file, never promoted
to `fixtures/captured/`, never cited as evidence for anything beyond 2b's own
findings. The `AGENT.md` fabrication halt point covers the fleet exactly as it
covers a single capture.

**Enabling is not steering.** Fleet runs send `parallel_tool_calls=True` on the
OpenAI backend; the reference capture does not. Asking the API to *permit*
several calls in one turn is not the same as steering the model toward making
them, and the difference is not academic: the first fleet produced no parallel
call while recording `llm.invocation_parameters` as `{"model": ...}` alone, so
the question had never been put. It is scoped to the fleet because the
parameter changes what the instrumentor records, and 2.6's matched pair must
differ from its twin only in the instrumentor. vLLM-served endpoints do not
reliably honour it, so it may change nothing — and if an endpoint rejects it
outright with a 400, the harness says so and retries once without it rather
than losing a credentialed run.

**What the fleet must contain**, or it is not exercising P5 — varied tools,
turns with no tool call at all, turns with parallel calls, and a tool that
failed. The harness does not *assume* it got them. A prompt steers a model; it
does not command one. So it reads back what the exported records actually
contain and prints a coverage table, then **exits non-zero if a required shape
is missing** — an exit code is harder to skim past than a paragraph.

When that happens: re-run, raise `--fleet`, or reword the run that was aimed at
the missing shape. What you must **not** do is edit an exported span to add the
shape. That makes the fleet synthetic while it still looks real, which is the
one thing this whole directory exists to prevent.

## Testing

`exporter.py` is duck-typed — it reads attributes off whatever it is handed
and imports nothing from opentelemetry — so the span-to-dialect conversion is
tested against stub spans with no SDK installed (`tests/test_capture.py`).
**It needed no change for the second instrumentor, and none for the third**,
and that is structural rather than lucky: it reads the OTel `ReadableSpan`
surface, which is the same class whichever instrumentor filled it, and copies
the attribute keys verbatim. The dialect lives in those keys.

For the `genai` backend the tests also cover the parts that decide whether a
credentialed run is worth anything: that the harness's own spans carry only
`gen_ai.*` keys and no OpenInference ones; that content capture is set
explicitly and the **resolved** mode read back, refusing before the model call
if it did not take (including the `true`-is-silently-`NO_CONTENT` trap); that a
trace with no message content is **refused rather than written**; and that
`TASKS.md` 2.6's three verifications are answered against the exported records,
each failing case included. Plus the matched pair itself: every field the two
halves must share is asserted equal, so the pair cannot drift quietly.

The fleet is covered the same way — against stub spans, never a real call.
Each required shape is built as stub spans, pushed through the real
span-to-record conversion, and read back by `fleet.shapes_of`, so the coverage
verdict is tested end to end from span to report. Plus: `converse` driven
against a stub backend (the default prompt and inventory must not drift, since
2.6's matched pair depends on it); a tool failure escaping its span before it
is caught, which is what makes the tracer mark the span ERROR; and one file per
run, with a non-zero exit when a shape is missing.

The tests also cover backend selection, the attributes of the spans the
harness emits itself, and — the strongest claim available without a key — that
the shape `make capture` is designed to produce builds into exactly the
structure the `llm_tool_llm` scenario asserts, including the `call_result`
edge. There is a test for the negative case too: drop the harness's own two
spans and the pairing disappears.

The model call itself is not tested, and should not be.
