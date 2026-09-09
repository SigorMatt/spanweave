# `duplicate_span_ids` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

Two copies of **L3**, differing only in tool name and timestamps, both claiming
`span_id` `s1`. `span_id` is an OTel span field; neither dialect can prevent a
collision and neither has an attribute that would.

The two renderings agree on the canonical graph — two `tool` nodes, one
`temporal` edge, one `duplicate_source_id` — with two things set aside, both
declared rather than assumed:

- `name`, in `expected/comparison.json`, as almost everywhere else: this
  dialect names a tool span `execute_tool alpha` where OpenInference names it
  `tool.alpha`.
- the node **ids**, by `FIXTURES.md` §4.1: they are derived (`SPEC.md` §3.6
  rule 3) and derived ids carry the adapter id, so `canonical()` compares them
  positionally as `n0` and `n1`.

Until batch A3 this rendering asserted §4.2's equivalence half instead — both
dialects had to raise `DuplicateNodeIdError`. They no longer refuse; they
agree on a graph, which is the stronger form of the same claim.
