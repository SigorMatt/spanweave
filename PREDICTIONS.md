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

**Status: CONFIRMED — operational, scoped.** Resolved at 3.4, Phase 3.

A cost & latency attributor over the committed corpus — the consumer P1
describes — reads `usage`, timestamps, `operation` and the `parent`
edges, and **nothing that losslessness retains**. Established by
comparison rather than by inspection: the attribution of a graph with
payload `value`, payload `raw` and `RawRecord.source` removed is
**byte-identical** to the attribution of the graph it was built from, on
all 41 committed traces, with a non-vacuity floor asserting the strip
removed something each time.

**Measured at the size P1 names.** At 100,000 spans with 1,500-character
payloads: **970.4 MB built, 145.6 MB stripped — 85% of resident bytes are
bytes the consumer never reads.** The committed corpus alone gives 46.1%
retained and **understates the case by a factor of three**, because the
stripped size is flat in payload length (1,456 B/node at both 200 and
1,500 characters) while the built size is not. That understatement is why
the corpus figure was checked against a generated load input rather than
quoted.

**The friction is at peak, not at residency, and that distinction is the
finding.** The consumer can already drop every byte it does not read,
today, through the public API — `dataclasses.replace` over the public
frozen types plus `Graph.of`. What it cannot do is avoid *allocating*
them: `build()` returns only after the verbatim bytes exist.
`tracemalloc` across the same run — peak **1.05 GB** after the build;
after the strip, `current` falls to 145.6 MB and **peak rises to
1.07 GB**, because the strip itself allocates. So `retain_payloads=False`
/ `retain_raw=False` is **wanted as a build-time option** and would buy
nothing as a post-hoc one. That is a want rather than a preference: no
code a consumer can write reaches the reading.

**Class: operational**, as predicted. The graph's shape is unchanged and
a field is elided by request — but see the next paragraph, which is the
part the prediction did not anticipate and which "operational" alone
would hide.

**The remedy carries a latent shape cost, and P1's own `WORSE` condition
names it.** A stripped payload is
`Payload(state=present, value=None, raw=None)`, and `SPEC.md` §3.3
defines `present` as *"a payload was reported and carries content"*. It
carries none, and `Payload.has_content` still answers **True** — the
branch a harness reads. The other route, `Payload.absent()`, misstates in
the opposite direction: `absent` means *"the instrumentor emitted no
payload attribute at all"*, and it did. There is no third route, because
no state means *"reported, and elided by request"*.

This consumer needs no such state: it never publishes the stripped graph,
and its attribution is byte-identical either way. **But the option would
hand exactly that graph to a consumer that does publish it, and to one
that did not do the stripping and has no way to know it happened.** So
the operational remedy cannot ship without either a new `Payload` state
(**shape**) or a §3.3 statement about what `state` asserts on an elided
payload (**spec gap**). P1's `WORSE` reads *"needs … a 'was this elided?'
marker that doesn't exist"*, and P2's names `elided_by_option` in the
same words.

**`WORSE` is not the mark, and the reason is worth stating precisely.**
The condition is written about what *a consumer* needs, and no consumer
needed it — this one least of all, since it is the consumer that does not
need the fix. What was found is a property of the **fix**, reached by
implementing the measurement rather than the remedy. It is recorded here
rather than classified, because widening the test to cover *"what would
the predicted remedy require"* is exactly the boundary re-reading this
file exists to prevent. **Whoever implements `retain_payloads=False`
inherits it as a halt point, not as a detail.**

**Scope of the confirmation.** Five things bound it; the last three are
load-bearing.

- **The 100k figure was measured on a generated load input, not a
  trace.** It is synthesized, gitignored, never entered `fixtures/`, and
  is not captured. The largest committed trace is **nine spans**. What
  was measured is how memory scales with span count and payload length;
  that it scales says nothing about whether real traces reach that size.
- **One consumer, and the designer picked it.** The exam-picking problem
  this file exists to name. A consumer holding many graphs at once, or
  streaming, or reading payloads *and* usage, was not written.
- **The payload length is a setting**, and the retained fraction is
  entirely a function of it: 15.0% at 1,500 characters, 32.3% at 200,
  46.1% on the corpus. A corpus of short payloads makes P1 look weak, and
  did.
- **`usage` itself is barely exercised**, and this was its first
  exercise by any consumer. 16 of 107 nodes carry it, in 7 traces, all
  `llm`; `total_tokens` is reported on **2 nodes in one trace** and
  `usage.extra` on the same 2; no committed trace ever reports one token
  count without the other. Cross-dialect, `usage` is compared on **two
  scenarios and two fields**.
- **Losslessness lives in three places and P1 names two.**
  `Diagnostic.source` retains verbatim fragments that neither
  `retain_payloads` nor `retain_raw` covers — 18.6% of what survives the
  strip over the corpus, 31.9% over the three captured traces. Negligible
  on a generated input and not negligible on a real one.

**2b's negative evidence, carried with its scope.** The Phase 2b fleet
aggregator asked for no retention option (2.4, F1–F9: no retention item,
no memory item, nothing about losslessness being cost). That is real
evidence and it is negative — and it was **not P1's test**: fourteen
traces of a handful of spans, built one at a time, by a consumer that
never read `usage` and never read a timestamp. For scale, the *entire*
committed corpus — 39 traces, 107 nodes — is 501,785 bytes built. A
prediction about memory at 100k spans cannot be refuted by an input three
orders of magnitude below it. Corroboration, at a size that could not
have produced the friction.

**What would falsify this confirmation:** a `retain_payloads=False`
implementation that turns out not to move the peak either, which would
mean the allocation happens somewhere this measurement did not look; or a
real 100k-span trace whose payloads are short enough that the corpus's
46% is the representative figure after all.

Honest claim: *P1's friction occurred, in one confirmatory consumer, on a
generated 100,000-span input at a chosen payload length — measured as an
85% residency saving and a 1.05 GB peak unreachable through the public
API — and the operational remedy it names cannot be built without saying
something about payloads the model currently cannot say.*

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

**Status: REFUTED — scoped.** Resolved at 3.3, Phase 3.

A trajectory dumper over the committed corpus — the consumer P2 describes,
since it is the only one that must decide what a transcript line says for
each state — **did not collapse the five states**. It reaches a decision
table rather than `Payload.has_content`, which is P2's predicted collapse in
one method: `has_content` answers True for `present` and `truncated` and
False for the other three, i.e. "did I get a string or not".

**Measured by perturbation rather than asserted** (`TASKS.md` 3.2's
instrument): each state was re-rendered as each other state, one directed
pair at a time, and the whole-corpus sweep re-run and diffed. Of the twenty
collapses, **fourteen change the branch a reader acts on** and sixteen change
the output at all. `absent`↔`empty` is among the fourteen, which is §3.3's
central honesty claim holding up under a consumer that had a reason to care:
a tool that returned nothing failed to answer, and a tool whose output the
instrumentor never recorded is a hole in the telemetry, and scoring those
alike scores the tracing setup as if it were the agent.

**Scope of the refutation.** Four things bound it, and the last two are the
load-bearing ones.

- **One consumer, and the designer picked it.** P2 says *most* consumers.
  This is a sample of one, chosen for being the consumer that reads payloads
  — which is the exam-picking problem this file exists to name, in its purest
  form. A dashboard, a viewer, or a notebook was not tested and is exactly
  where P2's "most" would live.
- **The table is this consumer's design.** The perturbation shows the
  distinctions are load-bearing *given that table*; it cannot show that an
  independently written transcript would have drawn the same lines. What it
  does show is that the lines, once drawn, are not decorative.
- **`absent` and `redacted` were collapsed** — on the branch a harness reads,
  this consumer puts both on `unavailable` and only the printed explanation
  differs. That is P2's predicted behaviour, observed, on one pair of five.
- **Two states were barely exercised and one not at all.** `redacted` is 2
  payloads in one scenario in one dialect (the `otel_genai` adapter has no
  redaction signal, so it cannot produce one). `truncated` is **zero across
  all 41 committed traces**.

**`truncated` is not refuted — it had no opportunity to occur.** Neither
shipped adapter can emit it: OpenInference signals redaction with a marker
string and has no truncation signal, and the GenAI convention states none
either. So the state is unexercised rather than unused, and a fixture could
only produce one by being written to — which would make the consumer its own
exam (`AGENT.md` run loop, step 3). All four `truncated` collapses change
nothing at all, and that measures the corpus, not the consumer. **On
`truncated`, P2 is unresolved and this refutation says nothing.**

**The `WORSE` condition was not met.** No state the enum lacks was wanted:
`sampled_out`, `deferred` and `elided_by_option` never came up, and nothing
the consumer needed to say about a payload was unsayable. One sixth
*rendering* was needed and is not a sixth state — `present` with `value is
None`, §3.3's parse failure — reached from an existing state plus an existing
field, 2 payloads.

**What would falsify this refutation:** a consumer that reads payloads and is
*not* an audit-shaped one — a viewer, a dashboard, a notebook, or an eval
harness written by someone who did not read `SPEC.md` §3.3 first. If such a
consumer reads `Payload.value` and never `Payload.state`, P2 reopens on the
four exercised states. Separately, an adapter that can emit `truncated` — a
dialect with a truncation signal — would test the fifth for the first time.

Honest claim: *P2 survived a single confirmatory consumer over 41 committed
traces, which separated four of the five states on the branch a reader acts
on, collapsed `absent` against `redacted`, and never met a `truncated`
payload at all.*

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

**Status: UNRESOLVED.** Assessed at 3.5, Phase 3. Not refuted, not
confirmed. Tracked as `OPEN_QUESTIONS.md` §7.

**Two reasons, and the second is the one that matters.**

**First: the friction had no opportunity to occur.** Of the three
consumers written against this library, two could not have produced it —
the 2b fleet aggregator reads no edges of any kind, and the 3.4 cost
attributor reads only `parent`. The third, the 3.3 trajectory dumper,
reads `data` edges the telemetry **declared** and never compares two
values to decide that one flowed into the other (3.3 F-5, 3.4 O-d). Every
piece of evidence this phase produced concerns **declared** edges, and
this prediction is about **inferred** ones. Recomputed at 3.5: 12 `data`
edges over 11 of the 39 buildable traces, all `warrant=explicit`, all with
the single basis `tool_call_id in tool-result message`; the only `derived`
edges anywhere in the corpus are `temporal` ones. The inferred `data` edge
is **unexercised**, in the same sense `truncated` is unexercised for P2,
and for the same reason: nothing that ships can produce one. A prediction
about inference is not refuted by consumers that performed none.

**Second: the stated class is wrong, so this prediction cannot be resolved
until what it claims is corrected.** The entry classifies its own remedy
as a boundary case that is *"by the letter of the rule … operational"*,
because `--infer-data-edges` *"uses an existing `EdgeKind` and an existing
warrant"*. Both halves fail:

- **The combination does not exist and cannot be constructed.**
  `Edge(kind=data, warrant=derived)` raises `ValueError` —
  `spanweave/model.py`'s `ALLOWED_WARRANTS`, present since the first
  implementation commit (`d8e2c37`): *"data edges are explicit-only;
  refusing to build one with warrant 'derived' (SPEC.md §4.1). A computed
  relation never becomes an explicit one."*
- **The letter of the rule says the opposite.** `SPEC.md` §4.1: *"If a
  rule is ever added that infers a relation of an explicit-only kind, it
  does not become that kind — **it becomes a new kind, through a spec
  change**."* A new `EdgeKind` is a **shape** change and an `AGENT.md`
  halt point — not an operational option.

**This is contemporaneous, not drift.** `git show c266c9e` — the seed
commit — created `SPEC.md`, `PREDICTIONS.md` and `OPEN_QUESTIONS.md`
together, and §4.1 already carried the sentence above
(`git show c266c9e:SPEC.md`, lines 265–269) while P3 already carried its
class (`git show c266c9e:PREDICTIONS.md`, lines 108–112). They disagreed
on arrival, by one author, on one day.

So the choice this prediction frames does not exist as framed. It is not
*policy versus flag*; it is **keep the prohibition** versus **change
`SPEC.md` §4.1 and the model**, at a higher stated price than the entry
assumed. `OPEN_QUESTIONS.md` §7(d) warned against waving this through *"on
the technicality that it reuses an existing `EdgeKind` and warrant"* —
there was never such a technicality to wave it through on, and §7 carries
that as evidence.

**One data point against this entry's own premise, with its scope.** The
argument is that *"the warrant system already makes inference safe:
anything computed is labeled `derived`, and consumers filter on warrant."*
The second half is a claim about consumers, and this repo has exactly one
that reads `data` edges. **It does not filter on warrant** — it renders
every one as `(declared)`, a string literal — and it printed that over a
`derived` edge forced past the validator
(`tests/test_prediction_evidence.py`). Scope, and it is load-bearing: the
assumption is currently **free**, since no derived `data` edge can exist;
the warrant **is** in the serialized graph, so the consumer could filter
and chose not to; and it is **one** consumer, written by this repo. It is
nevertheless the only empirical test that premise has ever had, and it
failed one for one.

**What this cannot support.** That inferred `data` edges are unwanted — no
consumer that would want one was written, and two of three could not have.
That the prohibition is, or is not, stricter than the architecture
requires: §7(b)'s argument is untouched. That the matching parameters
could be made consumer-supplied — §7(c)'s decisive question, never
attempted.

**What would resolve it.** First, correct the class: an inferred `data`
relation is a **new `EdgeKind` through a spec change** unless §4.1 is
changed, and that correction is itself the halt. Then a consumer that
actually wants value-match inference — one not written by this repo, since
the designer also picks the exam — is what would confirm or refute the
substance.

Honest claim: *P3 was not tested in Phase 3 — two confirmatory consumers
and one adversarial one performed no value comparison and wanted no
inferred edge — and it is not resolvable as written, because the class it
assigns itself was contradicted by `SPEC.md` §4.1 in the commit that
created them both.*

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

**Status: CONFIRMED as to class — none, scoped; the "will never notice"
clause REFUTED.** Resolved at 3.5, Phase 3, against the two confirmatory
consumers. A split result, and both halves belong in the mark.

**Needed by neither.** Measured rather than asserted, over the 30
multi-node committed traces: rebuilding each graph through the public
`Graph.of` with the node tuple reversed — what a differently-ordering
library would hand a consumer — leaves **every per-node value and every
total unchanged in both consumers, 30/30**, once the step index and list
order are normalised. Nothing either consumer computes depends on the
order it was given. 3.4 O-e reached the same conclusion for the attributor
by reasoning (*"a cost rollup would have been just as correct with
non-deterministic node ordering, because it sums"*); this is that claim
measured, and extended to the dumper.

**Noticed by both — so the prediction's second clause is false.** The same
perturbation changes the **serialized output of both consumers on 30 of
30**. For the trajectory dumper the order *is* the product: it walks
`graph.nodes()` and numbers the steps, so the library's ordering is
transcribed wholesale. And that ordering is a **choice**, not a
consequence — on **22 of 30** traces two or more nodes were topologically
ready at once and `SPEC.md` §5.2's stated tie-break decided the order; on
**2 of 30** (`parallel_tools`, both dialects) two nodes reported the same
`started_at`, so the `node_id` rule decided it. Edge order reaches the
transcript too, on **2 of 30** (`parallel_tool_calls`, both dialects: the
results one call produced come out `('s2','s3')` or `('s3','s2')`), and
reaches the attributor on **0 of 30**. Every count is asserted in
`tests/test_prediction_evidence.py`.

**Where determinism earned its keep is the verification, not the
function** (3.4 O-e). P1's entire instrument is a byte-for-byte comparison
of two serialized attributions, and 3.3's central claim is that two
*different* inputs produce the same transcript. Both consumers' test
suites would fail without byte-identity.

**Scope of the confirmation, and the first bound is the load-bearing one.**

- **Neither consumer is one of the three this prediction names.** A
  viewer, a dashboard and an exploratory notebook are the class it is
  about; both consumers written are batch, file-in/file-out tools with
  golden test suites — the class **most** likely to notice. So this does
  not test the "most consumers" claim; it tests the hardest case for it,
  and the substantive clause held there anyway.
- **The class is `none`, so a right prediction produces no friction to
  observe.** Refutation would have been visible — a consumer whose
  correctness required byte-identity — and none appeared. Confirmation is
  only ever the absence of that, over a sample.
- **The designer picked both consumers**, and picked them to test P1 and
  P2. P4 was observed in passing by consumers aimed elsewhere.
- **No non-deterministic build was ever run.** `CLAUDE.md` 4 forbids one.
  The perturbation is a surrogate: it changes the order a consumer is
  *handed*, not the builder that chose it, and it is a **larger**
  perturbation than a plausible non-deterministic implementation would
  produce — which is why the 22/30 tie-break count is reported beside it,
  that count being measured on genuinely valid alternative orders.
- **Two consumers, one library, 41 committed traces**, the largest nine
  spans.

**The prediction's own instruction stands: keep determinism regardless.**
Nothing here proposes relaxing it, and nothing tested what relaxing it
would cost.

**What this cannot support.** Anything about a viewer, a dashboard or a
notebook — none was written. That a non-deterministic library would be
invisible: measured false for both consumers that exist. That the
perturbation models a real non-deterministic build — it models a
differently-ordered *graph*, not a differently-ordering *builder*.

**What would falsify this confirmation:** a consumer whose *results*, not
bytes, change with node order — most plausibly one that reads
`graph.nodes()` positionally, or takes "the first `llm` node" as meaning
the first one to run. Separately, one of the three consumers this entry
names — a viewer, a dashboard, a notebook — would be the first test of its
"most consumers".

Honest claim: *neither confirmatory consumer's results depended on
byte-identical determinism, both consumers' bytes did on 30 of 30 traces,
and neither consumer belongs to the class this prediction is about.*

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
