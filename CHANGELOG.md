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
  must not affect the result. Rules 1 and 2 are untouched, so **no node id that
  the library produces today moves**; rule 3 covers a case that previously
  produced no ids at all.

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

- The reader tolerates two things about how a file was written. A UTF-8 BOM
  (`EF BB BF`) at the head of the input is skipped before the container format
  is detected -- `str.strip()` does not remove U+FEFF, so the BOM used to ride
  into the parser and cost the file its first record. And LF, CRLF and CR-only
  line endings are each one terminator, so a CR-only file is a trace rather
  than one very long unreadable line. Neither tolerance touches content: the
  same bytes anywhere but the head of the stream are part of a record and are
  passed through verbatim, and the input digest still fingerprints the bytes as
  given, BOM included. `SPEC.md` §7 states both. (audit finding: minor, BOM
  loses first record)

- Reading a record, or parsing a payload, nested deeper than the JSON parser
  will recurse no longer raises `RecursionError` out of the library. `json`
  reports that depth as a `RecursionError` rather than a `ValueError`, so it
  escaped the guards in the reader and in both adapters and took the whole
  build down. Such a record is now a `malformed_record` diagnostic carrying
  its text and the read continues; such a payload is `payload_parse_failed`
  with the text kept verbatim, as `SPEC.md` §7 now states. (audit finding 3)
