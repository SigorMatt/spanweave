# tool_call_history_echo

Three spans: an LLM call that requests a tool call, a tool span that fulfils
it, and a second LLM call whose **input context carries the same call id**
because the protocol required the conversation to be resent.

The second LLM span requested nothing. It must produce **no** `call_result`
edge.

## Why this scenario exists

It is the one the corpus did not have, and its absence let a real defect ship.
Every call-bearing fixture was hand-authored from a reading of the dialect
rather than from observed output, and none of them carried the history that a
real follow-up turn carries — so the adapter matched a call id *anywhere* on a
span, the fixtures agreed with it, and both were wrong about the world
together. A captured trace found it in one run (`FIXTURES.md` §5, §6).

Isolated deliberately: `llm_tool_llm` now carries the echo too, but it carries
four other properties as well. When this one fails, the thing that broke has a
name.

## Structure

Nodes: 2 `llm`, 1 `tool`. No agent span — this scenario is about one property
and containment is not it.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `call_result` | explicit | `tool_call_id` | s1→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3 |

**Exactly one `call_result` edge, and it does not start at s3.**

Node order: s1, s2, s3.

## Where the id appears

| Span | Attribute | Meaning |
|---|---|---|
| s1 | `llm.output_messages.0.message.tool_calls.0.tool_call.id` | the model **said** this call |
| s2 | `tool_call.id` | the span that **answered** it |
| s3 | `llm.input_messages.1.message.tool_calls.0.tool_call.id` | the call, **shown to** the model as history |
| s3 | `llm.input_messages.2.message.tool_call_id` | the result, **shown to** the model as history |

The dialect distinguishes them, and the distinction is the message list the
attribute sits in: `output_messages` is what the model produced,
`input_messages` is what it was given. A rule that matched the id by its
suffix alone would read the last two rows as requests.

s3's echoed ids are **not** consumed by the adapter, so they surface in
`unmapped` and are reported. They are evidence of context, and the library has
no edge kind for that — reporting them is the honest outcome, and inventing
one would be worse than saying nothing.

## Payloads

All present: the instrumentor emits `input.value` and `output.value` on every
LLM span. s2 reports an output and no input.

## Diagnostics

`unmapped_attributes` ×2, both `info` — one each on s1 and s3, naming the
message-list keys this library does not normalize, including the echoed ids.

No `unpaired_call`, no `unpaired_result`: `call_a` was requested once and
fulfilled once, and the echo is neither.

## Dialects

- [x] `openinference` — Phase 1, rendered from an observed capture
- [ ] `otel_genai` — Phase 2
