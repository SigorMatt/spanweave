# `derived_ids_shuffled` — provenance of the `otel_genai` rendering

Not a new rendering. This file is `derived_ids/dialects/otel_genai.jsonl`
**line for line**, in the reverse order — the same order this scenario's
OpenInference rendering uses. Provenance, and the one departure from observed
output, are `derived_ids/otel_genai.notes.md`'s in full; the two expected
graphs are byte-identical, so there is nothing further to derive.

That identity is the point. Any difference between these two scenarios in
either dialect is an ordering defect and can be nothing else: same bytes, same
expectation, only the line order moved. Here it is an ordering defect in **id
assignment** specifically, which is what separates this pair from
`shuffled_order` — there, a node id is a string the dialect supplied and file
order cannot reach it.

The declarations here are `derived_ids`'s, unchanged, for the same reason
`shuffled_order` gives: copying the reasoning would let the two drift.
