# unpaired_tool_call

Both halves of the pairing failure, in one trace:

- `s1` requests call `call_a`, and **no span fulfils it**.
- `s2` fulfils call `call_b`, and **no span requested it**.

The two spans are siblings, adjacent in time, one an LLM and one a tool. Every
heuristic a hurried implementation might reach for — nearest in time, same
parent, plausible kinds — would pair them. The correct output pairs nothing
and says so twice.

## Structure

Nodes: 1 `agent`, 1 `llm`, 1 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2 |

**No `call_result` edge.** A guessed pairing is indistinguishable from a real
one downstream, which is exactly the harm the warrant system exists to prevent
(`SPEC.md` §4.4).

Node order: s0, s1, s2.

## Payloads

s1 reports an output (the requested call, parsed). Everything else is
`absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `unpaired_call` | 1 | s1 |
| `unpaired_result` | 1 | s2 |

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
