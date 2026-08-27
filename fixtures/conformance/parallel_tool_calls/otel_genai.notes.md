# `parallel_tool_calls` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl`: **L1** the
`invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the
`execute_tool` span. Same vocabulary as
`llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

## The reconstruction, and what licenses it

The capture contains **one** tool call, not two. This scenario needs a single
turn requesting two, so it is the one of the three that is assembled rather
than transcribed: L2's `gen_ai.output.messages` carries one `tool_call` part,
and s1 here carries two of the same shape.

```json
[{"role":"assistant","parts":[
   {"arguments":{"supplier":"alpha"},"name":"alpha","id":"call_a","type":"tool_call"},
   {"arguments":{"supplier":"beta"},"name":"beta","id":"call_b","type":"tool_call"}],
  "finish_reason":"tool_calls"}]
```

What licenses it is that `gen_ai.output.messages` is a **list of parts** in the
capture, and a second part of a shape already observed is not a new claim about
the dialect — the *shape* of every part is transcribed, only the count is not.
This is the weakest provenance of the three renderings and is marked as such:
`FIXTURES.md` §5.1 forbids deriving a rendering from a reading, and the
distance between "one observed part, repeated" and "a reading" is short. A
capture with a genuine parallel call would retire this note. The 2b fleet
established that parallel calls are routine, so one is obtainable.

## Payloads

s2 and s3 carry only `gen_ai.operation.name`, `gen_ai.tool.name` and
`gen_ai.tool.call.id` — no `arguments`, no `result` — which is what makes both
payloads `absent` on both nodes, as the expected graph requires. L3 carries
both; their absence here is the scenario's subject.

It also means s2 and s3 have **no** unmapped attribute, so the single expected
`unmapped_attributes` diagnostic falls on s1 alone, matching the OpenInference
specimen.

## Observed keys deliberately omitted

As in `llm_tool_llm`, plus `gen_ai.usage.*` on s1: this scenario's expected
graph reports no usage. The capture carries it — omitted, not contradicted.

## What this rendering cannot make agree

1. **Payloads** — declared in `expected/comparison.json` (`FIXTURES.md` §4.4).
2. **`Node.name`** — the convention's `chat demo-model` / `execute_tool alpha`
   against the expected graph's `llm.plan` / `tool.alpha`, with no
   `comparison.json` declaring `name` dialect-varying. Not worked around here
   (`TASKS.md` 2.8).

## The mime this dialect never wrote

`Payload.mime` is `application/json` on every payload here, and **the dialect
emits no content-type attribute at all** — there is no counterpart to
OpenInference's `input.mime_type`. The `otel_genai` adapter reports it because
the convention *defines* `gen_ai.input.messages`, `gen_ai.output.messages`,
`gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` as structured
values; the OTLP exporter serializes them to JSON strings only because span
attributes cannot hold nested data. `ADAPTERS.md` §3 is the rule and its three
conditions; this note is the third one being met.

It is why `mime` is **not** declared dialect-varying on the `llm` payloads —
both dialects say `application/json` there — and why the `tool` payloads are
not declared at all. The alternative, `mime=None` with `value` left as the
source string, would have made tool payloads that agree byte for byte in the
two captured traces disagree at model level, and the corpus would have recorded
a serialization artifact as a finding.
