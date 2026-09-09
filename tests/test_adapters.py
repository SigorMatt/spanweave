"""The adapter protocol and the registry (TASKS.md 1.2).

Selection is where this library can fail quietly, so most of these tests are
about refusing rather than choosing.
"""

import dataclasses

import pytest

from spanweave import diagnostics as codes
from spanweave.adapters import (
    DETECTION_SAMPLE_SIZE,
    MINIMUM_CONFIDENCE,
    AdapterRegistry,
)
from spanweave.adapters.base import Adapter, NormalizedSpan
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.adapters.otel_genai import OtelGenAiAdapter
from spanweave.errors import AdapterSelectionError, UnknownAdapterError
from spanweave.model import NodeKind, RawRecord
from spanweave.read import record_digest
from spanweave.seam import CallRole, SpanLink


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
    assert "0.90" in message  # what each declared, so the reader can judge
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
    with pytest.raises(dataclasses.FrozenInstanceError):
        link.span_id = "changed"
    assert CallRole.REQUESTER != CallRole.FULFILLER


def test_a_span_link_states_no_basis_and_the_builder_names_it():
    # `basis` describes how an edge came to be, and the builder is what makes
    # edges. A link carries one only when the dialect states the link's
    # *reason*; none observed does, so the field is None and the builder
    # supplies LINK_BASIS (`TASKS.md` I1).
    assert SpanLink(span_id="s9").basis is None


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
    assert span.links == () and span.received_call_ids == () and span.unmapped == ()


# --------------------------------------------------------------------------
# How a timestamp is rendered, in every adapter at once (batch C1)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.1 fixes which *renderings* of a timestamp the library reads,
# and the rule is the library's, not a dialect's: the string, unquoted, would
# be a valid JSON number. OTLP JSON encodes 64-bit integers as decimal
# strings, so a quoted timestamp is a real exporter's output rather than a
# malformed one -- and every other spelling is refused, because tolerating
# one is a small normalization and the library performs none.
#
# The table lives here rather than in either adapter's own test file because
# the claim is that **both** adapters answer identically. Two copies of it
# could drift apart and each still pass.

REAL_ADAPTERS = (OpenInferenceAdapter(), OtelGenAiAdapter())

#: `(rendered start_time, the started_at it must produce)`. `None` means the
#: rendering is refused -- the field is not read, and §3.1's table says why.
TIMESTAMP_RENDERINGS = (
    (1700000000, 1700000000.0),
    (1700000000.5, 1700000000.5),
    (0, 0.0),
    (-1, -1.0),
    ("1700000000", 1700000000.0),  # the OTLP JSON int64 encoding
    ("1700000000.5", 1700000000.5),
    ("-1", -1.0),
    ("0", 0.0),
    ("1e9", 1e9),
    ("1E9", 1e9),
    ("1.5e-3", 1.5e-3),
    ("+1", None),  # JSON numbers carry no leading `+`
    (" 1700000000", None),  # trimming whitespace is a normalization
    ("1700000000 ", None),
    ("01", None),  # JSON forbids a leading zero
    (".5", None),
    ("1.", None),
    ("0x1", None),
    ("1_000", None),
    ("", None),
    ("NaN", None),
    ("Infinity", None),
    ("2026-09-05T10:00:00Z", None),
    (True, None),  # a boolean is not a time, and Python would read it as 1
    (None, None),
    ([1700000000], None),
)


def a_record(adapter, **fields):
    """One minimal record this adapter recognizes, with `fields` merged in."""
    marker = (
        {"openinference.span.kind": "CHAIN"}
        if adapter.id == "openinference"
        else {"gen_ai.operation.name": "chat"}
    )
    return {
        "trace_id": "t1",
        "span_id": "s0",
        "name": "op",
        "attributes": marker,
        **fields,
    }


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("rendered,expected", TIMESTAMP_RENDERINGS, ids=repr)
def test_a_timestamp_is_read_from_exactly_the_declared_renderings(
    adapter, rendered, expected
):
    span = next(iter(adapter.parse([a_record(adapter, start_time=rendered)])))
    assert span.started_at == expected


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_end_time_is_read_the_same_way_as_start_time(adapter):
    span = next(iter(adapter.parse([a_record(adapter, end_time="1700000002")])))
    assert span.ended_at == 1700000002.0


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_quoted_timestamp_is_the_same_timestamp_as_an_unquoted_one(adapter):
    quoted = next(iter(adapter.parse([a_record(adapter, start_time="1700000000")])))
    plain = next(iter(adapter.parse([a_record(adapter, start_time=1700000000)])))
    assert quoted.started_at == plain.started_at


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_timestamp_in_a_rendering_we_refuse_is_never_silently_absent(adapter):
    # Losslessness: the value stays in `raw`, and the field is named as one
    # this adapter did not normalize (`SPEC.md` §3.1, §3.7). Without this the
    # value vanished between the record and a `None`.
    span = next(
        iter(adapter.parse([a_record(adapter, start_time="2026-09-05T10:00:00Z")]))
    )
    assert span.started_at is None
    assert "<record>.start_time" in span.unmapped
    assert codes.UNMAPPED_ATTRIBUTES in [d.code for d in span.diagnostics]
    assert span.raw.source["start_time"] == "2026-09-05T10:00:00Z"


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_timestamp_the_dialect_simply_omits_is_not_an_unmapped_field(adapter):
    # Nothing was reported, so there is nothing the adapter failed to read.
    for span in adapter.parse([a_record(adapter)]):
        assert span.started_at is None and span.ended_at is None
        assert not [key for key in span.unmapped if key.startswith("<record>.")]


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_null_timestamp_is_absence_not_a_refused_rendering(adapter):
    # `"start_time": null` is how both dialects say "no start time"; it is
    # not a value in a spelling we declined to read.
    for span in adapter.parse([a_record(adapter, start_time=None)]):
        assert span.started_at is None
        assert "<record>.start_time" not in span.unmapped


# --------------------------------------------------------------------------
# The fallback source key, in every adapter at once (batch A5)
# --------------------------------------------------------------------------
#
# A dialect need not carry a span id, and when it does not the adapter has to
# supply the stable key `spanweave/ids.py` derives a node id from
# (`SPEC.md` §3.6 rule 2). The key must come from the record's **content**,
# never from its position: an index binds the id to where the record sat in
# the file, and input line order MUST NOT affect the result (`SPEC.md` §5.2).
#
# Here rather than in either adapter's own test file for the same reason the
# timestamp table is: the claim is that both adapters answer identically, and
# two copies of it could drift apart and each still pass.


def a_span_id_less_record(adapter, **fields):
    return a_record(adapter, span_id=None, **fields)


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_record_without_a_span_id_keys_on_its_content(adapter):
    record = a_span_id_less_record(adapter, name="alpha")
    span = next(iter(adapter.parse([record])))
    assert span.span_id is None
    assert span.source_key == record_digest(record)


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_record_that_is_not_an_object_keys_on_its_content_too(adapter):
    # The `unknown` branch takes its own exit before any span id is read, so
    # it needs the rule stated separately or it keeps the index quietly.
    spans = list(adapter.parse(["not a record", 7]))
    assert [s.source_key for s in spans] == [
        record_digest("not a record"),
        record_digest(7),
    ]


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_shuffling_span_id_less_records_does_not_rebind_their_keys(adapter):
    records = [
        a_span_id_less_record(adapter, name="alpha"),
        a_span_id_less_record(adapter, name="beta"),
    ]

    def keys(order):
        return {s.raw.source["name"]: s.source_key for s in adapter.parse(order)}

    assert keys(records) == keys(list(reversed(records)))


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_span_id_still_wins_over_the_record_digest(adapter):
    # Rule 2's fallback is a fallback. Where the dialect states an id, that id
    # is the key, and the node id is the id itself (`SPEC.md` §3.6 rule 1).
    span = next(iter(adapter.parse([a_record(adapter, span_id="s7")])))
    assert span.source_key == "s7"
