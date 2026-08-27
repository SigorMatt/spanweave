# `single_tool_call` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L3**, with its values swapped for this scenario's and `gen_ai.tool.call.id`
and `gen_ai.tool.type` dropped so the span neither pairs nor reports an
unmapped attribute. Every key present is a key L3 carries.

## Why nothing but `name` is declared

`gen_ai.tool.call.arguments` and `.result` agree with `input.value` and
`output.value` in **both** `value` and `mime`. That is not a coincidence of
this fixture: it is the byte-for-byte agreement the 2.6 matched pair showed on
tool spans, where the two dialects record the same fact because a tool call's
arguments have no envelope to disagree about.

So the smallest scenario in the corpus is also the cleanest statement of its
claim — one run, two instrumentors sharing no attribute name, one graph, and
the only thing set aside is a span name the GenAI convention prescribes.
