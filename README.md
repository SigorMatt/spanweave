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
nodes by adapter:
  openinference: 4
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
- **Every node says which adapter produced it.** Here one adapter read
  everything, so the tally is a single line. It stops being one when a trace
  carries two instrumentors' spans: a dialect is a property of a *record*, not
  of a file, so one file can hold both and each node still names its own
  reader (`SPEC.md` §6.1). Nothing about that is a mode you select — it is what
  `spanweave` does when you name no adapter, and `--adapter auto` is that
  default spelled out.
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

```
$ pip install spanweave
```

From a checkout:

```
$ git clone https://github.com/SigorMatt/spanweave
$ cd spanweave
$ pip install .
```

From a wheel you build yourself:

```
$ uv build
$ pip install dist/spanweave-0.9.1-py3-none-any.whl
```

Any of the three gives you `import spanweave` and the `spanweave` command with
**no runtime dependencies**; Python 3.11+ is the only requirement. Nothing is
pulled in behind them: on a fresh `pip install spanweave`, `pip show spanweave`
reports an empty `Requires`.

The distribution is **typed for consumers**: it carries the PEP 561 marker
`spanweave/py.typed`, so `mypy --strict` in your own code reads spanweave's
annotations instead of skipping the import — no `ignore_missing_imports` and no
`follow_untyped_imports` override.

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

- **Deterministic.** Same input bytes → byte-identical graph, on any machine
  and under any interpreter configuration. Sorted adjacency, explicit
  tie-breaks, no clocks, no randomness, no salted hashing, and an integer
  digit limit of the library's own rather than the interpreter's
  (`SPEC.md` §5.3).
- **Lossless.** Every node keeps its verbatim source record. Anything that can't
  be mapped becomes a **diagnostic**, never a silent discard.
- **Zero runtime dependencies.** Core is stdlib-pure and readable in one sitting.
- **Dialect-agnostic core.** Adding a dialect is a new *adapter*, never a change
  to the graph model.

## Building a graph while the trace is still arriving

A file is the finished case. When records are still arriving — off a socket,
tailed out of an exporter, one OTLP/HTTP body at a time — the same build runs
one record at a time (`SPEC.md` §10). `Builder` is that build taken
incrementally, not a second builder with rules of its own:

- **`Builder()` takes the wiring `build()` takes** — an `adapter` name, or none
  for the same auto-selection, and `temporal` to switch off the derived
  timeline.
- **`feed(record)` absorbs one record and returns the new version**, an integer
  counting records absorbed in arrival order and nothing else.
- **`graph()` materializes the prefix graph** — an ordinary `Graph`, carrying no
  version number and indistinguishable from one built from a file.
- **`delta(since=v)` says what changed** between version `v` and now: nodes,
  edges and diagnostics added and removed, each collection in the graph's own
  canonical order. It is *defined* as the difference between the two graphs, so
  it cancels — a diagnostic that opened and closed inside the window is in
  neither half, because it is in neither endpoint.
- **`fold(graph)` on a `Delta` applies that difference** and returns a new
  graph, byte for byte the `graph()` of the later version. Something it must
  remove and cannot find raises rather than producing a quietly wrong graph.
- **`retain(versions=N | "all" | 0)` is your journal policy**, `"all"` by
  default. A `since` the journal no longer holds raises
  `DeltaUnavailableError` — never a truncated delta, and never a whole graph
  offered in its place, because a caller that asked what changed and was handed
  something else could not tell.

**Three ways to consume it, and the corpus replays all three over every
rendering it holds** (`FIXTURES.md` §4): feed silently and materialize once at
the end; feed and materialize after every record; feed and take
`delta(since=version - 1)` each time, folding it onto the graph you already
hold. A `Delta` comes only from `delta(since=v)` — `feed` returns the version
and never a delta.

**The promise under all of it is prefix consistency.** At version `k`,
`graph()` is the graph the batch builder produces from those same `k` records,
as a value and as the bytes it serializes to (`SPEC.md` §10.1). Determinism,
losslessness, warrant and canonical order are inherited from that equality
rather than restated for the live path — and so is the serialized shape, which
does not move for this feature: there is no live-only field, and no graph
carries a version.

**What it cannot tell you, because it was never told.** A builder is fed
records, not bytes, so it reports no `meta.source_digest` and none of a
reader's facts about an input — a line that was not JSON, a record sent twice,
a record skipped before any adapter saw it (`SPEC.md` §10.4). Those belong to
whoever read the records, and a builder claiming them would be describing an
input it never saw.

**`read_records(data)` is that reader, on bytes instead of a path.** It takes
`bytes`, a `bytearray` or a `memoryview` of single bytes — what a receiver
actually holds — recognizes the same three containers the file and stdin forms
do, and returns a `Records`: the records in input order, the diagnostics the
read produced, and `skipped_records`. It consults no adapter, names no dialect
and builds nothing. **The reader neither buffers nor rejoins across calls**, so
a multi-byte character split between two chunks is half a character in each: a
receiver reading bytes in flight splits them on `\n` and keeps the remainder
for its next call, rather than handing over an arbitrary boundary
(`SPEC.md` §7).

**A delta serializes to its own top-level document** — `delta_to_document` for
the mapping, `delta_dumps` for the bytes — with `kind` telling it from a
graph's. Nodes, edges and diagnostics are written by the same functions that
write them into a graph document, so a consumer that reads one reads the other,
and the graph document gains no key for any of this (`SPEC.md` §10.9).
`basis_rewritten` is a *view* over the edge sets rather than a field: an edge's
identity includes its `basis`, so a `data` edge whose basis changed is one edge
removed and one added, and the view pairs them as `BasisRewrite` so a consumer
need not rediscover them.

Worked, from a checkout. The trace is the one the quickstart uses, read as
bytes rather than as a file, and fed one record at a time:

```python
import pathlib

import spanweave

# Bytes already in memory -- an OTLP/HTTP body, a chunk tailed off an
# exporter, a message off a queue. This one came off disk so it runs here.
trace = "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
records = spanweave.read_records(pathlib.Path(trace).read_bytes())
print(len(records.records), "records,", records.skipped_records, "skipped")

builder = spanweave.Builder()
for record in records:
    version = builder.feed(record)
    change = builder.delta(since=version - 1)
    print(
        f"v{version}",
        f"+{len(change.nodes_added)} nodes",
        f"+{len(change.edges_added)} edges",
        "opened", sorted(d.code for d in change.diagnostics_opened),
        "resolved", sorted(d.code for d in change.diagnostics_resolved),
    )

# A delta over a wider window, in its own document form.
document = spanweave.delta_to_document(builder.delta(since=2))
print(document["kind"], document["since"], "->", document["until"])

# Prefix consistency, and the one fact a builder cannot carry.
live = spanweave.to_document(builder.graph())
batch = spanweave.to_document(spanweave.build(trace))
print("documents differ in:", [k for k in batch if live[k] != batch[k]])
print("meta differs in:",
      [k for k in batch["meta"] if live["meta"][k] != batch["meta"][k]])
```

```
4 records, 0 skipped
v1 +1 nodes +0 edges opened [] resolved []
v2 +1 nodes +1 edges opened ['unmapped_attributes', 'unpaired_call'] resolved []
v3 +1 nodes +3 edges opened [] resolved ['unpaired_call']
v4 +1 nodes +3 edges opened ['unmapped_attributes'] resolved []
delta 2 -> 4
documents differ in: ['meta']
meta differs in: ['source_digest']
```

`unpaired_call` is open at version 2 and gone at version 3, and both are
correct: the fulfilling span arrived in between. Nothing on a live graph is a
prediction and nothing is a retraction — the graph at a version says what the
records up to it support, so a resolved diagnostic is simply absent, exactly as
it is in a batch graph (`SPEC.md` §10.3).

One builder per trace. Completion is not the library's: OTel has no end marker,
"this trace is finished" is a timeout policy you set, and no threads, sockets,
clocks or callbacks come with any of this (`SPEC.md` §10.10).

## The public API, in one table

`import spanweave` gives you exactly these names. Everything else is internal
and may be refactored without notice (`CLAUDE.md`), so a consumer that reaches
past this list is on its own — which is a rule the examples are held to by a
test, not a request.

| For | Names |
|---|---|
| Building a graph | `build`, `Builder` |
| Reading records without building one | `read_records`, `Records` |
| The graph and what it holds | `Graph`, `Node`, `Edge`, `Diagnostic`, `Meta`, `Payload`, `Provenance`, `RawRecord`, `Status`, `Usage` |
| The closed vocabularies | `NodeKind`, `EdgeKind`, `Warrant`, `PayloadState`, `DiagnosticLevel` |
| What changed between two versions | `Delta`, `BasisRewrite` |
| Your own facts, kept beside ours | `Annotation`, `AnnotationStore` |
| Serializing and checking | `dumps`, `dump`, `to_document`, `delta_dumps`, `delta_to_document`, `validate` |
| Refusals, matched on `.code` | `SpanweaveError`, `AdapterSelectionError`, `DeltaUnavailableError`, `DuplicateNodeIdError`, `GraphNotSerializableError`, `UnknownAdapterError` |
| Versions | `__version__`, `SCHEMA_VERSION`, `SCHEMA_FROZEN` |

The table is held to `spanweave.__all__` by a test, so an export that lands
without a line here fails the build rather than going unmentioned.

## Exit codes

| Exit | Meaning |
|---|---|
| `0` | it worked |
| `1` | a refusal: the library raised, a file could not be read, or a graph did not validate |
| `2` | a usage error (argparse's own) |

A failure the library **raised** prints its stable error `code` in brackets, so
a script can tell one refusal from another without matching English. The file
below **exists** — it holds JSON no adapter recognizes, which is the refusal
being shown; a name that is not there fails earlier and differently:

```
$ spanweave build unrecognized.jsonl
spanweave build: [adapter_unconfident] no adapter is confident enough about
this input (highest 0.00, minimum 0.50). Confidence declared by each adapter:
openinference 0.00, otel_genai 0.00. Name one explicitly with --adapter if you
know the dialect.
```

Codes are a public contract from `0.9.x` and every one is listed in `SPEC.md`
§3.10. **The machine-readable part of a failure line, when there is one, is
the bracket immediately after `spanweave <command>: `, and what it contains is
one of §3.10's codes** — that closed set is what a caller routes on, and the
prose after it is for you, and may be reworded in any release. The CLI adds
**no bracket of its own** to a failure the library did *not* raise: a file that
is not there prints the operating system's own text, which carries a bracket of
its own — `spanweave build: [Errno 2] No such file or directory: '...'`. `Errno
2` is the OS's number, not a spanweave code, and a caller must not match it:
route on §3.10's codes, never on *there is a bracket*. And `1` is never
subdivided — the exit status says *there is no graph*, the code says why.

## Conformance

A scenario in `fixtures/conformance/` is one run, rendered in **each dialect
that can express it**, and every rendering must produce that scenario's **single
canonical graph**. That equivalence is the library's entire reason to exist, and
it is a test, not a claim: `make conformance`.

**What it covers today, in numbers rather than adjectives.** The corpus holds
**29** scenarios. **24** are rendered in both dialects and compared across them.
The other **4** are rendered in one, because the second dialect genuinely cannot
express them — and each says so in a `coverage.json` file carrying the reason,
because silence would be indistinguishable from an adapter nobody got round to
(`FIXTURES.md` §4.3). And **1** is rendered as a single trace carrying **both**
dialects' records, because a mixed trace is the shape it is about: a dialect is
a property of a record rather than of a file, so one file can hold two
instrumentors' spans and still be one run (`SPEC.md` §6.1). Its expected graph
is the graph the single-dialect renderings of that same run produce — that
equality is the assertion.

**One field is set aside, said here rather than found later.** A scenario may
declare a field *dialect-varying* — a reviewable file in the corpus, never a
branch in the comparison code (`FIXTURES.md` §4.4). One field is declared almost
everywhere: `name`, the span name, which two instrumentors are least likely to
spell the same way. **24 of those 24 cross-dialect scenarios declare it**, so
the equivalence claim above is a statement about everything else — ids, kinds,
operations, timestamps, statuses, payload states and values, usage, and every
edge with its warrant and basis. **If you are matching nodes by `name` across
dialects, nothing here has tested that for you.** `CONTRACTS.md` carries the
measurement.

## Status

Early development. This is `0.9.1`, and it is what `pip install spanweave`
gives you today. `0.9.0` was the first version published for anyone outside
this repository; `0.9` rather than `1.0` is on purpose — see the schema note
below. `0.9.1` changes one thing: what the CLI prints on stderr when a file it
was asked to open is not there. The library, the graph and the schema are
byte-for-byte what `0.9.0` shipped.

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
| `CHANGELOG.md` | What changed, written when it lands. Starts at the September 2026 audit-fix series. |
| `CONTRIBUTING.md` | How to contribute. |

## License

MIT.
