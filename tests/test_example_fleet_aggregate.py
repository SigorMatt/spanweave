"""The Phase 2b adversarial consumer, run over the committed corpus.

`TASKS.md` 2.3 asks for a test so the example cannot rot. This is that test,
and it is deliberately **not** a golden snapshot of the aggregator's own
output: every number it checks is recomputed here from
`fixtures/conformance/*/expected/`, which is the corpus's own pinned
expectation and owes nothing to the code under test. A snapshot would agree
with whatever the aggregator happened to print; this disagrees when the
aggregator is wrong.
"""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CORPUS = REPO / "fixtures" / "conformance"
DIALECT = "openinference"


def _scenarios() -> list[pathlib.Path]:
    return sorted(
        d for d in CORPUS.iterdir() if (d / "dialects" / f"{DIALECT}.jsonl").is_file()
    )


def _traces() -> list[str]:
    return [str(d / "dialects" / f"{DIALECT}.jsonl") for d in _scenarios()]


def _run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "examples.fleet_aggregate", *args],
        cwd=REPO,
        capture_output=True,
        check=False,
    )


def _rollup() -> dict:
    done = _run("--format", "json", *_traces())
    assert done.returncode == 0, done.stderr.decode()
    return json.loads(done.stdout)


# -- the independent oracle ------------------------------------------------


def _expected() -> dict:
    kinds: collections.Counter[str] = collections.Counter()
    codes: collections.Counter[str] = collections.Counter()
    tool_calls: collections.Counter[str] = collections.Counter()
    tool_status: collections.Counter[tuple[str, str]] = collections.Counter()
    models: collections.Counter[str] = collections.Counter()
    built = 0
    unbuildable: list[str] = []

    for scenario in _scenarios():
        graph_file = scenario / "expected" / "graph.json"
        error_file = scenario / "expected" / "error.json"
        if not graph_file.is_file():
            assert error_file.is_file(), f"{scenario.name} pins neither outcome"
            unbuildable.append(json.loads(error_file.read_text())["code"])
            continue
        built += 1
        graph = json.loads(graph_file.read_text())
        for node in graph["nodes"]:
            kinds[node["kind"]] += 1
            operation = node.get("operation")
            if node["kind"] == "tool" and operation is not None:
                tool_calls[operation] += 1
                tool_status[(operation, node.get("status", "unset"))] += 1
            if node["kind"] == "llm" and operation is not None:
                models[operation] += 1
        for entry in graph.get("diagnostics", []):
            codes[entry["code"]] += entry["count"]

    return {
        "built": built,
        "unbuildable": sorted(unbuildable),
        "node_kinds": dict(kinds),
        "diagnostics": dict(codes),
        "tools": {
            name: {
                "calls": count,
                "errors": tool_status[(name, "error")],
                "ok": tool_status[(name, "ok")],
                "unset": tool_status[(name, "unset")],
            }
            for name, count in tool_calls.items()
        },
        "models": dict(models),
    }


# -- the checks ------------------------------------------------------------


def test_counts_match_the_corpus_expectations() -> None:
    """Every rollup number is the corpus's own, recomputed independently."""
    got = _rollup()
    want = _expected()

    assert got["traces"]["given"] == len(_traces())
    assert got["traces"]["built"] == want["built"]
    assert got["traces"]["unbuildable"] == len(want["unbuildable"])
    assert sorted(f["code"] for f in got["unbuildable"]) == want["unbuildable"]

    # Zero-valued kinds are carried so the schema is stable across fleets.
    assert {k: v for k, v in got["node_kinds"].items() if v} == want["node_kinds"]
    assert got["diagnostics"] == want["diagnostics"]
    assert got["tools"] == want["tools"]
    assert got["models"] == want["models"]


def test_an_unbuildable_trace_is_reported_not_fatal() -> None:
    """One bad trace in a fleet must not cost you the other 10,000."""
    got = _rollup()
    assert got["traces"]["unbuildable"] == 1
    failure = got["unbuildable"][0]
    assert failure["code"] == "duplicate_node_id"
    assert failure["source"].endswith("duplicate_span_ids/dialects/openinference.jsonl")
    # ...and the rest of the fleet still rolled up.
    assert got["traces"]["built"] == len(_traces()) - 1


def test_trace_id_does_not_identify_a_trace_in_this_corpus() -> None:
    """Pins a finding, not a preference (`TASKS.md` 2.4).

    All 19 buildable scenarios declare `trace_id: "t1"`, so a fleet keyed on
    `Graph.trace_id` collapses the whole corpus into one trace. The aggregator
    therefore keys on the input it was handed, and reports the collision
    instead of hiding it.
    """
    got = _rollup()
    assert got["traces"]["distinct_trace_ids"] == 1
    assert got["traces"]["built"] > 1


def test_the_boundary_the_task_exists_to_find_is_in_the_output() -> None:
    """`TASKS.md` 2.3: the friction is the deliverable, so it ships visibly.

    An unfulfilled call can be attributed to the model that asked for it --
    the diagnostic names that node, and `Node.operation` names the model. It
    cannot be attributed to the tool it asked for, because a call that never
    ran has no node. Both halves are asserted: a change that made `by_tool`
    answerable should fail this test and be read at 2.4, not pass silently.
    """
    got = _rollup()
    unfulfilled = got["unfulfilled_calls"]
    assert unfulfilled["total"] == got["diagnostics"]["unpaired_call"] > 0
    assert sum(unfulfilled["by_model"].values()) == unfulfilled["total"]
    assert unfulfilled["by_tool"] == {}
    assert any("by_tool" in limit for limit in got["limits"])


def test_rerun_is_byte_identical() -> None:
    first = _run("--format", "json", *_traces())
    second = _run("--format", "json", *_traces())
    assert first.stdout == second.stdout
    assert first.returncode == second.returncode == 0


def test_text_report_is_deterministic_and_nonempty() -> None:
    first = _run(*_traces())
    second = _run(*_traces())
    assert first.returncode == 0, first.stderr.decode()
    assert first.stdout == second.stdout
    assert b"node kinds" in first.stdout


def test_no_arguments_is_an_error_not_a_traceback() -> None:
    done = _run()
    assert done.returncode != 0
    assert b"Traceback" not in done.stderr
