# unset_and_error_status

Three spans that between them carry every span status this corpus can observe,
because until this scenario every one of them was `ok`.

- `s0`, an agent span, states `UNSET`.
- `s1`, a tool span, states `ERROR`, with a `status_message`.
- `s2`, a tool span, states `UNSET`.

Two of the three nodes are tools and neither is `ok`, which is what no other
scenario in this corpus can say.

## Structure

Nodes: 1 `agent`, 2 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2 |

Node order: s0, s1, s2.

## Payloads

`s1` reports its arguments and **no** result — the span that failed produced
none. That is `absent`, not `empty`. `s0` and `s2` report neither.

## Statuses

| Node | As stated | `status` | `status_note` |
|---|---|---|---|
| s0 | `"UNSET"` | `unset` | none |
| s1 | `"ERROR"` | `error` | `ToolFailure: no such flight` |
| s2 | `"UNSET"` | `unset` | none |

`status_note` is carried on `s1` alone, and this is the only scenario in the
corpus that carries one at all.

## Why it exists

The 2b fleet aggregator (`TASKS.md` 2.4, finding F6) computed a tool success
rate over the corpus and got 18 of 18 `ok`. Over 20 real tool spans it got
19 `unset` and 1 `error` — not one `ok`. A consumer written against the corpus
alone therefore reads a confident zero against real telemetry, and nothing in
the corpus was able to say so.

Every span here is degraded from observed output (`FIXTURES.md` §5.1):

- `UNSET` on an agent span and `UNSET` on a tool span are both in
  `fixtures/captured/openai_tool_call.jsonl` and
  `fixtures/captured/genai_tool_call.jsonl`. A span with **no** `status` key
  was drafted and removed: no record in any capture omits it. See
  `provenance.notes.md`.
- The `ERROR` span, its `status_message` text shape, and the **absent** output
  that goes with it are transcribed from the 2b fleet capture
  (`05_failing_flight`), which is the only observed error span either dialect
  has produced here.

## Dialects

- [x] `openinference` — Phase 2 (2.10)
- [x] `otel_genai` — Phase 2 (2.10)

`name` is declared dialect-varying (`expected/comparison.json`): the OTel GenAI
convention prescribes the span name, `<operation> <target>`, so a faithful
rendering cannot reuse OpenInference's. Nothing else is declared — both
dialects agree on every payload here, including `mime`, because a tool call's
arguments are `application/json` in both.
