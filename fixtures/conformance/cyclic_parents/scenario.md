# cyclic_parents

Two spans, each claiming the other as its parent. Telemetry should not produce
this and occasionally does.

## Structure

Nodes: 2 `chain`. **Both are kept.**

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s1→s2, s2→s1 |

Both parent references resolve, so both edges are real. The graph is a cycle,
and the library transcribes it rather than breaking it: the telemetry said
this, and editing it would be a different kind of lie than the one being
avoided.

No temporal edges: each node is the only member of its sibling group.

Node order: s1, s2. Nothing can be sorted topologically here, so the whole
residual set falls back to the tie-break — `(started_at, node_id)` — which is
already total and already deterministic.

## Diagnostics

| Code | Count |
|---|---|
| `ordering_cycle` | 1 |

The diagnostic names every node it could not order.

## What must not happen

The build must not hang, must not raise, and must not drop a node. A hang is a
denial of service when this runs inside CI or a pipeline (`SECURITY.md`).

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
