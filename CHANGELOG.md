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

- New error `graph_not_serializable` / `GraphNotSerializableError`, raised by
  the one encoder every byte this library writes goes through. The reader
  contains what the *parser* will not descend, but the encoder has its own
  limit and meets a value four levels lower down -- inside the document,
  inside a node, inside a payload -- so a payload that arrived intact could
  still not leave, and `json.dumps` said so with a `RecursionError` from a
  build that had already read its input without complaint. It is a refusal
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
