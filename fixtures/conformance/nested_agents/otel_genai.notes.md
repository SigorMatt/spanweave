# `nested_agents` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L1** twice and **L3** once, all payload attributes dropped. Three spans,
three attributes between them.

## The two agent spans have the same name, and that is correct

Both render as `invoke_agent`, so within this dialect `s0` and `s1` are
indistinguishable by name. The capture shows why: L1's span name is
`"invoke_agent agent.run"`, where the second half comes from
`gen_ai.agent.name`. This adapter deliberately does not read that attribute as
`operation` — an agent's name is not a tool, model or retriever name
(`SPEC.md` §3.2) — and this rendering does not carry it, because the scenario
does not assert anything about agent naming and a key that changes nothing but
the unmapped list is noise.

Containment is carried entirely by `parent_id`, which is a record-level field
both dialects share. That is the whole of what this scenario asserts, and it
is why two identically-named agent nodes are not a problem: the graph
distinguishes them by id and by edge, never by name.
