# spanweave

Turn agentic-system telemetry into a **graph you can reason over** — without
inheriting anyone's opinions about what the telemetry means.

`spanweave` ingests execution traces from agent frameworks and instrumentors —
**OpenInference and OTel GenAI** today — and produces one normalized,
deterministic, **semantically neutral** graph. It assigns no roles, no severity,
no cost, no risk. It tells you what the telemetry observed and how it knows —
and then gets out of your way. A dialect it does not read yet is a new
*adapter*, never a change to the graph model (`ADAPTERS.md`).

Point it at a trace. Every path below is a file that ships in this repository,
so the whole of this section runs as written from a checkout:

```
$ spanweave inspect fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl
trace: t1
schema: 0.1  (NOT FROZEN)
adapters: openinference 0.1.0

nodes: 4
  agent: 1
  llm: 2
  tool: 1
edges: 7
  call_result (explicit): 1
  data (explicit): 1
  parent (explicit): 3
  temporal (derived): 2
payloads:
  inputs  present: 4
  outputs absent: 1
  outputs present: 3
diagnostics: 2
  unmapped_attributes: 2
```

**That output is the library in one screen**, and it is worth reading before
writing any code against it:

- **Every edge says how it was established.** `explicit` means the telemetry
  asserted the relation; `derived` means spanweave computed it from a stated
  rule. The two `temporal` edges are inferences and are labelled as inferences.
  Nothing is presented as observed when it was computed.
- **`absent` is a state, not a blank.** One output payload was never recorded,
  and that is a different fact from an empty one or a redacted one. The
  distinction survives into the graph rather than being flattened.
- **Two attributes could not be mapped, and they are diagnostics, not
  discards.** "We didn't understand it" is a reportable outcome here. Nothing
  vanishes quietly.
- **The schema is not frozen**, and it says so on every run until `1.0.0`.

Then build one and query it:

```
$ spanweave build fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl -o graph.json
wrote graph.json
```

```python
import spanweave

# Any OpenInference or OTel GenAI trace. This one ships with the repository.
trace = "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
graph = spanweave.build(trace)

for node in graph.nodes(kind="tool"):
    # `name` is the one field two dialects may spell differently, and the
    # corpus does not compare it. See Conformance, below, before you match on it.
    print(node.name, node.inputs.state, node.outputs.state)

# Traverse only the edges you trust:
causal = graph.subgraph(edge_kinds={"parent", "call_result"})
print(len(list(causal.edges())), "edges you can defend")
```

```
tool.lookup present present
4 edges you can defend
```

## Install

**`spanweave` is not on PyPI yet, so there is no `pip install spanweave`.** The
two instructions below are the ones that resolve today; the index one lands in
the same change as the first release, and not before — a README promising an
install that 404s is the first thing a stranger tries.

From a checkout:

```
$ git clone https://github.com/SigorMatt/spanweave
$ cd spanweave
$ pip install .
```

From a wheel you build yourself:

```
$ uv build
$ pip install dist/spanweave-0.9.0-py3-none-any.whl
```

Either way `import spanweave` and the `spanweave` command work with **no
runtime dependencies**; Python 3.11+ is the only requirement. `make
install-check` is the gate that proves the built wheel works from outside this
repo.

The conformance corpus in `fixtures/` is deliberately **not** in the wheel — it
is development data, not library code. The paths in the section above therefore
resolve from a checkout or an unpacked sdist, which is where a first look
belongs anyway. Installed from a wheel alone, `spanweave` reads your own traces
and ships no sample of ours.

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

A scenario in `fixtures/conformance/` is one run, rendered in **each dialect
that can express it**, and every rendering must produce that scenario's **single
canonical graph**. That equivalence is the library's entire reason to exist, and
it is a test, not a claim: `make conformance`.

**What it covers today, in numbers rather than adjectives.** The corpus holds
**21** scenarios. **17** are rendered in both dialects and compared across them.
The other **4** are rendered in one, because the second dialect genuinely cannot
express them — and each says so in a `coverage.json` file carrying the reason,
because silence would be indistinguishable from an adapter nobody got round to
(`FIXTURES.md` §4.3).

**One field is set aside, said here rather than found later.** A scenario may
declare a field *dialect-varying* — a reviewable file in the corpus, never a
branch in the comparison code (`FIXTURES.md` §4.4). One field is declared almost
everywhere: `name`, the span name, which two instrumentors are least likely to
spell the same way. **16 of those 17 cross-dialect scenarios declare it**, so
the equivalence claim above is a statement about everything else — ids, kinds,
operations, timestamps, statuses, payload states and values, usage, and every
edge with its warrant and basis. **If you are matching nodes by `name` across
dialects, nothing here has tested that for you.** `CONTRACTS.md` carries the
measurement.

## Status

Early development. This is `0.9.0` — the first version meant for anyone outside
this repository, not yet on a package index (see **Install**), and `0.9` rather
than `1.0` on purpose: see the schema note below.

**What exists.** Two adapters, `openinference` and `otel_genai`, both registered
and both run against the whole corpus (`spanweave adapters`). The graph model,
the query surface, annotations, canonical serialization, the CLI (`build`,
`inspect`, `validate`, `adapters`), and the conformance corpus described above.
Three consumers in `examples/` — a trajectory dumper, a cost/latency attributor,
and a fleet aggregator — each reading committed fixtures through the public API
and nothing else.

**What that second adapter was for.** It exists to *falsify* this model rather
than confirm it: if one graph shape cannot carry two independently designed
instrumentors, the shape is wrong, and the corpus is where that would show. It
did show things — the four scenarios above that the second dialect cannot
express, and the `name` bound — which is the mechanism working, not a result to
round off. The examples were the same exercise pointed the other way. The two
confirmatory ones needed no change to the library; the adversarial one, written
to break it, produced nine findings, one of which is why the error types are on
the public API today.

**What does not exist yet.** A third dialect, the binary OTLP form, streaming or
any receiver, and a frozen schema. None of these is on a date.

**The graph schema is not frozen.**

It stays unfrozen through the `0.9.x` release: publishing is reversible and
freezing is not, so the launch happens first and the freeze happens on evidence
(`ROADMAP.md`). Until `1.0.0`, treat the schema as subject to change.

**Pin on the spanweave version, not on `schema_version`.** While unfrozen,
`schema_version` is a single bucket for the whole of `0.x` and does **not**
track changes to the serialized graph — it has not moved across two of them
already, and it will not move before the freeze (`SPEC.md` §3.9). The field
that does move is the library version, and `meta.spanweave_version` carries it
in every graph document, so you can read it from the file itself.

What stops a change to the serialized graph shipping unnoticed is not that
field but a committed shape artifact (`tests/serialized_shape.json`): the
document's field names, types and nesting are pinned, and moving any of them
fails the build until the change is regenerated into the diff.

## Development

```
uv sync --extra dev
make check          # the gate: lint, types, tests, the invariant gates, the CLI
make conformance    # the corpus: every scenario, against its canonical graph
make install-check  # build the wheel, install it, run it from OUTSIDE this repo
make shape          # regenerate tests/serialized_shape.json (see above)
make stranger       # walk and time the install path above, from a clean venv
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
| `CONTRACTS.md` | What every permissively-typed serialized field states and asserts — including where the answer is *nothing*. |
| `ENVIRONMENT.md` | Runtime & toolchain contract. |
| `GLOSSARY.md` | Terms of art, used precisely. |
| `OPEN_QUESTIONS.md` | Deliberately unresolved decisions. |
| `PREDICTIONS.md` | Where this model is predicted to be wrong — written before the test. |
| `SECURITY.md` | Threat model and reporting. |
| `CONTRIBUTING.md` | How to contribute. |

## License

MIT.
