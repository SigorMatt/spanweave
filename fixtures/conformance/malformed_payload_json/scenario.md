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
- [x] `otel_genai` — Phase 2 (2.10)

`name` is declared dialect-varying (`expected/comparison.json`). The payload is
**not** — and that is worth reading twice, because the two dialects arrive at
`present` / `application/json` / `value: null` from opposite directions.
OpenInference is *told* the mime by `output.mime_type` and fails to parse it.
OTel GenAI is told nothing: the adapter reports `application/json` because the
convention *defines* `gen_ai.tool.call.result` as a structured value
(`ADAPTERS.md` §3), and then fails to parse it. Same three fields, same
diagnostic, two different reasons for believing the content type.
