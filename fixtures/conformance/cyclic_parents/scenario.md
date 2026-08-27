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
- [ ] `otel_genai` — **declared unrenderable** (`expected/coverage.json`)

Not because of the cycle — that is envelope, and expressible — but because this
scenario's canonical graph pins `kind: chain`, and no `gen_ai.operation.name`
value the adapter maps produces one. The convention's `invoke_workflow` is a
real candidate and is deliberately *not* mapped; see `coverage.json` for what
was checked.

**The declaration's grounds changed at `TASKS.md` 2.16, and it is worth reading
which half.** It used to rest partly on *"no captured GenAI trace contains an
`invoke_workflow` span"*. One now does (`fixtures/captured/genai_workflow.jsonl`),
so that half is retired. What remains is the half that always did the work —
mapping `invoke_workflow` to `chain` is a judgement, not a name match — and the
capture argues *against* taking it rather than for it, because the span in it is
harness-emitted and no instrumentor can ever emit one.

**This scenario is one decision away and nothing else.** With the mapping made,
the rendering recorded at `TASKS.md` 2.16 reproduces `expected/graph.json`
exactly: `name` compared, no `comparison.json`, no edit to the expected graph.
That was measured, not predicted.
