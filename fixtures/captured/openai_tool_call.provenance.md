# openai_tool_call.jsonl — provenance

## What this is

A captured trace from a two-turn tool-using conversation, run by hand through
`make capture` (`capture/README.md`). Not hand-authored.

## Capture details

- **Instrumentor:** openinference-instrumentation-openai 0.1.54
  (openinference-instrumentation 0.1.57,
  openinference-semantic-conventions 0.1.32)
- **SDK:** openai 3.3.1; opentelemetry-sdk 1.44.0
- **Model:** openai/gpt-oss-120b
- **Endpoint:** https://api.tokenfactory.nebius.com/v1/ (Nebius Token Factory)
- **Captured:** 2026-08-21
- **Command:** `make capture` with `--backend openai`

## Redaction

Nothing was redacted, and that was checked rather than assumed.

Reviewed by Matthew Sigurko on 2026-08-21. Every payload was read in full, not
merely pattern-scanned. The conversation is synthetic and written for this
capture: a weather question, a stub tool returning fixed values, and two model
responses about Paris weather. No personal, customer, or proprietary content.
Scanned separately for credential patterns (API key prefixes, bearer tokens,
URLs with embedded credentials): none found. The Nebius endpoint does not
appear in the file at all — the instrumentor records the SDK call, not the
transport.

An unrecorded redaction is indistinguishable from none, so this section exists
even though nothing was removed.

## Matched pair

This file and `genai_tool_call.jsonl` are a **matched pair**: same model
(openai/gpt-oss-120b), same prompt, same tool inventory, differing **only in
the instrumentor** — OpenInference here, OTel GenAI there. Neither can be read
as evidence about a dialect without the other.

Note one asymmetry: GenAI defines an `execute_tool` span convention and
OpenInference defines none, so the tool span is convention-defined in that
half and ours in this one. That is a property of the dialects, not a choice.

## What this fixture may be used to claim

**It demonstrates `openinference-instrumentation-openai`** — whatever service
answered. The instrumentor patches the SDK client, not the endpoint, so the
spans it produces have the same shape against any OpenAI-compatible backend.
It does **not** demonstrate the Anthropic instrumentor.

**Only the `llm` spans come from the instrumentor.** The `agent.run` and
`tool.get_weather` spans are emitted by `capture/backends.py`, because
executing a tool is not an SDK call and no instrumentor would record it. A real
application's trace looks the same way — but "captured from real
instrumentation" is true of some spans here and not others.

**`tool.get_weather` ran in 32 microseconds.** It is a local stub, not a
network call. From an independent review of this trace: *a fidelity check that
never asks whether a leaf span is physically plausible will pass a fully mocked
trace as a real one.* This fixture proves the adapter reads the instrumentor
correctly; it proves nothing about real tool latency.

**It is the only committed evidence for `SPEC.md` §4.2.1.** Span 4 carries the
tool-result message — `{"role": "tool", "tool_call_id": ..., "content": ...}` —
alongside the assistant echo bearing the same id under `tool_calls`. Both
discriminators (`role`, and flat vs. nested attribute form) are visible in one
payload. Six documents previously asserted OpenInference declares no
producer→consumer relation; this file is what showed otherwise.

## Why this fixture exists

It found two real defects on first use, both invisible to the hand-authored
corpus:

1. **A false `call_result` edge.** The follow-up LLM span re-sends the
   assistant turn in its message history, so the same `tool_call.id` appeared
   on a span that requested nothing. The adapter matched on the attribute
   suffix and never read the segment saying who spoke, emitting two `explicit`
   edges where one relation existed. Fixed in 79f7dcd. That fix also revealed
   all four call-bearing fixtures were unrepresentative of the dialect.

2. **A missing declared `data` edge.** Found by an independent reviewer given
   only this trace and its graph, with no knowledge of the project. The
   instrumentor declares the tool result reaching the follow-up LLM, and we
   were dropping it into `unmapped_attributes`. Resolved by spec change
   (`SPEC.md` §4.2.1).

Both were invisible to 593 tests, six invariant gates, and two review scripts —
all of which agreed with each other because all were built from the same
misreading of the dialect. Only real instrumentor output disagreed.

That is what `FIXTURES.md` §6 requires a captured trace for.
