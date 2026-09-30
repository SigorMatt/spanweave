# WORKPLAN.md — spanweave live-graphs series

Status file for the live-graphs series: the incremental builder, the delta
contract, and the receiver boundary. One batch = one sub-agent = one commit
= one concern. This file plus git is the only state; any session can resume
cold from it.

Last updated: 2026-10-01 (run 3 in progress: L9 done; L10-L14 to go, then a
cold review. L7 and L8 moved to run 5).
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
| L6 | **Envelope-to-records API.** F2's container parsing exposed on in-memory input; tests; ADAPTERS.md. | done (`b5145de`) | 8 |
| L7 | Requires the empty GitHub repo `SigorMatt/spanweave-live` to exist; the builder clones it beside `~/git/spanweave` as `~/git/spanweave-live`. **Receiver project skeleton** (separate repo): file-tail ingest, per-trace builders, completion policy, delta fan-out, interleaving conformance. | awaiting the receiver repo (L6 is done; the repo does not exist yet) | 25 |
| L8 | **Live rules showcase**: agentgolden rules per delta, first-failure version recorded; `skipped_verification` flagged one version before the refund. | awaiting L7 | 15 |
| L9 | **`patches/` is ignored.** T14: one line in `.gitignore`; verify `git status --porcelain` no longer lists `patches/` and that `git add -A` in a scratch worktree stages nothing from it. Subject `chore: patches/ is ignored`. No test. | done (`ad257bc`) | 2 |
| L10 | **A refused record leaves the builder as it was.** B1: in `incremental.py`, every check that can refuse runs before any state is touched — the collision check precedes `self._spans.append`; nothing in `_ids`/`_nodes`/`_record_diagnostics`/the tally/the journal moves on a refusal. Tests red on the parent: after `DuplicateNodeIdError`, `version` unchanged, `graph()` byte-identical to before the refusal, a later `feed` succeeds and `graph()` equals `build` of the records minus the refused one; the same for the two-adapter refusal (already asserted for `version`, extend to `graph()`); both §10.5 bullets carry a test. SPEC §10.5 unchanged (it already promises this). | todo | 8 |
| L11 | **The two receiver properties are pinned, each by a test that bites alone.** B2, N1, tests only. (a) `read_records` called twice, the first call ending in an unterminated fragment: the fragment is one `malformed_record` with `skipped_records=1`, the second call never yields it, and a mutation that carries the fragment over (the review's `_CARRY`) fails this test **when run alone**. (b) the same record in two calls: yielded twice, no `duplicate_record`; a mutation that dedups across calls or emits a cross-call `duplicate_record` fails **when run alone**. Prove "alone" by `pytest tests/test_read.py::<name>` for each new test under each mutation in a throwaway worktree; record the four results in the commit body. No test in the commit may depend on what an earlier test read. | todo | 8 |
| L12 | **Undecodable bytes are a diagnostic, not a silent replacement.** T12. A byte sequence UTF-8 cannot decode is still replaced with U+FFFD and the record still read, but the read emits `undecodable_bytes` (record-scoped where a record results, naming the line; `skipped_records` unchanged), for `read_records`, file reads and every `errors="replace"` site (`read.py:243,278,312`). SPEC §3.7 enumerates the code; §7 gains one sentence: the reader neither buffers nor rejoins across calls, so a receiver splits its bytes on `\n` before calling. Tests red on the parent: `read_records(b'{"span_id":"\xff\xfe"}\n')` yields the record with the diagnostic; a valid multi-byte sequence split across two calls gives two diagnostics and two `malformed_record`s, not one record; a file with the same bytes matches. Corpus unmoved (verify — no fixture carries invalid bytes). | todo | 10 |
| L13 | **`read_records` accepts `bytearray` and `memoryview`.** T13: `isinstance(data, (bytes, bytearray, memoryview))`; the copy, if any, is the library's; `str` still refused with the path rationale. SPEC §7 one clause. Test red on the parent: a `bytearray` accumulator read in place yields what `bytes(buf)` yields; `memoryview` likewise. | todo | 4 |
| L14 | **The delta surface is pinned where the review found it wasn't.** N4, T9, tests only. `tests/schema_shape.py` specimens a `Delta` document beside the `Graph` one, so `tests/serialized_shape.json` sees `delta_to_document` (regenerated, with the explanation in the body; the `Graph` half byte-identical — verify). Gate 2 adds windows with `until < n` and width > 1 (at least `(1, n//2)`, `(n//4, 3n//4)`, `(n-3, n-1)` per rendering) against the oracle. Print the new assertion count. | todo | 6 |
| L15 | **A sibling group's temporal chain is maintained, not rebuilt.** Site (i): `_restate_chain` rebuilds the group's whole chain per arrival, O(m log m) and m−1 new `Edge`s. Keep each group's members in sorted order (`bisect` on the §4.3 tie-break key), and on an arrival replace only the chain edges adjacent to the insertion point — at most one removed, two added — through per-edge ledger add/drop instead of `Tally.set_edges` of the whole key. Prefix-consistency is untouched: gates 1–3 green on every rendering. Acceptance in `make bench`: wide shape `feed` ms/record at k=8000 within 1.5× of k=1000 (review: 11.3×), and `Edge.__init__` count linear in n under `cProfile`. | todo | 20 |
| L16 | **A late parent regroups its waiting children once.** Site (iii): `_regroup` per waiting child, each a full chain restate. On a parent arriving after its children, move every waiting child into the group and restate the chain **once**, O(n log n) for that one `feed`. Gates 1–3 green. Acceptance: wide shape with the root fed last, total `feed` within 2× of root-first (review: 15.4 s for the single arrival at n=2000). | todo | 12 |
| L17 | **A call id's `data` edges are maintained per receipt.** Site (ii): `build.data_edges` re-emits every (receiver, fulfiller) pair of a call id per new receipt because `basis` depends on which receipt ranks first — cubic in turns on the echo shape. Keep per call id the ranked-first receipt; a new receipt that does not outrank it adds its own edges and nothing else; one that does outrank it rewrites the previous first's basis (one removal, one addition per affected edge) and no other. Gates 1–3 green; `basis_rewritten` still reports every pair (gate 3 and `tests/test_live.py:550-592` are the pin). Acceptance: echo 400-turn `feed` ms/record for turns 301–400 within 1.5× of turns 1–100, and `Edge.__init__` count linear in receipts. | todo | 20 |
| L18 | **§10.6 on fresh numbers, and a harness that measures what the prose says.** N2, N3, T1–T5, after L15–L17. `tests/live_cost.py` times the materialize sort, the rewind, and both `ordering()` calls of one `delta()` separately; gains `--smoke` (`--turns 5 --wide 5`) that `make check` runs. SPEC §10.2/§10.6 cost paragraphs rewritten: complexity classes as promises (`feed` O(size of the keys touched) with the three former sites named as fixed), numbers cited to the harness with date, interpreter and commit, no bare ratios; the heap-Kahn sentence removed and the rejected subtree-recompute alternative named beside the deferred "no sort" question. CHANGELOG's heap-Kahn line reworded to "measured in the batch session; harness not retained". WORKPLAN §4 numbers are left as history. Re-measure both shapes at the new tip and put the numbers in the harness header. | todo | 10 |
| L19 | **The run-2 review archived and every finding dispositioned.** `reviews/2026-09-30-live-run2.md` byte-for-byte, sha256 in the body; TASKS.md subsection "Cold review of live-graphs run 2 — 2026-09-30": B1, B2, N1–N5, T12, T13 closed by their batches; T6, T8, T10, T11 registered as open threads with the review's sentences verbatim; T7 recorded as a correction. CHANGELOG entry. `make check`. | todo | 6 |

---

## 2. Execution order

L0 → L1, L2 (already written) → decisions → L3 → L4 → L5 → L6 → L7 → L8 →
close. Run 1 = L0 then stop at the decision point; it ran and stopped there.

Run 2 = L3 → L4 → L5 → L6, in the spanweave repo, then stop.

Run 3 = L9 → L10 → L11 → L12 → L13 → L14, spanweave repo, then stop: cold
review of L9–L14 (aux), decisions, then run 4. Run 4 = L15 → L16 → L17 →
L18 → L19, then stop: cold review, decisions. Run 5 = L7 → L8 in
`SigorMatt/spanweave-live` once it exists. Every batch: CI green on the
pushed tip before `done`. The cost batches precede L7 because a receiver is
not designed against a `feed` that costs 72 ms/record.

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
| 2026-09-30 | review run 2 | B1 and B2 are accepted as blocking L7 and are fixed before it (L10, L11). N1 is folded into L11. N4 and T9 are one test-only batch (L14). N5 and T7 are corrections to this file, made in this commit. T12 is a behaviour change decided here: an undecodable byte sequence is a diagnostic, never a silent replacement (L12). T13 is accepted (L13). T14 is a one-line chore (L9). T6, T8, T10, T11 are threads, registered in L19. | maintainer |
| 2026-09-30 | L5 / §10.6 | The review's independent re-measurement (90.2× vs the note's 116×; three superlinear sites, one cubic, one inside a single `feed`) stands as the record. The drop of the *resort* batch holds — ordering is not the cost. The three sites in `feed` are implementation, not spec: §10.1 is the promise, §10.2/§10.6's cost paragraphs describe the implementation and are rewritten on fresh numbers once the sites are fixed (L15–L18). The "no sort" conversation about carrying canonical order between versions stays deferred and gets no batch; it is revisited only after L18's numbers, since `delta()` at a few hundred ms on 20k spans is not what makes the builder unusable — `feed` is. | maintainer |
| 2026-09-30 | N2, T1–T5 | SPEC states complexity classes as promises and cites `tests/live_cost.py` for numbers with their provenance; bare machine ratios leave SPEC. The heap-Kahn claim is removed from SPEC and reworded in CHANGELOG as "measured in the batch session; harness not retained", because nothing can reproduce it. §10.6 names the rejected subtree-recompute alternative (T2). `make bench` gains a smoke form that `make check` runs (T5); the harness times what the prose attributes (N3, T3, T4). All in L18, after the numbers have changed. | maintainer |
| 2026-09-30 | runs | Run 3 = L9 → L10 → L11 → L12 → L13 → L14, spanweave repo, then stop for a cold review. Run 4 = L15 → L16 → L17 → L18 → L19, then stop for a cold review. Run 5 = L7 → L8 in the receiver repo, which still does not exist. A receiver is not designed against a `feed` that costs 72 ms/record, so the cost batches precede L7. | maintainer |

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
  over all 53 renderings (106 assertions) and was verified by deliberate
  breakage rather than
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
  assertions over all 53 buildable renderings, verified by deliberate
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
  by conformance gates 2 and 3 (the review showed gate 3 catches it too: 30
  failures with `Tally.set_edges` skipping `temporal`), so a batch that
  unifies them must keep those gates green. Two departures from the §18 memo's sketch, both stated in SPEC:
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
- 2026-09-30: L6 done (`b5145de`), CI green, additive and no schema movement.
  `spanweave.read_records(data) -> Records` with `.records`,
  `.diagnostics`, `.skipped_records` and `__iter__`; 13 tests, all confirmed
  failing at `d061268` first. It is eager (complete when returned), takes
  `bytes` only (a `str` is a `TypeError` and never a path read), consults no
  adapter and builds nothing. The neutrality gate rejected the word "cost" in
  a `spanweave/` docstring; it was reworded, not exempted. **Three properties
  the receiver (L7) must design around**, all measured rather than assumed:
  (1) there is **no buffering across calls** — a truncated trailing line is one
  `malformed_record` with `skipped_records=1`, so framing complete records and
  documents is the receiver's job; (2) **dedup scope is per call** — two calls
  carrying the same record yield it twice, with no `duplicate_record`; (3)
  reading an export is cheap and absorbing it is not — N spans is N `feed`
  calls, at the cost §10.6 and L5's numbers state.
- 2026-09-30: **run 2 ends here.** L3, L4, L6 done and L5 dropped on
  measurement, each with CI green on its own pushed tip; nothing blocked and
  nothing left `awaiting decision`. The schema did not move in any of the four
  — `tests/serialized_shape.json` is byte-identical to its state at `27ec3db`,
  which is option (a) from the L1 decision holding across the whole run. Next,
  per §2: a cold review of L3–L6 by aux (`Review WORKPLAN.md commits since
  27ec3db`), then decisions on its findings, then run 3. Two things for that
  review to weigh, both from L5: the two quadratics in `feed` that are not
  ordering, and the spec conversation about carrying canonical order between
  versions that §10.6 records and no batch has started. Run 3 (L7, L8) cannot
  start until the maintainer creates `SigorMatt/spanweave-live`; L7's row now
  says that rather than `awaiting L6`, which is satisfied.
- 2026-09-30: run-2 cold review read and decided (§3). Two blockers before
  L7 (a refusal that corrupts the builder; a receiver property with no test),
  one behaviour decision (undecodable bytes get a diagnostic), and the three
  superlinear `feed` sites the review confirmed and measured — one cubic, one
  O(n² log n) inside a single `feed` — become L15–L17. The review's numbers
  (90.2× at k=1000→8000, not 116×) are the record; §10.6 is rewritten on
  fresh numbers in L18 after the sites are fixed. Runs 3 and 4 in this repo,
  run 5 in the receiver repo.
- 2026-10-01: L9 done (`ad257bc`), CI green. One `.gitignore` line, and the
  proof is a counter-check rather than a green `git status`: in a throwaway
  worktree with review and patch files planted under `patches/`, `git add -A`
  staged nothing, while the same worktree with the parent's `.gitignore`
  restored staged two — so the new line is what does the work, not an
  already-empty directory. No test asserts on `.gitignore` contents or on the
  untracked-file set (`tests/install_check.py` and `tests/test_acceptance.py`
  know `.gitignore` only as a tracked root file name), so nothing needed
  updating. Note for the series close: `git format-patch main -o patches/`
  (§0.1 step 7) still works, but its output is now invisible to
  `git status` — a run's patches must be listed with `ls`, not looked for in
  the porcelain.

---

## 5. Findings reference

| Origin | Batch |
|---|---|
| Audit thread 80 (`TASKS.md`, *September 2026 audit*): eleven tests hard-code `100_000` as "too deep", the follow-on `546bdfa` left | L0 |
| Memo: prefix-consistent incremental build (`OPEN_QUESTIONS.md` §18) | L1, and L3–L5 once it is decided |
| Memo: the receiver boundary (`OPEN_QUESTIONS.md` §19) | L2, and L6–L8 once it is decided |
