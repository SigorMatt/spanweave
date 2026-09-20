# Provenance — `dialects/otel_genai.json`

**Derived, not captured** (`FIXTURES.md` §5.1).

Source: `fixtures/conformance/llm_tool_llm/dialects/otel_genai.jsonl`,
mechanically re-encoded as one `ExportTraceServiceRequest` by the rules
`SPEC.md` §7 states for the OTLP JSON container, read in the other direction:

- `trace_id`/`span_id`/`parent_id`/`name` → `traceId`/`spanId`/`parentSpanId`/
  `name`. The root is the one span where this is not a rename: the JSONL line
  carries **no** `parent_id` key, and the export writes
  `"parentSpanId": ""`. Both are proto3 JSON for the same fact — an unset
  `bytes` field, which a marshaler may omit or may write as its default — and
  writing it is what an emit-defaults marshaler does on **every root of every
  export**. It is written here deliberately, because the graph below must be
  the same graph either way: an empty parent reference is *no parent*, not a
  parent this input does not carry (`SPEC.md` §4.0). It read as the second
  until the September 2026 audit series (batch R10), and every root of every
  OTLP export drew an `orphan_parent` for it.
- `start_time`/`end_time` → `startTimeUnixNano`/`endTimeUnixNano`, as decimal
  strings carrying the same literal the JSONL line carried. See
  `scenario.md`, "Timestamps".
- `status: "OK"` → `status: {"code": "STATUS_CODE_OK"}`.
- the attribute object → an OTLP `KeyValue` list, each value tagged by its JSON
  type: `stringValue`, `intValue` (as the decimal string proto3 JSON requires),
  `arrayValue`.

Nothing was added, reordered or dropped except the root's `parentSpanId`
above, which states in OTLP's default form what the JSONL line states by
omitting the key: the record's attribute keys appear in the file's own order,
and the span order is the file's. **No `resource`, no
`scope`, no `kind`** — see `scenario.md`, "What this scenario deliberately
does NOT carry".
