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

## Seeded (Phase 1) — all of `FIXTURES.md` §3

Structural: `single_tool_call`, `llm_tool_llm` (the reference scenario),
`parallel_tools`, `nested_agents`, `retriever_and_embedding`, `span_links`,
`declared_data_edge`.

Degenerate — where honesty is actually tested, and not optional:
`missing_payloads`, `empty_payload`, `redacted_payload`, `unpaired_tool_call`,
`orphan_parent`, `clock_skew`, `unknown_kind`, `malformed_payload_json`,
`duplicate_span_ids`, `cyclic_parents`, `shuffled_order`.

Every one has an OpenInference rendering and a reviewed expected graph, with
two deliberate exceptions:

- **`declared_data_edge` has no rendering.** OpenInference declares no
  producer→consumer relation, so there is nothing to transcribe; writing a
  rendering would mean inventing an attribute and asserting the instrumentor
  emits it. Its `scenario.md` says so, and the mechanism is covered at the
  builder level instead.
- **`duplicate_span_ids` has no expected graph.** It must not build. Its
  expectation is an `expected/error.json`.

See `FIXTURES.md` §3 for what each must produce, and §1 for the two optional
files (`comparison.json`, `error.json`).
