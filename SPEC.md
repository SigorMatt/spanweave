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
  operation:   str | None      # tool name / model name / retriever name
  started_at:  float | None    # unix seconds; None if the dialect omits it
  ended_at:    float | None
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
  adapter_id:      str        # e.g. "openinference"
  adapter_version: str
  dialect_note:    str | None # anything the adapter wants a human to know
```

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
2. Otherwise the node id is `sw_` + the first 16 hex chars of
   `sha256(adapter_id + "\x00" + trace_id + "\x00" + source_key)`, where
   `source_key` is the adapter-supplied stable key (falling back to the 1-based
   record index).

**Python's built-in `hash()` is forbidden anywhere in identity or ordering** — it
is salted per-process and would break determinism (`CLAUDE.md` 4).

Id collisions within a trace are a **hard error**, not a silent overwrite.

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
| `payload_parse_failed` | JSON mime type but the value did not parse |
| `orphan_parent` | `parent` reference to a span not present in the trace |
| `unpaired_call` | a requested tool call with no fulfilling span |
| `unpaired_result` | a tool result with no requesting call |
| `missing_timestamp` | no start time; temporal edges omitted for this node |
| `nonmonotonic_time` | `ended_at` precedes `started_at` |
| `duplicate_source_id` | two records claimed the same source id |
| `multi_trace_input` | more than one trace id in a single input (§7) |
| `malformed_record` | an input line that is not valid JSON; its text is kept here |
| `ordering_cycle` | the ordering edges contain a cycle (§5.2); the graph is still built |

`unmapped_attributes` records attribute **keys only**, never values — the values
are already preserved verbatim in `RawRecord`, and duplicating payload content
into diagnostics is an unnecessary exposure surface.

### 3.8 Edge

```
Edge:
  src:     NodeId
  dst:     NodeId
  kind:    EdgeKind        # §4
  warrant: explicit | derived      # §4.1
  basis:   str             # the exact rule/field that produced it
  adapter: str | None      # who asserted it, when adapter-supplied
```

`basis` is a short, stable machine-and-human readable string naming the *reason*:
`"span.parent_span_id"`, `"tool_call_id"`, `"sibling start_time ordering"`.
It is what lets a consumer audit an edge instead of trusting it.

Edges are **unique** on `(src, dst, kind, basis)`. Duplicates are collapsed.
The same pair MAY be connected by several edges of different kinds; that is
normal and informative.

### 3.9 Graph

```
Graph:
  trace_id:    str
  nodes:       ordered mapping NodeId -> Node      # topological, tie-broken (§5.2)
  edges:       sorted tuple[Edge, ...]             # sorted (§5.2)
  diagnostics: sorted tuple[Diagnostic, ...]
  annotations: AnnotationStore                     # §8
  meta:        Meta
```

```
Meta:
  schema_version:   str        # "1" once frozen; "0.x" until then
  spanweave_version: str
  adapters:         tuple[AdapterInfo, ...]   # id + version + confidence, sorted
  source_digest:    str | None # sha256 of input bytes, when built from a file
  node_count / edge_count / diagnostic_count: int

AdapterInfo:
  id:         str
  version:    str
  confidence: float | None     # from detection; None when named with --adapter
```

`AdapterInfo.confidence` is where §6.1's "the chosen adapter and its confidence
are recorded in `meta`" lands. It is `None` when the caller named the adapter,
because there was no detection to report.

`source_digest` fingerprints the **input bytes**, not the graph. Shuffling the
input therefore changes it while the graph itself stays identical — which is
the correct behavior, and why §5.2's order-independence claim is about the
graph rather than about this field.

`meta` MUST NOT contain a build timestamp, a hostname, a username, or a file
path. Those would break byte-identical determinism and leak the operator's
environment.

## 4. Edge kinds — the centerpiece

A **closed** enum. Adding one is a spec change (halt point).

| Kind | Direction | Meaning | Allowed warrant |
|---|---|---|---|
| `parent` | parent → child | span containment as reported by the tracer | `explicit` only |
| `call_result` | requesting op → fulfilling op | a tool call and the span that answered it, joined by an id | `explicit` only |
| `data` | producer → consumer | an output feeds an input | `explicit` only |
| `link` | source → linked | an OTel span link (often cross-trace) | `explicit` only |
| `temporal` | earlier → later | one operation started before another | `derived` only |

`link` is the one kind whose `dst` may name a span that has **no node in this
graph**: links are routinely cross-trace, and requiring the target to be
present would make the kind useless for the case it exists to describe. A
consumer that only wants intra-trace structure filters on kind, which it is
already doing.

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
producer→consumer relation (some frameworks do). `spanweave` will not compare an
output string to an input string and conclude a flow. That comparison needs a
threshold, a normalization rule, and an encoding policy — none of them
opinion-free — and shipping one default set of those choices would be closer to
semantics than anything else in the library (`CLAUDE.md` 1).

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

The transitive closure is available to consumers via `graph.reachable(...)`;
it is not materialized in the edge set.

### 4.4 `call_result` pairing

Tool call/result pairing is the single most valuable thing a dialect-aware
adapter can recover, and it is frequently **not** the parent/child relation.

- Adapters SHOULD emit a `call_id` on requesting and fulfilling spans when the
  dialect carries one (`tool_call_id`, `function_call_id`, or equivalent).
- The builder joins on `call_id` within a trace and emits `call_result` with
  `basis = "tool_call_id"`.
- Unmatched calls/results produce `unpaired_call` / `unpaired_result`
  diagnostics — never a fabricated pairing, and never a fallback to guessing by
  name or proximity.

## 5. Determinism

### 5.1 Guarantee

Same input bytes + same adapter version + same `spanweave` version → **the same
graph, byte-for-byte** on serialization, on any machine.

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
- No clocks, no randomness, no `hash()`, no set iteration order, no
  dict-insertion-order dependence in any output-affecting path.

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
  started_at / ended_at: float | None
  status:      Status
  status_note: str | None
  inputs / outputs: Payload
  usage:       Usage | None
  call_id:     str | None         # for call_result pairing (§4.4)
  call_role:   requester | fulfiller | None
  links:       tuple[SpanLink, ...]
  data_edges:  tuple[DeclaredDataEdge, ...]   # explicit only (§4.2)
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
2. **Never drop silently.** Unrecognized attributes go in `unmapped`; the whole
   record is preserved in `raw`.
3. **Never interpret.** No roles, no severity, no scoring, no redaction of
   content the source did not redact.
4. **Never raise on bad input.** Malformed records produce diagnostics.
5. **Explicit warrants only.** An adapter may assert `parent`, `call_result`,
   `data`, `link` — all `explicit`, all traceable to a source field named in
   `basis`. Adapters MUST NOT emit `temporal` edges; those are the builder's.

### 6.1 Adapter selection

`spanweave build` runs `detect()` on a bounded sample (the first 50 records) of
every registered adapter and picks the highest confidence.

- Ties, or a top score below `0.5`, are a **hard error** with an actionable
  message listing the scores — never a silent fallback to a default adapter.
- `--adapter <id>` bypasses detection entirely and is the escape hatch.
- The chosen adapter and its confidence are recorded in `meta`.

> Auto-selection is ergonomics, not evidence: it is the first thing cut if
> Phase 2 slips, in which case `--adapter` becomes required and detection moves
> to Phase 4 (`ROADMAP.md`). The hard-error behavior above is what makes that
> deferral safe — an ambiguous input never silently produces a plausible graph
> from the wrong adapter.

## 7. Input/output contracts

### Inputs

- **JSONL** (one record per line) or a **JSON array** of records. Detected by
  first non-whitespace byte.
- Read from a path or from stdin (`-`).
- **One input = one trace.** If records carry more than one `trace_id`, the
  builder uses the most common one, emits `multi_trace_input`, and keeps the
  foreign records as nodes with a diagnostic. Splitting multi-trace inputs is
  the consumer's call, and `spanweave split` is deferred (`OPEN_QUESTIONS.md` §4).
- A dialect-specific binary form (OTLP protobuf) is Phase 4 and lives behind an
  optional extra — never in core (`ENVIRONMENT.md`).

### Outputs

- **Graph JSON**, `schema_version` at the root, canonical encoding per §5.2.
  **Unfrozen until Phase 4** — deliberately later than the `0.9.x` launch,
  because publishing is reversible and freezing is not (`ROADMAP.md`).
  Additive-only once frozen, with a version bump for any breaking change
  (`CLAUDE.md` 7).
- **Human summary** (`spanweave inspect`): counts by node kind, edge counts by
  kind and warrant, diagnostics grouped by code, payload-availability tallies.
  Informational; not a stable contract.
- Output goes to stdout / files **only**. Core never opens a network connection.

### Invocation

```
spanweave build <trace> [--adapter ID] [-o graph.json] [--no-temporal]
spanweave inspect <trace|graph.json>
spanweave validate <graph.json>
spanweave adapters
spanweave --version
```

## 8. Annotation API

Consumers attach their own meaning without forking the model.

```
graph.annotate(node_id, namespace, key, value) -> Graph     # returns a NEW graph
graph.annotations_for(node_id, namespace) -> Mapping
graph.nodes(annotated=(namespace, key, value)) -> tuple[Node, ...]
```

- Annotations are **namespaced by consumer** (`"trifecta_lens"`, `"my_evals"`).
  The library reserves the `spanweave` namespace and writes nothing into it in v1.
- Annotation is **immutable**: it returns a new `Graph`; the original is
  unchanged. This is what keeps determinism and pipelines composable.
- Annotation values must be JSON-serializable.
- Annotations round-trip through serialization under a top-level `annotations`
  key, sorted by `(namespace, node_id, key)`.
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
