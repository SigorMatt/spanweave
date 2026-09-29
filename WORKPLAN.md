# WORKPLAN.md — spanweave live-graphs series

Status file for the live-graphs series: the incremental builder, the delta
contract, and the receiver boundary. One batch = one sub-agent = one commit
= one concern. This file plus git is the only state; any session can resume
cold from it.

Last updated: 2026-09-29 (run 1 done; L1 and L2 decided; run 2 pending).
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
| L1 | **Memo: prefix-consistent incremental build** (`OPEN_QUESTIONS.md` §18). | done | — |
| L2 | **Memo: the receiver boundary** (`OPEN_QUESTIONS.md` §19). | done | — |
| L3 | **Incremental builder, correctness first.** `Builder` with `feed`/`graph`/`version`; absorb rules for parent, call_result, data (incl. basis rewrite), temporal, diagnostics open/resolve; canonical order by O(n) resort per arrival (oracle). Conformance gate 1: replay every fixture, `graph()` == `build(prefix)` at every k. SPEC section. `feed` returns the new version `int`; no `delta=` flag. | done (`58d3e69`) | 25 |
| L4 | **Journal and deltas.** Journal entries per feed; `Delta` dataclass; `delta(since)` fold with cancellation; retention policy and the raising `since`; conformance gates 2 and 3 (compare after every record; fold reproduces). `Delta` document form, additive. `Delta` is produced only by `delta(since)`; add the per-record gate as `delta(since=version-1)` after each feed, folded onto the previous graph, equals `graph()`. | done (`7f1f40c`) | 25 |
| L5 | **Canonical order without the resort.** Subtree recompute for late parents; measured against the O(n) oracle on the audit's 400-turn probe and a 20k-span wide trace; kept only if faster with the oracle still green. May end `dropped` on measurement. Must speed up `delta()`'s two `ordering()` calls, not only `materialize()` — SPEC §10.6 puts `delta(since=v)` at O(n + e). | dropped on measurement (`79a63f4`) | 15 |
| L6 | **Envelope-to-records API.** F2's container parsing exposed on in-memory input; tests; ADAPTERS.md. | todo | 8 |
| L7 | Requires the empty GitHub repo `SigorMatt/spanweave-live` to exist; the builder clones it beside `~/git/spanweave` as `~/git/spanweave-live`. **Receiver project skeleton** (separate repo): file-tail ingest, per-trace builders, completion policy, delta fan-out, interleaving conformance. | awaiting L6 | 25 |
| L8 | **Live rules showcase**: agentgolden rules per delta, first-failure version recorded; `skipped_verification` flagged one version before the refund. | awaiting L7 | 15 |

---

## 2. Execution order

L0 → L1, L2 (already written) → decisions → L3 → L4 → L5 → L6 → L7 → L8 →
close. Run 1 = L0 then stop at the decision point; it ran and stopped there.

Run 2 = L3 → L4 → L5 → L6, in the spanweave repo, then stop: L7 and L8 live
in the receiver repo and start run 3 once it exists. Every batch: CI green on
the pushed tip before `done`. After run 2: a cold review of L3–L6 (aux), then
decisions on its findings, then run 3.

L1 and L2 carried no call estimate because they were already written: the two
memos went in with the series-opening commit, so the series opened at the
decision point rather than working towards it. Both are now decided (§3), and
they unblocked independently — L3 needed only L1, L6 only L2 — so run 2 opens
with both of them available.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-09-29 | L1 | (1) Prefix-consistency is the definition: at version k the live graph equals `build(records[:k])` byte for byte, arrival order indexing versions, canonical order inside a version. (2) Diagnostic lifecycle option (a): the graph schema does not move; open/resolved history lives only in the journal. (3) Journal implementation with the checkpoint set-difference as the test oracle; the fold must cancel; retention is caller policy (`retain(versions=N \| "all" \| 0)`, default "all"); a `since` older than retention raises with a code. (4) API as sketched with one refinement: `feed(record)` always returns the new version `int` (never a graph, never a delta); every delta comes from `delta(since=v)`; the per-record mode is `delta(since=version - 1)`. `graph()` materializes on demand. The three-mode conformance gate (silent feed then compare; compare after every record; fold reproduces) is the acceptance test for L3–L4. | maintainer |
| 2026-09-29 | L2 | (1) The receiver is a separate project, `SigorMatt/spanweave-live`, not a subpackage. (2) The only spanweave change L2 needs is the additive envelope-to-records API (L6). (3) Completion is receiver policy; spanweave emits nothing about it. (4) The showcase (L8) is agentgolden's rules evaluated per delta, rules file unchanged, bringing its own trace since no conformance fixture carries the scenario. | maintainer |

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
- 2026-09-29: L1 and L2 decided; the `feed` return-type refinement is the one
  departure from the memo's sketch and is recorded in §3. L7 waits on the
  receiver repo being created by the maintainer.
- 2026-09-30: L3 done (`58d3e69`), CI green on the pushed tip, and the
  schema did not move — option (a) held. Gate 1 (`graph()` ==
  `graph_from_records(prefix)` at every k, by value *and* `dumps` bytes) runs
  over all 60 renderings and was verified by deliberate breakage rather than
  by greenness: disabling the parent, data and temporal absorb rules fails
  8, 27 and 5 corpus assertions respectively. Two findings L4 and L5 must
  carry, both departures from the §18 memo's own sketch: (1) "node ids never
  move" is **false** in two corpus-reachable ways — a majority trace-id
  change and a span id that stops being unique each move ids already issued.
  Such an arrival restates the whole state (O(n), `SPEC.md` §10.2), so its
  journal entry is *not* local and L4 must handle a non-local entry. (2)
  `meta.adapters[].declared_confidence` is declared over a growing 50-record
  sample, so it changes between versions; the Builder restates it per claimed
  record. Without that, prefix consistency would have failed silently on
  `meta` alone. No incremental case existed in `tests/audit/probe*.py`, so
  nothing was converted out.
- 2026-09-30: L4 done (`7f1f40c`), CI green, and again no schema movement —
  `make shape` regenerates `tests/serialized_shape.json` byte-identically, so
  the graph document gained no key. Gates 2 and 3 are 106 parametrized
  assertions over all 60 buildable renderings, verified by deliberate
  breakage: cancellation off fails 25, dropping the order-derived
  `ordering_cycle` fails 2, not restating whole-input statements fails 4, and
  a fold that does not recompute order fails 5. Three things later batches
  must carry. (1) **`SPEC.md` §10.6 is renumbered territory**: the old §10.6
  "Out of scope here" is now §10.10 and §10.6–§10.9 are the new
  delta/journal/retention/document sections; nothing outside SPEC cited the
  old number. (2) The cost split §10.6 now states: `feed` is O(keys touched)
  but `delta(since=v)` is **O(n + e)**, because it sorts both endpoints to
  recover canonical order and `ordering_cycle` — so L5's subtree recompute
  has to reach `delta()`'s two `ordering()` calls
  (`spanweave/delta.py:ordering`, `api.py:Builder.delta`), not only
  `materialize()`. (3) `spanweave/incremental.py` now keeps two accountings
  of the same three collections — its own per-key dicts, which define the
  graph's byte order, and the journal's `Tally`; their agreement is proven
  only by conformance gate 2, so a batch that unifies them must keep that
  gate green. Two departures from the §18 memo's sketch, both stated in SPEC:
  `Delta` carries no `annotations_*` (a builder never annotates, and `fold`
  preserves the graph's own) and it does carry `trace_id_*` / `adapters_*`
  because `meta` moves, with the three `meta` counts recomputed by the fold
  rather than travelling. Correcting L3's finding (2): neither registered
  adapter's `declared_confidence` actually moves with the growing sample —
  both answer 0.9 to any sample holding a record they claim — so the
  mechanism is carried and tested but the observable change needs a third
  adapter. New error code `delta_unavailable` (§3.10,
  `DeltaUnavailableError`).
- 2026-09-30: L5 **dropped on measurement** (`79a63f4`), CI green. Nothing
  under `spanweave/` moved; what landed is the benchmark (`tests/live_cost.py`,
  `make bench`), a `SPEC.md` §10.6 cost statement, and one test. The numbers,
  at `1d7ba8f` on CPython 3.14.6 — **echo** (the audit's 400-turn loop, 801
  nodes / 81,799 edges): `feed` 75.5 s = 94.2 ms/record, `graph()` 312 ms of
  which `in_order` 13.8 ms, `delta(since=v-1)` 229 ms of which the two
  `ordering()` calls 32.4 ms (14%) and endpoint assembly/rewind 140 ms.
  **wide** (20,000 spans, 20,001 nodes / 39,999 edges): `feed` 1,449 s =
  72.4 ms/record, `graph()` 391 ms, `delta(since=v-1)` 295 ms of which the two
  `ordering()` calls 176.6 ms (60%). Why it was dropped rather than kept: the
  recompute could improve **only `delta()`, and only on the wide shape** —
  `feed` never sorts at all (`build.in_order` is reached from the batch build,
  `materialize()` and `delta.ordering`, nowhere else), so a maintained order
  adds to `feed` and removes nothing. And the wide shape's 60% is not
  reachable by a *faster* sort — a heap Kahn was measured at an identical
  sequence and 2.1×, i.e. 3% of `delta()` — but only by *not sorting*, which
  means carrying canonical order and `ordering_cycle` between versions,
  reversing what §10.6/§10.7 deliberately promise and adding a second ordering
  rule beside §5.2's. That is a spec conversation; it is written down in
  `SPEC.md` §10.6 and `CHANGELOG.md` and deliberately not started. (This repo
  has no `DEBT.md`; SPEC is where the deferral lives.) **The finding that
  outlives the batch**, and the one for the cold review to weigh: the two real
  quadratics in `feed` are not ordering at all — the wide shape rebuilds its
  one sibling group's whole temporal chain on every arrival, and the echo
  shape rebuilds a call id's whole `data` edge set per echoed receipt. §10.6
  now states that a key is restated in full, so "touches only the keys the
  record names" can no longer be read as "cheap": 8× the records of a wide
  trace is 116× the feed.

---

## 5. Findings reference

| Origin | Batch |
|---|---|
| Audit thread 80 (`TASKS.md`, *September 2026 audit*): eleven tests hard-code `100_000` as "too deep", the follow-on `546bdfa` left | L0 |
| Memo: prefix-consistent incremental build (`OPEN_QUESTIONS.md` §18) | L1, and L3–L5 once it is decided |
| Memo: the receiver boundary (`OPEN_QUESTIONS.md` §19) | L2, and L6–L8 once it is decided |
