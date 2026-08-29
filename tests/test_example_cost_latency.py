"""The Phase 3 cost & latency attributor, run over the committed corpus.

`TASKS.md` 3.4 asks for a consumer that reads `usage` and timestamps, rolls
them up the `parent` tree, and answers `PREDICTIONS.md` P1's retention question
with a **measurement** rather than an impression.

Like `tests/test_example_fleet_aggregate.py` and
`tests/test_example_trajectory_dump.py` this is deliberately **not** a golden
snapshot of the attributor's own output: every number it checks is recomputed
from `fixtures/conformance/*/expected/`, from the raw records, or from the
model's own types. A snapshot would agree with whatever the attributor happened
to print.

The load-input tests write only to `tmp_path`. Nothing here generates a file
under `fixtures/`, and `test_the_load_generator_refuses_to_write_where_fixtures_live`
is the executable form of that rule.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import subprocess
import sys

import pytest

from examples import cost_latency
from examples.cost_latency import load as load_module
from spanweave import Graph, Node, Payload, PayloadState, build, to_document
from tests.conformance import DECLARABLE_PAYLOAD_FIELDS, canonical, scenarios

REPO = pathlib.Path(__file__).resolve().parent.parent
CORPUS = REPO / "fixtures" / "conformance"
CAPTURED = REPO / "fixtures" / "captured"


def _document(graph: Graph) -> dict:
    return json.loads(json.dumps(to_document(graph), sort_keys=True))


def _run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "examples.cost_latency", *args],
        cwd=REPO,
        capture_output=True,
        check=False,
    )


def _two_dialect_scenarios():
    return [s for s in scenarios() if len(s.dialects) > 1 and s.expected_graph]


def _buildable_scenarios():
    return [s for s in scenarios() if s.expected_graph]


def _every_committed_trace() -> list[str]:
    return [
        str(path)
        for path in sorted(CORPUS.glob("*/dialects/*.jsonl"))
        + sorted(CAPTURED.glob("*.jsonl"))
    ]


# -- the attribution is the graph's own numbers ----------------------------


@pytest.mark.parametrize("scenario", _buildable_scenarios(), ids=lambda s: s.name)
def test_every_step_carries_the_usage_and_timestamps_the_expected_graph_pins(scenario):
    """Checked against `expected/graph.json`, never against a snapshot."""
    for path in scenario.dialects:
        expected = scenario.expected_graph_for(path.stem)
        attribution = cost_latency.attribute(str(path))
        assert [step.node_id for step in attribution.steps] == [
            node["id"] for node in expected["nodes"]
        ], f"{scenario.name}[{path.stem}] step order"
        for step, node in zip(attribution.steps, expected["nodes"], strict=True):
            usage = node.get("usage")
            if usage is None:
                assert step.pricing == cost_latency.UNREPORTED
                assert (step.self_input, step.self_output) == (0, 0)
            else:
                assert step.self_input == (usage.get("input_tokens") or 0)
                assert step.self_output == (usage.get("output_tokens") or 0)
                assert step.self_total_reported == usage.get("total_tokens")
                assert step.self_extra == usage.get("extra", {})
            started, ended = node.get("started_at"), node.get("ended_at")
            if started is None or ended is None:
                assert step.self_seconds is None
            else:
                assert step.self_seconds == pytest.approx(ended - started)


@pytest.mark.parametrize("scenario", _two_dialect_scenarios(), ids=lambda s: s.name)
def test_the_two_dialects_attribute_alike(scenario):
    """The cross-dialect claim, for this consumer.

    Stronger than it looks, and deliberately so: `usage` and the timestamps are
    fields **no scenario may declare dialect-varying** — `canonical()` accepts
    declarations only for `name`, one `attributes` key, and a payload's
    `value`/`mime` (`FIXTURES.md` §4.4). So unlike the trajectory dumper's
    equivalence check, this one needs no exemption list at all: if the two
    dialects disagree about a single token or a single timestamp, this fails,
    and there is nowhere in the corpus to declare the disagreement away.
    """
    assert "usage" not in DECLARABLE_PAYLOAD_FIELDS  # the guard, stated
    forms = {}
    for path in scenario.dialects:
        form = cost_latency.attribute(str(path)).as_dict()
        form.pop("source")
        form.pop("dialect_local")
        forms[path.stem] = form
    first, *rest = list(forms)
    for other in rest:
        assert forms[first] == forms[other], f"{scenario.name}: {first} vs {other}"


def test_the_sweep_reads_every_committed_trace_and_names_what_it_refuses():
    traces = _every_committed_trace()
    results = list(cost_latency.attribute_all(traces))
    assert len(results) == len(traces)
    refused = [r for r in results if isinstance(r, cost_latency.Refused)]
    # The refusals are the corpus doing its job, not a gap in the consumer.
    assert {pathlib.Path(r.source).parent.parent.name for r in refused} == {
        "duplicate_span_ids"
    }
    assert {r.code for r in refused} == {"duplicate_node_id"}
    assert len(traces) == 41, "the corpus changed size; re-read what this bounds"


# -- tokens add; seconds do not --------------------------------------------


def test_subtree_tokens_are_the_sum_of_the_subtree_and_each_node_counted_once():
    attribution = cost_latency.attribute(
        str(CORPUS / "llm_tool_llm/dialects/openinference.jsonl")
    )
    root = next(s for s in attribution.steps if s.node_id in attribution.roots)
    assert root.subtree_nodes == len(attribution.steps)
    assert root.subtree_input == sum(s.self_input for s in attribution.steps)
    assert root.subtree_output == sum(s.self_output for s in attribution.steps)
    assert root.subtree_input == 103 and root.subtree_output == 29  # non-vacuous


def test_a_node_own_seconds_are_never_added_to_its_descendants():
    """The containment trap: children run *inside* their parent.

    `llm_tool_llm` nests three 0.8s spans inside a 4.0s agent. Adding the
    agent's own interval to theirs would report 6.4s of latency for a run that
    took 4.0s, so the consumer reports the descendants' union and what the
    parent's own interval does not account for.
    """
    attribution = cost_latency.attribute(
        str(CORPUS / "llm_tool_llm/dialects/openinference.jsonl")
    )
    root = next(s for s in attribution.steps if s.node_id in attribution.roots)
    assert root.self_seconds == pytest.approx(4.0)
    assert root.descendants_seconds_sum == pytest.approx(2.4)
    assert root.descendants_seconds_union == pytest.approx(2.4)
    assert root.unattributed_seconds == pytest.approx(1.6)


def test_concurrent_siblings_are_unioned_and_the_limit_says_so():
    """`parallel_tools`: three overlapping tools under one agent."""
    attribution = cost_latency.attribute(
        str(CORPUS / "parallel_tools/dialects/openinference.jsonl")
    )
    root = next(s for s in attribution.steps if s.node_id in attribution.roots)
    assert root.descendants_seconds_sum == pytest.approx(4.6)
    assert root.descendants_seconds_union == pytest.approx(2.3)
    assert root.descendants_seconds_sum > root.descendants_seconds_union
    assert cost_latency.OVERLAPPING in attribution.limits


def test_a_descendant_outside_its_parent_gives_a_negative_figure_unclamped():
    attribution = cost_latency.attribute(
        str(CORPUS / "cyclic_parents/dialects/openinference.jsonl")
    )
    negative = [
        s
        for s in attribution.steps
        if s.unattributed_seconds is not None and s.unattributed_seconds < 0
    ]
    assert negative, "expected an unclamped negative; the fixture has one"
    assert cost_latency.OUTSIDE_PARENT in attribution.limits


def test_a_missing_timestamp_is_unknown_rather_than_zero():
    attribution = cost_latency.attribute(
        str(CORPUS / "clock_skew/dialects/openinference.jsonl")
    )
    assert any(s.self_seconds is None for s in attribution.steps)
    assert any(
        s.self_seconds is not None and s.self_seconds < 0 for s in attribution.steps
    )
    assert cost_latency.NO_TIMESTAMPS in attribution.limits
    assert cost_latency.BACKWARDS in attribution.limits


# -- the tree the roll-up assumes, checked rather than assumed -------------


def test_a_parent_cycle_is_detected_structurally_and_without_a_diagnostic():
    """The consumer reads no diagnostics; it derives this from the edges.

    `cyclic_parents` also carries `ordering_cycle`, which this consumer never
    looks at. Asserted here so the independence is a fact rather than a claim:
    the same finding is reached from `graph.descendants` alone.
    """
    path = str(CORPUS / "cyclic_parents/dialects/openinference.jsonl")
    graph = build(path)
    assert any(d.code == "ordering_cycle" for d in graph.diagnostics)

    attribution = cost_latency.attribute(path)
    assert attribution.roots == ()
    assert cost_latency.NO_ROOT in attribution.limits
    assert all(step.in_cycle for step in attribution.steps)
    assert cost_latency.IN_CYCLE in attribution.limits


def test_every_other_committed_trace_has_a_root_and_no_cycle():
    """A non-vacuity floor: the check above must not be reporting everywhere."""
    for source in _every_committed_trace():
        if "cyclic_parents" in source or "duplicate_span_ids" in source:
            continue
        attribution = cost_latency.attribute(source)
        assert attribution.roots, source
        assert not any(step.in_cycle for step in attribution.steps), source


# -- what the library refuses to compute, and what this consumer does ------


def test_a_reported_total_is_carried_as_reported_and_never_replaced():
    """`SPEC.md` §3.4: the library never adds the other two. Nor does the field.

    The captured OpenInference trace is the only committed trace that reports a
    `total_tokens` at all, which is itself part of the bound this task records.
    """
    attribution = cost_latency.attribute(str(CAPTURED / "openai_tool_call.jsonl"))
    reported = [s for s in attribution.steps if s.self_total_reported is not None]
    assert [s.self_total_reported for s in reported] == [175, 225]
    for step in reported:
        assert step.self_total_reported == step.self_total_derived
    assert cost_latency.DERIVED_TOTALS not in attribution.limits

    # And the matched trace of the same conversation reports none at all.
    other = cost_latency.attribute(str(CAPTURED / "genai_tool_call.jsonl"))
    assert all(s.self_total_reported is None for s in other.steps)
    assert cost_latency.DERIVED_TOTALS in other.limits


def test_an_unrated_model_is_counted_unpriced_rather_than_charged_at_a_default():
    graph = build(str(CORPUS / "llm_tool_llm/dialects/openinference.jsonl"))
    renamed = Graph.of(
        trace_id=graph.trace_id,
        nodes=tuple(
            dataclasses.replace(n, operation="a-model-with-no-rate")
            if n.usage is not None
            else n
            for n in graph.nodes()
        ),
        edges=graph.edges(),
        diagnostics=graph.diagnostics,
        meta=graph.meta,
    )
    attribution = cost_latency.attribute_graph("in-memory", renamed)
    priced = [s for s in attribution.steps if s.pricing == cost_latency.PRICED]
    assert not priced
    assert attribution.total_charge == 0.0
    root = next(s for s in attribution.steps if s.node_id in attribution.roots)
    assert (root.subtree_unrated_input, root.subtree_unrated_output) == (103, 29)
    assert cost_latency.UNRATED_TOKENS in attribution.limits


def test_an_llm_span_with_no_usage_is_a_hole_and_not_zero_tokens():
    with_holes = [
        result
        for result in cost_latency.attribute_all(_every_committed_trace())
        if isinstance(result, cost_latency.Attribution)
        and any(step.subtree_unreported_llm for step in result.steps)
    ]
    assert with_holes, "no committed trace has an llm span without usage"
    for attribution in with_holes:
        assert cost_latency.UNREPORTED_USAGE in attribution.limits, attribution.source
        holes = [s for s in attribution.steps if s.pricing == cost_latency.UNREPORTED]
        # A hole is not priced, and it is not charged as zero either: it is named.
        assert all(s.self_charge is None for s in holes)
        assert all(s.self_input == 0 and s.self_output == 0 for s in holes)


# -- `Usage.extra`: the finding, pinned so it cannot go quiet --------------


def test_usage_extra_is_non_empty_on_the_committed_corpus():
    """The corpus DOES exercise `Usage.extra`, on the captured OpenInference pair.

    Two committed documents said the opposite — `CONTRACTS.md` F-C (*"`extra`
    is `{}` on every node of every conformance rendering and every captured
    trace in this repository"*) and `ROADMAP.md`'s Phase 4 row 5 (*"it is `{}`
    on every node of every fixture in the repository, so the disagreement is
    unreachable"*). Both were false: `fixtures/captured/openai_tool_call.jsonl`
    carries `llm.token_count.prompt_details.cache_read` on both of its `llm`
    spans, 80 and 144. **Both were corrected at `TASKS.md` 3.8**, the docs
    truth pass, and `tests/test_doc_truth.py` now holds both sentences to what
    this test measures — so the correction cannot silently expire the way the
    original did.

    ---

    **The pattern this is the third instance of, named here once rather than a
    fourth time in a fourth task record.**

    Neither document was careless. Both stated a **corpus-wide fact** —
    a quantifier over every fixture — and then nothing recomputed it. A claim
    like that is true when written and silently expires: the corpus grew a
    captured trace, and the sentence stayed. This is the same failure mode as:

    1. `CONTRACTS.md`'s own perturbation count at `TASKS.md` 3.2 (*"nine … and
       in seven of the nine"*, both figures wrong, caught by a recount that
       something else forced, not by anyone re-reading it);
    2. the 3.3 record's *"8 of 20 collapses change the branch"*, carried across
       from an earlier undirected run of the same sweep and corrected on
       re-measurement to 14;
    3. this.

    Three tasks, three instances, and **the remedy has been the same each
    time: a test, not a correction.** A corrected sentence is a sentence that
    will expire again; a recomputed one cannot. `CONTRACTS.md`'s own follow-up
    put it as *a prose count that nobody recomputes is the same species as an
    unstated field that nobody asserts* — and a prose **quantifier** that
    nobody recomputes is the same species again, one step more general,
    because it also expires when the corpus changes rather than only when the
    code does.

    So this test asserts the exact dict, not merely non-emptiness: it goes red
    both if `extra` empties out and if a *different* trace starts carrying one,
    which is the case the two documents were written to describe and could not
    have caught.
    """
    found: dict[str, dict[str, int]] = {}
    for source in _every_committed_trace():
        result = cost_latency.attribute_all([source])
        for attribution in result:
            if isinstance(attribution, cost_latency.Refused):
                continue
            if attribution.total_extra:
                found[source] = attribution.total_extra
    assert found == {
        str(CAPTURED / "openai_tool_call.jsonl"): {"prompt_details.cache_read": 224}
    }


def test_extra_token_counts_are_reported_and_never_priced():
    """A rate keyed on `prompt_details.cache_read` would be dialect-keyed.

    The key is OpenInference's own attribute suffix carried verbatim; the GenAI
    convention spells the same concept differently, and nothing states the
    vocabulary. So the counts are carried and excluded from `charge`.
    """
    attribution = cost_latency.attribute(str(CAPTURED / "openai_tool_call.jsonl"))
    assert attribution.total_extra == {"prompt_details.cache_read": 224}
    assert cost_latency.EXTRA_UNPRICED in attribution.limits
    # The charge is exactly the input/output arithmetic and nothing else.
    expected = sum(
        cost_latency.charge(step.operation, step.self_input, step.self_output) or 0.0
        for step in attribution.steps
    )
    assert attribution.total_charge == round(expected, cost_latency.PLACES)


def test_the_captured_matched_pair_disagrees_about_usage_and_nothing_can_declare_it():
    """`fixtures/captured/`'s two renderings of one conversation differ on `usage`.

    `canonical()` compares `usage`, and `FIXTURES.md` §4.4's declaration
    mechanism reaches `name`, one `attributes` key, and a payload's
    `value`/`mime` — **not `usage`**. So a conformance scenario could not
    absorb this disagreement even if it wanted to. It is invisible to the
    corpus only because both captured traces sit outside it.
    """
    openinference = build(str(CAPTURED / "openai_tool_call.jsonl"))
    genai = build(str(CAPTURED / "genai_tool_call.jsonl"))
    usage = {
        label: [
            (n.usage.total_tokens, dict(n.usage.extra))
            for n in graph.nodes()
            if n.usage is not None
        ]
        for label, graph in (("openinference", openinference), ("otel_genai", genai))
    }
    assert usage["openinference"] == [
        (175, {"prompt_details.cache_read": 80}),
        (225, {"prompt_details.cache_read": 144}),
    ]
    assert usage["otel_genai"] == [(None, {}), (None, {})]
    # And `usage` is not something a scenario may declare away. Two things
    # together make that concrete: the corpus's whitelist of declarable payload
    # fields does not reach it, and `canonical()` keeps `usage` on every node
    # it emits — so a disagreement like the one above would fail equivalence
    # with nowhere to record that it was expected.
    assert "usage" not in DECLARABLE_PAYLOAD_FIELDS
    for graph in (openinference, genai):
        reduced = canonical(_document(graph))
        assert [node.get("usage") for node in reduced["nodes"]] == [
            node.usage
            and {
                "input_tokens": node.usage.input_tokens,
                "output_tokens": node.usage.output_tokens,
                "total_tokens": node.usage.total_tokens,
                "extra": dict(node.usage.extra),
            }
            for node in graph.nodes()
        ]


# -- P1: what this consumer needs, measured rather than argued ------------


@pytest.mark.parametrize("source", _every_committed_trace())
def test_the_attribution_is_identical_with_every_verbatim_byte_removed(source):
    """**This is P1's question in executable form.**

    Build the graph, drop payload `value`, payload `raw` and
    `RawRecord.source`, and attribute both. If the two agree byte for byte,
    then everything mandatory losslessness retains is, to this consumer,
    exactly the dead weight P1 predicts — established by comparison rather than
    by reading the source for field accesses.
    """
    try:
        graph = build(source)
    except Exception as error:  # the corpus has two deliberate refusals
        assert type(error).__name__ == "DuplicateNodeIdError", error
        return
    stripped = cost_latency.without_verbatim(graph)
    assert cost_latency.dumps(
        cost_latency.attribute_graph(source, stripped)
    ) == cost_latency.dumps(cost_latency.attribute_graph(source, graph))


def test_the_strip_removed_something_on_every_trace_it_ran_on():
    """A non-vacuity floor for the test above: a no-op strip would also pass."""
    for source in _every_committed_trace():
        try:
            graph = build(source)
        except Exception:
            continue
        stripped = cost_latency.without_verbatim(graph)
        assert cost_latency.deep_bytes(stripped) < cost_latency.deep_bytes(graph), (
            source
        )


def test_the_reads_and_never_read_lists_account_for_every_node_field():
    """The two lists are a claim about the model; keep them exhaustive."""
    fields = {f.name for f in dataclasses.fields(Node)}
    assert set(cost_latency.READS) | set(cost_latency.NEVER_READ) == fields
    assert not set(cost_latency.READS) & set(cost_latency.NEVER_READ)


def test_dropping_a_payload_leaves_no_state_that_says_it_was_dropped():
    """The model has no way to say "content was reported and then elided".

    Both routes a stripping consumer can take produce a `Payload` whose `state`
    is false by `SPEC.md` §3.3's own definitions:

    * keep the state — `present` means *"a payload was reported and carries
      content"*, and this one carries none;
    * use `Payload.absent()` — `absent` means *"the instrumentor emitted no
      payload attribute at all"*, and it did.

    This consumer takes the first and never hands the result to anything, so it
    needs no marker. Recorded because P1 names exactly this as its `WORSE`
    condition, and because the option P1 predicts would return such a graph to
    someone who did not do the stripping.
    """
    graph = build(str(CORPUS / "llm_tool_llm/dialects/openinference.jsonl"))
    stripped = cost_latency.without_verbatim(graph)
    elided = [
        node.outputs
        for node in stripped.nodes()
        if node.outputs.state is PayloadState.PRESENT
    ]
    assert elided, "expected at least one present payload to strip"
    for payload in elided:
        assert payload.value is None and payload.raw is None
        assert payload.has_content is True, (
            "a stripped `present` payload still answers True to `has_content`, "
            "which is the collapse a harness would branch on"
        )
    # And there is no state in the enum that would have said it honestly.
    assert {str(s) for s in PayloadState} == {
        "present",
        "empty",
        "absent",
        "redacted",
        "truncated",
    }
    # `absent()` is the other route, and it misstates in the other direction.
    assert Payload.absent().state is PayloadState.ABSENT


def test_a_post_build_strip_lowers_residency_and_cannot_lower_the_peak():
    """The reading that separates "would accept" from "wants".

    A consumer can already drop what it does not need through the public API,
    so a build option buys it nothing in steady state. What it cannot do is
    avoid the allocation: `build()` returns only after the verbatim bytes
    exist, so the high-water mark is already paid. `tracemalloc`'s `peak` is
    monotonic, and that is precisely the fact being asserted.
    """
    peak = cost_latency.measure_peak(str(CAPTURED / "genai_workflow.jsonl"))
    assert peak.after_strip_current < peak.after_build_current
    assert peak.after_strip_peak >= peak.after_build_peak


@pytest.mark.parametrize("source", _every_committed_trace())
def test_residency_is_measured_and_diagnostics_survive_the_strip(source):
    try:
        residency = cost_latency.measure(source)
    except Exception:
        pytest.skip("this trace is one the library refuses")
    assert residency.stripped_bytes < residency.built_bytes
    assert 0.0 < residency.retained_fraction < 1.0
    # `Diagnostic.source` holds verbatim fragments too, and **neither of P1's
    # two option names covers it**. Asserted so the record's claim is checked.
    assert residency.diagnostic_bytes >= 0
    assert residency.diagnostic_bytes == cost_latency.deep_bytes(
        cost_latency.without_verbatim(build(source)).diagnostics
    )


def test_the_summary_labels_its_hundred_thousand_span_figure_an_extrapolation():
    summary = cost_latency.summarise(
        cost_latency.measure_all([str(p) for p in sorted(CAPTURED.glob("*.jsonl"))])
    )
    assert summary["extrapolation"]["spans"] == 100_000
    assert "EXTRAPOLATION" in summary["extrapolation"]["_note"]
    assert (
        summary["extrapolation"]["stripped_megabytes"]
        < (summary["extrapolation"]["built_megabytes"])
    )


# -- the load input, which is generated and is not a fixture ---------------


def test_the_load_generator_refuses_to_write_where_fixtures_live(tmp_path):
    destination = tmp_path / "fixtures" / "captured" / "not-a-capture.jsonl"
    with pytest.raises(load_module.RefusedDestination):
        load_module.generate(destination, spans=2, payload_chars=8)
    assert not destination.exists()


def test_the_load_input_is_deterministic_and_builds(tmp_path):
    first = load_module.generate(tmp_path / "a.jsonl", spans=25, payload_chars=32)
    second = load_module.generate(tmp_path / "b.jsonl", spans=25, payload_chars=32)
    assert first.read_bytes() == second.read_bytes()
    residency = cost_latency.measure(str(first))
    assert residency.nodes == 25
    assert residency.stripped_bytes < residency.built_bytes


def test_the_saving_grows_with_payload_length_which_is_the_extrapolations_bound(
    tmp_path,
):
    """Why the corpus figure understates it: the residue is flat, the payload is not."""
    small = cost_latency.measure(
        str(load_module.generate(tmp_path / "s.jsonl", spans=40, payload_chars=32))
    )
    large = cost_latency.measure(
        str(load_module.generate(tmp_path / "l.jsonl", spans=40, payload_chars=2048))
    )
    assert large.built_bytes > small.built_bytes
    assert large.retained_fraction < small.retained_fraction
    # The stripped size is the same shape either way: it is not payload data.
    assert large.stripped_bytes == small.stripped_bytes


# -- determinism and the CLI ----------------------------------------------


def test_the_attribution_is_byte_identical_on_re_run():
    source = str(CORPUS / "llm_tool_llm/dialects/openinference.jsonl")
    assert cost_latency.dumps(cost_latency.attribute(source)) == cost_latency.dumps(
        cost_latency.attribute(source)
    )


def test_input_order_does_not_change_the_attribution(tmp_path):
    source = CORPUS / "shuffled_order/dialects/openinference.jsonl"
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    reversed_file = tmp_path / "reversed.jsonl"
    reversed_file.write_text("".join(reversed(lines)), encoding="utf-8")

    forwards = cost_latency.attribute(str(source)).as_dict()
    backwards = cost_latency.attribute(str(reversed_file)).as_dict()
    forwards.pop("source")
    backwards.pop("source")
    assert forwards == backwards


def test_the_cli_runs_over_a_committed_fixture_in_both_dialects():
    for dialect in ("openinference", "otel_genai"):
        result = _run(f"fixtures/conformance/llm_tool_llm/dialects/{dialect}.jsonl")
        assert result.returncode == 0, result.stderr
        assert b"trace t1" in result.stdout
        assert b"demo-units" in result.stdout


def test_the_cli_reports_a_refusal_instead_of_crashing():
    result = _run(
        "fixtures/conformance/duplicate_span_ids/dialects/openinference.jsonl"
    )
    assert result.returncode == 0
    assert b"not attributed" in result.stdout
    assert b"duplicate_node_id" in result.stdout


def test_the_json_form_sorts_its_keys():
    result = _run(
        "--format",
        "json",
        "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (
        result.stdout.decode() == json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


def test_the_residency_form_names_the_interpreter_it_measured_on():
    result = _run("--residency", "fixtures/captured/openai_tool_call.jsonl")
    assert result.returncode == 0, result.stderr
    assert sys.version.split()[0].encode() in result.stdout
    assert b"EXTRAPOLATION" in result.stdout


def test_the_load_form_says_the_input_is_generated(tmp_path):
    result = _run(
        "--load", "12", "--load-chars", "16", "--load-path", str(tmp_path / "l.jsonl")
    )
    assert result.returncode == 0, result.stderr
    assert b"GENERATED load input (not a fixture, not captured)" in result.stdout
