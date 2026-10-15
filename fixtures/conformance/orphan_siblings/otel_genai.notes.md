# `orphan_siblings` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L1** for `s0` and **L3** three times, transcribed as `missing_payloads`
transcribes them: payload and id attributes dropped, tool names and
timestamps changed. `s2` and `s3` have `parent_id` pointed at one span that is
not in the file, as `orphan_parent` does with one.

`parent_id` is an OTel span field, not a `gen_ai.*` attribute, and the sibling
rule runs after the dialect is gone, so this rendering differs from the
OpenInference one only where every scenario's does: the span names and the
attribute keys. Nothing but `name` is declared.
