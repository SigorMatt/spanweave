# OPEN_QUESTIONS.md — deferred design decisions

Questions the seed specs deliberately did **not** answer. Each is a real fork
where the right answer depends on evidence the project does not yet have —
usually "what the second dialect does" or "what a real consumer needs."

**These must be resolved deliberately in planning, not silently in code.**
Deciding one by writing an implementation is exactly the failure mode this file
prevents: the specs are the source of truth (`CLAUDE.md`, spec-first), and code
that quietly picks a side leaves the contradiction in the documents for the next
reader to trip over. Touching one is a halt point (`AGENT.md`).

For each: **(a)** the question, **(b)** why it matters, **(c)** what evidence
would settle it, **(d)** the provisional stance the seed specs take.

---

## 1. Should `unknown` nodes be promotable?

**(a)** When a dialect reports a span kind we don't map, we emit an `unknown`
node plus a diagnostic. Should there be a mechanism — an adapter hint, a
consumer override, a mapping file — to later classify it?

**(b)** `NodeKind` is a closed enum, deliberately (`SPEC.md` §3.2). But real
dialects invent kinds constantly (`guardrail`, `reranker`, `router`, `handoff`).
If every new kind requires a spec change, adapters stall behind us. If kinds are
open, cross-dialect equivalence gets much weaker and consumers can no longer
exhaustively match.

**(c)** Phase 2 and 4. Count how many kinds real dialects emit that don't map,
and whether consumers actually need them distinguished or are happy to see
`unknown` with the original string preserved in `attributes`.

**(d) Provisional:** closed enum, `unknown` is terminal, original kind string
preserved in `attributes` and in the diagnostic. Revisit at Phase 4 with counts.

---

## 2. Are individual LLM messages nodes, or payload content?

**(a)** A single LLM span carries a message list — system, user, assistant, tool
results. Are those nodes in the graph, or do they stay inside the span's
`Payload`?

**(b)** This is the single largest open question about the model's granularity,
and it is where the security-analysis use case pulls hardest away from the cost
and latency use cases. Message-level nodes make in-context provenance
expressible (which retrieved document ended up in which prompt). They also
multiply node counts by an order of magnitude, make cross-dialect equivalence
much harder (dialects disagree far more about messages than about spans), and
serve no purpose at all for cost or latency work.

**(c)** Phase 2's adversarial consumer and Phase 3's confirmatory ones, plus a
real consumer that needs in-context provenance. If the trajectory dumper can work
from payloads alone, that is strong evidence spans are the right granularity.

**(d) Provisional:** spans are nodes; messages live in `Payload.value`. A
message-level layer, if ever built, would be an **additive** projection over the
same graph — never a replacement, and never a second graph type.

**Evidence — cold review of the first captured trace.** A reviewer with no
knowledge of this project, given the trace and its graph, reported that
*"reconstructing the dialogue means re-parsing the raw JSON, which is what
normalization was supposed to spare you."*

Measured on that trace: of **17** `llm.input_messages.*` / `llm.output_messages.*`
attributes, **16 are unmapped**. The one exception is the requester's
`tool_call.id`, mapped because `call_result` pairing needs it. So the entire
dialogue — every role, every content string, every tool-call argument — reaches
a consumer only inside `Payload.value` or `raw`, and the messages are already
*flattened into dotted attributes* by the instrumentor, so a consumer that wants
them must either re-parse `output.value` or re-assemble them from the dotted
keys itself.

**A position has now been taken, in code, and it should be visible here.**
`SPEC.md` §4.2.1 emits a `data` edge from a declaration the instrumentor makes
at **message** granularity — a tool-result message saying "this input is the
result of call X" — by resolving it to the **span** that fulfilled X. That is
message-level provenance answered at span level rather than surfaced as
message-level nodes.

It is evidence *for* the provisional stance, not against it: the resolution
worked, on real telemetry, and produced an edge a consumer can audit. The
information that lived in a message reached the graph without messages
becoming nodes.

It is not a resolution, and it is deliberately not written as one. It is one
relation, in one dialect, where the id happened to make the resolution
unambiguous. A message-level fact that does **not** carry a span-resolvable id
— which document ended up in which prompt, the case §2(b) is actually about —
would not survive this treatment, and nothing here says it would. Recorded so
that whoever resolves §2 knows a precedent exists and how narrow it is.

The other evidence for this question arrived as a usability complaint rather
than a design argument — which is the form the answer is most likely to take. It does **not** settle whether messages
should be *nodes*: mapping the message list into `Node.attributes` would answer
the complaint without touching granularity at all, and that is §5's question.
Recorded here because the two are easily confused and the evidence bears on
both.

---

## 3. Should `detect()` confidence be adapter-declared or centrally computed?

**(a)** Adapters currently self-report confidence. An adapter can inflate its
score and win inputs it shouldn't. Alternative: a central scorer over
adapter-declared marker keys, so the library computes confidence uniformly.

**(b)** Adapter-declared is simple and lets an adapter use dialect-specific
knowledge no central rule could encode. It is also unenforceable, and a
mis-detected input produces a **plausible but wrong graph** — the worst failure
mode this library has, because nothing downstream can tell.

**(c)** Phase 2, when there are two adapters and detection actually has to
choose. If they conflict on any realistic input, centralize.

**(d) Provisional:** adapter-declared, with a hard error on ties or sub-0.5
confidence and `--adapter` as the escape hatch (`SPEC.md` §6.1). The hard error
is what makes the weaker mechanism survivable: ambiguity fails loudly instead of
guessing.

---

## 4. Multi-trace inputs: tolerate, split, or reject?

**(a)** A file may contain several traces. Current stance: use the most common
`trace_id`, keep foreign records as nodes, emit `multi_trace_input`. Should
there instead be a `spanweave split`, or a `Graph` per trace, or a hard error?

**(b)** Real exports are frequently multi-trace, so rejecting is hostile. But
"most common trace_id" is an arbitrary rule that silently makes some records
second-class, and a consumer may not read the diagnostic.

**(c)** Phase 2/4, from real captured exports. If multi-trace files are the norm
rather than the exception, a first-class `build_all()` returning several graphs
is probably right.

**(d) Provisional:** tolerate + diagnose, as specified. Do not build `split`
yet.

---

## 5. How much attribute normalization is too much?

**(a)** `Node.attributes` holds a "normalized, typed subset." Which keys are in
it? Only ones the model uses, or a broader normalized set (model name,
temperature, tool schema, framework version)?

**(b)** Too narrow and every consumer reaches into `raw`, re-implementing dialect
knowledge — which is precisely the duplicated work the library exists to
eliminate. Too broad and we are making judgement calls about what matters,
drifting toward semantics (`CLAUDE.md` 1) and taking on an unbounded
normalization surface.

**(c)** Phase 3. Watch what the example consumers reach into `raw` for. Anything
both consumers need is a normalization gap; anything only one needs probably
isn't.

**(d) Provisional:** narrow — only what the model itself consumes. Widen on
demonstrated need, never on speculation.

**Evidence — cold review of the first captured trace.** Three specific gaps,
from a reviewer who did not know the stance above:

- **The dialogue.** 16 of 17 message attributes are unmapped (see §2). The
  complaint was that reconstructing the conversation means re-parsing raw JSON.
- **`llm.tools.*.tool.json_schema` is dropped.** The graph can express *"a tool
  ran"* but not *"these tools were on offer"* — so an **unused affordance is
  invisible**. A consumer cannot ask which tools the model could have called and
  did not, and the answer is present in the trace.
- **`llm.system` (`"openai"`) is dropped.** Nodes keep `model` but not who
  served it. On an OpenAI-compatible endpoint those are different facts, and the
  captured trace is precisely a case where the model string and the provider do
  not imply one another.

Note what this evidence is worth. §5's stance is "widen on demonstrated need,
never on speculation", and this is demonstrated need — but from **one** reviewer
on **one** trace, which is a long way from the two-consumer test §5(c) actually
specifies. It is also the kind of need that grows without limit: each of these
is individually reasonable, and normalizing all three starts the unbounded
surface §5(b) warns about. Recorded, not acted on.

---

## 6. Does `spanweave` ever gain a rendering surface?

**(a)** A graph is far more useful when you can look at it. Should there be an
SVG/HTML/DOT output?

**(b)** Rendering requires layout, and layout requires deciding what is
important — which is semantics wearing a hat. It is also an unbounded surface
(interactivity, filtering, styling) that would dominate maintenance of a library
whose value is being small and neutral.

**(c)** Post-launch, from demand. If several consumers each build their own
viewer, a neutral DOT export may be justified; a *styled* one probably never is.

**(d) Provisional:** no rendering in core. A stable DOT export is the most that
would ever be considered, and a viewer is a separate repo consuming the frozen
schema like any other consumer (`ROADMAP.md` north star).

---

## 7. Is the ban on inferred `data` edges architecture, or territory?

**(a)** `SPEC.md` §4.2 forbids emitting a `data` edge unless the instrumentor
declared one — absolutely, with no opt-in. Should there be a
`--infer-data-edges` mode that emits value-match edges as `kind=data`,
`warrant=derived`, `basis="normalized value containment"`?

**(b)** The warrant system was built precisely so that computed relations could
be published safely: anything derived is labeled derived, consumers filter on
warrant, and nothing is presented as observed when it was inferred. By that
logic, an inferred `data` edge is **already expressible honestly**, and the
absolute prohibition is stricter than the architecture requires.

So why is it there? Because value-matching is the core analysis of the
library's first consumer, and the seed spec reserved that territory for it.
That is a product decision, and it was written up as an architectural one.
Naming it plainly is the point of this entry.

The counter-argument is not nothing: a `data` edge is the most *consequential*
edge kind — it is what downstream tools will treat as evidence — and matching
requires a threshold, a normalization rule, and an encoding policy, none of
which are opinion-free. Shipping one default set of those choices is closer to
semantics than anything else in the library (`CLAUDE.md` 1). The warrant label
tells a consumer *that* we inferred; it does not tell them whether our
threshold was right for their data.

**(c)** Phase 3 (`PREDICTIONS.md` P3), plus any real consumer that asks for it.
The decisive question is whether the matching parameters can be made fully
consumer-supplied — the library providing the traversal, the consumer providing
the predicate. If so, the neutrality objection mostly dissolves and this
becomes an ordinary operational option.

**(d) Provisional:** keep the prohibition. If P3 fires, **do not wave it
through** on the technicality that it reuses an existing `EdgeKind` and warrant
— decide it here, deliberately, as the policy question it is.

**Evidence — the premise of this entry was false. The QUESTION is still open.**

This entry, and `PREDICTIONS.md` P3, both rest on an unstated premise:
that `EdgeKind.data` is **near-vacuous in v1** because no supported dialect
declares a producer→consumer relation, so the only way to get a `data` edge
would be to infer one. `declared_data_edge` was seeded with no OpenInference
rendering on exactly that ground.

A cold review of the first captured trace showed it is false, and the library
now emits such edges (`SPEC.md` §4.2.1). On a follow-up LLM span,
`llm.input_messages.N.message.tool_call_id` with `role="tool"` carries the same
id as the tool span's `tool_call.id`. The role **is** present and distinguishes
a tool-result message from an assistant message that merely echoes
`tool_calls`; the two also differ in attribute form. The join is by **id, with
no value comparison**, so none of §4.2's objections — threshold, normalization
rule, encoding policy — has anything to apply to.

So `EdgeKind.data` is **not** near-vacuous in v1: every multi-turn OpenInference
trace declares at least one, and the corpus had been carrying the evidence in
an `unmapped` list for a phase.

What that changes here: this entry asks whether to permit *inferred* data
edges, and that question is untouched — a declared edge is not an inferred one.
What moves is the **cost** of saying no. The argument for relaxing the
prohibition was partly that `data` would otherwise be an edge kind nothing ever
populated; it is populated now, from telemetry, with a warrant and an auditable
basis. Whether that makes inference less necessary or more attractive is
exactly what still has to be decided here, deliberately.

**Deliberately not resolved.** Neither this entry nor P3 is being decided, and
`PREDICTIONS.md` is not being edited — it records what was predicted *before*
the test, and its value is entirely in its timestamps (`AGENT.md`). This note
exists so that whoever resolves either one does so knowing the premise was
challenged, by whom, and on what evidence.

---

## 8. Can one span be both a requester and a fulfiller?

**(a)** `NormalizedSpan` carries `call_ids` — several, since one model turn
routinely requests several tools — but a **single** `call_role` shared by all of
them. A span that *fulfils* its parent's call while *requesting* its own cannot
be expressed. Should the seam instead carry `(id, role)` pairs?

**(b)** The shape is not hypothetical: **agent-as-tool** is a real and
near-term pattern. A sub-agent invoked as a tool fulfils the call that invoked
it and requests calls of its own, and an instrumentor that labels both ends
would produce exactly this span. Under the current seam an adapter must choose
one role, so one of the two relations is silently unavailable — and because the
seam simply has nowhere to put it, nothing would be reported: the failure is
invisible rather than diagnosed, which is worse than the multi-id limitation
this replaced.

Against changing it now: the seam is explicitly **not** a public contract
(`DESIGN.md` §3.1), so the change stays cheap for as long as we wait, and no
dialect we have read is known to label both ends of an agent-as-tool span
today. Building for it before seeing one emitted is buying generality on an
argument rather than on evidence — which is the exact move `PREDICTIONS.md`
exists to catch.

**(c)** Phase 2, and specifically the second adapter plus the captured traces.
The question resolves the moment one real instrumentor labels both ends of a
sub-agent span. Look for it deliberately rather than waiting to trip over it.

**(d) Provisional:** `call_ids` + one `call_role` per span. If agent-as-tool
appears, the fix is `calls: tuple[CallRef, ...]` where each `CallRef` carries
its own id and role — roughly the same size as the change that introduced
`call_ids`, and confined to the seam, the adapter and one builder loop.

**Recorded during Phase 1 review**, at the same time as the `call_ids` change,
so that Phase 2 recognises this case rather than rediscovering it.

---

## 9. Is `llm.output_messages` enough to identify a call's originator?

**(a)** A requester id is taken only from what a span itself produced — in
OpenInference, `llm.output_messages.*.tool_call.id` rather than
`llm.input_messages.*` (`SPEC.md` §4.4). Is that one attribute prefix enough,
or should the adapter corroborate it with a second signal?

**(b)** The rule is currently carried by a **single** attribute prefix. If a
dialect, an instrumentor version, or a streaming path ever puts an originating
call somewhere other than the output message list — or omits the message lists
entirely and reports only payloads — the rule quietly stops distinguishing
origination from echo, and the failure looks exactly like the defect it was
written to fix: a `call_result` edge with `warrant=explicit` for a relation
nobody stated. That edge is indistinguishable downstream from a real one.

There **is** a second signal available in the trace we have.
`llm.finish_reason` was `tool_calls` on the originating span and `stop` on the
follow-up that merely echoed the id. It corroborates the output-side rule
exactly, and it is emitted by the same instrumentor on the same spans.

Against wiring it in now: it has been observed on **one** dialect from **one**
instrumentor in **one** capture. `finish_reason` is a property of a whole
response, not of an individual call, so it cannot say *which* id originated
where a span both echoes an old call and requests a new one — a shape the
output-side rule already handles correctly on its own. And a second rule that
agrees with the first on every case seen so far adds no discrimination while
adding a way to disagree later.

**(c)** Phase 2, and the second adapter in particular. If OTel GenAI (or any
further instrumentor) turns out not to separate produced from received
messages, this stops being a corroboration question and becomes the larger one
§8 gestures at: whether the dialect can distinguish these at all. Watch also
for a streaming path, where the two signals are most likely to first disagree.

**(d) Provisional:** the output-side rule alone. `llm.finish_reason` is
**recorded here as available** and deliberately not wired in — one observed
dialect is not enough to justify a second rule, and a rule adopted before it is
needed is a rule nobody knows how to test. The corpus keeps `llm.finish_reason`
in its renderings precisely so that the signal is present the day this is
reopened.

**Recorded during the first captured-trace review**, alongside the fix it
would corroborate.

**Second, independent vote.** A cold reviewer of the same trace — with no
knowledge of this file or of the pairing fix — called `llm.finish_reason` *"the
single field that distinguishes a turn that requested a tool from one that
terminated"*, and noted that it has no home in the graph. That is two votes from
two directions: ours as corroboration for the pairing rule, theirs as a fact a
consumer wants in its own right.

It changes nothing yet, and deliberately so — two observations of one dialect
from one instrumentor is still one dialect. But it moves `finish_reason` from
"a signal we noticed" to "a field someone asked for", and if a third vote
arrives it should probably be answered in §5 (normalize it into
`Node.attributes`) rather than here (wire it into the pairing rule). Those are
different fixes to different problems, and the second vote is for the first
one.
