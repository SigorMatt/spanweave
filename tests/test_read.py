"""The reader (TASKS.md 1.1).

The reader's contract is mostly about what it refuses to do: it does not
raise, it does not drop, and it does not decide what a record means.
"""

import io
import json

import pytest

from spanweave import diagnostics as codes
from spanweave.read import read_trace

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


#: Nesting far past any interpreter's recursion limit. Cheap to build (200 KB
#: of brackets) and cheap to reject: the parser gives up at its own limit, not
#: at the end of the string, so these tests cost microseconds.
DEEP = b"[" * 100_000 + b"]" * 100_000


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
    assert stream.digest == __import__("hashlib").sha256(JSONL).hexdigest()


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
    assert stream.digest == __import__("hashlib").sha256(data).hexdigest()


def test_a_bom_split_across_chunk_boundaries_is_still_one_bom():
    from spanweave.read import RecordStream

    stream = RecordStream("<test>", iter((b"\xef", b"\xbb", b"\xbf", JSONL)))
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_crlf_line_endings_are_read():
    stream = read_trace(b'{"span_id":"s0"}\r\n{"span_id":"s1"}\r\n')
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_cr_only_line_endings_are_read():
    # Classic-Mac and some exporters end lines with CR alone. Without this the
    # whole file is one line, and one line that long is one malformed record:
    # the entire trace lost to a byte.
    stream = read_trace(b'{"span_id":"s0"}\r{"span_id":"s1"}\r')
    assert list(stream) == RECORDS
    assert len(stream.diagnostics) == 0


def test_line_endings_may_be_mixed_within_one_input():
    stream = read_trace(b'{"span_id":"s0"}\r\n{"span_id":"s1"}\r{"span_id":"s2"}\n')
    assert list(stream) == [*RECORDS, {"span_id": "s2"}]
    assert len(stream.diagnostics) == 0


def test_a_crlf_counts_as_one_line_not_two():
    stream = read_trace(b'{"a":1}\r\nbroken\r\n')
    list(stream)
    reported = stream.diagnostics.collected()
    assert "line 2" in reported[0].message
    assert reported[0].source == "broken"


def test_cr_only_lines_are_numbered_the_way_the_file_reads():
    stream = read_trace(b'{"a":1}\r\rbroken\r')
    list(stream)
    assert "line 3" in stream.diagnostics.collected()[0].message


def test_a_crlf_split_across_chunk_boundaries_is_still_one_terminator():
    # The CR arrives in one read and its LF in the next. Treating the CR as a
    # terminator on sight would insert a phantom blank line and shift every
    # line number after it.
    from spanweave.read import RecordStream

    stream = RecordStream("<test>", iter((b'{"a":1}\r', b"\nbroken\r\n")))
    assert list(stream) == [{"a": 1}]
    assert "line 2" in stream.diagnostics.collected()[0].message


def test_a_trailing_cr_at_the_end_of_the_input_ends_the_last_line():
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
