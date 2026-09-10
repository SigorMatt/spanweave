"""Serialization and validation (TASKS.md 1.8)."""

import json
import pathlib

import pytest

import spanweave
from spanweave.serialize import ROOT_KEYS, canonical_bytes, dumps, to_document, validate

FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"
)
RECORDS = [
    json.loads(line)
    for line in FIXTURE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]


@pytest.fixture
def document():
    return to_document(spanweave.build(FIXTURE))


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def test_the_document_has_the_root_keys_and_says_which_schema(document):
    assert set(document) == set(ROOT_KEYS)
    assert document["schema_version"] == spanweave.SCHEMA_VERSION
    assert document["schema_version"].startswith("0.")  # unfrozen, and says so


def test_a_node_carries_everything_the_model_says_it_does(document):
    node = document["nodes"][1]
    assert node["id"] == "s1"
    assert node["kind"] == "llm"
    assert node["usage"] == {
        "input_tokens": 42,
        "output_tokens": 17,
        "total_tokens": None,
        "extra": {},
    }
    # The instrumentor emits input.value on every LLM span (the fixture was
    # corrected against a captured trace).
    assert node["inputs"]["state"] == "present"
    assert node["provenance"]["adapter_id"] == "openinference"


def test_the_verbatim_source_round_trips_byte_for_byte(document):
    # Losslessness, checked the only way that means anything: what comes out
    # re-encodes to what went in (SPEC.md §3.5).
    for record, node in zip(
        RECORDS, sorted(document["nodes"], key=lambda n: n["id"]), strict=True
    ):
        assert node["raw"]["source"] == record
        assert json.dumps(node["raw"]["source"], sort_keys=True) == json.dumps(
            record, sort_keys=True
        )


def test_an_integer_timestamp_is_written_as_the_integer_it_was_reported_as():
    # Round-tripping (batch C3): a time reported as an integer literal comes
    # back out as the identical literal, so a consumer can compare the graph
    # against its own input without re-reading `raw.source`. Written from a
    # trace rather than a hand-built node so the whole path is under test.
    reported = 1700000000100000100
    trace = (
        b'{"trace_id":"t1","span_id":"s0","name":"op","start_time":'
        + str(reported).encode()
        + b',"attributes":{"openinference.span.kind":"CHAIN"}}\n'
    )
    body = dumps(spanweave.build(trace))
    assert b'"started_at":1700000000100000100' in body


def test_the_line_number_is_not_written_out(document):
    # It depends on where a record sat in one file, and the graph must not.
    assert "line_number" not in document["nodes"][0]["raw"]


def test_meta_carries_no_trace_of_the_machine_that_built_it(document):
    meta = document["meta"]
    assert set(meta) == {
        "spanweave_version",
        "adapters",
        "source_digest",
        "node_count",
        "edge_count",
        "diagnostic_count",
    }
    text = json.dumps(meta)
    for leak in [str(pathlib.Path.cwd()), "/home", "built_at"]:
        assert leak not in text


def test_annotations_are_written_in_their_stated_order():
    graph = (
        spanweave.build(FIXTURE)
        .annotate("s2", "zed", "k", 1)
        .annotate("s1", "abc", "k", 2)
    )
    written = to_document(graph)["annotations"]
    assert [(a["namespace"], a["node_id"]) for a in written] == [
        ("abc", "s1"),
        ("zed", "s2"),
    ]


def test_annotations_round_trip_through_the_file():
    graph = spanweave.build(FIXTURE).annotate("s2", "my_evals", "note", {"n": [1, 2]})
    reread = json.loads(dumps(graph))
    assert reread["annotations"][0]["value"] == {"n": [1, 2]}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_a_freshly_built_graph_validates(document):
    assert validate(document) == ()


def test_something_that_is_not_a_graph_is_reported_not_raised():
    assert validate("nope") != ()
    assert validate({"nodes": []}) != ()
    assert validate(None) != ()


def test_a_dangling_edge_is_caught(document):
    document["edges"].append(
        {
            "src": "s0",
            "dst": "ghost",
            "kind": "parent",
            "warrant": "explicit",
            "basis": "x",
        }
    )
    document["meta"]["edge_count"] += 1
    assert any("not here" in problem for problem in validate(document))


def test_a_dangling_link_is_allowed_because_links_leave_the_trace(document):
    document["edges"].append(
        {
            "src": "s0",
            "dst": "elsewhere",
            "kind": "link",
            "warrant": "explicit",
            "basis": "span.link",
        }
    )
    document["meta"]["edge_count"] += 1
    document["edges"].sort(key=lambda e: (e["kind"], e["src"], e["dst"], e["basis"]))
    assert validate(document) == ()


def test_duplicate_node_ids_are_caught(document):
    document["nodes"].append(document["nodes"][0])
    document["meta"]["node_count"] += 1
    assert any("not unique" in problem for problem in validate(document))


def test_edges_out_of_canonical_order_are_caught(document):
    document["edges"].reverse()
    assert any("canonical order" in problem for problem in validate(document))


def test_counts_that_disagree_with_the_content_are_caught(document):
    document["meta"]["node_count"] = 99
    assert any("node_count" in problem for problem in validate(document))


def test_an_environment_leak_in_meta_is_caught(document):
    document["meta"]["built_at"] = "2026-08-21T00:00:00Z"
    assert any("built_at" in problem for problem in validate(document))


def test_a_foreign_schema_version_is_flagged_not_rejected(document):
    document["schema_version"] = "0.0-from-the-future"
    problems = validate(document)
    assert any("not frozen" in problem for problem in problems)


# --------------------------------------------------------------------------
# The encoder's own containment (September 2026 audit, finding 3, batch A6;
# the claim about *why* it is reachable corrected in batch R6)
# --------------------------------------------------------------------------


def _nest(depth):
    """A list nested `depth` deep, built without recursing to build it."""
    value = []
    for _ in range(depth):
        value = [value]
    return value


def test_a_value_too_deep_to_encode_is_a_refusal_not_a_traceback():
    # `json.dumps` answers nesting it will not descend with RecursionError,
    # exactly as `json.loads` does, and this is the one encoder every byte
    # this library writes goes through. Uncontained it took down a build that
    # had already read its input without complaint -- a graph the library
    # holds and cannot write is a structural impossibility (`SPEC.md` §3.10),
    # so it is named rather than raised as an interpreter's traceback.
    with pytest.raises(spanweave.SpanweaveError) as failure:
        canonical_bytes({"deep": _nest(100_000)})
    assert failure.value.code == "graph_not_serializable"


def test_the_refusal_is_the_librarys_own_error_type():
    # A consumer routes on the library's error, per `SPEC.md` §3.10, and a
    # bare RecursionError is not routable: it is indistinguishable from a bug
    # in the consumer's own recursion.
    with pytest.raises(spanweave.GraphNotSerializableError):
        canonical_bytes(_nest(100_000))


def _deepest_accepted(attempt):
    """The deepest nesting `attempt` survives, found by bisection.

    Measured, never hard-coded: the ceiling belongs to the interpreter's C
    recursion budget, not to this library, and it differs between builds and
    between embedders (`SPEC.md` §7).
    """

    def survives(depth):
        try:
            attempt(depth)
        # The encoder reports depth as its own refusal (above), the parser
        # reports it as the interpreter's `RecursionError`. Same fact.
        except (RecursionError, spanweave.GraphNotSerializableError):
            return False
        return True

    low, high = 1, 2
    while survives(high):
        low, high = high, high * 2
        assert high < 10**7, "no depth this interpreter refuses"
    while high - low > 1:
        middle = (low + high) // 2
        if survives(middle):
            low = middle
        else:
            high = middle
    return low


#: How far apart the two measurements below may land and still be one budget.
#: Each is taken through a different call path -- `json.loads` through the
#: decoder, `canonical_bytes` through `json.dumps` -- and the frames of that
#: path cost a level or two. A *budget* difference would not be this small.
CALL_PATH_SLACK = 16


def test_the_encoder_does_not_give_out_before_the_parser_does():
    # `SPEC.md` §7 used to say writing had a limit *lower* than the parser's.
    # It has the same one: both draw on the interpreter's single C recursion
    # budget, and measured on CPython 3.12.3 they give out within a level of
    # each other (9997 nested containers each, taken at equal call depth).
    # What the old sentence needed -- an encoder that gives out materially
    # earlier -- is what this pins as false, so the story cannot come back.
    parser = _deepest_accepted(lambda depth: json.loads("[" * depth + "]" * depth))
    encoder = _deepest_accepted(lambda depth: canonical_bytes(_nest(depth)))
    assert encoder >= parser - CALL_PATH_SLACK, (
        f"the parser reads {parser} levels and the encoder writes {encoder}"
    )


def _deepest_nesting(value):
    """How many containers deep the deepest value in `value` sits.

    Iterative, because the things this file measures are deeper than the
    interpreter would let a recursive walk go.
    """
    deepest = 0
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            deepest = max(deepest, depth)
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            deepest = max(deepest, depth)
            stack.extend((child, depth + 1) for child in item)
    return deepest


def test_the_document_puts_a_records_value_four_levels_below_where_it_was_read(
    tmp_path,
):
    # What makes the refusal reachable at all is position, not limit: a value
    # the reader met two containers into a trace record -- the record, its
    # `attributes` -- is met by the encoder six containers into the graph
    # document: `nodes`, the node, `raw`, `source`, `attributes`. Those four
    # levels are the whole of the gap (`SPEC.md` §7), so they are measured
    # here rather than asserted in prose, and a document shape that moved
    # them would say so.
    nested = 1
    for _ in range(40):
        nested = {"a": nested}
    record = {
        "trace_id": "t1",
        "span_id": "s0",
        "parent_id": None,
        "name": "n",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": {"openinference.span.kind": "TOOL", "deep": nested},
    }
    trace = tmp_path / "deep.jsonl"
    trace.write_text(json.dumps(record) + "\n", encoding="utf-8")
    document = to_document(spanweave.build(trace))
    assert _deepest_nesting(record) == 42  # the record, `attributes`, 40 more
    assert _deepest_nesting(document) - _deepest_nesting(record) == 4


# --------------------------------------------------------------------------
# The encoder writes JSON, and a non-finite number is not JSON (batch R1)
# --------------------------------------------------------------------------
#
# `SPEC.md` §7: `Infinity`, `-Infinity` and `NaN` are Python's extension to
# JSON rather than JSON, and a strict parser on the other end rejects a
# document carrying one. Writing it is the worst outcome available -- the
# graph is produced, looks written, and cannot be read back -- so the encoder
# runs with `allow_nan=False` and the refusal is the library's own.

NON_FINITE = (float("inf"), float("-inf"), float("nan"))


@pytest.mark.parametrize("value", NON_FINITE, ids=repr)
def test_a_non_finite_number_is_a_refusal_not_a_bare_infinity_token(value):
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        canonical_bytes({"raw": {"source": {"start_time": value}}})
    assert failure.value.code == "graph_not_serializable"


@pytest.mark.parametrize("value", NON_FINITE, ids=repr)
def test_nothing_this_library_writes_can_contain_infinity_or_nan(value):
    # The gate, stated as the property rather than as the call: whatever
    # reaches the one encoder, the bytes that come out parse under a strict
    # JSON parser or there are no bytes at all.
    try:
        written = canonical_bytes({"v": value})
    except spanweave.GraphNotSerializableError:
        return
    json.loads(written, parse_constant=_no_constants)  # pragma: no cover
    raise AssertionError("a non-finite value was written")  # pragma: no cover


def _no_constants(token):
    raise AssertionError(f"the output carried a bare {token} token")


def test_a_trace_carrying_an_unquoted_infinity_refuses_rather_than_writing_it(
    tmp_path,
):
    # End to end, because this is how it reaches the encoder in practice: the
    # timestamp field itself is refused (`SPEC.md` §3.1), but `raw.source` is
    # verbatim and still holds the `inf` the parser produced.
    trace = tmp_path / "infinite.jsonl"
    trace.write_bytes(
        b'{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"n",'
        b'"start_time":1e400,"end_time":2.0,"status":"OK",'
        b'"attributes":{"openinference.span.kind":"AGENT"}}\n'
    )
    graph = spanweave.build(trace)
    node = next(iter(graph.nodes()))
    assert node.started_at is None
    assert with_code(graph, "missing_timestamp")
    with pytest.raises(spanweave.GraphNotSerializableError):
        dumps(graph)


def with_code(graph, code):
    return [item for item in graph.diagnostics if item.code == code]
