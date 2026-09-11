# `empty_ids` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the
`invoke_agent` span, **L3** the `execute_tool` span), by way of
`nested_agents/otel_genai.notes.md` and `derived_ids/otel_genai.notes.md`:
**L1** once and **L3** once, payload and id attributes dropped, timestamps
swapped for this scenario's. Every key present is a key those two lines carry.

## The two departures, stated rather than trimmed

**`span_id` is `""` on the first record, and `parent_id` is `""` on the
second.** No observed instrumentor writes the first one — a real exporter that
emits a span emits its id — and that is exactly why the scenario is here: the
library's rule for an empty *reference* (§4.0) rested on a claim about an
empty *identity*, and a claim with no fixture is a claim nobody checks. The
second is ordinary rather than pathological: OTLP's `parentSpanId` is a proto3
`bytes` field, an unset one is the empty string, and a marshaler that emits
defaults writes it on every root span of every export (`SPEC.md` §7).

The renderings state both in the **flat** JSONL form both adapters read, so
the scenario is about the identity rule rather than about the container. The
same pair inside an `ExportTraceServiceRequest` — where `spanId` and
`parentSpanId` are the proto3 `bytes` fields this argument is about — is
pinned in `tests/test_read.py` instead, because a container is not a dialect
and the corpus compares dialects.

So read this rendering as "what these adapters do when an id is stated empty",
never as "this is what an exporter emits".

## Why nothing but `name` is declared

Both spans carry `absent` payloads in both dialects, so there is nothing for a
payload declaration to cover. `name` is declared for the reason every scenario
declares it: the two dialects name a span from different conventions, and this
scenario asserts nothing about naming.
