# receipt_redeclared

Two tool-calling turns and a closing turn. The closing turn's request carries
**both** tool results, so the result of the first call is declared received a
**second** time — by a span that is not the first to have been given it.

This is the shape `SPEC.md` §4.2.1's rank exists for. Every declaration is an
edge; the `basis` says which occurrence came first.

## Why this scenario exists

`tool_call_history_echo` is about the resent **request** and the `call_result`
rule (§4.4): an id a span merely echoes is not a request. The receipt echo is
the mirror property and a different rule — a result id in a resent history
*is* mapped, so the second turn to be shown it gets a `data` edge too. Nothing
in the corpus carried a call id received by more than one span, and neither
does any captured trace: across the 15 captured files that produce `data`
edges there are 24 of them, every call id received exactly once. The rank was
therefore exercised by nothing (`OPEN_QUESTIONS.md` §11).

Isolated deliberately, by the same argument that created
`tool_call_history_echo`: when this one fails, the thing that broke has a name.

## Structure

Nodes: 3 `llm`, 2 `tool`. No agent span — this scenario is about one property
and containment is not it.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `call_result` | explicit | `tool_call_id` | s1→s2, s3→s4 |
| `data` | explicit | `tool_call_id in tool-result message` | s2→s3, s4→s5 |
| `data` | explicit | `tool_call_id in tool-result message (not the earliest receiving span)` | s2→s5 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3, s3→s4, s4→s5 |

Node order: s1, s2, s3, s4, s5.

**Three `data` edges, and s5 is the target of two of them that say different
things.** s5 was given the result of `call_b` first — nothing else ever was —
so that edge carries the plain basis. It was given the result of `call_a`
second, after s3, so that edge says so. Both are true statements the
instrumentor made about s5's own input, and neither is dropped: the graph
ranks them rather than choosing between them.

**No edge here was decided by a tie-break.** Every span reports a distinct
`started_at`, so the third basis in §4.2.1's table —
`(earliest tied, broken by node_id)` — is absent by construction. That case is
a decision the library makes rather than something a trace shows, and it is
pinned in `tests/test_build.py` rather than here.

## Where each call id appears

| Span | Attribute (OpenInference) | Meaning |
|---|---|---|
| s1 | `llm.output_messages.0…tool_call.id` = `call_a` | the model **said** `call_a` |
| s2 | `tool_call.id` = `call_a` | the span that **answered** it |
| s3 | `llm.input_messages.2.message.tool_call_id` = `call_a` | the result, **first** shown to the model |
| s3 | `llm.output_messages.0…tool_call.id` = `call_b` | the model **said** `call_b` |
| s4 | `tool_call.id` = `call_b` | the span that **answered** it |
| s5 | `llm.input_messages.2.message.tool_call_id` = `call_a` | the same result, shown **again** |
| s5 | `llm.input_messages.4.message.tool_call_id` = `call_b` | the second result, first shown |

s5's two echoed **request** ids (`call_a` and `call_b` in its
`input_messages`) are not consumed: they are evidence of context and there is
no edge kind for that, so they surface in `unmapped` and are reported (§4.4).

## Payloads

All present: the instrumentor emits `input.value` and `output.value` on every
LLM span, and each tool span reports an output and no input.

## Diagnostics

`unmapped_attributes` ×3, all `info` — one each on s1, s3 and s5, naming the
message-list keys this library does not normalize, including the echoed
request ids.

No `unpaired_call`, no `unpaired_result`: each call was requested once and
fulfilled once, and a re-declared **receipt** is neither.

## Cross-dialect notes

- Node ids: all dialect renderings of this scenario use the same span id
  strings (`FIXTURES.md` §4.1).
- `Node.name` is dialect-varying and erased by `canonical()`, declared in
  `expected/comparison.json`, for the reason `llm_tool_llm` gave at seed time.
- The `llm` payload `value`s are declared dialect-varying (`FIXTURES.md` §4.4):
  OpenInference records the request envelope and the whole provider response,
  OTel GenAI the normalized conversation. The **tool** payloads on s2 and s4
  are declared nowhere — they agree, which is the point — and so does `mime`
  everywhere.
- The two dialects declare the repeated receipt by different mechanisms — a
  flat `llm.input_messages.N.message.tool_call_id` against a
  `tool_call_response` part inside `gen_ai.input.messages` — and produce the
  identical three edges with the identical three bases, because the **builder**
  ranks them. An adapter reports only which call ids a span was given the
  results of; it sees one span and cannot know whether another saw the same
  result first.

## Dialects

- [x] `openinference` — added at the September 2026 audit's batch D2
- [x] `otel_genai` — added at the same batch, `otel_genai.notes.md`
