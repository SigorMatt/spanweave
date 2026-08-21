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

Deliver through the **Phase 2 exit** (`TASKS.md` 2.14), then **HALT for human
review**. Do **not** begin Phase 3 or later.

> **Phase 1 is complete, reviewed, and merged.** Its exit halt is discharged;
> the scope above replaces it. What Phase 1 found is not history to skim — the
> Phase 1 review records in `TASKS.md` are the reason several Phase 2 tasks are
> ordered the way they are, and the captured trace in `fixtures/captured/` is
> the reason four fixtures say what they now say.

Phase 2 falsifies the vertical slice Phase 1 built. Two workstreams, run
**strictly serially, 2b first** (`ROADMAP.md`, and `TASKS.md` Phase 2 encodes
the sequencing):

- **2b — the adversarial consumer.** A fleet aggregator in `examples/`,
  attacking `PREDICTIONS.md` P5. **Timeboxed to two days.** The box is a limit,
  not a target; it is never extended because the work got interesting.
- **2a — the second dialect.** The OTel GenAI adapter, its renderings, and the
  cross-dialect equivalence test. It **inverts Phase 1's order on purpose:
  capture first, then render from what the capture shows, then write the
  adapter.**

This phase exists to break things, so **expect the model to be wrong
somewhere.** A model change found here is cheap and expected; the same change
after the schema freeze is not. What is *not* permitted is absorbing one
silently — every model change either pressure forces is recorded in `TASKS.md`
with its cause, and that record is the input to the Phase 4 freeze decision.

Specifically, in this run you must **not**:
- freeze the graph schema,
- add a `NodeKind` or `EdgeKind` — still a **halt point**, and Phase 2 is the
  phase most likely to make one look necessary,
- build streaming, OTLP, tail mode, or a receiver of any kind,
- write the *confirmatory* consumers — the trajectory dumper and the
  cost/latency attributor are Phase 3. The Phase 2 consumer is the adversarial
  one, and only that one,
- add a third dialect. Breadth is Phase 4,
- weaken `canonical()`, edit an `expected/graph.json`, or relax a comparison to
  make a second-dialect rendering pass. If a dialect fails equivalence, the
  adapter is wrong or the model is, and finding out which is the entire value
  on offer (`FIXTURES.md` §4).

Two things Phase 1 forbade that Phase 2 **requires**, so they are named here
rather than left to inference: a **second adapter** under `spanweave/adapters/`
(2.9), and code under **`examples/`** (2.3). Both remain outside the package's
invariants in the way `DESIGN.md` §8 and `ENVIRONMENT.md` describe —
`examples/` still may not touch the network.

## Run loop (per task)

1. Read `CLAUDE.md` + the relevant `SPEC.md` section + the current `TASKS.md`
   entry.
2. Work the lowest-numbered unchecked task only. One task = one PR.
3. Write the fixture and its **expected canonical graph** before the
   implementation. **In 2a this inverts:** the expected graph already exists
   and is not yours to edit, and the rendering is *transcribed from a captured
   trace*, never written from a reading of the dialect (`FIXTURES.md` §5.1 —
   this is the defect that cost Phase 1 four fixtures).
4. Implement until the task's done-when passes.
5. Run `make check`. A task is done only when its check is green **and** the
   gates (neutrality, no-network, no-unsafe, no-dialect-in-builder, determinism,
   losslessness) pass.
6. Check the box in `TASKS.md` in the same change, recording anything that
   diverged from the plan. Commit. Move to the next task.

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

## Halt-and-hand-back points (do NOT proceed past these alone)

Every entry below is standing. Nothing here was discharged by Phase 1 except
the phase-exit halt, which moved forward rather than disappearing.

- **Captured fixtures (`TASKS.md` 1.9, and again at 2.6).** Conformance dialect
  specimens may be hand-authored, but at least one **captured** trace from a
  real instrumentor is required **per adapter** to prove it works against
  reality rather than against our idea of the dialect. You must **not**
  synthesize a file and label it captured. Build the capture harness, then
  STOP; a human runs it and commits the output with provenance
  (`FIXTURES.md` §6). *(The task number said 1.8; captured fixtures are 1.9.
  Corrected here.)*
- **Any model change** — adding or renaming a `NodeKind`, an `EdgeKind`, a
  `Payload` state, a warrant, or a `Diagnostic` code. Stop and ask.
- **Anything in `OPEN_QUESTIONS.md`.** If a task appears to require deciding one,
  stop. Deciding by implementation is precisely the failure that file exists to
  prevent.
- **Any edit to `PREDICTIONS.md`.** It records what was predicted *before* the
  test. Editing it during the build — even to add a prediction that now seems
  obvious — destroys the only property that makes it evidence.
- **Freezing the schema**, or any change to `schema_version` semantics.
- **The license**, or any change to `SPEC.md` scope or the `CLAUDE.md`
  invariants.
- **Live credentials, real model calls, network access, or anything touching a
  system outside this repo.** Stop and request it.
- **Phase exit.** Stop and hand back for review; do not start the next phase.
  Phase 1's exit (1.9) is **discharged**. The live one is the **Phase 2 exit
  (`TASKS.md` 2.14)** — do not start Phase 3.

Three added for Phase 2. Each names the artifact the human needs in order to
decide; `TASKS.md` carries the full form at the task.

- **The capture runs (`TASKS.md` 2.2 and 2.6).** Both need a model API key the
  agent does not have and must not have (`ENVIRONMENT.md`). 2.2 is the scratch
  fleet for the adversarial consumer; 2.6 is the second adapter's captured
  fixture. Write the harness, verify it against stub spans, then STOP. The
  fabrication rule above applies to both — and to the fleet in particular,
  where volume makes synthesis tempting and undetectable.
- **The 2b timebox expiry (`TASKS.md` 2.4).** Two days, then stop, whatever
  state the aggregator is in. Record the findings, classified shape or
  operational by `PREDICTIONS.md`'s binding test, and hand back: **a human
  resolves P5**, in a file you may not edit. Do not extend the box, and do not
  resolve the prediction by describing an outcome here instead.
- **The first cross-dialect equivalence run (`TASKS.md` 2.9).** Stop whichever
  way it goes — a match is the phase's central claim and its first evidence; a
  mismatch is a finding about the adapter or about the model, and deciding
  which is a human's call. Never weaken `canonical()` to get past this. If the
  `SPEC.md` §4.2.1 `data` edge is what disagrees, carry it to the human as
  **evidence about `EdgeKind.data`'s generality**, alongside
  `OPEN_QUESTIONS.md` §7 and `PREDICTIONS.md` P3 — as evidence, never as a
  resolution of either.

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
