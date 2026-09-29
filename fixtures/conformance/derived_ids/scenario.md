# derived_ids

Three tool spans, none of which carries a `span_id`. Every node id in this
scenario is therefore **derived** (`SPEC.md` §3.6 rule 2) rather than a string
the dialect supplied.

It is here because every record the corpus then held carried a usable span id
— 117 of them in a checkout, stated as 177 at the time from a scan of a
working tree that counted the git-ignored `capture/_scratch/` (batch R5) — so
rule 2, the whole fallback path, was exercised by no fixture at all. What that hid: the fallback `source_key` was the record's
**1-based index**, so a file of span-id-less records rebound its ids when its
lines were swapped, and `shuffled_order` could not see it because its records
have span ids. The fallback is the record's canonical digest now, and this
scenario plus its twin `derived_ids_shuffled` is what keeps it that way.

## Structure

Nodes: 3 `tool`.

Edges: 2 `temporal` (derived). The three spans are roots and therefore
siblings, ordered by `start_time`. No `parent` edge — a parent edge needs a
`parent_id` pointing at a span id, and there are none here — and no
`call_result`, because no span states a call id.

Node order: lookup, notify, archive.

The three `start_time` values are **deliberately distinct**. Node order
tie-breaks on `(started_at, node_id)` (`SPEC.md` §5.2), and a derived node id
differs between dialects by design (§3.6 puts the adapter id in the material),
so two spans sharing a start time would order by something this corpus cannot
compare. Distinct times keep the ordering a fact about the run.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| lookup | `present` (application/json) | `present` (application/json) |
| notify | `present` (application/json) | `present` (application/json) |
| archive | `present` (application/json) | `present` (application/json) |

## Usage

None. Neither dialect reports token counts on a tool span.

## Diagnostics

None. A missing span id is not a defect — it is a dialect that does not carry
one, and rule 2 is the honest answer to it, not a diagnostic.

## Cross-dialect notes

Node ids here are `sw_` ids and the two dialects **cannot** agree on them: the
adapter id is in the material (`SPEC.md` §3.6). `canonical()` maps them to
positional labels `n0`, `n1`, `n2` in node order before comparing, and
`expected/graph.json` is written in those labels (`FIXTURES.md` §4.1). This is
the first scenario in the corpus whose *every* node is relabelled, and the
first with more than one edge between relabelled nodes.

Only `name` is declared dialect-varying. Both payloads agree in both fields,
for the reason `single_tool_call` records: a tool call's arguments and result
have no envelope to disagree about.

## Dialects

- [x] `openinference`
- [x] `otel_genai`
