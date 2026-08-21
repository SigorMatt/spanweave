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
  consumer relation. Comparing values to guess a flow is forbidden
  (`SPEC.md` §4.2).
- Every declared edge needs a `basis` naming the source field.

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

## 6. Checklist

- [ ] Single file under `spanweave/adapters/`; nothing else in the package touched.
- [ ] `detect()` pure, non-raising, keyed on distinctive markers, honestly scored.
- [ ] `parse()` pure, lazy, non-raising, order-independent.
- [ ] All five payload states distinguished; absent ≠ empty.
- [ ] No inferred pairings, no inferred data edges, no invented ids.
- [ ] `unmapped` keys recorded; `raw` preserved verbatim.
- [ ] Renderings derived from **observed instrumentor output**, not from a
      reading of the dialect's spec.
- [ ] Requester ids taken only from what a span itself produced — history
      echoes do not pair.
- [ ] All conformance scenarios rendered and passing against the **unmodified**
      expected graphs.
- [ ] One captured fixture with provenance.
- [ ] `make check` green — including the neutrality and layering gates.
