# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-11 (reopened for run 3: run-2 review findings).
Baseline: fcc842d (series close), 2190 tests pass, 2 skipped.

---

## 0. Operating protocol

Two Claude Code sessions on the repo machine: **builder** (orchestrates and
executes batches, always through sub-agents) and **aux** (independent cold
reads and one-off checks; never edits tracked files). The human relays
one-line prompts. Everything a session needs to know is in this file, the
repo docs it names, and git.

### 0.1 Builder — orchestrator loop

The builder's own context must stay small. It reads this file, dispatches,
verifies, records, and moves on. It does not read source files itself,
does not debug itself, and does not carry batch detail in its context: all
of that happens inside a sub-agent whose context is discarded.

On the prompt `Execute WORKPLAN.md run N` (or `Resume WORKPLAN.md`):

1. `git status`. If the tree is dirty: dispatch one sub-agent with the
   **recovery brief** (0.4). Do not proceed until the tree is clean and
   `make check` is green (verify with a sub-agent; the builder runs no
   commands longer than `git status` / `git log --oneline -5` itself).
2. Read §1 and §2. Take the first batch of the requested run whose status is
   not `done` / `dropped` / `awaiting decision`.
3. Dispatch **one sub-agent** with the **batch brief** (0.3) for that batch.
   Wait for its ≤12-line report.
4. Verify: `git log --oneline -3` shows the batch commit; the report says
   `make check` passed. If not, dispatch the same batch once more with the
   report's failure appended. If it fails twice: set status
   `blocked: <one line>`, write the resume note, and continue to the next
   batch **unless** the blocked batch is a dependency of the next.
5. Edit this file: status → `done`, one line under §4 if anything was
   learned. Commit the plan edit together with nothing else
   (`plan: <batch> done`).
6. Repeat from 2. Stop when: the run's batches are exhausted; a batch ends
   `awaiting decision`; or the same batch has failed twice.
7. Final step of a run: dispatch a sub-agent to `git format-patch main -o
   patches/` and print `git log --oneline main..HEAD`. Report to the human:
   batches done, blocked, awaiting decision, and the memo file paths to read.
8. `git push origin audit-fixes` (create the branch on the first push). A
   run is not finished until the push succeeds; if it fails, report why and
   stop.

Memo batches (C2, D1, E1, G1, G3, H1) are also sub-agents; they end with
status `awaiting decision` and never touch `spanweave/`.

### 0.2 Aux — cold reader

On the prompt `Review WORKPLAN.md commits since <sha>`: for each commit,
in a sub-agent per commit, check against the `CONTRIBUTING.md` bar and
`AGENT.md` "Self-verification": spec changed in the same commit where
behaviour changed; the new test fails on the parent commit (`git stash` /
`git checkout <parent> -- spanweave` is not allowed — use `git worktree`
on the parent, run the test there); no `hash()`, clock, or network in
`spanweave/`; `tests/serialized_shape.json` unchanged or regenerated with
an explanation; commit is one concern. Write findings to
`patches/REVIEW-<date>.md` (untracked) and print them. Aux never edits
tracked files and never commits.

On the prompt `Reproduce WORKPLAN.md audit`: run `tests/audit/probe1.py`
and `probe2.py`, print output, and diff against §5 expectations.

### 0.3 Batch brief (template the builder passes to a sub-agent)

```
You are executing batch <ID> of WORKPLAN.md in the spanweave repo. Read,
in this order: CLAUDE.md, the WORKPLAN.md row for <ID> and §5, then the
SPEC.md sections the row names, then only the source and test files the
batch touches. Rules: spec first (SPEC.md edited in this commit if
behaviour changes); write the failing test before the fix and confirm it
fails; then implement; then `make check` (lint, format, mypy --strict,
tests, gates) and `make conformance`; if tests/serialized_shape.json
moves, regenerate it and explain why in the commit body. Add a CHANGELOG
entry. If the batch's case exists in tests/audit/probe*.py, convert it to
a pytest test and remove it from the probe. Commit once:
`<area>: <one line>` with a body naming <ID>, the SPEC sections touched,
and the audit finding number. Never edit WORKPLAN.md. If completing the
batch would require changing the data model, a serialized default, or an
edge/diagnostic default that SPEC.md does not already promise — stop,
write the options to OPEN_QUESTIONS.md under a heading "<ID>: …", commit
that alone, and report `awaiting decision`. Report in ≤12 lines: commit
sha, files changed, tests added, make check result, anything the
orchestrator must know.
```

### 0.4 Recovery brief (dirty tree or interrupted batch)

```
The previous batch was interrupted. Read WORKPLAN.md §4. Run git status
and git diff --stat. If the in-progress work is complete enough to pass
`make check`, finish it under the batch brief rules and commit. Otherwise
`git stash` it with the message `wip <ID> <date>` and report what was
stashed and where it stopped. Leave the tree clean either way.
`git push origin audit-fixes` (create the branch on the first push). A run
is not finished until the push succeeds; if it fails, report why and stop.
```

### 0.5 Context management (for the human)

- Builder: **clear context** before `Execute WORKPLAN.md run N` and before
  any `Resume WORKPLAN.md`. Continuity lives in this file and git, not in
  the session. The only time not to clear is when the builder has asked a
  question and is waiting for the answer.
- Aux: **always clear** before a prompt. Every aux task is stateless.
- If limits hit mid-run: when they reset, clear and send `Resume
  WORKPLAN.md`. Step 1 of 0.1 handles the dirty tree.

### 0.6 Standing rules (from CLAUDE.md, repeated because load-bearing)

No semantics in `spanweave/`. Nothing dropped silently. Never infer a
relation the telemetry did not state. No `hash()`, clocks, randomness,
input-order dependence. Adapters, not model changes — a model change is a
halt point, not a batch.

TASKS.md is the item registry (one line per batch, written by G2, final
statuses at series close); ROADMAP.md is untouched until G3; this file is
execution state only and is deleted at series close with §3 folded into
TASKS.md.

### 0.7 Watch (aux, read-only, report-then-stop)

While the builder is on a run, aux may run `~/spanweave-ops/watch_run.sh` in a
loop. It reads git log/status/stash/fetch, file mtimes, `pgrep`, and the
builder transcript tail; it never writes to the repo and never runs make, uv,
or pytest. Triggers: run finished (push landed and no batch left `todo`/`in
progress`); builder waiting on the user; 40-minute stall while a batch is `in
progress`; builder process gone with the run incomplete; contract tripwires on
any new commit — touches WORKPLAN.md without a `plan:` subject, touches
`spanweave/` while the newest commit's batch is a memo, changes
`tests/serialized_shape.json` without a commit-body explanation, lands on
`main`, or `git stash list` grew. It prints an evidence block and stops; it
never restarts, fixes, or touches anything. Conventions live in
`~/spanweave-ops/WATCH.md`, outside the repo on purpose.

---

## 1. Batch list

| # | Batch | Status | Est. calls |
|---|---|---|---|
| R1 | **Timestamps are finite and bounded, or missing.** Review blocker: `_as_time` on a quoted integer of >4300 digits raises the interpreter's digit-limit `ValueError` out of `spanweave.build`; `spanweave build`/`inspect` print a traceback (regression vs C3's parent). Also the C1-era should-fix: `"1e400"` parses to `inf` and serializes as bare `Infinity`, which strict JSON parsers reject. Rule: a timestamp that is not a finite number after parsing — non-numeric, non-finite (`inf`, `nan`), or beyond the interpreter's integer digit limit — is `None` with `missing_timestamp` and the literal in `source` (truncated to 64 chars if longer). `serialize.py` uses `allow_nan=False` so a non-finite value can never be written; a test proves it. Tests: quoted 5000-digit integer, bare 5000-digit integer literal (reader path), `1e400` bare and quoted, `NaN`, via `build` and via the CLI (no traceback, exit codes as documented). Also pin current F2 behaviour with an OTLP fixture whose timestamps are nanosecond strings: it builds and emits `timestamp_unit_suspect` once per span (R3 revisits this; the test states that). SPEC §3.1, §3.7. CHANGELOG. | done (`0e4262e`) | 20 |
| R2 | **Track the reviews; recover the two lost concerns.** G4 wrote "five other concerns were assigned" and listed three destinations; concerns 6 and 7 of the run-1 review exist nowhere in a clean checkout because `patches/` is untracked. Create `reviews/` (tracked; not a root `.md`, so doc-truth is unaffected) holding `2026-09-10-run1.md` and `2026-09-10-run2.md` verbatim from `patches/`. TASKS.md audit section: point at both files; add concerns 6 and 7 as open threads with their text; correct the "five … assigned" sentence. No code. | done (`0284ec3`) | 8 |
| R4 | **B3's sentence matches B3's behaviour.** SPEC says a key read to decide is consumed; the adapter consumes `role` even when it could not use it, and `role` has no mapped field. Decide the smaller change inside the SPEC's own principle (losslessness + "nothing reported as unmapped that was read"): either consume only when the key decided something, or state that a read key is consumed regardless and why. Tests either way; corpus expectations must not move (verify). | todo | 10 |
| R6 | **A6's narrative matches the measurement.** The commit body says the encoder's limit is lower than the parser's; measured on CPython it is ~1.9× higher, so the story is not reachable from a trace file. Correct CHANGELOG and SPEC §7 wording to what was measured; keep the containment (it is still correct to have). Record the measurement. Docs only. | todo | 6 |
| R5 | **Corpus counts recompute from a checkout.** Five commits (name them from `git log --grep` on "57 files\|177 records\|43+14\|117+60") cite counts that include the gitignored `capture/_scratch/`. Make F2's widened census the single source: a script or test under `tests/` that counts tracked files/records only and prints the figures; replace every cited figure in CHANGELOG, TASKS.md, OPEN_QUESTIONS.md and ROADMAP.md with the recomputed one and a "(tracked files only)" qualifier. G5 already did this for its own figures — match its wording. | todo | 12 |
| R3 | **Stated timestamp units (HALT memo).** An OTLP JSON envelope declares its unit in the field name (`startTimeUnixNano`); F2 reads it and the adapters then warn `timestamp_unit_suspect` on every span, while a genuinely seconds-encoded span in the same file is the only one *not* warned (signal inversion, measured). Options: (a) `NormalizedSpan.timestamp_unit: "s" \| "ns" \| None` — the container states `ns`, the flat record states nothing; the diagnostic fires only when no unit is stated and the value exceeds the ceiling; `started_at` still holds the reported value (C2 decision stands), and the graph carries the unit where stated (model field: schema moves); (b) the reader rescales OTLP ns to seconds before the seam (violates C2's "never rescale"); (c) leave as is and document the warning as expected on OTLP input. Memo to OPEN_QUESTIONS.md with recommendation; `awaiting decision`. | todo | 6 |
| R7 | **Series close, again.** As G4: final statuses to TASKS.md, §3 decisions moved, WORKPLAN.md and its README row removed, `make check`. Runs only after R3 is decided and implemented (run 4), or immediately if the decision is (c). | awaiting R3 | 6 |

---

## 2. Execution order

Run 3 = R1 → R2 → R4 → R6 → R5 → R3 (halts). Run 4 = R3 implementation per
decision → R7.

---

## 3. Decisions log

Empty; run 3 takes none.

---

## 4. Resume note

- 2026-09-11: reopened for the run-2 review. Verification of all six original
  findings against fcc842d passed independently (mixed build, duplicates,
  deep JSON incl. CLI, annotate 0.97 s, ns timestamps exact, echo basis
  split); the blocker is R1's.
- 2026-09-11: R1 also fixed the same digit-limit escape in the *reader*
  (`read.py:_int_value` on an OTLP `intValue`), spec'd in §7 in the same
  commit. New user-visible refusal: `spanweave build` on a trace holding a
  bare `NaN`/`Infinity`/`1e400` now exits 1 with `graph_not_serializable`
  rather than writing a document with a bare `Infinity`; `inspect` still
  exits 0. R3's signal inversion is now pinned by two tests in
  `tests/test_read.py`, which R3's decision will have to move.
- 2026-09-11: R2's row had a wrong premise -- `test_doc_truth.documents()`
  uses `rglob`, so `reviews/` is scanned like `patches/` already was (it
  passes; the README table test is root-only, so no README row). R2 added two
  doc-truth tests exempting the verbatim archives and WORKPLAN.md. The
  recovered concern 7 is now load-bearing beyond dedup: A5 keys span-id-less
  records on a content digest, so content-equality is an identity assumption.

---

## 5. Findings reference

| Review finding | Batch |
|---|---|
| C3 digit-limit `ValueError` escapes `build` and the CLI | R1 |
| `Infinity` serialized | R1 |
| F2 warning ships untested; signal inversion on OTLP | R1 (pin), R3 (decide) |
| G4 lost run-1 concerns 6 and 7; reviews untracked | R2 |
| B3 consumes `role` it could not use; SPEC sentence contradicts | R4 |
| A6 commit narrative wrong about encoder vs parser limit | R6 |
| Five commits cite non-recomputable corpus counts | R5 |
