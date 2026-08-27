# ADAPTERS.md — writing an adapter

An adapter teaches `spanweave` one telemetry dialect. It is the **only** place
dialect knowledge is allowed to live, and adding one is the primary way to
contribute (`CONTRIBUTING.md`).

An adapter is a single file plus fixtures. If you find yourself needing to touch
anything outside `spanweave/adapters/`, **stop** — you have found either a model
gap or a design error, and both are conversations before they are patches
(`CLAUDE.md` 6).

## 1. What an adapter does

```
raw JSON records  ──▶  Iterator[NormalizedSpan]
```

That's it. Adapters do not build graphs, assign ids, create `temporal` edges,
sort anything, or know that a `Graph` type exists.

**Transcribe, don't interpret.** The adapter's job is translation between
vocabularies. Every time you are tempted to infer something the dialect didn't
say, the answer is a `Diagnostic` or a `None`.

## 2. The protocol

```python
class Adapter(Protocol):
    id: str          # stable, lowercase, no spaces: "openinference"
    version: str     # the adapter's version, independent of the library's

    def detect(self, sample: Sequence[JsonValue]) -> float: ...
    def parse(self, records: Iterable[JsonValue]) -> Iterator[NormalizedSpan]: ...
```

### `detect(sample) -> float`

Confidence in `[0.0, 1.0]` that this adapter handles the input. Called with up
to the first 50 records (`SPEC.md` §6.1).

It is a **declaration, not a measurement** — nothing in the trace computes it,
you are asserting it — and the graph records it under that name
(`meta.adapters[].declared_confidence`). Score it as something you will have to
defend to someone reading a graph that came out wrong.

- **Must be pure** and **must not raise** — wrap everything.
- Key on **distinctive marker keys**, not on generic ones. `openinference.span.kind`
  is distinctive; `name` and `start_time` are not.
- Be honest about partial matches. Return `0.9` when your marker is present,
  `0.3` when the shape is plausible but unmarked, `0.0` when it clearly isn't
  yours. **Do not return `1.0` defensively** — inflated confidence turns
  detection into a race, and a wrong adapter silently producing a plausible
  graph is far worse than an honest "ambiguous input" error.

### `parse(records) -> Iterator[NormalizedSpan]`

- **Pure.** No network, no filesystem, no clock, no randomness, no `eval`.
- **Never raises on malformed input.** Emit what you can and attach a
  diagnostic; skip only when there is genuinely nothing to emit, and say why.
- **Lazy.** Yield as you go; never materialize the whole input.
- **Order-independent.** Do not rely on record order for meaning. The builder
  sorts.

## 3. Filling `NormalizedSpan`

Field-by-field guidance. The type is defined in `SPEC.md` §6.

**Identity**
- `source_key` — a stable key within this input. Prefer the dialect's span id;
  fall back to the 1-based record index.
- `span_id` / `parent_id` / `trace_id` — verbatim from the dialect, or `None`.
  **Do not synthesize ids** — that is `spanweave/ids.py`'s job.

**Classification**
- `kind` — map to the closed `NodeKind` set (`SPEC.md` §3.2). If the dialect's
  kind doesn't map, emit `unknown` **and** an `unknown_span_kind` diagnostic
  carrying the original string. Never force a near-miss into a neighbouring kind;
  a wrong kind is worse than an honest `unknown`, because `unknown` is visible
  and a wrong kind isn't.
- **A value no instrumentor can emit is not a mapping candidate, however well
  it fits the vocabulary.** Map from what instrumentors **produce**, not from
  what the registry **defines**. The two are not the same set, and where they
  differ the registry is the larger one.

  The test is mechanical: ask what would have to run for a span carrying this
  value to exist. An instrumentor wraps **SDK calls**. If the thing the value
  names is not an SDK call — a workflow, a pipeline stage, a business step —
  then only an *application* can emit it, and every rendering you write for it
  will be derived from a span you wrote yourself. Not just today, while a
  capture is pending: **permanently, for the whole class.** At that point
  `capture/README.md`'s rule binds — *evidence about the outside world that you
  generated from your own idea of the outside world is not evidence* — and
  `unknown` + `reported_kind` is the honest answer. It is a first-class
  outcome, and a consumer that wants the value can read it off the node
  (`SPEC.md` §3.2).

  This is not a rule about difficulty or about waiting. A mapping whose
  evidence can never arrive is not deferred, it is unfounded, and the
  difference matters because the first looks temporary and the second is not.

  **The worked case is `otel_genai`'s `invoke_workflow`** (`TASKS.md` 2.16),
  and it is worth reading because the definitional argument for mapping it was
  *real*: `SPEC.md` §3.2 defines `chain` as "a composite step with no more
  specific kind", a workflow is a composite step, and `NodeKind` has nothing
  more specific. It lost to provenance, not to definition. Three conformance
  scenarios pay for that and are declared rather than rendered, and the record
  says so with the cost measured.

  **When it reopens:** a dialect whose *instrumentor* emits a genuine composite
  step. Then the evidence exists, and the question is a fresh one rather than a
  re-derivation.
- `name` — as reported. Do not prettify or rewrite.
- `operation` — the tool/model/retriever name when the dialect distinguishes it
  from `name`.

**Payloads** — the part most adapters get wrong.
- Distinguish all five states (`SPEC.md` §3.3). The distinction between
  **absent** (no attribute emitted) and **empty** (attribute emitted, no
  content) is load-bearing for every downstream consumer, and only you can
  observe it.
- Parse when the mime type says JSON; on failure keep `raw`, set `value=None`,
  emit `payload_parse_failed`.
- Preserve `raw` always.
- Mark `redacted` / `truncated` **only** when the source signals it. Never
  redact or truncate on your own.
- **A mime the dialect defines but does not emit.** Some dialects carry no
  content-type attribute at all, because their convention *defines* the
  structure of each attribute instead of restating it per span. You **may**
  report that mime and parse accordingly — it is transcribing a fact the
  dialect states about itself, the same class of act as mapping a span-kind
  enum onto a `NodeKind`, and not a guess about an individual span. Three
  conditions, all required:
  1. **The convention states the structure**, normatively, for that named
     attribute. A convention that says "any" does not qualify, and neither
     does "this instrumentor happens to emit JSON here."
  2. **A parse failure stays honest** — `state` remains `present`, `value` is
     `None`, `raw` is kept, and `payload_parse_failed` is emitted. If you are
     tempted to suppress that diagnostic, condition 1 was not met.
  3. **You say so where a reader of the *fixture* will find it**, not only in
     your adapter's docstring: the scenario's cross-dialect notes and, if the
     fixture declares payloads dialect-varying, the `reason` in its
     `expected/comparison.json` (`FIXTURES.md` §4.4). Someone comparing two
     renderings must be able to see why one of them has a mime its dialect
     never wrote, without reading the adapter to find out.

  The alternative — reporting `mime=None` and leaving `value` as the source
  string — is not the conservative choice it looks like. It makes a payload
  that agrees with another dialect **byte for byte** disagree at model level,
  and the corpus then records a serialization artifact as a finding about the
  model. That is the worse error, because it is the one that looks like
  evidence. `spanweave/adapters/otel_genai.py` is the worked example, and the
  measurement behind it is at `TASKS.md` 2.9.

**Usage** — token counts only; no prices, ever (`SPEC.md` §9).

**Call pairing** — the highest-value thing you can recover.
- `call_ids` — the dialect's `tool_call_id` / `function_call_id` / equivalent.
  A **tuple**: one span routinely requests several calls at once, and all of
  them belong in it. Deduplicate, and do not worry about order — the builder
  joins on the ids and sorts what it emits.
- `call_role` — `requester` on the span that asked, `fulfiller` on the span that
  answered. One role per span, shared by all of its ids.
- **Take a requester id only from what the span itself produced.** Nearly
  every chat protocol resends the conversation on each turn, so a later span
  carries the earlier turn's call id as *input context*. If you match the id
  wherever it appears, that span becomes a requester and the builder states a
  request-fulfilment relation nobody asserted. Find the part of the dialect
  that distinguishes what the model **said** from what it was **shown** — in
  OpenInference it is `llm.output_messages.*` versus `llm.input_messages.*` —
  and key on it. An echo of a reference is not the reference. Leave the echoed
  ids unmapped so they are reported rather than dropped.
- If the dialect doesn't carry ids, leave `call_ids` empty and `call_role`
  `None`. **Do not pair by name,
  proximity, or timing** — a guessed pairing is indistinguishable from a real
  one downstream, which is exactly the harm the warrant system exists to
  prevent.

**Explicit relations**
- `links` — span links, when present.
- `data_edges` — **only** when the dialect explicitly declares a producer→
  consumer relation, naming both ends. Comparing values to guess a flow is
  forbidden (`SPEC.md` §4.2).
- `received_call_ids` — when the dialect says this span was **given** the
  result of a call (a tool-result message, typically). You cannot name the
  producer from one span, and you should not try: record the id and let the
  builder resolve it (`SPEC.md` §4.2.1).
- Look for this before concluding your dialect declares no data relations. It
  is easy to miss, because it does not look like an edge — it looks like a
  message in a request. This corpus asserted for a whole phase that
  OpenInference declared nothing of the kind, while every multi-turn trace
  carried it.
- Every declared edge needs a `basis` naming the source field — and, where the
  library resolved a declaration from one granularity to another, saying so.

**Losslessness**
- `unmapped` — the attribute **keys** you saw and did not normalize. Keys only;
  values are already in `raw` (`SPEC.md` §3.7).
- `raw` — the source record, verbatim and unmodified, plus its line number.

## 4. Registering

Add to the registry in `spanweave/adapters/__init__.py`. Registration order must
not affect selection: ties are a hard error, not a first-wins race
(`SPEC.md` §6.1).

## 5. Fixtures — not optional

An adapter without fixtures is not mergeable.

1. Render **every** scenario in `fixtures/conformance/` in your dialect,
   including all the degenerate ones (`FIXTURES.md` §3).

   **Render from output you have observed, not from your reading of the
   dialect's spec.** Run the instrumentor, look at what comes out, and write
   that down. A rendering built from your understanding tests your
   understanding: your adapter will agree with it, every test will pass, and
   both will be wrong about the world in the same way. That is not
   hypothetical — it is how all four call-bearing fixtures in this corpus came
   to omit the conversation history that every real follow-up turn carries,
   and how a pairing defect survived a full test suite until the first
   captured trace (`FIXTURES.md` §5).
2. Your renderings must produce the **existing** `expected/graph.json`,
   unmodified. If they don't, the adapter is wrong — or the model is, and that
   is a discussion, not an edit to the expectation (`FIXTURES.md` §4).
3. Commit at least one **captured** trace from real instrumentation, with
   provenance (`FIXTURES.md` §6). Hand-authored fixtures prove you matched our
   understanding of the dialect; only a captured one proves you matched the
   instrumentor.
4. Add adapter-specific unit tests for quirks the shared corpus doesn't cover.
5. **Every scenario must be either rendered or declared.** Since `TASKS.md`
   2.13 the corpus names both shipped dialects in
   `tests/conformance.py:DIALECTS`, which turns on `FIXTURES.md` §4.3's
   *silence is a failure* rule: a scenario your dialect cannot express needs an
   `expected/coverage.json` entry with a reason, and a missing rendering that
   nobody declared fails the build. There is **no third state and no exemption
   list** — one existed between 2.7 and 2.13, held exactly one dialect, was
   guarded and temporary, and was deleted rather than emptied. A new adapter
   lands with its renderings, or it does not land.
6. **Declaring is not free, and it expires.** A `coverage.json` reason is an
   *invitation to check it against observed output*, not a settled fact — the
   seed corpus's only user of the mechanism turned out to be wrong about its
   own dialect (`FIXTURES.md` §4.3). Likewise a `comparison.json` declaration
   that no dialect actually disagrees about fails the corpus, per field and per
   entry. Both are recorded findings, not exemptions.

### What the second dialect cost, as a worked expectation

`otel_genai` renders 17 of 21 scenarios. Four are declared, and the pattern is
worth knowing before you start: **three of the four are one missing kind.**
Nothing in the GenAI operation vocabulary maps to `NodeKind.chain`, so every
scenario pinning a `chain` node is out — including the only one carrying an
`EdgeKind.link`, which was not the coverage anybody expected to lose.

The lesson for a third adapter: coverage is lost to **kind vocabulary**, not to
attribute shape. Payload spellings differ everywhere and are handled by
declaration; a kind your dialect cannot name takes whole scenarios with it, and
often not the ones the scenario was written for.

**With one correction, from `TASKS.md` 2.17.** Payload spellings are handled by
declaration only while the dialects disagree about a payload's *value* or
*mime*. A dialect that emits **no attribute at all** where another emits one
produces `absent` against `present`, and `FIXTURES.md` §4.4 forbids declaring a
payload's `state` away — so that is coverage lost to attribute shape after all.
`retriever_and_embedding` is the case: OTel GenAI has no content attribute for
an embedding span, and no capture can retire that, because it is a property of
the convention rather than a gap in an adapter.

So the sharper version: coverage is lost to **what a dialect cannot say** —
usually a kind, sometimes an attribute that does not exist. Both are declared;
neither is a payload spelling.

## 6. Checklist

- [ ] Single file under `spanweave/adapters/`; nothing else in the package touched.
- [ ] `detect()` pure, non-raising, keyed on distinctive markers, honestly scored.
- [ ] `parse()` pure, lazy, non-raising, order-independent.
- [ ] All five payload states distinguished; absent ≠ empty.
- [ ] No inferred pairings, no inferred data edges, no invented ids.
- [ ] `unmapped` keys recorded; `raw` preserved verbatim.
- [ ] Renderings derived from **observed instrumentor output**, not from a
      reading of the dialect's spec.
- [ ] No `NodeKind` mapped from a convention value **no instrumentor can
      emit** — map from what instrumentors produce, not from what the registry
      defines (§3, `kind`).
- [ ] Requester ids taken only from what a span itself produced — history
      echoes do not pair.
- [ ] All conformance scenarios rendered and passing against the **unmodified**
      expected graphs, or declared in `coverage.json` with a reason checked
      against observed output.
- [ ] Your dialect added to `tests/conformance.py:DIALECTS` in the same change
      as its renderings — that line is what makes coverage un-rottable.
- [ ] One captured fixture with provenance.
- [ ] `make check` green — including the neutrality and layering gates.
