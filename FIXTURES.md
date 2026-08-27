# FIXTURES.md — the conformance corpus

The corpus is this project's executable spec and its contribution surface. It
encodes the library's central claim in a form that can fail:

> **The same run, described by any supported instrumentor, produces the same
> canonical graph.**

If that claim is false, the library has no reason to exist. So it is a test.

## 1. Layout

```
fixtures/
  conformance/
    <scenario_id>/
      scenario.md                 # what happens, described semantics-free
      dialects/
        openinference.jsonl
        otel_genai.jsonl
        langfuse.json
        ...
      expected/
        graph.json                # THE canonical graph. Exactly one of this
                                  #   or error.json — never both, never
                                  #   neither.
        error.json                # this scenario must NOT build (§4.2).
        diagnostics.json          # expected diagnostics (codes + counts)
        comparison.json           # optional: node fields, and payloads, this
                                  #   scenario has declared dialect-varying
                                  #   (§4, §4.4), set aside for the
                                  #   CROSS-DIALECT claim only. Absent =
                                  #   nothing declared.
        payloads/
          otel_genai.json         # optional: this dialect's own values for
                                  #   the payloads declared above, so the
                                  #   within-dialect claim still pins them
                                  #   (§4.4). Absent = agrees with graph.json.
        coverage.json             # optional: dialects that CANNOT render this
                                  #   scenario, each with a reason (§4.3).
                                  #   A dialect is either rendered or declared
                                  #   here. Silence is a failure.
  captured/
    <name>.jsonl
    <name>.provenance.md          # §6 — mandatory
```

One canonical graph per scenario. Not one per dialect. That asymmetry is the
whole point — and `payloads/` does not undo it. A dialect override does not
give a dialect its own graph; it names the handful of payload fields on which
the corpus has **recorded** that two dialects state different facts, so that
the one canonical graph can go on asserting everything else.

## 2. Writing `scenario.md`

Describe **structure and telemetry facts only**. No semantics — no "the agent
leaks a secret", no "an attacker injects". A scenario is a shape, not a story.

```markdown
# llm_tool_llm

An agent span containing: an LLM call that requests one tool call, a tool span
that fulfils it (joined by tool_call_id), and a second LLM call.

Nodes: 1 agent, 2 llm, 1 tool.
Edges: 3 parent (explicit), 1 call_result (explicit), 2 temporal (derived).
Payloads: all present.
Diagnostics: none.
```

That header block is the human-readable statement of what `expected/graph.json`
asserts, and reviewing it is how a reader checks the expectation is *right*
rather than merely *what the code currently does*.

## 3. Seed scenarios

Phase 1 seeds all of these. The degenerate ones are not optional — they are
where honesty is actually tested, and they are the cases every naive
implementation gets wrong.

**Structural**

| Scenario | Exercises |
|---|---|
| `single_tool_call` | the minimum viable trace |
| `llm_tool_llm` | `call_result` pairing across an LLM/tool boundary |
| `parallel_tool_calls` | **several** calls requested by one span, all paired |
| `parallel_tools` | sibling ordering and tie-breaks |
| `nested_agents` | multi-level `parent`, sub-agent containment |
| `retriever_and_embedding` | the less common node kinds |
| `span_links` | `link` edges |
| `declared_data_edge` | an `explicit` `data` edge from a dialect that emits one |

**Degenerate — the honesty cases**

| Scenario | Exercises | Must produce |
|---|---|---|
| `missing_payloads` | tool spans with no payload attributes | `Payload.absent`, never `empty` |
| `empty_payload` | a genuinely empty payload | `Payload.empty`, distinct from above |
| `redacted_payload` | source-signalled redaction | `Payload.redacted`, content untouched |
| `unpaired_tool_call` | a requested call with no fulfilling span | `unpaired_call`, **no invented edge** |
| `orphan_parent` | `parent_id` referencing an absent span | `orphan_parent`, node retained |
| `clock_skew` | `ended_at` before `started_at`; missing timestamps | `nonmonotonic_time`, `missing_timestamp` |
| `unknown_kind` | a span kind we do not map | `unknown` node **plus** diagnostic |
| `malformed_payload_json` | JSON mime, unparseable value | `payload_parse_failed`, `raw` preserved |
| `duplicate_span_ids` | two records claiming one id | hard error, not silent overwrite |
| `cyclic_parents` | a parent cycle | graph still built, diagnostic, no hang |
| `shuffled_order` | the same trace, lines reordered | byte-identical to its ordered twin |
| `tool_call_history_echo` | a call id resent as input context by a later turn | **no** `call_result` edge from the echoing span |

Every new adapter must render **all** of these, including the degenerate ones.
An adapter that only handles happy paths is not done.

## 4. The equivalence rule

The corpus makes **two** claims, and they were conflated until Phase 2 forced
them apart. Keeping them separate is what lets a dialect disagreement be
recorded instead of erased.

**Claim 1 — fidelity, within a dialect.** Every rendering reproduces its
scenario's expectation *in full*:

```
canonical(build(Dᵢ)) == expected/graph.json, as Dᵢ expects it (§4.4)
```

Nothing is erased for this claim beyond the declared node-field erasures below.
It is what catches a regression in an adapter or the builder, and it is the
claim with teeth: a payload that changes value fails here.

**Claim 2 — equivalence, across dialects.** For a scenario with dialects
D₁…Dₙ, the canonical graphs agree:

```
canonical(build(D₁)) ≡ canonical(build(D₂)) ≡ … ≡ expected/graph.json
```

where `≡` additionally sets aside the fields a scenario has **declared**
dialect-varying (§4.4). It is the library's central claim, and the reason a
declaration is a file in the corpus rather than a branch in the comparison
code.

Two scenarios in the seed corpus have no `expected/graph.json`, for two
**different** reasons, and they get two different mechanisms because they are
two different statements. Conflating them would make the corpus unable to say
which one it meant (§4.2, §4.3).

`canonical()` erases what is legitimately dialect-specific and nothing else:

- **Erased always:** `provenance` (adapter id/version, dialect note), `Node.raw`
  (the source record differs by construction), `Payload.raw` (the *encoding* of
  a payload is dialect-specific even when its parsed value is not),
  `Edge.adapter`, `meta.adapters`, `meta.source_digest`,
  `meta.spanweave_version`.
- **Erased where declared:** node `name`, and named `Payload` fields on named
  payloads (§4.4) — **only where** `expected/comparison.json` says so, so the
  erasure is a reviewable fact in the corpus. Declared erasures apply to
  **claim 2 only**; claim 1 still pins every one of them.
- **Compared:** node ids, kinds, operations, timestamps, statuses, payload
  **states, values and mime types**, usage, all edges (`src`, `dst`, `kind`,
  `warrant`, `basis`), node order, and diagnostics by code and count.

> `mime` was missing from the **Compared** list for two phases while
> `canonical()` compared it anyway — it erases only `Payload.raw`. Corrected
> here rather than in the code, because comparing it is right: a dialect that
> declares a content type is saying something a consumer acts on. It is now one
> of the fields §4.4 exists to handle.

If two dialects genuinely cannot agree on a compared field, that is a **finding
about the model**, not a reason to widen the erasure. Bring it to
`OPEN_QUESTIONS.md`, and record it under §4.4 if it is a payload.

> **Never weaken `canonical()` to make a test pass.** That inverts the corpus:
> instead of the fixtures testing the code, the code would be editing the
> fixtures. If an adapter fails equivalence, either the adapter is wrong or the
> model is — and finding out which is exactly the value the corpus provides.

### 4.1 Node ids across dialects

Node ids are compared, so dialects must agree on them. Two rules make that work:

- When a dialect carries native span ids, scenario renderings **use the same
  span id strings** across dialects. This is a fixture-authoring convention, and
  it is deliberate: it isolates the equivalence test to the *model*, not to
  id-generation trivia.
- When a dialect has no span ids, the derived id (`SPEC.md` §3.6) will differ.
  Such a scenario must say so in `scenario.md`, and `canonical()` maps ids to
  positional labels (`n0`, `n1`, …) in topological order before comparing.

### 4.2 Scenarios that must **not** build

A scenario whose expected outcome is a **refusal** carries `expected/error.json`
instead of `expected/graph.json`. `duplicate_span_ids` is the only one so far.

Almost everything in this corpus degrades into a diagnostic; where the library
must instead refuse (`SPEC.md` §3.6), the corpus has to be able to say so. A
missing `graph.json` on its own would be indistinguishable from an unfinished
fixture, which is exactly the ambiguity this file exists to remove.

```json
{
  "error": "DuplicateNodeIdError",
  "code": "duplicate_node_id"
}
```

- `error` — the exception type, by name.
- `code` — the stable error code the exception carries (`SPEC.md` §3.10).

Matched by **type and code, never by message text.** Pinning a phrase like
`"Refusing to overwrite"` would freeze wording into the corpus, and a fixture
that pins prose starts *pressuring the message to stay as written* the first
time someone tries to improve it. Matching by type alone is too weak in the
other direction: `AdapterSelectionError` covers a tie, a low confidence, an
empty registry and an adapter that raised, and a consumer must be able to tell
those apart without string-matching. The code is the machine-readable middle,
and it is the same shape as a diagnostic code for the same reason.

**Equivalence (§4):** every dialect rendering of a refusal scenario must raise
the **same** error type with the **same** code. A dialect that builds a graph
where another refuses is a finding about the model, not a fixture to relax.

### 4.3 Dialects that cannot render a scenario

Some scenarios cannot be expressed in some dialects at all — a dialect may
simply have no way to say the thing a scenario is about. Writing a rendering
anyway would mean inventing an attribute and asserting the instrumentor emits
it (`ADAPTERS.md` §1), which is worse than a gap because it passes.

> **The seed corpus's only user of this mechanism has since graduated, and the
> way it did is a warning.** `declared_data_edge` was declared unrenderable in
> OpenInference on the grounds that the dialect had no producer→consumer
> attribute. It has one, in every multi-turn trace, and the corpus had been
> carrying it in `unmapped` for a whole phase. The `coverage.json` was deleted
> and the scenario rendered (§5.1).
>
> So a `renderable: false` with a stated reason is an **invitation to check the
> reason against observed output**, not a settled fact. It records what we
> believed on the day, which is exactly why the reason is mandatory.

That is a statement about **coverage**, not about behavior, and unlike a refusal
it is **per dialect** and **temporary** — the scenario's `graph.json` arrives
with the first dialect that can render it.

```json
{
  "some_dialect": {
    "renderable": false,
    "reason": "the dialect has no attribute for <the thing this scenario is about>"
  }
}
```

**Equivalence (§4):** equivalence holds over the dialects that *can* render the
scenario. A dialect declared unrenderable here is skipped.

**Silence is a failure.** For every scenario and every supported dialect, there
must be either a rendering **or** an entry here with a reason. A missing
rendering that nobody declared fails the corpus — otherwise "we could not
express this" and "somebody forgot" look identical, and a dialect's coverage
could quietly rot away one file at a time.

### 4.4 Payloads two dialects record differently

**The finding this exists for.** `SPEC.md` §3.3 defines `Payload.value` as
*"parsed when `mime` is JSON, else `str`"* — a statement about the **parse of
`raw`**, and nothing at all about what a payload should **contain**. So two
faithful adapters, reading the source attributes their own dialects define, can
legitimately produce different `value`s for the same span. Comparing `value`
across dialects therefore asserts a property the model never promised.

That is not hypothetical. The 2.6 matched pair — one run, two instrumentors —
disagrees on every `llm` and `agent` span:

| | OpenInference | OTel GenAI |
|---|---|---|
| in | `input.value` = the request envelope: messages **plus** model, tool definitions, invocation parameters | `gen_ai.input.messages` = the conversation, normalized |
| out | `output.value` = the whole provider response, `system_fingerprint`, `usage`, `stop_reason` and all | `gen_ai.output.messages` = the assistant turn, normalized |
| mime | `input.mime_type` / `output.mime_type` | **no mime attribute exists in the dialect** |

`tool` span payloads, by contrast, agree **byte-for-byte**
(`gen_ai.tool.call.arguments` == `input.value`).

**This is not "the encoding is dialect-specific."** That argument is what
justifies erasing `Payload.raw`, and reaching for it here would be wrong on the
facts: one payload strictly *contains* the other plus more. No re-encoding
reaches the request envelope from the conversation, because the information is
not there. The disagreement is about **content**, and the model permits it
because the model never spoke about content.

**The mechanism.** A scenario declares, in `expected/comparison.json`, which
payloads dialects record differently and why:

```json
{
  "erase": ["name"],
  "dialect_varying_payloads": {
    "reason": "OpenInference records the request envelope on an LLM span; OTel GenAI records the normalized conversation. Neither is a re-encoding of the other.",
    "payloads": ["s0.inputs", "s1.inputs", "s1.outputs"]
  }
}
```

- `payloads` — `<node id>.<inputs|outputs>` selectors. Nothing else in the
  graph is declarable this way.
- `reason` — mandatory, and checked for substance, for the same reason §4.3's
  is: a declaration without a reason is a missing comparison with extra steps.

**Only `value` and `mime` are ever set aside. `state` is not, and cannot be
made so.** `absent` ≠ `empty` ≠ `redacted` is the model's central honesty
claim (`SPEC.md` §3.3); two dialects disagreeing about a payload's *state*
would be a real finding about the model, and there must be no mechanism that
can quietly absorb it. The erasable set is fixed in code, not read from the
fixture.

**Claim 1 still pins every declared field.** A dialect whose value differs from
`expected/graph.json` supplies its own in `expected/payloads/<dialect>.json`:

```json
{
  "s1.inputs": {
    "mime": null,
    "value": [{"role": "user", "parts": [{"content": "…", "type": "text"}]}]
  }
}
```

A dialect that agrees with `graph.json` supplies no file. A dialect that
differs and *forgets* the file fails claim 1 loudly — silence is not an
outcome here either. So a declaration costs the corpus **nothing** in
within-dialect regression detection: every payload of every rendering is still
pinned somewhere. What it sets aside is only the cross-dialect assertion, on
exactly the payloads named, with the reason on the record.

**A declaration is a recorded finding, not an exemption.** It says *these two
dialects record different facts here*. That is the thing a schema-freeze
decision needs to be able to read; a widened erasure would have said nothing at
all. It follows that a declaration nothing disagrees about is stale — once two
or more dialects can be built, a declared payload on which every dialect
already agrees fails the corpus.

## 5. Hand-authored fixtures

Dialect renderings in `conformance/` are **hand-authored, and that is correct**.
They are format specimens: their job is to state precisely what a dialect looks
like so the adapter can be tested against it. They make no claim about anything
having really happened.

Keep them minimal — the smallest trace that exercises the property. A fixture
that is hard to read is a fixture nobody will check.

### 5.1 Derive a rendering from observed output, never from a reading

Hand-authored does **not** mean invented. A rendering must be derived from
output you have actually seen an instrumentor produce — run it, look, write
that down — and only then trimmed.

A rendering written from your understanding of a dialect tests your
understanding. Your adapter will agree with it, every test will pass, and both
will be wrong about the world in the same way, silently and forever. There is
no test that catches this, because the fixture and the code share the error.

**This happened here, and it is why this section exists.** All four
call-bearing fixtures — `llm_tool_llm`, `shuffled_order`, `parallel_tool_calls`
and `unpaired_tool_call` — were written to an idea of OpenInference rather than
to its output. Three consequences, none visible from inside the corpus:

- They omitted the **conversation history** every real follow-up turn carries,
  so no fixture contained a call id echoed as input context. The adapter
  matched a call id anywhere on a span and emitted a second `call_result` edge
  for a span that had requested nothing — `warrant=explicit`, for a relation
  the telemetry never stated.
- They put the requester's id in a **top-level `tool_calls` key inside
  `output.value`**, a shape no observed instrumentor emits. The adapter grew a
  code path to read it. That path existed only because a fixture asked for it.
- They omitted `input.value`, which the instrumentor emits on **every** LLM
  span, so the expected graphs asserted `inputs: absent` — a statement about
  the dialect that was simply false.

The first captured trace found all three in one run, and `FIXTURES.md` §6
decided it: the captured one is right. The frozen expected graph moved.

The rule that follows, and the one to apply when trimming: **omission is fine,
misstatement is not.** A rendering may leave out keys it does not exercise. It
may not leave out a key whose absence changes what the expected graph asserts —
dropping `input.value` is not simplification, it is a claim that the
instrumentor does not send one.

`tool_call_history_echo` is the regression fixture for the specific defect;
this section is for the class.

## 6. Captured fixtures — different rules

A hand-authored fixture proves the adapter matches **our understanding** of a
dialect. Only a captured one proves it matches **the instrumentor**. Those are
different claims, and the second is the one that matters when someone points the
library at their own stack.

Therefore: **every adapter requires at least one captured trace from real
instrumentation.**

- Captured traces live in `fixtures/captured/`, never in `conformance/`.
- They are **never hand-authored or synthesized**. An autonomous agent must not
  produce one (`AGENT.md` halt point). A human runs the capture and commits it.
- Each requires a `<name>.provenance.md` recording: the instrumentor and its
  exact version, the framework/SDK and version, the model or runtime if
  relevant, the date, the command run, what was redacted before committing and
  by whom, and **what this fixture is allowed to be used to claim**.
- Redaction is a human act performed *before* commit, and it must be recorded.
  Never commit real credentials, customer data, or personal information — see
  `SECURITY.md`.

If a captured trace and a hand-authored one disagree, the **captured one is
right** and the adapter is wrong.

## 7. Worked example — `llm_tool_llm` (OpenInference)

```jsonl
{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"agent.run","start_time":1000.0,"end_time":1004.0,"status":"OK","attributes":{"openinference.span.kind":"AGENT","input.value":"Look up the order status.","input.mime_type":"text/plain"}}
{"trace_id":"t1","span_id":"s1","parent_id":"s0","name":"llm.plan","start_time":1000.2,"end_time":1001.0,"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.model_name":"demo-model","llm.finish_reason":"tool_calls","llm.token_count.prompt":42,"llm.token_count.completion":17,"input.value":"{\"messages\":[{\"role\":\"user\",\"content\":\"Look up the order status.\"}]}","input.mime_type":"application/json","llm.input_messages.0.message.role":"user","llm.input_messages.0.message.content":"Look up the order status.","llm.output_messages.0.message.role":"assistant","llm.output_messages.0.message.tool_calls.0.tool_call.id":"call_a","llm.output_messages.0.message.tool_calls.0.tool_call.function.name":"lookup","llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments":"{\"order\":\"A-1\"}","output.value":"{\"choices\":[{\"finish_reason\":\"tool_calls\",\"message\":{\"role\":\"assistant\",\"tool_calls\":[{\"id\":\"call_a\",\"function\":{\"name\":\"lookup\",\"arguments\":\"{\\\"order\\\":\\\"A-1\\\"}\"}}]}}]}","output.mime_type":"application/json"}}
{"trace_id":"t1","span_id":"s2","parent_id":"s0","name":"tool.lookup","start_time":1001.2,"end_time":1002.0,"status":"OK","attributes":{"openinference.span.kind":"TOOL","tool.name":"lookup","tool_call.id":"call_a","input.value":"{\"order\":\"A-1\"}","input.mime_type":"application/json","output.value":"{\"status\":\"shipped\"}","output.mime_type":"application/json"}}
{"trace_id":"t1","span_id":"s3","parent_id":"s0","name":"llm.answer","start_time":1002.2,"end_time":1003.0,"status":"OK","attributes":{"openinference.span.kind":"LLM","llm.model_name":"demo-model","llm.finish_reason":"stop","llm.token_count.prompt":61,"llm.token_count.completion":12,"input.value":"{\"messages\":[{\"role\":\"user\",\"content\":\"Look up the order status.\"},{\"role\":\"assistant\",\"tool_calls\":[{\"id\":\"call_a\",\"name\":\"lookup\",\"arguments\":{\"order\":\"A-1\"}}]},{\"role\":\"tool\",\"tool_call_id\":\"call_a\",\"content\":\"{\\\"status\\\":\\\"shipped\\\"}\"}]}","input.mime_type":"application/json","llm.input_messages.0.message.role":"user","llm.input_messages.0.message.content":"Look up the order status.","llm.input_messages.1.message.role":"assistant","llm.input_messages.1.message.tool_calls.0.tool_call.id":"call_a","llm.input_messages.1.message.tool_calls.0.tool_call.function.name":"lookup","llm.input_messages.2.message.role":"tool","llm.input_messages.2.message.content":"{\"status\":\"shipped\"}","llm.input_messages.2.message.tool_call_id":"call_a","llm.output_messages.0.message.role":"assistant","llm.output_messages.0.message.content":"Your order has shipped.","output.value":"{\"choices\":[{\"finish_reason\":\"stop\",\"message\":{\"role\":\"assistant\",\"content\":\"Your order has shipped.\"}}]}","output.mime_type":"application/json"}}
```

Expected canonical graph:

- **Nodes** (topological order): `s0` `agent`, `s1` `llm`, `s2` `tool`, `s3` `llm`.
- **Edges:**
  - `parent` explicit, basis `span.parent_span_id`: s0→s1, s0→s2, s0→s3
  - `call_result` explicit, basis `tool_call_id`: s1→s2
  - `data` explicit, basis `tool_call_id in tool-result message`: s2→s3
  - `temporal` derived, basis `sibling start_time ordering`: s1→s2, s2→s3
- **Payloads:** s0 inputs present / outputs absent; every LLM span reports both
  (the instrumentor emits `input.value` on every model call); s2 both present.
- **Usage:** on s1 and s3 only.
- **Diagnostics:** `unmapped_attributes` ×2, both `info` — the message-list
  keys this library does not normalize.

Note what *is* there, and what is not. The `data` edge s2→s3 exists because the
instrumentor **declared** it: s3's input carries a tool-result message whose
`tool_call_id` is the id s2 answered (§4.2.1). The `temporal` edge on the same
pair says something different and weaker, and both are kept.

What is still absent is any flow nobody stated. Nothing here compares an output
string to an input string; a consumer that wants a conclusion of that kind
draws it — and owns it.

> **This section previously said the opposite**, and it was wrong about the very
> trace it quotes: it claimed the library declined to connect s2 to s3 "because
> the telemetry did not state it". The telemetry did, in an attribute the
> adapter was discarding and this document never checked. The JSONL above is
> now generated from the fixture and asserted against it by
> `tests/test_docs.py`, because a document that quotes a fixture and drifts
> from it is a document that will eventually lie.

## 8. Fixture hygiene

- Keep line counts small; one property per scenario.
- Use stable, obviously-fake values (`A-1`, `demo-model`, `1000.0`). Never
  paste real data into a hand-authored fixture.
- Timestamps: start at `1000.0` and increment by tenths. Round numbers make
  ordering bugs visible on sight.
- Expected graphs are **generated once, then reviewed by a human, then frozen**.
  Regenerating an expected graph to match new code is how a corpus dies —
  changing one requires an explicit note in the PR saying why the *expectation*
  was wrong.
- The exception, and the only one: a **captured trace** disagreeing with a
  hand-authored fixture (§6). Then the expectation was wrong about the world
  and must move, and the diff is the record of what our reading of the dialect
  got wrong — worth writing down in the PR where someone can find it later
  without reading the code.
