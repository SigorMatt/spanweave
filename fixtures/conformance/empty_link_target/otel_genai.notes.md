# `empty_link_target` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the
`invoke_agent` span, **L3** the `execute_tool` span), by way of
`empty_ids/otel_genai.notes.md`: **L1** once and **L3** once, payload and id
attributes dropped, timestamps swapped for this scenario's. The `links` field
is traceable to `fixtures/captured/genai_workflow.jsonl`, whose second leg
carries one: `trace_id` and `span_id` keys, record-level, in the flat JSONL
form both adapters read.

## The one departure, stated rather than trimmed

**The link's `span_id` is `""`.** No observed instrumentor writes it — a real
exporter links to a span it has an id for — and that is exactly why the
scenario is here: `SPEC.md` §3.6 says the empty string is not a span id at
either end of a relation, and a claim with no fixture is a claim nobody
checks. In an OTLP export the field is `links[].spanId`, a proto3 `bytes`
field whose unset value is the empty string; the reader renames it to
`span_id` and leaves the value, so both containers meet the same seam reader.
The export rendering is pinned in `tests/test_read.py` rather than here,
because a container is not a dialect and the corpus compares dialects.

So read this rendering as "what these adapters do when a link target is
stated empty", never as "this is what an exporter emits".

## Why nothing but `name` is declared

Both spans carry `absent` payloads in both dialects, so there is nothing for a
payload declaration to cover. `name` is declared for the reason every scenario
declares it: the two dialects name a span from different conventions, and this
scenario asserts nothing about naming.
