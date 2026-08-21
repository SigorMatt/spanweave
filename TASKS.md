# TASKS.md — phase task breakdown (living doc)

Companion to `ROADMAP.md` (sequencing), `SPEC.md` (behavior), `CLAUDE.md`
(process), `DESIGN.md` (architecture). This file is the working checklist Claude
Code executes against.

**How to use this file**

- **Resolution rule.** The current + next phase are specified at PR granularity.
  Later phases are intentionally coarse and *provisional*. Sharpen a phase to
  PR level only when the prior phase's exit criterion is met — over-specifying
  speculative work now is pulling breadth forward, which `CLAUDE.md` forbids.
- **One task = one reviewable PR.** Keep diffs small.
- **Done means done.** A task is complete only when its fixture(s) + test exist
  *and* the invariant gates pass — neutrality and losslessness in particular are
  checked against the *output*, not just the logic.
- Update this file in the same PR whenever scope changes, and record what
  diverged from the plan. Check boxes as you go.

---

## Phase 0 — Skeleton & contract

- [ ] **0.1 Repo scaffold.** `pyproject.toml` (Python 3.11+, hatchling,
  ruff/mypy/pytest, **zero runtime deps**), package layout `spanweave/` +
  `spanweave/cli.py`, `LICENSE` (MIT), `.gitignore`, the doc set, README.
  *Done when `uv sync --extra dev` succeeds and
  `uv run python -c "import spanweave"` exits 0.*

- [ ] **0.2 CLI entrypoint.** `console_scripts` → `spanweave`; `--version`
  prints the version; subcommand skeleton (`build`, `inspect`, `validate`,
  `adapters`) that parses and exits cleanly with "not implemented".
  *Done when `spanweave --version` runs.*

- [ ] **0.3 CI.** GitHub Actions: ruff + mypy + pytest on push/PR via
  `make check`. *Done when CI is green on a trivial test.*

- [ ] **0.4 Safety gates.** Three AST/lexical checks over `spanweave/`, each
  proven by a deliberately planted violation:
  - **no-network** — fails on `requests`, `httpx`, `socket`, `urllib.request`,
    `http.client`, `aiohttp`.
  - **no-unsafe** — fails on `pickle`, `marshal`, `yaml.load`, `eval`, `exec`,
    `__import__`, `subprocess`, `os.system`.
  - **no-`hash()`** — fails on any call to the builtin `hash`.
  Encodes `CLAUDE.md` 4 and 5. *Done when each fails on a planted violation and
  passes otherwise.*

- [ ] **0.5 Neutrality + layering gates.** Two more checks, both **module-scoped**
  (`DESIGN.md` §3):
  - **neutrality** — fails if semantic vocabulary appears in identifiers or
    string literals under `spanweave/`: `severity`, `risk`, `secret`,
    `sensitive`, `sink`, `taint`, `vulnerab`, `attack`, `malicious`, `threat`,
    `cost`, `price`, `usd`, `score`, `quality`, `hallucinat`. Encodes
    `CLAUDE.md` 1. Maintain the banned list in one place with a rationale
    comment; a deliberate exception requires a spec change.
  - **no-dialect-in-builder** — fails if a known dialect id (`openinference`,
    `otel`, `langfuse`, `langsmith`, `logfire`, `vercel`) appears anywhere under
    `spanweave/` **except** `spanweave/adapters/`. Encodes `CLAUDE.md` 6.
  *Done when each fails on a planted violation and passes otherwise.*
  > Note the shape deliberately: a lexical scan would be fooled by a
  > dialect-keyed dict inside the builder, so the rule is scoped by **module**,
  > not by syntax.

- [ ] **0.6 Determinism + losslessness gates.** Property tests, wired into
  `make check`, that will grow with the fixture corpus:
  - build twice → byte-identical serialization;
  - **shuffle input lines → byte-identical graph**;
  - every input record appears as exactly one node **or** is explained by at
    least one diagnostic (no record unaccounted for);
  - serialization uses `sort_keys=True` (assert on the writer, not by eyeballing).
  *Done when all four run against the worked example and fail on a planted
  violation.*

- [ ] **0.7 Model types.** `spanweave/model.py`: `NodeKind`, `EdgeKind`,
  `Warrant`, `Status`, `Payload`, `Usage`, `Provenance`, `RawRecord`, `Node`,
  `Edge`, `Diagnostic`, `Meta` — all frozen dataclasses / enums per `SPEC.md`
  §3–§4. Pure, no I/O, no behavior beyond constructors and simple predicates
  (`Payload.absent()`, `Payload.has_content`).
  *Done when the types round-trip a hand-written node and mypy --strict is clean.*

- [ ] **0.8 Acceptance harness (`make check`).** The phase done-whens as runnable
  checks, not prose: lint, types, tests, `spanweave --version`, and the gates.
  Wired into CI. *Done when `make check` passes on the Phase 0 deliverables.*
  **(Phase 0 exit.)**

---

## Phase 1 — Vertical slice: one dialect, end to end

Build the whole pipeline for **one** dialect. No second adapter — that is Phase
2, and it exists to falsify this work.

- [ ] **1.1 Reader.** `spanweave/read.py`: bytes/path/stdin → `Iterable[JsonValue]`.
  Detects JSONL vs. JSON-array by first non-whitespace byte. Malformed lines
  produce a diagnostic and are skipped, never an exception. **Iterator-based
  end to end** (`DESIGN.md` §6). *Done when both forms and a malformed line are
  covered by tests.*

- [ ] **1.2 Adapter protocol + registry.** `spanweave/adapters/base.py`
  (`NormalizedSpan`, `Adapter` protocol, `SpanLink`, `DeclaredDataEdge`) and
  `adapters/__init__.py` (registry, `detect()` dispatch per `SPEC.md` §6.1 —
  including the hard error on ties or sub-0.5 confidence).
  *Done when a stub adapter registers and is selected, and ambiguity errors
  actionably.*

- [ ] **1.3 OpenInference adapter.** `adapters/openinference.py`. Maps
  `openinference.span.kind` → `NodeKind`; `tool.name` → `operation`;
  `input.value`/`input.mime_type` and `output.value`/`output.mime_type` →
  `Payload` (all five states distinguished); `llm.token_count.*` → `Usage`;
  tool-call ids → `call_id`/`call_role`. Everything else it sees goes in
  `unmapped` (keys only). Follows `ADAPTERS.md` exactly.
  *Done when the seeded scenarios parse and unmapped keys are reported, not lost.*

- [ ] **1.4 Identity.** `spanweave/ids.py` per `SPEC.md` §3.6: prefer the
  dialect span id; else the SHA-256 prefix. Collisions raise. No `hash()`.
  *Done when ids are stable across runs and processes, and a collision raises.*

- [ ] **1.5 Builder — nodes and explicit edges.** `spanweave/build.py`:
  `NormalizedSpan[]` → nodes; `parent` edges (with `orphan_parent` diagnostics),
  `call_result` pairing by `call_id` (with `unpaired_call` / `unpaired_result`),
  `link` edges, adapter-declared `data` edges. **No dialect knowledge.**
  *Done when explicit edges match the expected graphs and every unpaired case is
  diagnosed rather than guessed.*

- [ ] **1.6 Builder — temporal edges and ordering.** Sibling-consecutive
  `temporal` edges per `SPEC.md` §4.3 (`missing_timestamp` where excluded);
  Kahn topological sort over `parent ∪ call_result` with the
  `(started_at or +inf, node_id)` tie-break; cycle-tolerant fallback plus
  diagnostic. `--no-temporal` flag.
  *Done when ordering is stable, a synthetic cycle does not hang or raise, and
  shuffled input is byte-identical.*

- [ ] **1.7 Graph surface + annotations.** `spanweave/graph.py`: `nodes(...)`,
  `edges(kind=, warrant=)`, `node(id)`, `parents`/`children`, `ancestors`/
  `descendants`, `reachable`, `paths`, `subgraph(edge_kinds=)`, `topo_order`.
  `spanweave/annotate.py`: immutable `annotate()` returning a new graph,
  namespaced, JSON-serializable, round-tripping.
  *Done when `subgraph` projections are exercised and annotation never mutates.*

- [ ] **1.8 Serialization + CLI.** `spanweave/serialize.py` (canonical
  `schema_version` `0.1`, `sort_keys=True`, compact separators, trailing
  newline, `raw.source` byte-faithful round-trip; no timestamp/hostname/path in
  `meta`) and `spanweave/cli.py` (`build`, `inspect`, `validate`, `adapters`).
  `inspect` prints counts by node kind, edges by kind **and warrant**, and
  diagnostics grouped by code.
  *Done when `spanweave build` → `validate` round-trips and `make check` covers it.*

- [ ] **1.9 Conformance corpus + captured trace.** Seed every scenario in
  `FIXTURES.md` §3 with the OpenInference rendering and its expected canonical
  graph, including the degenerate ones. Add the capture harness (`make capture`,
  in `capture/`, **outside the package**).
  **HALT:** a human runs the harness against a real instrumented agent and
  commits the captured trace with provenance (`FIXTURES.md` §6). The agent must
  **not** synthesize a file and label it captured.
  *Done when all scenarios pass, the captured trace builds cleanly, and its
  provenance file exists.*
  **(Phase 1 exit — HALT for human review.)**

---

## Phase 2 — Falsify the model  *(provisional — sharpen after 1.9)*

Two independent pressures on the same question, run in parallel while nothing is
frozen. **2b does not depend on 2a** — it needs many traces in one dialect, not
two dialects.

**Start with 2b.** Two days against a phase measured in weeks, and its finding
changes what 2a should be testing: if P5 becomes a shape failure, every
dialect-two rendering written beforehand has to be rewritten afterwards.

**2b — the adversarial consumer**

- Build the consumer most likely to break the model: by default a **fleet
  aggregator** over many traces, attacking `PREDICTIONS.md` P5.
- Lives in `examples/`, outside the package, public API only.
- **Timeboxed to two days.** It does not need to be a good tool; it needs to be
  real enough to hit the shape question. Whatever it teaches in two days is the
  finding — same stop-loss discipline as a capture run. **Do not extend the box**
  because the work got interesting; that is a Phase 4 follow-up.
- Resolve **P5** in `PREDICTIONS.md` at the end of the timebox, whatever the
  outcome.

**2a — second dialect**

- OTel GenAI adapter; express every scenario in the second dialect.
- Turn on the **cross-dialect equivalence test** (`FIXTURES.md` §4).
- Implement/harden `detect()` for both adapters; prove selection is unambiguous.
- Capture one real trace from the second instrumentor, with provenance
  (`FIXTURES.md` §6). **HALT** — human-run, as in 1.9.

**If the phase slips** (full reasoning in `ROADMAP.md`): cut `detect()`
auto-selection first — require `--adapter` and defer to Phase 4, since it is
ergonomics and yields **zero** evidence about the model. Then cut structural
renderings in reverse order of expected disagreement: `declared_data_edge`,
`span_links`, `retriever_and_embedding`, `nested_agents`, `parallel_tools`,
`single_tool_call`.

**Never cut:** `llm_tool_llm` in dialect two (it behaves like a degenerate
scenario — dialects disagree most about `call_result` pairing); any degenerate
rendering (where dialect conventions actually diverge, and where P2 is tested);
the equivalence harness; the second adapter's captured trace; 2b's timebox;
P5's resolution.

**Both**

- **Record every model change either pressure forces, with its cause.** That
  record is the evidence for or against the model's generality, and it is the
  input to the freeze decision in Phase 4.
- **Exit:** identical canonical graphs across both dialects for every scenario
  still in scope; P5 resolved; findings recorded; any deferral recorded here.

## Phase 3 — Confirm, package, launch  *(provisional)*

Bounded work only. Falsification happened in Phase 2; nothing open-ended sits
next to the launch date.

- `examples/trajectory_dump/` and `examples/cost_latency/` — confirmatory,
  expected to pass, demonstrative rather than evidentiary. Prefer a
  **stranger-chosen** consumer over either.
- **Gate:** zero **shape** changes to `spanweave/` — no new field, `NodeKind`,
  `EdgeKind`, warrant, `Payload` state, `Diagnostic` code, or query primitive.
  **Operational** options (retention, multi-trace handling, laziness) are
  permitted, additive, and recorded. The distinction is defined in
  `PREDICTIONS.md` and binding as written there; do not widen it mid-phase.
- Mark **every** prediction CONFIRMED / REFUTED / WORSE. A `WORSE` blocks the
  freeze until the model is fixed. This is ~an hour of work and is **never** cut
  (`ROADMAP.md`, cut order).
- **Publish `0.9.x` to PyPI with `schema_version` `0.x`** and a loud unfrozen
  notice in README and `--help`. **Do not freeze here** — publishing is
  reversible, freezing is not, and keeping them separate takes the only
  irreversible decision off the launch's critical path.
- **Exit:** both consumers work with zero shape changes; every prediction marked;
  `pip install spanweave` works at `0.9.x`; install-and-build in ~60s for a
  stranger.

## Phase 4 — Breadth, then freeze  *(provisional)*

- Further adapters (Langfuse, LangSmith, Logfire, Vercel AI SDK, OTLP JSON;
  OTLP protobuf behind the `otlp` extra).
- Contributor conformance harness: one command validates a new adapter against
  the corpus.
- `CONTRIBUTING.md` adapter walkthrough, written against a **real merged**
  adapter.
- **Freeze `schema_version` `1`; release `1.0.0`; publish the compatibility
  policy** — once predictions are resolved, the Phase 2 finding is absorbed, and
  real users have exercised the schema at `0.9.x`. If a fifth adapter still
  forces a model change, the schema was not ready.
- **Exit:** three or more contributable adapters passing conformance; schema
  frozen; `1.0.0` published.

## North star — parked

Not tasks. Streaming/tail mode, cross-trace stitching, message-level
granularity, a neutral viewer in a separate repo. Direction only; never
represented as shipped (`SPEC.md` §9).
