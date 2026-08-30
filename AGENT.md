# AGENT.md — autonomous build brief

Entrypoint for an autonomous coding agent. Read this first, then `CLAUDE.md`,
then the specific task you're working. This file defines the run loop, the scope
of this run, and the points where you must stop and hand back to a human.

## Document map

- `SPEC.md` — what to build (behavior). **Source of truth.**
- `CLAUDE.md` — how to build + non-negotiable invariants. Never violate.
- `DESIGN.md` — architecture: the adapter/builder seam, determinism strategy,
  technology decisions. Binding.
- `ROADMAP.md` — phase sequencing.
- `TASKS.md` — the PR-sized checklist you execute against.
- `FIXTURES.md` — the conformance corpus contract (fixture layout, the
  cross-dialect equivalence rule, hand-authored vs. captured).
- `ADAPTERS.md` — how to write an adapter. Follow it exactly for any new dialect.
- `CONTRACTS.md` — the permissively-typed serialized field inventory (`TASKS.md`
  3.2). An **enumeration**, not a set of contracts: it records what states and
  what asserts each field that crosses the schema boundary, and says *unstated,
  unmeasured* where nothing does. Stating those contracts is Phase 4, with
  dialect three. `tests/test_contracts.py` fails if a field appears without a row.
- `ENVIRONMENT.md` — runtime & toolchain contract (exact commands, network
  zones, credentials). Conform to it; never choose your own runtime or invent
  commands.
- `GLOSSARY.md` — terms of art. Use them precisely; they are load-bearing.
- `OPEN_QUESTIONS.md` — deliberately unresolved. **Do not resolve one by writing
  code.**
- `PREDICTIONS.md` — where this model is predicted to be wrong, written before
  the tests that resolve it (**P5 at the end of Phase 2b**, the rest in Phase
  3). **Read-only to the agent, in every phase.** Do not add, edit, or resolve
  a prediction — a human marks them; the file's value is entirely in its
  timestamps.
- This file — orchestration: loop, scope, halt points.

## Scope of this run (bounded)

**There is no live scope, and that is the current state rather than an
oversight.** Phase 3 is complete and tagged `phase-3-exit`. The `0.9.1` release
is complete: `TASKS.md` R1–R3 are all checked, `spanweave 0.9.1` is on PyPI and
verified from the index, and its closing cold read has run. **Every box in
`TASKS.md` is ticked.**

**A session arriving here has nothing to pick up.** Do **not** begin Phase 4 —
it is a third dialect plus a freeze, it is gated on evidence neither Phase 3 nor
this release produces (`ROADMAP.md` Phase 4), and starting it is a human's
decision, not the next unchecked box's. Do **not** freeze the schema. Do **not**
open a `0.9.2`: the two `0.9.1` candidates are both **decided** — C1 shipped,
C2 is not shipping (`TASKS.md`, *Post-launch*) — and a new candidate needs a
measurement, not an idea. **Ask.**

**The Phase 3 scope below is discharged and is kept because everything in it
still binds a release session** — the must-nots especially. Read it as standing
constraints, not as an assignment.

Deliver through the **Phase 3 exit** (`TASKS.md` 3.11), then **HALT for human
review**. *(Discharged: the exit record landed at 3.11 and Phase 3 is tagged.)*

> **Phases 1 and 2 are complete, reviewed, and merged.** Their exit halts are
> discharged; the scope above replaces them. What Phase 2 found is not history
> to skim — the Phase 2 exit record (`TASKS.md` 2.14) and the follow-ups
> 2.15–2.17 are why several Phase 3 tasks are written and ordered as they are.
> `TASKS.md` Phase 3's *"What Phase 2 changed that Phase 3's plan predates"*
> section names the four, and says of each whether it **blocks** a task or
> **under-specifies** one. Read it before the first task, not after a surprise.

Phase 2 falsified the vertical slice. Phase 3 **confirms and packages** it, and
ships `0.9.x` — **publishing without freezing**, because publishing is reversible
and freezing is not (`ROADMAP.md`). Four workstreams, tagged in `TASKS.md`;
**never mix them in one session's context.** A cold session picks the
lowest-numbered unchecked task and works only that tag.

- **`[prereq]`** — 3.1, this task. It blocks everything, because until it lands
  a cold Phase 3 session reads this file and is told to stop.
- **`[contract]`** — the permissively-typed-field inventory (3.2) and the
  prediction resolution artifact (3.5). **3.2 runs before the consumers**, and
  that ordering is decided, not open: Phase 2's most transferable finding is that
  the permissive default won three times and each defect was invisible until
  something else had to agree with it. A consumer written against a field whose
  type then changes is that lesson paid for twice.
- **`[consumers]`** — the two *confirmatory* consumers, the trajectory dumper
  (3.3) and the cost/latency attributor (3.4). Both live in `examples/`, consume
  **committed fixtures only**, and change **nothing** under `spanweave/`.
- **`[launch]`** — the wheel-install check, the version, the docs truth pass, the
  stranger path, the publish preparation, and the exit record (3.6–3.11).

**The gate this phase is measured by: zero shape changes.** A new field,
`NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code or query
primitive wanted by a confirmatory consumer means the model could not express
what a real consumer needed. So every want is a **finding**, classified by
`PREDICTIONS.md`'s binding shape/operational test **as written there** — the
2.3/2.4 discipline, which is why Phase 2b produced nine findings rather than nine
patches. This phase is confirmation, so unlike Phase 2 a model change here is
**not** cheap and expected; it is the gate failing, and it is reported as that.

Specifically, in this run you must **not**:
- **freeze the graph schema**, flip `SCHEMA_FROZEN`, or set `schema_version` to
  `1`. That is Phase 4, it is gated on evidence this phase does not produce, and
  *never accelerate the freeze* is standing (`ROADMAP.md`),
- add a **third dialect**. Still Phase 4 — and now additionally a **freeze
  precondition** (`ROADMAP.md` Phase 4), which makes doing it early more
  load-bearing than it used to be, not less: the gate is that dialect three was
  *run* against the corpus, and a rushed one spends that evidence,
- add or rename a `NodeKind`, `EdgeKind`, `Payload` state, warrant, or
  `Diagnostic` code — still a **halt point**, in this phase as in every other,
- **resolve, mark, or edit `PREDICTIONS.md`.** A human marks P1–P4. The agent
  assembles evidence (3.5) and stops; describing an outcome in the human's place
  is the same act as marking it,
- **widen the shape/operational distinction** to classify a consumer's want as
  operational. If a want does not fit the test as written, it goes to the human
  unfitted. Re-reading the boundary under launch pressure is the exact
  rationalization `PREDICTIONS.md` exists to prevent,
- add a **runtime dependency to core** — including to make an example easier. An
  example that wants one is a finding about the example, not a licence to move
  the line (`ENVIRONMENT.md`, and it is a standing halt),
- **publish** to PyPI or TestPyPI, or run any other credentialed or
  outward-facing step. Preparing the distribution is in scope; pushing it is not
  (3.10 for `0.9.0`, **R3 for `0.9.1`**, and `ENVIRONMENT.md`'s publish zone),
- build streaming, OTLP, tail mode, or a receiver of any kind,
- **weaken `canonical()`, edit an `expected/graph.json`**, or relax a comparison
  to make anything pass. Nothing in this phase should need to touch either; if
  something appears to, the consumer is wrong or the model is, and finding out
  which is the value on offer (`FIXTURES.md` §4),
- touch the network from `spanweave/` **or from `examples/`** — the consumers run
  against committed fixtures so that a stranger can reproduce them
  (`ENVIRONMENT.md`).

Two things Phase 2 forbade that Phase 3 **requires**, named here rather than left
to inference: the **confirmatory consumers** (3.3, 3.4), which Phase 2's scope
deferred to this phase in those words; and **preparing a PyPI distribution** —
`uv build`, artifacts in `dist/`, and installing the locally built wheel into a
throwaway venv (3.6). Both stay inside the existing lines: `examples/` remains
outside the package and off the network (`DESIGN.md` §8), and preparing a
distribution is not publishing one.

**If the phase slips**, cut in the order at `TASKS.md` Phase 3, *"The cut order,
re-read after Phase 2"* — **not** `ROADMAP.md`'s list, one item of which Phase 2
made wrong and which is corrected there. The prediction resolutions (3.5) and the
unfrozen-schema notice are **never cut**; cutting either consumer defers a
prediction, and the cut note must say which, in the words that task gives.

## Run loop (per task)

1. Read `CLAUDE.md` + the relevant `SPEC.md` section + the current `TASKS.md`
   entry.
2. Work the lowest-numbered unchecked task only. One task = one PR.
3. Write the fixture and its **expected canonical graph** before the
   implementation. **In 2a this inverts:** the expected graph already exists
   and is not yours to edit, and the rendering is *transcribed from a captured
   trace*, never written from a reading of the dialect (`FIXTURES.md` §5.1 —
   this is the defect that cost Phase 1 four fixtures). **In Phase 3 no task
   authors a fixture at all:** the consumers read *committed* fixtures, and
   writing a new one to make a consumer look good would make the consumer its
   own exam. If a Phase 3 task appears to need a fixture, that is a finding.
4. Implement until the task's done-when passes.
5. Run `make check`. A task is done only when its check is green **and** the
   gates (neutrality, no-network, no-unsafe, no-dialect-in-builder, determinism,
   losslessness) pass.
6. Check the box in `TASKS.md` in the same change, recording anything that
   diverged from the plan. Commit. Move to the next task.

## Keeping a handoff note readable (retire before adding)

Step 6 above accumulates. `TASKS.md` carries per-workstream intro blocks whose
whole purpose is that a **cold** session finds them without reading backwards —
and a cold session reads this file outline-first: grep for the first unchecked
box and start there. An intro that has grown past a screen is jumped over
entirely, so it stops doing the one job it exists for. This is not a style
preference; it is the note failing silently, which is the same failure mode as
a gate that scans nothing.

`[2a]`'s intro reached four blocks and 55 lines before anyone noticed. The rule
that replaced it, and that applies to every such block:

- **Live items first**, and nothing may precede them. A reader who stops after
  three lines must have read the thing that would have changed what they do.
- **A settled item becomes a pointer the same day it is settled** — one or two
  lines naming the outcome and the commit, not the reasoning, which lives in
  the task record and in the code. Retire *before* adding the next item, not
  after; a list only ever grows if retirement is deferred.
- **The session marker stays last**, because it is the block most likely to be
  stale and the least likely to change what a reader does first.
- If it grows past three blocks again, **split it** rather than tightening the
  prose.

## Self-verification (don't self-certify by prose)

"Done" means the executable check passes, not that the output looks right. If a
done-when is not yet expressed as a runnable check, add the check first (tasks
0.4 / 0.5), then satisfy it.

Two checks in particular are not optional and must not be weakened to make a
task pass:

- **Cross-dialect equivalence** — all dialects of a scenario produce the same
  canonical graph (`FIXTURES.md` §4). If a new adapter fails this, the adapter
  is wrong, or the model is wrong. Never "fix" it by relaxing the comparison.
- **Shuffled-input determinism** — reordering input lines yields an identical
  graph. Never "fix" it by sorting the expected output.

### When the check is a human reading — use a cold reader

The rule above has a hole, and this is what goes in it. *"Add the check
first"* has no answer when the question is **does this document land**, **does
this graph represent this trace**, or **would a stranger get stuck** — none of
which has an executable form. The temptation there is to read it yourself and
call it verified, which is self-certifying by prose with extra steps.

**The practice.** Give the task to a model with **no project context** — a
blank session, ideally a different model than the one doing the work — and
**do not tell it what you are worried about.** Ask for the thing itself
("read this and tell me what it does", "you have this trace and this graph;
do they agree", "you just installed this; what do you do next"), never for the
suspicion.

**Why it works, which is the part worth keeping.** Every internal check in this
project was written by whoever wrote the thing it checks. The tests, the gates,
the review scripts and the reviewer all share one author's model of what could
go wrong, so they share its blind spots exactly. That is the same argument
`TASKS.md` 2.14 made for two independent implementations having to agree, and
the same one that makes a third dialect a freeze precondition (`ROADMAP.md`) —
one layer out, applied to prose and to judgement instead of to code. **A cold
reader is the cheapest instrument that supplies that independence.** It costs
one prompt.

Six uses so far, and what each returned:

- **2.6.** A blank session given only the captured trace and its graph found a
  **missing declared `data` edge** that 593 tests, six gates and two review
  scripts had all agreed to miss. It became `SPEC.md` §4.2.1.
- **3.9.** The stranger walk found the README's quickstart **did not run** —
  the same defect class reached by *executing* rather than reading, which is
  why that practice and this one are siblings rather than alternatives.
- **3.10 step 4.** Two models asked to behave as a user who had just installed
  the package, told nothing about the suspicion. Result and its limits at that
  task's record.
- **3.10 step 8, the closing read** — the same question asked again with a
  **true** premise, once the package was installable. Both models read the
  Install section **correctly**, both predicted the failure before typing it,
  and **both gave the failing command as their second move.** Knowing did not
  prevent doing. It confirmed `0.9.1` candidate C1 is fixing the right end,
  produced C2, and refuted a third observation. **This is the use worth
  reading before running one:** a clean read and a confused read are the two
  outcomes anyone plans for, and the informative one was neither.
- **`TASKS.md` R3 step 9, against the published `0.9.1` page** — the first read
  against a page changed *because of* a cold read, and it decided C2:
  **unnecessary**, the hint lands. Three things in it are worth carrying, and
  none of them is the verdict. **(a) The gate had a false positive.** Six runs
  were screened by a substring check for whether the reader pasted the failing
  command; it cannot tell *"I will run this"* from *"I am explaining why I
  won't"*, and it passed a run that recommended something else. The honest count
  is one clean observation with one weak corroboration — **a screening
  instrument written by the same hand as the question shares its blind spots
  too, exactly as this section argues about tests.** **(b) The interesting
  result was in turn 1**: four of six never reached the error at all, where both
  `0.9.0` readers had pasted after understanding. **(c) It is unsettleable** —
  the comparison needs `0.9.0`'s page as the *current* page, which it stopped
  being at the publish. If a read is going to be a before-and-after, **run both
  halves in the same batch**; the window closes when you ship.

- **`TASKS.md` I1, on `Edge.basis`** — the first use aimed at a **document
  pair** rather than at a document, a graph, or an install. Two models were
  given `SPEC.md` §3.8 and §4 and `ADAPTERS.md`, and asked only *who decides
  `basis`?* **They disagreed with each other**, which decided the question more
  firmly than agreement would have: one read the documents faithfully and
  concluded the wrong thing, the other reached the right conclusion through a
  mechanism the code does not implement. Neither could read the answer off the
  documents, because the documents did not contain one.

  **Why it is worth reading before running one.** The previous ten instances of
  this project's pattern were all *a claim nothing asserted*. This was **two
  documents asserting different things for four phases**, undetected because the
  field they disagreed about had never been populated by an adapter — so nothing
  ever had to choose between the readings. **The project's instruments catch a
  document disagreeing with the code, and two implementations disagreeing with
  each other. Nothing catches two documents disagreeing about a field nothing
  exercises.** A cold read does, and only because the readers were allowed to
  disagree.

**Two constraints, each stated with the failure that produced it — because a
rule without its failure gets softened by the next person who finds it
inconvenient.**

1. **The reader must not be told what to look for, and must not be able to
   find out.** At 2.3 the constraint *"do not read the producer side"* sat in a
   place the session reached only **after** the thing it was meant to hide; the
   session read it, and said so. A constraint on what a cold reader may see is
   a claim about **ordering**, not about wording: put it where the reader
   arrives before the evidence, or accept that it is decoration.
2. **The premise must be *true*, not merely unrevealing.** At 3.10 step 4 the
   prompt asserted something the README contradicts — *"you have just run
   `pip install spanweave`"*, which the document says is impossible. That is
   1's failure inverted: instead of revealing what to hide, it supplied
   something false, and the readers spent their attention arguing back. The
   answer that came back was real but **narrower than the question**: it
   measured whether the document can *correct* a mistaken reader, which is a
   weaker claim than whether a correct reader gets stuck. A cold read whose
   scenario the document contradicts tests the document's ability to argue,
   not its ability to land.

**When it does not apply.**

- **It never replaces a test.** A clean cold read is one reader's experience,
  not a guarantee, and it does not compound: two clean reads are two
  anecdotes. The remedy for anything it *finds* is still a test wherever one
  is possible — standing since 3.8, and the reason that task shipped sixteen
  tests rather than sixteen corrected sentences.
- **Never for a question with a mechanical answer.** Asking a model whether
  the suite passes, whether a file is tracked, or what a count is, is strictly
  worse than running the thing that knows. Reserve it for judgement, which is
  the only thing it has that a check does not.
- **A cold read cannot be run against a state that does not exist yet.** If
  the scenario requires the package to be installable and it is not, the
  question waits; see constraint 2.

*Placement, argued rather than assumed: this section already states the rule
this completes and is the only place a session meets it at the moment it
applies, and every session reads this file first, cold, by instruction.
**Not `CONTRIBUTING.md`** — its structure is a bar a PR must clear, so an
instrument listed there becomes a merge requirement, which is precisely what
this must never be. **Not `CLAUDE.md`** — everything in that file is a line
that must not be crossed, and this is an instrument, not an invariant.
**Not `DESIGN.md`**, though the independence argument lives there: it would be
met only by someone reading about the adapter/builder seam, which is the wrong
moment. **Not a new file** — a document nobody is told to read is a document
nobody meets, and being reached at the moment of use is the whole point.*

## Halt-and-hand-back points (do NOT proceed past these alone)

Every entry below is standing. Nothing here has been discharged by Phases 1 and
2 except the phase-exit halt, which moved forward rather than disappearing, and
the three task-specific entries Phase 2 added, retired at the end of this
section with a note saying why each is now false.

- **Captured fixtures (`TASKS.md` 1.9, 2.6, 2.15).** Conformance dialect
  specimens may be hand-authored, but at least one **captured** trace from a
  real instrumentor is required **per adapter** to prove it works against
  reality rather than against our idea of the dialect. You must **not**
  synthesize a file and label it captured. Build the capture harness, then
  STOP; a human runs it and commits the output with provenance
  (`FIXTURES.md` §6). **Still standing.** The three runs so far are done, but
  every further capture is a human act, and the fabrication rule binds
  regardless of whether any capture is scheduled — it also forbids describing
  a *generated load input* (3.4) as captured, or letting one near `fixtures/`.
- **Any model change** — adding or renaming a `NodeKind`, an `EdgeKind`, a
  `Payload` state, a warrant, or a `Diagnostic` code. Stop and ask.
- **Anything in `OPEN_QUESTIONS.md`.** If a task appears to require deciding one,
  stop. Deciding by implementation is precisely the failure that file exists to
  prevent. §7 (inferred `data` edges) is live in this phase: 3.5 hands the human
  evidence about it and resolves nothing.
- **Any edit to `PREDICTIONS.md`.** It records what was predicted *before* the
  test. Editing it during the build — even to add a prediction that now seems
  obvious — destroys the only property that makes it evidence. Read-only in
  **every** phase; P1–P4 are marked by a human at 3.5.
- **Freezing the schema**, or any change to `schema_version` semantics.
- **Adding any core runtime dependency** (`ENVIRONMENT.md`, *Dependencies*).
- **The license**, or any change to `SPEC.md` scope or the `CLAUDE.md`
  invariants.
- **Live credentials, real model calls, network access, or anything touching a
  system outside this repo.** Stop and request it.
- **Phase exit.** Stop and hand back for review; do not start the next phase.
  Phase 1's exit (1.9), Phase 2's (2.14), **Phase 3's (3.11)** and the **`0.9.1`
  publish (R3)** are all **discharged**. **There is no live halt, because there
  is no live work** — which is not permission to find some. The next thing is
  Phase 4, its entry is a human's call, and a release does not meet its
  conditions. Do not start it, and do not freeze the schema.

Four added for Phase 3. Each names the artifact the human needs in order to
decide; `TASKS.md` carries the full form at the task.

- **The PyPI publish (`TASKS.md` 3.10 for `0.9.0`, R3 for `0.9.1`; both run).**
  Credentialed, outward-facing, and the closest thing in this project to
  irreversible: a name-plus-version on PyPI cannot be reused. **`0.9.0` and
  `0.9.1` are both spent, so the entry is live for every version after them.** Each release writes its **own** runbook rather than
  pointing at the previous one: 3.10's step 2 carried a false wheel-hash claim
  that its amendment 1 corrected, and a runbook that defers inherits whatever
  was wrong with the one it defers to. The agent has no token and
  must not be given one — TestPyPI included, which is an outward-facing
  credentialed index too (`ENVIRONMENT.md`, publish zone). Prepare `uv build`'s
  sdist and wheel, get `install-check` green against the wheel, record the exact
  command **unrun**, then STOP. A human publishes. No document gains a
  `pip install spanweave` line until it has (3.8).
- **The `schema_version` decision (`TASKS.md` 3.7). DECIDED — see below.**
  Kept rather than deleted because the halt it instances is standing: *any
  change to `schema_version` semantics* still stops a session. **The decision
  is B plus C.** `0.x` is a single unfrozen bucket that never tracks changes,
  and pinning is on the library version (`SPEC.md` §3.9); the tripwire that
  stops a shape change shipping unnoticed is `tests/serialized_shape.json`,
  regenerated by `make shape`. A session that finds itself wanting to bump
  `SCHEMA_VERSION`, or to widen the tripwire's `PASSTHROUGH` boundary, is at
  the halt and must stop.

  **What 3.7 corrected, and it matters beyond this entry.** The version of this
  bullet that stood until 3.7 said `SCHEMA_VERSION` was `"0.1"` *"before Phase 2
  changed `Diagnostic.source`'s serialized type"* — naming one change. There
  were **two**. `a953a1f` renamed `meta.adapters[].confidence` to
  `declared_confidence`, and it was invisible to every instrument the project
  had: `canonical()` drops `meta.adapters` whole, so the corpus, both dialects
  and the cross-dialect equivalence test were *structurally incapable* of
  noticing it. Its own commit message says *"cheap now, a version bump after
  the freeze"*; the bump never came. That is the **fifth** instance of this
  project's pattern — a contract nothing had to agree with, after the three
  Phase 2 defects and `CONTRACTS.md`'s F-E — and the most direct, because the
  deferral was written down at the time and still went missing.
- **Each consumer's findings record (`TASKS.md` 3.3 and 3.4), and the
  resolution artifact (3.5).** Stop at each, whichever way it goes — **a human
  marks P1–P4**, in a file the agent may not edit. Hand over the findings, their
  scope, and what the evidence cannot support; do not describe an outcome in
  place of a mark. A refutation carries its scope the way P5's does: *what size,
  what consumer, what was actually measured.* This applies to a **negative**
  result as loudly as a positive one — a prediction whose friction never had the
  opportunity to occur is not refuted by silence.
- **A type change forced by the field inventory (`TASKS.md` 3.2) — conditional.**
  An instance of the model-change halt above, not a new licence: if a field's
  contract cannot be stated without changing what is serialized, that is a shape
  change and a human call *before* `0.9.x` publishes the field. It is **not** a
  failure of this phase's gate, which measures what a *consumer* could not
  express; record it as both things or as neither, never as whichever reads
  better. And do not invent a contract to avoid the halt — an honest
  *"unstated, unmeasured, needs dialect three"* row is the deliverable.

Three Phase 2 entries are **discharged** and deliberately deleted rather than
left standing, because a halt that is already false is how a list of halts stops
being read (2.1):

- the **2.2 / 2.6 capture runs** — both ran; the general captured-fixtures halt
  above is the one that survives them;
- the **2b timebox expiry (2.4)** — the box closed, its nine findings are
  recorded, and the human has marked P5 **REFUTED — scoped**;
- the **first cross-dialect equivalence run (2.9)** — it happened, and both
  dialects have agreed on the corpus since 2.13.

## When blocked or ambiguous

If a task is underspecified, or a change would require a dialect branch in the
builder, or you find yourself about to add a word like `severity`, `risk`,
`secret`, `sensitive`, or `cost` to a file under `spanweave/` — **STOP and ask
rather than guessing.** On the invariants, halted-and-correct beats
clever-and-wrong.

If you cannot map some telemetry, the correct action is almost always a
**diagnostic**, not a guess. Reaching for an inference is the signal to stop.

## Standing non-negotiables (from `CLAUDE.md` — repeated because they're load-bearing)

- **Semantic neutrality:** no roles, severity, risk, cost, or quality judgement
  in core. Ever.
- **Losslessness:** nothing silently dropped; unmapped input becomes `unknown`
  plus a diagnostic.
- **Warranted edges:** explicit vs. derived, always stated, never promoted;
  `data` edges are never inferred.
- **Determinism:** byte-identical output; no `hash()`, clocks, randomness, or
  input-order dependence.
- **No network, no execution, no unsafe deserialization** in core.
- **Adapters, not model changes:** a new dialect never touches the builder.
