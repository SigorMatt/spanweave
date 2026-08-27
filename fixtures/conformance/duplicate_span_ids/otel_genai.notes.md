# `duplicate_span_ids` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

Two copies of **L3**, differing only in tool name and timestamps, both claiming
`span_id` `s1`. `span_id` is an OTel span field; neither dialect can prevent a
collision and neither has an attribute that would.

There is no `expected/graph.json` to compare, so this rendering asserts
§4.2's equivalence half instead: both dialects must raise `DuplicateNodeIdError`
with code `duplicate_node_id`. A dialect that *built* a graph where the other
refused would be a finding about the model, and this file is what would
surface it.
