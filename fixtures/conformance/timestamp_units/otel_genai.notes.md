# `timestamp_units` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L1** the
`invoke_agent` span, **L3** the `execute_tool` span, used twice). Same
vocabulary as `llm_tool_llm/otel_genai.notes.md`; only what is specific is
repeated. The rendering is `clock_skew`'s with the timestamps changed and
nothing else, so the two scenarios stay comparable.

Two hand-made changes, both changes of **value within an observed field**,
which is the line `FIXTURES.md` §5.1 draws:

| Span | Change | Expected diagnostic |
|---|---|---|
| s0, s1, s2 | `start_time` / `end_time` written in nanoseconds | `timestamp_unit_suspect` |
| s2 | `start_time` set to an ISO-8601 string | `unmapped_attributes`, `missing_timestamp` |

The capture exports `start_time` / `end_time` as Unix seconds at the record
level — `1787781725.9583309` in L1 — so neither the unit nor the quoting is
this dialect's: timestamps are envelope, not dialect, exactly as
`clock_skew/otel_genai.notes.md` records.

**Why this rendering quotes its numbers and the `openinference` one does
not.** Not because the dialects differ. OTLP JSON encodes 64-bit integers as
decimal strings, so a quoted `start_time` is a real exporter's output that no
captured file here happens to contain; rendering it in one of the two files is
what makes `SPEC.md` §3.1's "a quoted timestamp is the same timestamp" claim
something the cross-dialect comparison can fail on. No observed span in either
capture quotes one, and this is recorded as hand-authored for that reason.
