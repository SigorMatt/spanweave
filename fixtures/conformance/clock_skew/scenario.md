# clock_skew

Two different ways a clock can fail a trace, in one scenario:

- `s1` reports an `end_time` **before** its `start_time`.
- `s2` reports **no** `start_time` at all.

## Structure

Nodes: 1 `agent`, 2 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2 |

**No temporal edges.** s2 is excluded from the temporal rule because it has no
start time, which leaves s1 alone in its sibling group, and a lone sibling has
nobody to be consecutive with.

Node order: s0, s1, s2. s2 sorts last because a node with no start time sorts
as `+inf` — last, but never dropped.

## Timestamps

s1 keeps **both** values exactly as reported: `started_at` 1001.0,
`ended_at` 1000.5. The library reports the skew and does not repair it. A
clock that ran backwards is a fact about the trace, and swapping the two
fields would hide it.

## Payloads

All `absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `missing_timestamp` | 1 | s2 |
| `nonmonotonic_time` | 1 | s1 |

`missing_timestamp` is `info`: it explains an omitted edge rather than
reporting something wrong.

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.10)

`name` is declared dialect-varying (`expected/comparison.json`). Nothing else
is declared. Timestamps are envelope, not dialect: both instrumentors export
`start_time` / `end_time` as Unix seconds, so an inverted pair and a missing
`start_time` degrade identically and produce the same two diagnostics.
