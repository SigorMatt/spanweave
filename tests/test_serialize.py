"""Serialization and validation (TASKS.md 1.8)."""

import json
import pathlib

import pytest

import spanweave
from spanweave.serialize import ROOT_KEYS, dumps, to_document, validate

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
