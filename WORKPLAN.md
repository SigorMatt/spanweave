# WORKPLAN.md — spanweave live-graphs series

Status file for the live-graphs series: the incremental builder, the delta
contract, and the receiver boundary. One batch = one sub-agent = one commit
= one concern. This file plus git is the only state; any session can resume
cold from it.

Last updated: 2026-10-02 (run 4 done and reviewed: L20, L21, L22, L15, L16,
L17, L18, L19, each with CI green on its own pushed tip. The run-4 cold review
(`patches/REVIEW-2026-10-02.md`) found the code sound and every acceptance
number re-taken independently; what blocks the merge is prose and the series
close. It is decided (§3) and run 5 is ordered: L23 → L24 → L25 → L26 → L27 →
L28 in this repo, then a scoped cold review of L23–L25 and L28 (aux) and the
PR to `main`. L28 deletes this file, so no `plan:` commit follows it. L7 and L8
move to their own series in `SigorMatt/spanweave-live`).
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
on the parent, run the test there), and the parent is `<sha>^`, derived —
never a sha a brief names, because `plan:` commits interleave with code
commits; no `hash()`, clock, or network in
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
| L10 | **A refused record leaves the builder as it was.** B1: in `incremental.py`, every check that can refuse runs before any state is touched — the collision check precedes `self._spans.append`; nothing in `_ids`/`_nodes`/`_record_diagnostics`/the tally/the journal moves on a refusal. Tests red on the parent: after `DuplicateNodeIdError`, `version` unchanged, `graph()` byte-identical to before the refusal, a later `feed` succeeds and `graph()` equals `build` of the records minus the refused one; the same for the two-adapter refusal (already asserted for `version`, extend to `graph()`); both §10.5 bullets carry a test. SPEC §10.5 unchanged (it already promises this). | done (`b40dac9`) | 8 |
| L11 | **The two receiver properties are pinned, each by a test that bites alone.** B2, N1, tests only. (a) `read_records` called twice, the first call ending in an unterminated fragment: the fragment is one `malformed_record` with `skipped_records=1`, the second call never yields it, and a mutation that carries the fragment over (the review's `_CARRY`) fails this test **when run alone**. (b) the same record in two calls: yielded twice, no `duplicate_record`; a mutation that dedups across calls or emits a cross-call `duplicate_record` fails **when run alone**. Prove "alone" by `pytest tests/test_read.py::<name>` for each new test under each mutation in a throwaway worktree; record the four results in the commit body. No test in the commit may depend on what an earlier test read. | done (`4807ae6`) | 8 |
| L12 | **Undecodable bytes are a diagnostic, not a silent replacement.** T12. A byte sequence UTF-8 cannot decode is still replaced with U+FFFD and the record still read, but the read emits `undecodable_bytes` (record-scoped where a record results, naming the line; `skipped_records` unchanged), for `read_records`, file reads and every `errors="replace"` site (`read.py:243,278,312`). SPEC §3.7 enumerates the code; §7 gains one sentence: the reader neither buffers nor rejoins across calls, so a receiver splits its bytes on `\n` before calling. Tests red on the parent: `read_records(b'{"span_id":"\xff\xfe"}\n')` yields the record with the diagnostic; a valid multi-byte sequence split across two calls gives two diagnostics and two `malformed_record`s, not one record; a file with the same bytes matches. Corpus unmoved (verify — no fixture carries invalid bytes). | done (`be16fa8`) | 10 |
| L13 | **`read_records` accepts `bytearray` and `memoryview`.** T13: `isinstance(data, (bytes, bytearray, memoryview))`; the copy, if any, is the library's; `str` still refused with the path rationale. SPEC §7 one clause. Test red on the parent: a `bytearray` accumulator read in place yields what `bytes(buf)` yields; `memoryview` likewise. | done (`6b2e866`) | 4 |
| L14 | **The delta surface is pinned where the review found it wasn't.** N4, T9, tests only. `tests/schema_shape.py` specimens a `Delta` document beside the `Graph` one, so `tests/serialized_shape.json` sees `delta_to_document` (regenerated, with the explanation in the body; the `Graph` half byte-identical — verify). Gate 2 adds windows with `until < n` and width > 1 (at least `(1, n//2)`, `(n//4, 3n//4)`, `(n-3, n-1)` per rendering) against the oracle. Print the new assertion count. | done (`b10c60a`) | 6 |
| L15 | **A sibling group's temporal chain is maintained, not rebuilt.** Site (i): `_restate_chain` rebuilds the group's whole chain per arrival, O(m log m) and m−1 new `Edge`s. Keep each group's members in sorted order (`bisect` on the §4.3 tie-break key), and on an arrival replace only the chain edges adjacent to the insertion point — at most one removed, two added — through per-edge ledger add/drop instead of `Tally.set_edges` of the whole key. Prefix-consistency is untouched: gates 1–3 green on every rendering. Acceptance in `make bench`: wide shape `feed` ms/record at k=8000 within 1.5× of k=1000 (review: 11.3×), and `Edge.__init__` count linear in n under `cProfile`. | done | 20 |
| L16 | **A late parent regroups its waiting children once.** Site (iii): `_regroup` per waiting child, each a full chain restate. On a parent arriving after its children, move every waiting child into the group and restate the chain **once**, O(n log n) for that one `feed`. Gates 1–3 green. Acceptance: wide shape with the root fed last, total `feed` within 2× of root-first (review: 15.4 s for the single arrival at n=2000). | done | 12 |
| L17 | **A call id's `data` edges are maintained per receipt.** Site (ii): `build.data_edges` re-emits every (receiver, fulfiller) pair of a call id per new receipt because `basis` depends on which receipt ranks first — cubic in turns on the echo shape. Keep per call id the ranked-first receipt; a new receipt that does not outrank it adds its own edges and nothing else; one that does outrank it rewrites the previous first's basis (one removal, one addition per affected edge) and no other. Gates 1–3 green; `basis_rewritten` still reports every pair (gate 3 and `tests/test_live.py:550-592` are the pin). Acceptance: echo 400-turn `feed` ms/record for turns 301–400 within 1.5× of turns 1–100, and `Edge.__init__` count linear in receipts. | done; the second criterion met exactly, the first unmeetable as written and corrected in L18 (§4) | 20 |
| L18 | **§10.6 on fresh numbers, and a harness that measures what the prose says.** N2, N3, T1–T5, after L15–L17. `tests/live_cost.py` times the materialize sort, the rewind, and both `ordering()` calls of one `delta()` separately; gains `--smoke` (`--turns 5 --wide 5`) that `make check` runs. SPEC §10.2/§10.6 cost paragraphs rewritten: complexity classes as promises (`feed` O(size of the keys touched) with the three former sites named as fixed), numbers cited to the harness with date, interpreter and commit, no bare ratios; the heap-Kahn sentence removed and the rejected subtree-recompute alternative named beside the deferred "no sort" question. CHANGELOG's heap-Kahn line reworded to "measured in the batch session; harness not retained". WORKPLAN §4 numbers are left as history. Re-measure both shapes at the new tip and put the numbers in the harness header. | done | 10 |
| L19 | **The run-2 and run-3 reviews archived and every finding dispositioned.** Archives **both** reviews — `reviews/2026-09-30-live-run2.md` and `reviews/2026-10-01-live-run3.md`, byte-for-byte, sha256 in the body — and dispositions both: run 2's as already written (TASKS.md subsection "Cold review of live-graphs run 2 — 2026-09-30": B1, B2, N1–N5, T12, T13 closed by their batches; T6, T8, T10, T11 registered as open threads with the review's sentences verbatim; T7 recorded as a correction); run 3's findings 1, 2, 3, 4, 7 closed by L20, L21, L22; finding 5 recorded as a correction to `b10c60a`'s body (gate 3 was not changed; mid-stream windows are redundant by construction); finding 6 recorded as corrected in the plan; the ten threads registered with the review's sentences verbatim. CHANGELOG entry. `make check`. | done | 8 |
| L20 | **A record is absorbed whole or not at all.** Review finding 1. `feed` classifies and translates the record, absorbs every span it yields into a staged change, and commits that change — `_claimed`, `_sample`, `_unread`, `_spans`, `_ids`, `_nodes`, `_record_diagnostics`, the tally, the ledger snapshot and `_version` — only when nothing refused; on a refusal every one of them is as it was, including the ledger's snapshot so that `delta(since=0)` after a refusal is the delta of an empty builder. Design the rollback once, as the thing L15/L17's per-edge ledger traffic will also go through. Tests red on the parent: (a) openinference alone — a refused record does not flip `graph()` from refusing to building, `_claimed`/`_sample`/`_unread` unchanged; (b) a test-local adapter yielding two spans per record whose second span collides — `version` unchanged, `graph()` byte-identical, `delta(since=0)` empty, a later `feed` equals `build` of the records minus the refused one. SPEC §10.5: one sentence making the umbrella cover all four bullets, and stating that a record's spans arrive together. Gates 1–3 green. | done | 12 |
| L21 | **`read_records` tests bite on every container and every branch.** Review findings 2 and 7, tests only. The no-carry property of L11 pinned for the array and the OTLP-document containers as it is for lines: a trailing fragment of each is `malformed_record`/`skipped_records=1` and the next call never sees it, with the review's carry mutation failing each new test **when run alone** (the four results in the body, as L11 did). L13's two refusals get distinct messages or distinct assertions so a branch swap fails a test. | done | 6 |
| L22 | **Two SPEC sentences made true, and a census that cannot go stale.** Review findings 3 and 4. `SPEC.md:2390` (§10.9) says what `tests/serialized_shape.json` now carries and when it moved; `SPEC.md:709`'s "three carry nothing" becomes the measured count, and a doc-truth check asserts the prose census equals the vocabulary's `null`-source count so the next addition fails `make check` instead of aging. CHANGELOG entry. No behaviour change; say so in the body. | done | 4 |
| L23 | **`_whole_input_from` is rolled back with everything else.** Review A4. `begin()` snapshots the memo; `rollback_to` restores it after `_tally.rollback()`, so no later derivation short-circuits on a memo the refused arrival wrote. Test red on the parent: the review's reproduction — a refused duplicate, then an unclaimed record, then a claimed one — `delta(since=0).diagnostics_opened` equals `graph().diagnostics` (three codes, not two); extend the L20 attribute probe so `_whole_input_from` is among the attributes compared. SPEC unchanged (§10.5 already promises it). Gates 1–3 green. | todo | 5 |
| L24 | **`basis_rewritten` reports every pair, pinned.** Review C1. A test in `tests/test_live.py` with two fulfillers and an out-of-order receiver whose arrival rewrites both edges' basis, asserting both pairs and that `delta(since)` removes both stale edges; the mutant `removed.extend(stale[:1])` at `incremental.py:599` must fail it (record the run). Add a conformance scenario carrying an out-of-order basis rewrite if both dialects can render one (`FIXTURES.md` rules, expected graphs regenerated with the explanation); if only one can, say so in the body and the test stands alone. Tests and fixtures only. | todo | 8 |
| L25 | **A call role is read the same way live and in batch.** Review thread. `incremental.py:525` and `build.py:644` compare `CallRole` with `==`, not `is`; the live `sorted(set(span.call_ids))` dedup is mirrored in `build.py` or the two are asserted equal by a test. Test red on the parent: a test-local adapter yielding `role="fulfiller"` as a plain `str` builds the same graph bytes live and in batch. SPEC §10.1 unchanged; ADAPTERS.md one sentence that a role is compared by value. Gates 1–3 green. | todo | 5 |
| L26 | **The cost record is exact and re-takeable.** Review A1, C3, C4, C5, B.2, B.4. `SPEC.md` §10.6 `:2412-2417` rewritten in the honest form: the per-record rise is bounded above by the rise in declarations (`(F + c·d₂)/(F + c·d₁) ≤ d₂/d₁`, equality at F = 0), the measured gap is fixed per-record cost, and the 1.5× criterion was unreachable at ~11 µs per edge — an empirical claim about constants, not a consequence of §4.2.1; the same correction in `CHANGELOG.md:513-517`, `TASKS.md:12865-12866` and `tests/live_cost.py:107-111`. The 24.6 figure states its 201-record denominator. `tests/live_cost.py` prints per-segment receipt counts so the declaration ratio is harness output, and the default `make bench` runs the two shapes in separate processes (or the header says the table was taken with `--only`). The heap guard adds `not re.search(r"faster sort", spec, re.I)`. `SPEC.md:2514`'s "and has moved since" corrected to the real order (L12 precedes L14). `OPEN_QUESTIONS.md:3391-3393` marks the subtree recompute as rejected on measurement, citing §10.6. Docs, tests and harness only; say so in the body. | todo | 8 |
| L27 | **README covers the live builder.** Review C8. A section with `Builder` — `feed` returning the version, `graph()`, `delta(since)`/`fold`, `retain`, the three consumption modes and the prefix-consistency promise in one sentence each — and `read_records` with the no-carry sentence from §7, plus the delta document; one worked example that runs. A doc-truth check that every name in `spanweave.__all__` appears in README, red on the parent for the eight new names. Docs and tests only. | todo | 8 |
| L28 | **The live-graphs series closes in this repo.** Review A2/A3. One commit, no `plan:` commit after it: `TASKS.md` gains the series registry — one line per batch L0–L28 with status and sha, L16 noting its bound was cleared by L15, L17 noting its criterion unmet and wrong, L5 dropped on measurement, L7/L8 moved to `SigorMatt/spanweave-live` — and §3 of WORKPLAN.md folded in full; `SPEC.md:744`, `:2447`, `:2515` and `tests/test_doc_truth.py:3059`, `:3113`, `:3115` re-pointed to TASKS.md; `WORKPLAN.md` deleted; `README.md:325` row and the `tests/test_doc_truth.py:409` exclusion removed; `reviews/2026-10-02-live-run4.md` byte-for-byte with sha256, every finding dispositioned (A1 L26, A2/A3 here, A4 L23, C1 L24, C3–C5 L26, C8 L27, C6/C7 by this registry, C9/C10 history, threads registered verbatim, the `CallRole` thread closed by L25); the three protocol changes recorded under TASKS.md's lessons section for the next series. CHANGELOG entry. `make check` + `make install-check`; `git ls-files WORKPLAN.md` empty. | todo | 10 |

---

## 2. Execution order

L0 → L1, L2 (already written) → decisions → L3 → L4 → L5 → L6 → L7 → L8 →
close. Run 1 = L0 then stop at the decision point; it ran and stopped there.

Run 2 = L3 → L4 → L5 → L6, in the spanweave repo, then stop.

Run 3 = L9 → L10 → L11 → L12 → L13 → L14, spanweave repo, then stop: cold
review of L9–L14 (aux), decisions, then run 4. Run 4 = L20 → L21 → L22 → L15
→ L16 → L17 → L18 → L19, spanweave repo, then stop: cold review of the range
(aux), decisions. L20 precedes the cost batches because the rollback it
introduces is the path their per-edge ledger traffic must take. Run 5 = L23 →
L24 → L25 → L26 → L27 → L28 in this repo; L28 is the last commit and deletes
this file. Then a scoped cold review of L23–L25 and L28 (aux), decisions, and
the PR to `main`. The receiver is its own series in `SigorMatt/spanweave-live`
once the repo exists. Every batch: CI green on the pushed tip before `done`.

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
| 2026-10-01 | review run 3 | Finding 1 (§10.5's atomicity promise is false two ways: `_translate` commits `_claimed`/`_sample`/`_unread` before the absorb loop, and the span loop is not atomic, leaving a *silently* corrupt builder) is one batch, L20, and it runs **before** L15/L17 so the rollback is derived once, before `Tally.set_edges` becomes per-edge ledger traffic. Finding 2 (a carry buffer in the array or document container is uncaught) and finding 7 (L13's two refusals indistinguishable) are one tests-only batch, L21. Findings 3 and 4 (`SPEC.md:2390` false; `SPEC.md:709` census stale) are one docs batch, L22, with a doc-truth check so the census cannot go stale again. Finding 5 is a correction recorded in L19, not a batch: the review showed mid-stream windows are full-prefix deltas of a shorter builder by construction, so gate 3 gains nothing from them. Finding 6 is corrected in this commit. The ten threads go to L19. | maintainer |
| 2026-10-01 | L14 | The 62 windows stay. They are redundant against every mutation tried because `until` is hard-wired to the current version (`api.py:226`); their value is the 19/62 windows that report a still-open fact, and the lever for selectivity is a longer fixture, not more windows. No further window batches. | maintainer |
| 2026-10-01 | L12 | The array branch's whole-input scope for `undecodable_bytes` is accepted as a thread, not a fix: a receiver that tails exporters feeds lines or documents, and a legitimately written U+FFFD is indistinguishable from a replaced one only on that branch. Revisit if L7 reads arrays. | maintainer |
| 2026-10-01 | §0.2 | The parent of a code commit is `<sha>^`, derived, never a sha named in a brief: `plan:` commits interleave, and the run-3 brief named a child as a parent. Written into §0.2 in this commit. | maintainer |
| 2026-10-01 | run 4 | L20 → L21 → L22 → L15 → L16 → L17 → L18 → L19, then stop for a cold review. Run 5 = L7 → L8 in the receiver repo once it exists. | maintainer |
| 2026-10-02 | review run 4 | A1 accepted in full: 7.1× is the rise in declared work and bounds the ms/record ratio from **above**, with equality only at zero fixed cost; the "floor" word and the sentence built on it are false and leave every place they were copied to (L26). A2/A3 accepted: the series closes in this repo with the §0.6 convention (L28). A4 taken as the brain's call, agreeing with the aux grading over the sub-agent's: a §10.5 sentence added in this series is falsified through public `register`, and the fix is one snapshot (L23). C1 is a pin that must exist before merge (L24). The `CallRole` identity comparison is a live-vs-batch divergence through public API and is fixed, not threaded (L25). C8 is accepted: the series' product must be visible in README before it merges (L27). C3, C4, C5, the 24.6 denominator and the two harness threads go into L26. C6/C7 are satisfied by the registry L28 writes, which carries L16 and L17 truthfully. C9/C10 are history. The remaining threads are registered in L28. | maintainer |
| 2026-10-02 | L17 | The 1.5× per-record criterion was wrong as written and the correction offered for it was wrong too: the honest statement is that the per-record rise is bounded above by the rise in declarations and that the gap is fixed per-record cost; 1.5× was unreachable for this implementation at ~11 µs per edge, an empirical claim about constants. The registry row says the criterion was unmet and why. | maintainer |
| 2026-10-02 | protocol | Three §0 changes, carried to the next series' WORKPLAN rather than edited here: (1) §0.2 asks for a mutation that the new test catches, not only the parent run, because a tests-only batch's derived parent is a `plan:` commit and the parent run is vacuous; (2) §0.1 step 5 lets the builder correct a row's acceptance number with the reason in the same plan commit, so a wrong criterion has an owner; (3) aux worktrees are created by absolute path under the scratchpad, never by a relative path. | maintainer |
| 2026-10-02 | run 5 | L23 → L24 → L25 → L26 → L27 → L28 in this repo, then a scoped cold review of L23–L25 and L28 (aux), then PR to `main`. L28 deletes WORKPLAN.md, so it has no `plan:` commit after it and the run ends on its code commit. The receiver (L7, L8) starts its own series in `SigorMatt/spanweave-live` with its own WORKPLAN §0 once the repo exists; both rows are registered in TASKS.md as moved there. | maintainer |

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
- 2026-10-01: L10 done (`b40dac9`), CI green, and the row's "SPEC §10.5
  unchanged (it already promises this)" was **wrong**, so SPEC moved after
  all. The promise — not absorbed, `version` does not move, no half-arrival —
  sat *inside* §10.5's two-adapter bullet rather than over the list, so the
  node-id collision the batch was fixing was the one refusal §10.5 did not
  actually cover; it is now stated once for every refusal §10.5 lists. The
  fix reads the three whole-input counts and derives the arriving id *before*
  any write, so `_absorb_at` takes the id as a parameter; no arrival pays more
  than before. Four tests, each proven red in a worktree on `55f0467` with a
  real crash rather than a wrong answer (`KeyError` at `incremental.py:507`
  twice, `IndexError` at `:370` twice) — the two-adapter `graph()` extension
  was already green there, as the row expected. **For L19's thread list**: a
  record that becomes more than one span is still a partial arrival, because
  `api.py:feed` loops `absorb` per span and each `absorb` is now atomic while
  the loop is not. No shipped adapter emits more than one span per record, so
  it is unreachable rather than fixed.
- 2026-10-01: L11 done (`4807ae6`), CI green, tests only and SPEC unmoved —
  §7 already states both properties, and the sharper "neither buffers nor
  rejoins across calls" sentence was left to L12 rather than pre-empted. The
  four run-alone results are in the commit body; the one that matters most is
  the negative control: under the review's `_CARRY` mutation **all 166
  pre-existing `test_read.py` + `test_live.py` tests passed**, which is B2's
  claim demonstrated rather than accepted. Each new test now fails alone under
  its mutation on a real assertion, and (b) was proven against *both* shapes
  of the dedup mutation — the narrow one that still yields the record but adds
  a spurious `duplicate_record`, and the wide one that drops it. Independence
  was checked by running the file in reverse collection order and under three
  shuffled orders (112 passed each); `tests/test_read.py` has no fixtures and
  no mutable module state, and neither does `spanweave/read.py`.
- 2026-10-01: L12 done (`be16fa8`), CI green. The row's three cases became
  five tests, and the two extra ones are where the batch was larger than the
  row: the buffered-document branch decodes in *two* places, and its fallback
  re-decodes per line, so reporting on both would have double-counted — the
  document branch reports only where it keeps the document, and a test pins
  that. The row's line numbers (`read.py:243,278,312`) still named the three
  core sites; the only other `errors=` in the tree is `cli.py`'s
  `backslashreplace` on stdout, an *encode* of output rather than a decode of
  trace input, and it is excluded on purpose. **Two censuses existed and both
  had to move**: `diagnostics.CODES` against SPEC §3.7 (`tests/test_codes.py`)
  and `CONTRACTS.md`'s `diagnostics[].source` row count (nine → ten). The new
  code's `source` is `null` and is stated as its own §3.7 row rather than left
  to the catch-all, which is the F-E defect not repeated.
  `tests/serialized_shape.json` moved for the first time this series (+2
  lines: the code in `vocabularies.diagnostic_codes`, its `null` in
  `diagnostic_source`), regenerated by `make shape`, nothing else in the shape
  touched. Corpus verified unmoved by decoding all 329 tracked files strictly:
  zero invalid, so no expected graph gained a diagnostic. **For the receiver
  (L7)**: `skipped_records` is deliberately *not* moved by this code, so a
  receiver counting losses must read the code, not the count.
- 2026-10-01: L13 done (`6b2e866`), CI green, and the row's two tests became
  six because accepting a buffer means deciding what a buffer is. Accepted:
  `bytes` (passed through, no copy), and `bytearray` / `memoryview` with
  `itemsize == 1` and `c_contiguous`, copied once via `bytes(data)` — the copy
  is the library's, and a multi-dimensional view of bytes is read as the run
  under it. Refused with a `TypeError` that names which: items wider than a
  byte, because byte order would decide the answer and that breaks
  determinism; and strided views, because they name no run of bytes. The red
  proof is worth keeping for the cold review: the four accepting tests failed
  on the parent with the right `TypeError`, but the **two refusing tests
  failed on the message** — the parent refuses them for the `str` reason, the
  right outcome reached by the wrong route, which a test asserting only
  "raises `TypeError`" would have called green. Post-call mutation cannot
  change a returned `Records` (tested by writing through the view and by
  appending to the buffer afterwards), which is L6's eagerness holding for a
  mutable input. No fourth decode path: everything still reaches
  `read_trace` → `_decoded`, so L12's three sites stay in agreement.
- 2026-10-01: L14 done (`b10c60a`), CI green, tests only and SPEC unmoved. Gate
  2 goes **195 → 257 assertions** (+62 mid-stream windows over the 53
  renderings; the parametrized case count stays 53), and
  `tests/serialized_shape.json` gains four `delta_*` sections. The `Graph` half
  was verified byte-identical the right way — each pre-existing section of the
  old and regenerated artifact re-serialized and sha256-compared, all six
  identical — so the only line that moved outside the new sections is the
  human note at the head. **The honest result the review must weigh**: the new
  windows do **not** isolate a bug the old family misses. Cancellation off
  fails 30 of 62 new and 27 of 195 old; dropping the `since`-endpoint order
  recompute fails 2 old and **0 new**; and no mutation was found that fails a
  new window while sparing the old family, because a builder's delta always
  ends at its current version, so a mid-stream window is the same code earlier
  in the stream. What the +62 do buy is coverage of state the full-prefix
  family cannot reach: all 62 answers differ from every full-prefix answer of
  their rendering, and 19 of 62 report a fact still open at `until` that
  version n has resolved. The docstring says they are structurally equivalent
  to running gate 2 on every prefix rather than claiming a new mechanism.
  **The corpus is the binding limit**: the longest rendering is 5 records, so
  23 of 53 renderings (n ≤ 2) get no mid-stream window at all, 17 get one, and
  `(1, n//2)` exists on **0** renderings while `(n−3, n−1)` exists on **30**
  (corrected 2026-10-01 by the run-3 review; the record said 13 for both, and
  the commit body's "always" for `(1, n//2)` was wrong — it needs n ≥ 6 and the
  corpus tops out at 5). Windows were dropped where they
  collapse, never clamped. `MID_STREAM_CEILING = 64` bounds the exhaustive set
  if a long captured trace is ever added; nothing in the corpus reaches it
  today, which makes a real-length captured fixture the first input that would.
- 2026-10-01: **run 3 ends here.** L9, L10, L11, L12, L13, L14 all done, each
  with CI green on its own pushed tip; nothing blocked, nothing left
  `awaiting decision`, and no batch reached `OPEN_QUESTIONS.md`. Two things
  moved that a tests-only reading of the run would not predict: `SPEC.md`
  (L10's §10.5 atomicity promise, wrongly assumed already stated; L12's §3.7
  and §7; L13's §7) and `tests/serialized_shape.json`, twice — L12 (+2 lines,
  the new diagnostic code) and L14 (four `delta_*` sections) — after three
  runs in which it never moved. Next, per §2: a cold review of L9–L14 by aux
  (`Review WORKPLAN.md commits since ce9ff17`), then decisions, then run 4
  (L15 → L16 → L17 → L18 → L19, the three superlinear `feed` sites and the
  §10.6 rewrite). Three things for that review to weigh: L14's finding that
  the mid-stream windows cannot isolate a bug the old family misses and the
  corpus length that causes it; L10's thread that `api.py:feed` loops `absorb`
  per span so the loop is not atomic even though each absorb now is; and
  whether L12's choice of *where* the buffered-document branch reports
  `undecodable_bytes` is the one a receiver would want.
- 2026-10-01: run-3 cold review read and decided (§3). Nothing blocks, but
  §10.5's atomicity promise was shown false two ways with the shipped
  adapters, and the fix (L20) is sequenced ahead of the cost batches so the
  rollback is written once. The review's own brief named a child as a parent;
  §0.2 now derives the parent. Run 4 is eight batches in this repo; the
  receiver repo is still not created.
- 2026-10-01: L20 done (`f04cbc8`). `_translate` now stages and writes
  nothing; `_commit` writes `_claimed`/`_sample`/`_unread` only after every
  span of the record has landed, and `feed` rolls the absorber back to the
  record's starting span count on any refusal. The rollback is one mechanism
  in two halves — `Ledger.rollback` and a new `Contributions.rollback`, both
  undoing from the snapshot `begin` already opens — which is what L15's and
  L17's per-edge ledger traffic will be reversed by, so it is written once as
  the decision intended. Red on the derived parent `71d282f`: 4 failed, 57
  passed, the control test green. `tests/serialized_shape.json` did not move.
  Note for the review: §5's findings table stops at L2, so batches from L9 on
  cite the §3 decisions log for their origin instead.
- 2026-10-01: L21 done (`6d39fe0`), tests only — nothing under `spanweave/`
  moved and `SPEC.md` did not need to: §7's "neither buffers nor rejoins
  across calls" is already unqualified by container, so the gap was in the
  tests, not the promise. The carry mutation fails each new test **alone**
  (array and export-document, both on the diagnostic-code list, not on a
  message), while the parent's whole suite stays green under *each* container
  mutation — which is the negative control that reproduces finding 2. Finding
  7 closed tests-only: the refusal message already interpolates the shape
  (`itemsize`/`c_contiguous`), so the two refusals were distinguishable
  without a code change. `tests/test_read.py` is order-independent forward,
  reversed, and under three seeds.
- 2026-10-01: L22 done (`369e826`), docs plus a gate, no behaviour change.
  The census was stale in **two** places, not the one finding 4 named: the
  `null` count aged at L12, and the object count was already off by one at the
  parent (`timestamp_unit_suspect`). Measured: three carry an object, four
  carry nothing, one carries something the library computed. §10.9 now names
  what `tests/serialized_shape.json` carries and the only two commits that
  moved it (`be16fa8` at L12, `b10c60a` at L14 — L20 and L21 left it alone,
  confirmed by `git log` on the file). The gate lives in `tests/test_codes.py`
  beside the existing `CONTRACTS.md` count guard and was proven red three
  ways, including the next-addition case: plant a fifth `null` row with the
  prose untouched and `make check` fails.
- 2026-10-01: L15 done (`cda7f74`), the first of the three cost sites.
  `_restate_chain` is gone, replaced by `_rank`/`_join`/`_leave` over members
  held in sorted order, with `Tally.amend_edges` carrying per-edge traffic
  instead of `set_edges` of the whole key. Acceptance met by `make bench`
  (`--only wide`, feed only, CPython 3.14.6, one machine): **0.1093 ms/rec at
  k=1000 → 0.1119 at k=8000 = 1.02×**, against the ≤1.5× the row asked for;
  the same machine on the parent gives 1.875 → 20.918 = 11.15×, which
  reproduces the review's 11.27×. `Edge.__init__` under `cProfile` is
  1999/3999/7999/15999 at k=1000/2000/4000/8000 — linear, against 1,999,000 at
  k=2000 before. Red on the derived parent `1250d35`: 2 failed, 64 passed, the
  three correctness controls green. The sequencing decision paid: the per-edge
  ledger traffic is reversed by L20's `Ledger.rollback`, pinned by a
  half-refused-record test. Two things for later batches: `cProfile`'s
  `pstats` merges every frozen-dataclass `__init__` under `<string>:2`, so an
  `Edge` count must be read from `Profile.getstats()` raw entries (L18's
  harness); and §10.6 moved here **only** for the one sentence L15 falsified —
  L18 still owns the wholesale rewrite.
- 2026-10-01: L16 done (`e708ed5`), and it corrected the row's own premise.
  Measured on one machine across three commits, wide n=2000, root-first /
  root-last / ratio: pre-L15 `1250d35` 7572.0 / 18810.7 ms = **2.48×**; parent
  `9f5b8c3` 218.8 / 264.5 = **1.21×**; here 217.9 / 230.6 = **1.05×**. So the
  row's ≤2× acceptance *failed* at the commit it was written against, L15
  brought it inside the bound, and L16 took it to 1.05× — met, not loosened.
  What L16 adds is the half L15 did not: the move made **once**.
  `_regroup_many` re-keys a group whose whole membership moves to an empty
  destination, and because a `temporal` edge names its endpoints rather than
  its group, **no edge moves at all** — the arrival is linear in the children
  (7.4 µs/child at n=1000, 8.7 at n=16000, against 18.3/28.4 at the parent).
  Partial moves fall back to L15's per-record `_leave`/`_join`. Red on the
  derived parent `9f5b8c3`: 1 failed, 68 passed. §10.6 gained an *addition*
  here, nothing was falsified, so L18's wholesale rewrite is still untouched;
  `make bench ARGS="--only wide --root-last --wide N"` is new and is how L18
  re-takes this number.
- 2026-10-02: L17 done (`7ddd630`), the cubic site, and the last of the three.
  Receipts are held in §4.2.1's ranking; `_received`/`_fulfilled` amend per
  edge through L15's `Tally.amend_edges`; `_restate_calls` no longer touches
  `data`. Red on the derived parent `f385d36`: 2 failed, 71 passed — 1330 data
  edges built for 190 held at 20 turns, which is C(21,3), the cube itself.
  Measured (`--only echo --turns 400 --segments 4`, CPython 3.14.6, one
  machine, here vs parent): feed 958 ms vs 75,171; `Edge.__init__` **81,799 vs
  10,748,399**, exactly 1.000 data edge per declared receipt at 50/100/200/400
  turns against 17.0/33.7/67.0/133.7. **The row's second criterion is met
  exactly; its first cannot be met by any correct implementation.** §4.2.1
  promises that n turns declare n(n−1)/2 receipts and that none is suppressed,
  so turns 301–400 carry 174.8 declarations/record against 24.6 — a **7.1×
  floor** on ms/record for anything that builds each declaration once. The
  measured 5.44× is *below* that floor, i.e. the per-record work is already
  sublinear in declarations; reaching the row's 1.5× would require not
  emitting declared relations, which §4.2.1 forbids. The batch did not loosen
  the acceptance or edit this file — correctly. **L18 owns the correction**:
  the 1.5× figure is replaced by the declaration-floor statement when §10.6's
  cost prose is rewritten, which is the same batch that was already told to
  take bare ratios out of SPEC. `--segments N` is new (turn-aligned on echo),
  and with all three sites fixed the whole `tests/live_cost.py` header table is
  now history and ready to be re-taken.
- 2026-10-02: L18 done (`60a831b`), docs plus harness, nothing under
  `spanweave/`. All seven row items satisfied: the materialize sort, the
  rewind and **each** `ordering()` of one `delta()` are timed in place; `--smoke`
  is a new `bench-smoke` prerequisite of `check` (~0.15 s, `make check` 27.5 s
  against 27.1 s before); §10.2/§10.6 are promises plus a dated,
  harness-cited numbers block with no bare ratios; heap-Kahn is gone from SPEC
  including its surviving "not a faster sort" form, with the rejected subtree
  recompute named beside the open "no sort" question; CHANGELOG's heap line is
  reworded; this file was not touched; both shapes re-taken. `--smoke` asserts
  **shape, never the clock** — receipt count, one `Edge` per edge held, sort
  counts 0/1/2, identical bytes across arrival order — the rule `bench` and
  `stranger` both already state. It bites per site when replayed on the three
  earlier tips (`1250d35` echo 90/34, `9f5b8c3` echo 54/34, `f385d36` echo
  54/34, each exit 1 at eleven records). Fresh numbers at `0718ba8`, CPython
  3.14.6, one machine — echo 400 turns: feed 1.2009 ms/rec, 0 sorts, 81,799
  `Edge` = 1.000 per edge held, `delta` 245.8 ms of which the sort is 15.1%;
  wide 20,000: feed 0.1198 ms/rec, 39,999 `Edge` = 1.000, `delta` 293.2 ms of
  which the sort is 59.3%; root-last at 2,000 is 1.07×. **L17's unmeetable
  ratio is now the declaration floor in §10.6**: 24.6 receipts/record for
  turns 1–100 against 174.8 for 301–400 makes 7.1× the floor for any
  implementation that builds each declaration once, the measured 5.43× is
  below it, and a target beneath the floor could only be met by suppressing
  declared relations, which §4.2.1 forbids. Red on the derived parent
  `0718ba8`: 4 failed, 4 passed. The harness also gained `--count-edges`,
  reading `Edge.__init__` from `Profile.getstats()` raw entries per L15's note,
  so an acceptance count can be re-taken from `make bench` without a one-off
  script.
- 2026-10-02: L19 done (`a97a525`), and run 4 is closed. Both reviews are in
  the tree byte-for-byte — `reviews/2026-09-30-live-run2.md`
  (`3800a79d…23ce38`) and `reviews/2026-10-01-live-run3.md` (`0aa047c4…7dd8f2`),
  `cmp` clean against the untracked scratch copies in `patches/`. Run 2: 17 of
  21 lettered findings closed or corrected, 4 threads registered verbatim. Run
  3: findings 1/2/3/4/7 closed by L20–L22, 6 corrected in `71d282f`, 5 recorded
  as a correction to `b10c60a`'s body, 10 threads registered verbatim, 8 open.
  Three places where the row's disposition did not match what happened, all
  recorded in the commit body rather than smoothed over: N5 was a plan
  correction and not a batch, and T1–T5/T9/T14 are closed though the row's list
  omits them; L21 closed findings 2 and 7 without touching `spanweave/`,
  because only the distinct-assertions route existed; and finding 4's census
  was stale in two places, not one. The cost number is recorded as
  **corrected, not met**. No census moved (`tests/corpus_census.py` still 56
  files / 159 records; `install-check` still 33 checks / 4 plants); the only
  counted surface the two new files reach is the sdist, which already ships
  `reviews/`. One thing for the cold review: this file's "329 tracked files" is
  now 331, left as the dated historical measurement it is.
- 2026-10-02: **run 4 closed.** Eight batches, eight code/doc commits and eight
  `plan:` commits, every one with CI green on its own pushed tip — no batch
  needed a second dispatch and none ended `blocked` or `awaiting decision`.
  The one judgement the run had to make is the one worth the review's
  attention: L17's first acceptance criterion was not merely unmet but
  arithmetically unmeetable against §4.2.1, so it was corrected in L18 rather
  than loosened, and the status cell says so. Next per §2: a cold review of the
  range `71d282f..` by aux, then decisions, then run 5 (L7 → L8) in the
  receiver repo, which still does not exist.
- 2026-10-02: run-4 cold review read and decided (§3). The code of run 4 is
  sound and every acceptance number re-took independently; what blocks the
  merge is prose and the series close. The "declaration floor" was a ceiling
  and is rewritten; the one rollback hole is closed; the series' product gets
  a README section; the registry is written and this file goes. Run 5 ends
  the spanweave half.

---

## 5. Findings reference

| Origin | Batch |
|---|---|
| Audit thread 80 (`TASKS.md`, *September 2026 audit*): eleven tests hard-code `100_000` as "too deep", the follow-on `546bdfa` left | L0 |
| Memo: prefix-consistent incremental build (`OPEN_QUESTIONS.md` §18) | L1, and L3–L5 once it is decided |
| Memo: the receiver boundary (`OPEN_QUESTIONS.md` §19) | L2, and L6–L8 once it is decided |
