# `tool_call_history_echo` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl`, 1-indexed: **L2** the
LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the LLM
turn that was shown the history. Same attribute vocabulary as
`llm_tool_llm/otel_genai.notes.md`; only what is specific to this scenario is
repeated here.

No agent span, so nothing is transcribed from L1.

## The property this scenario is about, in this dialect

s3's `gen_ai.input.messages` carries the previous turn in full, exactly as L4
does:

```json
[ {"role":"user", …},
  {"role":"assistant","parts":[{…,"type":"tool_call","id":"call_a"}]},
  {"role":"tool","parts":[{"response":"…","id":"call_a","type":"tool_call_response"}]} ]
```

The same id, `call_a`, appears **twice** in s3's input, and s3 requested
nothing. An adapter that took a call id from anywhere on the span would emit a
second `call_result` edge with `warrant=explicit` for a relation the telemetry
never stated — the Phase 1 defect this scenario exists to catch. Dialect two
can express the defect, which is what makes the rendering worth having.

Where the dialects differ is the **mechanism** that separates a request from an
echo, and the difference matters for `SPEC.md` §4.4:

| | OpenInference | OTel GenAI |
|---|---|---|
| separated by | the attribute prefix: `llm.output_messages.` vs `llm.input_messages.` | the `type` of the part: `tool_call` vs `tool_call_response`, **and** which attribute the message list sits in |
| request id at | `llm.output_messages.0.message.tool_calls.0.tool_call.id` | a `tool_call` part inside `gen_ai.output.messages` |
| result id at | `llm.input_messages.2.message.tool_call_id`, guarded by `.message.role == "tool"` | a `tool_call_response` part inside `gen_ai.input.messages` |
| the echo | `llm.input_messages.1.message.tool_calls.0.tool_call.id`, left unconsumed → surfaces in `unmapped` | a `tool_call` part inside `gen_ai.input.messages` — **inside a payload**, so it never reaches `unmapped` |

That last row is a real difference in what the corpus can observe. In
OpenInference the echoed request id is a flat attribute the adapter declines,
so `scenario.md` can say it "surfaces in `unmapped` and is reported". In GenAI
it lives inside the `gen_ai.input.messages` payload, which **is** consumed —
so there is nothing left over to report. The diagnostic on s3 therefore names
a different key (`gen_ai.response.finish_reasons`). Codes and counts still
match, which is all `FIXTURES.md` §4 compares, but the sentence in
`scenario.md` is true of one dialect only. Flagged rather than fixed:
`scenario.md` is not this task's to rewrite.

## Payloads

s2 carries `gen_ai.tool.call.result` and **no** `gen_ai.tool.call.arguments`,
which is what makes its `inputs` `absent` rather than `empty`. L3 in the
capture carries both; omitting one is the scenario's subject, not a claim that
the dialect cannot emit it.

## Observed keys deliberately omitted

As in `llm_tool_llm`, plus: no `gen_ai.usage.*`, because this scenario's
expected graph reports no usage on either LLM span. The capture does carry
usage on both — omitted, not contradicted.

`gen_ai.response.finish_reasons` is kept on s1 and s3 so each carries exactly
one unmapped key, matching the expected count of 2.

## What this rendering cannot make agree

1. **Payloads** — declared in `expected/comparison.json` (`FIXTURES.md` §4.4).
2. **`Node.name`** — `chat demo-model` and `execute_tool lookup` are the
   convention's names; the expected graph pins `llm.plan`, `tool.lookup`,
   `llm.answer` from the OpenInference specimen, and this scenario has no
   `comparison.json` declaring `name` dialect-varying the way `llm_tool_llm`
   does. Not worked around here (`TASKS.md` 2.8).
