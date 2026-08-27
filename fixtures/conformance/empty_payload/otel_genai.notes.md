# `empty_payload` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

## The degradation

**L3**, with the two payload attributes replaced by empty JSON containers:

| Attribute | L3 | here |
|---|---|---|
| `gen_ai.tool.call.arguments` | `{"city": "Paris"}` | `{}` |
| `gen_ai.tool.call.result` | `{"city": "Paris", "celsius": 18, ...}` | `{}` |

`gen_ai.tool.call.id` and `gen_ai.tool.type` are dropped so the span produces
neither a pairing nor an unmapped attribute.

## The mime this dialect never wrote

`application/json` on both payloads is the adapter's, not the instrumentor's:
the convention **defines** these two keys as structured values and the OTLP
exporter serializes them to JSON strings, so the adapter reports the content
type the convention fixes and parses accordingly (`ADAPTERS.md` §3). No
`gen_ai.*` content-type attribute exists anywhere in the capture.

## Why `s0.inputs` is declared and `s0.outputs` is not

`{}` at `application/json` is exactly what OpenInference's `output.value`
says, so the **outputs** agree in both fields and stay a tested claim.

The **inputs** cannot agree, and the reason is structural rather than
incidental. OpenInference's `input.value` is a free string carrying its own
`input.mime_type`, so it can say `""` at `text/plain`. This dialect's
`arguments` is a structured value: `""` is not valid JSON and would produce a
`payload_parse_failed` — a third fact, not the same one — so the only way the
dialect can say *empty* is an empty container. Both dialects reach
`state: empty`, which is the field the scenario exists to assert and the one
field no declaration may ever set aside (`FIXTURES.md` §4.4).
