# retriever_and_embedding

A chain span containing an embedding span and a retriever span. The two node
kinds nothing else in the corpus exercises.

## Structure

Nodes: 1 `chain`, 1 `embedding`, 1 `retriever`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1, s0→s2 |
| `temporal` | derived | `sibling start_time ordering` | s1→s2 |

Node order: s0, s1, s2.

## Operations

`s1.operation` is `demo-embed`, from `embedding.model_name`. **`s2.operation`
is `null`**: OpenInference names the model on an embedding span and names
nothing on a retriever span, and there is no rule by which a retriever's name
could be recovered. Filling it from the span name would be inventing a
distinction the dialect does not draw.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `absent` | `absent` |
| s1 | `present` (text/plain) | `absent` |
| s2 | `absent` | `present` (application/json) |

The retrieved documents are the retriever's output payload, parsed. They are
not nodes: message- and document-level granularity is deliberately open
(`OPEN_QUESTIONS.md` §2).

## Diagnostics

None.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — **declared unrenderable** (`expected/coverage.json`)

**Not for the reason anyone expected — and the reason has now changed three
times.** `TASKS.md` 2.11 flagged this as the most likely coverage candidate on
the grounds that GenAI's vocabulary might not name a retriever. It does: the
convention defines `retrieval`, the adapter maps it to `NodeKind.retriever`,
and `embeddings` was already mapped. So 2.11 recorded that the blocker was
`s0`, the **chain** parent. 2.16 measured that and found a second blocker in
the retriever's *payloads*. 2.17 fixed one of those and found that the other
one was somewhere else again.

Where it stands, measured at `TASKS.md` 2.17:

| Node | Field | `otel_genai` | Status |
|---|---|---|---|
| `s2` | `outputs` | `gen_ai.retrieval.documents`, parsed | **fixed** — agrees exactly |
| `s1` | `inputs` | `absent` | **blocker 1** |
| `s0` | `kind` | `unknown` | **blocker 2** |

### Blocker 1 — the dialect has no content attribute for an embedding span

`opentelemetry-util-genai` 1.1b0's `EmbeddingInvocation` emits
`gen_ai.embeddings.dimension.count`, `gen_ai.request.encoding_formats`,
`gen_ai.response.model` and token counts. **Nothing carrying the embedded
text.** So there is no attribute to render, and putting the text under
`gen_ai.input.messages` would be inventing one.

That makes `s1.inputs` `absent` where OpenInference records it `present`, and
`FIXTURES.md` §4.4 forbids declaring a payload's **state** away, ever: `absent`
≠ `present` is the model's central honesty claim, and a disagreement about it
must stay visible rather than be absorbed. This blocker is a property of the
dialect rather than an adapter gap, and **no captured trace can retire it** —
only a change to the convention could.

### Blocker 2 — the chain parent

`s0`, for the reason `cyclic_parents` and `span_links` carry: no
`gen_ai.operation.name` value denotes a chain, and the one candidate,
`invoke_workflow`, was decided at `TASKS.md` 2.16 and endorsed as **not
mapped** — on provenance rather than on definition.

**Blocker 1 outlives blocker 2, and that was measured rather than assumed:**
with `invoke_workflow` hypothetically mapped to `chain`, this scenario still
fails on `s1.inputs` alone. If that decision is ever reversed, this scenario
must **not** be retired alongside the other two.

### What was fixed, and on what evidence

The adapter now reads `gen_ai.retrieval.documents` (`application/json`, parsed)
and `gen_ai.retrieval.query.text` (`text/plain`, **not** parsed — the dialect
states that one is a plain string).

**Neither attribute appears in any captured trace in this repo.** Three traces,
17 spans, and not a `retrieval` or `embeddings` span among them. They were
mapped from `opentelemetry-util-genai` 1.1b0's `_retrieval_invocation.py` — the
support library the captured traces' own instrumentor delegates to for
`gen_ai.input.messages`, so the same source read at the same version. The
registry alone would not have done: in `opentelemetry-semantic-conventions`
0.65b0 every `gen_ai.*` docstring has been replaced by the notice that the
conventions moved house, leaving names and no structure.

That provenance is **weaker than a capture**, and it is recorded here rather
than left for a reader to discover, because it is the difference between what
this fixture could claim and what it can.
