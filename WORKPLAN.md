# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-12 (reopened for run 6: digit limit and run-5 review items; the PR follows this run).
Baseline: 67c7642 (third close), 2490 tests pass, 2 skipped.

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
| S8 | **Library-owned digit limit.** Per §3: a `DIGIT_LIMIT = 4300` constant applied by string length before any `int()` on a timestamp literal, in both adapters and the seam, so `PYTHONINTMAXSTRDIGITS=0` and `=640` produce the same graph as the default; R14's boundary tests derive from the constant, not `sys.get_int_max_str_digits()`; ENVIRONMENT.md's pinning sentence deleted; SPEC §5.3 and §5.1's determinism statement made unconditional again; README.md:169 likewise. Tests: the whole suite green under all three configurations, and one test that asserts byte-identical graphs across them. No corpus expectation moves (verify). CLAUDE.md untouched. | done (`62385b6`) | 15 |
| S9 | **Census families for every printed figure.** Review item 1: `N/M`, `N carrying a span id`, `N trace-unique`, `N tracked *.jsonl` have no family, so four figures at CHANGELOG.md:942-944 stay green when wrong; `RETIRED_CENSUS_FIGURES` masks `137 of the 155 → 135` and `52 → 64 *.jsonl` because `WORKING_TREE_CENSUS` was never extended. Derive families from the census's output line format so a figure with no family fails the guard itself; extend the retired set correctly; re-plant all figures the review lists and prove red. | done (`80a1cfe`) | 12 |
| S10 | **Links under the empty-id rule.** Review S3 finding: `links[].span_id == ""` still yields an `explicit` edge with `dst == ""`, so SPEC §3.6's "not a span id at either end of a relation" is falsifiable. Bring link targets under S3's rule at the seam (`""` → no link, with the same handling as an absent target and a diagnostic that says what was declared), extend `empty_ids` in both dialects, fix the body's before/after table so it reproduces. Corpus unmoved (verify). | todo | 10 |
| S11 | **The sentences the source still carries.** Review items 2 and 3 and the S6/S5 residue, swept by grep not by citation: `cli.py:398` ("prints no bracket"); both `_operation` docstrings (name unreadable → `None`, falsified by `('m','m')`); the replacement SPEC §3.7 clause falsified by `otel_genai._operation(LLM, {'gen_ai.tool.name': 't'})`; `CHANGELOG.md:1018` ceiling pairs (none coincide; match the R13 table at :555 and SPEC.md:1556, dated); `OPEN_QUESTIONS.md:594` ("0 under 256 ns" over seconds-magnitude data). Rule: for each sentence, grep the phrase repo-wide including `spanweave/` and `tests/`, fix every site, list the sites in the commit body. Docs and docstrings only. | todo | 10 |
| S12 | **Series close, final.** As S7, plus: track `reviews/2026-09-12-run5.md` with sha256; paste the review's 33 ready-made open-thread sentences into TASKS.md verbatim, each with its reproduction pointer, marking which S8–S11 closed; record the `install_check` self-plant gap (S4) and the "this commit" sha convention as threads; replace "this commit" in `audit-S*` rows with "the closing commit of run N" so the sentence is true without a sha; remove WORKPLAN.md and its README row; `make check`, `make conformance`, `make install-check`; push. | todo | 10 |

---

## 2. Execution order

Run 6 = S8 → S9 → S10 → S11 → S12. No memos. After the run: a scoped cold
review of the three code commits (S8, S9, S10) only; the PR opens unless it
finds a live traceback or an invariant violation.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-09-12 | thread 23 → S8 | CLAUDE.md invariant 4 stays unconditional. The library owns its digit limit: a numeric string longer than a spanweave constant (4300, the interpreter default) is over-limit → `missing_timestamp`, regardless of `PYTHONINTMAXSTRDIGITS`. The graph then depends on input bytes only. ENVIRONMENT.md's pinning advice is removed; SPEC §5.3 states the constant. | maintainer |

---

## 4. Resume note

- 2026-09-12: reopened after the run-5 review ("nothing blocks the PR; 33
  open threads"). Run 6 is the last run of the series; wording findings from
  its review become open threads in the PR description, not a run 7.
- 2026-09-19: S8 found the digit limit reached past timestamps: under
  `=640`, `json.dumps` of a long int, `str()`, the record digest and
  `json.loads` of a bare long literal all raised. New `spanweave/jsoncodec.py`
  owns `DIGIT_LIMIT` and is used by the reader, both adapters, build, CLI,
  annotate and serialize; the interpreter setting is never read or set.
  Suite green (2513 passed, 2 skipped) under unset, `=0` and `=640`.
- 2026-09-19: S9 made the census's output data (`Printed`), so a printed
  figure with no family fails the guard; all seven review plants red. The
  retired-figure check is per sentence and exempts a sentence that names a
  batch id or says "history"/"then-"/"working tree" -- a live sentence that
  also names a batch can still state a retired figure. For S12 / cold review.

---

## 5. Findings reference

| Source | Batch |
|---|---|
| thread 23 (invariant 4 vs digit limit) | S8 |
| run-5 review item 1 (census families, retired set) | S9 |
| run-5 review S3 finding (`links[].span_id`) | S10 |
| run-5 review items 2, 3; S6 clause; S5 residue | S11 |
| 33 open threads; S4 self-plant; "this commit" | S12 |
