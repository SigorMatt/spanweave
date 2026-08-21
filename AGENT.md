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
  the Phase 3 test. **Read-only during Phase 1–2.** Do not add, edit, or resolve
  a prediction; the file's value is entirely in its timestamps.
- This file — orchestration: loop, scope, halt points.

## Scope of this run (bounded)

Deliver through the **Phase 1 exit** (`TASKS.md` 1.9), then **HALT for human
review**. Do **not** begin Phase 2 or later.

Phase 1 is the vertical slice: **one** adapter (OpenInference), the builder, the
graph and its query surface, serialization, and the CLI — proven end-to-end on
the seeded conformance scenarios. Phases 2+ are marked provisional because their
design depends on what the first adapter reveals about the model; starting them
now is pulling breadth forward, which `CLAUDE.md` forbids.

Specifically, in this run you must **not**:
- write a second adapter (that is Phase 2, and it exists to *falsify* the model —
  writing it alongside the first defeats its purpose),
- freeze the graph schema,
- add a `NodeKind` or `EdgeKind`,
- build streaming, OTLP, tail mode, or a receiver of any kind,
- write the example consumers (Phase 3).

## Run loop (per task)

1. Read `CLAUDE.md` + the relevant `SPEC.md` section + the current `TASKS.md`
   entry.
2. Work the lowest-numbered unchecked task only. One task = one PR.
3. Write the fixture and its **expected canonical graph** before the
   implementation.
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

- **Captured fixtures (`TASKS.md` 1.8).** Conformance dialect specimens may be
  hand-authored, but at least one **captured** trace from a real instrumentor is
  required per adapter to prove it works against reality rather than against our
  idea of the dialect. You must **not** synthesize a file and label it captured.
  Build the capture harness, then STOP; a human runs it and commits the output
  with provenance (`FIXTURES.md` §6).
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
- **Phase 1 exit (1.9).** Stop and hand back for review. Do not start Phase 2.

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
