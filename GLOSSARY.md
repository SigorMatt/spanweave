# GLOSSARY.md — terms of art

These words are used precisely throughout the docs, the code, and the fixtures.
Where a term has a loose everyday meaning, the definition here is the binding
one. Using them loosely is how a neutral library acquires opinions by accident.

---

**Adapter** — A module that translates exactly one telemetry **dialect** into
`NormalizedSpan[]`. The only place dialect knowledge may live (`ADAPTERS.md`).

**Annotation** — A consumer-supplied, namespaced key/value attached to a node.
The library never reads one to change its own behavior (`SPEC.md` §8).

**Basis** — The short, stable string on an **edge** naming the exact rule or
field that produced it (`"span.parent_span_id"`, `"tool_call_id"`,
`"sibling start_time ordering"`). What makes an edge auditable rather than
merely trusted.

**Builder** — The dialect-agnostic stage that turns `NormalizedSpan[]` into a
**Graph**. It never learns a dialect name (`DESIGN.md` §3).

**Canonical graph** — The dialect-independent form of a scenario's expected
graph, after erasing legitimately dialect-specific fields. The object all
dialects of a scenario must agree on (`FIXTURES.md` §4).

**Captured fixture** — A trace produced by real instrumentation on a real run,
committed by a human with provenance. Never synthesized. Distinct from a
hand-authored **dialect rendering** (`FIXTURES.md` §6).

**Conformance corpus** — `fixtures/conformance/`: scenarios expressed in
multiple dialects with one canonical graph each. The executable form of the
library's central claim.

**Derived** — A **warrant** value meaning `spanweave` computed the relation from
a stated rule. Contrast **explicit**. Never promoted to explicit
(`CLAUDE.md` 3).

**Dialect** — One instrumentor's or framework's way of expressing a trace:
its attribute keys, nesting conventions, and id fields. OpenInference, OTel
GenAI, Langfuse, and Logfire are dialects.

**Diagnostic** — A structured record of something the library could not
confidently map. Part of the output, not log noise. The alternative to guessing
(`SPEC.md` §3.7).

**Edge kind** — The typed relation an edge asserts: `parent`, `call_result`,
`data`, `link`, `temporal`. A closed enum (`SPEC.md` §4).

**Explicit** — A **warrant** value meaning the telemetry itself asserted the
relation; the adapter is transcribing, not reasoning.

**Falsification consumer** — A deliberately unrelated tool built on the library
to test whether the model serves uses it wasn't designed for. Phase 3's gate,
living in `examples/` (`ROADMAP.md`).

**Graph** — The output object: nodes, edges, diagnostics, annotations, meta.
Immutable.

**Losslessness** — The invariant that every input record becomes a node and/or a
diagnostic, with its source preserved verbatim. Nothing is silently dropped
(`CLAUDE.md` 2).

**Node kind** — The classification of an operation: `agent`, `llm`, `tool`,
`retriever`, `embedding`, `chain`, `unknown`. A closed enum (`SPEC.md` §3.2).

**NormalizedSpan** — The seam type between adapter and builder. Internal; **not**
a public contract (`DESIGN.md` §3.1).

**Operational option** — A consumer-requested change that alters what is kept or
how it is obtained (retention, laziness, multi-trace handling) but not what a
graph *is*. Permitted and additive. Contrast **shape change**
(`PREDICTIONS.md`).

**Payload state** — One of `present`, `empty`, `absent`, `redacted`,
`truncated`. The distinction between *absent* and *empty* is load-bearing:
"we weren't told" and "there was nothing" are different statements about the
world (`SPEC.md` §3.3).

**Provenance** — Which adapter, at which version, produced a node — and, for
captured fixtures, the human record of how a trace was obtained and redacted.

**Scenario** — One structural situation in the corpus, described semantics-free,
rendered in every supported dialect (`FIXTURES.md` §2).

**Semantic neutrality** — The invariant that core assigns no roles, severity,
risk, cost, or quality judgement. The product, not a preference
(`CLAUDE.md` 1).

**Shape change** — A new field, `NodeKind`, `EdgeKind`, warrant, `Payload`
state, `Diagnostic` code, or query primitive: something the model cannot
currently express. A model failure, hard-gated at zero in Phase 3. Contrast
**operational option** (`PREDICTIONS.md`).

**Trace** — One run's worth of telemetry, sharing a `trace_id`. One input file =
one trace (`SPEC.md` §7).

**Warrant** — How an edge's relation was established: `explicit` or `derived`.
The mechanism that lets a consumer choose which relations to trust
(`SPEC.md` §4.1).
