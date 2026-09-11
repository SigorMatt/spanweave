# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-11 (R3 decided; run 4 pending).
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
| R4 | **B3's sentence matches B3's behaviour.** SPEC says a key read to decide is consumed; the adapter consumes `role` even when it could not use it, and `role` has no mapped field. Decide the smaller change inside the SPEC's own principle (losslessness + "nothing reported as unmapped that was read"): either consume only when the key decided something, or state that a read key is consumed regardless and why. Tests either way; corpus expectations must not move (verify). | done (`cb53ef9`) | 10 |
| R6 | **A6's narrative matches the measurement.** The commit body says the encoder's limit is lower than the parser's; measured on CPython it is ~1.9× higher, so the story is not reachable from a trace file. Correct CHANGELOG and SPEC §7 wording to what was measured; keep the containment (it is still correct to have). Record the measurement. Docs only. | done (`e243aeb`) | 6 |
| R5 | **Corpus counts recompute from a checkout.** Five commits (name them from `git log --grep` on "57 files\|177 records\|43+14\|117+60") cite counts that include the gitignored `capture/_scratch/`. Make F2's widened census the single source: a script or test under `tests/` that counts tracked files/records only and prints the figures; replace every cited figure in CHANGELOG, TASKS.md, OPEN_QUESTIONS.md and ROADMAP.md with the recomputed one and a "(tracked files only)" qualifier. G5 already did this for its own figures — match its wording. | done (`8d67589`) | 12 |
| R3 | **Stated timestamp units (HALT memo).** An OTLP JSON envelope declares its unit in the field name (`startTimeUnixNano`); F2 reads it and the adapters then warn `timestamp_unit_suspect` on every span, while a genuinely seconds-encoded span in the same file is the only one *not* warned (signal inversion, measured). Options: (a) `NormalizedSpan.timestamp_unit: "s" \| "ns" \| None` — the container states `ns`, the flat record states nothing; the diagnostic fires only when no unit is stated and the value exceeds the ceiling; `started_at` still holds the reported value (C2 decision stands), and the graph carries the unit where stated (model field: schema moves); (b) the reader rescales OTLP ns to seconds before the seam (violates C2's "never rescale"); (c) leave as is and document the warning as expected on OTLP input. Memo to OPEN_QUESTIONS.md with recommendation; `awaiting decision`. | done (`5697313`, OPEN_QUESTIONS §17) | 6 |
| R11 | **R3 decision (c) landed.** SPEC §3.7 `timestamp_unit_suspect` row and §7 OTLP container section state the expected per-span warning on a conformant nanosecond export and why it is not rescaled; ADAPTERS.md one sentence; R1's two pin tests gain the comment that the behaviour is documented, not merely current; OPEN_QUESTIONS §17 decision line filled verbatim from §3. Docs and test comments only. | done (`aef2404`) | 6 |
| R8 | **The rest of the adapter follows R4's rule.** Found by R4, out of its scope: `_operation` blanket-consumes `llm.model_name` / `embedding.model_name` / `tool.name` and `_call` blanket-consumes `tool_call.id`, so a value the adapter cannot read at any of those keys is consumed and never reported -- the same contradiction with SPEC §3.7 that R4 fixed for `role`. Apply R4's decision (consume only when the key decided something) uniformly; verify corpus expectations do not move. SPEC §3.7. CHANGELOG. | done (`97ce154`) | 10 |
| R9 | **The rest of the cited figures recompute too.** Found by R5, outside its row's grep (which named only the 57/177 family): four more non-recomputable figures are cited in durable documents -- C3's "154 timestamp values", D2's "15 captured files / 24 data edges", and F1/F2's "64 of 64" and "46 `malformed_record`". Extend `tests/corpus_census.py` to compute each from `git ls-files`, replace the cited figures, and let R5's `no_durable_document_states_the_working_tree_census_as_a_fact` test cover them. **Widened by the run-3 cold review (R5 finding 1):** planting wrong values in six of R5's own figures left all 39 doc-truth tests green, so R9 must *pin* every recomputable figure to the census, not only add four more unpinned ones -- a sibling test that scans every durable document for an asserted figure and requires it to equal the census. | done (`67d788d`, widening `0dbcc71`) | 10 |
| R10 | **An empty `parentSpanId` is no parent, as F1 says it is.** Found by R3, out of scope: an OTLP root span carries `parentSpanId: ""` and the builder emits `orphan_parent` ("parent span '' is not in this input") on every root -- contradicting F1's claim in OPEN_QUESTIONS §16(e) that `""` is treated as no parent. Decide where the empty string is normalised away (reader or seam), fix, and cover with an OTLP fixture whose roots draw no diagnostic. Corpus diagnostic expectations will move; state the before/after. SPEC §3.1. CHANGELOG. | done (`7480ac3`) | 10 |
| R12 | **The same rule, at the keys R8's row did not name.** Found by R8, out of its scope: `_payload` consumes `input.mime_type` / `output.mime_type` before reading and `_kind_of` consumes `openinference.span.kind` before reading (whose `unknown_span_kind` message says "no attribute" even when the key is present and unreadable); `adapters/otel_genai.py` blanket-consumes `gen_ai.tool.name`, `gen_ai.request.model` and `gen_ai.tool.call.id` the same way. The last one is not cosmetic: the two dialects report an unreadable name/id differently, which is a cross-dialect equivalence claim. Apply R4's rule uniformly; verify corpus expectations do not move. SPEC §3.7. CHANGELOG. **Also (found by R10):** record-level keys are consumed via a static `KNOWN_RECORD_KEYS`, so an *unreadable* `parent_id`/`name` (e.g. `42`) is swallowed with no `unmapped_attributes` entry -- the same class one level up from the attribute keys. | done (`f03de6b`, `2935d11`) | 12 |
| R13 | **R6's correction is false on CPython 3.14.** Review F1 (blocker for series close): `uv run` selects 3.14 in this repo, CI tests 3.11-3.13 only, and on 3.14 the encoder gives out ~2,865 levels *before* the parser for nested dicts (37241 vs 40106) -- A6's retracted claim. SPEC §7 and CHANGELOG: demote "the encoder's limit **is** the parser's" and "no trace file reaches the refusal at all" to interpreter-named observations carrying the measured table; keep the four-level positional claim, which is R6's real and durable contribution. The pin test builds dicts, not lists, and records the observed ratio rather than asserting a direction the library does not control. Add 3.14 to the CI matrix. | done (`1e121d2`) | 15 |
| R14 | **The digit limit is an environment fact.** Review F2: `PYTHONINTMAXSTRDIGITS=0` changes the graph bytes for R1's inputs, which is invariant 4. Document the dependency in SPEC §3.1 and `ENVIRONMENT.md`; derive R1's boundary tests from `sys.get_int_max_str_digits()` so they hold on any legal configuration; state in §7 that the graph depends on this interpreter setting and how to pin it. | done (`3f9a15a`) | 10 |
| R15 | **The sdist ships `reviews/`.** Review F3: `/reviews` is missing from the sdist include allowlist, so a stranger unpacking the sdist gets TASKS.md's citation without the review -- R2's defect with `patches/` swapped out. Add it, and make `audit_sdist` assert tracked-documents ⊆ sdist for every file TASKS.md cites. | done (`72c40a9`) | 4 |
| R16 | **Error codes are routable from the CLI, and `validate` refuses what `build` refuses.** Review F4: `cli.py` prints the `code` alongside the message for every `SpanweaveError`; exit codes are documented in README and SPEC §7, not only in a source comment; `spanweave validate` parses with `parse_constant` so a document carrying bare `NaN`/`Infinity` is reported invalid, matching `build`; `errors.py:107-119` wording updated for the `ValueError` arm; `serialize.py:77` distinguishes a circular reference from a non-finite number. | done (`e3d7743`) | 12 |
| R17 | **R3 record corrections.** Review §7: disclose in OPEN_QUESTIONS §17 that the headline measurement's envelope omitted `parentSpanId` (with it, **as measured then**: 201 `orphan_parent` + 200 `timestamp_unit_suspect`). R10 has since moved this: on the current tree the same export gives 200 `timestamp_unit_suspect` and **0** `orphan_parent`, so the disclosure is written as history of the pre-R10 measurement, not as current fact. §16(e)'s cell is now true in outcome but still wrong in mechanism -- it is `parent_ref` at the seam, not `_as_str`, and not the builder -- so it still needs correcting; note that the schema is currently unfrozen where the memo prices (a2); fix the known-false claim at `OPEN_QUESTIONS.md:2692`. Docs only. | done (`5a7b743`) | 6 |
| R18 | **The record-level fields whose reading is a judgement.** Found by R12, out of its scope. A non-dict `attributes` becoming `{}` and an unrecognised status *string* becoming `UNSET` without a diagnostic is likely an **invariant-2 violation** ("nothing dropped silently"), even though the record survives verbatim in `raw.source`. The fix needs a spec decision on which of these coercions get a diagnostic and which get a refusal -- so this is **not** decided in-batch and **not** a memo now: R7 records it as an open thread, and it is the **first memo of the next series**. Evidence to start from, four fields, both adapters (`openinference.py` / `otel_genai.py`): unrecognised status string -> `UNSET` at `:559` / `:746`; `status_message` read by `_as_str` at `:552` / `:739`; non-dict `attributes` -> `{}` at `:202` and `:578` / `:293` and `:765`; `_links` skips a link that is not a dict or carries no span id, at `:562-581` / `:749-768`. | open thread at R7 | 12 |
| R19 | **A bare `RecursionError` escapes `spanweave.build` on CPython 3.14.** Found by R13, out of its scope and the same class as R1's blocker: `read.py:306` (`record_digest`) digests every record with an uncontained `json.dumps`, so on an interpreter whose encoder is shallower than its parser the reader meets the encoder first -- depth 37,240 builds and writes, 37,260 raises a bare `RecursionError`, and only above ~40,100 does it become the `malformed_record` SPEC §7 promises. No test covers it, so CI stays green; §7 now states it as a defect against its own rule. The fix is a behaviour change SPEC specifies no target for, so it needs a decision inside the batch. **In run 4, before R7** (no preference expressed; the builder's call): an escaping traceback on a supported interpreter is the defect class run 3 was reopened for, and closing the series with it live would file it in `DEBT.md` instead of fixing it. | done (`e8746a1`) | 12 |
| R7 | **Series close, again.** As G4: final statuses to TASKS.md, §3 decisions moved, WORKPLAN.md and its README row removed, `make check`. Runs only after R3 is decided and implemented (run 4), or immediately if the decision is (c). **Additionally (run-3 review):** resolve the TASKS.md `R<n>` name collisions by prefixing this series' batch ids `audit-R…` in TASKS.md (F5); record R1's harsh-degradation note (one `NaN` refuses a whole graph, and the library already carries a non-JSON literal as *text* elsewhere) and the remaining review nits under open threads. Per review F6, any row still `todo` at the close moves to `DEBT.md` rather than being deleted with this file. **Also:** the run-3 review still lives only in untracked `patches/` -- R2's own defect shape -- so archive it as `reviews/2026-09-11-run3.md` (R15's sdist check then ships it, and durable documents may cite it by path). | blocked by R11-R17, R19 | 10 |

---

## 2. Execution order

Run 3 = R1 → R2 → R4 → R6 → R5 → R3 (halts).

Run 4 = R11 → R8 → R9 → R10 → R12 → R13 → R14 → R15 → R16 → R17 → R19 → R7
(series close). R7 is blocked until R11-R17 land: the run-3 cold review
makes F1 a blocker for the close.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-09-11 | R3 | Option (c): document that a conformant OTLP JSON export draws one `timestamp_unit_suspect` per span, and that the warning is a statement about the model's field contract, not about the telemetry. No unit is stated at the seam or in the graph; nothing is rescaled; `otlp_container` keeps its byte-identity with `llm_tool_llm`. Hold (a1)+(a′) as the memo describes until a second consumer of the unit exists or a real mixed-unit export is observed. When either arrives, evaluate first — as a new memo — a within-file consistency rule: one diagnostic per graph when every timestamp value is on the same side of the ceiling, per-span only for the minority side when they are not; it removes the volume and restores the signal without a stated unit or an invented key. Implemented by R11. | maintainer |

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
- 2026-09-11: R4 decided inside the batch -- a `role` the adapter cannot read
  decided nothing, so it stays in `unmapped_attributes`; a readable non-`tool`
  role is still consumed, leaving B3's quadratic-diagnostics fix intact. The
  corpus constraint was verified rather than assumed (23 files carry role
  keys, 0 non-string values). R4 found the same contradiction at four more
  keys and it is registered as R8 for run 4.
- 2026-09-11: R6 re-measured and found *both* stories wrong. On this
  interpreter (CPython 3.12.3) `json.loads` and `json.dumps` give out at the
  same depth, 9997 -- so neither A6's "encoder's limit is lower" nor the
  review's "~1.9x higher" holds; the review's 40112/74493 is a different
  interpreter, not a different fact. What is real is A6's *position* claim:
  the encoder meets a value four containers deeper than the reader did, so
  the reachable band is ~2 levels out of 10 000. Reachable, but not routine.
  SPEC now says the numbers are interpreter-specific; two pin tests re-measure.
- 2026-09-11: R5's recompute moved two substantive claims, not only
  arithmetic: a corpus file now carries both dialects' markers (constructed,
  in `mixed_instrumentation`, not observed), and "every record carries a span
  id" ended when A5 added `derived_ids` (139 of 151). The load-bearing **0
  records carrying both markers** is unchanged, so G3's decision still
  stands. Tracked census: 52 files, 151 records; the old 57/177 was a working
  tree whose tracked part was then 43/117. Four further non-recomputable
  figures were outside R5's row and are registered as R9.
- 2026-09-11: R3 halts the run, `awaiting decision` (OPEN_QUESTIONS §17). It
  corrected two things the row had wrong: `timestamp_unit_suspect` is the
  *builder's* diagnostic, not the adapters', and option (a) as the row stated
  it silences both sides of the inversion instead of fixing it -- so the memo
  splits (a) into (a1)/(a2)/(a'). Recommendation is (c) now, holding
  (a1)+(a') until a second consumer needs the unit. R3 also found the
  `parentSpanId: ""` orphan_parent contradiction, registered as R10.
- 2026-09-11: run 3 ends here. Run 4 resumes at R3's decision, then R8, R9,
  R10, R7. Nothing is blocked; nothing failed twice.
- 2026-09-11: R3 decided (c). R1's refusal of a trace carrying bare
  `NaN`/`Infinity` (`graph_not_serializable`, exit 1) is a user-visible change
  introduced without a halt because the row required strict-JSON output; the
  run-3 cold review is asked to judge it. R7 records it under open threads if
  the review does not settle it.
- 2026-09-11: R11 landed decision (c) in SPEC §3.7 and §7, ADAPTERS.md and
  OPEN_QUESTIONS §17; R1's two pin tests now say the behaviour is documented,
  not merely current. Nothing moved: `serialized_shape.json` unchanged,
  `otlp_container` still byte-identical to `llm_tool_llm`. The §17 line dates
  the decision rather than citing WORKPLAN.md, because doc-truth forbids a
  durable document depending on a file deleted at series close -- R7 should
  point it at the TASKS.md audit log when §3 moves there.
- 2026-09-11: R8 applied R4's rule at the four keys its row named, and fixed
  `tool_call.id` in *both* renderings the dialect uses (the bare key and
  `...tool_calls.N.tool_call.id`, where the loop consumed before reading).
  `_operation` now reads all three names before consuming any, so a readable
  name that lost the field is still consumed. Corpus verified, not assumed: 25
  tracked files carry one of the keys, 0 carry a non-string value. R8 found the
  same contradiction at three more OpenInference keys and at three keys in
  `otel_genai.py`; registered as R12. R12 arrived after run 4's order was
  fixed, so it is not in run 4 -- R7 carries it as an open thread unless the
  human opens a run 5 first.
- 2026-09-11: R9 recomputed four more figure families and moved every one:
  C3's 154 timestamp values -> 34, D2's 24 data edges over 15 files -> 4 over 3,
  F1's "64 of 64" -> 50 of 50, and the "46 malformed_record" recomputed from
  nothing at all (it was a temp-dir export no tracked file carries; the tracked
  figure is 327). Substantive: C3's "it bit no fixture and no captured trace"
  was measured over a scope holding no fixtures -- over the tracked corpus 10
  literals of 300 sit above the ceiling, the ten C1 wrote to sit there.
- 2026-09-11: the run-3 cold review (patches/REVIEW-2026-09-11-run3.md) lands
  between R9 and R10 and reorders the rest of the run. Its F1 is a blocker for
  the series close and is materially worse than the defect R6 was fixing: R6
  replaced A6's over-claim with a different over-claim, and its pin test is
  green only because it nests lists where a graph document nests dicts. R12-R17
  now stand between R10 and R7, and R7 is blocked until they land. R9's row is
  widened in place rather than reopened as a new row, because R9's own commit
  already added a binding test; the widening is verified by a follow-up pass,
  not assumed.
- 2026-09-11: the verification pass settled it against the guess above -- R9's
  binding test caught **none** of the review's six plants (OQ §13(h), §14,
  §14(h), CHANGELOG x2, TASKS.md note 7 all left doc-truth at 40 passed, 0
  failed), because it binds figures at listed *sites*. `0dbcc71` adds a
  site-free scanner: the `N files / M records` pair is read in every durable
  document, and the seven single-number families only inside a paragraph that
  states the census's scope, so `n(n-1)/2 data edges` stays quiet. Retired
  figures stay legal as values and the older drift test still requires them to
  be marked as history -- the two tests divide the work. Proven red on the six
  plants plus two in other families.
- 2026-09-11: R10 normalised the empty parent reference at the **seam**, not the
  reader: one shared `spanweave.seam.parent_ref()` maps `""` to `None` and both
  adapters call it, so the reader still renames `parentSpanId` verbatim (§16(c)
  holds) and the builder still tests `is None`. Exactly the empty string --
  `" "` and `"0000000000000000"` stay references. The rule went to SPEC §4.0/§6
  rule 1, not the §3.1 the row named, because a `Node` carries no parent; the
  batch flagged that rather than forcing it. Why nothing caught the defect: no
  tracked fixture carried an empty parent, because `otlp_container` *omitted*
  the field on its roots -- both renderings now write `parentSpanId: ""`, and
  the two scenarios go from 1 `orphan_parent` each to 0 with their stored
  expectations byte-identical. R10 also moved R17's premise; R17's row records
  the correction.
- 2026-09-11: R12 landed in two commits -- the six attribute keys
  (`f03de6b`) and the record-level identity fields (`2935d11`). The
  cross-dialect claim is pinned as a two-adapter test table rather than a
  conformance scenario, deliberately: a new scenario would add files and
  records to the tracked census that R9's site-free scanner now binds in every
  durable document, for a claim the table states more directly. The genai half
  of that table was red and the openinference half green before the fix, which
  is the finding itself. `unknown_span_kind` no longer says "no attribute" of a
  key that was sent. Corpus verified across 221 attribute-key occurrences in 51
  files and 660 record-field occurrences in 89: nothing in the tree reaches a
  changed branch. R12 registered R18.
- 2026-09-11: R13 re-measured rather than copying the review, and every row of
  the review's table reproduced *in direction*; 3.14's exact numbers did not,
  because 3.14 checks the C stack pointer (three runs: 40107/37243,
  40103/37242, 40097/37235, and a bigger environment moved both by ~170). The
  2,865-level band is exact. The list row explains the run-2 review's "~1.9x":
  that was 3.14 measured with lists. One correction to the review's own premise:
  `uv run` here selects **3.12.3**, not 3.14 -- this `.venv` predates 3.14, and
  it is a *fresh checkout* that would pick it. The new pin measures both shapes,
  records parser/encoder/ratio/band, and asserts no direction; the CI matrix is
  now derived from the classifiers, proven red by removing 3.14. R13 found a
  bare `RecursionError` escaping `build` on 3.14 and registered it as R19.
- 2026-09-11: R14 chose to **document** the digit-limit dependency rather than
  pin it at import: `sys.set_int_max_str_digits(4300)` inside `import spanweave`
  is a process-wide mutation of a DoS mitigation the host may have set
  deliberately (invariant 5), and it would not settle invariant 4 anyway, since
  any code can move the limit afterwards. New SPEC §5.3 states the condition
  with the measured before/after and the pin (`PYTHONINTMAXSTRDIGITS=4300`).
  The review undercounted its own finding: `=0` reddens five of R1's tests and
  `=640` two more -- seven, not two. The suite now passes under `=0`, `=640`
  and the default alike, with the boundaries derived from
  `sys.get_int_max_str_digits()` and two new doc-truth gates (docs must name
  the setting; no test may hard-code the boundary or move the limit). The graph
  still differs across settings -- that is now a documented, tested condition on
  §5.1, not a fixed defect; making it unconditional would be a spec decision.
- 2026-09-11: R15 implemented the general form rather than a `reviews/` special
  case: every `.md` read *out of the built tarball* is a citer, and a path in a
  code span whose first segment is a top-level repo entry must be an sdist
  member if git tracks it. 75 tracked files and 9 directories are in scope; the
  first-segment rule drops 38 document-relative candidates. Proven red with
  `/reviews` removed (it names both review files and their citers) and verified
  against the tarball's 301 members, not the config. SPEC deliberately unmoved:
  packaging only. The review's §4 nit -- `reviews/` enrolled in `documents()`
  scans, wanting `VERBATIM_PARTS` at `documents()` level -- is untouched and
  belongs to R7's open threads.
- 2026-09-11: R16 landed its five parts as one commit -- they are one contract
  seen from outside the process. The `validate`/`build` asymmetry was real and
  the red proof is captured: a graph carrying a bare `NaN` printed `valid`,
  exit 0. `serialize.py` now decides which fact a `ValueError` was with an
  iterative cycle-safe walk over keys as well as values, so a circular
  reference stops being reported as a number JSON cannot write. The README's
  failure line is now *run* and compared rather than asserted, and the
  documented exit-code set is recomputed from `cli.EXIT_OK`/`EXIT_FAILED` plus
  argparse's own. `OPEN_QUESTIONS.md` §16(a) quotes a pre-change failure line
  inside a dated "measured" block; left as a record, and R7 should note it.
- 2026-09-11: R17 re-measured on three trees rather than copying either number:
  on R3's own commit and on R10's parent, `parentSpanId: ""` gives
  `{'orphan_parent': 201, 'timestamp_unit_suspect': 200}` and the omitted form
  gives just the 200 -- both review figures reproduce exactly -- while on the
  current tree both shapes give 200 and **0** `orphan_parent`. Every correction
  is dated rather than silently rewritten, including a provenance note that
  F1's §16(e) claim was false in both halves when written. §16(a)'s quoted
  refusal was twice stale (F2 stopped it refusing; R16 added the bracket) and
  is now dated in place.
- 2026-09-11: R19 and R18 were put to the human, who expressed no preference,
  so the builder decided: R19 runs before R7, R18 goes to `DEBT.md` at R7. R17
  also found that the run-3 review is still only in untracked `patches/` --
  R2's defect shape exactly -- so R7 archives it as
  `reviews/2026-09-11-run3.md`.
- 2026-09-11: R19 reproduced the three bands on all four interpreters before
  fixing anything (3.14.6: parser ~40,100 / digest ~37,230, with 37,640 and
  38,670 raising a bare `RecursionError` out of `spanweave.build`; 3.11/3.12/
  3.13 ceilings coincide and have no middle band at all). The target chosen and
  argued from §7's own rule: the same `graph_not_serializable` the write side
  raises, contained in A6's shape *inside* `record_digest`, so it covers reader,
  seam and `ids.py` on every interpreter rather than only where the band exists.
  A `malformed_record` was considered and rejected -- it would make the document
  unwritable and make two such records' order depend on input order (invariant
  4). Two of the three tests digest a value built in memory, so they are red on
  **every** interpreter, which is how R13's one-interpreter-only trap was
  avoided. R13's depth machinery moved to a tracked `tests/json_depth.py`.
  Correction to R13's note: a fresh `.venv` picks 3.14.6, not 3.12.3.
- 2026-09-11: SPEC §7 no longer carries a known-deviation bullet -- the close
  has one fewer live defect than when the run-3 review was written.

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
