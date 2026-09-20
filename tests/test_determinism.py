"""Determinism + losslessness gates (TASKS.md 0.6), each watched failing.

The four properties live in `tests/determinism.py`. Here they are pointed at
deliberately broken fakes, so that every one is seen failing for the reason it
exists.

**Not yet pointed at the real pipeline.** There is none at Phase 0 — no
reader, no builder, no serializer. Task 1.8 wires these same four checks to
`spanweave build` over the worked example, unchanged. Writing them first is
deliberate: a determinism property invented *after* the code it judges tends
to describe the code.
"""

import itertools
import json

import pytest

from tests import determinism

RECORDS = [
    {"span_id": "s0", "name": "agent.run"},
    {"span_id": "s1", "name": "llm.plan"},
    {"span_id": "s2", "name": "tool.lookup"},
]


def _graph_of(records):
    """A minimal well-behaved graph: every record kept, verbatim, sorted."""
    nodes = [{"id": r["span_id"], "raw": {"source": r}} for r in records]
    return {"nodes": sorted(nodes, key=lambda n: n["id"]), "diagnostics": []}


def _canonical_dumps(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# 1. Build twice -> byte-identical
# --------------------------------------------------------------------------


def test_repeatable_holds_for_a_pure_build():
    determinism.assert_repeatable(lambda: _canonical_dumps(_graph_of(RECORDS)))


def test_repeatable_fails_when_a_counter_leaks_into_the_output():
    counter = itertools.count()

    def build():
        return _canonical_dumps({"build": next(counter)})

    with pytest.raises(determinism.PropertyFailed, match="differs from build #1"):
        determinism.assert_repeatable(build)


# --------------------------------------------------------------------------
# 2. Shuffle the input -> byte-identical graph
# --------------------------------------------------------------------------


def test_order_independence_holds_when_the_builder_sorts():
    determinism.assert_order_independent(RECORDS, _graph_of)


def test_order_independence_fails_when_the_builder_trusts_file_order():
    def build(records):
        # The classic bug: nodes emitted in arrival order.
        return {"nodes": [{"id": r["span_id"]} for r in records], "diagnostics": []}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


def test_order_independence_fails_when_dict_insertion_order_decides_it():
    def build(records):
        # The subtler bug, and the one this project is most exposed to: a
        # group-by whose output is emitted in dict insertion order. Sorted
        # *within* each group, arbitrary *between* them.
        groups: dict[str, list[str]] = {}
        for record in records:
            groups.setdefault(record["name"].split(".")[0], []).append(
                record["span_id"]
            )
        return {"nodes": [{"group": g, "ids": sorted(i)} for g, i in groups.items()]}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


# --------------------------------------------------------------------------
# 3. Every input record accounted for
# --------------------------------------------------------------------------


def test_losslessness_holds_when_every_record_is_a_node():
    determinism.assert_every_record_accounted_for(RECORDS, _graph_of(RECORDS))


def test_losslessness_holds_when_a_diagnostic_explains_the_gap():
    graph = {
        "nodes": [],
        "diagnostics": [{"code": "unknown_span_kind", "source": r} for r in RECORDS],
    }
    determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_on_a_silently_dropped_record():
    graph = _graph_of(RECORDS[:-1])
    with pytest.raises(determinism.PropertyFailed, match="silently dropped"):
        determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_when_a_record_is_prettified_on_the_way_in():
    # Losslessness is verbatim-ness, not merely presence: a node whose raw
    # source has been normalized has lost the thing raw exists to keep.
    tidied = [{"span_id": r["span_id"], "name": r["name"].title()} for r in RECORDS]
    with pytest.raises(determinism.PropertyFailed):
        determinism.assert_every_record_accounted_for(RECORDS, _graph_of(tidied))


# --------------------------------------------------------------------------
# 4. The writer is canonical
# --------------------------------------------------------------------------


def test_canonical_writer_passes():
    determinism.assert_canonical_json(_canonical_dumps)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"sort_keys": False}, "not sorted"),
        ({"sort_keys": True, "separators": (", ", ": ")}, "not compact"),
        ({"sort_keys": True, "ensure_ascii": True}, "escaped"),
    ],
)
def test_canonical_writer_fails_on_a_planted_violation(kwargs, expected):
    settings = {"ensure_ascii": False, "separators": (",", ":"), **kwargs}

    def dumps(value):
        return (json.dumps(value, **settings) + "\n").encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match=expected):
        determinism.assert_canonical_json(dumps)


def test_canonical_writer_fails_without_a_trailing_newline():
    def dumps(value):
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match="trailing newline"):
        determinism.assert_canonical_json(dumps)


# --------------------------------------------------------------------------
# The same four properties, now pointed at the real pipeline (TASKS.md 1.8)
# --------------------------------------------------------------------------
#
# This is the half 0.6 could not do: at Phase 0 there was no reader, builder
# or serializer to judge. The checks below are the ones above, unchanged.

import pathlib  # noqa: E402

import spanweave  # noqa: E402
from spanweave.serialize import canonical_bytes  # noqa: E402

WORKED_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
)
WORKED_RECORDS = [
    json.loads(line)
    for line in WORKED_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def _bytes_of(records):
    return b"".join(json.dumps(record).encode("utf-8") + b"\n" for record in records)


def _document_of(records):
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    # source_digest fingerprints the INPUT BYTES, not the graph (SPEC.md
    # §3.9). Shuffling the input changes the bytes by definition; that it
    # changes nothing else is exactly what is being tested here, and the
    # digest's own behavior is asserted separately below.
    document["meta"].pop("source_digest")
    return document


def test_building_the_worked_example_twice_is_byte_identical():
    determinism.assert_repeatable(
        lambda: spanweave.dumps(spanweave.build(WORKED_EXAMPLE))
    )


def test_shuffling_the_worked_example_changes_nothing():
    determinism.assert_order_independent(WORKED_RECORDS, _document_of)


def test_shuffling_produces_identical_bytes_too():
    ordered = canonical_bytes(_document_of(WORKED_RECORDS))
    reversed_input = canonical_bytes(_document_of(list(reversed(WORKED_RECORDS))))
    assert ordered == reversed_input


def test_the_digest_does_change_when_the_bytes_do():
    # Proof that popping it above hides nothing: it is a real fingerprint of
    # a real difference, and it is the only thing that differs.
    forwards = spanweave.build(_bytes_of(WORKED_RECORDS))
    backwards = spanweave.build(_bytes_of(list(reversed(WORKED_RECORDS))))
    assert forwards.meta.source_digest != backwards.meta.source_digest


def test_every_record_of_the_worked_example_is_accounted_for():
    document = spanweave.to_document(spanweave.build(WORKED_EXAMPLE))
    determinism.assert_every_record_accounted_for(WORKED_RECORDS, document)


def test_a_record_the_library_cannot_map_is_still_accounted_for():
    # Losslessness under duress: an unmappable record and a malformed line.
    records = [*WORKED_RECORDS, {"span_id": "s9", "attributes": {"nonsense": 1}}]
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    determinism.assert_every_record_accounted_for(records, document)


def test_the_shipped_writer_is_canonical():
    determinism.assert_canonical_json(canonical_bytes)


def test_the_graph_file_is_one_line_and_ends_in_a_newline():
    written = spanweave.dumps(spanweave.build(WORKED_EXAMPLE))
    assert written.endswith(b"\n")
    assert written.count(b"\n") == 1


# --------------------------------------------------------------------------
# The same properties over records the dialect gives NO span id (batch A5)
# --------------------------------------------------------------------------
#
# Everything above runs on `WORKED_RECORDS`, and every one of those -- like all
# 177 records the corpus held at the time -- carries a span id, so a node id is
# a string the dialect supplied and file order cannot reach it. The one path
# where file order CAN reach an id is the derived one (`SPEC.md` §3.6 rule 2),
# and it was unwatched: the fallback key was the record's 1-based index, so a
# file of span-id-less records rebound its ids when its lines were swapped.
#
# Byte-identity alone does not catch that. Ids are assigned in node order, so
# the two documents matched byte for byte while each id named a different
# record in each -- which is why the binding is asserted separately below.

DERIVED_ID_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/derived_ids/dialects/openinference.jsonl"
)
DERIVED_ID_RECORDS = [
    json.loads(line)
    for line in DERIVED_ID_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_the_span_id_less_records_really_carry_no_span_id():
    # Otherwise everything below is a second run of the tests above.
    assert DERIVED_ID_RECORDS
    assert not any("span_id" in record for record in DERIVED_ID_RECORDS)


def test_shuffling_span_id_less_records_changes_nothing():
    determinism.assert_order_independent(DERIVED_ID_RECORDS, _document_of)


def test_shuffling_span_id_less_records_does_not_rebind_their_ids():
    def binding(records):
        graph = spanweave.build(_bytes_of(records))
        return {node.id: node.raw.source["name"] for node in graph.nodes()}

    forwards = binding(DERIVED_ID_RECORDS)
    assert all(node_id.startswith("sw_") for node_id in forwards)
    assert forwards == binding(list(reversed(DERIVED_ID_RECORDS)))


def test_every_span_id_less_record_is_accounted_for():
    document = spanweave.to_document(spanweave.build(DERIVED_ID_EXAMPLE))
    determinism.assert_every_record_accounted_for(DERIVED_ID_RECORDS, document)


# --------------------------------------------------------------------------
# The same properties over a trace TWO adapters read (batch E3)
# --------------------------------------------------------------------------
#
# Everything above runs on a file one adapter reads whole. Under per-record
# dispatch the records are partitioned before they are parsed, and a partition
# is built by walking the input -- which is a second place file order could
# reach the result, and the only one the shuffle checks above cannot see.

MIXED_EXAMPLE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/mixed_instrumentation/dialects"
    / "openinference+otel_genai.jsonl"
)
MIXED_RECORDS = [
    json.loads(line)
    for line in MIXED_EXAMPLE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def test_the_mixed_records_really_come_from_two_dialects():
    # Otherwise everything below is a third run of the tests above.
    from spanweave.adapters import classify

    assert sorted({classify(record) for record in MIXED_RECORDS}) == [
        ("openinference",),
        ("otel_genai",),
    ]


def test_shuffling_a_mixed_trace_changes_nothing():
    determinism.assert_order_independent(MIXED_RECORDS, _document_of)


def test_shuffling_a_mixed_trace_does_not_rebind_its_ids():
    # A5's lesson, applied to the new mechanism: byte-identity alone would not
    # catch a rebinding, because ids are assigned in node order.
    def binding(records):
        graph = spanweave.build(_bytes_of(records))
        return {
            node.id: (node.raw.source["name"], node.provenance.adapter_id)
            for node in graph.nodes()
        }

    forwards = binding(MIXED_RECORDS)
    assert len(forwards) == 4
    assert forwards == binding(list(reversed(MIXED_RECORDS)))


def test_every_record_of_a_mixed_trace_is_accounted_for():
    document = spanweave.to_document(spanweave.build(MIXED_EXAMPLE))
    determinism.assert_every_record_accounted_for(MIXED_RECORDS, document)


def test_a_record_no_adapter_claims_is_accounted_for_too():
    # Losslessness where it is least automatic: nobody parsed this record, so
    # nothing but the dispatcher could have kept it (`SPEC.md` §6.1).
    records = [*MIXED_RECORDS, {"span_id": "s9", "attributes": {"nonsense": 1}}]
    document = spanweave.to_document(spanweave.build(_bytes_of(records)))
    determinism.assert_every_record_accounted_for(records, document)
    determinism.assert_order_independent(records, _document_of)


# --------------------------------------------------------------------------
# The digit limit is the library's, not the interpreter's (batch S8)
# --------------------------------------------------------------------------
#
# `SPEC.md` §5.3. CPython refuses to convert an integer string longer than
# `sys.get_int_max_str_digits()`, and that limit is a per-interpreter setting:
# 4300 by default, 640 at its lowest, or none at all. Batch R14 named it as an
# input to the graph and measured the two graphs one file produced under two
# settings. Batch S8 removed the input instead: the library owns the limit
# (`DIGIT_LIMIT`, 4300) and applies it by counting digits before any
# conversion, so the same bytes produce the same graph under every setting --
# which is `CLAUDE.md` invariant 4 as written, with no condition on it.
#
# Measured in separate processes, because the setting is process-wide and a
# test that moved it in-process would leave it moved for every test after.

#: Builds the trace at `argv[1]` and writes the graph's bytes to stdout.
_BUILD_AND_WRITE = (
    "import sys, spanweave\n"
    "sys.stdout.buffer.write(spanweave.dumps(spanweave.build(sys.argv[1])))\n"
)

#: Unset, disabled, and the lowest limit the interpreter accepts.
_DIGIT_SETTINGS = (None, "0", "640")


def _digit_limit_trace():
    """Every place an integer literal meets the library, at every boundary.

    Written as text rather than through `json.dumps`, because this process may
    itself be running under the lowest limit, where encoding the literals
    below would raise before any of them reached the library.
    """
    from tests import digit_limit

    past, inside, floor = (
        digit_limit.past(),
        digit_limit.inside(),
        digit_limit.above_the_floor(),
    )
    kind = '"openinference.span.kind":"AGENT"'
    lines = [
        # Quoted, past the library's limit: not read.
        f'{{"trace_id":"t1","span_id":"s0","name":"op","start_time":"{past}",'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
        # Quoted, exactly at it: read, and rendered into two messages.
        f'{{"trace_id":"t1","span_id":"s1","name":"op","start_time":"{inside}",'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
        # Unquoted, past the interpreter's lowest limit and inside the
        # library's: in a span kind, an unmapped attribute and a JSON payload.
        f'{{"trace_id":"t1","span_id":"s2","name":"op","start_time":1700000000,'
        f'"end_time":1700000001,"attributes":{{"openinference.span.kind":{floor},'
        f'"x.count":{inside},"input.mime_type":"application/json",'
        f'"input.value":"{{\\"n\\":{floor}}}"}}}}',
        # Unquoted, past the library's limit: the line is not JSON it reads.
        f'{{"trace_id":"t1","span_id":"s3","name":"op","start_time":{past}}}',
        # Unquoted, exactly at it: read.
        f'{{"trace_id":"t1","span_id":"s4","name":"op","start_time":{inside},'
        f'"end_time":1700000002,"attributes":{{{kind}}}}}',
    ]
    return ("\n".join(lines) + "\n").encode()


def _digit_limit_export():
    """An OTLP export whose `intValue`s sit either side of the limit."""
    from tests import digit_limit

    past, inside = digit_limit.past(), digit_limit.inside()
    attributes = (
        f'{{"key":"gen_ai.operation.name","value":{{"stringValue":"chat"}}}},'
        f'{{"key":"past","value":{{"intValue":"{past}"}}}},'
        f'{{"key":"inside","value":{{"intValue":"{inside}"}}}}'
    )
    span = (
        f'{{"traceId":"t1","spanId":"s0","name":"chat",'
        f'"startTimeUnixNano":"{inside}","endTimeUnixNano":"1700000000",'
        f'"attributes":[{attributes}]}}'
    )
    return f'{{"resourceSpans":[{{"scopeSpans":[{{"spans":[{span}]}}]}}]}}'.encode()


def _built_under(setting, path):
    import os
    import subprocess
    import sys

    environment = dict(os.environ)
    environment.pop("PYTHONINTMAXSTRDIGITS", None)
    if setting is not None:
        environment["PYTHONINTMAXSTRDIGITS"] = setting
    finished = subprocess.run(
        [sys.executable, "-c", _BUILD_AND_WRITE, str(path)],
        capture_output=True,
        env=environment,
        check=False,
    )
    assert finished.returncode == 0, (setting, finished.stderr.decode()[-2000:])
    return finished.stdout


@pytest.mark.parametrize(
    "trace", [_digit_limit_trace, _digit_limit_export], ids=["jsonl", "otlp"]
)
def test_the_digit_limit_setting_does_not_change_the_graph(tmp_path, trace):
    path = tmp_path / "trace.json"
    path.write_bytes(trace())
    built = {setting: _built_under(setting, path) for setting in _DIGIT_SETTINGS}
    assert built[None] == built["0"] == built["640"], (
        "the same bytes built different graphs under different "
        "PYTHONINTMAXSTRDIGITS settings (`SPEC.md` §5.3)"
    )


def test_the_graph_every_setting_agrees_on_is_the_librarys_limit(tmp_path):
    # Identity alone would pass if every setting agreed on the wrong graph.
    # This pins which one: the library's limit, applied as §3.1 and §7 state.
    from tests import digit_limit

    path = tmp_path / "trace.jsonl"
    path.write_bytes(_digit_limit_trace())
    # `parse_int=str` so that reading the result back cannot meet the limit
    # this process may be running under.
    document = json.loads(_built_under("640", path), parse_int=str)
    nodes = {node["raw"]["source"]["span_id"]: node for node in document["nodes"]}
    assert sorted(nodes) == ["s0", "s1", "s2", "s4"]
    assert nodes["s0"]["started_at"] is None
    assert nodes["s0"]["raw"]["source"]["start_time"] == digit_limit.past()
    assert nodes["s1"]["started_at"] == digit_limit.inside()
    assert nodes["s4"]["started_at"] == digit_limit.inside()
    assert nodes["s2"]["attributes"]["reported_kind"] == digit_limit.above_the_floor()
    assert nodes["s2"]["inputs"]["value"] == {"n": digit_limit.above_the_floor()}
    by_code = {}
    for item in document["diagnostics"]:
        by_code.setdefault(item["code"], []).append(item)
    assert "missing_timestamp" in by_code
    assert [item["source"] for item in by_code["malformed_record"]] == [
        f'{{"trace_id":"t1","span_id":"s3","name":"op",'
        f'"start_time":{digit_limit.past()}}}'
    ]
    assert any(
        digit_limit.inside() in item["message"] for item in by_code["nonmonotonic_time"]
    )

    export = tmp_path / "export.json"
    export.write_bytes(_digit_limit_export())
    (node,) = json.loads(_built_under("640", export), parse_int=str)["nodes"]
    assert node["raw"]["source"]["attributes"]["past"] == digit_limit.past()
    assert node["raw"]["source"]["attributes"]["inside"] == digit_limit.inside()
    assert node["started_at"] == digit_limit.inside()


def test_the_guarantee_holds_past_the_digit_limit_in_process():
    determinism.assert_repeatable(
        lambda: spanweave.dumps(spanweave.build(_digit_limit_trace()))
    )
