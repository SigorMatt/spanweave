# `declared_data_edge` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

`s1` from **L3** (result kept, arguments dropped, `gen_ai.tool.call.id` kept so
the span is a fulfiller with nothing requesting it) and `s2` from **L4**, whose
`gen_ai.input.messages` carries the `tool_call_response` part verbatim in
shape. `gen_ai.response.finish_reasons` is kept because it is observed on both
chat spans and is what produces the single expected `unmapped_attributes`.

## §4.2.1, by a second mechanism

This is the second scenario carrying the declared `data` edge in both dialects,
and the mechanisms have nothing in common:

| | how the span says "I was given the result of call X" |
|---|---|
| OpenInference | a flat attribute key, `llm.input_messages.2.message.tool_call_id` |
| OTel GenAI | a part with `"type": "tool_call_response"` **inside** the `gen_ai.input.messages` payload |

The edge, its `warrant` and its `basis` come out identical because the
**builder** produces all three. An adapter only reports which call ids a span
was given the results of (`received_call_ids`); it cannot name the producer,
because it sees one span at a time. That division is what keeps a `basis`
string out of adapter hands here — see `TASKS.md` 2.11 on the two places where
it is not.

## What agrees and what does not

`s1.outputs` is declared **nowhere**: `gen_ai.tool.call.result` and
`output.value` agree in value and mime. `s2`'s two payloads are declared for
`value` only — the envelope-versus-conversation finding — and `mime` agrees.
