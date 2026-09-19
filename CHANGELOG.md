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
  one -- what a file receiver writes -- produced **one `malformed_record`
  diagnostic per line and no nodes** -- **328** of them for the indented export
  a checkout now carries as `otlp_container/dialects/openinference.json`
  (tracked files only). Nine span keys are renamed, `attributes` is
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
  captured trace was a first receipt -- **4** across the **3** captured files a
  checkout carries (tracked files only), each call id received by exactly one
  span -- so keeping today's string for the earliest
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
  contains what the *parser* will not descend; the encoder meets a value four
  levels lower down -- inside the document, inside a node, inside a payload --
  so a payload that arrived intact could still not leave, and `json.dumps`
  said so with a `RecursionError` from a build that had already read its
  input without complaint. (Whether those four levels cost anything is the
  interpreter's answer and not this library's, and it differs by container
  shape. This sentence said "the encoder has its own limit" until R6, then
  "draws on one interpreter-wide C recursion budget" until R13; `SPEC.md` §7
  now carries the measured table instead of a mechanism.) It is a refusal
  rather than a diagnostic because there is nothing to degrade to: the
  offending value may be a node's verbatim source record, and dropping that to
  get past it is the one thing losslessness forbids. Nothing is written and
  nothing is partial. `SPEC.md` §3.10 and §7 state it.
  (audit finding 3, the write half)

- Conformance scenarios `derived_ids` and `derived_ids_shuffled`, in both
  dialects: three tool spans that carry **no span id**, and the same three
  lines reversed. Every node id in them is derived, which nothing in the
  corpus had ever been -- every one of the **117** records a checkout then
  held carried a span id, so `SPEC.md` §3.6 rule 2 was documented, implemented
  and exercised by no fixture at all. (This entry said "all 177 records" until
  batch R5: 177 was a scan of a working tree that counted the git-ignored
  `capture/_scratch/`. `tests/corpus_census.py` counts tracked files only, and
  makes these two scenarios the reason **12** of today's **151** records carry
  no span id.)
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

- **The run-6 cold review is archived and every finding it raised is
  registered.** The review read run 6's three code batches -- `S8`
  `62385b6`, `S9` `80a1cfe`, `S10` `f00ade4` -- found **nothing that
  blocks**, and raised twelve open threads, one of them a regression `S8`
  introduced, which `642773e` fixed (under *Fixed* below). It did not reopen
  the series. It is archived as `reviews/2026-09-13-run6.md`, byte-for-byte
  from the untracked scratch drop, `sha256` `d28837c91590688e...`, and
  `TASKS.md` records the scratch file's name and the whole digest beside it,
  as it does for run 5's. Its twelve ready-made sentences are pasted into
  `TASKS.md`'s open threads verbatim as threads 60-71, in the review's
  section order, each pointing at the section and finding id that reproduce
  it. Two are marked closed, each re-run rather than read off a report:
  S8.2 by `642773e`, and S8.1 by this commit, which narrows `S8`'s claim
  that no graph a stock interpreter built changes to nodes, edges and
  diagnostic codes, and records that the message of a `malformed_record` or
  `payload_parse_failed` refused over a literal of more than 4300 digits
  changed, in `SPEC.md` §5.3, the `DIGIT_LIMIT` comment and the `S8` entry
  below. The review accepted `S10`'s widening to absent, `null` and
  non-string link targets (thread 59, now closed) and confirmed and widened
  the retired-figure exemption (thread 58, open). **No behavior changed**;
  the one change under `spanweave/` is a comment. (run-6 review, all
  findings)

- **The September 2026 audit-fix series is closed a fourth and final time,
  and every run-5 review finding is accounted for.** Run 6 is five batches --
  `S8` `62385b6`, `S9` `80a1cfe`, `S10` `f00ade4`, `S11` `a834de4`, and `S12`,
  the closing commit of run 6 -- answering the maintainer's decision on
  thread 23 and the cold read of run 5, with no memo and no halt. The entry
  below is the previous close and is history, not the current fact. That
  review found **nothing that blocks** and 33 open threads, so run 6 was
  planned as the last run and its wording findings stay threads rather than
  becoming a run 7. The review is archived as `reviews/2026-09-12-run5.md`,
  byte-for-byte from the untracked scratch drop, `sha256`
  `4c1afa39ebfd6c38...`, and `TASKS.md` records the scratch file's name and
  the whole digest beside it, which is the review's own §7.3 applied to
  itself. Its 33 ready-made sentences are pasted into `TASKS.md`'s open
  threads verbatim as threads 24-56, each pointing at the review section
  that reproduces it; twelve are marked closed, ten by `S9`-`S11` and two by
  this close, each re-run rather than read off a batch's report, and thread
  23 is marked closed by `S8`. Three new threads record what run 6 itself
  left: that a close cannot name its own commit, the batch-name exemption
  `S9`'s retired-figure check keeps, and `S10`'s deliberate widening to
  absent, `null` and non-string link targets, for the cold review to accept
  or narrow. The registry's *"this commit"* spellings now say *"the closing
  commit of run N"*, with the sha where a later commit can supply it, and the
  run-4 map row that still called the ceiling pairs ±2 points at thread 10.
  Run 6's decision moved into `TASKS.md`'s decisions log verbatim but for one
  id spelling. `WORKPLAN.md` and its README row are removed, and
  `durable_documents()` drops its exclusion again. **No behavior changed**;
  nothing under `spanweave/` moved. (run-5 review, all findings; batch `S12`)

- **Five sentences that stated a rule more widely than the code keeps it are
  narrowed to what it does.** Found by the run-5 cold review, swept by grep
  rather than by citation. `spanweave/cli.py`'s comment said an `OSError`
  *"prints no bracket"*: the CLI adds none, but Python's `OSError.__str__`
  opens with `[Errno N]`, which is not a `SPEC.md` §3.10 code, and the
  comment now says so; the test whose name stated the retracted general rule
  is renamed to what it asserts, that the bracket on a *raised* refusal is
  one of `ERROR_CODES`. Both `_operation` docstrings said an unreadable name
  leaves *"`operation` and `model` stay `None`"*, which
  `openinference._operation({'tool.name': 7, 'llm.model_name': 'm'})` answers
  with `('m', 'm')`; `SPEC.md` §3.7's replacement clause, *"the two are
  `None` only where no readable name is left"*, is answered by
  `otel_genai._operation(LLM, {'gen_ai.tool.name': 't'})` with
  `(None, None)` and by `{'tool.name': 't', 'llm.model_name': 7}` with
  `('t', None)`. §3.7 and the two docstrings now state the same per-field
  reading for each dialect: each field is `None` only where no readable name
  for that field is left. This file's entry on the digest fix called three
  ceiling pairs *"coincide (991/989, 9997/9996, 9998/9997)"*; none did, and
  all three contradicted the `audit-R13` table. It now cites the table and
  carries a dated correction note, and `TASKS.md` thread 10 no longer calls
  the pairs ±2 recorded rather than rewritten. Re-measured 2026-09-19, one
  fresh process per probe, dicts and lists: 3.11.15 994/994, 3.12.3
  9997/9997, 3.13.14 9998/9998. Every pair coincides, and 3.11's figure moves
  with the caller's stack depth. `OPEN_QUESTIONS.md` §10(c)'s *"0 under
  256 ns"* was the epoch-nanosecond spacing applied to seconds-magnitude
  literals, and now reads 238.42 ns, `math.ulp(1.787e9)`. Comments,
  docstrings, one test name and documents only -- **no behaviour changed**.
  (run-5 review 2.1, 2.2, 5.1, 6.1, 6.2, 7.1; batch `S11`; `SPEC.md` §3.7)

- **The digit limit is the library's, and the interpreter's setting no longer
  changes a graph.** Batch R14 named CPython's integer-string digit limit as
  an input to the graph and told a caller to pin `PYTHONINTMAXSTRDIGITS=4300`
  for byte-identity; the maintainer decided instead (thread 23) that
  `CLAUDE.md` invariant 4 stays unconditional. The new
  `spanweave/jsoncodec.py` owns `DIGIT_LIMIT = 4300` -- the interpreter
  default, so no node, edge or diagnostic code a stock interpreter built
  changes, though a `malformed_record` or `payload_parse_failed` refused over
  a literal of more than 4300 digits now names the library's limit in its
  message instead of quoting the interpreter's (*"Exceeds the limit (4300
  digits) for integer string conversion: ..."* became *"an integer literal of
  4301 digits is longer than the 4300 digits spanweave reads (`SPEC.md`
  §5.3)"*). (Corrected 2026-09-19 from *"so nothing a stock interpreter
  built changes"*, false for those two messages, by the commit that archived
  the run-6 review, above; run-6 review S8.1.) It applies the limit by
  counting digits before any conversion: an unquoted literal past it is a
  `malformed_record`, a quoted timestamp past it is `missing_timestamp`, and
  an OTLP `intValue` past it is carried as its decimal string, under every
  setting. Integers inside it are parsed, rendered into diagnostic messages
  and encoded through `decimal.Decimal` or a placeholder pass over the
  unchanged stdlib encoder, so a lowered setting no longer refuses them: under
  `PYTHONINTMAXSTRDIGITS=640` a 1000-digit integer used to make its line a
  `malformed_record`, and a quoted 1000-digit timestamp built a node with no
  start time. The interpreter's setting is still never changed. A test builds
  one trace and one OTLP export carrying integers on both sides of both limits
  under the setting unset, `=0` and `=640`, and asserts the graphs are
  byte-identical; it replaces R14's test asserting they differ. The
  digit-limit tests derive their boundaries from the constant rather than
  from `sys.get_int_max_str_digits()`, and `tests/digit_limit.py` no longer
  moves the interpreter's limit. No corpus expectation and no serialized
  shape moves. (thread 23, batch S8; `SPEC.md` §3.1, §5.1, §5.3, §7;
  `ENVIRONMENT.md`, `README.md`)

- **The September 2026 audit-fix series is closed a third time, and
  `WORKPLAN.md` is gone with it.** Run 5 is seven batches -- `S1` `aed32a9`,
  `S2` `bed0ce2`, `S3` `5e8a40f`, `S4` `51da70e`, `S5` `4727a46`, `S6`
  `02c79b4`, `S7` this commit -- answering the cold read of run 4, with no
  memo and no halt. The entry below is the previous close and is history, not
  the current fact. What reopened the series this time is the sharpest version
  of what reopened it before: the blocker was **written into the close
  itself** -- `R9`'s widened census guard was recorded as having closed "a
  copy of the census can rot in place", and eighteen planted figures left five
  green with the whole suite passing, because the guard read a hand-written
  list of eight regex families while `tests/corpus_census.py` computed figures
  no family matched. `S1` derives that list from the census's own result type,
  so a figure the census can compute cannot be cited without a family, and a
  second test makes every family read a planted example, because a regex gone
  dead is invisible to a scan that reports only what it finds. The rest of the
  run is the series' other defect class, four more times: an `OSError` line
  three documents said prints no bracket while the suite asserted `[Errno 2]`
  (`S2`); an empty `span_id` that stayed a node identity after an empty
  *reference* had stopped being one, which silently lost an explicit parent
  edge (`S3`, and a decision -- an empty string is not a span identity, so it
  takes the content-derived fallback and no node can be named `""`); a sdist
  citation guard blind to the single-segment directory citation it was written
  for (`S4`); and three wrong figures with their second sites (`S5`, whose
  transferable finding is that **a wrong number in a durable document is
  copied into the `CHANGELOG.md` entry of the batch that first wrote it** --
  four of its six items had one, so grep the figure rather than fixing the
  line a review cites). `S6` took the nits with a spec surface and caught its
  own over-claim mid-batch. Final statuses, the decision taken on 2026-09-12,
  the run-4 review's finding-by-finding accounting -- every finding and
  sub-finding, including the four the review recorded without filing -- and
  **five** new open threads are in `TASKS.md` under *September 2026 audit*,
  which is again the only place any of it lives. The review's closing
  observation is recorded there verbatim as the series' lesson: the sentence
  describing a guard needs the same adversarial read as the guard. Three of
  the five threads are run 5's own residue rather than inherited work, and one
  of them -- `CLAUDE.md` invariant 4's unconditional determinism sentence,
  which `SPEC.md` §5.3 and `ENVIRONMENT.md` both qualify -- is a **halt
  point** recorded for the maintainer rather than a batch's to take. **No
  behavior changed**; nothing under `spanweave/` moved in this commit.
  (run-4 review findings F1-F7 and the accounting of all of them; batch `S7`)

- **The September 2026 audit-fix series is closed again, and `WORKPLAN.md` is
  gone for the second time.** G4 closed it on 2026-09-10 and deleted its
  execution state; a cold read of run 2 reopened it, and a cold read of run 3
  reopened it once more, so the entry below is history rather than the current
  fact. What each reopening found was a defect in the
  **close**, not new audit surface: a blocker that had escaped to the CLI
  (`R1`), a review cited from a durable document but living only in untracked
  scratch (`R2`, then `R15`, then this batch), and a sentence about the JSON
  depth ceiling that three consecutive batches stated as a universal from one
  interpreter's measurement (`R6`, corrected by `R13`). Runs 3 and 4 are
  nineteen registered batches, eighteen of which ran; their final statuses,
  the decision taken on 2026-09-11, the two cold reviews' finding-to-batch
  maps, and the threads the series did **not** close are all in `TASKS.md`
  under *September 2026 audit*, which is now the only place any of it lives.
  Three things are deliberate in how it was closed. The run-3 review is
  archived as `reviews/2026-09-11-run3.md`, verified byte-for-byte against the
  `patches/` original by digest, so the citation and the review ship together —
  `R15`'s sdist gate then proves it. Every finding that review raised is
  accounted for one by one: each is closed by a named batch or is an open
  thread, and the table says which, because a review whose nits evaporate at
  the close is one nobody writes again. And the seven new threads — chief among
  them that **one non-finite number refuses a whole graph** while the library
  already carries a non-JSON literal as *text* elsewhere, and the record-level
  coercions `R18` was registered for — are recorded in `TASKS.md` rather than
  in a new `DEBT.md`: this repository has none, and inventing one at a close
  would create the second place to look that deleting `WORKPLAN.md` exists to
  prevent. The series' batch ids are written `audit-R<n>` in `TASKS.md`, where
  the `0.9.1` launch checklist already numbers items `R1`-`R3`; everywhere
  else, including this file, they stay bare. **No behavior changed**; nothing
  under `spanweave/` moved.
  (run-3 review findings F5, F6, F7 and the accounting of all of them; batch
  `audit-R7`)

- **A refusal is now routable from outside the process, and `spanweave
  validate` refuses the document `spanweave build` refuses to write.**
  `spanweave/errors.py` has said *"match on this, never on the message"* since
  Phase 1 and `SPEC.md` §3.10 makes error codes a public contract from
  `0.9.x`, but the CLI printed `spanweave <command>: <message>` and dropped the
  code -- so from a subprocess, which is where most callers stand,
  `adapter_unconfident` and `graph_not_serializable` were both "exit 1 and an
  English sentence" and the only way to tell them apart was the prose nobody
  promised to keep. A raised `SpanweaveError` now prints its code in brackets
  first: `spanweave build: [adapter_unconfident] no adapter is confident
  enough…`. An `OSError` deliberately gets **no bracket from the CLI** -- it is
  the operating system's answer, it has no code in §3.10's table, and inventing
  one would name a contract that does not exist; the line stays Python's own
  text, which opens with the operating system's `[Errno 2]`, and that is an
  `errno`, not a spanweave code (corrected from *"prints no bracket"* by the
  batch below). The exit codes themselves (`0`, `1`, argparse's `2`) lived only
  in a comment inside `spanweave/cli.py`
  and are now a table in `SPEC.md` §7 and in the README, with the reason `1` is
  never subdivided stated rather than left to be inferred. Both tables are
  recomputed from the CLI by `tests/test_doc_truth.py`, and the failure line the
  README shows is *run* there rather than believed.

  The second half is the asymmetry found while checking the first: `validate`
  called `json.loads` with no `parse_constant`, so a graph document carrying a
  bare `NaN` printed `valid` and exited `0` -- a document the encoder refuses to
  write (`allow_nan=False`, batch R1) and a strict parser on the other end
  cannot read. `validate` now parses with those constants refused and reports
  such a file as not valid JSON, the same finding and the same exit code as a
  syntax error. `inspect` is unchanged and says so in §7: it summarizes what it
  is handed and never encodes anything, and folding well-formedness into the
  summary command would make it the gatekeeper for a question nobody asked it.

  Two wording defects in the same contract went with it. The docstring of
  `GraphNotSerializableError` still said `json.dumps` answers depth with
  `RecursionError` *"not a `ValueError`"* while R1 had added exactly a
  `ValueError` arm; it now names all three defeats (depth, a non-finite number, a value that refers back
  to itself) and which of the two exception types each arrives as. And
  `serialize.py`'s `except ValueError` was broader than its message: a circular
  reference -- the other thing `json.dumps` raises `ValueError` for -- was
  reported as *"it holds a number JSON has no way to write (Circular reference
  detected)"*. The refusal now looks at the value rather than at the
  interpreter's message and says which of the two it met.
  (run-3 review finding F4, batch R16; `SPEC.md` §3.10, §7)

- **The interpreter's integer-string digit limit is named as an input to the
  graph, and no test hard-codes it any more.** `CLAUDE.md` 4 promises the same
  graph from the same bytes *on any machine*; batch R1's rule made a legal
  per-interpreter setting decide graph content, and nothing in the repository
  said so -- the limit appeared exactly once, in a parenthesis in `SPEC.md`
  §3.1, and `ENVIRONMENT.md` did not mention it at all. Measured for this
  batch on CPython 3.12.3: one trace whose `start_time` is a quoted
  5000-digit integer builds `missing_timestamp` + `unmapped_attributes` at the
  default limit and `nonmonotonic_time` + `timestamp_unit_suspect` under
  `PYTHONINTMAXSTRDIGITS=0` -- two different graphs, same bytes. **The library
  does not pin the limit**, and that is the decision rather than an omission:
  `sys.set_int_max_str_digits()` at import is a process-wide mutation of a
  denial-of-service mitigation the host may have set deliberately, done as a
  side effect of `import spanweave`, and it would not even settle the question
  since any code may move the limit again afterwards. A library that sits
  underneath other people's tools does the minimum and surprises nobody. So
  the dependency is **stated**: new `SPEC.md` **§5.3** says which behaviours
  turn on the limit, why the library reads it rather than sets it, and how a
  caller pins it (`PYTHONINTMAXSTRDIGITS=4300`, the interpreter default);
  §3.1's bullet and §7 point at it; `ENVIRONMENT.md`'s Runtime section carries
  it as part of the runtime contract. It is a **measured** condition, not a
  declared one: a test builds one trace under two limits and asserts the
  graphs differ, and another asserts byte-identity is unaffected *within* one
  limit.

  The seven test *functions* R1 wrote about the limit each described one
  configuration. Six of them failed under `PYTHONINTMAXSTRDIGITS=0` -- seven
  `pytest` ids, one function being parametrized over both adapters -- because a
  5000-digit literal is one that interpreter reads, so the refusals they assert
  do not happen; the seventh raised `ValueError` inside its own body under
  `PYTHONINTMAXSTRDIGITS=640`, in both of its two ids. Nine ids, seven
  functions, both settings legal, the second the lowest the interpreter
  accepts. Every
  digit-limit test now derives both sides of the boundary from
  `sys.get_int_max_str_digits()` through the new `tests/digit_limit.py`, which
  also **installs** a limit where the interpreter has none, so no such test is
  skipped in the one configuration where the rule it pins does not hold. Green
  under the default, `=0` and `=640`. A `tests/test_doc_truth.py` gate keeps
  both halves: the two documents must name the setting, and no test file may
  write the boundary down or move the limit by hand.
  (run-3 review finding F2, batch R14; `SPEC.md` §3.1, §5.3, §7)

- **The four remaining corpus figures recompute from a checkout too.** R5 made
  `57 files / 177 records` counted rather than remembered; its grep named only
  that pair, and four more figures in the durable documents had the same defect.
  C3's timestamp sweep (*154 values, 41 sibling pairs, 81 µs*) and D2's
  `data`-edge sweep (*15 captured files, 24 edges*) both named the git-ignored
  `capture/_scratch/fleet/` as **half of their own scope**; F1's *64 of 64
  `*.jsonl`* counted 14 scratch captures a checkout does not have (the same 14
  R5 found); and F1's *46 `malformed_record`* counted the lines of an OTLP
  export `probe1.py` wrote into a temporary directory, so it recomputed from
  nothing at all. `tests/corpus_census.py` now counts each from `git ls-files`
  -- `Timestamps`, `Receipts`, `HeadScan` and `IndentedExport` -- and the
  documents state **34** timestamp literals over the **3** captured traces a
  checkout carries, **4** `data` edges over the same three, **50 of 50** tracked
  `*.jsonl` opening on `trace_id`, and **one `malformed_record` per line**
  (**328** for the indented export `otlp_container` carries), each with the
  *(tracked files only)* qualifier and each cited as history where the old
  figure is quoted. **One claim moved rather than only its arithmetic**: C3's
  *"it bit no fixture"* was measured over a scope that held no fixtures, and the
  widened scan finds **10** literals above the ceiling and **10** whose float
  differs from the digits in the file -- all of them the values C1 wrote into
  `timestamp_units` on purpose, five per dialect. §16(k)'s neighbouring *0 files
  contain `resourceSpans`* is now dated to F1 as well: the files that carry it
  are F2's own -- the two `otlp_container` renderings and the scenario note
  describing them. **No behavior changed**; nothing under `spanweave/` moved.
  (`OPEN_QUESTIONS.md` §2, §11, §16; `TASKS.md` audit note 7)

- **A conformant OTLP JSON export draws one `timestamp_unit_suspect` per span,
  and the documents now say so and say why.** The envelope states its unit in a
  field *name* -- `startTimeUnixNano` -- and §7's rule is that a name is not a
  type, so the value is carried verbatim and §3.1's 1e11 ceiling is over the
  line on every span. Measured on this tree, one 201-span export: **200
  warnings on 200 nanosecond spans, and the single span genuinely encoded in
  seconds is the one the channel is silent about.** That inversion is the
  finding, and the decision is to document it rather than paper over it
  (`OPEN_QUESTIONS.md` §17, option (c)): the warning is a statement about the
  **model's field contract** -- `started_at` is unix seconds -- and not about
  the telemetry, which is exactly as conformant as its field name says.
  **Nothing is rescaled.** A rescale in the reader was refused on C2's own
  grounds rather than on taste: `float()` at epoch-nanosecond magnitude has a
  spacing of 256 ns, so two spans 100 ns apart would collapse onto one number
  and their `temporal` edge would be emitted as tied. The cost of leaving it is
  stated unsoftened in `SPEC.md` §7 -- on such a file the diagnostic is a
  function of a format the consumer already knows, and a consumer that does not
  want it filters one code and loses nothing it could have used. Stating the
  unit at the seam (a `NormalizedSpan.timestamp_unit`, with the converse check
  that would restore the signal) is held, not rejected, against two conditions
  named in the memo: a second consumer of the unit, or a real mixed-unit export
  observed. **Nothing else moved**: no model field, no schema, no serialized
  default, no stored expectation, no fixture, and `otlp_container` keeps its
  byte-identity with `llm_tool_llm`, which is F2's whole demonstration that a
  container is not a dialect. R1's two pin tests in `tests/test_read.py` keep
  every assertion and gain a comment saying the behaviour is **documented**,
  not merely current, so a change that moves them is a change to what the spec
  promises. (`SPEC.md` §3.7, §7; `ADAPTERS.md`)

- **Every corpus figure this repository states is now counted from `git
  ls-files`, and states that it is.** `57 files / 177 records` was measured on
  a **working tree** holding local capture output under `capture/_scratch/`,
  which git ignores; it exceeded the tracked corpus of the day -- 43 files,
  117 records -- by exactly that scratch (14 files, 60 records), and it reached
  five commit bodies (`b6c5ea9`, `5995e0a`, `4774496`, `8adb8f2`, `fcc842d`)
  and six documents before anyone tried to reproduce it. Commit bodies cannot
  be rewritten; the documents can, and are: `ROADMAP.md`, `OPEN_QUESTIONS.md`
  §12(c), §12(d), §12(f), §13(h) and §14, `TASKS.md`, `CHANGELOG.md` and the
  two corpus documents that repeated it now assert **52 files / 151 records
  (tracked files only)** and cite the old pair as history, saying what it was
  and what it recomputes to. The count itself is `tests/corpus_census.py`, new
  and runnable (`uv run python -m tests.corpus_census`): it takes its file list
  from git rather than walking the tree, so a scratch capture, a half-finished
  fixture or a downloaded trace **cannot** move a number a document asserts,
  and `tests/test_doc_truth.py` recomputes the sentences against it -- with a
  planted untracked file proving the walk it replaced would have counted one.
  Two claims moved rather than only their arithmetic: **1** corpus file now
  carries both dialects' markers (the constructed `mixed_instrumentation`
  fixture, not an observation), and *"every record in the corpus carries a
  span id"* stopped being true when batch A5 added the span-id-less
  `derived_ids` pair -- **139** of the 151 records carry one, **135** of those
  trace-unique. The **0 records carrying both markers** that the freeze
  precondition rests on is unchanged under every one of these numbers. **No
  behavior changed**; nothing under `spanweave/` moved.

- **The JSON depth ceilings are a table with an interpreter in every row, not
  a sentence.** R6 (below) replaced A6's over-claim with another one: it said
  *"the encoder's limit **is** the parser's"* and gave the mechanism as *"both
  draw on one interpreter-wide C recursion budget"*, from a measurement taken
  on one interpreter, over nested **lists**. A graph document is nested
  **dicts** at every level, and on CPython 3.14 -- inside `requires-python`,
  and what a `uv run` in a fresh checkout picks -- the encoder gives out
  roughly 2,900 levels *before* the parser for dicts, which is the direction
  A6 claimed and R6 retracted. Re-measured for R13, one fresh process per
  measurement, Linux x86-64, under this library's `dumps` arguments:

  | CPython | nesting | `json.loads` | `json.dumps` | |
  |---|---|---|---|---|
  | 3.11.15 | dicts, lists | 992 | 992 | coincide |
  | 3.12.3 | dicts, lists | 9997 | 9997 | coincide |
  | 3.13.14 | dicts, lists | 9998 | 9998 | coincide |
  | 3.14.6 | **dicts** | ~40,100 | ~37,240 | encoder first |
  | 3.14.6 | lists | ~40,110 | ~74,480 | parser first |

  So `SPEC.md` §7 now carries the table, names its interpreters, says in terms
  that **no row of it is a promise** -- 3.14's numbers move by tens of levels
  between fresh processes, because it tests the C stack pointer -- and drops
  *"no trace file reaches the refusal at all"*, which is false on 3.14. What
  survives unchanged is R6's real contribution, the **positional** claim: the
  encoder meets a record's value four levels below where the reader met it
  (`nodes` -> the node -> `raw` -> `source` -> `attributes`), and that offset
  is this library's own and is pinned by a test that measures it off a built
  document. The limit pin now nests **dicts as well as lists**, records the
  ratio it observed instead of asserting a direction the library does not
  control, and asserts only what the library does control: that one level past
  whatever ceiling this interpreter has, the failure is
  `graph_not_serializable` and not a bare `RecursionError`. CI gained **3.14**,
  and the matrix is now derived from the classifiers in `pyproject.toml` rather
  than listed twice -- the blind spot was structural, since every version CI
  tested happened to be one where the two ceilings coincide. Documentation,
  one test and CI only -- no behaviour, no model, no serialized shape changed.
  (run-3 review F1)

- **The write-side depth guard is documented as what it is, and the
  measurement is on the record.** A6 introduced `graph_not_serializable` and
  narrated it as an encoder whose *limit* is lower than the parser's, and
  presented the defect as one users hit. **Measured on CPython 3.12.3**
  (Linux, `sys.getrecursionlimit()` 1000, which is not what bounds either)
  `json.loads` and `json.dumps` each give out at **9997 nested containers**
  taken at equal call depth -- so on *that* interpreter A6's direction does
  not hold, and neither does the ~1.9x *higher* one the run-2 review measured
  on its own (`json.loads` 40112, `json.dumps` 74493). *(R6 wrote those two
  observations up as a universal -- "the encoder's limit **is** the parser's",
  "one interpreter-wide C recursion budget" -- and measured nested lists.
  **R13, above, corrects that**: the direction differs by interpreter and by
  container shape, and on CPython 3.14 the encoder is the shallower of the two
  for the dicts a graph document is made of. R6's numbers stand as
  measurements of the interpreter they name; only the generalisation was
  wrong.)*
  What is real, and what survives R13, is **position**: a value the reader
  meets two containers into a trace record is met by the encoder six
  containers into the graph document (`nodes` -> the node -> `raw` ->
  `source` -> `attributes`), four levels further down. Those four levels are
  the whole gap, so how reachable the refusal is depends on the interpreter
  you are on: measured end to end on 3.12.3, a record whose attribute nests to
  9993 is read and the graph holding it is writable only to 9991 -- a band two
  levels wide out of ten thousand. **The guard stays**, and the reason rests
  on nothing an interpreter decides: the depth at which either gives out is
  the interpreter's and not this library's, the encoder's input is not only
  what the reader parsed, and a `RecursionError` reaching a caller is a
  traceback rather than a routable code. `SPEC.md` §7 states it that way,
  `serialize.py`'s docstring follows, and two tests in
  `tests/test_serialize.py` pin it. Documentation only -- no behaviour, no
  model, no serialized shape changed. (run-2 review, the A6 should-fix)

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
  gone.** *(Written at G4, 2026-09-10, and superseded four times: the series
  was reopened for runs 3, 4, 5 and 6 and the file came back with each of
  them. See the entry at the head of this section for the close that
  stands.)* That file was the
  series' execution state -- protocol, live batch
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
  markers** that the decision rests on is unchanged either way. (Both sections
  now *assert* the tracked pair, **52 files / 151 records**, and cite 57/177 as
  history; batch R5.) **No behavior changed**; nothing under `spanweave/`
  moved.
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
  bit no captured trace -- **34** timestamp values across the **3** captured
  files a checkout carries, none above 1e11, none whose float differs from the
  literal (tracked files only) -- and the one fixture it bit is the one C1
  wrote to sit over the ceiling: `timestamp_units`' ten integer literals are
  the only ten in the tracked corpus whose float differs from the digits in the
  file. But `startTimeUnixNano`
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

- **An OTLP `Status` that writes no `code` is read as code 0, `"UNSET"`,
  instead of vanishing from the record.** The reader flattened a plain
  `status` object field by field and wrote `status` only when a `code` was
  present, so a span carrying `"status": {}` produced a record with no
  `status` key -- exactly what a span carrying no `status` at all produces,
  which made the two indistinguishable on the record and on the node's
  `raw.source`. proto3 gives a scalar field a default rather than an absence,
  so the empty object is not missing information: it *is* `UNSET`, and
  dropping it was a silent discard (`CLAUDE.md` 2). A `{"message": "..."}`
  with no `code` gains the same `"UNSET"`, by the same argument. `message` is
  untouched and still has no default: none is invented, so no
  `status_message` key appears where the export wrote none. A populated
  status is unchanged, and a `status` object that is not a `{"code",
  "message"}` subset is still carried verbatim and gains nothing. No node's
  normalized `status` moves -- both adapters already read an absent status as
  `Status.UNSET` -- so no corpus expectation and no serialized shape moves
  either; every `otlp_container` fixture span carries `STATUS_CODE_OK`.
  (Qodo finding 9; `SPEC.md` §7)

- **A diagnostic about the whole input names an adapter only when a single
  adapter read every record, so a part-unclaimed input names none.**
  `missing_trace_id` and `duplicate_source_id` are one statement about
  everything that arrived (`SPEC.md` §7) and take their `adapter` from
  `_sole_contributor`, which asked only *how many adapters are named here* and
  ignored the records no adapter claimed. An input of one OpenInference record
  carrying no trace id plus one record nothing claimed therefore reported
  `missing_trace_id` with `adapter: "openinference"` -- a fact the unclaimed
  record helped make, attributed to a dialect that never saw it. It is now an
  id only when the input is non-empty **and** every record was produced by
  that same adapter; the empty input is decided rather than falling out of an
  empty set of names. This is the rule `Edge.adapter` already followed for an
  edge whose two ends came from different adapters (`SPEC.md` §3.8), one level
  up. A wholly-claimed single-dialect input is unchanged and still names its
  adapter, and `meta.adapters` is untouched -- it answers who contributed at
  all, is built from `_contributors`, and still lists the one real contributor
  of an input whose diagnostic can name nobody. Per-node `provenance` and
  per-edge `adapter` are unchanged. No corpus expectation and no serialized
  shape moves: `canonical()` compares diagnostics by code and count, and no
  conformance fixture carries an unclaimed record. (Qodo finding 7;
  `SPEC.md` §3.7)

- **An annotation is refused at annotate time for anything the graph file
  cannot carry, because the probe is now the encoder the file is written
  with.** `check_serializable` encoded the value with
  `json.dumps(value, sort_keys=True)`, while `serialize` writes a graph with
  `sort_keys=True, ensure_ascii=False, separators=(",", ":"),
  allow_nan=False`. Two shapes fell through the gap. `NaN`, `inf` and `-inf`
  passed `annotate` and `annotate_many` and were refused only later by `dumps`
  -- `GraphNotSerializableError`, *"it holds a number JSON has no way to
  write"* -- so the caller was handed a graph that could not be written. And a
  dict key that is not a string passed: `json` coerces it, so `{10: 1}` was
  annotated and read back as `{"10": 1}`, and a key of `10**700`, well inside
  the library's own digit limit, raised inside `str()` under
  `PYTHONINTMAXSTRDIGITS=640` -- which `serialize` then reported as *"a value
  refers back to itself"*, because `json.dumps` answers both facts with
  `ValueError`. The policy is now stated **once**, as
  `jsoncodec.canonical_dump`, and `serialize.canonical_bytes` and
  `check_serializable` both run it; it sits in `jsoncodec`, the bottom of the
  stack, because `serialize` imports `annotate` and the reverse import would be
  upward. A non-`str` mapping key at any depth is refused before the encode, by
  a walk that returns the key's *type* rather than rendering it -- rendering it
  is what can raise -- and is named as what it is: *"annotation values must be
  JSON-serializable so they survive serialization; dict is not (a mapping key
  of type int is not a string, and a JSON object is keyed by strings only, so
  it would not be read back as it was written)"*. Nothing about integers
  narrows: a value holding an integer of exactly 4300 digits is still
  annotated, written and read back equal, and the `DIGIT_LIMIT` refusal above
  is unchanged. `SPEC.md` §8 states both rules beside its round-trip promise.
  No corpus expectation and no serialized shape moves. (run-6 review S8.4;
  `SPEC.md` §5.2, §7, §8)

- **An annotation holding an integer of more than 4300 digits is refused when
  it is annotated, instead of being written into a file the library's own
  reader refuses.** Since batch `S8` the encoder writes an integer of any
  length whole under every interpreter setting, and the reader refuses a
  literal of more than `DIGIT_LIMIT` digits; `check_serializable` asked only
  the encoder, so at `6eb1762` a 4301-digit annotation was accepted, `dumps`
  wrote it, and `spanweave validate` exited 1 on the file (*"an integer
  literal of 4301 digits is longer than the 4300 digits spanweave reads"*).
  Before `S8`, on a stock interpreter, the encoder had refused it up front.
  `check_serializable` now also refuses an integer anywhere in the value --
  at the top, as a dict value, as a list item, at any depth -- whose
  magnitude has more than `DIGIT_LIMIT` digits, counted as the reader counts
  a literal's (the sign is not one) and by arithmetic rather than through
  the interpreter's string conversion, so the answer is the same under every
  setting. The refusal is the existing `ValueError`, in the same words:
  *"annotation values must be JSON-serializable so they survive
  serialization; int is not (an integer of 4301 digits is longer than the
  4300 digits spanweave reads (`SPEC.md` §5.3))"*. An integer of exactly 4300
  digits, either sign, is written and read back equal, and `spanweave
  validate` accepts the file. `SPEC.md` §8 states the rule beside its
  round-trip promise. No corpus expectation and no serialized shape moves.
  (run-6 review S8.2; `SPEC.md` §5.3, §8)

- **A span link whose target is `""` is no link, as an absent target always
  was, and the entry is reported rather than turned into an edge to `""`.**
  Batch `S3` made the empty string no span id at a record's `span_id` and
  `parent_id`, and `SPEC.md` §3.6 said so "at either end of a relation"; both
  adapters' `_links()` still read a link's `span_id` as a plain string, so the
  third reference field was left out. On run-5 review 3.1's two-record input
  (an agent `a`, and a tool whose `span_id` is `""` and whose `links` is
  `[{"span_id": ""}]`), in the flat OpenInference JSONL, the flat OTel GenAI
  JSONL and an `ExportTraceServiceRequest` carrying `links[].spanId: ""`:

  | Link entry | Before (`e0784f8`), all three containers | After, all three containers |
  |---|---|---|
  | `{}` (target absent) | no link edge, **no diagnostic** | no link edge, `unmapped_attributes` `["<record>.links[0]"]` |
  | `{"span_id": null}` | no link edge, **no diagnostic** | the same |
  | `{"span_id": ""}` | `(sw_…, '', link, explicit, span.link)`, no diagnostic | the same |

  An `explicit` edge whose `dst` is `""` is guaranteed to dangle, because S3
  made sure no node can be named `""`; the export additionally carries its
  expected one `timestamp_unit_suspect` per span, unchanged. The link target
  is now read at the seam by `link_ref`, over the same `_stated_id` as
  `span_ref` and `parent_ref`, inside a new `span_links(record)` that
  replaces the two adapters' identical `_links()` copies. An empty target is
  no link, exactly as an absent one was. Unlike the other two fields the entry
  is **reported**: a record with no `span_id` is still a node and one with no
  parent is still a root, but a link entry exists only to name a span, so one
  naming none becomes nothing, and its `trace_id` and `attributes` would
  vanish between `raw` and the graph. The report is `unmapped_attributes`
  -- the code §3.7 already gives a record field recognized and not read --
  keyed `<record>.links[<i>]` (keys only; the entry stays in `raw.source`
  verbatim). So absent and `null` targets now draw it too, as do a target
  that is not a string, an entry that is not an object, and a `links` field
  that is not a list (`<record>.links`): all were dropped silently before.
  **Exactly the empty string**: `" "` and `"0000000000000000"` remain targets.
  No new diagnostic code, no model change, and `tests/serialized_shape.json`
  is unchanged. New degenerate scenario `empty_link_target` in both dialects
  (one `parent` edge, no `link` edge, one `unmapped_attributes`); FIXTURES.md
  §8 freezes an expected graph, so `empty_ids` was not extended. **No corpus
  expectation moved**: no tracked record carried a link entry that names no
  span. At batch `S10` the corpus grew by two files and four records, all
  stating a usable span id: 54/155 -> **56/159**, 141 -> **145** carrying a
  span id, 137 -> **141** trace-unique, 308 -> **316** timestamp literals, 52
  -> **54** tracked `*.jsonl`, and the README's scenario counts went from 28
  and 23 to 29 and 24.

  **S3's before/after table, re-measured** (run-5 review 3.2). The body of
  `5e8a40f` prints a three-row table that does not reproduce: its first two
  rows came from the run-4 review's timestamp-less input, while its third row
  carries a derived id only a timestamped input produces. Measured here on
  **one** input for every row -- the record that derives
  `sw_b1ea560c790200c4`, recovered from `spanweave.ids.derive`:

  ```
  {"trace_id":"t1","span_id":"","name":"agent.run","start_time":1000.0,"end_time":1003.0,"attributes":{"openinference.span.kind":"AGENT"}}
  {"trace_id":"t1","span_id":"c","parent_id":"","name":"tool.lookup","start_time":1000.5,"end_time":1001.0,"attributes":{"openinference.span.kind":"TOOL","tool.name":"lookup"}}
  ```

  | Tree | nodes | edges | diagnostics |
  |---|---|---|---|
  | `0ad7382` (before R10, `7480ac3^`) | `['', 'c']` | `('', 'c', parent, explicit, span.parent_span_id)`, `('', 'c', temporal, derived)` | none |
  | `7480ac3` (R10) and `bed0ce2` (before S3) | `['', 'c']` | `('', 'c', temporal, derived)` | none |
  | `5e8a40f` (S3) | `['sw_b1ea560c790200c4', 'c']` | `('sw_b1ea560c790200c4', 'c', temporal, derived)` | none |

  The load-bearing claim holds as the body stated it -- the `explicit` parent
  edge disappears at R10 with no diagnostic -- but the body's second row
  (`edges []`) omits the `temporal` edge every row after the first carries,
  and its first omits the `temporal` edge beside the `parent` one.
  (run-5 review 3.1, 3.2; batch `S10`; `SPEC.md` §3.6, §3.7, §4.0)

- **Every figure the corpus census prints is read back by a figure family, in
  the census's own words, and a retired figure asserted in a live sentence
  fails.** Batch `S1` derived the census's *figures* from its result type, but
  the families that read documents were still a hand-written list of
  *spellings*: the run-5 review planted wrong values for four figures in S3's
  own recount sentence in this file -- the `N/M` pair, *carrying a span id*,
  *trace-unique* and *tracked `*.jsonl`* -- and the suite stayed green, while
  a fifth plant in the same sentence went red. `tests/corpus_census.py`'s
  output is now data (`report()`, a line of text and named figures), every
  figure the census computes is printed, in the number-first spelling the
  documents copy, and a test plants a sentinel at each printed figure in turn
  and requires a family to read it back under that figure's name -- so a
  printed figure with no family fails the guard itself. Four spellings gained
  a family or an alternative, and two widened to read the census's own
  `record(s)` and `1e+11`. The second half: `WORKING_TREE_CENSUS` listed only
  the working-tree values, so the values later batches retired passed any
  sentence (two green plants in `OPEN_QUESTIONS.md`). A new test derives the
  check from `RETIRED_CENSUS_FIGURES`: a retired value its family reads is
  allowed only in a *sentence* that names a batch, says *history* or sits left
  of a `->`, and a second test plants every retired value into its family's
  example to prove none is unreadable. One `OPEN_QUESTIONS.md` §12 sentence is
  split so today's rule-1 figure no longer shares a sentence with the batch
  that superseded the old one. **No behaviour changed**: nothing under
  `spanweave/` moved, and neither did any fixture or
  `tests/serialized_shape.json`. (run-5 review findings 1.1, 1.2; batch `S9`)

- **Four sentences that advertised a rule, a guard or a guarantee slightly
  wider than it holds, and one that was ungrammatical.** The run-4 cold
  review's per-batch nits with a code or a spec surface (its §4 `R8`, §7 `R12`
  twice, §9 `R14`, §10 `R15`), each probed against the code before the
  sentence was rewritten, which is what none of them had. **No behaviour changed**: nothing under `spanweave/`
  is touched, no stored expectation and no `tests/serialized_shape.json`
  moved.

  `SPEC.md` §3.7 said a name the adapter cannot read *"leaves `operation` and
  `model` `None`"*, listing all three OpenInference name keys, which reads as
  a claim about the span. It is a claim about the **key**: an attribute map of
  `{"tool.name": 7, "llm.model_name": "m"}` gives `operation` and `model` both
  `"m"`, in either dialect, because an unreadable key contributes nothing *of
  its own* and the readable one beside it is untouched -- exactly as if the
  number had never been sent, which is the wording the `audit-R8` entry below
  already used. §3.7 now states the per-key reading its adapters' `_operation`
  docstrings carry, and says the two fields are `None` only where no readable
  name is left. The same paragraph's *"The timestamps are not the only fields
  that holds for"* is now grammatical.

  `SPEC.md` §5.1 and `README.md`'s determinism bullet state the guarantee with
  no condition on it two subsections before §5.3 states the condition. Both
  now **point at** §5.3 by its title rather than paraphrasing it: the
  dependency is one fact, and a second wording of it is a second thing to keep
  true. Neither the guarantee nor `CLAUDE.md` invariant 4 is weakened, and
  `CLAUDE.md` -- the third site carrying the unconditional sentence, and the
  one `SPEC.md` §5.3 was written to qualify -- is deliberately left alone.

  `TASKS.md` 3.6's `audit-R15` amendment stated the sdist citation rule as a
  universal (*"every repo-relative path a document the sdist ships cites must
  resolve inside the sdist"*) with its qualifiers appended as an aside, and
  the shipped `TASKS.md` itself cites two paths that resolve nowhere. It was
  the last durable place claiming that guard's reach without the limits its
  code discloses. The qualifiers are now inside the rule, the reach is stated
  as the four edges it has -- an untracked candidate skipped rather than
  failed (the two unresolving citations are exactly that case, and one is now
  named where the rule is stated), a root name with no slash unreachable, a
  cited directory asking only that *something* ship beneath it, existence and
  never accuracy -- and the sentence says which three of the four are planted
  against in `tests/test_acceptance.py` and why the fourth cannot be.

  The `audit-R12` entry below counted *six* keys, *three per dialect*, and
  walked the corpus for six; the commit changed **seven**, the seventh being
  `gen_ai.operation.name` -- the genai half of the span-kind fix that entry
  describes in prose and left out of its list. Corrected there, with the
  seventh key's walk run here at that commit and again at this one rather than
  taken from the report.
  (run-4 review §4 `R8`, §7 `R12`, §9 `R14`, §10 `R15`;
  `SPEC.md` §3.7, §5.1)

- **Five wrong numbers in durable documents, and one present-tense claim that
  is no longer true.** All measured again here rather than taken from the
  report that found them (run-4 cold review, findings F5, F6 and F7 plus three
  counting nits).

  `SPEC.md` §7 said `float()` *"at epoch-nanosecond magnitude has a spacing of
  ~238 ns"*. `math.ulp(1.7e18)` is **256.0**; 238.42 ns is the spacing at 1.7e9
  **seconds**, one rescale away from the magnitude the sentence names. So the
  document set held two figures for one stated magnitude -- `SPEC.md` §3.1 and
  `ADAPTERS.md` already say 256 ns. The argument is untouched, because it never
  depended on which of the two: spans 100 ns apart still collapse. `SPEC.md`
  §7 and this file's `audit-R11` entry now say 256 ns.

  `tests/digit_limit.py` said five of `audit-R1`'s tests go red under
  `PYTHONINTMAXSTRDIGITS=0`, and its own enumeration summed to seven. Re-run on
  `audit-R14`'s parent (`1e121d2`) under CPython 3.12.3 and 3.14.6 alike: **7
  `pytest` ids / 6 functions** under `=0`, and **2 ids / 1 function** under
  `=640` -- nine ids, seven functions, disjoint. Both the module docstring and
  this file's `audit-R14` entry now say which population and which
  configuration, because "seven" without that is the same defect one digit
  over.

  `OPEN_QUESTIONS.md` §16(a) stated, under a heading reading *"What happens
  today, measured"*, that an indented OTLP export gives one `malformed_record`
  per line and no nodes. It has not done that since batch F2 made the envelope
  a container -- the same commit (`ff05b2d`) that added the fixture the
  sentence names, so the behaviour was never true of that file. Measured today,
  `spanweave inspect` on it reports **4** nodes, seven edges and two
  `unmapped_attributes`, with no `malformed_record` at all. The sentence is
  **dated rather than rewritten**, because it is the measurement the memo's
  design was taken from: the heading now says when, a provenance note names
  both commits and prints what the tree gives now, and the **328** it carries
  stays -- that is the file's line count, it recomputes, and a test pins it.

  Three counts. §16(k)'s *"the two that carry it now"* is **three** (`git grep
  -l resourceSpans -- fixtures capture examples`), and has been since F2: the
  two `otlp_container` renderings and the scenario note describing them. The
  `audit-R7` entry below said runs 3 and 4 were "nineteen registered batches,
  seventeen of which ran"; `TASKS.md` carries nineteen bullets of which exactly
  one (`audit-R18`) is marked never-run, so **eighteen** ran, `audit-R7`
  included. And `audit-R15`'s "38 scenario-relative citations" is dropped
  rather than recomputed, as batch S4 already dropped it from the docstring it
  described: the population depends on a pattern that has changed once, an
  independent scan reproduces neither the figure nor a single obvious
  definition of what it counted, and nothing gates it.

  Also in `TASKS.md`: the two remaining bare `R3`s inside the audit registry
  are now `audit-R3`, which is the collision the registry's own policy sentence
  says it resolves. The `0.9.1` launch checklist's `R3` is untouched -- it is
  the other `R3`, and the point of the spelling.

  Documents only. Nothing under `spanweave/` moved, no test assertion changed,
  and `tests/serialized_shape.json` does not move.
  (`SPEC.md` §7; `OPEN_QUESTIONS.md` §16; run-4 review findings F5, F6, F7)

- **The sdist citation guard can now see a directory, which is the citation it
  was written for.** Batch `audit-R15` added `install_check`'s "ships every
  tracked path its own documents cite" check, and a comment beside its pattern
  saying that `reviews/` **as a whole missing directory must be visible too**.
  It was not: the pattern required at least two path segments *and* a trailing
  slash, so a top-level directory citation -- `reviews/`, `.github/` -- matched
  nothing, in any document. The check went red on its own defect only because
  the review *files* are also cited by full path, which is an accident of those
  two citations rather than the rule the commit stated. The pattern now takes a
  second shape: one segment carrying a slash. Resolution follows it -- a cited
  path is a file or a directory according to what **git** tracks it as, not
  according to whether the citation happens to end in a slash, so
  `fixtures/conformance` and `fixtures/conformance/` are now the same question.
  Planted both ways before landing. With `/reviews` removed from
  `[tool.hatch.build.targets.sdist].include`, the check fails naming
  `reviews/` and the three documents citing it, alongside the three review
  files it already named. With `/.github` removed it fails naming `.github/`
  and the three documents citing that -- and with the single full-path
  citation of `.github/workflows/ci.yml` reworded out of the sandbox, the old
  pattern passes a sdist with no `.github` in it at all while the new one still
  fails: that is the generalization, isolated. Widening what is *looked* at
  widens what is not a path, so a candidate that resolves nowhere, or that git
  does not track, is skipped exactly as before rather than becoming a new
  failure. The scope sentences were rewritten with it, in the module
  docstring, in `_audit_sdist_resolves_its_own_citations`, and in the
  `pyproject.toml` comment that points at it, and they now state the two limits
  that remain: a root name written with no slash at all (`Makefile`, `tests`)
  is a word, not a citation, and cannot be seen; and a cited directory is
  resolved by *something* shipping beneath it, not by a per-file manifest. Both
  limits, and the directory citation itself, are pinned by tests in
  `tests/test_acceptance.py`, because a sentence about a guard's reach that
  nothing plants against is how this one came to overstate itself. `SPEC.md`
  does not move: the library's behaviour is unchanged, and nothing under
  `spanweave/` is touched. (run-4 review F4)

- **An empty string is not a span identity, so an empty parent reference now
  loses nothing.** Batch `audit-R10` normalized `parent_id: ""` /
  `parentSpanId: ""` to *no parent* at the seam, on the stated ground that,
  read as a reference, the empty string **names a span no input can contain**.
  Only half of that was implemented. A record whose `span_id` was `""` kept
  `""` as its node identity -- only a record with *no* `span_id` took
  `SPEC.md` §3.6 rule 2's content-derived key -- so an input could contain
  exactly the span the sentence said it could not, and the `parent` edge
  between such a pair went from `('', 'c', parent, explicit)` before R10 to
  **nothing at all, with no diagnostic**, after it. An `explicit` relation the
  telemetry stated was dropped silently, which touches losslessness as well as
  warrant, and the spec asserted an absolute an input could falsify. Both
  halves are one rule now: an empty `span_id` states no id, so the record is
  keyed by its content exactly as one that omits the field is, in **both
  dialects** and **both containers** -- the OTLP reader renames `spanId` to
  `span_id` and leaves the value, so the two paths meet at the same seam
  reader. The same two-record input now builds two nodes, the first under a
  derived `sw_` id, still no `parent` edge -- there is no pair of ids for one
  to be stated between -- and **nothing is dropped**: both empty strings are on
  the nodes' `raw.source` verbatim, which `tests/test_adapters.py` and
  `tests/test_read.py` assert, since `canonical()` erases `raw` and the corpus
  cannot see it. No new diagnostic code: an empty `span_id` is *read*, not
  failed-to-read, so it draws no `unmapped_attributes` (the reading
  `parent_id: ""` already gets), and a derived id is rule 2's honest answer
  rather than a defect to report -- `derived_ids` records that argument and it
  is unchanged here. **Exactly the empty string**, at both fields: `" "` and
  `"0000000000000000"` are ids like any other. New degenerate conformance
  scenario `empty_ids` in both dialects, one expected graph: two root spans,
  one derived id, one `temporal` edge, zero diagnostics. **No corpus
  expectation moved** -- no tracked record states an id empty, so no existing
  `expected/graph.json` is touched -- and `tests/serialized_shape.json` is
  unchanged. At batch `S3` the corpus grew by two files and four records, so
  every present-tense census citation was recomputed (52/151 -> **54/155**,
  139 -> **141** carrying a span id, 135 -> **137** trace-unique, 300 ->
  **308** timestamp literals, 50 -> **52** tracked `*.jsonl`); the superseded values
  survive only in the `CHANGELOG.md` entries that record what an earlier batch
  asserted, and are retired as history rather than rewritten.
  (run-4 review finding F3; batch `S3`; `SPEC.md` §3.6, §4.0)

- **The documented rule for matching a failure line says what the CLI prints,
  and the README transcript names its own precondition.** Batch `audit-R16`
  made a raised refusal routable from outside the process, and stated the other
  half of the rule three times -- in `README.md`, `SPEC.md` §7 (*Failures*) and
  its own `CHANGELOG.md` entry above -- as *"a failure the library did not
  raise prints no bracket: it has no code to print"*. That is false, and the
  repository's own tests said so: `OSError.__str__` opens with `[Errno 2]`, so
  `spanweave build /nope/not-a-trace.jsonl` prints
  `spanweave build: [Errno 2] No such file or directory: '/nope/not-a-trace.jsonl'`,
  which is exactly what `tests/test_cli.py` asserts. Followed literally, the
  matching rule -- *the bracket is the whole of what is machine-readable on
  that line* -- extracted `Errno 2` from a missing file and handed a caller a
  "code" absent from `SPEC.md` §3.10's table. The behaviour was right and is
  unchanged; the three sentences now say what it is. The intent survives in the
  form that is true -- **the CLI adds no bracket of its own** -- with the OS's
  bracket named as the operating system's text that a caller must not match,
  and the machine-readable rule restated positively: the code, if there is one,
  is the bracket immediately following `spanweave <command>: `, and its
  contents are one of §3.10's values, so a caller routes on that closed set and
  never on *the line carries a bracket*. Alongside it, the README's failure
  transcript said `$ spanweave build not-a-trace.jsonl` and showed
  `[adapter_unconfident] …`, which is true only if that file exists -- the
  doc-truth test creates it first, so the fence passed while a reader pasting
  the command met `[Errno 2] …`, the same confusion one screen above where it
  is explained. The file is now named `unrecognized.jsonl` and the sentence
  introducing it says that it exists and holds JSON no adapter recognizes.
  Documentation only: nothing under `spanweave/` and no test assertion moved.
  (run-4 review finding F2 and its §11 README nit; batch `S2`)

- **Every figure the corpus census computes is guarded, and the registry no
  longer claims more than that.** Batch `audit-R9` widened doc-truth from
  figures at listed *sites* to a corpus figure anywhere, and `TASKS.md`
  recorded the class as closed. It was not. The site-free scan read a
  hand-written list of eight regex families while `tests/corpus_census.py`
  computed figures no family matched, and a hand-written list cannot report
  what it omits: the run-4 cold review planted eighteen figures one at a time
  and **five stayed green** with the whole suite passing — records carrying a
  span id, trace-unique span ids, and three zero-valued counts. The list is no
  longer written down. `corpus_census.figure_names()` derives it from the
  `Census` result type itself — fields, properties, nested dataclasses, dicts
  and tuples, walked over the **type** so an empty container still has a name —
  and a new test requires every derived figure to appear in some family, and
  every family to name a figure the census actually computes. Adding a figure
  to the census now fails the suite until a family covers it. Sixteen families
  were added to reach that state, and every family — old and new — now carries
  an example sentence it must still read, because a family that matches nothing
  guards nothing and the scan reports only what it finds, never what it failed
  to find. The one class a value-matching regex cannot reach, a figure that is
  not a whole number, is named in `FRACTIONAL_FIGURES` together with the
  whole-number figure that does pin it, and a test holds that mapping to what
  the walk finds, so a new fractional figure fails rather than slips past. All
  five of the review's surviving plants are now red. `TASKS.md`'s `audit-R9`
  entry says what that batch closed — its eight families, wherever they are
  written — and what it did not. **No behavior changed**; nothing under
  `spanweave/` moved.

- **A record too deep to digest is the library's named refusal, not a bare
  `RecursionError` out of `spanweave.build`.** Every record is digested for
  the duplicate check (`SPEC.md` §3.6), and a digest is an **encode**. The
  reader's guards contained what the *parser* will not descend; that one call
  was uncontained, so on an interpreter whose encoder ceiling is the lower of
  the two — CPython 3.14, for the nested **dicts** a trace record actually is
  — the reader met the encoder on a record the parser had been willing to
  read, and an interpreter's traceback escaped a documented entry point where
  §3.10 promises a routable code. Measured end to end on 3.14.6 before the
  fix, attribute nesting through `spanweave.build`, against a digest ceiling
  bisected at ~37,230 and a parser ceiling at ~40,100 in the same process:
  **36,840 built and wrote, 37,640 and 38,670 raised `RecursionError`, 40,500
  was the `malformed_record` §7 promises** — three bands, the middle one a
  defect. On 3.11.15, 3.12.3 and 3.13.14 the two ceilings coincide (992/992,
  9997/9997, 9998/9998, the `audit-R13` table above and `SPEC.md` §7) and the
  middle band does not exist: every depth past the ceiling is a
  `malformed_record` there, measured the same way. (Corrected 2026-09-19 from
  *"coincide (991/989, 9997/9996, 9998/9997)"* -- three pairs, none of them
  coincident, contradicting the table -- by batch `S11`, below.)
  The middle band is now `graph_not_serializable` — **the code the write side
  already raises for the same value**, rather than a second code or a new
  diagnostic, because it is one fact about one record: a record with no digest
  has no identity (§3.6) and could not have been written either, and nothing
  may be dropped to get past it (`CLAUDE.md` 2). So the outcome is now one of
  three on every interpreter — a graph, a `malformed_record`, or the named
  refusal — and never a traceback. **The depth at which each band begins
  belongs to the interpreter; the outcome does not**, and `SPEC.md` §7 says
  exactly that rather than promising a number.
  Found by R13 while measuring for the depth table, outside its row, and
  carried as `TASKS.md` open thread 11 until now. Two of the three new tests
  are red on **every** interpreter before the fix — they digest a value built
  in memory, so the parser's ceiling cannot hide the encoder's, which is how
  the band-only test that could not fail on 3.12 was avoided; the third walks
  the depths either side of both measured ceilings and asserts no direction
  and no number. (`SPEC.md` §3.6, §3.10, §7)

- **The sdist ships `reviews/`, and now proves it ships what its own documents
  cite.** `[tool.hatch.build.targets.sdist].include` is an explicit allowlist
  and had no `/reviews` line, so the published artifact carried `TASKS.md`
  citing `reviews/2026-09-10-run1.md` as the full text of a review the artifact
  did not contain — a citation with no referent, which is the same defect the
  `reviews/` directory was created to fix, with "not in the allowlist" in place
  of "untracked scratch". `make install-check` could not see it: both of its
  sdist audits run outward — sdist ⊆ tracked, wheel ⊆ sdist — and this is the
  inward direction. Adding the one line would have left the next omission just
  as silent, so the inward direction is now a check, stated about the artifact
  rather than about `reviews/`: **every repo-relative path a document the sdist
  ships cites must resolve inside the sdist**. Both generations of the defect
  fail it. Its reach is bounded and the bounds are written down beside it
  (`install_check._audit_sdist_resolves_its_own_citations`): citations are read
  from code spans only, because a path in prose cannot be told from a sentence;
  a candidate counts as repo-relative only when its first segment is a
  top-level entry of the repository, which is what separates
  `reviews/2026-09-10-run1.md` from the scenario-relative `expected/graph.json`
  and package-relative `adapters/base.py` citations the corpus and the spec are
  full of, which are not counted here on purpose; only paths git tracks are required, so `dist/…`, `out/…` and
  untracked scratch are out of scope here and stay with
  `test_a_durable_document_cites_no_untracked_scratch_path`; and existence is
  all that is asked, never whether the cited section says what the citing
  document claims. Proven in both directions before landing: with `/reviews`
  removed the check fails and names both missing files and all four documents
  citing them; with it restored the built sdist carries 301 members, two of
  them `reviews/`, read out of the tarball rather than inferred from the
  config. `SPEC.md` does not move — the library's behaviour is unchanged and
  the spec says nothing about packaging.
  (audit batch R15, run-3 review finding F3; `TASKS.md` 3.6, amended)

- **A root span's empty `parentSpanId` is no parent, and no longer an orphan.**
  OTLP's `parentSpanId` is a proto3 `bytes` field; an unset one is the empty
  string, and a marshaler that emits default-valued fields writes
  `"parentSpanId": ""` on **every root span of every export**. The reader
  renamed it verbatim, `_as_str` handed it on unchanged, and the builder tested
  only for `None` -- so every root drew `orphan_parent`, *"parent span '' is not
  in this input"*: the diagnostic that means a trace was sampled, filtered or
  exported mid-run, reported on the one span that proves it was not. A record
  spells "no parent" two ways -- the field absent, or the field present and
  empty -- and both are now `None` at the seam, in one shared rule
  (`spanweave.seam.parent_ref`) rather than one copy per adapter, because two
  dialects disagreeing about a root is a cross-dialect equivalence claim.
  Exactly the empty string: `" "` and `"0000000000000000"` are references like
  any other, and a parent that *was* named and is absent still draws
  `orphan_parent`. Nothing is dropped -- the empty string is still in the node's
  verbatim `raw.source`, so which rendering the exporter used is still readable
  (`CLAUDE.md` 2). The corpus could not see any of this: `otlp_container`
  omitted the field on its roots, as proto3's canonical form allows. Both of its
  renderings now write it, which is what a real exporter writes, and both roots
  draw no diagnostic -- **before: 1 `orphan_parent` per rendering; after: 0**,
  with the stored expectations (2 `unmapped_attributes`) and the byte-identity
  with `llm_tool_llm`'s graph unchanged.
  (audit batch R10, found by R3; `SPEC.md` §4.0, §6, §7, §3.7)

- **A record's identity fields report themselves too.** `unmapped_attributes`
  names record fields as well as attribute keys, written `<record>.<field>`,
  and until now only the two timestamps used it: `span_id`, `parent_id`,
  `trace_id` and `name` were consumed by a static `KNOWN_RECORD_KEYS` set
  before anything read them, so a `"name": 42` became `""` and a
  `"parent_id": 42` became no parent -- each as silently as if the record had
  carried neither, with the value surviving only in `raw`. That is the same
  defect as the attribute keys above, one level up. The four are now reported
  when they arrive in a rendering neither dialect reads, by one rule at the
  seam (`spanweave/seam.py`) rather than a copy in each adapter, because two
  dialects reporting one unreadable id differently is a cross-dialect
  difference. Three readings are still **not** reports, because each is
  something the adapter read: an omitted field, a `null` one -- how a record
  says "no parent" and "no name" -- and `parent_id: ""`, which is *no parent*
  rather than an unreadable one. Nothing moved: across every tracked `.json` /
  `.jsonl`, these four field names and their OTLP spellings occur 660 times in
  89 files and every one is a string or `null`.
  (audit finding 6, follow-up; `SPEC.md` §3.7)

- **The rule now holds at every deciding key in both dialects, and the
  diagnostic stops saying "no attribute" of a key that was sent.** Three more
  OpenInference keys and four OTel GenAI ones were still marked consumed
  before they were read: `input.mime_type` / `output.mime_type` (a mime the
  adapter cannot read types nothing -- the payload is `present` with no mime
  -- and a mime stated beside *no value* is never read at all, since an
  `absent` payload carries none), `openinference.span.kind`, and
  `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.request.model`,
  `gen_ai.tool.call.id`. The last three are not cosmetic: an unreadable name
  or call id never reaches a node field, so `unmapped_attributes` is the
  entire report of it, and until now OpenInference reported one while OTel
  GenAI swallowed it -- a cross-dialect difference in the only place the
  difference could be seen. A span kind is the odd one in each dialect -- `openinference.span.kind` and
  `gen_ai.operation.name`: every value but `null` is read with `str()` and
  preserved as `attributes.reported_kind`, so only `null` is unreadable there,
  and the `unknown_span_kind` message said *"no `openinference.span.kind`
  attribute"* of a span that carried one. Both adapters now say which of the
  two happened. No conformance or corpus expectation moved: across every
  tracked `.json` / `.jsonl` at that commit, these seven keys occur 297 times
  in 52 files and **none** carries a non-string value or a mime with no value
  beside it, in either the flat or the OTLP `KeyValue` rendering. *The count
  was six, and the walk behind it six keys wide, until run 5's batch S6:
  `gen_ai.operation.name` was changed by the same commit and named in neither.
  Re-walked there, at the commit and again at run 5's tip: the seventh key
  alone is 76 occurrences in 25 files then and 78 in 26 now, all of them
  strings both times, so the conclusion the six-key walk reached holds for the
  branch it had not looked at.*
  (audit finding 6, follow-up; `SPEC.md` §3.7)

- **A name or a call id the adapter could not read is reported too.** The
  `role` fix above stated the rule -- a key is consumed where it is *read*,
  never before -- and four more keys in the same adapter still broke it. The
  operation names (`tool.name`, `llm.model_name`, `embedding.model_name`) were
  all marked consumed before any of them was read, and `tool_call.id` was
  marked consumed before it was read in either of its renderings (the bare key
  a fulfilling span carries, and the `...tool_calls.N.tool_call.id` a
  requesting span states in its own output). So a name or an id that arrived
  as a number, a null or an object left `operation`, `model` and `call_ids`
  exactly as if the key had never been sent, *and* vanished from
  `unmapped_attributes` -- the one place a consumer could have seen that
  something was there and could not be read. Now each of the four is consumed
  only where its value was readable; a readable one is still consumed even
  where another key won the field, because it was read and acted on. No
  conformance or corpus expectation moved: 25 tracked files carry one of these
  keys and none carries a non-string value at one, in either the flat or the
  OTLP `KeyValue` rendering.
  (audit finding 6, follow-up; `SPEC.md` §3.7, `ADAPTERS.md` §3)

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
