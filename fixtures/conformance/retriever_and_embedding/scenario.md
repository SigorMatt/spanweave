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
- [ ] `otel_genai` — Phase 2
