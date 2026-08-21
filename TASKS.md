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

- [x] **0.1 Repo scaffold.** `pyproject.toml` (Python 3.11+, hatchling,
  ruff/mypy/pytest, **zero runtime deps**), package layout `spanweave/` +
  `spanweave/cli.py`, `LICENSE` (MIT), `.gitignore`, the doc set, README.
  *Done when `uv sync --extra dev` succeeds and
  `uv run python -c "import spanweave"` exits 0.*
  > Divergence: the seed commit already carried `pyproject.toml`, `LICENSE`,
  > `.gitignore`, the doc set, and `README.md`, so this task added only the
  > package itself (`spanweave/__init__.py`, holding `__version__`). The
  > version is a literal rather than a read of installed metadata so that a
  > source checkout reports one too; `tests/test_version.py` (0.3) keeps it in
  > step with `pyproject.toml`.

- [x] **0.2 CLI entrypoint.** `console_scripts` → `spanweave`; `--version`
  prints the version; subcommand skeleton (`build`, `inspect`, `validate`,
  `adapters`) that parses and exits cleanly with "not implemented".
  *Done when `spanweave --version` runs.*
  > Divergence, both additive: (1) the subcommands declare their **full**
  > argument surface from `SPEC.md` §7 now (`--adapter`, `-o`, `--no-temporal`)
  > rather than a bare stub, so a later task implements a surface it did not
  > also get to redesign. (2) `SCHEMA_VERSION` moved into `spanweave/version.py`
  > next to `__version__`, and both `--version` and `--help` carry the loud
  > "NOT FROZEN" notice `CLAUDE.md` 7 requires.

- [x] **0.3 CI.** GitHub Actions: ruff + mypy + pytest on push/PR via
  `make check`. *Done when CI is green on a trivial test.*
  > The workflow shipped with the seed commit, so this task supplied the tests
  > it had nothing to run: `tests/test_version.py` (the version literal tracks
  > `pyproject.toml`; the schema version still announces itself unfrozen) and
  > `tests/test_cli.py` (every subcommand parses; `--version` exits 0).
  > **Known gap, closed by 0.8:** the seeded `Makefile`'s `gates` target runs
  > `tests/test_gates.py`, which tasks 0.4–0.5 create, and CI's `determinism`
  > job runs `make conformance` + `tests/test_determinism.py`, which 0.6 and
  > 1.9 create. So `make check` is red between here and 0.4, and the
  > `determinism` job is red until 1.9, purely because the harness was seeded
  > ahead of the checks it names. `uv run ruff check`, `ruff format --check`,
  > `mypy spanweave`, and `pytest` are all green here.

- [x] **0.4 Safety gates.** Three AST/lexical checks over `spanweave/`, each
  proven by a deliberately planted violation:
  - **no-network** — fails on `requests`, `httpx`, `socket`, `urllib.request`,
    `http.client`, `aiohttp`.
  - **no-unsafe** — fails on `pickle`, `marshal`, `yaml.load`, `eval`, `exec`,
    `__import__`, `subprocess`, `os.system`.
  - **no-`hash()`** — fails on any call to the builtin `hash`.
  Encodes `CLAUDE.md` 4 and 5. *Done when each fails on a planted violation and
  passes otherwise.*
  > Rules live in `tests/gates.py` so each can be run against a synthetic
  > planted module as well as against the package; `tests/test_gates.py`
  > asserts both directions. They are AST checks, not greps, so a comment or a
  > docstring mentioning a banned word does not fire them — there is a test for
  > that too, because the first false positive is what gets a gate switched
  > off. Two additions beyond the letter of the task: violations are deduped to
  > one per rule per line (`from urllib.request import x` matches the ban twice
  > and saying so twice adds nothing), and a tripwire asserts the scan actually
  > visited files, since a gate that silently scans nothing passes forever.

- [x] **0.5 Neutrality + layering gates.** Two more checks, both **module-scoped**
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
  > **Halt point resolved (asked, not assumed):** the banned list collided with
  > `SPEC.md` §3.7, which named a `Diagnostic` field `severity`. Decision: rename
  > the field to `level` (`SPEC.md` §3.7 updated in this change) rather than carve
  > an exception into the gate — an absolute gate is worth more than the word, and
  > fixing the name before `0.9.x` ships it as a serialized key is far cheaper
  > than after. The banned list therefore has **no** exceptions.
  > Two implementation notes: matching is substring and case-insensitive
  > (`max_severity` fails, `Severity` fails), and every word on the list is
  > exercised by a test, because a word silently dropped from the list is a hole
  > nobody would ever notice. The dialect gate is lexical over the whole file,
  > comments included — the builder naming a dialect *at all* is the smell — and
  > there is a test proving the identical dialect-keyed table is legal one
  > directory over, under `adapters/`, since the rule locates dialect knowledge
  > rather than forbidding it.

- [x] **0.6 Determinism + losslessness gates.** Property tests, wired into
  `make check`, that will grow with the fixture corpus:
  - build twice → byte-identical serialization;
  - **shuffle input lines → byte-identical graph**;
  - every input record appears as exactly one node **or** is explained by at
    least one diagnostic (no record unaccounted for);
  - serialization uses `sort_keys=True` (assert on the writer, not by eyeballing).
  *Done when all four run against the worked example and fail on a planted
  violation.*
  > **Done in two halves, and only the first is here.** At Phase 0 there is no
  > reader, no builder and no serializer, so there is nothing to run against the
  > worked example yet. This change lands all four properties as reusable checks
  > (`tests/determinism.py`) and watches **every one of them fail** against a
  > deliberately broken fake (`tests/test_determinism.py`): a counter leaking into
  > the output, a builder that trusts file order, a group-by emitting in dict
  > insertion order, a silently dropped record, a record prettified on the way in,
  > and four ways for a writer to be non-canonical. **Task 1.8 points the same
  > four checks at `spanweave build` over the worked example, unchanged** — and
  > 1.8 is not done until it does. Writing the properties before the code they
  > judge is deliberate: a determinism property invented afterwards tends to
  > describe the implementation rather than test it.
  > Also: the `gates` target now runs `tests/test_determinism.py` too, so `make
  > gates` covers 0.4–0.6 exactly as the seeded `Makefile` comment says it does.

- [x] **0.7 Model types.** `spanweave/model.py`: `NodeKind`, `EdgeKind`,
  `Warrant`, `Status`, `Payload`, `Usage`, `Provenance`, `RawRecord`, `Node`,
  `Edge`, `Diagnostic`, `Meta` — all frozen dataclasses / enums per `SPEC.md`
  §3–§4. Pure, no I/O, no behavior beyond constructors and simple predicates
  (`Payload.absent()`, `Payload.has_content`).
  *Done when the types round-trip a hand-written node and mypy --strict is clean.*
  > Two things are **enforced** rather than documented, both because they are
  > failures a consumer downstream could never detect: `Edge.__post_init__`
  > refuses an explicit-only kind with a `derived` warrant and vice versa
  > (`SPEC.md` §4.1's table is binding, so the model binds it), and
  > `tests/test_model.py` asserts the exact membership of `NodeKind`,
  > `EdgeKind`, `PayloadState`, `Warrant`, `Status` and `DiagnosticLevel` — a
  > tripwire, since extending any of them is a halt point.
  > `SPEC.md` updated in the same change for two things the types needed and it
  > did not say: `AdapterInfo` gains `confidence` (§6.1 requires the detection
  > confidence in `meta`, and §3.9 had no field for it), and §3.5 now states that
  > `RawRecord.line_number` is held but **not serialized** — it is a property of
  > where a record sat in one file, and writing it out would make a shuffled
  > input produce a different graph. §3.9 likewise now says `source_digest`
  > fingerprints the input bytes rather than the graph.
  > Mappings (`Node.attributes`, `Usage.extra`) are defensively copied on
  > construction, so a caller mutating the dict it passed in cannot reach inside
  > a frozen node afterwards.
  > Noted for the record: the neutrality gate fired on this file's first draft —
  > on the *denial* "no prices" in `Usage`'s docstring. The gate cannot tell a
  > denial from an assertion, and that is the right trade; the sentence was
  > reworded rather than the gate weakened.

- [x] **0.8 Acceptance harness (`make check`).** The phase done-whens as runnable
  checks, not prose: lint, types, tests, `spanweave --version`, and the gates.
  Wired into CI. *Done when `make check` passes on the Phase 0 deliverables.*
  **(Phase 0 exit.)**
  > `make check` is green. The `Makefile` and the workflow came with the seed
  > commit, so this task made the harness **self-checking** instead: a suite that
  > reads the `Makefile` and `ci.yml` and asserts `check` still depends on lint,
  > types, test and gates, still smoke-tests the installed entrypoint, that
  > `gates` still names both gate suites, and that CI runs `make check` on 3.11,
  > 3.12 and 3.13. A gate quietly dropped from the harness is indistinguishable
  > from a gate that passes, and this is the only thing that would notice.
  > Added beyond the task: a **zero-dependencies gate**. "Core has zero runtime
  > dependencies" was a hard constraint (`ENVIRONMENT.md`) with nothing enforcing
  > it; it is now an AST check that every import under `spanweave/` resolves to
  > the standard library or to `spanweave` itself, watched failing on planted
  > `yaml` / `pydantic` / `networkx` imports. The installed console script is run
  > as a real subprocess, so packaging is proven rather than assumed.
  > **Still open at the phase exit** (recorded at 0.3, unchanged): CI's second
  > job runs `make conformance` and `tests/test_determinism.py`; the latter
  > exists, the former's `tests/test_conformance.py` arrives at 1.9. That job is
  > red until then. `make check` — the job that gates a change — is green.

---

## Phase 1 — Vertical slice: one dialect, end to end

Build the whole pipeline for **one** dialect. No second adapter — that is Phase
2, and it exists to falsify this work.

- [x] **1.1 Reader.** `spanweave/read.py`: bytes/path/stdin → `Iterable[JsonValue]`.
  Detects JSONL vs. JSON-array by first non-whitespace byte. Malformed lines
  produce a diagnostic and are skipped, never an exception. **Iterator-based
  end to end** (`DESIGN.md` §6). *Done when both forms and a malformed line are
  covered by tests.*
  > **Halt point resolved (asked, not assumed):** a malformed line must produce a
  > diagnostic, and `SPEC.md` §3.7's table had no code for one. Decision: add
  > `malformed_record`, and `ordering_cycle` alongside it (§5.2 mandates a
  > diagnostic on a cycle and likewise named none). Both are now in the §3.7
  > table. Adding a diagnostic code is a halt point, so neither was invented in
  > passing.
  > The reader is genuinely lazy, not lazily described: a test asserts the first
  > record is yielded before the second chunk is pulled. The JSON-array form is
  > the one exception, and the format forces it — an array is not a record until
  > its closing bracket arrives.
  > A `str` source is **always** a path (or `-`), never trace content; content is
  > passed as `bytes`. Sniffing between the two is how a file named `{` becomes a
  > bug report.
  > `malformed_record` carries the line's **text** as its source. That is the only
  > place it can survive — it never became a record — and it is the one case
  > where a diagnostic legitimately carries content rather than keys.

- [x] **1.2 Adapter protocol + registry.** `spanweave/adapters/base.py`
  (`NormalizedSpan`, `Adapter` protocol, `SpanLink`, `DeclaredDataEdge`) and
  `adapters/__init__.py` (registry, `detect()` dispatch per `SPEC.md` §6.1 —
  including the hard error on ties or sub-0.5 confidence).
  *Done when a stub adapter registers and is selected, and ambiguity errors
  actionably.*
  > **Divergence, to keep `DESIGN.md` §2 literally true.** That section says
  > "`build.py` importing from `adapters/` is a layering violation", but the
  > builder must still be able to *name* `NormalizedSpan`. So the seam types
  > (`NormalizedSpan`, `SpanLink`, `DeclaredDataEdge`, `CallRole`) live in
  > `spanweave/seam.py` — they belong to neither side of the seam — and
  > `adapters/base.py` re-exports them, so an adapter author still has one
  > import and the builder imports nothing from `adapters/`. A new gate,
  > `no-adapter-imports`, enforces it: only `spanweave/api.py` and
  > `spanweave/cli.py` may reach the registry.
  > `NormalizedSpan` gains `diagnostics` (`SPEC.md` §6 updated): `parse()`
  > returns spans and has nowhere else to put what it could not map. The seam is
  > internal, so this costs nothing publicly.
  > `SPEC.md` §4 now states what the `link` row implied — a `link` edge's `dst`
  > may name a span with no node in this graph, because links are routinely
  > cross-trace and requiring the target to be present would make the kind
  > useless for the case it exists for.
  > An adapter whose `detect()` **raises** is reported as a hard error naming it,
  > not scored 0.0: swallowing it would let another adapter win by default, which
  > is the silent-wrong-graph outcome this module exists to prevent. Registration
  > order is proven not to decide anything — two registries built in opposite
  > orders must refuse an ambiguous input identically.

- [x] **1.3 OpenInference adapter.** `adapters/openinference.py`. Maps
  `openinference.span.kind` → `NodeKind`; `tool.name` → `operation`;
  `input.value`/`input.mime_type` and `output.value`/`output.mime_type` →
  `Payload` (all five states distinguished); `llm.token_count.*` → `Usage`;
  tool-call ids → `call_id`/`call_role`. Everything else it sees goes in
  `unmapped` (keys only). Follows `ADAPTERS.md` exactly.
  *Done when the seeded scenarios parse and unmapped keys are reported, not lost.*
  > **A model finding, recorded rather than patched.** The seam carries **one**
  > `call_id` per span (`SPEC.md` §6), but a single LLM span can request several
  > tool calls at once — a real and common shape. The adapter pairs the first and
  > reports the rest as `unmapped_attributes` (keys/ids only), so nothing is
  > dropped silently; it does **not** widen the seam, because that is a model
  > question for Phase 2 rather than a patch to sneak in here.
  > Requester recognition: an id is read from the dotted message attributes
  > (`llm.output_messages.*.tool_calls.*.tool_call.id`) **and** from a
  > `tool_calls[].id` stated inside a JSON `output.value` — which is the form the
  > seeded fixture uses. Both are the dialect stating an id, not a comparison of
  > values; §4.2's prohibition is on concluding a flow from matching *content*,
  > and no content is compared here.
  > `truncated` is never produced by this adapter: OpenInference signals
  > redaction (the literal `__REDACTED__`, which is why `redacted` and `absent`
  > stay distinguishable) but has no truncation signal. Claiming one would be
  > claiming the instrumentor said something it did not. There is a test asserting
  > the absence.
  > Unmapped reporting covers unrecognized **record** keys too (as
  > `<record>.events`), not only attribute keys — `events` is real telemetry that
  > Phase 1 does not model, and it should be visible rather than merely absent.

- [x] **1.4 Identity.** `spanweave/ids.py` per `SPEC.md` §3.6: prefer the
  dialect span id; else the SHA-256 prefix. Collisions raise. No `hash()`.
  *Done when ids are stable across runs and processes, and a collision raises.*
  > Stability across **processes** is tested by actually launching one — the
  > failure a salted hash produces is invisible inside a single run, so a
  > same-process assertion would not have caught it.
  > Note how §3.6's two rules interlock on duplicate span ids, which is what
  > makes `SPEC.md` §3.6 ("collisions are a hard error") and §3.7's
  > `duplicate_source_id` diagnostic consistent rather than contradictory: a span
  > id that is *not unique* fails rule 1's condition and falls to rule 2, where —
  > because the adapter's source key is normally that same id — the two derive
  > the same id and collide, and the collision raises. When an adapter gives the
  > two records **distinct** source keys, they derive distinct ids, both survive,
  > and the duplication is reported instead. Both docs are satisfied, and neither
  > case loses a record.

- [x] **1.5 Builder — nodes and explicit edges.** `spanweave/build.py`:
  `NormalizedSpan[]` → nodes; `parent` edges (with `orphan_parent` diagnostics),
  `call_result` pairing by `call_id` (with `unpaired_call` / `unpaired_result`),
  `link` edges, adapter-declared `data` edges. **No dialect knowledge.**
  *Done when explicit edges match the expected graphs and every unpaired case is
  diagnosed rather than guessed.*
  > The builder is handed an `AdapterInfo` — id, version, confidence — and never
  > an adapter object, so `build.py` imports nothing from `adapters/` and the
  > `no-adapter-imports` gate stays green.
  > Node **order** is not final here: the topological sort is 1.6, so nodes come
  > out in the `(started_at or +inf, node_id)` tie-break order that sort falls
  > back to. Already total, already deterministic, just not yet topological.
  > `spanweave/graph.py` is created here with the container and its id index
  > only; the query surface is 1.7.
  > Two judgement calls, both resolved toward *not guessing*: when two records
  > claim one span id and both survive (distinct source keys), a `parent_id`
  > pointing at that id resolves to **neither** — picking one would be a guess —
  > so the child gets `orphan_parent`. And the multi-trace tie-break is stated
  > (most common, then lowest id) rather than left to dict order, because an
  > arbitrary rule still has to be a repeatable one.
  > `nonmonotonic_time` lands here rather than in 1.6: it is a fact about one
  > node, not about ordering. `NormalizedSpan` gains `dialect_note` (`SPEC.md` §6
  > updated) so that `Provenance.dialect_note`, which §3.5 defines, is actually
  > reachable — it had no path from any adapter before.

- [x] **1.6 Builder — temporal edges and ordering.** Sibling-consecutive
  `temporal` edges per `SPEC.md` §4.3 (`missing_timestamp` where excluded);
  Kahn topological sort over `parent ∪ call_result` with the
  `(started_at or +inf, node_id)` tie-break; cycle-tolerant fallback plus
  diagnostic. `--no-temporal` flag.
  *Done when ordering is stable, a synthetic cycle does not hang or raise, and
  shuffled input is byte-identical.*
  > `--no-temporal` exists here as the `temporal=` build argument; the CLI flag is
  > wired at 1.8, and the **byte**-identical half of the done-when lands there too,
  > since there is no serializer until then. Order-independence is already tested
  > at the graph level: every rotation of an input builds the same node order.
  > Three decisions worth naming. `temporal` edges are deliberately **excluded**
  > from the ordering sort — they are derived from the very timestamps that break
  > ties, so including them would let a computed relation decide an order a stated
  > one should; a test pins that `temporal=False` does not change the order. A node
  > whose parent is missing is treated as a **root sibling**, because in *this*
  > graph it has no parent, which is exactly what `SPEC.md` §4.3 says makes
  > siblings. And `missing_timestamp` is emitted only when temporal edges are being
  > built: it exists to explain an omitted edge, and with the kind switched off
  > there is nothing to explain.
  > The cycle path orders the whole **residual** set (the cycle plus anything
  > downstream of it) by the tie-break and names it in the diagnostic. A
  > self-parenting span is the one-node case and is covered.

- [x] **1.7 Graph surface + annotations.** `spanweave/graph.py`: `nodes(...)`,
  `edges(kind=, warrant=)`, `node(id)`, `parents`/`children`, `ancestors`/
  `descendants`, `reachable`, `paths`, `subgraph(edge_kinds=)`, `topo_order`.
  `spanweave/annotate.py`: immutable `annotate()` returning a new graph,
  namespaced, JSON-serializable, round-tripping.
  *Done when `subgraph` projections are exercised and annotation never mutates.*
  > **A contradiction inside `SPEC.md`, resolved toward the API.** §3.9 listed
  > `nodes` and `edges` as *fields*; §8 and the README call them as *methods*
  > (`graph.nodes(annotated=...)`, `graph.nodes(kind="tool")`). A Python object
  > cannot have both under one name. Resolved in favour of the accessors — two
  > documents and every usage example agree on those — with the tuples held
  > privately and `Graph.of(...)` for construction. §3.9 updated to say so.
  > `subgraph` keeps **all** nodes, including the ones a projection isolates:
  > dropping them would be a judgement about which nodes matter, which belongs to
  > whoever is projecting. There is a test that the three canonical projections
  > (`parent`; `parent+call_result`; `temporal`) genuinely **disagree** about
  > whether s1 reaches s2 — that disagreement is the design working.
  > `reachable()` is where the transitive closure lives, which is what lets §4.3
  > keep the temporal edge set linear.
  > Annotation refuses three things rather than absorbing them: the reserved
  > `spanweave` namespace, a value that is not JSON-serializable (checked by
  > actually trying), and a node id that is not in the graph — an annotation
  > nothing can ever read is a silent bug, not a convenience. Cycles are bounded
  > in `reachable`/`paths` for the same reason they are in the builder: a hang is
  > a denial of service when this runs in CI.

- [x] **1.8 Serialization + CLI.** `spanweave/serialize.py` (canonical
  `schema_version` `0.1`, `sort_keys=True`, compact separators, trailing
  newline, `raw.source` byte-faithful round-trip; no timestamp/hostname/path in
  `meta`) and `spanweave/cli.py` (`build`, `inspect`, `validate`, `adapters`).
  `inspect` prints counts by node kind, edges by kind **and warrant**, and
  diagnostics grouped by code.
  *Done when `spanweave build` → `validate` round-trips and `make check` covers it.*
  > **0.6's second half is done here, as promised.** The four property checks
  > written at Phase 0 are now pointed at `spanweave.build` over the worked
  > example, unchanged: build twice is byte-identical, shuffling the records
  > produces identical bytes, every record is a node or a diagnostic, and the
  > shipped writer is canonical. The shuffle comparison excludes
  > `meta.source_digest` — it fingerprints the input *bytes*, which shuffling
  > changes by definition (`SPEC.md` §3.9) — and a separate test proves the digest
  > really does differ, so the exclusion hides nothing.
  > `spanweave/api.py` is added as the public `spanweave.build(...)` the README
  > has always shown, and is the second of the two modules permitted to reach the
  > adapter registry.
  > `inspect` tells a trace from a built graph by **content** (a JSON object with
  > a `schema_version`) rather than by file extension, and prints the same summary
  > either way — there is a test that the two are identical.
  > `validate` allows a dangling `link` target and nothing else, per `SPEC.md` §4,
  > and refuses `meta` keys that would leak the operator's environment. A
  > `schema_version` from another build is **flagged, not rejected**: the schema is
  > unfrozen, and refusing to read a neighbour's graph would be overclaiming
  > stability we have not got.
  > Deliberately **not** built: a deserializer. `inspect` summarizes the JSON
  > document directly, so there is only one contract in this direction rather than
  > two that could drift.

- [x] **1.9 Conformance corpus + captured trace.** Seed every scenario in
  `FIXTURES.md` §3 with the OpenInference rendering and its expected canonical
  graph, including the degenerate ones. Add the capture harness (`make capture`,
  in `capture/`, **outside the package**).
  **HALT:** a human runs the harness against a real instrumented agent and
  commits the captured trace with provenance (`FIXTURES.md` §6). The agent must
  **not** synthesize a file and label it captured.
  *Done when all scenarios pass, the captured trace builds cleanly, and its
  provenance file exists.*
  **(Phase 1 exit — HALT for human review.)**
  > **DELIBERATELY LEFT UNCHECKED. The corpus half is done; the captured half is
  > yours.** Everything an agent may do here is done:
  > - All 18 scenarios from `FIXTURES.md` §3 are seeded with an OpenInference
  >   rendering, a `scenario.md`, and a reviewed expected graph. `make
  >   conformance` is green.
  > - The capture harness exists (`capture/`, outside the package, `make
  >   capture`). Its span→dialect conversion is duck-typed and unit-tested
  >   against stub spans, including the join that matters: what the harness
  >   writes, the adapter must read.
  > - **`fixtures/captured/` is still empty, and must stay that way until a human
  >   fills it.** Running the harness needs a model API key the agent does not
  >   have and must not have (`ENVIRONMENT.md`), and synthesizing a file and
  >   labelling it captured is the one thing that would destroy the only property
  >   that directory has. `make capture` writes to `capture/_scratch/` and prints
  >   the three steps that remain: read it, redact it and record the redaction,
  >   then move it and write its provenance.
  >
  > Two things about the corpus a reviewer should look at rather than take on
  > trust:
  > - **`llm_tool_llm`'s expected graph was frozen before any of this code
  >   existed, and the pipeline reproduces it exactly.** That is the one
  >   expectation in the corpus this agent did not author, and it is the strongest
  >   evidence here that the implementation follows the spec rather than the
  >   reverse.
  > - **Every other expected graph was generated from this implementation and then
  >   read back against its `scenario.md`.** That is generated-then-reviewed by the
  >   author, which is weaker than `FIXTURES.md` §8 intends. Each `scenario.md`
  >   states its node and edge counts, payload states and diagnostics **in prose**
  >   precisely so a human can check the expectation is *right* rather than merely
  >   *what the code currently does* — that read is the outstanding review, and it
  >   is worth doing before Phase 2 turns these into cross-dialect anchors.
  >
  > Two scenarios are deliberately shaped differently, both documented in
  > `FIXTURES.md` §1/§4: `declared_data_edge` has **no** OpenInference rendering
  > (the dialect declares no producer→consumer relation, and inventing an
  > attribute would make the fixture assert something unsubstantiated —
  > **this turned out to be false; see the cold-review record below**), and
  > `duplicate_span_ids` has **no** expected graph, because it must not build —
  > its expectation is an `expected/error.json`.

---

### Phase 1 review — outcomes

Human review of the Phase 1 exit. Sixteen scenarios signed off unchanged; six
items came back. All six are implemented; **1.9 stays unchecked** for the same
reason as before — the captured trace is a human step.

| # | Outcome |
|---|---|
| 1 | `SPEC.md` §5.2 now states the `meta.source_digest` exclusion. It lived only in a test, so an independent checker written against the spec alone reported a failure the spec did not intend — which is how it was found. The spec also requires the exclusion to carry its own proof, since an exclusion nobody can see through is indistinguishable from excusing a field that never varies. |
| 2 | `SPEC.md` §3.2 now defines `attributes.reported_kind`, invented during implementation and part of the schema that freezes at Phase 4. `redacted_payload/scenario.md` records the upstream corroboration for `__REDACTED__` — the same absent-vs-hidden argument, reached independently by the people emitting the data. |
| 3 | The corpus can now say "no expected graph", **two ways, because they are two statements**: `expected/error.json` for a refusal (behavior, all dialects, permanent) and `expected/coverage.json` for an unrenderable dialect (coverage, per-dialect, temporary — the file deletes itself when a dialect can render). `FIXTURES.md` §4.2/§4.3 define equivalence for each, and silence is now a failure: every scenario × dialect is either rendered or declared. Refusals are matched by **type + error code, never message text**; errors therefore gained stable codes (`SPEC.md` §3.10), mirroring diagnostic codes. |
| 4 | The seam carries `call_ids` (plural). Parallel tool calls are ubiquitous, so the first captured trace would have shown one pairing where there should be several. No schema, serializer or expected-graph change — the seam is not a public contract and the graph model already allowed many `call_result` edges from one node. New scenario `parallel_tool_calls`; the adapter got **smaller**. `OPEN_QUESTIONS.md` §8 records agent-as-tool as the concrete shape that would force `(id, role)` pairs. |
| 5 | `temporal` asserted a precedence that is false for equal start times, and that false claim was frozen into `parallel_tools`. Fixed both ways: §4 now claims an **order**, and a tie-broken edge carries its own `basis`, so a consumer can tell the two apart from the graph rather than by re-deriving timestamps. The edge is labelled, not suppressed — dropping it would break the sibling chain and leave the order partial. |
| 6 | The `link`/`parent` dangling-reference asymmetry is stated in `SPEC.md` §4.0 and back-referenced from the `orphan_parent` row. Dangling ids are **kept** (the edge names its target; dropping it would hide a stated relation) with `node() -> None` as the documented contract. No new diagnostic: a cross-trace link is confidently mapped, and using that channel for an inventory fact would dilute it. The duplicate-entry finding was a **defect** and is fixed — node-returning queries report each node once. Coverage added for `descendants` / `reachable` / `ancestors` / `paths` / `parents` / `subgraph` / `topo_order` against a dangling target. |

### Capture harness — second backend, and a defect it exposed

`capture/` now drives **two** backends: the Anthropic SDK, and the OpenAI SDK
against any OpenAI-compatible endpoint (`NEBIUS_BASE_URL` / `NEBIUS_API_KEY`,
default model `openai/gpt-oss-120b`). Neither replaced the other. Selection uses
the configured one, and refuses on ambiguity naming `--backend` — the same
posture as `SPEC.md` §6.1, for the same reason: a capture that ran against the
backend you did not mean is a fixture whose provenance file is wrong.

**`exporter.py` needed no change**, and that is structural rather than lucky: it
reads the OTel `ReadableSpan` surface, which is the same class whichever
instrumentor filled it, and copies attribute keys verbatim. The dialect lives in
the keys. Both instrumentors emit OpenInference semantic conventions, so one
`record_of` handles both — there is now a test asserting the two records differ
only in `attributes`.

**A defect in what 1.9 shipped, found while adding the second backend.** The
harness executed the tool as plain Python between two SDK calls and created no
spans of its own, so a capture would have been two **sibling root LLM spans** —
no `parent` edges, no `tool` node, and **no `call_result` pairing**, which is the
one relation the harness exists to demonstrate. Its docstring claimed the
`llm -> tool -> llm` shape that its code could not produce. Fixed for both
backends: `capture/backends.py` now emits the `agent` and `tool` spans itself,
because executing a tool is not an SDK call and no instrumentor would record it.
Only the `llm` spans come from the instrumentor, and the printed provenance
template says so — "captured from real instrumentation" is otherwise true of
some spans and not others.

### First captured trace — a pairing defect, and four unrepresentative fixtures

The first real capture disagreed with the corpus, and `FIXTURES.md` §6 decided
it. **This is the most valuable artifact of Phase 1 review**: the diff below is
the record of what our reading of the dialect got wrong.

**The defect.** One tool span acquired **two** `call_result` edges, both
`warrant=explicit`. Only one LLM span had originated the call id; the other
re-sent it in message history, because the protocol requires a follow-up turn
to resend the conversation. The library asserted a request-fulfilment relation
the telemetry never stated — and nothing downstream could have told.

**The dialect distinguishes them; the adapter ignored the part that does.** The
originator states the id under `llm.`**`output_messages`**`.*.tool_call.id`; the
echo appears under `llm.`**`input_messages`**`.*`. The rule matched the *suffix*
and never looked at the message list. Fixed: a requester id is taken only from
what a span itself produced. Echoed ids are left unmapped, so they are reported
rather than dropped. `SPEC.md` §4.4 now states the principle dialect-agnostically.

**Expected graphs that moved, and why.** Structure — nodes and edges — did not
change in any of them. What changed is everything the old renderings had
quietly asserted about the dialect:

| Scenario | What moved | Cause |
|---|---|---|
| `llm_tool_llm` | s1/s3 `inputs` `absent`→`present`; s1 `outputs.value` reshaped; diagnostics `[]`→`unmapped_attributes` ×2 | omitted `input.value` (emitted on **every** LLM span); tool calls moved from a top-level `output.value` key to `llm.output_messages.*`; the rendering carried only keys the library maps |
| `shuffled_order` | identical to its twin | it is the same records reordered |
| `parallel_tool_calls` | s1 `inputs` `absent`→`present`; +`unmapped_attributes` ×1 | same rendering corrections; **both** `call_result` edges unchanged |
| `unpaired_tool_call` | s1 `inputs` `absent`→`present`; +`unmapped_attributes` ×1 | same; both unpaired diagnostics unchanged |

`llm_tool_llm`'s expectation was the one frozen by a human before any code
existed. It moved because a captured trace disagreed with it, which is the only
circumstance in which it may (`FIXTURES.md` §8).

**New scenario `tool_call_history_echo`** isolates the property. Verified as a
regression test rather than assumed: simulating the old rule against it
produces the spurious second edge. The corrected `llm_tool_llm` catches it too;
`parallel_tool_calls` does **not** — it has no follow-up turn, so no echo — which
is why the isolated scenario earns its place.

**Removed:** the adapter path that read tool-call ids from a top-level
`tool_calls` key inside `output.value`. No observed instrumentor emits that
shape — OpenAI nests them under `choices[0].message` — so the path existed only
because a hand-authored fixture asked for it.

**The lesson, written where the next contributor will meet it:** `FIXTURES.md`
§5.1 (derive a rendering from observed output, never from a reading; omission is
fine, misstatement is not) and `ADAPTERS.md` §5 and its checklist.

`OPEN_QUESTIONS.md` §9 records `llm.finish_reason` (`tool_calls` on the
originator, `stop` on the echo) as an available second signal, deliberately
**not** wired in: one observed dialect is not enough to justify a second rule.
The corpus keeps the attribute in its renderings so the signal is there the day
it is reopened.

### Cold review of the first captured trace — a missed `data` edge

A reviewer with no knowledge of this project, given the capture and its graph
and asked only whether the graph represents the trace, found a relation we were
discarding. We had just finished establishing that input-side tool-call ids are
history echoes, and over-generalized that into "input-side ids are noise".

**What was there.** A tool-result message in the follow-up span's input —
`role="tool"`, `tool_call_id=X` — carries the same id the tool span answered.
That is the instrumentor declaring that one span's output became another's
input, joined by **id**, with no value comparison anywhere. Our own
`unmapped_attributes` diagnostic had been listing the attribute all along.

**The spec change, made deliberately rather than slipped in.** `SPEC.md` §4.2.1
now permits a `data` edge from a declaration made at **message** granularity,
resolved to spans by declared id. It names the objection and accepts it rather
than dismissing it: the declaration's subject is a message and the edge's
subject is a span, which is a granularity leap that takes a position on
`OPEN_QUESTIONS.md` §2 — recorded there as a precedent, with its narrowness
spelled out. The `basis` names the resolution (`tool_call_id in tool-result
message`), not just the field, so the step is auditable. A stated gap: a
received result whose producer is absent yields no edge and no diagnostic.

**What moved.** `llm_tool_llm`, `shuffled_order`, `tool_call_history_echo` each
gain one `data` edge (6→7 edges, 3→4 for the echo). `parallel_tool_calls` and
`unpaired_tool_call` are unchanged — no follow-up turn, so no result received.
`declared_data_edge` **is rendered at last** and its `coverage.json` deleted,
which is the §4.3 lifecycle working exactly as designed; no scenario is
unrenderable now, and the tripwire test says so.

**The restraint sentence inverted rather than vanished.** `llm_tool_llm` and
`FIXTURES.md` §7 said the graph declined to connect the tool to the second LLM
call "because the telemetry didn't" — the library's most-quoted illustration of
restraint, wrong about the very trace it described. It now shows the rule
working in both directions: the declared relation is emitted with a basis
naming how it was resolved, and what is still not asserted is any flow nobody
stated. That is the better illustration.

**And the class of defect is now checked.** `FIXTURES.md` §7 had also gone stale
against the fixture it quotes — I corrected the fixture and not the document.
`tests/test_docs.py` extends the `test_codes.py` pattern to prose: the quoted
JSONL must be the fixture verbatim, every edge kind/warrant/basis the section
claims must be one the graph builds, the diagnostics claim must match, and
per-span attribute counts must agree. Watched failing on planted drift in both
the block and the prose.

**Two notes for whoever picks this up next.**

The reviewer's `review_corpus.py` flags `declared_data_edge` and
`duplicate_span_ids` as "no expected/graph.json". That is now their *correct*
state; the tool predates the convention and wants teaching about `error.json`
and `coverage.json` (`FIXTURES.md` §4.2, §4.3).

Item 3's strictness (type + error code) was chosen by the reviewer after the
first implementation had already gone in under a different assumption. The
codes are a public contract from `0.9.x`, so `SPEC.md` §3.10 is the place to
argue with them, and `tests/test_codes.py` parses that table out of the spec
and fails if the library drifts from it.

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
