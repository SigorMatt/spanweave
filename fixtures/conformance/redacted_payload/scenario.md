# redacted_payload

An LLM span whose payloads the **instrumentor** suppressed.
`openinference-instrumentation` replaces a hidden value with the literal
string `__REDACTED__` rather than omitting the attribute — which is precisely
what keeps `redacted` and `absent` distinguishable here.

## Upstream corroboration

That sentinel is not a convenience we read into the dialect. The OpenInference
specification (`Arize-ai/openinference`) states that `__REDACTED__` exists so
that a consumer can tell **hidden** content from **missing or empty** content,
and its Go instrumentors accordingly *replace* `input.value` / `output.value`
with the sentinel rather than omitting the attribute.

That is the same argument this library's five-state `Payload` makes, reached
independently by the people who emit the data: "we withheld this", "there was
nothing", and "we weren't told" are three different statements about the
world, and a model that collapses them makes its consumers report the same
thing for all three (`SPEC.md` §3.3).

It is worth recording as **evidence rather than agreement**. The
redacted-vs-absent distinction was a design position in `SPEC.md` before this
adapter existed; finding an upstream instrumentor that had already paid the
cost of the same distinction is the closest thing available to an independent
check that the position is right and not merely ours. Corroboration supplied
in Phase 1 review.

## Structure

Nodes: 1 `llm`.

Edges: none.

Node order: s0.

## Payloads

| Node | inputs | outputs |
|---|---|---|
| s0 | `redacted` | `redacted` |

`value` is `null` on both: there is no content to parse. The marker itself
survives verbatim in `Payload.raw` (erased by `canonical()`, since the marker
string is a dialect convention) and in `Node.raw`.

The library **marks what the source marked**. It never redacts anything
itself, and it never un-redacts anything either (`SPEC.md` §9).

## Usage

None reported.

## Diagnostics

None. A redaction the source performed is not a mapping failure.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — **declared unrenderable** (`expected/coverage.json`)

The dialect defines no redaction marker, and the thing it *can* do — omit the
content attribute when capture is off — is `absent`, a different state and a
different fact. `state` is the one field no declaration may set aside, so
rendering it any other way would not be this scenario. The reason in
`coverage.json` names the three checks behind it, and §4.3 makes it an
invitation to recheck rather than a settled fact.
