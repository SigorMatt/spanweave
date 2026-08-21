# declared_data_edge

An `explicit` `data` edge: a producer→consumer relation that **the
instrumentor itself declared**.

Two spans, minimal on purpose. A tool span that answered call `call_a`, and an
LLM span whose input carries the result of `call_a` as a tool-result message.
The dialect states the relation; the library transcribes it.

## Structure

Nodes: 1 `tool`, 1 `llm`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `data` | explicit | `tool_call_id in tool-result message` | s1→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2 |

Node order: s1, s2.

Both edges connect the same pair and say different things: `data` is what the
telemetry declared, `temporal` is what the clock shows. A consumer that trusts
only stated relations filters on warrant (`SPEC.md` §3.8).

## How the relation is declared

| Span | Attribute | Meaning |
|---|---|---|
| s1 | `tool_call.id` = `call_a` | this span **answered** `call_a` |
| s2 | `llm.input_messages.2.message.role` = `tool` | this input is a **result** |
| s2 | `llm.input_messages.2.message.tool_call_id` = `call_a` | of `call_a` |

The join is by **id**. No content is compared — the contents happen to match,
and that is irrelevant to the edge. This is what keeps the edge inside
`SPEC.md` §4.2: there is no threshold, no normalization rule and no encoding
policy, because nothing is being matched.

The `basis` names the **resolution**, not just the field. The instrumentor
declares the relation about a *message*; the library resolves it to the span
that fulfilled the id. A consumer auditing this edge is entitled to know that a
resolution happened (`SPEC.md` §4.2.1).

## This scenario was unrenderable for a whole phase, and should not have been

It was seeded with **no** OpenInference rendering, on the stated grounds that
"OpenInference declares no producer→consumer relation". That was false, and
every multi-turn trace in the corpus carried the counter-example — the
attribute was sitting in the `unmapped` list of a diagnostic we printed.

It was believed because it was never checked against observed output: the
renderings were written from a reading of the dialect, so the corpus and the
adapter agreed with each other and neither was tested against reality
(`FIXTURES.md` §5.1). A cold review of the first captured trace found it.

Its `expected/coverage.json` has been deleted, which is what §4.3 says happens
when a dialect turns out to be able to render a scenario after all. That file
was written to record an inability; the inability was ours.

## Payloads

s1 reports an output and no input. s2 reports both, as every LLM span in this
dialect does.

## Diagnostics

`unmapped_attributes` ×1 on s2, `info` — the message-list keys this library
does not normalize.

## Dialects

- [x] `openinference` — Phase 1, rendered from an observed capture
- [ ] `otel_genai` — Phase 2
