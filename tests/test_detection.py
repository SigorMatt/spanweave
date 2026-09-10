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

import json
import pathlib

import pytest

import spanweave
from spanweave.adapters import REGISTRY, AdapterRegistry
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.adapters.otel_genai import OtelGenAiAdapter
from spanweave.errors import ADAPTER_AMBIGUOUS, AdapterSelectionError
from spanweave.read import read_trace
from spanweave.serialize import to_document

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
    #
    # **The corpus currently holds no refusal scenario**, so this is vacuous
    # and the skip above never fires -- said here rather than asserted away.
    # `duplicate_span_ids` was the only one, and batch A3 turned it into a
    # graph: two records claiming one span id are now both kept (`SPEC.md`
    # §3.6 rule 3). No trace file reaches `DuplicateNodeIdError` any more, so
    # there is nothing to write a refusal fixture out of -- and inventing one
    # to keep a check non-vacuous would be a fixture testing itself. The
    # mechanism stays for the next refusal that has an input (`FIXTURES.md`
    # §4.2); the moment one is added, this stops being vacuous on its own.
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


# --------------------------------------------------------------------------
# Classification is per record (batch E2)
# --------------------------------------------------------------------------

# `tests/test_adapters.py` proves the mechanism with stubs. These are the same
# three cases over the two dialects that ship, because the claim that matters
# is not "the registry can partition" but "`openinference.` and `gen_ai.` sort
# every real record into exactly one adapter".

#: One record from each dialect's rendering of the same scenario, so the mixed
#: input below is verbatim corpus material rather than something hand-written.
MIXED_SCENARIO = CORPUS / "llm_tool_llm/dialects"


def _record(dialect, index):
    lines = (MIXED_SCENARIO / f"{dialect}.jsonl").read_text().splitlines()
    return json.loads(lines[index])


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_every_record_of_a_single_dialect_file_goes_to_its_own_adapter(path, dialect):
    kept = records(path)
    partition = REGISTRY.partition(kept)
    assert partition.contributors == (dialect,)
    assert list(partition.claims[0].records) == kept
    assert partition.unclaimed == ()
    assert partition.claims[0].declared_confidence >= 0.5


@pytest.mark.parametrize(("path", "dialect"), INPUTS, ids=IDS)
def test_the_detected_path_builds_exactly_what_the_forced_path_builds(path, dialect):
    """The hard requirement of per-record classification: nothing moved.

    `--adapter <id>` skips classification entirely, so it is the same code
    path it was before E2. Byte-equality between the two documents is
    therefore the statement that classification changed nothing for a
    single-dialect input -- every id, every edge, every diagnostic, every
    count. The one field that legitimately differs is the confidence the
    adapter declared, which the forced path never asks for.
    """
    if path.parent.parent.name in REFUSING:
        pytest.skip(f"{path.parent.parent.name} must not build (FIXTURES.md §4.2)")
    detected = to_document(spanweave.build(path))
    forced = to_document(spanweave.build(path, adapter=dialect))
    assert detected["meta"]["adapters"][0]["declared_confidence"] == 0.9
    assert forced["meta"]["adapters"][0]["declared_confidence"] is None
    for document in (detected, forced):
        document["meta"]["adapters"][0]["declared_confidence"] = None
    assert json.dumps(detected, sort_keys=True) == json.dumps(forced, sort_keys=True)


def test_a_record_both_adapters_claim_is_refused_by_name():
    """The one case where a guess would be required, and the only refusal.

    Today this input is refused whole-file too, because both adapters see
    their marker in the sample and tie. What the per-record rule adds is that
    it is still refused when the sample would have hidden it -- and that the
    message says which record, rather than "this input".
    """
    both = {
        "span_id": "s0",
        "attributes": {
            "openinference.span.kind": "LLM",
            "gen_ai.operation.name": "chat",
        },
    }
    with pytest.raises(AdapterSelectionError) as failure:
        REGISTRY.partition([_record("openinference", 0), both])
    message = str(failure.value)
    assert failure.value.code == ADAPTER_AMBIGUOUS
    for expected in ("record 2", "s0", "openinference", "otel_genai", "--adapter"):
        assert expected in message


def test_a_doubly_claimed_record_is_refused_even_beyond_the_detection_sample():
    """The case whole-input detection cannot see (`OPEN_QUESTIONS.md` §12(i)).

    Fifty-one records in, the sample is long past. Before per-record
    classification this file built cleanly under one adapter and the other
    dialect's span went quietly into an `unknown` node.
    """
    first = _record("openinference", 0)
    # Distinct records: the reader collapses repeats (`SPEC.md` §7), so sixty
    # copies of one span would be one record and the sample would never be
    # exhausted. `record N` counts the records the reader yielded, which is
    # exactly what `RawRecord.line_number` counts.
    lines = [json.dumps(dict(first, span_id=f"s{n}")) for n in range(60)]
    lines.append(
        json.dumps(
            {
                "span_id": "late",
                "attributes": {
                    "openinference.span.kind": "LLM",
                    "gen_ai.operation.name": "chat",
                },
            }
        )
    )
    with pytest.raises(AdapterSelectionError) as failure:
        spanweave.build("\n".join(lines).encode())
    assert failure.value.code == ADAPTER_AMBIGUOUS
    assert "record 61" in str(failure.value)


def test_a_record_neither_adapter_claims_is_carried_as_unclaimed():
    """Never a discard (`CLAUDE.md` 2), and never handed over on a guess.

    The record still reaches a node today, because a single-dialect input is
    parsed whole by the adapter that claimed the rest of it. What the
    partition adds is that the library can now *say* nobody recognized it,
    which is the honest report of "you are missing an adapter".
    """
    stranger = {"span_id": "s9", "attributes": {"service.name": "whatever"}}
    kept = [_record("openinference", 0), stranger]
    partition = REGISTRY.partition(kept)
    assert partition.contributors == ("openinference",)
    assert partition.unclaimed == (stranger,)

    document = to_document(spanweave.build("\n".join(map(json.dumps, kept)).encode()))
    assert len(document["nodes"]) == 2
    assert document["nodes"][1]["raw"]["source"] == stranger


def test_a_marker_after_the_sample_still_decides_an_otherwise_unmarked_input():
    """Refusal is decided over the input, not over its first 50 records."""
    stranger = {"attributes": {"service.name": "whatever"}}
    lines = [json.dumps(dict(stranger, span_id=f"s{n}")) for n in range(60)]
    lines.append(json.dumps(_record("openinference", 0)))
    graph = spanweave.build("\n".join(lines).encode())
    assert [a.id for a in graph.meta.adapters] == ["openinference"]


def test_a_trace_in_two_dialects_is_partitioned_and_still_refused_for_now():
    """Where E leaves the library after E2, stated so the next step moves it.

    The records sort themselves cleanly -- two adapters, disjoint claims, no
    record either could argue over -- and the builder does not yet accept
    spans from more than one adapter, so the input is refused exactly as it
    was before classification existed. The refusal is whole-input and its
    message says so.
    """
    mixed = [
        _record("openinference", 0),
        _record("otel_genai", 1),
        _record("openinference", 2),
        _record("otel_genai", 3),
    ]
    partition = REGISTRY.partition(mixed)
    assert partition.contributors == ("openinference", "otel_genai")
    assert partition.unclaimed == ()
    assert [len(claim.records) for claim in partition.claims] == [2, 2]

    with pytest.raises(AdapterSelectionError) as failure:
        spanweave.build("\n".join(map(json.dumps, mixed)).encode())
    assert failure.value.code == ADAPTER_AMBIGUOUS
    assert "this input is ambiguous" in str(failure.value)


def test_an_input_no_adapter_claims_at_all_is_still_refused_the_same_way():
    plain = json.dumps({"span_id": "s0", "attributes": {"service.name": "x"}})
    with pytest.raises(AdapterSelectionError) as failure:
        spanweave.build(plain.encode())
    assert failure.value.code == "adapter_unconfident"
