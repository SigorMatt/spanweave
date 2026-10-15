# orphan_parent

A span whose `parent_id` names a span that is not in this input. An ordinary
situation: a trace exported mid-run, or filtered, or sampled.

## Structure

Nodes: 1 `tool`. **The node is kept.** Dropping the record would lose far more
than the missing parent did.

Edges: none. No `parent` edge is made to a span that is not here, and none is
invented to a substitute.

Node order: s1.

## Payloads

Both `absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `orphan_parent` | 1 | s1 |

The diagnostic carries the missing parent's id, so a consumer can tell which
reference dangled.

## Cross-dialect notes

In this graph s1 has no `parent` edge, but it states a parent, and for the
temporal rule a node's sibling group is the parent it **states** (`SPEC.md`
§4.3). So s1 is ordered against nothing: it states an absent parent, which
makes it neither a root nor a root's sibling, and no other node here states
that parent. The case with company is `orphan_siblings`.

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.10)

`name` is declared dialect-varying (`expected/comparison.json`), for the reason
given in `missing_payloads`. Nothing else is declared: a dangling `parent_id`
is an envelope fact, identical in both dialects, so the diagnostic is reached
by the same route in both.
