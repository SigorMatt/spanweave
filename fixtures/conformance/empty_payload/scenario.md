# empty_payload

A tool span whose payload attributes **are** present and **are** empty: an
empty string in, an empty JSON object out.

The contrasting case to `missing_payloads`, and the reason the model keeps
five payload states rather than a nullable string.

## Structure

Nodes: 1 `tool`.

Edges: none.

Node order: s0.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `empty` (text/plain, value `""`) | `empty` (application/json, value `{}`) |

Both are `empty`, neither is `absent`. The value is kept as reported: an empty
string is a value, and so is an empty object.

## Diagnostics

None.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
