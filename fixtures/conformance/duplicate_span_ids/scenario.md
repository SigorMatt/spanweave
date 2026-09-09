# duplicate_span_ids

Two records claiming the same span id, differing in everything else. **Both are
kept.** The dialect's ids are not unique, so neither record qualifies for
`SPEC.md` §3.6 rule 1; they share a source key, so rule 3 derives an id for
each from the record itself, and `duplicate_source_id` reports the reuse.

## Expected outcome

- two `tool` nodes, one per record, in start-time order;
- one `temporal` edge between them — they are siblings at trace root;
- one `duplicate_source_id` diagnostic, naming the reused id `s1`.

Nothing is dropped and nothing is merged. A silent overwrite would lose a
record, and losslessness is not negotiable (`CLAUDE.md` 2): a graph that
quietly contains three of your four tool calls is worse than no graph, because
nothing downstream can tell.

A reference to `s1` would resolve to **neither** node — two records answer to
that id and picking one would be a guess. This scenario has no such reference;
`tests/test_build.py` carries one.

## Why the ids are `n0` and `n1`

Derived ids include the adapter id by `SPEC.md` §3.6, so two faithful
renderings of one run cannot produce the same one. `canonical()` compares
derived ids by position instead (`FIXTURES.md` §4.1) — this scenario is the
first in the corpus that needs it, and the first that has any node with a
derived id at all.

## This scenario used to be a refusal

Until batch A3 it carried `expected/error.json`: a duplicated span id raised
`DuplicateNodeIdError` and the whole file was refused. Both records fell to
rule 2, whose material was the source key — which *is* the span id — so the
two derived the same id and collided.

The September 2026 audit recorded that as finding 2: a duplicate a dialect has
no way to prevent cost a consumer the entire trace, and `SPEC.md` §3.7 had
always described the `duplicate_source_id` diagnostic that was supposed to fire
instead. It could not: nothing could reach it. Rule 3 is what makes the
documented fallback reachable, and it disambiguates on the record's content
rather than on its position, because a position is input order and input order
must not decide anything (`CLAUDE.md` 4).

The hard error is not gone — a record is still never overwritten — but no trace
file reaches it now (`SPEC.md` §3.6).

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.10)

`expected/comparison.json` declares `name` dialect-varying, like almost every
other cross-dialect scenario: the two instrumentors spell a tool span's name
differently and always have (`FIXTURES.md` §4.4).
