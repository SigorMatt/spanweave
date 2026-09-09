# fixtures/conformance/

The conformance corpus. Contract and authoring rules: `FIXTURES.md`.

One directory per scenario:

```
<scenario_id>/
  scenario.md               # what happens, described semantics-free
  <dialect>.notes.md        # provenance of that dialect's rendering (§5.1)
  dialects/<dialect>.*      # one rendering per supported dialect
  expected/graph.json       # THE canonical graph — one per scenario, not per dialect
  expected/diagnostics.json
  expected/error.json       # instead of graph.json, where the scenario must NOT build (§4.2)
  expected/comparison.json  # what this scenario declares dialect-varying (§4, §4.4, §4.5)
  expected/payloads/<dialect>.json   # that dialect's own values for what it declared (§4.4)
  expected/coverage.json    # dialects that cannot render this scenario, with a reason (§4.3)
```

**The rule this corpus exists to enforce:** every dialect rendering of a
scenario must produce that scenario's single canonical graph. Run it with
`make conformance`.

If your adapter fails, the adapter is wrong — or the model is. Finding out which
is the point. **Do not edit an expected graph to make a test pass**
(`FIXTURES.md` §4).

## Coverage

Two dialects: `openinference` (Phase 1) and `otel_genai` (Phase 2). Since
`TASKS.md` 2.13 both are named in `tests/conformance.py:DIALECTS`, which turns
on §4.3's **silence is a failure** rule for the whole corpus: every scenario
must either render each dialect or declare in `coverage.json` that it cannot,
with a reason. There is no third state, and no exemption list.

The pytest header prints the live numbers on every run — scenarios, renderings
per dialect, how many are compared *across* dialects, and how many declarations
stand. Read those rather than a list here, which would go stale.

## Scenarios

Seeded in Phase 1, from `FIXTURES.md` §3.

Structural: `single_tool_call`, `llm_tool_llm` (the reference scenario),
`parallel_tools`, `parallel_tool_calls`, `nested_agents`,
`retriever_and_embedding`, `span_links`, `declared_data_edge`.

Degenerate — where honesty is actually tested, and not optional:
`missing_payloads`, `empty_payload`, `redacted_payload`, `unpaired_tool_call`,
`orphan_parent`, `clock_skew`, `unknown_kind`, `malformed_payload_json`,
`duplicate_span_ids`, `cyclic_parents`, `shuffled_order`,
`tool_call_history_echo`.

Added since, each for a reason recorded at its task:

- **`unset_and_error_status`** (2.10). The corpus was 18-of-18 tool spans
  `ok` while no real tool span was. A consumer written against it computed a
  success rate that read zero against real telemetry (finding F6).
- **`derived_ids`** and **`derived_ids_shuffled`** (September 2026 audit,
  batch A5). All 177 records in the corpus carried a span id, so every node id
  in it was a string a dialect supplied and `SPEC.md` §3.6 rule 2 — the
  derived-id path — was exercised by nothing. The fallback key it went
  unwatched with was the record's **1-based index**, so a file of span-id-less
  records rebound its ids when its lines were swapped, and `shuffled_order`
  could not see it because its records have span ids. These two are that
  scenario and its reordered twin, where the id is computed rather than
  quoted.
- **`timestamp_units`** (September 2026 audit, batch C1). Nothing in the
  corpus reported a timestamp in anything but seconds, and nothing reported
  one the library could not read, so neither `timestamp_unit_suspect` nor a
  refused rendering was exercised anywhere (audit finding 5). It is also the
  one scenario whose two renderings deliberately differ in **encoding** —
  nanosecond integers against the same values as decimal strings — because
  that is the equality `SPEC.md` §3.1 claims.

## Three things this README used to get wrong, kept as a warning

- **`declared_data_edge` "has no rendering."** It did not, on the stated
  grounds that OpenInference declares no producer→consumer relation. It does,
  in every multi-turn trace, and the corpus had been carrying it in `unmapped`
  for a whole phase. The `coverage.json` was deleted and the scenario rendered.
  A `renderable: false` is an **invitation to check the reason against observed
  output**, never a settled fact (`FIXTURES.md` §4.3).
- **`duplicate_span_ids` has no expected graph.** Written as "that one is
  still true: it must not build". It builds. Batch A3 of the September 2026
  audit series made two records claiming one span id derive an id each from
  their own content (`SPEC.md` §3.6 rule 3): both are kept, the reuse is
  reported as `duplicate_source_id`, and the scenario carries an
  `expected/graph.json` and an `expected/diagnostics.json` like every other.
  **No scenario in this corpus carries an `expected/error.json` today** —
  `FIXTURES.md` §4.2 says why the vacancy is honest rather than a gap.
  This bullet went on asserting the opposite for the whole of the audit
  series' first run, under a heading about getting things wrong, which is the
  warning making its own point: a **"still true" is a claim with a date on
  it**, and the date is the last time somebody checked.
  `tests/test_doc_truth.py` now reads this file for the claim rather than
  trusting the next reader to notice.
