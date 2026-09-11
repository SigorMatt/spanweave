# empty_ids

Two spans. The first states `span_id: ""`; the second states `span_id: "s2"`
and `parent_id: ""`. Both fields are present, and both are empty.

An **empty string is not a span identity** (`SPEC.md` §3.6), and it is not a
span reference either (§4.0). The two halves are one rule, and this scenario
exists because for one batch they were not: `parent_id: ""` had been
normalized to "no parent" (batch R10) on the stated ground that the empty
string names a span no input can contain, while a record whose `span_id` was
`""` went on being named `""`. So an input could contain exactly the span the
sentence said it could not, and the `parent` edge between these two records —
`explicit`, stated by the telemetry — was dropped without a diagnostic. The
rule is now stated at both ends: an empty `span_id` states no id, so the node
id comes from the record's content (§3.6 rule 2), the same answer an absent
`span_id` gets.

## Structure

Nodes: 1 `agent`, 1 `tool`. **Both records are kept**, and the first is kept
under a derived id rather than under `""`.

Edges: 1 `temporal` (derived). Both spans are roots — the first states no
usable id and the second states no parent — so they are siblings, ordered by
`start_time` (`SPEC.md` §4.3).

**No `parent` edge, and that is the point rather than a loss.** The child's
parent reference is empty, which is no reference; the would-be parent's id is
empty, which is no id. There is no pair of ids for an edge to be stated
between, so there is no edge to drop. What the two records said is still
readable on the nodes: `raw.source` carries `span_id: ""` and `parent_id: ""`
verbatim (§3.5), which is the whole of what was reported and the whole of what
is kept (`CLAUDE.md` 2). `tests/test_adapters.py` and `tests/test_read.py`
assert that verbatim carriage, because `canonical()` erases `raw` and this
corpus therefore cannot see it.

Node order: the agent (1000.0), then the tool (1000.5).

The two `start_time` values are **deliberately distinct**, for `derived_ids`'
reason: node order tie-breaks on `(started_at, node_id)` (`SPEC.md` §5.2) and
a derived node id differs between dialects by design (§3.6), so two spans
sharing a start time would order by something this corpus cannot compare.

## Payloads

Both `absent` on both nodes. Neither record carries a payload attribute, and
`absent` is not `empty` (`SPEC.md` §3.3).

## Usage

None. Neither dialect reports token counts on an agent or a tool span.

## Diagnostics

**None**, and that is asserted rather than incidental. An empty `span_id` is
read, not failed-to-read: it decided the identity rule that applies, so it is
not an unreadable field (`SPEC.md` §3.7, batch R12) — the same reading
`parent_id: ""` already gets. And a derived id is not a defect: `derived_ids`
records why rule 2 is the honest answer to a missing id rather than something
to report, and an empty id reaches the same rule by the same argument.

## Cross-dialect notes

The agent's node id is a `sw_` id and the two dialects **cannot** agree on it:
the adapter id is in the material (`SPEC.md` §3.6). `canonical()` maps it to
the positional label `n0`, and `expected/graph.json` is written that way
(`FIXTURES.md` §4.1). The tool's id is `s2` in both, compared by value.

Both empty fields are **record-level**, not `gen_ai.*` or `openinference.*`
attributes, so the two renderings differ only in the vocabulary of the two
attributes that state the kind. That is what makes this an envelope property:
both dialects reach it by the same route.

Only `name` is declared dialect-varying, for the reason `missing_payloads`
records.

## Dialects

- [x] `openinference`
- [x] `otel_genai`
