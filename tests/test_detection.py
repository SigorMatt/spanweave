"""Detection, for the two adapters that actually ship (`TASKS.md` 2.12).

`tests/test_adapters.py` proves the *registry*: ties are hard errors,
registration order decides nothing, an adapter that raises is reported. It
does so with stubs, which is right — the mechanism should be testable without
a dialect.

This file proves the thing stubs cannot: that the two **real** adapters, over
the **real** corpus and both captured traces, are unambiguous. That claim is
not about the registry at all. It is about whether `openinference.*` and
`gen_ai.*` are genuinely distinctive markers, and the only way to know is to
run every input the project has through both.

Auto-selection is ergonomics, not evidence (`SPEC.md` §6.1) — it yields
nothing about whether the model is general. But its failure mode is the one
this library least wants: a mis-detected input produces a **plausible but
wrong graph**, and nothing downstream can tell.
"""

import pathlib

import pytest

import spanweave
from spanweave.adapters import REGISTRY, AdapterRegistry
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.adapters.otel_genai import OtelGenAiAdapter
from spanweave.errors import ADAPTER_AMBIGUOUS, AdapterSelectionError
from spanweave.read import read_trace

REPO = pathlib.Path(__file__).resolve().parent.parent
CAPTURED = REPO / "fixtures/captured"
CORPUS = REPO / "fixtures/conformance"

SHIPPED = ("openinference", "otel_genai")


def _inputs():
    """Every trace file the project holds, with the dialect it is written in.

    Derived from the tree rather than listed, so a rendering added tomorrow is
    checked tomorrow and not whenever someone remembers this file.
    """
    found = [
        (path, path.stem)
        for path in sorted(CORPUS.glob("*/dialects/*.jsonl"))
        if path.stem in SHIPPED
    ]
    found.append((CAPTURED / "openai_tool_call.jsonl", "openinference"))
    found.append((CAPTURED / "genai_tool_call.jsonl", "otel_genai"))
    return found


INPUTS = _inputs()
IDS = [f"{p.parent.parent.name}/{p.name}" for p, _ in INPUTS]


def records(path):
    return list(read_trace(path))


def test_the_corpus_actually_holds_both_dialects():
    # Otherwise every assertion below is about one adapter and passes for the
    # wrong reason.
    covered = {dialect for _, dialect in INPUTS}
    assert covered == set(SHIPPED)
    assert len(INPUTS) > 20


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_detection_picks_the_dialect_the_file_is_written_in(path, dialect):
    chosen, confidence = REGISTRY.detect(records(path))
    assert chosen.id == dialect
    assert confidence >= 0.5


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_the_other_adapter_declines_outright(path, dialect):
    """The claim that matters, and it is stronger than "the right one wins".

    A margin would be enough for selection and not enough for confidence: two
    adapters both scoring above the floor means the markers overlap, and the
    next dialect to arrive turns that overlap into a tie. Zero from everyone
    else is the property worth having.
    """
    scored = dict(REGISTRY.confidences(records(path)))
    others = {name: score for name, score in scored.items() if name != dialect}
    assert others, "only one adapter is registered; this proves nothing"
    assert set(others.values()) == {0.0}, (
        f"{path.name} is {dialect}, but {others} also claim it"
    )


#: Scenarios the corpus says must NOT build (`FIXTURES.md` §4.2). Read from
#: the corpus rather than named here, so a refusal added later is excluded
#: automatically instead of turning this file red for the wrong reason.
REFUSING = {
    path.parent.parent.name
    for path, _ in INPUTS
    if (path.parent.parent / "expected/error.json").exists()
}


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_building_with_no_adapter_records_the_one_that_was_chosen(path, dialect):
    # `spanweave.build` with no `--adapter` is the ergonomic path, and `meta`
    # is where a consumer finds out what it got (`SPEC.md` §6.1).
    #
    # A refusal scenario is skipped here and NOT skipped above: detection is
    # what this file tests, and it succeeds on those inputs -- the refusal
    # happens afterwards, in the builder, which is `test_conformance.py`'s
    # subject. Conflating the two would let a detection regression hide behind
    # an expected error.
    if path.parent.parent.name in REFUSING:
        pytest.skip(f"{path.parent.parent.name} must not build (FIXTURES.md §4.2)")
    graph = spanweave.build(path)
    assert [a.id for a in graph.meta.adapters] == [dialect]


def test_the_refusal_scenarios_are_still_detected_correctly():
    # The half the skip above must not lose: an input that refuses to build
    # still has to be handed to the right adapter first.
    assert REFUSING, "no refusal scenario in the corpus; the skip is vacuous"
    for path, dialect in INPUTS:
        if path.parent.parent.name in REFUSING:
            assert REGISTRY.detect(records(path))[0].id == dialect


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_registration_order_decides_nothing_for_a_real_input(path, dialect):
    forwards, backwards = AdapterRegistry(), AdapterRegistry()
    for adapter in (OpenInferenceAdapter(), OtelGenAiAdapter()):
        forwards.register(adapter)
    for adapter in (OtelGenAiAdapter(), OpenInferenceAdapter()):
        backwards.register(adapter)
    sample = records(path)
    assert forwards.detect(sample)[0].id == backwards.detect(sample)[0].id == dialect
    assert forwards.confidences(sample) == backwards.confidences(sample)


def test_detection_is_idempotent_and_leaves_the_records_alone():
    # `detect()` is required to be pure (`ADAPTERS.md` §2). Purity is easy to
    # lose by accident -- a `pop`, a sort, a cached flag -- and impossible to
    # notice downstream, because the second caller simply gets a different
    # graph.
    sample = records(CAPTURED / "genai_tool_call.jsonl")
    before = repr(sample)
    assert REGISTRY.confidences(sample) == REGISTRY.confidences(sample)
    assert repr(sample) == before


def test_an_input_carrying_both_dialects_markers_is_refused():
    # The failure this module exists for. Guessing between two adapters that
    # both recognise an input produces a plausible graph from possibly the
    # wrong dialect, and nothing downstream can tell.
    mixed = [
        {
            "span_id": "s0",
            "attributes": {
                "openinference.span.kind": "LLM",
                "gen_ai.operation.name": "chat",
            },
        }
    ]
    with pytest.raises(AdapterSelectionError) as failure:
        REGISTRY.detect(mixed)
    assert failure.value.code == ADAPTER_AMBIGUOUS
    # Actionable: both names, both scores, and the way out.
    for expected in ("openinference", "otel_genai", "--adapter"):
        assert expected in str(failure.value)


def test_an_input_in_neither_dialect_is_refused_rather_than_assigned():
    plain = [{"span_id": "s0", "attributes": {"service.name": "whatever"}}]
    with pytest.raises(AdapterSelectionError) as failure:
        REGISTRY.detect(plain)
    assert failure.value.code == "adapter_unconfident"


@pytest.mark.parametrize("adapter", [OpenInferenceAdapter(), OtelGenAiAdapter()])
@pytest.mark.parametrize(
    "sample",
    [
        [],
        [None],
        ["not a record"],
        [{"attributes": None}],
        [{"attributes": {}}],
        [{"attributes": {1: "a non-string key"}}],
        [{"no attributes key at all": True}],
    ],
    ids=["empty", "null", "string", "null-attrs", "empty-attrs", "int-key", "no-attrs"],
)
def test_detect_is_total_on_input_no_instrumentor_would_produce(adapter, sample):
    """No blanket `except` in either adapter, so this has to hold by shape.

    A catch there would look defensive and be the opposite: it converts a
    broken adapter into a confident `0.0` and hands the input to whichever
    adapter is still standing. Letting an exception escape reaches
    `adapter_detect_failed`, which names the culprit. That trade is only safe
    if `detect()` genuinely cannot raise on garbage, which is what this
    asserts.
    """
    assert adapter.detect(sample) == 0.0
