# derived_ids_shuffled

`derived_ids`, line for line, in a different order. Its expected graph is a
copy of `derived_ids`'s, and that is the whole point.

`shuffled_order` makes this claim for a trace whose records carry span ids,
where a node id is the dialect's own string and file order cannot reach it.
This pair makes it where the id is **computed**, which is the only place file
order ever could — and did: the fallback `source_key` was the 1-based record
index until the September 2026 audit series, so this scenario's records
swapped ids with each other when the lines were swapped, deterministically and
invisibly.

`tests/test_conformance.py` asserts that this scenario and its twin produce
**byte-identical** canonical graphs, not merely equal ones, per dialect — and
then asserts something byte-identity does not cover, because here it does not
suffice. Ids are assigned in node order, and node order is a fact about the
run, so an index-derived key produced two graphs that were byte-identical
**while each id named a different record in each**. The pair is therefore also
checked on the binding itself: the id that names the `lookup` span forwards
names the `lookup` span reversed. That assertion is the one that was red
before batch A5; the byte comparison was green throughout.

## Structure

Identical to `derived_ids` in every compared field, including node order:
3 `tool`; 2 `temporal`; node order lookup, notify, archive. The lines are in
the reverse of the order its twin uses (archive, notify, lookup).

## Payloads

As its twin: all six `present` (application/json).

## Usage

None.

## Diagnostics

None, exactly as its twin — the same records in a different order.

## Cross-dialect notes

Same as `derived_ids`: every node id is derived and compared by position,
`expected/graph.json` is written in the labels `n0`–`n2`, and only `name` is
declared dialect-varying.

## Dialects

- [x] `openinference`
- [x] `otel_genai`
