# orphan_siblings

One root span with one child, and two spans whose `parent_id` names the
**same** span, which is not in this input. `orphan_parent`'s situation with
company: the question it cannot ask, because it has one node, is what an
orphan is ordered against.

The answer is `SPEC.md` §4.3's rule: a node's sibling group is the parent it
**states**, whether or not the input carries it. So the two orphans are
siblings of each other and of nothing else. They are not the root's siblings
(the root states no parent), and not the root's child's (that one states
`s0`), however their timestamps interleave with either.

## Structure

Nodes: 1 `agent`, 3 `tool`. Every node is kept; neither orphan is dropped or
re-parented.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1 |
| `temporal` | derived | `sibling start_time ordering` | s2→s3 |

Note what is **not** there. No `parent` edge into s2 or s3: their parent is
not here, and none is invented to a substitute. No `temporal` edge between an
orphan and s0, although s0 started first and is the only other node at trace
root; and none between an orphan and s1, although s1 started first and is the
only other node with a stated parent. s0 and s1 are each alone in their
groups, so they get no `temporal` edge at all.

Node order: s0, s1, s2, s3.

## Payloads

All `absent`: no span reports a payload attribute.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `orphan_parent` | 2 | s2, s3 |

## Dialects

- [x] `openinference`
- [x] `otel_genai`

`name` is declared dialect-varying (`expected/comparison.json`), for the
reason given in `missing_payloads`. Nothing else is declared: a dangling
`parent_id` is an envelope fact, identical in both dialects, and the sibling
rule is the builder's, so both dialects reach the same two edges by the same
route.
