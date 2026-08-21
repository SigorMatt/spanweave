# nested_agents

An agent span containing a sub-agent span, which in turn contains a tool span.
Containment two levels deep.

## Structure

Nodes: 2 `agent`, 1 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s1→s2 |

No temporal edges: every sibling group here has exactly one member, and a lone
sibling has nobody to be consecutive with.

Node order: s0, s1, s2 — the topological sort, which here agrees with the
clock.

## Payloads

All `absent`: this scenario is about containment, and payloads would only make
it longer.

## Diagnostics

None.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
