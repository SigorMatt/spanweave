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
