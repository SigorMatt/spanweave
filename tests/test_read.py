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
