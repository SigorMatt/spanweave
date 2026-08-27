# span_links

Two spans, carrying two OTel span links: one to a span **inside** this trace,
and one to a span in another trace entirely.

## Structure

Nodes: 1 `agent`, 1 `chain`.

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `parent` | explicit | `span.parent_span_id` | s0→s1 |
| `link` | explicit | `span.link` | s0→s1, s1→s9 |

Two things to read carefully.

**s0→s1 appears twice**, once as `parent` and once as `link`. That is normal
and informative: the same pair may be connected by several kinds of edge, and
a consumer that only trusts containment filters on kind (`SPEC.md` §3.8).

**s1→s9 points at a span that has no node here.** `link` is the one kind
allowed to leave the trace, because links routinely do; requiring the target
to be present would make the kind useless for the case it exists for
(`SPEC.md` §4). `graph.node("s9")` returns `None`, and that is the honest
answer.

Note the deliberate contrast with `orphan_parent`, which meets the identical
situation — a reference to an absent span — and does the **opposite**:
suppresses the edge and emits a diagnostic. A dangling parent means the trace
is incomplete, which is worth reporting; a dangling link is the normal case,
and reporting it would be reporting that the feature worked. `SPEC.md` §4.0
states the asymmetry and what follows from it for a consumer resolving ids.

No temporal edges: each sibling group has one member.

Node order: s0, s1.

## Payloads

All `absent`.

## Diagnostics

None. A cross-trace link is not a defect.

## Dialects

- [x] `openinference` — Phase 1
- [ ] `otel_genai` — **declared unrenderable** (`expected/coverage.json`)

Not because of the links. OTel span links are a record-level `links` field,
identical in both dialects and read by both adapters. The blocker is `s1`,
which this scenario pins as a **chain**.

That makes this the most expensive of the three `chain` declarations: it is the
only scenario in the corpus carrying an `EdgeKind.link`, so `link` edges — and
the adapter-supplied `basis` string that comes with them — are **untested
across dialects**. Recorded at `TASKS.md` 2.11 rather than left implicit.
