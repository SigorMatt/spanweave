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
| s1 | `present` (application/json) | `present` (application/json) |
| s2 | `present` (application/json) | `present` (application/json) |
| s3 | `present` (application/json) | `present` (application/json) |

Every LLM span reports both. The instrumentor emits `input.value` (the whole
request) and `output.value` (the whole response object) on every model call —
so an LLM span with `absent` inputs would be a claim about this dialect that
is simply false. For the `absent`-versus-`empty` contrast, see
`missing_payloads` and `empty_payload`, which are about exactly that and
nothing else.

## Usage

Present on s1 and s3 only. `total_tokens` is `null` on both: the dialect reports
prompt and completion counts and does not report a total, and the adapter does
not compute one. Deriving a total would be inventing a fact the telemetry did
not state (`ADAPTERS.md` §1).

## Diagnostics

`unmapped_attributes` ×2 — one each on s1 and s3, both `info`.

This is still the clean case: **no warnings**, nothing unpaired, nothing
unmappable. Real telemetry carries more than this library normalizes —
`llm.finish_reason`, the message lists, the request payload — and the library
reports those keys rather than dropping them (`SPEC.md` §3.7). A scenario with
*zero* diagnostics would be a scenario whose rendering had been trimmed until
the library had nothing left to report, which is how the corpus came to be
wrong about this dialect in the first place.

## The history echo, and why this expectation changed

s3 carries the call id `call_a` — twice — under
`llm.input_messages.1.message.tool_calls.0.tool_call.id` and
`llm.input_messages.2.message.tool_call_id`. **s3 requested nothing.** The
protocol requires a follow-up turn to resend the whole conversation, so the
previous turn's tool call and its result arrive as *input* context, and the
instrumentor records them faithfully.

There is exactly **one** `call_result` edge, s1→s2. An edge from s3 would
assert a request-fulfilment relation the telemetry never stated. An echo of a
reference is not the reference.

This scenario's expected graph was frozen by a human before any code existed,
and it changed here anyway, because a **captured trace disagreed with it**
(`FIXTURES.md` §6: the captured one is right). What moved, and why:

| Change | Cause |
|---|---|
| s1, s3 inputs `absent` → `present` | the instrumentor does emit `input.value` on every LLM span; the old rendering omitted it |
| diagnostics `[]` → `unmapped_attributes` ×2 | the old rendering carried only keys the library maps |
| s1 `outputs.value` reshaped | the old rendering put tool calls at the top level of `output.value`; the real response object nests them under `choices[0].message` |
| the requester id moved | from a top-level `tool_calls` key in the payload to `llm.output_messages.0.message.tool_calls.0.tool_call.id`, which is what the instrumentor actually emits |

The node and edge structure did **not** change. What changed is everything the
old rendering had quietly asserted about the dialect.

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
