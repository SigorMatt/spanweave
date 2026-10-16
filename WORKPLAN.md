# WORKPLAN.md — spanweave, the wire series

Status file for the series that lets the reader unpack the OTLP **protobuf**
wire format into the same records it unpacks from OTLP/JSON. It answers the
zoo's L1 (`PROBES.md` at `SigorMatt/spanweave-zoo` `7eb5b69`): every one of
the twelve captures' 29 exports was sent by the stock Python OTLP/HTTP
exporter as `application/x-protobuf`, and no consumer of this library can
read one without a Collector in between. The zoo sealed, for every export,
both the raw protobuf body and the Collector's JSON re-encoding of it — 29
pairs — and that is this series' oracle. One batch = one sub-agent = one
commit = one concern. This file plus git is the only state; any session can
resume cold from it.

Last updated: 2026-10-16 (series opened; run 1 not started.)

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
8. `git push origin wire`. A run is not finished until the push succeeds
   **and the GitHub checks on the pushed tip are green, or every failing
   check is explained in the run report**; local `make check` is not a
   substitute — the CI matrix runs interpreters the machine does not have.
   A series branch is never force-pushed. An amended batch is a new commit
   on top; the replaced sha is recorded in §4 with the reason.

### 0.2 Aux — cold reader

On the prompt `Review commits since <sha>`: for each code commit, in a
sub-agent per commit, check against `CONTRIBUTING.md` and `CLAUDE.md`: spec
changed in the same commit where behaviour changed; the new test fails on
the parent commit, where the parent is `<sha>^` **derived**, never a sha a
brief names (`plan:` commits interleave); a **mutation the new test catches**
is required for every code commit, and the reviewer tries two more plausible
mutations of any code the commit adds; worktrees are created by **absolute
path under the scratchpad**, never relative, never inside the repo; no clock
read, no randomness, no network in `spanweave/`; commit is one concern.
Write findings to `patches/REVIEW-<date>.md` (untracked) and print them.
**Aux never edits tracked files and never commits**: a finding that needs a
commit is made by the builder from the review file, never by the reviewer.

### 0.3 Batch brief (template the builder passes to a sub-agent)

```
You are executing batch <ID> of WORKPLAN.md in the spanweave repo.
Read, in this order: CLAUDE.md, the WORKPLAN.md row for <ID> and §5, then
the SPEC.md sections the row names, then only the source and test files
the batch touches. Rules: spec first (SPEC.md edited in this commit if
behaviour changes); write the failing test before the fix and confirm it
fails on the parent (`<sha>^`, in a worktree by absolute path under the
scratchpad); name one mutation the test catches and show it caught, and
try two more plausible mutations of any code you add; then implement; then
`make check`, `make conformance` and `make install-check`. Add a CHANGELOG
entry. Commit once: `<area>: <one line>` with a body naming <ID>, the SPEC
sections touched and the probes answered. Never edit WORKPLAN.md. Never
edit a zoo body or manifest under `fixtures/zoo/` (the record; its README
is ours). A number you state in a document is a citation with a test that
re-derives it, or it is not stated. If completing the batch would require
a model or schema change, a new NodeKind or normalized key, a dialect read
outside the adapters, a change to the graph a JSON export yields, or a
rule the spec does not already state — stop, write the options to
OPEN_QUESTIONS.md under a heading "<ID>: …", commit that alone, and report
`awaiting decision`. Report in ≤12 lines: commit sha, files changed, tests
added, mutations shown, make check result, anything the orchestrator must
know.
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
- A prompt that starts a run names `run N` within its first 100 characters.
  Decisions files are copied to `patches/` by the relay before the builder
  is prompted, and are cited in the record by their TASKS.md decisions-log
  row id (`decisions log D<n>`), never by file name.

### 0.6 Standing rules (from CLAUDE.md, repeated because load-bearing)

No semantics in `spanweave/`. Nothing dropped silently. Never infer a
relation the telemetry did not state. No `hash()`, clocks, randomness,
input-order dependence. Adapters, not model changes — a model change is a
halt point, not a batch; a NodeKind is a closed enum (§3.2) and a normalized
attribute key is a schema change. `spanweave/` imports no consumer and no
receiver. **No schema change this series**, in the words the stranger series
gave the shape gate: no field on any serialized model, no `PASSTHROUGH`
path, no key-tree move; the diagnostic code vocabulary may grow with the
artifact regenerated.

The zoo's captures are the record and are never edited here: `fixtures/zoo/`
is a copy pinned to `SigorMatt/spanweave-zoo` at `7eb5b69`, and a test
re-derives each file's sha256 against the zoo's sealed manifests and the
README's seals. **The protobuf path is held to the JSON path by the
oracle**: for every one of the 29 exports, the records the reader unpacks
from the raw body equal, as Python values and as `dumps` bytes of the built
graph, the records it unpacks from the Collector's JSON body. Where the two
disagree, the JSON path — the only one any graph has ever been built from —
is the reference, and the disagreement is a finding, never a special case.

TASKS.md is the item registry (one line per batch, written at series
close); ROADMAP.md is edited only where a row says (W2 strikes the Phase 4
line this series fulfils); this file is execution state only and is deleted
at series close with §3 and §4 folded into TASKS.md.

---

## 1. Batch list

| ID | Batch | Status | Calls |
|---|---|---|---|
| W0 | **The raw bodies join the record.** `fixtures/zoo/<project>/<run-id>/raw/NNNN.body`: the 29 protobuf bodies copied byte for byte from the zoo at `7eb5b69` (the manifests already seal them: each `bodies` entry with `content_type: application/x-protobuf`), `.gitattributes` marking them binary; `tests/test_zoo.py` re-derives each raw body's sha256 against its manifest entry as it does for the JSON bodies, and asserts the pairing: for every JSON body there is exactly one raw body in the same manifest, same ordinal (the zoo's `forwards` list says which raw body each JSON body came from — the test reads it, not the file name). `fixtures/zoo/README.md` gains the raw column and says the pairs are the wire series' oracle. No library change. Tests red on the parent: the raw files are absent. | todo | 3 |
| W1 | **The reader unpacks the OTLP protobuf wire format into the same records.** L1. One additive API in `spanweave/` behind an optional extra `spanweave[otlp]` that depends on `opentelemetry-proto` (and so `protobuf`): a function taking the bytes of an `ExportTraceServiceRequest` and yielding the same flat, reader-marked records that the OTLP/JSON path yields for the same export — the batch names the function and its module (one module, the only one that imports the proto package, listed in the gates' allowlist for that import), with SPEC §7 and ADAPTERS.md naming it beside the container rules. The mapping from proto to the JSON shape is the OTLP/JSON specification's, not `protojson`'s where they differ: trace and span ids as lowercase hex, 64-bit integers as decimal strings, enums as the Collector writes them, defaults omitted — **the oracle decides every such choice**, and the batch records in SPEC §7 each place the Collector's encoding differs from `MessageToDict` so the choice is stated, not discovered. Without the extra installed, the function raises a `SpanweaveError` whose code names the extra; the JSON path is untouched and `make check` without the extra stays green (the proto tests skip with the reason, and CI gains a job with the extra). Tests red on the parent on all 29 pairs: `read_records(raw) == read_records(json)` record by record, and `dumps(build(raw records)) == dumps(build(json records))` byte for byte; the census (`tests/zoo_census.py`) runs each capture from its raw bodies as well as its JSON bodies and holds every count equal; a hand-made request with two resource spans and two scopes unpacks in document order. Mutations: a hex id emitted as base64; a `UnixNano` emitted as a number; an omitted default emitted — each red by the oracle. | awaiting W0 | 6 |
| W2 | **The series closes.** TASKS.md: registry W0–W2 with shas, §3 and §4 folded, L1's spanweave half dispositioned (the receiver's half is spanweave-live's V1); `reviews/`; CHANGELOG; `schema_version` unchanged; ROADMAP.md's Phase 4 line "OTLP protobuf behind the `otlp` extra" marked done with the sha, and nothing else there touched; WORKPLAN.md deleted; PR `wire` → `main`, a merge commit. No `plan:` commit follows. | awaiting W1 | 4 |

## 2. Execution order

Run 1 = W0 → W1 → W2, then the aux cold review, the fix commits with their
own scoped review, Qodo's review (first fetch archived; post-push diff), and
the PR. Every batch: CI green on the pushed tip before `done`. The branch is
`wire`, from `main` at `88c7339`.

## 3. Decisions log

| Date | Batch | Decision | By |
|---|---|---|---|
| 2026-10-16 | series | The wire format is the reader's, not the receiver's: the stranger series decided the OTLP envelope is a container the reader owns (F1/F2, T1), and a second encoding of the same container is the same ownership; the receiver never reads a dialect, and a transcoder in the receiver would be a second reader of the envelope disagreeing subtly with the first. It is an optional extra because `protobuf` is a heavy dependency a JSON-only consumer should not pay for, and because the ROADMAP placed it there before this series existed. | maintainer |
| 2026-10-16 | W1 | The oracle is the rule. Twenty-nine exports exist in both encodings, sealed by the zoo; the JSON path has built every graph this library has ever produced; the protobuf path is correct exactly when it yields the same records, and any place the two could differ (id encoding, 64-bit integers, enums, omitted defaults, unknown fields) is decided by the pair, stated in SPEC §7, and pinned by a mutation. A protobuf-only behaviour with no JSON counterpart is a halt, not a choice. | maintainer |
| 2026-10-16 | W1 | No schema change: the records are the same records, so the graph, the shape artifact and `schema_version` cannot move; if the oracle shows they would, the batch halts. | maintainer |

## 4. Resume note

- 2026-10-16: series opened on `wire` from `main` `88c7339`, from the zoo's
  L1 at `7eb5b69`. The receiver's series (V0–V4) follows and pins to this
  series' merge.

## 5. Origins

| ID | Origin |
|---|---|
| W0 | `PROBES.md` L1 ("every body answered 415"; the manifests' `bodies` entries). |
| W1 | L1; spanweave `ROADMAP.md` Phase 4 ("raw OTLP JSON; OTLP protobuf behind the `otlp` extra"); `OPEN_QUESTIONS.md` §16 (F1/F2: a container, not a dialect). |
| W2 | Close. |
