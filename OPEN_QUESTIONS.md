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

**Evidence — (d)'s technicality was never true. The QUESTION is still open.**

Added at `TASKS.md` 3.5, Phase 3, where P3 was marked **UNRESOLVED** by a
human. **(d)** warns against waving this through *"on the technicality that it
reuses an existing `EdgeKind` and warrant"*. There is no such technicality to
wave anything through on, and there never was:

- `Edge(kind=data, warrant=derived)` **raises at construction**.
  `spanweave/model.py`'s `ALLOWED_WARRANTS` has refused the combination since
  the first implementation commit (`d8e2c37`), and the error names §4.1.
- **§4.1 already answers the classification question**, in the seed commit
  (`c266c9e`) that also created this entry and `PREDICTIONS.md` P3: *"If a rule
  is ever added that infers a relation of an explicit-only kind, it does not
  become that kind — it becomes a new kind, through a spec change."* A new
  `EdgeKind` is a shape change and an `AGENT.md` halt point.

So the choice this entry frames is not *policy versus flag*. It is **keep the
prohibition** versus **change `SPEC.md` §4.1 and the model** — which is the
same deliberate decision (d) asks for, arrived at without needing (d)'s
guardrail, and at a higher stated price than P3 assumed.

One further data point, from the only consumer this repo has that reads `data`
edges at all: **it does not filter on warrant.** `examples/trajectory_dump`
renders every `data` edge as `(declared)`, a string literal, and printed that
over a `derived` edge forced past the validator
(`tests/test_prediction_evidence.py`). That bears on **(b)**'s argument that
the warrant label makes inference safe — the label only helps if consumers
read it. Scope, and it is doing real work here: the assumption is currently
free, since no derived `data` edge can exist; the warrant *is* in the
serialized graph, so the consumer could filter and chose not to; and it is one
consumer, written by this repo.

**Deliberately not resolved, again.** This is evidence about what saying yes
would *cost* and about **(b)**'s premise. It decides nothing. `PREDICTIONS.md`
was not edited by the agent, and §7 remains an `AGENT.md` halt point.

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

---

## 10. C2: Should a timestamp keep the digits the record wrote?

**(a)** `Node.started_at` and `Node.ended_at` are `float | None`, and both
adapters reach them through `_as_time`, which ends in `float(value)`. At
epoch-nanosecond magnitude float64 cannot hold the digits an exporter wrote:
the gap between adjacent representable values is **256 ns**, so two spans
100 ns apart become one number. Should the model keep a wider numeric type —
the reported integer, an integer count of nanoseconds, or `Decimal` — or stay
on `float` and say so out loud?

**(b) The failure, demonstrated.** `tests/audit/probe2.py` case G builds three
ns-encoded spans, two of them 100 ns apart:

    ns precision: s1.start=1.7000000001e+18 s2.start=1.7000000001e+18
    equal=True temporal=[('s1', 's2')] duration_s1=100000000.0
    bases: [('s1', 's2', 'sibling start_time ordering (tied, broken by node_id)')]

The record wrote `1700000000100000000` and `1700000000100000100`. The first is
exactly representable; the second is off by **-100 ns**. The two collapse, and
the temporal edge between them is emitted as **tied**.

The precision floor is a property of the *magnitude*, not of the nanosecond
encoding. A 1000 ns window at 1.7e18 ns holds **4** distinct float64 values; a
1 µs window at 1.7e9 s holds **4** as well, because the ULP there is
**238.42 ns**. A seconds field carrying nanosecond digits sits on the same
floor as a nanosecond field.

The digits are not lost in the reader. `json.loads` returns a Python `int`,
which is arbitrary-precision, and `raw.source` still holds
`1700000000100000100` and serializes it verbatim. They are lost at
`float(value)` inside the adapter, and nowhere else.

**What is observably wrong — precisely.** Less than the size of the number
suggests, and worth stating exactly, because it changes the urgency:

- **Not a determinism bug.** Same bytes → same graph; float comparison is
  deterministic even when it is lossy; shuffled input is unaffected. Invariant
  4 holds, on every input, today.
- **Not a losslessness bug.** The exact literal survives in `raw.source` and in
  the serialized output. Invariant 2 holds. A consumer *can* recover the
  digits — by re-parsing the source record, which is the complaint §2 of this
  file already records against the library.
- **What breaks** is `SPEC.md` §3.1's promise for the *normalized* field —
  *"what the telemetry put in the field is what the node carries"* — and the
  **premise** of one edge. Per §4.3 a tie-broken `temporal` edge asserts that
  neither sibling started first; here one demonstrably did. The edge is
  deterministic, correctly warranted `derived`, and honestly labelled a
  decision rather than an observation — and it is a decision taken on a fact
  the library got wrong. **Deterministic but wrong-ordered** is the honest
  summary.
- One further casualty, from C1: `timestamp_unit_suspect` prints *"Every value
  is kept exactly as reported and nothing is rescaled"* while showing
  `1.7000000001e+18` for a record that wrote `...100000100`. Its `source` field
  carries the same lossy value. The diagnostic's own sentence is falsified in
  exactly the case the diagnostic exists to report.

**How much of this bites today: none of it.** Across the 17 captured trace
files (`fixtures/captured/`, `capture/_scratch/fleet/`): **154** timestamp
values, **0** above 1e11, **0** whose shortest float repr differs from the
literal in the file, **0** pairs of distinct literals collapsing onto one
float. **41** sibling pairs, minimum gap **81 µs** — 317x the ULP at that
magnitude. Only one fixture, `timestamp_units`, carries a value over the line,
and it was written by C1 to exercise the ceiling.

**What would trigger it:** any exporter writing epoch nanoseconds or
milliseconds as an integer. That is precisely `startTimeUnixNano` in OTLP JSON,
and batch F1 sits behind this entry in `WORKPLAN.md` for that reason. It is not
a hypothetical input; it is the next input.

**The options, and what each one moves.** The stored expectations at stake:
**22** expected graphs holding **108** timestamp slots (**106** non-null,
**23** distinct values). Every seconds fixture writes its timestamps as
fractional literals (`1000.0`, `1000.2`), which no option below changes; only
`timestamp_units` writes integers, and it holds **5** non-null values.

1. **Keep `float`, diagnose the loss.** A new diagnostic when a reported value
   exceeds 2^53 (9.007e15), above which consecutive integers are no longer
   distinguishable, or more sharply when the reported value is not exactly
   representable. C1's "kept exactly as reported" sentence has to go either
   way. **Moves: 0 stored expectations.** Free now and free later — nothing
   about the schema changes. It does not fix the ordering; it documents it.

2. **Keep the reported integer. Never rescale.** `started_at: int | float |
   None`; `_as_time` returns the `int` when the literal (quoted or not) is an
   integer literal, and `float` only when it carries a fraction or an exponent.
   This is "integer nanoseconds internally" in *effect* for ns-encoded input
   without being a unit conversion: the library still does not know the unit
   and still never rescales, so §3.1's central sentence stays true rather than
   being amended. **Moves: 5 timestamp values in one expected graph, one
   sentence in `timestamp_units/scenario.md` that quotes `1.7e+18`, two type
   lines in `tests/serialized_shape.json`, and §3.1's field table.** Free now.
   After the Phase 4 freeze it is not breaking in the JSON schema — `int` and
   `float` are both `number` — but it changes the *literal* emitted for
   integer-encoded input, which a consumer comparing serialized bytes would
   see; do it before the freeze and there is nothing to migrate.

3. **Integer nanoseconds with a unit assumed, seconds restored in
   serialization** (the form `WORKPLAN.md` proposes). Requires the library to
   know the unit of the field, which is exactly what §3.1 refuses to know and
   what C1's whole diagnostic exists because we cannot know. Multiplying a
   reported 1.7e18 by 1e9 yields a nanosecond count in the year 5e10; and
   multiplying a fractional-seconds float by 1e9 reintroduces the same rounding
   the option was meant to remove, because the digits are already gone by then.
   **Moves: all 106 stored values**, every scenario prose line that quotes one,
   and §3.1 in full. Recommended against, in the plan's own terms.

4. **`Decimal`, i.e. keep the literal exactly.** The only option that also
   fixes fractional seconds. Its cost is not in the model, it is in the
   **reader**: by the time an adapter sees a bare JSON number, `json.loads` has
   produced a float, so exactness requires `json.loads(..., parse_float=
   Decimal)` in `read.py` — which retypes every number in every payload and in
   every `raw.source`, not just timestamps. `json.dumps` refuses `Decimal`, so
   `canonical_bytes`, the digest and the serializer all need an encoder;
   `Decimal("0.1") == 0.1` is `False`, so consumer comparisons quietly change
   meaning; and a public model field gains a type every consumer must handle.
   **Moves: the same 5 values as option 2, plus the reader, the digest and the
   serializer.** Free now in schema terms and very expensive in blast radius.

**Round-tripping.** A value read must serialize back to something a consumer
can compare against its own input. Option 1: the float round-trips to itself,
but not to the input literal — `1.7000000001e+18` against `1700000000100000100`
is both a different spelling and a different number, and recovering the
original means re-reading `raw.source`. Option 2: integer in, identical integer
out; fractional seconds are unaffected, since Python's repr is
shortest-round-trip and 0 of the 154 corpus literals differ from it. Option 3:
nothing round-trips — every value is rescaled twice and comes back out as a
float. Option 4: exact in both directions, at the price of a custom encoder.

**C1's two handoffs, answered.**

- **The ceiling.** `TIMESTAMP_UNIT_CEILING = 1e11` compares against the value
  as the model holds it. Under option 2 the check needs no logic change:
  Python compares `int` and `float` exactly rather than coercing, so an integer
  timestamp is tested correctly as written. Two consequences follow anyway —
  the constant should become `100_000_000_000` so the message stops printing
  `100000000000.0`, and the diagnostic's `source` then carries the exact
  reported value, which is what makes its "kept exactly as reported" sentence
  true instead of false. Under option 3 the constant changes meaning entirely
  (the field is no longer seconds); under option 4 the comparison stays exact
  but a `Decimal` in `source` is not JSON-serializable.
- **The string/number asymmetry** — that a quoted timestamp can preserve every
  digit where a bare one cannot, because `json.loads` got there first. It is
  real, and it is **confined to option 4**. For integers there is no asymmetry
  to resolve: `json.loads` already yields an exact `int`, so both renderings
  arrive intact and only `float()` discards them. Options 1 and 2 treat the two
  renderings identically, which is what §3.1 already promises — *"the two
  renderings of one trace produce the same graph"* — and option 2 keeps that
  promise at full precision rather than at a shared loss. Only for a
  **fractional** value does the quoted form carry digits the bare form has
  already lost, and only an exact-decimal representation could spend them.

**(c) What would settle it — and the smallest experiment that falsifies the
recommendation below.** Find one real exporter emitting a timestamp finer than
238 ns that is *not* an integer: scan incoming captured traces and OTLP JSON
exports for a literal whose shortest float repr differs from the literal, or
for two sibling spans whose literals differ while their floats do not. One hit
means option 2 is insufficient and option 4's blast radius is bought
honestly. The corpus today: 154 values, 0 hits; 41 sibling pairs, 0 under
256 ns. The same scan is one loop over `start_time`/`end_time` literals and can
run against every trace the project captures from here on.

**(d) Provisional — recommendation: option 2.** Keep the reported integer;
never rescale; leave fractional seconds on `float`. It fixes the case that
actually bites (integer ms/ns encodings, which is every OTLP JSON export and so
every input F1 will bring), it fixes it *without* the library forming an
opinion about the unit, it closes the string/number asymmetry by construction,
and it costs 5 stored values in one fixture while the schema is still unfrozen.
Option 1 is the fallback if the answer is that nanosecond-distinct siblings are
not worth a model change — but it should then be taken deliberately, and C1's
false sentence has to be fixed under it too. Option 3 is recommended against
for the reason above: it buys precision by asserting a unit the library has
just finished saying it cannot know.

**Decision: option 2**, logged in `WORKPLAN.md` §3 (2026-09-10) and implemented
by batch C3. `started_at`/`ended_at` are `int | float | None`, an integer
literal — quoted or bare — is carried as an `int`, the ceiling constant is
`100_000_000_000`, and C1's *"kept exactly as reported"* sentence is true by
construction rather than by assertion. `tests/audit/probe2.py` case G is now a
regression test (`tests/test_adapters.py`, *An integer timestamp keeps its
digits*). What (a) and (b) describe is the state **before** C3.

(c) stays open, and is the reason option 4 is recorded rather than dismissed:
one real exporter emitting a *fractional* timestamp finer than 238 ns would
show that option 2 is insufficient. The scan is over incoming captures, not
over what is already committed.

## 11. D1: Should a re-declared receipt look different from a first one?

**(a)** A chat protocol resends the whole conversation on every turn, so a
tool-result message that §4.2.1 reads as a declaration is re-sent by every
later turn as well. The builder emits one `data` edge per declaration, so an
`n`-turn agent loop produces `n(n-1)/2` `data` edges where `n-1` of them are
first receipts and the rest are the same declaration repeated. Should the
graph distinguish the two — by `basis`, by a build flag that omits the
repeats, or both?

**(b) The mechanism, and the curve.** `_data_edges` in `spanweave/build.py`
walks `span.received_call_ids` and joins each id to the spans that fulfilled
it. Both adapters fill `received_call_ids` from the span's *input* message
list (`_received_results`), which is the request the model was sent — and a
conversational request contains the entire history. Turn `i` therefore
declares receipt of calls `c₀…c₍ᵢ₋₁₎`, not just `c₍ᵢ₋₁₎`, and the number of
declarations in the file is `Σi = n(n-1)/2`.

Measured on `tests/audit/probe2.py` case B's shape (OpenInference, one agent
root, `n` llm→tool turns, full history echo), rebuilt for this memo:

| turns | input | nodes | `data` | all edges | build | serialized |
|---|---|---|---|---|---|---|
| 25 | 47 KB | 51 | 300 | 424 | 0.01 s | 0.18 MB |
| 50 | 155 KB | 101 | 1,225 | 1,474 | 0.02 s | 0.59 MB |
| 100 | 544 KB | 201 | 4,950 | 5,449 | 0.06 s | 2.16 MB |
| 200 | 2.12 MB | 401 | 19,900 | 20,899 | 0.22 s | 8.28 MB |
| 400 | 8.30 MB | 801 | **79,800** | 81,799 | 0.99 s | 32.48 MB |
| 800 | 32.91 MB | 1,601 | 319,600 | 323,599 | 4.90 s | 128.77 MB |

The audit's single data point reproduces exactly: 400 turns → 79,800, which is
`400·399/2`. Max in-degree at 400 turns is 399, on the last llm span.

**The quadratic is the telemetry's, not the builder's.** The edge count equals
the declaration count *exactly* — 79,800 tool-result messages in, 79,800 edges
out, one edge per declaration, no fan-out. The builder is O(1) per declaration;
the input file is already quadratic (47 KB → 32.91 MB across the same range) for
the same reason the edge set is. This is unlike `temporal`, where §4.3 exists
because the *rule* could have been quadratic over a linear input. There is no
analogous rule to narrow here: narrowing means dropping declarations.

**Is any of it wrong? No — every one of the 79,800 is true.** Under §4.2.1 an
edge asserts that the output of the span which fulfilled call X became an input
to the span that received the message. Turn 300's request really does contain
the results of calls `c₀…c₂₉₈`; the instrumentor really did state so, about
that span, in that span's own record; the join is by id and compares nothing.
Every edge is `explicit`, correctly warranted, and individually defensible. So
this entry is **not** about wrongness. It is about **legibility and volume**,
and that changes which option is right: nothing here licenses removing an edge
on the grounds that it is unwarranted, because none of them is.

What a consumer actually experiences is a *question* it can no longer ask.
"What fed this span" is answered correctly and uselessly — 399 producers, all
of them real. "Which tool output did this turn act on" has no expression at
all, because the graph does not say which of the 399 arrived first. The only
consumer in this repo that reads `data` edges, `examples/trajectory_dump`,
carries a per-step `feeds` tuple; on the 400-turn trace the last step's `feeds`
holds 399 ids and the render is unreadable.

**Where the bytes actually are, at 400 turns.** Serialized output splits:
`diagnostics` **13.36 MB**, `edges` **11.95 MB** (of which `data` edges are
11.69 MB, 142 B each), `nodes` **8.71 MB**. The largest quadratic term is not
the edges — it is 400 `unmapped_attributes` diagnostics naming the echoed
`llm.input_messages.N.message.role` keys, which `_received_results` does not
consume. The nodes are quadratic too, because invariant 2 keeps every record
verbatim in `raw.source`. **Any** `data_echo` mode leaves both untouched.

**(c) What each option costs.**

1. **Option (a) — two builder-owned `basis` strings, every edge kept.**
   No edge-set change, so no graph loses a relation and invariant 2 is not in
   play at all. A consumer filters `basis` to get the `n-1` first receipts
   (1.0% of the edges at 200 turns; 0.5% at 400) or keeps everything, and the
   library decides nothing on its behalf. This is exactly §4.3's precedent:
   one edge kind, two bases, because *"this one started first"* and *"we put
   these in an order"* are different claims. It buys **no** byte reduction.

2. **Option (b) — a `data_echo="all"|"first"` build flag.**
   `first` mode omits `n(n-1)/2 − (n-1)` edges the telemetry declared. Against
   invariant 2 — *nothing is ever silently dropped* — the operative word is
   *silently*, and the flag is not automatically incompatible: an omission
   that is announced is a reportable outcome, not a vanishing. But it is not
   honest **as written**. To be honest it needs, at minimum:
   - a diagnostic (one per graph, in A4's shape — there is no single node to
     hang it on) naming the code, the mode, and the **count** omitted, so a
     graph on disk cannot be read as complete;
   - a `Meta` field recording the mode, because `Meta` is what a consumer
     reads to know what produced the graph, and a graph that has been
     narrowed by a flag is a different artifact from one that has not;
   - a clause in §5.1, whose guarantee is *same input bytes + same adapter
     version + same `spanweave` version → the same graph*. A build flag is a
     fourth term in that sentence and it is currently unstated. **`--no-temporal`
     is not the precedent it looks like**: `temporal` is `derived`-only, so
     omitting it removes only what the library computed and can recompute.
     `data` is `explicit`-only. Omitting it removes what the telemetry said,
     and that has never happened in this library.

   Its payoff is a **34.7%** smaller file at 400 turns (32.48 MB → ~21.21 MB)
   — a constant factor on a curve it does not bend. The remaining 21 MB is
   still O(turns²), because losslessness has already committed the library to
   storing the echo verbatim. Refusing to *index* what we are required to
   *store* is the weakest possible trade.

3. **Option (c) — both.** (a) is a precondition for (b) being expressible at
   all: without a basis distinction, "which edges did `first` mode omit" has
   no answer in the vocabulary of the graph. If (b) is ever wanted, it is
   additive on top of (a) and can be decided then, on volume evidence that
   does not exist today.

**(d) Option (a)'s determination: what "first" means, and whether it is
order-independent.**

For a call id X with at least one fulfiller, collect the spans that declared
receipt of X. They are a **set**, so any function of that set is
order-independent by construction; the ranking is by `(started_at, node_id)`,
the same total order §5.2 already uses for node position and §4.3 for sibling
temporal edges. Verified empirically: a 200-turn build from shuffled input is
byte-identical to the ordered one (modulo `source_digest`, which fingerprints
the bytes and is *meant* to move). Invariant 4 holds.

It is not free of judgement, and the naming has to say so:

- **A tie is a decision, not an observation.** Two receiving spans reporting
  the same `started_at` leave the earliest decided by `node_id`. §4.3 already
  ruled that such an edge must carry a *different* basis rather than pass as
  an observation. So the row's "two strings" is two only if the library is
  willing to leave a tie-broken *earliest* unmarked, which §4.3 has already
  decided it is not. Three is the honest count. §10 (C2) sharpens this: at
  epoch-ns magnitude float64 manufactures ties between spans the telemetry
  distinguished, so the tie basis is not a corner case there — it is the
  common case until C2 is decided.
- **Untimed spans.** A span with no `started_at` has no place in the order.
  Sorting it as `+inf` (§5.2's existing convention) means it is never the
  earliest unless nothing is timed, which is the honest default; it already
  draws `missing_timestamp`.
- **The word matters (invariant 1).** "Echo" and "re-declaration" name a
  *cause* — a protocol resending history — that the builder cannot see. All
  it determines is *not the earliest declaring span*. A genuine fan-out, where
  two spans each consume the same tool result once, produces the identical
  shape and is not an echo of anything. The basis must describe the
  determination, not the story. Proposed, in §4.3's parenthetical form:

  | Situation | `basis` |
  |---|---|
  | earliest span declaring receipt of this call | `tool_call_id in tool-result message` |
  | earliest, decided by `node_id` on a `started_at` tie | `tool_call_id in tool-result message (earliest tied, broken by node_id)` |
  | any later span declaring receipt of the same call | `tool_call_id in tool-result message (not the earliest receiving span)` |

  Keeping the **existing** string for the earliest case is deliberate and it
  is what makes the change free in the corpus — see below.

**How much of the corpus this touches: 4 expectations, and 0 of them change
under the proposal.** Counted before proposing anything, per `FIXTURES.md` §4.
Of 22 conformance scenarios, **4** have a `data` edge in
`expected/graph.json`, **one edge each**, all with basis
`tool_call_id in tool-result message`:

- `declared_data_edge` (s1→s2), `llm_tool_llm` (s2→s3),
  `shuffled_order` (s2→s3), `tool_call_history_echo` (s2→s3).

**Every one is a first receipt. Not one scenario in the corpus carries a
re-declaration edge**, and neither does any captured trace: across the 15
captured files that produce `data` edges (`fixtures/captured/`,
`capture/_scratch/fleet/`) there are **24** `data` edges, every call id
received by exactly one span, **0** re-declarations and **0** ties. Every
capture is a single tool round, so the shape this memo is about has never been
observed in this repo's own material — only constructed. Under the table above
all 4 expectations keep their current basis byte-for-byte, and D2's fixture
work is *additive*: one new degenerate scenario (a two-turn loop where turn 3
re-declares turn 1's result) in both dialects. Note also that
`tool_call_history_echo` is about the **request** echo and the `call_result`
rule (§4.4); the receipt echo is a different property and wants its own
scenario, by the same "when this one fails, the thing that broke has a name"
argument that scenario was created under.

**Recommendation: option (a), alone, with no flag.** The reasoning is the
finding in **(b)**: nothing here is wrong. Every edge is a relation the
telemetry stated about itself, and the library's entire position is that it
transcribes those and labels how. Removing true edges to save a third of the
bytes on a curve that stays quadratic regardless is a bad trade twice over —
it spends the invariant that makes the library depend-able and does not fix
the problem. (a) fixes the part that is actually broken, which is that the
graph cannot express a distinction its consumers need, and it fixes it in the
vocabulary the library already has (`basis`, §4.3's precedent, builder-owned
per `TASKS.md` I1), at a cost of **0** moved expectations.

**If a flag is added anyway, the default is `all`.** A default of `first`
would mean the out-of-the-box artifact silently omits declared relations,
which is the failure mode invariant 2 names.

**Two things D2 must carry that this memo cannot.** `DESIGN.md` §6 says the
build has *"no quadratic edge construction"*; that is true per declaration and
false per turn, and the sentence needs the qualifier. And the 13.36 MB of
`unmapped_attributes` diagnostics is a larger volume problem than the edges —
`_received_results` consumes the `tool_call_id` key but not the sibling
`...message.role` key it read to decide. Neither is in D1's scope; both are
findings, not decisions.

**Draft `SPEC.md` §4.2 text** — for D2 to land if (a) is taken, as a new
paragraph at the end of §4.2.1, immediately before *"A stated gap"*:

> **A declaration repeated is still a declaration.** Conversational protocols
> resend the whole history on every turn, so the same tool-result message
> reappears in the request of every later span. Each occurrence is a
> declaration made by the span that carries it, about its own input, and it is
> true: the result did reach that span. Every one of them is transcribed, and
> `n` such turns produce `n(n-1)/2` `data` edges — the input carries that many
> declarations, and suppressing a relation the telemetry states plainly is the
> failure this section exists to prevent.
>
> What the graph adds is which occurrence came first. For each call id, the
> spans declaring receipt are ranked by `(started_at, node_id)` — the order
> §5.2 already defines — and the basis records the rank:
>
> | Situation | `basis` |
> |---|---|
> | earliest span declaring receipt of this call | `tool_call_id in tool-result message` |
> | earliest, decided by `node_id` on a `started_at` tie | `tool_call_id in tool-result message (earliest tied, broken by node_id)` |
> | any later span declaring receipt of the same call | `tool_call_id in tool-result message (not the earliest receiving span)` |
>
> A span with no `started_at` sorts last and is never the earliest unless no
> receiving span is timed. The ranking is a function of a *set* of spans, so
> input order cannot affect it (§5.2).
>
> The third basis says **only** that an earlier span declared the same
> receipt. It does not say the later declaration is an artifact of a protocol
> resending history, because the library cannot see that: two spans genuinely
> consuming one result produce the identical shape. As with §4.3's tie-break,
> the warrant says the relation was stated and the basis says what was
> determined about it — a consumer that does not care matches on `kind` and
> ignores both.

**(e) The smallest experiment that would falsify the recommendation.** Capture
one trace with **≥5** tool-calling turns from a real framework — the corpus has
none, which is why this shape has only ever been constructed — and run
`examples/trajectory_dump` over it twice: once on every `data` edge, once
filtered to the earliest-receipt basis. If the filtered render answers "which
tool output did this turn act on" and the consumer's complaint is gone, (a) is
sufficient and (b) is unbought generality. If instead the reported failure is
that the graph could not be **loaded, held, or transmitted** at all, then
volume is the binding constraint, (a) does not touch it, and (b) is bought
honestly — at which point it still needs the diagnostic, the `Meta` field and
the §5.1 clause listed above. One capture settles it; the same capture is D2's
fixture material either way.

**Decision:**

*Not taken.* This entry is a `WORKPLAN.md` D1 halt; no code changed with it,
and `tests/audit/probe2.py` case B stays in the probe until D2 converts it.
Record the decision in `WORKPLAN.md` §3.

---

## 12. E1: Should dialect dispatch be per file, or per record?

**(a)** `spanweave build` picks **one** adapter for the whole input (`SPEC.md`
§6.1): `detect()` runs on the first 50 records, the highest score wins, and
every record is then parsed by that adapter. A trace whose records come from
two instrumentors has no correct answer under that rule. Should classification
move to the record — each adapter parsing only the records it claims — and if
so, what becomes of a record no adapter claims, and of one two adapters claim?

**(b) The failure, demonstrated.** A mixed trace was built from this repo's own
material: `llm_tool_llm`'s OpenInference rendering supplies the `agent` (s0)
and `tool` (s2) spans, its OTel GenAI rendering supplies the two `chat` spans
(s1, s3). Nothing was hand-written; the four records are verbatim from
`fixtures/conformance/llm_tool_llm/dialects/`. This is the shape `WORKPLAN.md`
E3 names, and it is the shape a framework instrumentor plus an SDK
instrumentor produce (see **(c)**).

Under **auto** detection, today's library refuses:

> `spanweave build: this input is ambiguous: openinference, otel_genai are`
> `equally confident (0.90). Confidence declared by each adapter:`
> `openinference 0.90, otel_genai 0.90. Name one explicitly with --adapter;`
> `guessing between them would produce a plausible graph from possibly the`
> `wrong dialect.`

That refusal is correct and it is the *good* outcome. The bad outcome is the
escape hatch the message recommends. Both forced builds **succeed**, exit 0,
and write a graph:

| | canonical `llm_tool_llm` | `--adapter openinference` | `--adapter otel_genai` |
|---|---|---|---|
| nodes | 4 | 4 | 4 |
| node kinds correct | 4 | 2 (s1, s3 → `unknown`) | 2 (s0, s2 → `unknown`) |
| edges | 7 | 5 | 5 |
| `parent` | 3 | 3 | 3 |
| `temporal` | 2 | 2 | 2 |
| `call_result` | **1** (s1→s2) | **0** | **0** |
| `data` | **1** (s2→s3) | **0** | **0** |
| `usage` present | s1, s3 | none | s1, s3 |
| payloads `present` | 7 of 8 | 3 of 8 | 4 of 8 |

**The audit's claim is right and undercounts.** "Loses the `call_result`
pairing" is true — the s1→s2 edge is gone under both forced adapters — but the
`data` edge s2→s3 goes with it, for the same reason: `call_result` needs the
requester id from s1 (`gen_ai.output.messages`) *and* the fulfiller id from s2
(`tool_call.id`), and `data` needs s3's `tool_call_response` part *and* s2 as
the resolved producer. Every relation that **joins the two dialects** is lost;
every relation that lives inside one record (`parent`) survives. Two of seven
edges, and both of the `explicit` ones the library exists to recover.

**The sharper harm is not the missing edges — it is `Payload.state`.** Under
`--adapter otel_genai` the `agent` span reports `inputs.state = absent`. The
record emitted `input.value`. `SPEC.md` §3.3 and `DESIGN.md` §5 make `absent`
mean *we were not told*, and call collapsing it the most common way a telemetry
tool becomes quietly dishonest. Here the library states it about a span it
**was** told about, in a dialect it can read, that is registered and installed.
Nothing else in this codebase produces a false `absent`.

**The library does not lie about the rest of it,** and that is worth recording
because it bounds the severity. Each forced build emits `unknown_span_kind`
twice, names every foreign attribute in `unmapped_attributes`, keeps every
record verbatim in `raw`, and reports the broken join honestly from its own
side: `unpaired_result` ("call 'call_a' was fulfilled but no span in this input
requests it") under `openinference`, `unpaired_call` ("requested and no span in
this input fulfils it") under `otel_genai`. Invariant 2 holds. What fails is
§6.1's own standard — *an ambiguous input never silently produces a plausible
graph from the wrong adapter* — because a consumer reading `nodes` and `edges`
and not `diagnostics` sees a complete-looking four-node agent trace with two
`unknown` spans and no tool call.

**Per-record dispatch recovers all of it.** A prototype that classifies each
record by the adapters' existing markers, parses each subset with its own
adapter, and hands the merged spans to today's unmodified `build_graph`
produces:

```
classification: {'openinference': ['s0', 's2'], 'otel_genai': ['s1', 's3']}
unclaimed: []   doubly-claimed: []
  edge call_result explicit s1 -> s2 | tool_call_id
  edge data        explicit s2 -> s3 | tool_call_id in tool-result message
  edge parent      explicit s0 -> s1 | span.parent_span_id
  edge parent      explicit s0 -> s2 | span.parent_span_id
  edge parent      explicit s0 -> s3 | span.parent_span_id
  edge temporal    derived  s1 -> s2 | sibling start_time ordering
  edge temporal    derived  s2 -> s3 | sibling start_time ordering
  diagnostics: unmapped_attributes ×2
MIXED canonical == llm_tool_llm expected (modulo declared payloads): True
```

Seven edges, both joins, two diagnostics — the canonical graph, exactly. All
**24** permutations of the four input records produce one identical document
(modulo `source_digest`, which fingerprints the bytes and is meant to move).
The builder was not modified for this: it already accepts a span list from any
source.

**(c) Is a mixed trace real? Constructible, structurally motivated, anticipated
in this repo's own harness — and not observed.** Said plainly, because G3 will
ask whether E is a freeze precondition and the answer turns on this.

What the corpus shows, scanned end to end (57 `*.jsonl` files, 177 records):

- **0 files** carry both markers. 37 are `openinference`-only, 20 are
  `otel_genai`-only.
- **0 records** carry both markers. **0 records** carry neither.

So the shape has never been captured here. What makes it more than a thought
experiment is three things:

1. **Both instrumentors write into one OTel SDK.** The two captured provenance
   files record `opentelemetry-sdk 1.44.0` under both backends. Installing
   `openinference-instrumentation-langchain` (framework spans: `AGENT`,
   `CHAIN`, `TOOL`) beside `opentelemetry-instrumentation-genai-openai` (SDK
   spans: `chat`) puts both dialects on one tracer provider and into one
   export. Nothing coordinates them, and `opentelemetry-instrument` loads every
   installed instrumentation entry point by design.
2. **The reason to install both is the reason the mixing hurts.** The GenAI SDK
   instrumentor cannot see an agent or a tool execution — those are not SDK
   calls. The framework instrumentor is what emits them. A stack that wants
   both layers instrumented is a stack that gets both dialects.
3. **This repo already had to steer around it.** `capture/backends.py`, on the
   spans the harness emits itself:

   > *Which means they have to speak the SAME dialect as the instrumentor that
   > produced the rest of the file. Emitting OpenInference keys beside GenAI
   > ones would produce a mixed-dialect trace that no adapter honestly reads:
   > detection would see both, one adapter would win, and whichever lost would
   > take its spans' meaning with it.*

   That comment predates the audit and describes finding #1 exactly. The
   harness avoids the shape **by hand**, because the harness controls both
   halves. A real deployment controls neither.

The honest verdict: *not observed, and cheap to observe* — see **(j)**. Point 3
is the strongest evidence available short of a capture, and it is first-party
and unprompted, but it is a prediction made by this project about the world,
which is not the same as the world.

**(d) Per-record classification, and whether the adapter API must change.**

**The markers already exist and are disjoint.** `openinference.` and `gen_ai.`
are the two `MARKER_PREFIX` constants; each adapter's `detect()` is already a
per-record scan that returns `0.9` if **any** record in its sample carries its
prefix in `attributes`, and `0.0` otherwise. That makes `detect([record])` a
per-record classifier with no new method: *this adapter claims this record* iff
`detect([record]) >= MINIMUM_CONFIDENCE`. Checked against a direct marker scan
over all **177** corpus records: **0 disagreements**.

- **Total.** Every branch of both `detect()` bodies is an `isinstance` guard
  with a `0.0` fall-through, and there is deliberately no blanket `except`
  (a raising adapter still reaches `adapter_detect_failed`, which names it).
  So every record gets a verdict from every adapter.
- **Order-independent.** `detect([record])` sees one record and no context, so
  a record's classification cannot depend on where it sat. The 24-permutation
  result in **(b)** is the end-to-end confirmation.
- **Registration-order-independent.** `AdapterRegistry.registered()` already
  sorts by id, and the recommendation below never lets registration order break
  a tie (it refuses instead).

**No new adapter API is needed. One sentence of `ADAPTERS.md` contract is**
— so the row's hope holds for code and not quite for documents. `ADAPTERS.md`
§2 says `detect()` is "called with up to the first 50 records" and that it must
key on distinctive marker keys. Nothing there promises that a one-record sample
is meaningful, and an adapter could legally score `0.9` only when it sees three
matching records. Both shipped adapters are record-decomposable; the contract
does not require it. E2 should add one paragraph making the requirement
explicit — *`detect()` must be decomposable over records: a sample scores at or
above `MINIMUM_CONFIDENCE` iff at least one record in it does alone* — plus a
checklist line. That is a contract addition, not an API addition: no adapter
gains a method, and neither shipped adapter changes by a character.

**(e) The two edge cases, which are the whole decision.**

**A record two adapters claim → hard error. Agreed, and for §6.1's own
reason.** Producing both parses publishes two nodes for one operation, which
`SPEC.md` §7 already rules out in the duplicate-record case (*"an invented span
is worse than a missing one, because nothing downstream can tell"*). Producing
one is a guess between two dialects that disagree about the span's kind, its
payloads and its call ids — the exact plausible-but-wrong graph §6.1 exists to
prevent, now at record granularity. Downgrading it to an `unknown` node is
worse than refusing, because the graph then looks complete while one span's
relations are silently gone: finding #1 in miniature. And the refusal is
recoverable — `--adapter <id>` bypasses classification entirely, which is the
same escape hatch §6.1 already documents.

*Recommend reusing the existing `adapter_ambiguous` code* rather than minting
one. The class of failure, the remedy and the message are the same; only the
scope narrows from "this input" to "record N". Reusing it also avoids leaving
a code reachable from nothing, which is the bookkeeping A3 had to do for
`DuplicateNodeIdError`. The message must name the record's line number, its
span id if it has one, and both claimants.

**A record no adapter claims → an `unknown` node *and* a diagnostic.** Never a
discard (invariant 2), and never handed to a designated adapter, which would
put a dialect's name in a node's `Provenance` on the strength of that dialect
having said nothing about it.

This case is not hypothetical: it is what **every** record looks like today
under `--adapter <the other one>`, and today it produces an `unknown` node with
`unknown_span_kind`. Keeping that shape is what makes mixed dispatch a strict
improvement rather than a different set of losses — mixed and forced builds of
one file should differ in *provenance*, never in `node_count`.

It costs a model decision, and this memo cannot take it: `Provenance.adapter_id`
is `str`, and the honest value here is "none". Three ways out, in preference
order:

1. **`Provenance.adapter_id: str | None`** — correct, and a model change, so a
   second halt inside this one. The schema is unfrozen (`0.9.x`, freeze at
   Phase 4), which is exactly the window in which this is cheapest.
2. **Diagnostic only, no node** — no model change. `malformed_record` is the
   precedent (a diagnostic and no node), and invariant 2's wording (*"an
   `unknown` node **and/or** a Diagnostic"*) permits it. The cost is the
   asymmetry above: the same file builds a different `node_count` under
   `--adapter` than under auto, and a consumer iterating `nodes` never sees the
   record at all.
3. **Attribute it to a designated adapter** — rejected. It fabricates
   provenance, and provenance is the one field whose whole job is to say who
   read this.

Either way a new `unclaimed_record` diagnostic (warning) carries the record and
says no registered adapter recognized it. It is the honest report of *"you are
missing an adapter"*, which is a thing this library should be able to say.

**(f) What per-record dispatch does to ids — and E3's acceptance test.**

`ids.derive(adapter_id, trace_id, source_key[, record])`. Three rules
(`SPEC.md` §3.6), and dispatch touches each differently:

- **Rule 1 — a trace-unique `span_id` is the id.** Dispatch-independent: the
  id is the dialect's own string and no adapter id enters it. **This is every
  record in the corpus**: 177 of 177 carry a usable `span_id`. So for every
  fixture and every capture that exists today, mixed dispatch moves **no id at
  all**. Verified: the mixed build's nodes are `s0`–`s3`, the same ids the
  pure builds give.
- **Rule 2 — no `span_id` → `derive(adapter_id, trace_id, source_key)`.** Ids
  **move**, for two independent reasons. `adapter_id` changes for the records
  the other adapter now parses; and `source_key` falls back to the 1-based
  record index (`ADAPTERS.md` §3), which is an index **within the sequence
  handed to that `parse()` call**, so partitioning renumbers it. Measured on a
  span-id-stripped mixed file: forced `openinference` gives
  `sw_f3adffe8…`/`sw_cde39f99…`/…, forced `otel_genai` gives `sw_ece4112c…`/…,
  and mixed gives a third set again. All three are deterministic; none is
  comparable to another.
  > **Half of this is retired — batch A5 (`b6c5ea9`), 2026-09-10.** The
  > fallback `source_key` is the record's **canonical digest**, not its index,
  > so partitioning no longer renumbers anything and `ADAPTERS.md` §3 now says
  > the opposite of the sentence quoted above. The **first** reason stands
  > unchanged: `adapter_id` is in rule 2's material, so a record parsed by the
  > other adapter still gets a different id, and the measured id sets above
  > were taken under the old key and are not the ids the library derives
  > today. Kept rather than rewritten because it is what the probe measured;
  > what it measured is no longer what happens.
- **Rule 3 — A3 (`b44c3a5`), a shared `source_key` puts the record's canonical
  digest into the material.** Dispatch makes this rule reachable through a new
  door: two adapters can each hand `assign()` a record whose `source_key` is
  `"1"`. Rule 3 fires, the digest separates them, both are kept, no collision —
  it works, and it is order-independent by construction. But it now fires for a
  cause A3 did not have in mind, and **silently**: the `duplicate_source_id`
  report is keyed on `span_id`, not on `source_key`, so nothing says the two
  ids were disambiguated. E3 should decide whether that deserves a report.
  > **The door named here is closed — batch A5 (`b6c5ea9`).** No adapter hands
  > `assign()` a `source_key` of `"1"` any more: where a record states no span
  > id the key is the record's canonical digest, so two adapters collide only
  > on two records that are the same record. Rule 3 stays reachable through
  > the door A3 built it for — a dialect that reused a span id — and the
  > question of whether a `source_key` collision deserves its own report is
  > still E3's, on the narrower ground.

> **A defect this probe found that is not in the audit, is not caused by
> dispatch, and was real when this was written — fixed by batch A5
> (`b6c5ea9`), 2026-09-10, exactly as the last four sentences propose.** The
> fallback `source_key` is the record's canonical digest now (`SPEC.md` §3.6
> rule 2), the corpus gained `derived_ids` and `derived_ids_shuffled` — a
> span-id-less scenario and its reordered twin — and the shuffle tests assert
> the
> id-to-record **binding** rather than byte-identity, which is the assertion
> this defect hid behind. Read the rest as the finding, not as the state of
> the library. A record with **no** `span_id` gets an id
> derived from its position in the file, so shuffling the input changes the
> graph. Measured on a forced single-adapter build, no mixing involved: the
> document (modulo `source_digest`) and the per-record id assignment both
> differ between a file and its reverse. That contradicts `CLAUDE.md`
> invariant 4 and `SPEC.md` §5.2. It is invisible to the suite because the
> `shuffled_order` scenario — like all 177 corpus records — carries span ids,
> so no test has ever exercised the derived-id path under a shuffle. The fix
> is A3's own reasoning applied one level up: **the fallback `source_key`
> should be the record's canonical digest, not its index** — content, never
> position. That would move **0** stored expectations, because no fixture has
> a record without a span id. It also makes rule 2 dispatch-independent, which
> retires the second bullet above. Not E1's to decide; it wants its own batch,
> and E3 will collide with it if it is left.

**E3's acceptance test as written is achievable, and it is already insulated
twice.** `tests/conformance.py:canonical()` erases `provenance` from every node
(`ERASED_NODE_FIELDS = ("raw", "provenance")`), erases `adapter` from every
edge (`ERASED_EDGE_FIELDS = ("adapter",)`), and reduces `meta` to
`schema_version`, `trace_id` and the three counts — `meta.adapters` is not
compared. A derived id is compared **by position** (`_positional_labels`, A3).
So per-node provenance differing is not merely tolerable, it is invisible to
the comparison by design, and the corpus already documents why: *"who parsed it
is not a property of the run."*

One thing E3 must not assume, because it is the part that would fail: a mixed
rendering's **payload values** are a mix. `llm_tool_llm` declares
`s0.inputs` (`mime`, `value`), `s1.inputs`, `s1.outputs`, `s3.inputs`,
`s3.outputs` (`value`) dialect-varying in `expected/comparison.json`, and a
mixed rendering takes s0's from OpenInference and s1/s3's from OTel GenAI.
Compared **with** those declarations applied, the mixed graph is identical to
`llm_tool_llm`'s canonical graph — that is the `True` in **(b)**. Compared
without them it differs on exactly those five payload fields and nothing else.
So E3's scenario needs its own `expected/comparison.json` carrying the same
declarations (and, if it is rendered as a scenario rather than asserted against
`llm_tool_llm` directly, its own `expected/payloads/` entry). It must **not**
be added to `tests/conformance.py:DIALECTS` — that tuple obliges every scenario
to render every entry, and "mixed" is not a dialect.

**(g) What `Meta.adapters` and `Provenance.adapter` mean afterwards.**

- **`Meta.adapters`** already is a `tuple[AdapterInfo, ...]` sorted by
  `(id, version)`, and `SPEC.md` §3.9 already describes it as plural. Its
  meaning goes from *the adapter that read this input* to **every adapter that
  produced at least one node**. A single-dialect file still yields exactly one
  entry, unchanged.
- **`AdapterInfo.declared_confidence`** should be each contributing adapter's
  `detect()` over **the records it claimed** (first 50 of them). That keeps the
  field's meaning exactly as `SPEC.md` §3.9 states it — the adapter's own claim
  about the input it was given — and, because an adapter that claims every
  record gets the same first-50 sample it gets today, **no existing graph's
  number moves**.
- **`Provenance.adapter_id` / `adapter_version`** stop being graph-wide facts
  and become what the field's docstring already says: *which adapter produced
  this node*. No definition changes; it stops being trivially constant.
- **`Edge.adapter` is the one the row does not mention and E3 must answer.**
  `SPEC.md` §3.8 defines it as *"which adapter's spans the edge was built
  from"*, and under mixing an edge can join two adapters' spans: the prototype's
  `call_result` s1→s2 has an `otel_genai` requester and an `openinference`
  fulfiller. Three candidates — the adapter of the span that **stated** the
  relation (well-defined for `parent`: the child; and for `data`: the
  receiver — but arbitrary for `call_result`, which is a join of two
  statements); `None` when the contributors differ (honest, and `None` is
  already the value on every `temporal` edge, so no consumer can be relying on
  it being set); or a set, which is a schema change. **Recommend `None` when
  the contributors differ**, with §3.8 saying so: it reuses an existing legal
  value, it is the same answer the field already gives for an edge no adapter
  asserted, and it never names one dialect for a relation two dialects made.

**(h) Does the seam hold? Yes, under all three options, and here is the gate.**

`tests/gates.py:no_dialect_outside_adapters` (violation label
`no-dialect-in-builder`) scans every file under `spanweave/` **except**
`spanweave/adapters/` for the strings in `DIALECT_IDS`, lexically, comments
included; `tests/test_gates.py::test_package_names_no_dialect_outside_adapters`
asserts it over the shipped package. Its companion,
`no_adapter_imports_below_the_top` (`no-adapter-imports`), permits
`spanweave/api.py` and `spanweave/cli.py` to import the registry and nothing
else. Both stay green under every option here, because:

- **Classification lives in the registry**, `spanweave/adapters/__init__.py`,
  which is under `adapters/` and where dialect knowledge is already legal — and
  under the `detect([record])` reuse it holds **no marker table of its own**;
  each adapter answers for itself, so the registry stays as dialect-blind as it
  is today.
- **The builder is untouched by dispatch.** It receives spans and, for
  per-node provenance, an `AdapterInfo` alongside each — an opaque value it
  copies into `Provenance` and sorts into `Meta.adapters`. It never branches on
  one. This is already true of the single `adapter` parameter; E3 makes it a
  per-span value, not a new kind of knowledge. The prototype in **(b)** ran
  against **unmodified** `build.py`.
- **The partition happens above the seam**, in `api.py`, which is one of the
  two modules already permitted to reach the registry.

The one thing that would breach it: a residual rule that hands unclaimed
records to a named default. That is why **(e)** rejects option 3 on provenance
grounds — it would also require the dispatcher to name a dialect.

**(i) The options, and the recommendation.**

**Option (a) — the registry classifies every record; each adapter parses only
its own.** File-level detection becomes a *summary* of record-level
classification rather than a separate mechanism. Behaviour by case:

| Input | Result |
|---|---|
| every record claimed by one and the same adapter | exactly today's graph, today's ids, one `Meta.adapters` entry |
| ≥2 adapters each claim ≥1 record, none doubly claimed | mixed build |
| any record claimed by two adapters | hard error, `adapter_ambiguous`, naming the record |
| some records claimed by nobody | `unknown` node + `unclaimed_record` per **(e)** |
| **no** record claimed by anybody | today's `adapter_unconfident` hard error, unchanged |

**Option (b) — an explicit composite `--adapter openinference+otel_genai`.** A
new argument grammar, a new error surface for a malformed composite, and a
question about what a name *not* in the list does to a record. It buys the
ability to restrict mixing to a named set, which nothing has asked for. Under
(a), `--adapter <id>` keeps its exact current meaning (force one adapter over
everything) and remains the escape hatch for a doubly-claimed file and for
reproducing a pre-E graph.

**Option (c) — (a), but only when file-level detection is ambiguous.** *This
one is actively unsafe, and it is worth being specific about why.*
`DETECTION_SAMPLE_SIZE` is **50**. A trace of 10,000 OpenInference spans with
80 GenAI `chat` spans starting at record 200 has an unambiguous first 50:
`openinference` scores `0.9`, `otel_genai` scores `0.0`, no tie, so (c) never
enters mixed mode — and the 80 chat spans become `unknown` with their pairings
gone, exactly as in **(b)**'s table, in a file that built cleanly. (c)'s
precondition is a property of the first 50 records, not of the file, so it
gates the fix on a sampling artifact. The mixed-and-detected case is the *easy*
one; the mixed-and-undetected case is the dangerous one, and (c) covers only
the first.

**Recommendation: option (a), always, with no composite flag and no
ambiguity precondition.** Classification is per record because *dialect is a
property of a record* — that is the actual fact of the matter, and file-level
selection was an approximation that held only while a file had one producer.
The reasons, in order:

1. It is the only option that fixes the dangerous case, per (c) above.
2. It costs no adapter API, no builder change, and no marker table anywhere:
   `detect([record])`, already written, already pure, already total.
3. It is behaviour-preserving where it matters. A single-dialect input produces
   a byte-identical graph — same ids (rule 1 for all 177 corpus records), same
   `declared_confidence` (same first-50 sample), one `Meta.adapters` entry.
4. It makes the refusal proportionate. Today a mixed file is refused *entirely*
   and the recommended remedy silently damages it. Under (a) the refusal
   survives exactly where a guess would be required — one record, two claimants
   — and nowhere else.

E4's row proposes `--adapter auto|<id>|mixed`. Under this recommendation there
is **no `mixed` mode**: `auto` mixes iff the input is mixed, and a separate
spelling would only let a user assert something the records already settle.
`--adapter auto` as the explicit spelling of the default is worth having;
`--adapter mixed` is not.

**(j) The smallest experiment that would falsify it.** Install
`openinference-instrumentation-langchain` **and**
`opentelemetry-instrumentation-genai-openai` into one environment, point both
at one `TracerProvider`, and run a single tool-using LangChain agent turn
through `capture/`. Then read the export and answer two questions:

- **Does any record carry both markers?** If real instrumentors overlap —
  a framework instrumentor emitting `gen_ai.*` beside its own keys, which the
  convergence of the two conventions makes plausible — then the doubly-claimed
  case is the **common** case rather than the corner case, a hard error per
  record is hostile, and this memo's **(e)** is wrong. That is the single
  finding that would overturn the recommendation.
- **Is the file mixed at all, and is it mixed within the first 50 records?**
  A "no" to the first retires E entirely and answers G3 (not a freeze
  precondition). A "yes" to the first and "no" to the second is the decisive
  argument against option (c).

One capture settles both, and it is E3's fixture material either way. Until it
exists, the honest status of finding #1 is **a real defect on a constructible
input, with the input's occurrence in the wild predicted but unmeasured** —
which is a weaker claim than the audit makes and a stronger one than "we made
it up", and G3 should have it in those words.

**(k) Draft `DESIGN.md` §3 text** — a new subsection after §3.1, for E3/E4 to
land if (a) is taken. `DESIGN.md` itself is unchanged by this memo.

> ### 3.2 Dispatch is per record, and it happens above the seam
>
> A dialect is a property of a **record**, not of a file. One process can run
> a framework instrumentor and an SDK instrumentor at once; they share a
> `TracerProvider` and their spans share an export. Choosing one adapter per
> file was an approximation of the common case, and where it fails it fails
> silently: the losing dialect's spans become `unknown`, their payloads report
> `absent`, and every relation that joined the two dialects disappears while
> the graph still looks complete.
>
> So the registry classifies each record and each adapter parses only the
> records it claims. This does not move the seam — it *narrows* what crosses
> it. Nothing changes below:
>
> - **The builder still never learns a dialect name.** It receives spans and an
>   opaque `AdapterInfo` per span, copies it into `Provenance`, and sorts the
>   distinct ones into `Meta.adapters`. It never branches on one.
>   `no_dialect_outside_adapters` (`tests/gates.py`) is unchanged and stays
>   green.
> - **Classification stays inside `adapters/`.** The registry asks each adapter
>   `detect([record])`; no marker table lives outside the adapter that owns the
>   marker.
> - **The partition happens in `api.py`**, one of the two modules
>   `no_adapter_imports_below_the_top` already permits to reach the registry.
>
> Consequence, and it is the same one as §3: a new dialect is still a new file
> under `adapters/` plus fixtures. It now also composes with every existing
> dialect in one trace, for free, because composition is a property of the
> dispatcher rather than of any adapter.

**Draft `SPEC.md` §6.1 text** — replacing the current §6.1 in full. `SPEC.md`
itself is unchanged by this memo.

> ### 6.1 Adapter selection
>
> **A dialect is a property of a record.** `spanweave build` asks every
> registered adapter about **every** record — `detect([record])`, the same
> declaration §6 defines — and an adapter **claims** a record when it scores at
> or above `0.5`. Each adapter then parses the records it claimed, and the
> builder receives all of their spans together.
>
> | Input | Result |
> |---|---|
> | every record claimed by one adapter | one adapter, one `meta.adapters` entry — the single-dialect case, unchanged |
> | several adapters each claim some records, none claims a record another claims | a **mixed** build: each adapter parses its own records, `meta.adapters` lists every contributor sorted by `(id, version)`, and each node's `provenance` names the adapter that produced it |
> | any record claimed by two adapters | a **hard error** (`adapter_ambiguous`), naming the record, its span id, and the claimants |
> | a record claimed by no adapter | an `unknown` node carrying the record verbatim, plus `unclaimed_record` (warning) |
> | no record claimed by any adapter | a **hard error** (`adapter_unconfident`), listing every declared score |
>
> - `--adapter <id>` bypasses classification entirely: the named adapter parses
>   every record, whatever the markers say. It is the escape hatch, and it is
>   the remedy the ambiguity error names. `--adapter auto` is the default,
>   spelled out.
> - **Ambiguity is refused where a guess would be required, and nowhere else.**
>   Two adapters claiming one record is unresolvable — they disagree about that
>   span's kind, payloads and call ids, publishing both would invent a second
>   span for one operation (§7), and picking one is the plausible-but-wrong
>   graph this section exists to prevent. Two adapters claiming *different*
>   records is not ambiguity at all: each record has exactly one answer.
> - **Nothing is claimed by proximity.** A record's classification is a
>   function of that record alone, so it cannot depend on input order, on
>   registration order, or on how many neighbours matched (§5).
> - The confidence each contributing adapter **declared** is recorded in `meta`
>   as `declared_confidence` (§3.9), measured over the first 50 records **it
>   claimed** — the adapter's own claim about the input it was given, not a
>   measurement of anything. An adapter that claims every record therefore
>   reports the same number it reported before this rule existed.
>
> > Detection is still ergonomics rather than evidence, and `--adapter` still
> > works without it. What changed is the failure mode it defends against.
> > Before, an ambiguous input was refused as a whole and the documented remedy
> > — force an adapter — silently discarded the other dialect's meaning: its
> > spans became `unknown`, its payloads reported `absent` although content was
> > emitted, and every relation joining the two dialects vanished from a graph
> > that still looked complete. Refusing a *whole file* because *one record* is
> > ambiguous was never the honest scope of the refusal.

**(l) What E2–E4 inherit from this memo, beyond the decision.**

1. `ADAPTERS.md` §2 needs the record-decomposability paragraph and a checklist
   line (E2). No adapter gains a method.
2. `Edge.adapter` needs a rule for an edge joining two adapters (E3);
   recommended `None`, with `SPEC.md` §3.8 saying so.
3. `Provenance.adapter_id: str | None` is a model change and a **second**
   decision inside this one (E3). The fallback that avoids it is diagnostic-only
   for an unclaimed record, at the cost of a `node_count` that differs between
   the auto and forced paths for one file.
4. Rule 3 becomes reachable through a second door — two adapters both numbering
   a record `"1"` — and reports nothing when it fires (E3).
5. The scenario needs its own `expected/comparison.json` declarations, and
   "mixed" must not go into `tests/conformance.py:DIALECTS` (E3).
6. A separate, pre-existing defect: an index-derived `source_key` makes a
   record's id depend on its file position, so shuffling a trace with no span
   ids changes the graph. Not caused by dispatch; widened by it. Its own batch.

**Decision:**

*Not taken.* This entry is a `WORKPLAN.md` E1 halt; no code changed with it,
and `tests/audit/probe1.py`'s mixed-instrumentation case stays in the probe
until E2/E3 convert it. Record the decision in `WORKPLAN.md` §3.

---

## 13. G1: What counts as "real outside users", and when does the clock start?

**(a)** `ROADMAP.md` makes outside use a freeze precondition in **three**
places, at three different strengths, and none of them is a condition anyone
could check. Verbatim, so the decision is taken against the text and not a
paraphrase:

> The through-line: **earn the right to be depended on before asking to be
> depended on.** The schema does not freeze until a consumer the model was not
> designed for has used it unchanged.

> **Freeze later, on evidence.** `schema_version` `1` and `1.0.0` land when the
> predictions are resolved, the adversarial finding is absorbed, and real users
> have exercised the schema — not when the calendar says launch.

> - **The freeze.** `schema_version` `1` and `1.0.0`, once the predictions are
>   resolved, the Phase 2 adversarial finding is absorbed, real users have
>   exercised the schema at `0.9.x`, **and a third dialect is rendered in the
>   conformance corpus** — see the gate below.

**The three do not say the same thing, and the difference is the question.**
The through-line is nearly a definition already, and it is a **no-change**
test: the evidence is that nothing had to move. The two bullets say
*exercised*, which any use satisfies. And `CONTRIBUTING.md` #4 — which the
proposed definition cites, and the citation resolves; it is item 4 of *Ways to
contribute, most to least valuable* — counts the **opposite** event:

> 4. **A falsification consumer.** Built something on the library that needed a
>    change to it? Tell us what and why. That is direct evidence about the
>    model's generality, which is the thing we most need and can least
>    manufacture.

So the documents hold both *"the schema is ready when an outsider needed
nothing"* and *"the most valuable outside signal is an outsider who needed
something"*. Both are real evidence, of different things. A gate that does not
say which it counts gets argued at freeze time by whoever already has the
answer they want — which is this project's own recurring failure shape: a
statement nothing had to agree with until it mattered.

**(b) What the gate is for, stated before the conditions are judged against
it.** A freeze is a promise, and the thing worth measuring before making one is
whether the schema has been tested by someone **whose interests differ from the
author's**. Phase 4's third-dialect section already establishes what instrument
finds defects here: *two independent implementations having to agree*. All
three Phase 2 contract defects (`TASKS.md` 2.14) were found that way and none
by any number of tests written by one author against one dialect. "Real outside
users" is that same instrument pointed at the **consumer** side rather than the
producer side. Anything in the gate that does not put a second party in a
position of having to agree with the model is measuring **exposure** — someone
else's bytes met our code — which is worth having and is not what the sentence
promises.

**(c) The state of the repo today, measured, because it sets the clock.**

| Question | Answer, and how it was checked |
|---|---|
| Has `0.9.x` shipped to PyPI? | **Yes.** `0.9.0` and `0.9.1`, both `2026-08-30` (tag `v0.9.1`; `TASKS.md` 3.10 ticked, and R3). 3.10 records the verification from a directory outside the repo: `pip install spanweave` into a clean venv, `spanweave 0.9.0 (graph schema 0.1; UNFROZEN)`, `Requires:` empty, and the served sdist byte-identical to the built one (`sha256 ec3eeae2…`) |
| Is the README's index install true? | Yes, and **test-gated in both directions** — `tests/test_doc_truth.py::test_the_readme_says_what_is_true_of_the_index_install_in_both_directions` keys the `pip install spanweave` fence to 3.10's checkbox |
| Days on PyPI as of this memo (`2026-09-10`) | **11** |
| Outside commits | **0.** 108 commits, one author address (`git log --format=%ae \| sort -u`) |
| Outside adapters | **0.** Two exist; both first-party |
| Outside captured traces | **0.** Three in `fixtures/captured/`, all produced by `make capture`, run by hand, provenance first-party |
| Outside issues referenced anywhere in the repo | **0.** `.github/` holds `workflows/ci.yml` and nothing else — no issue template, no discussion config |
| A recorded announcement | **None anywhere.** `TASKS.md`, `ROADMAP.md`, `AGENT.md`, `ENVIRONMENT.md` and `WORKPLAN.md` mention no post, release note, or thread |

Two things follow, and they matter more than the counts.

First, **the gate starts from zero on every condition.** Whatever is decided
here is a schedule, not a scoring of things already banked. `TASKS.md` 3.11 §9
says as much: *"two of four met … Not met: real outside users, and a third
dialect rendered in the corpus."*

Second, and not written down anywhere yet: **the package has been installable
for eleven days and, as far as this repository records, nobody has been told it
exists.** That reframes condition 4 below — a clock started at publication
measures elapsed silence — and it is why the announcement belongs *before* the
clock rather than beside it.

*The honest bound on this section:* every check above is a check of **this
repository**, run with no network (`CLAUDE.md` 5; `ENVIRONMENT.md` zones 1–2).
GitHub issues and PyPI download counts are not visible from here. The
recommendation in **(f)** turns that limitation into a rule rather than
apologising for it: nothing counts until it is in the repo.

**(d) The four proposed conditions, judged one at a time.**

**1. An adapter contribution merged from outside.** The strongest of the four,
and it is not close.

- *Observable, and by whom:* unambiguously, by git — a merged commit whose
  author is not the maintainer. No judgement call.
- *Gamed or accidentally satisfied:* fraud is not the risk; **solicitation**
  is. An adapter the maintainer commissioned, walked through, or substantially
  rewrote in review is a weaker measurement than one that arrived. Either the
  condition says *unsolicited*, or the record says which it was.
- *What it evidences:* exactly what **(b)** asks for. `CONTRIBUTING.md`'s bar
  makes a mergeable adapter render the corpus and pass equivalence against the
  **unmodified** expected graphs — so its author had to agree with the model's
  fields or open an issue instead. That is the two-implementations instrument.
- **It double-counts, and that must be said out loud.** A merged outside
  adapter also satisfies the *third dialect rendered in the corpus*
  precondition, because CONTRIBUTING requires the renderings for merge. One PR
  closing two of the four freeze conditions is legitimate — it genuinely is two
  kinds of evidence — but a gate that can be halved by a single contribution
  should say so deliberately rather than be found doing it at freeze time.
- *Weakness:* nobody can cause it. A gate built only from events outside the
  maintainer's control may never close. That argues for a floor and a stated
  what-if, not against the condition.

**2. A consumer built on `0.9.x` that filed a model-level issue.** Right
instinct, three defects as drafted.

- ***"Model-level" is judged by the party the gate exists to test.*** Who
  decides an issue is model-level rather than a bug or a doc gap? Today, the
  maintainer — the one person whose interests the gate is measuring against.
  The project already owns a written standard for this exact classification:
  `PREDICTIONS.md`'s shape/operational test, which `ROADMAP.md` calls **binding
  as written there**, over the surfaces Phase 3's gate enumerates (a new field,
  `NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code, or query
  primitive). Require the issue to name one of those and be classified under
  that test, and the judgement is against a document written before the event.
- ***It never says the consumer is not us.*** `examples/` holds three consumers
  built on this model by its author. A fourth would satisfy the condition as
  written. The clause *not the maintainer, and not an agent working to the
  maintainer's instruction* belongs on **every** condition; this is where its
  absence is most visible.
- ***It counts only failure.*** CONTRIBUTING #4's event is a consumer that
  **needed a change**; the through-line's is a consumer that needed **none**.
  As drafted the gate rewards the model being wrong and records nothing when it
  is right — and "it worked, so I said nothing" is unobservable, which is the
  genuine difficulty here rather than a drafting slip. The form that survives
  it does not turn on the outcome: **a named, inspectable outside consumer** (a
  repository, a post, or an issue), with a recorded answer to *did the model
  have to change?* If yes, it is fixed before the freeze — Phase 3's gate,
  unchanged. If no, that is the through-line's own condition, met.

**3. A captured trace with provenance contributed from outside.** *This is the
one that does not measure what the gate is for* — named plainly, as the brief
asks. (It is also `CONTRIBUTING.md` **#2**, not #4; the #4 citation belongs to
condition 2 and is accurate there.)

- *Observable:* yes — a merged fixture plus a `FIXTURES.md` §6 provenance file.
  Weakly attested, though: provenance is self-declared prose, and "outside" is
  precisely the field nothing can check.
- *What it evidences:* a trace contributor **implements nothing and agrees with
  nothing**. It tests our *adapters* against an instrumentor's real output,
  which is valuable and is exactly why `FIXTURES.md` §6 prefers captures to
  hand-authored renderings — but it does not put a second party in front of the
  schema. On the gate's stated purpose it is the weakest of the four by a wide
  margin, and in a *two-of-four* rule it is the cheapest to obtain, which is the
  worst possible combination.
- **Unless it is narrowed — and then it is one of the most valuable things on
  the whole freeze list.** Phase 4's *necessary and not sufficient* section
  already names what reaches the nine strictly-compared node fields: *"a
  **captured** trace from dialect three, of a scenario `fixtures/captured/`'s
  existing pair also covers, compared against that pair field by field on the
  nine"* — and calls it the one schedulable condition and the one most likely to
  be assumed rather than done. A contributed capture meeting **that**
  description is worth more than the other three. A contributed capture of a
  dialect already captured here re-measures what is already measured. Recommend
  the narrow form, with the comparison **run and recorded** rather than the file
  merely merged.

**4. 30 days on PyPI with ≥1 issue reproducing on a non-fixture trace.** Two
clauses of very different quality, ANDed, which hides that one of them does no
work at all.

- ***"30 days on PyPI" is a clock.*** Unambiguous, ungameable, and evidence of
  nothing: no property of the schema changes because a month passed. With no
  announcement recorded it measures how long the package sat unmentioned. It is
  a **floor**, and a floor does not belong inside a count of conditions.
- *It is also under-specified in a way that will be argued.* Thirty days from
  **which** publish? `0.9.0` and `0.9.1` landed the same day, and C2 is a live
  `0.9.2` candidate. Say **from the first `0.9.x` publish, `2026-08-30`**, and
  that a later `0.9.z` does not restart it: the clock is on the line being
  installable, not on a version.
- ***"≥1 issue reproducing on a non-fixture trace"* is the real content**, and
  it is decent. It is checkable — does the reproducer live outside `fixtures/`?
  — and it converts itself into a regression scenario, which is what
  `CONTRIBUTING.md`'s *Reporting a bug* already asks for. But it evidences
  exposure, not agreement. Keep it, in the other column.

**(e) "At least two of four" is the wrong shape. This is my main disagreement
with the proposal.**

The four are not four of a kind. **1** and **2** are *agreement* evidence: a
second party's implementation or consumer had to live with the model's fields.
**3** and **4** are *exposure* evidence: someone else's telemetry met our code.
Any *two of N* over a heterogeneous set is satisfied by the two cheapest — and
here the two cheapest are 3 and 4. **A contributed trace plus a bug report
closes the gate without one person ever having had to agree with a `NodeKind`,
an `EdgeKind`, a warrant, a `Payload` state, or the serialized document.** That
pair satisfies the letter of the definition and leaves the sentence's meaning
entirely unmeasured, and it is the pair most likely to arrive first, because
both are cheap for the contributor.

So **two is about the right number of events and entirely the wrong rule.** The
recommendation below keeps the cost at two events and makes the load-bearing
half compulsory: one from each column, plus a floor.

**(f) Recommended replacement text.** `ROADMAP.md` is **not edited by this
memo**; this is the block to land when the decision is taken. Two clauses in
the Phase 4 freeze bullet change, and a new subsection follows *The third
dialect is a freeze precondition*. Note also that the through-line and Phase 3's
*Freeze later, on evidence* state the same gate in two weaker forms — each
should gain a pointer to the subsection in the same edit, or the project ends
up with three statements of one condition, drifting, which is the defect this
memo opened by describing.

> - **The freeze.** `schema_version` `1` and `1.0.0`, once the predictions are
>   resolved, the Phase 2 adversarial finding is absorbed, **the outside-use
>   gate below is met**, **and a third dialect is rendered in the conformance
>   corpus** — see both gates below. […rest of the bullet unchanged…]

> ### "Real outside users" is a stated gate, not a hope
>
> `0.9.x` is on PyPI so that someone whose interests differ from the author's
> can live with the schema before it becomes a promise. That is the only thing
> this gate measures. It is met when **all three** of the following hold.
>
> Two rules govern all of them. **No condition may be satisfied by the
> maintainer, or by an agent working to the maintainer's instruction** — that
> is the entire point of the word *outside*. And **nothing counts until it is
> in this repository**: a merged commit, a committed fixture, or an issue
> linked from `TASKS.md`. Everything else in this project is measured from the
> repo, cold, by anyone; this gate is checkable the same way or it is not
> checkable at all.
>
> **A. One agreement event** — a second party had to live with the model:
>
> 1. **An adapter merged from outside.** `CONTRIBUTING.md`'s bar already makes
>    this the strong form: a mergeable adapter renders the corpus and passes
>    equivalence against the **unmodified** expected graphs, so its author had
>    to agree with the model's fields or open an issue instead. This also
>    satisfies the third-dialect precondition above — one contribution closing
>    both is intended, and is stated here so it is not discovered. If the
>    contribution was solicited, the record says so; solicited is weaker
>    evidence and still counts.
> 2. **A named outside consumer, and what it needed.** A consumer built on
>    `0.9.x` by someone else, identifiable from the repo (a repository, a post,
>    or an issue), with a recorded answer to *did the model have to change?*
>    If it did, the change is made **before** the freeze and is classified under
>    `PREDICTIONS.md`'s shape/operational test, naming the surface — a field,
>    `NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code, or
>    query primitive (`CONTRIBUTING.md` #4, *a falsification consumer*). If it
>    did not, that is this file's own through-line satisfied — *a consumer the
>    model was not designed for used it unchanged* — and the record says so.
>
> **B. One exposure event** — someone else's telemetry met this code:
>
> 3. **A captured trace contributed from outside** (`CONTRIBUTING.md` #2), from
>    an instrumentor `fixtures/captured/` does not already hold, **compared
>    field by field against the existing captured pair on the nine
>    strictly-compared node fields** — the comparison run and recorded, not the
>    file merged. That narrow form is the one named above under *what would be
>    sufficient for the nine strictly-compared node fields*. A capture of a
>    dialect already captured here re-measures what is already measured and
>    does not satisfy this.
> 4. **An issue that reproduces on a trace not in `fixtures/`**, from telemetry
>    this project did not produce, landed in the corpus as a scenario
>    (`CONTRIBUTING.md`, *Reporting a bug*).
>
> **C. The floor.** **30 days** since the later of the first `0.9.x` publish
> (`2026-08-30`) and the announcement below. A later `0.9.z` does not restart
> it — the clock is on the line being installable, not on a version. The floor
> is **not evidence** and never satisfies a condition on its own; it exists so
> that A and B are given time to arrive rather than declared absent.
>
> **If the floor passes with A unmet, that is a finding and it gets written
> down** — *published, announced, and no second party engaged with the model in
> N days* — and then a deliberate choice between waiting, going and asking for
> one, and freezing on the third-dialect gate alone with the absence stated in
> the compatibility policy. What is not permitted is a freeze that happens while
> this sentence still reads as satisfied.

**(g) Announcement — a task, with an owner.** The row asks for an owner, and
the git history shows one author on 108 commits, so *owner* cannot mean
delegation. It means what it means at `ENVIRONMENT.md` **network zone 4**:
outward-facing, credentialed, human-run, and **not an agent's to perform**. An
agent may draft the text and assemble the links; posting is a halt point
(`AGENT.md`). Proposed task text, to land with **(f)**:

> ### Announcement *(owner: the maintainer, personally — human-run, `ENVIRONMENT.md` zone 4)*
>
> **When:** before the floor above is meaningful. Thirty days of an unannounced
> package measures silence, not adoption.
>
> **Where** — at most three places, each recorded in `TASKS.md` with its date:
> a release note on the `v0.9.1` tag; one thread where people who own agent
> telemetry are (the OpenTelemetry GenAI community; the instrumentor
> communities whose dialects this reads); one general post if wanted. More
> venues do not make a bigger measurement.
>
> **What it may claim: nothing the README does not.** The README is truth-gated
> (`tests/test_readme_quickstart.py`, `tests/test_doc_truth.py`), so the
> cheapest honest rule is that every claim in the announcement is one a test in
> this repository already holds the README to. That is enough to say: two
> adapters, `openinference` and `otel_genai`; 22 scenarios, 18 of them compared
> across both dialects; one deterministic graph; no runtime dependencies. Plus
> the actual ask, which is the invitation Phase 4 is built around — *your
> instrumentor, in one PR*.
>
> **What it must not claim.** An announcement that overclaims is the failure
> mode, and each of these is a claim the repo can already prove false:
>
> - **Not stable, not `1.0`, not "the schema".** It is `0.1` and UNFROZEN and
>   `spanweave --version` says so. This gate exists *because* it is unfrozen;
>   announcing it as settled makes the freeze a formality and destroys the
>   evidence the announcement was posted to collect.
> - **No dialect it does not read.** Langfuse, LangSmith, Logfire, Vercel and
>   OTLP protobuf are Phase 4 wants. "Supports OpenTelemetry" reads as all of
>   them.
> - **No unqualified equivalence claim.** `Node.name` is declared
>   dialect-varying in 18 of the 18 compared scenarios. The README carries that
>   qualifier; the announcement does not get to drop it for being long.
> - **No security, cost, evaluation, or quality framing** (`CLAUDE.md` 1). The
>   audiences most likely to pick this up are the ones that want exactly that,
>   and a neutral library announced as a security tool has acquired an opinion
>   in the only place it finally matters — the reader's.
> - **Not "production-ready", not "battle-tested".** Zero outside users is the
>   measurement this gate exists to change; claiming otherwise falsifies it.
> - **Not `pip install` followed by a `fixtures/` path.** The corpus is
>   deliberately not in the wheel — the finding `0.9.1` shipped C1 for. Any
>   example in the announcement runs from a checkout or reads the reader's own
>   trace.

**(h) Where this meets G3, and E.** G3 asks whether mixed instrumentation is a
freeze precondition. Not this memo's to decide; §12 (E1) supplies the fact it
turns on — a mixed trace is **constructible but not observed**: 57 corpus
files, 177 records, **0** carrying both markers. The gate above interacts with
that in one direction worth having in front of G3:

- **This gate is the mechanism by which a mixed trace would first be
  *observed*.** E1's three reasons a real stack mixes dialects — both
  instrumentors writing into one OTel SDK, the two layers seeing different
  spans, `opentelemetry-instrument` loading every installed entry point — are
  all properties of *someone else's* deployment. The maintainer can only
  construct one. A contributed capture (B3) or an outside adapter author (A1)
  is where an observed one comes from. If G3 wants observation rather than
  construction, it is waiting on the same events this gate counts.
- **That cuts both ways.** If E is made a freeze precondition, it is one whose
  only instrument today is this gate — and E1 records that the project's own
  harness deliberately avoids producing the shape by hand. If E is not made a
  precondition, the absence should be recorded as *measured and unobserved*,
  with E1's number, rather than assumed away; B3 is where the first
  counter-example would arrive.
- Smaller, in the other direction: per-record dispatch would make composition a
  property of the dispatcher rather than of any adapter (§12(k)), so an outside
  adapter would compose with every existing dialect for free. That raises what
  A1 is worth, and it is an argument about ordering E before breadth rather
  than about the freeze. G3's to weigh.

**Decision:**

*Not taken.* This entry is a `WORKPLAN.md` G1 halt; no code changed with it and
`ROADMAP.md` is untouched — the text in **(f)** and **(g)** lands only when the
decision is taken. Record the decision in `WORKPLAN.md` §3.

---

## 14. G3: Is mixed instrumentation a freeze precondition, and on what grounds?

**(a)** `WORKPLAN.md` G3 asks two things. **First:** is the audit's E — one
trace carrying two dialects' spans (§12) — a precondition of the schema freeze?
The row supplies an argument that it is: *"the freeze measures whether
adapter-supplied fields agree across adapters; a single trace exercising two
adapters at once is the strongest form of that measurement."* **Second:**
`ROADMAP.md` Phase 4 is coarse by design and sharpens when the Phase 3 exit is
met — is it met, and what is the sharpened text? Neither is this memo's to
decide; `ROADMAP.md` is not edited by it.

**(b) The answer in three lines**, with the rest as the working:

- **Yes, E is a freeze precondition — and not for the row's reason.** It is one
  because **E moves the schema**, under every option §12 leaves live. That
  ground is far simpler than the evidential one, it does not depend on anyone
  ever observing a mixed trace, and it is the ground the roadmap should state.
- **The row's evidential argument does not survive contact with this project's
  own reasoning.** Under per-record dispatch each record is parsed by exactly
  **one** adapter, so a mixed trace contests no adapter-supplied field at all.
  It measures *composition*, not *agreement*, and the two fields it introduces
  are erased by `canonical()` before the comparison runs.
- **Phase 3's exit is met.** Sharpen the freeze **conditions** now; hold the
  PR-level Phase 4 breakdown until the four open memos are decided, because the
  decisions determine what those PRs contain.

**(c) Is the Phase 3 exit met? Yes — checked in the repo, not assumed.**

`ROADMAP.md` Phase 3's exit is *both consumers work with zero shape changes;
every prediction marked; `pip install spanweave` works at `0.9.x`; a stranger
can build a graph from their own trace in ~60 seconds.* `TASKS.md` 3.11 is the
exit record and it is checked.

| Exit clause | State, from the record |
|---|---|
| Both consumers, zero shape changes | **Met.** 3.11 §1: `git diff --stat spanweave/` empty for 3.3 and 3.4 individually, with each consumer's own bound on what that zero means |
| Every prediction marked | **Met, with a qualification the record states itself:** all five plus O1 marked by a human; **P3 marked UNRESOLVED**, which is a mark and not an answer, and §7 of this file stays live |
| `pip install spanweave` at `0.9.x` | **Met.** `0.9.0` and `0.9.1`, `2026-08-30`, verified from the index outside the repo (3.10; §13(c) re-measures it) |
| A stranger in ~60s | **Met, and its one live defect has since closed.** 5.76–7.17s measured over four walks against a ~60s budget. 3.11 §7 recorded that the *index* path failed on its first command; that is C1, which shipped as `0.9.1` and is verified from the index (3.11 §8, amendment 3) |

So `TASKS.md`'s resolution rule — *sharpen a phase to PR level only when the
prior phase's exit criterion is met* — is satisfied, and Phase 4 may be
sharpened. **(i)** proposes the part of that sharpening this memo can honestly
write; **(h)** item 5 says why the rest should wait a little longer.

**(d) The simple reason, and it is not the row's: E changes schema-visible
things.** The freeze is a promise about the *schema* (`CLAUDE.md` 7), so the
question that settles a precondition is not *how strong is the evidence* but
*does this move a serialized field*. For E the answer is yes under every option
§12 leaves live.

| What E adds | Where it lands | Class under `PREDICTIONS.md`'s binding test |
|---|---|---|
| **`unclaimed_record`**, a new diagnostic code (§12(e), under *both* live options) | `spanweave/diagnostics.py` holds **15** codes today and none of them is this one; a code whose `source` shape is stated per code, as `unmapped_attributes` and `malformed_record` are, also moves `tests/serialized_shape.json` | **Shape change.** *"A new field, `NodeKind`, `EdgeKind`, warrant, `Payload` state, `Diagnostic` code, or query primitive"* — named in the definition, verbatim |
| **`Provenance.adapter_id: str` → `str \| None`** (§12(e) option 1, the recommended one) | `$.nodes[].provenance.adapter_id`, typed `"str"` in the committed shape artifact | **Shape cost** under the 2.10 amendment: a *serialized* field changing type on a public contract. Widening it after the freeze is breaking — a consumer that could never see `null` now can |
| **`Edge.adapter = None` when the contributors differ** (§12(g)) | `$.edges[].adapter`, already `"str \| None"` | **Not** a shape change. A new *value* on an existing field plus a `SPEC.md` §3.8 sentence. Nothing moves |
| **`Meta.adapters` with more than one entry; `Provenance` varying per node** | already `tuple[AdapterInfo, ...]`, already per-node | **Not** a shape change. Two fields stop being trivially constant, which is what their docstrings already say they are |

Three things follow, and the third is the one that makes this a precondition
rather than a preference.

1. **There is no schema-invisible version of E.** §12(e) option 2 — diagnostic
   only, no node — avoids the `adapter_id` widening and still adds the code.
   Option 3 is rejected on provenance grounds. So every path through §12 spends
   shape budget.
2. **"Hard gate: zero" is not violated by that, and it would be dishonest to
   imply it is.** That zero is *Phase 3's* measurement over its two
   confirmatory consumers, and it is discharged (3.11 §1). This series has
   already added two diagnostic codes since — `duplicate_record` (A3) and
   `missing_trace_id` (A4) — with nobody's gate broken. Shape changes are not
   forbidden; they are **cheap now and expensive later**, which is the whole
   design of decoupling the launch from the freeze (`ROADMAP.md` Phase 3,
   *Publish without freezing*).
3. **So the precondition is on the *decision*, not on the *implementation*.**
   Deciding *against* per-record dispatch resolves it just as well — but it must
   be decided, because freezing `adapter_id` as `str` prices a later E at a
   version bump and a migration note instead of at a minor release. A freeze
   taken while §12 is open is a freeze taken without knowing what it costs.

**(e) The row's own argument, weighed — and it fails on the roadmap's own
reasoning.** Stated plainly because the row is the reason this batch exists.

Phase 4 already fixes what "agree" means, and it is exact: *"an adapter-supplied
field is only measured when two adapters that **chose** a value have to agree on
it."* Test mixing against that sentence:

- **Under per-record dispatch, no adapter-supplied field is contested.** Each
  record is parsed by exactly one adapter (§12(i)), so every node's fields come
  from one adapter, exactly as they do in that dialect's pure rendering. The
  mixed build's `Usage.extra` on s1 and s3 is `otel_genai`'s, alone —
  the same value, from the same code, as in the pure `otel_genai` rendering. The
  three unmeasured rows on the freeze list (`Usage.extra`'s keys, the nine
  strictly-compared node fields, the inventory's unstated rows) are untouched by
  mixing. It adds no second chooser anywhere.
- **The fields E itself introduces are invisible to the comparison.**
  `tests/conformance.py` erases them before comparing: `ERASED_NODE_FIELDS =
  ("raw", "provenance")` and `ERASED_EDGE_FIELDS = ("adapter",)`. So E3's
  acceptance test cannot measure `Provenance.adapter_id` or `Edge.adapter` even
  in principle — by design, and the corpus already says why: *"who parsed it is
  not a property of the run."*
- **There *is* one value two adapters must genuinely agree on, and it is not on
  any gate: the join key of an edge that crosses them.** The prototype's
  `call_result` s1→s2 has an `otel_genai` requester and an `openinference`
  fulfiller (§12(g)); the edge exists only because the two adapters extracted
  the *same string*. Within a pure rendering an id only ever has to match
  itself, so no existing test contests this. **Per-record dispatch introduces a
  cross-adapter value dependency the library does not have today** — that is a
  finding, and it belongs on the freeze list's *necessary-and-not-sufficient*
  side rather than being sold as the measurement.
- **And a constructed mixed fixture cannot measure even that**, for the reason
  Phase 4 already gives about the nine node fields: both renderings of
  `llm_tool_llm` descend from **one `scenario.md`**, so a hand-authored pair
  agrees exactly where its author made it agree. Checked: both dialect files
  spell the call id `call_a`, because one person wrote both. E3's acceptance
  test therefore proves *composition works on a fixture whose halves were
  authored to agree* — which is what it should prove, and is not evidence about
  a vocabulary.

**So "the strongest form of that measurement" is backwards on constructed
input.** The strongest form is a *captured* mixed trace, where the join key
agrees or fails to agree because two real instrumentors read the same provider
id. That is an outside-evidence event — §13's B column — not a new gate.

**Evidential power and urgency point different ways, as the brief asks be said.**
The row's argument is about **power**: how much would a mixed trace tell us. The
answer above is *less than the row assumes, and on constructed input almost
nothing*. §12(c)'s finding is about **urgency**: 57 corpus files, 177 records,
**0** carrying both markers — constructible, structurally motivated, first-party
evidence in `capture/backends.py` that the project itself steers around the
shape, and **not observed**. An unobserved failure mode is a weaker precondition
than an observed one, so urgency is low too.

**Both therefore point away from the row's conclusion, and the conclusion holds
anyway** — because (d)'s ground is untouched by either. That is worth saying
because it changes what the roadmap should *write*: a sentence about evidence
would be a sentence this memo has just shown to be wrong.

One distinction to keep, so low urgency is not misread: E's urgency **as a bug**
is high. §12(b) measures a forced build losing 2 of 7 edges and reporting
`Payload.state = absent` where content was emitted, at exit `0`, from a
graph that looks complete. Silent wrongness on a constructible input is a strong
argument for fixing E soon. It is simply not an argument about the *freeze*,
which turns on whether the contract moves.

**(f) The collision with §13, named and resolved.** If E is a freeze
precondition and the only mixed trace in existence is one we constructed, the
precondition is satisfiable **only by our own artifact** — which is exactly what
§13(f)'s standing rule excludes: *no condition may be satisfied by the
maintainer, or by an agent working to the maintainer's instruction.*

The contradiction is real for one reading of "E is a precondition" and absent
for the other. Phase 4 already holds two kinds of precondition and has never
distinguished them by name:

| Kind | Instances | Who may satisfy it |
|---|---|---|
| **Work that must land before the contract locks** | a third dialect rendered in the corpus; the predictions resolved; the Phase 2 finding absorbed | **us, deliberately.** That is the point of them |
| **Evidence that must arrive from outside** | §13's A column (agreement) and B column (exposure) | **not us, by rule** — the rule is what the word *outside* means |

**E belongs in the first, and §13's rule does not reach it.** "The library
represents a mixed trace before the schema locks" is a work item, discharged by
E2–E4 and their fixture. §13's exclusion governs the outside-use gate, where the
maintainer's own artifact would *be* the measurement; here the artifact is the
deliverable, and building your own deliverable is not self-dealing.

**The reading that does collide should be rejected on its own merits.** "A mixed
trace must be **observed** before the freeze" is a gate nobody here can cause —
§13(h) says so, and E1's three reasons a real stack mixes dialects are all
properties of *someone else's* deployment. Its only instruments are §13's A1 (an
outside adapter author) and B3 (a contributed capture), so adopting it would
count §13's own conditions a second time under a different name, and a gate that
can be closed once and counted twice is the defect §13(d) raised about
condition 1's double-count. Reject it; record the absence instead, as §13(h)'s
second bullet already proposes — *measured and unobserved*, with §12's number.

**(g) The one experiment, and it is cheap.** §12(j) is the smallest thing that
would settle both questions this memo splits: install both instrumentors into
one environment, point them at one `TracerProvider`, run one tool-using agent
turn through `capture/`. It answers *does any record carry both markers* (which
would overturn §12(e)'s hard error) and *is the file mixed outside the first 50
records* (which is the decisive argument against §12's option (c)).

Two properties of it belong in front of the maintainer:

- **It is the only experiment on the whole freeze list that needs no second
  party.** The third-dialect capture (`ROADMAP.md`, *what would be sufficient
  for the nine strictly-compared node fields*) needs a dialect we do not have;
  §13's A and B need a person who is not us. This one needs two `pip install`s
  and one agent turn.
- **It is a human act and a halt point** (`ENVIRONMENT.md` network zone 4,
  `AGENT.md`, `FIXTURES.md` §6) — an agent builds the harness and stops. So it
  is schedulable, and it is the second item on the freeze list with that
  property, which by 3.11 §9's own reasoning makes it the second most likely to
  be assumed rather than done.

Recommend scheduling it beside the dialect-three capture. **Not as a gate
condition** — it must not become one, per **(f)** — but as the measurement that
would tell E2 whether its central recommendation is right before E2 implements
it.

**(h) Recommendation.** Five items; the decision is the maintainer's.

1. **Make E a freeze precondition, on schema grounds, in a sentence that
   mentions no evidence.** The text is in **(i)**.
2. **State it as a rule rather than as a special case, because E is not
   alone.** The live memos each either move a serialized field or are a
   decision to leave one where it is: §10 would change `started_at`'s type,
   §12 adds a diagnostic code under every option, and the agent-identity memo
   (H1) proposes a new `identity` field outright. §11 is the exception that
   proves the rule — builder-owned `basis` strings, no type movement, and I1
   already measured that class of change at zero serialized bytes. One bullet
   covering all of them is honest, is shorter than four, and does not require
   the roadmap to relitigate each.
3. **Do not add a "mixed trace observed" condition.** **(f)**.
4. **Record the absence as a measurement**: 57 files, 177 records, 0 with both
   markers, with the `capture/backends.py` comment as the strongest first-party
   evidence and the honest note that it is a prediction about the world.

   A **second measured absence** belongs beside it, recorded here by batch H2
   from §15(j). Across the three captured traces — `openai_tool_call.jsonl`,
   `genai_tool_call.jsonl`, `genai_workflow.jsonl`, 17 records — there are 4
   `agent` spans, and **0 of them come from an instrumentor**. All four are
   written by the harness (`capture/backends.py`, `agent_span_attributes` and
   `genai_agent_span_attributes`), for the reason that file states: executing
   an agent turn is not an SDK call and there is nothing for an instrumentor
   to wrap. It is the same shape of claim as the mixed-trace one — a
   measurement of this corpus, and a prediction about the world only until an
   agent-framework instrumentation package is run through `capture/` (§15(j)).
   It bears on the freeze the same way: §15's option B would normalize an
   attribute whose cross-dialect behaviour nobody here has observed.
5. **Sharpen the freeze conditions now; hold `TASKS.md`'s provisional Phase 4
   at its current resolution.** The exit is met (**(c)**), so sharpening is
   licensed — but the PR-level breakdown of Phase 4 depends on four open
   decisions, and specifying PRs whose content the decisions determine is the
   over-specification `TASKS.md`'s resolution rule and `CLAUDE.md`'s
   *vertical slice before breadth* both forbid. The freeze **conditions** do
   not depend on those decisions, which is why they can be sharpened today.

**(i) Proposed `ROADMAP.md` text.** Two edits to Phase 4. `ROADMAP.md` is **not
edited by this memo**; this is the block to land when the decision is taken. The
first composes on top of §13(f)'s edit to the same bullet rather than replacing
it — if §13 is decided differently, only the outside-use clause changes.

> - **The freeze.** `schema_version` `1` and `1.0.0`, once the predictions are
>   resolved, the Phase 2 adversarial finding is absorbed, **the outside-use
>   gate below is met**, **a third dialect is rendered in the conformance
>   corpus**, and **every open model question in `OPEN_QUESTIONS.md` is
>   decided** — see the three gates below. […rest of the bullet unchanged…]

Then a new subsection after *The gate is necessary and, for these three, not
sufficient*:

> ### No open model question survives the freeze
>
> The freeze is a promise about the **schema**, so what binds it is anything
> that would move the schema afterwards. Until it is taken, a shape change costs
> a minor release; after it, the same change costs a version bump and a
> migration note (`CLAUDE.md` 7). **That asymmetry, and not the strength of the
> evidence behind any one question, is what makes an open question a
> precondition.**
>
> So: `OPEN_QUESTIONS.md` carries no undecided entry that would move a
> serialized field at the moment `1` is declared. **Deciding an entry to change
> nothing is a resolution; leaving it open is not.** The live entries are the
> four design memos written for the September 2026 audit — timestamp
> representation, `data` edge echo, per-record dialect dispatch, and agent
> identity — plus the outside-use gate above, which governs the gate rather than
> the model.
>
> **Mixed instrumentation is a precondition on exactly these grounds and no
> others.** Every option its memo leaves live adds a `Diagnostic` code, and the
> recommended one also widens `Provenance.adapter_id` to `str | None` — a
> serialized field changing type, which `PREDICTIONS.md`'s binding test as
> amended at 2.10 costs as shape. Deciding *against* per-record dispatch is
> equally a resolution and equally must happen first: freezing `adapter_id` as
> `str` prices the change at a migration rather than at a minor release.
>
> **What it is not: evidence that adapters agree.** Under per-record dispatch
> each record is parsed by exactly one adapter, so no adapter-supplied field is
> contested by mixing, and the two fields dispatch introduces — a node's
> `provenance` and an edge's `adapter` — are erased by `canonical()` before the
> comparison runs. A mixed trace tests **composition**, which is worth having
> and is not the measurement the gates above ask for. The one value two adapters
> must genuinely agree on is the **join key** of an edge that crosses them, and
> a constructed mixed fixture cannot measure it for the reason given above about
> the nine node fields: both renderings descend from one `scenario.md`, so they
> agree where their author made them agree. Only a **captured** mixed trace
> measures it — an outside event, counted once, under the gate above.
>
> **The shape has never been observed here**: 57 corpus files, 177 records,
> **0** carrying both dialects' markers. It is constructible, structurally
> motivated — two instrumentors share one `TracerProvider`, and this repo's own
> capture harness steers around the shape by hand — and predicted rather than
> seen. Recorded as a measurement rather than assumed away, and the capture that
> would settle it is a human act, schedulable alongside the dialect-three
> capture above.

**(j) G2's three lines in `ROADMAP.md`: they should stay.** §0.6 says
*"`ROADMAP.md` is untouched until G3"*, so G3 is the batch entitled to judge
them (`ad77259`, verbatim):

> *Raw OTLP JSON is pulled forward by the September 2026 audit as batches F1–F2,
> which ask whether the envelope is a container format for the reader rather than
> a dialect for an adapter (registered in `TASKS.md`, tracked in `WORKPLAN.md`).*

**Keep**, for three reasons and against one temptation.

- **They are within what G2's row permitted, and correctly scoped.** The row
  allowed a pointer *"only if a bullet already covers the item (OTLP JSON);
  otherwise nothing"*. Phase 4's first bullet already names raw OTLP JSON, so
  the sentence annotates an existing item rather than adding one. Nothing else
  in the file moved.
- **They are true, and they are the kind of true that decays if unwritten.**
  F1 asks whether the envelope is a *reader-level container* rather than a
  dialect — which, if decided that way, changes what Phase 4's own bullet means:
  raw OTLP JSON would stop being an adapter on the flywheel list and become a
  reader feature. A roadmap whose bullet is being reinterpreted elsewhere should
  say so where the bullet is.
- **§0.6's rule is about entitlement, not about correctness.** "Untouched until
  G3" sequenced *who may edit*; it did not predict the edit would be wrong.
  Reverting to keep the file virgin would spend a commit to remove a true
  sentence, and would leave `ROADMAP.md` the only document that does not know
  its own item is being worked.

**One defect in them, and it is `WORKPLAN.md`'s to have caught, not G2's.**
*"tracked in `WORKPLAN.md`"* is a pointer to a file **G4 deletes**. G4's row
covers the `TASKS.md` statuses and the README row; it does not mention
`ROADMAP.md`, and it does not mention this file, where every memo in the
series — five of them now — ends with *"Record the decision in `WORKPLAN.md`
§3."* Sixteen registry lines in
`TASKS.md` carry the same phrase and are inside G4's scope by its wording.
**Recommend G4's scope explicitly gain the `ROADMAP.md` line and the memo
sign-offs here**, re-pointed at `TASKS.md`. That is a one-line addition to a
batch that has not run, not an edit to G2's work, and this memo makes none.

**(k) What this memo hands forward.**

1. **E is a freeze precondition on schema grounds**, and the roadmap sentence
   should not claim it is evidence — **(d)**, **(e)**.
2. **A new finding for the freeze list, if per-record dispatch is taken:** the
   join key of an edge crossing two adapters is a cross-adapter value dependency
   the library does not have today, and no constructed fixture can measure it.
   It belongs beside `Usage.extra` and the nine node fields as
   *necessary-and-not-sufficient*, not as a gate — **(e)**.
3. **The observation gate is rejected and the absence is recorded instead**, so
   §13's conditions are not counted twice — **(f)**.
4. **§12(j)'s capture is the only freeze-list experiment needing no second
   party**, and it is a human act. Schedule it beside the dialect-three
   capture — **(g)**.
5. **Phase 3's exit is met; `TASKS.md`'s Phase 4 should stay coarse** until the
   four memos are decided — **(c)**, **(h)** item 5.
6. **G4 needs one more line of scope**: `ROADMAP.md`'s pointer and this file's
   memo sign-offs outlive `WORKPLAN.md` — **(j)**.

**Decision:**

*Not taken.* This entry is a `WORKPLAN.md` G3 halt; no code changed with it and
`ROADMAP.md` is untouched — the text in **(i)** lands only when the decision is
taken, and the three lines judged in **(j)** are left exactly as G2 wrote them.
Record the decision in `WORKPLAN.md` §3.

---

## 15. H1: Should a node carry the name of the agent, chain or retriever it ran?

**(a)** `Node.operation` is `None` on every `agent`, `chain` and `retriever`
node the corpus produces, in both dialects. OTel GenAI states an agent's name
in a normative attribute, `gen_ai.agent.name`, and the `otel_genai` adapter
deliberately does not read it. Three options were tabled: map it into
`operation`; add a new `identity` field carrying a value plus the provenance of
that value, mirroring `Edge.warrant`; or leave it and say so in the spec. Any of
the first two is a model change, so this is a halt point (`AGENT.md`).

**(b) The actual state, per kind and per dialect, verified against fixtures.**

| Kind | Dialect | What names the thing | Where it is today |
|---|---|---|---|
| `agent` | openinference | the span `name` only — no attribute | `nodes[].name`, `raw.source.name` |
| `agent` | otel_genai | `gen_ai.agent.name`, **and** the span `name`, which is the operation and the agent name joined | `raw.source.attributes`, plus one `unmapped_attributes` key, plus `nodes[].name` |
| `chain` | openinference | the span `name` only | `nodes[].name`, `raw.source.name` |
| `chain` | otel_genai | *nothing* — the dialect has no `chain` | n/a: `invoke_workflow` is deliberately unmapped, so no GenAI span becomes a `chain` |
| `retriever` | openinference | the span `name` only | `nodes[].name`, `raw.source.name` |
| `retriever` | otel_genai | *nothing* — the convention names the operation (`retrieval`), not the retriever | n/a |

The two captured traces are the evidence, and they were produced from one
harness against one model, so they are directly comparable.
`fixtures/captured/openai_tool_call.jsonl`, first record:

```
"name": "agent.run",
"attributes": {"openinference.span.kind": "AGENT", "input.value": …, "input.mime_type": …}
```

`fixtures/captured/genai_tool_call.jsonl`, first record:

```
"name": "invoke_agent agent.run",
"attributes": {"gen_ai.operation.name": "invoke_agent",
               "gen_ai.agent.name": "agent.run",
               "gen_ai.input.messages": …}
```

Built (`uv run spanweave build fixtures/captured/genai_tool_call.jsonl`), the
GenAI agent node is `operation: null`, `attributes: {}`, and the name is not
lost — it is in **two** places a consumer can reach:

```
nodes[0].raw.source.attributes["gen_ai.agent.name"] == "agent.run"
diagnostics[] {"code": "unmapped_attributes", "level": "info",
               "node_id": "81bcfdbbf4b66e32", "source": ["gen_ai.agent.name"]}
```

So losslessness holds twice over: the **value** verbatim in `raw.source` — which
`CONTRACTS.md` asserts round-trips byte-for-byte and which is serialized on
every node unconditionally — and the **fact that we declined to normalize it**
as an `info` diagnostic naming the key. `raw.source` is the answer to "where can
a consumer find it now"; the diagnostic is the answer to "how would a consumer
know to look".

Two precisions the row's one-line statement omits, both found by probing rather
than by reading:

- **`operation` is not structurally `None` on an agent node.** Neither
  adapter's `_operation` has an agent branch; both fall through to the model
  name (`spanweave/adapters/otel_genai.py:514`,
  `spanweave/adapters/openinference.py:385`). Fed an agent span carrying
  `gen_ai.request.model` / `llm.model_name`, **both dialects today put the
  model name in `operation`** — measured, `operation: "m1"` in each. The `None`
  in the corpus is a property of the fixtures, not of the code. This matters in
  **(g)**.
- **"retriever name" is unrealizable in both dialects.** `SPEC.md` §3.1
  documents `operation` as `# tool name / model name / retriever name`, and
  no dialect this library reads states a retriever's name anywhere. The one
  `retriever` node in the corpus has `operation: null`; an OpenInference
  RETRIEVER span carrying `embedding.model_name` would get the *model*. The
  third of the three names in the spec's own definition has never been
  produced. That is a documentation defect this memo surfaces and does not fix.

**(c) What a consumer cannot ask today.** It can already ask "what is this agent
called" — the value is on the node — but it cannot ask it **the same way twice**.
In OpenInference the answer is `node.name`; in OTel GenAI it is
`node.raw.source.attributes["gen_ai.agent.name"]`, and `node.name` there is
`"invoke_agent agent.run"`, a composite that needs a dialect-specific split.
Reaching either means a consumer branching on the dialect, which is precisely
the work the library exists to absorb (`SPEC.md` §3.7 makes exactly this
argument for putting a tool name on `unpaired_call`: "recovering the name meant
walking the requesting node's output payload, in a dialect-specific shape,
inside a consumer that must not know a dialect").

**But the inconvenience is smaller than that precedent's**, and the difference
decides the ranking. There, the value existed **nowhere on the graph** — an
unfulfilled call has no node. Here it is on the node, in a field
`CONTRACTS.md` pins as byte-exact, and the diagnostic already points at the key.
So the honest statement is: *a consumer can answer it today, less conveniently
and with one dialect branch*, and what an identity field buys is uniformity, not
capability. Set against that, `nodes[].name` — the field that carries the
identity in the one dialect that has nowhere else to put it — is declared
dialect-varying and erased in **18 of 22** scenarios, and `CONTRACTS.md` records
that `name` "has **never** been compared across dialects, in any scenario, at
any point in this project". A consumer relying on `name` is relying on something
the corpus does not test.

**(d) The neutrality test, both sides.**

*It is neutral.* The attribute is literally named `gen_ai.agent.name`. Copying
its value into a field means transcribing a string the telemetry wrote into a
slot, keyed off nothing but the attribute's own key — the same act as reading
`gen_ai.tool.name` into `operation`, which nobody calls interpretation.
`ADAPTERS.md` §1's rule is *transcribe, don't interpret*, and "the instrumentor
said this span's agent is called `agent.run`" is a report, not a judgement. It
assigns no role, no severity, no risk and no quality: `CLAUDE.md` 1's list is
about **evaluating** telemetry, and a name evaluates nothing.

*It is interpretation.* Not on the GenAI side — on the other one. The moment
identity is a field, the pressure is to fill it for OpenInference too, and there
the only candidate is the span `name`. Deciding that `"agent.run"` in a span
name *is* the agent's identity is a reading of a free-text field; so is
splitting `"invoke_agent agent.run"` on a space. Both are the class of inference
`AGENT.md` calls a halt point. A field that only one dialect can honestly fill
is a standing invitation to fill it dishonestly in the other, and the invitation
is the risk — not the first commit.

**Verdict: the fact is neutral, the field is not automatically so.** Neutrality
does not settle H1 in either direction; it only rules out *deriving* an identity
where a dialect states none. Both live options survive it. What kills option A
is **(e)** and **(f)**, neither of which is about neutrality.

**(e) Does an agent name fit `operation`? The precedent is real but narrower
than it looks.** `SPEC.md` §3.1: `operation: str | None # tool name / model
name / retriever name`. §3.7 leans harder, calling `operation` "the identity of
an operation" — read that way, `invoke_agent` invokes an agent, the agent is the
callee, and its name is the callee's name exactly as `gen_ai.tool.name` is on
`execute_tool`. That reading is coherent and I do not think it is smuggling.

The problem is that it is not the only thing already in the field. Per **(b)**,
an agent span carrying a model attribute puts the **model** in `operation`
today, in both dialects. Option A therefore needs a precedence rule, and both
choices are bad: agent-name-wins silently drops a value the two dialects
currently agree on, and model-wins silently drops the agent name whenever the
span also names a model. Either way `operation` on an `agent` node stops having
one meaning — a consumer reading `"m1"` cannot tell whether it holds a model or
an agent without going back to `raw`. That is a worse contract than `null`, and
it is a defect of option A **on a single dialect**, before any cross-dialect
question is asked.

**(f) The dialect asymmetry. It is real, it is measured, and it is decisive for
option A.** Simulated by injecting `gen_ai.agent.name: "agent.run"` into every
`invoke_agent` / `create_agent` span of every `otel_genai` rendering — which is
what `capture/backends.py` already writes for a real capture — then applying
option A and running the corpus's own `canonical()` with each scenario's
declared erasures and payload declarations:

| | scenarios |
|---|---|
| rendered in both dialects, adapter-backed | 18 |
| **diverge under option A** | **11** |
| diverge today (baseline) | 0 |

The eleven: `clock_skew`, `llm_tool_llm`, `missing_payloads`, `nested_agents`,
`parallel_tool_calls`, `parallel_tools`, `shuffled_order`, `timestamp_units`,
`unknown_kind`, `unpaired_tool_call`, `unset_and_error_status` — 12 agent nodes,
`nested_agents` carrying two. In each, `operation` reads `"agent.run"` in
`otel_genai` and `null` in `openinference` for the same logical span. That is
the cross-dialect equivalence claim (`FIXTURES.md` §4, `CLAUDE.md` *conformance
is the executable spec*) failing on the library's most-rendered node kind.

Three things sharpen it:

- **The corpus would not catch it today.** Zero conformance renderings carry
  `gen_ai.agent.name` (`grep -rl` over `fixtures/conformance/*/dialects/` = 0
  files), so option A moves **0 stored expectations** and `make check` stays
  green. The divergence arrives with the first fixture that renders the
  attribute honestly — and `FIXTURES.md` §6 says a captured trace outranks a
  hand-authored one, so that fixture is a matter of when.
- **The only repair available is the one the corpus forbids.** A scenario would
  have to declare `erase: ["operation"]`. Whole-field erasure in
  `tests/conformance.py:_node` applies to **every node of the scenario**, not to
  the agent node, so those eleven declarations would also stop comparing **22
  non-null `operation` values** on the llm and tool nodes beside them —
  `demo-model`, `lookup`, `alpha`, `beta`, `gamma`, `lookup_flight`. `operation`
  is, per `CONTRACTS.md`, agreed across dialects in 15 of 16 compared scenarios,
  "the strongest evidence any unstated field here has". Option A spends that to
  buy a value already present in `raw`. `tests/conformance.py`'s own docstring:
  *"Never weaken this to make a test pass."*
- **`chain` and `retriever` have no cross-dialect exposure at all**, so they are
  not part of this. All 4 `chain` nodes and the 1 `retriever` node live in
  `cyclic_parents`, `retriever_and_embedding` and `span_links`, which
  `otel_genai` declares unrenderable. H1 is an `agent` question wearing three
  names.

**Option B is not exposed to this the same way, and that is its one real
advantage.** `identity` would also be `"agent.run"` against `null` in the same
eleven — but an `erase: ["identity"]` declaration would cost **zero** collateral
assertions, because no other node kind would ever populate it. Option A puts the
asymmetry inside a field that carries symmetric, well-tested content; option B
quarantines it in a field that carries nothing else. Same divergence, very
different blast radius.

**(g) What each option costs, counted.**

| | A: into `operation` | B: new `identity` | C: leave, document |
|---|---|---|---|
| `spanweave/model.py` | — | `Node` + 1 field, + 1 frozen dataclass | — |
| `spanweave/seam.py` | — | `NormalizedSpan` + 1 field | — |
| `spanweave/build.py` | — | 1 pass-through line (beside `:196`) | — |
| `spanweave/serialize.py` | — | `_node` + 1 key | — |
| adapters | 1 (`otel_genai._operation`, ~5 lines + precedence rule) | 2 (one populates, one documents why it never can) | 0 |
| `tests/serialized_shape.json` | unchanged | +1 row as a leaf, +3 as `{value, source}` | unchanged |
| stored `expected/graph.json` | **0 today**, 11 scenarios / 12 nodes on the first honest fixture | **all 22 files, all 54 node entries** gain the key | 0 |
| `canonical()` | unchanged in code; 11 scenarios need an erasure that costs 22 other assertions | unchanged in code; erasures cost nothing else | unchanged |
| `FIXTURES.md` §4 Compared bullet | unchanged | must name `identity` — enforced by `test_the_compared_list_names_every_field_that_is_compared` | unchanged |
| `CONTRACTS.md` | one row's meaning changes | +1 inventory row, +1 "what is unstated" row | one row's meaning restated |
| `SPEC.md` | §3.1 definition widened, §3.7 re-read | §3.1 + a new subsection | §3.1, one paragraph |

Option C is not free of documents, only of code. Today the non-mapping is
recorded in an adapter **docstring** (`otel_genai.py:519`) and in two fixture
notes (`nested_agents/scenario.md`, `nested_agents/otel_genai.notes.md`) — and
nowhere in `SPEC.md`, which `CLAUDE.md` names the source of truth for behaviour.
C's whole content is moving that sentence to where it binds.

**(h) The freeze. H1 must be decided before it; only one option must also be
implemented before it.** §14(h) item 2 already names this memo — *"the
agent-identity memo (H1) proposes a new `identity` field outright"* — and folds
it into the rule that no undecided entry may survive the freeze. That rule is
right about H1, but its stated **reason** does not reach every option, and the
distinction should be recorded rather than smoothed over:

- **Option A binds, hardest.** It changes what an existing, frozen,
  cross-dialect-compared field *means*, with no movement in
  `tests/serialized_shape.json` to warn anyone — the shape is identical and the
  value domain is not. After the freeze that is the worst class of change to
  discover: `CLAUDE.md` 7 permits additions and prices breaks at a version bump,
  and a field that quietly starts holding a different kind of string is neither,
  which is to say it is unpriceable. Foreclosing option A is the single strongest
  reason H1 cannot be left open.
- **Option B binds by §14's rule but not by §14's reason.** `CLAUDE.md` 7:
  after the freeze, *"changes are additive-only"* — and a new optional field is
  the additive case, not the breaking one. Unlike E, which widens
  `Provenance.adapter_id` from `str` to `str | None` and so must precede the
  freeze on pain of a migration note, `Node.identity` could honestly be added at
  `1.1`. What it could not do post-freeze is arrive quietly: it changes what
  `canonical()` compares and what every consumer written against `1` sees.
- **Option C is a resolution.** §14(i)'s own text — *"Deciding an entry to
  change nothing is a resolution; leaving it open is not"* — makes C a complete
  discharge of the precondition at zero schema bytes.

So the sentence for the roadmap is *H1 decided*, not *H1 implemented*.

**(i) Recommendation: option C, with option B held open as the additive path.**
Leave `operation` `None` for `agent`, `chain` and `retriever`; write the
non-mapping into `SPEC.md` §3.1 as a stated rule rather than an adapter
docstring; state in the same paragraph that the identity is carried verbatim in
`raw.source` and announced by `unmapped_attributes`. Reject option A outright,
on **(e)** and **(f)** — it is the only option that can make an existing field
mean two things and cost 22 tested cross-dialect assertions to repair.

The case for C over B is not that B is wrong. It is that B pays a permanent
schema field, 54 stored node entries and a line in a test-enforced contract list
for a value that is **one dialect's, on one node kind, already on the node**, and
that the payment can be made later without penalty because it is additive. The
case for B — one uniform question a consumer can ask — is real and stays real;
what is missing is any evidence that a *second* dialect would fill the field,
and a normalized field that exactly one dialect populates is a rename of that
dialect's attribute, not a normalization.

Two things belong with the decision either way. First, the `retriever name`
defect in **(b)** — `SPEC.md` §3.1 promises a name no dialect states. Second,
the precedence hole in **(b)**: an agent span that names a model already gets it
in `operation` in both dialects, which is symmetric and therefore not a bug
today, but is the thing option A would collide with.

**(j) The smallest experiment that would falsify this.** The recommendation
rests on one factual claim: *OpenInference states no agent identity as an
attribute, so an `identity` field would be single-dialect*. The claim is
supported by every artefact in this repo — `openinference.py` defines no such
key, and `openai_tool_call.jsonl`'s AGENT span carries only
`openinference.span.kind`, `input.value`, `input.mime_type` — and **not one of
those artefacts is instrumentor evidence.** `capture/backends.py:311` and
`:357` emit both agent spans by hand ("executing a tool is not an SDK call and
there is nothing for an instrumentor to wrap"), and
`genai_tool_call.provenance.md` says the `invoke_agent` span's attributes "remain
a judgement call". **The corpus contains no instrumentor-emitted agent span, in
either dialect, at all.** H1 is a question about a span kind we have never
observed in the wild.

So: **install an OpenInference instrumentation package for an agent framework
(one that wraps agent runs, not just the model client), run one tool-using agent
turn through `capture/`, and read the AGENT span's attribute keys.** If it emits
an agent-name attribute, the asymmetry dissolves, `identity` becomes a
cross-dialect-comparable field with real teeth, and option B — not C — is the
answer. If it does not, C's premise is confirmed by the only instrument that can
confirm it.

It costs one `pip install` and one agent turn, it is a human act and a halt
point (`ENVIRONMENT.md` network zone 4, `FIXTURES.md` §6), and it is the same
shape as the capture §12(j)/§14(g) already wants scheduled — the harness can
emit both dialects in one session, so H1's experiment rides along at close to
zero marginal cost. Recommend scheduling it there. It is **not** a gate:
§14(f)'s reasoning applies unchanged, and C is decidable today without it.

**(k) What this memo hands forward.**

1. **Reject option A** — it makes `operation` mean two things on one node kind
   (**e**), and its only corpus repair erases 22 tested cross-dialect
   assertions to protect 12 nodes (**f**).
2. **The asymmetry is real and measured**: 11 of 18 cross-dialect scenarios
   diverge, 0 today, and the corpus cannot see it because no conformance
   rendering carries the attribute yet (**f**).
3. **H1 must be decided before the freeze; C discharges it at zero cost.**
   §14's rule is right about H1 and its reason over-reaches for option B, which
   is additive and could land at `1.1` (**h**).
4. **Two defects found in passing, unfixed**: `SPEC.md` §3.1 promises a
   "retriever name" no dialect states, and an agent span naming a model already
   puts the model in `operation` in both dialects (**b**).
5. **No instrumentor-emitted agent span exists in this corpus, in either
   dialect** — every agent span in all three captures is written by
   `capture/backends.py`. Whatever is decided, that absence should be recorded
   beside §14(h) item 4's other measured absence (**j**).

**Decision: option C**, logged in `WORKPLAN.md` §3 (2026-09-10) and
implemented by batch H2. `operation` stays `None` for `agent`, `chain` and
`retriever` wherever no dialect states a tool or model name, and the
non-mapping is now a **stated rule in `SPEC.md` §3.1** — with the note that the
value survives verbatim in `raw.source` and that `unmapped_attributes` names the
key — rather than an adapter docstring. Option A is rejected on **(e)** and
**(f)**. The `retriever name` defect in **(b)** is fixed in the same batch, in
`SPEC.md` §3.1 and in the two documents that repeated it (`ADAPTERS.md`,
`CONTRACTS.md`); the precedence observation beside it is stated in §3.1 as a
precision rather than changed, because it is symmetric across both dialects and
therefore not a defect. What **(a)**–**(g)** describe is the state **before**
H2; nothing under `spanweave/` moved with it.

**Option B is the additive `1.1` path, and stays open on those terms.** Per
**(h)**, a new optional `Node.identity` is the additive case `CLAUDE.md` 7
permits after the freeze, so it does not have to land before it and is not
foreclosed by this decision — unlike option A, which the decision closes. What
would reopen it is the evidence **(j)** names and this corpus does not have: an
*instrumentor-emitted* agent span, in a second dialect, carrying a name
attribute. Until then the field would be one dialect's attribute under a
normalized name, which is a rename rather than a normalization. If B is ever
taken it arrives as a version bump's worth of announcement, not quietly: it
changes what `canonical()` compares and what every consumer written against `1`
sees (**h**), and it adds a key to all 22 stored `expected/graph.json` files and
a line to `FIXTURES.md` §4's test-enforced Compared list (**g**).
