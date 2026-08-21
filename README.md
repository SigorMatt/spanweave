# spanweave

Turn agentic-system telemetry into a **graph you can reason over** — without
inheriting anyone's opinions about what the telemetry means.

`spanweave` ingests execution traces from agent frameworks and instrumentors
(OpenInference, OTel GenAI, and more) and produces one normalized, deterministic,
**semantically neutral** graph. It assigns no roles, no severity, no cost, no
risk. It tells you what the telemetry observed and how it knows — and then gets
out of your way.

```python
import spanweave

graph = spanweave.build("trace.jsonl")

for node in graph.nodes(kind="tool"):
    print(node.name, node.inputs.state, node.outputs.state)

# Traverse only the edges you trust:
causal = graph.subgraph(edge_kinds={"parent", "call_result"})
```

```
$ spanweave build trace.jsonl -o graph.json
$ spanweave inspect trace.jsonl
```

## Why this exists

Every instrumentor disagrees about attribute keys for the same three facts:
*what was called, with what, returning what*. Reconciling those — plus
tool-call↔result pairing, agent nesting, retries, errors, partial payloads —
is tedious, genuinely hard, and completely opinion-free work that every
downstream tool currently redoes badly.

`spanweave` does that work once. What you build on top is yours.

## The central design idea: typed edges with a stated warrant

`spanweave` never emits "an edge." Every edge declares **what kind of relation
it is** and **how that relation was established**:

| Edge kind | Meaning | Typical warrant |
|---|---|---|
| `parent` | span hierarchy | `explicit` — the telemetry said so |
| `call_result` | a requested tool call and the span that fulfilled it | `explicit` — id linkage |
| `data` | an output feeds an input | `explicit` only — never inferred |
| `link` | cross-trace span link | `explicit` |
| `temporal` | one operation started before another | `derived` — computed from timestamps |

A consumer that needs causal grounding walks `parent` + `call_result`. A
consumer that just needs a timeline walks `temporal`. Nobody is forced to accept
an inference they didn't ask for, and nothing is presented as observed when it
was computed.

This is what makes one graph shape serve uses it wasn't designed for.

## What spanweave does **not** do

These are permanent non-goals, not a backlog. See `SPEC.md` §9.

- **No semantics.** No roles (source / sensitive / sink), no severity, no risk,
  no quality scores, no dollar costs.
- **No inferred data flow.** It will not guess that A's output reached B's
  input. That is your analysis, on top of the graph.
- **No enforcement, no runtime.** It never sits in a request path.
- **No network, ever.** It reads files and stdin; it writes files and stdout.
- **No execution of payload content.** Trace payloads are treated as hostile
  data (`SECURITY.md`).

## Guarantees

- **Deterministic.** Same input bytes → byte-identical graph. Sorted adjacency,
  explicit tie-breaks, no clocks, no randomness, no salted hashing.
- **Lossless.** Every node keeps its verbatim source record. Anything that can't
  be mapped becomes a **diagnostic**, never a silent discard.
- **Zero runtime dependencies.** Core is stdlib-pure and readable in one sitting.
- **Dialect-agnostic core.** Adding a dialect is a new *adapter*, never a change
  to the graph model.

## Conformance

Every scenario in `fixtures/conformance/` is expressed in **multiple dialects**
that must all produce the **same canonical graph**. That equivalence is the
library's entire reason to exist, and it is a test, not a claim.

## Status

Early development. Phase 1 is the vertical slice — one dialect (OpenInference)
read end to end into a graph, with the conformance corpus, the query surface,
annotations, canonical serialization, and the CLI. A second adapter, which
exists to *falsify* this model rather than confirm it, is Phase 2.

**The graph schema is not frozen.**

It stays unfrozen through the `0.9.x` release: publishing is reversible and
freezing is not, so the launch happens first and the freeze happens on evidence
(`ROADMAP.md`). Until `1.0.0`, treat the schema as subject to change and pin
your version.

## Development

```
uv sync --extra dev
make check          # the gate: lint, types, tests, the invariant gates, the CLI
make conformance    # the corpus: every scenario, against its canonical graph
```

`make capture` is human-run only and makes a real model call — see
`capture/README.md`.

## Documents

| File | Purpose |
|---|---|
| `SPEC.md` | Behavior. Source of truth. |
| `DESIGN.md` | Architecture and technology decisions. |
| `CLAUDE.md` | Operating contract + non-negotiable invariants. |
| `AGENT.md` | Autonomous build brief (run loop, halt points). |
| `ROADMAP.md` | Phase sequencing. |
| `TASKS.md` | PR-sized checklist. |
| `FIXTURES.md` | The conformance corpus contract. |
| `ADAPTERS.md` | How to write an adapter (the contribution path). |
| `ENVIRONMENT.md` | Runtime & toolchain contract. |
| `GLOSSARY.md` | Terms of art, used precisely. |
| `OPEN_QUESTIONS.md` | Deliberately unresolved decisions. |
| `PREDICTIONS.md` | Where this model is predicted to be wrong — written before the test. |
| `SECURITY.md` | Threat model and reporting. |
| `CONTRIBUTING.md` | How to contribute. |

## License

MIT.
