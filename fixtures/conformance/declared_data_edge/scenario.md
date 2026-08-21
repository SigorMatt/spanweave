# declared_data_edge

An `explicit` `data` edge: a producer→consumer relation that **the
instrumentor itself declared**.

## Status: seeded, with no dialect rendering yet

**OpenInference declares no producer→consumer relation.** There is no
attribute in the dialect that says "this span's output fed that span's input",
so there is nothing for an OpenInference adapter to transcribe, and this
scenario has no `dialects/openinference.jsonl`.

Writing one would mean inventing an attribute and asserting that OpenInference
emits it. That is precisely the failure `ADAPTERS.md` §1 forbids — the fixture
would be testing our imagination rather than the dialect — and a fixture that
lies about a dialect is worse than a missing one, because it passes.

So the scenario is seeded and its rendering waits for a dialect that really
emits such a declaration (Phase 2). Until then:

- the **mechanism** is covered at the builder level:
  `tests/test_build.py::test_a_declared_data_edge_is_transcribed_with_the_declared_basis`
  builds one from a `DeclaredDataEdge` on the seam and checks its warrant and
  basis;
- the **prohibition** is covered too:
  `tests/test_build.py::test_no_data_edge_appears_from_matching_values` gives
  two spans where one's output is byte-identical to the other's input, and
  asserts that no `data` edge appears.

## Expected structure, when a dialect for it arrives

Nodes: 2 (producer, consumer).

Edges:

| Kind | Warrant | Basis | Pairs |
|---|---|---|---|
| `data` | explicit | whatever field declared it | producer→consumer |

The `basis` must name the **source field**, not the rule: it is what lets a
consumer audit the edge rather than trust it.

## Why `data` is never derived

A `data` edge is the most consequential kind in the model — it is what
downstream tools treat as evidence. Matching an output string to an input
string needs a threshold, a normalization rule, and an encoding policy, none
of which are opinion-free, and shipping one default set of those choices would
be closer to semantics than anything else in the library (`SPEC.md` §4.2).

That prohibition is itself under review — `OPEN_QUESTIONS.md` §7 records that
it is stricter than the warrant system requires, and names it as a scope
decision rather than an architectural one. It is binding until decided.

## Dialects

- [ ] `openinference` — **not renderable**: the dialect declares no such relation
- [ ] `otel_genai` — Phase 2
