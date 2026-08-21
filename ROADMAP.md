# ROADMAP.md — phased plan

Each phase exits with something **runnable** and a **shareable moment**. Build in
this order; resist pulling later work forward. Behavior per `SPEC.md`,
architecture per `DESIGN.md`.

The through-line: **earn the right to be depended on before asking to be
depended on.** The schema does not freeze until a consumer the model was not
designed for has used it unchanged.

## Phase 0 — Skeleton & contract

Repo, MIT license, the doc set, `pyproject.toml`, CI, and the gates that encode
the invariants: no-network, no-unsafe-deserialization, no-`hash()`,
semantic-neutrality, no-dialect-in-builder, determinism, losslessness. Model
types (`Node`, `Edge`, `Payload`, `Usage`, `Diagnostic`, `Provenance`,
`RawRecord`) as frozen dataclasses with no behavior yet.

- **Exit:** `spanweave --version` runs; every gate fails on a deliberately
  planted violation and passes otherwise; `make check` green in CI.
- **Shareable:** none yet (internal).

## Phase 1 — Vertical slice: one dialect, end to end

Reader (JSONL + JSON array, stdin), the **OpenInference adapter**, the builder
(identity, `parent` / `call_result` / `link` / declared `data` edges, sibling
`temporal` edges, topological order, diagnostics), the `Graph` query surface,
the annotation API, canonical serialization at `schema_version` `0.1`, and the
CLI (`build`, `inspect`, `validate`, `adapters`).

Seed `fixtures/conformance/` with the scenarios in `FIXTURES.md` §3 — including
the degenerate ones — each with an expected canonical graph.

- **Exit:** `spanweave build` turns a real OpenInference trace into a graph;
  every seeded scenario passes; shuffled input is byte-identical; a captured
  (human-run) trace from a real instrumentor is committed with provenance.
- **Shareable:** the `spanweave inspect` summary of a real agent run — node kinds,
  edge kinds with warrants, honest diagnostics. First public-able artifact.

## Phase 2 — Falsify the model: second dialect + the adversarial consumer

Two independent pressures on the same question — *is this model general, or is it
just shaped like its first consumer?* — applied while nothing is frozen and every
fix is a diff.

**2a. Second dialect.** Add the **OTel GenAI** adapter and adapter
auto-detection (`detect()` + selection, `SPEC.md` §6.1). Express every existing
scenario in the second dialect and turn on the **cross-dialect equivalence
test**.

**2b. The adversarial consumer.** Build the consumer most likely to break the
model — by default a **fleet aggregator** over many traces, which attacks
`PREDICTIONS.md` P5 ("one trace = one graph"), the prediction most likely to be
a genuine *shape* failure.

It lives in `examples/` and needs only one adapter, so nothing in it waits on
2a. **Run it first and alone, not alongside 2a** — the sequencing note below is
the operative instruction, and `TASKS.md` Phase 2 encodes it as strictly serial.
**Timebox it to two days.** It does not need to be a good tool; it needs to be
real enough to hit the shape question. Whatever it teaches in two days is the
finding.

**Sequencing: start 2b first.** It is two days against a phase measured in
weeks, and its finding changes what 2a should be testing. If the aggregator
turns P5 into a shape failure, the model changes — and every dialect-two
rendering written before that change has to be rewritten after it. Two days of
de-risking buys the larger workstream a stable target.

This phase exists to break things. Expect the model to be wrong somewhere.
**Model changes discovered here are cheap and expected; the same changes after a
schema freeze are not** — which is precisely why the adversarial consumer runs
here rather than next to the launch.

- **Exit:** both dialects produce identical canonical graphs for every scenario
  still in scope; the adversarial consumer has run and P5 is resolved in
  `PREDICTIONS.md`; every model change forced by either pressure is recorded in
  `TASKS.md` with its cause. Detection, if kept, picks the right adapter with no
  ambiguity; if deferred, `--adapter` is required and the deferral is recorded.
- **Shareable:** "the same run, two instrumentors, one graph" — the diff that
  isn't.

## If Phase 2 slips — the cut order (decided in advance)

Phase 2 is the heavy phase, deliberately: it is where breakage is cheap, so it is
where breakage should happen. But that also makes it where schedule pressure
lands, and unlike Phase 3 it has no launch date forcing discipline — which makes
it *easier* to cut sloppily, not harder.

The governing principle: **scenarios differ in information value.** Rendering
eighteen scenarios in a second dialect is volume work, and the volume is not
uniformly informative. Dialects broadly agree about basic structure — everyone
has spans, parents, and tool calls. They diverge sharply about how they signal
*absence*, truncation, redaction, errors, and unmatched calls. So the degenerate
scenarios carry most of the falsification signal, and the happy-path structural
ones carry least.

**Cut in this order:**

1. **`detect()` auto-selection.** Require `--adapter` explicitly and defer
   detection to Phase 4. It is ergonomics; it produces **zero evidence** about
   whether the model is general. It is the only item in this phase that can be
   removed without losing information.
2. **Structural scenario renderings in dialect two**, in reverse order of
   expected disagreement: `declared_data_edge`, `span_links`,
   `retriever_and_embedding`, `nested_agents`, `parallel_tools`,
   `single_tool_call`. Each cut costs a little coverage and no principle.
3. **Nothing else.**

**Never cut:**

- **`llm_tool_llm` in dialect two.** `call_result` pairing is the structural
  relation dialects most disagree about, and the one an adapter is uniquely able
  to get wrong (`ADAPTERS.md` §3). It is a happy-path scenario that behaves like
  a degenerate one. It also carries the declared `data` edge added in Phase 1
  (`SPEC.md` §4.2.1), which did not exist when this list was written.
- **`parallel_tool_calls` in dialect two.** Added during Phase 1 review, after
  this list was written, so the list was silent about it. Classified never-cut
  on the list's own grounds: it is the multi-call form of the same
  `call_result` pairing, and the shape that made a real captured trace disagree
  with the corpus.
- **The degenerate renderings** — `missing_payloads`, `empty_payload`,
  `redacted_payload`, `unpaired_tool_call`, `orphan_parent`, `clock_skew`,
  `unknown_kind`, `malformed_payload_json`. This is where dialect conventions
  actually diverge and where `PREDICTIONS.md` P2 gets tested. Cutting these keeps
  the pleasant half of the corpus and discards the informative half — the exact
  inversion this file exists to prevent.
- **The equivalence harness itself.** Without it, renderings are decoration.
- **The captured trace for the second adapter.** Hand-authored fixtures prove the
  adapter matches *our understanding* of a dialect; only a captured one proves it
  matches the instrumentor (`FIXTURES.md` §6). Skipping it means shipping an
  adapter validated entirely against our own assumptions.
- **2b's timebox and P5's resolution.** Two days and a few minutes respectively.
  Cutting a timeboxed item means the box was never real.

**Never extend:** 2b's timebox — the symmetric rule to *never accelerate the
freeze*. A box that grows because the work got interesting is not a box. If the
aggregator is still producing findings at day two, that is a Phase 4 follow-up
with its own scope, not a reason to blow through the limit.

## Phase 3 — Confirm, package, launch

With falsification done in Phase 2, this phase is confirmation and packaging —
bounded work, no open-ended discovery sitting next to a launch date.

**Confirmatory consumers.** Two more in `examples/`, both expected to work:

1. **Trajectory dumper** — flatten a run into an ordered call/result transcript
   for an eval harness.
2. **Cost & latency attributor** — roll token usage and duration up the `parent`
   tree, applying the consumer's own price table. Tests `PREDICTIONS.md` P1.

These are the comfortable picks — uses the model was already believed to handle.
Their value is demonstrative (example code, documentation-by-instance), not
evidentiary. **Better than either: a consumer chosen by a stranger.** One person
who didn't design the model is worth several who did.

**Publish without freezing.** Ship `0.9.x` to PyPI with `schema_version` `0.x`
and a loud unfrozen notice in the README and `--help`. This is the one item that
must not be conflated with the freeze: publishing is reversible and a
pre-release says so; **freezing is not.** Decoupling them takes the only
irreversible decision off the launch's critical path and buys real adoption
feedback before making it.

**Freeze later, on evidence.** `schema_version` `1` and `1.0.0` land when the
predictions are resolved, the adversarial finding is absorbed, and real users
have exercised the schema — not when the calendar says launch.

### The gate

- **Shape changes: zero.** A new field, `NodeKind`, `EdgeKind`, warrant,
  `Payload` state, `Diagnostic` code, or query primitive means the model could
  not express what a real consumer needed. That is a model failure, fixed
  **before** the freeze.
- **Operational options: permitted, additive, recorded.** Retention, multi-trace
  handling, laziness — what you keep or how you get it, never what a graph *is*.
- The distinction is defined in `PREDICTIONS.md` and is **binding as written
  there**. Widening it mid-phase to accommodate whatever happened is the exact
  rationalization that file exists to prevent.

- **Exit:** both consumers work with zero shape changes; **every prediction
  marked** CONFIRMED / REFUTED / WORSE; `pip install spanweave` works at `0.9.x`;
  a stranger can build a graph from their own trace in ~60 seconds.
- **Shareable:** the launch. Three unrelated consumers, one library, no forks —
  and a public record of what was predicted to break, with outcomes.

## If Phase 3 slips — the cut order (decided in advance)

Written now, before the pressure exists, because under deadline pressure people
cut the work whose output is *information* and keep the work whose output is
*artifacts*. Artifacts are visible; information isn't. That instinct is backwards
when the information gates an irreversible decision.

**Cut in this order:**

1. **Confirmatory consumer 2**, then **consumer 1**. They are reproducible after
   launch at nearly zero cost and nothing about them is time-locked. Expected to
   pass, so cutting one forfeits little.
2. **The CONTRIBUTING adapter walkthrough** — already deferred to Phase 4, where
   a real merged adapter exists to write it against.
3. **The compatibility policy** — it only binds once the schema freezes, and the
   freeze is no longer on this phase's critical path.

**Never cut:**

- **The prediction resolutions.** They cost about an hour: five entries, three
  possible markers. "No time" can never be the true reason to skip them, so if
  they get dropped, the stated reason will be schedule and the real reason will
  be that writing **WORSE** next to your own design is uncomfortable. A
  `PREDICTIONS.md` with predictions and no outcomes is *worse than not having
  written it* — a visible promise of rigor, unkept, and read as theater by
  exactly the audience it was meant to persuade.
- **The Phase 2 adversarial finding.** Already absorbed by then; re-opening it
  under launch pressure is how a shape failure gets reclassified as operational.
- **The unfrozen-schema notice.** Shipping without it converts a reversible
  pre-release into an implied commitment.

**Never accelerate:** the freeze. If the schedule is tight, `0.9.x` ships and
`1.0` waits. A freeze made to hit a date is the one mistake in this project that
cannot be undone with a patch.

## Phase 4 — Breadth: the adapter flywheel, then freeze

Adapters for further dialects (Langfuse, LangSmith, Logfire, Vercel AI SDK, raw
OTLP JSON; OTLP protobuf behind the `otlp` extra). A contributor-facing
**conformance harness**: drop your dialect's rendering of each scenario in,
run one command, see whether your adapter agrees with the canonical graph.

The flywheel is deliberate: the contribution surface is *"add your
instrumentor"*, backed by a corpus that makes a correct contribution obvious and
an incorrect one impossible to merge.

Also here, because both want a real merged adapter to exist first:

- **The `CONTRIBUTING.md` adapter walkthrough**, written against an actual
  merged contribution rather than a hypothetical one.
- **The freeze.** `schema_version` `1` and `1.0.0`, once the predictions are
  resolved, the Phase 2 adversarial finding is absorbed, and real users have
  exercised the schema at `0.9.x`. Plus the compatibility policy: additive-only
  thereafter, version bump for anything breaking (`CLAUDE.md` 7).

Dialects three through six are the real test of the freeze decision. If a fifth
adapter still forces a model change, the schema was not ready — and finding that
out at `0.9.x` costs a minor release instead of a migration.

- **Exit:** three or more community-contributable adapters passing conformance;
  schema frozen at `1`; `1.0.0` published.
- **Shareable:** "your instrumentor, supported in one PR" — the corpus as the
  invitation.

## North star (parked — not promised)

Direction only. Never represented as shipped (`SPEC.md` §9).

- **Streaming / tail mode** — consuming records as a run proceeds. The insurance
  is already paid in two constraints (`DESIGN.md` §6): iterator-based reading and
  append-only per-record builder work. New work when unparked: out-of-order
  buffering and finalize-step windowing. **File-tailing needs no renegotiation of
  the no-network posture; an OTLP listener would** — that would be a deliberate
  decision, not a drift.
- **Cross-trace stitching** — linking related traces via span links into one
  graph.
- **Message-level granularity** — whether individual LLM messages become nodes
  (`OPEN_QUESTIONS.md` §2).
- **A neutral trace viewer** — rendering only, in a separate repo, consuming the
  frozen schema like anyone else.

Never in core, at any phase: semantics, severity, inferred dataflow, money,
enforcement, network (`SPEC.md` §9).
