# otlp_container

`llm_tool_llm`'s run, packed into an **OTLP JSON export** —
`resourceSpans[].scopeSpans[].spans[]`, the body every OTLP-HTTP exporter POSTs
and every file receiver writes — once in each dialect.

**Its expected graph is byte-identical to `llm_tool_llm`'s**
(`expected/graph.json` is that scenario's file, compared by a test rather than
by eye), and that is the whole assertion: **a container is not a dialect**
(`SPEC.md` §7). The same spans, differently packed, are the same spans. An
export carries whatever its instrumentors emitted — possibly two dialects at
once, which is why unpacking it is the reader's job and not an adapter's
(`OPEN_QUESTIONS.md` §16).

Nothing here is hand-authored as telemetry. Every span is
`llm_tool_llm/dialects/<dialect>.jsonl` re-encoded field for field by the
rules `SPEC.md` §7 states — nine keys renamed, the attribute list folded into
OTLP `KeyValue` entries with the `AnyValue` tag each Python type calls for, and
`status` written as the proto enum name. `expected/comparison.json` and
`expected/payloads/` are that scenario's, unchanged.

## What this scenario deliberately does NOT carry

The envelope is **minimal**: no `resource`, no `scope`, no `kind`, no `events`,
no unfoldable attribute. That is a choice, and it is the reason the claim above
can be *byte-identical* rather than nearly. Every one of those fields is
carried into the record under its own name and reported as unmapped, so a
rendering that had them would produce the same nodes and the same edges and
**two more `unmapped_attributes` diagnostics per span** — a different
`diagnostic_count`, and a graph file that no longer matches this one byte for
byte while agreeing about everything a consumer reads.

Rather than weaken the claim to hold that, the honest-carrying half is tested
directly, in `tests/test_read.py` under "OTLP JSON as a container": resource
and scope preservation, `kind` never becoming a `NodeKind`, `status.code` in
both spellings, `AnyValue` by tag, `intValue` decoding, repeated and unfoldable
attribute entries, envelope levels with no spans, a file of one export per
line, and an array of exports. One of those tests adds `resource`, `scope` and
`kind` to *this* fixture's own spans and asserts exactly the difference this
paragraph predicts.

## The root's parent

Both renderings write `"parentSpanId": ""` on the root — the empty `bytes`
field an emit-defaults marshaler puts on **every root of every export**, and
the thing a JSONL root says by carrying no `parent_id` key at all. The
scenario asserts that those are the same statement: the root draws **no**
diagnostic, and the graph is still `llm_tool_llm`'s byte for byte.

It was not, until the September 2026 audit series (batch R10). An empty parent
reference was read as a parent this input does not carry, so every root of
every OTLP export drew an `orphan_parent` — the diagnostic for a trace that
was sampled, filtered or exported mid-run, reported on the one span that
proves it was not (`SPEC.md` §4.0). The fixture omitted the field, so the
corpus could not see it.

## Timestamps

The spans carry `startTimeUnixNano` / `endTimeUnixNano` holding
`llm_tool_llm`'s own values — `1000.0`, `1000.2` — as decimal strings, which
is how proto3 JSON writes an `int64` and how a real exporter writes this field.
They are seconds, and the field name says nanoseconds, and that is not a
contradiction here: **`spanweave` reads no unit from a field name**
(`SPEC.md` §3.1, and nothing is ever rescaled). Changing the numbers would
change the scenario rather than the encoding, and this scenario's claim is
about the encoding. `timestamp_units` is where the numbers are the claim.

## Structure

Identical to `llm_tool_llm` — 1 `agent`, 2 `llm`, 1 `tool`; 3 `parent`,
1 `call_result`, 2 `temporal` and 1 `data` edge; 2 `unmapped_attributes`.
Read that scenario's `scenario.md` for the table; duplicating it here would
give it two places to go stale.
