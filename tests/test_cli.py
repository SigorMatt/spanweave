"""The CLI (TASKS.md 0.2 for the surface, 1.8 for the behavior)."""

import json
import pathlib

import pytest

from spanweave.cli import main

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures/conformance"
TRACE = str(FIXTURES / "llm_tool_llm/dialects/openinference.jsonl")


def test_version_exits_zero_and_names_the_schema(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    printed = capsys.readouterr().out
    assert "spanweave" in printed
    # The unfrozen schema is announced in --version itself (CLAUDE.md 7).
    assert "UNFROZEN" in printed


def test_no_command_prints_help_and_exits_zero(capsys):
    assert main([]) == 0
    assert "usage: spanweave" in capsys.readouterr().out


def test_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        main(["nope"])
    assert exit_info.value.code == 2


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def test_build_writes_a_graph_to_stdout(capsysbinary):
    assert main(["build", TRACE]) == 0
    document = json.loads(capsysbinary.readouterr().out)
    assert [node["id"] for node in document["nodes"]] == ["s0", "s1", "s2", "s3"]


def test_build_writes_a_graph_to_a_file(tmp_path, capsys):
    out = tmp_path / "graph.json"
    assert main(["build", TRACE, "-o", str(out)]) == 0
    assert json.loads(out.read_bytes())["trace_id"] == "t1"
    # The path goes to stderr, so stdout stays pipeable.
    assert str(out) in capsys.readouterr().err


def test_build_then_validate_round_trips(tmp_path, capsys):
    out = tmp_path / "graph.json"
    assert main(["build", TRACE, "-o", str(out)]) == 0
    assert main(["validate", str(out)]) == 0
    assert "valid" in capsys.readouterr().out


def test_build_is_byte_identical_between_stdout_and_a_file(tmp_path, capsysbinary):
    out = tmp_path / "graph.json"
    main(["build", TRACE, "-o", str(out)])
    main(["build", TRACE])
    assert capsysbinary.readouterr().out == out.read_bytes()


def test_no_temporal_omits_the_derived_edges(capsysbinary):
    main(["build", TRACE, "--no-temporal"])
    document = json.loads(capsysbinary.readouterr().out)
    assert {edge["warrant"] for edge in document["edges"]} == {"explicit"}


def test_naming_the_adapter_skips_detection(capsysbinary):
    main(["build", TRACE, "--adapter", "openinference"])
    document = json.loads(capsysbinary.readouterr().out)
    # No detection happened, so there is no claim to report.
    assert document["meta"]["adapters"][0]["declared_confidence"] is None


def test_naming_an_unknown_adapter_fails_with_a_message_not_a_traceback(capsys):
    assert main(["build", TRACE, "--adapter", "nope"]) == 1
    assert "no adapter with id" in capsys.readouterr().err


def test_an_input_no_adapter_recognizes_fails_actionably(tmp_path, capsys):
    trace = tmp_path / "mystery.jsonl"
    trace.write_text('{"span_id":"s0","name":"x"}\n')
    assert main(["build", str(trace)]) == 1
    message = capsys.readouterr().err
    assert "--adapter" in message  # the way out is named


def test_a_missing_file_is_a_message_not_a_traceback(capsys):
    assert main(["build", "no/such/trace.jsonl"]) == 1
    assert "no/such/trace.jsonl" in capsys.readouterr().err


# --------------------------------------------------------------------------
# inspect, validate, adapters
# --------------------------------------------------------------------------


def test_inspect_counts_nodes_edges_and_diagnostics(capsys):
    assert main(["inspect", TRACE]) == 0
    printed = capsys.readouterr().out
    assert "nodes: 4" in printed
    assert "llm: 2" in printed
    # Edges by kind AND by warrant, which is the distinction that matters.
    assert "parent (explicit): 3" in printed
    assert "temporal (derived): 2" in printed
    # info-level only: real telemetry carries keys this library does not
    # normalize, and reports them rather than dropping them.
    assert "diagnostics: 2" in printed
    assert "unmapped_attributes: 2" in printed


def test_inspect_reports_payload_availability(capsys):
    main(["inspect", TRACE])
    printed = capsys.readouterr().out
    assert "inputs  present: 4" in printed
    assert "outputs absent: 1" in printed
    assert "outputs present: 3" in printed


def test_inspect_reads_a_built_graph_as_happily_as_a_trace(tmp_path, capsys):
    out = tmp_path / "graph.json"
    main(["build", TRACE, "-o", str(out)])
    capsys.readouterr()
    main(["inspect", TRACE])
    from_trace = capsys.readouterr().out
    main(["inspect", str(out)])
    assert capsys.readouterr().out == from_trace


def test_inspect_says_the_schema_is_unfrozen(capsys):
    main(["inspect", TRACE])
    assert "NOT FROZEN" in capsys.readouterr().out


def test_validate_reports_each_problem_and_exits_nonzero(tmp_path, capsys):
    broken = tmp_path / "graph.json"
    broken.write_text(json.dumps({"schema_version": "0.1", "nodes": []}))
    assert main(["validate", str(broken)]) == 1
    assert "missing top-level key" in capsys.readouterr().err


def test_validate_on_something_that_is_not_json(tmp_path, capsys):
    broken = tmp_path / "graph.json"
    broken.write_text("{not json")
    assert main(["validate", str(broken)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_adapters_lists_what_is_registered(capsys):
    assert main(["adapters"]) == 0
    assert "openinference" in capsys.readouterr().out


# --------------------------------------------------------------------------
# The missing-file hint (`0.9.1` candidate C1)
# --------------------------------------------------------------------------
#
# Measured from the PUBLISHED 0.9.0 package, not predicted: a reader who runs
# `pip install spanweave` and pastes the README's first command gets
#
#   spanweave inspect: [Errno 2] No such file or directory: 'fixtures/...'
#
# Every word of which is true, and which reads as a broken package to exactly
# the reader who did what the front page told them to. The corpus is
# development data and is deliberately not in the wheel, so the fix is the
# message rather than the packaging.
#
# What these two tests hold: the hint fires under the documented corpus prefix
# and nowhere else, and the line that was already there does not move. The
# third test -- that the prefix still covers what the documents actually quote
# -- lives in `tests/test_doc_truth.py`, because it is a claim about documents.

CORPUS_PATH = "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl"


def first_line_for(command, path):
    """The line C1 keeps byte for byte, spelled out rather than recomputed."""
    return f"spanweave {command}: [Errno 2] No such file or directory: '{path}'"


def test_a_missing_path_under_the_documented_corpus_gets_a_secondary_hint(
    tmp_path, monkeypatch, capsys
):
    # The reader's actual situation: a package, no checkout, a relative path
    # out of the README. `OSError.filename` is where the path comes from, so
    # one change covers every subcommand that opens a path a caller named.
    monkeypatch.chdir(tmp_path)
    for command in ("build", "inspect", "validate"):
        assert main([command, CORPUS_PATH]) == 1
        printed = capsys.readouterr().err
        lines = printed.splitlines()
        assert lines[0] == first_line_for(command, CORPUS_PATH), (
            "C1 keeps the existing line byte for byte -- it is what an OSError "
            "says, and anything reading stderr keeps working"
        )
        assert lines[1].startswith("hint: "), printed
        # The sentence that keeps the hint from reading as "you installed the
        # wrong thing", which is the misreading it exists to prevent.
        assert "reads any trace file you point it at" in printed


def test_no_other_missing_path_gets_the_hint_and_the_first_line_never_moves(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    # A typo, a bare filename, and -- the one worth having -- a path that
    # merely CONTAINS the prefix. The match is on a prefix, not a substring:
    # somebody else's `fixtures/` under their own tree is not ours.
    for path in ("no/such/trace.jsonl", "trace.jsonl", "my/fixtures/trace.jsonl"):
        assert main(["inspect", path]) == 1
        printed = capsys.readouterr().err
        assert printed == first_line_for("inspect", path) + "\n", (
            f"a missing {path!r} is somebody else's problem and gets the plain "
            f"message; the hint is for a path this project's documents quote"
        )
