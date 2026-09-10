# Changelog

Notable changes, newest first. Entries are written when the change lands, not
at release time.

This file starts at the September 2026 audit-fix series. The `0.9.0` and
`0.9.1` releases predate it and are **not** reconstructed here: an invented
history is worse than an absent one, and their content is in git.

The format is loosely [Keep a Changelog](https://keepachangelog.com/); the
project follows semantic versioning with the caveat that the serialized graph
shape is **unfrozen until Phase 4** (`ROADMAP.md`).

## [Unreleased]

### Added

- **An OTLP JSON export is now read, as a third container format rather than
  as a dialect.** `resourceSpans[].scopeSpans[].spans[]` is unpacked in the
  reader into one flat record per span, so the spans inside it are classified
  per record like any others -- which is the point: an export carries whatever
  its instrumentors emitted, possibly two dialects at once, and an `otlp_json`
  *adapter* would have had to answer the dialect question for a whole file,
  one level below the place that can answer it (`OPEN_QUESTIONS.md` §16).
  Until now a compact export built **one `unknown` node** holding the entire
  file under a forced adapter and was refused by detection, and an indented
  one -- what a file receiver writes -- produced **46 `malformed_record`
  diagnostics and no nodes**. Nine span keys are renamed, `attributes` is
  folded from OTLP's `KeyValue` list into an object, and **every other key is
  carried under its own OTLP name**, where `unmapped_attributes` reports it:
  the reader never drops an OTLP key and never invents one. `kind` is one of
  those carried keys and deliberately so -- no dialect reads an OTLP
  `SpanKind`, and mapping one onto a `NodeKind` would be an interpretation
  made below the adapter seam. Resource and scope are preserved beside the
  span under `resource_spans` / `scope_spans` rather than merged into its
  attributes, because a merged resource attribute could change which adapter
  claims the span. `intValue` is decoded from the decimal string proto3 JSON
  writes it as, because the format states a *type* there; `startTimeUnixNano`
  is **not**, because it states only a *name* and `SPEC.md` §3.1's rule for a
  numeric string -- written for this encoding -- owns that field. New
  conformance scenario `otlp_container`: `llm_tool_llm`'s run packed as an
  export once per dialect, sharing that scenario's `expected/graph.json`
  **byte for byte**. **No existing input changed**: both new branches are
  gated on the key `resourceSpans`, which no trace in this tree carries, and
  all 64 traces in the tree serialize byte-identically across the change.
  (audit finding "minor: OTLP JSON envelope refused"; `SPEC.md` §7)

- **`--adapter auto` names the default, and `spanweave inspect` says which
  adapter produced which nodes.** `auto` is the classification that already
  happens with no flag -- byte for byte the same build -- so a script or a
  pasted command can state what it relies on instead of relying on an absent
  flag meaning something. It is resolved at the CLI, which makes `auto` a
  reserved adapter id (`ADAPTERS.md` §4). There is deliberately **no `mixed`
  mode**: a mixed input is what `auto` does, not a mode a caller selects, and
  nobody can know before reading a file whether it is one. `inspect` gains a
  `nodes by adapter:` tally, reading `provenance.adapter_id` -- the one thing
  the `adapters:` line could not say, since it named every contributor but
  never the split -- with the nodes no adapter produced counted under
  `(no adapter)` rather than folded into the dialect that read the rest.
  (audit finding 1, the surface half; `SPEC.md` §6.1, §7)

- **A trace whose records come from two instrumentors now builds as one
  graph.** The builder takes spans from several adapters at once: each adapter
  parses the records it claimed, an `AdapterInfo` travels beside each span,
  and `meta.adapters` carries every contributor with the confidence **it**
  declared over the records **it** claimed. Until now such an input was
  refused, and the remedy the refusal named -- force one adapter -- silently
  lost every relation that joined the two dialects: on the new
  `mixed_instrumentation` fixture, two of seven edges, both of them the
  `explicit` ones (`call_result` and `data`), while payloads reported `absent`
  where content had been emitted and the graph still looked complete. The node
  count is the same either way, which is what made the loss quiet, and a test
  pins that equality beside the edges. (audit finding 1, the build half;
  `SPEC.md` §6.1, §3.9)

  The acceptance test is an equality between two scenarios: the mixed
  rendering's canonical graph **is** `llm_tool_llm`'s, whose expected
  `graph.json` it shares byte for byte. The builder joins on what the
  telemetry stated and never on who parsed it, so nothing about a relation
  depends on the partition.

- **`Provenance.adapter_id` and `adapter_version` are now `str | None`, and a
  record no adapter claims becomes an `unknown` node plus a new
  `unclaimed_record` warning.** It is never handed to a designated adapter:
  that would put a dialect's name on a node on the strength of that dialect
  having said nothing about the record, and provenance is the one field whose
  whole job is to say who read this. The node carries the record verbatim and
  nothing normalized -- nobody read it, so nothing in it has been read. **This
  moves the serialized graph** (`tests/serialized_shape.json` regenerated:
  the two `Provenance` types, and the new code in the diagnostic vocabulary);
  the schema is unfrozen and this is the window in which the change is a minor
  release rather than a migration (`CLAUDE.md` 7). (`SPEC.md` §3.5, §3.7, §6.1)

- **`Edge.adapter` is `null` when the edge's two ends came from different
  adapters.** Naming either dialect would attribute to it a relation the two of
  them made together; `null` is the value the field already carries for every
  `temporal` edge. An end that is not a node in this graph -- a `link` pointing
  outside the trace -- is not consulted, so a dangling link still names the
  adapter of the span that stated it. (`SPEC.md` §3.8)

- **Conformance scenario `mixed_instrumentation`.** `llm_tool_llm`'s run,
  described half by each instrumentor in one file, every record verbatim from
  that scenario's two renderings. Its single rendering is named for both
  adapters that read it (`openinference+otel_genai.jsonl`); `+` is not a
  dialect, is not in `tests/conformance.py`'s `DIALECTS`, and nothing is
  obliged to render a mix (`FIXTURES.md` §4.3.1). Determinism is asserted where
  the new mechanism could reach it: a shuffled mixed trace produces the same
  document **and** the same id-to-record binding.

- **Decided: `duplicate_source_id` keeps reporting the reused span id**, not
  the `source_key` (`OPEN_QUESTIONS.md` §12(f), asked by the E1 memo). Since
  the fallback key became the record's canonical digest, a `source_key`
  collision without a span-id collision is unreachable -- and the message
  reports something *the dialect* did, where a `source_key` is the library's
  own construct. The cross-adapter case dispatch made newly reachable is now a
  test: two adapters reusing one span id keep both records, get two ids from
  the records' own digests, and draw one report. (`SPEC.md` §3.6)

- **A dialect is now decided per record, not per file.** The registry gained
  `classify(record)` -- which adapters claim this one record -- and
  `partition(records)`, which sorts a whole input into them; `spanweave.build`
  partitions above the seam before it parses. Nothing new is asked of an
  adapter: a record is claimed when `detect([record])` reaches the same `0.5`
  floor selection always used, so no marker table lives outside the adapter
  that owns the marker and the builder still never learns a dialect name.

  **A single-dialect input is byte-identical to what it was.** Proven rather
  than asserted: every `*.jsonl` trace in the tree -- 49 committed fixtures and
  14 uncommitted captures -- was serialized before and after and the two
  documents diffed clean, and `tests/test_detection.py` now asserts for every
  corpus and captured trace that the detected path builds exactly what
  `--adapter <id>` builds, which is the path classification does not touch.

  Two things do change, both refusals, and both where a sample used to decide:
  a record carrying **two** dialects' markers is a hard error (`adapter_ambiguous`)
  wherever it sits in the file, naming the record's position, its span id and
  both claimants -- before, a record past the 50-record detection sample was
  parsed by whichever adapter won and the other dialect's meaning went quietly
  into an `unknown` node; and an input whose first 50 records carry no marker
  but whose hundredth does is now built rather than refused. `--adapter <id>`
  still bypasses classification entirely. (audit finding 1, the classification
  half; `SPEC.md` §6.1)

- `ADAPTERS.md` §2: `detect()` must be **decomposable over records** -- a
  sample reaches `0.5` iff one record in it does alone. Both shipped adapters
  already were, to the character; what was missing was the sentence saying an
  adapter may not need a record's neighbours to answer for it.

- **Two `basis` strings that say which declaration of a receipt came first.**
  A conversational protocol resends the whole history, so the tool-result
  message `SPEC.md` §4.2.1 reads as a declaration is re-sent by every later
  turn -- and an `n`-turn agent loop produced `n(n-1)/2` `data` edges that were
  indistinguishable from each other. They still do, and every one of them is
  kept: the count equals the *declaration* count exactly, each declaration is a
  true statement the instrumentor made about that span's own input, and
  suppressing a relation the telemetry states plainly is the failure §4.2 exists
  to prevent. What is new is the rank. For each call id, the spans declaring
  receipt are ordered by `(started_at, node_id)` -- the total order §5.2 already
  defines -- and the basis records it:
  `tool_call_id in tool-result message` for the earliest,
  `... (earliest tied, broken by node_id)` when a `started_at` tie left the
  choice to the library, and `... (not the earliest receiving span)` for every
  later one. A span with no `started_at` sorts last.

  The third string says **only** that an earlier span declared the same
  receipt. It deliberately does not say "echo": two spans genuinely consuming
  one result produce the identical shape, and a protocol resending history is a
  cause this library cannot see. As with §4.3's tie-break, the warrant says the
  relation was stated and the basis says what was determined about it; a
  consumer that does not care matches on `kind`.

  **No stored expectation moved.** Every `data` edge in the corpus and in every
  captured trace was a first receipt -- 24 across 15 captured files, each call
  id received by exactly one span -- so keeping today's string for the earliest
  case leaves all four scenarios that carry one byte-identical. The ranking is a
  function of a *set* of spans, so input order cannot reach it. (audit finding 6,
  the edge half)

- Conformance scenario `receipt_redeclared`, in both dialects: two tool-calling
  turns and a closing turn whose request carries **both** results, so the first
  call's result is declared received a second time. Nothing in the corpus and no
  captured trace had a call id received by more than one span, which is why the
  rank above was exercised by nothing.

- New error `graph_not_serializable` / `GraphNotSerializableError`, raised by
  the one encoder every byte this library writes goes through. The reader
  contains what the *parser* will not descend; the encoder draws on the same
  interpreter budget but meets a value four levels lower down -- inside the
  document, inside a node, inside a payload -- so a payload that arrived at
  the very top of the parser's range could still not leave, and `json.dumps`
  said so with a `RecursionError` from a build that had already read its
  input without complaint. (That band is narrow and interpreter-specific,
  and the sentence above said "the encoder has its own limit" until batch R6
  measured it; `SPEC.md` §7 carries the measurement.) It is a refusal
  rather than a diagnostic because there is nothing to degrade to: the
  offending value may be a node's verbatim source record, and dropping that to
  get past it is the one thing losslessness forbids. Nothing is written and
  nothing is partial. `SPEC.md` §3.10 and §7 state it.
  (audit finding 3, the write half)

- Conformance scenarios `derived_ids` and `derived_ids_shuffled`, in both
  dialects: three tool spans that carry **no span id**, and the same three
  lines reversed. Every node id in them is derived, which nothing in the
  corpus had ever been -- all 177 records carried a span id, so `SPEC.md`
  §3.6 rule 2 was documented, implemented and exercised by no fixture at all.
  The pair also carries the corpus's first assertion that a shuffle keeps each
  id **on its own record**: the two graphs were byte-identical while the ids
  had swapped records, because ids are assigned in node order, so byte
  comparison alone could not see the defect below.

- New diagnostic `timestamp_unit_suspect` (level `warning`). A `started_at` or
  `ended_at` strictly greater than **1e11** cannot be unix seconds -- 1e11
  seconds after the epoch is the year 5138, while *now* in milliseconds is
  ~1.8e12 and in nanoseconds ~1.8e18 -- and nothing said so, which is how a
  nanosecond export reached a consumer looking like a span that ran for
  fifty-four years. It reports the **unit of the field**, never anything about
  the run: the number is kept exactly as reported, nothing is rescaled, and
  every edge is still built from it. **One per node**, not one per value and
  not one per graph: both endpoints of a span share one encoding, so the
  diagnostic names each offending field in its `source` instead of firing
  twice, and it points at a node because an input carrying seconds from one
  exporter and nanoseconds from another is exactly what a per-graph statement
  cannot express. Only the reported values are checked and never a duration --
  a duration is something the library computed, and calling one implausible is
  a claim about the run. `SPEC.md` §3.1 and §3.7 state it. The serialized code
  vocabulary gains one entry, which is additive.
  (audit finding 5, the half that was decidable)

- **Timestamps are read from numeric strings**, in both adapters. OTLP JSON
  encodes 64-bit integers as decimal strings, so `"1700000000"` is a real
  exporter's output -- and it produced `None`, a node with no start time, and
  no temporal edges at all. It is now read as the identical value the same
  literal would have produced unquoted, so the quoted and unquoted renderings
  of one trace build one graph. The rule is deliberately one sentence -- *the
  string, unquoted, would be a valid JSON number* -- rather than a list of
  tolerated spellings: `"+1"`, `" 1700000000"`, `"01"`, `".5"` and
  `"2026-09-05T10:00:00Z"` are all refused, because every tolerated spelling
  is a small normalization and this library performs none. Nothing is
  converted; the value that arrives is the value the node carries.
  `SPEC.md` §3.1 states it, with the accept/reject table.
  (audit finding 5)

- Conformance scenario `timestamp_units`, in both dialects: three spans with
  nanosecond timestamps, one of them reporting a `start_time` in a rendering
  the library does not read. It is the one scenario whose two renderings
  deliberately differ in **encoding** -- nanosecond integers against the same
  values as decimal strings -- because "a quoted timestamp is the same
  timestamp" is a cross-dialect claim and belongs where the corpus can fail on
  it.

- New diagnostic `duplicate_record` (level `info`). At-least-once export and
  collector retries put the same record in a file twice, and the library built
  two nodes for one operation -- an *invented* span, which is worse than a
  missing one because nothing downstream can tell. The reader now reads each
  distinct record once and reports the collapse, carrying the record and how
  many copies were seen. "The same record" is decided on the **parsed** record,
  not on its bytes: the parsed value is what the library preserves
  (`RawRecord.source`), so whitespace and key order never reach a node and
  collapsing two lines that parse equal loses nothing -- and a bytes rule would
  have nothing to say about the JSON-array form, where a record has no bytes of
  its own. The **first** copy is the one kept; which one that is cannot be seen
  in the graph, because the copies are equal and the only field separating them,
  `line_number`, is not serialized. `SPEC.md` §3.7 and §7 state it. The
  serialized code vocabulary gains one entry, which is additive.
  (audit finding 2, first half)

- New diagnostic `missing_trace_id` (level `info`). An input that identifies no
  trace built a graph whose `trace_id` was the empty string and said nothing
  about it -- the one degradation the builder did not report. It now says so:
  once per graph, never once per record, because the fact is about the input as
  a whole, has no node to point at, and would otherwise repeat one sentence
  once per span. It fires whether no record carried a trace id or the id the
  input reported was itself empty, and for an input with no records at all.
  Nothing is invented: an unidentified trace stays unidentified, and a record
  that carries no id in an input where others do is still not diagnosed --
  that graph has a trace id. `SPEC.md` §3.7 and §7 state it. The serialized
  code vocabulary gains one entry, which is additive.
  (audit finding: minor, missing `trace_id` silent)

- `Graph.annotate_many(entries)`, which takes an iterable of
  `(node_id, namespace, key, value)` and returns **one** new graph carrying all
  of them. It is defined as `annotate` applied to each entry in order and equal
  to it, so of two entries naming the same `(namespace, node_id, key)` the later
  one wins, exactly as setting the same key twice does. Every entry is checked
  before any is kept: a refused entry costs the caller the batch, never leaves a
  graph carrying half of it. It grants no ability `annotate` did not have --
  a consumer labeling a whole graph now pays for one copy instead of one per
  label. `SPEC.md` §8 states it. (audit finding 4)

### Changed

- **The write-side depth guard is documented as what it is, and the
  measurement is on the record.** A6 introduced `graph_not_serializable` and
  narrated it as an encoder whose *limit* is lower than the parser's. It is
  not: both draw on one interpreter-wide C recursion budget, and measured
  here on CPython 3.12.3 (Linux, `sys.getrecursionlimit()` 1000, which is not
  what bounds either) `json.loads` and `json.dumps` each give out at **9997
  nested containers**, taken at equal call depth -- a ratio of 1.00, neither
  the lower limit A6 claimed nor the ~1.9x *higher* one the run-2 review
  measured on its own interpreter (`json.loads` 40112, `json.dumps` 74493).
  What is real is **position**: a value the reader meets two containers into
  a trace record is met by the encoder six containers into the graph document
  (`nodes` -> the node -> `raw` -> `source` -> `attributes`), four levels
  further down. Those four levels are the whole gap, so how reachable the
  refusal is depends on the interpreter you are on: measured end to end here,
  a record whose attribute nests to 9993 is read and the graph holding it is
  writable only to 9991 -- a band two levels wide out of ten thousand -- while
  on an interpreter with the review's headroom no trace file reaches it at
  all. **The guard stays**, and the reason no longer rests on the wrong
  mechanism: the depth at which either gives out is the interpreter's and not
  this library's, the encoder's input is not only what the reader parsed, and
  a `RecursionError` reaching a caller is a traceback rather than a routable
  code. `SPEC.md` §7 states it that way, `serialize.py`'s docstring follows,
  and two tests in `tests/test_serialize.py` pin it: one re-measures both
  limits and fails if the encoder ever becomes materially the shallower of
  the two, the other pins the four-level offset to the document's actual
  shape. Documentation only -- no behaviour, no model, no serialized shape
  changed. (run-2 review, the A6 should-fix)

- **The cold reviews are in the repository, and the two concerns that were
  lost with them are open threads again.** Both reviews of the September 2026
  audit-fix series were written to `patches/`, which is untracked, and cited
  from `TASKS.md` as the full text: a clean checkout had the citation and not
  the review. They are now `reviews/2026-09-10-run1.md` and
  `reviews/2026-09-10-run2.md`, copied verbatim -- a directory rather than
  root documents, so the README's document table stays a map of the root.
  Two of run 1's concerns had existed only inside that untracked file:
  **6**, that B1's field test asserts against the *parent* graph, so a future
  `Graph` field derived from `annotations` would go stale and the test would
  still pass, and **7**, that the reader's pre-adapter content dedup can
  collapse two genuinely distinct span-id-less spans while `SPEC.md` argues
  only the other side. Both are now threads 8 and 9 of *Open threads the
  series did not close*, with the review's own text. The sentence that said
  "the review's five other concerns were assigned" -- it enumerated three --
  now says which three, and which two were not. Two `tests/test_doc_truth.py`
  checks keep it that way: a document written to outlive a work series may
  not cite a `patches/` path, and every `reviews/` file a document cites must
  be in the tree. Documentation and tracking only; no behaviour change.

- **The September 2026 audit-fix series is closed, and `WORKPLAN.md` is
  gone.** That file was the series' execution state -- protocol, live batch
  status, decisions log, resume note, finding-to-batch map -- and was written
  to be deleted once the series ended, so that no reader would have two places
  to look up a status and one place to read a stale one. Everything of it that
  outlives the series is now in `TASKS.md` under *September 2026 audit*: every
  batch with its final status and commit, the decisions taken on 2026-09-10,
  the cold review of run 1 with both of its blockers, the finding-to-batch map,
  and -- deliberately kept -- the threads the series did **not** close
  (seven at the close; nine since run 3 recovered two lost concerns, below).
  Its README row is removed with it, the six memo sign-offs in
  `OPEN_QUESTIONS.md` and the `ROADMAP.md` pointer now name `TASKS.md`, and
  `OPEN_QUESTIONS.md` §12(c) and §14 state the provenance of the corpus census
  those memos were decided on: `57 files / 177 records` was a working-tree
  scan that included the git-ignored `capture/_scratch/`, so it does not
  recompute from a checkout -- the **0 records carrying both dialects'
  markers** that the decision rests on is unchanged either way. **No behavior
  changed**; nothing under `spanweave/` moved.
- **A timestamp reported as an integer keeps its digits.** `Node.started_at`
  and `Node.ended_at` are now `int | float | None`: an integer literal, quoted
  or bare, is carried as an `int`, and only a literal with a fraction or an
  exponent becomes a `float`. Both used to end in `float(value)`, and float64's
  spacing at epoch-nanosecond magnitude is **256 ns** -- so two spans a hundred
  nanoseconds apart collapsed onto one number, and the `temporal` edge between
  them was emitted as *tied*, asserting that neither started first when one
  demonstrably did. That is not a losslessness bug (the literal was always
  verbatim in `raw.source`) and not a determinism bug; it is the normalized
  field failing §3.1's own promise, and an edge whose premise was wrong. It
  bit no fixture and no captured trace -- 154 timestamp values, none above
  1e11, none whose float differs from the literal -- but `startTimeUnixNano`
  in OTLP JSON is an integer nanosecond count, so it is the next input rather
  than a hypothetical one.

  This is **not** a unit conversion and not an opinion about the unit: nothing
  is scaled, nothing is inferred, and the number a consumer reads is the number
  the record wrote. It also closes the string/number asymmetry by construction,
  since `json.loads` yields an exact `int` for both renderings and only
  `float()` was spending them. `SPEC.md` §3.1 states the type and §7 carries it
  into the `NormalizedSpan` contract. The serialized field is still a JSON
  number, so the schema is unmoved; the *literal* emitted for an
  integer-encoded input changes, which is why it lands before the Phase 4
  freeze rather than after it. `tests/serialized_shape.json` moves by two type
  lines. (audit finding 5)

- **`timestamp_unit_suspect` now quotes the bound as a whole number**, and its
  `source` carries the value the record wrote. The threshold constant was
  `1e11`, so the message read `exceeds 100000000000.0` -- a float somebody
  chose rather than the year-5138 bound it is -- and the value it printed for
  an integer-encoded time was the nearest float64 to it, which falsified the
  message's own sentence *"every value is kept exactly as reported"* in exactly
  the case the diagnostic exists to report. Both are now true as written. The
  threshold itself is unchanged: `int` and `float` compare exactly in Python,
  so an integer timestamp is tested as written. (audit finding 5)

- **A timestamp the library cannot read is no longer silently absent.** A
  `start_time` in a rendering `SPEC.md` §3.1 does not accept -- an ISO-8601
  string, say -- became a `None` with nothing said, so the value existed in
  `raw` and nowhere a consumer would look. The adapter now names the record
  field in `unmapped_attributes` as `<record>.start_time`, which is that
  code's whole job, and the builder still adds `missing_timestamp`: *we did
  not normalize this field*, and *so this node has no start time*. A field the
  record omits, or reports as `null`, is unchanged -- that is an absence, not
  something the adapter failed to read. `unmapped_attributes` stays keys-only.
  (audit finding 5)

- **Annotating no longer costs a pass over the whole graph.** `annotate`
  rebuilt the node index and both adjacency maps on every call, so labeling was
  O(nodes + edges) *per label* -- 2,000 annotations on a 3,001-node,
  5,999-edge graph took 12.5 s here (33 s on the audit's machine), 85% of it
  inside that rebuild. Nodes and edges are the one thing an annotation cannot
  change, so the new graph now shares those structures with the graph it came
  from instead of rebuilding them: the same 2,000 annotations take 1.5 s, and
  as one `annotate_many` batch, 0.011 s.

  Nothing about the result moved. The graph is still immutable and still a new
  object per annotation; the shared structures are written once at construction
  and only read afterwards, so neither graph can observe the other's
  annotations, and a test walks `dataclasses.fields(Graph)` to prove the
  shared-index copy carries every field a rebuilt graph has. `SPEC.md` §8 states
  the sharing and its consequence for cost. (audit finding 4)

- **Two records claiming the same span id no longer refuse the file.** They are
  both kept, with a node id each, and the `duplicate_source_id` diagnostic that
  `SPEC.md` §3.7 has always described now actually fires. Previously a
  duplicated span id -- something no dialect can prevent, and which an
  at-least-once exporter produces routinely -- raised `DuplicateNodeIdError`
  and cost the consumer the entire trace, while the documented fallback was
  unreachable: both records fell to §3.6 rule 2, whose material *was* the span
  id, so they derived the same id and collided.

  `SPEC.md` §3.6 gains **rule 3**: when two or more records share a source key,
  the record's own canonical digest joins the derivation material. It
  disambiguates on **content, never on position** -- numbering the records
  would make an id depend on where its line sat in the file, and input order
  must not affect the result. Rules 1 and 2 are untouched, so **no stored
  expectation moves and no id in the corpus changes** -- rule 1 covers every
  record there.

  That last sentence read "**no node id that the library produces today
  moves**" until batch A8 corrected it, and it was wider than the truth. An id
  **does** move for a record whose source key a second record also claims:
  that record shifts from rule 2 to rule 3 and the record's digest joins its
  material. Two ways in. A duplicated **span id** is one, and it moves nothing
  that ever existed -- before rule 3 both records derived the *same* id and the
  file was refused, so there was no id to move; that is the case the sentence
  was thinking of. The other was reachable and built: while the fallback key
  was a record's 1-based index, a record with no span id at index 2 beside a
  record whose span id was the string `2` shared the key `2`, and the keyless
  record's id moved (`sw_fc49b046c1cd484d` -> `sw_70ae5dd0e179edd9`, review
  concern 4, first claim). Batch A5 has since made that fallback the record's canonical
  digest, so no trace file reaches it now -- but `assign` is public ground and
  a caller's two spans can still share a key, so the behaviour is pinned by
  `tests/test_ids.py::test_a_key_a_second_record_also_claims_moves_that_record_off_rule_2`
  rather than described.

  A reference to a duplicated span id still resolves to *neither* record:
  picking one would be a guess. The hard error remains as the guarantee that a
  record is never overwritten, but no trace file reaches it now.

  Two visible consequences. The conformance corpus's only refusal scenario,
  `duplicate_span_ids`, now expects a graph; `FIXTURES.md` §4.2 records that no
  scenario carries `expected/error.json` today and why one was not invented to
  fill the gap. And `canonical()` now compares **derived** node ids by position
  (`n0`, `n1`, ...) rather than by value, which `FIXTURES.md` §4.1 has specified
  since Phase 1 and nothing had implemented, because until now no scenario
  produced a derived id. (audit finding 2)

### Fixed

- **An unreadable `role` is reported again, because it decided nothing.** The
  previous fix marked a tool-result message's `...message.role` consumed the
  moment the key was *present*, so a `role` the adapter could not read as a
  string -- a number, a null, an object -- vanished from
  `unmapped_attributes` while the id beside it stayed reported. That inverted
  the sentence the same fix wrote into `SPEC.md` §3.7: a key read and **not
  usable** stays reported, and an unreadable role is exactly that. It is also
  the one key where reporting is the only trace left, since a `role` never
  becomes a field of its own -- consuming it let the fact that one arrived
  unreadable disappear between the raw record and a decision that was never
  made. A readable role is still consumed, whether it says `tool` or not: that
  one really did decide. No conformance or corpus expectation moved -- no
  trace in the tree carries a non-string `...message.role` -- and the
  quadratic-diagnostics fix is untouched, since a resent history states its
  roles as strings.
  (audit finding 6, follow-up; `SPEC.md` §3.7, `ADAPTERS.md` §3)

- **A timestamp is finite and within the interpreter's reach, or it is not
  read at all.** Three JSON numbers used to leave the library by three
  different wrong doors. A **quoted** integer of more than 4300 digits --
  ordinary JSON as far as the reader is concerned -- reached `int()` in each
  adapter's `_as_time`, which answers a string that long by raising: the
  interpreter's digit-limit `ValueError` came out of `spanweave.build`, and
  `spanweave build` / `spanweave inspect` printed it as a traceback. `1e400`,
  quoted or not, parses to `inf`, was carried as a timestamp, and reached the
  output as a bare `Infinity` -- which is Python's extension to JSON, not
  JSON, and which a strict parser on the other end rejects; the unquoted
  `NaN` and `Infinity` tokens did the same. And an OTLP `intValue` of more
  than 4300 digits raised the same `ValueError` out of the *reader*, one
  layer earlier.

  `SPEC.md` §3.1 now says the rule once, as a property rather than a list:
  **a rendering the table accepts is read only when what it parses to is a
  finite number.** `inf`, `-inf`, `nan` and an integer past the interpreter's
  integer-string digit limit are not, so each becomes the refused rendering
  every other unread spelling already is -- the field is `None`, the value
  stays verbatim in `raw.source`, the field is named in
  `unmapped_attributes`, and the builder adds `missing_timestamp`. Nothing
  new was added to the model or to the diagnostic set to do it. An OTLP
  `intValue` past the limit is carried verbatim as the decimal string it
  arrived as (`SPEC.md` §7), the same as any other value the reader cannot
  decode.

  Refusing the *field* does not make an unquoted `NaN` writable, because
  `raw.source` is verbatim and still holds it. So the encoder -- the single
  one every byte this library writes goes through -- now runs with
  `allow_nan=False`, and a graph holding a non-finite number is a
  `graph_not_serializable` refusal (`SPEC.md` §7, §3.10) for exactly the
  reason a graph nesting too deep to encode already was: a node's source
  record is verbatim or it is nothing, and a document that is produced, looks
  written and cannot be read back is the worst of the outcomes available.
  `spanweave build` on such a trace now exits 1 with one line on stderr;
  `spanweave inspect`, which writes no graph, still works.

  Tests: the cross-adapter rendering table gains the non-finite rows, with
  the digit limit tested either side of the line (4300 digits read, 4301
  refused); `tests/test_serialize.py` proves no bare `Infinity` or `NaN` can
  be written; `tests/test_read.py` and `tests/test_cli.py` cover the reader
  path, the OTLP `intValue` path, and every case through both CLI commands.
  `tests/audit/probe1.py`'s `nan_timestamps` case is now those regression
  tests rather than a probe.

- **`SPEC.md` §3.1 promised a retriever name no dialect states, and stated no
  rule for the names it declines.** `operation` was documented as *"tool name /
  model name / retriever name"*. Neither adapter has ever read a retriever's
  name -- no attribute for one exists in either dialect, and OTel GenAI names
  the *operation*, `retrieval`, not the retriever -- so the third of the three
  names has never been produced. Meanwhile the one identity a dialect does
  state normatively, `gen_ai.agent.name`, is deliberately **not** read, and the
  only place that was written down was an adapter docstring and two fixture
  notes. §3.1 now carries an `operation` subsection: the field holds a tool or
  model name the dialect states in a dedicated attribute, no dialect's agent,
  chain or retriever name is read into it, and a declined name survives twice
  over -- verbatim in `raw.source` (§3.5) and announced by an
  `unmapped_attributes` diagnostic naming the key (§3.7). Two precisions are
  stated with it: the rule is about name attributes and not about the kind, so
  an agent span that also carries a model attribute still gets the model in
  both dialects; and a retriever name is simply not among the names any dialect
  states. `ADAPTERS.md` and `CONTRACTS.md`, which repeated the promise, follow.

  **No behavior changed** -- nothing under `spanweave/` moved, and this is the
  H1 decision (`OPEN_QUESTIONS.md` §15, 2026-09-10) written
  where it binds. Mapping an agent name into `operation` was rejected: it was
  measured to diverge in 11 of 18 cross-dialect scenarios, and the corpus's only
  repair would have erased 22 tested cross-dialect `operation` assertions. A
  uniform `identity` field stays open as an **additive** change for a later
  schema version rather than a precondition of the freeze.
  `tests/test_doc_truth.py` reads the rule out of §3.1 and then measures it on
  both dialects, so the sentence and the library fail together or not at all.
  (audit finding: minor, agent/chain/retriever identity)

- **`SPEC.md` did not state where `missing_trace_id` stops.** The diagnostic
  A4 added is fenced on two sides: one per graph, never one per record, and it
  fires **only** when the built graph reports no trace id at all -- so a record
  carrying none among records that do is not diagnosed, because that graph has
  a trace id and nothing about it is missing. The second half was written in a
  commit body and in this file, and nowhere in the document a consumer reads to
  learn what a code means; §3.7's row stated the first half only, which left it
  reasonable to expect one diagnostic per id-less record and to build a consumer
  around that. §3.7's row and §7's bullet now both say it. **No behavior
  changed** -- the library has kept that scope since A4, and `tests/` held both
  sides of it; what was missing was the sentence. `tests/test_doc_truth.py`
  reads the scope out of §3.7 and then measures both sides through
  `spanweave.build`, so the row and the library fail together or not at all.
  (audit finding: minor, missing `trace_id` silent -- scope half)

- **A key an adapter reads to decide is no longer reported as one it could not
  map.** The OpenInference adapter reads a tool-result message's
  `...message.role` to tell a result the span was **given** (`SPEC.md` §4.2.1)
  from an echo of a request it never made (§4.4), and then reported that key
  in `unmapped_attributes` -- saying it had failed to understand the key it had
  just decided with. It reported the id key beside it too, because the pass
  that consumed the id ran **after** the unmapped keys were tallied, so the
  consumption had no effect at all. Both are two keys per resent message per
  turn, and a conversation resends its whole history, so the diagnostics grew
  quadratically: on the audit's 400-turn agent loop, `unmapped_attributes` was
  **13,193,072 bytes** of the serialized graph and is now **99,092** -- one
  key per span, the opening user message's role, which genuinely is read by
  nothing. No id, edge, node or count changed; the OTel GenAI adapter was
  audited for the same defect and has none (its history lives inside one
  attribute it consumes). `SPEC.md` §3.7 now states the rule in both
  directions: a key read and **acted on** is mapped, a key read and **not
  usable** stays reported.
  (audit finding 6, the diagnostics half)

- **A lone carriage return is no longer a line terminator**, because a lone
  carriage return is legal JSON whitespace *inside* a record. RFC 8259 lists
  CR among the four inter-token whitespace characters, so `{"a":<CR>1}` is one
  record that every JSON parser reads -- and the reader, having just learned to
  split on a bare CR, split it into two lines and reported two
  `malformed_record`s for a record that had been fine the day before. That is
  a tolerance about *how a file was written* reaching *what it says*, which is
  the one thing the rule was written not to do. LF and CRLF are unchanged (the
  terminator is the LF; the CR ahead of it goes with the whitespace the reader
  already strips, so a CRLF is one line), and the BOM rule is unchanged.

  The consequence is stated rather than hidden: a **CR-only file is one line**,
  and one line that long is one `malformed_record` carrying its text. A loud
  refusal on a file format nobody exports beats a silent misreading of a record
  somebody wrote. `SPEC.md` §7 says both halves.
  (review concern 4, third claim; correcting this series' own batch A2)

- **The spec stated the canonical digest without `ensure_ascii=False`**, and
  the library has passed it since the digest existed. `SPEC.md` §3.6 is the
  one place in this project where a paraphrase is a defect rather than a
  rounding: it exists so that something other than this library can derive the
  same node id. Followed as written, it could not -- under the default,
  `{"name": "café"}` canonicalizes to `{"name":"caf\u00e9"}`, whose digest
  begins `9db11f5f` where the library's begins `645fa443`, so every id derived
  from any record containing a non-ASCII character disagreed. §3.6 and §7 now
  state the call the library makes, together with the two things a
  reimplementation otherwise had to guess: both hashes are taken over a string
  encoded UTF-8, and `trace_id` is the empty string where the input states
  none. **No behavior changed** -- the code was right and the document was
  wrong. It was also unpinned on both sides, because `canonical()` relabels
  derived ids to `n0`/`n1` and no expectation anywhere held a real `sw_`
  string: `tests/test_ids.py` now derives an id from a reimplementation of the
  spec text, compares it against the library's on exactly the record that
  exposed the gap, and pins two `sw_` literals.
  (review concern 3)

- **Three documents were describing a library that had changed underneath
  them.** `fixtures/conformance/README.md` still called `duplicate_span_ids` a
  scenario that "must not build", under a heading about things the README used
  to get wrong, a whole run after it started building. `CONTRACTS.md` counted
  "seven rows" in §3.7's `source` table, which states nine, and listed
  `duplicate_source_id` among the codes no fixture emits, which one has since
  it stopped refusing. `OPEN_QUESTIONS.md` §12(f) still reported the
  positional fallback id as "real today". Each is corrected in place, with
  what it used to say kept -- a claim that goes stale silently is worth more
  as a warning than as a deletion. The two countable ones are derived from
  `SPEC.md` and the corpus by tests now, in both directions, so a table that
  grows a row or a corpus that gains a refusal fixture fails rather than
  drifting. (review concern 5)

- **`spanweave inspect` and `spanweave validate` no longer die on a file
  `spanweave build` reads without complaint.** Each opens the file with its own
  `json.loads` -- `inspect` to decide whether it was handed a built graph or a
  trace, `validate` to read the graph -- and each caught only `ValueError`,
  which is not what the parser raises for nesting it will not descend. So the
  containment added for the reader and the adapters stopped at the library's
  edge: the same trace built fine, summarized with a traceback. Both now
  report and exit non-zero, and `SPEC.md` §7 says the rule holds for every
  reading path, the CLI's own included. (review blocker 2, audit finding 3)

- **An adapter no longer raises on a structured attribute it cannot render.**
  An exporter that carries nested attributes hands the adapter a value that
  was never a string, and the adapter renders it back to text for `raw` with
  `json.dumps` -- which refuses depth exactly as `json.loads` does, and not
  with a `ValueError`. Both adapters now report `payload_parse_failed`, leave
  `value` and `raw` `None`, and say that the value survives verbatim on the
  node's raw record, which is where a structured attribute was always going to
  survive. `SPEC.md` §3.3 states the case. The annotation check that exists to
  ask *will this survive the graph file?* was blind to the same depth and now
  refuses it with the `ValueError` it already raises for a value that is not
  JSON. (audit finding 3, the write half)

- **A record with no span id is now identified by its content, not by where it
  sat in the file.** The `source_key` both adapters fall back to when the
  dialect states no span id was the record's 1-based index, so a file of
  span-id-less records **rebound its node ids when its lines were swapped**:
  the same two `sw_` ids came back, naming the other record. That contradicts
  `CLAUDE.md` invariant 4 and `SPEC.md` §5.2 -- input line order must not
  affect the result -- and it was invisible to the suite because every fixture
  and every capture carries a span id. The fallback is the record's canonical
  digest now, which is rule 3's reasoning applied one level up: an id is a
  name for a record, and a name that moves when the file is re-exported names
  nothing. `SPEC.md` §3.6 rule 2 and `ADAPTERS.md` §3 say so. No stored
  expectation moved, and no id a fixture or capture produces changed: rule 1
  covers every record in the corpus. (review blocker 1, `OPEN_QUESTIONS.md`
  §12(f))

- The cross-dialect comparison sorts a scenario's edges on the **positional
  labels** it already gives derived ids, not on the ids themselves. `SPEC.md`
  §5.2 sorts edges by `(kind, src, dst, basis)` over the ids the graph
  carries, and a derived id differs by adapter by design, so two faithful
  renderings of a scenario with two or more edges between derived-id nodes
  held the same edges in different orders -- and the equivalence claim would
  have failed on exactly the id-generation trivia the positional labels exist
  to isolate. `duplicate_span_ids` never showed it: it has one edge.
  Test-harness only; the library's own edge order is unchanged and still
  pinned everywhere a node id is a string a dialect supplied
  (`FIXTURES.md` §4.1).

- The reader tolerates a UTF-8 BOM (`EF BB BF`) at the head of the input: it
  is skipped before the container format is detected -- `str.strip()` does not
  remove U+FEFF, so the BOM used to ride into the parser and cost the file its
  first record. The tolerance does not touch content: the same bytes anywhere
  but the head of the stream are part of a record and are passed through
  verbatim, and the input digest still fingerprints the bytes as given, BOM
  included. `SPEC.md` §7 states it. (audit finding: minor, BOM loses first
  record)

  This entry also announced CR-only line endings as a second terminator, and
  said "neither tolerance touches content". The CR half did touch content and
  was **withdrawn by batch A8** the following day, before any release carried
  it; the entry above, under this section's newest changes, says what a lone CR
  is instead.

- Reading a record, or parsing a payload, nested deeper than the JSON parser
  will recurse no longer raises `RecursionError` out of the library. `json`
  reports that depth as a `RecursionError` rather than a `ValueError`, so it
  escaped the guards in the reader and in both adapters and took the whole
  build down. Such a record is now a `malformed_record` diagnostic carrying
  its text and the read continues; such a payload is `payload_parse_failed`
  with the text kept verbatim, as `SPEC.md` §7 now states. (audit finding 3)
