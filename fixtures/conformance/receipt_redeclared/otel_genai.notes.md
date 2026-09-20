# `receipt_redeclared` — provenance of the `otel_genai` rendering

**Constructed, not captured.** Said first because `FIXTURES.md` §5.1 is about
exactly this risk: a rendering written from a reading of the dialect can agree
with an adapter written from the same reading, and neither is then tested
against the world.

Every attribute here is taken from a rendering that *is* traceable to a
capture — `tool_call_history_echo/otel_genai.jsonl`, itself derived from
`fixtures/captured/genai_tool_call.jsonl` — with one span pair appended in the
same shape. Nothing new is invented: `gen_ai.operation.name`,
`gen_ai.request.model`, `gen_ai.response.finish_reasons`,
`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.name`,
`gen_ai.tool.call.id` and `gen_ai.tool.call.result` are the observed keys, in
the observed encodings.

**What is not observed is the multi-receipt shape itself.** No trace in this
repo carries a call id received by more than one span, in either dialect
(`OPEN_QUESTIONS.md` §11: 3 captured files, 4 `data` edges, 0
re-declarations, tracked files only). Every capture is a single tool round. The falsifying
experiment is named in §11(e) — one capture with ≥5 tool-calling turns — and
until it exists this scenario is a construction and says so.

## The same property, by a different mechanism

| | how a span says "I was given the result of call X" |
|---|---|
| OpenInference | a flat key, `llm.input_messages.N.message.tool_call_id` |
| OTel GenAI | a part with `"type": "tool_call_response"` **inside** `gen_ai.input.messages` |

s5's `gen_ai.input.messages` carries **two** such parts, one of which repeats
the part s3 already carried. The adapter reports both ids on s5 and nothing
else; it cannot know that s3 was shown `call_a` first, because it sees one
span. The rank, and therefore the third basis, is the builder's
(`SPEC.md` §4.2.1).

## What agrees and what does not

The `execute_tool` spans (s2, s4) agree with their OpenInference counterparts
byte-for-byte in both payload fields, so nothing about them is declared. The
three `chat` spans disagree on `value` only, in both directions, for the
reason `declared_data_edge` records: OpenInference keeps the request envelope
and the provider response, this dialect keeps the normalized conversation, and
neither is a re-encoding of the other. `mime` agrees everywhere —
`ADAPTERS.md` §3, "a mime the dialect defines but does not emit".

`gen_ai.response.finish_reasons` is kept because it is observed on every chat
span and is what produces the single expected `unmapped_attributes` per span.
