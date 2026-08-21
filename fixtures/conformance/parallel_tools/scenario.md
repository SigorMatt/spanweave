# parallel_tools

An agent span containing three tool spans whose lifetimes overlap. Two of them
(`s1`, `s2`) report the **same** start time.

This is the tie-break scenario. Ordering by start time alone leaves s1 and s2
undecided, and an undecided order is a determinism bug that only shows up on
someone else's machine. The stated rule is `(started_at, node_id)` ascending,
so s1 precedes s2 because `"s1" < "s2"` -- for no better reason than that the
rule has to say something and this is what it says (`SPEC.md` §4.3).

## Structure

Nodes: 1 `agent`, 3 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2, s0→s3 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3 |

Note what is **not** there: no s1→s3 temporal edge. Only consecutive siblings
are joined; the closure is available from `graph.reachable(...)`.

Node order: s0, s1, s2, s3.

## Payloads

s0 has an input; the tool spans report neither an input nor an output, so both
are `absent`.

## Diagnostics

None. Overlapping spans are ordinary, not a problem to report.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
