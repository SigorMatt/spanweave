# Scoped cold review — the live-graphs close, `3ab6638..a0204a3`

Aux, 2026-10-03. Scope set by the §0.2 protocol now recorded in `TASKS.md`'s
live-graphs section; `WORKPLAN.md` is deleted at the tip, so the protocol was
read from `git show 3ab6638:WORKPLAN.md`.

Eleven commits in range: four code commits reviewed one sub-agent each — L23
`5803afb`, L24 `ed6d3f6`, L25 `effcafe`, L28 `a0204a3` — and a hygiene pass over
L26 `a82fd30`, L27 `8d04106` and the five `plan:` commits `b729bd0`, `c78b3cb`,
`32a37c7`, `01261f1`, `cebcd77`.

Every parent is **derived** as `<sha>^`, never a sha a brief names, because
`plan:` commits interleave with code commits:

| batch | commit | derived parent |
|---|---|---|
| L23 | `5803afb` | `3ab6638` |
| L24 | `ed6d3f6` | `b729bd0` *(a `plan:` commit — see below)* |
| L25 | `effcafe` | `c78b3cb` |
| L26 | `a82fd30` | `32a37c7` |
| L27 | `8d04106` | `01261f1` |
| L28 | `a0204a3` | `cebcd77` |

Per the protocol change carried out of run 4, each code commit was asked for **a
mutation at the tip that the new test catches**, not only a parent run — a
tests-only batch's derived parent is a `plan:` commit, which makes the parent run
vacuous. All worktrees were created by absolute path under the session scratchpad
and removed afterwards.

---

## Verdict

**READY, after the two commits this review required.**

The four code commits are individually sound: every new test fails on its derived
parent (or is disclosed as vacuous and substituted by a mutation), every required
mutant dies, no `hash()`/clock/randomness/network enters `spanweave/`,
`tests/serialized_shape.json` is untouched throughout, each commit is one
concern, and each carries a CHANGELOG entry. The close commit's record is true:
29 registry rows reconcile sha for sha against the branch, §3 of the deleted plan
is folded verbatim, the archive digest is exactly what `TASKS.md` publishes, and
A3 is discharged — `SPEC.md` no longer mentions `WORKPLAN.md` at all.

Two findings were binned **blocks PR**. Both are fixed:

| finding | fix |
|---|---|
| **L26-G1** — the declaration-ratio guard greps a fixed four-file list, so the eighth copy escapes as the seventh did | `b9324e1` |
| **L25-1** — L25's dedup test states, in its docstring, the premise that this very commit corrected and its own failure disproves | `ba8a6f0` |

Sixteen findings were binned **thread** and are registered in the PR comment
below. None of them is a correctness defect in shipped behaviour.

---

## Gates at the tip

Run at `ba8a6f0`, after both fixes:

```
make check          All checks passed!   3001 passed, 2 skipped;  82 gate checks
make install-check  33 checks passed against the installed wheel
make stranger       stranger path green: 1 walk(s), 5.27s best, 5.27s worst
```

At `a0204a3` itself the same three were green with 3000 passed, 2 skipped — the
two new tests are the one added case and the widened guard.

### CI conclusion for `a0204a3`

Run `37000347581` — <https://github.com/SigorMatt/spanweave/actions/runs/37000347581>
— workflow **CI**, head sha `a0204a30c02df03054c1cd8e666724cef4907510`,
status `completed`, conclusion **success**. Every job:

| job | conclusion |
|---|---|
| `check (3.11)` | success |
| `check (3.12)` | success |
| `check (3.13)` | success |
| `check (3.14)` | success |
| `determinism (ubuntu-latest)` | success |
| `determinism (macos-latest)` | success |

Six of six. `make check` and `make install-check` both run in CI on every push;
the local run is not a substitute, because the matrix runs interpreters this
machine does not have.

---

## L23 `5803afb` — a refused record leaves no memo behind

**Sound. No blockers, three threads.**

No `SPEC.md` change, and correctly so: §10.5's promise — "the builder is left as
it was: the next `feed` and every later `graph()` and `delta()` answer exactly as
they would have had the record never arrived" — is already at
`3ab6638:SPEC.md:2214`. Behaviour moved *to* the spec, not away from it.

**Parent run.** In a worktree at `3ab6638` with the tip's `tests/test_live.py`
copied in, two of the six new cases fail, exactly as the body claims:
`E At index 1 diff: 'unclaimed_record' != 'missing_trace_id'` at
`tests/test_live.py:812`, and
`E AssertionError: a refusal on an empty builder moved ['_absorber._whole_input_from']`
at `:897`.

**Mutations at the tip.** Deleting `spanweave/incremental.py:247`
(`self._whole_input_from = self._whole_input_before`) kills the same two.
Neutering the `begin()` snapshot at `:197` kills four *other* shapes — so both
new lines are independently covered.

### (1) The review's reproduction is the test, and `_whole_input_from` is in the probe

**It is the same reproduction, slightly stronger.** The review's A4 drove
`feed` → `DuplicateNodeIdError` → `feed({"not":"any dialect"})` → `feed(ts("q"))`
and compared `graph().diagnostics` against `delta(0).diagnostics_opened`. The
test (`tests/test_live.py:777-813`) drives the same `feed` calls through the same
`two_span` adapter installed via public `register` (`:571`), and adds two
assertions the review did not make: whole `Diagnostic` values rather than codes,
and `dumps(builder.graph()) == dumps(graph_from_records([...]))`.

**The probe is a walk, not a list.** `_whole_input_from` is named explicitly at
`:891`, so it cannot quietly fall out of the comparison; but `builder_state`
(`:846-870`) recurses `vars()` through spanweave-typed objects and deep-copies
every leaf — 59 paths found, 57 compared after two exclusions. Proven general:
adding a `self._future_attr` to `SpanAbsorber.__init__`, incremented in `begin()`
and restored nowhere, fails the probe on all five shapes with
`a refusal on an empty builder moved ['_absorber._future_attr']`, with no test
edit. **A future attribute is caught automatically.** The only escape is adding
a name to `ARRIVAL_SCOPED` by hand — loud, not silent (thread 2).

---

## L24 `ed6d3f6` — a basis rewrite names every pair it moved

**Sound. No blockers, four threads.**

Tests-only: `git diff --stat b729bd0 ed6d3f6 -- spanweave/` is empty. `SPEC.md`
unchanged, and `SPEC.md:2287-2292` already carries the per-edge promise the body
leans on.

**Parent run is vacuous, and says so.** The derived parent `b729bd0` is a `plan:`
commit, so in a worktree there with the tip's test file copied in: `80 passed`,
the two named pins `2 passed`. The commit discloses this verbatim ("vacuous by
construction") and substitutes the mutation. This is precisely the case the run-4
protocol change anticipated, and it is already registered as `TASKS.md:13497`
thread 18.

**The required mutant dies.** At the tip, `spanweave/incremental.py:625`
`removed.extend(stale)` → `removed.extend(stale[:1])` gives
**1 failed, 2999 passed, 2 skipped**, the sole failure being
`test_a_basis_rewrite_names_every_pair_it_moved_and_not_just_the_first` at
`tests/test_live.py:1266`:

```
E  AssertionError: assert [('s1','s4',...)] == [('s1','s4',...)]
E    Right contains one more item: ('s2', 's4', 'tool_call_id in tool-result message',
E      'tool_call_id in tool-result message (not the earliest receiving span)')
```

The pre-existing pin `test_a_basis_rewrite_is_one_edge_out_one_in_and_named_as_a_pair`
survives, exactly as the body and `reviews/2026-10-02-live-run4.md:437` claim.
(The body cites `:619`; `a0204a3` moved the line six down. Not a defect.)

### (2) The declined scenario's reason is **true** — and the renderability claim is **false**

The reason recorded in `c78b3cb` is a **scope** reason, and it holds. The
renderability escape the row offered — *neither dialect can render an
out-of-order basis rewrite* — is false, and the commit already says so rather
than leaning on it.

Hand-authoring the exact shape (two fulfillers of `call_a`, receivers in reverse
start-time order) in **both** dialects and running it through `build()` and
`Builder.feed`/`delta(since=3)` produced identical data edges and identical
two-pair rewrites on both paths: `s1→s3`, `s2→s3` plain basis; `s1→s4`, `s2→s4`
"(not the earliest receiving span)"; `basis_rewritten = [(s1,s4), (s2,s4)]`.

- **openinference** renders it: `tool_call.id` on a TOOL span
  (`spanweave/adapters/openinference.py:84,511,537`), receipt via
  `llm.input_messages.N.message.tool_call_id` (`:107,613`) — and it is *already*
  rendered at `fixtures/conformance/receipt_redeclared/dialects/openinference.jsonl`,
  where s3 and s5 both receive `call_a`.
- **otel_genai** renders it: `gen_ai.tool.call.id` on `execute_tool`
  (`spanweave/adapters/otel_genai.py:167,645,668`), receipt via a
  `tool_call_response` part (`:206,695`; `:30` states §4.2.1 outright).

The **stated** blocker is true independently: staging a new
`fixtures/conformance/` scenario in a tip worktree failed **six** doc-truth
tests, including `test_the_cited_corpus_figures_are_the_tracked_census`, with
`TASKS.md`, `ROADMAP.md`, `OPEN_QUESTIONS.md` and `CHANGELOG.md` all stating
`56, 159` against a census of `58, 167`. That is the figures change L24 declined,
and declining it on scope was right.

---

## L25 `effcafe` — a call role is read by value

**Sound; one blocker (now fixed), two threads.**

**Parent run.** All three new tests fail on the derived parent `c78b3cb`:
`AssertionError: version 1 is not build(records[:1])`, and live `unpaired_call`
against batch `unpaired_result` for `role="neither"`.

**Mutations at the tip.** Restoring the identity comparison
(`side = requesters if span.call_role is CallRole.REQUESTER else fulfillers`,
plus `fulfils = span.call_role is CallRole.FULFILLER`) fails the plain-`str` and
the `neither` tests; reverting `incremental.py` alone fails the plain-`str` test;
`sorted(set(span.call_ids))` → `span.call_ids` in `build.py` fails the
twice-named test. `grep 'is CallRole'` under `spanweave/` returns nothing at the
tip.

**Determinism and neutrality hold.** `_call_sides`' dicts are consumed through
`sorted(set(requesters) | set(fulfillers))` (`build.py:800`) and
`sorted(requesters)` (`:754`), so the added in-span sort changes no iteration
order — only the dedup. `CallRole` stays a pairing label; no interpretation is
added.

### (3) What was wrong in the thread, and whether a plain string still diverges

**The thread is run-4 §D thread 4**, "A new live/batch divergence introduced by a
cost commit" (`reviews/2026-10-02-live-run4.md:497-501`). Thread 3 — the
`StrEnum`-with-`is` one — was correct and needed no correction.

**What was wrong:** thread 4 called the dedup asymmetry "harmless today only
because `build.deduplicated` collapses identical edges." That is false.
Diagnostics are not deduplicated, so the two `unpaired_call`s are emitted per
named node and survive — §10.1 was already broken on a second, *observable*
axis. Reproduced here at `c78b3cb`: `diagnostic_count=3` in batch against `2`
live, differing on `diagnostics` **and** `meta`, failing `replay`'s
`live == batch` at version 1.

**Where it is recorded:** not only in a commit body —
`reviews/2026-10-02-live-run4.md` carries it as numbered correction 5 above the
threads, thread 4's own entry says "with its premise corrected: see correction 5
above", and `TASKS.md:13324` repeats it in the L25 registry row with these
numbers. The one place the stale premise still read as true was the test
docstring, which is finding L25-1 and is now fixed in `ba8a6f0`.

**Does the fix close the divergence through a plain string?** **Yes**, in both
directions and for strings equal to neither member. Run in a tip worktree with a
test-local adapter through public `register`, comparing live against batch as a
value *and* as bytes at every prefix:

```
plain str "requester"/"fulfiller"  agree-at-every-prefix=True  live call_result=[('ask','answer')]  diags live=[] batch=[]
plain str, fulfiller arrives 1st   agree-at-every-prefix=True  live call_result=[('ask','answer')]  diags live=[] batch=[]
str "FULFILLER" (wrong case)       agree-at-every-prefix=True  live call_result=[]  diags live/batch=['unpaired_call','unpaired_call']
str " fulfiller" (whitespace)      agree-at-every-prefix=True  live call_result=[]  diags live/batch=['unpaired_call','unpaired_call']
str "neither"                      agree-at-every-prefix=True  live call_result=[]  diags live/batch=['unpaired_call']
plain str + id named twice         agree-at-every-prefix=True  live call_result=[('ask','answer')]  diags live=[] batch=[]
(shuffled-input identical=True in every case)          ALL CASES AGREE: True
```

The pairing a bare `"fulfiller"` gets is the one the dialect stated. The residue
is thread L25-3: agreement is bought by a silent fall-through, not by a
diagnostic.

---

## L26 `a82fd30` / L27 `8d04106` — the hygiene pass

The five `plan:` commits — `b729bd0`, `c78b3cb`, `32a37c7`, `01261f1`,
`cebcd77` — each touch `WORKPLAN.md` and nothing else. No exceptions.

### (4) The seven copies and the 36 names — found by a check that finds the next one?

**L27: yes, genuinely derived.** `tests/test_doc_truth.py:644-654` reads
`public = list(spanweave.__all__)` with **no exemption list**, matching
word-bounded inside README code spans. Proven: adding `"dummy_public_export"` to
`__all__` in a tip worktree fails with
`AssertionError: 1 name(s) on the public API are nowhere in README.md: ['dummy_public_export']`
(`:669`). The 37th export fails until README covers it. A companion plant test
asserts both directions. No findings against L27.

**L26: no — and that was finding L26-G1, now fixed.** The guard greps strings the
files genuinely carry, so it does *not* repeat C4's defect: `7.1×` + `declar`
matches in all four listed files, and the faster-sort addition
(`tests/test_doc_truth.py:3247`) greps a phrase `SPEC.md` really carried at
`0718ba8`, correctly closing C4. But the **site list** bounded it. Appending A1's
sentence verbatim to `DESIGN.md` and `README.md` left
`tests/test_doc_truth.py`, `tests/test_docs.py`,
`tests/test_readme_quickstart.py` (77 passed) and `tests/test_gates.py` (47
passed) all green — nothing fired. So L26 fixed the wrong-*string* defect and
reproduced the wrong-*scope* one. `b9324e1` sweeps `git ls-files` instead, with
two written exemptions (`reviews/`, because its `sha256` is published and the
archive must be allowed to say the wrong thing it said; and the guard file
itself, which must quote what it forbids), and the same plant now fails naming
the path.

On the word itself: "floor" survives at only five sites tied to the ratio
(CHANGELOG ×3, TASKS ×2, `tests/live_cost.py` ×1), every one a retraction citing
A1. `SPEC.md` §10.6 has none. The 7.1× claim is stated as a ceiling with equality
only at `F = 0` in all four files.

### (4b) Does every number in §10.6 still carry its provenance?

One blanket citation covers the table — `SPEC.md:2395`: "Measured at `0718ba8` on
2026-10-02, CPython 3.14.6, by `tests/live_cost.py` (`make bench`) … whose header
holds the full table." **No bare machine ratio is left uncited**, and no citation
points at anything removed.

| number | provenance | resolves? |
|---|---|---|
| 0.1139 / 0.1136 ms/rec (wide, 1k/8k) | harness header + `measure()` | yes |
| 39,999 / 81,799 `Edge` objects, 1.000 | `--count-edges`; re-run gave `81799`, `1.000 x` | yes |
| zero canonical sorts | `--smoke` asserts it; run printed `0` | yes |
| 1.2009 ms/rec (echo total) | header table | yes |
| 0.3784 / 0.8133 / 1.5593 / 2.0567 | `--segments`; re-run 0.3876/0.8280/1.6565/2.3296 (run spread) | yes |
| 4,950 / **201** and 34,950 / **200** | `_per_segment` prints both; re-run matched | yes |
| 24.6 / 174.8 per record | printed as `24.627/record`, `174.750/record` | yes |
| **7.1×** | printed, with "bounds the first from above, with equality only at zero fixed per-record cost" | yes |
| **5.43×** | printed as `last segment / first segment` (re-run 6.01× — dated figure, not drift) | yes |
| `c ≈ 11 µs`, `F ≈ 0.10 ms`, "30× cheaper" | **prose arithmetic only** | arithmetic correct, uncomputed → thread L26-N1 |
| 249.9 / 18.0 and 298.7 / 86.9 (`graph()`) | header; `measure()` times the sort in place | yes |
| 245.8 → 161.5 / 44.3 / 18.5 / 18.7 | header; four parts timed one at a time | yes |
| 293.2 → 77.8 / 26.1 / 91.2 / 82.5, vs 0.1198 | header, taken with `--only` per `test_bench_runs_the_two_shapes_in_separate_processes` | yes |
| 235.9 / 220.7 / 19.9 (root-last) | `--root-last` | yes |

The three derived constants were checked by hand and are correct
(c = 1.6783/150.123 = 11.18 µs; F = 0.3784 − 24.627c = 0.1031 ms;
c′ = 0.5F/137.81 = 0.374 µs → 29.9×) — but nothing recomputes them, which is the
exact failure shape this file exists for. Every other §10.6 figure was
cross-checked against the harness header: present verbatim, no drift at the tip.
The one genuinely different quantity in the tree is CHANGELOG's L17 entry (5.44×,
2.0393/0.3746), explicitly labelled as the older measurement and not restated in
SPEC.

---

## L28 `a0204a3` — the series close

**Sound. No blockers, three threads.** Six checks, all PASS.

**1. Registry L0–L28 reconciles sha for sha.** 29 rows at `TASKS.md:12849-12865`,
27 distinct shas cited. Branch `40bce13..a0204a3` is **54 commits = 25 non-plan +
29 `plan:`**. Every one of the 25 non-plan commits is cited exactly once, and its
subject matches its row's description — **0 mismatches**. All 29 `plan:` commits
are correctly absent; no row cites one as its batch commit. The only uncited
non-plan commit is `a0204a3` itself, whose cell reads "the closing commit of the
series" — a self-reference, not an omission (thread T-C). Dropped and moved rows
say so: L5 is `dropped on measurement` (and cites `79a63f4` for what *did* land),
L7/L8 are `moved to SigorMatt/spanweave-live` with an em-dash commit cell.

**2. L16 and L17 discharge C6 and C7.** `TASKS.md:12853` (L16): its bound was
"**already cleared by L15**: wide n=2000 root-last/root-first is 2.48× pre-L15,
1.21× at L16's own parent and 1.05× here" — names L15 as the mover, gives all
three measurements. `:12854` (L17): the 1.5× criterion is "**unmet, and wrong as
written**", with the arithmetic and the ~11 µs/declaration reason at
`:12867-12874`. Both numbers are corroborated independently by the review itself
(`reviews/2026-10-02-live-run4.md:407`), not self-asserted.

**3. §3 of the deleted plan is folded in full.** `git show cebcd77:WORKPLAN.md` §3
and `git show 3ab6638:WORKPLAN.md` §3 are identical (16 table lines each). Against
`TASKS.md:12885-12904`: **15 data rows vs 15, all 15 byte-identical** including
the header. **0 dropped, 0 altered, 0 extra.** The two rows that mention
`WORKPLAN.md` are quoted un-re-pointed, which the preamble at `:12878-12884`
states deliberately.

**4. The archive digest is exactly what is published.**

```
27d7d4fb9a27cb0c00ee635afb7a6d5c20b9997759df29f8eebf13cd3610e549  reviews/2026-10-02-live-run4.md
27d7d4fb9a27cb0c00ee635afb7a6d5c20b9997759df29f8eebf13cd3610e549  patches/REVIEW-2026-10-02.md
```

`patches/REVIEW-2026-10-02.md` **is** present in the working tree; `cmp` is
silent. The tracked blob at `a0204a3` gives the same digest, so the string
`TASKS.md` publishes is of what is committed. `reviews/` holds 12 files, as the
body claims.

**5. Every A/C/thread is dispositioned; the thread count is 17.** A1–A4
(`:13261-13265`) and C1–C10 (`:13272-13283`) all have a non-blank disposition.
The review's §D (`reviews/2026-10-02-live-run4.md:486-563`) has **17 bullets**;
`TASKS.md` registers Thread 1…17 plus a Thread 18 opened by run 5. Matched
mechanically: each of the 17 maps 1:1, **in order**, at ratio **1.0000**
(whitespace-folded) — 17/17 verbatim, nothing unregistered. Spot-checks against
diffs found **no disposition false**: threads 3+4 → `effcafe` really converts
`is CallRole.X` → `== CallRole.X` on both sides and mirrors the dedup; threads
10+11 → `a82fd30` really splits `make bench` into two processes and adds
`_declared_receipts()`; C3/C4/C5 → `a82fd30` really removes "and has moved
since", the heap grep and the OQ recommendation; C8 → `8d04106` adds a 152-line
README API table plus the `__all__`-derived check.

**6. `WORKPLAN.md` is gone and A3 is discharged.**
`git ls-files --with-tree=a0204a3 WORKPLAN.md` → empty.
`git grep -c WORKPLAN a0204a3 -- SPEC.md` → **0** (the parent `cebcd77` had 3).
Also 0 in `README.md` (was 1), `Makefile` (was 2), `.gitignore` (was 1). Every
survivor is history: dated `CHANGELOG.md` entries, the verbatim `reviews/`
archives, `TASKS.md`'s quoted decision rows and `git show <sha>:WORKPLAN.md`
provenance pointers, two past-tense comments in `tests/test_doc_truth.py`, and 19
mentions in `OPEN_QUESTIONS.md` — all 19 inside §10–§17, the audit-era memos
governed by the explicit preamble at `:16-26`. **§18–§19, the live-graphs memos,
carry zero.** This is the fifth `WORKPLAN.md` deletion in repo history
(`fcc842d`, `b091904`, `67c7642`, `6eb1762`, `a0204a3`), as the body claims.

---

## Findings

### `blocks PR` — both fixed in this review

**L26-G1 — the declaration-ratio guard greps a fixed four-file list, so the
eighth copy escapes.** `tests/test_doc_truth.py:3270-3275`'s
`WHERE_THE_DECLARATION_RATIO_IS_CITED` bounded the check to the sites it already
knew. Appending A1's sentence to `DESIGN.md` and `README.md` left every doc-truth
and gate test green. Fixed in **`b9324e1`**: the sweep reads `git ls-files`, with
`reviews/` and the guard file itself exempt for written reasons, and the plant now
fails naming the path.

**L25-1 — the test docstring states the premise this commit corrected, and its own
failure disproves it.**
`test_one_span_naming_a_call_id_twice_is_read_the_same_way_live_and_in_batch`
said a divergence here "is invisible in the bytes today" — run-4 thread 4's
premise. On the real parent it fails on the bytes: `diagnostic_count=3` against
`2`, `unpaired_call` emitted twice for node `ask`. CHANGELOG,
`spanweave/build.py:647`, correction 5 and `TASKS.md:12862` all say the opposite,
so the one place a future reader met the claim was the one copy still false.
Fixed in **`ba8a6f0`**.

### `thread` — registered, no commit

**L23**

1. **The "after `Tally.rollback`" ordering the fix documents is not real.**
   `spanweave/incremental.py:234`, the commit body and the CHANGELOG all assert an
   ordering dependency. `Tally.rollback` (`spanweave/delta.py:310-317`) only
   restores its own `_groups`/`_now`; it cannot touch `_whole_input_from`.
   Swapping the two lines gives `3000 passed, 2 skipped`. The fix is right; the
   explanation of *why that position* is not.
2. **`ARRIVAL_SCOPED` is the probe's one hand-maintained surface.**
   `tests/test_live.py:826`. Two entries, each with a written reason. The escape
   it permits is deliberate — someone must add a name — not silent. Worth naming
   so a later batch does not grow it quietly.
3. **No conformance fixture, and the reason lives only in the review.**
   `CONTRIBUTING.md`'s bar asks for one. None is added, correctly: the defect
   needs a refusal followed by arrivals, which the dialect-rendering corpus
   cannot express. That reasoning is in the review, not in the commit or the
   CHANGELOG.

**L24**

4. **The parent run is vacuous, as the body says.** Disclosed verbatim and
   substituted by the mutation; already `TASKS.md:13497` thread 18 and protocol
   change 1, so nothing is hidden by the plan's deletion.
5. **Conformance gate 3 stays vacuous for the `stale[:1]` mutant.** The only
   death in the whole-suite run is in `tests/test_live.py`; no conformance test
   bites. Disclosed in the body, the CHANGELOG and thread 18.
6. **The body's origin citation is an untracked path.**
   `patches/REVIEW-2026-10-02.md` is `.gitignore`d (`.gitignore:43`). The tracked
   copy only becomes tracked at `a0204a3`, so the citation resolves at the PR tip
   but not at `ed6d3f6`. Content verified to match.
7. **The oracle is independent except for one field it is handed.**
   `delta == oracle_delta(built, 3, 4, delta.restated)` feeds `restated` from the
   object under test. `tests/delta_oracle.py:14-18` documents why two endpoint
   graphs cannot compute it. Noted, not a defect.

**L25**

8. **`SPEC.md` unchanged is right for the role half, wrong-by-silence for the
   dedup half.** §10.1 (`SPEC.md:2139`) pre-promises the role fix, so nothing was
   owed there. But the commit also changed observable *batch* output for a span
   naming one call id twice, and SPEC speaks only of edges ("Edges are unique on
   `(src, dst, kind, basis)`", `:853`) — never of a span's duplicate `call_ids`,
   never of one diagnostic per node per call id. The new rule lives in
   `build.py`'s docstring and the CHANGELOG only. "Read by value" likewise lives
   only in `ADAPTERS.md:253`, while `SPEC.md:1420` still presents `call_role` as
   the closed type.
9. **An unreadable role is silently read as "requester", with no diagnostic.**
   `"FULFILLER"` and `" fulfiller"` fall through to the requesting side on both
   paths: two `unpaired_call`s, nothing saying the role was unreadable. §10.1
   holds — that is the fix — but "degrade honestly" does not. The commit
   knowingly asserts no side.

**L26 / L27**

10. **Within a listed file the direction is asserted with `any()`.**
    `test_the_declaration_ratio_is_stated_as_a_bound_from_above` requires only
    that *some* matching paragraph says "from above"; a second paragraph stating
    7.1× with no direction passes. Already latent at
    `tests/live_cost.py:122-134`. Worse, `TASKS.md`'s decision table has no blank
    lines, so `split("\n\n")` reads the whole table as one paragraph containing
    both "from above" and "A1" — a false sentence added to a row there is guarded
    by nothing. (The new tree sweep inherits the same paragraph splitter, so this
    thread survives `b9324e1`.)
11. **`c ≈ 11 µs`, `F ≈ 0.10 ms` and "30× cheaper" are prose arithmetic with no
    harness.** `SPEC.md:2421-2427`. Correct, but the only §10.6 numbers nothing
    recomputes.
12. **§10.6 duplicates ~22 machine figures from the harness header, and only the
    provenance line is checked.** `test_spec_cost_numbers_cite_the_harness_that_took_them`
    compares the `Measured at <sha> on <date>, CPython <v>` triple, not the
    figures. A hand-edit to one copy drifts silently. No drift at the tip.
13. **The harness header's documented `ARGS` runs one shape twice.**
    `tests/live_cost.py:5-9` documents `ARGS="--only wide --root-last --wide 2000"`,
    but `Makefile:102-104` appends `$(ARGS)` to both lines, so the echo line
    becomes `--only echo --only wide` (argparse: last wins) and the wide shape
    runs twice. Same for `ARGS="--smoke"`.

**L28**

14. **L1/L2 cite a `plan:`-subject commit as their batch commit, and that commit
    is the series' only `plan:` commit that is not WORKPLAN-only.**
    `TASKS.md:12850-12851` cite `aac1915`, decided in `27ec3db`; both subjects
    start `plan:`. The citation is substantively right — `aac1915` is where the
    memos landed, adding `## 18. L1:` and `## 19. L2:` to `OPEN_QUESTIONS.md` —
    so the registry is not lying. But `aac1915` also touched `README.md` and
    `tests/test_doc_truth.py`, so the §0 rule the run-2/3/4 reviews each verified
    ("every `plan:` commit touches `WORKPLAN.md` and nothing else") does not hold
    for it, and no review covered it: run 1 had no cold review and run 2's range
    began at `27ec3db`. Register it so the next series' §0 says what a
    memo-opening commit may touch.
15. **C6's first half is not actually answered.** `TASKS.md:13278` says C6 is
    "satisfied by the registry above, whose L17 row records the criterion as
    unmet and why" — which answers the second clause only. A commit subject in
    history cannot be edited, so the registry *is* the only available remedy, but
    the cell does not say that, and a reader checking C6 against
    `git log -1 0718ba8` still finds the overstatement with no note beside it.
    One clause would close it.
16. **L28's own row is unresolvable to a sha from `TASKS.md` alone.**
    `TASKS.md:12865`'s commit cell reads "the closing commit of the series".
    Unavoidable in the commit that writes it, and `CHANGELOG.md:477` dates the
    close — but once this is on `main`, L28 is the one registry row a reader
    cannot `git show`. The PR body should name `a0204a3`.

---

## The PR comment

> **Scoped cold review of the live-graphs close, `3ab6638..a0204a3`** — four code
> commits one sub-agent each (L23 `5803afb`, L24 `ed6d3f6`, L25 `effcafe`, L28
> `a0204a3`), a hygiene pass over L26 `a82fd30`, L27 `8d04106` and the five
> `plan:` commits. Parents derived as `<sha>^`; each code commit asked for a
> mutation at the tip the new test catches, not only a parent run.
>
> **Verdict: READY**, after two commits this review required — `b9324e1`
> (L26's declaration-ratio guard greps a fixed four-file list, so the eighth copy
> escaped as the seventh did; the sweep now reads `git ls-files`) and `ba8a6f0`
> (L25's dedup test stated in its docstring the premise the commit corrected and
> its own failure disproves).
>
> The four code commits are individually sound: parent runs fail as claimed or
> are disclosed vacuous and substituted, every required mutant dies — including
> `stale[:1]`, which kills exactly one test — no `hash()`/clock/randomness/network
> enters `spanweave/`, `tests/serialized_shape.json` is untouched, each commit is
> one concern with a CHANGELOG entry. The close's record reconciles: 25 non-plan
> commits each cited exactly once across 29 registry rows with 0 mismatches, §3 of
> the deleted plan folded 15/15 byte-identical, the archive digest exactly
> `27d7d4fb…49` on both sides, 17/17 threads registered verbatim in order, and
> A3 discharged — `SPEC.md` no longer mentions `WORKPLAN.md` at all.
>
> Two corrections to the record worth carrying forward. L24's declined scenario is
> declined on **scope**, and that reason is true — but the renderability claim the
> row offered is **false**: both dialects render an out-of-order basis rewrite, and
> openinference already does at `fixtures/conformance/receipt_redeclared/`. And the
> live-vs-batch divergence through a plain-string role is **closed** in both
> directions and for strings equal to neither member, verified at every prefix as
> value and as bytes — bought, however, by a silent fall-through rather than a
> diagnostic (thread 9).
>
> Gates at the tip `ba8a6f0`: `make check` 3001 passed / 2 skipped / 82 gate
> checks; `make install-check` 33 checks against the installed wheel; `make
> stranger` green in 5.27s. CI on `a0204a3` is **success** on all six jobs
> (`check` 3.11–3.14, `determinism` on ubuntu and macos).
>
> **Sixteen threads registered, none a correctness defect in shipped behaviour.**
> The ones a maintainer should actually decide: the "after `Tally.rollback`"
> ordering L23 documents is not real, though the fix is right (1); `SPEC.md` is
> silent on the dedup half of L25 while `ADAPTERS.md` alone carries "read by
> value" (8); an unreadable role lands on the requesting side with no diagnostic,
> which satisfies §10.1 but not "degrade honestly" (9); the paragraph splitter
> reads `TASKS.md`'s whole decision table as one paragraph, so the new tree sweep
> guards nothing added to a row there (10); `c ≈ 11 µs`, `F ≈ 0.10 ms` and "30×
> cheaper" are the only §10.6 numbers nothing recomputes (11); `make bench ARGS=…`
> runs the wide shape twice (13); and `aac1915`, cited by L1/L2, is the series'
> one `plan:` commit that touches more than the plan — no review has ever covered
> it, so the next series' §0 should say what a memo-opening commit may touch (14).
