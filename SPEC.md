# SPEC.md — technical specification

Source of truth for behavior. Code conforms to this; when they disagree, fix one
of them deliberately (don't let them silently diverge). Companions: `CLAUDE.md`
(process + invariants), `DESIGN.md` (architecture), `ROADMAP.md` (sequencing),
`FIXTURES.md` (the conformance corpus), `ADAPTERS.md` (writing an adapter),
`GLOSSARY.md` (terms).

## 1. Goal and scope

Convert agentic-system execution telemetry into **one normalized, deterministic,
semantically neutral graph**, and expose a small query and annotation surface
over it.

The library commits only to **what the telemetry observed and how it was
established**. Every interpretation — roles, severity, cost, quality, data-flow
inference — belongs to the consumer. This is the line that makes one graph shape
serve uses it was not designed for (§9).

**In scope:** dialect normalization, node/edge construction, warranted edge
typing, losslessness and diagnostics, deterministic serialization, a query
surface, a consumer annotation API.

**Out of scope, permanently:** §9.

## 2. Pipeline

```
raw trace bytes
   │  Adapter (per dialect)            ← all format mess lives here
   ▼
NormalizedSpan[]                        ← the internal seam (§6)
   │  Builder (dialect-agnostic)        ← never learns a dialect name
   ▼
Graph  ( Node[], Edge[], Diagnostic[], Meta )
   │  Serializer (schema v1)
   ▼
graph.json   /   in-process Python object
```

Two stages, one process. The builder never sees a dialect name, an attribute
key, or a file format (`DESIGN.md` §3). The seam is serializable for debugging
but is **not** a public contract; the *graph* is.

## 3. Data model

All model types are **frozen dataclasses**. Nothing in the model is mutable.

### 3.1 Node

One node per observed operation.

```
Node:
  id:          NodeId          # stable, deterministic (§3.6)
  kind:        NodeKind        # §3.2
  name:        str             # operation name as reported
  operation:   str | None      # tool or model name, when stated (below)
  started_at:  int | float | None   # unix seconds as reported; None if the
  ended_at:    int | float | None   #   dialect omits it
  status:      Status          # ok | error | unset
  status_note: str | None      # error message as reported, verbatim
  inputs:      Payload         # §3.3 — never None; use Payload.absent()
  outputs:     Payload         # §3.3
  usage:       Usage | None    # §3.4 — counts only, never money
  attributes:  Mapping[str, JsonValue]   # normalized, typed subset
  raw:         RawRecord       # §3.5 — verbatim source (losslessness)
  provenance:  Provenance      # §3.5
```

`name` is reported, not derived. Do not prettify, title-case, or rewrite it.

#### `operation`

`operation` carries a name the dialect states in a **dedicated attribute**,
and is `None` when it states none. Exactly two kinds of attribute fill it
today: a tool name (`tool.name`, `gen_ai.tool.name`) and a model name
(`llm.model_name`, `embedding.model_name`, `gen_ai.request.model`). Nothing
else does, and `None` is an answer rather than a gap to be filled.

**No dialect's agent, chain or retriever name is read into `operation`.** OTel
GenAI states an agent's name normatively, in `gen_ai.agent.name`, and the
adapter deliberately declines it. OpenInference states no name attribute for
any of the three kinds, so its adapter has nothing to decline. The rule is
stated here rather than left to each adapter because the alternative is
asymmetry: a field exactly one dialect could fill would be that dialect's
attribute wearing a normalized name, and a consumer reading it would get a
value that is `null` in the other dialect on the same logical span. Whether a
uniform identity should exist at all is `OPEN_QUESTIONS.md` §15, and it is not
this field.

Declining to normalize a name is not losing it, and the library says so twice:

- the **value**, verbatim, in `raw.source` (§3.5) — serialized on every node
  unconditionally, and byte-exact through a round trip;
- the **fact that it was not normalized**, as an `unmapped_attributes`
  diagnostic (§3.7) naming the key — keys only, as that code always is.

`raw.source` is where a consumer finds the name; the diagnostic is how a
consumer learns to look for it.

Two precisions, so the rule is not read wider than it is:

- It is a rule about **name attributes**, not a rule that the field is empty
  on those kinds. An `agent`, `chain` or `retriever` span that also carries a
  *model* attribute gets the model in `operation`, in both dialects, by the
  ordinary rule above. Every such node in this project's corpus reads `null`
  because those spans carry no model attribute — not because the kind
  suppresses the field.
- **A retriever name is not one of the names any dialect states.** Earlier
  wording of this section listed one; no attribute for it exists in either
  dialect read today (OTel GenAI names the *operation*, `retrieval`, not the
  retriever), so no such value has ever been produced. A retriever span
  reaches `operation` only through `embedding.model_name`, and what it holds
  then is a model name.

#### Timestamps

`started_at` and `ended_at` are **unix seconds, as reported**. The library
never rescales, never converts, and never infers a unit: what the telemetry
put in the field is what the node carries, and a consumer that needs another
unit converts it itself. Only three things are decided here — which
*renderings* of a value the library will read, what numeric type it is carried
as, and when the library says the value looks like it is not in seconds.

**Renderings.** A timestamp is read from a JSON number, and from a **string
that is exactly a JSON number literal** — OTLP JSON encodes 64-bit integers as
decimal strings, so a quoted timestamp is a real rendering of a real exporter
and not a malformed one. A quoted value is read as the identical value the
same literal would have produced unquoted: `"1700000000"` and `1700000000` are
the same timestamp, and the two renderings of one trace produce the same
graph. Nothing else is a rendering. Concretely, and deliberately narrow:

| Rendering | Read | Carried as | Why |
|---|---|---|---|
| `1700000000`, `-1`, `0` | yes | `int` | a JSON number, written as an integer |
| `1700000000.5` | yes | `float` | a JSON number carrying a fraction |
| `"1700000000"`, `"-1"` | yes | `int` | the string is a JSON number literal, and is read as that literal |
| `"1700000000.5"`, `"1e9"` | yes | `float` | the same, for a literal carrying a fraction or an exponent |
| `"+1"` | no | — | JSON numbers carry no leading `+`; accepting one would read something JSON does not write |
| `" 1700000000"`, `"1700000000 "` | no | — | whitespace is not part of a number, and trimming is a normalization |
| `"01"`, `".5"`, `"1."` | no | — | JSON forbids each of these, so no exporter emits them |
| `"2026-09-05T10:00:00Z"`, `"NaN"`, `"0x1"`, `""` | no | — | not a number in any reading |
| `true` / `false` | no | — | a boolean is not a time, and Python would read it as `1` / `0` |
| `1e400`, `"1e400"` | no | — | a well-formed JSON number with no float64: it parses to `inf`, and `inf` is not a time |
| `NaN`, `Infinity`, `-Infinity` (unquoted) | no | — | Python's parser reads these as an extension; RFC 8259 does not write them, and none is a number |
| an integer literal of more than 4300 digits | no | — | past the library's digit limit (below, and §5.3) |

The rule is one sentence — *the string, unquoted, would be a valid JSON
number* — rather than a list of tolerated spellings, because every tolerated
spelling is a small normalization, and a library that trims whitespace here
has started deciding what the telemetry meant.

**Numeric type.** `started_at` and `ended_at` are `int | float | None`. An
integer literal is carried as an `int` and a literal with a fraction or an
exponent as a `float` — that is the whole rule, and it reads the *literal*,
not the value: `1e9` is a `float` and `"1e9"` is the same `float`, while
`1700000000` and `"1700000000"` are one `int`. Neither type is ever converted
into the other.

The reason is that `float` cannot hold what an exporter writes. float64's
spacing at 1.7e18 is **256 ns**, so a time reported in epoch nanoseconds —
which is what OTLP JSON's `startTimeUnixNano` is — loses its last digits the
moment it is passed through `float()`: two spans a hundred nanoseconds apart
collapse onto one number, and the `temporal` edge between them is then emitted
as tied (§4.3), asserting that neither started first when one demonstrably
did. A seconds field carrying nanosecond digits sits on the same floor, so
this is a property of the magnitude rather than of the unit.

Keeping the reported integer is **not** a unit conversion and not an opinion
about the unit: nothing is scaled, nothing is inferred, and the number a
consumer reads is the number the record wrote — which is also what makes it
round-trip, since an integer in serializes as the identical integer out. A
consumer that wants one numeric type coerces it, in the same way a consumer
that wants one unit converts it.

**Finite, or not read.** A rendering the table accepts is read only when what
it parses to is a **finite number**. Two things are not, and neither is a
time:

- `inf` and `nan`. Python's JSON parser produces them for the non-standard
  `NaN` / `Infinity` / `-Infinity` tokens, and produces `inf` for a literal
  whose magnitude no float can hold — `1e400` is a well-formed JSON number that
  has no float64.
- An integer literal longer than the library's **digit limit**: **4300
  digits**, a constant of this library (§5.3). The digits are counted before
  anything converts them, so which literals the limit covers is a fact about
  this library and the same on every interpreter — the interpreter's own
  integer-string limit, whatever it is set to, decides nothing here.

Each used to leave by a door of its own. `inf` reached the output as a bare
`Infinity`, which is not JSON and which a strict parser on the other end
rejects. A quoted integer past the digit limit reached the caller as the
interpreter's `ValueError`, raised out of `build` and printed by the CLI as a
traceback. Neither is a special case now: both take the door every other
rendering the library does not read takes, described next.

**A value in a rendering the library does not read is never silently
absent.** The field becomes `None`, the value stays verbatim in `raw.source`
(§3.5), and the adapter names the record field in `unmapped_attributes` (§3.7)
— keys only, as that code always is. A node that loses its `started_at` this
way then also gets `missing_timestamp` from the builder, which is the honest
pair: *we did not normalize this field*, and *so this node has no start time*.

Refusing the *field* does not make the record writable. `raw.source` is
verbatim, so an **unquoted** `NaN` or `1e400` is still in the graph as a
Python `nan` or `inf`, and the encoder — which writes RFC 8259 and nothing
else — refuses the whole graph rather than write a token JSON has no word for
(§7, `graph_not_serializable`). A **quoted** `"1e400"` is a string in the
record and writes back as the string it was.

**Unit suspicion.** A `started_at` or `ended_at` strictly greater than
**1e11** gets a `timestamp_unit_suspect` diagnostic (§3.7, level `warning`).
1e11 seconds after the epoch is the year 5138, so no wall-clock time in
seconds reaches it, while *now* in milliseconds is ~1.8e12 and in nanoseconds
~1.8e18. The value above the line is therefore evidence about the **unit of
the field**, which is a property of the encoding, and not a judgement about
the run — the library still keeps the number exactly as reported and still
builds every edge from it.

Three things about the rule are chosen rather than obvious, and are fixed
here so they are not re-decided per adapter:

- **It is checked on the reported values only** — `started_at` and
  `ended_at`, each against the threshold — and never on a *duration*. A
  duration is something the library computed by subtracting two numbers, and
  a claim about whether one is plausible is a claim about the run. Where both
  endpoints share a unit, which is the case a suspect unit produces, each
  endpoint already trips the check on its own.
- **One diagnostic per node**, not one per value and not one per graph. Both
  endpoints of a span share one field encoding, so two diagnostics for one
  span would say one thing twice; the diagnostic names every offending field
  in its `source`. It is per node rather than per graph — unlike
  `missing_trace_id`, which is per graph — because there *is* a node to point
  at, and because the case where the answer changes what a consumer does is
  the mixed one: an input carrying seconds from one exporter and nanoseconds
  from another is exactly what a per-graph statement cannot express. The cost
  is that an input entirely in nanoseconds emits one per node, which is the
  same shape `missing_timestamp` already has, and a consumer that wants one
  line groups by code.
- **Strictly greater**, so 1e11 itself is not suspect. The line is a bound on
  seconds, not a value seconds may not take.

### 3.2 NodeKind

A **closed** enum. Adding a kind is a spec change (halt point, `AGENT.md`).

| Kind | Meaning |
|---|---|
| `agent` | an agent or sub-agent invocation |
| `llm` | a model call |
| `tool` | a tool / function invocation |
| `retriever` | a retrieval / RAG operation |
| `embedding` | an embedding operation |
| `chain` | a composite step with no more specific kind |
| `unknown` | the dialect reported a kind we do not map |

`unknown` is a **first-class outcome**, not a failure. A span whose kind cannot
be mapped becomes an `unknown` node **plus** a diagnostic (§3.7) — never a
discard, never a guess. Downstream tools can then decide for themselves.

When an adapter maps a span to `unknown`, it MUST preserve the dialect's own
kind string, verbatim, under the normalized attribute key **`reported_kind`**,
as well as in the diagnostic. `attributes.reported_kind` is the only normalized
key this specification currently defines, and it is named here rather than left
to each adapter because `Node.attributes` is part of the serialized schema
(§3.9, §7) and freezes with it at Phase 4: a key invented per adapter would
become a per-adapter schema.

This is what makes the closed enum survivable in practice. Real dialects invent
kinds constantly — `guardrail`, `reranker`, `router`, `handoff` — and a
consumer that needs one of them can read the original string off the node
instead of waiting for a spec change (`OPEN_QUESTIONS.md` §1, whose provisional
stance this implements).

### 3.3 Payload

Telemetry is routinely partial. Conflating "absent," "empty," and "redacted"
destroys a consumer's ability to degrade honestly, so the model keeps them
distinct.

```
Payload:
  state: present | empty | absent | redacted | truncated
  mime:  str | None                      # e.g. "application/json", "text/plain"
  value: JsonValue | None                # parsed when mime is JSON, else str
  raw:   str | None                      # the unparsed source string
```

- `present` — a payload was reported and carries content.
- `empty` — a payload was reported and is genuinely empty (`""`, `{}`, `[]`).
- `absent` — the instrumentor emitted no payload attribute at all.
- `redacted` — the instrumentor signalled redaction/suppression.
- `truncated` — the instrumentor signalled the value was cut short.

`absent` and `empty` MUST NOT be collapsed. A consumer that needs payload-level
content reports *unavailable* on `absent` and *no content* on `empty`; those are
different statements about the world.

If `mime` indicates JSON, parse into `value` and keep the source in `raw`. If
parsing fails: `state` stays `present`, `value` is `None`, `raw` holds the
string, and a diagnostic is emitted. Never raise on a malformed payload.

The mirror case: an exporter that carries **nested attributes** hands the
adapter a value that was never a string, and the adapter renders it back to
text for `raw`. Rendering has the same limit parsing does — `json.dumps`
refuses nesting it will not descend — so when there is no text form, `state`
stays `present`, `value` and `raw` are both `None`, and the same
`payload_parse_failed` diagnostic says so. Nothing is lost: the value is in
the node's verbatim source record (§3.5), which is where a structured
attribute was always going to survive.

### 3.4 Usage

```
Usage:
  input_tokens:  int | None
  output_tokens: int | None
  total_tokens:  int | None
  extra:         Mapping[str, int]     # cache reads, reasoning tokens, etc.
```

**Counts only.** No prices, no currency, no rate tables — those are consumer
policy and they change (§9).

### 3.5 Provenance and RawRecord

Losslessness is an invariant (`CLAUDE.md` 2), and it is carried here.

```
RawRecord:
  source:      JsonValue      # the source span, verbatim, unmodified
  source_id:   str | None     # the dialect's own id for this record
  line_number: int | None     # 1-based, for file-based dialects

Provenance:
  adapter_id:      str | None # e.g. "openinference"; null when no adapter
  adapter_version: str | None #   produced this node (§6.1)
  dialect_note:    str | None # anything the adapter wants a human to know
```

**Both adapter fields are `null` on a node no adapter produced.** A record no
registered adapter claimed is kept as an `unknown` node carrying the record
verbatim, with `unclaimed_record` (§6.1) beside it. Naming an adapter there
would say a dialect read a record it declined, and provenance is the one field
whose whole job is to say who read this. They were `str` until the September
2026 audit series widened them, while the schema is unfrozen (`CLAUDE.md` 7).

Every node MUST be traceable back to exactly one source record. Round-tripping
`raw.source` through the serializer MUST reproduce the input record byte-for-byte
after canonical JSON encoding.

`line_number` is held in memory — it is what makes a diagnostic about an
unparseable line actionable — but it is **not serialized**. It is a property of
where a record sat in one file, not of the run the graph describes, and writing
it out would make a shuffled input produce a different graph, breaking §5.2.

### 3.6 Identity

Node ids are deterministic and stable across runs, machines, and Python versions.

1. If the dialect supplies a span id that is unique within the trace, the node id
   is that string, unchanged.
2. Otherwise, if the `source_key` is unique within the trace, the node id is
   `sw_` + the first 16 hex chars of
   `sha256(adapter_id + "\x00" + trace_id + "\x00" + source_key)`, where
   `source_key` is the adapter-supplied stable key: the dialect's span id where
   the record carries one, and otherwise the record's **canonical digest**
   (defined in rule 3). **Never the record's position.** A 1-based index would
   bind the id to where the record sat in the file, and input order MUST NOT
   affect the result (§5.2) — the same reasoning rule 3 states below, applied
   one level up.
3. Otherwise — two or more records share one `source_key`, which is what a
   dialect that reused a span id looks like from here — the node id is `sw_` +
   the first 16 hex chars of
   `sha256(adapter_id + "\x00" + trace_id + "\x00" + source_key + "\x00" +
   record_digest)`, where `record_digest` is the record's **canonical digest**:
   the SHA-256 of
   `json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   over the verbatim source record (§3.5). Both records are kept and
   `duplicate_source_id` (§3.7) reports the reuse.

**The empty string is not a span id — at either end of a relation.** This is
one rule at three fields, and it is stated here in one place because stating
it at only some of them is how it went wrong — twice.

| Field | Rendering | Read as |
|---|---|---|
| `span_id` / `spanId` | absent, `null`, or `""` | **no id stated** — rule 2 keys the record by its content |
| `parent_id` / `parentSpanId` | absent, `null`, or `""` | **no parent** (§4.0) |
| `links[].span_id` / `links[].spanId` | absent, `null`, or `""` | **no link** — and the entry is reported (below, and §3.7) |

The reference half is the one a real exporter exercises: `parentSpanId` is a
proto3 `bytes` field, an unset one is the empty string, and a marshaler that
emits defaults writes `""` on every root span of every export (§7). It is
normalized to "no parent" on the ground that an empty reference **names a span
no input can contain** — and that ground is the identity half above. While
`""` was accepted as an identity the claim was false: an input could contain
exactly that span, and the `parent` edge between such a pair — `explicit`, and
stated by the telemetry — was dropped with no diagnostic. Both halves together,
**nothing is lost**, because there is no node for an empty reference to have
named.

An empty `span_id` is therefore **read, not failed to read**: it decides which
identity rule applies, so it is not an unreadable field and draws no
`unmapped_attributes` (§3.7), and a derived id is not a defect to report but
rule 2's honest answer. Nothing is dropped either way — the empty string is
still on the node's `raw.source` verbatim (§3.5), so a consumer that wants to
know which rendering the exporter wrote reads it there.

**A link target is the third field, and the far end of a relation.** Batch S3
stated the rule at the first two and left the third reading `""` as a target,
so a link stating `span_id: ""` became an `explicit` `link` edge whose `dst`
was `""` — a span the identity half had just made sure no input can contain,
and this sentence was falsifiable by a one-line input (run-5 review 3.1, fixed
at batch S10). An empty link target now gets exactly what an absent one always
got: **no link**, so no edge. It differs from the other two fields in one
respect, and the difference is what the reading leaves behind. A record with
no `span_id` is still a node, and a record with no parent is still a root —
each statement is complete. A link entry exists only to name a span, so one
that names none becomes **nothing**, and its `trace_id` and `attributes` would
vanish between `raw` and the graph. So the entry is reported:
`unmapped_attributes` names it `<record>.links[<i>]`, its place in that
record's `links` (never the record's place in the file), keys only (§3.7).
Every entry that becomes no link draws that report — absent, `null` or `""`
target, a target that is not a string, an entry that is not an object — and a
`links` field that is not a list is reported as `<record>.links`.

**Exactly the empty string**, at every field. `" "` and `"0000000000000000"`
are ids like any other, because trimming or decoding one would be deciding
what the telemetry meant. All three readings live at the seam
(`spanweave.seam.span_ref`, `parent_ref` and `link_ref`, the last read by
`span_links`), not in each adapter: two dialects disagreeing about one id is a
cross-dialect equivalence claim, and a rule copied into two modules is a rule
that can drift in one of them. `fixtures/conformance/empty_ids` and
`fixtures/conformance/empty_link_target` are the scenarios, in both dialects;
the same inputs inside an OTLP export are pinned in `tests/test_read.py`,
because a container is not a dialect (§7).

**The formula is exact, because a reimplementation has to land on the same
id.** Both hashes are taken over a **string encoded UTF-8** and read as a
lowercase `hexdigest()`; the outer one is truncated to 16 characters, and the
record digest enters rule 3's material at its full 64. `trace_id` is the empty
string where the input states none. `ensure_ascii=False` is not house
style here, it is part of the contract: with the default, `{"name": "café"}`
canonicalizes to `{"name":"caf\u00e9"}` instead, whose digest begins
`9db11f5f` where the library's begins `645fa443`, so every id derived from
that record differs. An id is a name for a record, and the name would depend
on which of two equally reasonable encodings each implementation happened to
pick. Rules 2 and 3 stated the digest without that argument until the
September 2026 audit series (batch A7); the library has passed it since the
digest existed (batch A3), so it was the spec that was wrong.
`tests/test_ids.py` derives an id from this text and compares it against the
library's, and pins two `sw_` literals so neither side can drift quietly.

**A record the digest cannot be taken over is refused, not given an identity
some other way.** The formula is an encode, and an encoder has a ceiling
(§7): a record nested deeper than it will descend has no digest, and the only
alternatives would be to invent an id the formula does not produce — which
breaks the reimplementation claim above — or to drop the record, which
losslessness forbids. So it raises `graph_not_serializable` (§3.10), the same
refusal the write side gives for the same value, which could not have been
written either. This is a property of the interpreter's recursion budget and
not of any trace worth reading: the ceiling measured on CPython 3.11–3.14 is
between ~990 and ~37,000 levels of nesting inside one record.

**`adapter_id` is the adapter that read *that record*, not the adapter that
read the input.** A dialect is a property of a record (§6.1), so under a mixed
input the material of rule 2 and rule 3 differs per record, and it is the
**empty string** for a record no adapter claimed — the same way `trace_id` is
where the input states none. Rule 1 never consults it, which is why an input
whose dialect states span ids gets exactly the same ids however its records
were dispatched.

**`duplicate_source_id` reports a reused *span id*, not a shared `source_key`.**
Rule 3 fires on the `source_key`, so the two are not the same event, and the
September 2026 audit series (batch E3, `OPEN_QUESTIONS.md` §12(f)) asked whether
the report should move to the key. It does not, on two grounds. The first is
reachability: since the fallback key became the record's canonical digest
(rule 2), two records share a `source_key` **only** by sharing a span id — a
digest is shared only by records that are the same record, and §7 has already
collapsed those — so a key collision without an id collision is unreachable,
and a report for it would be a report nothing can produce. The second is what
the sentence would say: the message reports that *the dialect* reused an id,
which is a fact about the input, whereas a `source_key` is the library's own
construct and a diagnostic about one would be the library reporting on itself.
Should a dialect ever arrive whose adapter derives a key that is neither, this
is the decision to revisit.

**Python's built-in `hash()` is forbidden anywhere in identity or ordering** — it
is salted per-process and would break determinism (`CLAUDE.md` 4).

**Rules 2 and 3 both disambiguate on content, never on position.** The obvious
alternative — number the records, 1, 2, 3 — would make a node
id depend on where its record sat in the file, and input order MUST NOT affect
the result (§5.2, `CLAUDE.md` 4). Deriving from the record instead means the
two ids are the same two ids however the file is ordered, and the record
carrying `name: "beta"` keeps its id when the file is re-exported with the
lines swapped.

Rule 2 said "the 1-based record index" until the September 2026 audit series,
and a file of span-id-less records really did rebind its ids when its lines
were swapped. The fallback is content now, in both rules, for one reason: an
id is a name for a record, and a name that moves when the file is re-exported
names nothing.

Rule 3 is total because §7 collapses byte-identical duplicate records before
they reach here: two records that survive the reader and share a `source_key`
differ somewhere, so their digests differ. The two rules are one mechanism —
a record duplicated outright is *one* record, and a span id reused for two
different records is *two*.

Id collisions within a trace are a **hard error**, not a silent overwrite.
Under rules 1–3 no trace file can reach one: the only remaining routes are a
SHA-256 collision and a caller that hands the builder two spans it constructed
itself with the same key and the same record. The refusal stays as the
structural guarantee that a record is never overwritten — it is not something
an input is expected to trip, and no conformance scenario does.

### 3.7 Diagnostic

The record of everything the library could not confidently map. Diagnostics are
part of the output, not log noise.

```
Diagnostic:
  code:     str          # stable, machine-matchable — see the table below
  level:    info | warning        # never "error": errors raise
  message:  str          # human-readable, specific
  node_id:  NodeId | None
  source:   JsonValue | None      # the offending fragment, verbatim
  adapter:  str | None
```

The field is `level`, not `severity`. It grades how loudly to report a mapping
gap — nothing about the trace. `severity` is banned vocabulary under
`spanweave/` (`TASKS.md` 0.5) because in this domain it reads as a judgement
about what the telemetry *means*, which is exactly what core never makes
(`CLAUDE.md` 1). Keeping the gate absolute is worth more than the word, and the
name is fixed here rather than after `0.9.x` ships it as a serialized key.

Seed codes (extend deliberately; codes are a public contract once frozen):

| Code | Meaning |
|---|---|
| `unknown_span_kind` | the dialect's kind did not map to a `NodeKind` |
| `unmapped_attributes` | attributes the adapter did not normalize (names only) |
| `payload_parse_failed` | JSON mime type but the value did not parse (malformed, or nested deeper than the parser will recurse) |
| `orphan_parent` | `parent` reference to a span not present in the trace (§4.0 — a dangling `link` is **not** reported, and why; an **empty** parent reference is *no parent* rather than an absent one, and is not reported either) |
| `unpaired_call` | a requested tool call with no fulfilling span |
| `unpaired_result` | a tool result with no requesting call |
| `missing_timestamp` | no start time; temporal edges omitted for this node |
| `nonmonotonic_time` | `ended_at` precedes `started_at` |
| `timestamp_unit_suspect` | a reported `started_at`/`ended_at` exceeds 1e11, which unix seconds cannot (§3.1); the value is kept as reported. On a conformant OTLP JSON export every span is over the line, so **one per span is the expected output** and reports the encoding, not the run (§7) |
| `duplicate_source_id` | two records claimed the same source id |
| `duplicate_record` | the same record appeared more than once in the input; one copy is kept (§7) |
| `missing_trace_id` | no trace id in this input, so the graph reports none (§7); one per graph, never one per record, and only when the built graph reports no trace id at all; a record carrying none among records that do is not diagnosed |
| `multi_trace_input` | more than one trace id in a single input (§7) |
| `unclaimed_record` | no registered adapter claimed this record (§6.1); it is kept as an `unknown` node carrying the record verbatim, and its `provenance` names no adapter |
| `malformed_record` | an input record the JSON parser could not read (malformed, or nested deeper than it will recurse); its text is kept here |
| `ordering_cycle` | the ordering edges contain a cycle (§5.2); the graph is still built |

`unmapped_attributes` records attribute **keys only**, never values — the values
are already preserved verbatim in `RawRecord`, and duplicating payload content
into diagnostics is an unnecessary exposure surface. Its keys are attribute
names, and also record fields, written `<record>.<field>`: a field the adapter
recognizes but cannot read — a `start_time` in a rendering §3.1 does not
accept — is *not* normalized, and saying so here is what keeps it from
vanishing between the raw record and a `None`.

The timestamps are not the only fields it holds for. A record's **identity
fields** — `span_id`, `parent_id`, `trace_id`, `name` — are read as plain
strings, so one stated in any other rendering (`"name": 42`) is a field
recognized and not read: it falls to its default and is reported. Three
readings are *not* reports, because each is something the adapter read rather
than failed to: a field the record omits, a field reported as `null` — which
is how a record says "no parent" and "no name" — and `parent_id: ""`, which is
*no parent* rather than an unreadable one (§4.0).

A **span link** is held to the same rule and lands on the other side of it. An
entry in `links` that names no span — its target absent, `null`, `""` or not
a string, or the entry not an object — becomes no link (§3.6), and that is a
declaration the adapter recognized and could not map: nothing of the entry
reaches the graph, so it is reported as `<record>.links[<i>]`. A `links` field
that is present, not `null`, and not a list is `<record>.links`. A `links`
field the record omits or reports as `null` states no links and is not
reported.

**A key an adapter read and acted on is mapped, and is not reported here.**
Not every mapped key becomes a field. Some are read to *decide*: a tool-result
message's `role` is what tells the adapter that the id beside it is a result
the span received (§4.2.1) rather than a request it merely echoed (§4.4), and
that decision is the mapping. Reporting such a key overstates the gap — it
says the adapter did not understand a key it in fact acted on — and at
conversational scale it says so once per resent message per turn, which is
quadratic in the length of the conversation. A key the adapter read and could
**not** use is the opposite case and stays reported: a `llm.token_count.*`
whose value is not a number is a real gap, and so is an id whose sibling role
said it was not a result.

**A key that decided nothing was not acted on**, however it was read. A
tool-result `role` the adapter cannot read as a string — a number, a null, an
object — decides nothing: the id beside it is left reported by the *default*
rather than by a decision, and the unreadable `role` is reported too. It is the
`llm.token_count.*` case again, and reporting is the only trace it leaves,
because a `role` never becomes a field of its own — consuming it would let the
fact that one arrived unreadable vanish between the raw record and a decision
that was never made.

That is the adapter's rule, not one key's: **a key is consumed where it is
read, never before**. The reading is per key, and so is what it costs: a name
the adapter cannot read as a string contributes nothing *of its own*, and each
of `operation` and `model` is `None` only where no readable name **for that
field** is left. In OpenInference, `model` is `llm.model_name` when that reads
as a non-empty string, else `embedding.model_name` when that reads as a
string, else `None` (so an empty `llm.model_name` counts as no name for
`model`); `operation` is `tool.name` when that reads as a string, else
`model`. In OTel GenAI, `model` is `gen_ai.request.model` when that reads
as a string, else `None`; `operation` is `gen_ai.tool.name` when that reads as
a string and the span is a tool span, else `model`. So a span whose
`tool.name` is a number and whose `llm.model_name` is `"m"` reports
`operation` and `model` as `"m"`, exactly as one that never sent a tool name
would; one whose `tool.name` is `"t"` and whose `llm.model_name` is a number
reports `operation` `"t"` and `model` `None`; and a GenAI span that is not a
tool span, carrying a readable `gen_ai.tool.name` and no readable
`gen_ai.request.model`, reports both as `None` — its tool name was read and
consumed, and has no field on that span. A call id
it cannot read (`tool_call.id`, in the fulfilling form or the requested one)
leaves the span stating no call. Each unreadable key is a key read and not
usable, whatever the keys beside it decided, so each stays reported. Marking
the key consumed ahead of the read is the same overstatement pointing the
other way: it claims the adapter mapped a value it never had, and the claim is
loudest exactly where it is wrong, because the value that survives only in
`raw` is the one nothing else records.

The rule is the adapter's whole surface, not a list of keys, and three of its
cases are worth naming because each looks like an exception and is not:

- **A key read to *type* another one.** A mime type the adapter cannot read as
  a string (`input.mime_type`, `output.mime_type`) types nothing: the payload
  is `present` with no mime, exactly as if the key had never been sent. It is
  reported. So is a mime stated beside **no value at all** — an `absent`
  payload carries no mime either, so that key was never read.
- **A key whose only unreadable rendering is `null`.** A span kind is rendered
  with `str()`, so every value but `null` is read and is preserved verbatim as
  `attributes.reported_kind`; `null` alone leaves nothing, and is reported.
  The `unknown_span_kind` diagnostic must also say **which** of the two
  happened: a message that says "no attribute" of a key the span carried is
  untrue in the one place a reader would look to find out.
- **The same key in two dialects.** An unreadable name or call id
  (`tool.name` / `gen_ai.tool.name`, `tool_call.id` / `gen_ai.tool.call.id`)
  never reaches a node field, so `unmapped_attributes` is the *entire* report
  of it. One dialect reporting it and the other swallowing it is therefore a
  cross-dialect difference in the only place the difference could be seen, and
  §1's claim is that the two dialects describe one run the same way.

#### `source`, per code

`source` is typed `JsonValue`, so its shape is per code and must be stated
rather than inferred. Most codes carry the offending fragment as the type it
arrived as; two carry an object, three carry nothing, and one carries something
the library computed rather than something it was given.

| Code | `source` |
|---|---|
| `unpaired_call` | `{"call_id": str, "operation": str \| null}` |
| `unpaired_result` | `{"call_id": str, "operation": str \| null}` |
| `unmapped_attributes` | `list[str]` — attribute keys, never values |
| `malformed_record` | `str` — the line's text |
| `missing_trace_id` | `null` — there is no fragment. The absence being reported is the graph's own empty `trace_id`, and there is no node to point at either |
| `missing_timestamp` | `null` — there is no fragment. The diagnostic is about something **absent**, and `node_id` is where to look |
| `payload_parse_failed` | `null` — the unparsed text is already on the payload's `raw` (§3.3), and copying it here would duplicate content for no benefit |
| `ordering_cycle` | `list[str]` — the node ids that could not be ordered topologically. **Derived, not transcribed:** the cycle is something the library computed, and no input record contains it |
| `timestamp_unit_suspect` | `{"started_at": number, "ended_at": number}` — an object naming **only** the fields over the threshold, so one key, the other, or both, each carrying the value as reported. An object rather than an array because *which* field is over the line is the content of the report |
| everything else | the offending fragment, as the type it arrived as |

The three rows above the catch-all were added at `TASKS.md` 3.2, which measured
what each code actually carries and found that the catch-all's older wording —
*"the offending fragment, verbatim"* — was **false for exactly these three**.
Two carry no fragment at all, and `ordering_cycle` carries library output rather
than source. That is a document making a false statement about the library,
which is a smaller instance of what 3.2 exists to find, so it is corrected here
rather than left for a consumer to discover.

`missing_trace_id` joined the `null` rows later (the September 2026 audit's
batch A4, registered in `TASKS.md`), for the same reason as `missing_timestamp`:
it reports something **absent**, so there is no fragment of the input to carry.
Unlike `missing_timestamp` it carries no `node_id` either — §7 says why it is
one statement about the input rather than one per record.

`duplicate_record` falls under the catch-all and is worth one sentence
anyway, because its fragment is not *the* offending record but the one copy
that was kept — every copy is the same parsed record, which is exactly why
only one is kept.

Two things the catch-all still leaves open, said plainly rather than implied.
`unknown_span_kind`'s fragment is the dialect's kind **string** when there was
one and the **whole record** when there was not — both are the offending
fragment, and which one arrives depends on why the kind was unknown.
`nonmonotonic_time`'s is a two-element array assembled from `started_at` and
`ended_at`; the values are reported, the array is not. Neither contradicts the
row, and neither is a shape a consumer should infer from a single example.

The rows here state what the library emits today; they are not a vocabulary
adapters are held to for codes an adapter raises, and no second implementation
has yet had to agree with them. `CONTRACTS.md` carries `Diagnostic.source` as an
inventory row and says which half is which.

`operation` is the name the dialect gave the tool, and is `null` when the
dialect named none. It is not a guess: a dialect that states a requested call's
name states it on the requesting span, next to the id.

On `unpaired_result` the name is **redundant** — that call *has* a fulfilling
span, so `node_id` already leads to a node whose `operation` says the same
thing. It is carried anyway, because the two codes are read together and a
consumer that had to branch on which one it was holding to know whether
`source` was a string or an object would be a worse contract than one
redundant field.

**Why this is not a breach of the keys-only rule above.** That rule exists
because values are already in `RawRecord` and copying payload *content* into a
diagnostic is exposure without benefit. A tool's **name** is not content in
that sense — it is the identity of an operation, the same category as
`Node.operation` (§3.2), which the model already normalizes and puts on every
node. The library is not deciding to expose something new; it is putting a
value it already publishes on a fulfilled call in the one place a call that
never ran can be seen at all.

**Why it is needed.** Without it, a call that was requested and never fulfilled
can be attributed to the model that asked — via `node_id` — but not to the tool
it named, because a call with no fulfilling span has no node and therefore no
`operation`. Per-tool requested-versus-fulfilled is a question any fleet
consumer asks, and it was unanswerable from the graph. Recovering the name
meant walking the requesting node's output payload, in a dialect-specific shape
(`FIXTURES.md` §4.4), inside a consumer that must not know a dialect.

That was measured, not assumed, once a second dialect existed
(`TASKS.md` 2.10): the tool name appeared **zero** times in either dialect's
diagnostics, and the two payload paths share no prefix — `outputs.value` is a
JSON object in one dialect and an array in the other — so no single expression
reaches both.

### 3.8 Edge

```
Edge:
  src:     NodeId
  dst:     NodeId
  kind:    EdgeKind        # §4
  warrant: explicit | derived      # §4.1
  basis:   str             # the exact rule/field that produced it
  adapter: str | None      # which adapter's spans the edge was built from;
                           # null when they came from more than one (below)
```

`basis` is a short, stable machine-and-human readable string naming the *reason*:
`"span.parent_span_id"`, `"tool_call_id"`, `"sibling start_time ordering"`.
It is what lets a consumer audit an edge instead of trusting it.

**The builder supplies it.** Adapters state *relations* — a parent id, a call
id, a received call id, a link — and the builder is what turns a relation into
an edge, so the account of how that edge came to be is its account to give. All
five bases the library emits are builder constants, and a consumer reading
`basis` is reading one vocabulary rather than one per dialect.

The single reserved exception is a dialect that states *why* a link exists
rather than merely that it does (`SpanLink.basis`, §6). No observed dialect
does, and until one is observed every `link` edge carries the builder's
`"span.link"`. A `DeclaredDataEdge` seam type formerly let an adapter name both
ends of a `data` relation and supply that edge's `basis` itself; no adapter
ever populated it, the real case arrived in the shape §4.2.1 describes instead,
and it was removed (`TASKS.md` I1).

**`adapter` is `null` when the edge's ends came from different adapters.** A
dialect is a property of a record (§6.1), so an edge can join two adapters'
spans — a `call_result` whose requester one adapter read and whose fulfiller
another did, or a `data` edge across the same seam. There is no honest single
answer for such an edge: naming either dialect would attribute to it a relation
the two of them made together. `null` is the value the field already carries
for every `temporal` edge, so it says "no adapter asserted this on its own"
rather than introducing a new state. An end that is **not a node in this
graph** — a `link` pointing outside the trace (§4.0) — is not consulted, so a
dangling link still names the adapter of the span that stated it. An edge
touching a node no adapter produced is `null` for the same reason.

> Note the asymmetry this creates with `adapter`, and that it is deliberate.
> `adapter` records *whose spans this edge was built from*, which is provenance
> and belongs to the adapter. `basis` records *what rule made it*, which is
> mechanism and belongs to the builder. An edge carries both because auditing
> it needs both, and they are not the same question.

Edges are **unique** on `(src, dst, kind, basis)`. Duplicates are collapsed.
The same pair MAY be connected by several edges of different kinds; that is
normal and informative.

> A cold reviewer of the first captured trace read `edge_count: 6` as a
> double-count, having noticed that one pair carried both `call_result` and
> `temporal`. The behavior is correct and stays: the two edges assert different
> relations with different warrants, and collapsing them would destroy the
> distinction the whole model is built on. But the misreading is worth
> recording, because it was not careless — it is what a first-time reader
> concludes from a bare total. It is an argument about **presentation**, not
> about the model: `spanweave inspect` already breaks edges down by kind and
> warrant, and a total printed above that breakdown may simply be inviting the
> wrong reading.

### 3.9 Graph

```
Graph:
  trace_id:    str
  nodes(...):  -> tuple[Node, ...]                 # topological, tie-broken (§5.2)
  edges(...):  -> tuple[Edge, ...]                 # sorted (§5.2)
  diagnostics: sorted tuple[Diagnostic, ...]
  annotations: AnnotationStore                     # §8
  meta:        Meta
```

`nodes` and `edges` are **accessors, not attributes** — `graph.nodes(kind=...)`,
`graph.edges(kind=, warrant=)`, as §8 and the README use them. Called with no
arguments each returns the whole ordered tuple, so the ordering guarantees
above are guarantees about what they return. Everything the graph holds is
still immutable; `Graph.of(...)` builds one.

```
Meta:
  schema_version:   str        # "0.x" until the freeze, and it never moves
                               # while it is "0.x"; "1" once frozen (below)
  spanweave_version: str
  adapters:         tuple[AdapterInfo, ...]   # id + version + confidence, sorted
  source_digest:    str | None # sha256 of input bytes, when built from a file
  node_count / edge_count / diagnostic_count: int

AdapterInfo:
  id:         str
  version:    str
  declared_confidence: float | None   # the adapter's own claim; None when named
```

`meta.adapters` carries **every adapter that produced at least one node**,
distinct on `(id, version)` and sorted by it. An input written in one dialect
therefore carries exactly one entry, as it always did; an input whose records
came from two instrumentors carries both (§6.1). A record no adapter claimed
adds no entry — there is nobody to name — and is reported by `unclaimed_record`
instead.

`AdapterInfo.declared_confidence` is where §6.1's "the chosen adapter and its
confidence are recorded in `meta`" lands. It is `None` when the caller named the
adapter, because there was no detection to report. It is each contributor's own
declaration over the first 50 records **it claimed**, so an adapter that claimed
every record reports the number it reported before per-record dispatch existed.

The name says `declared_` because **it is not a measurement**. Nothing in the
trace could produce it: an adapter self-reports a number from `detect()`, and
that number is a claim about the input, not an observation of it. Every other
figure in a graph is derived from the bytes that came in; this one is a fact
about the *build*, which is why it lives in `meta` and not on a node. A bare
`confidence` would read as measured, and a graph that presents a hard-coded
constant as a measurement is doing the thing this library exists not to do.

Whether it should remain adapter-declared at all is `OPEN_QUESTIONS.md` §3.
Naming it honestly makes the current answer visible in the output rather than
hiding it behind a plausible field name.

`source_digest` fingerprints the **input bytes**, not the graph. Shuffling the
input therefore changes it while the graph itself stays identical — which is
the correct behavior, and why §5.2's order-independence claim is about the
graph rather than about this field.

`meta` MUST NOT contain a build timestamp, a hostname, a username, or a file
path. Those would break byte-identical determinism and leak the operator's
environment.

#### `schema_version` while unfrozen: `0.x` is one bucket, and it never tracks

**`0.x` is a single unfrozen bucket. It does not track changes to the
serialized graph, it never has, and it will not before the freeze. A consumer
must pin on the *library* version, not on this field.**

That is a decision (`TASKS.md` 3.7), not a description of neglect, and it is
stated here because the alternative was to imply a precision the value never
had. `SCHEMA_VERSION` was `"0.1"` before **two** changes to what is serialized
and `"0.1"` after both of them:

| Change | What moved |
|---|---|
| `a953a1f` | `meta.adapters[].confidence` renamed to `declared_confidence` |
| `9e79658` | `diagnostics[].source` on the unpaired codes: a bare string became `{"call_id", "operation"}` (§3.7) |

Bumping to `"0.2"` now would buy a distinction **no one can observe** — nothing
has ever been published from this repository, so no consumer has ever read a
`"0.1"` graph — while implying that the sequence `0.1 → 0.2` tracks contract
changes, which for the `0.1` era is not true. Declaring the bucket says the
same thing without the implication.

**What to pin on instead.** `meta.spanweave_version` is in every graph
document, so the library version is recoverable from the file itself with no
out-of-band knowledge. That is the field that moves when the serialized graph
moves, and it is what a consumer should compare.

**What still stops a change shipping unnoticed.** Not this field — under this
decision it cannot. `tests/test_schema_shape.py` does: the shape of the
serialized document (field names, types, nesting — never contents) is
committed to `tests/serialized_shape.json`, and moving it fails the build
until the artifact is regenerated in the same change, which puts the move in
the diff. It is deliberately blind to what a trace contains, so growing the
conformance corpus cannot fire it.

**At the freeze, `"1"` is a fresh start.** It is not the next term in a
sequence that ran through `0.x`, because no such sequence ran. The field
acquires meaning *at* the freeze and had none before it, and the
additive-only compatibility policy (`CLAUDE.md` 7) is the first thing that
ever gives it teeth (`ROADMAP.md`, Phase 4).

### 3.10 Errors and error codes

Almost everything the library cannot handle becomes a **diagnostic** (§3.7).
What remains is a short list of structural impossibilities, where continuing
would mean publishing a graph that is quietly wrong — or where there is no
graph left to publish at all. Those raise.

Every raised error is a `SpanweaveError` (or a subclass) and carries a stable,
machine-matchable `code`:

```
SpanweaveError:
  code:    str        # stable, machine-matchable — see the table below
  args[0]: str        # human-readable, specific. NOT a matching surface.
```

| Code | Type | Meaning |
|---|---|---|
| `duplicate_node_id` | `DuplicateNodeIdError` | two records resolved to one node id (§3.6) |
| `no_adapters_registered` | `AdapterSelectionError` | nothing is registered to read this input |
| `adapter_ambiguous` | `AdapterSelectionError` | two or more adapters are equally confident (§6.1) |
| `adapter_unconfident` | `AdapterSelectionError` | no adapter reached the minimum confidence (§6.1) |
| `adapter_detect_failed` | `AdapterSelectionError` | an adapter raised from `detect()`, which §6 forbids |
| `duplicate_adapter_id` | `AdapterSelectionError` | two adapters claim the same id |
| `unknown_adapter` | `UnknownAdapterError` | a caller named an adapter that is not registered |
| `graph_not_serializable` | `GraphNotSerializableError` | a value the library must encode cannot be: it nests deeper than the JSON encoder will descend, is a non-finite number RFC 8259 cannot write, or refers back to itself (§7). Either the graph is held and cannot be written, or a record cannot be digested (§3.6) — one code, because it is one fact about one value |

Codes are a **public contract from `0.9.x`**, on the same terms as diagnostic
codes: adding one is deliberate, and renaming one after the freeze needs a
version bump.

Match on the code, never on the message. The exception *type* is too coarse to
act on — `AdapterSelectionError` alone covers four different situations, and a
caller that wants to retry an ambiguous input with `--adapter` but fail hard on
a broken adapter cannot tell them apart from the type. The alternative to a
code is string-matching the message, which silently makes every message a
compatibility surface and means nobody can improve one without breaking a
caller.

**A caller who has only stderr can follow that rule too.** A rule nobody can
obey from where they stand is not a contract, and a process that runs
`spanweave` as a subprocess stands outside the exception: all it has is an
exit status and a line of text. So the CLI prints the code in brackets ahead
of the message (§7, *Failures*). That does not make stderr a matching
surface — it puts the code, which is the matching surface, somewhere a caller
can reach.

## 4. Edge kinds — the centerpiece

A **closed** enum. Adding one is a spec change (halt point).

| Kind | Direction | Meaning | Allowed warrant |
|---|---|---|---|
| `parent` | parent → child | span containment as reported by the tracer | `explicit` only |
| `call_result` | requesting op → fulfilling op | a tool call and the span that answered it, joined by an id | `explicit` only |
| `data` | producer → consumer | an output feeds an input | `explicit` only |
| `link` | source → linked | an OTel span link (often cross-trace) | `explicit` only |
| `temporal` | earlier → later | one operation **ordered** before another among its siblings | `derived` only |

`link` is the one kind whose `dst` may name a span that has **no node in this
graph**: links are routinely cross-trace, and requiring the target to be
present would make the kind useless for the case it exists to describe. A
consumer that only wants intra-trace structure filters on kind, which it is
already doing.

### 4.0 Dangling references: why `link` and `parent` differ

`parent` and `link` meet the identical situation — a reference to a span that
is not in this input — and handle it in **opposite** ways. That is deliberate,
and it is a statement about the two relations rather than an inconsistency:

| | Reference to an absent span | Rationale |
|---|---|---|
| `parent` | **no edge**, plus an `orphan_parent` diagnostic (§3.7); the node is kept | A parent is a containment claim *within* one trace. A dangling one means the trace is incomplete — sampled, filtered, or exported mid-run — which is worth reporting. |
| `link` | **edge emitted**, `dst` naming the absent span; no diagnostic | A link is routinely *about* another trace. A dangling one is the normal case, not a defect, and reporting it would be reporting that the feature worked. |

Consequences a consumer must know:

- **A `link` edge's `dst` may not resolve.** `graph.node(dst)` returns `None`,
  and that is the contract, not a bug. Node-returning queries (`children`,
  `parents`, `descendants`, `ancestors`, `reachable`, `paths`) report ids
  exactly as the edges name them, foreign targets included: the edge exists and
  names its target, so dropping the id would hide a relation the telemetry
  stated. Resolve defensively.
- **No other edge kind may dangle.** `parent`, `call_result` and `data` edges
  connect nodes that are present; `validate()` enforces exactly that asymmetry
  (§7).
- Node-returning queries report each node **once**, even when several kinds of
  edge connect the same pair. One result per *relation* is what `edges()` is
  for.

#### No parent, and a parent this input does not carry

`orphan_parent` reports a parent the record **named** and this input does not
carry. A record that names no parent at all is a **root**, and a root is not a
truncated trace: it gets no edge, no diagnostic, and nothing to report.

The two are not always spelled apart, which is the whole of this rule. A
record states "no parent" in **two** renderings, and they are the same
statement:

| Rendering | Meaning |
|---|---|
| the field is absent (`parent_id` missing, `parentSpanId` omitted) | no parent |
| the field is present and **empty** (`""`) | no parent |

The second is not an edge case in the wild, it is the ordinary one: OTLP's
`parentSpanId` is a proto3 `bytes` field, an unset `bytes` field is the empty
string, and a marshaler that emits default-valued fields writes
`"parentSpanId": ""` on **every root span of every export** (§7). Read as a
reference, that empty string names a span no input can contain, so every root
would draw an `orphan_parent` — the diagnostic saying "this trace is
incomplete" about the one span that proves it is not.

**"No input can contain it" is §3.6's half of this rule, not a hope about
inputs.** An empty `span_id` states no id, so no node is ever named `""` —
which is what makes normalizing the reference away lose nothing. Until the
September 2026 audit series (batch S3) only the reference half was stated, and
in the gap a record whose `span_id` was `""` kept `""` as its identity: the
`parent` edge between such a pair was dropped silently, and this paragraph
asserted something an input could falsify. Read the two halves as one rule.

So an empty parent reference is **no parent**, and the normalization happens in
the adapter, at the seam (§6): `NormalizedSpan.parent_id` is `None`, and the
builder — which tests presence, and should never have to ask whether an id is
really an id — never sees it. Exactly the empty string, and nothing else: a
parent id of `" "` or `"0000000000000000"` is a reference like any other and is
reported like any other, because trimming or decoding one would be deciding
what the telemetry meant.

Nothing is dropped in the process (`CLAUDE.md` 2). The empty string is still in
the node's `raw.source`, verbatim (§3.5), so a consumer that wants to know
which of the two renderings the exporter used reads it there. What is
normalized away is the *reference*, into the absence it already stated.

#### A link that names no span

The table above is about a link whose target is **not in this input**. A link
whose target is **no span at all** — `span_id` absent, `null` or `""` — is a
different case and gets no edge: an edge whose `dst` is `""` would not be a
dangling link but an `explicit` claim to a span the telemetry never named,
and no input can contain one (§3.6). Unlike an empty parent reference it is
reported, as `unmapped_attributes` (§3.7), because a link entry that names
nothing becomes nothing, and the report is what keeps it from vanishing
between `raw` and the graph. The entry itself is in `raw.source`, verbatim.

### 4.1 Warrant

- **`explicit`** — the telemetry asserted this relation. The adapter is
  transcribing, not reasoning.
- **`derived`** — `spanweave` computed it from a stated rule over the data.

The warrant column above is **binding**: `parent`, `call_result`, `data`, and
`link` are `explicit`-only; `temporal` is `derived`-only. A derived edge may
**never** be promoted to explicit (`CLAUDE.md` 3). If a rule is ever added that
infers a relation of an explicit-only kind, it does not become that kind — it
becomes a new kind, through a spec change.

### 4.2 `data` edges are never inferred

> **NOTE (Phase 3): see `OPEN_QUESTIONS.md` §7 and `PREDICTIONS.md` P3.** The
> warrant system already makes computed relations publishable honestly, so this
> absolute prohibition is **stricter than the architecture requires**. It is
> partly a scope decision — value-matching is the first consumer's core
> analysis — and that should be decided deliberately rather than inherited.
> The rule below is binding until it is.

A `data` edge is emitted **only** when the instrumentor itself declares a
producer→consumer relation (some frameworks do), and it reaches the graph by
one route: §4.2.1's. `spanweave` will not compare an
output string to an input string and conclude a flow. That comparison needs a
threshold, a normalization rule, and an encoding policy — none of them
opinion-free — and shipping one default set of those choices would be closer to
semantics than anything else in the library (`CLAUDE.md` 1).

#### 4.2.1 Declarations made at message granularity

A declaration does **not** have to name two spans. It may be made about a
**message**, and resolved to spans by **declared id** — never by comparing
values.

The case this exists for: a chat protocol's tool-result message
(`{"role": "tool", "tool_call_id": X, ...}`) states that the output of whatever
answered call X became an input to the span that received the message. The span
that answered X declares the same id. Joining them is the mechanism §4.4
already uses for `call_result`, and no content is examined at any point — so
none of the three objections above has anything to apply to: there is no
threshold, no normalization rule and no encoding policy, because there is
nothing being matched.

Such an edge is `explicit`, and its `basis` MUST name the resolution rather
than only the field — `"tool_call_id in tool-result message"`, not
`"tool_call_id"` — because a consumer auditing it is entitled to know that a
resolution step happened and what it joined on.

**The objection, which is accepted rather than dismissed.** The subject of the
declaration is a *message*; the subject of the edge is a *span*. In
`call_result` both endpoints make claims about themselves, and here one endpoint
makes a claim about something it received, which the library then attributes to
another span. That is a granularity leap, and it takes a position on
`OPEN_QUESTIONS.md` §2 (are messages nodes, or payload content?): it resolves
message-level provenance **to span level** instead of surfacing it as
message-level nodes.

It is accepted because the alternative is worse in the library's own terms.
Suppressing a relation the telemetry states plainly is the mirror image of
asserting one it did not — the failure this section exists to prevent — and the
warrant and basis together make exactly what happened auditable: `explicit`
says the telemetry asserted it, and the basis says how it was resolved. What is
**not** licensed is any widening of this: a declaration must still be a
declaration, and the id must still be the join.

**A declaration repeated is still a declaration.** Conversational protocols
resend the whole history on every turn, so the same tool-result message
reappears in the request of every later span. Each occurrence is a declaration
made by the span that carries it, about its own input, and it is true: the
result did reach that span. Every one of them is transcribed, and `n` such
turns produce `n(n-1)/2` `data` edges — the input carries that many
declarations, and suppressing a relation the telemetry states plainly is the
failure this section exists to prevent.

What the graph adds is which occurrence came first. For each call id, the
spans declaring receipt are ranked by `(started_at, node_id)` — the order §5.2
already defines — and the basis records the rank:

| Situation | `basis` |
|---|---|
| earliest span declaring receipt of this call | `tool_call_id in tool-result message` |
| earliest, decided by `node_id` on a `started_at` tie | `tool_call_id in tool-result message (earliest tied, broken by node_id)` |
| any later span declaring receipt of the same call | `tool_call_id in tool-result message (not the earliest receiving span)` |

A span with no `started_at` sorts last and is never the earliest unless no
receiving span is timed. The ranking is a function of a *set* of spans, so
input order cannot affect it (§5.2).

The third basis says **only** that an earlier span declared the same receipt.
It does not say the later declaration is an artifact of a protocol resending
history, because the library cannot see that: two spans genuinely consuming
one result produce the identical shape. As with §4.3's tie-break, the warrant
says the relation was stated and the basis says what was determined about it —
a consumer that does not care matches on `kind` and ignores both.

**A stated gap.** If a span reports receiving the result of call X and no span
in the input fulfilled X, no edge is emitted and **nothing is reported** — the
producer is simply absent. That is currently silent; it wants a diagnostic code
the first time someone meets it.

### 4.3 `temporal` edges: scope and rule

Emitting a `temporal` edge for every ordered pair is O(n²) and useless. The rule
is narrow and stated:

> For each set of sibling nodes sharing the same `parent` (nodes with no parent
> are siblings of each other at trace root), sort by `(started_at, node_id)` and
> emit a `temporal` edge between **consecutive** siblings only.
> `basis = "sibling start_time ordering"`.

Nodes with no `started_at` are excluded from temporal edges and get a
`missing_timestamp` diagnostic. Ties are broken by `node_id`, ascending, and the
tie-break rule is a determinism invariant.

**A `temporal` edge asserts an order, not a precedence.** Two siblings may
report the *same* start time, and then neither started first — the edge between
them records a decision the library made so that the order is total, not
something the telemetry observed. Such an edge is still emitted (a partial order
would not be deterministic, and dropping it would break the sibling chain), but
it carries a different basis:

| Situation | `basis` |
|---|---|
| `started_at` strictly increases | `sibling start_time ordering` |
| `started_at` is equal, order decided by `node_id` | `sibling start_time ordering (tied, broken by node_id)` |

That distinction is why `basis` exists. `warrant` already says the relation was
computed; the basis says *from what*, so a consumer can discount a tie-broken
edge — or find every one of them — by reading the graph rather than by
re-deriving the timestamps it was built from. A consumer that does not care
matches on `kind` and ignores both.

The transitive closure is available to consumers via `graph.reachable(...)`;
it is not materialized in the edge set.

### 4.4 `call_result` pairing

Tool call/result pairing is the single most valuable thing a dialect-aware
adapter can recover, and it is frequently **not** the parent/child relation.

- Adapters SHOULD emit `call_ids` on requesting and fulfilling spans when the
  dialect carries them (`tool_call_id`, `function_call_id`, or equivalent).
  **A span may carry several.** One model turn requesting several tools at
  once is how current agent frameworks work, not an edge case, and a seam that
  held one id per span could only express it by dropping one.
- All of a span's ids share that span's `call_role`. A span that both requests
  one call and fulfils another is not expressible; that shape is recorded in
  `OPEN_QUESTIONS.md` §8 rather than designed for in advance.
- The builder joins on each `call_id` within a trace and emits `call_result`
  with `basis = "tool_call_id"`. Several `call_result` edges may leave one
  node, and that is ordinary.
- **A requester is the span that *originated* the call, not one that merely
  mentions it.** Conversational protocols require the whole history to be
  resent on every turn, so the same call id reappears on later spans as
  *context* — and a rule that matched the id anywhere would make a span that
  requested nothing look like a requester, producing a `call_result` edge with
  `warrant=explicit` for a relation the telemetry never stated. An adapter
  MUST take a requester id only from what the span itself produced. **An echo
  of a reference is not the reference.**
- An id a span merely **echoes** — one it did not originate — is not dropped:
  it is left unmapped and reported (§3.7). It is evidence of context, and there
  is no edge kind for that — inventing one would be worse than saying nothing.
  A tool-*result* id in the same resent history is the other case, not this
  one: §4.2.1 maps it, so it and the `role` key that identified it are
  consumed like any other mapped key.
- Unmatched calls/results produce `unpaired_call` / `unpaired_result`
  diagnostics — never a fabricated pairing, and never a fallback to guessing by
  name or proximity.

## 5. Determinism

### 5.1 Guarantee

Same input bytes + same adapter version + same `spanweave` version → **the same
graph, byte-for-byte** on serialization, on any machine, under any interpreter
configuration.

The last clause is earned rather than assumed: the one interpreter setting that
used to change a graph, the integer-string digit limit, is replaced inside the
library by a constant of its own (§5.3).

### 5.2 Rules

- Nodes are ordered by a Kahn topological sort over `parent` ∪ `call_result`
  edges, tie-broken by `(started_at or +inf, node_id)`. **The tie-break is a
  determinism invariant.**
- If the ordering-relevant edges contain a cycle (malformed input), the graph is
  still produced: nodes involved in the cycle are ordered by
  `(started_at or +inf, node_id)` alone, and a diagnostic is emitted. A cycle
  MUST NOT hang or crash the builder.
- Edges are sorted by `(kind, src, dst, basis)`.
- Diagnostics are sorted by `(code, node_id or "", message)`.
- Serialization uses stdlib `json` with `sort_keys=True`, `ensure_ascii=False`,
  `separators=(",", ":")`, and a trailing newline.
- **Input line order is not significant.** Shuffling the records of an input file
  MUST produce an identical graph. This is a test (`TASKS.md` 0.6).
  - The one field exempt from that claim is **`meta.source_digest`**, which
    fingerprints the input **bytes** rather than the graph's content (§3.9).
    Shuffling changes the bytes by definition, so the digest changes with them;
    everything else — every node, edge, diagnostic and remaining `meta` field —
    must be byte-identical. An independent checker must exclude that one field,
    or it will report a failure the spec does not intend.
  - The exclusion is required to carry its own proof: a **separate** assertion
    shows that `source_digest` genuinely *does* differ between a trace and its
    shuffled twin. Without it, excluding a field would be indistinguishable from
    excusing a field that never varies — and an exclusion nobody can see through
    is exactly the shape of a determinism claim that is quietly false.
- No clocks, no randomness, no `hash()`, no set iteration order, no
  dict-insertion-order dependence in any output-affecting path.

### 5.3 The digit limit is the library's

CPython refuses to convert an integer *string* longer than its integer-string
digit limit, in both directions — `int()` of the text raises, and so does
`str()` of the integer — and that limit is a per-process setting: 4300 digits
by default, any value from `sys.int_info.str_digits_check_threshold` (640)
upward, or none at all, moved by `PYTHONINTMAXSTRDIGITS`,
`-X int_max_str_digits` and `sys.set_int_max_str_digits`, and read by
`sys.get_int_max_str_digits`. Every JSON parse and encode of an integer asks
it. Left to the interpreter, one trace file built different graphs under
different settings — a quoted 5000-digit `start_time` was refused on a stock
interpreter and read under `PYTHONINTMAXSTRDIGITS=0`; an unquoted 1000-digit
integer was part of a record on a stock interpreter and made its line
unreadable under `PYTHONINTMAXSTRDIGITS=640`.

**The library owns the limit instead.** `DIGIT_LIMIT` in
`spanweave/jsoncodec.py` is **4300** — the interpreter default, so on a stock
interpreter no graph's nodes, edges or diagnostic codes change, though the
message text of two diagnostics does (below) — and it is applied by
**counting the literal's digits** (the sign is not a digit) before anything
converts it:

- an **unquoted** integer literal of more than 4300 digits makes its line
  unreadable JSON, reported as `malformed_record` (§7);
- a **quoted** timestamp of more than 4300 digits is not read: `started_at`
  or `ended_at` is `null`, the field is named in `unmapped_attributes`, and
  the node gets `missing_timestamp` (§3.1);
- an OTLP `intValue` of more than 4300 digits is carried verbatim as the
  decimal string it arrived as (§7).

The two diagnostics are `malformed_record` and `payload_parse_failed`. When
either refuses a line or a payload over a literal of more than 4300 digits,
its message used to quote the interpreter's refusal — *"Exceeds the limit
(4300 digits) for integer string conversion: …"* — and now names the
library's: *"an integer literal of 4301 digits is longer than the 4300 digits
spanweave reads (`SPEC.md` §5.3)"*. Nodes, edges and diagnostic codes are the
same as a stock interpreter built them before the constant existed (run-6
review S8.1).

An integer of 4300 digits or fewer is read, carried and written whole, and
every conversion the library makes between such an integer and text — in the
reader, in both adapters, in diagnostic messages and in the encoder — goes
through a path the interpreter's limit does not govern (`decimal.Decimal`,
which converts by arithmetic rather than through `int`'s string conversion).
So the graph is a function of the input bytes under every interpreter setting,
and that is measured: `tests/test_determinism.py` builds one trace carrying
integers on both sides of both limits in three processes — the setting unset,
`PYTHONINTMAXSTRDIGITS=0`, and `PYTHONINTMAXSTRDIGITS=640` — and asserts the
three graphs are byte-identical.

**The interpreter's setting is never changed.** Calling
`sys.set_int_max_str_digits()` at import would also have made the graph
independent of the setting, and would have been the wrong thing to do: the
limit is process-wide and it is a denial-of-service mitigation the host may
have set deliberately, and a library that moves it on import changes the
behaviour of every unrelated line of code in that process, silently, as a side
effect of `import spanweave`. The library reads trace bytes against its own
constant and leaves the host's setting as it found it.

## 6. Adapter contract

Full authoring guide in `ADAPTERS.md`. The normative contract:

```
NormalizedSpan:
  source_key:  str                # stable within the input
  span_id:     str | None
  parent_id:   str | None
  trace_id:    str | None
  kind:        NodeKind
  name:        str
  operation:   str | None
  started_at / ended_at: int | float | None   # §3.1
  status:      Status
  status_note: str | None
  inputs / outputs: Payload
  usage:       Usage | None
  call_ids:    tuple[str, ...]    # for call_result pairing (§4.4); may be many
  call_role:   requester | fulfiller | None
  links:       tuple[SpanLink, ...]   # SpanLink.basis is None unless the
                                      # dialect states the link's REASON (§3.8)
  received_call_ids: tuple[str, ...]  # results this span was GIVEN (§4.2.1);
                                      # the builder resolves them to producers
  attributes:  Mapping[str, JsonValue]
  unmapped:    tuple[str, ...]    # attribute keys seen and not normalized
  raw:         RawRecord
  dialect_note: str | None       # anything a human should know; -> Provenance
  diagnostics: tuple[Diagnostic, ...]   # what this record could not map (§3.7)
```

`diagnostics` is on the span because `parse()` returns spans and has nowhere
else to put them: an adapter that cannot map something must be able to say so
(`ADAPTERS.md` §2) without a side channel. The seam is internal, so carrying
them here costs nothing publicly.

```
Adapter (Protocol):
  id:      str        # stable, lowercase, e.g. "openinference"
  version: str        # the adapter's own version, not the library's

  detect(sample: Sequence[JsonValue]) -> float
      # confidence in [0.0, 1.0] that this adapter handles the input.
      # Pure. Must not raise. Must not consume a stream.

  parse(records: Iterable[JsonValue]) -> Iterator[NormalizedSpan]
      # Pure. No network. No filesystem. No eval/exec. Never raises on
      # malformed input — emit a NormalizedSpan with diagnostics attached,
      # or skip and record why.
```

Rules binding on every adapter:

1. **Never invent.** If a field isn't in the input, it is `None` / `absent`.

   The corollary the seam depends on: **a field that says nothing is `None`,
   not the empty thing it said it with.** `parent_id` is the case that has a
   rule of its own, because a dialect spells "no parent" two ways — the field
   absent, or the field present and empty — and one of the two is what a
   conformant OTLP export writes on every root (§4.0, §7). Both are `None` at
   the seam. An empty id is not a reference, so it never reaches the builder as
   one, and no root of any export is reported as an orphan. The empty string
   itself is untouched in `raw`, as everything else is.
2. **Never drop silently.** Unrecognized attributes go in `unmapped`; the whole
   record is preserved in `raw`.
3. **Never interpret.** No roles, no severity, no scoring, no redaction of
   content the source did not redact.
4. **Never raise on bad input.** Malformed records produce diagnostics.
5. **Relations, not edges.** An adapter states the relations its dialect
   asserts — `parent_id`, `call_ids` + `call_role`, `received_call_ids`,
   `links` — and the **builder** constructs every edge from them. All four
   yield `explicit` edges; `temporal` is the builder's alone and an adapter
   has no way to ask for one.

   An adapter therefore supplies no edge's `basis`, because it emits no edges.
   The vocabulary is the builder's (§3.8), and the one reserved exception —
   `SpanLink.basis`, for a dialect that states a link's *reason* — is `None` in
   every adapter observed so far.

   *This rule previously read "an adapter may assert `parent`, `call_result`,
   `data`, `link` … all traceable to a source field named in `basis`". That was
   false for `parent` and `call_result` from the first release: both have always
   been builder constants. It was corrected at `TASKS.md` I1, alongside the
   `ADAPTERS.md` §3 sentence that disagreed with §3.8 and §4.3 for four
   phases.*

### 6.1 Adapter selection

**A dialect is a property of a record, not of a file.** One process can run a
framework instrumentor and an SDK instrumentor at once; they share a tracer
provider, and their spans share an export. So `spanweave build` asks every
registered adapter about **every** record — `detect([record])`, the same
declaration §6 defines — and an adapter **claims** a record when what it
declares reaches `0.5`.

| Input | Result |
|---|---|
| every record claimed by the same one adapter | that adapter parses the input, and `meta.adapters` carries its one entry — the single-dialect case, unchanged |
| a record claimed by **two** adapters | a **hard error** (`adapter_ambiguous`), naming the record's position, its span id where it has one, and both claimants |
| no record claimed by any adapter | a **hard error** (`adapter_unconfident`), listing every declared confidence |
| a record claimed by **no** adapter | an `unknown` node carrying the record verbatim, plus `unclaimed_record` (warning). Its `provenance` names no adapter (§3.5), and it is never handed to a designated one |
| several adapters each claiming records, none claiming a record another claims | a **mixed** build: each adapter parses the records it claimed, the builder receives all of their spans together, `meta.adapters` lists every contributor (§3.9), and each node's `provenance` names the adapter that produced it |

- `--adapter <id>` bypasses classification entirely: the named adapter parses
  every record, whatever the markers say. It is the escape hatch, and it is the
  remedy both refusals name.
- **`--adapter auto` is the default, spelled out.** It names the classification
  above and is byte-for-byte the same build as passing no flag at all; it
  exists so a script, a Makefile or a pasted command can *say* what it relies
  on instead of relying on an absent flag meaning something. `auto` is
  therefore a **reserved adapter id**: no adapter may register it, because one
  that did would be unreachable through the flag that names it. There is no
  `mixed` spelling — a mixed input is what `auto` does, not a mode a caller
  selects, and a caller cannot know before reading a file whether it is one.
- **Ambiguity is refused where a guess would be required, and nowhere else.**
  Two adapters claiming one record is unresolvable — they disagree about that
  span's kind, its payloads and its call ids; publishing both parses would
  invent a second span for one operation (§7); and picking one is the
  plausible-but-wrong graph this section exists to prevent. Two adapters
  claiming *different* records is not ambiguity at all: each record has exactly
  one answer.
- **Nothing is claimed by proximity.** A record's classification is a function
  of that record alone, so it cannot depend on input order, on registration
  order, or on how many neighbours matched (§5).
- **A mixed input is not an ambiguous one.** Each record has exactly one
  answer, so nothing is guessed; every join is made on what the telemetry
  stated and never on who parsed it, and an edge whose two ends came from
  different adapters names no adapter (§3.8). Forcing one adapter over such an
  input is still permitted and still builds: the same nodes, some of them
  `unknown`, and without the relations that joined the two dialects.
- **A record's `line_number` counts the input, not the partition.** An adapter
  numbers what it is given (§3.5), and under dispatch it is given a subset, so
  the dispatcher puts each span's number back where its record sat in the
  input. Nothing is serialized from it either way; a diagnostic that points a
  human at a record has to point at the file they have.
- **Both refusals are decided over the whole input, not over a sample.** A
  record carrying two dialects' markers is refused wherever it sits, and an
  input whose first 50 records carry no marker but whose hundredth does is
  built rather than refused. A record's *position* in a refusal message counts
  the records the reader yielded — blank lines skipped and repeats collapsed
  (§7) — which is what `RawRecord.line_number` counts (§3.5).
- The confidence the chosen adapter **declared** is recorded in `meta` as
  `declared_confidence` (§3.9), declared over the first 50 records **it
  claimed** — the adapter's own claim about the input it was given, not a
  measurement, and named so that it cannot be mistaken for one. An adapter that
  claims every record therefore reports the number it reported before this rule
  existed.

> Auto-selection is ergonomics, not evidence: it is the first thing cut if
> Phase 2 slips, in which case `--adapter` becomes required and detection moves
> to Phase 4 (`ROADMAP.md`). The hard-error behavior above is what makes that
> deferral safe — an ambiguous input never silently produces a plausible graph
> from the wrong adapter. What per-record classification changes is the *scope*
> of that refusal: refusing a whole file because one record is ambiguous was
> never its honest scope, and a sample that never reached the ambiguous record
> was never a reason to build.

## 7. Input/output contracts

### Inputs

- **JSONL** (one record per line), a **JSON array** of records, or an **OTLP
  JSON** document. The first two are told apart by the first non-whitespace
  byte; the third is told apart by its first member key, and is specified in
  its own bullet below.
- A **UTF-8 BOM** (`EF BB BF`) at the very start of the input is an encoding
  artifact, not content: it is skipped before the format is detected, so the
  first record reads like any other. Only at the start — the same bytes
  anywhere else are part of a record and are left exactly where they are. The
  input digest is taken over the bytes *as given*, BOM included.
- **Line endings** may be LF or CRLF. The terminator is the LF, a CRLF is one
  line rather than two, and line numbers in diagnostics count lines the way
  the file does under either. A **lone CR is not a terminator**: RFC 8259
  lists it among JSON's inter-token whitespace characters, so `{"a":<CR>1}` is
  one record and a reader that split on it would take a record that parses and
  break it into two that do not. The consequence is stated rather than hidden:
  a CR-only file is **one line**, and one line that long is one
  `malformed_record` carrying its text — a loud refusal, not a silent misread.
- Read from a path or from stdin (`-`).
- **One input = one trace.** If records carry more than one `trace_id`, the
  builder uses the most common one, emits `multi_trace_input`, and keeps the
  foreign records as nodes with a diagnostic. Splitting multi-trace inputs is
  the consumer's call, and `spanweave split` is deferred (`OPEN_QUESTIONS.md` §4).
- **An input may report no trace id at all**, and one that does still builds:
  the graph's `trace_id` is the empty string and a `missing_trace_id` (info)
  says so. It fires whenever the built graph reports no trace id — no record
  carried one, or the id that won the count was itself empty — including an
  input with no records, where the question *why is `trace_id` empty* is still
  owed an answer. **One diagnostic per graph, never one per record**: the fact
  is about the input as a whole, it has no node to point at, and a per-record
  form would repeat one sentence once per span while adding nothing. **And
  only then**: a record carrying no trace id among records that do is *not*
  diagnosed — that graph has a trace id, and nothing about it is missing.
  Nothing is invented — the library never synthesizes a trace id.
- **A record that appears more than once is read once.** At-least-once export
  and collector retries put the same record in a file twice; keeping both
  would publish two nodes for one operation, and an invented span is worse
  than a missing one because nothing downstream can tell. The reader keeps the
  **first** copy, skips the rest, and emits one `duplicate_record` (info) per
  distinct record that was duplicated, carrying that record and how many
  copies were seen.
  - **"The same record" is decided on the parsed record, not on its bytes.**
    What the library preserves is the parsed value (`RawRecord.source`, §3.5);
    whitespace and key order never reach a node, so two lines that parse equal
    are indistinguishable everywhere downstream and collapsing them loses
    nothing. A bytes-level rule would also have nothing to say about the JSON
    array form, where a record has no bytes of its own. Records are compared
    by their **canonical digest** (§3.6): the SHA-256 of
    `json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`,
    encoded UTF-8. §3.6 states the arguments exactly and why.
  - **Which copy is kept is stated so that it is a rule rather than an
    accident**, but it is not observable: the copies are equal as parsed
    records, so the only thing that distinguishes them is
    `RawRecord.line_number`, which is not serialized (§3.5). Reordering the
    input therefore changes nothing, including the diagnostics — the reports
    are emitted in canonical-digest order, not in the order the copies
    appeared.
  - Two records that differ **anywhere**, including two that share a span id,
    are both kept. That is §3.6 rule 3's case, not this one.
- **No interpreter setting is load-bearing for what a graph says.** The
  library's digit limit (4300 digits, §5.3) decides whether an integer literal
  is read at all, whether a quoted one is read as a timestamp (§3.1), and
  whether an OTLP `intValue` is folded to an integer or carried verbatim as
  its decimal string (below). It is a constant, applied by counting digits, so
  the interpreter's own integer-string limit — `PYTHONINTMAXSTRDIGITS` and its
  equivalents — changes none of those answers.
- **Input that will not parse never raises out of the reader or an adapter**
  (`SECURITY.md`): a record that is malformed *or nested deeper than the JSON
  parser will recurse* becomes a `malformed_record` diagnostic carrying its
  text and the read continues, and the same inside a payload attribute becomes
  `payload_parse_failed` with the text kept verbatim.
  - **That holds for every reading path, including the CLI's own.**
    `spanweave inspect` decides whether its argument is a built graph or a
    trace by reading it, and `spanweave validate` reads a graph file the same
    way; both report an unreadable file and exit non-zero. Deep nesting is
    reported as `RecursionError` rather than as a `ValueError` — a different
    exception for the same fact — so a guard that names only the second is a
    guard that is not there.
  - **`validate` refuses what `build` refuses to write.** Python's JSON parser
    reads the bare tokens `NaN`, `Infinity` and `-Infinity`, which RFC 8259
    does not define (§3.1); the encoder this library writes with refuses them
    (*Outputs*, below). A graph document carrying one is therefore a document
    this library could not have produced and a strict parser on the other end
    cannot read, so `spanweave validate` parses with those constants refused
    and reports such a file as not valid JSON — the same finding, and the same
    exit code, as a syntax error. The alternative is worse than a gap: a
    `validate` that reads the tokens its own encoder will not write blesses a
    file `build` would refuse, and the two commands disagree about one file
    while both say they are about well-formedness.
  - **`inspect` is not `validate`, and does not make that check.** It
    summarizes what it is handed and never encodes anything, so a graph
    document holding a bare `NaN` — or any other shape `build` could not have
    produced — is summarized rather than refused. That is the division of
    labour rather than an oversight: `inspect` answers *what is in this file*,
    `validate` answers *is this file a well-formed graph*, and folding the
    second question into the first would make the summary command the
    gatekeeper for a document nobody asked it to judge.
  - **Writing is contained too, and how much room it has is the
    interpreter's answer rather than this library's.** What is fixed is
    *position*. A value the reader met two containers into a trace record —
    the record, its `attributes` — is met by the encoder six containers into
    the graph document: `nodes`, the node, `raw`, `source`, `attributes`.
    **Four levels, and those four levels are the whole of the offset.**
    Whether they cost anything depends on which of `json.loads` and
    `json.dumps` gives out first, and **that is a property of the
    interpreter and of the container shape, not of this library.** Measured
    2026-09-11 on Linux x86-64, one fresh process per measurement, under this
    library's own `dumps` arguments, with `sys.getrecursionlimit()` 1000
    throughout — which bounds neither, because both draw on a C stack budget:

    | CPython | nesting | `json.loads` | `json.dumps` | |
    |---|---|---|---|---|
    | 3.11.15 | dicts, lists | 992 | 992 | coincide |
    | 3.12.3 | dicts, lists | 9997 | 9997 | coincide |
    | 3.13.14 | dicts, lists | 9998 | 9998 | coincide |
    | 3.14.6 | **dicts** | ~40,100 | ~37,240 | encoder gives out ~2,900 levels first |
    | 3.14.6 | lists | ~40,110 | ~74,480 | encoder has ~34,000 levels spare |

    3.14's figures are given approximately on purpose: it tests the actual C
    stack pointer, so repeating the measurement in a fresh process moves each
    number by tens of levels, and enlarging the environment block moved them
    by about 170. **A graph document is nested dicts at every level**, so
    3.14's dict row is the row that applies to it, and on that interpreter the
    encoder is the shallower of the two. On 3.11, 3.12 and 3.13 the two
    coincide and the four positional levels are the entire band: measured end
    to end on 3.12.3, a record whose attribute nests to 9993 is read and the
    graph holding it is writable only to 9991. **No row of this table is a
    universal and none of it is a promise** — the next release, another build,
    or an embedder that resizes the stack moves every number in it, and three
    successive attempts to state this quantity as a fact about the library
    each measured one interpreter and were falsified on another (`TASKS.md`,
    the September 2026 audit's open threads).
    **The containment stays regardless**, for reasons that do not depend on
    which of the two an interpreter gives you: the depth at which either
    gives out belongs to the interpreter and not to this library — it moves
    between builds and an embedder can move it — the encoder's input is not
    only what the reader parsed, and a `RecursionError` arriving at a caller
    is an interpreter's traceback rather than a routable code (§3.10). Where
    something can be dropped without losing it, it is: an adapter that cannot
    render a structured attribute back to text reports `payload_parse_failed`
    and leaves the value in the record (§3.3). Where nothing can be — a
    node's verbatim source record is verbatim or it is nothing — the library
    **refuses**, with `graph_not_serializable` (§3.10). It never writes a
    partial graph.
    - **The reader meets the encoder too, and it is the same refusal.** The
      bullet above says input that will not *parse* never raises out of the
      reader. Some of what the reader does is an **encode**: duplicate
      detection digests every record with `json.dumps` (§3.6), and where the
      encoder is the shallower of the two ceilings that call meets a record
      the parser was willing to read. So a record can be readable and still
      have no digest — and a record with no digest has no identity (§3.6) and
      could not have been written either, which makes it the case §3.10
      already names: nothing can be dropped to get past it, so the library
      **refuses**, with `graph_not_serializable`. It is the same code the
      write side raises for the same value, because it is the same fact about
      the same record.
      **The depth at which this begins belongs to the interpreter; the
      outcome does not.** Measured 2026-09-11 on CPython 3.14.6, attribute
      nesting, end to end through `spanweave.build`, against a digest
      ceiling bisected at ~37,230 and a parser ceiling at ~40,100 in the same
      process: 36,840 builds and writes, 37,640 and 38,670 are the
      `graph_not_serializable` refusal, and 40,500 is the `malformed_record`
      this bullet promises. On 3.11, 3.12 and 3.13 the two
      ceilings coincide, so the middle band is empty and every depth past the
      ceiling is a `malformed_record`. **No depth here is a promise**; what
      is promised is that every depth on every interpreter is one of those
      three outcomes and none of them is a `RecursionError`. Until R19 the
      middle band raised a bare one out of `spanweave.build` — an
      interpreter's traceback where §3.10 promises a routable code — and it
      was stated here as a defect against this rule rather than an exception
      to it.
  - **What it writes is RFC 8259 JSON, so a non-finite number is not
    writable at all.** The encoder runs with `allow_nan=False`. `Infinity`,
    `-Infinity` and `NaN` are Python's extension to JSON rather than JSON, and
    a strict parser on the other end rejects a document carrying one — which
    makes writing it the worst outcome available, because the graph is
    produced, looks written, and cannot be read back. No field the library
    normalizes can hold one (§3.1 does not read a non-finite timestamp), so
    the only way one reaches the encoder is inside a node's verbatim source
    record — the case just above, where nothing can be dropped — and it is the
    same refusal for the same reason.
    - **A value that refers back to itself is refused too, and is said to be
      that.** `json.dumps` reports a cycle and a non-finite number with the
      same exception type, so the refusal states which of the two it actually
      found rather than whichever is more common. Nothing the reader parses
      can hold a cycle — JSON has no way to write one — so a cycle reaches the
      encoder only from a graph a caller assembled in memory, and a refusal
      that misnamed it would send that caller looking for a number that is not
      there.
- **OTLP JSON** (`ExportTraceServiceRequest`: an object whose `resourceSpans`
  is a list) is a third **container**, not a dialect. The spans inside it are
  in whatever dialect their instrumentor speaks — possibly two dialects in one
  export — so the envelope is unpacked here and the records that come out are
  classified per record like any others (§6.1). No adapter is written for OTLP
  JSON, and one would re-create the failure §6.1 exists to prevent: it would
  have to answer the dialect question for a whole file, one level below the
  place that can answer it at all.
  - **One span, plus the envelope above it, is one record.** Nine keys are
    renamed to the record shape the adapters read — `traceId`, `spanId`,
    `parentSpanId`, `name`, `startTimeUnixNano`, `endTimeUnixNano`,
    `status.code`, `status.message`, `attributes` — one of those is folded, and
    **every other key of the span is carried under its own OTLP name**, where
    `unmapped_attributes` names it. `kind` is one of those: no dialect reads an
    OTLP `SpanKind`, and mapping one onto a `NodeKind` would be an
    interpretation made below the adapter seam, by the one layer forbidden to
    have one.
  - **`parentSpanId` is renamed like the other eight, empty string and all.**
    A root span's `parentSpanId` is a proto3 `bytes` field holding its default,
    which a marshaler may omit or may write as `""` — both are conformant, and
    an export that writes it puts `""` on every root it carries. The reader
    normalizes neither rendering away: it renames the key and leaves the value,
    because deciding that an empty reference is *no* reference is a statement
    about the dialect's field and belongs to the layer that owns the field. The
    adapters make it, and a root therefore draws no `orphan_parent` (§4.0).
  - **`attributes` is folded** from OTLP's `[{"key", "value"}]` list to an
    object, unwrapping each `AnyValue` by its tag: `stringValue`, `boolValue`,
    `doubleValue`, `arrayValue`, `kvlistValue` (folded by this same rule),
    `bytesValue` as the base64 string it already is, and an `AnyValue` with no
    field set as `null`. `intValue` arrives as a decimal string, as proto3 JSON
    encodes every `int64`, and is read as the integer it declares itself to
    be — unless that string is longer than the library's digit limit (4300
    digits, §5.3), which no `int64` is, in which case it is carried verbatim
    as the string it arrived as rather than raised out of the reader:
    **where the format states a type, the reader honours it; where the format
    states only a name, the value goes to the layer that owns the field.**
    `startTimeUnixNano` states only a name, so it is carried verbatim and read
    by §3.1's rule for a numeric string — the rule written for this encoding.
    A repeated key keeps the last, and every entry the fold could not take —
    a non-object entry, a missing or non-string `key`, an unrecognized `value`
    tag, and **both** copies of a repeated key — is kept in a list under
    `attributes_unfolded`, which is omitted when there is nothing to put in it.
  - **A conformant export draws one `timestamp_unit_suspect` per span** (§3.7),
    and that is the expected output rather than a defect report.
    `startTimeUnixNano` states a unit, but it states it in a *name*, so the
    value is carried verbatim and §3.1's ceiling is over the line on every
    span. The warning is a statement about the **model's field contract** —
    `started_at` is unix seconds — and not about the telemetry, which is as
    conformant as its field name says. **Nothing is rescaled**: the reported
    number is kept exactly (§3.1), so no digit is lost and every edge is still
    built from what the export wrote. A rescale here is refused outright, and
    not on a technicality — `float()` at epoch-nanosecond magnitude has a
    spacing of 256 ns (§3.1's figure), so it would merge spans the record kept
    apart and make the normalized field disagree with `raw.source` with nothing
    to report it.
    The cost of leaving it is stated rather than softened: on such a file the
    diagnostic is a function of a format the consumer already knows, and a span
    genuinely encoded in seconds among nanosecond neighbours is the one span it
    is *silent* about. A consumer that does not want it filters one code and
    loses nothing it could have used. Stating a unit at the seam was weighed
    against that and held (`OPEN_QUESTIONS.md` §17).
  - **`status.code`** becomes `"UNSET"`, `"OK"` or `"ERROR"`, read from the
    proto enum name (`STATUS_CODE_OK`) or its number (`0`, `1`, `2`), because
    proto3 JSON permits either. Any other value is carried verbatim, read as
    `UNSET`, and survives in the record.
  - **Resource and scope are preserved, not dropped.** Each record carries
    `resource_spans` — its `ResourceSpans` entry without `scopeSpans` — and
    `scope_spans` — its `ScopeSpans` entry without `spans` — verbatim, and each
    is omitted when that level carries nothing but its children. They are
    **not** merged into the span's `attributes`: that would fabricate
    attributes no instrumentor wrote, and a resource attribute could change
    which adapter claims the span (§6.1).
  - **An envelope level with no spans is not a discard**: it is yielded as a
    record of its own and becomes an `unknown` node carrying it, exactly as any
    other record the library cannot read as a span does.
  - **Reading it needs the whole input**, as the JSON array form does and for
    the same reason: a document is not a record until its closing brace. The
    reader buffers only when the input's first member key is `resourceSpans`;
    if what it buffered is not a single document — a file of one export per
    line is a real artefact, and it begins with the same bytes — it is read
    line by line as before, and each line that is an envelope is unpacked the
    same way. A JSON array of envelopes is unpacked element by element for the
    same reason.
- A dialect-specific binary form (OTLP protobuf) is Phase 4 and lives behind an
  optional extra — never in core (`ENVIRONMENT.md`).

### Outputs

- **Graph JSON**, `schema_version` at the root, canonical encoding per §5.2.
  Root keys: `schema_version`, `trace_id`, `meta`, `nodes`, `edges`,
  `diagnostics`, `annotations`.
  **Unfrozen until Phase 4** — deliberately later than the `0.9.x` launch,
  because publishing is reversible and freezing is not (`ROADMAP.md`).
  Additive-only once frozen, with a version bump for any breaking change
  (`CLAUDE.md` 7).
- **Human summary** (`spanweave inspect`): counts by node kind, node counts by
  the adapter that produced them (`provenance.adapter_id`, §3.5, with the nodes
  no adapter produced counted under their own label), edge counts by kind and
  warrant, diagnostics grouped by code, payload-availability tallies.
  Informational; not a stable contract.
- **Failures** (stderr): a command that fails prints one line,
  `spanweave <command>: <the failure>`.
  - **A failure the library raised names its code.** When the failure is a
    `SpanweaveError` (§3.10), the line carries that error's `code` in square
    brackets ahead of the message:
    `spanweave build: [graph_not_serializable] the graph could not be encoded: …`.
    Without it §3.10's rule — *match on the code, never on the message* — is
    unfollowable from the one place most callers stand: `adapter_unconfident`
    and `graph_not_serializable` are otherwise both "exit 1 and an English
    sentence", and a script that wants to retry an ambiguous input with
    `--adapter` but fail hard on a graph that cannot be written has nothing to
    branch on but prose. On such a line that bracket is the *whole* of what is
    machine-readable; everything after it is for a human and may be reworded in
    any release.
  - **A failure the library did not raise carries no code, and the CLI adds no
    bracket of its own.** An `OSError` from a file that is not there is the
    operating system's answer, not a refusal this library defines, and it has
    no code in §3.10's table. Printing an invented one would name a contract
    that does not exist, so the line stays exactly as it was — which means it
    stays whatever Python's `OSError.__str__` produced, and that text opens
    with a bracket of the operating system's own:
    `spanweave build: [Errno 2] No such file or directory: '/nope/t.jsonl'`.
    `Errno 2` is the OS's `errno`, not a spanweave code; it is absent from
    §3.10's table and a caller must not match it. When the file it could not
    open does **not exist** and its path is one this project's own documents
    quote — the `fixtures/` corpus, which ships in the source tree and not in
    the installed package — a second, clearly secondary `hint:` line follows it,
    naming where those paths resolve from. The first line is byte-for-byte
    unchanged by the presence of the second, and the exit code is unchanged.
    Both lines are prose for a human, and neither is a matching surface: what
    a caller matches on is a code from §3.10's table, and this failure has
    none. Hence the rule's positive form — **the code, if there is one, is the
    bracket immediately following `spanweave <command>: `, and its contents are
    one of §3.10's values**. A caller routing on a code matches against that
    closed set; *the line carries a bracket* is not the test, because this one
    does.
- Output goes to stdout / files **only**. Core never opens a network connection.

### Invocation

```
spanweave build <trace> [--adapter auto|ID] [-o graph.json] [--no-temporal]
spanweave inspect <trace|graph.json> [--adapter auto|ID]
spanweave validate <graph.json>
spanweave adapters
spanweave --version
```

### Exit codes

| Exit | Meaning |
|---|---|
| `0` | the command did what it was asked |
| `1` | a refusal: the library raised (§3.10), a file could not be read, or a graph did not validate |
| `2` | a usage error — argparse's, chosen by argparse and not by this library |

**`1` is deliberately not subdivided.** An exit status answers *did it work*,
and a caller that needs to know *why* reads the bracketed error `code` on
stderr (*Failures*, above), which is the thing §3.10 makes a contract. Splitting
`1` into a family of numbers would create a second contract that says less than
the first — 8 bits, no room to add a cause, and nothing to say about the
failures that carry no code at all — and it would have to be frozen alongside
it. A raised refusal and an unreadable file exit the same way on purpose: from
outside, both mean *there is no graph*.

## 8. Annotation API

Consumers attach their own meaning without forking the model.

```
graph.annotate(node_id, namespace, key, value) -> Graph     # returns a NEW graph
graph.annotate_many(entries) -> Graph                       # one new graph for a batch
graph.annotations_for(node_id, namespace) -> Mapping
graph.nodes(annotated=(namespace, key, value)) -> tuple[Node, ...]
```

- Annotations are **namespaced by consumer** (`"trifecta_lens"`, `"my_evals"`).
  The library reserves the `spanweave` namespace and writes nothing into it in v1.
- Annotation is **immutable**: it returns a new `Graph`; the original is
  unchanged. This is what keeps determinism and pipelines composable.
- Annotation values must be JSON-serializable.
- `annotate_many` takes an iterable of `(node_id, namespace, key, value)`
  entries and returns **one** new graph carrying all of them. It is *defined*
  as applying `annotate` to each entry in order, and its result MUST equal that
  sequence's result — including when two entries name the same
  `(namespace, node_id, key)`, where the later entry wins exactly as annotating
  the same key twice does. It grants no ability `annotate` does not have; it
  exists so a consumer labeling a whole graph pays for one copy instead of one
  per label. An empty batch returns a new graph equal to the original.
- An entry `annotate` would refuse — reserved or empty namespace, a node this
  graph does not hold, a value that is not JSON-serializable — is refused by
  `annotate_many` in the same way, at the first such entry, and no graph is
  returned. A batch produces a graph or raises; it never applies part of itself.
- Annotating copies the **annotations**, not the nodes and edges: the new graph
  shares its node and edge lookup structures with the graph it came from, which
  nothing ever mutates. The cost of annotating is therefore proportional to the
  number of annotations, not to the size of the graph, and a graph that has been
  annotated is indistinguishable from one built with those annotations from the
  start.
- Annotations round-trip through serialization under a top-level `annotations`
  key, sorted by `(namespace, node_id, key)`. So a value the library could
  write but not read back is refused when it is annotated, not when the file
  is read: an integer anywhere in the value — at the top, as a dict value, as
  a list item, at any depth — of more than the library's digit limit (4300
  digits, §5.3; the sign is not a digit) is refused by `annotate` and
  `annotate_many` as a value that is not JSON-serializable, under every
  interpreter setting. An integer of 4300 digits or fewer is written whole and
  read back equal.
- The library **never reads** an annotation to change its own behavior. It has
  no opinion about what is in there — that is the whole point.

A consumer's semantic layer (e.g. a security tool's role catalog) is exactly one
labeling function over this API, living in the consumer's repo.

## 9. Non-goals — permanent, not parked

These are not a backlog. Implementing any of them in core is a defect, however
well-implemented.

- **Semantic roles.** Source / sensitive / sink / trusted / untrusted. Consumer's.
- **Severity, risk, or security findings** of any kind.
- **Inferred data flow** — value matching, taint, similarity, "probably fed."
- **Money.** Token counts yes; prices, rate tables, currency no.
- **Quality/eval scoring**, hallucination detection, rubric grading.
- **Retry / loop / anomaly *detection*.** The structure that makes these
  computable is exposed; the judgement is not made.
- **Redacting or mutating payloads.** The library marks what the source marked.
- **Storage, indexing, a server, a UI.**
- **Enforcement or runtime interception.**
- **Network access from core** — including reading a remote trace URL, including
  an OTLP receiver. A file-tailing mode would not renegotiate this; a listener
  would, and that is a deliberate future decision, not a drift (`ROADMAP.md`).
- **Execution or unsafe deserialization of trace content** (`SECURITY.md`).

Deferred (not permanent, but not now): §4.3 richer causal edges from frameworks
that emit real dataflow, streaming/tail mode, cross-trace stitching, OTLP
protobuf. See `ROADMAP.md` north star.
