"""The adapter protocol and the registry (TASKS.md 1.2).

Selection is where this library can fail quietly, so most of these tests are
about refusing rather than choosing.
"""

import dataclasses

import pytest

from spanweave.adapters import (
    DETECTION_SAMPLE_SIZE,
    MINIMUM_CONFIDENCE,
    AdapterRegistry,
)
from spanweave.adapters.base import Adapter, NormalizedSpan
from spanweave.errors import AdapterSelectionError, UnknownAdapterError
from spanweave.model import NodeKind, RawRecord
from spanweave.seam import CallRole, DeclaredDataEdge, SpanLink


class StubAdapter:
    """A minimal adapter: a marker key and one span per record."""

    def __init__(self, adapter_id, marker, confidence=0.9, seen=None):
        self.id = adapter_id
        self.version = "0.1.0"
        self.marker = marker
        self.confidence = confidence
        self.seen = seen if seen is not None else []

    def detect(self, sample):
        self.seen.append(len(sample))
        if any(self.marker in record for record in sample if isinstance(record, dict)):
            return self.confidence
        return 0.0

    def parse(self, records):
        for index, record in enumerate(records, start=1):
            yield NormalizedSpan(
                source_key=str(index),
                kind=NodeKind.CHAIN,
                name=str(record.get("name", "")),
                raw=RawRecord(source=record, line_number=index),
            )


def a_registry(*adapters):
    registry = AdapterRegistry()
    for adapter in adapters:
        registry.register(adapter)
    return registry


ONE = [{"one.marker": True, "name": "a"}]
TWO = [{"two.marker": True, "name": "b"}]
NEITHER = [{"name": "c"}]


def test_a_stub_adapter_registers_and_is_selected():
    registry = a_registry(StubAdapter("one", "one.marker"))
    adapter, confidence = registry.detect(ONE)
    assert adapter.id == "one"
    assert confidence == 0.9


def test_the_selected_adapter_parses():
    registry = a_registry(StubAdapter("one", "one.marker"))
    adapter, _ = registry.detect(ONE)
    spans = list(adapter.parse(ONE))
    assert [s.name for s in spans] == ["a"]
    assert spans[0].raw.source is ONE[0]


def test_the_right_adapter_wins_among_several():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    assert registry.detect(ONE)[0].id == "one"
    assert registry.detect(TWO)[0].id == "two"


def test_registration_order_does_not_decide_anything():
    first = a_registry(StubAdapter("one", "m"), StubAdapter("two", "m"))
    second = a_registry(StubAdapter("two", "m"), StubAdapter("one", "m"))
    # Both are equally confident, so both registries must refuse -- and refuse
    # identically. A first-wins race would make these two disagree.
    for registry in (first, second):
        with pytest.raises(AdapterSelectionError) as failure:
            registry.detect([{"m": 1}])
        assert "ambiguous" in str(failure.value)


def test_registered_is_ordered_by_id_not_by_arrival():
    registry = a_registry(
        StubAdapter("zeta", "z"), StubAdapter("alpha", "a"), StubAdapter("mu", "m")
    )
    assert [a.id for a in registry.registered()] == ["alpha", "mu", "zeta"]


# --------------------------------------------------------------------------
# Refusing, actionably
# --------------------------------------------------------------------------


def test_a_tie_is_a_hard_error_that_names_the_candidates_and_the_way_out():
    registry = a_registry(StubAdapter("one", "m"), StubAdapter("two", "m"))
    with pytest.raises(AdapterSelectionError) as failure:
        registry.detect([{"m": 1}])
    message = str(failure.value)
    assert "one" in message and "two" in message
    assert "0.90" in message  # the confidences, so the reader can judge
    assert "--adapter" in message  # and the escape hatch


def test_low_confidence_is_a_hard_error_not_a_best_guess():
    registry = a_registry(StubAdapter("one", "m", confidence=0.4))
    with pytest.raises(AdapterSelectionError) as failure:
        registry.detect([{"m": 1}])
    message = str(failure.value)
    assert "confident enough" in message
    assert f"{MINIMUM_CONFIDENCE:.2f}" in message


def test_no_adapter_recognizes_the_input_at_all():
    registry = a_registry(StubAdapter("one", "one.marker"))
    with pytest.raises(AdapterSelectionError):
        registry.detect(NEITHER)


def test_an_empty_registry_says_so_rather_than_returning_nothing():
    with pytest.raises(AdapterSelectionError, match="no adapters are registered"):
        AdapterRegistry().detect(ONE)


def test_an_adapter_that_raises_during_detection_is_reported_not_swallowed():
    class Broken(StubAdapter):
        def detect(self, sample):
            raise RuntimeError("boom")

    registry = a_registry(Broken("broken", "m"), StubAdapter("one", "one.marker"))
    # Swallowing it would let the other adapter win by default: a plausible
    # graph from an unexamined choice.
    with pytest.raises(AdapterSelectionError, match="broken"):
        registry.detect(ONE)


def test_naming_an_unregistered_adapter_lists_what_is_registered():
    registry = a_registry(StubAdapter("one", "m"))
    with pytest.raises(UnknownAdapterError) as failure:
        registry.get("nope")
    assert "one" in str(failure.value)


def test_two_adapters_cannot_claim_one_id():
    registry = a_registry(StubAdapter("one", "m"))
    with pytest.raises(AdapterSelectionError, match="unique"):
        registry.register(StubAdapter("one", "other"))


def test_registering_the_same_adapter_twice_is_harmless():
    adapter = StubAdapter("one", "m")
    registry = a_registry(adapter, adapter)
    assert len(registry.registered()) == 1


# --------------------------------------------------------------------------
# Detection is bounded and pure
# --------------------------------------------------------------------------


def test_detection_sees_a_bounded_sample():
    seen = []
    registry = a_registry(StubAdapter("one", "one.marker", seen=seen))
    registry.detect([{"one.marker": True}] * 500)
    assert seen == [DETECTION_SAMPLE_SIZE]


def test_detection_does_not_consume_the_records():
    records = [{"one.marker": True, "name": "a"}]
    registry = a_registry(StubAdapter("one", "one.marker"))
    registry.detect(records)
    assert records == [{"one.marker": True, "name": "a"}]


def test_confidences_are_reported_for_every_adapter():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    assert registry.confidences(ONE) == (("one", 0.9), ("two", 0.0))


# --------------------------------------------------------------------------
# The protocol and the seam types
# --------------------------------------------------------------------------


def test_a_stub_satisfies_the_adapter_protocol():
    assert isinstance(StubAdapter("one", "m"), Adapter)


def test_the_seam_types_exist_and_are_frozen():
    link = SpanLink(span_id="s9", trace_id="t2")
    edge = DeclaredDataEdge(src="s1", dst="s2", basis="declared")
    with pytest.raises(dataclasses.FrozenInstanceError):
        link.span_id = "changed"
    assert edge.basis == "declared"
    assert CallRole.REQUESTER != CallRole.FULFILLER


def test_a_span_defaults_to_absent_payloads_and_no_pairing():
    span = NormalizedSpan(
        source_key="1",
        kind=NodeKind.TOOL,
        name="tool.lookup",
        raw=RawRecord(source={}),
    )
    assert span.inputs.state.value == "absent"
    assert span.outputs.state.value == "absent"
    # Never invented: no id in the dialect means no pairing at all.
    assert span.call_ids == ()
    assert span.call_role is None
    assert span.links == () and span.data_edges == () and span.unmapped == ()
