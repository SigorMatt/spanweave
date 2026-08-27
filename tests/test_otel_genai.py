"""The OTel GenAI adapter (TASKS.md 2.9).

The shared corpus proves this adapter reproduces the reviewed expectations.
What it cannot cover is the quirks of *this* dialect — chiefly that "what the
model said" and "what the model was shown" are separated by a part `type`
inside a payload rather than by an attribute prefix, which is a new way to get
`SPEC.md` §4.4 wrong.

As in `test_openinference.py`, most of these assert a `None`, an `absent`, or a
diagnostic: most of what an adapter must get right is what it refuses to
invent.
"""

import json
import pathlib

from spanweave import diagnostics as codes
from spanweave.adapters.otel_genai import OtelGenAiAdapter
from spanweave.model import NodeKind, PayloadState, Status
from spanweave.read import read_trace
from spanweave.seam import CallRole

CAPTURED = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures/captured/genai_tool_call.jsonl"
)

ADAPTER = OtelGenAiAdapter()


def span_of(attributes=None, **record):
    full = {"span_id": "s1", "name": "op", **record}
    if attributes is not None:
        full["attributes"] = attributes
    return next(iter(ADAPTER.parse([full])))


def messages(*msgs):
    return json.dumps(list(msgs), separators=(",", ":"))


def user(text="hello"):
    return {"role": "user", "parts": [{"content": text, "type": "text"}]}


def calls(*ids):
    return {
        "role": "assistant",
        "parts": [
            {"arguments": {}, "name": "t", "id": i, "type": "tool_call"} for i in ids
        ],
        "finish_reason": "tool_calls",
    }


def responses(*ids):
    return {
        "role": "tool",
        "parts": [
            {"response": "{}", "id": i, "type": "tool_call_response"} for i in ids
        ],
    }


def codes_of(span):
    return sorted(diagnostic.code for diagnostic in span.diagnostics)


# --------------------------------------------------------------------------
# detect()
# --------------------------------------------------------------------------


def test_detect_keys_on_the_gen_ai_namespace():
    assert ADAPTER.detect([{"attributes": {"gen_ai.operation.name": "chat"}}]) == 0.9


def test_detect_declines_another_dialect_rather_than_guessing():
    # The two captured traces describe the same run. Each adapter must claim
    # exactly one of them, or `SPEC.md` §6.1 selection becomes a race.
    assert ADAPTER.detect([{"attributes": {"openinference.span.kind": "LLM"}}]) == 0.0
    assert ADAPTER.detect([{"attributes": {}}]) == 0.0
    assert ADAPTER.detect([]) == 0.0


def test_detect_never_raises_on_junk():
    assert ADAPTER.detect(["not a record", None, 7, {"attributes": "not a map"}]) == 0.0


# --------------------------------------------------------------------------
# Kinds
# --------------------------------------------------------------------------


def test_the_operation_name_is_the_kind_marker():
    assert span_of({"gen_ai.operation.name": "chat"}).kind is NodeKind.LLM
    assert span_of({"gen_ai.operation.name": "execute_tool"}).kind is NodeKind.TOOL
    assert span_of({"gen_ai.operation.name": "invoke_agent"}).kind is NodeKind.AGENT


def test_an_unknown_operation_is_unknown_and_says_so():
    # Never forced into a neighbouring kind: a wrong kind is invisible
    # downstream and an `unknown` is not (ADAPTERS.md §3).
    span = span_of({"gen_ai.operation.name": "transmogrify"})
    assert span.kind is NodeKind.UNKNOWN
    assert codes.UNKNOWN_SPAN_KIND in codes_of(span)
    assert span.attributes["reported_kind"] == "transmogrify"


def test_a_span_with_no_operation_is_unknown_and_kept():
    span = span_of({"gen_ai.request.model": "m"})
    assert span.kind is NodeKind.UNKNOWN
    assert codes.UNKNOWN_SPAN_KIND in codes_of(span)
    assert span.raw.source["attributes"]["gen_ai.request.model"] == "m"


def test_a_record_that_is_not_an_object_is_still_a_node():
    span = next(iter(ADAPTER.parse(["nonsense"])))
    assert span.kind is NodeKind.UNKNOWN
    assert span.raw.source == "nonsense"


# --------------------------------------------------------------------------
# Pairing — the part this dialect offers a new way to get wrong
# --------------------------------------------------------------------------


def test_a_tool_call_part_in_the_span_s_own_output_is_a_request():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(calls("call_a")),
        }
    )
    assert span.call_role is CallRole.REQUESTER
    assert span.call_ids == ("call_a",)


def test_several_calls_in_one_turn_all_belong_to_the_span():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(calls("call_a", "call_b")),
        }
    )
    assert span.call_ids == ("call_a", "call_b")


def test_the_same_call_named_twice_is_recorded_once():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(calls("call_a"), calls("call_a")),
        }
    )
    assert span.call_ids == ("call_a",)


def test_a_tool_call_part_in_the_INPUT_messages_does_not_pair():
    # THE defect this dialect can reproduce. The protocol resends the whole
    # conversation, so a follow-up turn carries the previous turn's `tool_call`
    # part as input context. Reading it as a request would make the builder
    # state a `call_result` relation with `warrant=explicit` that the
    # telemetry never asserted (`SPEC.md` §4.4).
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": messages(user(), calls("call_a")),
            "gen_ai.output.messages": messages(
                {"role": "assistant", "parts": [{"content": "done", "type": "text"}]}
            ),
        }
    )
    assert span.call_ids == ()
    assert span.call_role is None


def test_a_tool_call_response_part_is_a_result_the_span_was_given():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": messages(user(), responses("call_a")),
        }
    )
    assert span.received_call_ids == ("call_a",)
    # Received is not requested. Different relation, opposite direction.
    assert span.call_ids == ()


def test_a_response_part_in_the_OUTPUT_messages_is_not_a_received_result():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(responses("call_a")),
        }
    )
    assert span.received_call_ids == ()


def test_the_fulfilling_span_carries_the_id_directly():
    span = span_of(
        {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.call.id": "call_a"}
    )
    assert span.call_role is CallRole.FULFILLER
    assert span.call_ids == ("call_a",)


def test_nothing_pairs_when_the_dialect_names_no_id():
    span = span_of({"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "t"})
    assert span.call_ids == ()
    assert span.call_role is None


def test_a_message_list_of_an_unexpected_shape_yields_no_relation():
    # Tolerant rather than raising, and it claims nothing: the payload is still
    # `present` and still in `raw`, so only the relation is declined.
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": json.dumps({"not": "a list"}),
        }
    )
    assert span.call_ids == ()
    assert span.outputs.state is PayloadState.PRESENT


def test_the_dialect_declares_no_both_ends_data_edge():
    assert span_of({"gen_ai.operation.name": "chat"}).data_edges == ()


# --------------------------------------------------------------------------
# Payloads
# --------------------------------------------------------------------------


def test_an_absent_payload_is_not_an_empty_one():
    span = span_of({"gen_ai.operation.name": "execute_tool"})
    assert span.inputs.state is PayloadState.ABSENT
    assert span.outputs.state is PayloadState.ABSENT


def test_an_emitted_but_empty_payload_is_empty():
    span = span_of(
        {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.call.arguments": "{}"}
    )
    assert span.inputs.state is PayloadState.EMPTY
    assert span.inputs.raw == "{}"


def test_a_payload_that_does_not_parse_keeps_its_text_and_reports():
    span = span_of(
        {"gen_ai.operation.name": "chat", "gen_ai.input.messages": '[{"role": '}
    )
    assert span.inputs.state is PayloadState.PRESENT
    assert span.inputs.value is None
    assert span.inputs.raw == '[{"role": '
    assert codes.PAYLOAD_PARSE_FAILED in codes_of(span)


def test_a_tool_span_reads_the_tool_keys_and_an_llm_span_the_message_keys():
    tool = span_of(
        {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.call.arguments": '{"a": 1}',
            "gen_ai.tool.call.result": '{"b": 2}',
        }
    )
    assert tool.inputs.value == {"a": 1}
    assert tool.outputs.value == {"b": 2}


def test_the_pair_a_span_did_not_use_is_reported_rather_than_preferred_away():
    # A tool span carrying message attributes too would otherwise have them
    # silently dropped. Lossless means the unread pair is named.
    span = span_of(
        {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.call.arguments": "{}",
            "gen_ai.input.messages": messages(user()),
        }
    )
    assert "gen_ai.input.messages" in span.unmapped


def test_the_dialect_never_signals_redaction_or_truncation():
    # OpenInference writes a literal `__REDACTED__` marker; this dialect has no
    # such signal, so those states are simply never produced here. Inventing
    # one would claim the instrumentor said something it did not.
    span = span_of(
        {"gen_ai.operation.name": "chat", "gen_ai.input.messages": '"__REDACTED__"'}
    )
    assert span.inputs.state is PayloadState.PRESENT


# --------------------------------------------------------------------------
# Everything else the adapter declines to invent
# --------------------------------------------------------------------------


def test_the_agent_name_is_not_read_as_an_operation():
    # `operation` is the tool / model / retriever name (`SPEC.md` §3.2). An
    # agent's name is none of those, and mapping it would fill a field the
    # other dialect leaves empty on the same span.
    span = span_of(
        {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "agent.run"}
    )
    assert span.operation is None
    assert "gen_ai.agent.name" in span.unmapped
    assert codes.UNMAPPED_ATTRIBUTES in codes_of(span)


def test_no_total_token_count_is_derived():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 4,
        }
    )
    assert span.usage.input_tokens == 10
    assert span.usage.output_tokens == 4
    assert span.usage.total_tokens is None


def test_a_token_count_the_model_has_no_field_for_is_kept_in_extra():
    span = span_of(
        {"gen_ai.operation.name": "chat", "gen_ai.usage.cached_input_tokens": 8}
    )
    assert span.usage.extra == {"cached_input_tokens": 8}


def test_a_usage_key_that_is_not_a_count_is_reported_rather_than_coerced():
    span = span_of({"gen_ai.operation.name": "chat", "gen_ai.usage.input_tokens": "8"})
    assert span.usage is None
    assert "gen_ai.usage.input_tokens" in span.unmapped


def test_no_usage_at_all_is_none_not_zero():
    assert span_of({"gen_ai.operation.name": "chat"}).usage is None


def test_an_unreported_status_is_unset():
    assert span_of({"gen_ai.operation.name": "chat"}).status is Status.UNSET
    assert span_of({"gen_ai.operation.name": "chat"}, status="ERROR").status is (
        Status.ERROR
    )


def test_a_record_key_the_adapter_does_not_read_is_reported():
    span = span_of({"gen_ai.operation.name": "chat"}, events=[{"name": "x"}])
    assert "<record>.events" in span.unmapped


# --------------------------------------------------------------------------
# Against the captured trace, not only against hand-written spans
# --------------------------------------------------------------------------


def test_the_captured_trace_pairs_exactly_one_call_and_one_result():
    spans = list(ADAPTER.parse(read_trace(CAPTURED)))
    requesters = [s for s in spans if s.call_role is CallRole.REQUESTER]
    fulfillers = [s for s in spans if s.call_role is CallRole.FULFILLER]
    assert len(requesters) == 1, "the follow-up turn echoes the id and must not pair"
    assert len(fulfillers) == 1
    assert requesters[0].call_ids == fulfillers[0].call_ids


def test_the_captured_trace_declares_the_data_relation():
    spans = list(ADAPTER.parse(read_trace(CAPTURED)))
    received = [s for s in spans if s.received_call_ids]
    assert len(received) == 1
    # The span that received the result is NOT the one that requested it.
    assert received[0].call_role is None


def test_every_captured_span_keeps_its_record_verbatim():
    records = [json.loads(line) for line in CAPTURED.read_text().splitlines()]
    spans = list(ADAPTER.parse(records))
    assert [span.raw.source for span in spans] == records


# --------------------------------------------------------------------------
# The name inside the part (SPEC.md 3.7, `source` per code)
# --------------------------------------------------------------------------


def test_a_requested_call_carries_the_name_inside_its_part():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(
                {
                    "role": "assistant",
                    "parts": [
                        {
                            "arguments": {"order": "A-1"},
                            "name": "lookup",
                            "id": "call_a",
                            "type": "tool_call",
                        }
                    ],
                }
            ),
        }
    )
    assert span.call_names == {"call_a": "lookup"}


def test_each_requested_call_gets_its_own_name_not_the_first_one():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(
                {
                    "role": "assistant",
                    "parts": [
                        {"name": "alpha", "id": "call_a", "type": "tool_call"},
                        {"name": "beta", "id": "call_b", "type": "tool_call"},
                    ],
                }
            ),
        }
    )
    assert span.call_names == {"call_a": "alpha", "call_b": "beta"}


def test_a_part_with_no_name_leaves_its_call_unnamed():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(
                {"role": "assistant", "parts": [{"id": "call_a", "type": "tool_call"}]}
            ),
        }
    )
    assert span.call_ids == ("call_a",)
    assert span.call_names == {}


def test_a_fulfilling_span_names_its_call_from_its_own_tool_name():
    span = span_of(
        {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "lookup",
            "gen_ai.tool.call.id": "call_a",
        }
    )
    assert span.call_names == {"call_a": "lookup"}


def test_an_echoed_call_name_in_the_input_list_is_not_read():
    # The echo defect, one level down: the same `tool_call` part reappears in
    # the NEXT turn's input list, name and all (`tool_call_history_echo`).
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": messages(
                {
                    "role": "assistant",
                    "parts": [{"name": "lookup", "id": "call_a", "type": "tool_call"}],
                }
            ),
        }
    )
    assert span.call_ids == ()
    assert span.call_names == {}


def test_a_response_part_is_not_a_request_even_when_it_names_a_tool():
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.output.messages": messages(
                {
                    "role": "tool",
                    "parts": [
                        {
                            "name": "lookup",
                            "id": "call_a",
                            "type": "tool_call_response",
                        }
                    ],
                }
            ),
        }
    )
    assert span.call_names == {}


# --------------------------------------------------------------------------
# The operation vocabulary against the convention's own registry
# --------------------------------------------------------------------------


def test_a_retrieval_operation_is_a_retriever():
    # Added at `TASKS.md` 2.11, which asked whether "GenAI's operation
    # vocabulary may not name a retriever". It does: the convention's own
    # description is "Retrieval operation such as ... Search Vector Store".
    # Its absence from OPERATIONS was an inconsistency, not an abstention --
    # `embeddings`, `text_completion`, `generate_content` and `create_agent`
    # are all mapped on exactly the same evidence.
    span = span_of({"gen_ai.operation.name": "retrieval"})
    assert span.kind is NodeKind.RETRIEVER
    assert codes_of(span) == []


def test_invoke_workflow_stays_unmapped_and_says_so():
    # The one convention value deliberately not mapped: `chain` would be a
    # judgement about what a workflow is, not a name match. An honest
    # `unknown` plus a diagnostic is the library's answer to that
    # (`SPEC.md` §3.2), and the reported token survives.
    from spanweave.adapters.otel_genai import OPERATIONS, UNMAPPED_BY_DECISION

    assert set(UNMAPPED_BY_DECISION).isdisjoint(OPERATIONS)
    span = span_of({"gen_ai.operation.name": "invoke_workflow"})
    assert span.kind is NodeKind.UNKNOWN
    assert span.attributes["reported_kind"] == "invoke_workflow"
    assert codes_of(span) == ["unknown_span_kind"]


def test_the_adapter_accounts_for_every_operation_the_convention_defines():
    """Mapped, or named as a decision. Never silently absent.

    The corpus cannot see this: no scenario exercises seven of the nine, so a
    value dropped from `OPERATIONS` would fail nothing. The convention is the
    only source of truth for what the dialect can say, and it moves.
    """
    from spanweave.adapters.otel_genai import OPERATIONS, UNMAPPED_BY_DECISION

    defined = {
        "chat",
        "create_agent",
        "embeddings",
        "execute_tool",
        "generate_content",
        "invoke_agent",
        "invoke_workflow",
        "retrieval",
        "text_completion",
    }
    unaccounted = sorted(defined - set(OPERATIONS) - set(UNMAPPED_BY_DECISION))
    assert unaccounted == [], (
        f"the convention defines {unaccounted}, which this adapter neither "
        f"maps nor names as a decision"
    )


# --------------------------------------------------------------------------
# A retrieval span's two content attributes (TASKS.md 2.17)
# --------------------------------------------------------------------------
#
# Neither attribute appears in any captured trace in this repo -- three traces
# and not a `retrieval` or `embeddings` span among them. What they were mapped
# from is `opentelemetry-util-genai` 1.1b0's `_retrieval_invocation.py`, the
# support library the captured traces' own instrumentor delegates to for
# `gen_ai.input.messages`. That is the same source at the same version, and it
# is stated here rather than left to be inferred from the fact that these tests
# pass.


def a_retrieval(**attributes):
    return span_of({"gen_ai.operation.name": "retrieval", **attributes})


def test_a_retrieval_span_states_its_query_as_text_and_its_documents_as_json():
    # The dialect distinguishes the two, and so must the adapter:
    # `query_text` is typed `str` and written verbatim; `documents` goes
    # through the same `gen_ai_json_dumps` the message lists use.
    span = a_retrieval(
        **{
            "gen_ai.retrieval.query.text": "order status",
            "gen_ai.retrieval.documents": '[{"id":"doc-1"},{"id":"doc-2"}]',
        }
    )
    assert span.kind is NodeKind.RETRIEVER
    assert span.inputs.state is PayloadState.PRESENT
    assert span.inputs.mime == "text/plain"
    assert span.inputs.value == "order status"
    assert span.outputs.state is PayloadState.PRESENT
    assert span.outputs.mime == "application/json"
    assert span.outputs.value == [{"id": "doc-1"}, {"id": "doc-2"}]
    assert codes_of(span) == []


def test_a_query_that_looks_like_json_is_still_text():
    # The mime comes from what the convention says the attribute IS, not from
    # what one value happens to look like. Parsing this would invent a
    # structure the dialect does not claim -- the same error as refusing
    # `application/json` on the attributes it does.
    span = a_retrieval(**{"gen_ai.retrieval.query.text": '{"not":"json to us"}'})
    assert span.inputs.mime == "text/plain"
    assert span.inputs.value == '{"not":"json to us"}'
    assert codes_of(span) == []


def test_a_retrieval_span_with_no_content_has_absent_payloads():
    # Both attributes are Opt-In in the convention, so absent is the ordinary
    # case and must not be confused with empty (SPEC.md §3.3).
    span = a_retrieval()
    assert span.inputs.state is PayloadState.ABSENT
    assert span.outputs.state is PayloadState.ABSENT
    assert span.inputs.mime is None and span.outputs.mime is None


def test_an_empty_document_list_is_empty_not_absent():
    span = a_retrieval(**{"gen_ai.retrieval.documents": "[]"})
    assert span.outputs.state is PayloadState.EMPTY
    assert span.outputs.value == []


def test_documents_that_do_not_parse_stay_present_and_say_so():
    span = a_retrieval(**{"gen_ai.retrieval.documents": "[{"})
    assert span.outputs.state is PayloadState.PRESENT
    assert span.outputs.value is None
    assert span.outputs.raw == "[{"
    assert codes_of(span) == ["payload_parse_failed"]


def test_a_retrieval_span_does_not_fall_back_to_the_message_pair():
    # The retrieval pair is not a fallback, and the asymmetry is the
    # convention's: `RetrievalInvocation` emits no message list at all. A
    # retrieval span carrying one is reporting something this adapter does not
    # read, and reporting it is the honest outcome -- not preferring it away.
    span = a_retrieval(**{"gen_ai.input.messages": messages(user("hi"))})
    assert span.inputs.state is PayloadState.ABSENT
    assert "gen_ai.input.messages" in span.unmapped
    assert codes_of(span) == ["unmapped_attributes"]


def test_the_retrieval_attributes_are_not_read_on_other_kinds():
    # They belong to one invocation in the convention. On a `chat` span they
    # are attributes this adapter does not normalize, which is `unmapped` plus
    # a diagnostic -- never a payload smuggled in from another operation.
    span = span_of(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.retrieval.documents": '[{"id":"doc-1"}]',
        }
    )
    assert span.kind is NodeKind.LLM
    assert span.outputs.state is PayloadState.ABSENT
    assert "gen_ai.retrieval.documents" in span.unmapped


def test_an_embedding_span_has_no_content_attribute_in_this_dialect():
    # The reason `retriever_and_embedding` is STILL declared unrenderable
    # after this task. `opentelemetry-util-genai`'s `EmbeddingInvocation`
    # emits `dimension_count`, `encoding_formats`, `response_model` and token
    # counts -- and no content of any kind. So an embedding span's payloads
    # are `absent` here, where OpenInference records the embedded text as
    # `present`. `absent` != `present` is a payload-STATE disagreement, and
    # FIXTURES.md §4.4 forbids declaring one away, ever.
    span = span_of(
        {"gen_ai.operation.name": "embeddings", "gen_ai.request.model": "demo-embed"}
    )
    assert span.kind is NodeKind.EMBEDDING
    assert span.inputs.state is PayloadState.ABSENT
    assert span.outputs.state is PayloadState.ABSENT
    assert span.operation == "demo-embed"
