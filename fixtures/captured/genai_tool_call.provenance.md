# genai_tool_call.jsonl — provenance

## What this is

A captured trace from the same two-turn tool-using conversation as
`openai_tool_call.jsonl`, run by hand through `make capture --backend genai`.
Not hand-authored. Half of a matched pair (below).

## Capture details

- **Instrumentor:** opentelemetry-instrumentation-genai-openai 1.1b0
  (opentelemetry-util-genai 1.1b0)
- **SDK:** openai 3.3.1; opentelemetry-sdk 1.44.0
- **Dialect emitted:** `otel_genai`
- **Model:** openai/gpt-oss-120b
- **Endpoint:** https://api.tokenfactory.nebius.com/v1/ (Nebius Token Factory)
- **Captured:** 2026-08-27
- **Command:** `make capture ARGS="--backend genai"`
- **Content capture:** `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY`,
  set explicitly and the **resolved** mode read back before instrumenting.
  This matters: `=true`, which the older package's docs prescribe, is not
  valid on this path — it is rejected with one line of stderr and silently
  downgraded to `NO_CONTENT`. A trace captured that way looks healthy and
  carries no payloads and no tool-call ids.

## Matched pair

This file and `openai_tool_call.jsonl` are a **matched pair**: same model
(openai/gpt-oss-120b), same prompt, same tool inventory, differing **only in
the instrumentor**. Neither can be read as evidence about a dialect without
the other — an equivalence failure between them is attributable to the
dialect precisely because nothing else varies.

## Redaction

Nothing was redacted, and that was checked rather than assumed.

Reviewed by Matthew Sigurko on 2026-08-27. Every payload was read in full.
The conversation is synthetic and written for this capture: a weather
question, a stub tool returning fixed values, two model responses about Paris
weather. Scanned for credential patterns (API key prefixes, bearer tokens,
URLs with embedded credentials): none found.

**`server.address` is kept, deliberately.** Unlike the OpenInference half,
this instrumentor names the service that answered:
`server.address = api.tokenfactory.nebius.com`. That is a public endpoint
hostname carrying no credential, and this file names the endpoint anyway.
Do **not** copy the other fixture's sentence about the endpoint not appearing
in the trace — here it does.

## Verification at capture time

All three points passed, checked by the harness against the records it had
just written and confirmed here against the file:

1. **Content capture really was on** — 3 of 4 spans carry
   `gen_ai.input.messages` / `gen_ai.output.messages`.
2. **Tool-call ids on both the requesting and the fulfilling span** —
   `chatcmpl-tool-ba26764988bf8aa9` on the first `chat` span's output and on
   the `execute_tool` span.
3. **The follow-up turn declares the tool result with the same id**
   (`SPEC.md` §4.2.1) — a `role: "tool"` message in the second `chat` span's
   `gen_ai.input.messages`.

## What this fixture may be used to claim

**It demonstrates `opentelemetry-instrumentation-genai-openai`**, whatever
service answered. The instrumentor patches the SDK client, not the endpoint.

**It is the second dialect's evidence that `EdgeKind.data` generalizes.**
`SPEC.md` §4.2.1 was written from a single instrumentor's convention, and
`OPEN_QUESTIONS.md` §7 / `PREDICTIONS.md` P3 rest on how far that generalizes.
This trace declares the same producer→consumer relation, by id, in an
unrelated dialect. That is evidence the kind is a property of the domain
rather than of OpenInference — **evidence, not a resolution** of either
question.

**The tool span is convention-defined here and ours in the other half.**
GenAI defines `execute_tool`; OpenInference defines nothing for a tool
execution. So the `execute_tool` span is named and shaped by the conventions,
though still emitted by `capture/backends.py` — executing a tool is not an SDK
call and no instrumentor records it. The `invoke_agent` span's attributes
remain a judgement call. This asymmetry is a property of the dialects, not a
choice, and it may be what an equivalence run trips on.

**Only the `chat` spans come from the instrumentor.** As above: "captured from
real instrumentation" is true of some spans here and not others.
