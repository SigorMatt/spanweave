# duplicate_span_ids

Two records claiming the same span id. **This scenario has no expected graph,
because it must not produce one.**

## Expected outcome

A hard error: `DuplicateNodeIdError`, naming the id and both records. The
expectation lives in `expected/error.json` rather than `expected/graph.json`.

Almost everything else in this corpus degrades into a diagnostic. This does
not, and the difference is worth stating. A silent overwrite would drop a
record, and losslessness is not negotiable (`SPEC.md` §3.6, `CLAUDE.md` 2). A
graph that quietly contains three of your four tool calls is worse than no
graph, because nothing downstream can tell.

The two rules of §3.6 interlock here: a span id that is *not unique* fails
rule 1's condition and falls through to the derived id of rule 2 — where,
because this adapter's source key **is** that same span id, both records
derive the same id and collide. The collision is what raises.

An adapter that gave the two records distinct source keys would instead
produce two nodes and a `duplicate_source_id` diagnostic, losing nothing. Both
paths keep every record; neither guesses.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
