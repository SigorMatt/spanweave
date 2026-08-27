# `shuffled_order` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

Not a new rendering. This file is `llm_tool_llm/dialects/otel_genai.jsonl`
**line for line**, reordered to s2, s0, s3, s1 — the order this scenario's
OpenInference rendering already uses. The two scenarios' `expected/graph.json`
files are byte-identical, so provenance is `llm_tool_llm`'s in full and there
is nothing further to derive.

That identity is the point. Any difference between these two scenarios in
either dialect is an ordering defect and can be nothing else: same bytes, same
expectation, only the line order moved. It also means the declarations here are
`llm_tool_llm`'s, unchanged — copying the reasoning would let the two drift.
