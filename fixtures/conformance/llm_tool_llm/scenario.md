# llm_tool_llm

An agent span containing: an LLM call that requests one tool call, a tool span
that fulfils it (joined by a tool-call id), and a second LLM call.

This is the reference scenario. It exercises the one relation that a
dialect-aware adapter is uniquely able to recover — `call_result` pairing —
and it demonstrates the library's central restraint: the second LLM call
obviously used the tool's result, and the graph does **not** say so, because the
telemetry didn't.

## Structure

Nodes: 1 `agent`, 2 `llm`, 1 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2, s0→s3 |
| `call_result` | explicit | `tool_call_id` | s1→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3 |

Node order (topological over `parent ∪ call_result`, tie-broken by
`(started_at, node_id)`): s0, s1, s2, s3.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `present` (text/plain) | `absent` |
| s1 | `absent` | `present` (application/json) |
| s2 | `present` (application/json) | `present` (application/json) |
| s3 | `absent` | `present` (text/plain) |

Note s1 and s3: the dialect emits no input payload for these spans. That is
`absent`, **not** `empty` — see `empty_payload` for the contrasting case.

## Usage

Present on s1 and s3 only. `total_tokens` is `null` on both: the dialect reports
prompt and completion counts and does not report a total, and the adapter does
not compute one. Deriving a total would be inventing a fact the telemetry did
not state (`ADAPTERS.md` §1).

## Diagnostics

None. This is the clean case.

## Cross-dialect notes

- Node ids: all dialect renderings of this scenario use the span id strings
  `s0`–`s3` (`FIXTURES.md` §4.1).
- `Node.name` is dialect-varying and erased by `canonical()`; dialects disagree
  about operation naming conventions and that disagreement is not interesting.
- `Payload.raw` is erased: the parsed `value` must agree, the encoding need not.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2 (this is the rendering that first tests whether the
      model was general or merely OpenInference-shaped)
