# `unset_and_error_status` — provenance of both renderings

This scenario is new at `TASKS.md` 2.10 and is the only one in the corpus whose
tool spans are not `ok`. It has no single source capture; each fact is
transcribed from the observed span it comes from.

| Fact | Observed in |
|---|---|
| `UNSET` on an agent span | `fixtures/captured/openai_tool_call.jsonl` L1, `genai_tool_call.jsonl` L1 |
| `UNSET` on a tool span | `openai_tool_call.jsonl` L3, `genai_tool_call.jsonl` L3 |
| `ERROR` + `status_message`, with **no** output payload | 2b fleet, `05_failing_flight`: `status: "ERROR"`, `status_message: "ToolFailure: no such flight: 'BA117'"`, `input.value` present, no `output.value` |

The flight number is the only thing changed from the fleet span, and the
`status_message` is shortened; neither is a claim about a dialect.

## A span with no `status` key: considered, and deliberately not rendered

The first draft of this scenario gave `s2` **no** `status` key at all, to
separate "stated as unset" from "not stated". It was removed after checking:
across all 68 captured records — both `fixtures/captured/` traces and the
14-trace 2b fleet — **every** record carries a `status` key. Omitting it here
would have been a claim that an exporter drops the field, and §5.1's rule is
explicit that omitting a key whose absence changes what the expected graph
asserts is a misstatement, not a simplification.

The branch is not untested; it is tested where it belongs. Both adapters map an
absent status to `unset` and both have a unit test that says so
(`tests/test_openinference.py::test_a_missing_status_is_unset_not_ok`,
`tests/test_otel_genai.py::test_an_unreported_status_is_unset`). A capture
whose exporter omits the field would move it into the corpus.

## What is *not* claimed

The GenAI rendering carries **no `error.type`**. The convention says an
instrumentation should set it when an operation fails, but no captured GenAI
trace contains a failing span, so emitting one here would be a rendering
derived from a reading (`FIXTURES.md` §5.1) — and, since the adapter does not
map it, it would also change the expected diagnostics. Recorded so that a
capture with a GenAI error span is known to be worth taking.

## Why the two dialects agree on everything but `name`

Span status, `status_message`, and the timestamps are **envelope** — OTel span
fields both instrumentors export identically — so nothing about status is
dialect-specific. The one payload present (`{"flight": "BA117"}` at
`application/json`) is a tool call's arguments, which the 2.6 matched pair
showed agreeing byte-for-byte between the dialects. Only `name` is declared.

## What it fixes

Finding **F6** (`TASKS.md` 2.4): the corpus was 18-of-18 `status: "ok"` while
20 real tool spans were 19 `unset` and 1 `error`. A consumer computing a
success rate against the corpus alone read a confident zero against real
telemetry, and no fixture could say so. Three of the six tool nodes in the
degenerate set are now not `ok`, and `status_note` is exercised at all for the
first time.
