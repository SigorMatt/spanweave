# PREDICTIONS.md — where this model is probably wrong

Committed **before** the falsification work begins, so Phases 2–3 confirm or
refute something stated in advance instead of ratifying a design after the fact.

## Why this file exists

`DESIGN.md` §1 sets the shape test: *the library's shape is right when a use it
wasn't designed for needs no changes to it.* `ROADMAP.md` turns that into a gate
— run in Phase 2, confirmed in Phase 3, and decided at the Phase 4 freeze.

But every judgement call in the seed specs was reached by asking what **one**
consumer — a security analyzer over agent traces — needed. Origin doesn't
determine generality: plenty of good abstractions were extracted from a single
use case. It does, however, determine *where to look for the bias*, and it is
the whole reason the gate exists at all.

There is a specific failure mode this file guards against: **the designer also
picks the exam.** Consumers chosen after the model exists, by the process that
built the model, are the uses already known to work. Writing the predictions down
first is what makes Phase 3 a test rather than a demonstration.

## How a prediction resolves

Each is marked at the phase named in *When predictions resolve* (below):

- **CONFIRMED** — the predicted friction occurred.
- **REFUTED** — it didn't; the model was more general than expected here.
- **WORSE** — friction occurred, and it was a *shape* problem, not the
  operational one predicted. This is the outcome that blocks the freeze.

## The shape / operational distinction (binding)

Not every change a consumer wants is a model failure. The line — and it must be
drawn **now**, because drawn later it becomes a rationalization for whatever
happened:

- **Shape change** — a new field, `NodeKind`, `EdgeKind`, warrant, `Payload`
  state, `Diagnostic` code, or query primitive. Something the model cannot
  currently express. **This is a model failure. Hard gate: zero, or the model is
  fixed before the schema freezes.**
- **Operational option** — payload retention, multi-trace handling, laziness,
  output verbosity. Changes what you *keep* or *how you get it*, never what a
  graph *is*. Permitted, additive, and recorded here.
- **Spec gap** — a need the model *could* express with no new field, kind,
  warrant, `Payload` state, `Diagnostic` code or query primitive, but which
  nothing populates because no document asks for it. Neither shape nor
  operational: the remedy is a spec change plus an adapter change, not a model
  change. Found in practice at Phase 2b (see O1 below); use it where it fits
  rather than forcing the binary. A candidate already exists: 2.4's F7 (nothing states which diagnostic
  codes are node-scoped) has the same structure and was classified
  operational only because this category did not yet exist. Re-read it
  against this definition once 2a has exercised the category.

  **Amended at 2.10:** a spec gap can still carry a **shape cost** when the
  permissive field is a *serialized* one. O1's remedy needed no new kind,
  state, warrant or code — but `Diagnostic.source` is serialized, so a value
  changed type on a public contract. "The model can express it" is not the
  same as "the change is free". Check whether the permissive field crosses the
  schema boundary before classifying.

The test for which one you're looking at: *could an existing graph.json express
the consumer's need, if it had been built with different options?* If yes,
operational. If the consumer needs a field that cannot exist, shape.

---

## P1 — Mandatory losslessness will be pure cost to some consumers

**Prediction.** `CLAUDE.md` 2 requires every node to retain its verbatim source
record. A cost/latency attributor needs `usage` and timestamps and nothing else;
retaining full payloads for a 100k-span trace is memory it has no use for. It
will want `retain_payloads=False` or `retain_raw=False`.

**Origin bias.** Losslessness is load-bearing for an *audit* consumer, which must
be able to show its work. It is dead weight for an aggregation consumer.

**Class if it occurs:** operational. The graph's shape is unchanged; a field is
elided by request.

**What would make it WORSE:** if a consumer needs losslessness to be *selective*
per node kind, or needs a "was this elided?" marker that doesn't exist. That is
a `Payload` state or `Meta` field — shape.

**Status:** open.

---

## P2 — The five payload states are over-specified for most consumers

**Prediction.** `absent` / `empty` / `redacted` / `truncated` / `present` exists
because a security analyzer must distinguish "we weren't told" from "there was
nothing" in order to degrade honestly. Most consumers will collapse all five to
"did I get a string or not" and never look at the state field.

**Origin bias.** The distinction is load-bearing for exactly one kind of claim —
honest unavailability — and that claim is trifecta-lens's.

**Class if it occurs:** none. An unused field is not a design failure; it is a
cost paid by the model, not by the consumer. Predicted outcome is REFUTED-as-
harmless rather than friction.

**What would make it WORSE:** if a consumer wants a state the enum lacks —
`sampled_out`, `deferred`, `elided_by_option` (see P1). Shape.

**Status:** open.

---

## P3 — The prohibition on inferred `data` edges is stricter than the architecture requires

**Prediction.** `SPEC.md` §4.2 forbids inferring a `data` edge from value
comparison, absolutely. But the warrant system already makes inference safe:
anything computed is labeled `derived`, and consumers filter on warrant. A
consumer that wants "output of A appears verbatim in input of B" as a `derived`
`data` edge is asking for something the model can already express honestly.

**Origin bias — and this is the sharpest one.** The prohibition is not there
because the architecture demanded it. It is there because value-matching is
trifecta-lens's core analysis, and the seed spec reserved that territory for it.
That is a product decision wearing an architectural argument's clothes, and it
should be named as such.

**Class if it occurs:** boundary case, and deliberately flagged as one. Adding
`--infer-data-edges` uses an existing `EdgeKind` and an existing warrant, so by
the letter of the rule it is operational. But it changes what the library is
*willing to assert*, which is closer to policy than to plumbing. **If this one
fires, do not wave it through on the operational technicality** — take it to
`OPEN_QUESTIONS.md` §7 and decide it deliberately.

**Status:** open. Tracked as `OPEN_QUESTIONS.md` §7.

---

## P4 — Byte-identical determinism is unnecessary for most consumers

**Prediction.** Determinism is a hard invariant because CI gating and
cross-run diffing require it. A viewer, a dashboard, or an exploratory notebook
does not care and will never notice.

**Origin bias.** Determinism serves auditability, which serves the security
consumer.

**Class if it occurs:** none. This is a cost the library pays to keep a property
that is expensive to add later and cheap to maintain now. Keep it regardless of
the finding — but record honestly that it was not what made the consumers work.

**Status:** open.

---

## P5 — "One trace = one graph" is the most likely genuine shape failure

**Prediction.** `SPEC.md` §7 fixes one input to one trace to one graph. Any
fleet- or cohort-level consumer — "how often does this tool fail across 10,000
runs", "did latency regress after the prompt change" — needs many traces at once.
It will want `build_all()` returning several graphs, or cross-trace linking, or
an aggregate type.

**Origin bias.** trifecta-lens analyzes one run at a time. Single-trace scope was
never questioned because its only consumer never needed anything else.

**Class if it occurs:** **shape**, most likely. A multi-graph return type or
cross-trace edges cannot be expressed by an existing `graph.json`. This is the
prediction that would block the freeze, and it is therefore the one that must be
deliberately provoked rather than avoided — which is why the adversarial
consumer that attacks it runs in **Phase 2**, alongside the second dialect,
while nothing is frozen and every fix is a diff (`ROADMAP.md` Phase 2b).

**Status: REFUTED — scoped.** Resolved at 2.4, Phase 2b.

A fleet aggregator over 14 real traces (3 models, 5 graph shapes) required
none of P5's predicted remedies. Cross-trace edges were not merely unused but
never wanted (2.4 finding F2). `build_all()` and an aggregate type were not
needed: the consumer built each graph independently and summed over them.

**Scope of the refutation.** The consumer was a counting rollup, which
*structurally* cannot need cross-trace linking — it sums over graphs and never
relates them. The adversarial consumer was chosen by the same person who wrote
the prediction, and it could not have falsified it. The fleet was also
one-turn, so depth is untested.

**What would falsify this refutation:** a consumer that *relates* traces
rather than counting over them — retry detection, session reconstruction, or
comparing the same prompt across models (this fleet contains `two_cities`
under three models). If any such consumer needs a cross-trace representation,
P5 reopens.

Honest claim: *P5 survived a one-turn fleet of fourteen traces across three
models, tested by a counting consumer in one dialect.*

---

## When predictions resolve

- **P5** — end of Phase 2b (two-day timebox), regardless of what the aggregator
  achieved. A timebox that expires without a verdict is still a verdict.
- **P1, P2, P3, P4** — Phase 3, with the confirmatory consumers.
- **All five must be marked before the freeze**, which is Phase 4. The freeze is
  the decision these predictions exist to inform; marking them afterwards would
  be documentation, not evidence.

Resolving all five costs roughly an hour — five entries, three possible markers.
**"No time" can therefore never be the true reason to skip them.** If they get
dropped, the stated reason will be schedule and the real reason will be that
writing **WORSE** next to your own design is uncomfortable. `ROADMAP.md`'s cut
order names them as never-cut for exactly that reason: a `PREDICTIONS.md` with
predictions and no outcomes is worse than never having written one — a visible
promise of rigor, unkept, read as theater by precisely the audience it was meant
to persuade.

---

## Related, tracked elsewhere

- **Node granularity** — whether LLM messages are nodes or payload content is the
  largest open question about the model's shape, and it pulls hardest between the
  security use case and the cost/eval ones. Tracked as `OPEN_QUESTIONS.md` §2;
  not duplicated here.
- **Attribute normalization breadth** — `OPEN_QUESTIONS.md` §5 already names
  Phase 3 as its evidence source: whatever both example consumers reach into
  `raw` for is a normalization gap.

## Adding a prediction

Anyone may add one, at any time, **before the phase that would test it**. A
prediction added after its test has run is not a prediction and must be recorded
as an observation instead — in a separate section, plainly labeled. The value of
this file is entirely in its timestamps.

---

## Observations — found after the test, not predicted

These are **not predictions.** They were found during Phase 2b, after the work
that would have tested them began, and are recorded separately because a
prediction written after its test is an observation and this file's value is
entirely in its timestamps.

### O1 — a requested-but-unfulfilled call has no representation

Found at 2.4 (finding F5). An unfulfilled call can be attributed to the model
that asked (diagnostic `node_id` → llm node → `operation`) but **not to the
tool it named**, because a call that never ran has no node. Per-tool
requested-vs-fulfilled rollup — a question a fleet tool obviously asks — is
not answerable from `graph.json`.

A consumer must instead walk
`outputs.value["choices"][0]["message"]["tool_calls"][…]["function"]["name"]`,
re-implementing the adapter's pairing logic against one dialect's payload
shape. Against a second dialect the paths do not merely differ, they disagree on
container type at the first step: `outputs.value` is a JSON object in
OpenInference and an array in OTel GenAI.

**Classification: spec gap, not shape.** `Diagnostic.source` is `JsonValue`, so
an adapter could carry `{call_id, operation}` today with no new field, kind, or
halt point. The model permits it; nothing populates it; no document asks for
one. That is a third category the shape/operational test above does not cover,
and it should be used where it fits rather than forcing a binary.

**Status: RESOLVED — scoped, and partly self-refuting.** Settled at 2.10,
Phase 2a, against two dialects. `unpaired_tool_call` was rendered in
`otel_genai`, both graphs were built, and the output was inspected.

1. **From the graph alone the requested tool cannot be named — in neither
   dialect, and they agree exactly.** Both emit the same diagnostic, identical
   but for the adapter id. The call **id** appears three times — `source`,
   inside `message`, and as the `node_id` of the asking span — and the tool
   **name** appears zero times. A call that never ran has no node, so
   `operation`, where a tool's name lives (`SPEC.md` §3.2), has nowhere to be.
   One asymmetry, and it is the kind that makes a consumer look portable when
   it is not: OpenInference *mentions* the name in a second diagnostic, because
   `unmapped_attributes` lists the key
   `llm.output_messages.0.message.tool_calls.0.tool_call.function.name` — as a
   **key**, never a value. GenAI carries it inside the payload and names it in
   no diagnostic at all. A consumer scraping names out of diagnostic key lists
   works against dialect one and finds nothing in dialect two.

2. **The payload paths are not the same path.** OpenInference reaches the name
   at `outputs.value["choices"][i]["message"]["tool_calls"][j]["function"]["name"]`
   and the id at the same path's `[j]["id"]`; OTel GenAI reaches the name at
   `outputs.value[i]["parts"][j]["name"]` where `parts[j]["type"] ==
   "tool_call"`, and the id at that path's `[j]["id"]`. `outputs.value` is a
   **dict** in one and a **list** in the other. No prefix in common, so no
   single expression reaches both.

3. **Loud failure, not a confident zero — and this partly refutes O1 as
   written.** Measured in both directions on the two graphs this scenario
   builds: the OpenInference path against `otel_genai` raises `TypeError: list
   indices must be integers or slices, not str`, and the usual defensive
   `.get()` chain raises `AttributeError: 'list' object has no attribute
   'get'`, because `.get` on a list is an `AttributeError` rather than a miss;
   the OTel GenAI path against `openinference` raises `TypeError: string
   indices must be integers, not 'str'`. O1 said the walk "does not raise — it
   reports a confident zero." **It raises.** The confident zero is still real,
   but its **mechanism is the consumer's own error handling, not a silent
   shape mismatch**: any `try/except` around the walk — and there will be one,
   since trace payloads are untrusted input (`SECURITY.md`), and
   `examples/fleet_aggregate` already wraps at trace granularity for exactly
   that reason — converts the loud failure into an empty result. So the gap is
   **weaker than O1 claimed and still a gap**: a portable consumer *can*
   detect this today, if it chooses not to swallow it.

**Remedy taken.** `Diagnostic.source` on `unpaired_call` and `unpaired_result`
changed from a bare id to `{"call_id", "operation"}`, and `SPEC.md` §3.7 now
states `source`'s shape per code where it stated none. The result, which is
the point of the exercise, is byte-identical in both dialects:

```json
{"code": "unpaired_call",   "node_id": "s1", "source": {"call_id": "call_a", "operation": "lookup"}}
{"code": "unpaired_result", "node_id": "s2", "source": {"call_id": "call_b", "operation": "other"}}
```

No payload is walked, so the consumer is one line and the same line in every
dialect. `examples/fleet_aggregate`'s `unfulfilled_calls.by_tool` was empty
for a whole phase and now reconciles against the same total as `by_model`; a
dialect that states an id and no name buckets under `(dialect named no tool)`
rather than shrinking the total, because a rollup that silently drops what it
cannot label is F5 one layer up.

**What the spec-gap classification got right, and what it missed.** Right: the
remedy needed no new `NodeKind`, no new `EdgeKind`, no new warrant, no new
`Payload` state and no new `Diagnostic` code, so it was not an `AGENT.md`
model-change halt point; the model permitted the fact, nothing populated it,
no document asked for one, and the fix was a spec change plus an adapter
change — exactly the category as defined. Missed: the cost. `NormalizedSpan`
gained a field (`call_names`) and a **serialized** value changed type on a
public contract, which is why the change is recorded at TASKS.md 2.14 and
classified **shape** — "not a halt point" is not "not a shape change", and
Phase 3's gate is zero shape changes. The category held; the assumption that
it came for free did not.
