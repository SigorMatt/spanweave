# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-12 (reopened for run 5: run-4 review findings; PR follows).
Baseline: b091904 (second close), 2435 tests pass, 2 skipped.

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
| S1 | **Every census figure is guarded, and TASKS.md says only what is true.** Review F1: `CENSUS_FIGURE_PATTERNS` is eight fixed families; `corpus_census.py` computes figures no family matches (records with a span id 139, trace-unique ids 135, three zero-counts). Replace the fixed list with a guard derived from the census's own output: every figure the census prints must be matched by a family, and a test fails if the census emits a figure with no family. Plant each of the review's five surviving figures and prove red. Then correct `TASKS.md:10733` to the scope that is now actually closed. | todo | 15 |
| S2 | **Error-output sentence matches the test.** Review F2: README.md:199, SPEC.md:1693, CHANGELOG.md:344 say an `OSError` prints no bracket; `tests/test_cli.py:630` asserts `[Errno 2]`. Reword all three to what the test asserts and say that `[Errno N]` is the OS's text, not a spanweave code, and that the spanweave bracket is the only one a caller should route on. Docs only. | todo | 5 |
| S3 | **Empty string is not an identity.** Per §3 decision: `span_id: ""` (both dialects, both containers) → content-derived fallback + diagnostic, as for a missing id; SPEC §3.6 and §893 sentence; conformance degenerate scenario `empty_ids` with a `""` span id and a `""` parent in both dialects, expected graph carries the explicit parent edge the review showed being lost (`('', 'c')` on the parent commit) — or, if the decision makes that edge unstatable, the fixture proves nothing is dropped silently. Corpus expectations must not move (verify). | todo | 15 |
| S4 | **Sdist citation guard sees directories.** Review F4: `CITED_PATH` needs two segments and a trailing slash, so `reviews/` and `.github/` are invisible. Widen to any cited path that resolves to a tracked file or directory; plant `reviews/` and `.github/` absent from the sdist include list and prove red. | todo | 6 |
| S5 | **Three wrong numbers.** Review F5 (SPEC.md:1632 "~238 ns" → 256 ns at 1.7e18, matching SPEC.md:162 and ADAPTERS.md:175), F6 (OPEN_QUESTIONS §16(a): the indented export gives 4 nodes and no `malformed_record`; state it dated, do not rewrite history), F7 (`tests/digit_limit.py:16` "five tests" → seven). Also the review's counting nits: R15's "38 candidates", R7's two, and the two bare `R3`s at TASKS.md:10720/:10782 → `audit-R3`. Docs only. | todo | 6 |
| S6 | **Nits with a code or spec surface.** R8's SPEC over-statement, R12's missing seventh key and the ungrammatical SPEC.md:521, R14's unqualified determinism claim in SPEC §5.1 and README.md:169 (qualify with the digit-limit dependency §5.3 already states). Take each from the review's per-batch sections; one commit. Corpus must not move. | todo | 10 |
| S7 | **Series close, third time.** As R7, plus: the two unowned threads (a gate holding future adapters to the `parent_ref` convention; OPEN_QUESTIONS §17's figures unguarded by doc-truth) recorded as open threads; the run-4 review tracked under `reviews/2026-09-11-run4.md` and accounted finding by finding; the review's closing observation — that every new guard was advertised slightly beyond its scope — recorded verbatim as the lesson; WORKPLAN.md and its README row removed; `make check`. | todo | 8 |

---

## 2. Execution order

Run 5 = S1 → S2 → S3 → S4 → S5 → S6 → S7. No memos.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-09-12 | S3 | An empty string is not a span identity. A record whose `span_id` is `""` takes the same content-derived fallback as one with no `span_id` (A5's rule), with the same diagnostic; an empty `parent_id`/`parentSpanId` means "no parent" (R10's rule) and therefore loses nothing, because no node can be named `""`. SPEC §3.6 states both halves together and the sentence at §893 becomes true. | maintainer |

---

## 4. Resume note

- 2026-09-12: reopened for the run-4 review. Rule agreed with the maintainer:
  the PR opens after this run unless its review finds a live traceback or an
  invariant violation; wording findings become open threads.

---

## 5. Findings reference

| Review finding | Batch |
|---|---|
| F1 five census figures unguarded; TASKS.md over-claims | S1 |
| F2 OSError bracket sentence false in three documents | S2 |
| F3 `""` parent → explicit edge lost silently | S3 |
| F4 `CITED_PATH` blind to directory citations | S4 |
| F5, F6, F7 and counting nits | S5 |
| per-batch nits with spec surface | S6 |
| two unowned threads | S7 |
