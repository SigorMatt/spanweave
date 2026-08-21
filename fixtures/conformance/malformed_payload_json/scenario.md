# malformed_payload_json

A tool span whose output declares `application/json` and is not valid JSON —
a truncated write, which is what this usually is in the wild.

## Structure

Nodes: 1 `tool`.

Edges: none.

Node order: s0.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `absent` | `present`, `value` is `null` |

The state stays **`present`**, not `empty` and not `absent`: something *was*
reported, and the library simply could not read it. `Payload.raw` keeps the
text verbatim — `canonical()` erases it, because payload encoding is
dialect-specific, so the corpus checks it separately against the serialized
graph.

Note also what the state is not: `truncated`. That state means *the source
said it truncated the value*. Nobody said so here; we merely failed to parse
something. Inferring truncation from a parse failure would be reading a claim
into the data.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `payload_parse_failed` | 1 | s0 |

Never an exception. A malformed payload in one span must not cost a consumer
the other 9,999 (`SECURITY.md`).

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
