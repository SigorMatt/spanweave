# redacted_payload

An LLM span whose payloads the **instrumentor** suppressed.
`openinference-instrumentation` replaces a hidden value with the literal
string `__REDACTED__` rather than omitting the attribute — which is precisely
what keeps `redacted` and `absent` distinguishable here.

## Structure

Nodes: 1 `llm`.

Edges: none.

Node order: s0.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `redacted` | `redacted` |

`value` is `null` on both: there is no content to parse. The marker itself
survives verbatim in `Payload.raw` (erased by `canonical()`, since the marker
string is a dialect convention) and in `Node.raw`.

The library **marks what the source marked**. It never redacts anything
itself, and it never un-redacts anything either (`SPEC.md` §9).

## Usage

None reported.

## Diagnostics

None. A redaction the source performed is not a mapping failure.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
