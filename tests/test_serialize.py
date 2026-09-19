"""Serialization and validation (TASKS.md 1.8)."""

import decimal
import json
import pathlib

import pytest

import spanweave
from spanweave import jsoncodec
from spanweave.jsoncodec import DIGIT_LIMIT
from spanweave.serialize import ROOT_KEYS, canonical_bytes, dumps, to_document, validate
from tests.json_depth import (
    MEASUREMENT_NOISE,
    deepest_accepted,
    dicts_text,
    lists_text,
    nested_dicts,
    nested_lists,
)

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


# The run-6 review, S8.2. Since batch S8 the encoder writes an integer of any
# length whole under every interpreter setting, while the reader refuses a
# literal of more than `DIGIT_LIMIT` digits (`SPEC.md` §5.3). An annotation
# holding a longer one was accepted, written, and then refused by the
# library's own reader, so `check_serializable` refuses it up front; one of
# exactly `DIGIT_LIMIT` digits must still go all the way round. Both sides are
# derived from the library's constant, and converted through `Decimal`, as
# `tests/digit_limit.py` requires.


def _integer(text):
    return int(decimal.Decimal(text))


def _placed(number):
    """The integer alone, as a dict value, as a list item, and deep in both."""
    return {
        "alone": number,
        "dict value": {"n": number},
        "list item": [1, number],
        "nested": {"a": [{"b": [number]}]},
    }


@pytest.mark.parametrize("sign", [1, -1], ids=["positive", "negative"])
@pytest.mark.parametrize("where", sorted(_placed(0)))
def test_an_annotation_integer_past_the_digit_limit_is_refused_when_annotated(
    sign, where
):
    from tests import digit_limit

    past = sign * _integer(digit_limit.past())
    graph = spanweave.build(FIXTURE)
    expected = (
        f"must be JSON-serializable so they survive serialization; .* is not "
        f"\\(an integer of {DIGIT_LIMIT + 1} digits is longer than the "
        f"{DIGIT_LIMIT} digits spanweave reads"
    )
    with pytest.raises(ValueError, match=expected):
        graph.annotate("s2", "my_evals", "k", _placed(past)[where])
    with pytest.raises(ValueError, match=expected):
        graph.annotate_many([("s2", "my_evals", "k", _placed(past)[where])])


@pytest.mark.parametrize("sign", [1, -1], ids=["positive", "negative"])
def test_an_annotation_integer_at_the_digit_limit_round_trips(tmp_path, capsys, sign):
    from spanweave.cli import main
    from tests import digit_limit

    inside = sign * _integer(digit_limit.inside())
    value = _placed(inside)
    graph = spanweave.build(FIXTURE).annotate("s2", "my_evals", "k", value)
    written = dumps(graph)
    reread = jsoncodec.loads(written)
    assert validate(reread) == ()
    assert reread["annotations"][0]["value"] == value
    path = tmp_path / "graph.json"
    path.write_bytes(written)
    assert main(["validate", str(path)]) == 0, capsys.readouterr().err


#: Annotates the integers either side of the limit and writes what survives.
_ANNOTATE_BOTH_SIDES = (
    "import decimal, sys, spanweave\n"
    "from spanweave import jsoncodec\n"
    "from tests import digit_limit\n"
    "graph = spanweave.build(sys.argv[1])\n"
    "past = int(decimal.Decimal(digit_limit.past()))\n"
    "inside = int(decimal.Decimal(digit_limit.inside()))\n"
    "try:\n"
    "    graph.annotate('s2', 'my_evals', 'k', {'n': [past]})\n"
    "except ValueError:\n"
    "    pass\n"
    "else:\n"
    "    raise SystemExit('accepted an integer the reader refuses')\n"
    "written = spanweave.dumps(graph.annotate('s2', 'my_evals', 'k', [inside]))\n"
    "assert jsoncodec.loads(written)['annotations'][0]['value'] == [inside]\n"
    "sys.stdout.buffer.write(written)\n"
)


def test_the_annotation_digit_rule_is_the_same_under_every_setting():
    # The refusal counts digits rather than asking the interpreter, so a
    # lowered or disabled `PYTHONINTMAXSTRDIGITS` moves neither side of it.
    import os
    import subprocess
    import sys

    written = set()
    for setting in (None, "0", "640"):
        environment = dict(os.environ)
        environment.pop("PYTHONINTMAXSTRDIGITS", None)
        if setting is not None:
            environment["PYTHONINTMAXSTRDIGITS"] = setting
        finished = subprocess.run(
            [sys.executable, "-c", _ANNOTATE_BOTH_SIDES, str(FIXTURE)],
            capture_output=True,
            env=environment,
            cwd=pathlib.Path(__file__).resolve().parent.parent,
            check=False,
        )
        assert finished.returncode == 0, (setting, finished.stderr.decode()[-2000:])
        written.add(finished.stdout)
    assert len(written) == 1


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


def test_a_value_too_deep_to_encode_is_a_refusal_not_a_traceback():
    # `json.dumps` answers nesting it will not descend with RecursionError,
    # exactly as `json.loads` does, and this is the one encoder every byte
    # this library writes goes through. Uncontained it took down a build that
    # had already read its input without complaint -- a graph the library
    # holds and cannot write is a structural impossibility (`SPEC.md` §3.10),
    # so it is named rather than raised as an interpreter's traceback.
    with pytest.raises(spanweave.SpanweaveError) as failure:
        canonical_bytes({"deep": nested_dicts(100_000)})
    assert failure.value.code == "graph_not_serializable"


def test_the_refusal_is_the_librarys_own_error_type():
    # A consumer routes on the library's error, per `SPEC.md` §3.10, and a
    # bare RecursionError is not routable: it is indistinguishable from a bug
    # in the consumer's own recursion.
    with pytest.raises(spanweave.GraphNotSerializableError):
        canonical_bytes(nested_dicts(100_000))


def test_the_two_json_depth_ceilings_are_measured_and_neither_is_this_librarys(
    record_property,
):
    """Record where the parser and the encoder give out. Assert containment.

    This test deliberately asserts **no direction**. Which of `json.loads` and
    `json.dumps` gives out first is a property of the interpreter *and of the
    container shape*, and this library controls neither: on CPython 3.11-3.13
    the two coincide, while on 3.14.6 the encoder gives out ~2,900 levels
    earlier for **dicts** and ~34,000 levels later for **lists**
    (`SPEC.md` §7 carries the table). Three consecutive attempts to state this
    quantity as a fact -- A6, the run-2 review, R6 -- each measured one
    interpreter and wrote a universal, and R6's pin was green on 3.14 only
    because it nested lists where a graph document nests dicts (run-3 review
    F1). So both shapes are measured, both are recorded, and the assertions
    are confined to what is the library's own: that one level past whatever
    ceiling this interpreter has, the failure is the library's named refusal
    and not a bare `RecursionError`, and that where a readable-but-unwritable
    band exists it is that same refusal rather than a traceback.
    """
    observed = {}
    for shape, text, build in (
        ("dicts", dicts_text, nested_dicts),
        ("lists", lists_text, nested_lists),
    ):
        parser = deepest_accepted(lambda depth, fn=text: json.loads(fn(depth)))
        encoder = deepest_accepted(lambda depth, fn=build: canonical_bytes(fn(depth)))
        observed[shape] = (parser, encoder)
        record_property(
            f"json_depth_{shape}",
            f"parser={parser} encoder={encoder} ratio={encoder / parser:.3f}",
        )

    # The shape a graph document has at every level, and so the only row of
    # the two that says anything about this library's own output.
    parser, encoder = observed["dicts"]

    # Up to the measured ceiling the encoder writes, which is what makes the
    # bisection above a measurement rather than a coincidence.
    assert canonical_bytes(nested_dicts(encoder)).endswith(b"\n"), (
        f"the bisection says the encoder writes {encoder} levels and it does "
        f"not (parser {parser}, shapes {observed})"
    )
    # Past it, the refusal is the library's and is named. This is the whole of
    # what the library controls here, and it is red if the `RecursionError`
    # arm of `canonical_bytes` is ever dropped -- on every interpreter, under
    # either direction, because the ceiling it steps past is measured and not
    # assumed.
    with pytest.raises(spanweave.GraphNotSerializableError):
        canonical_bytes(nested_dicts(encoder + MEASUREMENT_NOISE))

    # The band that the parser reads and the encoder cannot write: empty
    # wherever the two coincide, thousands of levels wide on CPython 3.14.
    # Exercised where it exists, recorded as empty where it does not -- the
    # test never asserts which of the two it got.
    band = parser - encoder
    record_property("readable_but_unwritable_dict_levels", band)
    if band > 2 * MEASUREMENT_NOISE:
        with pytest.raises(spanweave.GraphNotSerializableError):
            canonical_bytes(json.loads(dicts_text((encoder + parser) // 2)))


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


# --------------------------------------------------------------------------
# One exception type, two facts (run-3 review F4, batch R16)
# --------------------------------------------------------------------------
#
# `json.dumps` answers a non-finite number and a value that refers back to
# itself with the same `ValueError`. The refusal names which of the two it
# found, because a caller sent looking for a number that is not there is a
# caller the message misled (`SPEC.md` §7, *Outputs*).


def _self_referential():
    source = {"attributes": {}}
    source["attributes"]["itself"] = source
    return {"raw": {"source": source}}


def test_a_circular_reference_is_refused_as_a_circular_reference():
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        canonical_bytes(_self_referential())
    message = str(failure.value)
    assert failure.value.code == "graph_not_serializable"
    assert "refers back to itself" in message
    assert "number" not in message, message


def test_the_non_finite_refusal_still_names_the_number():
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        canonical_bytes({"raw": {"source": {"start_time": float("nan")}}})
    assert "number JSON has no way to write" in str(failure.value)


def test_a_value_that_is_both_is_reported_as_the_number_it_holds():
    # Both facts are true of this value; the message names the one a caller
    # can find by looking, and says nothing false about the other.
    value = _self_referential()
    value["raw"]["source"]["start_time"] = float("inf")
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        canonical_bytes(value)
    assert "number JSON has no way to write" in str(failure.value)


def test_a_mapping_keyed_by_a_non_finite_number_is_reported_as_the_number():
    # The walk looks at keys too. A mapping keyed by `nan` defeats the encoder
    # the same way a value does, and reporting it as a cycle would be the
    # original defect with the two facts swapped.
    with pytest.raises(spanweave.GraphNotSerializableError) as failure:
        canonical_bytes({"raw": {float("nan"): "keyed by a number"}})
    assert "number JSON has no way to write" in str(failure.value)
