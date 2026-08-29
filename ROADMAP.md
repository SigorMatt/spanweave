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
  isn't. *Bounded after the fact, at `TASKS.md` 3.2: the diff that isn't is a
  diff over everything `canonical()` compares **except `Node.name`**, which 16
  of the 17 both-dialect scenarios declare dialect-varying. Show the diff with
  that said, not without it.*

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

**And `1` is a fresh start, not the next term in a sequence** (`TASKS.md` 3.7,
`SPEC.md` §3.9). `0.x` is a single unfrozen bucket that never tracked changes —
two contract changes shipped under `"0.1"` and it did not move for either — so
there is no `0.1 → 0.2 → … → 1` progression for `1` to continue. The field
acquires meaning **at** the freeze and had none before it.

That has a consequence worth stating before it arrives rather than after.
**The freeze is the first real exercise of the mechanism that replaces the
version number**: `tests/serialized_shape.json`, the committed shape artifact
(`make shape`), which is what additive-only will be measured against. Until
then it has only ever guarded a schema nobody was promised. This is exactly the
pattern that has produced every contract defect in this project — a contract
nothing had to agree with until it mattered — and naming it here does not
remove it. What reduces it is the same thing that reduced it in Phase 2:
another implementation having to agree, which is why the third dialect is a
freeze precondition below. Run the tripwire against dialect three's arrival,
and prefer discovering it is wrong there over discovering it at `1.0.0`.

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
  resolved, the Phase 2 adversarial finding is absorbed, real users have
  exercised the schema at `0.9.x`, **and a third dialect is rendered in the
  conformance corpus** — see the gate below. Plus the compatibility policy:
  additive-only thereafter, version bump for anything breaking (`CLAUDE.md` 7).
  `1` is a **fresh start**: `0.x` never tracked changes, so nothing about it
  carries forward (`SPEC.md` §3.9). The freeze is also the first time
  `tests/serialized_shape.json` guards anything anyone was promised — see
  *Freeze later, on evidence* above for why that is the project's own recurring
  failure shape rather than a detail of sequencing.

Dialects three through six are the real test of the freeze decision. If a fifth
adapter still forces a model change, the schema was not ready — and finding that
out at `0.9.x` costs a minor release instead of a migration.

### The third dialect is a freeze precondition, not a nice-to-have

This phase already implies breadth-before-freeze by its ordering. **An implied
gate is one that gets skipped under launch pressure**, so it is stated here as a
condition rather than left to be inferred from the order of the bullets: the
freeze does not happen until a third dialect has been rendered across the
conformance corpus and run against the cross-dialect equivalence test.

**It comes from measured evidence, not from caution.** Phase 2 produced three
defects in the project's own contract, and all three have the same shape
(`TASKS.md` 2.14):

| Found | What the project relied on | What stated it |
|---|---|---|
| 2.8 | `canonical()` compares `Payload.mime` | nothing — absent from `FIXTURES.md` §4's Compared list for two phases |
| 2.10 | `canonical()` compares `Node.attributes` | nothing — absent for three |
| 2.10 | `Diagnostic.source` carries a specific shape per code | nothing — no test asserted it, so changing its type broke **zero** tests |

Each is a property the library depends on that no document stated and no test
asserted. None was a drafting slip: in every case the **permissive default won**
— `canonical()` keeps a field unless told otherwise, `JsonValue` permits any
shape — so the code was right, the contract was absent, and nothing was red.

The part that makes this a gate is the **discovery mechanism**, which was the
same all three times: *two independent implementations had to agree on
something.* No number of tests written by one author against one dialect finds a
defect of this species, because the author's single implementation is the only
thing the tests can be written against. A second dialect found three. A third is
the only instrument known to find the fourth.

**What satisfies the gate.** A third dialect *rendered in the corpus* — its
scenarios participating in the equivalence test — not an adapter that merely
parses its files. Declared coverage is permitted and recorded as `FIXTURES.md`
§4.3 requires; a scenario a dialect genuinely cannot express is a finding, not a
failure.

**The gate is that dialect three has been run, not that it found nothing.**
Defects it surfaces are fixed before the freeze, which is the entire point: at
`0.9.x` that costs a minor release, after the freeze it costs a migration.

**It binds the freeze, not the launch.** `0.9.x` still ships from Phase 3, on
schedule, unfrozen — nothing here moves breadth earlier or adds a condition to
publishing. Decoupling the two is what makes this affordable: the irreversible
decision waits for the evidence, and the reversible one does not.

Known already, and waiting on exactly this — **two** instances now, both caught
before they bit, both unstated and **unmeasurable by construction** with two
dialects:

| | Why it is unmeasurable today |
|---|---|
| **4. `Edge.basis`** (2.14) | a free `str`, compared by `canonical()`, adapter-supplied — and both adapter-supplied bases are invisible to the cross-dialect claim |
| **5. `Usage.extra`'s keys** (3.2) | an open key vocabulary, compared by `canonical()`, adapter-supplied and **dialect-derived verbatim** — each adapter takes its own attribute suffix, so `llm.token_count.cache_read` becomes `cache_read` and `gen_ai.usage.cache_read_input_tokens` becomes `cache_read_input_tokens` for the same concept. Two dialects would disagree, and it is `{}` on every node of every fixture in the repository, so the disagreement is unreachable |

### The gate is necessary and, for these three, not sufficient

Stated here because it is exactly the kind of thing that is otherwise discovered
*at* freeze time. **"A third dialect rendered across the corpus" satisfies the
gate as written, and still leaves both rows above where they are** unless the
conditions below also hold — and leaves a **third** thing untouched entirely,
which is not a row above but a whole class of node fields (`TASKS.md` 3.4 F-6).
That is a qualification of the gate, not a weakening of it: the gate stays a
hard precondition, and these are additional conditions on the specific fields —
and now the one field class — it was partly written to measure.

The reason is the measurement, and 3.2 sharpened it in a way 2.14 could not
have: **an adapter-supplied field is only measured when two adapters that
*chose* a value have to agree on it.** Agreement on a value neither author
chose is structural, the way the builder's four `basis` strings are — real, but
not evidence about a vocabulary.

**What would be sufficient for `Edge.basis`.** Three conditions, and only the
first is a corpus act:

1. **A `link`-carrying scenario that a second dialect can render.**
   `span_links` is the corpus's only one and is declared unrenderable in
   `otel_genai` — blocked by the `invoke_workflow` → `chain` decision
   (`TASKS.md` 2.16), *not* by link support: `fixtures/captured/genai_workflow.jsonl`
   proves the `otel_genai` adapter reads a real span link and emits an
   `EdgeKind.link` with `basis` `span.link`. Either that decision is taken, or a
   `link`-carrying scenario that does not pin `kind: chain` is authored.
2. **An adapter that has to choose a different `basis`.** Both current adapters
   take `SpanLink.basis`'s *default*, `"span.link"` (`TASKS.md` 3.2). Two
   dialects agreeing on a default measures the default, not the vocabulary. The
   measurement needs a dialect whose links come from somewhere other than the
   OTel record-level `links` field — which is a property of whatever dialect
   three turns out to be, and cannot be arranged by choosing one.
3. **For `DeclaredDataEdge.basis`, an adapter that emits one at all.** 2.14
   recorded that `otel_genai` produces none; 3.2 found `openinference` produces
   none either — both reach the same relation through `received_call_ids`, whose
   `basis` the *builder* supplies. It is a required seam field that nothing has
   ever populated, in either dialect. If dialect three also names no data
   relation with both ends on one span, that is itself the finding, and a seam
   field three dialects never populate is a candidate for removal — which is a
   **shape** change and belongs in the freeze decision rather than after it.

**What would be sufficient for `Usage.extra`.** Less, and differently: it is
blocked by the *corpus*, not by what dialect three is. Both current dialects
already define counted attributes the model has no field for; what is missing is
a scenario whose renderings carry one. A scenario exercising a non-standard
token count in two dialects would measure the disagreement immediately — subject
to `FIXTURES.md` §5.1, which forbids deriving a rendering from a reading of a
dialect rather than from observed output.

**What would be sufficient for the nine strictly-compared node fields.**
Different from both of the above, and the difference is what makes it worth
stating: for these, *rendering in the corpus buys nothing at all* — it is the
weaker half of the gate rather than an incomplete one.

`canonical()` compares nine groups of node field that `FIXTURES.md` §4.4's
declaration mechanism cannot reach — *must agree, cannot be declared to
disagree*. **Two of the nine are already known to disagree between the two real
instrumentors**: `status` (`TASKS.md` 3.3, F-3) and `usage` (`TASKS.md` 3.4,
F-6). Both were found by reading **captured** traces, by consumers with
unrelated jobs, neither looking for it. The enumeration of the nine, the
argument, and what it predicts are recorded at `TASKS.md` 3.4 F-6 and are not
repeated here; what belongs in a gate is the consequence.

The consequence is that no amount of rendering reaches them. Both renderings of
a conformance scenario descend from **one `scenario.md`**, so a hand-authored
pair can only disagree where its author knew to make it — which is precisely
what nobody knew in either case. A third dialect rendered across the corpus
adds a third rendering of that same single decision. It cannot surface a row.

**What would be sufficient: a *captured* trace from dialect three, of a
scenario `fixtures/captured/`'s existing pair also covers, compared against
that pair field by field on the nine.** Two properties of that condition matter
more than its content:

- **It asks nothing of *what* dialect three is.** Unlike `Edge.basis`, whose
  condition 2 depends on a property no one can arrange by choosing a dialect,
  any third instrumentor will do. The requirement is only that it be
  **captured**, not rendered.
- **It is therefore schedulable, and it is a human act.** Capturing is a halt
  point (`AGENT.md`; `FIXTURES.md` §6) — an agent builds the harness and stops.
  So this is the one of the three conditions that can be planned for now, and
  the one most likely to be assumed rather than done.

Its bound, stated with it, and it is **scenario** coverage rather than field
coverage: the existing captured pair is *one* scenario, a tool-using
conversation. It already compares seven of the nine and agrees on five —
`TASKS.md` 3.3 F-3 records the pair agreeing on step count, order, `kind`,
`operation`, depth, `call_result` pairing and every payload `state`, and
disagreeing on `status`; 3.4 F-6 adds `usage`. So the fields are not the gap.
What that one scenario never contains is: an `error` status, any
`status_note` at all, a `retriever`, an `embedding`, a `chain`, an `unknown`
kind, or a `link` edge — so a disagreement about any of those is out of reach
for the same reason. (It does carry `parent`, `call_result`, `data` and
`temporal` edges in both dialects, which is four of the five `EdgeKind`s and
the one part of row 9 the pair genuinely does compare.) Widening means **more captured scenarios**, which
is more human acts, not more renderings.

*(Row 5 above says the `Usage.extra` disagreement "is unreachable". That clause
is false as of 3.4: `fixtures/captured/openai_tool_call.jsonl` carries one, and
the captured pair disagrees on it. `TASKS.md` 3.4 F-1 records the correction and
where it is pinned; the correction itself is not made here.)*

**Neither of these licenses stating a contract early.** Writing one for a field
no second implementation has had to agree with is the same defect inverted, and
that is why the enumeration (`CONTRACTS.md`, `TASKS.md` 3.2) states no contracts
and this section states no vocabulary. What is recorded here is what the
instrument would have to be.

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
