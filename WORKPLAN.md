# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-10 (decisions of 2026-09-10 applied; run 2 batches
added).
Baseline: commit `8d26e1b` ("I1 resolved"), 1601 tests pass, 4 skipped.

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

Legend: `todo` · `in progress` · `awaiting decision` · `done` · `dropped`

### Phase A — contract violations and correctness (small, low risk)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| A1 | **RecursionError containment.** Catch `RecursionError` with `ValueError` in `read._read_line`, `read._read_array`, and payload/message JSON parsing in both adapters. Emit `malformed_record` / `payload_parse_failed`. Tests: 100k-deep array as a record line, as a payload attribute, inside `gen_ai.input.messages`. SPEC §7 Inputs: one sentence. CHANGELOG. | done | 15 |
| A2 | **Reader tolerance.** Strip a UTF-8 BOM at the head of the stream; accept CR-only line endings. Tests. SPEC §7. CHANGELOG. | done | 10 |
| A3 | **Duplicate records and duplicate span ids.** (a) Byte-identical duplicate records: keep one, emit new diagnostic `duplicate_record` (SPEC §3.7 table, `diagnostics.py`, `test_codes`). (b) Same span id, different content: derive ids from `(source_key, ordinal)` so both are kept and `duplicate_source_id` fires *as SPEC §3.7 already claims*; fix the contradicting comment in `ids.py`; SPEC §3.6 rule 2 wording. Conformance degenerate scenario `duplicate_span_id` in both dialects with expected graph + diagnostics. CHANGELOG. | done | 25 |
| A4 | **Missing trace id diagnostic.** `trace_id == ""` currently silent → emit `missing_trace_id` (info). SPEC §3.7. Test. | done | 8 |
| A5 | **Content-derived fallback ids.** Review blocker 1 / §12(f): a record with no `span_id` gets `source_key = str(index)` in both adapters, so shuffling the input rebinds ids (`sw_cde39f998fc177dc` names `beta` forward and `alpha` reversed). Fallback `source_key` becomes the record's canonical digest (A3's rule applied one level up); SPEC §3.6 rule 2 wording; both adapters identical under diff. New degenerate conformance scenario `derived_ids` with span-id-less records **and a shuffled rendering**, expected graphs equal. Shuffle tests extended beyond `WORKED_RECORDS`. Moves 0 stored expectations. Must land before E2. | done | 20 |
| A6 | **RecursionError on the CLI path and dump paths.** Review blocker 2: `spanweave inspect`/`validate` still die (`cli.py:178`/`:208` catch `ValueError`/`OSError`; `_read_document` sniffs with its own `json.loads`). Plus resume-note finding: `json.dumps` in the adapters' `_payload` non-str branch and in `serialize.py` can raise on a payload parsed just under the limit. Route the sniff through the fixed reader or catch `RecursionError` there; catch on the dump paths with `payload_parse_failed`/a serializer diagnostic per SPEC §3.7. Tests on the CLI entry points. | done | 12 |
| A7 | **Spec–code formula and stale doc truth.** SPEC §3.6 at lines ~258 and ~963 omits `ensure_ascii=False` that `read.py:252` passes; `{"name":"café"}` derives different ids by spec and by code. Fix SPEC; add a test that derives one node id from a spec-faithful reimplementation of the digest and compares it to the library's, and pin at least one golden `sw_` id. Also: `fixtures/conformance/README.md:75-77` ("`duplicate_span_ids` must not build") and `CONTRACTS.md:341-344` (seven rows → nine; `duplicate_source_id` now has a fixture). | todo | 12 |
| A8 | **Overclaims and the CR terminator.** Per §3 A2 follow-up: remove lone-CR terminator, keep CRLF/BOM, correct A2's CHANGELOG entry and module docstring; add `{"a":\r1}` as a passing test. Correct A3's CHANGELOG/commit-note claim "no id the library produces moves" (reachable case `sw_fc49b046c1cd484d` → `sw_70ae5dd0e179edd9`): state which ids move and why. C1's sentence is fixed by C3, not here. | todo | 10 |

### Phase B — performance

| # | Batch | Status | Est. calls |
|---|---|---|---|
| B1 | **Annotation cost.** `Graph.annotate` rebuilds indexes via `dataclasses.replace` → O(N+E) per call (measured: 2,000 annotations on 3,001 nodes = 33 s). Carry `_index/_out/_in` across the replace (nodes/edges unchanged), add `Graph.annotate_many(entries)`. Tests: identity of shared indexes after annotate; `annotate_many` equals sequential `annotate`; determinism gate still green. SPEC §8. CHANGELOG. | done | 15 |
| B2 | **Reader line splitting.** `_read_lines` re-copies the buffer per line. Measure on a 200 MB file first; implement `bytes.find`-based splitting only if ≥20% faster. Otherwise `dropped` with the numbers recorded here. **Measured 2026-09-09, not implemented:** 200 MB JSONL, varied line lengths (p50 754 B, 124,656 records), 7 interleaved A/B runs, spread <0.5% — current 6.012 s median vs `bytes.find` prototype 5.776 s = **1.041x (3.9%)**. Worst realistic case (uniform ~334 B lines, 626,023 records): 13.906 s vs 12.771 s = 1.089x (8.2%). Ceiling is structural: cProfile puts `_read_lines` + `_line_break` at 0.77 s of 7.51 s (10.3%); the reader is dominated by the dedup digest's `json.dumps` (2.28 s) and `json.loads` (1.11 s). Prototype verified byte-identical across 66 case/chunking pairs, then discarded. Machine: i7-4600U @ 2.1 GHz, CPython 3.12.3. | dropped | 10 |
| B3 | **`unmapped_attributes` volume.** §11's finding: 13.36 MB of diagnostics at 400 turns because `_received_results` reads `...message.role` to decide but never marks it consumed. Mark every key an adapter *reads* as consumed, in both adapters; audit for other read-but-unconsumed keys; measure diagnostic bytes on `tests/audit/probe2.py` loop 400 before/after and record both numbers in this row. Moves 0 expectations unless a fixture's `unmapped_attributes` list shrinks — if so, regenerate and say so. | todo | 15 |

### Phase C — timestamps

| # | Batch | Status | Est. calls |
|---|---|---|---|
| C1 | **Unit suspicion + numeric strings.** New diagnostic `timestamp_unit_suspect` (warning) when a start/end value exceeds 1e11 (seconds since epoch cannot; ms/ns can). Both adapters accept numeric-string timestamps (OTLP JSON encodes int64 as strings). Values stay as reported (losslessness); nothing is converted. SPEC §3.1, §3.7. Fixtures: ns-int and string-timestamp renderings. CHANGELOG. | done | 20 |
| C2 | **Representation memo (HALT).** float64 seconds loses precision at epoch-ns scale (ULP 256 ns → 100 ns-apart spans compare equal; temporal tie falls to node id). Options: keep float + diagnostic; integer nanoseconds internally with seconds only in serialization; `Decimal`. Write `OPEN_QUESTIONS.md` entry with recommendation (int ns internal). No code until decided. | done | 6 |
| C3 | **Timestamp representation, per C2 decision.** `int \| float \| None`; `_as_time` returns `int` for integer literals (quoted or bare), `float` otherwise; ceiling constant `100_000_000_000`; C1 diagnostic `source` carries the exact reported value; SPEC §3.1 field table; `timestamp_units` expected graph (5 values) and its scenario.md sentence; `tests/serialized_shape.json` (two type lines). probe2 case G converted to a test. | todo | 20 |

### Phase D — `data` edge echo

| # | Batch | Status | Est. calls |
|---|---|---|---|
| D1 | **Echo memo (HALT).** History echo makes `data` edges O(turns²) (measured: 400 turns → 79,800 edges). Options: (a) two builder-owned `basis` strings, first declared receipt vs re-declaration, all edges kept (no edge-set change); (b) build flag `data_echo="all"\|"first"`; (c) both. Default is the decision. Memo in `OPEN_QUESTIONS.md` + `SPEC.md` §4.2 draft text. | done | 6 |
| D2 | Implement §11(d): three `basis` strings per the table, earliest by `(started_at, node_id)`; every edge kept; DESIGN.md §6 qualifier; SPEC §4.2 draft text from §11 landed; the 4 corpus expectations that carry receipts must not change (verify). probe2 loop case stays as a test of edge count and basis split. | todo | 20 |

### Phase E — mixed instrumentation in one trace (the critical one)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| E1 | **Design memo (HALT).** Per-record dialect dispatch. Today selection is per file; real traces mix OpenInference framework spans and OTel GenAI SDK spans, and forcing either adapter loses the `call_result` pairing. Options: (a) registry classifies each record by marker, each adapter parses only its records, `Meta.adapters` lists all used (already a tuple), `Provenance.adapter` per node; (b) explicit composite `--adapter openinference+otel_genai`; (c) both, with (a) as the auto path when file-level detection is ambiguous but every record is individually unambiguous. Also: what happens to a record no adapter claims. Memo to `OPEN_QUESTIONS.md` + `DESIGN.md` draft + `SPEC.md` §6.1 draft. | done | 8 |
| E2 | Registry `classify(record)` from each adapter's existing `detect([record])`; per-record partition above the seam in `api.py`; single-dialect input byte-identical to today; a record two adapters claim → `adapter_ambiguous` naming line/span id/claimants; a record none claims → passed through as unclaimed for E3. Detection tests for all three cases. | todo | 20 |
| E3 | Builder accepts spans from several adapters; unclaimed records → `unknown` node + `unclaimed_record` warning; `Provenance.adapter_id: str \| None` (regenerate `serialized_shape.json`, say so); `Edge.adapter = None` when ends differ (SPEC §3.8); `Meta.adapters` = all contributors with each one's `declared_confidence`; decide and document whether `duplicate_source_id` should report on `source_key` rather than `span_id` (§12(f)). Conformance scenario `mixed_instrumentation`: OpenInference agent+tool, OTel GenAI chat, expected graph identical to `llm_tool_llm`'s canonical graph; a shuffled rendering; a forced-single-adapter rendering whose `node_count` equals the mixed build's. Depends on A5. | todo | 25 |
| E4 | `--adapter auto\|<id>` (no `mixed`); `spanweave inspect` shows per-adapter node counts; README, ADAPTERS.md (the one-sentence per-record contract from §12(d)), SPEC §6.1 final text from §12, DESIGN.md §3 subsection from §12(k), CHANGELOG. | todo | 12 |

### Phase F — OTLP JSON container (ROADMAP Phase 4 item, pulled forward)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| F1 | **Design memo.** OTLP JSON as a *container format* in `read.py` (like the array form), not an adapter: `resourceSpans[].scopeSpans[].spans[]` → flat records; attribute arrays → dict; `startTimeUnixNano` strings → numbers (depends on C1/C2); `kind` int, `status.code` mapping; resource/scope attributes preserved under a reserved key or dropped with a diagnostic (losslessness says preserved). Memo + SPEC §7 draft. **F1 may proceed directly into F2 in the same run** if its design needs no model or schema change and no new default; if it needs any, it halts as `awaiting decision` and F2 waits for run 3. | todo | 8 |
| F2 | **Implementation.** Reader support, fixtures: OTLP-JSON rendering of `llm_tool_llm` in both dialects → same canonical graph. Tests, SPEC §7, ADAPTERS.md note, CHANGELOG. Timestamps land as `int` per C3; `startTimeUnixNano` strings arrive intact. | todo | 25 |

### Phase G — roadmap and governance

| # | Batch | Status | Est. calls |
|---|---|---|---|
| G1 | **"Real outside users" gate definition.** ROADMAP.md Phase 4: replace the hope with a condition. Proposed definition (for decision, not mine to make): at least two of — an adapter contribution merged from outside; a consumer built on 0.9.x that filed a model-level issue (a falsification consumer, CONTRIBUTING #4); a captured trace with provenance contributed from outside; 30 days on PyPI with ≥1 issue reproducing on a non-fixture trace. Add "Announcement" as an explicit task with owner. | done | 6 |
| G2 | **Track the audit in TASKS.md.** Append section "September 2026 audit" to TASKS.md: one line per batch A1–H1 with its one-sentence purpose and "tracked in WORKPLAN.md". Do not edit earlier sections. Add a one-line pointer under the relevant ROADMAP.md Phase 4 bullet only if a bullet already covers the item (OTLP JSON); otherwise nothing in ROADMAP.md. | done | 6 |
| G3 | **Roadmap review.** Phase 4 is coarse by design (sharpen when Phase 3 exit is met). Check: is the audit's E (mixed instrumentation) a freeze precondition? Argument that it is: the freeze measures whether adapter-supplied fields agree across adapters; a single trace exercising two adapters at once is the strongest form of that measurement. Propose text; decision is the maintainer's. | done | 6 |
| G5 | **Roadmap text, per G1 and G3 decisions.** Land §13(f) and §14(i) text in ROADMAP.md: the outside-users condition (A and B and floor), the announcement task with owner and "what it must not claim", the general schema-movement rule for the freeze, the recorded absences (57 files / 177 records / 0 mixed; no instrumentor-emitted agent span in the corpus). Keep G2's three lines. No code. | todo | 10 |
| G4 | **Series close:** record final statuses in TASKS.md, move §3 decisions there, remove WORKPLAN.md and its README row, run make check. Also: the ROADMAP.md line and memo cross-references per §14(j); CONTRACTS.md rows; confirm every OPEN_QUESTIONS §10–§15 decision line reads the §3 decision verbatim. | todo | 4 |

### Phase H — agent identity (from the earlier review)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| H1 | **Identity memo (HALT).** `operation` is `None` for agent/chain/retriever in both dialects. Options: map `gen_ai.agent.name` into `operation` (dialect-asymmetric); a new `identity` field carrying value + provenance (mirrors `warrant`); leave as is and document. Memo in `OPEN_QUESTIONS.md`. Model change → decision required. | done | 6 |
| H2 | **Identity non-mapping, per H1 decision.** SPEC §3.1: state the rule that `operation` is not populated for agent/chain/retriever from any dialect's name attribute, with the `raw.source`/`unmapped_attributes` note; fix §3.1's "retriever name" promise no dialect states; record the measured absence of instrumentor-emitted agent spans beside §14(h) item 4. OPEN_QUESTIONS §15: mark option B as the additive 1.1 path. No code. | todo | 8 |

---

## 2. Execution order

G2 → A1 → A2 → A4 → A3 → B1 → B2 → C1 → C2 (memo) → D1 (memo) → E1 (memo) →
G1 → G3 → H1 (memo) → [decisions] → D2 → E2 → E3 → E4 → F1 → F2 → G4.

Rationale: everything before the first memo is unambiguous under the
current SPEC and can be reviewed independently. The four memos are
batched together so decisions can be taken in one sitting. E is the largest
and most valuable change and is last among implementations because it is the
one most likely to need a second round.

Run grouping: **Run 1** = G2 A1 A2 A4 A3 B1 B2 C1 then memos C2 D1 E1 G1 G3 H1
(stopped at the decision point; decisions logged in §3 on 2026-09-10).
**Run 2** = A5 → A6 → A7 → A8 → B3 → C3 → D2 → H2 → G5 → E2 → E3 → E4 → F1 →
(F2 if F1 did not halt) → G4 (only if F2 is done; otherwise G4 waits for run
3). Each batch is one sub-agent regardless of run.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-09-10 | C2 | Option 2: keep the reported integer literal as `int`, never rescale; fractional literals stay `float`; `started_at`/`ended_at: int \| float \| None`. Ceiling constant becomes `100_000_000_000`; C1's "kept exactly as reported" sentence becomes true by construction. Implemented by C3. | maintainer |
| 2026-09-10 | D1 | Option (a), no flag: every declared receipt stays an edge; three builder-owned `basis` strings per §11(d) table (earliest / earliest tied broken by node_id / not the earliest receiving span). DESIGN.md §6 "no quadratic edge construction" gets the per-turn qualifier. Implemented by D2. | maintainer |
| 2026-09-10 | E1 | Option (a), always: per-record classification in the registry via `detect([record])`; no `mixed` mode, `--adapter auto` is the explicit default spelling. A record two adapters claim → hard error reusing `adapter_ambiguous`, message naming line, span id, both claimants. A record no adapter claims → `unknown` node + new `unclaimed_record` warning; `Provenance.adapter_id: str \| None` (model change taken now, unfrozen). `Edge.adapter = None` when the two ends came from different adapters, SPEC §3.8 says so. E3 lands only after A5. | maintainer |
| 2026-09-10 | G1 | Adopt §13(f) replacement text: one agreement event (1 or 2) AND one exposure event (3 or 4), plus a 30-day floor from the later of 2026-08-30 and the announcement; the floor is never evidence. Announcement becomes an owned task per §13(g). Implemented by G5. | maintainer |
| 2026-09-10 | G3 | All five items of §14(h): E is a freeze precondition on schema grounds, stated as a general rule ("no freeze while any batch that moves a serialized field is open"); no "mixed trace observed" condition; absences recorded as measurements; freeze conditions sharpened now, Phase 4 PR breakdown held; G2's ROADMAP lines kept. G4 scope widened per §14(j). | maintainer |
| 2026-09-10 | H1 | Option C: `operation` stays `None` for agent/chain/retriever; the non-mapping becomes a stated rule in SPEC §3.1 with the verbatim-in-`raw.source` note; option B (`identity` field) recorded as the additive 1.1 path in OPEN_QUESTIONS §15. Implemented by H2. | maintainer |
| 2026-09-10 | A2 follow-up | Bare CR is legal JSON whitespace; a lone-CR *terminator* splits `{"a":\r1}` that used to parse (review overclaim 3). Resolution: keep BOM and CRLF handling, drop the lone-CR terminator; CR-only files are not a real input, CR inside a record is. Implemented by A8. | maintainer |

---

## 4. Resume note

Run 1 in progress on branch `audit-fixes` (base `02e9f6e`). G2 done (`ad77259`).

- **No CHANGELOG file exists in this repo.** Seven rows (A1, A2, A3, B1, C1,
  D2, F2) say "CHANGELOG." Ruling for the series: the first batch that needs
  one checks for release notes under another name first; if there are none it
  creates `CHANGELOG.md` with an `## [Unreleased]` section only — no invented
  history for the already-shipped 0.9.x releases.
- A1 done (`4d7bb32`); it created `CHANGELOG.md` (`## [Unreleased]` only) under
  the ruling above, and had to add a README Documents-table row because
  `tests/test_doc_truth.py` requires every root `*.md` to be listed. Later
  batches add to the existing Unreleased section.
- A2 done (`817951e`): BOM stripped once at the head only, and LF/CRLF/CR each
  count as one terminator with a pending-CR guard across chunk boundaries. The
  input digest still covers the BOM bytes.
- A4 done (`e25ab29`): `missing_trace_id` is **one diagnostic per graph**, not
  per record (no node to point at; per-record would repeat one sentence 10k
  times). Fires when the built graph reports no trace id at all; a single
  record missing an id among records that have one is not diagnosed.
  `tests/serialized_shape.json` moved additively and was regenerated.
- A3 done (`b44c3a5`), and it **deviated from its row deliberately**: rule 3
  puts the record's *canonical digest* into id derivation, not
  `(source_key, ordinal)`. An ordinal is input position, which CLAUDE.md
  invariant 4 forbids from affecting the result; the digest is
  order-independent and total, because (a) first collapses records that differ
  in nothing. "Same record" for (a) = the **parsed** record (canonical digest),
  first copy kept. No existing node id moved, so the halt condition never fired.
- **Consequence of A3 the later batches must respect:** `DuplicateNodeIdError`
  is no longer reachable from any trace file, and the corpus has no refusal
  scenario left that reaches it. `FIXTURES.md` §4.2 and `tests/test_detection.py`
  record the vacancy. Also, `canonical()` now maps derived ids to positional
  labels (`n0`, `n1`) — specified in `FIXTURES.md` §4.1 since Phase 1, first
  implemented here because nothing had produced a derived id before.
- B1 done (`cee10fb`): sequential `annotate` on the audit's case went
  12.50 s -> 1.47 s (8.5x) and `annotate_many` does the same batch in 0.011 s;
  85% of the old time was `Graph.__post_init__`. `annotate_many` is *defined*
  in SPEC §8 as sequential `annotate` (last-wins on a repeated
  `(namespace, node_id, key)`; a refused entry raises and applies nothing).
- **The neutrality gate rejects the word "cost" in `spanweave/` string
  literals** — use "work"/"time" in any docstring a later batch adds.
- B2 dropped, numbers in its row. **Follow-up it surfaced:** if reader speed
  ever matters, the target is the dedup digest A3 introduced — `record_digest`
  re-serializes every record, 3.8 s of 7.5 s cumulative — not line splitting.
- C1 done (`467ff97`). `timestamp_unit_suspect` is **one per node** (both
  endpoints share an encoding, so `source` names the offending fields rather
  than firing twice); checked on reported `started_at`/`ended_at` only, never a
  duration, strictly `> 1e11`. A numeric string is accepted iff unquoting it
  yields a valid JSON number; an unreadable value is named in
  `unmapped_attributes` and still draws `missing_timestamp` — never silently
  absent.
- **C2 must revisit two things C1 left it:** (1) `TIMESTAMP_UNIT_CEILING`
  compares against the value as the model holds it, so an internal
  representation change moves the constant, the check and the diagnostic's
  `source` together; (2) if C2 picks integer nanoseconds, the *string* path can
  preserve every digit where the JSON-number path cannot — a new asymmetry.
- **Pre-existing doc defect, unfixed and untested:**
  `fixtures/conformance/README.md` still says `duplicate_span_ids` "must not
  build" / "no expected graph". A3 made it build. No test catches it.
- C2 memo written (`cd62d45`, `OPEN_QUESTIONS.md` §10) — **awaiting decision**.
  It does **not** recommend the plan's "int ns internally": recommendation is
  *keep the reported integer and never rescale* (`started_at: int | float |
  None`), because rescaling requires knowing the unit C1 just established is
  unknowable. Moves 5 of 108 stored timestamp slots (one fixture) vs 106 for
  the rescale option. Classified honestly as deterministic-but-wrong-ordered,
  not a determinism or losslessness bug; 0 corpus traces affected today. The
  digits arrive exact from `json.loads` and die at `float(value)` in the
  adapters, not in the reader.
- D1 memo written (`635e6ef`, `OPEN_QUESTIONS.md` §11) — **awaiting decision**.
  Recommends **option (a) alone, no flag**. Key finding: the quadratic is the
  *telemetry's*, not the builder's — edge count equals declaration count
  exactly, and all 79,800 edges at 400 turns are `explicit`, warranted and
  individually true under §4.2.1. So this is legibility and volume, never
  wrongness, and a `first` mode would drop true edges for a 34.7% saving on a
  curve that stays quadratic. Curve: 25/50/100/200/400/800 turns → 300 / 1,225
  / 4,950 / 19,900 / 79,800 / 319,600 edges; 0.01 s → 4.90 s; 0.18 MB → 128.77
  MB serialized. 4 of 22 scenarios carry a `data` edge, all first receipts,
  0 re-declarations — so keeping today's string for the earliest case moves
  **0** stored expectations.
- **D1 says the row undercounts: three `basis` strings, not two** — a
  tie-broken *earliest* needs its own, per §4.3's precedent, and §10/C2's float
  ties make ties the common case at ns magnitude. D2 also inherits two defects
  D1 found but did not fix: `DESIGN.md` §6's "no quadratic edge construction"
  needs a qualifier, and `_received_results` consumes the `tool_call_id` key
  but not the sibling `...role` key it reads (13.36 MB of diagnostics at 400
  turns).
- E1 memo written (`5995e0a`, `OPEN_QUESTIONS.md` §12) — **awaiting decision**.
  Recommends **option (a) always**, not (c): the "only when file-level
  detection is ambiguous" precondition is a property of the first 50 records,
  not of the file, so a 10k-span OpenInference trace whose GenAI spans start at
  record 200 would never enter mixed mode and would lose them silently.
  Demonstrated: auto refuses (`adapter_ambiguous`); each forced build exits 0
  and loses **2 of 7 edges** — `call_result` *and* `data`, so the audit's claim
  is right and undercounts — and reports `Payload.state = absent` where content
  was emitted, which is the sharper harm.
- **E3's acceptance test as written is achievable**: `canonical()` already
  erases `provenance` from nodes and `adapter` from edges and compares derived
  ids positionally, and `meta.adapters` is not compared. Caveat E3 must carry:
  a mixed rendering's payload *values* are a mix, so the scenario needs
  `llm_tool_llm`'s existing `comparison.json` declarations, and "mixed" must
  not enter `tests/conformance.py:DIALECTS`.
- **A mixed trace is constructible, not observed** — 57 files / 177 records in
  the corpus, 0 with both markers, 0 doubly claimed, 0 unclaimed. G3 should
  weigh that. The strongest evidence is first-party and unprompted:
  `capture/backends.py` already avoids emitting one by hand, and its comment
  describes finding #1 exactly.
- **E1 surfaced two extra model decisions folded inside E's**: `Edge.adapter`
  needs a rule for a two-adapter join (memo recommends `None`), and an
  unclaimed record wants an `unknown` node + diagnostic, which needs
  `Provenance.adapter_id: str | None`.
- **NEW BUG, pre-existing and dispatch-independent, no batch yet:** a record
  with no `span_id` gets a **position-derived** id, so shuffling such a trace
  changes the graph — a direct violation of CLAUDE.md invariant 4. Undetected
  because all 177 corpus records have span ids. The fix is A3's own reasoning
  (digest, not index) and moves 0 expectations. **E3 will collide with this if
  it is left unfixed** — it wants its own batch before E3.
- G1 memo written (`7c26f0f`, `OPEN_QUESTIONS.md` §13) — **awaiting decision**,
  and it argues the row's own draft is the wrong shape. Proposal: **one
  agreement event + one exposure event + a 30-day floor**, the floor never
  satisfying a condition by itself, nothing counting if the maintainer or their
  agent produced it, and nothing counting until it is in the repo. Reasoning:
  "at least two of four" lets the two cheapest conditions close the gate
  without anyone ever having to agree with a `NodeKind`, `EdgeKind`, warrant or
  `Payload` state — which is the only thing the gate is for. "30 days on PyPI"
  is a clock, not evidence, and was moved out of the conditions.
- **G1's factual findings, which G3 needs:** 0.9.0 and 0.9.1 both published
  2026-08-30 (11 days as of 2026-09-10). Outside evidence today is **zero on
  every checkable axis** — 108 commits/one author, no outside adapters, all
  three captures first-party, no issue references. **No announcement is
  recorded anywhere**, so the clock as drafted measures silence; the memo
  places the announcement before the floor starts. It also documents a real
  contradiction: ROADMAP's "used it unchanged" and CONTRIBUTING #4's "needed a
  change" count *opposite* events as success.
- G3 memo written (`ef857f8`, `OPEN_QUESTIONS.md` §14) — **awaiting decision**.
  Answer: **E is a freeze precondition — but the row's own argument for it
  fails.** The row argued evidential power (a trace exercising two adapters is
  the strongest cross-adapter measurement); G3 shows that under per-record
  dispatch each record is parsed by exactly one adapter, so no adapter-supplied
  field is ever contested, `canonical()` erases the two fields dispatch adds,
  and the one genuine cross-adapter value cannot be measured by a fixture we
  constructed. The conclusion survives on a simpler ground: **E moves the
  schema** under every option E1 leaves live (`unclaimed_record` is a new
  diagnostic code; the recommended option widens
  `Provenance.adapter_id: str -> str | None`). So the precondition is on the
  **decision**, not the implementation — deciding *against* dispatch resolves
  it equally, while freezing `adapter_id` as `str` prices a later E at a
  migration.
- G3 resolves the G1 collision: Phase 4 holds two kinds of precondition — work
  that must land (ours, deliberately) vs outside evidence (not ours, by rule).
  E is the first, so G1's maintainer-exclusion never reaches it.
  **Phase 3 exit: met** (checked against `TASKS.md` 3.11). **G2's three
  ROADMAP lines: keep.**
- **G4's row is short by three items**, per G3: "tracked in `WORKPLAN.md`" in
  TASKS.md points at a file G4 deletes, and G4's row covers `TASKS.md` + the
  README row but not `ROADMAP.md` or the memo sign-offs.
- H1 memo written (`c945ef9`, `OPEN_QUESTIONS.md` §15) — **awaiting decision**.
  Recommends **option C** (leave `operation` `None`; move the non-mapping out
  of an adapter docstring into `SPEC.md` §3.1), holding option B (a new
  `identity` field) open as the additive path that can honestly land at 1.1.
  **The dialect asymmetry is real and measured, and is decisive against option
  A:** injecting `gen_ai.agent.name` — which `capture/backends.py` already
  writes for a real capture — diverges **11 of 18** cross-dialect scenarios /
  12 agent nodes against a baseline of 0, and the only repair
  (`erase: ["operation"]`) is per-scenario and would stop comparing 22 non-null
  `operation` values on neighbouring llm/tool nodes. Independently: both
  adapters already put a *model* name in `operation` on an agent span that
  carries one, so option A needs a precedence rule and either choice makes the
  field mean two things. H1 must be **decided**, not implemented, before the
  freeze; option A binds hardest because it moves an existing field's meaning
  with no `serialized_shape.json` movement to warn anyone.
- **H1 surfaced two more unfixed defects:** `SPEC.md` §3.1 promises a
  "retriever name" no dialect states, and **no instrumentor-emitted agent span
  exists in this corpus in either dialect** — all three captures write theirs
  by hand. That absence is also H1's falsifying experiment.
- **New finding, not in the audit and not yet a batch:** `json.dumps` in the
  adapters' `_payload` non-str branch and in `serialize.py` can still raise
  `RecursionError` on a payload that parsed just under the limit but is dumped
  from a deeper stack. Out of A1's scope by its row's wording. Maintainer's
  call whether to register it as a batch.
- G2 touched `ROADMAP.md` (one line under the Phase 4 OTLP-JSON bullet, which
  its row explicitly permits). §0.6's "ROADMAP.md is untouched until G3" is the
  general rule; G3 may revert those three lines if it wants the file virgin.
- 2026-09-10: run 1 reviewed (`patches/REVIEW-2026-09-10.md`, untracked; all
  §0.2 checks passed on all 27 commits). Decisions logged in §3; A5–A8, B3, C3,
  G5, H2 added; run 2 order set. The three overclaims are assigned (A8, C3);
  the CR terminator is removed by A8. Stale doc-truth lines are A7's.
- The review's summary and both blockers' evidence are worth preserving: G4
  copies `patches/REVIEW-2026-09-10.md` into TASKS.md's audit section as a
  dated subsection before removing WORKPLAN.md.
- A5 done (`b6c5ea9`). Two carry-forwards: (1) byte-identity does **not** catch an
  id-rebinding shuffle defect — ids are assigned in node order, so both renderings
  were byte-identical while every id named a different record; any shuffle claim
  over derived ids needs the id-to-record **binding** assertion the batch added.
  (2) `tests/conformance.py:canonical()` now re-sorts edges on positional labels,
  because SPEC §5.2 sorts edges over graph ids and a derived id differs per
  adapter by design — E3 would have hit this. `OPEN_QUESTIONS.md` §12(f)'s "real
  today" note is now stale; A7 owns stale doc truth.
- A6 done (`477fe9b`). The write half was real, not just the CLI: a payload at
  depth 9994 parses and builds, then `serialize.dumps` raises — the encoder meets
  the value about four levels deeper than the parser does. Contained with a new
  error code `graph_not_serializable` / `GraphNotSerializableError` (SPEC §3.10 +
  export). **This is an additive public-API change**, judged not a halt because no
  data-model field, serialized default, or diagnostic default moved; flagging it
  here so review sees it named. Also: `annotate.check_serializable` did not catch
  `RecursionError`, and on CPython 3.12 the JSON C recursion budget is independent
  of Python stack depth, so the adapters' non-string `json.dumps` is unreachable
  via the reader and is guarded defensively only.
- 2026-09-10, maintainer: a dependency marker (`awaiting <batch>`) whose named
  batch is `done` means `todo`; only the literal `awaiting decision` stops a
  batch. D2, E2, E3, E4, F1, F2 set to `todo` on that instruction. E3, E4 and F2
  were set with their predecessor (E2, E3, F1) still open — §2's run-2 order, not
  the status column, is what holds those three dependencies now.

---

## 5. Findings reference (from the audit, for traceability)

| Audit # | Finding | Batch |
|---|---|---|
| 1 | mixed instrumentation unrepresentable; forced adapter loses `call_result` | E1–E4 |
| 2 | any duplicate span id refuses the file; documented fallback unreachable | A3 |
| 3 | `RecursionError` escapes on deep JSON (record or payload) | A1 |
| 4 | `Graph.annotate` O(N+E) per call | B1 |
| 5 | no timestamp unit check; float64 precision at epoch-ns; strings → missing | C1, C2 |
| 6 | history-echo `data` edges O(turns²) | D1, D2 |
| minor | BOM loses first record | A2 |
| minor | missing `trace_id` silent | A4 |
| minor | OTLP JSON envelope refused | F1, F2 |
| minor | agent/chain/retriever identity | H1 |
| roadmap | "real outside users" undefined; announcement not a task | G1, G3 |

Reproduction scripts for 1–6: `tests/audit/probe1.py`, `tests/audit/probe2.py`
(committed with this plan). Each fixing batch turns the relevant case into a
pytest regression test and deletes it from the probe script.
