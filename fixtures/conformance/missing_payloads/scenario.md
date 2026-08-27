# missing_payloads

A tool span that reports **no payload attributes at all**. The instrumentor
emitted nothing, so the model says nothing.

Contrast `empty_payload`, where the instrumentor emitted an attribute whose
content is empty. Collapsing those two is the most common way a telemetry tool
becomes quietly dishonest: a consumer can no longer tell "there was nothing"
from "we weren't told", and reports the same thing for both (`SPEC.md` §3.3).

## Structure

Nodes: 1 `agent`, 1 `tool`.

Edges: 1 `parent` (explicit, `span.parent_span_id`), s0→s1.

Node order: s0, s1.

## Payloads

Every payload on both nodes is **`absent`**, and none of them is `empty`.

## Diagnostics

None. A span without payloads is ordinary telemetry, not a failure to map
something — the model has a state that says exactly what happened.

## Dialects

- [x] `openinference` — Phase 1
- [x] `otel_genai` — Phase 2 (2.10)

`name` is declared dialect-varying (`expected/comparison.json`): the OTel GenAI
convention prescribes the span name as `<operation> <target>`, so a faithful
rendering cannot reuse OpenInference's. Nothing else is declared — with no
payload attributes on either span there is nothing left for two dialects to
disagree about, which is what makes this the cheapest cross-dialect check in
the corpus and a good first one to read.
