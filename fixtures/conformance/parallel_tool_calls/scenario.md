# parallel_tool_calls

An agent span containing: one LLM call that requests **two** tool calls in a
single turn, and two tool spans that fulfil them, joined by their own ids.

This is the scenario `llm_tool_llm` is not. There, one span requests one call;
here one span requests two, which is what current agent frameworks emit
constantly. It exists because the seam used to carry a single `call_id` per
span, so this shape was expressible only by dropping an id or reporting it as
unmapped — the corpus had no fixture that would have failed, and the
limitation was found by reading rather than by testing. Now it has one.

## Structure

Nodes: 1 `agent`, 1 `llm`, 2 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2, s0→s3 |
| `call_result` | explicit | `tool_call_id` | s1→s2, s1→s3 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3 |

**Two `call_result` edges leave s1.** The graph model always permitted that —
one node may be the source of several edges of one kind — and the ids are what
make each of them a transcription rather than a guess.

Node order: s0, s1, s2, s3.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `present` (text/plain) | `absent` |
| s1 | `present` (application/json) | `present` (application/json) — both requested calls |
| s2 | `absent` | `absent` |
| s3 | `absent` | `absent` |

## Usage

None. The dialect reports no token counts here; `llm_tool_llm` covers usage.

## Diagnostics

`unmapped_attributes` ×1 on s1, `info`. No warnings: every requested id is
fulfilled, and nothing has to be reported to avoid dropping one.

## What this scenario does not cover

There is no follow-up LLM turn here, so no call id is ever echoed as history —
which means this scenario would **not** have caught the pairing defect that
`tool_call_history_echo` exists for, and it is not asked to. Rendered
faithfully with a follow-up turn it would have shown that defect twice over,
once per id. One property per scenario: this one is about several calls
requested at once.

## Cross-dialect notes

- Node ids: all renderings use the span id strings `s0`–`s3`
  (`FIXTURES.md` §4.1).
- The tool spans have **distinct** start times on purpose. Tie-breaking is
  `parallel_tools`' subject, and entangling the two would make a failure in
  either one ambiguous.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
