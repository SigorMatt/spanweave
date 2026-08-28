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

## Phase 2 — Falsify the model

Sharpened from the provisional bullets after the 1.9 exit, per this file's
resolution rule. Two pressures on one question — *is this model general, or is
it just shaped like its first consumer?* — applied while nothing is frozen.

**Read before starting any task here:** `ROADMAP.md` Phase 2 and its cut order,
`PREDICTIONS.md` P5, `FIXTURES.md` §4 / §5.1 / §6, `ADAPTERS.md` §5–§6, and the
Phase 1 review records above. Several decisions below are what they are
*because* of what those records found.

**Workstreams. Never mix them in one session's context.** Every task is tagged
`[2b]`, `[2a]`, or `[prereq]`. A cold session picks the lowest-numbered
unchecked task and works only that tag.

**Ordering — decided, do not re-litigate.** 2b runs **before** 2a, strictly
serial, not in parallel. If P5 turns out to be a shape failure the model
changes, and every dialect-two rendering written beforehand would have to be
redone afterwards. Two days of de-risking buys the larger workstream a stable
target. (`ROADMAP.md` said "run them in parallel" *and* "start 2b first"; the
serial reading is the one that survives, and `ROADMAP.md` has been corrected.)

**The timebox is a limit, not a target.** 2b is two days. It does not need to
be a good tool; it needs to be real enough to hit the shape question. Whatever
it teaches in two days is the finding. **Do not extend it** because the work
got interesting — that is a Phase 4 follow-up with its own scope
(`ROADMAP.md`, *Never extend*).

**HALT markers.** A task marked **HALT** ends the session. It names the
artifact the human needs in order to decide. Do not proceed past one alone.
The standing halt points in `AGENT.md` still apply on top of these — any model
change, anything in `OPEN_QUESTIONS.md`, any edit to `PREDICTIONS.md`, any
credentialed or networked step.

### What Phase 1 changed that Phase 2's plan predates

`ROADMAP.md`'s Phase 2 was written before the last three commits of Phase 1.
Three things it could not have accounted for, each carried into the tasks
below:

1. **The declared `data` edge (`SPEC.md` §4.2.1) is now in the canonical graph
   of three never-cut scenarios** — `llm_tool_llm`, `shuffled_order`,
   `tool_call_history_echo` — plus `declared_data_edge` itself. So dialect two
   must be able to express a message-granularity producer→consumer
   declaration, or `llm_tool_llm` fails equivalence. This is the single most
   likely blocker in 2a and it is checked at three separate points below
   (2.5, 2.6, 2.9).
   **Do not solve it now.** It may not fire at all — content capture may emit
   the tool-result message with its id, and then there is nothing to solve.
   Decide at the **2.9 HALT, with the capture in hand**. And decide it knowing
   that **whichever way it goes, it is evidence about `EdgeKind.data`'s
   generality**: a second dialect that declares the relation says the kind
   generalizes beyond the dialect it was found in; one that cannot says the
   kind currently rests on a single instrumentor's convention. Either finding
   belongs in the 2.9 checkpoint artifact alongside `OPEN_QUESTIONS.md` §7 and
   `PREDICTIONS.md` P3 — **as evidence, not as a resolution of either.**
   Resolving §7 by implementation is precisely what that file exists to
   prevent, and P3 resolves in Phase 3.
2. **`parallel_tool_calls` and `tool_call_history_echo` did not exist when the
   cut order was written.** `tool_call_history_echo` is degenerate and
   therefore never-cut by the existing rule. `parallel_tool_calls` is
   structural and the cut list is silent about it; `ROADMAP.md` has been
   corrected to name it never-cut, on the list's own stated grounds (it is the
   multi-call form of the `call_result` pairing the list already refuses to
   cut). Reverse that classification if you disagree — but do it in
   `ROADMAP.md`, not by quietly cutting the scenario.
3. **`FIXTURES.md` §4.3 has no "not rendered yet" state**, and its "silence is
   a failure" tripwire fires for every scenario the moment a dialect id is
   added to `tests/conformance.py:DIALECTS`. `renderable: false` means *cannot
   express*, not *not done*. Tasks 2.7–2.13 work around this by adding the
   dialect id **last** (2.13) and building whatever renderings exist in the
   meantime. If that transitional gap proves uncomfortable, the alternative is
   a `pending` state in §4.3 — a spec conversation, not a patch.

---

### `[prereq]`

- [x] **2.1 Re-scope `AGENT.md` for Phase 2.** `[prereq]` `AGENT.md`'s *Scope of this run*
  delivers through the 1.9 exit and then halts; it explicitly forbids a second
  adapter, `examples/`, and starting Phase 2 at all. A cold Phase 2 session
  reads that file first and is told to stop. Rewrite the scope block for Phase
  2, **keeping every halt point** and adding the three new ones (the 2b timebox
  expiry, the second capture run, the first cross-dialect equivalence run).
  Also correct `ENVIRONMENT.md`'s repo layout, which annotates `examples/` as
  Phase 3 — 2b puts a consumer there in Phase 2, and its no-network rule for
  `examples/` still binds and is load-bearing for 2.3.
  *Done when `AGENT.md`'s scope section names Phase 2, its "must not" list no
  longer forbids the second adapter or `examples/`, its halt list still
  contains every entry it had plus the three new ones, and `make check` is
  green.*
  **HALT** — the run scope is a human decision, not an agent's.
  *Artifact for the decision:* the diff of `AGENT.md`'s *Scope of this run* and
  *Halt-and-hand-back points* sections, side by side with the old text.
  > **Scope change authorised explicitly by the human before this ran**, since
  > `AGENT.md` forbade Phase 2 and this is the task that changes that. The
  > **HALT still stands**: 2.2 has not been started, and the new scope wants
  > approval before it does.
  > Every pre-existing halt point is still there. Only one moved: the
  > **phase-exit** halt, which is now Phase 2's (2.14) with Phase 1's recorded
  > as discharged. Keeping "do not start Phase 2" verbatim would have made the
  > list contradict the scope it sits under — a halt that is already false is
  > how a list of halts stops being read. The three new ones are the capture
  > runs (2.2 **and** 2.6 — the fleet is a credentialed run too, and volume is
  > where synthesis is most tempting), the 2b timebox expiry, and the first
  > cross-dialect equivalence run.
  > Four things beyond the letter of the task, each because a cold session
  > following the file literally would otherwise get it wrong:
  > - The **"must not" list gained** what Phase 2 newly forbids — a third
  >   dialect, the *confirmatory* consumers (Phase 3's, not this phase's), and
  >   editing an `expected/graph.json` or weakening `canonical()` to make a
  >   rendering pass. A scope section that only removes prohibitions reads as
  >   open season.
  > - **Run loop step 3 inverts for 2a**, and says so. As written it told the
  >   session to author the fixture before the implementation; in 2a the
  >   expected graph already exists and is not the session's to edit, and the
  >   rendering is transcribed from a capture. Following the old step literally
  >   is precisely the defect that cost Phase 1 four fixtures.
  > - The captured-fixtures halt cited **`TASKS.md` 1.8**; captured fixtures
  >   are **1.9**. Corrected, with the correction noted in place.
  > - The doc map said `PREDICTIONS.md` was written before "the Phase 3 test"
  >   and read-only "during Phase 1–2". **P5 resolves at the end of Phase 2b**,
  >   and the file is read-only to the agent in *every* phase — a session
  >   reading the old wording could conclude it may resolve P5 itself once
  >   Phase 2 is over.
  > `ENVIRONMENT.md`'s layout entry now says the adversarial consumer arrives
  > in Phase 2b and the confirmatory ones in Phase 3. **Its no-network rule for
  > `examples/` is untouched and still binding** — it is what forces 2.3's
  > committed form to run against the corpus rather than against 2.2's fleet.

---

### `[2b]` — the adversarial consumer  *(two days, starting at 2.3)*

- [x] **2.2 Scratch fleet generator.** `[2b]` **REQUIRED — 2.3 does not start
  without it.** P5 is *"one trace = one graph"*. An aggregator run over the
  committed corpus tests **the aggregator**; run over a real heterogeneous
  fleet it tests **the claim**. The traces are scratch and cost cents, so the
  only thing that would ever skip this is timebox pressure — and skipping it
  resolves P5 on weaker evidence than was available. That is exactly the
  failure `ROADMAP.md`'s cut order exists to forbid, so it is not optional
  here.
  Add a fleet mode to `capture/` that runs N conversations and writes
  `capture/_scratch/fleet/<i>.local.jsonl`. The model and the instrumentor stay
  **fixed**; what varies is the shape of the runs, and the variation is the
  point — a fleet of identical traces is one trace counted N times.
  **Required heterogeneity** (a fleet missing any of these is not exercising
  P5):
  - **varied tools** — more than one tool in the inventory, so per-tool rollup
    has something to roll up;
  - **turns with no tool call at all** — the model answers directly;
  - **turns with parallel tool calls** — several requested at once
    (`parallel_tool_calls`' shape, from a real model rather than a fixture);
  - **errors or refusals** — a tool that fails, and a prompt the model declines
    or cannot answer, so `Status` and the diagnostic codes are populated by
    something real.
  Steer these with the prompt and the stub tools; do not fabricate them
  post-hoc by editing exported spans, which would make the fleet synthetic
  again while looking real.
  **These are scratch, and the distinction is absolute:** gitignored, no
  provenance file, **never** promoted to `fixtures/captured/` and never cited
  as evidence for anything beyond 2.3's own findings. `fixtures/captured/`
  holds human-reviewed, redacted, provenance-bearing artifacts; a fleet of
  unreviewed traces in there would destroy the only property that directory
  has.
  *Done when `uv run pytest tests/test_capture.py` is green with no key set and
  covers each required shape against stub spans, `make capture
  ARGS="--fleet 8"` fails with the same actionable no-credential error as
  today rather than a traceback, and `git status --porcelain capture/_scratch`
  is empty after a run.*
  **HALT** — running it needs a Nebius credential the agent does not have and
  must not have (`ENVIRONMENT.md`, credentials). `AGENT.md`'s fabrication halt
  point applies in full: the agent must not synthesize a fleet and describe it
  as captured.
  *Artifact for the decision:* the generator, its no-key test output, and the
  list of required shapes above so the human can confirm the fleet that comes
  out actually contains each one. If the fleet cannot be produced, **record
  why here and say so at 2.4** — P5 then resolves on corpus-only evidence and
  the resolution must state that limitation rather than absorb it silently.
  > **The generator is built; the fleet is not captured.** `make capture
  > ARGS="--fleet 8"` writes one file per run to `capture/_scratch/fleet/`
  > (`capture/fleet.py`), and with no credential set it refuses with the same
  > actionable error as a single capture and exits 2. **The HALT stands.**
  > `AGENT.md`'s run loop step 3 does not apply literally here — there is no
  > expected output to author before the implementation — so the verification
  > is against **stub spans**, as 2.5 will be: each required shape is built as
  > stub spans, pushed through the real span→record conversion, and read back
  > by `fleet.shapes_of`, so the coverage verdict is tested end to end from
  > span to report without a model call.
  > **The design decision that shaped everything else: steering is not
  > guaranteeing.** A prompt steers a model; it does not command one. So the
  > harness never asserts that a run produced the shape it was aimed at. Each
  > `RunSpec` carries an `intends` tuple, but that is documentation plus a
  > tripwire (a test fails if the fleet stops *aiming* at a required shape) —
  > never evidence. What a run actually produced is read back off its exported
  > records, the fleet's coverage is printed as a table, and a missing required
  > shape **exits non-zero**. That last part is deliberate: a partial fleet is
  > a real problem to fix by re-running, and an exit code is harder to skim
  > past than a paragraph. The report names the one shortcut a human under
  > timebox pressure might otherwise take, and there is a test that it does.
  > Five smaller decisions worth naming:
  > - **The failing tool raises, and the exception escapes its span before it
  >   is caught.** That is what makes the tracer mark the span `ERROR` and
  >   record the exception, exactly as a real failure would. Catching it inside
  >   the span would have produced an `OK` span describing a failure — a trace
  >   that lies, in the fixture directory of a library whose whole claim is
  >   that it does not. The error is then handed back to the model as the
  >   tool's result, which is what a real application does and what keeps the
  >   second turn alive.
  > - **The reference conversation did not move.** `converse()` gained a
  >   `prompt` and a `tool_names` argument, both defaulting to what they always
  >   were (`QUESTION`, `DEFAULT_TOOLS`). 2.6's matched pair differs only in
  >   the instrumentor, so a drifting default would quietly invalidate it;
  >   there is a test pinning both.
  > - **One file per run**, and `JsonlSpanExporter.drain()` between runs. One
  >   trace is one graph (`SPEC.md` §7), and without the drain run 2's file
  >   would inherit run 1's spans — a multi-trace input, which is a different
  >   question and not the one 2.3 is asking.
  > - **Two shape detections are sound only because of how `converse` is
  >   built**, so the reasoning is written into `shapes_of` rather than
  >   assumed: every tool span is a child of the run's one `agent.run` span and
  >   the harness executes tools for exactly one assistant turn, so two tool
  >   spans mean two calls requested at once; and a tool span is emitted for
  >   every call requested, so no tool span means none was requested rather
  >   than one was lost.
  > - **An error on a non-tool span is not the tool-error shape.** Otherwise a
  >   failed LLM call would silently satisfy the requirement for a failing
  >   *tool*, and the fleet would be missing a shape it reported as present.
  > Three tools were added beside `get_weather` — `get_population`,
  > `convert_currency`, and `lookup_flight`, which always fails. All keep the
  > existing rule: no clock, no network, nothing that would have to be redacted
  > or explained.
  >
  > **First fleet run (human, 12 traces): three of four required shapes.**
  > `varied_tools`, `no_tool_call` and `tool_error` all appeared. **No run
  > produced parallel calls** — never more than one tool span in a trace, even
  > for the prompts that asked for three things at once.
  >
  > **Before recording that as a gap: the harness had never asked.** The
  > `chat.completions` call set neither `parallel_tool_calls` nor
  > `tool_choice`, and the captured spans record
  > `llm.invocation_parameters` as `{"model": "openai/gpt-oss-120b"}` alone.
  > So the evidence was three attempts of *the model not doing it unprompted*
  > and nothing at all about whether the API had been asked to permit it.
  > Those are different claims and only one of them was supported.
  > **`parallel_tool_calls=True` is now sent on fleet runs**, explicitly and
  > with the reason in the code. Enabling a capability is not steering toward
  > an outcome, so it is not what `fleet.py` prohibits — it asks the API to
  > permit several calls and leaves entirely open whether the model makes any.
  > It may change nothing: vLLM-served endpoints (which is what
  > `openai/gpt-oss-120b` is behind Nebius) do not reliably honour it.
  > **Resolved toward scoping, not toward moving the reference.** The
  > parameter changes `llm.invocation_parameters`, so a reference capture
  > taken with it would differ from 2.6's GenAI capture by more than the
  > instrumentor and the matched pair would be matched on nothing. `converse`
  > therefore takes `parallel=False` by default and only `_fleet` passes
  > `True`. The pinning test still holds and was **extended** to assert the
  > reference run does not enable it — the property is now pinned in both
  > directions.
  > If an endpoint rejects the parameter with a 400 the harness reports that
  > and retries once without it, rather than losing a credentialed run to one
  > unsupported keyword. Detection is on the status code, never the message
  > text (`SPEC.md` §3.10's rule, applied to the harness).
  >
  > ---
  > **READ THE FINAL RECORD FIRST (below, "Fleet complete").** Two readings in
  > this section were **superseded** by the multi-model fleet, and only the
  > final one is right. They are kept rather than deleted because *how* they
  > were wrong is the more useful record: both were well-evidenced within their
  > setup, and the setup was the thing that needed varying.
  > ---
  >
  > **Superseded reading (1 of 2): `openai/gpt-oss-120b` calls tools
  > sequentially.** This part is still true, and it is a finding about **that
  > model**, not about models. What was wrong was everything generalised from
  > it. Four fleet attempts —
  > `--fleet 8` twice, `--fleet 12` twice, the last with
  > `parallel_tool_calls=True` — **32 runs, three specs aimed at the shape,
  > not one parallel call.** The endpoint accepted the parameter: no 400
  > retry was reported, so the capability was asked for and granted.
  > The evidence for *why* is in `08_three_at_once`: the **follow-up** LLM
  > span carries `llm.finish_reason: tool_calls` and requests a second tool.
  > `openai/gpt-oss-120b` is not declining to call several tools — it is
  > calling them **sequentially, across turns**. That is a fact about the
  > model. It is not a harness defect and not an endpoint limitation, and both
  > of those were ruled out rather than assumed: the parameter was sent, and
  > the spans show the model going on to request more.
  >
  > **Two limitations this puts on the fleet as evidence. Neither may be
  > absorbed silently at 2.4.**
  >
  > 1. **`parallel_tool_calls` coverage comes from a hand-authored fixture,
  >    not from a model.** Every other required shape in the fleet was
  >    produced by a real run; this one exists in the corpus only. P5's
  >    resolution must **state which kind of evidence it rests on for this
  >    shape** — a fixture and a captured trace are different claims
  >    (`FIXTURES.md` §6), and a resolution that reports "all four shapes
  >    present" without that distinction would be overclaiming exactly where
  >    the fleet was weakest.
  > 2. **Every fleet trace is at most `agent -> llm -> tool -> llm`, and this
  >    is the broader limitation.** `converse()` executes tools for one turn
  >    only. Real agent runs loop until done, so P5 — *one trace = one graph*
  >    — is being tested against traces **structurally shallower** than the
  >    ones a fleet aggregator would meet in the wild. A model that would have
  >    exposed a shape problem at depth cannot do so here. **Whether
  >    `converse()` should loop is a decision for the 2.4 HALT, with the
  >    aggregator's experience in hand — it is not changed now**, because
  >    changing the harness mid-timebox to chase a shape is how a two-day box
  >    becomes a week.
  >
  > **An unpaired call nobody designed — and it is systematic.** A sweep of
  > all twelve traces: **five carry `unpaired_call`** — `02_two_cities`,
  > `03_weather_and_people`, `08_three_at_once`, `10_two_cities`,
  > `11_weather_and_people` — and those are **exactly** the specs that asked
  > for more than one tool. Every one requested a second tool on the follow-up
  > turn and got no span for it, because `converse()` stops after one turn.
  > That, not `08` alone, is the evidence for the sequential-calls reading
  > above: it is a reproducible behavior tied to a property of the prompt, not
  > one model response that happened to go that way.
  > The corpus carries `unpaired_tool_call` as a **hand-authored degenerate
  > scenario**, built from a mismatched id. Here the identical diagnostic
  > arises from real telemetry by a **different cause** — a truncated agent
  > loop. That is worth recording on its own terms: it is evidence that the
  > degenerate scenarios describe **real situations** and not just the ways we
  > imagined a trace could be malformed, which is the thing hand-authored
  > fixtures can never establish about themselves. The same traces also carry
  > a declared `data` edge (`SPEC.md` §4.2.1) — the second time that relation
  > has turned up outside a fixture.
  >
  > **The fleet has exactly two shapes.** Nine traces are 4 nodes / 7 edges;
  > three are 2 nodes / 1 edge. Nothing in between, no variation in depth or
  > breadth at all. That is limitation 2 above seen from the outside, and it
  > sharpens it: **the aggregator may find P5 holds simply because nothing in
  > this fleet stresses it.** *"P5 survived this fleet"* is a weak claim when
  > the fleet has two shapes, and **2.4's resolution must say so explicitly**
  > rather than reporting survival. A negative result from an unstressed test
  > is not evidence of generality; it is absence of evidence, and the whole
  > point of `PREDICTIONS.md` is not to let those two be written down the same
  > way.
  >
  > **Reopened: a fleet from one model is a batch, not a fleet.** The stop rule
  > above is about **selection pressure inside a fixed setup** — rewording
  > prompts until one model does what you want. **Swapping the model changes
  > the setup**, and 2.2's objective was the *shape*, not the model. Nothing
  > pins the fleet to `gpt-oss-120b`; that pin belongs to **2.6's matched
  > pair**, which is untouched.
  > The stronger reason is not procedural: **real fleets span models.** A
  > multi-model fleet is closer to what a fleet aggregator actually meets,
  > which is precisely what P5 needs — so this makes the fleet better evidence
  > regardless of whether parallel calls appear.
  > `RunSpec` gains `model` and `endpoint_env`. The three parallel-aimed specs
  > are repeated against **`Qwen/Qwen3-235B-A22B-Instruct-2507`** (same
  > endpoint) and **`moonshotai/Kimi-K3`** (needs `NEBIUS_BASE_URL_EU_WEST2`),
  > both of which advertise strong agentic tool use. Same prompts, same tools,
  > same instrumentor — **only the model differs**, so a difference in outcome
  > is attributable to the model and to nothing else.
  > Four things are enforced rather than intended:
  > - **Attribution.** Every fleet trace stamps `{"model", "spec"}` as
  >   OpenInference `metadata` on its `agent.run` span, and carries the model
  >   in its filename. A fleet that mixes models without saying which is worse
  >   than a single-model fleet, because every finding it produces is
  >   unattributable. The reference capture is **not** stamped — that would be
  >   one more difference in a pair that must differ only in the instrumentor
  >   — and there is a test for each direction.
  > - **The bound.** At most **two** models beyond the configured default
  >   (`MAX_EXTRA_MODELS`), pinned by a test, because past that it *is*
  >   selection. Only parallel-aimed specs may name a model, also tested:
  >   varying it elsewhere would make every other finding harder to attribute
  >   for no gain.
  > - **No misrouting.** A spec whose `endpoint_env` is unset is **skipped and
  >   reported**, never sent to the default endpoint — the `SPEC.md` §6.1
  >   posture, for the same reason: a trace whose provenance is wrong is worse
  >   than a trace you do not have.
  > - **No silent cap.** The multi-model specs sit at the end, so `--fleet 8`
  >   reaches none of them. The harness names every spec it did not reach and
  >   says to run `--fleet 14`.
  > *(That anticipation — "if neither model produces parallel calls, the shape
  > is rarer in practice than the corpus implies" — is **superseded reading 2
  > of 2**. Both models produced them immediately. See below.)*
  >
  > ### Fleet complete — 14 traces, three models, all five shapes
  >
  > Reproduced on a **second independent run**, so what follows is stable
  > behavior rather than a lucky draw.
  >
  > **1. Parallel tool calls are routine. `gpt-oss-120b` is the outlier.**
  > Qwen3-235B and Kimi-K3 produced them on **every** parallel-aimed spec,
  > first try, both runs. `three_at_once` builds to 6 nodes / 15 edges on both:
  > **3 `call_result` edges and 3 declared `data` edges**, against
  > `gpt-oss-120b`'s 1 and 1 for the identical prompt and tools.
  >
  > **This reverses the earlier reading, and the reversal is the finding.**
  > "Parallel calls are rare in practice; the corpus overstates the shape" was
  > wrong. It was one model's behavior generalised from a sample of one — and
  > it was not sloppy: 32 runs, three specs aimed at the shape, the capability
  > explicitly enabled and accepted by the endpoint, a mechanism identified
  > (sequential calls across turns) and corroborated by
  > `llm.finish_reason: tool_calls` on follow-up spans. **Well-evidenced,
  > internally consistent, and still wrong**, because every one of those 32
  > runs varied the prompt inside a fixed setup and the setup was the variable
  > that mattered. The corpus's `parallel_tool_calls` scenario describes
  > something **common**, and the fleet now produces it from a model rather
  > than only from a fixture — which retires limitation 1 above as well.
  >
  > **2. The unpaired call is an interaction, not a truncated loop.** Sharper
  > than recorded above: the Qwen and Kimi traces have **zero** unpaired calls
  > despite running through the *same* single-turn loop, because a model that
  > requests everything in one turn is fully served by one turn. The unpaired
  > call is the **interaction** between a sequentially-calling model and a
  > single-turn loop — a property of neither alone.
  > That **weakens the case for making `converse()` loop**: the shape it would
  > fix is specific to models that call sequentially, and two of the three
  > models here do not. Still a 2.4 decision, now with a smaller expected
  > payoff.
  >
  > **3. A harness defect that would have corrupted 2.3's evidence silently.**
  > `_fleet` appended rather than replaced, so `--fleet 14` after `--fleet 12`
  > left **26 files** — 12 stale under the old naming beside 14 new. An
  > aggregator pointed at that directory would have double-counted nine traces
  > and treated stale runs as distinct from their own re-runs. And the
  > duplicates are **not identical**: `unmapped_attributes` went 2 → 3 once the
  > model/spec stamp was added, so they would have read as *real variation*
  > rather than as duplicates. Fixed: the directory now holds exactly one
  > fleet, only files this harness writes are removed, and the count removed is
  > reported.
  >
  > **The recorded limitation, updated.** The fleet is **five distinct shapes
  > across three models**, not two across one: `2/1` (no tool call), `4/7`,
  > `4/7` with an unpaired call, `5/11` (two parallel calls), `6/15` (three).
  > It is **still a one-turn fleet** — `converse()` executes tools for one turn,
  > so no trace is deeper than `agent -> llm -> tool* -> llm`, and depth
  > remains untested. But it is no longer *unstressed*: it varies in breadth,
  > in diagnostics, in edge count, and across three models. **2.4's resolution
  > must still name the depth limit** — "P5 survived a one-turn fleet" is the
  > honest claim — but it no longer has to add "and a fleet with two shapes".
  >
  > **One thing the library got right that nothing had tested.** `04_no_tool`
  > and `07_out_of_scope` are the **first traces it has ever seen with no tool
  > span at all** — the model answered directly. Both build to 2 nodes and a
  > single `parent` edge: no spurious `temporal` edge between a parent and its
  > only child, no invented `tool` node, no diagnostic beyond the ordinary
  > `unmapped_attributes`. The corpus contains no such scenario, so this is
  > the pipeline handling a shape it was never shown, correctly — and it is
  > the kind of evidence only real traces produce, since a corpus can only
  > test the shapes someone thought to write down.
  >
  > **Correction, made at 2.3: three traces carry `unpaired_call`, not five.**
  > The "five" above — `02`, `03`, `08`, `10`, `11` — is a count of the
  > **12-trace** fleet under the old naming. In the final 14-trace fleet the
  > files at `10` and `11` are Qwen re-runs and are clean, so the traces that
  > carry the diagnostic are `02_two_cities`, `03_weather_and_people` and
  > `08_three_at_once` — **three, all `openai/gpt-oss-120b`, one diagnostic
  > each**. Verified from the graphs, not the traces: the aggregator's
  > `unfulfilled_calls.by_model` reports `openai/gpt-oss-120b: 3`.
  > The number was carried forward across the re-run without rechecking. It
  > changes nothing in the reading above — the correlation it supports is
  > *stronger* at 3-of-6 gpt-oss traces than it looked at 5-of-14 — but a
  > stale count in the evidence record is exactly the kind of thing 2.4 must
  > not build on.

- [x] **2.3 Fleet aggregator in `examples/`.**
  **The fleet is evidence, and reading how it was made destroys it.** The 14
  traces in `capture/_scratch/fleet/` are telemetry from someone else's
  system. Do **not** read `capture/` to learn how they were produced — not
  `fleet.py`, not `backends.py`, not the 2.2 record in this file. If you need
  to know something about a trace, the graph is where you find it, and **if
  the graph does not carry it, that is the finding.** This task measures
  whether the graph is sufficient for a consumer; knowing the answer from the
  producer's side makes the measurement meaningless. This constraint survives
  compaction only because it is written here — re-read it if the session runs
  long.
 `[2b]` **The timebox starts
  here, with 2.2's fleet in hand.** Build the consumer most likely to break the
  model: a rollup over **many** graphs — per-tool call counts and failure
  counts, per-diagnostic-code counts, per-node-kind counts, across every trace
  at once. It exists to
  attack `PREDICTIONS.md` P5 ("one trace = one graph"), so build it the way a
  fleet consumer would actually want it and **write down every place the
  library fights you** — that friction is the entire deliverable.
  Constraints: `examples/fleet_aggregate/`, outside the package, **public API
  only** (`spanweave/__init__.py` exports — reaching into an internal module
  would fake a generality the library does not have), and **no network**
  (`ENVIRONMENT.md`: examples consume committed fixtures so anyone can
  reproduce them). **2.2's fleet is the pressure this task exists to apply** —
  run the aggregator over it during the box — but it is never a committed
  input, so what lands in `examples/` must still run for a stranger against the
  corpus alone.
  Do **not** fix the library here. A change to `spanweave/` from this task is a
  finding to record at 2.4, not a patch to apply — that is the difference
  between falsifying the model and quietly accommodating the consumer.
  *Done when `uv run python -m examples.fleet_aggregate fixtures/conformance/*/dialects/openinference.jsonl`
  prints a deterministic rollup over every buildable scenario, running it twice
  is byte-identical, `uv run ruff check .` is clean, `uv run mypy examples` is
  clean (add the target to `make types`), and a test runs the example over the
  committed corpus so it cannot rot.*
  > **Built and run against both corpora.** `examples/fleet_aggregate/` rolls
  > up node kinds, diagnostic codes, per-tool calls/status, per-model llm
  > calls, and unfulfilled calls, over any number of traces. Public API only;
  > no import from `spanweave` outside `__init__`'s exports. All five
  > done-when clauses are green and `make check` passes (656 tests).
  > **The friction is recorded at 2.4** — that is the deliverable, and it is
  > written there rather than here so the whole timebox reads in one place.
  > Four things about *this* task that belong here:
  > - **Run-loop step 3, adapted the way 2.2 adapted it.** There is no new
  >   conformance fixture and no expected canonical graph to author: the
  >   corpus already exists and 2.3 must not touch it. The expected output
  >   written first is `tests/test_example_fleet_aggregate.py`, committed red
  >   before the implementation existed. Its oracle is **recomputed from
  >   `fixtures/conformance/*/expected/`** rather than snapshotted from the
  >   aggregator: a golden file would agree with whatever the code printed,
  >   where this disagrees when the code is wrong. Six of seven checks passed
  >   on the first run of the implementation; the seventh failed because the
  >   oracle had not yet been widened to the per-status tool breakdown.
  > - **Two rollups beyond the three the task names**, both free from
  >   `Node.operation` (`SPEC.md` §3.1 defines it as tool name / model name):
  >   per-model `llm` counts, and `unfulfilled_calls.by_model`. The second is
  >   not decoration — it is the exact contrast that makes the task's central
  >   finding legible, and it is pinned by a test in **both** directions
  >   (`by_model` sums to the total; `by_tool` is empty).
  > - **The aggregator is dialect-neutral by construction**, and that was a
  >   decision with a cost. Where reading a payload's shape would have bought
  >   an answer, it declines and emits the reason into a machine-readable
  >   `limits` list instead. An example that quietly became an OpenInference
  >   tool would have reported a generality the library does not have.
  > - **Nothing under `spanweave/` was changed.** Per the task, every place
  >   the library fought back is a finding at 2.4, not a patch.

- [x] **2.4 Timebox close: the findings record.** `[2b]` **NEVER CUT**
  (`ROADMAP.md`: "cutting a timeboxed item means the box was never real").
  At the end of day two, whatever state 2.3 is in, write the record here:
  every place the aggregator wanted something the model would not give, each
  classified **shape** or **operational** by `PREDICTIONS.md`'s binding test —
  *could an existing `graph.json` express this need, if it had been built with
  different options?* Yes → operational. No → shape. Do not widen the
  distinction to fit what happened; that is the rationalization the file exists
  to prevent. State plainly what the aggregator did **not** get to, so the
  finding is not read as broader than it is.
  *Done when this file carries the findings record, each item classified with
  its reasoning, and the aggregator's state at expiry is described honestly.*
  **HALT** — **P5 is resolved by a human**, in `PREDICTIONS.md`, which the
  agent must not edit (`AGENT.md`). The human also decides go/no-go on 2a: a
  **WORSE** on P5 means the model changes first and every 2a task below is
  re-planned against the changed model.
  *Artifact for the decision:* the findings record above, the aggregator as it
  stands, and — for each shape-classified item — the exact field, `NodeKind`,
  `EdgeKind`, warrant, `Payload` state, `Diagnostic` code or query primitive
  that would have to exist.

  > ## The 2b findings record
  >
  > **State of the aggregator at close.** Complete and green against both
  > corpora. `examples/fleet_aggregate/` rolls up node kinds, diagnostic
  > codes, per-tool calls and status, per-model `llm` calls, unfulfilled calls
  > by model, unfulfilled results, and unbuildable inputs, over any number of
  > traces, in text or JSON. Seven tests, `make check` green (656 tests).
  >
  > **The timebox did not bind, and that is part of the record.** The work
  > finished inside the box; nothing below is missing because time ran out.
  > Everything missing is missing for a *stated* reason — a scope rule, one
  > dialect, or the fleet's own shape — and those reasons are named. A record
  > that blamed the box for its gaps would be hiding the real limits behind an
  > acceptable-sounding one.
  >
  > **Nothing under `spanweave/` was changed.** Per 2.3, every item below is a
  > finding, not a patch.
  >
  > ### Index
  >
  > | # | What the aggregator wanted | Class |
  > |---|---|---|
  > | F1 | A multi-graph entry point (`build_all`) / a fleet type | **operational** — and it never hurt |
  > | F2 | Cross-trace edges | *not wanted* — refutes one of P5's predicted symptoms |
  > | F3 | A non-building trace representable inside the rollup | **operational** |
  > | F4 | To `except` the library's own error type | **operational** — spec/surface inconsistency |
  > | F5 | Which **tool** an unfulfilled call asked for | **SHAPE** |
  > | F6 | A success signal on tool spans that have one | *not a model finding* — a **corpus** finding |
  > | F7 | To know which diagnostic codes are node-scoped | **operational** |
  > | F8 | A graph-level annotation, for cohorting | **shape**, but anticipated, never encountered in anger |
  > | F9 | A trace identity usable as a fleet key | **operational** — and largely a corpus artifact |
  >
  > ---
  >
  > ### F1 — no multi-graph entry point. **Operational.** It never hurt.
  >
  > `build()` is one source → one graph, so the aggregator wrote its own loop
  > and its own accumulator (`aggregate()`, `Fleet`). That is the literal
  > subject of P5, so it is reported first and reported honestly: **it was
  > about eight lines and it cost nothing.** Every number in the rollup came
  > out of existing `graph.json` documents, unchanged, built with default
  > options.
  >
  > Binding test: could an existing `graph.json` express the need? **Yes** —
  > it *did*, nineteen and then fourteen times over. A `build_all()` would be
  > a convenience on the API, not a change to the document. **Operational.**
  >
  > ### F2 — cross-trace edges were never wanted. *Refutes a predicted symptom.*
  >
  > P5 names three anticipated remedies: `build_all()`, **cross-trace
  > linking**, or an aggregate type. The aggregator wanted the first as a
  > convenience and never wanted the second at all. A fleet rollup is counts
  > over a *set* of traces; there is no relation between trace 3 and trace 9
  > to draw. This is a negative result and it belongs in the record: one of
  > the three things P5 predicted would be needed was not needed, and the
  > `EdgeKind` enum was never under pressure from this consumer.
  >
  > ### F3 — a trace that does not build cannot join the rollup. **Operational.**
  >
  > `duplicate_span_ids` raises `DuplicateNodeIdError`. In a fleet, one bad
  > trace must not cost the other ten thousand, so the consumer wraps every
  > build and invents its own record (`TraceFailure`) to hold what the library
  > raised. There is no graph-shaped or diagnostic-shaped representation of
  > "this input did not build", so unbuildable traces cannot be counted in the
  > same structure as everything else.
  >
  > Binding test: the *information* the consumer needed — which input, which
  > exception, which code — was fully available from what was raised. Nothing
  > had to be guessed or inferred. What is missing is a container, not a fact,
  > and `graph.json` is untouched by the fix. **Operational.**
  >
  > `SPEC.md` §3.10's choice to raise here rather than emit a partial graph is
  > *right* and this finding does not argue with it: a graph that quietly
  > holds three of your four tool calls is worse than no graph, and a fleet is
  > exactly where that would go unnoticed.
  >
  > ### F4 — the error types are not on the public API. **Operational.**
  >
  > The sharpest of the operational findings, because it is a plain
  > inconsistency between the spec and the shipped surface. `SPEC.md` §3.10
  > says error codes are "a public contract from `0.9.x`" and instructs
  > callers to "**match on the code, never on the message**". But
  > `spanweave/__init__.py` exports neither `SpanweaveError` nor any of the
  > five subclasses in that table. A public-API-only consumer therefore
  > **cannot** `except SpanweaveError`. It must `except Exception` and
  > duck-type `getattr(error, "code", None)` — which is what
  > `TraceFailure.__init__` does, with a comment saying why.
  >
  > The cost is not cosmetic: a missing file, a permissions error and a
  > `MemoryError` all land in the same branch as a trace the library
  > deliberately refused, and the consumer cannot tell them apart. The one
  > distinguishing signal is `.code` being `None`, which is an absence, not a
  > statement.
  >
  > Binding test: needs no change to any `graph.json` and no build option —
  > it needs an export. **Operational.**
  > *Concrete:* add `SpanweaveError` and the subclasses named in the §3.10
  > table to `spanweave/__init__.py` and `__all__`. Worth doing regardless of
  > how P5 resolves, and cheap while the surface is unfrozen.
  >
  > ### F5 — an unfulfilled call cannot be attributed to the tool it asked for. **SHAPE.**
  >
  > **This is the finding.** It was predicted as a candidate at the start of
  > 2.3 and it is recorded here because the aggregator hit it, not because it
  > was expected to.
  >
  > The rollup a fleet consumer actually wants is *"which tools get requested
  > and never run"* — that is the fleet-scale version of the question
  > `unpaired_call` exists to answer. The graph can attribute an unfulfilled
  > call to the **model that asked**: the diagnostic carries `node_id`, the
  > node is the `llm` that requested it, and `Node.operation` is the model
  > name (`SPEC.md` §3.1). The aggregator does exactly that, and over the
  > fleet it reports `openai/gpt-oss-120b: 3` with no producer-side knowledge.
  >
  > It **cannot** attribute the call to the **tool it named**. A call that was
  > requested and never fulfilled has **no node**, so the operation it asked
  > for exists nowhere in the model. `Diagnostic.source` carries the bare call
  > id (`"chatcmpl-tool-8aee0472ff5742cd"`) and nothing else.
  >
  > The two halves sit side by side in the output on purpose, because the
  > boundary is the finding: **the graph knows who asked, and not what for.**
  > Both are pinned by `test_the_boundary_the_task_exists_to_find_is_in_the_output`,
  > in both directions, so a change that made `by_tool` answerable fails a
  > test and gets read here rather than passing silently.
  >
  > Binding test: could an existing `graph.json` express it, built with
  > different options? The only options are `adapter` and `temporal`, and
  > neither is relevant. The tool name is present in the input bytes and
  > **preserved verbatim** — losslessness holds, this is not a losslessness
  > bug — inside the requesting node's `outputs` payload, at
  > `value["choices"][0]["message"]["tool_calls"][…]["function"]["name"]`.
  > It is preserved but not **modeled**. **SHAPE.**
  >
  > **Would the aggregator break on a second dialect if it reached in?**
  > **Yes, and silently — which is the worse failure.** That path is the
  > OpenAI chat-completion response shape as OpenInference records it. An
  > OTel GenAI rendering of the same scenario puts the fact somewhere else, or
  > does not carry it. A consumer that walked it would produce correct numbers
  > for dialect one and, for dialect two, either a `KeyError` or — far more
  > likely, since the code would have to be defensive to survive absent
  > payloads at all — **a confident zero**. A fleet dashboard reading
  > "0 unfulfilled calls" because its payload path missed is indistinguishable
  > from one reading "0 unfulfilled calls" because there were none.
  > This is why the aggregator declines and emits `limits` instead.
  > **2a can settle it directly:** render `unpaired_tool_call` in
  > `otel_genai` and check whether *any single* payload path yields the tool
  > name in both dialects. If none does, F5 is confirmed as shape by
  > independent evidence.
  >
  > **What would have to exist.** Three options, and the human's decision is
  > which — or whether the rollup is simply not owed.
  >
  > - **A. A convention on `Diagnostic.source`.** `source` is `JsonValue`, so
  >   an adapter could already put `{"call_id": …, "operation": …}` there
  >   instead of a bare string. **No schema change, no halt point** — which
  >   means F5 has a schema-legal shortcut, and the record must say so rather
  >   than present the shape reading as the only one. The cost: it is a
  >   per-adapter *convention*, not a contract. A consumer cannot rely on it,
  >   cannot tell a dialect that does it from one that does not, and would be
  >   right back to duck-typing. It buys the number and gives up the guarantee.
  > - **B. A node for the request.** A `tool` node — **no new `NodeKind`
  >   needed** — with `operation` set, `inputs` from the requested arguments,
  >   `outputs` `PayloadState.absent`, and the existing `call_result` edge from
  >   the `llm` with warrant `explicit`. This makes `by_tool` fall out of the
  >   normal rollup with no special case at all. **But it needs a way to say
  >   "this node is a request, not an observation"**, and the model has no such
  >   distinction. `Status.UNSET` cannot carry it — F6 shows `unset` already
  >   means "the telemetry did not say", and real tool spans use it constantly.
  >   So B needs a new `Status` member (or a `Payload` state, or a node-level
  >   flag), and **every one of those is a halt point** (`AGENT.md`: adding or
  >   renaming a `NodeKind`, `EdgeKind`, `Payload` state, warrant, or
  >   `Diagnostic` code). B is also the option most at risk of breaking
  >   invariant 2 in spirit: a node that was never observed is the library
  >   asserting something the telemetry did not.
  > - **C. A dangling edge.** A `call_result` edge with no `dst`. Dead end, and
  >   instructive: `SPEC.md` §4.0 lets a `link` dangle and forbids `parent` to.
  >   A dangling `call_result` is a **third** case the model does not have, and
  >   inventing one to solve a rollup would be the tail wagging the dog.
  >
  > *Recommendation, offered as input and not as a decision:* **A is the
  > cheapest and B is the honest one**, and the choice is really a question
  > about what `Diagnostic` is *for* — a report to a human, or a queryable
  > part of the graph. That question is bigger than this rollup, which is why
  > it stops here.
  >
  > ### F6 — successful tool spans have no success signal, and the corpus hides it. *Corpus finding.*
  >
  > Over the 14-trace fleet: `get_weather` 12 calls — **0 error, 0 ok, 12
  > `unset`**. `get_population` 4, all `unset`. `convert_currency` 3, all
  > `unset`. `lookup_flight` 1 call, 1 **error**. So a fleet "tool failure
  > rate" has a real numerator and a denominator complement that is
  > **unknowable**: 19 of 20 fleet tool calls never said whether they
  > succeeded.
  >
  > This is **not** a finding against the model. No build option can add a
  > status the trace does not carry, and inferring `ok` from "the span did not
  > error" is precisely the inference `CLAUDE.md` 2 forbids. The library is
  > right, and visibly so — which is why the aggregator prints `error`, `ok`
  > and `unset` as three separate columns rather than folding two of them.
  >
  > **The finding is about the corpus.** Every tool node in
  > `fixtures/conformance/` is `status: "ok"` — 18 of 18. Not one real tool
  > span in the fleet is. The corpus therefore encodes *our idea* of what a
  > tool span looks like, and a consumer written against the corpus alone
  > would compute a success rate that silently reads zero against real
  > telemetry. This is the same family as `FIXTURES.md` §5.1's Phase 1
  > defect — fixtures agreeing with the adapter because both came from one
  > reading of the dialect — and it was invisible until real traces
  > disagreed. **Recommend a conformance scenario whose tool span carries no
  > status**, so `unset` is somewhere in the corpus. Filed here rather than
  > acted on: 2.3 must not touch the corpus, and 2a owns the next fixtures.
  >
  > ### F7 — diagnostics are not uniformly node-scoped, and nothing says which are. **Operational.**
  >
  > Across both corpora, every observed code carries a `node_id` except
  > `ordering_cycle`, which is graph-scoped and carries `None`.
  > `malformed_record` and `multi_trace_input` are very likely the same, but
  > neither appears in either corpus so this is unverified. A fleet dashboard
  > cross-tabbing diagnostics by model or by node kind therefore has a
  > partial answer, and **the only way to learn which codes are attributable
  > is to try them.** The aggregator handles it by naming the two ways
  > attribution can fail (`(no node on the diagnostic)`,
  > `(node not in this graph)`) as buckets rather than dropping them.
  >
  > Binding test: for every code that carries a node, the attribution the
  > consumer wanted is already expressible from today's `graph.json`. What is
  > missing is a *statement of which codes those are* — contract, not schema.
  > **Operational.**
  > *Concrete:* a **node-scoped** column on the `SPEC.md` §3.7 code table,
  > with a test pinning each code's answer against the corpus.
  >
  > ### F8 — no graph-level annotation. **Shape — but anticipated, not encountered.**
  >
  > `graph.annotate(node_id, …)` is node-scoped, and the serialized
  > `annotations` list is node-keyed. There is nowhere to hang a fact about
  > **the trace as a whole** — "fleet run 3", "prompt v2", "cohort A" — which
  > is the natural way to carry a cohort through a fleet analysis. The
  > workaround is to annotate the root node, and the root is not a given: the
  > two corpora hold graphs with 1 root (30), **0** roots (`cyclic_parents`),
  > 2, and 3. There is also no `roots()` primitive; a consumer recomputes it
  > from `parents()`.
  >
  > Binding test: no option produces a place in the document for it. **Shape.**
  > *Concrete:* a graph-scoped namespace in `AnnotationStore` and a
  > corresponding root key in the serialized document — additive, and
  > therefore cheap **now** and expensive after the freeze.
  >
  > **The honest weight, which must not be lost:** the aggregator **never
  > needed this.** It keyed the rollup on the input it was handed and lost
  > nothing. F8 is a gap noticed while deliberately looking for gaps, not one
  > that stopped the work. It is listed because omitting it would be worse,
  > and it is marked because reading it at the same weight as F5 would
  > overstate the evidence.
  >
  > ### F9 — no trace identity usable as a fleet key. **Operational.**
  >
  > Two candidate keys, with complementary weaknesses. `Graph.trace_id` is
  > **`"t1"` for all nineteen buildable corpus scenarios** — a fleet keyed on
  > it collapses the entire corpus into one trace. `meta.source_digest`
  > fingerprints the input *bytes*, so the same trace re-exported with its
  > lines in a different order gets a different digest while the graph is
  > byte-identical (`SPEC.md` §3.9 states this and calls it correct — it is).
  > So one key can collide for different traces and the other can differ for
  > the same graph.
  >
  > Binding test: both fields are already in today's `graph.json`; the
  > aggregator keyed on the input path and lost nothing. **Operational.**
  >
  > Recorded despite being minor because 2.2's own near-miss is exactly this
  > failure — 26 files in the fleet directory, nine of them stale duplicates
  > that would have read as *real variation* rather than as double-counting.
  > The aggregator now **reports the collision** in its output
  > (`distinct_trace_ids`, plus a note when it is fewer than the traces built)
  > rather than silently collapsing, and a test pins that behavior against the
  > corpus. Mostly a corpus artifact: all 14 real fleet trace ids are distinct.
  >
  > ---
  >
  > ### What the aggregator did **not** get to
  >
  > Stated plainly so no finding above is read as broader than it is.
  >
  > - **Latency and token rollups were not built.** `started_at` / `ended_at`
  >   and `Usage` are on every node and either would have been trivial. They
  >   are Phase 3's confirmatory consumer and `AGENT.md` forbids writing it
  >   here. The consequence is real: P5 is **untested against the consumer
  >   most likely to want cross-trace numeric aggregation**, which is arguably
  >   the one it was written about. Everything above is counts.
  > - **No statistic beyond a count.** No percentiles, no distributions, no
  >   per-trace vectors, no comparison between cohorts.
  > - **One dialect.** Every number here is OpenInference. The claim "a
  >   dialect-neutral fleet rollup is possible" is a property of code written
  >   to be neutral, **not** a property tested by a second rendering. 2a is
  >   what turns it into evidence — see F5's test.
  > - **The query primitives were never used.** `paths`, `reachable`,
  >   `descendants`, `subgraph`, `annotate` — the aggregator called none of
  >   them. It needed `nodes()`, `edges()`, `node()`, `parents()` and
  >   `diagnostics`. Nothing is known about how the traversal surface behaves
  >   under fleet pressure.
  > - **Depth was never tested**, and this is 2.2's standing limitation
  >   carried forward, not a new one. No fleet trace is deeper than
  >   `agent → llm → tool* → llm`, because `converse()` executes tools for one
  >   turn. A shape problem that only appears at depth could not have surfaced
  >   here. **The honest claim is "P5 survived a one-turn fleet."**
  > - **Scale was never tested.** 14 traces and 19 scenarios. `build()` reads
  >   whole files and `Fleet` accumulates counters rather than graphs, so it
  >   would *probably* hold at 10,000 — and "probably" is the accurate word.
  >
  > ### What this fleet cannot tell you, however good the graph is
  >
  > Carried here so it is not mistaken for a model finding at the HALT.
  >
  > All three unfulfilled calls are `openai/gpt-oss-120b`, and the graphs
  > support that attribution completely. What the graphs **cannot** separate
  > is *the model requesting tools one at a time* from *the harness serving
  > one turn* — those two variables move together across all fourteen traces,
  > so the correlation is **confounded**. That is a limitation of **the
  > evidence**, not of the graph: no field on any `graph.json` could separate
  > them, because a trace does not record the loop policy of the application
  > that produced it. Only a fleet that varied the loop could. **Do not read
  > this as something a better model would have expressed.**
  >
  > ### The evidence P5 rests on — not a resolution
  >
  > P5 is resolved by a human, in `PREDICTIONS.md`, which this agent must not
  > edit. What the two days produced, stated for that decision:
  >
  > - **P5's headline — "one trace = one graph" — did not break the
  >   aggregator.** The rollup was written against unmodified `graph.json`
  >   documents, built with default options, and every count it publishes came
  >   out of them. Of the three remedies P5 anticipated, one (`build_all`) was
  >   a convenience, one (cross-trace edges) was never wanted, and one (an
  >   aggregate type) the consumer wrote for itself in a few lines.
  > - **One shape finding, and it is not the one P5 predicted.** F5 is not
  >   about multiplicity at all. It is about a single graph failing to model
  >   something it *reports* — a requested call with no node — and it would
  >   have been just as true of a single-trace consumer that asked the same
  >   question. The fleet did not cause it; the fleet made someone ask.
  > - **The claim's honest scope.** "P5 survived a **one-turn** fleet of
  >   fourteen traces across three models, tested by a **counting** consumer
  >   in **one** dialect." Every qualifier in that sentence is load-bearing
  >   and each is justified above.
  > - **Retired from 2.2's limitations:** `parallel_tool_calls` no longer
  >   rests on a hand-authored fixture — Qwen3-235B and Kimi-K3 produce it,
  >   and the aggregator counts 20 real tool calls across the fleet.
  >   **Still standing:** the depth limit.
  > - **A `converse()` loop is not recommended.** 2.2 left the decision to
  >   this HALT. The aggregator's experience does not argue for it: the shape
  >   it would fix (the unpaired call) is specific to sequentially-calling
  >   models, two of the three models here do not produce it, and F5 — the one
  >   shape finding — would be **unchanged** by looping, since a fulfilled
  >   call has a node either way. Looping would buy depth, which is the real
  >   untested axis, but that is a Phase 4 scope with its own budget, not a
  >   mid-timebox harness change.
  >
  > ### HALT cleared — the human's decision, recorded here for the next session
  >
  > **P5: REFUTED, scoped.** In `PREDICTIONS.md` (commit `200c22d`), which
  > this agent may now read and still may not edit. The refutation is scoped
  > and the human recorded the scope as **their** error, not the agent's: a
  > *counting* rollup structurally cannot need cross-trace linking, so the
  > consumer 2.3 directed could not have falsified the prediction it was aimed
  > at. **What reopens P5** is written into the entry — a consumer that
  > *relates* traces rather than counting over them (retry detection, session
  > reconstruction, or comparing one prompt across models, for which this
  > fleet already holds `two_cities` under three models).
  >
  > **A third classification now exists: SPEC GAP.** F5 is recorded as **O1**
  > in `PREDICTIONS.md` under it — the model *could* express the fact today
  > (`Diagnostic.source` is `JsonValue`), but nothing populates it and no
  > document asks for one. Neither shape nor operational fits: the schema does
  > not need to change, and no build option helps either. The binary in this
  > file's classification test was insufficient, and **later phases should use
  > the third category where it fits rather than forcing a fit.** O1 is filed
  > as an *observation*, not a prediction, because it was found after the work
  > that tested it began.
  >
  > **GO on 2a**, against the unchanged model. No model change is owed first,
  > so 2.5–2.14 stand as planned.
  >
  > **Accepted: `converse()` does not loop.** 2.2's deferred decision is
  > closed. Depth stays untested in Phase 2 and that limitation is carried in
  > the honest claim above.

---

### `[2a]` — the second dialect  *(begins only after 2.4's HALT clears)*

> **LIVE HANDOFF — read this before the first unchecked box.** One item, and
> it is **answered but not closed**: the evidence is in, the remedy is a
> human's to choose.
>
> **O1 / finding F5 — a requested-but-unfulfilled call names no tool.**
> `unpaired_tool_call` is now rendered in `otel_genai` and the three questions
> are answered at **2.10, Halt A**, with a remedy proposed and deliberately not
> implemented. Two things a reader should take from it before touching this:
>
> - **Neither dialect can name the tool from the graph, and they agree
>   exactly.** The diagnostic carries the call id three times and the name
>   zero times, in both.
> - **O1's stated risk is partly refuted.** The cross-dialect payload walk
>   **raises** — in both directions, including the defensive `.get()` idiom —
>   rather than reporting a confident zero. The zero comes from the consumer's
>   own `try/except`, which is a weaker gap than O1 claimed and still a gap.
>
> Do **not** implement a remedy without the decision. Three are costed at the
> task; `PREDICTIONS.md` is the human's to edit.

> **This workstream inverts Phase 1's order on purpose: capture first, then
> render from what the capture shows, then write the adapter.** Phase 1
> rendered from a *reading* of OpenInference and produced four fixtures that
> were confidently wrong about the dialect in three separate ways — invisible
> to 593 tests, six gates and two review scripts, because the fixtures and the
> adapter shared the error (`FIXTURES.md` §5.1). Only real instrumentor output
> disagreed. Do not repeat it.

> **Retired from the handoff list** (kept as pointers, not as tasks).
> **F6 — the corpus was 18-of-18 `status: "ok"` while no real tool span was —
> is CLOSED at 2.10.** A new scenario, `unset_and_error_status`, renders
> `unset` and `error` in both dialects from observed spans, and
> `test_the_corpus_is_not_uniformly_ok` makes the gap un-reintroducable rather
> than merely fixed.
>
> **F4 — the §3.10 error types were unexportable — is DONE** (2026-08-22,
> commit `89f629a`, its own commit rather than folded into 2.5). Two
> corrections to the finding as written: the §3.10 table names **three**
> subclasses, not five, and the fix was not only an export —
> `examples/fleet_aggregate` now distinguishes `refused` from every other
> reason a build can fail, which is the distinction F4 said was unavailable.
> `tests/test_codes.py` derives the required type names from the §3.10 table
> itself, so a type added to the spec and not exported fails the build.

> **WHERE THIS SESSION STOPPED (2026-08-27).** **Phase 2a is complete: 2.10
> through 2.14 are all done, and the Phase 2 exit HALT is live.** Do not start
> Phase 3.
>
> `make check` green (1155 tests), `make conformance` green, `make gates`
> green, `review_corpus.py` exit 0. The phase's central claim, over 17 of 21
> scenarios rendered in both dialects: **16 byte-identical canonical graphs,
> 1 identical refusal, 0 differ** — **not including `Node.name`, which 16 of
> the 17 declare dialect-varying (measured at 3.2; see 2.14's evidence block
> before quoting the figure).**
>
> **Read 2.14.** It is the phase-exit artifact and the input to the Phase 4
> freeze decision. Its headline: `spanweave/model.py` was **not touched** in
> all of Phase 2 — no kind, state, warrant or diagnostic code moved. One shape
> change (`Diagnostic.source` on two codes) and one additive public-API change
> (the §3.10 error types).
>
> Three things a next session should not have to re-derive:
>
> - **The pattern named at 2.14** — `mime`, `attributes` and
>   `Diagnostic.source` were each relied on with nothing stating it and nothing
>   asserting it, all three because the *permissive* default won, and all three
>   found only by a second dialect. Before the freeze: audit every serialized
>   field typed permissively. `Edge.basis` is the next one.
> - **The highest-value action outstanding is a capture, not a decision.** One
>   GenAI trace containing an `invoke_workflow` span retires three coverage
>   declarations at once and restores `EdgeKind.link` to the cross-dialect
>   claim. A capture is a human act (`AGENT.md` halt point).
> - **Both-sides `erase` is still not adopted**, deliberately, twice. It must
>   arrive in its own change with nothing riding on it.
>
> The handoff-note rule that produced this section's layout lives in
> `AGENT.md` ("Keeping a handoff note readable"), not here.

- [x] **2.5 GenAI capture backend — written, not run.** `[2a]` Add a third
  backend to `capture/` emitting **OTel GenAI** semantic conventions.
  Four things this task must get right:
  - **The package moved, and the agent must not guess which one works.**
    `opentelemetry-instrumentation-openai-v2` in `opentelemetry-python-contrib`
    now carries a migration note pointing at
    `opentelemetry-instrumentation-genai-openai` in the newer
    `open-telemetry/opentelemetry-python-genai` repository. These conventions
    are still moving. The backend must be written against whichever package
    **actually works when 2.6 runs it**, and the exact package name and version
    must land in the provenance file. Where the two disagree, record the
    disagreement rather than picking silently.
  - **Content capture is opt-in and the capture is useless without it.**
    Without it there are no `gen_ai.input.messages` /
    `gen_ai.output.messages` attributes — so no payloads, no tool-call ids, no
    `call_result`, and no §4.2.1 declaration. Enable it **explicitly** in the
    backend (do not rely on an ambient default), and make the harness **fail
    loudly** if the exported spans carry no message attributes rather than
    writing a useless trace.
  - **Same model, same prompt as the OpenInference capture** —
    `openai/gpt-oss-120b` via Nebius, the Paris weather conversation — so the
    *only* difference between the two traces is the instrumentor. Otherwise an
    equivalence failure cannot be attributed to the dialect rather than to the
    model behaving differently, and the whole comparison is worthless.
  - **The harness's own spans must speak GenAI**, not OpenInference. Only the
    `llm` spans come from the instrumentor; `capture/backends.py` emits the
    `agent` and tool spans itself (Phase 1 review). Emitting those in
    OpenInference keys would produce a mixed-dialect file that no adapter
    honestly reads. GenAI defines an `execute_tool` span, so unlike
    OpenInference the tool span here is convention-defined — say so in the
    printed provenance template.
  *Done when `uv run pytest tests/test_capture.py` is green with no key and no
  instrumentor installed (stub spans, as today), `make capture
  ARGS="--backend genai"` refuses with the actionable no-credential error,
  backend selection still refuses ambiguity by naming `--backend`, and a test
  asserts the harness's own spans carry `gen_ai.*` keys and no
  `openinference.*` ones.*

  > ### 2.5 — what it settled, and what it changed
  >
  > **Done.** `make check` green (680 tests). All four done-when clauses hold,
  > and five things are worth carrying forward.
  >
  > **1. The package question, settled by running both rather than reading.**
  > Checked 2026-08-22 by installing each into a throwaway environment and
  > driving a two-turn tool-calling conversation through it against a local
  > stub endpoint. The result is not a preference:
  >
  > | | `opentelemetry-instrumentation-genai-openai` **1.1b0** | `opentelemetry-instrumentation-openai-v2` **2.4b0** |
  > |---|---|---|
  > | Imports against `openai` 3.3.1 | yes | **no** — `from httpx import URL`, and `openai` 3.x depends on `httpx2`, so `httpx` is simply absent |
  > | With `httpx` installed alongside | — | works |
  > | Message attributes | identical — both delegate to `opentelemetry-util-genai` | identical |
  > | Also emits | `server.address`, `server.port`, `gen_ai.tool.definitions` | — |
  >
  > So: the newer package, because the older one **does not import at all**
  > against a current `openai` without an install its own metadata does not
  > ask for. The disagreement is recorded rather than tidied away, in
  > `capture/README.md` with its date. Neither package's PyPI metadata
  > actually carries the migration note the task text describes — what *is*
  > present is broader: in `opentelemetry-semantic-conventions` 0.65b0 the
  > whole `gen_ai.*` attribute set is marked *"Deprecated: moved to the
  > OpenTelemetry GenAI semantic conventions repository"*. **The names are
  > unchanged; the conventions moved house.** That is why `backends.py`
  > writes the attribute names as string literals instead of importing the
  > constants: a future rename should be a visible diff in one file.
  >
  > **2. A behaviour change to an existing command, not a new flag beside it.**
  > `genai` shares `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_MODEL` and the
  > default model with `openai` — that identity is the matched pair and is
  > pinned by a test. The consequence is that **one exported credential now
  > configures two backends, so a bare `make capture` refuses as ambiguous.**
  > That is the right refusal to be given: the two differ only in the
  > instrumentor, so a wrong guess produces an entirely plausible trace beside
  > a provenance file naming the wrong dialect. Both halves must now be named
  > explicitly. `capture/README.md` says so under *Which one runs*.
  >
  > **3. The emitted dialect is now a seam (`SpanDialect`), not a constant.**
  > Required by the fourth bullet, but worth naming as structure: the keys the
  > harness puts on its *own* agent and tool spans are a property of the
  > backend, chosen alongside the instrumentor and never independently of it.
  > The OpenInference emission is unchanged byte-for-byte and a test pins it,
  > because Phase 1's capture is committed and its provenance describes those
  > exact keys.
  >
  > **4. Three things added beyond the task text, each in service of 2.6.**
  > - The provenance template now prints the **exact installed versions**,
  >   read from the environment that produced the trace rather than typed from
  >   memory. 2.5 requires the fixture to name package and version, and these
  >   conventions move fast enough that a transcription step is where a
  >   provenance file goes quietly stale.
  > - The harness prints **2.6's three-point checklist answered against the
  >   records it just wrote**, and exits non-zero if any point fails (the file
  >   stays — it is the evidence for why). Same posture as the fleet's
  >   coverage report. It does not certify anything: a harness that both
  >   produces a trace and certifies it is not evidence, so the printed block
  >   says to confirm each point against the file.
  > - The harness reports any attribute that **names the service that
  >   answered** (`server.address`, `server.port`, `url.full`, `http.url`)
  >   before the redaction step. This is a real asymmetry, found by running
  >   it: the OpenInference instrumentor emits none of them, and
  >   `openai_tool_call.provenance.md` accordingly says *"The Nebius endpoint
  >   does not appear in the file at all."* **The GenAI instrumentor emits
  >   `server.address` and `server.port`.** Copying that sentence across would
  >   put a false claim in the one kind of file whose whole purpose is being
  >   true.
  >
  > **5. Verified end to end without a credential.** The harness was driven
  > through `run.main(["--backend", "genai"])` against a local stub
  > OpenAI-compatible endpoint in a throwaway venv with the real instrumentor
  > installed — no key, no model, no outside network, and nothing written into
  > the repository. It produced the `llm_tool_llm` shape in a single dialect,
  > all three verifications green, exit 0; and with content capture defeated
  > it refused **before any request reached the endpoint**, writing nothing.
  > That is the "verify it against stub spans, then STOP" `AGENT.md` sanctions,
  > and it is as far as it goes: a stub is not a model, so it says nothing
  > about what `openai/gpt-oss-120b` will actually emit. **2.6 is still a
  > HALT.**

- [x] **2.6 The GenAI capture run.** `[2a]` **NEVER CUT** (`ROADMAP.md`: a
  hand-authored fixture proves the adapter matches our *understanding* of a
  dialect; only a captured one proves it matches the instrumentor).
  **HALT — human-run, exactly as 1.9 was.** The agent must not synthesize a
  file and label it captured (`AGENT.md`, `FIXTURES.md` §6).
  Before the trace is treated as usable, verify **in the file**:
  1. `gen_ai.input.messages` / `gen_ai.output.messages` are present — content
     capture really was on;
  2. tool-call **ids** are present on both the requesting and the fulfilling
     span, or there is no `call_result` to recover;
  3. the follow-up turn's input carries the tool-result message with the same
     id — the `SPEC.md` §4.2.1 declaration. **If it does not, stop and say so:**
     `llm_tool_llm` is never-cut and its canonical graph contains that edge, so
     a dialect that cannot declare it is a finding about the corpus's
     equivalence rule, not a rendering to fudge (see 2.9's HALT).
  Then the usual three steps: read it, redact and record the redaction, move it
  to `fixtures/captured/` with `<name>.provenance.md`. The provenance must
  record the exact instrumentor package **and version** (per 2.5), and **both**
  provenance files must state that the two traces are a **matched pair** — same
  model, same prompt, different instrumentor — because that is the property
  that makes the equivalence comparison mean anything, and it is invisible from
  either file alone.
  *Done when `fixtures/captured/` holds the GenAI trace and its provenance,
  both provenance files carry the matched-pair statement, and the three
  verifications above are recorded as performed.*
  *Artifact for the decision:* the scratch trace from `make capture
  ARGS="--backend genai"`, plus the three-point verification checklist above
  answered against it.

  > ### 2.6 — HALTED, awaiting the human. Everything up to the credential is done.
  >
  > **Session stopped here (2026-08-22).** The agent has no model API key and
  > must not have one (`ENVIRONMENT.md`, `AGENT.md`). Nothing was written into
  > `fixtures/captured/`, and no file anywhere was labelled captured.
  >
  > **The runbook.** In an environment with `NEBIUS_API_KEY` and
  > `NEBIUS_BASE_URL` exported:
  >
  > ```bash
  > uv pip install openai opentelemetry-instrumentation-genai-openai opentelemetry-sdk
  > make capture ARGS="--backend genai"
  > ```
  >
  > `--backend genai` is now **required**, not optional: that backend shares
  > `NEBIUS_API_KEY` with `openai`, so a bare `make capture` refuses as
  > ambiguous (2.5, point 2).
  >
  > **The three-point checklist is answered for you, and you still confirm
  > it.** The harness reads the exported records back and prints all three
  > verifications with what each was read off, then exits non-zero if any
  > failed — the trace is still written, because it is the evidence for why. A
  > harness that both produces a trace and certifies it is not evidence, so
  > check each line against the file before promoting anything.
  >
  > **If point 3 fails — the follow-up turn does not declare the tool result
  > with the same id — stop.** Do not render around it. `llm_tool_llm` is
  > never-cut and its canonical graph contains that `data` edge, so a dialect
  > that cannot declare it is a finding about the corpus's equivalence rule
  > and belongs at 2.9's HALT, alongside `OPEN_QUESTIONS.md` §7 and
  > `PREDICTIONS.md` P3 — as evidence, never as a resolution of either. The
  > harness prints this sentence too.
  >
  > **Redaction differs from the first capture, and the difference is easy to
  > carry across wrongly.** `openai_tool_call.provenance.md` says *"The Nebius
  > endpoint does not appear in the file at all"* — true of the OpenInference
  > instrumentor. **The GenAI instrumentor emits `server.address` and
  > `server.port`.** The harness lists every such attribute with its value
  > before the redaction step; decide whether the host is public and say what
  > you decided. Do not reuse the other file's sentence.
  >
  > **Both provenance files need the matched-pair statement**, and the second
  > one is an edit to a file already committed:
  > `fixtures/captured/openai_tool_call.provenance.md` must gain a sentence
  > naming the GenAI capture as its pair. It was left alone deliberately —
  > asserting a pair before the other half exists would be a claim about a
  > file that is not there. The harness prints the sentence to copy.
  >
  > **Asked and answered: does the GenAI instrumentor require anything that
  > would change what the reference records?** No — and this was checked
  > rather than assumed, because absorbing such a change quietly is the
  > failure that would make the comparison worthless.
  >
  > - Same SDK object, same `client`/`request`/`results` functions, same
  >   credential, endpoint, model, prompt, tool inventory and conversation.
  >   Pinned by `test_the_genai_backend_differs_from_openai_only_in_the_instrumentor`.
  > - Neither half sends `parallel_tool_calls`; that stays scoped to the fleet.
  > - Content capture is a GenAI-only environment variable and has no effect
  >   on the OpenInference instrumentor.
  > - The OpenInference emission in `capture/backends.py` is unchanged
  >   byte-for-byte by the refactor, pinned by
  >   `test_the_openinference_spans_are_byte_for_byte_what_they_were`.
  >
  > **One asymmetry that cannot be removed, stated rather than hidden.** The
  > pair differs by the instrumentor *and* by what the two conventions define
  > for the spans no instrumentor emits. GenAI defines `execute_tool`;
  > OpenInference defines nothing for a tool execution. So on the GenAI half
  > the tool span is convention-defined (`execute_tool <name>`,
  > `gen_ai.tool.name`, `gen_ai.tool.call.id`) while on the OpenInference half
  > it is this harness's own invention. That is not a choice made here and
  > could not be avoided by any choice: it is a property of the two dialects,
  > and therefore part of what the equivalence test is for. Both provenance
  > files must say it, and the printed template does.
  >
  > **What was verified without a credential, and what that does not prove.**
  > The harness was driven end to end against a local stub OpenAI-compatible
  > endpoint with the real instrumentor installed: it produced the
  > `llm_tool_llm` shape in a single dialect, all three verifications green,
  > exit 0 — and with content capture defeated it refused **before any request
  > reached the endpoint**, writing nothing. A stub is not a model. It says
  > nothing about what `openai/gpt-oss-120b` will actually emit through this
  > instrumentor, which is the entire reason 2.6 exists.

- [x] **2.7 Equivalence harness: build every rendering.** `[2a]` **NEVER CUT**
  (`ROADMAP.md`: "without it, renderings are decoration").
  `tests/test_conformance.py` builds `scenario.dialects[0]` only — with one
  dialect that proves the pipeline reproduces the reviewed expectation, but it
  is not yet the cross-dialect claim. Parametrize over **every** rendering
  present whose dialect has a **registered adapter**, each asserted against the
  scenario's one unmodified canonical graph. Extend the same rule to the
  refusal scenarios: every rendering of `duplicate_span_ids` must raise the
  same error **type and code** (`FIXTURES.md` §4.2).
  The "has a registered adapter" clause is the transitional state 2.8 needs and
  2.9 closes, so make it **visible**: the suite must report which renderings it
  skipped and why, and a tripwire must assert that the set of adapter-backed
  dialects equals `DIALECTS` — which is what 2.13 finally flips. A silent skip
  is how a dialect's coverage rots one file at a time.
  *Done when the suite is green and unchanged in effect with one dialect, a
  planted second rendering that disagrees with the canonical graph **fails**,
  a planted rendering for an adapterless dialect is reported as skipped rather
  than passing silently, and `make conformance` is green.*

  > **Done (2026-08-27).** The suite now parametrizes over `Rendering`
  > objects — one dialect file of one scenario — rather than over scenarios,
  > and `built()` skips loudly rather than the parametrization filtering
  > quietly: *a filtered-out rendering leaves no trace in the run, and "we
  > chose not to check this" must not look like "there was nothing to check".*
  > `duplicate_span_ids` gets the same treatment, so §4.2's equivalence half
  > (same error type **and** code from every dialect) is now parametrized too.
  > 190 conformance tests, up from 106; with one dialect the effect is
  > unchanged, as required.
  >
  > Visibility is `tests/conftest.py`: a `pytest_report_header` naming the
  > declared dialects, the adapter-backed ones, and every skipped rendering
  > with its dialect — on **every** pytest run, not only under `-v`. Verified
  > by planting `otel_genai.jsonl` into `llm_tool_llm`: 5 skips, each reported
  > with the reason, header line `conformance SKIPPING 1 rendering(s) of
  > 'otel_genai'`. Both other done-when plants are permanent tests
  > (`test_a_second_rendering_that_disagrees_with_the_canonical_graph_fails`,
  > `test_a_rendering_for_an_adapterless_dialect_is_skipped_not_passed`), and
  > they write to `tmp_path` — a fixture planted to prove a test has teeth is
  > a fixture someone later mistakes for a real one.
  >
  > **DIVERGED — the tripwire as specified is unreachable at 2.9, so it is
  > declared rather than absolute.** This task says "a tripwire must assert
  > that the set of adapter-backed dialects equals `DIALECTS` — which is what
  > 2.13 finally flips." Taken literally that tripwire goes **red the moment
  > 2.9 registers the `otel_genai` adapter**, because 2.13 (not 2.9) is what
  > adds `otel_genai` to `DIALECTS`, and flipping it early fires §4.3's
  > "silence is a failure" rule against the ~17 scenarios 2.10–2.11 have not
  > rendered yet. But 2.9's done-when requires `make conformance` green, and
  > so does 2.10, 2.11 and 2.12. The plan as written has no green state
  > between 2.9 and 2.13.
  >
  > Resolved by giving the gap the shape `FIXTURES.md` §4.3 already gives a
  > scenario a dialect cannot render — **declared, with the declaration itself
  > under test** — rather than by dropping the tripwire or by leaving four
  > tasks red:
  > - `test_no_adapter_reads_a_dialect_the_corpus_does_not_account_for`
  >   asserts `adapter_backed() == set(DIALECTS) | set(DIALECTS_PENDING_CORPUS_COVERAGE)`.
  > - `DIALECTS_PENDING_CORPUS_COVERAGE` is `()` today, so **right now this is
  >   literally the specified equality**. It is not an exemption switch: two
  >   further tests forbid a stale entry and an entry that is also in
  >   `DIALECTS`, and its docstring says empty is the only correct long-term
  >   value.
  > - `test_every_declared_dialect_has_an_adapter_that_can_read_it` adds the
  >   other direction, which was never at risk of going red but is the half
  >   that keeps `DIALECTS` from claiming coverage nothing can check.
  >
  > **2.9 must add `"otel_genai"` to `DIALECTS_PENDING_CORPUS_COVERAGE` in the
  > same commit that registers the adapter, and 2.13 must delete the constant,
  > both tests that guard it, and the `conftest.py` header** — 2.13 already
  > says "retire 2.7's skipped-pending-adapter state and its tripwire in the
  > same change". If a future session finds itself adding an entry to that
  > tuple for any reason other than 2.9, the tripwire is doing its job and the
  > answer is to stop, not to append.
  >
  > Not touched, and worth knowing: `test_a_shuffled_trace_is_byte_identical_
  > to_its_ordered_twin` still names `dialects/openinference.jsonl` directly.
  > It is a determinism claim rather than an equivalence one, so it is outside
  > this task, but it will not extend to a second dialect on its own.

- [x] **2.8 Dialect-two renderings — the pairing set.** `[2a]` **NEVER CUT.**
  Transcribe from the 2.6 capture, in this order: `llm_tool_llm`,
  `tool_call_history_echo`, `parallel_tool_calls`. These three are the
  `call_result` relation — the structural relation dialects disagree about most
  and the one an adapter is uniquely able to get wrong (`ADAPTERS.md` §3) — and
  `llm_tool_llm` additionally carries the §4.2.1 `data` edge.
  **`FIXTURES.md` §5.1 is the rule: derive from observed output, never from a
  reading.** Every attribute in a rendering must be traceable to a line of the
  captured trace. Trim afterwards, and only by omission: *omission is fine,
  misstatement is not* — leaving out a key whose absence changes what the
  expected graph asserts is not simplification, it is a false claim about the
  dialect. Keep span id strings identical to the OpenInference renderings
  (`FIXTURES.md` §4.1) so equivalence tests the model and not id trivia.
  Do **not** touch any `expected/graph.json`. If a rendering cannot produce the
  existing expectation, that is 2.9's HALT, not an edit here.
  *Done when the three renderings exist under `dialects/otel_genai.jsonl`, each
  line is annotated in `scenario.md` (or a sibling note) with the captured
  record it came from, the suite reports them as skipped-pending-adapter per
  2.7, and `make check` is green.*

  > **HALT RESOLVED (2026-08-27) — C, in its narrow form, after §4 was
  > corrected. The record of the halt is kept below in full; the resolution and
  > what it cost are at the end of it.**
  >
  > **The halt as raised.** The two captured traces disagree about
  > `Payload.value` on every `llm` and `agent` span, and `FIXTURES.md` §4
  > compares payload values. Picking a way out is a spec conversation.
  >
  > ### What was checked
  >
  > Both files in `fixtures/captured/`, attribute by attribute, comparing
  > values rather than reading conventions. Four spans each, same shape
  > (agent → llm → tool → llm), the 2.6 matched pair.
  >
  > **TOOL spans agree byte-for-byte.** `gen_ai.tool.call.arguments` ==
  > `input.value` == `{"city": "Paris"}`; `gen_ai.tool.call.result` ==
  > `output.value` == `{"city": "Paris", "celsius": 18, "summary": "clear"}`.
  > Verified as string equality, not as "the same thing in different words".
  >
  > **LLM spans disagree, in both directions:**
  >
  > | | OpenInference | OTel GenAI |
  > |---|---|---|
  > | in | `input.value` = `{"messages":[…],"model":…,"tools":[…]}` | `gen_ai.input.messages` = `[{"role":"user","parts":[{"content":…,"type":"text"}]}]` |
  > | out | `output.value` = the whole provider response envelope | `gen_ai.output.messages` = `[{"role":"assistant","parts":[…],"finish_reason":…}]` |
  >
  > **The `agent` span disagrees too, which the collision report did not
  > predict.** OpenInference: `input.value` = `"What is the weather in Paris?
  > Use the tool."` with `input.mime_type` = `text/plain`. GenAI:
  > `gen_ai.input.messages` = the same text wrapped in the normalized message
  > array, no mime. So the clean line is **not** "only LLM spans diverge" — it
  > is **"only TOOL span payloads agree."** Restated that way, the corrected
  > blast radius over the whole corpus is **8 of 19 scenarios** carrying at
  > least one non-`absent` `llm`/`agent` payload: `llm_tool_llm`,
  > `tool_call_history_echo`, `parallel_tool_calls`, `parallel_tools`,
  > `declared_data_edge`, `shuffled_order`, `unpaired_tool_call`,
  > `redacted_payload`. The other 11 are immune — their `llm`/`agent` payloads
  > are `absent`, or they have only `tool` nodes.
  >
  > **A third divergence, unmentioned so far and worse than the other two:
  > `Payload.mime`.** OTel GenAI emits **no mime attribute of any kind** — the
  > only `*.type`-shaped key in the capture is `gen_ai.tool.type` =
  > `"function"`, which is the tool's type, not a content type. `canonical()`
  > erases only `Payload.raw`, so `mime` **is compared**, and a faithful
  > adapter reporting what the dialect said would set it to `None` on every
  > payload — including the tool payloads whose *values* agree. This one has
  > an adapter-level answer (derive the mime from the convention: these keys
  > are defined to be JSON), but it is a judgement the OpenInference adapter
  > never had to make, and it does not survive the `agent` span, where the two
  > dialects genuinely disagree `text/plain` vs `application/json`.
  >
  > ### Why this is not "the encoding is dialect-specific"
  >
  > That argument is what §4 already uses to erase `Payload.raw`, and it is the
  > obvious reach here. **It is false on the evidence.** These are not two
  > encodings of one fact. OpenInference records the **request envelope** —
  > messages *plus* model *plus* tool definitions *plus* invocation parameters,
  > and on the output side the entire provider response including
  > `system_fingerprint`, `usage`, `stop_reason`, `prompt_logprobs` and
  > vLLM-specific fields. GenAI records the **conversation**, normalized. One
  > strictly contains the other plus more. Re-encoding cannot get you from the
  > second to the first, because the information is not there.
  >
  > So the disagreement is about **content**, and the reason the model permits
  > it is that the model never said what the content should be. `SPEC.md` §3.3
  > defines `value` as *"parsed when mime is JSON, else str"* — a statement
  > about `raw`'s **parse**, and nothing about what the payload should
  > *contain*. Both adapters would be faithful. `FIXTURES.md` §4 comparing
  > `value` across dialects therefore asserts a cross-dialect property
  > `SPEC.md` never promised.
  >
  > **That is the finding, and it is a finding about the model, not the
  > adapter** — which is exactly the outcome `AGENT.md` says this phase exists
  > to produce, arriving one task earlier than the 2.9 HALT expected it.
  >
  > ### Three resolutions. NOT picked — this needs a human.
  >
  > Measured, not argued: each row is "how many of the 8 payload-carrying
  > scenarios still detect a perturbed payload value", by rebuilding every
  > OpenInference rendering with its payload strings altered and comparing
  > against the expectation **as it would be regenerated under that option**.
  >
  > | | expected graphs moved | `comparison.json` moved | detects a perturbed payload |
  > |---|---|---|---|
  > | today | — | — | **8 / 8** |
  > | **A** erase `Payload.value` | 0 (regenerated, all 19) | 0 | **0 / 8** |
  > | **B** normalize in adapters | **8** | 0 | 8 / 8 |
  > | **C** per-scenario declaration | 0 | 8 | **5 / 8** |
  >
  > **A — extend `canonical()`'s erasure from `Payload.raw` to
  > `Payload.value`,** on the "encoding is dialect-specific" argument.
  > *Moves:* no expected graph changes meaning, but all 19 are regenerated
  > without payload values. *Cost:* the measured 8→0. After it, `state` is the
  > only payload field compared, so `present` matches `present` whatever it
  > holds. It pays for a disagreement on `llm`/`agent` spans by **discarding
  > the agreement on `tool` spans** — the byte-for-byte match above, the single
  > strongest piece of cross-dialect evidence the corpus has. It also silently
  > disarms 2.7's own teeth test
  > (`test_a_second_rendering_that_disagrees_with_the_canonical_graph_fails`
  > perturbs a payload string; under A it goes green while asserting the
  > comparison has teeth). **And `FIXTURES.md` §4 forbids it in the sentence
  > immediately after the erasure list:** *"If two dialects genuinely cannot
  > agree on a compared field, that is a finding about the model, not a reason
  > to widen the erasure."* `AGENT.md`'s scope-of-run names weakening
  > `canonical()` as not permitted. Listed for completeness and because it is
  > the tempting one; recommending it would be the failure mode this phase is
  > designed to catch.
  >
  > **B — normalize messages in the adapters** so both emit a common message
  > shape in `Payload.value`. *Moves:* 8 expected graphs, plus a message schema
  > in `SPEC.md`. *Keeps all the teeth.* *Cost:* it decides `OPEN_QUESTIONS.md`
  > §5 (and brushes §2) by implementation, which `AGENT.md` names as the
  > failure those files exist to prevent. It is also not clearly **possible**
  > faithfully: to reach a normalized list from OpenInference's `output.value`
  > the adapter must parse a **provider** response envelope, so the surface
  > becomes one adapter per (dialect × provider) rather than per dialect, and
  > `Payload.value` stops being the parse of `raw` — contradicting `SPEC.md`
  > §3.3 — and becomes our re-rendering of it. Choosing a canonical message
  > schema is choosing what a message *is*; that is close to the
  > `CLAUDE.md` 1 line even if it stays structural. Large, and a spec
  > conversation before it is a patch.
  >
  > **C — per-scenario dialect-varying declarations,** extending the mechanism
  > `expected/comparison.json` already carries for node `name`, from node
  > fields to named payload fields on named nodes. *Moves:* 0 expected graphs,
  > 8 `comparison.json` files. *Keeps 5/8 of the teeth* — and is blind in
  > exactly the three scenarios (`parallel_tool_calls`, `parallel_tools`,
  > `unpaired_tool_call`) whose only present payloads sit on `llm`/`agent`
  > nodes, **per scenario and on the record**, rather than corpus-wide and
  > silently. §4 already blesses this mechanism and its rationale — *"so the
  > erasure is a reviewable fact in the corpus rather than a branch in the
  > comparison code"*. *Cost:* it is still a widening of the erasure, and the
  > §4 sentence quoted under A still applies to it; §4 sanctions the mechanism
  > for `name` specifically, not for payload values. Its honest advantage over
  > A is that it **preserves the finding instead of erasing it**: each
  > declaration is a written statement that these two dialects record different
  > facts here, which is the thing a Phase 4 freeze decision needs to read.
  >
  > **Considered and rejected: §4.3 coverage.** Declaring `otel_genai`
  > `renderable: false` for the 8 scenarios. `coverage.json` is all-or-nothing
  > per scenario — the same shortcoming 2.9's HALT text raises for the §4.2.1
  > `data` edge — so it would discard the three most valuable renderings
  > wholesale to express a disagreement about one field.
  >
  > ### A documentation gap found on the way
  >
  > `FIXTURES.md` §4's **Compared:** list names *"payload states and values"*
  > and does not mention `mime`; `canonical()` compares it anyway, since it
  > erases only `raw`. Whichever option is chosen, §4's two lists should be
  > made to agree with the code, because `mime` is one of the three fields in
  > dispute.
  >
  > ### What 2.9 will and will not find
  >
  > Checked early, because it changes what the 2.9 HALT is likely to be about:
  > **the §4.2.1 `data` edge is NOT at risk.** GenAI does carry a
  > message-granularity producer→consumer declaration — `gen_ai.input.messages`
  > on the second LLM span holds `{"role":"tool","parts":[{"type":
  > "tool_call_response","id":"chatcmpl-tool-ba26764988bf8aa9",…}]}`, and that
  > `id` is the tool call id. So `llm_tool_llm`'s `s2 -> s3` `data` edge is
  > derivable **explicitly** from dialect two, and the feared "canonical graph
  > contains an edge dialect two cannot produce" does not materialise. Two
  > dialects independently declaring this relation is also a second data point
  > for `OPEN_QUESTIONS.md` §7 and `PREDICTIONS.md` P3 — carried as evidence,
  > resolving neither.
  >
  > One thing 2.9 must still settle: `canonical()` compares `Edge.basis`, and
  > `basis` is a rule name written by the adapter. `llm_tool_llm` expects
  > `"tool_call_id in tool-result message"`. Both adapters must therefore emit
  > the **same** basis string for the same relation, which makes `basis`
  > cross-dialect vocabulary rather than adapter-local prose. Nothing in
  > `SPEC.md` or `ADAPTERS.md` currently says so.

  > ### Recorded, not acted on: three fields two independent dialects both model
  >
  > Read off the 2.6 GenAI attribute dump while checking the above. Written
  > here rather than in `OPEN_QUESTIONS.md`, which is a halt point and not the
  > agent's to edit, and rather than `PREDICTIONS.md`, which is read-only in
  > every phase. **No action taken and none owed by 2.9.**
  >
  > The test these three now meet: *what two independent dialects, written by
  > different people for different purposes, both bothered to model* is a
  > principled signal that a field is a property of the **domain** rather than
  > of one convention — which is a much better argument for normalizing it
  > than "a reviewer asked for it".
  >
  > - **Finish reason.** `gen_ai.response.finish_reasons` = `["tool_calls"]`
  >   then `["stop"]`; `llm.finish_reason` = `tool_calls` then `stop`. We model
  >   neither. `OPEN_QUESTIONS.md` §9 currently records it as available and
  >   deliberately unwired, on the explicit ground that *"two observations of
  >   one dialect from one instrumentor is still one dialect"*, and §9(c) names
  >   **the second adapter** as the thing to watch. It arrived. §9 also says in
  >   advance that a further vote *"should probably be answered in §5
  >   (normalize it into `Node.attributes`) rather than here (wire it into the
  >   pairing rule)"* — worth honouring, since the vote is again for the field
  >   existing, not for a second pairing rule.
  > - **The tool inventory.** `gen_ai.tool.definitions` /
  >   `llm.tools.*.tool.json_schema`. Unmapped in both. This is the
  >   *unused-affordance* gap `OPEN_QUESTIONS.md` §5 already records from the
  >   cold review — the graph can say "a tool ran" but not "these tools were on
  >   offer". Now two dialects, not one reviewer.
  > - **The provider.** `gen_ai.provider.name` = `openai` /
  >   `llm.system` = `openai`. Unmapped in both. Also already in §5, and the
  >   captured trace is again the case that makes it non-redundant: `model` is
  >   `openai/gpt-oss-120b` and `server.address` is
  >   `api.tokenfactory.nebius.com`, so provider, model and endpoint are three
  >   different facts.
  >
  > §5's own bar is the two-consumer test in §5(c), and this is not that — it
  > is a two-*dialect* test, which §5 does not currently name. Whether that
  > counts is §5's to decide, and 2.14 is where it should be argued, not here.

  > ### The resolution, and what 2.8 then did (2026-08-27)
  >
  > **Decided by the human: correct §4 first as its own statement of what
  > equivalence claims, then C on top. A is out** (0/8 detection is the corpus
  > losing the ability to notice payload regressions, and it disarms 2.7's own
  > teeth test — §4's prohibition happening wholesale). **B is out for now**
  > (it decides `OPEN_QUESTIONS.md` §2 and §5 by implementation; argue it on
  > merits at 2.14 or later, never because it made a test pass).
  >
  > **The question that changed C's cost, asked before implementing.** Does a
  > declaration suppress value comparison only in the cross-dialect claim, or
  > also in the single-dialect expected-graph check? **It was the broader
  > form.** `expected/graph.json` is itself in canonical form — `name`, which
  > `llm_tool_llm` declares dialect-varying, is simply *absent from the file* —
  > so any erasure removes the field from both sides and no dialect's value
  > stays pinned anywhere. C at 5/8 was C priced at the broader form.
  >
  > **Built as the narrow form, so the price is 0.** The two claims are now
  > separate tests (`FIXTURES.md` §4):
  > - *Claim 1, fidelity within a dialect* —
  >   `test_the_rendering_produces_its_scenario_s_canonical_graph`, comparing
  >   against `expected_graph_for(dialect)` with **nothing** set aside. A
  >   dialect whose declared payload differs supplies its own values in
  >   `expected/payloads/<dialect>.json`; one that agrees supplies no file; one
  >   that differs and **forgets** the file fails loudly. So every payload of
  >   every rendering is still pinned, and detection stays **8/8**.
  > - *Claim 2, equivalence across dialects* —
  >   `test_every_dialect_of_a_scenario_produces_the_same_canonical_graph`,
  >   the only place a declaration applies. Vacuous with one adapter, and
  >   written so it stops being vacuous the moment a second registers rather
  >   than needing to be remembered then;
  >   `test_the_cross_dialect_claim_is_reported_as_vacuous_while_it_is` keeps
  >   "0 scenarios compared" from rendering identically to "every scenario
  >   agrees".
  >
  > **`mime` rides along, per the decision, but per-selector rather than as a
  > fixed field set.** A declaration names the fields for each payload, and on
  > the **tool** spans it names `mime` **alone** — so the byte-for-byte value
  > agreement between the two captures stays a *tested* claim instead of being
  > erased alongside the disagreement. A fixed `(value, mime)` set would have
  > thrown away the corpus's strongest cross-dialect evidence to fix a problem
  > that evidence does not have.
  >
  > **`state` is not declarable, and cannot be made so.** Guarded twice:
  > `test_a_declaration_never_reaches_payload_state` fails the fixture, and
  > `canonical()` intersects with `DECLARABLE_PAYLOAD_FIELDS` so it would
  > refuse to honour such a declaration even if that test were deleted
  > (`test_a_declaration_that_names_state_cannot_erase_it`). `absent` ≠
  > `empty` ≠ `redacted` is the model's central honesty claim; two dialects
  > disagreeing about a payload's *state* must stay a finding.
  >
  > Five more hygiene tests: a declaration must carry a reason of substance
  > (§4.3's rule, same grounds), must name payloads that exist, must not cover
  > an `absent` payload, an override may only touch what was declared, and —
  > **`test_no_declaration_outlives_the_disagreement_that_earned_it`** — a
  > declaration on which every buildable dialect already agrees fails the
  > corpus. Stale is how an exemption becomes permanent.
  >
  > ### The three renderings
  >
  > Written after the mechanism, transcribed from
  > `fixtures/captured/genai_tool_call.jsonl`, with per-attribute provenance in
  > `<scenario>/otel_genai.notes.md` — beside `scenario.md`, **not** in
  > `dialects/`, because `scenarios()` treats every file there as a rendering
  > and a notes file would have become a phantom dialect skipping forever.
  > `test_only_dialect_files_live_under_dialects` now fails that.
  >
  > Each notes file lists the observed keys **deliberately omitted** and why.
  > The choice that most deserves review is named in them rather than left
  > implicit: `unmapped_attributes` is emitted **once per span**, the expected
  > graphs pin the count at 2 / 2 / 1, and so which spans carry an unmapped key
  > is a fixture-authoring choice made with that count in view. It is
  > precedented — the OpenInference specimens already omit `llm.system`,
  > `llm.tools.*.tool.json_schema`, `llm.invocation_parameters` and
  > `llm.token_count.prompt_details.cache_read`, all of which the OpenInference
  > capture carries — but precedent is not proof, and a reviewer should check
  > it.
  >
  > `parallel_tool_calls` has the weakest provenance of the three and says so
  > in its notes: the capture has **one** tool call and the scenario needs two,
  > so the *shape* of each `tool_call` part is transcribed and only the count
  > is not. The 2b fleet established parallel calls are routine, so a capture
  > that retires this note is obtainable.
  >
  > ### Two things carried to 2.9 rather than worked around here
  >
  > 1. **`Node.name`.** The GenAI convention names spans `{operation} {target}`
  >    — `chat demo-model`, `execute_tool lookup` — against the expected
  >    graphs' `llm.plan` / `tool.lookup`. `llm_tool_llm` already declares
  >    `name` dialect-varying ("dialects disagree about operation naming
  >    conventions and that disagreement is not interesting"), so it does not
  >    bite there. **`tool_call_history_echo` and `parallel_tool_calls` do
  >    not**, and it bites in both. This is **bookkeeping the corpus already
  >    decided**, not a model finding — but the fix is deleting `name` from two
  >    `expected/graph.json` files, which 2.8 forbids. 2.9 owns it.
  > 2. **A sentence in `tool_call_history_echo/scenario.md` is now true of one
  >    dialect only.** It says the echoed request id "surfaces in `unmapped`
  >    and is reported". In OpenInference it does — it is a flat attribute the
  >    adapter declines. In GenAI it sits **inside** `gen_ai.input.messages`,
  >    which *is* consumed, so nothing is left over to report. Codes and counts
  >    still match, which is all §4 compares. Flagged, not rewritten.
  >
  > ### One earlier concern, withdrawn
  >
  > 2.8's first record said `Edge.basis` would need to become cross-dialect
  > vocabulary. **Mostly not:** `CALL_BASIS`, `DATA_BASIS`, `PARENT_BASIS` and
  > the temporal bases are all set in `spanweave/build.py`, so every dialect
  > gets the same string for free. Only `link.basis` and `DeclaredDataEdge.basis`
  > come from an adapter, and neither is used by these three scenarios. It
  > remains a real gap for `span_links` (2.11) and for any dialect that names
  > both ends of a relation on one span — carried to 2.9 at that reduced size.

- [x] **2.9 The OTel GenAI adapter — and the first equivalence run.** `[2a]`
  Single file under `spanweave/adapters/`, registered; nothing else in the
  package touched (`ADAPTERS.md` §6 checklist applies in full). Requester ids
  taken only from what a span itself **produced** — history echoes do not pair
  (`SPEC.md` §4.4, and the defect that rule came from). All five payload states
  distinguished; `absent` ≠ `empty`; no inferred pairings, no inferred data
  edges, no invented ids; `unmapped` keys recorded; `raw` verbatim.
  The **first cross-dialect equivalence run** happens here, and it is the
  moment this whole phase exists for.
  *Done when the three 2.8 renderings each produce their scenario's
  **unmodified** `expected/graph.json`, `make conformance` is green, and the
  captured GenAI trace from 2.6 builds cleanly.*
  **HALT** — whatever the result. **Never weaken `canonical()` to make this
  pass** (`FIXTURES.md` §4): if a dialect fails equivalence, either the adapter
  is wrong or the model is, and finding out which is the entire value on offer.
  Two outcomes need a human before anything else happens:
  - **The graphs match.** That is the phase's central claim, first evidence.
    Hand back the diff-that-isn't.
  - **They do not.** Especially the §4.2.1 `data` edge: if GenAI declares no
    message-granularity producer→consumer relation, `llm_tool_llm`'s canonical
    graph contains an edge dialect two cannot produce, and `FIXTURES.md` §4.3's
    per-scenario `coverage.json` cannot express "this dialect renders the
    scenario but not that one edge". That is a gap in the equivalence rule, a
    spec conversation, and a candidate finding about the model.
  *Artifact for the decision:* `make conformance` output, and for any
  mismatch, the canonical-graph diff plus the captured lines that do or do not
  carry the contested attribute.

  > **HALT DISCHARGED (2026-08-27). `make conformance` is GREEN. The same run,
  > described by two independent instrumentors, produces one graph — and the
  > graphs are byte-identical, not merely equal after allowances. This is the
  > phase's central claim, evidenced.**
  >
  > *Bounded at 3.2: "after allowances" is doing real work for one field —
  > `Node.name` is declared dialect-varying by 16 of the 17 scenarios rendered
  > in both dialects, so it is not among what agrees. See 2.14's evidence
  > block.*
  >
  > ### `make conformance`
  >
  > ```
  > conformance dialects: declared=['openinference'] adapter-backed=['openinference', 'otel_genai']
  > conformance skipping nothing: every rendering has an adapter
  > 247 passed
  > ```
  >
  > `make check` green: `ruff`, `mypy --strict`, every gate, 783 tests.
  >
  > ### The diff-that-isn't
  >
  > ```
  > scenario                 claim 1 (per dialect)    claim 2 (cross-dialect)
  > llm_tool_llm             both dialects match      BYTE-IDENTICAL
  > parallel_tool_calls      both dialects match      BYTE-IDENTICAL
  > tool_call_history_echo   both dialects match      BYTE-IDENTICAL
  > ```
  >
  > Compared by `canonical_bytes`, not by `==`. Every node id, kind, operation,
  > timestamp, status, payload state, usage figure, edge (`src`, `dst`, `kind`,
  > `warrant`, `basis`), node ordering and diagnostic code-and-count agrees
  > across two dialects that share no attribute, no naming convention and no
  > mechanism for distinguishing a request from an echo.
  >
  > And the **captured** GenAI trace from 2.6 builds cleanly, auto-detected,
  > with the same seven edges the hand-authored reference scenario expects:
  >
  > ```
  > adapter: otel_genai
  > nodes:   agent(None), llm(openai/gpt-oss-120b), tool(get_weather), llm(openai/gpt-oss-120b)
  > edges:   call_result/explicit/tool_call_id
  >          data/explicit/'tool_call_id in tool-result message'
  >          parent/explicit ×3, temporal/derived ×2
  > ```
  >
  > Both captures detect to exactly one adapter each — no tie, no fallback.
  >
  > ### Three things recorded here as **evidence**, none of them a resolution
  >
  > **1. `SPEC.md` §4.2.1, confirmed on real telemetry in a second dialect.**
  > The outcome 2.9 was written to fear does not occur. OTel GenAI carries a
  > message-granularity producer→consumer declaration:
  > `gen_ai.input.messages` on the follow-up turn holds
  > `{"role":"tool","parts":[{"type":"tool_call_response","id":"chatcmpl-tool-ba26764988bf8aa9",…}]}`,
  > and that `id` is the tool call id. So `llm_tool_llm`'s `s2 → s3` `data`
  > edge is derivable **explicitly** in dialect two, and it was produced from
  > the **captured** trace, not only from a hand-authored specimen:
  >
  > ```
  > $ spanweave build fixtures/captured/genai_tool_call.jsonl
  > adapter: otel_genai
  > nodes:   agent(None), llm(openai/gpt-oss-120b), tool(get_weather), llm(openai/gpt-oss-120b)
  > edges:   call_result/explicit/tool_call_id
  >          data/explicit/'tool_call_id in tool-result message'
  >          parent/explicit ×3, temporal/derived ×2
  > ```
  >
  > Evidence that **`EdgeKind.data` generalizes past the dialect it was found
  > in**: two independent conventions, written by different people for
  > different purposes, both declare this relation, and both resolve to the
  > same span-level edge with the same warrant and the same basis. It bears on
  > `OPEN_QUESTIONS.md` §7 and `PREDICTIONS.md` P3 and **resolves neither**.
  > `PREDICTIONS.md` is read-only to the agent in every phase.
  >
  > **2. The mechanism disagreement — the stronger form of the same evidence.**
  > The two dialects do not merely spell the said-versus-shown distinction
  > differently; they draw it in different *places*. OpenInference separates
  > them by **attribute prefix** (`llm.output_messages.` vs
  > `llm.input_messages.`), so the discriminator is in the key. GenAI's two
  > lists have the identical shape and the discriminator is a **part `type`
  > inside the payload** (`tool_call` vs `tool_call_response`). `SPEC.md`
  > §4.4's rule — a requester id comes only from what the span itself produced
  > — survived unchanged, but it had to be **re-implemented against a different
  > mechanism** to survive.
  >
  > That distinction is the whole value of the run. **A rule that holds across
  > two mechanisms is general; across two spellings of one mechanism it is
  > lucky.** We now know which, and the corpus can show it: the same
  > `tool_call_history_echo` scenario catches the same defect in both dialects,
  > by two different readings.
  >
  > **3. C's real price, and the property that hid it.** Resolution C was
  > costed at 5/8 payload-regression detection at the 2.8 halt. That was **the
  > broad form's price, not C's**. `expected/graph.json` is *itself in
  > canonical form* — a declared erasure is not applied to it, it is simply
  > **absent from the file** — so erasing a field removes it from both sides of
  > the comparison and no dialect's value stays pinned anywhere. Built narrow,
  > with claim 1 and claim 2 as separate assertions and a per-dialect override
  > for what differs, **detection stays 8/8** and the declaration costs
  > nothing.
  >
  > Recorded because that same already-canonical property is exactly what makes
  > **proposal 2 look free**, and it is the first thing to check when proposal
  > 2 is argued at 2.14. An erasure that is baked into a fixture and an erasure
  > applied at comparison time are not interchangeable, and the difference was
  > invisible until it was priced.
  >
  > ### The corpus refused a declaration it had not earned
  >
  > Easy to skip, so recorded on its own. 2.8 declared payloads from the
  > *capture*; 2.9's first real run narrowed them from *evidence*. `mime`
  > turned out to agree on every `llm` payload and to differ **only** on the
  > `agent` span; the `tool` payloads agree entirely, mime and value both. The
  > staleness test was tightened from per-selector to **per-field** —
  > `test_no_declaration_outlives_the_disagreement_that_earned_it` — so a
  > `mime` riding along beside a genuinely varying `value` no longer passes
  > untested. It then **deleted two selectors and one field** that 2.8 had
  > added unnecessarily.
  >
  > The direction matters. A mechanism for declaring disagreements will tend to
  > accumulate them, because every declaration is locally reasonable and
  > nothing pushes back. This one shrank on contact with the first real
  > evidence, and it shrank *automatically* rather than because someone
  > remembered to check. That is the property to preserve if §4.4 is ever
  > extended.
  >
  > ### The one mismatch, and how it was closed — **proposal 1, approved**
  >
  > The first run had 4 failures, all one cause: `Node.name`. The GenAI
  > convention names spans `{operation} {target}`; the expected graphs carried
  > `llm.plan` / `tool.lookup` / `agent.run` from the OpenInference specimens.
  > Nothing else differed.
  >
  > `llm_tool_llm` did not fail, because it **already declares `name`
  > dialect-varying** — decided by a human at seed time, before any second
  > dialect existed, with the reasoning written into its `scenario.md`:
  > *"dialects disagree about operation naming conventions and that
  > disagreement is not interesting."* `tool_call_history_echo` and
  > `parallel_tool_calls` predate the *mechanism*, not the *decision*.
  >
  > **This is not weakening `canonical()` to pass, and a later reader should
  > not mistake it for that.** The rule against relaxing a comparison exists to
  > stop an expectation moving to accommodate an adapter. Here the expectation
  > did not move: a declaration taken once, on stated grounds, was extended to
  > two scenarios that were written before it could be expressed. That is
  > closing a gap in the corpus, not bending a rule — and it is why 2.8 refused
  > to do it silently and carried it to a human instead.
  >
  > Done: `expected/comparison.json` gains `erase: ["name"]` in both, `name` is
  > deleted from both `expected/graph.json`, and both `scenario.md` files gain
  > the cross-dialect note explaining why. `llm_tool_llm`'s own note was also
  > corrected — it still said *"the parsed `value` must agree, the encoding
  > need not"*, which §4.4 has since disproved.
  >
  > **Proposal 2 was NOT adopted, deliberately.** Applying `erase` to both
  > sides at comparison time is mechanically better and will probably win — but
  > it changes how *every* scenario is compared, and adopting it here would
  > have made a comparison-semantics change arrive as a side effect of a naming
  > mismatch. Same shape as resolution B last round. **It is carried to 2.14 as
  > its own proposal, to stand on its own argument.** The thing to check first
  > when arguing it is in the next section but one: `expected/graph.json` is
  > *itself already canonical*, which is exactly what makes proposal 2 look
  > free.
  >
  > ### The mime the dialect never wrote — **kept, and promoted to a rule**
  >
  > OTel GenAI emits **no content-type attribute anywhere**. The adapter
  > nonetheless reports `application/json` for `gen_ai.input.messages`,
  > `gen_ai.output.messages`, `gen_ai.tool.call.arguments` and
  > `gen_ai.tool.call.result`, and parses them, because the convention
  > **defines** those four as structured values that the OTLP exporter
  > serializes to strings only because span attributes cannot hold nested data.
  >
  > **Approved, and moved out of the adapter's docstring into `ADAPTERS.md`
  > §3**, where the next adapter author will meet it: *an adapter may report a
  > mime the dialect defines but does not emit*, under three conditions — the
  > convention states the structure normatively (an attribute typed "any" does
  > not qualify, and neither does "this instrumentor happens to emit JSON
  > here"); a parse failure stays honest (`present`, `value=None`, `raw` kept,
  > `payload_parse_failed`, never suppressed); and **it is said where a reader
  > of the fixture will find it**, not only where a reader of the adapter will.
  >
  > That third condition is now met three ways: the cross-dialect notes in each
  > affected `scenario.md`, the `reason` in each
  > `expected/comparison.json`, and a section in each
  > `otel_genai.notes.md`. Someone comparing two renderings can see why one has
  > a mime its dialect never wrote without opening any Python.
  >
  > The reason it is the right call rather than the bold one was measured, not
  > asserted: `mime=None` with `value` left as the source string makes tool
  > payloads that agree **byte for byte** in the two captured traces disagree
  > at model level, and the corpus then records a serialization artifact as a
  > finding about the model. That is the worse error, because it is the one
  > that looks like evidence.
  >
  > ### `Edge.basis` — the earlier concern, at its real size
  >
  > 2.8 withdrew most of this and the run confirms it: `PARENT_BASIS`,
  > `CALL_BASIS`, `DATA_BASIS` and the temporal bases all live in
  > `spanweave/build.py`, so both dialects emit identical basis strings without
  > coordinating. Only `SpanLink.basis` and `DeclaredDataEdge.basis` come from
  > an adapter. Neither is exercised by these three scenarios, so **nothing is
  > blocked** — but it stays a genuine spec gap of the O1 kind (the model
  > permits an answer; no document commits to one), and it becomes live at
  > **2.11** (`span_links`). Proposal, not adopted: `SPEC.md` should say that
  > `basis` is cross-dialect vocabulary — two adapters describing the same
  > relation must emit the same string — and name the strings the library
  > itself uses, so a third dialect has something to conform to rather than a
  > convention to guess at. Brought here as 2.9 was asked to; deciding it is a
  > spec conversation.
  >
  > ### Also done here, per `ADAPTERS.md` §5.4
  >
  > `tests/test_otel_genai.py`, 33 tests for the quirks the shared corpus
  > cannot cover — chiefly that a `tool_call` part in the **input** list must
  > not pair, asserted directly and again against the captured trace (exactly
  > one requester and one fulfiller across four real spans).
  >
  > `DIALECTS_PENDING_CORPUS_COVERAGE` now names `otel_genai`, as 2.7's record
  > said 2.9 must. 2.13 deletes it along with the rest of the transitional
  > mechanism.

- [x] **2.10 Dialect-two renderings — the degenerate set.** `[2a]` **NEVER
  CUT** (`ROADMAP.md`: this is where dialect conventions actually diverge and
  where `PREDICTIONS.md` P2 gets tested; cutting these keeps the pleasant half
  of the corpus and discards the informative half).
  `missing_payloads`, `empty_payload`, `redacted_payload`,
  `unpaired_tool_call`, `orphan_parent`, `clock_skew`, `unknown_kind`,
  `malformed_payload_json`, `duplicate_span_ids`, `cyclic_parents`,
  `shuffled_order`. Dialects broadly agree about spans, parents and tool calls;
  they diverge sharply about how they signal **absence**, truncation,
  redaction, errors and unmatched calls — so expect adapter work here, not just
  transcription. In particular GenAI's redaction and truncation conventions are
  a different set from OpenInference's `__REDACTED__`; claim only what the
  instrumentor actually says, and where it says nothing, emit nothing and
  record the gap.
  §5.1 still binds: a degenerate rendering is still derived from observed
  output, degraded by hand — not imagined.
  *Done when every scenario above has an `otel_genai` rendering producing its
  unmodified canonical graph (or its `expected/error.json` with the same type
  and code), `make conformance` is green, and any scenario the dialect
  genuinely cannot express carries a `coverage.json` entry with a reason that
  has been checked against observed output rather than assumed
  (`FIXTURES.md` §4.3 — a `renderable: false` is an invitation to check the
  reason, not a settled fact).*
  > **STATE: DONE. All 11 covered, 1 new scenario added, both halts
  > discharged.** Worked over two sittings; the intermediate state is kept
  > below because the halts are the record. 9 rendered, 2 declared
  > unrenderable, and `unknown_kind` rendered after Halt B was decided.
  > `make check` and `make conformance` green.
  >
  > ### What landed
  >
  > | Scenario | `otel_genai` | Declared |
  > |---|---|---|
  > | `missing_payloads` | rendered | `name` |
  > | `empty_payload` | rendered | `name`; `s0.inputs` `mime`+`value` |
  > | `unpaired_tool_call` | rendered | `name`; `s1.inputs`/`s1.outputs` `value` |
  > | `orphan_parent` | rendered | `name` |
  > | `clock_skew` | rendered | `name` |
  > | `malformed_payload_json` | rendered | `name` |
  > | `duplicate_span_ids` | rendered | — (no graph; §4.2 refusal, same type + code) |
  > | `shuffled_order` | rendered | `name`; the five `llm_tool_llm` payloads |
  > | `redacted_payload` | **`coverage.json`** | — |
  > | `cyclic_parents` | **`coverage.json`** | — |
  > | `unknown_kind` | rendered *(after Halt B)* | `name`; `attributes.reported_kind` |
  > | `unset_and_error_status` | **new scenario**, both dialects | `name` |
  >
  > `name` is declared everywhere for the reason settled at 2.9: the OTel GenAI
  > convention *prescribes* the span name as `<operation> <target>`, so a
  > faithful rendering cannot reuse OpenInference's. That is the mechanism
  > working, not a new decision.
  >
  > Only **three** payload disagreements exist across the whole degenerate set,
  > and two of them are the envelope-vs-conversation finding §4.4 already
  > records. The third (`empty_payload`) is new and is a better statement of
  > the same thing: both dialects reach `state: empty` — the field the scenario
  > exists to assert, and the one no declaration may ever set aside — but they
  > cannot agree on how emptiness is *spelled*. OpenInference's `input.value`
  > is a free string with its own mime, so it can say `""` at `text/plain`;
  > `gen_ai.tool.call.arguments` is a structured value, and `""` there is not
  > valid JSON, so the dialect's only spelling of empty is an empty container.
  > Every other degenerate payload agrees in both `value` and `mime`.
  >
  > Two renderings are worth reading for what they prove rather than what they
  > cover. `malformed_payload_json` is the test that `ADAPTERS.md` §3's
  > "a mime the dialect defines but does not emit" rule **degrades honestly**:
  > both dialects reach `present` / `application/json` / `value: null` by
  > opposite routes — one is told the mime, the other asserts it from the
  > convention — and the adapter-asserted mime does not suppress
  > `payload_parse_failed`. And `shuffled_order`'s rendering is
  > `llm_tool_llm`'s, byte for byte, reordered; the determinism pair is now
  > parametrized over every dialect that renders both halves, with a guard that
  > fails if one side gains a dialect the other lacks.
  >
  > ### Two `coverage.json` declarations, both with the check that produced them
  >
  > `FIXTURES.md` §4.3 makes a `renderable: false` *an invitation to check the
  > reason*, so both reasons name what was checked rather than what was
  > believed.
  >
  > - **`redacted_payload`.** The scenario asserts `Payload.redacted` and the
  >   state is its whole subject. Checked three ways: the convention defines no
  >   redaction sentinel; the captured GenAI trace contains no marker of any
  >   kind; and the mechanism the dialect *does* have — opt-in content capture
  >   — omits the attribute entirely, which is `absent`, a different state and
  >   a different fact. The dialect can say "nothing was recorded"; it cannot
  >   say "something was recorded and withheld."
  > - **`cyclic_parents`.** Not the cycle — that is envelope and expressible —
  >   but `kind: chain`, which no mapped operation produces.
  >
  > ### A finding that lands on 2.11, recorded here because it was found here
  >
  > `gen_ai.operation.name` was read from the convention's own registry rather
  > than from memory: `opentelemetry-semantic-conventions` **0.65b0**, the
  > version 2.6's capture ran under, defines **nine** values. The adapter maps
  > **seven**. The two it does not:
  >
  > - **`retrieval`** — maps to `NodeKind.retriever` on its face. 2.11's note
  >   says `retriever_and_embedding` is "the most likely `coverage.json`
  >   candidate, since GenAI's operation vocabulary may not name a retriever —
  >   check that against observed output before declaring it." **It does name
  >   one.** That check is now done and the answer is no coverage entry.
  > - **`invoke_workflow`** — a real candidate for `chain` (`SPEC.md` §3.2: "a
  >   composite step with no more specific kind"), and the reason
  >   `cyclic_parents` is declared unrenderable rather than rendered. Not
  >   mapped, deliberately: `OPERATIONS`' own docstring says the unconfirmed
  >   entries are "claims awaiting a capture", and no capture contains one.
  >
  > Neither is acted on here. Both are adapter changes that belong to 2.11, and
  > mapping either on a reading is what `FIXTURES.md` §5.1 forbids.
  >
  > ### Finding F6 closed: `unset_and_error_status`
  >
  > Handoff item 2. The corpus was **18 of 18** tool spans `ok`; of 20 real
  > tool spans, **none** was (19 `unset`, 1 `error`). A consumer computing a
  > success rate against the corpus alone reads a confident zero against real
  > telemetry, and nothing inside the corpus could see it — only a consumer
  > pointed at real traces could, which is what 2b was for.
  >
  > New scenario, rendered in both dialects, every fact transcribed from an
  > observed span: `UNSET` on an agent span and on a tool span from both
  > captures; `ERROR` + `status_message` + an **absent** output from the 2b
  > fleet's `05_failing_flight`, the only observed error span either dialect
  > has produced. It is also the corpus's first `status_note` anywhere.
  >
  > **The first draft was wrong and the check caught it.** It gave one span no
  > `status` key at all, to separate "stated unset" from "not stated". Checked
  > before committing: across all **68** captured records, every one carries a
  > `status` key. Omitting it would have been a claim that an exporter drops
  > the field — §5.1's "omitting a key whose absence changes what the expected
  > graph asserts is a misstatement, not a simplification". The span now states
  > `UNSET`, and the absent-key branch stays where it was already tested, in
  > both adapters' unit tests. Recorded because the draft was plausible and
  > only the capture said no.
  >
  > The gap is now un-reintroducable rather than merely fixed:
  > `test_the_corpus_is_not_uniformly_ok` fails if every tool span in the
  > corpus is `ok` again. Watched failing (`{'error','unset'} <= {'ok'}`) with
  > the scenario removed.
  >
  > Two other tests were added for gaps this task exposed:
  > `test_a_declared_unrenderable_dialect_really_has_no_rendering` (until 2.13
  > flips `DIALECTS`, nothing would notice a scenario that both renders a
  > dialect and declares it unrenderable — a contradiction worse than either
  > half), and the twinning guard on the shuffle pair.
  >
  > ---
  >
  > ## HALT A — O1 / finding F5, settled by evidence
  >
  > Handoff item 1. Rendered `unpaired_tool_call` in `otel_genai`, built both,
  > and inspected the output. Full working in
  > `fixtures/conformance/unpaired_tool_call/otel_genai.notes.md`.
  >
  > **(a) From the graph alone, can the requested tool be named? No — in
  > neither dialect, and they agree exactly.** Both emit the same diagnostic,
  > identical but for the adapter id:
  >
  > ```json
  > {"code": "unpaired_call", "level": "warning", "node_id": "s1",
  >  "source": "call_a",
  >  "message": "call 'call_a' was requested and no span in this input fulfils it; no edge is invented"}
  > ```
  >
  > The call **id** appears three times — `source`, inside `message`, and as
  > the `node_id` of the asking span. The tool **name** appears zero times. A
  > call that never ran has no node, so `operation` — where a tool's name lives
  > (`SPEC.md` §3.2) — has nowhere to be.
  >
  > One asymmetry, and it is the kind that makes a consumer look portable when
  > it is not: OpenInference *mentions* the name in a second diagnostic, because
  > `unmapped_attributes` lists the key
  > `llm.output_messages.0.message.tool_calls.0.tool_call.function.name` — as a
  > **key**, never a value. GenAI carries it inside the payload and names it in
  > no diagnostic at all. A consumer scraping names out of diagnostic key lists
  > works against dialect one and finds nothing in dialect two.
  >
  > **(b) The payload paths, and they are not the same path.** They disagree on
  > the container type at the first step:
  >
  > | | to the name | to the id |
  > |---|---|---|
  > | OpenInference | `outputs.value["choices"][i]["message"]["tool_calls"][j]["function"]["name"]` | same, `[j]["id"]` |
  > | OTel GenAI | `outputs.value[i]["parts"][j]["name"]`, where `parts[j]["type"] == "tool_call"` | same, `[j]["id"]` |
  >
  > `outputs.value` is a **dict** in one and a **list** in the other. No prefix
  > in common, so no single expression reaches both.
  >
  > **(c) Confident zero, or loud failure? Loud — and this partly refutes O1 as
  > written.** Measured in both directions on the two graphs this scenario
  > builds:
  >
  > | consumer | vs `openinference` | vs `otel_genai` |
  > |---|---|---|
  > | OpenInference path, direct indexing | `['lookup']` | `TypeError: list indices must be integers or slices, not str` |
  > | OpenInference path, defensive `.get()` chain | `['lookup']` | `AttributeError: 'list' object has no attribute 'get'` |
  > | OTel GenAI path, direct indexing | `TypeError: string indices must be integers, not 'str'` | `['lookup']` |
  >
  > O1 says the walk "does not raise — it reports a confident zero,
  > indistinguishable from 'there were none.'" **It raises**, and so does the
  > usual defensive idiom, because `.get` on a list is an `AttributeError`
  > rather than a miss.
  >
  > The confident zero is still real, but its **mechanism is the consumer's own
  > error handling, not a silent shape mismatch**. Any `try/except` around the
  > walk — and there will be one, since trace payloads are untrusted input
  > (`SECURITY.md`) — converts the loud failure into an empty result;
  > `examples/fleet_aggregate` already wraps at trace granularity for exactly
  > that reason. So the gap is **weaker than O1 claimed and still a gap**: a
  > portable consumer *can* detect this today, if it chooses not to swallow it.
  > That is a materially different fact from "cannot detect it at all", and it
  > is the agent's job to say so rather than confirm the prediction it was
  > handed.
  >
  > ### The remedy, proposed and NOT implemented
  >
  > **Proposal 1 — enrich `Diagnostic.source` on `unpaired_call` (and
  > `unpaired_result`) from a bare id to `{call_id, operation}`.** Recommended.
  >
  > Exact surface, and it is smaller than it looks:
  >
  > | Where | Today | Proposed |
  > |---|---|---|
  > | `Diagnostic.source` (`spanweave/model.py`) | `JsonValue`; carries `"call_a"` | unchanged type; carries `{"call_id": "call_a", "operation": "lookup"}` |
  > | `NormalizedSpan` (`spanweave/seam.py`) | `call_ids: tuple[str, ...]` | + `call_names: Mapping[str, str]` — id → the name the dialect gave it, absent when it gave none |
  > | `spanweave/build.py` ~L338 | `source=call_id` | `source={"call_id": …, "operation": …}` |
  > | both adapters | — | OpenInference reads `llm.output_messages.N.message.tool_calls.M.tool_call.function.name`, already observed and today only reported as unmapped; GenAI reads the `tool_call` part's `name`, already parsed by `_ids_of_type` |
  > | `SPEC.md` §3.7 | says nothing about `source`'s shape | states it per code |
  >
  > What it is **not**: no new `NodeKind`, no new `EdgeKind`, no new `Payload`
  > state, no new warrant, no new diagnostic code — so no `AGENT.md` model-change
  > halt point. `Diagnostic.sort_key` is `(code, node_id, message)` and does not
  > touch `source`, so ordering and determinism are unaffected. Neutrality is
  > unaffected: `operation` is the dialect's own word for the tool, the same
  > word a fulfilled call already puts on its node.
  >
  > What it **costs**, stated rather than buried: `source` changes from a
  > string to an object for two codes. `schema_version` is unfrozen and this is
  > exactly the kind of change Phase 2 exists to find, but it is a
  > public-contract change and belongs in 2.14's model-change record either way.
  > It also puts a *name from a payload* into a diagnostic, and `SPEC.md` §3.7's
  > standing rule is that a diagnostic carries keys, not payload content — the
  > argument for the exception is that a tool's name is the dialect's own
  > identifier for the call, not the call's content, and it is already carried
  > verbatim on every *fulfilled* call's node. That distinction is a human's to
  > accept or reject.
  >
  > **Proposal 2 — do nothing to the model; document the two paths.** Ship a
  > table like (b) above in `ADAPTERS.md`, so a consumer that must walk knows
  > it is walking one dialect. Cheapest, changes no contract, and leaves the
  > gap exactly where it is: every consumer re-implements the pairing logic the
  > library already did, per dialect.
  >
  > **Proposal 3 — a node for the call that never ran.** Named only to be
  > visibly rejected: it invents a span the telemetry never recorded, and
  > `unknown` nodes exist for records we *saw*. It would put the tool name in
  > `operation` at the cost of the losslessness invariant meaning something
  > different.
  >
  > O1 is an observation in `PREDICTIONS.md`, which the agent may not edit. The
  > evidence above is offered for a human to resolve it with; nothing here
  > resolves it.
  >
  > ### HALT A DISCHARGED (2026-08-27) — accepted, implemented, two conditions met
  >
  > **Proposal 1 taken.** `Diagnostic.source` on `unpaired_call` and
  > `unpaired_result` is now `{"call_id", "operation"}`; `SPEC.md` §3.7 states
  > `source`'s shape per code where it previously stated none. The result, and
  > it is the point of the whole exercise — **byte-identical in both
  > dialects**:
  >
  > ```json
  > {"code": "unpaired_call",   "node_id": "s1", "source": {"call_id": "call_a", "operation": "lookup"}}
  > {"code": "unpaired_result", "node_id": "s2", "source": {"call_id": "call_b", "operation": "other"}}
  > ```
  >
  > No payload is walked, so the consumer is one line and the same line in
  > every dialect. `examples/fleet_aggregate`'s `unfulfilled_calls.by_tool`
  > was empty for a whole phase and now reconciles against the same total as
  > `by_model`. Its `UNATTRIBUTED_CALLS` limit is retired to a quotation; what
  > replaced it is narrower and still honest — a dialect that states an id and
  > no name buckets under `(dialect named no tool)` rather than shrinking the
  > total, because a rollup that silently drops what it cannot label is F5 one
  > layer up.
  >
  > **The 2b tripwire fired, which is worth more than the fix.**
  > `test_the_boundary_the_task_exists_to_find_is_in_the_output` asserted
  > `by_tool == {}` and said in as many words that "a change that made
  > `by_tool` answerable should fail this test and be read at 2.4, not pass
  > silently." It failed exactly that way. Renamed to
  > `..._the_task_found_is_now_closed` and rewritten to assert the new state,
  > with the old text quoted in its docstring — a tripwire edited into
  > agreement leaves no evidence it ever meant anything.
  >
  > **Condition: the §3.7 exception, written as reasoning not a carve-out.**
  > Keys-not-content exists because values are already in `RawRecord` and
  > duplicating payload content is unnecessary exposure. A tool **name** is not
  > content in that sense — it is the identity of an operation, the same
  > category as `Node.operation`, which the model already normalizes and puts
  > on every node. The library is not exposing something new; it is putting a
  > value it already publishes on a *fulfilled* call in the one place a call
  > that never ran can be seen at all. That argument is in §3.7, not a
  > footnote.
  >
  > **Condition: the refutation recorded first.** Done above, and the exact
  > wording for `PREDICTIONS.md` O1 was handed to the human — the agent may not
  > edit that file.
  >
  > **What the suite did not have, and now does.** Nothing anywhere asserted
  > `source` for either code; the change broke **zero** tests, which is its own
  > finding. Added: five builder tests (including that two spans naming one
  > call differently yield `operation: null` rather than a pick, in both input
  > orders), five per adapter — each with the echo case, because reading a
  > name off an echoed `tool_call` part is the `tool_call_history_echo` defect
  > one level down — a cross-dialect equality assertion in the corpus, and
  > `test_the_unpaired_codes_emit_the_object_the_spec_declares`, which reads
  > §3.7's table and fails if the library and the document disagree. That last
  > one exists because `source` is typed `JsonValue`: the type permits
  > anything, so the contract lives entirely in a table, and an unchecked table
  > is how `FIXTURES.md` §4's Compared list went wrong three times.
  >
  > The contract change is recorded at **2.14** and classified **shape**.
  >
  > ---
  >
  > ## HALT B — `unknown_kind`, and a compared field with no declaration mechanism
  >
  > Not anticipated by the task, and the reason 2.10's box is unchecked.
  >
  > `unknown_kind` renders cleanly in `otel_genai`. Built against the honest
  > rendering — `gen_ai.operation.name: "invoke_workflow"`, a value the
  > convention really defines (0.65b0) and the adapter really does not map —
  > the two canonical graphs differ by **exactly one line**:
  >
  > ```diff
  >    "attributes": {
  > -    "reported_kind": "GUARDRAIL"
  > +    "reported_kind": "invoke_workflow"
  >    },
  > ```
  >
  > Everything else agrees: `kind: unknown`, the `unknown_span_kind` diagnostic,
  > the parent edge, both payloads, the node order.
  >
  > **The disagreement is not a defect. It is unavoidable and it is correct.**
  > `reported_kind` is by definition the *dialect's own verbatim token* for a
  > kind we could not map. Two dialects necessarily spell it differently —
  > that is the same fact `name` records, one level down — and an adapter that
  > made them agree would be lying about what it read.
  >
  > **The corpus cannot say so.** `canonical()` compares `Node.attributes`;
  > `erase` declares whole node fields; §4.4 declares `value`/`mime` on named
  > payloads. Nothing declares one key of one node's `attributes`. Worse,
  > `attributes` is **not in `FIXTURES.md` §4's Compared list at all** — it is
  > compared by implementation and unmentioned by the contract, which is
  > precisely the position `mime` was in for two phases before the §4.4 rewrite
  > caught it. So this is a second instance of a known defect class, found the
  > same way: by a second dialect arriving.
  >
  > **Not decided here, on the standing instruction.** Adopting a
  > comparison-semantics change because it unblocked a rendering is the shape
  > refused twice already (resolution B at 2.8, proposal 2 at 2.9). Three
  > options, with what each moves:
  >
  > 1. **Extend `erase` to dotted paths** — `erase: ["attributes.reported_kind"]`.
  >    Narrowest, and the exact analogue of §4.4's per-field payload
  >    declaration. Moves: `canonical()`'s `_without` gains one level of path
  >    walking; `FIXTURES.md` §4 gains `attributes` in the Compared list and a
  >    sentence in "erased where declared"; one `comparison.json`. Nothing else
  >    in the corpus changes, because `attributes` holds only `model` elsewhere
  >    and every dialect agrees on that.
  > 2. **`erase: ["attributes"]` on this scenario alone** — uses the mechanism
  >    exactly as built, changes no code, one line of fixture. Costs the
  >    pinning of `reported_kind` in *both* claims for this scenario (`erase`
  >    applies to both, unlike a §4.4 declaration). Mitigated but not covered:
  >    both adapters already assert it in unit tests
  >    (`test_openinference.py:240`, `test_otel_genai.py:107`). This is the
  >    coarse form of exactly the thing §4.4 was carefully made fine-grained
  >    about, which is the argument against it.
  > 3. **Declare `unknown_kind` unrenderable in `otel_genai`.** Rejected as
  >    dishonest and named so it is visibly rejected: the dialect renders the
  >    scenario perfectly. §4.3 means "the dialect cannot say this"; using it
  >    for "the corpus cannot compare this" would make the two
  >    indistinguishable, which is the ambiguity §4.2/§4.3 were split apart to
  >    remove.
  >
  > Recommendation: **1**.
  >
  > ### §4 CORRECTED FIRST (2026-08-27), on its own terms
  >
  > Done, in its own commit, with **no rendering riding on it**:
  > `Node.attributes` is now named in `FIXTURES.md` §4's Compared list, because
  > it *is* compared. That was the third time a comparison rule asserted
  > something the contract never stated — `mime` for two phases, `attributes`
  > for three, and §3.3-vs-§4 on payload contents was the same shape, the one
  > that forced §4.4 into existence.
  >
  > It is not a drafting slip and it was not fixed as one. A field is added to
  > the model, `canonical()` keeps it because keeping is the **default**, and
  > prose is not where anyone looks — so the gap surfaces only when a second
  > dialect happens to disagree on that field, which is phases of latency for a
  > contract error. So the list is now exact rather than illustrative, written
  > in the model's own field names, and checked in both directions:
  > `test_the_compared_list_names_every_field_that_is_compared` (watched
  > failing on `attributes`) and
  > `test_the_compared_list_names_nothing_that_is_erased` (watched failing on
  > `provenance`, which is the easy mistake to make while fixing the first).
  >
  > **The three options above are unchanged by the correction, and that is the
  > useful outcome.** Option 1 is now an extension of a contract that already
  > admits `attributes` is compared, rather than the thing that reveals it; it
  > can be argued on whether a dotted path is the right granularity, which is
  > the actual question. Option 2's cost is now visible in the document too:
  > erasing `attributes` wholesale would set aside a field §4 explicitly lists
  > as compared, on a scenario where only one **key** of it disagrees. Option 3
  > stays rejected for the same reason.
  >
  > ### HALT B DISCHARGED (2026-08-27) — option 1, dotted-path erase
  >
  > Taken on the stated grounds: whole-field erase sets aside a field §4 now
  > explicitly lists as compared, over **one key** disagreeing, and the corpus
  > has consistently preferred narrow-and-declared over broad-and-silent —
  > `coverage.json`, §4.4's per-field payload declaration, and resolution C at
  > 2.8 all took that shape. This is the same instrument one level finer.
  >
  > `FIXTURES.md` **§4.5** is the mechanism's home. `unknown_kind` declares
  > `erase: ["attributes.reported_kind", "name"]` and is now rendered; its
  > `otel_genai` span carries `gen_ai.operation.name: "invoke_workflow"`, read
  > from the convention's own registry at the version 2.6's capture ran under,
  > and genuinely unmapped.
  >
  > **Condition: per-key, and it expires.** The staleness test that deleted
  > 2.8's tool-span selectors now covers `erase` too, per entry — a whole
  > field or a single dotted key — and compares the **unerased** graphs, since
  > an erased one cannot show a disagreement by definition. Watched failing by
  > adding `operation` to the list, on which both dialects agree. A second
  > guard fails a declaration naming a key no node carries (watched failing on
  > `attributes.nonexistent`).
  >
  > **Condition: the scenario states why agreement is impossible.**
  > `unknown_kind/scenario.md` now says it in those terms — `reported_kind` is
  > by definition the dialect's verbatim token, so two vocabularies
  > necessarily produce two strings and an adapter making them agree would be
  > lying about what it read. §4.5 makes that a *requirement* of the
  > mechanism, not a courtesy: a reader must be able to tell "this field means
  > different things by construction" from "nobody has reconciled these yet",
  > because only the second is a bug.
  >
  > **The whitelist is the load-bearing part of the implementation.** Only
  > `attributes` may have a key erased, fixed in code and never read from a
  > fixture. `inputs` and `outputs` are mappings too, and a dotted erasure
  > reaching one would route straight around §4.4's guarantee that a payload's
  > `state` can never be set aside. The narrow mechanism must not be reachable
  > through the broad one; guarded where the fixture is read **and** where the
  > erasure happens, because the second is what holds if the first is deleted.
  > Watched refusing `inputs.state`.
  >
  > The rendering is **not** committed. Writing it would leave the corpus with
  > a file no test can compare, which is the silent rot `DIALECTS_PENDING…` and
  > the skip machinery exist to prevent. The two-line specimen is reproduced
  > above in full; recreating it costs nothing.

- [x] **2.11 Dialect-two renderings — the structural set.** `[2a]`
  **CUT 2 IF THE PHASE SLIPS** (`ROADMAP.md`). Render in this order — the
  reverse of the cut order, so the tail is what gets dropped:
  `single_tool_call`, `parallel_tools`, `nested_agents`,
  `retriever_and_embedding`, `span_links`, `declared_data_edge`.
  Cut from the end. Each cut costs a little coverage and no principle; record
  each one here with the reason. Two notes: `retriever_and_embedding` is the
  most likely `coverage.json` candidate, since GenAI's operation vocabulary may
  not name a retriever — check that against observed output before declaring
  it. And cutting `declared_data_edge` no longer removes §4.2.1 from dialect
  two, because `llm_tool_llm` carries the same edge and is never cut.
  *Done when each rendered scenario produces its unmodified canonical graph,
  `make conformance` is green, and every scenario not rendered is recorded here
  as cut, with its reason, or declared in `coverage.json`.*

  > **DONE. 4 of 6 rendered, 2 declared, nothing cut.** `single_tool_call`,
  > `parallel_tools`, `nested_agents` and `declared_data_edge` produce their
  > unmodified canonical graphs. `retriever_and_embedding` and `span_links`
  > carry `coverage.json`. `make check` and `make conformance` green.
  >
  > | Scenario | `otel_genai` | Declared |
  > |---|---|---|
  > | `single_tool_call` | rendered | `name` only |
  > | `parallel_tools` | rendered | `name`; `s0.inputs` `mime`+`value` |
  > | `nested_agents` | rendered | `name` only |
  > | `declared_data_edge` | rendered | `name`; `s2.inputs`/`s2.outputs` `value` |
  > | `retriever_and_embedding` | **`coverage.json`** | — |
  > | `span_links` | **`coverage.json`** | — |
  >
  > ### 2.11's own prediction, checked and refuted
  >
  > This task said `retriever_and_embedding` was "the most likely
  > `coverage.json` candidate, since GenAI's operation vocabulary may not name
  > a retriever — check that against observed output before declaring it."
  >
  > **It names one.** The convention defines `retrieval`, described as
  > "Retrieval operation such as ... Search Vector Store", and the adapter now
  > maps it to `NodeKind.retriever`. Its absence was an inconsistency rather
  > than an abstention: `embeddings`, `text_completion`, `generate_content` and
  > `create_agent` were all already mapped on exactly the same evidence, so a
  > real `retrieval` span became `unknown` while a real `embeddings` span did
  > not. That is a live defect for a user, fixed here with a unit test.
  >
  > **And the scenario is still unrenderable, for a reason nobody predicted:**
  > its `s0` is a **chain**. The prediction checked the interesting spans and
  > missed the parent.
  >
  > ### The finding this task actually produced: `chain` costs three scenarios
  >
  > `gen_ai.operation.name` has nine values; the adapter now maps eight. The
  > ninth is `invoke_workflow`, and **not mapping it is a decision**, recorded
  > in the adapter as `UNMAPPED_BY_DECISION` rather than left as an absence.
  >
  > Every other entry is a **name match** — the convention's word and the
  > model's word denote the same thing, and the convention's own description
  > confirms it. `invoke_workflow` is described only as "Invoke GenAI
  > workflow". Mapping it to `chain` (`SPEC.md` §3.2: "a composite step with no
  > more specific kind") would be a **judgement about what a workflow is**, and
  > `AGENT.md` is explicit that reaching for an inference is the signal to
  > stop.
  >
  > **The price, stated rather than buried.** Three scenarios pin `kind: chain`
  > and are now all declared unrenderable in this dialect:
  > `cyclic_parents` (2.10), `retriever_and_embedding`, `span_links`. The last
  > is the expensive one: it is the **only** scenario in the corpus carrying an
  > `EdgeKind.link`, so `link` edges are untested across dialects — and with
  > them the one adapter-supplied `basis` string this dialect would produce.
  >
  > **One captured GenAI trace containing an `invoke_workflow` span retires all
  > three declarations at once.** That makes it the highest-value capture
  > outstanding, and it is carried to 2.14 as such. It is a capture, not a
  > decision: §4.3 exists so a gap like this is reviewable rather than argued.
  >
  > ### `Edge.basis` as cross-dialect vocabulary — carried from 2.9, and the
  > ### answer is that the corpus cannot currently test it
  >
  > The concern was that `basis` is a free string, is **compared** by
  > `canonical()`, and is adapter-supplied in two places — so two adapters
  > could describe the same relation with two different strings and fail
  > equivalence on vocabulary rather than on substance. Measured across all
  > sixteen renderings now in the corpus:
  >
  > | `basis` | Produced by | Cross-dialect |
  > |---|---|---|
  > | `span.parent_span_id` | builder | agrees, structurally |
  > | `tool_call_id` | builder | agrees, structurally |
  > | `tool_call_id in tool-result message` | builder | agrees, structurally |
  > | `sibling start_time ordering` (+ the tie-break variant) | builder | agrees, structurally |
  > | `span.link` | **adapter** (`SpanLink.basis`) | **never compared** — `span_links` is unrenderable |
  > | *declared data edge* | **adapter** (`DeclaredDataEdge.basis`) | **never compared** — `otel_genai` produces none; it uses `received_call_ids`, whose basis the builder supplies |
  >
  > So every `basis` the corpus actually compares is the builder's, and
  > agreement is structural rather than lucky — the builder has one string per
  > rule and no dialect can reach it. **Both adapter-supplied bases are
  > invisible to the cross-dialect claim**, one because its only scenario
  > cannot be rendered and one because the second dialect takes a different
  > route to the same edge.
  >
  > That is a sharper answer than "it might be a problem": the risk is real,
  > entirely confined to the two adapter-supplied cases, and **currently
  > unmeasurable by construction**. Both adapters happen to write `span.link`,
  > which is right in both because it names an OTel record-level field rather
  > than a dialect attribute — but nothing in the corpus checks that, and
  > nothing states the vocabulary. Carried to 2.14 with this shape, not as an
  > open worry.

- [x] **2.12 `detect()` for both adapters.** `[2a]` **CUT 1 IF THE PHASE
  SLIPS** — the first thing to go, and the only item in this phase that can be
  removed without losing information (`ROADMAP.md`: it is ergonomics and yields
  **zero** evidence about whether the model is general).
  Harden `detect()` on both adapters per `SPEC.md` §6.1: pure, non-raising,
  keyed on distinctive markers (`gen_ai.*` vs `openinference.*`), honestly
  scored. Prove selection is unambiguous over the whole corpus and both
  captured traces, and that registration order decides nothing.
  *Done when `spanweave build` with no `--adapter` picks the right adapter for
  every rendering in `fixtures/conformance/` and both files in
  `fixtures/captured/`, two registries built in opposite orders agree, and a
  deliberately ambiguous input raises `adapter_ambiguous` rather than falling
  back.*
  **If cut:** make `--adapter` required, update `SPEC.md` §6.1 and `--help` to
  say so, move detection to Phase 4, and record the deferral here. `SPEC.md`
  §6.1's hard-error behavior is what makes that deferral safe.

  > **DONE — not cut.** `tests/test_detection.py`. Over **all 42** trace files
  > the project holds (40 corpus renderings + both captured traces), selection
  > is correct with **zero** mismatches, and the two registries built in
  > opposite orders agree on every one.
  >
  > The registry mechanics were already proved with stubs in
  > `tests/test_adapters.py`, and that is the right level — the mechanism
  > should be testable without a dialect. What stubs cannot say is whether
  > `openinference.*` and `gen_ai.*` are genuinely distinctive, which is a
  > claim about the real world and needs the real corpus.
  >
  > **The assertion is stronger than "the right one wins": the other adapter
  > scores exactly `0.0` on every input.** A margin would be enough for
  > selection and not enough for confidence — two adapters both above the floor
  > means the markers overlap, and the third dialect turns that overlap into a
  > tie. The file list is derived from the tree, so a rendering added tomorrow
  > is checked tomorrow rather than whenever someone remembers this file.
  >
  > ### The hardening this task actually found
  >
  > Both adapters wrapped `detect()` in `try: ... except Exception: return
  > 0.0`, marked `pragma: no cover`. It reads as defensive and is **the exact
  > inverse of what this module is for**: it converts a broken adapter into a
  > *confident* `0.0` and hands the input to whichever adapter is still
  > standing — a plausible graph from possibly the wrong dialect, which is the
  > silent failure `spanweave/adapters/__init__.py`'s own docstring says it
  > exists to prevent. Meanwhile the registry already turns an escaping
  > exception into `adapter_detect_failed` **naming the adapter**, which is the
  > loud outcome. The catch was suppressing the good path.
  >
  > Both removed. `detect()` is now total by construction — every branch is an
  > `isinstance` guard — and that is asserted rather than asserted-about:
  > fourteen cases per adapter of input no instrumentor would produce
  > (`None`, a bare string, `attributes: null`, an integer attribute key, no
  > `attributes` key at all) all return `0.0` without raising.
  >
  > Also pinned: detection is idempotent and does not mutate the sample
  > (purity is easy to lose to a `pop` or a cached flag and impossible to
  > notice downstream); a record carrying **both** dialects' markers raises
  > `adapter_ambiguous` naming both and pointing at `--adapter`; an input in
  > neither raises `adapter_unconfident`.
  >
  > One structural note. `duplicate_span_ids` is skipped in the *build* check
  > and deliberately **not** in the detection checks: detection succeeds there
  > and the refusal happens afterwards, in the builder. Conflating them would
  > let a detection regression hide behind an expected error. The refusal set
  > is read from the corpus (`expected/error.json`), not named.

- [x] **2.13 Close the corpus: flip `DIALECTS`.** `[2a]` **NEVER CUT** — this
  is the task that makes coverage un-rottable.
  Add `otel_genai` to `tests/conformance.py:DIALECTS`. That single line turns
  on `FIXTURES.md` §4.3's "silence is a failure" rule for the whole corpus:
  every scenario must now either render the dialect or declare in
  `coverage.json` that it cannot, with a reason. Retire 2.7's
  skipped-pending-adapter state and its tripwire in the same change — a
  transitional mechanism left in place outlives its transition.
  Also here, because they are the same closure: update
  `fixtures/conformance/README.md` (which still says `declared_data_edge` has
  no rendering — stale since the cold review) and `ADAPTERS.md` where it speaks
  of one adapter, and teach `review_corpus.py` about `error.json` and
  `coverage.json`, which it predates and currently misreports as missing
  expectations (recorded at the end of Phase 1).
  *Done when `make conformance` is green with both dialects in `DIALECTS`, no
  scenario is silent for either dialect, the transitional skip is gone, and
  `review_corpus.py` reports no false findings against the corpus as it stands.*

  > **DONE.** `DIALECTS = ("openinference", "otel_genai")`. `make conformance`
  > green at 419 tests, and the header now reads:
  >
  > ```
  > conformance dialects: declared=['openinference', 'otel_genai'] adapter-backed=['openinference', 'otel_genai']
  > conformance coverage: 21 scenarios, renderings: openinference 21, otel_genai 17; 17 compared across dialects; 4 declared unrenderable
  > conformance skipping nothing: every rendering has an adapter
  > ```
  >
  > 17 of 21 scenarios are now compared **across** dialects rather than
  > round-tripped through one. The four declared are `redacted_payload` (no
  > redaction marker in the dialect) and the three `chain` scenarios
  > (`cyclic_parents`, `retriever_and_embedding`, `span_links`).
  >
  > ### The exemption is deleted, not emptied
  >
  > `DIALECTS_PENDING_CORPUS_COVERAGE` held exactly one dialect between 2.7 and
  > here. It is **removed from the source**, and the tripwire that read
  > `adapter_backed() == set(DIALECTS) | set(PENDING)` is now a plain equality.
  > Emptying it would have left an invitation: an exemption list that exists is
  > an exemption list somebody uses. The circumstance that justified it — four
  > consecutive tasks each requiring green while a tripwire was necessarily red
  > — was a **plan defect**, acknowledged as such at 2.7, and is not a
  > circumstance that recurs. A third adapter lands with its renderings or it
  > does not land, and `ADAPTERS.md` §5 now says so.
  >
  > ### `tests/conftest.py` kept, and re-scoped rather than deleted
  >
  > The task said to retire 2.7's mechanism. Its *state* and its *tripwire* are
  > gone. The pytest **header** is not, and the reasoning is worth recording
  > because it cuts against the instruction: what it reports stopped being a
  > transition and became standing coverage. It now prints scenario and
  > rendering counts, how many are compared across dialects, and how many
  > declarations stand — so "the cross-dialect claim" cannot quietly decay into
  > a claim about one dialect without the number moving. The skip branch
  > survives with its wording inverted: it now says a skip is **a defect, not a
  > transition**, because a skip that reads like a known condition is a skip
  > nobody investigates.
  >
  > ### `review_corpus.py` — it was reporting a false finding, and worse
  >
  > It called `duplicate_span_ids` "no expected/graph.json" and exited 1. That
  > scenario's expectation *is* the refusal, and a review aid that flags a
  > correct fixture trains a reviewer to ignore it — which is the only failure
  > mode a review aid really has. It now reads `error.json` and prints the
  > refusal as the expectation, and refuses the two states `FIXTURES.md` §1
  > forbids (both files, or neither).
  >
  > Added beyond the task, because closing the corpus made it necessary: the
  > tool now prints **what each scenario has SET ASIDE** — `coverage.json`
  > reasons, every `erase` entry, every declared payload selector with its
  > reason, and any per-dialect override file — under the heading *the
  > expectation is only as strong as what it still compares*. Before this, a
  > reviewer signing a scenario off saw the graph and not the erasures that
  > make it green, which is precisely backwards now that there are eleven
  > declarations across the corpus. It also prints which dialects each scenario
  > is rendered in, and fails loudly if its own `DEGENERATE` list names a
  > scenario that no longer exists (it did: `malformed_record`, a phantom, and
  > it was missing `tool_call_history_echo`).
  >
  > `fixtures/conformance/README.md` and `ADAPTERS.md` updated. The README's
  > stale claim that `declared_data_edge` has no rendering is not merely
  > deleted — it is kept as a **warning**, since being wrong about one's own
  > dialect for a whole phase is the thing §4.3 exists to catch. `ADAPTERS.md`
  > §5 gains what the second dialect actually cost, as a worked expectation for
  > the third: **coverage is lost to kind vocabulary, not to attribute shape.**
  > Payload spellings differ everywhere and are handled by declaration; a kind
  > your dialect cannot name takes whole scenarios with it, and often not the
  > ones the scenario was written for.

- [x] **2.14 Phase 2 exit: the model-change record.** `[2a]`
  Record **every** model change either pressure forced, with its cause — the
  2b findings from 2.4, anything 2.9–2.11 forced, and every deferral. That
  record is the evidence for or against the model's generality and it is the
  direct input to the Phase 4 freeze decision; a change absorbed without being
  written down is a change the freeze will be made blind to. Note explicitly
  which changes were **shape** and which **operational**, using
  `PREDICTIONS.md`'s binding test and not a widened version of it.
  **Carried here from 2.9, to be argued on its own merits and not adopted as a
  side effect:** *apply a declared `erase` to both sides of the comparison
  rather than requiring the field to be absent from `expected/graph.json`.* It
  was proposal 2 at 2.9's halt, and it was **not** taken there because it
  changes how every scenario is compared and would have arrived as a side
  effect of a naming mismatch. The thing to check first is recorded at 2.9:
  `expected/graph.json` is *itself already canonical*, which is exactly what
  makes the change look free, and is the same property that made resolution C
  look like it cost 5/8 when the narrow form costs 0.
  Also carried: **`Edge.basis` as cross-dialect vocabulary** (2.9), which goes
  live at 2.11.

  > **Public-contract change already made, for this record (2.10).**
  > `Diagnostic.source` changed from a bare id string to
  > `{"call_id", "operation"}` on **two** codes, `unpaired_call` and
  > `unpaired_result`, and `SPEC.md` §3.7 now states `source`'s shape per code
  > where it stated none.
  >
  > **Classify it as SHAPE**, by `PREDICTIONS.md`'s binding test and not a
  > widened version of it: `NormalizedSpan` gained a field (`call_names`), and
  > a serialized value changed type. No `NodeKind`, `EdgeKind`, warrant,
  > `Payload` state or `Diagnostic` code was added, so it was not an
  > `AGENT.md` halt point — but "not a halt point" is not "not a shape change",
  > and Phase 3's gate is zero shape changes, which is precisely why it is
  > written here rather than left to be inferred from a diff.
  >
  > **Cause:** finding F5 / `PREDICTIONS.md` O1, settled at 2.10 against two
  > dialects rather than argued from one. This is the phase working as
  > intended: pre-`0.9.x` the change is cheap, and the freeze is the thing that
  > stops it being cheap later.
  >
  > **Also for the record, the `unpaired_result` half is redundant** — that
  > call has a fulfilling span whose node already carries the name. It was
  > changed anyway so both codes share one `source` shape; a consumer that had
  > to branch on which code it was holding to know whether `source` was a
  > string or an object would be a worse contract than one redundant field.
  > Recorded so the freeze decision reads a deliberate choice rather than an
  > overreach.

  *Done when both dialects produce identical canonical graphs for every
  scenario still in scope, P5 is resolved in `PREDICTIONS.md`, every model
  change and every cut is recorded here with its cause, and `make check` and
  `make conformance` are green.*
  **HALT — Phase 2 exit, for human review, as 1.9 was.** Do not start Phase 3.
  *Artifact for the decision:* the model-change record, `make conformance`
  output over both dialects, and the "same run, two instrumentors, one graph"
  comparison for `llm_tool_llm`.

  > # Phase 2 exit record
  >
  > `make check` green (1155 tests, 2 skipped), `make conformance` green,
  > `make gates` green, `review_corpus.py` exit 0.
  >
  > ## The headline: `spanweave/model.py` was not touched
  >
  > `git diff` over the whole of Phase 2 shows **zero** lines changed in
  > `spanweave/model.py` and **zero** in `schema/findings…` — no `NodeKind`, no
  > `EdgeKind`, no `Payload` state, no warrant, no `Diagnostic` code, no query
  > primitive. Phase 2's job was to break the model with a second dialect and an
  > adversarial consumer, and the model held. Six files under `spanweave/`
  > changed at all: the new adapter, its registration, the public `__init__`,
  > `build.py`, `seam.py`, and the OpenInference adapter.
  >
  > That is the input the Phase 4 freeze decision needs, and it is worth being
  > precise about what it does and does not say. It says the **types** were
  > general enough. It does not say the corpus proved them so: four scenarios
  > are declared unrenderable in dialect two, and what they would have tested is
  > listed below rather than counted as passing.
  >
  > ## The evidence
  >
  > 17 of 21 scenarios are rendered in both dialects. Compared by
  > `canonical_bytes`, not `==`:
  >
  > ```
  > 16 byte-identical canonical graphs
  >  1 identical refusal (duplicate_span_ids: DuplicateNodeIdError / duplicate_node_id in both)
  >  0 differ
  > ```
  >
  > The same run, described by two instrumentors that share **no attribute
  > name, no naming convention, no message shape and no mechanism for telling a
  > request from an echo**, produces one graph. `llm_tool_llm` is the reference
  > case and was the first evidence, at 2.9.
  >
  > > ### The bound on that figure, added at 3.2 — read it beside the number
  > >
  > > **The 16 do not include `Node.name`.** `canonical()` compares `name`, and
  > > **16 of those 17 scenarios declare it dialect-varying** in
  > > `expected/comparison.json`; the 17th is `duplicate_span_ids`, the
  > > identical refusal, which produces no graph to compare. So `name` has
  > > **never been compared across dialects, in any scenario, at any point in
  > > this project** — measured at `TASKS.md` 3.2 and rowed in `CONTRACTS.md`.
  > >
  > > This does not weaken the claim; it states it. `name` is the field two
  > > instrumentors are *least* likely to agree on, which is precisely why §4.4's
  > > declaration mechanism exists — one dialect names a span
  > > `ChatCompletion`, the other `chat gpt-oss-120b`, and neither is wrong. The
  > > sentence above is true of everything the corpus compares. It is simply not
  > > a claim about `name`, and a reader quoting "16 byte-identical canonical
  > > graphs" without this would overstate it.
  > >
  > > **The `phase-2-exit` tag message carries the unqualified form.** It was
  > > written before this was measured and is **superseded by this block**; the
  > > tag is an annotated object and published history, and it is not rewritten.
  > > A reader who finds the tag first should be led here.
  >
  > ## Model changes, with cause and classification
  >
  > Two, and only one touches a public contract.
  >
  > ### 1. `Diagnostic.source` on `unpaired_call` / `unpaired_result` — SHAPE
  >
  > From `"call_a"` to `{"call_id": "call_a", "operation": "lookup"}`, plus
  > `NormalizedSpan.call_names` at the seam and a `source`-per-code table in
  > `SPEC.md` §3.7.
  >
  > **Cause:** finding F5 (2b) → `PREDICTIONS.md` O1 → settled at 2.10 against
  > two dialects. A requested call that nothing fulfils has no node, so
  > `operation` — where a tool's name lives — had nowhere to be, and a fleet
  > could say *which model* left a call unfulfilled but not *what it asked for*.
  >
  > **Classification: SHAPE**, by the binding test and not a widened version of
  > it. `NormalizedSpan` gained a field and a serialized value changed type.
  > It was **not** an `AGENT.md` halt point — nothing in the model's closed
  > enums moved — and "not a halt point" is not "not a shape change". Phase 3's
  > gate is zero shape changes; this one is spent in Phase 2, which is where it
  > belongs.
  >
  > **What O1's own classification got wrong, and it is the more useful
  > finding.** O1 was filed as a *spec gap* — "the model could express this
  > today, nothing populates it, no document asks for one" — and that was right
  > about the remedy's **shape** and wrong about its **cost**.
  > `Diagnostic.source` is typed `JsonValue`, which made the change look free;
  > it was not, because `source` is **serialized**. **A spec gap can carry a
  > shape cost when the permissive field is a serialized one.** That is a hole
  > in the category as written at 2.4, and it is now recorded in
  > `PREDICTIONS.md` by the human who wrote the category.
  >
  > ### 2. Public API: the `SPEC.md` §3.10 error types — additive
  >
  > `SpanweaveError` and its three subclasses are now exported (F4). Purely
  > additive: it made a written spec rule followable that was previously
  > impossible to obey through the public API. Not a shape change.
  >
  > ### And one adapter change worth recording as a defect, not a decision
  >
  > `retrieval` was missing from the OTel GenAI operation table while
  > `embeddings`, `text_completion`, `generate_content` and `create_agent` were
  > present on identical evidence — so a real `retrieval` span became `unknown`
  > and a real `embeddings` span did not. Found at 2.11 by checking a prediction
  > against the convention's registry rather than from memory. Fixed. No model
  > change.
  >
  > ## The pattern behind three of this phase's findings
  >
  > The human asked for this to be named once rather than filed three times, and
  > it is the most transferable thing Phase 2 produced.
  >
  > | Found | What was relied on | What said so |
  > |---|---|---|
  > | 2.8 | `canonical()` compares `Payload.mime` | nothing — absent from `FIXTURES.md` §4's Compared list for two phases |
  > | 2.10 | `canonical()` compares `Node.attributes` | nothing — absent for three |
  > | 2.10 | `Diagnostic.source` carries a specific shape per code | nothing — no test asserted it for either unpaired code, so changing its type broke **zero** tests |
  >
  > All three are the same species: **a property the project depends on, that no
  > document states and no test asserts.** Not one was a drafting slip. Each has
  > the same mechanism — the *permissive* default won. `canonical()` keeps a
  > field unless told otherwise, so a field added to the model is silently
  > compared. `JsonValue` permits any shape, so a diagnostic's payload is
  > silently unconstrained. In every case the code was right and the contract
  > was absent, which is why nothing was red.
  >
  > And they share a discovery mechanism: **the second dialect**. Each surfaced
  > only when two independent implementations had to agree on it. That is
  > exactly the value 2a was bought for, and it is the argument for a *third*
  > dialect being worth more than its coverage — a defect of this species is
  > invisible to any number of tests written by one author against one dialect.
  >
  > Both `FIXTURES.md` lists are now checked in both directions
  > (`test_the_compared_list_names_every_field_that_is_compared`,
  > `..._nothing_that_is_erased`), and §3.7's table is checked against what the
  > library emits. A fourth instance goes red rather than waiting for a dialect.
  >
  > **For the freeze decision:** before freezing `schema_version`, audit every
  > serialized field typed permissively (`JsonValue`, free `str`) for a stated
  > contract and an asserting test. `Diagnostic.source` was one.
  > `Edge.basis` — a free `str`, compared, adapter-supplied — is the next one,
  > and it is unresolved (below).
  >
  > ## Carried forward, not done
  >
  > ### Apply a declared `erase` to both sides of the comparison
  >
  > Proposal 2 at 2.9's halt; **still not adopted**, deliberately, twice. Today
  > an `erase` entry is honoured by stripping the built graph, and
  > `expected/graph.json` simply does not carry the field — so an erasure
  > applies to **both** claims, and a declared field is pinned nowhere. A §4.4
  > payload declaration is narrower: it applies to claim 2 only, and claim 1
  > still pins the value through `expected/payloads/<dialect>.json`.
  >
  > The asymmetry is real and it grew this phase: `erase` now carries `name` on
  > eleven scenarios and one `attributes` key. The thing to check first, from
  > 2.9: `expected/graph.json` is **itself already canonical**, which is exactly
  > what makes the change look free — and is the same property that made
  > resolution C look like it cost 5/8 detection when the narrow form cost 0.
  >
  > It has not been taken because both times it arrived as a side effect of
  > something else (a naming mismatch, then an `attributes` key). It should be
  > argued on its own, in its own change, with nothing riding on it — the way
  > §4's Compared list was corrected at Halt B.
  >
  > ### `Edge.basis` as cross-dialect vocabulary — measured, and worse than open
  >
  > Carried from 2.9, answered at 2.11, and the answer is sharper than the
  > question. `basis` is a free `str`, is **compared** by `canonical()`, and is
  > adapter-supplied in exactly two places. Across all 38 renderings:
  >
  > - Every `basis` the corpus actually compares is the **builder's** — one
  >   string per rule, unreachable from any dialect. Agreement is structural,
  >   not lucky.
  > - **Both** adapter-supplied bases are invisible to the cross-dialect claim.
  >   `SpanLink.basis` because its only scenario (`span_links`) is declared
  >   unrenderable; `DeclaredDataEdge.basis` because `otel_genai` produces none
  >   — it reaches the same edge through `received_call_ids`, whose basis the
  >   builder supplies.
  >
  > So the risk is real, entirely confined to two cases, and **currently
  > unmeasurable by construction**. Both adapters happen to write `span.link`,
  > which is right in both because it names an OTel record-level field rather
  > than a dialect attribute — and nothing checks that, and no document states
  > the vocabulary. This is the same species as the three findings above, caught
  > before it bit. It belongs to Phase 4 alongside the freeze audit.
  >
  > ## Declared coverage, and what it costs
  >
  > Four scenarios are declared unrenderable in `otel_genai`. Nothing was
  > **cut** — 2.11 and 2.12 both survived the phase intact.
  >
  > | Scenario | Reason | What is untested in dialect two |
  > |---|---|---|
  > | `redacted_payload` | the dialect defines no redaction marker; turning content capture off yields `absent`, a different state | `PayloadState.redacted` |
  > | `cyclic_parents` | pins `kind: chain` | `ordering_cycle` |
  > | `retriever_and_embedding` | pins `kind: chain` on the parent | `NodeKind.chain` |
  > | `span_links` | pins `kind: chain` | **`EdgeKind.link`**, and the only adapter-supplied `basis` |
  >
  > **Three of the four are one missing kind.** Nothing in
  > `gen_ai.operation.name` maps to `chain`, because the one candidate,
  > `invoke_workflow`, is described by the convention only as "Invoke GenAI
  > workflow" — mapping it to "a composite step with no more specific kind"
  > would be a judgement rather than the name match every other entry is, and
  > `AGENT.md` says reaching for an inference is the signal to stop. It is
  > recorded in the adapter as `UNMAPPED_BY_DECISION`, not left as an absence.
  >
  > **The single highest-value action outstanding is a capture, not a
  > decision:** one GenAI trace containing an `invoke_workflow` span retires
  > three declarations at once and restores `EdgeKind.link` to the cross-dialect
  > claim. A capture is a human act (`AGENT.md` halt point).
  >
  > **The generalizable lesson, now in `ADAPTERS.md` §5:** coverage is lost to
  > **kind vocabulary**, not to attribute shape. Payload spellings differ
  > everywhere and are absorbed by declaration; a kind a dialect cannot name
  > takes whole scenarios with it — and often not the ones the scenario was
  > written for. `retriever_and_embedding` was predicted to fail on the
  > *retriever*; it fails on its `chain` parent.
  >
  > ## Recorded, deliberately not acted on
  >
  > - **Three attributes both dialects model and this library does not**
  >   (2.6): finish reason (`gen_ai.response.finish_reasons` /
  >   `llm.finish_reason`), the tool inventory (`gen_ai.tool.definitions` /
  >   `llm.tools.*`), and the provider (`gen_ai.provider.name` / `llm.system`).
  >   *What two independent dialects both bothered to model* is a principled
  >   test for what belongs in normalization, and three candidates now meet it.
  >   `OPEN_QUESTIONS.md` §5 and §9 — evidence for, not resolution of.
  > - **§4.2.1 `data` edges generalize** (2.9): confirmed on real telemetry in a
  >   second dialect, and by a *different mechanism* — OpenInference separates
  >   said-from-shown by attribute prefix, GenAI by a part `type` inside the
  >   payload. A rule that holds across two mechanisms is general; across two
  >   spellings of one mechanism it is lucky. Evidence for `OPEN_QUESTIONS.md`
  >   §7 and `PREDICTIONS.md` P3, resolving neither.
  > - **F7** (nothing states which diagnostic codes are node-scoped) is flagged
  >   for re-reading under the spec-gap category, which did not exist when it
  >   was classified operational.
  >
  > ## Definition of done
  >
  > - [x] Both dialects produce identical canonical graphs for every scenario in
  >       scope — 16 byte-identical, 1 identical refusal, 0 differ. **Bounded at
  >       3.2: not including `Node.name`, which 16 of the 17 declare
  >       dialect-varying — see the block under *The evidence*.**
  > - [x] P5 resolved in `PREDICTIONS.md` (REFUTED, scoped) by the human at 2.4;
  >       O1 amended by the human at 2.10. Neither file touched by the agent.
  > - [x] Every model change recorded above with its cause and classification.
  > - [x] Every declaration recorded with what it costs. Nothing cut.
  > - [x] `make check` and `make conformance` green.

## Phase 2 follow-up — post-exit  *(Phase 2 is tagged `phase-2-exit`)*

Phase 2 is complete, tagged and merged. This section holds only work that
2.14's exit record **named as outstanding**, and that is not Phase 3: it
confirms nothing, packages nothing, and does not touch the Phase 3 shape gate.
Starting Phase 3 is still a separate decision.

- [x] **2.15 Capture harness — the workflow shape.** `[2a]`
  **HALT: the capture itself is human-run and was not run here.**

  2.14 named the highest-value outstanding action, and it is a **capture, not a
  decision**. Three of the four scenarios declared unrenderable in `otel_genai`
  are one missing kind: nothing in `gen_ai.operation.name` maps to `chain`,
  because the one candidate, `invoke_workflow`, is described by the convention
  only as "Invoke GenAI workflow" — mapping it to "a composite step with no
  more specific kind" is a judgement, not a name match, and `AGENT.md` says
  reaching for an inference is the signal to stop. One captured GenAI trace
  containing an `invoke_workflow` span retires all three declarations, and one
  of the three, `span_links`, carries the corpus's **only** `EdgeKind.link`.

  **Done-when:** `make capture ARGS="--backend genai --shape workflow"` can
  produce such a trace, is verified against stub spans, and refuses to
  certify itself.

  > **What was built.** A capture **shape** (`capture/backends.py`,
  > `CaptureShape`), which is a new axis and deliberately not a new backend: a
  > backend chooses the SDK and the instrumentor, a shape chooses what the run
  > *does*. They are separate because the reference conversation must not move
  > — 2.6's matched pair is matched on same model, same prompt, same tool
  > inventory, differing only in the instrumentor, so anything that varies the
  > conversation has to be a different capture rather than a change to that one.
  > `reference` is the default and unchanged; `workflow` is scoped to the
  > `genai` backend and refuses the others, because emitting a GenAI operation
  > into an OpenInference trace would produce a mixed-dialect file no adapter
  > reads honestly.
  >
  > ```
  > invoke_workflow paris.brief          <- emitted by capture/backends.py
  > ├── invoke_agent agent.run           <- emitted by capture/backends.py
  > │   ├── chat <model>                 <- the instrumentor
  > │   ├── execute_tool get_weather     <- emitted by capture/backends.py
  > │   └── chat <model>                 <- the instrumentor
  > └── invoke_agent agent.run           <- emitted here; LINKS to the first leg
  >     ├── chat <model>
  >     ├── execute_tool get_population
  >     └── chat <model>
  > ```
  >
  > **Where the `invoke_workflow` span comes from — the disclosure asked for,
  > and the answer that was expected.** From `capture/backends.py`, not from
  > the instrumentor. An instrumentor wraps **SDK calls** and a workflow is not
  > one, so nothing would record it; only the `chat` spans are the
  > instrumentor's, exactly as the existing two provenance files already say of
  > `invoke_agent` and `execute_tool`. What the conventions supply is the
  > **vocabulary**: `invoke_workflow` is one of the nine normative
  > `gen_ai.operation.name` values and `gen_ai.workflow.name` is a defined
  > attribute, so the span is **convention-named and harness-emitted** — the
  > same standing `execute_tool` has, and one step further from `invoke_agent`,
  > whose attributes are a judgement call. Emitting it is transcription.
  > Nothing else is attached: the conventions describe no message content for a
  > workflow, and inventing some would be the judgement this shape exists to
  > avoid. The resulting node has `absent` payloads, which is the honest state.
  >
  > **Which span carries the link, and whose link it is.** The second leg's
  > `invoke_agent` span, naming the first leg's. OTel span links are a
  > record-level field of the **span data model** — identical in both dialects,
  > read by both adapters, and convention-defined in that sense; it is why
  > `span_links` says the blocker there was never the links. But **which** spans
  > are linked, and what the link means, is defined by neither GenAI nor
  > OpenInference. That part is **ours**, and it says so in this harness's own
  > namespace (`spanweave.capture.link = previous_workflow_leg`) rather than
  > under a `gen_ai.` name it has no right to — the same posture as
  > `spanweave.capture.note` on the fleet's spans. The relation asserted is the
  > weakest one true of the run: *this leg ran after that one, inside this
  > workflow*. Not "this leg consumed that leg's output": the legs are
  > independent conversations, and a link claiming otherwise would be a small
  > fabrication in a file whose entire value is containing only what happened.
  >
  > **The link is in-trace only, and that is a stated limit rather than an
  > oversight.** `span_links` also carries a link into *another* trace.
  > Producing one here would mean naming a span in a trace this run did not
  > produce, which is invention. Whoever renders that scenario from this capture
  > must say which half the capture shows and which half remains hand-authored.
  >
  > **Provenance: its own, and not shared with the matched pair.** Asked
  > explicitly rather than assumed, and the answer is its own. The pair
  > statement in `genai_tool_call.provenance.md` and
  > `openai_tool_call.provenance.md` claims *same model, same prompt, same tool
  > inventory, differing only in the instrumentor*. This shape has different
  > prompts, a different tool inventory and a different span topology, and no
  > twin — there is no OpenInference capture it differs from only by
  > instrumentor. Filing it under the pair's provenance would make that file's
  > central claim false, which is the one thing a provenance file may never be.
  > So: `genai_workflow.jsonl` + `genai_workflow.provenance.md`, and the harness
  > **refuses to print the pair sentence** for any non-reference shape
  > (`CaptureShape.matched_pair`) — printing it would be an instruction to write
  > something untrue. It prints instead the sentence saying which capture this
  > one is *not*.
  >
  > **Verification.** The self-checklist the harness already printed gained two
  > lines, appended to the backend's three and answered **against the records it
  > just wrote**, never against what the run intended — the same rule as the
  > fleet's coverage table, for the same reason: a shape steers a run, it does
  > not command one. Is there a span reporting
  > `gen_ai.operation.name=invoke_workflow`? Is there a link joining two spans
  > **of this trace**? A failure exits non-zero and the trace is still written,
  > because it is the evidence for why. A link whose target is not in the file
  > is reported as such rather than counted: it is a valid link — `link` is the
  > one kind allowed to leave the trace — and it is not the thing this shape is
  > for.
  >
  > All of it verified against stub spans as 2.5 was, with no credential and no
  > `opentelemetry` import in the test path. `link_to` is looked up through the
  > module at call time so the run can be driven with a stub link factory; the
  > real one builds a genuine `opentelemetry.trace.Link`, because unlike an
  > exported span that object is handed **to** the SDK and a plausible stand-in
  > would fail in the one place it must not. 124 tests in `tests/test_capture.py`
  > (was 108). `make check` and `make conformance` green.
  >
  > **The reference capture is unchanged, and that is tested, not asserted.**
  > `converse` gained `links` and `on_agent_span`, both defaulting to nothing.
  > `links=()` is what the OTel SDK itself defaults to, so passing it changes no
  > exported byte, and the byte-for-byte OpenInference assertion still holds.
  >
  > **Deliberately NOT done.**
  > - **The three scenarios were not pre-rendered.** They are rendered from what
  >   the capture actually shows, after it exists — the inverted order 2a used
  >   throughout, and the reason Phase 1 lost four fixtures (`FIXTURES.md` §5.1).
  > - **`invoke_workflow` was not mapped.** It remains `UNMAPPED_BY_DECISION`.
  >   Mapping it to `NodeKind.chain` is a model question and a halt point, and
  >   the capture is the evidence that would inform it, not a substitute for it.
  >   `tests/test_capture.py` pins what a human would see today: the workflow
  >   span builds to `unknown` plus a diagnostic, beside a real `link` edge.
  > - **No coverage declaration was touched**, no `expected/graph.json`, and
  >   nothing under `spanweave/`. `PREDICTIONS.md` untouched, as in every phase.
  > - **The capture was not run.** It needs a credential the agent does not have
  >   and must not have (`ENVIRONMENT.md`), and `AGENT.md`'s fabrication halt
  >   point applies in full: no file in `fixtures/captured/` was created, and
  >   nothing here is described as captured.
  >
  > **What a human does next**, in order:
  > 1. `make capture ARGS="--backend genai --shape workflow"`, with
  >    `NEBIUS_API_KEY` and `NEBIUS_BASE_URL` set. Read the checklist it prints;
  >    a non-zero exit means a shape is missing, and the fix is to re-run, never
  >    to edit an exported span.
  > 2. Read, redact, and promote per `FIXTURES.md` §6, writing
  >    `genai_workflow.provenance.md` from the template the harness prints —
  >    including both disclosures above, and **not** the matched-pair sentence.
  > 3. *Then*, and only then, decide whether `invoke_workflow` maps to
  >    `NodeKind.chain` (a halt point), and render the three scenarios from what
  >    the file shows.
  >
  > **Noted, not acted on:** `fixtures/captured/README.md` still says the
  > directory is "Currently empty — the first one lands at `TASKS.md` 1.9". Two
  > fixtures have been there since 2.6. A stale claim in the one directory whose
  > subject is provenance, left for the human whose directory it is.

  ### Definition of done

  - [x] The harness can emit a GenAI trace with an `invoke_workflow` span and a
        span link, and says plainly which spans are the instrumentor's.
  - [x] The link's carrier and ownership are stated in the harness, the README,
        and the printed provenance template.
  - [x] Verified against stub spans; self-checklist extended and exits non-zero
        when either shape is missing.
  - [x] Its own provenance file, argued rather than assumed; the pair sentence
        suppressed for it.
  - [x] Nothing pre-rendered, no model change, `make check` and
        `make conformance` green.
  - [ ] **The capture itself — human-run.** HALT.

- [x] **2.16 Render the three declared scenarios — from the capture.** `[2a]`
  **Decision: `invoke_workflow` is NOT mapped to `chain`. ENDORSED by the human
  (2026-08-28). The reversal below is kept intact and is NOT applied.**

  2.15's capture landed (`fixtures/captured/genai_workflow.jsonl`, ff11065).
  This task read it and derived the renderings from it, in that order.

  > ## The load-bearing argument: provenance
  >
  > **No instrumentor can ever emit an `invoke_workflow` span.** An
  > instrumentor wraps **SDK calls**, and a workflow is not one — there is
  > nothing for it to hook. Only an application can emit such a span, which is
  > exactly what `capture/backends.py` did to produce the one in the capture.
  >
  > So the mapping would rest permanently on renderings derived from spans **we
  > emit ourselves** — not while a capture is pending, but **for the whole
  > class, and for good.** At that point `capture/README.md`'s founding rule
  > binds: *evidence about the outside world that you generated from your own
  > idea of the outside world is not evidence.*
  >
  > That is the whole argument, and it generalizes past this value. The general
  > form is now in `ADAPTERS.md` §3 under `kind`, where someone filling that
  > field will meet it: **a convention value no instrumentor can emit is not a
  > mapping candidate, however well it fits the vocabulary — map from what
  > instrumentors produce, not from what the registry defines.** A mapping
  > whose evidence can never arrive is not deferred, it is unfounded, and the
  > difference matters because the first looks temporary and the second is not.
  >
  > **Checked against the convention's own library, not assumed.**
  > `opentelemetry-util-genai` 1.1b0 *does* ship a `WorkflowInvocation`
  > (`_workflow_invocation.py`): operation `invoke_workflow`, span name
  > `invoke_workflow {name}`, attributes `gen_ai.operation.name` +
  > `gen_ai.workflow.name`. Two things follow, and they point the same way.
  > First, it **confirms the capture's transcription** — the harness's span
  > matches that shape attribute for attribute, which is what a faithful
  > emission looks like. Second, it is reached through `handler.workflow(name)`,
  > a surface an **application** calls, exactly as our harness does. The
  > convention defines the shape; nothing auto-discovers a workflow, because a
  > workflow is a fact about an application that no wrapper can observe. The
  > argument survives its strongest check.
  >
  > ## The definitional argument is real, and lost anyway
  >
  > A later reader should be able to see that this was close, so it is recorded
  > at full strength rather than as a straw man.
  >
  > `SPEC.md` §3.2 defines `chain` as *"a composite step with no more specific
  > kind"*. A workflow **is** a composite step. `NodeKind` has nothing more
  > specific, and the captured span is exactly that: a composite parent, no
  > payloads, no model, two attributes. On the definition alone, `chain` fits —
  > better than any other value in the enum, and better than `unknown` does.
  >
  > **It loses to provenance, not to definition.** The question is not whether
  > the shoe fits; it is whether we are entitled to say so on evidence we
  > generated. We are not, and never will be for this class.
  >
  > ## The cost measurement — confirming, not carrying
  >
  > Secondary to the above, and recorded in that order deliberately: it is
  > weaker, and it does not generalize. It does confirm.
  >
  > | Scenario | Under the mapping | |
  > |---|---|---|
  > | `cyclic_parents` | reproduces `expected/graph.json` **exactly** | retired |
  > | `span_links` | reproduces `expected/graph.json` **exactly** | retired |
  > | `retriever_and_embedding` | still fails, on `s1.inputs` alone (2.17) | **not** retired |
  > | `unknown_kind` | **breaks** | broken |
  >
  > Two retired, one broken. And what breaks is the adapter's **only** unmapped
  > convention value — `unknown_kind`'s `otel_genai` half uses `invoke_workflow`
  > precisely because it is read from the registry rather than invented.
  > Re-authoring it would mean picking a `gen_ai.operation.name` outside the
  > convention's nine, i.e. **inventing one**, which `FIXTURES.md` §5.1 forbids
  > and which that scenario's own table says it deliberately avoided.
  >
  > Measured, not predicted:
  >
  > ```
  > unknown_kind[otel_genai]:  node s1.kind: got 'chain'  want 'unknown'
  >                            diagnostics: got []  want [unknown_span_kind ×1]
  > ```
  >
  > `SPEC.md` §3.2 says the same thing in prose: `unknown` + `reported_kind` is
  > the first-class outcome for exactly this class, naming `guardrail`,
  > `reranker`, `router`, `handoff`, and calling it *"what makes the closed enum
  > survivable in practice"*.
  >
  > ## What the three scenarios rest on instead
  >
  > All three `coverage.json` files were rewritten, because each carried a
  > clause the capture made **false** — *"no captured GenAI trace contains
  > one"*. A §4.3 reason is an invitation to check it against observed output;
  > one that has stopped being true is how a declaration becomes an exemption.
  >
  > - `cyclic_parents`, `span_links`: **one decision away and nothing else.**
  > - `retriever_and_embedding`: blocked independently — see 2.17.
  >
  > ## `EdgeKind.link` across dialects — unchanged, and not softened
  >
  > **The cross-dialect claim does not cover `EdgeKind.link`.**
  >
  > `fixtures/captured/genai_workflow.jsonl` produces a real `link` edge in
  > `otel_genai`, `basis` `span.link`, target resolving in-trace. That proves
  > the adapter reads links. It is **fidelity evidence in one dialect, and
  > fidelity in one dialect is not equivalence** — `fixtures/captured/` is not
  > the equivalence corpus.
  >
  > **What would cover it:** `span_links` rendered in `otel_genai`. Nothing
  > else in the corpus carries the kind, and nothing else carries the only
  > adapter-supplied `basis` string in the library. **The chain decision blocks
  > exactly that**, and the rendering is written and verified below, so the
  > coverage is one decision away rather than one piece of work away.
  >
  > ## The reversal — WRITTEN AND VERIFIED, **NOT APPLIED**
  >
  > Kept whole so the next person does not re-derive it. Nothing here is in the
  > tree; the corpus builds green without it.
  >
  > **Its cost, stated with it:** applying this retires `cyclic_parents` and
  > `span_links` and **breaks `unknown_kind[otel_genai]`**, which then needs an
  > invented `gen_ai.operation.name` — there is no observed value to fall back
  > on. `retriever_and_embedding` stays declared either way (2.17).
  >
  > One line in `spanweave/adapters/otel_genai.py`:
  >
  > ```diff
  >      "create_agent": NodeKind.AGENT,
  > +    "invoke_workflow": NodeKind.CHAIN,
  >  }
  > -UNMAPPED_BY_DECISION = ("invoke_workflow",)
  > +UNMAPPED_BY_DECISION = ()
  > ```
  >
  > `fixtures/conformance/cyclic_parents/dialects/otel_genai.jsonl`:
  >
  > ```json
  > {"attributes":{"gen_ai.operation.name":"invoke_workflow"},"end_time":1002.0,"name":"chain.one","parent_id":"s2","span_id":"s1","start_time":1000.0,"status":"OK","trace_id":"t1"}
  > {"attributes":{"gen_ai.operation.name":"invoke_workflow"},"end_time":1001.0,"name":"chain.two","parent_id":"s1","span_id":"s2","start_time":1000.2,"status":"OK","trace_id":"t1"}
  > ```
  >
  > `fixtures/conformance/span_links/dialects/otel_genai.jsonl`:
  >
  > ```json
  > {"attributes":{"gen_ai.operation.name":"invoke_agent"},"end_time":1002.0,"links":[{"span_id":"s1","trace_id":"t1"}],"name":"agent.run","parent_id":null,"span_id":"s0","start_time":1000.0,"status":"OK","trace_id":"t1"}
  > {"attributes":{"gen_ai.operation.name":"invoke_workflow"},"end_time":1001.0,"links":[{"span_id":"s9","trace_id":"t2"}],"name":"chain.step","parent_id":"s0","span_id":"s1","start_time":1000.2,"status":"OK","trace_id":"t1"}
  > ```
  >
  > Both verified byte-exact against the **unmodified** expected graphs, with
  > `name` **compared** — no `comparison.json`, no `erase: ["name"]`, and so no
  > edit to any frozen graph. That is worth noting against the 2.8 precedent,
  > where rendering a second dialect *did* need `erase: ["name"]` plus deleting
  > `name` from the expected graph, and was carried to a human for it.
  >
  > Then delete those two `coverage.json` files (the §4.3 lifecycle, as
  > `declared_data_edge`'s did), tick their `scenario.md` dialect boxes, and
  > re-author `unknown_kind`'s `otel_genai` half — the part that is not free.
  >
  > Attribute shapes are transcribed from the capture: the workflow span
  > carries `gen_ai.operation.name` alone, as every other `otel_genai` rendering
  > carries only the keys its scenario exercises, and `gen_ai.workflow.name` is
  > omitted for the same reason `server.address` and `gen_ai.response.*` are
  > omitted everywhere else — omission is fine, misstatement is not (§5.1).
  >
  > **When this reopens:** a dialect whose *instrumentor* emits a genuine
  > composite step. Then the evidence exists and the question is fresh. Until
  > then it is settled, and this record is the reason.
  >
  > ## Done
  >
  > - [x] Renderings derived by **reading the committed fixture**, then probed
  >       against the unmodified expected graphs. `canonical()` untouched, no
  >       `expected/graph.json` edited, nothing written to make a test pass.
  > - [x] Decision taken, endorsed, and recorded with the provenance argument
  >       load-bearing and the definitional argument stated at full strength.
  > - [x] General rule in `ADAPTERS.md` §3 (`kind`) and its §6 checklist.
  > - [x] All three `coverage.json` reasons rewritten; `unknown_kind`'s cost
  >       recorded in its own `scenario.md`, and its stale *"one of the two this
  >       adapter does not map"* corrected to **the only one**.
  > - [x] `EdgeKind.link` answered plainly and not softened anywhere.

- [x] **2.17 `retriever_and_embedding`: the adapter gap, and what remains.**
  `[2a]` **HALT: still not renderable. Two blockers, both evidenced below.**

  2.16 found this scenario blocked on a payload as well as on `chain`. The
  payload half was an **adapter gap, not a vocabulary one**, and is now closed.
  The scenario is still declared, and the reason is a better one.

  > ## Fixed: the retriever's output
  >
  > The adapter now reads a retrieval span's two content attributes:
  >
  > | Attribute | mime | parsed |
  > |---|---|---|
  > | `gen_ai.retrieval.documents` | `application/json` | yes |
  > | `gen_ai.retrieval.query.text` | `text/plain` | **no** |
  >
  > The asymmetry is the dialect's, not a choice: `RetrievalInvocation.documents`
  > goes through the same `gen_ai_json_dumps` the message lists use, and
  > `query_text` is typed `str | None` and written verbatim. So this is
  > `ADAPTERS.md` §3's *"a mime the dialect defines but does not emit"* rule
  > applied in **both** directions — reading a JSON-shaped query as JSON would
  > invent a structure the convention does not claim, which is the same error as
  > refusing `application/json` on the attributes it does.
  >
  > `s2.outputs` now agrees with `expected/graph.json` exactly.
  >
  > ## What it was mapped from — said plainly, because it is weaker
  >
  > **Neither attribute appears in any captured trace in this repo.** The
  > evidence, since it was asked for:
  >
  > ```
  > fixtures/captured/openai_tool_call.jsonl   4 spans   AGENT, LLM, TOOL
  > fixtures/captured/genai_tool_call.jsonl    4 spans   invoke_agent, chat, execute_tool
  > fixtures/captured/genai_workflow.jsonl     9 spans   invoke_workflow, invoke_agent, chat, execute_tool
  >
  > lines carrying gen_ai.retrieval.documents / .query.text / embeddings content:  NONE
  > ```
  >
  > Three traces, 17 spans, and not a `retrieval` or `embeddings` span among
  > them. The mapping comes from `opentelemetry-util-genai` 1.1b0's
  > `_retrieval_invocation.py` — the support library the captured traces' **own
  > instrumentor** delegates to for `gen_ai.input.messages`, so the same source
  > read at the same version, and it states the types rather than only the
  > names.
  >
  > The registry alone would **not** have been enough, and this is worth
  > knowing: in `opentelemetry-semantic-conventions` 0.65b0 every `gen_ai.*`
  > docstring has been replaced by the notice that the conventions moved house.
  > It supplies names and nothing else — no type, no brief, no requirement
  > level. `capture/README.md` already warns not to trust that package past its
  > date; this is the first place the warning bit.
  >
  > This provenance is weaker than a capture and is recorded as such in the
  > adapter, in the tests, and in the scenario — not left for a reader to work
  > out from the fact that the tests pass.
  >
  > ## Still blocked, and the blocker moved again
  >
  > | Node | Field | `otel_genai` | |
  > |---|---|---|---|
  > | `s2` | `outputs` | agrees exactly | **fixed** |
  > | `s1` | `inputs` | `absent` vs `present` | **blocker 1** |
  > | `s0` | `kind` | `unknown` vs `chain` | blocker 2 |
  >
  > **Blocker 1: the dialect has no content attribute for an embedding span at
  > all.** `EmbeddingInvocation` emits `gen_ai.embeddings.dimension.count`,
  > `gen_ai.request.encoding_formats`, `gen_ai.response.model` and token counts
  > — nothing carrying the embedded text. There is no attribute to render, and
  > putting the text under `gen_ai.input.messages` would be inventing one.
  >
  > That is `absent` against `present`, a payload **state** disagreement, and
  > `FIXTURES.md` §4.4 forbids declaring one away *ever*: `absent` ≠ `empty` ≠
  > `redacted` is the model's central honesty claim and there must be no
  > mechanism that can absorb a disagreement about it. So this is not a
  > declaration away from renderable — it is unrenderable, and **no capture can
  > retire it**, because it is a property of the convention rather than a gap in
  > an adapter.
  >
  > **Blocker 1 outlives blocker 2, measured:** with `invoke_workflow`
  > hypothetically mapped to `chain`, the scenario still fails on `s1.inputs`
  > alone. If 2.16 is ever reversed, this scenario must **not** be retired with
  > the other two.
  >
  > ## The stated blocker has now been wrong three times
  >
  > Worth recording as a pattern rather than three separate corrections. 2.11:
  > *the dialect may not name a retriever* — refuted, it does. 2.11 then: *the
  > chain parent* — true but not the whole of it. 2.16: *the chain parent and
  > the retriever's payloads* — the payloads were an adapter gap, now closed,
  > and the real one was one node over.
  >
  > Each reason was checked and each was wrong in the same direction: it named
  > the first blocker found and stopped. `FIXTURES.md` §4.3's *"an invitation to
  > check the reason against observed output"* is doing real work on this
  > scenario, and the corrected version of `ADAPTERS.md` §5 now carries the
  > general lesson — coverage is lost to **what a dialect cannot say**, which is
  > usually a kind and sometimes an attribute that does not exist.
  >
  > ## Done
  >
  > - [x] Adapter reads both retrieval attributes, with the mime each one's type
  >       warrants and neither invented.
  > - [x] Eight unit tests, including the state-honesty cases, the
  >       looks-like-JSON query, the no-fallback rule, and the embedding span
  >       that has no content attribute — which is blocker 1, pinned.
  > - [x] What it was mapped from stated in the adapter, the tests, the
  >       scenario and the `coverage.json`.
  > - [x] `coverage.json` rewritten again: one blocker removed, one restated,
  >       one added. **Not retired** — the scenario still cannot be rendered.
  > - [x] `make check`, `make conformance`, gates green. `PREDICTIONS.md`
  >       untouched.
  > - [ ] **Renderable only if the convention grows an embedding content
  >       attribute (blocker 1) *and* 2.16 is reversed (blocker 2).** HALT.

## Phase 3 — Confirm, package, launch

Sharpened from the provisional bullets after the Phase 2 exit (2.14) and the
post-exit follow-up (2.17), per this file's resolution rule. Falsification
happened in Phase 2; this phase is **confirmation and packaging**, and nothing
open-ended sits next to a launch date.

**Read before starting any task here:** `ROADMAP.md` Phase 3 and its cut order,
`PREDICTIONS.md` P1–P4 and the binding shape/operational test, the Phase 2 exit
record (2.14), and 2.15–2.17. Several tasks below are what they are *because* of
what those records found, and the blockers section immediately following says
which.

**Workstreams. Never mix them in one session's context.** Every task is tagged
`[prereq]`, `[contract]`, `[consumers]`, or `[launch]`. A cold session picks the
lowest-numbered unchecked task and works only that tag.

**Ordering — decided, do not re-litigate.** `[contract]` (3.2) runs **before**
the consumers. Phase 2's most transferable finding is that the *permissive
default won* three times and each defect was invisible until something else had
to agree with it; a consumer written against a field whose type then changes is
that lesson paid for twice. The counter-argument — that the consumers are this
phase's evidence and the inventory is bookkeeping — is real and loses on cost,
not on importance.

**The gate this phase is measured by: zero shape changes.** A new field,
`NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code or query
primitive wanted by a confirmatory consumer means the model could not express
what a real consumer needed. Classify with `PREDICTIONS.md`'s binding test, **as
written there** — widening the distinction mid-phase to accommodate whatever
happened is the exact rationalization that file exists to prevent.

**HALT markers.** A task marked **HALT** ends the session. It names the artifact
the human needs in order to decide. Do not proceed past one alone. The standing
halt points in `AGENT.md` still apply on top of these — any model change,
anything in `OPEN_QUESTIONS.md`, any edit to `PREDICTIONS.md`, any change to
`schema_version` semantics, any credentialed or networked step.

### What Phase 2 changed that Phase 3's plan predates

`ROADMAP.md`'s Phase 3 was written before Phase 2 ran. Four things it could not
have accounted for. Each says plainly whether it **blocks** a task or
**under-specifies** one, so that none of them is rediscovered mid-phase.

**1. P1's predicted friction did not appear in 2b — and 2b was not P1's test.
*Under-specifies 3.4. Does not block it, and does not partly resolve P1.***

P1 predicts a cost/latency attributor will want `retain_payloads=False` or
`retain_raw=False`, because retaining full payloads for a 100k-span trace is
memory it has no use for. Phase 2b's fleet aggregator asked for **no such
option**: findings F1–F9 (2.4) contain no retention item, no memory item, and
nothing about losslessness being cost. That is real evidence and it is negative,
so it is recorded rather than discarded.

It is also **not the test P1 names**, in three specific ways, and each is a
requirement on 3.4 rather than a caveat to be waved through:

- **The fleet could not exert the pressure.** Fourteen traces of a handful of
  spans each, built one at a time and released. Peak residency was one small
  graph. A prediction about memory at 100k spans cannot be refuted by an input
  that never approaches it.
- **The aggregator was not the consumer P1 describes.** It counted node kinds,
  diagnostic codes, per-tool calls and status. It never read `usage` and never
  read a timestamp — which is exactly the pair P1 says a cost/latency consumer
  needs *and nothing else*. The consumer that would feel losslessness as dead
  weight has not been built yet.
- **A counting rollup discards as it goes.** It never holds a corpus in memory,
  so it structurally cannot want a retention option — the same shape of scoping
  that limited P5's refutation (`PREDICTIONS.md` P5, *Scope of the refutation*).

So P1 keeps its full test at **3.4**, and 3.4 is written to *apply the
pressure*, not to demonstrate an attributor. 2b's negative evidence is carried
to the human at **3.5** as corroboration, labelled for what it is: a different
consumer, at a size that could not have produced the friction.

**2. `Diagnostic.source` changed type in Phase 2, and `schema_version` did not.
*Under-specifies 3.7 — and 3.7 is a HALT for it. Constrains 3.3.***

O1's remedy changed `Diagnostic.source` on `unpaired_call` / `unpaired_result`
from a bare id string to `{"call_id", "operation"}`, classified **SHAPE** at
2.14. `SPEC.md` §3.7 now states `source`'s shape per code, and
`tests/test_codes.py` asserts that table against what the library emits — so the
contract half is done and needs nothing in Phase 3.

What needs accounting for is the **version**. `SCHEMA_VERSION` was `"0.1"` before
the change and is `"0.1"` after it. A consumer pinning on `schema_version` across
those two releases sees one value describing two different serialized contracts.
0.9.x publishes that to strangers. The decision — bump to `"0.2"`, or state
explicitly that `0.x` is a single unfrozen bucket that never bumps and that
pinning must therefore be on the *library* version — is `AGENT.md`'s
*"any change to `schema_version` semantics"* halt point, and it is **3.7**.

It also constrains **3.3**: the remedy exists so a consumer can name an
unfulfilled call's tool in one line, identically in every dialect. If either
Phase 3 consumer reaches that name by walking `outputs.value[...]` instead, the
remedy did not land, and that is a finding about the remedy rather than a detail
of the example.

**3. The three-defects pattern: audit now, resolve later. *Neither blocks. The
inventory half is Phase 3 (3.2); the resolution half stays Phase 4.***

2.14's instruction reads *"before freezing `schema_version`, audit every
serialized field typed permissively (`JsonValue`, free `str`) for a stated
contract and an asserting test"*, and names `Edge.basis` as the next one. The
freeze is Phase 4, so the sentence has been read as placing the whole audit
there. It places the **resolution** there, and the two halves have different
costs and different evidence:

- **Enumerating** the permissively-typed serialized fields is cheap, needs no
  dialect, and is worth most *before* 0.9.x — because publishing is what turns an
  unstated serialized field into something strangers observe and pin behavior to.
  A de-facto contract formed by observation is harder to correct than an unstated
  one nobody has seen. **Phase 3, task 3.2.**
- **Stating a contract** for a field whose vocabulary no second implementation
  has ever had to agree with is the *same mistake in the other direction* — it
  is one author writing down one implementation's behavior and calling it a
  contract, which is precisely how all three defects were born. `Edge.basis` is
  unmeasurable by construction today (2.14): both adapter-supplied bases are
  invisible to the cross-dialect claim. **Phase 4, with dialect three**, exactly
  where 2.14 put it.

3.2 therefore produces a list and a tripwire, not a set of new contracts. Where a
field has no evidence, it records *"unstated, unmeasured, needs dialect three"*
and stops. This is also the second argument for the freeze gate recorded in
`ROADMAP.md` Phase 4: the audit's own instrument is a third dialect.

**4. `AGENT.md` and `ENVIRONMENT.md` still deliver Phase 2. *Blocks everything —
it is 3.1.***

`AGENT.md`'s *Scope of this run* delivers through 2.14 and then halts, its
must-not list explicitly forbids the confirmatory consumers as "Phase 3", and its
live phase-exit halt is Phase 2's. A cold Phase 3 session reads that file first
and is told to stop — the same condition 2.1 found and fixed for Phase 2.
`ENVIRONMENT.md` needs less but needs it precisely: its three network zones have
no zone for *publishing to an external index*, and PyPI credentials are a
category it currently does not mention at all.

### The cut order, re-read after Phase 2

`ROADMAP.md`'s Phase 3 cut order **still stands, and one item in it is now
wrong** — wrong because of something Phase 2 did, which is why it is corrected
here rather than left to be discovered under pressure.

**That Phase 2's timeboxes never bound is not evidence about Phase 3.** Both
boxes were insurance and both went unused; nothing ran long. But Phase 2 had no
external date, which the cut order itself names as the reason it was *easier* to
cut sloppily there. Phase 3 is the **first phase with a launch date**, so it is
the first phase where the pressure the cut order was written for actually exists.
An unused box says the estimate was good, not that the next phase's will be.

**The correction.** The list says cut *"confirmatory consumer 2, then consumer
1"* — consumer 1 being the trajectory dumper and consumer 2 the cost/latency
attributor — on the grounds that both are expected to pass and "cutting one
forfeits little". Phase 2 falsified the premise:

- The cost/latency attributor is now the **only** test P1 has (blocker 1). The
  same list names the prediction resolutions **never-cut**. So cutting the first
  item on the cut list silently cuts a never-cut item, which is the failure mode
  the list exists to prevent, executed by the list itself.
- The trajectory dumper is the only consumer that reads payloads across the five
  states, which makes it P2's only real test.

So neither consumer "forfeits little" any more; each carries a prediction that
must be marked before the freeze. **Cut the trajectory dumper (3.3) first** — P2's
predicted outcome is REFUTED-as-harmless with no model consequence, so its
evidence is the cheaper of the two to defer. **Cutting the attributor (3.4)
defers P1 to Phase 4** and must be recorded as that, in the exit record, in
those words. Neither cut may be described as forfeiting little.

Items 2 and 3 of the list — the `CONTRIBUTING.md` adapter walkthrough and the
compatibility policy — are already Phase 4 and appear in no task below. Nothing
here can cut them because nothing here schedules them.

**Never cut, unchanged:** the prediction resolutions (3.5), the Phase 2
adversarial finding, the unfrozen-schema notice (3.7, 3.8). **Never accelerate:**
the freeze — which is now additionally gated on a third dialect (`ROADMAP.md`
Phase 4), and that gate binds Phase 4, not this phase's launch.

---

### `[prereq]`

- [x] **3.1 Re-scope `AGENT.md` and `ENVIRONMENT.md` for Phase 3.** `[prereq]`
  As 2.1 did for Phase 2, and for the same reason: a cold session reads
  `AGENT.md` first and is currently told that Phase 3 must not start. Rewrite
  *Scope of this run* for Phase 3, **keeping every halt point**, discharging the
  Phase 2 exit halt by moving it forward rather than deleting it, and adding what
  this phase newly needs:

  - **New halts:** the PyPI publish (3.10 — credentialed, outward-facing, and a
    name-plus-version on PyPI cannot be reused, so it is closer to irreversible
    than any other step in this phase); the `schema_version` decision (3.7 —
    already a standing halt as *"any change to `schema_version` semantics"*, named
    at its task so it is not missed); each consumer's findings record, because
    **a human marks P1–P4** in a file the agent may not edit.
  - **New must-nots:** freeze the schema or change `SCHEMA_FROZEN`; add a third
    dialect (still Phase 4, and now also a freeze precondition — see the gate in
    `ROADMAP.md`); resolve or edit `PREDICTIONS.md`; widen the shape/operational
    distinction to classify a consumer's finding as operational; add a runtime
    dependency to make an example easier.
  - **Retire what Phase 2 discharged:** the 2b timebox, the 2.2/2.6 capture
    halts (the general captured-fixtures halt stays standing — 2.15's capture ran
    and further ones are still human acts), and the first-equivalence-run halt.
    A halt that is already false is how a list of halts stops being read (2.1).
  - `ENVIRONMENT.md`: add the **publish zone** to the network policy — it has
    three zones, all of them *inbound or none*, and pushing an artifact to an
    external index is a fourth; add **PyPI credentials** to the credentials
    section as human-only, alongside the model API key; drop the `otlp` extra's
    "Phase 4" annotation only if it moves, and otherwise leave it; add
    `make install-check` (3.6) to the commands list once it exists.

  *Done when `AGENT.md`'s scope section names Phase 3, its must-not list no
  longer forbids the confirmatory consumers, its halt list contains every entry
  it had minus only the ones Phase 2 discharged plus the new ones above,
  `ENVIRONMENT.md` names a publish zone and PyPI credentials, and `make check` is
  green.*
  **HALT** — the run scope is a human decision, not an agent's.
  *Artifact for the decision:* the diff of `AGENT.md`'s *Scope of this run* and
  *Halt-and-hand-back points* sections and `ENVIRONMENT.md`'s network and
  credentials sections, side by side with the old text.
  > **Scope change authorised explicitly by the human before this ran**, since
  > `AGENT.md` scoped the run to the Phase 2 exit and this is the task that
  > changes that. The **HALT still stands**: 3.2 has not been started, and the
  > new scope wants approval before it is.
  > **Halts: eight kept, one moved, three retired, five added.** The eight
  > standing entries are unchanged in force — captured fixtures, any model
  > change, `OPEN_QUESTIONS.md`, editing `PREDICTIONS.md`, the freeze /
  > `schema_version` semantics, the license and `SPEC.md` scope, live
  > credentials and network, and the phase exit. The one that moved is the
  > **phase exit**, now Phase 3's (3.11), with 1.9 and 2.14 recorded as
  > discharged rather than deleted.
  > **The three retired are named as retired, with why each is now false** —
  > the 2.2 / 2.6 capture runs (both ran; the general captured-fixtures halt is
  > what survives them, and it now also forbids describing 3.4's generated load
  > input as captured), the 2b timebox (closed; the human has marked P5
  > **REFUTED — scoped**), and the first cross-dialect equivalence run (it
  > happened, and both dialects have agreed since 2.13). Deleted rather than
  > left standing, for 2.1's reason: a halt that is already false is how a list
  > of halts stops being read.
  > **Five added**, one more than this task listed. The four it named: the PyPI
  > publish (3.10), the `schema_version` decision at its task (3.7), the
  > consumers' findings records and the resolution artifact (3.3, 3.4, 3.5,
  > because a human marks P1–P4), and — as an explicit instance rather than a
  > new licence — a type change **forced by the 3.2 inventory**, which 3.2
  > marks HALT and which the halt list otherwise reached only through the
  > general model-change entry. The fifth is **adding a core runtime
  > dependency**: `ENVIRONMENT.md` has always called it *"a halt point
  > (`AGENT.md`)"* and `AGENT.md` did not carry it. A cross-reference that
  > resolves to nothing is not a halt, and this phase's must-not list depends
  > on it.
  > **The must-not list gained what Phase 3 newly forbids, not only lost what
  > it newly permits** — the argument is 2.1's and it held: a scope section
  > that only removes prohibitions reads as open season. It now forbids the
  > freeze and `SCHEMA_FROZEN` and `schema_version` `1`; a third dialect (Phase
  > 4, and *now also a freeze precondition*, which makes doing it early cost
  > more than it used to, not less); resolving or editing `PREDICTIONS.md`;
  > widening the shape/operational distinction to classify a want as
  > operational; a core runtime dependency added to make an example easier;
  > publishing to PyPI **or TestPyPI**; and — carried forward unweakened —
  > editing an `expected/graph.json` or weakening `canonical()`, which no Phase
  > 3 task should touch, so an apparent need to is itself a finding.
  > Two things Phase 2 forbade are now named as **required**: the confirmatory
  > consumers (3.3, 3.4), and **preparing** a PyPI distribution. The
  > prepare/push line is drawn in the scope text and again in the publish zone.
  > **One line changed outside the four requested sections**, and it is in the
  > artifact below: **run loop step 3**. As written it tells a session to author
  > the fixture and its expected graph before implementing. No Phase 3 task
  > authors a fixture — the consumers read committed ones — and a session
  > following step 3 literally would write the fixture its own consumer is then
  > measured against, which is the consumer setting its own exam. The step now
  > says so and calls the apparent need a finding.
  > `ENVIRONMENT.md`: the network policy is **four zones**, and the new one is
  > stated as differing *in kind* — the first three are inbound or none (build
  > and capture both *pull*), and pushing to an external index is outward-facing,
  > credentialed, and effectively irreversible on a name-plus-version. It says
  > what the agent **may** do — `uv build`, and installing a locally built wheel
  > into a throwaway venv, which reaches PyPI only as zone 1 does — so that 3.6
  > and 3.10 are not blurred by the same rule. Credentials now names **two**
  > human-run credentialed steps rather than "the single credentialed step":
  > the model API key, and a PyPI/TestPyPI token the agent must not hold and
  > must not be given "just to test the upload".
  > Two things this task offered conditionally were **not** done, because their
  > condition is unmet: `make install-check` is not in the commands list (3.6
  > has not built it, and a contract naming a command that does not run is the
  > `fixtures/captured/README.md` failure in advance), and the `otlp` extra
  > keeps its "(Phase 4)" annotation because it has not moved.

---

### `[contract]`

- [x] **3.2 Inventory every permissively-typed serialized field.** `[contract]`
  From 2.14's freeze instruction, split per blocker 3: **this task produces the
  list and the tripwire, and states no contract it cannot evidence.**

  Enumerate every field that crosses the schema boundary and is typed
  permissively — `JsonValue`, a free `str`, `dict`/`list` of anything. Known
  members: `Diagnostic.source` (stated at `SPEC.md` §3.7, asserted by
  `tests/test_codes.py` — the worked example of what "done" looks like),
  `Edge.basis`, `Node.attributes`, `Payload.value`, `Payload.mime`,
  `RawRecord`'s contents, `Meta.adapters[].id`. Find the rest from the model
  rather than from this list.

  For each, record exactly one of:
  - **stated + asserted** — the document that states it and the test that
    asserts it;
  - **unstated, unmeasured** — and *why no contract is being written now*.
    `Edge.basis` is the reference case: adapter-supplied, compared by
    `canonical()`, and both of its adapter-supplied instances are invisible to
    the cross-dialect claim (2.14), so any contract written today would be one
    author describing one implementation — the mechanism that produced all three
    Phase 2 defects. It stays Phase 4, with dialect three.

  **Do not invent a contract to close a row.** An honest "unmeasured" row is the
  deliverable for those fields; a plausible one is the defect.

  *Done when a test enumerates the permissively-typed serialized fields from the
  model and fails if one appears without an inventory entry — the same
  both-directions shape as `test_the_compared_list_names_every_field_that_is_compared`
  — and `make check` is green.*
  **HALT — only if the inventory forces a type change**, i.e. a field whose
  stated contract cannot be written without changing what is serialized. That is
  a shape change and it is a human call *before* 0.9.x publishes the field.
  Record it under this task with `PREDICTIONS.md`'s binding test; it is **not**
  a Phase 3 gate failure, because the gate measures what a *consumer* could not
  express — say so explicitly rather than letting the two be conflated in either
  direction.
  *Artifact for the decision:* the inventory, the field, what it serializes
  today, and what stating its contract would change.

  **Cut order:** not on `ROADMAP.md`'s list — it did not exist when the list was
  written. If cut, it joins the resolution half in Phase 4, and the cost is that
  0.9.x publishes an unenumerated surface. Record the cut; do not let it vanish.

  > # 3.2 record — the inventory, and what it measured
  >
  > `CONTRACTS.md` (new) + `tests/test_contracts.py` (new). `make check` green
  > (1332 passed, 2 skipped; +153 from this file), `make conformance` green,
  > `make gates` green, `review_corpus.py` exit 0. Nothing under `spanweave/`
  > changed. No fixture was authored, no `expected/graph.json` was touched, and
  > `canonical()` was not weakened.
  >
  > ## The halt condition — tested, and NOT met
  >
  > **No type change is forced.** Every row was recorded without writing a
  > contract, and no row needed what is serialized to change in order to be
  > *enumerated*. Naming a field as unmeasured is not the act of stating its
  > contract, which is the distinction the task rests on.
  >
  > Two rows are **pre-registered** as the likeliest to force one in Phase 4,
  > and saying so now is not the same as meeting the condition now:
  > `nodes[].usage.extra` (any honest key contract changes what is serialized or
  > what `canonical()` compares) and `diagnostics[].source` (closing §3.7's
  > catch-all may change what three codes emit). Both are argued in
  > `CONTRACTS.md`, *The halt condition*.
  >
  > **And it is not a Phase 3 gate failure, in either direction.** That gate
  > measures what a *confirmatory consumer* could not express; no consumer has
  > run, because 3.3 and 3.4 come after this task. This produces no evidence for
  > or against it. Recorded as both things separately, as the task asks, rather
  > than as whichever reads better.
  >
  > ## What was measured, and how
  >
  > **36** permissively-typed serialized fields, enumerated from the model by a
  > type test rather than from 3.2's known-members list (which named 7; the
  > other 29 came from the model). Each was then **perturbed in the serializer,
  > one at a time, with the whole suite run** — 39 runs, the three payload
  > fields split per side. That is the instrument that made the 2.10 defect
  > visible in the first place: *changing its type broke zero tests*.
  >
  > **Eleven of thirty-six can be changed at the schema boundary with the suite
  > green.** That is the headline, and it is the answer to the question the task
  > asks rather than "it is typed permissively": `meta.spanweave_version`,
  > `meta.source_digest`, `meta.adapters[].id`, `meta.adapters[].version`,
  > `nodes[].raw.source_id`, `nodes[].provenance.adapter_version`,
  > `nodes[].provenance.dialect_note`, `edges[].adapter`,
  > `diagnostics[].message`, `diagnostics[].adapter`, `annotations[].key`.
  >
  > ## Findings beyond the rows
  >
  > - **`nodes[].name` has never been compared across dialects.** `canonical()`
  >   compares it; 16 of the 17 scenarios rendered in both dialects declare it
  >   dialect-varying, and the 17th is a scenario that must not build. This is a
  >   bound on what "16 byte-identical canonical graphs" (2.14) proves, and it
  >   belongs beside that figure rather than under it.
  > - **`Usage.extra` is a second `Edge.basis`, and 2.14 did not name it.**
  >   Adapter-supplied, dialect-derived verbatim (`cache_read` vs
  >   `cache_read_input_tokens` for the same concept), compared by `canonical()`,
  >   and empty in every fixture in the repo — so the disagreement is unreachable
  >   by construction. Same species, same resolution: Phase 4, dialect three.
  > - **`Edge.basis`, refined — two corrections to 2.14.** (1) *No adapter emits
  >   a `DeclaredDataEdge` at all*; 2.14 says `otel_genai` produces none, and
  >   `openinference._data_edges` also returns `()` and says why. It is a
  >   required seam field nothing has ever populated. (2) *Neither adapter has
  >   ever chosen a `SpanLink.basis`* — both take the default `"span.link"`.
  >   2.14's conclusion is unchanged and stronger; what changes is the
  >   instrument: **dialect three does not resolve this unless the corpus also
  >   gains a `link` scenario a second dialect can render**, which `span_links`
  >   currently blocks (2.16's pending decision). A third dialect added without
  >   that leaves the row exactly where it is.
  > - **§3.7's `source` catch-all is stated and unasserted.** "Everything else —
  >   the offending fragment, verbatim" covers ten codes; measured, three do not
  >   match its words (`missing_timestamp` and `payload_parse_failed` carry no
  >   fragment at all; `ordering_cycle` carries spanweave node ids, which are
  >   derived output). `tests/test_codes.py` asserts the two unpaired codes and
  >   checks the table's other direction only as *declared shapes ⊆ real codes*.
  >   Same species as the defect the remedy fixed, one level down.
  > - **F7 is now a field row.** "Nothing states which diagnostic codes are
  >   node-scoped" (2.4) is `diagnostics[].node_id`'s *Relies on* note.
  > - **One field is excluded by the scope rule and named anyway:**
  >   `meta.adapters[].declared_confidence` is `float | None`, so constrained by
  >   type, yet `ADAPTERS.md` §2 states a `[0.0, 1.0]` range nothing enforces.
  >   Same species, differently-typed field; widening the rule to catch it would
  >   make the rule a judgement instead of a type test, so it is named in
  >   `CONTRACTS.md` rather than rowed.
  >
  > ## Divergences from the task as written
  >
  > - **Three statuses, not two.** 3.2 says record *exactly one of* `stated +
  >   asserted` or `unstated, unmeasured`. Applied literally, `Edge.basis` and
  >   `Node.operation` get the same label, though one is invisible to the
  >   cross-dialect claim by construction and the other is agreed by two
  >   independent adapters in 15 of 16 compared scenarios. Collapsing those loses
  >   exactly the information the task exists to preserve. The vocabulary is
  >   therefore a **2×2 over the task's own two questions** — is it stated, is it
  >   asserted — plus `pinned` for "a fixture detects a change but nothing states
  >   what the value should be". Six values, closed, and derived mechanically
  >   from each row's own cells so a status cannot be written by hand.
  > - **`Asserted` is measured at the schema boundary, not read.** A field can be
  >   asserted at the *model* level and still show `—` (`meta.source_digest` and
  >   `edges[].basis` both are). That is a different gap and the notes keep them
  >   apart; the boundary is what `0.9.x` publishes.
  > - **`AGENT.md`'s document map gained one line** for `CONTRACTS.md`. A cold
  >   session reads that file outline-first, and an inventory it cannot find is
  >   an inventory that rots.
  >
  > ## The tripwire
  >
  > `tests/test_contracts.py`, both directions in five places: the object map vs.
  > a real document; every serialized key vs. its model type and every model
  > field vs. what is written (with `RawRecord.line_number` and
  > `Meta.schema_version` **declared** unserialized, so neither can quietly start
  > or stop); every permissive field vs. a row and every row vs. a permissive
  > field; the *Relies on* list vs. the rows; and the document's own
  > eleven-unasserted list vs. the rows whose Asserted cell is empty. Each row's
  > cited sections and test node ids must resolve, and each row's type must be
  > the model's.
  >
  > **Verified by planting, not by reading:** eight violations — a new
  > permissively-typed serialized field, a status that does not follow from its
  > cells, a citation to a section that does not exist, one to a test that does
  > not exist, a stale eleven-field list, a missing *Relies on* note, a model
  > field dropped from the serializer, and a declared type drifting from the
  > model — each went red in the intended test, and each was reverted.
  >
  > ## Definition of done
  >
  > - [x] Every permissively-typed serialized field enumerated **from the model**
  >       (36; 3.2's list named 7).
  > - [x] Each records what states it, what asserts it, and — where nothing does
  >       — that, with why no contract is written now.
  > - [x] No contract invented to close a row. Four rows say `unstated`.
  > - [x] A test fails if a field appears without an entry, and if an entry
  >       appears without a field.
  > - [x] `make check` green.

  > # 3.2 follow-ups — approved and worked in the same session
  >
  > Three, all arising from 3.2's findings, all before 3.3. `make check` green
  > (1335 passed, 2 skipped), `make conformance` green, `make gates` green,
  > `review_corpus.py` exit 0. Nothing under `spanweave/` changed.
  >
  > ## 1. The Phase 2 headline is bounded, in five places
  >
  > "16 byte-identical canonical graphs" does **not** include `Node.name`. The
  > bound is now stated beside the figure at **2.14's evidence block** (the
  > canonical statement), and at every other place the claim is made: 2.14's
  > definition-of-done line, **2.9's HALT-DISCHARGED note**, the `[2a]` session
  > marker, `ROADMAP.md`'s Phase 2 *Shareable*, `FIXTURES.md` §4 (with the
  > count, where the declaration mechanism is defined), and `README.md`'s
  > *Conformance* section — which had the unqualified claim in the most-read
  > place and no mention of the declaration mechanism at all.
  >
  > The claim is not weakened, it is stated. `name` is what two instrumentors
  > are least likely to agree on, which is why §4.4 exists.
  >
  > **The `phase-2-exit` tag carries the unqualified form and is not
  > rewritten.** It is an annotated object and published history. 2.14's record
  > now says the tag message predates this finding and is superseded by that
  > block, so a reader who finds the tag first is led to the correction.
  >
  > `README.md`'s stale *Status* section (it still describes Phase 2 as
  > upcoming) was **left alone**: that is 3.8's docs truth pass, not this.
  >
  > ## 2. The freeze gate is qualified — necessary, and not sufficient
  >
  > In `ROADMAP.md`, *The third dialect is a freeze precondition*. The gate
  > stands unweakened; what is added is that **"a third dialect rendered"
  > satisfies the gate as written and still leaves `Edge.basis` unmeasured**,
  > because 3.2's two corrections changed the instrument: no adapter emits a
  > `DeclaredDataEdge` at all, and neither adapter has ever *chosen* a
  > `SpanLink.basis` — both take the default.
  >
  > The principle now stated there, which 2.14 could not have: **an
  > adapter-supplied field is only measured when two adapters that *chose* a
  > value have to agree on it.** Agreement on a default is structural, the way
  > the builder's four `basis` strings are.
  >
  > What would be sufficient is written out: (1) a `link`-carrying scenario a
  > second dialect can render — `span_links` is the only one and is blocked by
  > the `invoke_workflow` → `chain` decision (2.16), *not* by link support;
  > (2) an adapter that has to choose a different basis, which is a property of
  > whatever dialect three turns out to be and cannot be arranged; (3) for
  > `DeclaredDataEdge.basis`, an adapter that emits one at all — and if dialect
  > three emits none either, a seam field three dialects never populate is a
  > removal candidate, which is a **shape** change and belongs in the freeze
  > decision rather than after it.
  >
  > **`Usage.extra` added as the fifth instance** of the pattern, beside
  > `Edge.basis` as the fourth. It is blocked differently and that is recorded:
  > by the **corpus**, not by what dialect three is — both current dialects
  > already define counted attributes the model has no field for, so a scenario
  > carrying one in two dialects would measure the disagreement immediately,
  > subject to `FIXTURES.md` §5.1.
  >
  > ## 3. `SPEC.md` §3.7's `source` catch-all is corrected and asserted
  >
  > The catch-all read *"everything else — the offending fragment, verbatim"*
  > and was **false for three of the ten codes it covered**:
  > `missing_timestamp` and `payload_parse_failed` carry no fragment at all, and
  > `ordering_cycle` carries spanweave node ids, which is derived output.
  >
  > **Fixing it needed no decision, so it did not halt.** The correction makes
  > the document *less* claiming than it was: three rows added for what those
  > codes actually carry, the catch-all narrowed to "as the type it arrived
  > as", and the two shapes it still leaves open named in prose
  > (`unknown_span_kind` carries the kind string *or* the whole record;
  > `nonmonotonic_time`'s array is assembled from two reported values). §3.7
  > now says explicitly that these rows state what the library emits and are
  > **not** a vocabulary adapters are held to — no second implementation has
  > agreed with them, so stating one would be 3.2's defect inverted.
  >
  > **Asserted, because a table nothing checks is how this happened.** Three
  > checks in `tests/test_codes.py`, each verified by planting: a `null` row
  > that starts carrying a fragment, a code carrying nothing whose row claims
  > one, and `ordering_cycle`'s source being node ids of its own graph. The
  > table's older direction — *declared shapes ⊆ real codes* — passes a wrong
  > shape, which is why it caught nothing.
  >
  > **Left alone deliberately:** `read.py` has an unreachable defensive branch
  > that would emit `malformed_record` with a parsed document rather than a
  > `str`. Recorded in `CONTRACTS.md` F-E, not in `SPEC.md`, because the spec
  > should describe what the library does rather than what an unreachable
  > branch would.
  >
  > ## And one thing the re-measurement caught inside 3.2 itself
  >
  > Correcting §3.7 changed what three probes break, so the whole sweep was
  > re-run. That recount found a **false sentence in `CONTRACTS.md` as
  > approved**: it said "nine of these twenty-five go red in exactly one test,
  > and in seven of the nine that one test is the expected-graph comparison".
  > The real figures are **fourteen** and **eight**. Corrected, with the
  > correction left visible in the document — a prose count that nobody
  > recomputes is the same species as an unstated field that nobody asserts,
  > occurring inside the file written to find it. The eleven green fields were
  > unchanged by the re-run.

---

### `[consumers]`

Both consumers live in `examples/`, consume **committed fixtures only**
(`ENVIRONMENT.md`: `examples/` may not touch the network), and change **nothing**
under `spanweave/`. Every want is a finding, classified by `PREDICTIONS.md`'s
binding test — the 2.3/2.4 discipline, which is why 2b produced nine findings
instead of nine patches.

**Better than either, and still true:** a consumer chosen by a stranger is worth
more than both of these together, because these are the uses already believed to
work and `PREDICTIONS.md` exists because *the designer also picks the exam*.
Finding a stranger is a human act, not an agent task. If one appears, their
consumer's findings go in the exit record beside these and carry more weight.

- [x] **3.3 Trajectory dumper.** `[consumers]` Tests `PREDICTIONS.md` P2.
  Flatten a run into an ordered call/result transcript an eval harness could
  read. It walks `parent` + `call_result`, reads payloads across all five states,
  and — per blocker 2 — names an unfulfilled call's tool from
  `Diagnostic.source["operation"]`, **in one line and the same line in both
  dialects**. If it needs to walk `outputs.value[...]` to get that name, the O1
  remedy did not land and that is the finding.

  P2 predicts most consumers collapse the five payload states to "did I get a
  string or not". This consumer is the test: it must decide, per state, what a
  transcript line says, and record which distinctions it actually used. An unused
  state is P2 confirmed-as-harmless; a **wanted-but-absent** state
  (`sampled_out`, `deferred`, `elided_by_option`) is **WORSE** and a shape
  failure.

  *Done when `uv run python -m examples.trajectory_dump <fixture>` prints an
  ordered transcript for a committed fixture in **both** dialects, the two
  outputs agree where the canonical graphs agree, output is byte-identical on
  re-run, `git diff --stat spanweave/` is empty for this task, and `make check`
  is green.*
  **HALT** — **a human marks P2**, in a file the agent must not edit
  (`AGENT.md`). Record the findings; do not describe an outcome in their place.
  *Artifact for the decision:* the findings record, the transcript for one
  fixture in both dialects, and — per state — whether the consumer used the
  distinction or collapsed it.

  **Cut order: cut this one first** (`ROADMAP.md` Phase 3 cut list, item 1, **as
  corrected in the blockers section above** — the list's own order is wrong).
  Cutting it defers P2's Phase 3 evidence; P2's predicted outcome is
  REFUTED-as-harmless with no model consequence, which is what makes it the
  cheaper of the two to lose. Record the cut and say P2 is unmarked because of it.

  > # 3.3 record — the trajectory dumper, and what it could not exercise
  >
  > `examples/trajectory_dump/` (new, `__init__.py` + `__main__.py`) +
  > `tests/test_example_trajectory_dump.py` (new, 57 tests). `make check` green
  > (**1392 passed, 2 skipped**; +57 from this file), `make gates` green,
  > `make conformance` green (419), `review_corpus.py` exit 0.
  > **`git diff --stat spanweave/` is empty.** No fixture was authored, no
  > `expected/graph.json` was touched, `canonical()` was not weakened, and no
  > dependency was added.
  >
  > ## The gate — zero shape changes, and it held
  >
  > **No new field, `NodeKind`, `EdgeKind`, warrant, `Payload` state,
  > `Diagnostic` code or query primitive was wanted.** The consumer is built
  > entirely from what `spanweave/__init__.py` already exports, and every
  > question it had to answer it answered from an existing field. The findings
  > below are **two bounds on evidence, one spec gap, and two observations**;
  > each carries its classification explicitly rather than being left to read as
  > one. The spec gap (F-2) is not a gate failure and does not become one: the
  > gate measures what a consumer **could not express**, and F-2 is a fact the
  > model expresses and no document states — O1 is the worked precedent for
  > that distinction, and unlike O1 this one carries no shape cost.
  >
  > That is the gate passing, which is what this phase expects. It is *not*
  > evidence that the model is general — it is evidence that **this** consumer,
  > chosen by the same process that built the model, needed nothing new
  > (`PREDICTIONS.md`, *the designer also picks the exam*).
  >
  > ## Blocker 2 — the O1 remedy landed, measured rather than asserted
  >
  > The tool of a call that never ran is read in **one line**
  > (`_asked_for`: `diagnostic.source.get("operation")`), and it is **the same
  > line in both dialects**. No payload is walked. Asserted two ways:
  > `test_the_tool_of_an_unfulfilled_call_is_read_off_the_diagnostic` passes a
  > bare `Diagnostic` with no graph behind it — if the name needed
  > `outputs.value[...]` it could not pass at all — and the transcripts below
  > carry the identical line in both dialects.
  >
  > ```
  > openinference                            otel_genai
  >   2    llm demo-model   [s1] ok  0.800s    2    llm demo-model   [s1] ok  0.800s
  >          ! asked for lookup — nothing ran         ! asked for lookup — nothing ran
  >   3    tool other   [s2] ok  0.800s        3    tool other   [s2] ok  0.800s
  >          ! no call in this trace asked           ! no call in this trace asked
  >            for this                                for this
  > ```
  >
  > The full pair for `unpaired_tool_call` differs on exactly three things: the
  > source path, the two `dialect-local:` lines, and the payload content the
  > scenario declares dialect-varying. Nothing else.
  >
  > ## P2 — the per-state record. **Do not read an outcome off this; a human
  > marks P2.**
  >
  > The consumer decides per state rather than calling `Payload.has_content` —
  > which is itself P2's predicted collapse, since it answers True for `present`
  > and `truncated` and False for the other three. The table
  > (`STATE_RENDERINGS`) splits what a reader **branches on** (`availability`,
  > `complete`) from what it **prints** (`reason`), because that is the only way
  > to say "used" without inflating it.
  >
  > | state | availability | exercised on the corpus |
  > |---|---|---|
  > | `present` | `content` | 92 payloads |
  > | `empty` | `none` | 4 |
  > | `absent` | `unavailable` | 114 |
  > | `redacted` | `unavailable` | 2 |
  > | `truncated` | `content`, `complete=False` | **0** |
  >
  > A sixth rendering exists and is **not** a sixth state: `present` with
  > `value is None` (`SPEC.md` §3.3's parse failure) is reached from an existing
  > state plus an existing field, 2 payloads. It was expressible; it is recorded
  > because "the consumer needed a distinction" and "the model lacked one" are
  > different claims.
  >
  > **Measured by perturbation, not by reading** — 3.2's instrument, 20 runs,
  > one directed collapse each (`a` re-rendered as `b`, whole-corpus sweep
  > re-run and diffed). **Pinned as a test** at the follow-up, not left in
  > prose: `test_the_perturbation_counts_in_the_3_3_record_still_hold` and
  > `test_the_two_named_collapses_are_the_ones_the_record_names` recompute it
  > every run, which is what the first version of this figure lacked.
  >
  > - **14 of 20 collapses change the branch** a reader acts on, and 16 change
  >   the output at all. `absent`↔`empty` is among them, which is `SPEC.md`
  >   §3.3's central claim holding up under a consumer that had a reason to
  >   care.
  >
  >   > **This figure was wrong in the record as first written** — it read *"8
  >   > of 20"*, which is the count off an earlier *undirected* run of the same
  >   > sweep, carried across when the measurement was redone directionally. Two
  >   > of the twenty change only the wording and four change nothing, so 14 is
  >   > the branch count and 16 the any-change count. Corrected on
  >   > re-measurement against the final code, with the correction left visible:
  >   > a prose count nobody recomputes is the same species as an unstated field
  >   > nobody asserts — which is the defect 3.2's own follow-up caught inside
  >   > `CONTRACTS.md`, occurring here one task later in the file written to
  >   > report it.
  > - **`absent` read as `redacted` (and the reverse) changes only the printed
  >   reason.** This consumer puts both on `unavailable`, so a harness branching
  >   on `availability` cannot tell them apart. Recorded as evidence in P2's
  >   direction on that one pair, not hidden.
  > - **All four `truncated` collapses change nothing at all.** Not "unused" —
  >   *unexercised*: no committed trace contains one, so the distinction never
  >   had the opportunity to be used or refused.
  >
  > **Why `truncated` is zero, and why that is structural rather than a corpus
  > gap to fill:** neither shipped adapter can emit it.
  > `spanweave/adapters/openinference.py` says so in its module docstring — the
  > dialect signals redaction with a marker string and has no truncation signal
  > — and the GenAI convention states none either. So a fixture could only
  > produce one by being written to. **Per 3.1's re-scoped run-loop step 3, that
  > would be the consumer setting its own exam, and it was not done.**
  >
  > **The `WORSE` condition was not met.** No state the enum lacks was wanted:
  > `sampled_out`, `deferred` and `elided_by_option` never came up, and nothing
  > this consumer needed to say about a payload was unsayable.
  >
  > ## What the dumper reads, and what that bounds
  >
  > **All 41 committed traces**: 38 conformance renderings (21 scenarios — 17 in
  > both dialects, 4 in `openinference` only) and **all 3 captured traces**. 39
  > transcribe; **2 are refused** and reported rather than raised —
  > `duplicate_span_ids` in both dialects, `DuplicateNodeIdError`
  > [`duplicate_node_id`], which is the fixture doing its job.
  >
  > All 7 `NodeKind`s, all 4 explicit `EdgeKind`s and 9 of the 12 seed
  > diagnostic codes appear. **What it did not exercise is the bound**, and it
  > is the same species of bound `nodes[].name` turned out to need:
  >
  > - **`chain`, `retriever` and `embedding` appear only in single-dialect
  >   scenarios.** Their transcripts were never cross-dialect compared, by this
  >   consumer or by anything else.
  > - **`link` edges appear only in single-dialect renderings** — `span_links`
  >   (`openinference` only) and the captured `genai_workflow` (`otel_genai`
  >   only). So `links_to` / `links_outside` are pinned within a dialect and
  >   compared across none. This is 3.2's follow-up finding arriving from the
  >   consumer side: `span_links` is the blocked scenario, and it is blocked by
  >   2.16's `invoke_workflow` → `chain` decision, not by link support.
  > - **`redacted` is `openinference`-only by construction**, since the
  >   `otel_genai` adapter has no redaction signal to read. Its 2 payloads are
  >   one scenario in one dialect.
  > - **`duplicate_source_id`, `multi_trace_input` and `malformed_record` never
  >   appear.** No transcript was produced under them.
  > - **`usage` is not read at all.** That is 3.4's consumer, deliberately; this
  >   one produces no evidence about P1.
  >
  > ## Findings — two bounds, one spec gap, two observations
  >
  > **Classified at review**, and the classifications are the human's: F-1 no
  > want and no classification, a bound; **F-2 SPEC GAP**; F-3 a bound and not a
  > proposal. The gate is unaffected in every case — a spec gap is not a shape
  > change (`PREDICTIONS.md`, and O1 is the worked precedent).
  >
  > ### F-1 (bound). `Node.name` is the transcript's natural label, and the one
  > field the equivalence claim has never compared
  >
  > A transcript wants a short human label per step. The obvious field is
  > `Node.name`; it is also the field 16 of 17 two-dialect scenarios declare
  > dialect-varying, so the corpus has never compared it (`CONTRACTS.md` F-B).
  > This consumer therefore keys on `kind` + `operation` and demotes `name` to a
  > `dialect_local` block — arrived at independently, and it lands on exactly
  > what the corpus declares.
  >
  > The cost is real and is not a model failure: where `operation` is `None` —
  > every `agent` span, every `unknown` node — the portable label degrades to
  > the bare kind, so two sibling agent spans read identically and are told
  > apart only by their node id. The field that would distinguish them is the
  > dialect-varying one.
  >
  > **No want, and no classification.** Nothing new is needed; the consumer
  > chose a different existing field, and there is therefore nothing to
  > classify — recorded as a **bound on the equivalence claim**, beside F-3 and
  > 3.2's own `nodes[].name` bound (F-B), which are the same fact reached three
  > ways. **The 2.10 boundary check settles it:** `nodes[].name` does cross the
  > schema boundary, but declaring it dialect-varying changes neither its type
  > nor its value, so there is **no shape cost**.
  >
  > One consequence stays live for 3.8, and is a docs item rather than a
  > finding: the fact that `name` does not agree across dialects lives in
  > `FIXTURES.md` §4 and `CONTRACTS.md` F-B, and **neither ships in the wheel**
  > (`[tool.hatch.build] packages = ["spanweave"]`), so a stranger installing
  > `0.9.x` gets `name` and no warning.
  >
  > ### F-2 (SPEC GAP). Nothing states what a `Diagnostic` is scoped to, or
  > which codes bear on ordering — 2.4's F7, with independent evidence
  >
  > Building the transcript found it was under-reporting, twice, and both had
  > the same root. A transcript **is an ordering**, so a diagnostic that bears
  > on ordering qualifies the whole artifact — and `cyclic_parents`'
  > `ordering_cycle` was being dropped entirely, because it carries no
  > `node_id`. `clock_skew`'s `nonmonotonic_time` was likewise invisible next to
  > a step printing `-0.500s`.
  >
  > Both are fixed (`qualifiers`, `notes`, and three `limit:` lines printed
  > **before** the steps — a reader who learns the order is untrustworthy after
  > reading it has learned it too late). What the fix required is the finding.
  > The consumer learns "graph-scoped" from `node_id is None` **by
  > observation**, and — the sharper half — it learns which codes bear on
  > ordering by **reading `SPEC.md` §3.7's prose and hard-coding three code
  > strings** (`ORDERING_CODES = {"ordering_cycle", "missing_timestamp",
  > "nonmonotonic_time"}`). **It depends on a document, not on an API.** A
  > consumer that re-reads §3.7 after a code is added gets it right; one that
  > does not gets it silently wrong, and nothing in the schema or the types can
  > tell it which it is.
  >
  > **This is 2.4's F7** — *nothing states which diagnostic codes are
  > node-scoped* — classified `operational` there only because the spec-gap
  > category did not yet exist, and named in `PREDICTIONS.md`'s spec-gap
  > definition as the candidate to re-read against it. **This is that re-read,
  > and it carries independent evidence**: a second consumer, with a different
  > job, hit the same gap without reference to the first. F7 came from a
  > counting rollup asking which codes it could attribute to a node; this came
  > from an ordered transcript asking which codes invalidate an order. Two
  > consumers, one unstated fact.
  >
  > **Why SPEC GAP is the right category, against the definition as written.**
  > The need is expressible with **no** new field, `NodeKind`, `EdgeKind`,
  > warrant, `Payload` state, `Diagnostic` code or query primitive — `node_id`
  > already carries the scope and `code` already carries the identity. It is
  > therefore not shape. It is not operational either: it changes nothing about
  > what you *keep* or *how you get it*. What is missing is that **no document
  > states it**, which is the category exactly.
  >
  > One refinement, because the definition's wording does not line up in one
  > respect and forcing it would be the thing this file exists to prevent. The
  > definition says the remedy is *"a spec change plus an adapter change"*. Here
  > **the remedy is spec-only**: `node_id` is already populated correctly, so no
  > adapter has to start emitting anything. That makes this a *cheaper* instance
  > than O1, not a worse-fitting one — and the ordering half is the cleaner fit
  > of the two, since nothing anywhere populates "this code bears on ordering".
  >
  > **The 2.10 amendment was checked and does not bite.** `diagnostics[].node_id`
  > and `diagnostics[].code` both cross the schema boundary, so the check is
  > required — and stating what they mean changes neither type nor value.
  > **No shape cost, and no halt.** Unlike O1, whose remedy changed
  > `Diagnostic.source`'s serialized type, this one changes nothing that is
  > serialized.
  >
  > **Not resolved here.** The remedy is a `SPEC.md` §3.7 change, which is a
  > spec conversation and not this task's diff. Recorded for the human, with the
  > `CONTRACTS.md` row it corroborates (`diagnostics[].node_id`, *Relies on*).
  >
  > ### F-3 (bound). The captured matched pair disagrees on `status`, and the
  > conformance corpus cannot surface it **by construction**
  >
  > Transcribing `openai_tool_call.jsonl` and `genai_tool_call.jsonl` — the
  > matched pair of the same tool-using conversation
  > (`fixtures/captured/README.md`) — the two agree on step count, order, kind,
  > `operation`, depth, `call_result` pairing and every payload **state**, and
  > disagree on `status`:
  >
  > | span | `openinference` | `otel_genai` |
  > |---|---|---|
  > | agent | `unset` | `unset` |
  > | llm (both turns) | **`ok`** | **`unset`** |
  > | tool | `unset` | `unset` |
  >
  > Read back from the raw records: the OpenInference instrumentor sets
  > `status: "OK"` on LLM spans and the GenAI instrumentor leaves them `"UNSET"`.
  > Both runs succeeded, so this is a property of the two instrumentors, not of
  > the two runs — with the honest caveat that they are **two separate captures
  > of two separate runs**, so it is strong evidence and not a controlled
  > comparison.
  >
  > Why it matters: `canonical()` **compares `status`**, and §4.4's declaration
  > mechanism covers `name`, one `attributes` key, and payload `value`/`mime` —
  > **not `status`**.
  >
  > **The structural reason the corpus cannot show it.** Both renderings of a
  > conformance scenario descend from **one `scenario.md`**, which fixes the
  > status before either dialect file is written. A hand-authored pair can only
  > disagree where its author knew to make it disagree, so a real instrumentor
  > disagreement on a field nobody suspected is **invisible to the conformance
  > corpus by construction** — not missing from it, unreachable in it. That is
  > the same shape as `FIXTURES.md` §5.1's rule (transcribe a rendering from a
  > captured trace, never write it from a reading of the dialect), seen from the
  > other side: §5.1 stops a rendering from being wrong, and cannot make a pair
  > disagree about something its author did not anticipate.
  >
  > **This is the second bound found by reading captured traces rather than the
  > corpus**, and it belongs with the first. The first is F-1/F-B — `name`,
  > which the corpus handles by declaration; this one the corpus cannot reach at
  > all. Both say the same thing about where the remaining evidence has to come
  > from, and both are arguments for the third dialect being *run against real
  > captures* rather than rendered (`ROADMAP.md` Phase 4).
  >
  > **Not a want, and explicitly not a proposal to make `status` declarable** —
  > widening the erasable set is exactly the move `FIXTURES.md` §4.4 forbids for
  > `state`, and proposing it here under launch pressure would be that
  > rationalization. It is a bound, and a human call.
  >
  > ### F-4 (observation). The transcript compares diagnostics per node, and the
  > two dialects still agree
  >
  > `canonical()` compares diagnostics by **code and global count**
  > (`FIXTURES.md` §4). This consumer's `notes` are the same codes **scoped to a
  > node**, and the cross-dialect test compares them — so it asserts something
  > strictly stronger than the corpus does, on every two-dialect scenario, and
  > it passes. Pinned in
  > `test_the_transcript_compares_diagnostics_per_node_and_they_still_agree`,
  > with a non-vacuity floor so it cannot go quiet.
  >
  > ### F-5 (observation). Declared `data` edges were read; none was ever wanted
  > inferred
  >
  > For 3.5, stated plainly rather than left to silence: the transcript shows
  > `data` edges **the telemetry declared** (`⇒ feeds …(declared)`), all
  > `warrant=explicit`, and **never compares two payload values to decide that
  > one flowed into the other**. The consumer did not want
  > `--infer-data-edges` and had no occasion to. Per `PREDICTIONS.md` P3 and
  > 3.5's own wording, **that is not a refutation** — P3's friction never had the
  > opportunity to occur here. `OPEN_QUESTIONS.md` §7 is untouched.
  >
  > ## Divergences from the task as written
  >
  > - **The transcript grew two things 3.3 did not name** — graph-scoped
  >   qualifiers and per-node diagnostic notes (F-2), and `link` targets
  >   including the ones outside the trace (§4.0). Both were found by running
  >   the thing, both use existing fields, and leaving them out would have made
  >   the consumer look like it needed less than it did.
  > - **`ENVIRONMENT.md`'s `examples/` line was left alone.** It still reads
  >   *"the confirmatory ones in Phase 3"*, which is now half-true. That is
  >   3.8's docs truth pass, and 3.1's precedent — do not write a contract line
  >   ahead of its condition — cuts the same way in reverse. Named here so it is
  >   not rediscovered as a surprise.
  > - **One stale line was found in the *other* example and not fixed.**
  >   `examples/fleet_aggregate/__main__.py` still prints *"...by the tool it
  >   asked for: not available (see limit below)"* in its text report, though
  >   `by_tool` has been populated since the O1 remedy landed at 2.10 and the
  >   JSON form carries it. It is a rot in a Phase 2 artifact, outside this
  >   task's diff, and it is recorded rather than silently swept.
  >
  > ## Definition of done
  >
  > - [x] `uv run python -m examples.trajectory_dump <fixture>` prints an
  >       ordered transcript for a committed fixture in **both** dialects.
  > - [x] The two outputs agree where the canonical graphs agree — asserted for
  >       every two-dialect scenario, using the corpus's own
  >       `expected/comparison.json` declarations rather than a list written in
  >       the test.
  > - [x] Byte-identical on re-run, and identical under reversed input order.
  > - [x] `git diff --stat spanweave/` empty for this task.
  > - [x] Per state, whether the consumer used the distinction or collapsed it —
  >       measured by perturbation, and separated from whether the corpus ever
  >       exercised it.
  > - [x] `make check` green.

  > # 3.3 follow-ups — the review's rulings, and one rot fixed
  >
  > Worked in the same session, after the human ruled on F-1, F-2 and F-3.
  > `make check` green (**1395 passed, 2 skipped**), `make gates` green,
  > `make conformance` green, `review_corpus.py` exit 0. Nothing under
  > `spanweave/` changed. `PREDICTIONS.md` untouched.
  >
  > ## 1. The three findings are classified, and the classifications are the
  > human's
  >
  > **F-1 — no want, no classification, recorded as a bound.** The 2.10 boundary
  > check settles it: `nodes[].name` crosses the schema boundary, and declaring
  > it dialect-varying changes neither type nor value, so there is no shape
  > cost. It now sits beside F-3 and 3.2's `nodes[].name` row (`CONTRACTS.md`
  > F-B) as one of three routes to the same bound.
  >
  > **F-2 — SPEC GAP.** 2.4's F7, which `PREDICTIONS.md`'s spec-gap definition
  > names as the candidate to re-read once the category had been exercised. This
  > is that re-read, and it carries **independent evidence**: a second consumer,
  > with a different job, hit the same unstated fact without reference to the
  > first. F7 came from a counting rollup asking which codes it could attribute
  > to a node; this came from an ordered transcript asking which codes
  > invalidate an order.
  >
  > The sharpest part is recorded as the sharpest part: the consumer
  > **hard-codes three code strings read out of `SPEC.md` §3.7's prose**
  > (`ORDERING_CODES`). *It depends on a document, not on an API.* A consumer
  > that re-reads §3.7 after a code is added gets it right; one that does not
  > gets it silently wrong, and nothing in the schema or the types can say which.
  >
  > **The 2.10 amendment does not bite.** `diagnostics[].node_id` and
  > `diagnostics[].code` both cross the schema boundary, so the check was
  > required — and stating what they mean changes neither type nor value. **No
  > shape cost, no halt**, and unlike O1 nothing serialized changes.
  >
  > One refinement is recorded rather than smoothed over: the definition says a
  > spec gap's remedy is *"a spec change plus an adapter change"*, and here the
  > remedy is **spec-only** — `node_id` is already populated correctly, so no
  > adapter has to start emitting anything. A cheaper instance than O1, not a
  > worse-fitting one, and the ordering half is the cleaner fit of the two since
  > nothing anywhere populates "this code bears on ordering".
  >
  > **F-3 — a bound, with its structural reason now stated.** Both renderings of
  > a conformance scenario descend from **one `scenario.md`**, which fixes the
  > status before either dialect file is written. A hand-authored pair can only
  > disagree where its author knew to make it disagree, so a real instrumentor
  > disagreement on a field nobody suspected is **invisible to the conformance
  > corpus by construction** — not missing from it, unreachable in it. F-3 is
  > named as the **second bound found by reading captured traces rather than the
  > corpus**, beside F-1/F-B, and both are recorded as arguments for the third
  > dialect being *run against real captures* rather than rendered
  > (`ROADMAP.md` Phase 4).
  >
  > The gate section is amended to match, and says why a spec gap is not a gate
  > failure: the gate measures what a consumer **could not express**, and F-2 is
  > a fact the model expresses and no document states.
  >
  > ## 2. The `fleet_aggregate` rot, fixed and pinned
  >
  > `examples/fleet_aggregate/__main__.py` printed *"...by the tool it asked
  > for: not available (see limit below)"* while the JSON form carried a
  > populated `by_tool` — false since the O1 remedy landed at 2.10 — and pointed
  > at a `limit:` that is only emitted when a dialect named no tool, so the
  > pointer resolved to nothing too. A document making a false statement about
  > the library, in the one example a stranger is most likely to run.
  >
  > Fixed: the text form prints the `by_tool` table exactly as it prints
  > `by_model`, and the column width now accounts for tool names.
  >
  > **Pinned, because a stale line is what happens when nothing compares the two
  > forms.** `test_the_text_report_states_every_by_tool_count_the_json_form_carries`
  > reads `--format json`, reads the text report, and asserts the text carries
  > every `by_tool` count the JSON does. **Verified by planting**: restoring the
  > old line turns it red, and the count comparison was checked non-vacuous
  > (`by_tool == printed == {"lookup": 1}`) rather than assumed.
  >
  > This is the same species as §3.7's catch-all at 3.2 — a statement nothing
  > checked, found by something else having to agree with it — one layer out, in
  > an example rather than a spec.
  >
  > ## 3. One count in the 3.3 record was wrong, and is now executable
  >
  > Re-measuring against the final code before drafting P2's wording found the
  > record's perturbation figure was **wrong**: it read *"8 of 20 collapses
  > change the branch"*, carried across from an earlier *undirected* run of the
  > same sweep. The directed figures are **14** on the branch and **16** on any
  > change, with 2 wording-only and 4 no-change. Corrected in place with the
  > correction left visible.
  >
  > **And pinned, because prose was the problem.** The sweep now runs as two
  > tests (`test_the_perturbation_counts_in_the_3_3_record_still_hold`,
  > `test_the_two_named_collapses_are_the_ones_the_record_names`), so the
  > numbers in the record are recomputed on every `make check` rather than read.
  > This is 3.2's own follow-up finding — *a prose count that nobody recomputes
  > is the same species as an unstated field that nobody asserts* — happening
  > one task later, in the record written to report it. The remedy the second
  > time is a test rather than a correction.
  >
  > ## 4. P2's resolution wording, drafted and handed over
  >
  > Written in `PREDICTIONS.md`'s own form, carrying its scope the way P5's
  > does: what the consumer read, what it did not exercise, and that `truncated`
  > **had no opportunity to occur** rather than surviving. **Handed to the human
  > as text; `git diff PREDICTIONS.md` is empty.** The file is read-only to the
  > agent in every phase and a human marks P2.

- [ ] **3.4 Cost & latency attributor.** `[consumers]` Tests `PREDICTIONS.md` P1.
  Roll `usage` and duration up the `parent` tree, applying the **consumer's own**
  price table — the table lives in `examples/`, never in `spanweave/`, and the
  word `cost` never appears under the package (`CLAUDE.md` 1, and it is banned
  vocabulary in the neutrality gate).

  **Written to apply P1's pressure, not to demonstrate an attributor** — blocker
  1 is why. It reads `usage` and timestamps and *nothing else*, which is the
  consumer P1 describes, and it must answer the retention question with a
  measurement rather than an impression:

  - Measure resident bytes per span for a built graph, and separately with
    payloads and `RawRecord` dropped after the build, on the committed corpus.
  - Extrapolate to P1's stated 100k spans, and **label it an extrapolation**.
  - A generated load input may be used to check the extrapolation. It is a
    **load input, not a fixture**: it says nothing about what real traces
    contain, it is gitignored, it never enters `fixtures/`, and it is never
    described as captured (`AGENT.md`'s fabrication halt point).
  - Then state plainly whether the consumer **wanted** `retain_payloads=False` /
    `retain_raw=False`, or merely would have accepted it. Those are different
    findings and only the first is P1's predicted friction.

  A refutation here must carry its scope the way P5's does: *what size, what
  consumer, what was actually measured.*

  *Done when `uv run python -m examples.cost_latency <fixture>` attributes tokens
  and duration up the parent tree for a committed fixture in both dialects, the
  measurement above is recorded with its method, `git diff --stat spanweave/` is
  empty for this task, and `make check` is green.*
  **HALT** — **a human marks P1**. Same rule as 3.3.
  *Artifact for the decision:* the findings record, the memory measurement with
  its extrapolation stated as one, 2b's negative evidence and why it was not P1's
  test (blocker 1), and — if anything classified shape — the exact field,
  `NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code or query
  primitive that would have to exist.

  **Cut order: cut this one second, and only after 3.3.** `ROADMAP.md`'s list
  names it first; that ordering predates Phase 2 and is corrected above. Cutting
  it **defers P1 to Phase 4** — write that in the exit record in those words, not
  "forfeits little", because P1 then has no test anywhere in this phase and the
  freeze inherits an unmarked prediction.

- [ ] **3.5 The prediction resolution artifact — P1 through P4.** `[contract]`
  Assemble, for each of P1–P4, the evidence this phase produced, in the form the
  human needs in order to mark it. **Do not mark them. Do not touch
  `PREDICTIONS.md`** — it is read-only to the agent in every phase, and the
  file's entire value is in its timestamps.

  Per prediction, and honestly:
  - **P1** — 3.4's measurement, plus 2b's negative evidence with its scope
    (blocker 1).
  - **P2** — 3.3's per-state record. Unused ≠ unwanted ≠ missing.
  - **P3** — *neither Phase 3 consumer wants inferred `data` edges.* Say that
    plainly. A prediction whose friction never had the opportunity to occur is
    **not REFUTED by silence** — REFUTED would claim the model was more general
    than expected, and nothing here tested it. Hand the human the fact and the
    gap. P3 is also flagged in its own entry as a boundary case that must not be
    waved through on the operational technicality, and it is tracked as
    `OPEN_QUESTIONS.md` §7, which an agent may not resolve.
  - **P4** — determinism was kept regardless and the entry says to keep it
    regardless. The honest record is whether it was ever what made a consumer
    work. It was not, unless this phase shows otherwise; say so.

  *Done when the artifact names, for each of P1–P4, the evidence, its scope, and
  what the evidence cannot support — and `git diff PREDICTIONS.md` is empty.*
  **HALT** — **the human marks all four.**
  *Artifact for the decision:* the assembled evidence, one section per
  prediction.

  **Cut order: NEVER CUT** (`ROADMAP.md`, and `PREDICTIONS.md`'s own closing
  argument). It costs about an hour. "No time" can therefore never be the true
  reason it was skipped, so if it is skipped the stated reason will be schedule
  and the real reason will be that writing **WORSE** next to your own design is
  uncomfortable.

---

### `[launch]`

- [ ] **3.6 `make install-check` — prove what ships works.** `[launch]`
  `make check` runs everything under `uv run`, with the source tree on the path.
  Nothing in this repo currently builds the wheel and runs it from **outside** the
  repo, so a packaging break — a module missing from `[tool.hatch.build]`, a
  console script that does not resolve, a data file that exists in the tree and
  not in the distribution — passes every gate and fails for the first stranger.
  `tests/test_acceptance.py::test_the_installed_console_script_reports_its_version`
  looks like this check and is not: it finds the *development* install.

  Build the wheel, install it into a throwaway venv, `cd` outside the repo, and
  run `spanweave --version`, `spanweave adapters`, and a `spanweave build` over a
  fixture path.

  *Done when `make install-check` passes from a clean tree, and fails when a
  module is deliberately removed from the wheel's package list — verify both
  directions, as tasks 0.4–0.6 did for the gates.*

  **Cut order:** not on `ROADMAP.md`'s list. Cutting it means 0.9.x is published
  without any check that the published artifact runs. Do not cut it before 3.3.

- [ ] **3.7 Version to `0.9.0`, and decide what `schema_version` means while
  unfrozen.** `[launch]`
  Two things, and the second is the reason this is a halt.

  `__version__` and `pyproject.toml` go to `0.9.0` together
  (`tests/test_version.py` already pins them to each other). `SCHEMA_FROZEN`
  stays `False` — the unfrozen notice in `--help`, in `--version`, in `inspect`'s
  output and in the README is **never cut**.

  Then: `SCHEMA_VERSION` is `"0.1"`, and it was `"0.1"` before Phase 2 changed
  `Diagnostic.source`'s serialized type (blocker 2). Publishing leaves one value
  describing two contracts. The options are to bump to `"0.2"` now, or to state
  in `SPEC.md` §3.9 that `0.x` is a single unfrozen bucket that does not track
  changes and that pinning must be on the library version. Both are defensible;
  neither is the agent's call.

  *Done when the version is `0.9.0` everywhere `tests/test_version.py` checks,
  `spanweave --version` still says `UNFROZEN`, and `make check` is green.*
  **HALT** — `AGENT.md`: *any change to `schema_version` semantics*.
  *Artifact for the decision:* the list of serialized changes made since `"0.1"`
  was assigned, and, for each option, what a consumer pinning on
  `schema_version` at 0.9.x could and could not conclude.

- [ ] **3.8 The docs truth pass, before anything is published.** `[launch]`
  0.9.x is the first time these files are read by someone who cannot check them
  against the tree. Three are false today:

  - `README.md`'s **Status** section still says Phase 1 is the vertical slice and
    "a second adapter … is Phase 2". Two adapters ship.
  - `fixtures/captured/README.md` still says the directory is *"Currently empty —
    the first one lands at `TASKS.md` 1.9"*. It has held two fixtures since 2.6
    and three since 2.15. Noted at 2.15 and left for the human whose directory it
    is; it cannot ship this way. A stale claim in the one directory whose subject
    is provenance is worse than a stale claim anywhere else.
  - There is **no installation section at all**. The install instruction must be
    the one that resolves **today** — from source / from the built wheel. The
    `pip install spanweave` line lands in the same change as 3.10's publish and
    not before, because a README promising an install that 404s is the first
    thing a stranger tries.

  *Done when a test asserts each claim against the tree — at minimum, that
  `fixtures/captured/README.md` does not claim emptiness while the directory is
  non-empty, and that the README names no install command that does not resolve
  at the current published state — and `make check` is green.*

  **Cut order:** the unfrozen notice inside these files is **never cut**
  (`ROADMAP.md`). The rest of the pass is cuttable only down to *"nothing in the
  shipped docs is false"*, which is the floor, not a target.

- [ ] **3.9 The sixty-second stranger path.** `[launch]`
  `ROADMAP.md`'s exit says a stranger builds a graph from their own trace in ~60
  seconds. Verify it rather than assert it: from a clean venv, install the wheel
  3.6 built, run the README's quickstart **verbatim**, and build a graph from a
  committed fixture. Time it and record the number.

  The README's Python and shell blocks are the script. If they do not run as
  written, the README is wrong — fix the README, not the test.

  *Done when a check runs the README's quickstart blocks verbatim against the
  installed wheel and they succeed, and the elapsed time is recorded in this
  task.*

  **Cut order:** not on the list. It is the only thing that tests the exit
  criterion "a stranger can build a graph in ~60 seconds", so cutting it means
  the exit criterion is asserted rather than met — record it that way.

- [ ] **3.10 Publish `0.9.x` to PyPI.** `[launch]` **HUMAN-RUN. The agent
  prepares and stops.**
  This is the one outward-facing, credentialed, effectively irreversible step in
  the phase: a name-plus-version on PyPI cannot be reused, and a bad 0.9.0 is
  spent forever. `ENVIRONMENT.md`'s network policy has no zone for pushing to an
  external index and 3.1 adds one; the agent has no PyPI token and must not have
  one.

  The agent prepares: `uv build`, the sdist and wheel in `dist/`, 3.6's
  `install-check` green against the built wheel, the exact publish command, and
  the recommendation to push to **TestPyPI first** and install from there. It does
  not publish, and it does not add a `pip install spanweave` line to any document
  until the publish has happened (3.8).

  *Done when `uv build` produces both artifacts, `make install-check` passes
  against the built wheel, and the publish command is recorded here unrun.*
  **HALT** — credentialed, outward-facing, irreversible. A human publishes.
  *Artifact for the decision:* the built `dist/` artifacts, `install-check`
  output against the wheel, the exact command, and what is in the sdist that is
  not in the wheel.

- [ ] **3.11 Phase 3 exit record.** `[launch]`
  The mirror of 2.14, and the direct input to the Phase 4 freeze decision.
  Record:

  - **Shape changes: the count, and it must be zero.** If it is not zero, the
    model could not express what a real consumer needed, and the fix comes before
    the freeze. Classify with `PREDICTIONS.md`'s binding test **as written
    there** — including a change forced by 3.2 rather than by a consumer, which
    is a shape change but *not* a failure of this gate, and must be recorded as
    both rather than as whichever is more convenient.
  - **Every finding from 3.3 and 3.4**, with cause and classification, the way
    F1–F9 are recorded at 2.4.
  - **Every prediction's state** — marked by the human at 3.5, with what the
    evidence does and does not support. Any prediction left unmarked because its
    consumer was cut is named, with the words from that task's cut note.
  - **Everything cut**, with what it cost.
  - **The Phase 4 freeze gate as it now stands:** predictions resolved, Phase 2
    finding absorbed, real users have exercised 0.9.x, **and a third dialect
    rendered in the corpus** (`ROADMAP.md` Phase 4). Say which of the four are
    met on the day this record is written. Also carry forward the two items 2.14
    left open — the `erase`-both-sides proposal and `Edge.basis` — plus 3.2's
    unmeasured rows, so the freeze reads one list rather than three.
  - **Whether the launch met its own exit criteria**, from 3.9's measured number
    rather than from the claim.

  *Done when the record above exists, `pip install spanweave` resolves at 0.9.x
  from an environment that is not this repo, `make check`, `make conformance` and
  `make install-check` are green, and `git diff PREDICTIONS.md` is empty for
  every agent commit in the phase.*
  **HALT — Phase 3 exit, for human review, as 1.9 and 2.14 were.** Do not start
  Phase 4. **Do not freeze the schema** — it is gated on evidence this phase does
  not produce, and *never accelerate the freeze* is `ROADMAP.md`'s standing rule.
  *Artifact for the decision:* the exit record, the two consumers' findings, the
  prediction table, and the four-item freeze gate with each item's status.

## Phase 4 — Breadth, then freeze  *(provisional)*

- Further adapters (Langfuse, LangSmith, Logfire, Vercel AI SDK, OTLP JSON;
  OTLP protobuf behind the `otlp` extra).
- Contributor conformance harness: one command validates a new adapter against
  the corpus.
- `CONTRIBUTING.md` adapter walkthrough, written against a **real merged**
  adapter.
- **Freeze `schema_version` `1`; release `1.0.0`; publish the compatibility
  policy** — once predictions are resolved, the Phase 2 finding is absorbed,
  real users have exercised the schema at `0.9.x`, **and a third dialect is
  rendered in the conformance corpus**. That fourth condition is a stated gate,
  not an implication of this phase's ordering (`ROADMAP.md` Phase 4, *The third
  dialect is a freeze precondition*): all three Phase 2 contract defects were
  found by two implementations having to agree, and none by any number of tests
  written by one author against one dialect. The gate is that dialect three has
  been **run**, not that it found nothing. If a fifth adapter still forces a
  model change, the schema was not ready.
- **The permissively-typed serialized fields left unmeasured at 3.2**, with
  `Edge.basis` first — the resolution half of 2.14's freeze audit, held here
  because dialect three is its instrument.
- **Exit:** three or more contributable adapters passing conformance; schema
  frozen; `1.0.0` published.

## North star — parked

Not tasks. Streaming/tail mode, cross-trace stitching, message-level
granularity, a neutral viewer in a separate repo. Direction only; never
represented as shipped (`SPEC.md` §9).
