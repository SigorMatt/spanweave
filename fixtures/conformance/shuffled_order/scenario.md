# shuffled_order

`llm_tool_llm`, line for line, in a different order. Its expected graph is a
copy of `llm_tool_llm`'s, and that is the whole point.

Input line order is not significant (`SPEC.md` §5.2). This is the single most
valuable determinism check in the corpus, because it catches every accidental
reliance on file order at once: a group-by that emits in dict insertion order,
a first-wins index, an id derived from a record's position, a sort that is
stable rather than total.

`tests/test_conformance.py` additionally asserts that this scenario and its
twin produce **byte-identical** canonical graphs, not merely equal ones.

## Structure

Identical to `llm_tool_llm` in every compared field, including node order:
1 `agent`, 2 `llm`, 1 `tool`; 3 `parent`, 1 `call_result`, 2 `temporal`;
node order s0, s1, s2, s3.

That includes the history echo on s3: the shuffled twin must also produce
exactly one `call_result` edge, and reordering the lines must not change which
span is the requester.

## Diagnostics

`unmapped_attributes` ×2, exactly as its twin — identical in code and count,
because it is the same records in a different order.

## Cross-dialect notes

Same as `llm_tool_llm`: node ids are the span id strings `s0`–`s3`, and
`Node.name` is dialect-varying and erased by `canonical()`.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — Phase 2
