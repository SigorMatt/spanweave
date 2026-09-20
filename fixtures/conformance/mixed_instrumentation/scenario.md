# mixed_instrumentation

One trace whose records come from **two instrumentors**. A framework
instrumentor emitted the `agent` span and the `tool` span in OpenInference; an
SDK instrumentor emitted the two `chat` spans in OTel GenAI. They shared a
tracer provider, so their spans share an export and arrive in one file.

This is the same run as `llm_tool_llm`, described half by each dialect, and
that is the whole point: **its expected graph is byte-identical to
`llm_tool_llm`'s** (`expected/graph.json`, compared by a test rather than by
eye). Composition is what is being asserted — a dialect is a property of a
record, not of a file (`SPEC.md` §6.1), so a record read by one adapter and
its neighbour read by another join into the same graph they would have joined
had one instrumentor described both.

Nothing here is hand-authored. Every record is verbatim from
`llm_tool_llm/dialects/` — s0 and s2 from `openinference.jsonl`, s1 and s3
from `otel_genai.jsonl` (`FIXTURES.md`, provenance).

## Structure

Nodes: 1 `agent` (openinference), 2 `llm` (otel_genai), 1 `tool`
(openinference).

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2, s0→s3 |
| `call_result` | explicit | `tool_call_id` | s1→s2 |
| `data` | explicit | `tool_call_id in tool-result message` | s2→s3 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2, s2→s3 |

**The two edges that cross the dialects are the ones a per-file adapter choice
loses.** `call_result` s1→s2 needs the requester id from an OTel GenAI record
and the fulfiller id from an OpenInference one; `data` s2→s3 needs the
producer from one and the receiving message from the other. Forced to a single
adapter, this file builds four nodes and five edges — two of the four spans
become `unknown`, their payloads report `absent` although content was emitted,
and both explicit joins disappear from a graph that still looks complete.
The node **count** is the same either way, which is why the loss is quiet and
why a test pins the count alongside the edges.

Node order (topological over `parent ∪ call_result`, tie-broken by
`(started_at, node_id)`): s0, s1, s2, s3.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `present` (text/plain) | `absent` |
| s1 | `present` (application/json) | `present` (application/json) |
| s2 | `present` (application/json) | `present` (application/json) |
| s3 | `present` (application/json) | `present` (application/json) |

Every payload **state** here is the state `llm_tool_llm` records, in both of
its renderings. That is the assertion, not a coincidence: a false `absent` is
what the forced-adapter build produces, so the states are what a reader should
check first.

The `value` on s1 and s3 is OTel GenAI's, because those two records are, and
it is declared dialect-varying in `expected/comparison.json` for the same
reason `llm_tool_llm` declares it (`FIXTURES.md` §4.4). s0's `mime` and
`value` are **not** declared: s0 is an OpenInference record here and agrees
with `expected/graph.json` exactly.

## Usage

Present on s1 and s3 only, from the OTel GenAI records, with `total_tokens`
`null` on both.

## Diagnostics

`unmapped_attributes` ×2 — one each on s1 and s3, both `info`. The same two
`llm_tool_llm` produces.

Nothing here is unpaired and nothing is unclaimed: every record carries
exactly one dialect's markers, and each is read by the adapter that owns them.
A record **no** adapter claims is a different shape, kept as an `unknown` node
with an `unclaimed_record` warning (`SPEC.md` §6.1); no scenario renders it,
because a corpus file carrying an unrecognized record would also be a corpus
file no future adapter could be added for without silently changing it.

## Provenance and adapter fields

Neither reaches the comparison — `canonical()` erases a node's `provenance`
and an edge's `adapter` (`FIXTURES.md` §4) — and both are real here rather
than constant:

- `provenance.adapter_id` is `openinference` on s0 and s2, `otel_genai` on s1
  and s3.
- `meta.adapters` carries **both**, each with the confidence it declared over
  the records it claimed.
- `adapter` is `null` on the `call_result` and `data` edges, because their two
  ends came from different adapters and naming one dialect for a relation two
  dialects made would be a false attribution (`SPEC.md` §3.8). It names the
  adapter on every `parent` edge whose ends agree, and `temporal` edges carry
  none, as everywhere.

## Cross-dialect notes

- Node ids: `s0`–`s3`, the span ids both renderings of `llm_tool_llm` use
  (`FIXTURES.md` §4.1). Per-record dispatch moves no id, because rule 1 —
  a trace-unique span id — never consults the adapter (`SPEC.md` §3.6).
- `Node.name` is dialect-varying and erased, as in `llm_tool_llm`; here the
  names come from both dialects in one graph.
- Neither `openinference` nor `otel_genai` can render this scenario on its
  own, and `expected/coverage.json` says why. That is not a gap in coverage:
  the single-dialect renderings of this run are `llm_tool_llm`'s, and this
  scenario's expected graph is the same file.

## Dialects

- [x] `openinference+otel_genai` — one rendering, read by both adapters, added
      by the September 2026 audit series (batch E3). The `+` names every
      adapter that reads a record in it; it is not a dialect and is not in
      `tests/conformance.py`'s `DIALECTS`.
