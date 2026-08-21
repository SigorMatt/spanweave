# parallel_tools

An agent span containing three tool spans whose lifetimes overlap. Two of them
(`s1`, `s2`) report the **same** start time.

This is the tie-break scenario. Ordering by start time alone leaves s1 and s2
undecided, and an undecided order is a determinism bug that only shows up on
someone else's machine. The stated rule is `(started_at, node_id)` ascending,
so s1 precedes s2 because `"s1" < "s2"` — for no better reason than that the
rule has to say something and this is what it says (`SPEC.md` §4.3).

And because that is *all* it is, the s1→s2 edge says so: it carries a
different `basis` from a genuinely ordered pair. Neither span started first,
so an edge claiming precedence would be false — which is the exact failure
this project exists to prevent, and it would have been frozen into this
expected graph. The edge is kept (a partial order would not be deterministic,
and dropping it would break the sibling chain) and it is **labelled**, so a
consumer can tell the two apart by reading the graph rather than by
re-deriving the timestamps.

## Structure

Nodes: 1 `agent`, 3 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2, s0→s3 |
| `temporal` | derived | `sibling start_time ordering (tied, broken by node_id)` | s1→s2 |
| `temporal` | derived | `sibling start_time ordering` | s2→s3 |

Note what is **not** there: no s1→s3 temporal edge. Only consecutive siblings
are joined; the closure is available from `graph.reachable(...)`.

Note also which edge is tied and which is not. s1 and s2 both start at 1000.2,
so their edge is the tie-broken one; s3 starts at 1001.0, strictly later than
s2, so s2→s3 is an observation.

Node order: s0, s1, s2, s3.

## Payloads

s0 has an input; the tool spans report neither an input nor an output, so both
are `absent`.

## Diagnostics

None. Overlapping spans are ordinary, not a problem to report.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
