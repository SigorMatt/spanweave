# `clock_skew` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the `invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the `execute_tool` span, **L4** the follow-up turn). Same vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is repeated.

**L1** and **L3** twice, with two timestamps degraded:

| Span | Change | Expected diagnostic |
|---|---|---|
| s1 | `end_time` set before `start_time` | `nonmonotonic_time` |
| s2 | `start_time` set to `null` | `missing_timestamp` |

Both captures export `start_time` / `end_time` as Unix seconds at the record
level — `1787781725.9583309` in L1 — so timestamps are envelope, not dialect.
Neither degradation touches a `gen_ai.*` attribute, and nothing but `name` is
declared.

`null` for a timestamp is a degradation by hand: no observed span omits one.
It is a change of value within an observed field, not an invented field, which
is the line `FIXTURES.md` §5.1 draws.
