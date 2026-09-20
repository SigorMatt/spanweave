"""The CLI (TASKS.md 0.2 for the surface, 1.8 for the behavior)."""

import json
import pathlib

import pytest

from spanweave.cli import main
from tests import digit_limit

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures/conformance"
TRACE = str(FIXTURES / "llm_tool_llm/dialects/openinference.jsonl")
MIXED = str(FIXTURES / "mixed_instrumentation/dialects/openinference+otel_genai.jsonl")


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


def test_adapter_auto_is_the_default_spelled_out(capsysbinary):
    """`SPEC.md` §6.1: `auto` names the classification that already happens.

    The spelling exists so a caller can *say* what they are relying on -- in a
    script, in a Makefile, in a pasted command -- without the reader having to
    know that the absent flag means per-record classification. It therefore has
    to be the same build, byte for byte, and not merely a similar one.
    """
    main(["build", TRACE])
    without = capsysbinary.readouterr().out
    main(["build", TRACE, "--adapter", "auto"])
    assert capsysbinary.readouterr().out == without


def test_adapter_auto_classifies_per_record_rather_than_forcing_one_adapter(
    capsysbinary,
):
    """The spelling must not collapse to "pick one": the mixed trace proves it.

    A forced adapter over this input builds two `unknown` nodes and loses the
    relations that join the dialects (`SPEC.md` §6.1). `auto` is the path that
    does not, so it names both contributors.
    """
    main(["build", MIXED, "--adapter", "auto"])
    document = json.loads(capsysbinary.readouterr().out)
    assert [a["id"] for a in document["meta"]["adapters"]] == [
        "openinference",
        "otel_genai",
    ]
    assert [node["kind"] for node in document["nodes"]] == [
        "agent",
        "llm",
        "tool",
        "llm",
    ]


def test_auto_is_not_a_name_an_adapter_can_take():
    """The reserved word, guarded where it would otherwise be shadowed.

    `--adapter auto` is resolved by the CLI before the registry sees it, so an
    adapter registering that id would become unreachable through the flag --
    silently, and only for that one adapter (`ADAPTERS.md` §4).
    """
    from spanweave.adapters import registered

    assert "auto" not in {adapter.id for adapter in registered()}


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


def test_inspect_counts_nodes_by_the_adapter_that_produced_them(capsys):
    """`SPEC.md` §7, *Human summary*. One dialect: every node, one name."""
    main(["inspect", TRACE])
    printed = capsys.readouterr().out
    assert "nodes by adapter:" in printed
    assert "  openinference: 4" in printed


def test_inspect_says_which_adapter_produced_which_nodes_in_a_mixed_trace(capsys):
    """The count `meta.adapters` cannot give: who contributed how much.

    `adapters:` names both contributors for a mixed input and has named both
    since E3, but it says nothing about the split -- an adapter that claimed
    one record of four reads exactly like one that claimed three. That is the
    question the summary was missing, and it is a count of something the graph
    already says (`provenance.adapter_id`), never a judgement about it.
    """
    main(["inspect", MIXED])
    printed = capsys.readouterr().out
    assert "nodes by adapter:" in printed
    assert "  openinference: 2" in printed
    assert "  otel_genai: 2" in printed


def test_inspect_counts_a_node_no_adapter_produced_under_its_own_label(
    tmp_path, capsys
):
    """An unclaimed record's node is not filed under somebody else's dialect.

    `provenance.adapter_id` is `None` there on purpose (`SPEC.md` §3.5), and
    the summary has to keep saying so rather than rounding it into the adapter
    that read the rest of the input.
    """
    trace = tmp_path / "mixed_with_a_stranger.jsonl"
    records = [
        {
            "span_id": "s0",
            "name": "chat",
            "attributes": {"openinference.span.kind": "LLM"},
        },
        {"span_id": "s9", "attributes": {"service.name": "whatever"}},
    ]
    trace.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    assert main(["inspect", str(trace)]) == 0
    printed = capsys.readouterr().out
    assert "  openinference: 1" in printed
    assert "  (no adapter): 1" in printed


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


# --------------------------------------------------------------------------
# Deep nesting on the CLI's own reading paths (September 2026 audit, finding 3,
# batch A6). `build` was contained by batch A1; `inspect` and `validate` were
# not, because each opens the file with its OWN `json.loads` and each caught
# only `ValueError`. The parser answers nesting it will not descend with
# `RecursionError`, so both commands died with a traceback on a file `build`
# reads without complaint.
# --------------------------------------------------------------------------

#: A record the reader parses fine and a record nested past any interpreter's
#: recursion limit. The deep one is second so the file is still JSONL: a file
#: whose FIRST byte is '[' is the array container, which is a different path.
DEEP_VALUE = b"[" * 100_000 + b"]" * 100_000
SHALLOW_RECORD = (
    b'{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"n",'
    b'"start_time":1.0,"end_time":2.0,"status":"OK",'
    b'"attributes":{"openinference.span.kind":"AGENT"}}\n'
)
DEEP_RECORD = b'{"span_id":"s9","attributes":{"input.value":' + DEEP_VALUE + b"}}\n"


def _deep_trace(tmp_path):
    path = tmp_path / "deep.jsonl"
    path.write_bytes(DEEP_RECORD + SHALLOW_RECORD)
    return str(path)


def test_inspect_survives_a_record_nested_past_the_parsers_limit(tmp_path, capsys):
    trace = _deep_trace(tmp_path)
    # `build` already contains it, and that is the comparison that makes the
    # defect legible: the same file, two commands, one traceback.
    assert main(["build", trace, "-o", str(tmp_path / "g.json")]) == 0
    assert main(["inspect", trace]) == 0
    printed = capsys.readouterr().out
    assert "nodes: 1" in printed
    assert "malformed_record: 1" in printed


def test_validate_survives_a_file_nested_past_the_parsers_limit(tmp_path, capsys):
    path = tmp_path / "graph.json"
    path.write_bytes(DEEP_VALUE)
    assert main(["validate", str(path)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_inspect_on_a_deep_graph_file_is_a_refusal_not_a_traceback(tmp_path, capsys):
    # The sniff dies on this file's very first byte, so it is the sharpest
    # form of the defect. What it must produce is the refusal any unreadable
    # input produces -- the sniff answers "not a graph document", the reader
    # reports the record it could not read, and detection then has nothing to
    # be confident about. One line on stderr, an exit code, no traceback.
    path = tmp_path / "graph.json"
    path.write_bytes(DEEP_VALUE)
    assert main(["inspect", str(path)]) == 1
    assert capsys.readouterr().err.startswith("spanweave inspect: ")


def test_build_contains_a_payload_at_the_edge_of_the_parsers_limit(tmp_path, capsys):
    # The other half of the finding: a payload deep enough to parse but too
    # deep to write back out. `json.dumps` in `serialize.py` recurses from
    # inside the graph document, four levels below where `json.loads` started,
    # so a value that arrived intact could not leave. Whatever the interpreter's
    # limit is, the command must end in an exit code, never a traceback.
    limit = _parser_limit()
    for depth in range(limit - 8, limit + 1):
        trace = tmp_path / f"d{depth}.jsonl"
        trace.write_text(
            json.dumps(
                {
                    "trace_id": "t1",
                    "span_id": "s0",
                    "parent_id": None,
                    "name": "n",
                    "start_time": 1.0,
                    "end_time": 2.0,
                    "status": "OK",
                    "attributes": {
                        "openinference.span.kind": "TOOL",
                        "output.value": "[" * depth + "]" * depth,
                        "output.mime_type": "application/json",
                    },
                }
            )
            + "\n"
        )
        code = main(["build", str(trace), "-o", str(tmp_path / f"d{depth}.json")])
        assert code in (0, 1), depth
        if code == 1:
            assert capsys.readouterr().err.startswith("spanweave build: ")
        else:
            capsys.readouterr()


def _parser_limit():
    """The deepest array this interpreter's JSON parser will read."""
    low, high = 1, 200_000
    while low < high:
        middle = (low + high + 1) // 2
        try:
            json.loads("[" * middle + "]" * middle)
        except RecursionError:
            high = middle - 1
        else:
            low = middle
    return low


# --------------------------------------------------------------------------
# Numbers no interpreter can hold (September 2026 run-2 review, batch R1)
# --------------------------------------------------------------------------
#
# The same shape as the section above and the same rule: whatever a trace
# file says, the command ends in an exit code and a line on stderr, never a
# traceback. Three ways a JSON number defeats the interpreter -- an integer
# past its integer-string digit limit, quoted and unquoted, and a literal
# with no float64 -- each through `build` and through `inspect`.


def _span(start):
    return (
        '{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"n",'
        f'"start_time":{start},"end_time":2.0,"status":"OK",'
        '"attributes":{"openinference.span.kind":"AGENT"}}\n'
    )


def _assert_the_timestamp_is_refused_and_the_graph_writes(tmp_path, capsys, start):
    # Quoted, so the record itself is ordinary JSON: only the timestamp is in
    # a rendering §3.1 does not read, and the graph writes normally.
    trace = tmp_path / "t.jsonl"
    trace.write_text(_span(start))
    out = tmp_path / "g.json"
    assert main(["build", str(trace), "-o", str(out)]) == 0
    document = json.loads(out.read_text())
    assert document["nodes"][0]["started_at"] is None
    codes = {item["code"] for item in document["diagnostics"]}
    assert "missing_timestamp" in codes
    assert "unmapped_attributes" in codes
    assert main(["inspect", str(trace)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize(
    "start",
    ('"1e400"', '"-1e400"'),
    ids=("quoted-1e400", "quoted-minus-1e400"),
)
def test_a_number_the_interpreter_cannot_read_still_builds(tmp_path, capsys, start):
    _assert_the_timestamp_is_refused_and_the_graph_writes(tmp_path, capsys, start)


def test_a_quoted_integer_past_the_digit_limit_still_builds(tmp_path, capsys):
    # Same rule, and "past the limit" is the library's constant, derived
    # rather than written down (batches R14 and S8, `SPEC.md` §5.3).
    _assert_the_timestamp_is_refused_and_the_graph_writes(
        tmp_path, capsys, f'"{digit_limit.past()}"'
    )


@pytest.mark.parametrize(
    "start",
    ("1e400", "-1e400", "NaN", "Infinity"),
    ids=("1e400", "-1e400", "NaN", "Infinity"),
)
def test_an_unquoted_non_finite_number_is_a_refusal_not_a_traceback(
    tmp_path, capsys, start
):
    # Unquoted, the value is in the record itself, and `raw.source` is
    # verbatim -- so the graph builds and cannot be written (`SPEC.md` §7).
    # One line on stderr, exit 1, no traceback.
    trace = tmp_path / "t.jsonl"
    trace.write_text(_span(start))
    assert main(["build", str(trace), "-o", str(tmp_path / "g.json")]) == 1
    assert capsys.readouterr().err.startswith("spanweave build: ")
    # `inspect` writes no graph, so it has nothing to refuse and still works.
    assert main(["inspect", str(trace)]) == 0
    assert "nodes: 1" in capsys.readouterr().out


def test_an_unquoted_integer_past_the_digit_limit_is_a_malformed_record(
    tmp_path, capsys
):
    # This one never reaches an adapter: the reader refuses the line and
    # reports it (`SPEC.md` §5.3, §7).
    trace = tmp_path / "t.jsonl"
    trace.write_text(_span(digit_limit.past()) + _span("1.0").replace('"s0"', '"s1"'))
    assert main(["inspect", str(trace)]) == 0
    printed = capsys.readouterr().out
    assert "nodes: 1" in printed
    assert "malformed_record: 1" in printed


def _otlp_envelope(digits):
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "t1",
                                "spanId": "s0",
                                "name": "chat",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "chat"},
                                    },
                                    {"key": "k", "value": {"intValue": digits}},
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }


def test_an_otlp_int_value_past_the_digit_limit_is_not_a_traceback(tmp_path, capsys):
    digits = digit_limit.past()
    trace = tmp_path / "otlp.json"
    trace.write_text(json.dumps(_otlp_envelope(digits)))
    out = tmp_path / "g.json"
    assert main(["build", str(trace), "-o", str(out)]) == 0
    document = json.loads(out.read_text())
    assert document["nodes"][0]["raw"]["source"]["attributes"]["k"] == digits
    capsys.readouterr()


# --------------------------------------------------------------------------
# A refusal is routable from outside the process (run-3 review F4, batch R16)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.10: match on the `code`, never on the message. A caller running
# `spanweave` as a subprocess has neither the exception nor the type -- only an
# exit status and a line of text -- so the line carries the code in brackets
# (§7, *Failures*). Without it `adapter_unconfident` and
# `graph_not_serializable` are both "exit 1 and a sentence", and the only way
# to tell them apart is the English nobody promised to keep.

_UNRECOGNIZABLE = '{"hello":"world"}\n'

_NON_FINITE_SPAN = (
    '{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"n",'
    '"start_time":NaN,"end_time":2.0,"status":"OK",'
    '"attributes":{"openinference.span.kind":"AGENT"}}\n'
)


def _refusal(tmp_path, text, argv):
    trace = tmp_path / "t.jsonl"
    trace.write_text(text)
    return [str(part).replace("TRACE", str(trace)) for part in argv]


@pytest.mark.parametrize(
    ("text", "argv", "code"),
    (
        (_UNRECOGNIZABLE, ["build", "TRACE"], "adapter_unconfident"),
        (_UNRECOGNIZABLE, ["inspect", "TRACE"], "adapter_unconfident"),
        (_UNRECOGNIZABLE, ["build", "TRACE", "--adapter", "nope"], "unknown_adapter"),
        (_NON_FINITE_SPAN, ["build", "TRACE"], "graph_not_serializable"),
    ),
    ids=("unconfident-build", "unconfident-inspect", "unknown-adapter", "non-finite"),
)
def test_a_raised_refusal_names_its_code_on_stderr(tmp_path, capsys, text, argv, code):
    argv = _refusal(tmp_path, text, argv)
    assert main(argv) == 1
    printed = capsys.readouterr().err
    assert printed.startswith(f"spanweave {argv[0]}: [{code}] "), printed
    assert printed.count("\n") == 1, "a refusal is one line"


def test_the_bracket_on_a_raised_refusal_is_one_of_the_error_codes(tmp_path, capsys):
    # On a refusal the library raised, whatever the prose says, the code a
    # caller reads off the line is one of §3.10's codes. This is not the
    # general rule for every failure line: an `OSError`'s line opens with
    # the operating system's `[Errno N]` (the test below).
    from spanweave.errors import ERROR_CODES

    trace = tmp_path / "t.jsonl"
    trace.write_text(_UNRECOGNIZABLE)
    assert main(["build", str(trace)]) == 1
    printed = capsys.readouterr().err
    bracketed = printed[printed.index("[") + 1 : printed.index("]")]
    assert bracketed in ERROR_CODES


def test_a_failure_the_library_did_not_raise_carries_no_code(tmp_path, capsys):
    # An `OSError` is the operating system's answer and has no code in
    # §3.10's table. Inventing one would name a contract that does not exist,
    # so this line is byte-for-byte the line it always was.
    missing = tmp_path / "nope.jsonl"
    assert main(["build", str(missing)]) == 1
    printed = capsys.readouterr().err
    assert printed.startswith("spanweave build: [Errno 2] "), printed
    assert not printed.startswith("spanweave build: [graph")


# --------------------------------------------------------------------------
# `validate` refuses what `build` refuses to write (run-3 review F4)
# --------------------------------------------------------------------------


def _graph_with_a_bare_nan(tmp_path):
    """A graph document that is exactly what `build` wrote, plus one `NaN`.

    Placed inside `raw.source`, which is where a non-finite number reaches a
    graph at all (`SPEC.md` §7): every field the library normalizes refuses
    one, so a document carrying one carries it verbatim or not at all.
    """
    out = tmp_path / "graph.json"
    assert main(["build", TRACE, "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert '"start_time":1000.0' in text
    out.write_text(text.replace('"start_time":1000.0', '"start_time":NaN', 1))
    return out


def test_validate_refuses_a_graph_carrying_a_bare_nan(tmp_path, capsys):
    # The asymmetry this closes: `build` will not write this document, and
    # `validate` used to call it valid and exit 0 -- so the two commands
    # disagreed about one file while both claimed to be about well-formedness.
    graph = _graph_with_a_bare_nan(tmp_path)
    capsys.readouterr()
    assert main(["validate", str(graph)]) == 1
    printed = capsys.readouterr()
    assert "not valid JSON" in printed.err
    assert "NaN" in printed.err
    assert "valid" not in printed.out


@pytest.mark.parametrize("token", ("NaN", "Infinity", "-Infinity"))
def test_validate_refuses_every_token_rfc_8259_does_not_define(tmp_path, capsys, token):
    graph = _graph_with_a_bare_nan(tmp_path)
    graph.write_text(graph.read_text(encoding="utf-8").replace("NaN", token, 1))
    capsys.readouterr()
    assert main(["validate", str(graph)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_build_refuses_to_write_the_document_validate_now_refuses_to_read(
    tmp_path, capsys
):
    # The two halves are one rule, so they are asserted together: the trace
    # that produces the document above is the trace `build` refuses.
    trace = tmp_path / "t.jsonl"
    trace.write_text(_NON_FINITE_SPAN)
    assert main(["build", str(trace), "-o", str(tmp_path / "g.json")]) == 1
    assert "graph_not_serializable" in capsys.readouterr().err
