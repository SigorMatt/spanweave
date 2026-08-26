"""The conformance corpus (TASKS.md 1.9) -- the executable spec.

Every rendering in `fixtures/conformance/` is built and compared against the
**one** canonical graph its scenario declares — *every* rendering, not the
first one, which is what makes this the cross-dialect claim rather than a
round-trip of a single dialect (`TASKS.md` 2.7).

A rendering whose dialect has no registered adapter cannot be built. It is
**skipped with a reason**, never quietly dropped, and the header line from
`conftest.py` names it on every run. That state is transitional — 2.8 renders
a dialect, 2.9 adapts it — and the tripwire below is what stops it becoming
permanent.

If a scenario fails, the fix is upstream. Editing an expected graph to match
new code is how a corpus dies (`FIXTURES.md` §4, §8).
"""

import json

import pytest

import spanweave
from spanweave.errors import ERROR_CODES, SpanweaveError
from spanweave.serialize import canonical_bytes, dumps, to_document, validate
from tests import determinism
from tests.conformance import (
    CORPUS,
    DIALECTS,
    DIALECTS_PENDING_CORPUS_COVERAGE,
    Rendering,
    adapter_backed,
    canonical,
    renderings,
    scenarios,
    unsupported,
)

SCENARIOS = scenarios()
BUILDABLE = [s for s in SCENARIOS if s.dialects and s.expected_error is None]
FAILING = [s for s in SCENARIOS if s.expected_error is not None]
PENDING = [s for s in SCENARIOS if not s.dialects]

# The unit of the equivalence claim: one dialect file of one scenario. Both
# lists carry EVERY rendering present, including ones no adapter can read --
# those become visible skips inside `built()`, which is the point (§4.3).
BUILDABLE_RENDERINGS = renderings(BUILDABLE)
FAILING_RENDERINGS = renderings(FAILING)

# The seed corpus, from FIXTURES.md §3. Listed here as well so that a scenario
# quietly disappearing from the corpus fails a test rather than nothing.
STRUCTURAL = (
    "single_tool_call",
    "llm_tool_llm",
    "parallel_tools",
    "parallel_tool_calls",
    "nested_agents",
    "retriever_and_embedding",
    "span_links",
    "declared_data_edge",
)
DEGENERATE = (
    "missing_payloads",
    "empty_payload",
    "redacted_payload",
    "unpaired_tool_call",
    "orphan_parent",
    "clock_skew",
    "unknown_kind",
    "malformed_payload_json",
    "duplicate_span_ids",
    "cyclic_parents",
    "shuffled_order",
    "tool_call_history_echo",
)


def ids(collection):
    return [scenario.name for scenario in collection]


def labels(collection):
    return [rendering.label for rendering in collection]


def built(rendering):
    """Build one rendering, or skip loudly if nothing can read its dialect.

    The skip is inside the test rather than a filter on the parametrization on
    purpose: a filtered-out rendering leaves no trace in the run, and "we chose
    not to check this" must not look like "there was nothing to check".
    """
    if not rendering.supported:
        pytest.skip(rendering.skip_reason)
    return spanweave.build(rendering.path)


# --------------------------------------------------------------------------
# The corpus itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", STRUCTURAL + DEGENERATE)
def test_every_seeded_scenario_exists(name):
    assert (CORPUS / name / "scenario.md").exists()


def test_the_corpus_holds_nothing_undeclared():
    # A scenario nobody described is a scenario nobody can review.
    assert sorted(s.name for s in SCENARIOS) == sorted(STRUCTURAL + DEGENERATE)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
def test_every_scenario_describes_itself(scenario):
    text = (scenario.path / "scenario.md").read_text(encoding="utf-8")
    assert text.startswith(f"# {scenario.name}")
    # Described semantics-free (FIXTURES.md §2): a scenario is a shape, not a
    # story about an attacker or a leak.
    for forbidden in ("attacker", "malicious", "exfiltrat", "victim"):
        assert forbidden not in text.lower()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_dialect_is_either_rendered_or_declared_unrenderable(scenario, dialect):
    """Silence is a failure (`FIXTURES.md` §4.3).

    Without this, "we could not express this in that dialect" and "somebody
    forgot" look identical, and a dialect's coverage could rot away one file
    at a time with nothing noticing.
    """
    rendered = scenario.rendering(dialect) is not None
    reason = scenario.declared_unrenderable(dialect)
    assert rendered != (reason is not None), (
        f"{scenario.name} must either render {dialect} or declare in "
        f"expected/coverage.json that it cannot, with a reason"
    )
    if reason is not None:
        # A declaration without a reason is just a missing file with extra
        # steps. The reason is what a reviewer checks.
        assert len(reason) > 20


def test_no_scenario_is_currently_unrenderable():
    # `declared_data_edge` was the only one, on the stated grounds that
    # OpenInference declared no producer->consumer relation. It does, in every
    # multi-turn trace (SPEC.md §4.2.1), so the scenario was rendered and its
    # coverage.json deleted -- which is the §4.3 lifecycle working.
    #
    # Kept as a tripwire: a new unrenderable scenario has to be argued for
    # rather than merely added, and the reason has to survive being checked
    # against observed output.
    assert ids(PENDING) == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
def test_a_scenario_expects_exactly_one_outcome(scenario):
    # Exactly one of graph.json or error.json -- never both, never neither
    # (`FIXTURES.md` §1). Neither would be indistinguishable from an
    # unfinished fixture; both would be a contradiction.
    has_graph = (scenario.path / "expected/graph.json").exists()
    has_error = scenario.expected_error is not None
    if not scenario.dialects:
        assert not has_graph and not has_error
        return
    assert has_graph != has_error


# --------------------------------------------------------------------------
# The transitional gap: renderings no adapter can read (TASKS.md 2.7)
# --------------------------------------------------------------------------


def test_every_declared_dialect_has_an_adapter_that_can_read_it():
    # `DIALECTS` is what drives §4.3's "silence is a failure" rule. Naming a
    # dialect there that nothing can build would make the corpus demand
    # renderings no test could ever check -- coverage on paper only.
    missing = sorted(set(DIALECTS) - adapter_backed())
    assert missing == [], f"DIALECTS names {missing}, which no adapter reads"


def test_no_adapter_reads_a_dialect_the_corpus_does_not_account_for():
    """The tripwire 2.13 finally clears.

    An adapter whose dialect is absent from `DIALECTS` is an adapter the corpus
    does not require any scenario to cover: its renderings can be added, or
    quietly not added, and nothing goes red. That is the rot this whole
    mechanism exists to prevent.

    `DIALECTS_PENDING_CORPUS_COVERAGE` is the only way to hold that state, and
    it is a *declaration*, not an exemption -- the same shape §4.3 already uses
    for a scenario a dialect cannot render, and for the same reason: a declared
    gap is reviewable, a silent one is not. Empty is the only correct
    long-term value. **Do not add an entry to get a test green** -- add one
    only when a task explicitly says the corpus is not yet covering a new
    dialect, and delete it in the task that covers it.
    """
    assert adapter_backed() == set(DIALECTS) | set(DIALECTS_PENDING_CORPUS_COVERAGE)


def test_the_pending_list_holds_nothing_stale():
    # A dialect listed as pending that no adapter provides is a leftover, and
    # a leftover here silently widens the exemption above.
    assert set(DIALECTS_PENDING_CORPUS_COVERAGE) <= adapter_backed()
    assert not (set(DIALECTS_PENDING_CORPUS_COVERAGE) & set(DIALECTS))


def test_the_suite_reports_every_rendering_it_skipped_and_why():
    # The skip has to be *visible*, not merely correct: `conftest.py` puts it
    # in the pytest header on every run, and each skipped rendering is a
    # reported skip rather than an absent test.
    from tests import conftest

    header = "\n".join(conftest.pytest_report_header(None))
    skipped = unsupported(SCENARIOS)
    if not skipped:
        assert "skipping nothing" in header
        return
    for rendering in skipped:
        assert rendering.dialect in header
        assert rendering.scenario.name in header


def _planted(scenario, dialect, tmp_path, text=None):
    """A rendering that does not live in the corpus, for the two proofs below.

    Written to tmp rather than into `fixtures/`, because a fixture planted to
    prove a test has teeth is a fixture someone later mistakes for a real one.
    """
    source = scenario.rendering("openinference")
    path = tmp_path / f"{dialect}.jsonl"
    path.write_text(
        text if text is not None else source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return Rendering(scenario=scenario, dialect=dialect, path=path)


def test_a_second_rendering_that_disagrees_with_the_canonical_graph_fails(tmp_path):
    # Teeth. Without this the parametrization could be comparing nothing: with
    # one dialect per scenario today, "every rendering agrees" is vacuously
    # true, and would stay green if the comparison were broken.
    scenario = next(s for s in BUILDABLE if s.name == "llm_tool_llm")
    disagreeing = _planted(
        scenario,
        "openinference",
        tmp_path,
        text=scenario.rendering("openinference")
        .read_text(encoding="utf-8")
        .replace("Look up the order status.", "Look up something else."),
    )
    document = to_document(built(disagreeing))
    assert canonical(document, scenario.erase) != scenario.expected_graph


def test_a_rendering_for_an_adapterless_dialect_is_skipped_not_passed(tmp_path):
    # The failure mode this guards is not a wrong answer but a confident
    # silence: a rendering nothing can read must not slide through green.
    scenario = next(s for s in BUILDABLE if s.name == "llm_tool_llm")
    unreadable = _planted(scenario, "not_a_registered_dialect", tmp_path)
    assert not unreadable.supported
    assert "no registered adapter" in unreadable.skip_reason
    with pytest.raises(pytest.skip.Exception) as skipped:
        built(unreadable)
    assert "not_a_registered_dialect" in str(skipped.value)


# --------------------------------------------------------------------------
# The central assertion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_the_rendering_produces_its_scenario_s_canonical_graph(rendering):
    # THE claim. Every dialect of a scenario, against that scenario's one
    # unmodified expectation. If this fails for a second dialect, the adapter
    # is wrong or the model is -- it is never the expectation that moves.
    document = to_document(built(rendering))
    assert canonical(document, rendering.scenario.erase) == (
        rendering.scenario.expected_graph
    )


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_the_rendering_produces_exactly_its_expected_diagnostics(rendering):
    document = to_document(built(rendering))
    assert canonical(document, rendering.scenario.erase)["diagnostics"] == (
        rendering.scenario.expected_diagnostics
    )


@pytest.mark.parametrize(
    "rendering", FAILING_RENDERINGS, ids=labels(FAILING_RENDERINGS)
)
def test_the_rendering_refuses_to_build(rendering):
    # §4.2's equivalence half: every dialect of a refusal scenario must refuse
    # the SAME way. A dialect that builds a graph where another refuses is a
    # finding about the model, not a fixture to relax.
    expectation = rendering.scenario.expected_error
    with pytest.raises(SpanweaveError) as failure:
        built(rendering)
    # Type AND code, never message text (`FIXTURES.md` §4.2). A fixture that
    # pinned a phrase would start pressuring the message to stay as written.
    assert type(failure.value).__name__ == expectation["error"]
    assert failure.value.code == expectation["code"]


@pytest.mark.parametrize(
    "rendering", FAILING_RENDERINGS, ids=labels(FAILING_RENDERINGS)
)
def test_a_refusal_still_says_something_useful_to_a_human(rendering):
    # The corpus does not pin the wording, so something else has to insist
    # there IS wording. Otherwise "matched by code" quietly licenses an empty
    # message.
    with pytest.raises(SpanweaveError) as failure:
        built(rendering)
    assert len(str(failure.value)) > 40


def test_every_expected_error_code_is_one_the_library_actually_raises():
    for scenario in FAILING:
        assert scenario.expected_error["code"] in ERROR_CODES


# --------------------------------------------------------------------------
# Properties every scenario must hold, not just the one it was written for
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_builds_a_valid_graph(rendering):
    assert validate(to_document(built(rendering))) == ()


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_is_byte_identical_on_a_rebuild(rendering):
    graph = built(rendering)
    determinism.assert_repeatable(lambda: dumps(graph))


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_accounts_for_every_record(rendering):
    graph = built(rendering)
    records = [
        json.loads(line)
        for line in rendering.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    determinism.assert_every_record_accounted_for(records, to_document(graph))


# --------------------------------------------------------------------------
# The two scenarios whose point lives outside the canonical graph
# --------------------------------------------------------------------------


def test_a_shuffled_trace_is_byte_identical_to_its_ordered_twin():
    # Not merely equal: identical bytes. This is the single most valuable
    # determinism check in the corpus (SPEC.md §5.2).
    shuffled = CORPUS / "shuffled_order"
    twin = CORPUS / "llm_tool_llm"
    erase = ("name",)
    one = canonical_bytes(
        canonical(
            to_document(spanweave.build(shuffled / "dialects/openinference.jsonl")),
            erase,
        )
    )
    other = canonical_bytes(
        canonical(
            to_document(spanweave.build(twin / "dialects/openinference.jsonl")), erase
        )
    )
    assert one == other


def test_a_shuffled_trace_really_is_a_reordering_of_its_twin():
    # Otherwise the test above proves nothing.
    def lines(name):
        path = CORPUS / name / "dialects/openinference.jsonl"
        return sorted(path.read_text(encoding="utf-8").splitlines())

    assert lines("shuffled_order") == lines("llm_tool_llm")
    assert (CORPUS / "shuffled_order/dialects/openinference.jsonl").read_text(
        encoding="utf-8"
    ) != (CORPUS / "llm_tool_llm/dialects/openinference.jsonl").read_text(
        encoding="utf-8"
    )


def test_an_unparseable_payload_keeps_its_text_verbatim():
    # canonical() erases Payload.raw, because a payload's *encoding* is
    # dialect-specific -- so the scenario's central claim is checked here,
    # against the serialized graph rather than the canonical one.
    document = to_document(
        spanweave.build(CORPUS / "malformed_payload_json/dialects/openinference.jsonl")
    )
    outputs = document["nodes"][0]["outputs"]
    assert outputs["state"] == "present"
    assert outputs["value"] is None
    assert outputs["raw"] == '{"status": "shipp'


def test_a_redacted_payload_keeps_the_marker_the_source_wrote():
    document = to_document(
        spanweave.build(CORPUS / "redacted_payload/dialects/openinference.jsonl")
    )
    assert document["nodes"][0]["inputs"]["raw"] == "__REDACTED__"
