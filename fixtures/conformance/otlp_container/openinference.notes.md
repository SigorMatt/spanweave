# Provenance — `dialects/openinference.json`

**Derived, not captured** (`FIXTURES.md` §5.1).

Source: `fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl`,
mechanically re-encoded as one `ExportTraceServiceRequest` by the rules
`SPEC.md` §7 states for the OTLP JSON container, read in the other direction:

- `trace_id`/`span_id`/`parent_id`/`name` → `traceId`/`spanId`/`parentSpanId`/
  `name`. `parentSpanId` is **omitted** on the root rather than written as
  `""`, because proto3 JSON omits a field holding its default.
- `start_time`/`end_time` → `startTimeUnixNano`/`endTimeUnixNano`, as decimal
  strings carrying the same literal the JSONL line carried. See
  `scenario.md`, "Timestamps".
- `status: "OK"` → `status: {"code": "STATUS_CODE_OK"}`.
- the attribute object → an OTLP `KeyValue` list, each value tagged by its JSON
  type: `stringValue` and `intValue` (as the decimal string proto3 JSON
  requires). This dialect's records carry no list-valued attribute, so no
  `arrayValue` appears here; `otel_genai.json` has one.

Nothing was added, reordered or dropped: the record's attribute keys appear in
the file's own order, and the span order is the file's. **No `resource`, no
`scope`, no `kind`** — see `scenario.md`, "What this scenario deliberately
does NOT carry".
