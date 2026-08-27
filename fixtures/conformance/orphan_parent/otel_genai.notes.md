# `orphan_parent` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L3**, with the payload and id attributes dropped and `parent_id` pointed at a
span that is not in the file. `parent_id` is an OTel span field, not a
`gen_ai.*` attribute — identical in both dialects and in both captures — so
this rendering is a transcription with one value changed.

That is also what it proves: the diagnostic is reached by the same route in
both dialects, so `orphan_parent` is a property of the envelope rather than of
either convention. Nothing but `name` is declared.
