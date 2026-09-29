# WORKPLAN.md — spanweave live-graphs series

Status file for the live-graphs series: the incremental builder, the delta
contract, and the receiver boundary. One batch = one sub-agent = one commit
= one concern. This file plus git is the only state; any session can resume
cold from it.

Last updated: 2026-09-29 (series opened; run 1 not started).
Baseline: 40bce13 (PR #2 merged into main, 2026-09-29). `make check` on this
commit: 2660 passed, 2 skipped, plus 82 gate checks.

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
8. `git push origin live-graphs`. A run is not finished until the push
   succeeds **and `gh pr checks` (or `gh run list --branch live-graphs`) on
   the pushed tip is green, or every failing check is explained in the run
   report**; local `make check` is not a substitute — the CI matrix runs
   interpreters the machine does not have.

Memo batches (L1, L2) are also sub-agents; they end with status
`awaiting decision` and never touch `spanweave/`. Both are already written
(§1), so run 1 reaches the decision point without dispatching either.

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
and the origin §5 gives for <ID>. Never edit WORKPLAN.md. If completing the
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
`git push origin live-graphs`. A run is not finished until the push
succeeds and `gh pr checks` (or `gh run list --branch live-graphs`) on the
pushed tip is green, or every failing check is explained in the run report;
local `make check` is not a substitute -- the CI matrix runs interpreters
the machine does not have.
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

TASKS.md is the item registry (one line per batch, written at series
close); ROADMAP.md is untouched unless a batch says otherwise; this file is
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
| L0 | **Ceilings measured, not assumed — the eleven remaining tests.** Audit thread 80: eleven tests still hard-code `100_000` as "too deep" and pass only because the `loads` and nested-dict ceilings sit below it at an 8 MB stack. Derive each from `tests/json_depth.py` as `546bdfa` did for the first four. Tests only. CI green on the pushed tip. | done (`f07b321`) | 10 |
| L1 | **Memo: prefix-consistent incremental build** (`OPEN_QUESTIONS.md` §18). | awaiting decision | — |
| L2 | **Memo: the receiver boundary** (`OPEN_QUESTIONS.md` §19). | awaiting decision | — |
| L3 | **Incremental builder, correctness first.** `Builder` with `feed`/`graph`/`version`; absorb rules for parent, call_result, data (incl. basis rewrite), temporal, diagnostics open/resolve; canonical order by O(n) resort per arrival (oracle). Conformance gate 1: replay every fixture, `graph()` == `build(prefix)` at every k. SPEC section. | awaiting L1 | 25 |
| L4 | **Journal and deltas.** Journal entries per feed; `Delta` dataclass; `delta(since)` fold with cancellation; retention policy and the raising `since`; conformance gates 2 and 3 (compare after every record; fold reproduces). `Delta` document form, additive. | awaiting L3 | 25 |
| L5 | **Canonical order without the resort.** Subtree recompute for late parents; measured against the O(n) oracle on the audit's 400-turn probe and a 20k-span wide trace; kept only if faster with the oracle still green. May end `dropped` on measurement. | awaiting L4 | 15 |
| L6 | **Envelope-to-records API.** F2's container parsing exposed on in-memory input; tests; ADAPTERS.md. | awaiting L2 | 8 |
| L7 | **Receiver project skeleton** (separate repo): file-tail ingest, per-trace builders, completion policy, delta fan-out, interleaving conformance. | awaiting L6 | 25 |
| L8 | **Live rules showcase**: agentgolden rules per delta, first-failure version recorded; `skipped_verification` flagged one version before the refund. | awaiting L7 | 15 |

---

## 2. Execution order

L0 → L1, L2 (already written) → decisions → L3 → L4 → L5 → L6 → L7 → L8 →
close. Run 1 = L0 then stop at the decision point.

L1 and L2 carry no call estimate because they are already written: the two
memos went in with this commit, so the series opens at the decision point
rather than working towards it. L3 and L6 are the first batches the
maintainer's answers unblock, and they unblock independently — L3 needs
only L1, L6 only L2.

---

## 3. Decisions log

Empty; the series takes none yet. Both memos are `awaiting decision`, and a
decision is recorded here on the commit that takes it.

---

## 4. Resume note

- 2026-09-29: series opened by this commit, from `main` at `40bce13` on
  branch `live-graphs`. Nothing under `spanweave/` moved and no batch has
  run. L0 is `todo` and is the whole of run 1. L1 and L2 are written and
  `awaiting decision`: the memos are `OPEN_QUESTIONS.md` §18 (prefix-consistent
  incremental build) and §19 (the receiver boundary), each ending on a blank
  `**Decision:**` line for the maintainer to fill. Everything from L3 on is
  blocked behind one of those two answers, so run 1 ends at the decision
  point whatever L0 finds. Restored with the plan: the `README.md` Documents
  row for this file, and the `WORKPLAN.md` exclusion in
  `durable_documents()` (`tests/test_doc_truth.py`) — the same pair every
  previous series removed at its close.
- 2026-09-29: L0 done (`f07b321`), and the row's own count was wrong in a way
  worth keeping. The eleven tests are real — at `aac1915` under
  `ulimit -s 65536` exactly those eleven fail — but they are fed by **nine**
  literal `100_000` depth sites across five files, and those nine feed
  **twelve** tests. The twelfth lives in `tests/test_cli.py` and asserts that
  `inspect` on a deep graph file is a refusal rather than a traceback; it
  shares `DEEP_VALUE` and kept passing at a 64 MB stack for a reason unrelated
  to depth, its comment claiming a sniff failure on the file's first byte that
  does not happen. Count the constants,
  not the tests. Folded in from the same assumption: `test_cli.py`'s private
  `_parser_limit()` bisected to a hard-coded `200_000` and *returned that cap*
  when nothing under it was refused; it now calls `deepest_accepted` and fails
  instead. New helper `too_deep_for_nested_dicts()` beside the lists one —
  dicts are measured separately because on 3.14.6 the two ceilings sit about
  37,000 levels apart. Depths were verified as measurements, not merely green:
  on 3.11/3.12/3.13/3.14 the derived depth is refused and one level below it
  is accepted. Pre-existing and not L0's: on 3.11-3.13 the suite crashes under
  `ulimit -s 2048` in pytest's own frames, at `aac1915` as well.
- 2026-09-29: run 1 ends here, at the decision point §2 names. Nothing is
  blocked and nothing failed; L0 needed no spec or model decision, so
  `OPEN_QUESTIONS.md` carries only §18 and §19 and both are still blank.
  Run 2 resumes at those two answers: L3 unblocks on §18 alone and L6 on §19
  alone, so a partial decision is enough to start.

---

## 5. Findings reference

| Origin | Batch |
|---|---|
| Audit thread 80 (`TASKS.md`, *September 2026 audit*): eleven tests hard-code `100_000` as "too deep", the follow-on `546bdfa` left | L0 |
| Memo: prefix-consistent incremental build (`OPEN_QUESTIONS.md` §18) | L1, and L3–L5 once it is decided |
| Memo: the receiver boundary (`OPEN_QUESTIONS.md` §19) | L2, and L6–L8 once it is decided |
