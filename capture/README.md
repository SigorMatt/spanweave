# capture/ — the capture harness

**Human-run only.** An autonomous agent must not run this and must not create
a file in `fixtures/captured/` (`AGENT.md` halt point).

```
make capture
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

## What you need

```
uv pip install anthropic opentelemetry-sdk openinference-instrumentation-anthropic
export ANTHROPIC_API_KEY=...
```

These are **not** in `pyproject.toml`, not even as an extra. Core has zero
runtime dependencies, and the lockfile that pins the build should not move for
a step that runs once, by hand, on your machine.

## What it does

Runs a two-turn tool-using conversation through the Anthropic SDK with
OpenInference instrumentation attached, and converts the resulting OTel spans
into the flat JSONL dialect the corpus uses (`exporter.py`).

The conversation shape is chosen deliberately: an LLM call that requests a
tool, a tool span that fulfils it, and a second LLM call. Call/result pairing
is the one relation a dialect-aware adapter is uniquely able to recover, and
the thing dialects disagree about most (`SPEC.md` §4.4).

## What it does **not** do

It does not write to `fixtures/captured/`. Output goes to
`capture/_scratch/<name>.local.jsonl`, which is gitignored. Promoting it to a
fixture is a human act with three parts, and the harness prints them when it
finishes:

1. **Read it.** It contains what the model and the instrumentation actually
   produced — your prompt and the response included.
2. **Redact it** if anything in it should not be public, and **record what you
   removed**. An unrecorded redaction is indistinguishable from none.
3. **Move it and write its `<name>.provenance.md`** — instrumentor and exact
   version, SDK and version, model, date, command, what was redacted and by
   whom, and **what this fixture may be used to claim**.

## Testing

`exporter.py` is duck-typed — it reads attributes off whatever it is handed
and imports nothing from opentelemetry — so the span-to-dialect conversion is
tested against stub spans without the SDK installed
(`tests/test_capture.py`). That includes the join that matters: what the
harness writes, the OpenInference adapter must read.

The model call itself is not tested, and should not be.
