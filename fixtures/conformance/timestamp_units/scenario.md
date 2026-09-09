# timestamp_units

Timestamps in a unit that is not seconds, and a timestamp in a rendering the
library does not read — the two halves of `SPEC.md` §3.1 that decide nothing
about a run and everything about how a field was encoded.

- `s0` and `s1` report `start_time` and `end_time` in **nanoseconds**.
- `s2` reports an `end_time` in nanoseconds and a `start_time` that is a
  string but not a number (`"2026-09-05T10:00:00Z"`).

## Structure

Nodes: 1 `agent`, 2 `tool`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2 |

**No temporal edges.** s2 is excluded because it has no start time, which
leaves s1 alone in its sibling group, and a lone sibling has nobody to be
consecutive with. This is `clock_skew`'s shape on purpose: the two scenarios
differ in how the start time went missing, and must not differ in anything
else.

Node order: s0, s1, s2. s2 sorts last because a node with no start time sorts
as `+inf` — last, but never dropped.

## Timestamps

Every value is kept **exactly as reported**. `s0.started_at` is
`1.7e+18`, not `1700000000.0`: the library does not rescale, and a consumer
that wants seconds converts them itself. The nanosecond values are what
produce `timestamp_unit_suspect`, which reports the *unit of the field* and
never anything about the run — the nodes keep their numbers and the edges are
still built from them.

Three spans carry a value over the line and three diagnostics are emitted, one
per node: s0 and s1 have both endpoints over it and get **one** report each,
naming both fields, because the two endpoints of a span share one encoding.
s2's report names `ended_at` alone.

s2's `start_time` is not read at all. It is not silently absent: the string
stays verbatim in `raw.source`, the adapter names `<record>.start_time` in
`unmapped_attributes`, and the builder then says `missing_timestamp` — *we did
not normalize this field*, and *so this node has no start time*.

## Payloads

All `absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `missing_timestamp` | 1 | s2 |
| `timestamp_unit_suspect` | 3 | s0, s1, s2 |
| `unmapped_attributes` | 1 | s2 |

`timestamp_unit_suspect` is `warning`; the other two are `info`.

## Dialects

- [x] `openinference` — batch C1
- [x] `otel_genai` — batch C1

`name` is declared dialect-varying (`expected/comparison.json`). Nothing else
is declared.

**The two renderings deliberately differ in encoding, and that is the point.**
`openinference` writes the nanosecond values as JSON integers;
`otel_genai` writes the same values as decimal **strings**, which is how OTLP
JSON encodes a 64-bit integer. §3.1 says a quoted timestamp is read as the
identical value the same literal would have produced unquoted, so the two
renderings must produce one canonical graph — and this scenario is where that
claim is executable rather than asserted. It is not a statement that one
dialect quotes timestamps and the other does not: either exporter may, and the
library answers the same way for both (`tests/test_adapters.py` holds the full
rendering table for each adapter separately).

`s2`'s unreadable `start_time` is the same string in both renderings, because
a value in a rendering the library refuses is refused identically everywhere.
