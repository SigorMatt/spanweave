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
- [x] `otel_genai` — Phase 2 (2.10)

Both dialects say **empty**, and `state` is compared — no declaration may ever
set a state aside (`FIXTURES.md` §4.4). They cannot agree on how emptiness is
spelled, and `s0.inputs` is declared dialect-varying for `mime` and `value`
because of it: OpenInference's `input.value` is a free string with its own
`input.mime_type`, so it can carry a bare `""` at `text/plain`, while OTel
GenAI's `gen_ai.tool.call.arguments` is defined by the convention as a
structured value, whose only way to say empty is an empty JSON container. A
bare `""` there would not parse, which is a third fact again. The **outputs**
are declared nowhere: both dialects say `{}` at `application/json`.
