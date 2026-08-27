# `unpaired_tool_call` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl`: **L1** the
`invoke_agent` span, **L2** the LLM turn that requested a call, **L3** the
`execute_tool` span. Same vocabulary as `llm_tool_llm/otel_genai.notes.md`;
only what is specific is repeated.

## The degradation

Both halves of the pairing failure, made by changing **ids** and nothing else:

| Span | Source | Change |
|---|---|---|
| s0 | L1 | `gen_ai.input.messages` dropped; the scenario's agent reports no payload |
| s1 | L2 | the `tool_call` part's `id` is `call_a`; `gen_ai.tool.definitions`, `provider.name`, `response.id`, `response.model`, `usage.*` and `server.address` dropped |
| s2 | L3 | `gen_ai.tool.call.id` is `call_b` — a **different** id — and `arguments` / `result` / `type` are dropped |

`gen_ai.response.finish_reasons` is kept on s1 on purpose: it is observed on
both chat spans in the capture, the adapter does not map it, and it is what
produces the single `unmapped_attributes` diagnostic the expected graph
requires. The OpenInference specimen reaches the same count through
`llm.finish_reason`.

## The mechanism, which is the interesting part

The two dialects state "this span requested a call" by different means and
produce the same graph:

| | OpenInference | OTel GenAI |
|---|---|---|
| requested id | an attribute **key**: `llm.output_messages.0.message.tool_calls.0.tool_call.id` | a `tool_call` **part** inside `gen_ai.output.messages` |
| fulfilled id | `tool_call.id` | `gen_ai.tool.call.id` |

Neither produces a `call_result` edge, both produce `unpaired_call` on s1 and
`unpaired_result` on s2, and the ids in both diagnostics match. The rule
(`SPEC.md` §4.4 — a requester id comes only from what the span itself
*produced*) survived being re-implemented against a different mechanism.

---

# `PREDICTIONS.md` O1 — what this rendering actually shows

O1 (finding **F5**, `TASKS.md` 2.4) said a requested-but-unfulfilled call can
be attributed to the model that asked but **not to the tool it named**, and
deferred to 2.10 the question of whether any single payload path recovers the
name in both dialects. Answered here against both renderings of this scenario,
built and inspected rather than reasoned about.

## (a) From the graph alone, can the requested tool be named?

**No, in either dialect — and they agree exactly on what they do carry.**

Serialized `graph.json`, both dialects, identical but for the adapter id:

```json
{"code": "unpaired_call", "level": "warning", "node_id": "s1",
 "source": "call_a",
 "message": "call 'call_a' was requested and no span in this input fulfils it; no edge is invented"}
```

The call **id** appears three times — `source`, inside `message`, and as the
`node_id` of the span that asked. The tool **name** appears zero times. There
is no node for a call that never ran, so `operation`, which is where a tool's
name lives (`SPEC.md` §3.2), has nowhere to be.

One asymmetry worth recording, because it is the kind of thing that makes a
consumer look portable when it is not: in OpenInference the name is *mentioned*
in a second diagnostic —
`unmapped_attributes` lists the key
`llm.output_messages.0.message.tool_calls.0.tool_call.function.name` — as a
**key**, never a value. In OTel GenAI it is inside the payload and appears in
no diagnostic at all. A consumer that scraped names out of diagnostic key lists
would work against dialect one and silently find nothing in dialect two.

## (b) The payload paths, and whether they are the same

Only by walking a payload, and the paths are not the same. They do not even
agree on the container type at the first step:

| | path to the name | path to the id |
|---|---|---|
| OpenInference | `outputs.value["choices"][i]["message"]["tool_calls"][j]["function"]["name"]` | same, `[j]["id"]` |
| OTel GenAI | `outputs.value[i]["parts"][j]["name"]`, where `parts[j]["type"] == "tool_call"` | same, `[j]["id"]` |

`outputs.value` is a **dict** in one and a **list** in the other. There is no
prefix in common, so no single expression reaches both, and a consumer holding
one of these paths holds one dialect.

## (c) Does a consumer written against one path return a confident zero?

**Not on its own — it raises.** Measured, in both directions, on the two graphs
this scenario builds:

| consumer | against `openinference` | against `otel_genai` |
|---|---|---|
| OpenInference path, direct indexing | `['lookup']` | `TypeError: list indices must be integers or slices, not str` |
| OpenInference path, defensive `.get()` chain | `['lookup']` | `AttributeError: 'list' object has no attribute 'get'` |
| OTel GenAI path, direct indexing | `TypeError: string indices must be integers, not 'str'` | `['lookup']` |

This **partly refutes O1 as written**, and the correction matters more than the
confirmation. O1 said the walk "does not raise — it reports a confident zero,
indistinguishable from 'there were none.'" It does raise, and the usual
defensive idiom (`.get(key, [])` chains, written precisely because payloads are
untrusted) raises too, because a `.get` on a list is an `AttributeError` rather
than a miss.

The confident zero is real, but it is **the consumer's own error handling**,
not a silent shape mismatch. Any `try/except` around the walk — and there will
be one, because trace payloads are untrusted input (`SECURITY.md`) — converts
the loud failure into an empty result. `examples/fleet_aggregate` already wraps
at trace granularity for exactly that reason (`TraceFailure`).

So the risk stands and its mechanism is different: a portable consumer **can**
detect this today, if it chooses not to swallow it. That is a weaker gap than
O1 claimed, and it is a real one.

## What `examples/fleet_aggregate` does today

It declines to walk, and says so in the output rather than reporting an empty
rollup as a fact:

> `unfulfilled_calls.by_tool` is empty: `unpaired_call` names the requesting
> node and the call id, and a call that was requested but never ran has no
> node, so the tool it asked for is not on the graph. Recovering it means
> parsing the requesting node's outputs payload — one dialect's shape, in a
> consumer that must not know one.

That sentence was written against one dialect. This rendering is the evidence
that it was right about the second.

## The remedy is a decision, not a patch

Proposed at the `TASKS.md` 2.10 halt with the exact model surface. It is not
implemented here, and this file is deliberately evidence only.
