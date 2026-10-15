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

**A file format is not a dialect, so it is never an adapter.** JSONL, a JSON
array and an **OTLP JSON export** are containers, and `spanweave/read.py`
unpacks all three before an adapter sees anything (`SPEC.md` §7). Writing an
`otlp_json` adapter would look natural and would be wrong: the spans inside an
export are in whatever dialect their instrumentor speaks — possibly two
dialects in one export — so the adapter would have to answer the dialect
question for a whole file, one level below the place that can answer it per
record (`SPEC.md` §6.1, `OPEN_QUESTIONS.md` §16). If the input you want to
support differs from a supported one only in how the spans are *packed*, you
want a container, not an adapter, and that is a `SPEC.md` §7 conversation.

**The unpacking is reachable without a file, and it is still not an adapter.**
`spanweave.read_records(data)` reads bytes a caller already holds — an OTLP/HTTP
request body, a chunk tailed off an exporter — and hands back records and
diagnostics (`SPEC.md` §7, `OPEN_QUESTIONS.md` §19). It is the same reader, so
an export cannot read one way from a file and another way in flight; and it
consults no adapter, names no dialect, and classifies nothing. A live consumer
reads with it and then feeds a `Builder` (`SPEC.md` §10) — which is to say the
dialect question is still asked per record, one layer above this one.

## 2. The protocol

```python
class Adapter(Protocol):
    id: str          # stable, lowercase, no spaces: "openinference"
    version: str     # the adapter's version, independent of the library's

    def detect(self, sample: Sequence[JsonValue]) -> float: ...
    def parse(self, records: Iterable[JsonValue]) -> Iterator[NormalizedSpan]: ...
```

### `detect(sample) -> float`

Confidence in `[0.0, 1.0]` that this adapter handles the input. Called two ways
(`SPEC.md` §6.1): with **one record** at a time, to decide whose record it is,
and with up to the first 50 records you claimed, for the number the graph
records.

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
- **Must be decomposable over records.** A sample must reach `0.5` **iff at
  least one record in it reaches `0.5` on its own**. A per-record scan that
  returns as soon as it sees its marker — what both shipped adapters do — has
  this property already. What does not: a rule that wants to see three matching
  records before it commits, or one that reads a record's neighbours. Neither
  is a legal adapter, because a dialect is a property of a record and an
  adapter that needs context to answer cannot say which records are its own.
  This is a contract, not a new method: the library asks the question it always
  asked, one record at a time.

### `parse(records) -> Iterator[NormalizedSpan]`

**You are handed the records you claimed, and only those** — a subset of the
input, in input order, because a dialect is a property of a record rather than
of a file (`SPEC.md` §6.1). So number what you were *given*: `raw.line_number`
counts the sequence you received, and the library puts each span's number back
where its record sat in the whole input, so a diagnostic points a human at the
file they have. Never try to guess the input position yourself, and never read
anything into a gap in what you were handed — the records between yours belong
to another adapter, and they are not yours to interpret or to count.

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
  fall back to the record's canonical digest
  (`from spanweave.read import record_digest`), which is what both shipped
  adapters do. **Never the record's index.** A key derived from position binds
  the node id to where the record sat in the file, and shuffling the input MUST
  NOT change the graph (`SPEC.md` §3.6 rule 2, §5.2).
- `span_id` / `parent_id` / `trace_id` — verbatim from the dialect, or `None`.
  **Do not synthesize ids** — that is `spanweave/ids.py`'s job.
- `span_id` and `parent_id` have one shared rule, and it is not optional: fill
  them with `from spanweave.seam import span_ref, parent_ref`. A dialect
  spells "no id" two ways — the field absent, or the field present and
  **empty** — and an OTLP export writes the second as `parentSpanId` on every
  root it carries. Both must be `None`, or the builder reads an empty
  reference as a parent this input does not carry and reports every root as an
  orphan (`SPEC.md` §4.0). **`span_ref` is the same rule at the other end, and
  it is what makes that one sound:** an empty `span_id` states no id, so the
  record falls to §3.6 rule 2's content-derived key and no node is ever named
  `""` — which is the whole reason normalizing an empty reference away loses
  nothing. Use the shared helpers rather than your own check: two adapters
  disagreeing about one id is a cross-dialect equivalence failure, not a
  detail.
- **The same rule holds at the third reference field, a link's target.** Fill
  `links` from `from spanweave.seam import span_links`, which reads each
  entry's `span_id` with `link_ref` — the same rule again — and returns the
  links together with the `<record>.links[<i>]` keys of the entries that name
  no span. Add those keys to what you report as `unmapped_attributes`. An
  empty target is **no link**, exactly as an absent one is: transcribing it
  gives the builder an `explicit` `link` edge whose `dst` is `""`, a span no
  input can contain (`SPEC.md` §3.6; batch S3 left this field out, and batch
  S10 closed it). Unlike the other two it is *reported*, because a link entry
  that names nothing becomes nothing.

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
- `operation` — the tool or model name, when the dialect states one in a
  dedicated attribute. Never an agent's, a chain's or a retriever's own
  name: no dialect read today states a retriever's, and the one that states
  an agent's is declined rather than normalized (`SPEC.md` §3.1).

**Timestamps** — `started_at` / `ended_at`, unix seconds.
- Read them through `seam.record_time(record, field)`, never by hand. It
  applies §3.1's rendering rule and, for a record the reader unpacked from an
  OTLP export, the unit `startTimeUnixNano` declares: the value is converted
  to unix seconds and the string stays verbatim in `raw.source` (`SPEC.md`
  §3.1, *Declared nanoseconds*; batch T2). Never infer a unit, and never
  rescale a field that declares none, whatever the dialect calls it.
  A value too large to be seconds is the builder's business: it emits
  `timestamp_unit_suspect` and the number is kept untouched (`SPEC.md` §3.1).
  A conformant OTLP JSON export draws none — its fields declare their unit
  (`SPEC.md` §7; until T2 it drew one per span, `OPEN_QUESTIONS.md` §17).
- Read a JSON number, and a **string that is exactly a JSON number literal** —
  OTLP JSON encodes 64-bit integers as decimal strings. Read nothing else: not
  a trimmed string, not a leading `+`, not a date. The rule is one sentence,
  *the string, unquoted, would be a valid JSON number*, because every
  tolerated spelling beyond it is a small normalization.
- Carry an **integer** literal as an `int` and a fractional or exponent one as
  a `float` (`int | float | None`, `SPEC.md` §3.1). Never call `float()` on a
  timestamp: float64's spacing at epoch-nanosecond magnitude is 256 ns, so it
  would merge spans the record kept apart. The type follows the *literal*, so
  a quoted integer and a bare one land as one `int`.
- A value in a rendering you do not read must **not** become a silent `None`.
  Name the field in `unmapped` as `<record>.<field>`; the builder then adds
  `missing_timestamp` on its own. Two adapters ship with a `_timestamps()`
  helper doing exactly this — copy it rather than re-deriving it, and
  `tests/test_adapters.py` holds the rendering table both must answer alike.

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
  answered. One role per span, shared by all of its ids. `CallRole` is a
  `StrEnum` and the builder compares it **by value**, so the plain string
  `"fulfiller"` is read exactly as `CallRole.FULFILLER` is, on the batch path
  and the live one alike.
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

**You state relations. You do not emit edges, and you do not name a `basis`.**
The builder constructs every edge and supplies every `basis`, because `basis`
describes how an edge came to be and the builder is what brings edges into
being (`SPEC.md` §3.8). Nothing you fill in below is an edge.

- `links` — span links, when present, read with `span_links` (above) so an
  entry that names no span is no link and is reported. Leave
  `SpanLink.basis` as `None`: your
  dialect saying a link *exists* is not your dialect saying *why*, and the
  builder names the relation. Set it **only** if the dialect states the
  reason — a retry, a continuation, a fan-in — in which case the builder
  carries your string verbatim. No dialect observed so far does, so expect to
  leave it alone (`TASKS.md` I1).
- `received_call_ids` — when the dialect says this span was **given** the
  result of a call (a tool-result message, typically). You cannot name the
  producer from one span, and you should not try: record the id and let the
  builder resolve it (`SPEC.md` §4.2.1).
- Look for this before concluding your dialect declares no data relations. It
  is easy to miss, because it does not look like an edge — it looks like a
  message in a request. This corpus asserted for a whole phase that
  OpenInference declared nothing of the kind, while every multi-turn trace
  carried it.
- **There is no seam field for naming both ends of a data relation yourself,
  and its removal is the reason this section reads as it does.** A
  `DeclaredDataEdge` type once offered exactly that, with a `basis` you
  supplied. In four phases no adapter populated it; when the real declared
  relation was finally found it was a *message* saying "I received the result
  of call X", which one span cannot resolve. If your dialect appears to name
  both ends on one record, that is a finding worth raising rather than a gap
  to work around — stop and ask (`TASKS.md` I1).

**Losslessness**
- `unmapped` — the attribute **keys** you saw and did not normalize. Keys only;
  values are already in `raw` (`SPEC.md` §3.7).
- **Mark every key you read and acted on as consumed**, including one you read
  only to *decide* — a message's `role`, a part's `type`. It never becomes a
  field, but the decision is the mapping, and reporting it says you failed to
  understand a key you used. Mark it where you read it, and make sure that
  runs **before** `unmapped` is tallied. A key you read and could not use is
  the other case: leave that one reported — including a deciding key whose
  value you could not read at all, since a key that decided nothing was not
  acted on (`SPEC.md` §3.7).
- `raw` — the source record, verbatim and unmodified, plus its line number:
  1-based over the records you were handed, per §2.

## 4. Registering

Add to the registry in `spanweave/adapters/__init__.py`. Registration order must
not affect selection: ties are a hard error, not a first-wins race
(`SPEC.md` §6.1).

**`auto` is a reserved id.** `--adapter auto` is the default spelled out and is
resolved at the CLI before the registry is asked, so an adapter registering that
id would be unreachable through the flag that names it — silently, and only for
that one adapter. Pick a dialect name.

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
- [ ] `detect()` decomposable over records: a sample reaches `0.5` iff one
      record in it does alone (§2). Classification asks it one record at a time.
- [ ] `parse()` pure, lazy, non-raising, order-independent.
- [ ] All five payload states distinguished; absent ≠ empty.
- [ ] No inferred pairings, no inferred data edges, no invented ids.
- [ ] `unmapped` keys recorded; `raw` preserved verbatim — including a
      timestamp in a rendering §3.1 does not read, which is `<record>.<field>`
      and never a silent `None`.
- [ ] Timestamps read from a JSON number or a JSON-number string, and from
      nothing else, through `seam.record_time`; rescaled only where the
      field declares its unit (§3.1).
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

## 7. What the zoo saw unmapped, and how it reads

The zoo (`SigorMatt/spanweave-zoo` at `7eb5b69`, copied byte for byte into
`fixtures/zoo/`) is a real and a recorded capture of each of the agents Z1–Z6,
built by implementers who knew nothing about this library, under stock
instrumentation (§7.4 captures/the zoo, agents/the zoo). Its `PROBES.md` left questions *to
establish* about what the adapters map — S5, S6, S9, S14, S16, S17, S19, S20,
S22. This section answers them. Each answer is a reading: the rendering is
right, and why. None changes a rule.

**Every table and number below is re-derived.** `tests/test_zoo_readings.py`
parses §7.1, §7.2 and §7.4 and holds them equal to what the adapters report
over every record of every capture, each disposition in full. Every number
§7 states is a row of §7.4: the prose says "nested" and cites the row by
its number and where, `(§7.4 nested/Z2)`, and the test fails if a citation
names no row of the table or the prose states a number of its own. The per-capture counts
§7.4 shares with `tests/zoo_census.py` (`unknown`, `unpaired_call`,
`temporal`) are the census's too, which `make conformance` re-derives.

How to read the tables. A key's numeric indices are folded to `<n>`. *Projects*
names the zoo projects (Z1–Z6) on which some node reports the key. *Reported,
not mapped* means the key stays verbatim in `raw.source`, and the node's
`unmapped_attributes` diagnostic names it (`SPEC.md` §3.7). *Mapped at T3/T4*
means the audit saw the key unmapped, and since that batch no diagnostic names
it. Every such key is the OTLP envelope's, read in the seam (§7.4
envelope-keys/the zoo).

No field holds most of these keys, and that is the reason for most of the
dispositions. A node normalizes a model or tool name (`operation`), token
counts (`usage`), payloads and `reported_kind`, and nothing else. A further
normalized attribute key would be a schema change (`SPEC.md` §3.2). Rows below
that say *no field* mean exactly this.

### 7.1 `openinference`

Z1, Z2, Z3, Z5 and Z6: the LangChain, LlamaIndex, openai-agents, OpenAI-client
and CrewAI OpenInference instrumentors (`PROBES.md` S7).

| Key | Projects | Disposition |
|---|---|---|
| `<record>.flags` | Z1, Z2, Z3, Z5, Z6 | mapped at T3: the OTLP envelope, verbatim in `raw.source` (`SPEC.md` §7; S7) |
| `<record>.kind` | Z1, Z2, Z3, Z5, Z6 | mapped at T3: the OTLP envelope, verbatim in `raw.source` (`SPEC.md` §7; S7) |
| `<record>.resource_spans` | Z1, Z2, Z3, Z5, Z6 | mapped at T3: the envelope's resource level, read as `envelope(record).resource` (`SPEC.md` §7; S7) |
| `<record>.scope_spans` | Z1, Z2, Z3, Z5, Z6 | mapped at T3: the envelope's scope level, read as `envelope(record).scope` (`SPEC.md` §7; S7) |
| `<record>.droppedAttributesCount` | Z3 | mapped at T3: the `attributes_dropped` diagnostic (`SPEC.md` §3.7; S8) |
| `<record>.events` | Z2, Z5 | mapped at T4: one `exception_event` or `span_event` diagnostic per event (`SPEC.md` §3.7, §7; S11, S17) |
| `agent.name` | Z3 | reported, not mapped: an agent's name is declined from `operation` (`SPEC.md` §3.1). An `llm` node carries no agent identity (S20; §7.3) |
| `crew_agents` | Z6 | reported, not mapped: no field |
| `crew_id` | Z6 | reported, not mapped: no field |
| `crew_inputs` | Z6 | reported, not mapped: no field |
| `crew_key` | Z6 | reported, not mapped: no field |
| `crew_tasks` | Z6 | reported, not mapped: no field |
| `graph.node.id` | Z3, Z6 | reported, not mapped: it names the framework's node in a sequence, not a span. See `graph.node.parent_id` (S19) |
| `graph.node.parent_id` | Z6 | reported, not mapped: it names the previous agent in the crew's sequence, while the span's stated parent is the kickoff. It states a sequence, not containment. A `parent` edge is the span's stated parent (`SPEC.md` §4.0), and no `EdgeKind` holds a second structure, so the sequence appears only as §4.3's `temporal` order of the siblings (S19) |
| `llm.finish_reason` | Z1, Z2, Z3, Z6 | reported, not mapped: no field |
| `llm.input_messages.<n>.message.content` | Z1, Z2, Z3, Z6 | reported, not mapped: a message is payload content, not a node (`OPEN_QUESTIONS.md` §2). Payloads come from `input.value` / `output.value` (`SPEC.md` §3.3) |
| `llm.input_messages.<n>.message.contents.<n>.message_content.text` | Z2 | reported, not mapped: message content, as above |
| `llm.input_messages.<n>.message.contents.<n>.message_content.type` | Z2 | reported, not mapped: message content, as above |
| `llm.input_messages.<n>.message.name` | Z1, Z6 | reported, not mapped: message content, as above |
| `llm.input_messages.<n>.message.role` | Z1, Z2, Z3, Z6 | reported, not mapped: a role is read only to decide whether a `tool_call_id` beside it is a tool result (`SPEC.md` §4.2.1). With no such id beside it, it decided nothing (§3, *Losslessness*) |
| `llm.input_messages.<n>.message.tool_call_id` | Z3 | reported, not mapped: a tool-result id is read only when its message's `role` is `tool` (`SPEC.md` §4.2.1). The openai-agents instrumentor's message states no `role`, so nothing decided it |
| `llm.input_messages.<n>.message.tool_calls.<n>.tool_call.function.arguments` | Z1, Z2, Z3, Z6 | reported, not mapped: an echo of an earlier request in the resent history (`SPEC.md` §4.4) |
| `llm.input_messages.<n>.message.tool_calls.<n>.tool_call.function.name` | Z1, Z2, Z3, Z6 | reported, not mapped: an echo, as above |
| `llm.input_messages.<n>.message.tool_calls.<n>.tool_call.id` | Z1, Z2, Z3, Z6 | reported, not mapped: an echo of a reference is not the reference (`SPEC.md` §4.4) |
| `llm.invocation_parameters` | Z1, Z2, Z3, Z6 | reported, not mapped: no field |
| `llm.output_messages.<n>.message.content` | Z1, Z2, Z3, Z6 | reported, not mapped: message content, as above. The span's output payload is `output.value` |
| `llm.output_messages.<n>.message.contents.<n>.message_content.text` | Z2 | reported, not mapped: message content, as above |
| `llm.output_messages.<n>.message.contents.<n>.message_content.type` | Z2 | reported, not mapped: message content, as above |
| `llm.output_messages.<n>.message.role` | Z1, Z2, Z3, Z6 | reported, not mapped: message content, as above |
| `llm.output_messages.<n>.message.tool_calls.<n>.tool_call.function.arguments` | Z1, Z2, Z3, Z6 | reported, not mapped: the call's id is mapped (`call_ids`, requester, `SPEC.md` §4.4), and its function name is read into `unpaired_call`'s `source`. No field holds the arguments |
| `llm.prompt_template.template` | Z1 | reported, not mapped: no field. It is on Z1's `PROMPT` spans, which are `unknown` nodes (S14; §7.3) |
| `llm.prompt_template.variables` | Z1 | reported, not mapped: as above |
| `llm.provider` | Z1, Z2 | reported, not mapped: no field |
| `llm.system` | Z1, Z2, Z3, Z6 | reported, not mapped: no field |
| `llm.tools.<n>.tool.json_schema` | Z1, Z2, Z3, Z6 | reported, not mapped: no field |
| `metadata` | Z1, Z5 | reported, not mapped: no field |
| `task_id` | Z6 | reported, not mapped: no field |
| `task_key` | Z6 | reported, not mapped: no field |
| `tool.cache_function` | Z6 | reported, not mapped: no field |
| `tool.current_usage_count` | Z6 | reported, not mapped: no field |
| `tool.description` | Z1, Z2, Z3, Z5, Z6 | reported, not mapped: no field |
| `tool.description_updated` | Z6 | reported, not mapped: no field |
| `tool.parameters` | Z2, Z3, Z6 | reported, not mapped: no field |
| `tool.result_as_answer` | Z6 | reported, not mapped: no field |

### 7.2 `otel_genai`

Z4: the OpenTelemetry GenAI handler's `llm` spans (`PROBES.md` S4; §7.4 llm/Z4). Z4's
root span is claimed by no adapter. It reports `unclaimed_record` and never
`unmapped_attributes` (`SPEC.md` §6.1; S1), so it is in neither table.

| Key | Projects | Disposition |
|---|---|---|
| `<record>.flags` | Z4 | mapped at T3: the OTLP envelope, verbatim in `raw.source` (`SPEC.md` §7; S4) |
| `<record>.kind` | Z4 | mapped at T3: the OTLP envelope, verbatim in `raw.source` (`SPEC.md` §7; S4) |
| `<record>.resource_spans` | Z4 | mapped at T3: the envelope's resource level, read as `envelope(record).resource` (`SPEC.md` §7; S4) |
| `<record>.scope_spans` | Z4 | mapped at T3: the envelope's scope level, read as `envelope(record).scope` (`SPEC.md` §7; S4) |
| `gen_ai.provider.name` | Z4 | reported, not mapped: no field |
| `gen_ai.response.id` | Z4 | reported, not mapped: no field |
| `gen_ai.response.model` | Z4 | reported, not mapped: `operation` takes the model from `gen_ai.request.model` (`SPEC.md` §3.1). The response's model is a second statement, and no field holds it |
| `server.address` | Z4 | reported, not mapped: no field |
| `server.port` | Z4 | reported, not mapped: no field |

### 7.3 Readings

- **A node's instrumentation scope is read from its envelope, never from
  `meta`** (S6, S21). `envelope(node.raw.source).scope.get("scope")` gives the
  scope that wrote the span. Scope is per node, not per graph: Z3's graph holds
  `openinference.instrumentation.openai_agents` and
  `openinference.instrumentation.openai`. Z4's and Z6's graphs each hold more
  than one scope too (§7.4 scopes/Z4, scopes/Z6; `tests/zoo_census.py`,
  `Capture.scopes`). `Meta`
  carries no scope (batch T3, option 3).

  **The read works in process only.** It works on a graph `build` or a
  `Builder` returns, because `raw.source` there is the record the reader
  marked as unpacked (`SPEC.md` §7). After a JSON round trip, `raw.source` is a
  plain object, and the mark does not survive. A reader of the serialized
  graph instead takes the levels from `raw.source` verbatim:
  `raw.source["scope_spans"]["scope"]` and `raw.source["resource_spans"]`.
  These are the objects `Envelope.scope` and `Envelope.resource` were. The
  round trip itself is not part of `envelope()`'s contract.
- **Instrumentors stacked on one client** (S6). Z3 runs openai-agents and the
  OpenAI client together. Each model call there gives an `llm` node nested in
  another: an `openai_agents` `generation` is the parent of an `openai`
  `ChatCompletion` (§7.4 nested/Z3). Z6 runs CrewAI and the OpenAI client, and every
  `llm` node is the OpenAI client's (§7.4 nested/Z6). In neither
  case does spanweave state any relation between the nested nodes beyond the
  `parent` edge the records carry. It does not say "one call", because no
  record says so.
- **One instrumentor, an `llm` node nested in another** (S17). Z2's inner
  `astream_chat` is nested in an outer one (§7.4 nested/Z2) and is its only
  child (`tests/test_zoo_readings.py`), and parent and child come from one
  scope, `llama_index`. This is not S6's case of stacked
  instrumentors. The reading is the same: the `parent` edge the records state,
  and nothing more.
- **No tool span in the zoo records a call id** (S9, S5). The LangChain (Z1,
  Z5), LlamaIndex (Z2), openai-agents (Z3) and CrewAI (Z6) instrumentors write
  tool spans with no call-id key. Pairing is by call id and never by name or
  proximity (`SPEC.md` §4.4), so no zoo graph has a `call_result` edge. Every
  call an `llm` node requests is an `unpaired_call`, which is the correct
  rendering (§7.4 unpaired_call/Z1, unpaired_call/Z2, unpaired_call/Z3,
  unpaired_call/Z4, unpaired_call/Z6 real, unpaired_call/Z6 recorded;
  `tests/zoo_census.py`). Pairing by name
  would hide this. On Z6 it would also need a spelling `tool.name` does not
  share (`Delegate work to coworker` against `delegate_work_to_coworker`, S9).
- **Z4's `unpaired_call`** (S5). It does not follow from S1. The GenAI handler
  exports no tool span at all, so the `book_table` call an `llm` node requests
  (`tests/test_zoo_readings.py` pins which) is fulfilled by no span in the
  input. With the root span built (batch T1), the count is unchanged (§7.4
  unpaired_call/Z4; `tests/zoo_census.py`, `_Z4_WHOLE`).
- **`PROMPT`, `RERANKER`, `GUARDRAIL` and `EVALUATOR` are `unknown` by design**
  (S14). `NodeKind` is closed (`SPEC.md` §3.2). Each of these becomes an
  `unknown` node with an `unknown_span_kind` diagnostic, and the dialect's
  string is kept as `attributes.reported_kind`. Z1's `ChatPromptTemplate`
  nodes, each reporting `PROMPT`, are the zoo's case (§7.4 unknown/Z1;
  `tests/zoo_census.py`).
- **`graph.node.id` and `graph.node.parent_id` state a sequence, not
  containment** (S19). They are reported, not mapped (§7.1).
- **An `llm` node carries no agent identity** (S20). Its normalized attributes
  are its model or nothing (Z3's model-less steps, S10; §7.4 model-less/Z3;
  `tests/test_zoo.py`). An agent's name is never normalized (`SPEC.md` §3.1,
  `OPEN_QUESTIONS.md` §15). On Z6, a coworker's `ChatCompletion` differs from
  the delegator's in its `parent` edge to the delegation `tool` node, and in
  its messages, which sit verbatim in `raw.source`.
- **Z2's fan-out is ordered by start** (S16). This is right. Each `acall` tool
  node is the only child of its own `call_tool` chain, and §4.3 orders the
  `call_tool` siblings by `started_at`. That is an order and not a precedence:
  record order and end order are not used (§7.4 temporal/Z2;
  `tests/zoo_census.py`).
- **Z6's real and recorded captures are shapes of one crew** (S22). This is
  right. Each graph is what its run exported, and the census holds each
  (`tests/zoo_census.py`).

### 7.4 The numbers

Every number this section states, and where it holds. A project (Z3) means
every capture of it; a capture (Z6 real) is named where a project's captures
differ. Each row is re-derived from the zoo by `tests/test_zoo_readings.py`,
and a row added, dropped or changed fails there.

| Number | Where | Value |
|---|---|---|
| captures | the zoo | 12 |
| agents | the zoo | 6 |
| OTLP envelope keys mapped at T3/T4 | the zoo | 6 |
| `llm` nodes | Z4 | 4 |
| scopes | Z3 | 2 |
| scopes | Z4 | 2 |
| scopes | Z6 | 2 |
| `llm` nodes with an `llm` parent | Z2 | 2 |
| `llm` nodes with an `llm` parent | Z3 | 25 |
| `llm` nodes with an `llm` parent | Z6 | 0 |
| `unpaired_call` | Z1 | 1 |
| `unpaired_call` | Z2 | 3 |
| `unpaired_call` | Z3 | 48 |
| `unpaired_call` | Z4 | 1 |
| `unpaired_call` | Z6 real | 8 |
| `unpaired_call` | Z6 recorded | 4 |
| `unknown` nodes | Z1 | 2 |
| model-less `llm` nodes | Z3 | 9 |
| `temporal` edges | Z2 | 14 |
