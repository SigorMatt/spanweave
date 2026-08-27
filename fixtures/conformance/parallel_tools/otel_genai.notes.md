# `parallel_tools` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L1** for `s0` and **L3** three times, with the tool names changed and the
timestamps this scenario needs. `gen_ai.tool.call.id`, `.arguments` and
`.result` are dropped from all three, which is what makes their payloads
`absent` and leaves them with no unmapped attribute.

## What is being tested is not in the dialect at all

`s1` and `s2` share a `start_time`. The order is settled by node id, and the
edge says so — `sibling start_time ordering (tied, broken by node_id)`. Both
the rule and the `basis` string are the **builder's**, so both dialects
produce the identical edge from identical timestamps.

That is the interesting part of rendering this scenario twice: it confirms the
tie-break is not reachable from a dialect. An adapter cannot influence it,
because by the time ordering happens there is no dialect left.

## Declared

`name`, and `s0.inputs` in `mime` and `value` — the agent span, where
OpenInference reports a bare string at `text/plain` against this dialect's
message array. The three tool spans are declared nowhere.
