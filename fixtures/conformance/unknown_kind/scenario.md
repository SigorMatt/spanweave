# unknown_kind

A span whose reported kind the library does not map. Real dialects invent
kinds constantly — `guardrail`, `reranker`, `router`, `handoff` — and
`NodeKind` is deliberately closed (`OPEN_QUESTIONS.md` §1).

## Structure

Nodes: 1 `agent`, 1 `unknown`.

Edges: 1 `parent` (explicit, `span.parent_span_id`), s0→s1.

Node order: s0, s1.

## The unknown node

`s1.kind` is `unknown`, and `s1.attributes.reported_kind` is `"GUARDRAIL"` —
the original string, preserved. It appears in the diagnostic too.

`unknown` is a **first-class outcome, not a failure** (`SPEC.md` §3.2). The
alternative a hurried implementation reaches for is to force the near-miss
into a neighbouring kind, and a wrong kind is worse than an honest unknown
precisely because `unknown` is visible and a wrong kind is not.

## Payloads

All `absent`.

## Diagnostics

| Code | Count | On |
|---|---|---|
| `unknown_span_kind` | 1 | s1 |

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.10)

Two things are declared dialect-varying (`expected/comparison.json`): `name`,
for the reason every scenario here declares it, and — uniquely in this corpus
— **one key of one node's `attributes`**, `attributes.reported_kind`
(`FIXTURES.md` §4.5).

### Why the two dialects cannot agree on `reported_kind`, ever

Not a quirk of these two dialects, and not something a better adapter would
fix. `reported_kind` is **by definition** the dialect's own verbatim token for
a kind the library could not map — that is the entire content of the field. So
two dialects drawing from two vocabularies necessarily put two different
strings there, and an adapter that made them agree would be **lying about what
it read**: either normalizing a token whose only job is to be unnormalized, or
reporting a string the instrumentor never wrote.

The corpus therefore declares it rather than erasing `attributes` wholesale.
The rest of the mapping is compared as usual — `model` agrees across dialects
everywhere it appears — and the disagreement is a recorded fact rather than an
absence. It expires like any other declaration: if the two dialects ever agree
on `reported_kind`, the staleness test deletes it.

### The tokens, and why each is the honest one

| | attribute | value | why this one |
|---|---|---|---|
| `openinference` | `openinference.span.kind` | `GUARDRAIL` | Phase 1; a kind the dialect's own vocabulary has and `NodeKind` does not |
| `otel_genai` | `gen_ai.operation.name` | `invoke_workflow` | one of the **nine** values `opentelemetry-semantic-conventions` 0.65b0 defines, and **the only one** this adapter does not map |

`invoke_workflow` is not invented to make a point: it is read from the
convention's own registry, at the version 2.6's capture ran under, and it is
genuinely unmapped. `SPEC.md` §3.2 defines `chain` as "a composite step with no
more specific kind", which makes it a real candidate — deliberately not taken,
because mapping it is a judgement rather than the name match every other
`OPERATIONS` entry is. That candidacy is recorded at `TASKS.md` 2.10 and is why
`cyclic_parents` and `span_links` are declared unrenderable.

### This rendering is what the `chain` candidacy costs

`invoke_workflow` is the adapter's **only** unmapped convention value, so this
scenario's `otel_genai` half depends on it staying unmapped. `TASKS.md` 2.16
measured the consequence rather than predicting it: with `invoke_workflow`
mapped to `chain`, this rendering builds `s1` as a `chain` with no diagnostic
and **fails** its expected graph.

Recovering it would mean picking a `gen_ai.operation.name` value that is *not*
in the convention's registry — which is precisely what the table above says this
rendering deliberately avoided, and which no observed output supports
(`FIXTURES.md` §5.1). So the `chain` decision is not "retire three declarations
for free": it retires two, leaves `retriever_and_embedding` blocked for an
unrelated reason, and takes this rendering's principled specimen with it. That
trade belongs in the decision, and it is why the decision is a human's.
