# single_tool_call

The minimum viable trace: one tool span, with an input and an output, and
nothing else.

It is here because the smallest case is the one a naive implementation gets
wrong in the most interesting way -- a single node has no siblings, so it must
produce **no** temporal edge, and no parent edge either.

## Structure

Nodes: 1 `tool`.

Edges: none. One node cannot be in a relation.

Node order: s0.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `present` (application/json) | `present` (application/json) |

## Usage

None. The dialect reports no token counts on a tool span.

## Diagnostics

None.

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.11)

Only `name` is declared. Both payloads agree in **both** fields — a tool
call's arguments and result are `application/json` in both dialects and carry
the same values, which is the byte-for-byte agreement the 2.6 matched pair
showed. The minimum viable trace is therefore also the minimum viable
cross-dialect claim: two instrumentors, no declaration but a span name.
