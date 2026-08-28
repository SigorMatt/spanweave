"""The Phase 3 confirmatory consumer, run over the committed corpus.

`TASKS.md` 3.3 asks for a transcript that is ordered, portable across
dialects, and byte-identical on re-run. Like `tests/test_example_fleet_aggregate.py`
this is deliberately **not** a golden snapshot of the dumper's own output:
every step it checks is recomputed from `fixtures/conformance/*/expected/`,
which owes nothing to the code under test. A snapshot would agree with
whatever the dumper happened to print.

The cross-dialect check reuses the corpus's own §4.4 declarations
(`tests/conformance.py`) rather than a list written here, for `FIXTURES.md`'s
reason: a comparison that carries its own exemption list is a comparison that
can be widened to make a failure go away.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from examples import trajectory_dump
from spanweave import PayloadState
from tests.conformance import scenarios

REPO = pathlib.Path(__file__).resolve().parent.parent
CORPUS = REPO / "fixtures" / "conformance"
CAPTURED = REPO / "fixtures" / "captured"


def _run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "examples.trajectory_dump", *args],
        cwd=REPO,
        capture_output=True,
        check=False,
    )


def _two_dialect_scenarios():
    return [s for s in scenarios() if len(s.dialects) > 1 and s.expected_graph]


def _buildable_scenarios():
    """Every scenario the library builds, one dialect or two.

    The first test runs over all of them rather than only the pairs: the four
    single-dialect scenarios are the only ones whose `expected/graph.json`
    still carries `name`, so they are where the `name` assertion below is not
    vacuous.
    """
    return [s for s in scenarios() if s.expected_graph]


def _every_committed_trace() -> list[str]:
    return [
        str(path)
        for path in sorted(CORPUS.glob("*/dialects/*.jsonl"))
        + sorted(CAPTURED.glob("*.jsonl"))
    ]


# -- the transcript is the graph, in the graph's order ----------------------


@pytest.mark.parametrize("scenario", _buildable_scenarios(), ids=lambda s: s.name)
def test_the_transcript_is_the_expected_nodes_in_the_expected_order(scenario):
    """Every step, checked against `expected/graph.json` rather than a snapshot."""
    for path in scenario.dialects:
        expected = scenario.expected_graph_for(path.stem)
        transcript = trajectory_dump.transcribe(str(path))
        assert [step.node_id for step in transcript.steps] == [
            node["id"] for node in expected["nodes"]
        ], f"{scenario.name}[{path.stem}] step order"
        for step, node in zip(transcript.steps, expected["nodes"], strict=True):
            assert step.kind == node["kind"]
            assert step.operation == node.get("operation")
            assert step.status == node.get("status", "unset")
            # `name` is NOT checked against `expected/graph.json`, and cannot
            # be: 16 of the 17 two-dialect scenarios declare it dialect-varying,
            # so the pinned graph is in canonical form and does not carry the
            # field at all (`FIXTURES.md` §4, `CONTRACTS.md` F-B). That is the
            # bound this consumer works around by never keying on it.
            assert "name" not in node or step.name == node["name"]
            assert [line.state for line in step.lines] == [
                node["inputs"]["state"],
                node["outputs"]["state"],
            ], f"{scenario.name}[{path.stem}] {node['id']} payload states"


# -- the cross-dialect claim, one layer up ---------------------------------


def _comparable(transcript, scenario) -> dict:
    """A transcript with exactly what the corpus declares dialect-varying gone.

    `dialect_local` is dropped wholesale -- the consumer put `adapter` and
    `name` there itself, which is the claim being tested. Payload `content`
    and `mime` are dropped only where the scenario's `expected/comparison.json`
    declares them (§4.4), and `state` is never droppable, here as there.
    """
    drop = scenario.drop_payloads
    document = transcript.as_dict()
    document.pop("source")
    document.pop("dialect_local")
    for step in document["steps"]:
        step.pop("dialect_local")
        for line in step["lines"]:
            side = "inputs" if line["side"] == "in" else "outputs"
            declared = drop.get(f"{step['node_id']}.{side}", frozenset())
            if "value" in declared:
                line.pop("content")
            if "mime" in declared:
                line.pop("mime")
    return document


@pytest.mark.parametrize("scenario", _two_dialect_scenarios(), ids=lambda s: s.name)
def test_the_two_dialects_transcribe_alike_where_the_graphs_agree(scenario):
    forms = {
        path.stem: _comparable(trajectory_dump.transcribe(str(path)), scenario)
        for path in scenario.dialects
    }
    first, *rest = sorted(forms)
    for other in rest:
        assert forms[first] == forms[other], (
            f"{scenario.name}: {first} and {other} transcribe differently "
            f"outside what expected/comparison.json declares"
        )


def test_the_text_transcripts_of_two_dialects_differ_only_where_declared():
    """The *printed* form too, not only the machine one.

    `unpaired_tool_call` is the case blocker 2 names: the tool of a call that
    never ran must be reachable in one line, identically in both dialects.
    """
    scenario = next(s for s in scenarios() if s.name == "unpaired_tool_call")
    printed = {path.stem: _run(str(path)).stdout.decode() for path in scenario.dialects}
    for text in printed.values():
        assert "! asked for lookup — nothing ran" in text
        assert "! no call in this trace asked for this" in text
    differing = {
        line
        for line in printed["openinference"].splitlines()
        if line not in set(printed["otel_genai"].splitlines())
    }
    assert all(
        "dialect-local" in line
        or ".jsonl" in line
        or "in  present" in line
        or "out present" in line
        for line in differing
    ), differing


# -- the O1 remedy, which this consumer is the test of ---------------------


def test_the_tool_of_an_unfulfilled_call_is_read_off_the_diagnostic():
    """No payload is walked to name it (`TASKS.md` 3.3, blocker 2).

    Asserted against a bare `Diagnostic` with no graph behind it: if naming
    the tool needed `outputs.value[...]`, this could not pass at all.
    """
    from spanweave import Diagnostic

    diagnostic = Diagnostic(
        code="unpaired_call",
        message="…",
        node_id="s1",
        source={"call_id": "call_a", "operation": "lookup"},
    )
    assert trajectory_dump._asked_for(diagnostic) == "lookup"


def test_a_bare_string_source_degrades_to_unnamed_rather_than_crashing():
    from spanweave import Diagnostic

    older = Diagnostic(code="unpaired_call", message="…", source="call_a")
    assert trajectory_dump._asked_for(older) is None


# -- P2: the payload-state table -------------------------------------------


def test_every_payload_state_has_a_rendering_and_every_rendering_a_state():
    """Both directions, so a new state cannot be added without a decision here."""
    assert set(trajectory_dump.STATE_RENDERINGS) == set(PayloadState)


def test_the_table_is_reached_rather_than_has_content():
    """`Payload.has_content` is the collapse P2 predicts; this must not be it."""
    from spanweave import Payload

    absent = Payload.absent()
    empty = Payload(state=PayloadState.EMPTY, value="")
    assert absent.has_content == empty.has_content
    assert trajectory_dump.render(absent) != trajectory_dump.render(empty)


def test_a_present_payload_that_did_not_parse_is_not_printed_as_content():
    """`SPEC.md` §3.3: state stays `present`, `value` is None, `raw` survives."""
    from spanweave import Payload

    unreadable = Payload(
        state=PayloadState.PRESENT, mime="application/json", value=None, raw="{oops"
    )
    rendering = trajectory_dump.render(unreadable)
    assert rendering.availability == trajectory_dump.UNAVAILABLE
    assert rendering is trajectory_dump.UNREADABLE


#: What the committed corpus actually contains, measured over every trace in
#: the repo. **This is the bound on what 3.3's P2 evidence proves**, so it is
#: pinned rather than described: a fixture that changes it changes the claim,
#: and the change should be deliberate. `truncated` is zero because neither
#: adapter can emit it -- OpenInference has no truncation signal
#: (`spanweave/adapters/openinference.py`) and the GenAI convention states
#: none either.
CORPUS_STATES = {
    "absent": 114,
    "empty": 4,
    "present": 94,
    "redacted": 2,
    "truncated": 0,
}


def test_the_corpus_exercises_four_of_the_five_states():
    results = list(trajectory_dump.transcribe_all(_every_committed_trace()))
    measured = trajectory_dump.coverage(results)
    assert measured["states_seen"] == CORPUS_STATES
    assert measured["states_never_seen"] == ["truncated"]


def test_the_sweep_reads_every_committed_trace_and_names_what_it_refuses():
    """A refused trace is a result, not an exit -- and it is named."""
    traces = _every_committed_trace()
    results = list(trajectory_dump.transcribe_all(traces))
    measured = trajectory_dump.coverage(results)
    assert len(measured["sources_read"]) + len(measured["sources_refused"]) == len(
        traces
    )
    refused = {entry["source"] for entry in measured["sources_refused"]}
    assert refused == {
        str(path) for path in sorted(CORPUS.glob("duplicate_span_ids/dialects/*.jsonl"))
    }
    for entry in measured["sources_refused"]:
        assert entry["code"] == "duplicate_node_id"


def test_the_distinctions_record_is_computed_from_the_table():
    rows = {tuple(row["states"]): row for row in trajectory_dump.distinctions()}
    assert rows[("absent", "empty")]["kind"] == "verdict"
    # The one pair this consumer does NOT separate on the branch a harness
    # reads. Recorded, not hidden: it is evidence in P2's direction.
    assert rows[("absent", "redacted")]["kind"] == "wording"
    assert len(rows) == 10


# -- portability and determinism -------------------------------------------


def test_no_step_is_labelled_by_a_dialect_local_field():
    for path in sorted(CORPUS.glob("*/dialects/openinference.jsonl")):
        if path.parent.parent.name == "duplicate_span_ids":
            continue
        for step in trajectory_dump.transcribe(str(path)).steps:
            assert step.name not in step.label or step.name == step.operation


def test_the_transcript_is_byte_identical_on_re_run():
    traces = _every_committed_trace()
    first = _run("--format", "json", *traces)
    second = _run("--format", "json", *traces)
    assert first.returncode == 0, first.stderr.decode()
    assert first.stdout == second.stdout


def test_input_order_does_not_change_the_transcript(tmp_path):
    """The library's shuffled-input claim, seen from a consumer."""
    source = CORPUS / "llm_tool_llm" / "dialects" / "openinference.jsonl"
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    shuffled = tmp_path / "shuffled.jsonl"
    shuffled.write_text("".join(reversed(lines)), encoding="utf-8")
    straight = trajectory_dump.transcribe(str(source)).as_dict()
    reversed_ = trajectory_dump.transcribe(str(shuffled)).as_dict()
    straight.pop("source")
    reversed_.pop("source")
    assert straight == reversed_


def test_the_cli_runs_over_a_committed_fixture_in_both_dialects():
    for dialect in ("openinference", "otel_genai"):
        done = _run(str(CORPUS / "llm_tool_llm" / "dialects" / f"{dialect}.jsonl"))
        assert done.returncode == 0, done.stderr.decode()
        assert b"trace t1" in done.stdout


def test_the_json_form_sorts_its_keys():
    trace = CORPUS / "single_tool_call" / "dialects" / "openinference.jsonl"
    done = _run("--format", "json", str(trace))
    loaded = json.loads(done.stdout)
    assert loaded[0]["trace_id"] == "t1"
    assert done.stdout.decode() == json.dumps(loaded, indent=2, sort_keys=True) + "\n"


# -- what building it found the transcript was under-reporting --------------


def test_a_graph_scoped_diagnostic_qualifies_the_whole_transcript():
    """`ordering_cycle` carries no `node_id`, and a transcript IS an ordering.

    Nothing on a `Diagnostic` says whether it is node-scoped or graph-scoped;
    `node_id is None` is where this consumer learns it, which is `TASKS.md`
    2.4's F7 met again by a second consumer.
    """
    transcript = trajectory_dump.transcribe(
        str(CORPUS / "cyclic_parents" / "dialects" / "openinference.jsonl")
    )
    assert transcript.qualifiers == ("ordering_cycle",)
    assert trajectory_dump.UNTRUSTED_ORDER in transcript.limits
    assert all(step.notes == () for step in transcript.steps)


def test_ordering_diagnostics_on_a_step_also_qualify_the_order():
    transcript = trajectory_dump.transcribe(
        str(CORPUS / "clock_skew" / "dialects" / "openinference.jsonl")
    )
    assert transcript.qualifiers == ()
    notes = {note for step in transcript.steps for note in step.notes}
    assert notes == {"nonmonotonic_time", "missing_timestamp"}
    assert trajectory_dump.UNTRUSTED_ORDER in transcript.limits
    assert trajectory_dump.BACKWARDS in transcript.limits


def test_a_negative_duration_is_reported_and_not_clamped():
    transcript = trajectory_dump.transcribe(
        str(CORPUS / "clock_skew" / "dialects" / "openinference.jsonl")
    )
    assert [step.duration for step in transcript.steps] == [5.0, -0.5, None]


def test_reported_kind_is_carried_and_is_dialect_local():
    """§3.2's escape hatch, and §4.5's reason it cannot go in the body."""
    seen = {}
    for dialect in ("openinference", "otel_genai"):
        transcript = trajectory_dump.transcribe(
            str(CORPUS / "unknown_kind" / "dialects" / f"{dialect}.jsonl")
        )
        unknown = [s for s in transcript.steps if s.kind == "unknown"]
        assert len(unknown) == 1
        seen[dialect] = unknown[0].reported_kind
    assert seen["openinference"] != seen["otel_genai"]
    assert all(value is not None for value in seen.values())


def test_the_transcript_compares_diagnostics_per_node_and_they_still_agree():
    """A claim the corpus does not make, and it holds anyway.

    `canonical()` compares diagnostics by code and global count (`FIXTURES.md`
    §4). The equivalence test above compares this consumer's `notes`, which are
    the same codes *scoped to a node*. That is strictly stronger, and it is
    recorded here so the strength is not mistaken for an accident of the
    comparison.
    """
    checked = 0
    for scenario in _two_dialect_scenarios():
        per_dialect = {}
        for path in scenario.dialects:
            transcript = trajectory_dump.transcribe(str(path))
            per_dialect[path.stem] = {
                step.node_id: step.notes for step in transcript.steps
            }
        first, *rest = sorted(per_dialect)
        for other in rest:
            assert per_dialect[first] == per_dialect[other], scenario.name
        if any(notes for notes in per_dialect[first].values()):
            checked += 1
    # Not a vacuous pass: several scenarios really do carry per-node codes.
    assert checked >= 5


def test_declared_data_edges_are_read_and_none_are_inferred():
    """`PREDICTIONS.md` P3 evidence, from the consumer side.

    The transcript shows `data` edges the telemetry **declared** (`SPEC.md`
    §4.2) and never compares two payload values to decide one flowed into the
    other. Every `feeds` entry below is an explicit edge; the count is taken
    from `expected/graph.json`, not from the consumer.
    """
    scenario = next(s for s in scenarios() if s.name == "llm_tool_llm")
    declared = [
        (edge["src"], edge["dst"])
        for edge in scenario.expected_graph["edges"]
        if edge["kind"] == "data"
    ]
    assert declared, "fixture no longer carries a declared data edge"
    for path in scenario.dialects:
        transcript = trajectory_dump.transcribe(str(path))
        shown = [
            (step.node_id, target) for step in transcript.steps for target in step.feeds
        ]
        assert shown == declared, path
    for edge in scenario.expected_graph["edges"]:
        if edge["kind"] == "data":
            assert edge["warrant"] == "explicit"


def test_a_link_to_a_span_outside_the_trace_is_named_not_dropped():
    """`SPEC.md` §4.0: a dangling `link` target is normal, and `Graph.node`
    returns None for it. Dropping the id would hide a stated relation."""
    transcript = trajectory_dump.transcribe(
        str(CORPUS / "span_links" / "dialects" / "openinference.jsonl")
    )
    outside = [t for step in transcript.steps for t in step.links_outside]
    inside = [
        t
        for step in transcript.steps
        for t in step.links_to
        if t not in step.links_outside
    ]
    assert outside == ["s9"]
    assert inside == ["s1"]


# -- the P2 perturbation measurement, pinned ------------------------------


def _collapse_sweep():
    """Re-render state `a` as state `b`, one directed pair at a time.

    3.2's instrument: a distinction that is *used* is one whose removal
    changes the output. `branch` is what a harness acts on (`availability`,
    `complete`); `anything` includes the printed `reason`.
    """
    traces = _every_committed_trace()

    def observe(branch_only):
        seen = []
        for result in trajectory_dump.transcribe_all(traces):
            if not isinstance(result, trajectory_dump.Transcript):
                continue
            for step in result.steps:
                for line in step.lines:
                    seen.append(
                        (line.availability, line.complete)
                        if branch_only
                        else (line.availability, line.complete, line.reason)
                    )
        return seen

    original = dict(trajectory_dump.STATE_RENDERINGS)
    base_branch, base_all = observe(True), observe(False)
    rows = {}
    try:
        for first in sorted(PayloadState):
            for second in sorted(PayloadState):
                if first is second:
                    continue
                trajectory_dump.STATE_RENDERINGS = {**original, first: original[second]}
                rows[(str(first), str(second))] = (
                    observe(False) != base_all,
                    observe(True) != base_branch,
                )
                trajectory_dump.STATE_RENDERINGS = original
    finally:
        trajectory_dump.STATE_RENDERINGS = original
    return rows


#: The measurement `TASKS.md` 3.3 reports. Pinned because the first version of
#: that record carried a **wrong** count (it said 8 of 20, off an earlier
#: undirected run) and nothing recomputed it — the same species as an unstated
#: field nothing asserts, which is what 3.2 exists to find.
COLLAPSES = {"total": 20, "anything": 16, "branch": 14, "wording_only": 2, "none": 4}


def test_the_perturbation_counts_in_the_3_3_record_still_hold():
    rows = _collapse_sweep()
    counts = {
        "total": len(rows),
        "anything": sum(1 for anything, _ in rows.values() if anything),
        "branch": sum(1 for _, branch in rows.values() if branch),
        "wording_only": sum(
            1 for anything, branch in rows.values() if anything and not branch
        ),
        "none": sum(1 for anything, _ in rows.values() if not anything),
    }
    assert counts == COLLAPSES


def test_the_two_named_collapses_are_the_ones_the_record_names():
    rows = _collapse_sweep()
    # The one pair this consumer does not separate on the branch.
    assert rows[("absent", "redacted")] == (True, False)
    assert rows[("redacted", "absent")] == (True, False)
    # `truncated` in either direction changes nothing: no committed trace
    # contains one, so the distinction never had the opportunity to be used.
    for other in ("absent", "empty", "present", "redacted"):
        assert rows[("truncated", other)] == (False, False), other
