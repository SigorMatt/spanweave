# `unknown_kind` — provenance of the `otel_genai` rendering

Two spans: **L1** of `fixtures/captured/genai_tool_call.jsonl` transcribed for
`s0`, and `s1` carrying a single attribute.

## What is transcribed and what is not

`s1`'s `gen_ai.operation.name` is `invoke_workflow`. That value is **not**
transcribed from a captured span — no capture contains one — and it is not
invented either. It is read from the convention's own registry:
`opentelemetry-semantic-conventions` **0.65b0**, the version the 2.6 capture
ran under, defines nine values for `gen_ai.operation.name`:

```
chat  create_agent  embeddings  execute_tool  generate_content
invoke_agent  invoke_workflow  retrieval  text_completion
```

The adapter maps seven. `invoke_workflow` and `retrieval` are the two it does
not, so `invoke_workflow` is a value this dialect really can emit and this
adapter really cannot map — which is the whole of what this scenario is about.

This is the weakest provenance in the corpus after
`parallel_tool_calls`, and it is marked as such. It is a claim about the
**convention**, checked against the installed package, rather than a claim
about an **instrumentor**, which only a capture can settle. A captured span
carrying an unmapped operation would retire this note.

## What it deliberately does not do

It does not map `invoke_workflow` to `NodeKind.chain`, though `SPEC.md` §3.2's
definition — "a composite step with no more specific kind" — fits it well.
Mapping it would be deriving adapter behaviour from a reading of a
specification, which is exactly the defect `FIXTURES.md` §5.1 exists for, and
it would also silently retire `cyclic_parents`' coverage declaration. Recorded
at `TASKS.md` 2.10 as a candidate for a capture to settle.

## The one thing this rendering proves that nothing else does

Both dialects reach `kind: unknown` **plus** a diagnostic, from operation
vocabularies with nothing in common — no shared attribute, no shared spelling,
no shared enum. The canonical graphs differ by exactly one line, and that line
is `attributes.reported_kind`, which is *supposed* to differ. See
`scenario.md` for why it can never do anything else.
