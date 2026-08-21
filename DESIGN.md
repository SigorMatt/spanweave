# DESIGN.md — architecture (design note)

**Status:** binding. Companion to `SPEC.md` (behavior) and `CLAUDE.md`
(invariants). Where this file and `SPEC.md` disagree, `SPEC.md` wins and this
file gets fixed.

## 1. The shape problem, and how the design answers it

A graph's shape is normally dictated by whoever consumes it. A cost tool wants
a containment tree; an eval harness wants a linear trajectory; a security
analyzer wants a dataflow DAG. Ship any one of those and the library serves one
audience.

The resolution is not a compromise shape. It is a **shape with no semantics and
several kinds of edge, each labeled with how it was established**. The library
ships all the structures at once and lets the consumer project out the one it
trusts:

```python
tree       = graph.subgraph(edge_kinds={"parent"})
causal     = graph.subgraph(edge_kinds={"parent", "call_result"})
timeline   = graph.subgraph(edge_kinds={"temporal"})
```

Every downstream disagreement about "what an edge means" becomes a selection
over `EdgeKind` × `Warrant` rather than a fork of the library.

**The falsification test for the whole design:** a use the library was not
designed for should require no change to the library. `ROADMAP.md` makes this an
actual gate — run in Phase 2, confirmed in Phase 3, decided at the Phase 4
freeze — not an aspiration.

Two honesty notes about that gate, because it is easy to let it become
ceremony. First, every judgement call in these specs was reached by asking what
**one** consumer needed. Origin doesn't determine generality — abstractions are
routinely extracted from a single use case — but it does say where to look, and
it is the entire reason the gate exists. `PREDICTIONS.md` names five specific
places the model is probably biased, **written before the test runs**. Second,
the gate distinguishes *shape* changes (a field or kind the model cannot
express — a real failure, hard-gated at zero) from *operational* options
(retention, laziness — permitted and recorded). That line is drawn in
`PREDICTIONS.md` and is binding as written there, precisely so it cannot be
redrawn later around whatever happened to occur.

## 2. Layers

```
┌─────────────────────────────────────────────────┐
│ CLI  (spanweave/cli.py)                         │  argument parsing, I/O
├─────────────────────────────────────────────────┤
│ Serialize  (serialize.py)                       │  canonical JSON, schema
├─────────────────────────────────────────────────┤
│ Graph + Query + Annotate  (graph.py, annotate.py)│  the consumer surface
├─────────────────────────────────────────────────┤
│ Builder  (build.py, ids.py)                     │  NormalizedSpan[] -> Graph
├═════════════════════════════════════════════════┤  ← the seam (§3)
│ Adapters  (adapters/*.py)                       │  all dialect mess
├─────────────────────────────────────────────────┤
│ Reader  (read.py)                               │  bytes -> JSON records
└─────────────────────────────────────────────────┘
```

Dependencies point **downward only**. `build.py` importing from `adapters/` is a
layering violation; the registry hands the builder an iterator of
`NormalizedSpan`, never an adapter object it can interrogate.

## 3. The seam: adapters vs. builder

This is the load-bearing boundary, and it is the direct analogue of a
"front-end / engine" split.

- **Above the seam (adapters).** Everything dialect-specific: attribute key
  names, mime-type quirks, nesting conventions, id fields, vendor extensions,
  malformed-record tolerance. Adapters know *one* dialect deeply and know
  nothing about graphs.
- **Below/after the seam (builder).** Everything dialect-agnostic: identity,
  edge construction, temporal rules, topological ordering, diagnostics
  aggregation, meta. The builder knows *graphs* and knows nothing about dialects.

**The builder must never contain a dialect name.** No `if adapter_id ==
"openinference"`, no dialect-keyed dict, no attribute-key string. This is
enforced by a CI gate that is **module-scoped**: dialect literals are legal
under `spanweave/adapters/` and illegal everywhere else in the package
(`TASKS.md` 0.5). A lexical gate is fooled by a dict table, so the rule is
scoped by module rather than by syntax — the shape of the check matters as much
as its existence.

Consequence: a new dialect is a **new file under `adapters/`, plus fixtures**.
It is never a builder change. If adding a dialect requires touching the builder,
the model is wrong and that is a spec conversation, not a patch.

### 3.1 Is the seam serializable?

`NormalizedSpan[]` can be dumped for debugging (`--dump-spans`). It is
**explicitly not a public contract** — only the `Graph` schema is. Publishing
two schemas would double the versioning burden for no consumer benefit, and the
seam exists to be refactored.

## 4. Identity and ordering

Determinism is not a nice property here; it is the reason a downstream tool can
diff two runs, cache a result, or gate CI on a graph.

- **Ids** — prefer the dialect's own span id; else a salted-free SHA-256 prefix
  (`SPEC.md` §3.6). Python's `hash()` is banned outright: it is salted per
  process, so any use of it in ordering or identity silently breaks
  reproducibility across runs. The no-`hash()` rule is a CI gate, not a habit.
- **Node order** — Kahn's topological sort over `parent ∪ call_result`,
  tie-broken by `(started_at or +inf, node_id)`. Hand-rolled, ~30 lines.
- **Cycles** — malformed telemetry can produce them. The sort detects the
  residual set and orders it by the tie-break key alone, plus a diagnostic. It
  never hangs, never raises, never drops nodes.
- **Edge/diagnostic order** — total sort on stable keys (`SPEC.md` §5.2).
- **Input order independence** — shuffling input lines must yield an identical
  graph. This is the single most valuable determinism test because it catches
  every accidental reliance on file order.

## 5. Payload handling

The five-state `Payload` (`SPEC.md` §3.3) exists because collapsing
absent/empty/redacted is the most common way a telemetry tool becomes quietly
dishonest: a consumer cannot distinguish "there was nothing" from "we weren't
told," and so reports "no finding" for both.

Parsing rules:
- JSON mime → parse; on failure keep `raw`, set `value = None`, emit
  `payload_parse_failed`. **Never raise.**
- Non-JSON mime → `value` is the string; `raw` is the same string.
- Size: payloads are kept whole. No truncation by the library — truncation is a
  claim about the data, and only the source may make it (`truncated` state).

## 6. Memory and scale

v1 targets traces up to ~10⁵ spans, which comfortably fits in memory as frozen
dataclasses. The build is a single pass plus a sort; no quadratic edge
construction (hence the consecutive-siblings-only temporal rule, `SPEC.md` §4.3).

**Streaming readiness (cheap insurance, binding now).** Live/tail mode is a
north-star item, not promised. Two constraints keep it additive:

1. The **reader is an iterator** — `Iterable[JsonValue]` end to end. Nothing in
   the read or adapter path requires the complete input as a precondition.
2. The **builder's per-record work is append-only**; only ordering and pairing
   need the full set, and both are isolated in a single finalize step.

That is the entire premium. Out-of-order buffering, windowing, and whether an
OTLP *listener* is ever worth renegotiating the no-network posture are deferred
to the north star itself — do not build them now.

## 7. Technology decisions

- **Language/runtime:** Python 3.11+, fully typed, `mypy --strict`. The
  consumers (agent frameworks, eval harnesses, security tooling) live in Python.
- **Zero runtime dependencies in core.** Not asceticism — a library meant to sit
  underneath other people's tools must not drag a dependency tree into them. A
  tree readable in one screen is itself a feature. Optional extras (`otlp`,
  `dev`) never affect core.
- **Hand-rolled graph type.** No `networkx`: it would be a glorified adjacency
  dict with nondeterministic iteration order, and iteration order is a
  correctness property here, not a detail. Frozen dataclasses + sorted tuples +
  explicit adjacency indexes.
- **Algorithms, all textbook, all hand-rolled:** Kahn's topological sort with an
  explicit tie-break; a single-pass group-by for sibling temporal edges; a dict
  join for `call_result` pairing.
- **Serialization:** stdlib `json`, `sort_keys=True`, `ensure_ascii=False`,
  compact separators — enforced by a test, not convention.
- **No YAML in core.** There is no human-edited config; the catalog-style
  tunability that would justify YAML lives in consumers, not here.
- **Reading:** stdlib only. `json.loads` per line. **Never `pickle`, never
  `yaml.load`, never `eval`/`exec`** — trace payloads are hostile input
  (`SECURITY.md`), and this is a CI gate.
- **Optional extras:** `otlp` (protobuf) at Phase 4; `dev` (ruff, mypy, pytest).
- **Packaging:** hatchling; the wheel ships `spanweave/` only — `examples/`,
  `fixtures/`, and `tests/` stay out.

## 8. Why `examples/` lives outside the package

The falsification consumers (`ROADMAP.md` Phase 3) exist to prove the model
serves uses it was not designed for. They will do semantically loaded things —
attribute cost, extract trajectories, flag loops. That is exactly what core must
never do.

Keeping them outside `spanweave/` means the **neutrality gate** (`TASKS.md` 0.5)
can scan the package for semantic vocabulary and stay green, while the examples
are free to be as opinionated as they like. The gate's blast radius and the
examples' freedom are the same architectural move.

## 9. What this design deliberately does not decide

Recorded in `OPEN_QUESTIONS.md` and resolved in planning, not in code:
multi-trace inputs, message-level granularity (are individual LLM messages nodes
or payload content?), the `unknown` kind's promotion path, and whether `detect()`
confidence should be adapter-declared or computed centrally.
