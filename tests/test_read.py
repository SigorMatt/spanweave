"""The reader (TASKS.md 1.1).

The reader's contract is mostly about what it refuses to do: it does not
raise, it does not drop, and it does not decide what a record means.
"""

import dataclasses
import hashlib
import io
import json

import pytest

import spanweave
from spanweave import diagnostics as codes
from spanweave.model import EdgeKind
from spanweave.read import read_trace, record_digest
from spanweave.serialize import canonical_bytes
from tests import digit_limit
from tests.json_depth import (
    MEASUREMENT_NOISE,
    deepest_accepted,
    dicts_text,
    lists_text,
    nested_dicts,
    too_deep_for_nested_dicts,
    too_deep_for_nested_lists,
)

JSONL = b'{"span_id":"s0"}\n{"span_id":"s1"}\n'
ARRAY = b'[{"span_id":"s0"},{"span_id":"s1"}]'
RECORDS = [{"span_id": "s0"}, {"span_id": "s1"}]


def test_reads_jsonl():
    stream = read_trace(JSONL)
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_reads_a_json_array():
    stream = read_trace(ARRAY)
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_both_container_formats_produce_the_same_records():
    # The container is not part of the dialect and must not reach the adapter.
    assert list(read_trace(JSONL)) == list(read_trace(ARRAY))


def test_the_format_is_decided_by_the_first_non_whitespace_byte():
    assert list(read_trace(b"\n\n   " + ARRAY)) == RECORDS
    assert list(read_trace(b"\n\n   " + JSONL)) == RECORDS


def test_a_malformed_line_is_diagnosed_and_the_read_continues():
    stream = read_trace(b'{"span_id":"s0"}\n{not json\n{"span_id":"s1"}\n')
    records = list(stream)
    # The good lines on either side survive. A reader that gives up in the
    # middle of a trace is worse than useless in a pipeline.
    assert records == RECORDS
    reported = stream.diagnostics.collected()
    assert [d.code for d in reported] == [codes.MALFORMED_RECORD]
    assert "line 2" in reported[0].message
    # The text is kept: it cannot become a record, so this is the only place
    # it survives at all.
    assert reported[0].source == "{not json"


def test_a_malformed_line_never_raises():
    for hostile in [b"\x00\x01\x02", b'{"unterminated": ', b"]", b'{"a":1}][']:
        stream = read_trace(hostile)
        list(stream)  # must not raise


def test_an_unparseable_array_is_diagnosed_rather_than_raised():
    stream = read_trace(b'[{"span_id":"s0"},')
    assert list(stream) == []
    assert [d.code for d in stream.diagnostics.collected()] == [codes.MALFORMED_RECORD]


def test_the_stream_counts_what_never_became_a_record():
    # One per `malformed_record`, and the builder's only way to know that a
    # record existed which no adapter ever saw (`SPEC.md` §3.7). A whole
    # container that will not parse counts as one, because how many records
    # it held is precisely what could not be read.
    for data, expected in [
        (JSONL, 0),
        (ARRAY, 0),
        (b'{"span_id":"s0"}\n{not json\n{"span_id":"s1"}\n', 1),
        (b'{not json\n{"a":\n', 2),
        (b'[{"span_id":"s0"},', 1),
        (b'{"span_id":"s0"}', 0),
        # A repeat is skipped too, and is deliberately not counted: an
        # identical copy was read, so nothing about it is unknown (§7).
        (b'{"span_id":"s0"}\n{"span_id":"s0"}\n', 0),
    ]:
        stream = read_trace(data)
        list(stream)
        assert stream.skipped_records == expected, data


#: Nesting past *this* interpreter's recursion limit, measured here rather
#: than written down. Cheap to build and cheap to reject: the parser gives up
#: at its own limit, not at the end of the string, so these tests cost
#: microseconds.
#:
#: It was a flat 100,000 and a comment calling that "far past any
#: interpreter's recursion limit". It is not: `json.loads` reads 40,106 levels
#: of brackets on CPython 3.14.6 at an 8 MB stack and **322,402** under
#: `ulimit -s 65536`, where this file parsed cleanly and the two tests below
#: asserted a `malformed_record` that never came.
DEEP = lists_text(too_deep_for_nested_lists()).encode()


def test_a_deeply_nested_record_line_is_diagnosed_rather_than_raised():
    # Audit finding 3. `json.loads` answers deep nesting with RecursionError,
    # which is not a ValueError, so it escaped the reader's guard and took the
    # whole read down -- exactly the "gives up on line 4,000 of 10,000"
    # failure this module exists to prevent.
    stream = read_trace(b'{"span_id":"s0"}\n' + DEEP + b'\n{"span_id":"s1"}\n')
    assert list(stream) == RECORDS
    reported = stream.diagnostics.collected()
    assert [d.code for d in reported] == [codes.MALFORMED_RECORD]
    assert "line 2" in reported[0].message
    # The text survives here or nowhere.
    assert reported[0].source == DEEP.decode()


def test_a_deeply_nested_array_container_is_diagnosed_rather_than_raised():
    # The same finding through the other container format.
    stream = read_trace(DEEP)
    assert list(stream) == []
    assert [d.code for d in stream.diagnostics.collected()] == [codes.MALFORMED_RECORD]


def test_a_record_too_deep_to_digest_is_the_librarys_refusal_not_a_traceback():
    # R19. Every record is digested for the duplicate check (`SPEC.md` §3.6),
    # and a digest is an *encode*. The reader's other guards contain what the
    # parser will not descend; this one contains the encoder, whose ceiling is
    # its own and, on CPython 3.14, the lower of the two -- so the reader met
    # it on a record the parser had been willing to read and `spanweave.build`
    # raised a bare `RecursionError`. A consumer routes on the code (§3.10);
    # an interpreter's traceback is not routable and is indistinguishable from
    # a bug in the consumer's own recursion.
    #
    # Built in memory rather than parsed, so this is red on **every**
    # interpreter and not only on one where the band exists: the value never
    # goes near `json.loads`, so the parser's ceiling cannot hide the
    # encoder's.
    #
    # And deep enough on every interpreter, because the depth is measured in
    # this process against the shape a record has: 100,000 was under the
    # encoder's dict ceiling on CPython 3.14.6 whenever the stack was larger
    # than the runner's 8 MB default (299,372 under `ulimit -s 65536`), and
    # there the digest simply succeeded.
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        record_digest(nested_dicts(too_deep_for_nested_dicts()))
    assert failure.value.code == "graph_not_serializable"
    assert "digested" in str(failure.value)


def test_the_digest_refusal_is_the_one_the_write_side_already_raises():
    # Same value, same fact, one code. A record too deep to digest is a record
    # too deep to write, so no graph carrying it was ever publishable, and
    # naming the two failures differently would invent a distinction the
    # interpreter does not make and a consumer would have to learn twice.
    #
    # Same measured depth as the test above, for the same reason.
    value = nested_dicts(too_deep_for_nested_dicts())
    with pytest.raises(spanweave.SpanweaveError) as digesting:
        record_digest(value)
    with pytest.raises(spanweave.SpanweaveError) as writing:
        canonical_bytes(value)
    assert digesting.value.code == writing.value.code == "graph_not_serializable"


def test_the_reader_never_raises_a_bare_recursion_error_at_any_depth(
    record_property,
):
    """The band collapses: one outcome per depth, and never a traceback.

    Three bands existed on CPython 3.14.6 and the middle one was a defect:
    a record nesting to ~37,240 built and wrote, one nesting to ~37,260 raised
    a bare `RecursionError` out of `spanweave.build`, and only above ~40,100
    did the parser refuse first and make it the `malformed_record` `SPEC.md`
    §7 promises. On 3.11-3.13 the two ceilings coincide and the middle band
    does not exist at all.

    So this test asserts **no direction and no depth**. It measures where this
    interpreter's parser and encoder give out, walks the depths either side of
    each, and asserts only what the library controls: at every depth the
    outcome is a graph, a `malformed_record`, or the library's named refusal —
    and never a `RecursionError`. Where the band exists it is walked; where it
    does not, that is recorded rather than asserted away.
    """
    parser = deepest_accepted(lambda depth: json.loads(dicts_text(depth)))
    digest = deepest_accepted(lambda depth: record_digest(nested_dicts(depth)))
    record_property("json_depth_reader", f"parser={parser} digest={digest}")
    record_property("readable_but_undigestible_levels", parser - digest)

    probes = [
        digest - MEASUREMENT_NOISE,
        digest + MEASUREMENT_NOISE,
        parser + MEASUREMENT_NOISE,
    ]
    if parser - digest > 2 * MEASUREMENT_NOISE:
        probes.append((digest + parser) // 2)

    for depth in sorted(probes):
        line = (
            b'{"span_id":"s9","attributes":{"deep":'
            + dicts_text(depth).encode()
            + b"}}"
        )
        source = b'{"span_id":"s0"}\n' + line + b"\n"
        try:
            stream = read_trace(source)
            records = list(stream)
        except spanweave.GraphNotSerializableError as refusal:
            # The library's own, named. This is the band the defect lived in.
            assert refusal.code == "graph_not_serializable"
            continue
        # Otherwise the record either came through or was diagnosed -- both
        # are outcomes `SPEC.md` §7 already promises.
        assert len(records) in (1, 2)
        assert all(
            d.code == codes.MALFORMED_RECORD for d in stream.diagnostics.collected()
        )


def test_a_json_document_that_is_not_an_array_is_diagnosed():
    stream = read_trace(b"[")
    assert list(stream) == []
    assert len(stream.diagnostics) == 1


def test_blank_lines_are_not_records_and_are_not_diagnosed():
    stream = read_trace(b'\n{"span_id":"s0"}\n\n\n{"span_id":"s1"}\n\n')
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_line_numbers_count_blank_lines_so_they_match_the_file():
    stream = read_trace(b'{"a":1}\n\n\nbroken\n')
    list(stream)
    assert "line 4" in stream.diagnostics.collected()[0].message


def test_trailing_newline_is_optional():
    assert list(read_trace(b'{"span_id":"s0"}')) == [{"span_id": "s0"}]


def test_a_record_may_be_any_json_value():
    # The reader has no opinion about shape; that is the adapter's business.
    assert list(read_trace(b'5\n"text"\n[1,2]\nnull\n')) == [5, "text", [1, 2], None]


def test_reads_from_a_path(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_bytes(JSONL)
    assert list(read_trace(path)) == RECORDS
    assert list(read_trace(str(path))) == RECORDS


def test_reads_from_stdin(monkeypatch):
    monkeypatch.setattr(
        "sys.stdin", io.TextIOWrapper(io.BytesIO(JSONL), encoding="utf-8")
    )
    assert list(read_trace("-")) == RECORDS


def test_a_str_is_always_a_path_never_content(tmp_path, monkeypatch):
    # Guessing between the two is how you get a bug report about a file
    # named '{'.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OSError):
        list(read_trace('{"span_id":"s0"}'))


def test_the_digest_fingerprints_the_input_bytes():
    stream = read_trace(JSONL)
    assert stream.digest is None  # nothing read yet, nothing to fingerprint
    list(stream)
    assert stream.digest == hashlib.sha256(JSONL).hexdigest()


def test_reading_is_lazy_until_asked():
    # Iterator-based end to end (DESIGN.md §6): nothing is pulled from the
    # source until the consumer asks for a record.
    pulled = []

    def chunks():
        for line in JSONL.splitlines(keepends=True):
            pulled.append(line)
            yield line

    from spanweave.read import RecordStream

    stream = iter(RecordStream("<test>", chunks()))
    assert pulled == []
    next(stream)
    assert len(pulled) < 2


def test_a_large_input_is_split_across_chunk_boundaries_correctly():
    records = [{"span_id": f"s{n}", "pad": "x" * 500} for n in range(400)]
    data = ("\n".join(json.dumps(r) for r in records) + "\n").encode("utf-8")
    assert list(read_trace(data)) == records


# --- Encoding and line endings (audit "minor: BOM loses first record") -------


def test_a_utf8_bom_at_the_head_is_skipped_and_the_first_record_survives():
    # Audit finding (minor). Editors and Windows tooling put EF BB BF at the
    # front of a UTF-8 file. `str.strip()` does not remove U+FEFF, so the BOM
    # rode into `json.loads` and cost the file its FIRST record -- the one
    # failure mode a reader must never have.
    stream = read_trace(b"\xef\xbb\xbf" + JSONL)
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_a_bom_does_not_hide_the_array_form():
    # The BOM is skipped before the format is decided, or every BOM'd array
    # would be read as one very long JSONL line.
    stream = read_trace(b"\xef\xbb\xbf" + ARRAY)
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_an_input_that_is_only_a_bom_reads_as_empty():
    stream = read_trace(b"\xef\xbb\xbf")
    assert list(stream) == []
    assert len(stream.diagnostics) == 0


def test_an_empty_input_reads_as_empty():
    stream = read_trace(b"")
    assert list(stream) == []
    assert len(stream.diagnostics) == 0


def test_those_bytes_anywhere_but_the_head_are_content_and_are_kept():
    # Only the head is an encoding artifact. The same three bytes inside a
    # record are a character the record chose, and losing it would be a
    # losslessness bug rather than a tolerance.
    stream = read_trace(b'{"span_id":"\xef\xbb\xbfs0"}\n')
    assert list(stream) == [{"span_id": "﻿s0"}]
    assert len(stream.diagnostics) == 0


def test_a_bom_at_the_head_of_a_later_line_is_diagnosed_not_skipped():
    # Nothing claims a second BOM is an encoding artifact, so that line is
    # simply not JSON -- reported, with its text, exactly like any other
    # unreadable line.
    stream = read_trace(b'{"span_id":"s0"}\n\xef\xbb\xbf{"span_id":"s1"}\n')
    assert list(stream) == [{"span_id": "s0"}]
    reported = stream.diagnostics.collected()
    assert [d.code for d in reported] == [codes.MALFORMED_RECORD]
    assert "line 2" in reported[0].message


def test_the_digest_covers_the_bom_because_it_fingerprints_the_bytes_as_given():
    data = b"\xef\xbb\xbf" + JSONL
    stream = read_trace(data)
    list(stream)
    assert stream.digest == hashlib.sha256(data).hexdigest()


def test_a_bom_split_across_chunk_boundaries_is_still_one_bom():
    from spanweave.read import RecordStream

    stream = RecordStream("<test>", iter((b"\xef", b"\xbb", b"\xbf", JSONL)))
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_crlf_line_endings_are_read():
    stream = read_trace(b'{"span_id":"s0"}\r\n{"span_id":"s1"}\r\n')
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_a_bare_cr_inside_a_record_is_whitespace_and_the_record_still_reads():
    # RFC 8259 lists CR among the four inter-token whitespace characters, so a
    # pretty-printer that writes CR-terminated lines inside a record produces
    # this, and it is one record. A reader that split on a lone CR would turn
    # a record that parses into two that do not -- content damaged in the name
    # of tolerating a file format.
    stream = read_trace(b'{"a":\r1}\n')
    assert list(stream) == [{"a": 1}]
    assert len(stream.diagnostics) == 0


def test_a_cr_only_file_is_one_line_and_is_reported_as_one():
    # The other side of the same rule: a lone CR is not a terminator, so a
    # CR-only file is a single line. It is refused loudly -- one
    # `malformed_record` carrying the text -- rather than misread, and no
    # record vanishes silently.
    stream = read_trace(b'{"span_id":"s0"}\r{"span_id":"s1"}\r')
    assert list(stream) == []
    reported = stream.diagnostics.collected()
    assert [d.code for d in reported] == [codes.MALFORMED_RECORD]
    assert reported[0].message.startswith("line 1 ")
    assert reported[0].source == '{"span_id":"s0"}\r{"span_id":"s1"}'


def test_lf_and_crlf_may_be_mixed_within_one_input():
    stream = read_trace(b'{"span_id":"s0"}\r\n{"span_id":"s1"}\n{"span_id":"s2"}\n')
    assert list(stream) == [*RECORDS, {"span_id": "s2"}]
    assert len(stream.diagnostics) == 0


def test_a_crlf_counts_as_one_line_not_two():
    stream = read_trace(b'{"a":1}\r\nbroken\r\n')
    list(stream)
    reported = stream.diagnostics.collected()
    assert "line 2" in reported[0].message
    assert reported[0].source == "broken"


def test_a_bare_cr_does_not_advance_the_line_number():
    # Line numbers count the terminators the reader knows, and a lone CR is
    # not one of them, so everything up to the LF is line 1.
    stream = read_trace(b'{"a":1}\r\rbroken\n')
    list(stream)
    reported = stream.diagnostics.collected()
    assert reported[0].message.startswith("line 1 ")
    assert reported[0].source == '{"a":1}\r\rbroken'


def test_a_crlf_split_across_chunk_boundaries_is_still_one_terminator():
    # The CR arrives in one read and its LF in the next, so the pair is only
    # a pair once both chunks are in hand. The terminator is the LF and the CR
    # ahead of it is stripped with the rest of the line's surrounding space:
    # no phantom blank line, and no line number shifted after it.
    from spanweave.read import RecordStream

    stream = RecordStream("<test>", iter((b'{"a":1}\r', b"\nbroken\r\n")))
    assert list(stream) == [{"a": 1}]
    assert "line 2" in stream.diagnostics.collected()[0].message


def test_a_trailing_cr_at_the_end_of_the_input_does_not_cost_the_last_record():
    # Not a terminator, just whitespace after the last record's final brace.
    stream = read_trace(b'{"span_id":"s0"}\r')
    assert list(stream) == [{"span_id": "s0"}]
    assert len(stream.diagnostics) == 0


def test_a_bom_costs_a_trace_none_of_its_spans_end_to_end():
    # The audit case as it was reported: a whole build, not just the reader.
    import spanweave

    record = {
        "trace_id": "t1",
        "span_id": "s0",
        "parent_id": None,
        "name": "agent.run",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": {"openinference.span.kind": "AGENT"},
    }
    line = json.dumps(record).encode("utf-8") + b"\n"
    graph = spanweave.build(b"\xef\xbb\xbf" + line)
    assert len(graph) == 1
    assert graph.trace_id == "t1"
    assert [d.code for d in graph.diagnostics if d.code == codes.MALFORMED_RECORD] == []


# --- Duplicate records (audit finding 2a, batch A3) -------------------------
#
# At-least-once export and collector retries put the same record in a file
# twice. Keeping both would publish two nodes for one operation -- an
# invented span, which is worse than a missing one, because a consumer
# counting tool calls cannot tell. The reader collapses them and says so.


def test_an_identical_record_appearing_twice_is_read_once():
    stream = read_trace(b'{"span_id":"s0"}\n{"span_id":"s0"}\n')
    assert list(stream) == [{"span_id": "s0"}]


def test_the_collapsed_copy_is_reported_not_silently_dropped():
    stream = read_trace(b'{"span_id":"s0"}\n{"span_id":"s0"}\n')
    list(stream)
    reported = [
        d for d in stream.diagnostics.collected() if d.code == codes.DUPLICATE_RECORD
    ]
    assert len(reported) == 1
    assert reported[0].source == {"span_id": "s0"}
    assert "2" in reported[0].message


def test_the_first_copy_is_the_one_kept():
    # Stated in SPEC.md 7 so that it is a rule rather than an accident. The
    # copies are equal as parsed records, so the choice is observable only in
    # `RawRecord.line_number`, which is not serialized.
    stream = read_trace(b'{"a":1}\n{"b":2}\n{"a":1}\n')
    assert list(stream) == [{"a": 1}, {"b": 2}]


def test_records_that_differ_by_one_key_are_both_kept():
    stream = read_trace(b'{"span_id":"s0","name":"a"}\n{"span_id":"s0","name":"b"}\n')
    assert len(list(stream)) == 2
    assert len(stream.diagnostics) == 0


def test_a_record_written_twice_with_different_key_order_is_still_one_record():
    # "Identical" is decided on the parsed record, because the parsed record
    # is what the library preserves (`RawRecord.source`, SPEC.md 3.5). Key
    # order never reaches a node, so keeping both copies would preserve
    # nothing and invent a span.
    stream = read_trace(b'{"a":1,"b":2}\n{"b":2,"a":1}\n')
    assert list(stream) == [{"a": 1, "b": 2}]


def test_three_copies_are_one_record_and_one_diagnostic():
    stream = read_trace(b'{"a":1}\n{"a":1}\n{"a":1}\n')
    assert list(stream) == [{"a": 1}]
    reported = [
        d for d in stream.diagnostics.collected() if d.code == codes.DUPLICATE_RECORD
    ]
    assert len(reported) == 1
    assert "3" in reported[0].message


def test_duplicates_are_collapsed_in_the_json_array_form_too():
    stream = read_trace(b'[{"a":1},{"a":1}]')
    assert list(stream) == [{"a": 1}]
    assert len(stream.diagnostics) == 1


def test_the_duplicate_report_does_not_depend_on_where_the_copies_sat():
    def report(data):
        stream = read_trace(data)
        list(stream)
        return [(d.code, d.message, d.source) for d in stream.diagnostics.collected()]

    assert report(b'{"a":1}\n{"a":1}\n{"b":2}\n') == report(
        b'{"a":1}\n{"b":2}\n{"a":1}\n'
    )


def test_two_duplicated_records_are_reported_in_a_content_determined_order():
    # Two groups with the same count would otherwise be separated only by
    # insertion order, and insertion order is input order (CLAUDE.md 4).
    def report(data):
        stream = read_trace(data)
        list(stream)
        return [d.source for d in stream.diagnostics.collected()]

    forwards = report(b'{"a":1}\n{"a":1}\n{"b":2}\n{"b":2}\n')
    backwards = report(b'{"b":2}\n{"b":2}\n{"a":1}\n{"a":1}\n')
    assert forwards == backwards
    assert len(forwards) == 2


def test_a_duplicated_record_costs_a_trace_no_span_end_to_end():
    # The audit case as it was reported (probe2, "exact_duplicate_line"): an
    # exporter that sent one span twice must not produce two nodes.
    import spanweave

    def record(span_id, name, kind, parent=None):
        return {
            "trace_id": "t1",
            "span_id": span_id,
            "parent_id": parent,
            "name": name,
            "start_time": 1.0,
            "end_time": 3.0,
            "status": "OK",
            "attributes": {"openinference.span.kind": kind},
        }

    agent = record("s0", "agent.run", "AGENT")
    tool = record("s1", "tool.lookup", "TOOL", parent="s0")
    lines = [agent, tool, tool]
    graph = spanweave.build(
        b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
    )
    assert len(graph) == 2
    assert [d.code for d in graph.diagnostics if d.code == codes.DUPLICATE_RECORD]


# --- OTLP JSON as a container (audit "minor: OTLP JSON envelope refused") ----
#
# `SPEC.md` §7: an `ExportTraceServiceRequest` is a third container, not a
# dialect. The spans inside it are in whatever dialect their instrumentor
# speaks -- possibly two dialects in one export -- so it is unpacked here and
# the records that come out are classified per record like any others (§6.1).
# `OPEN_QUESTIONS.md` §16(b) is why an adapter would have been the wrong shape.


def envelope(*spans, resource=None, scope=None):
    """One `ExportTraceServiceRequest` carrying the given OTLP spans."""
    resource_spans: dict = {"scopeSpans": [{"spans": list(spans)}]}
    if resource is not None:
        resource_spans["resource"] = resource
    if scope is not None:
        resource_spans["scopeSpans"][0]["scope"] = scope
    return {"resourceSpans": [resource_spans]}


OTLP_SPAN = {
    "traceId": "t1",
    "spanId": "s0",
    "parentSpanId": "",
    "name": "chat",
    "startTimeUnixNano": "1700000000000000000",
    "endTimeUnixNano": "1700000000500000000",
    "status": {"code": 1},
    "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}],
}


def only(source):
    stream = read_trace(source)
    records = list(stream)
    assert len(records) == 1, records
    return records[0]


def test_an_otlp_json_document_is_unpacked_into_flat_records():
    record = only(json.dumps(envelope(OTLP_SPAN)).encode("utf-8"))
    assert record == {
        "trace_id": "t1",
        "span_id": "s0",
        "parent_id": "",
        "name": "chat",
        "start_time": "1700000000000000000",
        "end_time": "1700000000500000000",
        "status": "OK",
        "attributes": {"gen_ai.operation.name": "chat"},
    }


def test_a_pretty_printed_otlp_document_reads_the_same_as_a_compact_one():
    # 46 `malformed_record` diagnostics and 0 nodes was the audit's finding;
    # indentation is how every file receiver and every `curl | jq` writes it.
    document = envelope(OTLP_SPAN)
    compact = read_trace(json.dumps(document).encode("utf-8"))
    indented = read_trace(json.dumps(document, indent=2).encode("utf-8"))
    assert list(compact) == list(indented)
    assert len(indented.diagnostics) == 0


def test_a_file_of_one_export_per_line_is_unpacked_line_by_line():
    # The shape that makes a whole-input rule wrong on its own: this begins
    # with the same bytes as a single compact document (`SPEC.md` §7).
    first = dict(OTLP_SPAN, spanId="s0")
    second = dict(OTLP_SPAN, spanId="s1")
    lines = b"".join(
        json.dumps(envelope(span)).encode("utf-8") + b"\n" for span in (first, second)
    )
    stream = read_trace(lines)
    assert [record["span_id"] for record in stream] == ["s0", "s1"]
    assert len(stream.diagnostics) == 0


def test_a_json_array_of_exports_is_unpacked_element_by_element():
    first = dict(OTLP_SPAN, spanId="s0")
    second = dict(OTLP_SPAN, spanId="s1")
    array = json.dumps([envelope(first), envelope(second)]).encode("utf-8")
    assert [record["span_id"] for record in read_trace(array)] == ["s0", "s1"]


def test_a_bom_does_not_hide_the_otlp_form():
    data = b"\xef\xbb\xbf" + json.dumps(envelope(OTLP_SPAN)).encode("utf-8")
    assert only(data)["span_id"] == "s0"


def test_every_other_span_key_is_carried_under_its_own_otlp_name():
    # Losslessness (`CLAUDE.md` 2): the reader never drops an OTLP key and
    # never invents one, so the span is reconstructible from the record.
    span = dict(
        OTLP_SPAN,
        kind=3,
        flags=256,
        traceState="a=1",
        droppedAttributesCount=2,
        events=[{"name": "e", "timeUnixNano": "1"}],
    )
    record = only(json.dumps(envelope(span)).encode("utf-8"))
    assert record["kind"] == 3
    assert record["flags"] == 256
    assert record["traceState"] == "a=1"
    assert record["droppedAttributesCount"] == 2
    assert record["events"] == [{"name": "e", "timeUnixNano": "1"}]


def test_span_kind_is_never_mapped_to_a_node_kind():
    # §16(h): the flat record has no field for an OTLP SpanKind, no dialect
    # reads one, and mapping it would be an interpretation below the seam.
    for reported in (0, 1, 2, 3, 4, 5, "SPAN_KIND_SERVER"):
        record = only(json.dumps(envelope(dict(OTLP_SPAN, kind=reported))).encode())
        assert record["kind"] == reported
        assert "openinference.span.kind" not in record["attributes"]


def test_status_code_is_read_from_the_enum_name_or_its_number():
    for reported, expected in (
        (0, "UNSET"),
        (1, "OK"),
        (2, "ERROR"),
        ("STATUS_CODE_UNSET", "UNSET"),
        ("STATUS_CODE_OK", "OK"),
        ("STATUS_CODE_ERROR", "ERROR"),
    ):
        span = dict(OTLP_SPAN, status={"code": reported})
        assert only(json.dumps(envelope(span)).encode())["status"] == expected


def test_an_unrecognized_status_code_is_carried_verbatim():
    span = dict(OTLP_SPAN, status={"code": 9, "message": "boom"})
    record = only(json.dumps(envelope(span)).encode())
    assert record["status"] == 9
    assert record["status_message"] == "boom"


def test_a_status_object_with_no_code_is_the_default_code_it_declares():
    # proto3 gives every scalar field a default rather than an absence, so
    # `"status": {}` is a `Status` carrying code 0 -- `UNSET` -- and not a span
    # that said nothing about its status (`SPEC.md` §7).
    record = only(json.dumps(envelope(dict(OTLP_SPAN, status={}))).encode())
    assert record["status"] == "UNSET"
    # `message` has no default worth inventing, so none is invented.
    assert "status_message" not in record


def test_an_empty_status_object_stays_distinguishable_from_no_status_at_all():
    # The whole point of the fix, asserted as the one comparison rather than
    # left to fall out of two tests: dropping the key made an export that
    # wrote `"status": {}` read exactly like one that wrote no `status`.
    no_status = {key: v for key, v in OTLP_SPAN.items() if key != "status"}
    present = only(json.dumps(envelope(dict(OTLP_SPAN, status={}))).encode())
    absent = only(json.dumps(envelope(no_status)).encode())
    assert present != absent
    assert present["status"] == "UNSET"
    assert "status" not in absent


def test_an_empty_status_object_reaches_the_built_node_as_unset(tmp_path):
    # Losslessness is about `raw.source`, so the record shape is only half of
    # it: the status the export wrote has to survive onto the node.
    graph = _built(envelope(dict(OTLP_SPAN, status={})), tmp_path)
    (node,) = graph.nodes()
    assert node.raw.source["status"] == "UNSET"
    assert "status_message" not in node.raw.source


def test_an_explicit_zero_and_an_omitted_code_read_the_same():
    # They are the same wire value: proto3 JSON may write a field holding its
    # default or omit it, and both say code 0.
    omitted = only(json.dumps(envelope(dict(OTLP_SPAN, status={}))).encode())
    written = only(json.dumps(envelope(dict(OTLP_SPAN, status={"code": 0}))).encode())
    assert omitted["status"] == written["status"] == "UNSET"


def test_a_status_with_a_message_and_no_code_carries_both():
    # The same proto3 argument: a `Status` that writes a message and no code is
    # an `UNSET` status with a message, not a message with no status.
    span = dict(OTLP_SPAN, status={"message": "boom"})
    record = only(json.dumps(envelope(span)).encode())
    assert record["status"] == "UNSET"
    assert record["status_message"] == "boom"


def test_a_populated_status_is_untouched_by_the_default():
    # A guard on the scope of the rule: reading an omitted `code` as 0 must not
    # reach a `Status` that stated one.
    span = dict(OTLP_SPAN, status={"code": 2, "message": "boom"})
    record = only(json.dumps(envelope(span)).encode())
    assert record["status"] == "ERROR"
    assert record["status_message"] == "boom"


def test_a_status_that_is_not_plain_is_still_carried_verbatim():
    # The other half of the scope: only a `{"code", "message"}` subset is
    # flattened at all, so an object with anything else in it is carried as it
    # arrived and gains no default (`SPEC.md` §7, and `_is_a_plain_status`).
    for reported in ({"unexpected": 1}, {"message": "boom", "unexpected": 1}):
        span = dict(OTLP_SPAN, status=reported)
        record = only(json.dumps(envelope(span)).encode())
        assert record["status"] == reported
        assert "status_message" not in record


def test_an_any_value_is_unwrapped_by_its_tag():
    attributes = [
        {"key": "s", "value": {"stringValue": "a"}},
        {"key": "b", "value": {"boolValue": True}},
        {"key": "d", "value": {"doubleValue": 1.5}},
        {"key": "i", "value": {"intValue": "42"}},
        {"key": "bytes", "value": {"bytesValue": "3q2+7w=="}},
        {"key": "empty", "value": {}},
        {"key": "arr", "value": {"arrayValue": {"values": [{"intValue": "1"}]}}},
        {
            "key": "kv",
            "value": {
                "kvlistValue": {"values": [{"key": "n", "value": {"intValue": "7"}}]}
            },
        },
    ]
    record = only(json.dumps(envelope(dict(OTLP_SPAN, attributes=attributes))).encode())
    assert record["attributes"] == {
        "s": "a",
        "b": True,
        "d": 1.5,
        "i": 42,
        "bytes": "3q2+7w==",
        "empty": None,
        "arr": [1],
        "kv": {"n": 7},
    }


def test_an_int_value_is_decoded_because_the_format_states_its_type():
    # §16(f)/(g): `intValue` is a type tag, so the reader honours it;
    # `startTimeUnixNano` states only a name, so §3.1 reads it instead.
    span = dict(
        OTLP_SPAN,
        attributes=[{"key": "gen_ai.usage.input_tokens", "value": {"intValue": "42"}}],
    )
    record = only(json.dumps(envelope(span)).encode())
    assert record["attributes"]["gen_ai.usage.input_tokens"] == 42
    assert record["start_time"] == "1700000000000000000"


def test_an_int_value_past_the_interpreter_digit_limit_is_carried_verbatim():
    # Batch R1. No `int64` is thousands of digits long, but a trace file can
    # say one is, and `int()` answers a string that long by raising -- which
    # used to come out of `spanweave build` as an interpreter traceback. The
    # reader carries the decimal string it could not convert (`SPEC.md` §7).
    #
    # "That long" is the library's limit, derived rather than written down
    # (batches R14 and S8, `SPEC.md` §5.3), and the same on every interpreter
    # setting.
    digits = digit_limit.past()
    span = dict(OTLP_SPAN, attributes=[{"key": "k", "value": {"intValue": digits}}])
    stream = read_trace(json.dumps(envelope(span)).encode())
    records = list(stream)
    assert records[0]["attributes"]["k"] == digits
    assert len(stream.diagnostics) == 0


def test_an_int_value_that_is_not_an_integer_literal_is_carried_verbatim():
    span = dict(OTLP_SPAN, attributes=[{"key": "k", "value": {"intValue": "twelve"}}])
    assert only(json.dumps(envelope(span)).encode())["attributes"]["k"] == "twelve"


def test_an_unfoldable_attribute_entry_is_kept_rather_than_dropped():
    attributes = [
        {"key": "good", "value": {"stringValue": "a"}},
        "not an object",
        {"value": {"stringValue": "no key"}},
        {"key": 7, "value": {"stringValue": "key is not a string"}},
    ]
    record = only(json.dumps(envelope(dict(OTLP_SPAN, attributes=attributes))).encode())
    assert record["attributes"] == {"good": "a"}
    assert record["attributes_unfolded"] == attributes[1:]


def test_a_repeated_attribute_key_keeps_the_last_and_keeps_both_copies():
    attributes = [
        {"key": "k", "value": {"stringValue": "first"}},
        {"key": "k", "value": {"stringValue": "second"}},
    ]
    record = only(json.dumps(envelope(dict(OTLP_SPAN, attributes=attributes))).encode())
    assert record["attributes"] == {"k": "second"}
    assert record["attributes_unfolded"] == attributes


def test_attributes_unfolded_is_omitted_when_there_is_nothing_to_put_in_it():
    assert "attributes_unfolded" not in only(json.dumps(envelope(OTLP_SPAN)).encode())


def test_resource_and_scope_are_preserved_beside_the_span():
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": "d"}}]}
    scope = {"name": "opentelemetry.instrumentation.openai", "version": "0.1.0"}
    record = only(
        json.dumps(envelope(OTLP_SPAN, resource=resource, scope=scope)).encode()
    )
    # Verbatim: nothing reads these, so folding them would invent a
    # representation nothing has agreed on (§16(i)).
    assert record["resource_spans"] == {"resource": resource}
    assert record["scope_spans"] == {"scope": scope}
    # And never merged into the span's attributes, where they could change
    # which adapter claims the span.
    assert record["attributes"] == {"gen_ai.operation.name": "chat"}


def test_resource_and_scope_are_omitted_when_the_level_carries_only_children():
    record = only(json.dumps(envelope(OTLP_SPAN)).encode())
    assert "resource_spans" not in record
    assert "scope_spans" not in record


def test_an_envelope_level_with_no_spans_is_yielded_rather_than_discarded():
    document = {
        "resourceSpans": [
            {"resource": {"attributes": []}, "schemaUrl": "https://example/1"}
        ]
    }
    record = only(json.dumps(document).encode())
    assert record == {
        "resource_spans": {
            "resource": {"attributes": []},
            "schemaUrl": "https://example/1",
        }
    }


def test_a_scope_level_with_no_spans_is_yielded_rather_than_discarded():
    document = {"resourceSpans": [{"scopeSpans": [{"scope": {"name": "n"}}]}]}
    record = only(json.dumps(document).encode())
    assert record == {"scope_spans": {"scope": {"name": "n"}}}


def test_an_empty_export_reads_as_empty():
    stream = read_trace(b'{"resourceSpans":[]}')
    assert list(stream) == []
    assert len(stream.diagnostics) == 0


def test_a_non_object_where_a_span_was_expected_is_kept_verbatim():
    document = {"resourceSpans": [{"scopeSpans": [{"spans": ["not a span"]}]}]}
    assert only(json.dumps(document).encode()) == "not a span"


def test_a_non_object_where_an_envelope_level_was_expected_is_kept_verbatim():
    assert only(b'{"resourceSpans":["not a resource"]}') == "not a resource"


def test_an_input_whose_first_key_is_resource_spans_but_will_not_parse_falls_back():
    # The safety net under the head scan: what was buffered is read line by
    # line, which is exactly today's output for it (`SPEC.md` §7).
    data = b'{"resourceSpans": oops}\n{"span_id":"s0"}\n'
    stream = read_trace(data)
    assert list(stream) == [{"span_id": "s0"}]
    assert [d.code for d in stream.diagnostics.collected()] == [codes.MALFORMED_RECORD]


def test_a_record_whose_resource_spans_is_not_a_list_is_not_an_envelope():
    # The trigger is the *list*, which is what keeps `resource_spans` -- an
    # object -- from being mistaken for one on a second pass.
    record = {"resourceSpans": {"not": "a list"}}
    assert only(json.dumps(record).encode()) == record


def test_an_object_with_a_second_top_level_key_is_not_an_export():
    # `ExportTraceServiceRequest` has exactly one field, so an object with a
    # second is not one -- and unpacking it would have to decide where that
    # second key went, which is how a reader starts dropping things.
    record = {"resourceSpans": [], "somethingElse": 1}
    assert only(json.dumps(record).encode()) == record


def test_two_copies_of_one_span_in_two_envelopes_are_still_one_record():
    # Expansion happens above deduplication, so an at-least-once export that
    # repeated a whole envelope still produces one node (`SPEC.md` §7).
    data = json.dumps([envelope(OTLP_SPAN), envelope(OTLP_SPAN)]).encode()
    stream = read_trace(data)
    assert len(list(stream)) == 1
    assert [d.code for d in stream.diagnostics.collected()] == [codes.DUPLICATE_RECORD]


def test_links_are_flattened_the_same_way_the_span_is():
    link = {
        "traceId": "t2",
        "spanId": "s9",
        "traceState": "a=1",
        "attributes": [{"key": "why", "value": {"stringValue": "because"}}],
    }
    span = dict(OTLP_SPAN, links=[link])
    record = only(json.dumps(envelope(span)).encode())
    assert record["links"] == [
        {
            "trace_id": "t2",
            "span_id": "s9",
            "traceState": "a=1",
            "attributes": {"why": "because"},
        }
    ]


def test_a_deeply_nested_otlp_document_is_diagnosed_rather_than_raised():
    # Measured, not assumed: the container is unpacked by the same
    # `json.loads` as everything else in this module, and its ceiling moves
    # with the interpreter and with the stack the process was given.
    depth = too_deep_for_nested_lists()
    data = b'{"resourceSpans":' + b"[" * depth + b"]" * depth + b"}"
    stream = read_trace(data)
    assert list(stream) == []
    assert [d.code for d in stream.diagnostics.collected()] == [codes.MALFORMED_RECORD]


def test_an_otlp_export_builds_the_spans_it_carries_end_to_end():
    # The audit case as it was reported (probe1, "otlp_json_envelope"): one
    # unknown node under a forced adapter, and nothing at all under auto.
    import spanweave

    def span(span_id, parent, name, operation, extra):
        return {
            "traceId": "t1",
            "spanId": span_id,
            "parentSpanId": parent,
            "name": name,
            "startTimeUnixNano": "1000",
            "endTimeUnixNano": "2000",
            "status": {"code": 1},
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": operation}},
                *extra,
            ],
        }

    document = envelope(
        span("s0", "", "invoke_agent", "invoke_agent", []),
        span(
            "s1",
            "s0",
            "chat demo-model",
            "chat",
            [
                {"key": "gen_ai.request.model", "value": {"stringValue": "demo-model"}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "42"}},
            ],
        ),
        resource={
            "attributes": [{"key": "service.name", "value": {"stringValue": "d"}}]
        },
    )
    graph = spanweave.build(json.dumps(document).encode("utf-8"))
    assert graph.trace_id == "t1"
    assert [node.kind.value for node in graph.nodes()] == ["agent", "llm"]
    llm = graph.nodes()[1]
    # C3's decision, reached through the reader without the reader applying it.
    assert llm.started_at == 1000 and isinstance(llm.started_at, int)
    assert llm.usage is not None and llm.usage.input_tokens == 42


def test_a_root_span_draws_no_diagnostic_for_the_parent_it_does_not_have():
    """`SPEC.md` §4.0 and §7 — batch R10, found by the R3 memo.

    A root's `parentSpanId` is a proto3 `bytes` field holding its default, and
    a marshaler that emits defaults writes it as `""`. Read as a reference it
    names a span no input can contain, so **every root of every export** drew
    `orphan_parent` — the diagnostic that means "this trace is incomplete",
    on the one span that proves it is not. It is no parent, and it is
    normalized at the seam.
    """
    import spanweave

    root = dict(OTLP_SPAN, spanId="s0", parentSpanId="")
    child = dict(OTLP_SPAN, spanId="s1", parentSpanId="s0")
    graph = spanweave.build(json.dumps(envelope(root, child)).encode("utf-8"))

    assert codes.ORPHAN_PARENT not in [d.code for d in graph.diagnostics]
    assert [(e.src, e.dst) for e in graph.edges() if e.kind is EdgeKind.PARENT] == [
        ("s0", "s1")
    ]
    # Losslessness (`CLAUDE.md` 2): the reader renamed the key and left the
    # value, so what the export wrote is still readable on the node.
    assert graph.node("s0").raw.source["parent_id"] == ""


def test_a_parent_the_export_names_and_does_not_carry_is_still_an_orphan():
    # The other half, and the reason the rule is "exactly the empty string":
    # `orphan_parent` still reports a parent that was *named*. Silencing that
    # would trade one wrong answer for a worse one.
    import spanweave

    named = dict(OTLP_SPAN, spanId="s0", parentSpanId="s9")
    graph = spanweave.build(json.dumps(envelope(named)).encode("utf-8"))
    reported = [d for d in graph.diagnostics if d.code == codes.ORPHAN_PARENT]
    assert [d.source for d in reported] == ["s9"]


def test_an_empty_span_id_is_no_identity_in_the_export_container_too():
    """`SPEC.md` §3.6 — batch S3, the other half of the rule above.

    The sentence the test above rests on — that `""` names a span no input can
    contain — was checkable and, until this batch, false: a span whose
    `spanId` was `""` kept `""` as its node identity, so an export could carry
    exactly the span the reference was said to be unable to name, and R10's
    normalization dropped the `parent` edge between the two without a word.
    An empty `spanId` states no id, so the node id is derived from the
    record's content (§3.6 rule 2), here as in a JSONL file: the container is
    not a dialect and it is not an identity rule either.
    """
    import spanweave

    nameless = dict(OTLP_SPAN, spanId="", parentSpanId="")
    graph = spanweave.build(json.dumps(envelope(nameless)).encode("utf-8"))

    ids = [node.id for node in graph.nodes()]
    assert ids != [""] and ids[0].startswith("sw_")
    # Losslessness (`CLAUDE.md` 2): both empty strings are still on the record.
    assert graph.node(ids[0]).raw.source["span_id"] == ""
    assert graph.node(ids[0]).raw.source["parent_id"] == ""


def test_an_empty_link_target_is_no_link_in_the_export_container_too():
    """`SPEC.md` §3.6 — batch S10, the third reference field.

    `links[].spanId` is a proto3 `bytes` field like `parentSpanId`, so an
    unset one is the empty string. The reader renames it to `span_id` and
    leaves the value, so it meets the same seam reader a JSONL link does:
    no link, and no `link` edge whose `dst` is `""` (run-5 review 3.1) --
    reported, because a link entry that names no span becomes nothing.
    """
    import spanweave

    linked = dict(OTLP_SPAN, links=[{"traceId": "t1", "spanId": ""}])
    graph = spanweave.build(json.dumps(envelope(linked)).encode("utf-8"))

    assert [edge.kind.value for edge in graph.edges()] == []
    reported = [d for d in graph.diagnostics if d.code == "unmapped_attributes"]
    assert [d.source for d in reported] == [["<record>.links[0]"]]
    # Losslessness (`CLAUDE.md` 2): the link is still on the record.
    (node,) = graph.nodes()
    assert node.raw.source["links"] == [{"trace_id": "t1", "span_id": ""}]


def test_no_trace_in_the_tree_reaches_the_otlp_branches():
    """The durable form of "no existing input changed" (`SPEC.md` §7).

    The byte-identity of all 64 traces before and after this branch landed was
    measured once, out of band, and a measurement taken once is a claim with a
    date on it. This is the structural reason underneath it, and it stays
    checkable: both new branches are gated on a single key, and no JSONL input
    in this tree carries it -- at the head, where it would trigger buffering,
    or on a record, where it would trigger expansion.
    """
    import pathlib

    from spanweave.read import _is_an_export, _scan_for_export_key

    root = pathlib.Path(__file__).resolve().parent.parent
    traces = sorted(p for p in root.rglob("*.jsonl") if ".git" not in p.parts)
    assert len(traces) > 40, "vacuous: the corpus was not found"
    for path in traces:
        data = path.read_bytes()
        assert _scan_for_export_key(data) is False, path
        assert not any(_is_an_export(record) for record in read_trace(data)), path


def test_what_a_fuller_envelope_costs_is_diagnostics_and_nothing_else():
    """The half `fixtures/conformance/otlp_container` deliberately leaves out.

    That scenario's envelope is minimal so its expected graph can be
    `llm_tool_llm`'s byte for byte. This adds the three things a real export
    carries and it does not, and pins the whole of the difference: the same
    nodes, the same edges, and one `unmapped_attributes` key per span for each
    thing carried -- which is losslessness being *reported* rather than being
    quiet about it.
    """
    import pathlib

    import spanweave
    from spanweave.serialize import to_document

    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "fixtures/conformance/otlp_container/dialects/openinference.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    minimal = to_document(spanweave.build(json.dumps(document).encode("utf-8")))

    resource_spans = document["resourceSpans"][0]
    resource_spans["resource"] = {
        "attributes": [{"key": "service.name", "value": {"stringValue": "demo"}}]
    }
    resource_spans["scopeSpans"][0]["scope"] = {
        "name": "an.instrumentation",
        "version": "1",
    }
    for span in resource_spans["scopeSpans"][0]["spans"]:
        span["kind"] = 1
    fuller = to_document(spanweave.build(json.dumps(document).encode("utf-8")))

    def without_raw(graph):
        return [
            {key: value for key, value in node.items() if key != "raw"}
            for node in graph["nodes"]
        ]

    assert without_raw(fuller) == without_raw(minimal)
    assert fuller["edges"] == minimal["edges"]

    def unmapped(graph):
        return sorted(
            key
            for diagnostic in graph["diagnostics"]
            if diagnostic["code"] == codes.UNMAPPED_ATTRIBUTES
            for key in diagnostic["source"]
        )

    added = sorted(set(unmapped(fuller)) - set(unmapped(minimal)))
    assert added == ["<record>.kind", "<record>.resource_spans", "<record>.scope_spans"]
    # Every span reports all three, so the fuller export gains a diagnostic on
    # each of the four spans that had none.
    assert len(fuller["diagnostics"]) == len(minimal["diagnostics"]) + 2


def test_shuffling_the_spans_inside_an_export_changes_nothing():
    """Determinism (`CLAUDE.md` 4) at the level the new container introduces.

    Input order must not reach the result, and an export gives order a new
    place to hide: the spans sit in a list inside a document rather than on
    lines, and they are unpacked in the order the list holds them.
    """
    import pathlib

    import spanweave
    from spanweave.serialize import canonical_bytes, to_document

    def without_the_input_fingerprint(graph):
        # `meta.source_digest` fingerprints the input BYTES as given
        # (`SPEC.md` §3.9), so it is *supposed* to move when the bytes move.
        # Everything else is the result, and none of it may.
        document = to_document(graph)
        document["meta"] = {
            key: value
            for key, value in document["meta"].items()
            if key != "source_digest"
        }
        return canonical_bytes(document)

    root = pathlib.Path(__file__).resolve().parent.parent
    path = root / "fixtures/conformance/otlp_container/dialects/otel_genai.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    spans = document["resourceSpans"][0]["scopeSpans"][0]["spans"]
    ordered = without_the_input_fingerprint(spanweave.build(path))
    for rotation in range(1, len(spans)):
        document["resourceSpans"][0]["scopeSpans"][0]["spans"] = (
            spans[rotation:] + spans[:rotation]
        )
        shuffled = spanweave.build(json.dumps(document).encode("utf-8"))
        assert without_the_input_fingerprint(shuffled) == ordered


# --- Numbers no interpreter can hold (batch R1) -----------------------------
#
# `SPEC.md` §3.1 and §7. A JSON number can be written that Python cannot
# read (an integer past the interpreter's integer-string digit limit) or can
# read only as `inf` (`1e400`). Neither may raise out of the reader, and
# neither may reach the output as a token JSON has no word for.


def test_a_bare_integer_past_the_digit_limit_is_a_malformed_record():
    # The reader's parse refuses it, which is already how the reader reports
    # an unreadable line -- pinned here because the *quoted* form of the same
    # number reaches a different layer, and this states which is which.
    # Length derived from the library's constant (batches R14 and S8,
    # `SPEC.md` §5.3).
    digits = digit_limit.past()
    line = f'{{"span_id":"s0","start_time":{digits}}}\n'.encode()
    stream = read_trace(line)
    assert list(stream) == []
    reported = stream.diagnostics.collected()
    assert [d.code for d in reported] == [codes.MALFORMED_RECORD]
    assert digits in reported[0].source


def test_a_quoted_integer_past_the_digit_limit_is_a_record_like_any_other():
    # The reader has no opinion about a string: it is the adapter that must
    # decline to read it as a timestamp (`SPEC.md` §3.1, tests/test_adapters).
    digits = digit_limit.past()
    line = f'{{"span_id":"s0","start_time":"{digits}"}}\n'.encode()
    stream = read_trace(line)
    assert list(stream) == [{"span_id": "s0", "start_time": digits}]
    assert len(stream.diagnostics) == 0


# --- What a real OTLP export's timestamps produce (batch R1, pinned) ---
#
# An OTLP JSON envelope states its unit in the field name -- `startTimeUnixNano`
# -- and the reader carries the value verbatim because §7's rule is that a
# format's *name* is not a type. §3.1's ceiling then fires on every span, and
# on nothing else: a span that really is in seconds is the only one in the file
# NOT warned about.
#
# This is DOCUMENTED behaviour, not merely current behaviour: `SPEC.md` §3.7's
# `timestamp_unit_suspect` row and §7's OTLP container section both state that
# a conformant export draws one warning per span, that it reports the model's
# field contract rather than the telemetry, and that nothing is rescaled. The
# alternatives were weighed and held (`OPEN_QUESTIONS.md` §17, decided (c)).
# So these tests are a contract, not a snapshot: a change that moves them is
# changing what the spec promises, and the spec moves with it.

NS_OTLP_SPAN = {
    "traceId": "t1",
    "spanId": "s0",
    "parentSpanId": "",
    "name": "chat",
    "startTimeUnixNano": "1700000000000000000",
    "endTimeUnixNano": "1700000000500000000",
    "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}],
}


def _built(document, tmp_path, name="otlp.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return spanweave.build(path)


def test_a_nanosecond_otlp_export_builds_and_warns_once_per_span(tmp_path):
    spans = [dict(NS_OTLP_SPAN, spanId=f"s{n}") for n in range(3)]
    graph = _built(envelope(*spans), tmp_path)
    suspect = [d for d in graph.diagnostics if d.code == codes.TIMESTAMP_UNIT_SUSPECT]
    assert [d.node_id for d in suspect] == ["s0", "s1", "s2"]
    # Nothing is rescaled, and every digit the export wrote is still there --
    # `SPEC.md` §7 states the refusal to rescale and why (float64's spacing at
    # this magnitude would merge spans the record kept apart).
    assert graph.nodes()[0].started_at == 1700000000000000000


def test_the_span_that_really_is_in_seconds_is_the_one_not_warned_about(tmp_path):
    # The signal inversion, stated as a test: on an all-nanosecond export the
    # warning is on every span, so the one span it is silent about is the one
    # whose unit differs from its neighbours'. `SPEC.md` §7 states this cost in
    # those terms, so the silence is documented rather than merely observed.
    seconds = dict(
        NS_OTLP_SPAN,
        spanId="s9",
        startTimeUnixNano="1700000000",
        endTimeUnixNano="1700000001",
    )
    graph = _built(envelope(NS_OTLP_SPAN, seconds), tmp_path)
    suspect = [d for d in graph.diagnostics if d.code == codes.TIMESTAMP_UNIT_SUSPECT]
    assert [d.node_id for d in suspect] == ["s0"]


# --- Records from bytes in memory (`SPEC.md` §7) -----------------------------
#
# The reader's other door, and the one a receiver needs: `OPEN_QUESTIONS.md`
# §19 asks for the container parsing above on records *in flight* -- an
# OTLP/HTTP request body, a chunk tailed off an exporter, a message off a
# queue -- rather than on a path. It is the same function underneath, so an
# export cannot read one way from a file and another way in memory.


def test_read_records_is_on_the_public_api():
    assert "read_records" in spanweave.__all__
    assert "Records" in spanweave.__all__


def test_read_records_unpacks_an_export_that_never_touched_a_file():
    data = json.dumps(envelope(OTLP_SPAN)).encode("utf-8")
    result = spanweave.read_records(data)
    assert result.records == (
        {
            "trace_id": "t1",
            "span_id": "s0",
            "parent_id": "",
            "name": "chat",
            "start_time": "1700000000000000000",
            "end_time": "1700000000500000000",
            "status": "OK",
            "attributes": {"gen_ai.operation.name": "chat"},
        },
    )
    assert result.diagnostics == ()
    assert result.skipped_records == 0


def test_read_records_reads_every_container_the_path_form_reads():
    # The four shapes `OPEN_QUESTIONS.md` §16(d) separates, each read by the
    # one implementation: a difference here would be a second reader.
    document = json.dumps(envelope(OTLP_SPAN)).encode("utf-8")
    second = json.dumps(envelope(dict(OTLP_SPAN, spanId="s1"))).encode("utf-8")
    for data in (JSONL, ARRAY, document, document + b"\n" + second + b"\n"):
        assert spanweave.read_records(data).records == tuple(read_trace(data))


def test_read_records_holds_its_diagnostics_before_anything_is_iterated():
    # A `RecordStream` fills its diagnostics *while* it is iterated, which is
    # honest for a file and a trap for a caller handed bytes: the bytes are
    # already in memory, so there is nothing to stream and nothing to arrive
    # late. The result is complete when it is returned.
    result = spanweave.read_records(b'{"span_id":"s0"}\n{oops\n')
    assert [d.code for d in result.diagnostics] == [codes.MALFORMED_RECORD]
    assert result.skipped_records == 1
    assert result.records == ({"span_id": "s0"},)


def test_read_records_never_raises_on_bytes_that_are_not_json_at_all():
    result = spanweave.read_records(b"not json at all\n")
    assert result.records == ()
    assert [d.code for d in result.diagnostics] == [codes.MALFORMED_RECORD]


def test_read_records_collapses_a_duplicate_exactly_as_a_file_does():
    data = b'{"span_id":"s0"}\n{"span_id":"s0"}\n'
    result = spanweave.read_records(data)
    assert result.records == ({"span_id": "s0"},)
    assert [d.code for d in result.diagnostics] == [codes.DUPLICATE_RECORD]
    # A duplicate is not a loss: an identical copy was read (`SPEC.md` §7).
    assert result.skipped_records == 0


def test_read_records_iterates_so_the_result_feeds_a_builder_directly():
    result = spanweave.read_records(JSONL)
    assert list(result) == list(result.records) == RECORDS


def test_a_records_result_is_frozen_like_every_other_value_the_library_hands_back():
    result = spanweave.read_records(JSONL)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.records = ()


def test_read_records_refuses_a_str_rather_than_reading_it_as_content():
    with pytest.raises(TypeError) as failure:
        spanweave.read_records('{"span_id":"s0"}')
    assert "bytes" in str(failure.value)
    # The refusal keeps the reason it was made for: a `str` is a path, and the
    # buffers now accepted beside `bytes` do not change that (`SPEC.md` §7).
    assert "path" in str(failure.value)


def test_read_records_does_not_open_the_file_a_str_would_have_named(tmp_path):
    # The door this refusal closes. Everywhere else in this library a `str` is
    # a path, so a `read_records` that read one as content would turn
    # `read_records("trace.jsonl")` into an empty read with no complaint --
    # and one that passed it through to `read_trace` would read the file, from
    # a function whose whole contract is that it touches no file.
    path = tmp_path / "trace.jsonl"
    path.write_bytes(JSONL)
    with pytest.raises(TypeError):
        spanweave.read_records(str(path))


# --- What `data` may be (`SPEC.md` §7) ---------------------------------------
#
# A receiver holding bytes in flight holds them in a `bytearray` it appends to,
# or in a `memoryview` of one. Refusing those made it write `bytes(buf)` on
# every call -- a copy charged to the caller by a refusal whose stated reason
# (a `str` is a path) says nothing about either of them (live-graphs L13,
# registered in `TASKS.md`).
# The copy, where one is needed at all, is the library's.


def test_read_records_reads_a_bytearray_accumulator_in_place():
    buffer = bytearray()
    buffer += JSONL
    assert spanweave.read_records(buffer) == spanweave.read_records(bytes(buffer))
    assert spanweave.read_records(buffer).records == tuple(RECORDS)


def test_read_records_reads_a_memoryview_of_an_accumulator_in_place():
    buffer = bytearray(JSONL)
    assert spanweave.read_records(memoryview(buffer)) == spanweave.read_records(
        bytes(buffer)
    )
    # A view of read-only bytes is the same read; `readonly` is not a property
    # of the bytes, and this layer writes to nothing either way.
    assert spanweave.read_records(memoryview(JSONL)).records == tuple(RECORDS)


def test_read_records_reads_a_multidimensional_byte_view_as_the_run_under_it():
    # Contiguous and one byte per item, so the bytes it names are the bytes
    # underneath it in C order -- the same run, differently shaped.
    buffer = bytearray(JSONL)
    shaped = memoryview(buffer).cast("B", shape=[2, len(buffer) // 2])
    assert spanweave.read_records(shaped).records == tuple(RECORDS)


def test_a_write_after_the_call_cannot_change_what_the_call_returned():
    # `read_records` is complete when it returns (`SPEC.md` §7), and a caller
    # holding a `bytearray` goes on writing into it. The copy that makes the
    # result independent of that is the library's, not a rule for the caller.
    buffer = bytearray(JSONL)
    result = spanweave.read_records(buffer)
    view = memoryview(buffer)
    from_view = spanweave.read_records(view)
    view[:] = b"x" * len(buffer)
    view.release()
    buffer += b'{"span_id":"written-after"}\n'
    assert result.records == tuple(RECORDS)
    assert from_view.records == tuple(RECORDS)


# The two refusals below share one message, which names both conditions, so
# neither "one byte per item" nor "contiguous" tells the two refused shapes
# apart: each is in the message whichever shape was passed. What does tell them
# apart is the shape the message interpolates, and each test asserts its own and
# denies the other's, so swapping which condition reports which fails a test
# rather than nothing (`patches/REVIEW-2026-10-01.md` finding 7).


def test_read_records_refuses_a_memoryview_whose_items_are_wider_than_a_byte():
    # Rendering one to bytes takes the machine's own endianness, so the same
    # input would read differently on another machine (`CLAUDE.md` 4).
    wide = memoryview(bytearray(JSONL)).cast("H")
    with pytest.raises(TypeError) as failure:
        spanweave.read_records(wide)
    message = str(failure.value)
    assert "memoryview" in message
    assert "one byte per item" in message
    # Wide items, laid out contiguously: that pair, and not the strided one.
    assert wide.itemsize == 2 and wide.c_contiguous
    assert "itemsize 2 with c_contiguous=True" in message, (
        "the refusal did not report the shape it refused"
    )
    assert "c_contiguous=False" not in message


def test_read_records_refuses_a_memoryview_that_is_not_a_contiguous_run():
    every_other = memoryview(bytearray(JSONL))[::2]
    with pytest.raises(TypeError) as failure:
        spanweave.read_records(every_other)
    message = str(failure.value)
    assert "contiguous" in message
    # Single bytes, strided: the other half of the same condition, and the one
    # discriminator between the two refusals.
    assert every_other.itemsize == 1 and not every_other.c_contiguous
    assert "itemsize 1 with c_contiguous=False" in message, (
        "the refusal did not report the shape it refused"
    )
    assert "itemsize 2" not in message


def test_read_records_reports_no_digest_because_build_is_what_fingerprints_bytes():
    # `SPEC.md` §10.4: a builder fed records carries no `source_digest`, so the
    # digest has no consumer on this path and is not offered on it.
    result = spanweave.read_records(JSONL)
    assert not hasattr(result, "digest")


# --- What one call does not carry into the next (`SPEC.md` §7) ---------------
#
# The two properties a receiver is designed against (live-graphs L7,
# registered in `TASKS.md`): a
# `Records` is complete when it is returned, and dedup is a property of one
# input. Both are about what the reader does **not** remember between calls,
# which is exactly what a test written inside one call cannot see. Each of the
# two below carries its own bytes, asserts the whole property itself, and bites
# when it is the only test that runs -- verified by running each one alone
# under a mutation that breaks it (`patches/REVIEW-2026-09-30.md` B2 and N1).


def test_an_unterminated_tail_is_diagnosed_in_its_own_call_and_never_the_next():
    """No buffering across calls: the fragment is a loss, not a pending record.

    A receiver tailing an exporter hands over whatever bytes it has, and the
    last of them is often half a line. The reader does not hold that half back
    hoping for the rest: the terminator is the LF (§7), so the tail is the last
    line, it is one `malformed_record` carrying its text, and it counts once in
    `skipped_records`. The alternative -- remember the fragment and rejoin it to
    the next call's first bytes -- would make a `Records` incomplete when it was
    returned, which §7 says it never is, and would silently invent a record out
    of two calls a caller may have made about two different streams.
    """
    fragment = b'{"span_id":"carry-s1","na'
    first = spanweave.read_records(b'{"span_id":"carry-s0"}\n' + fragment)
    assert first.records == ({"span_id": "carry-s0"},)
    assert [d.code for d in first.diagnostics] == [codes.MALFORMED_RECORD], (
        "the unterminated tail was not reported in the call that received it"
    )
    assert first.diagnostics[0].source == fragment.decode("utf-8")
    assert first.skipped_records == 1, "the tail is a record that was never read"

    # The rest of that line, as the next call would deliver it. On its own it is
    # not JSON either, so a reader that had kept the fragment would show it by
    # producing a *record* here -- and one that had not, by producing none.
    second = spanweave.read_records(b'me":"x"}\n')
    assert second.records == (), "a fragment from an earlier call was rejoined here"
    assert [d.code for d in second.diagnostics] == [codes.MALFORMED_RECORD]
    assert second.skipped_records == 1


def test_the_same_record_in_two_calls_is_read_twice_and_diagnosed_in_neither():
    """Dedup is a property of one input, and two calls are two inputs.

    An at-least-once exporter resends; a receiver that calls the reader twice
    with the same span gets it twice, because the reader has no memory to answer
    the question with. It must not answer it anyway: a cross-call
    `duplicate_record` would report a fact about the second call's input that is
    not true of it, and dropping the record would leave a receiver that
    restarted its builder holding a graph with a hole in it. Deciding whether
    two arrivals are one operation is the receiver's call, on `feed`.
    """
    data = b'{"span_id":"retried-s0"}\n'
    first = spanweave.read_records(data)
    second = spanweave.read_records(data)
    assert first.records == ({"span_id": "retried-s0"},)
    assert second.records == first.records, "the second call dropped the record"
    assert first.diagnostics == ()
    assert second.diagnostics == (), (
        "a duplicate was reported across calls; the second call's input has "
        "one copy of one record in it"
    )
    assert first.skipped_records == 0
    assert second.skipped_records == 0

    # And the boundary is the call, not the absence of dedup: the same two
    # copies inside one call still collapse to one record and one report (§7).
    together = spanweave.read_records(data + data)
    assert together.records == first.records
    assert [d.code for d in together.diagnostics] == [codes.DUPLICATE_RECORD]
    assert together.skipped_records == 0


# The two above pin "neither buffers nor rejoins across calls" (§7) where lines
# are the unit. The sentence is not qualified by container, and the other two --
# the JSON array and the OTLP export document -- are the ones a reader has to
# buffer whole, so they are where a carry buffer would be easiest to introduce
# and hardest to see. The two below carry the same structure one container over
# (`patches/REVIEW-2026-10-01.md` finding 2): a trailing fragment is one
# `malformed_record` with `skipped_records=1` in the call that received it, and
# the bytes that would complete it produce no record in the next call. Each one
# brings its own bytes and bites alone.


def test_an_unterminated_array_is_diagnosed_in_its_own_call_and_never_the_next():
    """An array cut short is a loss in its own call, not a record held open.

    The array form is the one place laziness is impossible -- it is not a record
    until its closing bracket arrives -- so a reader tempted to wait for that
    bracket would wait across the call boundary. It does not: the whole
    container is one `malformed_record`, counted once because how many records
    it held is exactly what could not be read (§3.7), and the remainder of the
    array is read on its own terms in the next call, where it is not JSON
    either.
    """
    whole = b'[{"span_id":"array-carry-s0"},{"span_id":"array-carry-s1"}]'
    cut = whole.index(b",") + 1
    opening, remainder = whole[:cut], whole[cut:]

    first = spanweave.read_records(opening)
    assert first.records == (), "a half-read array yielded a record"
    assert [d.code for d in first.diagnostics] == [codes.MALFORMED_RECORD], (
        "the unterminated array was not reported in the call that received it"
    )
    assert "could not be read as a JSON array" in first.diagnostics[0].message, (
        "the array container did not report this; the branch under test is not "
        "the one that ran"
    )
    assert first.diagnostics[0].source == opening.decode("utf-8")
    assert first.skipped_records == 1, "the array is records that were never read"

    # The bytes that would close it. A reader holding the opening would show it
    # by producing the two records here; one holding nothing produces none,
    # because these bytes are not a record on their own.
    second = spanweave.read_records(remainder)
    assert second.records == (), (
        "an array fragment from an earlier call was rejoined here"
    )
    assert [d.code for d in second.diagnostics] == [codes.MALFORMED_RECORD]
    assert second.skipped_records == 1
    # Stated so the two-call claim cannot be mistaken for a claim that the
    # bytes are unreadable: joined, they are two records.
    assert len(spanweave.read_records(whole).records) == 2


def test_an_unterminated_export_document_is_diagnosed_in_its_own_call_too():
    """An OTLP document cut short is a loss in its own call as well.

    This container is buffered for the array's reason and reached by a head
    scan of one member key, so a truncated export is read as far as the scan
    went and then refused. The refusal is the line reader's, because an input
    that is not a single document is read line by line -- what matters here is
    that the refusal happens *now*, and that the bytes completing the document
    cannot combine with it in the next call.
    """
    whole = (
        b'{"resourceSpans":[{"scopeSpans":[{"spans":'
        b'[{"spanId":"doc-carry-s0","name":"doc-carry"}]}]}]}'
    )
    cut = whole.index(b'"spans"')
    opening, remainder = whole[:cut], whole[cut:]

    first = spanweave.read_records(opening)
    assert first.records == (), "a half-read export document yielded a record"
    assert [d.code for d in first.diagnostics] == [codes.MALFORMED_RECORD], (
        "the unterminated document was not reported in the call that received it"
    )
    assert first.diagnostics[0].source == opening.decode("utf-8")
    assert first.skipped_records == 1

    second = spanweave.read_records(remainder)
    assert second.records == (), (
        "a document fragment from an earlier call was rejoined here"
    )
    assert [d.code for d in second.diagnostics] == [codes.MALFORMED_RECORD]
    assert second.skipped_records == 1
    # Joined, they are the one span the export carries -- so the two empty
    # reads above are about the call boundary, not about unreadable bytes.
    assert spanweave.read_records(whole).records == (
        {"span_id": "doc-carry-s0", "name": "doc-carry"},
    )


# --- Bytes UTF-8 cannot decode (`SPEC.md` §3.7, §7) --------------------------
#
# The reader decodes with `errors="replace"`, so a byte sequence that is not
# UTF-8 becomes U+FFFD and the record is read anyway. That is the right
# outcome -- what did decode is still there, and discarding the record would
# lose it -- and until this batch it was a *silent* one: the record arrived
# carrying a character nothing in the input wrote, and no diagnostic said so
# (`patches/REVIEW-2026-09-30.md` T12). A receiver is where it matters most,
# because a chunk tailed off an exporter can split a multi-byte sequence in
# half and the reader does not rejoin across calls (§7).


def test_bytes_that_are_not_utf8_are_still_read_and_the_substitution_is_reported():
    result = spanweave.read_records(b'{"span_id":"\xff\xfe"}\n')
    # Read, not refused: U+FFFD is Unicode's own substitution, and the rest of
    # the record is exactly what the input wrote.
    assert result.records == ({"span_id": "��"},)
    assert [d.code for d in result.diagnostics] == [codes.UNDECODABLE_BYTES], (
        "the substitution was made and nothing reported it"
    )
    diagnostic = result.diagnostics[0]
    assert "line 1" in diagnostic.message, "the diagnostic does not name the line"
    # No fragment: JSON has no bytes to carry, and the text they were replaced
    # by is on the record itself (`SPEC.md` §3.7).
    assert diagnostic.source is None
    # The record was read, so nothing was skipped -- the count is unmoved by
    # this code, which is the difference between it and `malformed_record`.
    assert result.skipped_records == 0


def test_a_multi_byte_sequence_split_across_two_calls_is_two_reports_not_a_record():
    """The receiver case, and why §7 tells a receiver to split on `\\n` itself.

    `"\\xc3\\xa9"` is one character in two bytes. A chunk boundary between them
    leaves each call holding half a character, and the reader neither buffers
    nor rejoins across calls (§7): each half is one `undecodable_bytes` and one
    `malformed_record`, and no record is invented out of two calls that may
    have been about two different streams.
    """
    whole = b'{"span_id":"\xc3\xa9"}\n'
    head, tail = whole[:13], whole[13:]
    assert head.endswith(b"\xc3") and tail.startswith(b"\xa9"), "the split moved"

    for part, half in (
        (spanweave.read_records(head), "first"),
        (spanweave.read_records(tail), "second"),
    ):
        assert part.records == (), f"the {half} half of one character became a record"
        assert sorted(d.code for d in part.diagnostics) == [
            codes.MALFORMED_RECORD,
            codes.UNDECODABLE_BYTES,
        ], f"the {half} half was not reported twice over: unreadable, and not UTF-8"
        assert part.skipped_records == 1

    # The same bytes in one call are one record with nothing to report, which
    # is the whole of the advice §7 gives a receiver.
    together = spanweave.read_records(head + tail)
    assert together.records == ({"span_id": "é"},)
    assert together.diagnostics == ()
    assert together.skipped_records == 0


def test_a_file_of_those_bytes_reads_exactly_as_the_bytes_in_memory_did(tmp_path):
    # Every reading path meets the same decoder, so a file and a body cannot
    # disagree about what is in them.
    data = b'{"span_id":"\xff\xfe"}\n'
    path = tmp_path / "trace.jsonl"
    path.write_bytes(data)

    stream = read_trace(path)
    records = list(stream)
    in_memory = spanweave.read_records(data)

    assert records == list(in_memory.records) == [{"span_id": "��"}]
    assert [d.code for d in stream.diagnostics.collected()] == [
        codes.UNDECODABLE_BYTES
    ], "a file's bytes were replaced with nothing said about it"
    assert [(d.code, d.message, d.source) for d in stream.diagnostics.collected()] == [
        (d.code, d.message, d.source) for d in in_memory.diagnostics
    ]
    assert stream.skipped_records == in_memory.skipped_records == 0


def test_every_container_reports_the_bytes_it_could_not_decode():
    # Three decode sites, one per container form, and the line reader is the
    # one above. None of them may replace a byte without saying so.
    array = spanweave.read_records(b'[{"span_id":"\xff"}]')
    assert array.records == ({"span_id": "�"},)
    assert [d.code for d in array.diagnostics] == [codes.UNDECODABLE_BYTES]

    export = spanweave.read_records(
        b'{"resourceSpans":[{"scopeSpans":[{"spans":[{"spanId":"\xff"}]}]}]}'
    )
    assert export.records == ({"span_id": "�"},)
    assert [d.code for d in export.diagnostics] == [codes.UNDECODABLE_BYTES]


def test_the_document_branch_that_falls_back_to_lines_reports_the_bytes_once():
    """The one path that decodes the same bytes twice must report them once.

    An input whose first member key is `resourceSpans` is buffered and parsed
    as one document; when that fails it is read line by line instead (§7), so
    the bytes pass a decoder twice. Two diagnostics for one substitution would
    report the reader's own second attempt as a second fact about the input.
    """
    result = spanweave.read_records(
        b'{"resourceSpans":[{"a":"\xff"}\n{"resourceSpans":[]}\n'
    )
    assert result.records == ()
    assert [d.code for d in result.diagnostics] == [
        codes.MALFORMED_RECORD,
        codes.UNDECODABLE_BYTES,
    ]
    undecodable = next(
        d for d in result.diagnostics if d.code == codes.UNDECODABLE_BYTES
    )
    assert "line 1" in undecodable.message, "the surviving report lost the line"
    assert result.skipped_records == 1
