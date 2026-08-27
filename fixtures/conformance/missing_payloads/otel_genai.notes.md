# `missing_payloads` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

## The degradation

Transcribed from **L1** and **L3** with the payload attributes removed, and
nothing else changed:

| Span | Keys kept | Keys removed | Source |
|---|---|---|---|
| s0 | `gen_ai.operation.name` | `gen_ai.input.messages` | L1 |
| s1 | `gen_ai.operation.name`, `gen_ai.tool.name` | `gen_ai.tool.call.arguments`, `.result`, `.id`, `gen_ai.tool.type` | L3 |

Removal is the scenario's whole subject, and it is the one degradation §5.1
permits without qualification: an attribute the instrumentor did not emit is
exactly what an absent payload means. Nothing here is added.

## Observed keys deliberately omitted

`gen_ai.tool.type` (L3) and `gen_ai.agent.name` (L1). Both are real and both
would land in `unmapped_attributes`, which this scenario expects **none** of.
Omitting a key does not misstate the dialect; adding one would.

## What this rendering proves

Both payloads reach `absent` — not `empty` — through a dialect that spells
payloads with entirely different keys. `SPEC.md` §3.3's central distinction is
therefore a property of the model and not of one dialect's attribute set,
which is the smallest possible version of the corpus's whole claim.
