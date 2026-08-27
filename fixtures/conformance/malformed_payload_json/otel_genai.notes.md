# `malformed_payload_json` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L3**, with `gen_ai.tool.call.result` truncated mid-string —
`{"status": "shipp` — and every other attribute except the operation and the
tool name dropped.

## Why the payload is declared nowhere

The two dialects agree on all three compared fields (`present`,
`application/json`, `value: null`) and reach them by **opposite routes**, which
is worth more than the agreement itself:

- OpenInference is *told* the content type by `output.mime_type`, tries to
  parse, and fails.
- OTel GenAI is told nothing. The adapter reports `application/json` because
  the convention **defines** `gen_ai.tool.call.result` as a structured value
  (`ADAPTERS.md` §3, "a mime the dialect defines but does not emit"), tries to
  parse, and fails.

So this scenario is also the test that the ADAPTERS.md §3 rule **degrades
honestly**: the third condition of that rule is that a parse failure must stay
`present` with `raw` kept and a `payload_parse_failed` diagnostic, never
silently downgraded to `absent` because the mime was the adapter's own claim.
A rule that only worked when the content parsed would be worthless here.
