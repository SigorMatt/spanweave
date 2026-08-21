# fixtures/conformance/

The conformance corpus. Contract and authoring rules: `FIXTURES.md`.

One directory per scenario:

```
<scenario_id>/
  scenario.md            # what happens, described semantics-free
  dialects/<dialect>.*   # one rendering per supported dialect
  expected/graph.json    # THE canonical graph — one per scenario, not per dialect
  expected/diagnostics.json
```

**The rule this corpus exists to enforce:** every dialect rendering of a
scenario must produce that scenario's single canonical graph. Run it with
`make conformance`.

If your adapter fails, the adapter is wrong — or the model is. Finding out which
is the point. **Do not edit an expected graph to make a test pass**
(`FIXTURES.md` §4).

## Seeded (Phase 1)

- `llm_tool_llm` — the reference scenario.

## To seed (Phase 1, `TASKS.md` 1.9)

Structural: `single_tool_call`, `parallel_tools`, `nested_agents`,
`retriever_and_embedding`, `span_links`, `declared_data_edge`.

Degenerate — where honesty is actually tested, and not optional:
`missing_payloads`, `empty_payload`, `redacted_payload`, `unpaired_tool_call`,
`orphan_parent`, `clock_skew`, `unknown_kind`, `malformed_payload_json`,
`duplicate_span_ids`, `cyclic_parents`, `shuffled_order`.

See `FIXTURES.md` §3 for what each must produce.
