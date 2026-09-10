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
from spanweave.build import build_graph
from spanweave.errors import (
    ADAPTER_AMBIGUOUS,
    ADAPTER_DETECT_FAILED,
    NO_ADAPTERS_REGISTERED,
    AdapterSelectionError,
    UnknownAdapterError,
)
from spanweave.model import (
    AdapterInfo,
    EdgeKind,
    NodeKind,
    RawRecord,
)
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
#: The Python **type** of each expectation is part of the table (batch C3): an
#: integer literal is read as `int`, a fractional or exponent one as `float`,
#: so each pair below is written with the type it must produce.
TIMESTAMP_RENDERINGS = (
    (1700000000, 1700000000),
    (1700000000.5, 1700000000.5),
    (0, 0),
    (-1, -1),
    ("1700000000", 1700000000),  # the OTLP JSON int64 encoding
    ("1700000000.5", 1700000000.5),
    ("-1", -1),
    ("0", 0),
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
    # Finite, or not read (batch R1). Each of these parses -- as a number,
    # even -- and none of them is a time (`SPEC.md` §3.1).
    ("1e400", None),  # a JSON number literal with no float64: it is `inf`
    # The digit-limit rendering is not in this table because its `repr` is its
    # 5000 digits and that becomes the test's id; it has its own test below.
    (float("inf"), None),  # what an unquoted `Infinity` or `1e400` parses to
    (float("-inf"), None),
    (float("nan"), None),  # what an unquoted `NaN` parses to
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
    # The type is part of the answer rather than an implementation detail:
    # `1 == 1.0` in Python, so equality alone cannot see a digit that float64
    # cannot hold (`SPEC.md` §3.1, batch C3).
    assert type(span.started_at) is type(expected)


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_end_time_is_read_the_same_way_as_start_time(adapter):
    span = next(iter(adapter.parse([a_record(adapter, end_time="1700000002")])))
    assert span.ended_at == 1700000002
    assert type(span.ended_at) is int


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
@pytest.mark.parametrize(
    "rendered",
    ("1e400", "9" * 5000, float("inf"), float("nan")),
    ids=("quoted-1e400", "quoted-5000-digits", "inf", "nan"),
)
def test_a_non_finite_timestamp_is_refused_the_way_any_other_rendering_is(
    adapter, rendered
):
    # Batch R1. Both of these used to leave by a door of their own: the digit
    # limit as an interpreter `ValueError` raised straight out of `parse`, and
    # `inf` as a value that reached the output as a bare `Infinity` token.
    # They are refused renderings like any other -- `None`, verbatim in `raw`,
    # and named in `unmapped_attributes` (`SPEC.md` §3.1).
    span = next(iter(adapter.parse([a_record(adapter, start_time=rendered)])))
    assert span.started_at is None
    assert "<record>.start_time" in span.unmapped
    assert codes.UNMAPPED_ATTRIBUTES in [d.code for d in span.diagnostics]
    source = span.raw.source
    assert isinstance(source, dict)
    reported = source["start_time"]
    assert reported is rendered or reported == rendered


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_timestamp_just_inside_the_digit_limit_is_still_read(adapter):
    # The line is the interpreter's, and the test states which side of it is
    # which: 4300 digits convert, 4301 do not. Without this the fix could be
    # "refuse any long integer" and still pass everything above.
    inside = "9" * 4300
    span = next(iter(adapter.parse([a_record(adapter, start_time=inside)])))
    assert span.started_at == int(inside)
    assert type(span.started_at) is int


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
# An integer timestamp keeps its digits, in every adapter at once (batch C3)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.1: a timestamp reported as an integer literal is carried as an
# `int`, and only a fractional or exponent literal becomes a `float`. The
# library still never rescales and still never infers a unit -- it simply
# stops spending digits it was given. float64's spacing at epoch-nanosecond
# magnitude is 256 ns, so passing an ns-encoded time through `float()` merges
# spans that a record wrote apart (audit finding 5, `tests/audit/probe2.py`
# case G before this batch consumed it).

#: An epoch-nanosecond time whose last digits float64 cannot hold.
NS_LITERAL = 1700000000100000100


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize(
    "rendered", (NS_LITERAL, str(NS_LITERAL)), ids=("bare", "quoted")
)
def test_an_integer_timestamp_keeps_every_digit_the_record_wrote(adapter, rendered):
    span = next(iter(adapter.parse([a_record(adapter, start_time=rendered)])))
    assert span.started_at == NS_LITERAL
    assert isinstance(span.started_at, int)
    # The premise: this number is not one float64 can hold, so a library that
    # went through `float()` would fail this by 100 ns whatever it asserted.
    assert float(NS_LITERAL) != NS_LITERAL


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_two_spans_a_hundred_nanoseconds_apart_stay_apart(adapter):
    # The whole path, because the loss used to happen in the adapter and show
    # up in the builder: the two siblings collapsed onto one float and the
    # edge between them was emitted as tied -- deterministic, and wrong about
    # which span started first (`SPEC.md` §4.3).
    spans = list(
        adapter.parse(
            [
                a_record(adapter, span_id="s0"),
                a_record(adapter, span_id="s1", parent_id="s0", start_time=NS_LITERAL),
                a_record(
                    adapter,
                    span_id="s2",
                    parent_id="s0",
                    start_time=NS_LITERAL + 100,
                ),
            ]
        )
    )
    graph = build_graph(
        spans, adapter=AdapterInfo(id=adapter.id, version=adapter.version)
    )
    starts = {node.id: node.started_at for node in graph.nodes()}
    assert starts["s1"] == NS_LITERAL and starts["s2"] == NS_LITERAL + 100
    temporal = [edge for edge in graph.edges() if edge.kind is EdgeKind.TEMPORAL]
    assert [(edge.src, edge.dst) for edge in temporal] == [("s1", "s2")]
    assert "tied" not in temporal[0].basis


# --------------------------------------------------------------------------
# A record field stated in a rendering neither adapter reads (batch R12)
# --------------------------------------------------------------------------
#
# The same rule as the attribute keys above, one level up. `unmapped` names
# record fields too, written `<record>.<field>` (`SPEC.md` §3.7), and until
# this batch only the two timestamps used it: the identity fields were
# consumed by a static `KNOWN_RECORD_KEYS` set, so a `name` or a `parent_id`
# reported as `42` fell to its default -- `""`, `None` -- and left no trace
# anywhere but `raw`. Here rather than in either adapter's own file because
# both dialects read these four fields the same way, and one reporting an
# unreadable id that the other swallows is a cross-dialect difference.

IDENTITY_FIELDS = ("span_id", "parent_id", "trace_id", "name")

#: Renderings neither dialect reads as a string. `None` is deliberately not
#: here: it is an absence, and the test below says so.
UNREADABLE = (42, 4.5, True, [], {}, ["s0"])


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
@pytest.mark.parametrize("rendered", UNREADABLE, ids=repr)
def test_an_identity_field_the_adapter_cannot_read_is_reported(
    adapter, field, rendered
):
    span = next(iter(adapter.parse([a_record(adapter, **{field: rendered})])))
    assert f"<record>.{field}" in span.unmapped
    assert codes.UNMAPPED_ATTRIBUTES in [d.code for d in span.diagnostics]
    # It still fell to its default, which is the reason reporting it is the
    # only trace: nothing on the node says a value was stated here.
    assert getattr(span, field, None) is None or field == "name"
    # And the value itself is still in `raw`, verbatim.
    assert span.raw.source[field] == rendered


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_an_identity_field_the_dialect_omits_is_not_reported(adapter, field):
    # Nothing was stated, so there is nothing the adapter failed to read.
    record = a_record(adapter)
    record.pop(field, None)
    span = next(iter(adapter.parse([record])))
    assert f"<record>.{field}" not in span.unmapped


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_a_null_identity_field_is_absence_not_a_refused_rendering(adapter, field):
    # `null` is how a record says "no parent", "no name" -- the same reading
    # `start_time: null` already gets (`SPEC.md` §3.1, §3.7).
    span = next(iter(adapter.parse([a_record(adapter, **{field: None})])))
    assert f"<record>.{field}" not in span.unmapped


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_an_empty_parent_reference_was_read_and_is_not_reported(adapter):
    # The one string that means something other than itself: `""` is *read*
    # as "no parent" (`SPEC.md` §4.0, batch R10), so it decided something and
    # is not a rendering the adapter refused.
    span = next(iter(adapter.parse([a_record(adapter, parent_id="")])))
    assert span.parent_id is None
    assert "<record>.parent_id" not in span.unmapped


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_readable_identity_field_is_not_reported(adapter):
    # The pin on the other side: the ordinary record reports no field at all.
    span = next(iter(adapter.parse([a_record(adapter)])))
    assert not [key for key in span.unmapped if key.startswith("<record>.")]


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


# --------------------------------------------------------------------------
# Classification is per record (batch E2)
# --------------------------------------------------------------------------

# A dialect is a property of a **record**, not of a file (`SPEC.md` §6.1): one
# process can run a framework instrumentor and an SDK instrumentor at once and
# their spans share one export. So the registry asks each adapter about each
# record, using the declaration the protocol already has -- `detect([record])`
# -- and no marker table lives outside the adapter that owns the marker.
#
# With stubs here, and over the two real dialects in `tests/test_detection.py`.


def test_a_record_is_classified_by_the_adapters_that_claim_it():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    assert registry.classify(ONE[0]) == ("one",)
    assert registry.classify(TWO[0]) == ("two",)
    assert registry.classify(NEITHER[0]) == ()


def test_classification_is_ordered_by_adapter_id_not_by_arrival():
    both = {"one.marker": True, "two.marker": True}
    forwards = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    backwards = a_registry(
        StubAdapter("two", "two.marker"), StubAdapter("one", "one.marker")
    )
    assert forwards.classify(both) == backwards.classify(both) == ("one", "two")


def test_the_partition_sorts_every_record_into_the_adapter_that_claimed_it():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    records = [ONE[0], TWO[0], ONE[0]]
    partition = registry.partition(records)
    assert [claim.adapter_id for claim in partition.claims] == ["one", "two"]
    assert partition.contributors == ("one", "two")
    # Input order within an adapter, because `parse()` numbers what it is
    # given and `RawRecord.line_number` is that number (`SPEC.md` §3.5).
    assert partition.claims[0].records == (ONE[0], ONE[0])
    assert partition.claims[1].records == (TWO[0],)
    assert partition.unclaimed == ()


def test_a_record_no_adapter_claims_is_carried_rather_than_dropped():
    registry = a_registry(StubAdapter("one", "one.marker"))
    partition = registry.partition([ONE[0], NEITHER[0]])
    assert partition.contributors == ("one",)
    assert partition.claims[0].records == (ONE[0],)
    assert partition.unclaimed == (NEITHER[0],)


def test_a_record_two_adapters_claim_is_a_hard_error_naming_both():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    records = [ONE[0], {"span_id": "s7", "one.marker": True, "two.marker": True}]
    with pytest.raises(AdapterSelectionError) as failure:
        registry.partition(records)
    message = str(failure.value)
    assert failure.value.code == ADAPTER_AMBIGUOUS
    # Locatable: which record, which span, who claimed it, and the way out.
    for expected in ("record 2", "s7", "one", "two", "--adapter"):
        assert expected in message


def test_the_ambiguous_record_error_survives_a_record_with_no_span_id():
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    with pytest.raises(AdapterSelectionError) as failure:
        registry.partition([{"one.marker": True, "two.marker": True}])
    assert "record 1" in str(failure.value)


def test_the_partition_refuses_when_nothing_is_registered():
    with pytest.raises(AdapterSelectionError) as failure:
        AdapterRegistry().partition(ONE)
    assert failure.value.code == NO_ADAPTERS_REGISTERED


def test_classification_cannot_depend_on_where_a_record_sat():
    """One record, no context: proximity has nowhere to enter (`SPEC.md` §5)."""
    registry = a_registry(
        StubAdapter("one", "one.marker"), StubAdapter("two", "two.marker")
    )
    records = [ONE[0], TWO[0], NEITHER[0]]
    forwards = registry.partition(records)
    backwards = registry.partition(list(reversed(records)))
    assert [c.adapter_id for c in forwards.claims] == [
        c.adapter_id for c in backwards.claims
    ]
    assert forwards.unclaimed == backwards.unclaimed
    for ahead, behind in zip(forwards.claims, backwards.claims, strict=True):
        assert sorted(map(repr, ahead.records)) == sorted(map(repr, behind.records))


def test_the_declared_confidence_is_measured_over_the_records_it_claimed():
    """Per record to classify, over a bounded sample to declare.

    The number in `meta` keeps its meaning from `SPEC.md` §3.9 -- the adapter's
    own claim about the input it was given -- and stays bounded, so an adapter
    that claims every record reports what it reported before classification
    existed.
    """
    seen = []
    registry = a_registry(StubAdapter("one", "one.marker", seen=seen))
    partition = registry.partition([{"one.marker": True}] * 500)
    assert partition.claims[0].declared_confidence == 0.9
    assert seen[:500] == [1] * 500
    assert seen[500:] == [DETECTION_SAMPLE_SIZE]


def test_an_adapter_that_raises_while_classifying_is_named():
    class Raiser:
        id = "raiser"
        version = "0.1.0"

        def detect(self, sample):
            raise RuntimeError("boom")

        def parse(self, records):
            return iter(())

    registry = a_registry(StubAdapter("one", "one.marker"), Raiser())
    with pytest.raises(AdapterSelectionError) as failure:
        registry.partition(ONE)
    assert failure.value.code == ADAPTER_DETECT_FAILED
    assert "raiser" in str(failure.value)


# --------------------------------------------------------------------------
# The keys a decision reads, in every adapter at once (batch R12)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.7: a key is consumed where it is READ, never before, so a value
# the adapter could not read decided nothing and stays in `unmapped`. Each
# adapter's own test file states the rule at each of its keys; what lives here
# is the claim the two must make **together**. A tool name or a call id that
# one dialect reports and the other swallows is a cross-dialect difference in
# the only place the difference could be seen -- an unreadable value never
# reaches a node field, so `unmapped_attributes` is the whole report.

#: The key each dialect states one deciding fact at. The keys differ; what
#: must not differ is whether an unreadable value at them is reported.
DECIDING_KEYS = {
    "openinference": {
        "operation": "tool.name",
        "call_id": "tool_call.id",
        "kind": "openinference.span.kind",
    },
    "otel_genai": {
        "operation": "gen_ai.tool.name",
        "call_id": "gen_ai.tool.call.id",
        "kind": "gen_ai.operation.name",
    },
}


def a_record_stating(adapter, **facts):
    """`a_record`, with each named fact written at this dialect's key for it."""
    record = a_record(adapter)
    stated = {DECIDING_KEYS[adapter.id][fact]: value for fact, value in facts.items()}
    record["attributes"] = {**record["attributes"], **stated}
    return record


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("value", [7, None, {"name": "lookup"}, [], True])
def test_an_operation_name_neither_dialect_can_read_is_reported_by_both(adapter, value):
    span = next(iter(adapter.parse([a_record_stating(adapter, operation=value)])))
    assert span.operation is None
    assert span.unmapped == (DECIDING_KEYS[adapter.id]["operation"],)
    assert codes.UNMAPPED_ATTRIBUTES in [d.code for d in span.diagnostics]


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
@pytest.mark.parametrize("value", [7, None, {"id": "call_a"}, [], True])
def test_a_call_id_neither_dialect_can_read_is_reported_by_both(adapter, value):
    span = next(iter(adapter.parse([a_record_stating(adapter, call_id=value)])))
    assert span.call_ids == ()
    assert span.call_role is None
    assert span.unmapped == (DECIDING_KEYS[adapter.id]["call_id"],)


@pytest.mark.parametrize("adapter", REAL_ADAPTERS, ids=lambda a: a.id)
def test_a_span_kind_reported_as_null_is_reported_by_both(adapter):
    # And is reported *as present* by both: the diagnostic that used to say
    # "no attribute" said it in both dialects, of a key both had been sent.
    span = next(iter(adapter.parse([a_record_stating(adapter, kind=None)])))
    assert span.kind is NodeKind.UNKNOWN
    assert span.unmapped == (DECIDING_KEYS[adapter.id]["kind"],)
    [reported] = [d for d in span.diagnostics if d.code == codes.UNKNOWN_SPAN_KIND]
    key = DECIDING_KEYS[adapter.id]["kind"]
    assert f"no {key} attribute" not in reported.message
    assert "null" in reported.message
