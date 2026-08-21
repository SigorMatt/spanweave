"""The conformance corpus (TASKS.md 1.9) -- the executable spec.

Every scenario in `fixtures/conformance/` is built from its dialect rendering
and compared against the **one** canonical graph that scenario declares. In
Phase 1 there is a single dialect, so what this proves is that the pipeline
produces the reviewed expectation; the cross-dialect equivalence the corpus
exists for switches on with the second adapter (Phase 2), against these same
unmodified expectations.

If a scenario fails, the fix is upstream. Editing an expected graph to match
new code is how a corpus dies (`FIXTURES.md` §4, §8).
"""

import json

import pytest

import spanweave
from spanweave.errors import SpanweaveError
from spanweave.serialize import canonical_bytes, dumps, to_document, validate
from tests import determinism
from tests.conformance import CORPUS, canonical, scenarios

SCENARIOS = scenarios()
BUILDABLE = [s for s in SCENARIOS if s.dialects and s.expected_error is None]
FAILING = [s for s in SCENARIOS if s.expected_error is not None]
PENDING = [s for s in SCENARIOS if not s.dialects]

# The seed corpus, from FIXTURES.md §3. Listed here as well so that a scenario
# quietly disappearing from the corpus fails a test rather than nothing.
STRUCTURAL = (
    "single_tool_call",
    "llm_tool_llm",
    "parallel_tools",
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
)


def ids(collection):
    return [scenario.name for scenario in collection]


def built(scenario):
    return spanweave.build(scenario.dialects[0])


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


def test_the_scenarios_with_no_rendering_are_the_ones_we_expect():
    # Not a hole: OpenInference declares no producer->consumer relation, so
    # there is nothing to transcribe and inventing an attribute would make the
    # fixture assert something about the dialect we cannot substantiate.
    assert ids(PENDING) == ["declared_data_edge"]


# --------------------------------------------------------------------------
# The central assertion
# --------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BUILDABLE, ids=ids(BUILDABLE))
def test_the_scenario_produces_its_canonical_graph(scenario):
    document = to_document(built(scenario))
    assert canonical(document, scenario.erase) == scenario.expected_graph


@pytest.mark.parametrize("scenario", BUILDABLE, ids=ids(BUILDABLE))
def test_the_scenario_produces_exactly_its_expected_diagnostics(scenario):
    document = to_document(built(scenario))
    assert canonical(document, scenario.erase)["diagnostics"] == (
        scenario.expected_diagnostics
    )


@pytest.mark.parametrize("scenario", FAILING, ids=ids(FAILING))
def test_the_scenario_refuses_to_build(scenario):
    expectation = scenario.expected_error
    with pytest.raises(SpanweaveError) as failure:
        built(scenario)
    assert type(failure.value).__name__ == expectation["error"]
    for fragment in expectation["message_contains"]:
        assert fragment in str(failure.value)


# --------------------------------------------------------------------------
# Properties every scenario must hold, not just the one it was written for
# --------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BUILDABLE, ids=ids(BUILDABLE))
def test_every_scenario_builds_a_valid_graph(scenario):
    assert validate(to_document(built(scenario))) == ()


@pytest.mark.parametrize("scenario", BUILDABLE, ids=ids(BUILDABLE))
def test_every_scenario_is_byte_identical_on_a_rebuild(scenario):
    determinism.assert_repeatable(lambda: dumps(built(scenario)))


@pytest.mark.parametrize("scenario", BUILDABLE, ids=ids(BUILDABLE))
def test_every_scenario_accounts_for_every_record(scenario):
    records = [
        json.loads(line)
        for line in scenario.dialects[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    determinism.assert_every_record_accounted_for(records, to_document(built(scenario)))


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
