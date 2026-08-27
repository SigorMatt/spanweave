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

**Not for the reason anyone expected — twice now.** `TASKS.md` 2.11 flagged
this as the most likely coverage candidate on the grounds that GenAI's
vocabulary might not name a retriever. It does: the convention defines
`retrieval`, the adapter maps it to `NodeKind.retriever`, and `embeddings` was
already mapped. So 2.11 recorded that the blocker was `s0`, the **chain**
parent, which no mapped operation produces.

**That was also incomplete.** `TASKS.md` 2.16 measured it: this scenario has
**two independent blockers**, and the chain parent is not the binding one.

`s2.outputs` is `absent` in `otel_genai` under every candidate attribute,
because the adapter reads neither `gen_ai.retrieval.documents` nor
`gen_ai.retrieval.query.text` — both of which the convention **does** define
(`opentelemetry-semantic-conventions` 0.65b0) and neither of which this adapter
consumes. `FIXTURES.md` §4.4 forbids setting a payload's `state` aside, ever:
`absent` ≠ `present` is a real disagreement and must stay visible. Rendering it
would need the adapter to learn two attributes written from the convention
registry, with no captured `retrieval` or `embeddings` span anywhere in the
repo — the reading-not-observation `FIXTURES.md` §5.1 forbids.

So the retriever *is* a blocker after all, one level down: at the payload rather
than at the kind. **This blocker outlives the `chain` decision** — mapping
`invoke_workflow` would not make this scenario renderable, and it must not be
retired alongside `cyclic_parents` and `span_links`.
