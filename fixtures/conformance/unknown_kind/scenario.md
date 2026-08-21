# unknown_kind

A span whose reported kind the library does not map. Real dialects invent
kinds constantly — `guardrail`, `reranker`, `router`, `handoff` — and
`NodeKind` is deliberately closed (`OPEN_QUESTIONS.md` §1).

## Structure

Nodes: 1 `agent`, 1 `unknown`.

Edges: 1 `parent` (explicit, `span.parent_span_id`), s0→s1.

Node order: s0, s1.

## The unknown node

`s1.kind` is `unknown`, and `s1.attributes.reported_kind` is `"GUARDRAIL"` —
the original string, preserved. It appears in the diagnostic too.

`unknown` is a **first-class outcome, not a failure** (`SPEC.md` §3.2). The
alternative a hurried implementation reaches for is to force the near-miss
into a neighbouring kind, and a wrong kind is worse than an honest unknown
precisely because `unknown` is visible and a wrong kind is not.

## Payloads

All `absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `unknown_span_kind` | 1 | s1 |

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
