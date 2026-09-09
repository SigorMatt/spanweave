# WORKPLAN.md — spanweave audit-fix series

Status file for the fix series that follows the September 2026 audit. One
batch = one sub-agent = one commit = one concern. This file plus git is the
only state; any session can resume cold from it.

Last updated: 2026-09-09 (plan adapted to the two-session Claude Code model;
no batches started).
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

---

## 1. Batch list

Legend: `todo` · `in progress` · `awaiting decision` · `done` · `dropped`

### Phase A — contract violations and correctness (small, low risk)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| A1 | **RecursionError containment.** Catch `RecursionError` with `ValueError` in `read._read_line`, `read._read_array`, and payload/message JSON parsing in both adapters. Emit `malformed_record` / `payload_parse_failed`. Tests: 100k-deep array as a record line, as a payload attribute, inside `gen_ai.input.messages`. SPEC §7 Inputs: one sentence. CHANGELOG. | done | 15 |
| A2 | **Reader tolerance.** Strip a UTF-8 BOM at the head of the stream; accept CR-only line endings. Tests. SPEC §7. CHANGELOG. | done | 10 |
| A3 | **Duplicate records and duplicate span ids.** (a) Byte-identical duplicate records: keep one, emit new diagnostic `duplicate_record` (SPEC §3.7 table, `diagnostics.py`, `test_codes`). (b) Same span id, different content: derive ids from `(source_key, ordinal)` so both are kept and `duplicate_source_id` fires *as SPEC §3.7 already claims*; fix the contradicting comment in `ids.py`; SPEC §3.6 rule 2 wording. Conformance degenerate scenario `duplicate_span_id` in both dialects with expected graph + diagnostics. CHANGELOG. | todo | 25 |
| A4 | **Missing trace id diagnostic.** `trace_id == ""` currently silent → emit `missing_trace_id` (info). SPEC §3.7. Test. | done | 8 |

### Phase B — performance

| # | Batch | Status | Est. calls |
|---|---|---|---|
| B1 | **Annotation cost.** `Graph.annotate` rebuilds indexes via `dataclasses.replace` → O(N+E) per call (measured: 2,000 annotations on 3,001 nodes = 33 s). Carry `_index/_out/_in` across the replace (nodes/edges unchanged), add `Graph.annotate_many(entries)`. Tests: identity of shared indexes after annotate; `annotate_many` equals sequential `annotate`; determinism gate still green. SPEC §8. CHANGELOG. | todo | 15 |
| B2 | **Reader line splitting.** `_read_lines` re-copies the buffer per line. Measure on a 200 MB file first; implement `bytes.find`-based splitting only if ≥20% faster. Otherwise `dropped` with the numbers recorded here. | todo | 10 |

### Phase C — timestamps

| # | Batch | Status | Est. calls |
|---|---|---|---|
| C1 | **Unit suspicion + numeric strings.** New diagnostic `timestamp_unit_suspect` (warning) when a start/end value exceeds 1e11 (seconds since epoch cannot; ms/ns can). Both adapters accept numeric-string timestamps (OTLP JSON encodes int64 as strings). Values stay as reported (losslessness); nothing is converted. SPEC §3.1, §3.7. Fixtures: ns-int and string-timestamp renderings. CHANGELOG. | todo | 20 |
| C2 | **Representation memo (HALT).** float64 seconds loses precision at epoch-ns scale (ULP 256 ns → 100 ns-apart spans compare equal; temporal tie falls to node id). Options: keep float + diagnostic; integer nanoseconds internally with seconds only in serialization; `Decimal`. Write `OPEN_QUESTIONS.md` entry with recommendation (int ns internal). No code until decided. | todo | 6 |

### Phase D — `data` edge echo

| # | Batch | Status | Est. calls |
|---|---|---|---|
| D1 | **Echo memo (HALT).** History echo makes `data` edges O(turns²) (measured: 400 turns → 79,800 edges). Options: (a) two builder-owned `basis` strings, first declared receipt vs re-declaration, all edges kept (no edge-set change); (b) build flag `data_echo="all"|"first"`; (c) both. Default is the decision. Memo in `OPEN_QUESTIONS.md` + `SPEC.md` §4.2 draft text. | todo | 6 |
| D2 | **Echo implementation** per decision. Check which existing conformance expectations carry echo edges before touching them (`FIXTURES.md` §4 rule). Tests, fixtures, SPEC §4.2, CHANGELOG. | awaiting D1 | 20 |

### Phase E — mixed instrumentation in one trace (the critical one)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| E1 | **Design memo (HALT).** Per-record dialect dispatch. Today selection is per file; real traces mix OpenInference framework spans and OTel GenAI SDK spans, and forcing either adapter loses the `call_result` pairing. Options: (a) registry classifies each record by marker, each adapter parses only its records, `Meta.adapters` lists all used (already a tuple), `Provenance.adapter` per node; (b) explicit composite `--adapter openinference+otel_genai`; (c) both, with (a) as the auto path when file-level detection is ambiguous but every record is individually unambiguous. Also: what happens to a record no adapter claims. Memo to `OPEN_QUESTIONS.md` + `DESIGN.md` draft + `SPEC.md` §6.1 draft. | todo | 8 |
| E2 | **Registry: per-record classification.** `AdapterRegistry.classify(record) -> adapter_id | None` from the adapters' existing marker logic (no new adapter API if avoidable; `ADAPTERS.md` update if not). Detection tests: pure files unchanged; mixed file → classification map; a record claimed by two adapters → still a hard error. | awaiting E1 | 20 |
| E3 | **Builder: multi-adapter spans.** `build_graph` accepts spans from several adapters; `ids.derive` already takes `adapter_id` per span — verify id stability; `Meta.adapters` = all used, ordered by id. Conformance scenario `mixed_instrumentation`: OpenInference agent + tool, OTel GenAI chat, expected graph **identical to `llm_tool_llm`'s canonical graph**. This extends cross-dialect equivalence to intra-trace mixing and is the batch's acceptance test. | awaiting E2 | 25 |
| E4 | **CLI, docs, changelog.** `--adapter auto|<id>|mixed` semantics, `spanweave inspect` shows per-adapter node counts, README "What is real" section, ADAPTERS.md, SPEC §6.1 final text. | awaiting E3 | 12 |

### Phase F — OTLP JSON container (ROADMAP Phase 4 item, pulled forward)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| F1 | **Design memo.** OTLP JSON as a *container format* in `read.py` (like the array form), not an adapter: `resourceSpans[].scopeSpans[].spans[]` → flat records; attribute arrays → dict; `startTimeUnixNano` strings → numbers (depends on C1/C2); `kind` int, `status.code` mapping; resource/scope attributes preserved under a reserved key or dropped with a diagnostic (losslessness says preserved). Memo + SPEC §7 draft. | awaiting C2 | 8 |
| F2 | **Implementation.** Reader support, fixtures: OTLP-JSON rendering of `llm_tool_llm` in both dialects → same canonical graph. Tests, SPEC §7, ADAPTERS.md note, CHANGELOG. | awaiting F1 | 25 |

### Phase G — roadmap and governance

| # | Batch | Status | Est. calls |
|---|---|---|---|
| G1 | **"Real outside users" gate definition.** ROADMAP.md Phase 4: replace the hope with a condition. Proposed definition (for decision, not mine to make): at least two of — an adapter contribution merged from outside; a consumer built on 0.9.x that filed a model-level issue (a falsification consumer, CONTRIBUTING #4); a captured trace with provenance contributed from outside; 30 days on PyPI with ≥1 issue reproducing on a non-fixture trace. Add "Announcement" as an explicit task with owner. | todo | 6 |
| G2 | **Track the audit in TASKS.md.** Append section "September 2026 audit" to TASKS.md: one line per batch A1–H1 with its one-sentence purpose and "tracked in WORKPLAN.md". Do not edit earlier sections. Add a one-line pointer under the relevant ROADMAP.md Phase 4 bullet only if a bullet already covers the item (OTLP JSON); otherwise nothing in ROADMAP.md. | done | 6 |
| G3 | **Roadmap review.** Phase 4 is coarse by design (sharpen when Phase 3 exit is met). Check: is the audit's E (mixed instrumentation) a freeze precondition? Argument that it is: the freeze measures whether adapter-supplied fields agree across adapters; a single trace exercising two adapters at once is the strongest form of that measurement. Propose text; decision is the maintainer's. | todo | 6 |
| G4 | **Series close:** record final statuses in TASKS.md, move §3 decisions there, remove WORKPLAN.md and its README row, run make check. | todo | 4 |

### Phase H — agent identity (from the earlier review)

| # | Batch | Status | Est. calls |
|---|---|---|---|
| H1 | **Identity memo (HALT).** `operation` is `None` for agent/chain/retriever in both dialects. Options: map `gen_ai.agent.name` into `operation` (dialect-asymmetric); a new `identity` field carrying value + provenance (mirrors `warrant`); leave as is and document. Memo in `OPEN_QUESTIONS.md`. Model change → decision required. | todo | 6 |

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
(stops at the decision point). **Run 2** (after decisions are logged in §3)
= D2 E2 E3 E4 F1 F2 G4. Each batch is one sub-agent regardless of run.

---

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| | | | |

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
- **New finding, not in the audit and not yet a batch:** `json.dumps` in the
  adapters' `_payload` non-str branch and in `serialize.py` can still raise
  `RecursionError` on a payload that parsed just under the limit but is dumped
  from a deeper stack. Out of A1's scope by its row's wording. Maintainer's
  call whether to register it as a batch.
- G2 touched `ROADMAP.md` (one line under the Phase 4 OTLP-JSON bullet, which
  its row explicitly permits). §0.6's "ROADMAP.md is untouched until G3" is the
  general rule; G3 may revert those three lines if it wants the file virgin.

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
