# WORKPLAN.md — spanweave, the stranger's-trace series

Status file for the series that answers the zoo's probes: twenty-two
reproductions (`PROBES.md` S1–S22 at `SigorMatt/spanweave-zoo` `7eb5b69`)
taken from twelve captures of six agents built by implementers who knew
nothing about this library, under stock instrumentation. Each batch names
the probes it answers; a probe is answered by a change, by a stated
decision that the rendering is right, or by a documented reading — never
by silence. One batch = one sub-agent = one commit = one concern. This file
plus git is the only state; any session can resume cold from it.

Last updated: 2026-10-14 (run 1: T0, T1 done; T2 next.)

---

## 0. Operating protocol

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
   not `done` / `dropped` / `awaiting decision`. A status `awaiting <batch>`
   is `todo` once that batch is `done`.
3. Dispatch **one sub-agent** with the **batch brief** (0.3) for that batch.
   Wait for its ≤12-line report.
4. Verify: `git log --oneline -3` shows the batch commit; the report says
   `make check` passed. If not, dispatch the same batch once more with the
   report's failure appended. If it fails twice: set status
   `blocked: <one line>`, write the resume note, and continue to the next
   batch **unless** the blocked batch is a dependency of the next.
5. Edit this file: status → `done (<sha>)`, one line under §4 if anything
   was learned. If a row's acceptance number or premise was shown wrong by
   the batch, correct the row in the same edit and say why in the §4 line
   — a wrong criterion has an owner, and it is this step. Commit the plan
   edit together with nothing else (`plan: <batch> done`; a second clause
   after the batch id is allowed when it records something a reader needs).
6. Repeat from 2. Stop when: the run's batches are exhausted; a batch ends
   `awaiting decision`; or the same batch has failed twice.
7. Final step of a run: dispatch a sub-agent to `git format-patch main -o
   patches/` and print `git log --oneline main..HEAD`. Report to the human:
   batches done, blocked, awaiting decision, and the memo file paths to read.
8. `git push origin stranger`. A run is not finished until the push succeeds
   **and the GitHub checks on the pushed tip are green, or every failing
   check is explained in the run report**; local `make check` is not a
   substitute — the CI matrix runs interpreters the machine does not have.
   A series branch is never force-pushed. An amended batch is a new commit
   on top; the replaced sha is recorded in §4 with the reason.

### 0.2 Aux — cold reader

On the prompt `Review WORKPLAN.md commits since <sha>`: for each code commit,
in a sub-agent per commit, check against `CONTRIBUTING.md` and `CLAUDE.md`:
spec changed in the same commit where behaviour changed; the new test fails
on the parent commit, where the parent is `<sha>^` **derived**, never a sha a
brief names (`plan:` commits interleave) — and because a tests-only batch's
derived parent is a `plan:` commit, which makes the parent run vacuous, a
**mutation the new test catches** is required for every code commit, not only
the parent run; worktrees are created by **absolute path under the
scratchpad**, never relative, never inside the repo; no clock read, no
randomness, no network in `spanweave_zoo/` except behind the injected
`now`/`sleep`/socket seams the spec names; commit is one concern. Write
findings to `patches/REVIEW-<date>.md` (untracked) and print them. **Aux
never edits tracked files and never commits**: a finding that needs a commit
is made by the builder from the review file, never by the reviewer.

### 0.3 Batch brief (template the builder passes to a sub-agent)

```
You are executing batch <ID> of WORKPLAN.md in the spanweave repo.
Read, in this order: CLAUDE.md, the WORKPLAN.md row for <ID> and §5, then
the SPEC.md sections the row names, then only the source and test files
the batch touches. Rules: spec first (SPEC.md edited in this commit if
behaviour changes); write the failing test before the fix and confirm it
fails on the parent (`<sha>^`, in a worktree by absolute path under the
scratchpad); name one mutation the test catches and show it caught; then
implement; then `make check`, `make conformance` and `make install-check`.
Add a CHANGELOG entry. Commit once: `<area>: <one line>` with a body naming
<ID>, the SPEC sections touched and the probes answered. Never edit
WORKPLAN.md. Never edit a file under `fixtures/zoo/` (the record). If
completing the batch would require a model or schema change, a new NodeKind
or normalized key, a dialect read outside the adapters, or a rule the spec
does not already state — stop, write the options to OPEN_QUESTIONS.md under
a heading "<ID>: …",
commit that alone, and report `awaiting decision`. Report in ≤12 lines:
commit sha, files changed, tests added, mutation shown, make check result,
anything the orchestrator must know.
```

### 0.4 Recovery brief (dirty tree or interrupted batch)

```
The previous batch was interrupted. Read WORKPLAN.md §4. Run git status
and git diff --stat. If the in-progress work is complete enough to pass
`make check`, finish it under the batch brief rules and commit. Otherwise
`git stash` it with the message `wip <ID> <date>` and report what was
stashed and where it stopped. Leave the tree clean either way.
```

### 0.5 Context management (for the human)

- Builder: **clear context** before `Execute WORKPLAN.md run N` and before
  any `Resume WORKPLAN.md`. Continuity lives in this file and git, not in
  the session. The only time not to clear is when the builder has asked a
  question and is waiting for the answer.
- Aux: **always clear** before a review or a status check. Every aux task
  is stateless.
- A prompt that starts a run names `run N` within its first 100 characters,
  so the watcher's transcript derivation can see it. Decisions files are
  copied to `patches/` by the relay before the builder is prompted.

### 0.6 Standing rules (from CLAUDE.md, repeated because load-bearing)

No semantics in `spanweave/`. Nothing dropped silently. Never infer a
relation the telemetry did not state. No `hash()`, clocks, randomness,
input-order dependence. Adapters, not model changes — a model change is a
halt point, not a batch; a NodeKind is a closed enum (§3.2) and a normalized
attribute key is a schema change (§3.2, `reported_kind` is the only one).
`spanweave/` imports no consumer and no receiver.

The zoo's captures are the record and are never edited here: `fixtures/zoo/`
is a copy, pinned to `SigorMatt/spanweave-zoo` at `7eb5b69`, and a test
re-derives each file's sha256 against the zoo's sealed manifests. A number in
a document is a promise or a citation, and a citation needs a test that
re-derives it (the live-graphs series' lesson).

TASKS.md is the item registry (one line per batch, written at series
close); ROADMAP.md is untouched unless a batch says otherwise; this file is
execution state only and is deleted at series close with §3 folded into
TASKS.md.

### 0.7 Watch (aux, read-only, report-then-stop)

While the builder is on a run, aux may run `~/spanweave-ops/watch_monitor.sh`
with `--base` set to the run's plan commit; it derives the branch and the
builder PIDs itself. Triggers and tripwires are as `~/spanweave-ops/WATCH.md`
states; the series-close commit that deletes this file is the one plan
commit that cannot say `plan:`, and the watcher exempts it once per series.

---

## 1. Batch list

| ID | Batch | Status | Calls |
|---|---|---|---|
| T0 | **The zoo's captures are a fixture, and the audit's census is a gate.** `fixtures/zoo/<project>/<run-id>/NNNN.json`: the twelve captures' `json/` bodies copied byte for byte from `SigorMatt/spanweave-zoo` at `7eb5b69` (29 bodies; corrected from 24 at T0), with `fixtures/zoo/README.md` naming the pin, each capture's `MANIFEST.json` seal and the brief it came from, and a test re-deriving every file's sha256 against the zoo's manifests (the manifests copied beside them). `tests/zoo_census.py`: for each capture, `read_records` over its bodies in body order, `build` and the incremental `Builder` fed record by record (exporter order — child before parent, S15), asserting batch == incremental byte for byte, and the node, `parent`-edge, `temporal`-edge, `orphan_parent`, `unpaired_call`, `unknown` and `timestamp_unit_suspect` counts the audit reports give (`PROBES.md` "The captures" and S2–S22; the twelve `audit/*.md` at `7eb5b69`). Every number cites its report. A later batch that changes a count updates the census in its own commit with the reason — the census is the series' instrument, not its verdict. `make conformance` runs it. | done (162f1b6) | 6 |
| T1 | **The OTLP envelope is public, and an unclaimed record is keyed and placed by it.** S1, S2, S12; the receiver's L2. `OPEN_QUESTIONS.md` §20, option 1. (1) `spanweave.envelope(record) -> Envelope(trace_id, span_id, parent_id, name, started_at, ended_at, status, status_note)`, typed, over a record the reader unpacked from an OTLP export (the reader marks it), raising `EnvelopeError` on any other record or a missing key. (2) An unclaimed OTLP record's `unknown` node takes its id, parent, trace, name, times and status from its envelope (§3.6 rule 1 reworded "the record's envelope or its dialect"; §6.1's table row; §7; `seam.unclaimed_span` reversed); provenance names no adapter; `unclaimed_record` says no dialect read its attributes. Tests red on the parent on Z4's real capture (both bodies, five records): `envelope` on all five gives one trace id; `build` yields 5 nodes, **4 `parent` edges, 0 `orphan_parent`**, 1 `unclaimed_record`, 1 `unknown` named `concierge.conversation` with the root's times, `missing_timestamp` 0; a flat non-OTLP record with a `span_id` key still gets a derived `sw_` id and `envelope()` raises on it; the mixed-instrumentation scenario's `unknown` node (if any) unchanged. Incremental equals batch (§10.1). `orphan_parent`'s `source` keeps the absent parent's id (S12). Census updated with each moved count and its reason. | done (a1405be) | 6 |
| T2 | **A declared unit is not a suspicion.** S3. `startTimeUnixNano`/`endTimeUnixNano` declare their unit in their name; the reader carries that knowledge. Decision (§3): the reader converts a declared-nanosecond value to unix seconds (`int` nanoseconds → `float` seconds, the integer kept verbatim in `raw.source`, so nothing is lost and §3.1's "unix seconds" is true of the field), and `timestamp_unit_suspect` fires only on a value whose unit is **not** declared by its field — SPEC §3.1, §3.7 and §7 amended; the census drops 12 × "one per node" to 0 on every zoo capture, with the reason. Test red on the parent on Z1's capture: 31 suspicions → 0, every `started_at` in seconds, every `raw.source` still holding the nanosecond string; a hand-made record with a bare `start_time` of 1.7e18 still draws the diagnostic. Determinism unchanged (§5). | todo | 5 |
| T3 | **The envelope's own keys are not unmapped attributes, and a dropped count is a diagnostic.** S4, S7 (the four `<record>.*` keys on every node), S8, S10. `flags`, `kind`, `resource_spans` and `scope_spans` are the envelope, not span attributes (§7): they stay in `raw.source` and are **not** reported by `unmapped_attributes` per node — `kind` keeps its one sentence in §7 (no dialect reads a `SpanKind`), resource and scope are reported **once per graph** in `meta` (`resource`, `scope` as the record carries them, so a consumer can read the instrumentation scope — S6, S21). `droppedAttributesCount > 0` is a diagnostic, `attributes_dropped` (warning, `source: {"count": n}`): the export says attributes are missing and names none, which is a fact about the span, not an unmapped key. A model absent on a node that carries the count stays absent (S10; nothing is invented). Tests red on the parent on Z3's real capture: 102 `unmapped_attributes` diagnostics no longer name the four keys; 18 `attributes_dropped`; `meta.scope` names `openinference.instrumentation.openai-agents` and `.openai`. Census updated. | todo | 5 |
| T4 | **A span's events are reported, and an exception is an error the graph can see.** S11, S17. OTLP span events are envelope, not dialect; today they are one unmapped `<record>.events` key. Decision (§3): no schema change — events are reported through diagnostics: each `exception` event is an `exception_event` diagnostic (level `error`, `source: {type, message, escaped, time}`), and any other event is a `span_event` diagnostic (info, `source: {name, time}`); the events stay verbatim in `raw.source`; `<record>.events` is no longer an unmapped key. Tests red on the parent on Z5's real capture: two `exception_event` diagnostics naming `ConnectionError` and "(attempt 1)"/"(attempt 2)", on the two `error` tool nodes; on Z2's, two `span_event` named `First Token Stream Event`, each with a time after its node's `ended_at` kept as reported. §3.7's census gate updated. | todo | 5 |
| T5 | **Siblings are grouped by the parent the record states.** S18, L3. §4.3's "nodes with no parent are siblings at trace root" groups a root (no parent stated) with an orphan (a parent stated and absent), so a partial graph orders orphans whose stated parents differ and asserts an order the complete graph withdraws. Rule: the sibling group is the **stated** parent id — `None` for roots, the stated id for every other node, present or absent — so an orphan is ordered only against nodes stating the same parent, and an arriving parent changes no group. Prefix consistency improves (§10.1) and incremental stays equal to batch. SPEC §4.3 amended; a `temporal` edge between orphans of one stated parent keeps its basis. Tests red on the parent: Z2's first body alone (3 records: two stating the root, one stating `run_agent_step`) yields one `temporal` edge, not two; the full capture unchanged; the delta oracle and prefix-consistency gates green. Census updated where a count moves. | todo | 5 |
| T6 | **The adapters say what they do not map, and the three instrumentations are described.** S5, S6, S9, S14, S16, S17, S19, S20, S22. `ADAPTERS.md` gains, per adapter, the table of keys the zoo saw unmapped (S7's list) with each key's disposition — *reported, not mapped* with the reason, or *mapped at T3/T4* — and these readings, each cited to its probe: OpenInference's `PROMPT`, `RERANKER`, `GUARDRAIL`, `EVALUATOR` are `unknown` by design (§3.2; S14); two instrumentors on one client give two `llm` nodes nested (openai-agents + openai) or one (crewai + openai), and spanweave states no relation between them beyond the `parent` edge the records carry (S6, S17); the LangChain, LlamaIndex and CrewAI OpenInference instrumentors record no call id on a tool span, so `unpaired_call` is the correct rendering of every tool call they export and §4.4 forbids the pairing by name that would hide it (S9, S5); `graph.node.id`/`graph.node.parent_id` state a sequence, not containment, and are reported, not mapped (S19); an `llm` node carries no agent identity (S20). A test holds the documented key list equal to what the adapters leave unmapped on the zoo corpus after T3/T4 (a citation with its re-derivation). Docs and one test. | todo | 4 |
| T7 | **The series closes.** `TASKS.md`: registry T0–T7 with shas, §3 and §4 folded, every probe S1–S22 dispositioned (answered by which batch, or read as right with the reason); `reviews/` with every review byte for byte and sha256; CHANGELOG; `schema_version` unchanged (no field added); the zoo pin and the census recorded as the conformance corpus' third dialect having been **run** (Phase 4's gate, ROADMAP) — six agents, three instrumentations; WORKPLAN.md deleted; PR `stranger` → `main`, a merge commit. No `plan:` commit follows. | awaiting T6 | 5 |

## 2. Execution order

Run 1 = T0 → T1 → T2 → T3. Run 2 = T4 → T5 → T6 → T7, then the scoped review
of the close, Qodo's review of the PR, and the PR. Every batch: CI green on
the pushed tip before `done`. The branch is `stranger`, from `main` at
`fec7da2`.

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-10-14 | series | The zoo's twenty-two probes are answered one by one; "to establish" is answered by a reading recorded in `ADAPTERS.md` or `TASKS.md` when the rendering is right, and by a batch when it is not. Nothing is fixed by guessing: §4.4's no-pairing-by-name stands against S9's 48 `unpaired_call`, and §3.2's closed enum stands against S14's `PROMPT`. | maintainer |
| 2026-10-14 | T1 | The envelope is public because the OTLP envelope is not a dialect: trace id, span id and parent id are the transport's, and a consumer that routes by them is not interpreting telemetry. `classify` is unchanged; an unclaimed record is still an `unknown` node with `unclaimed_record` (§6.1). The receiver's half (routing every record it reads) is spanweave-live's series. | maintainer |
| 2026-10-14 | T2 | A unit declared by the field name is known, not suspected; converting a declared nanosecond integer to seconds loses nothing when the integer stays verbatim in `raw.source`, and leaves §3.1's "unix seconds" true. The diagnostic keeps its job for the undeclared case. | maintainer |
| 2026-10-14 | T3, T4 | No schema change this series (Phase 4's freeze precondition is a dialect *run*, which this series supplies; a field added now would move the thing being measured). Dropped counts and span events therefore go through diagnostics, the channel §3.7 already gives to "what the record says and the graph cannot hold"; `meta` gains `resource` and `scope` because §3.9 already carries per-graph facts and the scope is the one fact S6 and S21 turn on. | maintainer |
| 2026-10-14 | T5 | Grouping siblings by the stated parent is the reading of §4.3 that survives a partial input: an order between two nodes that state different parents was never something the telemetry stated. | maintainer |
| 2026-10-14 | T0 | The census asserts the audit's numbers at the start and is updated by each batch that moves one, with the reason in the commit — so the series' effect on a stranger's trace is a diff of one file, re-derived on every `make conformance`. | maintainer |
| 2026-10-14 | T1 | **Option 1, the whole envelope, OTLP-unpacked records only.** An unclaimed record that the reader unpacked from an OTLP export is an `unknown` node keyed by its envelope's `span_id` (§3.6 rule 1: "the record's envelope or its dialect supplies"), with its `parent_id` and `trace_id` as its relations and its `name`, `start_time`/`end_time` (under T2's unit rule) and `status` as the node's — the nine keys the reader already renamed are the transport's, and the one it does not read, `attributes`, is what `unclaimed_record` reports: no dialect read this span's attributes. Kind stays `unknown`, provenance names no adapter. (1a) The reader marks a record it unpacked (`RawRecord`/the record shape carries that fact); `envelope()` raises `EnvelopeError` on any other record — a key named `span_id` in a flat file is not an envelope. (1b) All of it, for the reason above: an `unknown` node is first-class (§3.2), and a first-class node has a name and a time. (1c) Every unclaimed OTLP node with a span id changes id; no conformance scenario renders one; the CHANGELOG says so; the census moves with every count explained (Z4: 4 `parent`, 0 `orphan_parent`, 0 `missing_timestamp`, `temporal` among the root's four children — the batch states what the build gives and why). `seam.unclaimed_span`'s docstring is reversed: reading the envelope is not deciding what a span looks like on behalf of an adapter; it is reading what the transport stated before any adapter was asked. | maintainer |
| 2026-10-14 | T0 | Confirmed: 29 files, not 24 (the row counted bodies and forgot the manifests and multi-body captures); the row correction stands. | maintainer |

## 4. Resume note

- 2026-10-14: series opened on `stranger` from `main` `fec7da2`, from the
  zoo's `PROBES.md` at `7eb5b69`. The receiver's series (L1–L4) follows this
  one, because L2 needs T1.

## 5. Origins

| ID | Origin |
|---|---|
| T0 | `PROBES.md` "The captures" and "Reproducing"; S15, S16, S21 (ordering holds, and must keep holding under every batch here). |
| T1 | S1, S2, S12; L2 (spanweave-live, enabled here). |
| T2 | S3. |
| T3 | S4, S7, S8, S10. |
| T4 | S11, S17. |
| T5 | S18, L3. |
| T6 | S5, S6, S9, S14, S16, S17, S19, S20, S22. |
| T7 | ROADMAP Phase 4, "the third dialect is a freeze precondition". |
- 2026-10-14 T0 (`162f1b6`): the zoo holds 29 bodies, not 24 (2+1+3+1+4+1+2+1+1+1+11+1, as
  `PROBES.md` and L1's "29 of 29"); row corrected. Census matches all twelve audits on all
  seven counts. Z4's audit graph is the receiver's 4-record feed; the census holds that, and
  the full 5-record capture is checked separately as the audit plus one `unknown`. **T1's
  premise:** on the parent, all five Z4 records give 0 `parent` and 4 `orphan_parent` — the
  unclaimed root's node id is `sw_…`, not its span id, so the children still find no parent.
  T1's 4-parent/0-orphan target appears to need a rule §6.1 does not state (an unclaimed
  node keyed by its envelope span id); T1's brief carries this. S12's `source` already
  carries the absent parent's id.
- 2026-10-14 T1 (`aff117e`): halted. No spec rule keys an unclaimed record by its envelope
  span id (§3.6 rule 1 needs a dialect; §6.1 gives an unclaimed record no relations;
  `seam.unclaimed_span` must not read the record). Options in `OPEN_QUESTIONS.md` §20:
  (1) key unclaimed nodes by envelope span/parent id (scope: OTLP-unpacked only or any
  record? id+parent only, or name/times/status too?); (2) land `envelope()` only, row
  acceptance becomes 0 `parent` / 4 `orphan_parent`, S12 answered by a reading; (3) as 2,
  id question to `DEBT.md`. T2 and T3 do not depend on T1, but §0.1 step 6 stops the run here.
- 2026-10-14: T1 decided (option 1, whole envelope, OTLP-unpacked only); the halt was right —
  §6.1's "carrying the record verbatim" had no identity and the series' own decision implied
  one. Run 1 resumes T1 → T2 → T3.
- 2026-10-14 T1 (`a1405be`, CI green): Z4's whole capture builds as the row says (5 nodes,
  4 `parent`, 0 `orphan_parent`, root `3013a003149d6951` named `concierge.conversation`).
  The row did not state `timestamp_unit_suspect` on that capture: it moves 4→5 (the root now
  carries its nanosecond times) and T2 must bring it to 0. Three choices beyond the row, for
  the maintainer to confirm: (a) an unpacked record and a flat record that parse equal are
  no longer duplicates (else the kept one, and so the node id, depends on line order; SPEC
  §7); (b) `envelope()` requires only `trace_id`/`span_id` — a missing name reads `""`,
  missing times `None` (proto3 JSON omits defaults), a wrongly typed field raises and the
  node falls back to the digest id — where the row said "raising on a missing key";
  (c) the §3.1 time reader moved from both adapters to `seam.stated_time`, unchanged.
