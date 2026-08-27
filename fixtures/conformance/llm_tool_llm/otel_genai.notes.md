# `llm_tool_llm` — provenance of the `otel_genai` rendering

Every attribute in `dialects/otel_genai.jsonl` is traceable to a line of
`fixtures/captured/genai_tool_call.jsonl` (`FIXTURES.md` §5.1). Capture lines
are 1-indexed: **L1** the `invoke_agent` span, **L2** the LLM turn that
requested a tool call, **L3** the `execute_tool` span, **L4** the LLM turn that
answered.

The capture is one run of exactly this shape, so this scenario is a
transcription rather than a reconstruction.

## Attribute by attribute

| Rendering | Attribute | Captured at | Note |
|---|---|---|---|
| s0 | `gen_ai.operation.name` = `invoke_agent` | L1 | the kind marker |
| s0 | `gen_ai.input.messages` | L1 | verbatim shape; text swapped for the scenario's |
| s1, s3 | `gen_ai.operation.name` = `chat` | L2, L4 | |
| s1, s3 | `gen_ai.request.model` | L2, L4 | → `operation` and `attributes.model` |
| s1, s3 | `gen_ai.response.finish_reasons` | L2 (`["tool_calls"]`), L4 (`["stop"]`) | a **list**, not a string, in the capture — rendered as one |
| s1, s3 | `gen_ai.usage.input_tokens` / `.output_tokens` | L2, L4 | ints; the dialect reports no total |
| s1, s3 | `gen_ai.input.messages` | L2, L4 | L4's is the 3-message history, transcribed below |
| s1, s3 | `gen_ai.output.messages` | L2 (a `tool_call` part), L4 (a `text` part) | |
| s2 | `gen_ai.operation.name` = `execute_tool` | L3 | |
| s2 | `gen_ai.tool.name`, `gen_ai.tool.call.id` | L3 | |
| s2 | `gen_ai.tool.call.arguments`, `.result` | L3 | serialized by the **application**, so they carry `json.dumps` spacing; the message attributes are serialized by the instrumentor and are compact. Both spacings are as captured. |

## The two shapes this scenario turns on

**A requested call**, from L2's `gen_ai.output.messages`:

```json
[{"role":"assistant","parts":[{"arguments":{"city":"Paris"},"name":"get_weather","id":"chatcmpl-tool-ba26764988bf8aa9","type":"tool_call"}],"finish_reason":"tool_calls"}]
```

**A received result**, from L4's `gen_ai.input.messages` — the third message:

```json
{"role":"tool","parts":[{"response":"{\"city\": \"Paris\", \"celsius\": 18, \"summary\": \"clear\"}","id":"chatcmpl-tool-ba26764988bf8aa9","type":"tool_call_response"}]}
```

The `type` discriminates. A `tool_call` part in **output** messages is a
request; a `tool_call_response` part in **input** messages is a result the span
was given. L4 also carries the assistant's `tool_call` part again, in its
**input** messages — the history echo — and it must not be read as a request
(`SPEC.md` §4.4). The dialect draws the same distinction OpenInference draws
with `output_messages` / `input_messages`, by a different mechanism.

**This is the §4.2.1 declaration, and dialect two has it.** The `data` edge
s2→s3 was the thing 2.9's HALT text expected might be unrenderable here. It is
not: the `id` on the `tool_call_response` part is the tool call id, so the
relation is stated and the edge is `explicit`.

## Observed keys deliberately omitted

Trimmed by omission only. Each of these is present in the capture and carries
nothing this scenario asserts; the OpenInference specimen omits the same class
of key (it carries none of the capture's `llm.system`,
`llm.tools.0.tool.json_schema`, `llm.invocation_parameters`, or
`llm.token_count.prompt_details.cache_read`).

| Omitted | On | Why |
|---|---|---|
| `gen_ai.agent.name` | L1 | conditionally required "if available"; an anonymous `invoke_agent` span is valid |
| `gen_ai.provider.name` | L2, L4 | unmapped either way; `gen_ai.response.finish_reasons` already carries the unmapped-key diagnostic |
| `server.address` | L2, L4 | names the endpoint that answered; not this scenario's subject |
| `gen_ai.response.model`, `gen_ai.response.id` | L2, L4 | |
| `gen_ai.tool.definitions` | L2, L4 | the tool inventory; unmapped in both dialects |
| `openai.response.system_fingerprint` | L2, L4 | provider-specific, not a GenAI key |
| `gen_ai.tool.type` = `function` | L3 | optional; would put an unmapped key on s2 |

**The choice that deserves review** is which spans end up carrying an unmapped
key, because `unmapped_attributes` is emitted **once per span** and the
expected graph pins the count at 2. Here s1 and s3 carry one and s0 and s2
carry none, matching the OpenInference specimen. That is a property of the
*specimen*, not of the dialect — both dialects emit far more than either
specimen carries — but it is a fixture-authoring choice made with the expected
count in view, and it is recorded here rather than left implicit.

## Two things this rendering cannot make agree

Not worked around here (`TASKS.md` 2.8: an unproducible expectation is 2.9's
HALT, not an edit).

1. **Payloads.** Declared dialect-varying in `expected/comparison.json`
   (`FIXTURES.md` §4.4). OpenInference records an LLM span's request envelope;
   GenAI records the normalized conversation, and states no mime at all.
2. **`Node.name`.** `chat demo-model` / `execute_tool lookup` are the
   convention's span names, and they are not `llm.plan` / `tool.lookup`. This
   scenario already declares `name` dialect-varying, so it does not bite here —
   but `tool_call_history_echo` and `parallel_tool_calls` do not, and it bites
   there.
