"""The model types (TASKS.md 0.7).

Two of these tests are tripwires rather than tests: the closed-enum membership
assertions exist so that adding a `NodeKind` or an `EdgeKind` cannot happen
quietly. Both are spec changes and halt points (`AGENT.md`); if one of these
fails, the fix is a conversation, not an edit to the expected set.
"""

import dataclasses

import pytest

from spanweave.model import (
    ALLOWED_WARRANTS,
    AdapterInfo,
    Diagnostic,
    DiagnosticLevel,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeKind,
    Payload,
    PayloadState,
    Provenance,
    RawRecord,
    Status,
    Usage,
    Warrant,
)

# The worked example's first span (FIXTURES.md §7), hand-written.
SOURCE_RECORD = {
    "trace_id": "t1",
    "span_id": "s0",
    "parent_id": None,
    "name": "agent.run",
    "start_time": 1000.0,
    "end_time": 1004.0,
    "status": "OK",
    "attributes": {
        "openinference.span.kind": "AGENT",
        "input.value": "Look up the order status.",
        "input.mime_type": "text/plain",
    },
}


def a_node(**overrides):
    fields = {
        "id": "s0",
        "kind": NodeKind.AGENT,
        "name": "agent.run",
        "raw": RawRecord(source=SOURCE_RECORD, source_id="s0", line_number=1),
        "provenance": Provenance(adapter_id="some_dialect", adapter_version="0.1.0"),
        "started_at": 1000.0,
        "ended_at": 1004.0,
        "status": Status.OK,
        "inputs": Payload(
            state=PayloadState.PRESENT,
            mime="text/plain",
            value="Look up the order status.",
            raw="Look up the order status.",
        ),
    }
    return Node(**{**fields, **overrides})


# --------------------------------------------------------------------------
# Closed enums (halt points if these fail)
# --------------------------------------------------------------------------


def test_node_kinds_are_exactly_the_specified_set():
    assert {k.value for k in NodeKind} == {
        "agent",
        "llm",
        "tool",
        "retriever",
        "embedding",
        "chain",
        "unknown",
    }


def test_edge_kinds_are_exactly_the_specified_set():
    assert {k.value for k in EdgeKind} == {
        "parent",
        "call_result",
        "data",
        "link",
        "temporal",
    }


def test_payload_states_are_exactly_the_specified_five():
    assert {s.value for s in PayloadState} == {
        "present",
        "empty",
        "absent",
        "redacted",
        "truncated",
    }


def test_warrants_and_levels_are_closed():
    assert {w.value for w in Warrant} == {"explicit", "derived"}
    assert {s.value for s in Status} == {"ok", "error", "unset"}
    # Never "error": errors raise (SPEC.md §3.7).
    assert {level.value for level in DiagnosticLevel} == {"info", "warning"}


# --------------------------------------------------------------------------
# A hand-written node round-trips
# --------------------------------------------------------------------------


def test_a_hand_written_node_keeps_what_it_was_given():
    node = a_node()
    assert node.id == "s0"
    assert node.kind is NodeKind.AGENT
    assert node.name == "agent.run"
    assert node.raw.source == SOURCE_RECORD
    assert node.inputs.has_content
    # Absent by default, and absent is a statement, not a blank.
    assert node.outputs.state is PayloadState.ABSENT
    assert node.usage is None


def test_a_node_round_trips_through_asdict_and_back():
    node = a_node()
    unpacked = dataclasses.asdict(node)
    assert unpacked["raw"]["source"] == SOURCE_RECORD
    rebuilt = Node(
        **{
            **unpacked,
            "raw": node.raw,
            "provenance": node.provenance,
            "inputs": node.inputs,
            "outputs": node.outputs,
        }
    )
    assert rebuilt == node


def test_the_verbatim_source_is_not_a_reference_to_a_prettified_copy():
    node = a_node()
    # Losslessness is verbatim-ness: what went in is what comes out.
    assert node.raw.source is SOURCE_RECORD


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("obj", "attribute"),
    [
        (a_node(), "kind"),
        (Payload.absent(), "state"),
        (Usage(input_tokens=1), "input_tokens"),
        (
            Edge("a", "b", EdgeKind.PARENT, Warrant.EXPLICIT, "span.parent_span_id"),
            "src",
        ),
        (Diagnostic(code="orphan_parent", message="x"), "code"),
        (RawRecord(source={}), "source"),
        (Meta(schema_version="0.1", spanweave_version="0.1.0"), "node_count"),
    ],
)
def test_model_types_are_frozen(obj, attribute):
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, attribute, "mutated")


def test_mappings_are_copied_on_construction():
    supplied = {"model": "demo-model"}
    node = a_node(attributes=supplied)
    supplied["model"] = "something-else"
    assert node.attributes == {"model": "demo-model"}

    counts = {"cache_read": 5}
    usage = Usage(extra=counts)
    counts["cache_read"] = 99
    assert usage.extra == {"cache_read": 5}


# --------------------------------------------------------------------------
# Payload states
# --------------------------------------------------------------------------


def test_absent_and_empty_are_not_the_same_statement():
    absent = Payload.absent()
    empty = Payload(state=PayloadState.EMPTY, mime="text/plain", value="", raw="")
    assert absent != empty
    assert absent.has_content is False
    assert empty.has_content is False
    # Same answer to "is there content", different reasons -- and `state` is
    # where a consumer reads which (SPEC.md §3.3).
    assert absent.state is not empty.state


def test_redacted_has_no_content_but_truncated_does():
    redacted = Payload(state=PayloadState.REDACTED, raw="__REDACTED__")
    truncated = Payload(state=PayloadState.TRUNCATED, value="the beginning of", raw="x")
    assert redacted.has_content is False
    assert truncated.has_content is True


def test_a_payload_that_failed_to_parse_keeps_its_raw_text():
    # SPEC.md §3.3: state stays present, value is None, raw holds the string.
    broken = Payload(
        state=PayloadState.PRESENT, mime="application/json", value=None, raw="{not json"
    )
    assert broken.raw == "{not json"
    assert broken.value is None


# --------------------------------------------------------------------------
# The warrant table is enforced, not documented
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", [EdgeKind.PARENT, EdgeKind.CALL_RESULT, EdgeKind.DATA, EdgeKind.LINK]
)
def test_explicit_only_kinds_refuse_a_derived_warrant(kind):
    with pytest.raises(ValueError, match="explicit-only"):
        Edge("a", "b", kind, Warrant.DERIVED, "some rule")


def test_temporal_refuses_an_explicit_warrant():
    # The promotion this forbids is the one nothing downstream could detect.
    with pytest.raises(ValueError, match="derived-only"):
        Edge(
            "a", "b", EdgeKind.TEMPORAL, Warrant.EXPLICIT, "sibling start_time ordering"
        )


def test_every_edge_kind_has_a_warrant_rule():
    assert set(ALLOWED_WARRANTS) == set(EdgeKind)


def test_edges_are_unique_on_src_dst_kind_and_basis():
    one = Edge("a", "b", EdgeKind.PARENT, Warrant.EXPLICIT, "span.parent_span_id")
    same = Edge(
        "a", "b", EdgeKind.PARENT, Warrant.EXPLICIT, "span.parent_span_id", adapter="x"
    )
    assert one.identity == same.identity
    other_kind = Edge("a", "b", EdgeKind.DATA, Warrant.EXPLICIT, "declared")
    assert one.identity != other_kind.identity


def test_edge_and_diagnostic_sort_keys_match_the_specified_order():
    edge = Edge("a", "b", EdgeKind.PARENT, Warrant.EXPLICIT, "span.parent_span_id")
    assert edge.sort_key == ("parent", "a", "b", "span.parent_span_id")
    diagnostic = Diagnostic(code="orphan_parent", message="m", node_id="n1")
    assert diagnostic.sort_key == ("orphan_parent", "n1", "m")
    assert Diagnostic(code="c", message="m").sort_key == ("c", "", "m")


# --------------------------------------------------------------------------
# Usage and meta
# --------------------------------------------------------------------------


def test_usage_never_invents_a_total():
    usage = Usage(input_tokens=42, output_tokens=17)
    assert usage.total_tokens is None


def test_meta_carries_the_adapter_and_its_confidence():
    meta = Meta(
        schema_version="0.1",
        spanweave_version="0.1.0",
        adapters=(
            AdapterInfo(id="some_dialect", version="0.1.0", declared_confidence=0.9),
        ),
    )
    # Declared, not measured: nothing in the trace could compute it, and the
    # name has to say so (SPEC.md §3.9).
    assert meta.adapters[0].declared_confidence == 0.9
    assert meta.source_digest is None
