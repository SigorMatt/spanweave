# CONTRACTS.md — the permissively-typed serialized field inventory

`TASKS.md` 3.2, from the freeze instruction at 2.14: *before freezing
`schema_version`, audit every serialized field typed permissively (`JsonValue`,
free `str`) for a stated contract and an asserting test.*

## What this is, and what it deliberately is not

**It is an enumeration.** Every field that crosses the schema boundary and is
typed permissively, with what states it, what asserts it, and — where the answer
is "nothing" — that answer written down.

**It is not a set of contracts, and writing one here would be the defect this
file exists to record.** Phase 2 produced three findings of one species: a
property the library depends on that no document states and no test asserts
(2.14). Each was born the same way — one author wrote down one implementation's
behavior, and nothing had to agree with it. Stating a contract now for a field
no second implementation has ever had to agree with is that mechanism running
again, in the other direction. So a row whose evidence is missing says
**unstated, unmeasured** and stops. The resolution half is Phase 4, with dialect
three (`ROADMAP.md` Phase 4, `TASKS.md` Phase 3 blocker 3).

**Why it is Phase 3 and not Phase 4.** Publishing is what turns an unstated
serialized field into something strangers observe and pin behavior to. A
de-facto contract formed by observation is harder to correct than an unstated
one nobody has seen. Enumerating is cheap, needs no dialect, and is worth most
*before* `0.9.x`.

## Scope — what counts as permissively typed

A field is in scope when it **crosses the schema boundary** (it appears in a
graph document written by `spanweave/serialize.py`) **and** its model
annotation permits an open set of values:

- `JsonValue` (an alias for `Any`) — any JSON shape at all;
- a free `str` — any string;
- a `Mapping`, `dict`, `list` or `tuple` of anything — an open key or element
  vocabulary, even where the *values* are typed (`Usage.extra` is
  `Mapping[str, int]`: the ints are constrained, the keys are not).

Out of scope, and it is a type-level fact rather than a judgement: the closed
enums (`NodeKind`, `EdgeKind`, `Warrant`, `Status`, `PayloadState`,
`DiagnosticLevel`), and `int` / `float` / `bool` fields. `tests/test_contracts.py`
applies exactly this rule to the model and fails if a field appears on either
side of it without a row here.

**One field is excluded by the rule and named anyway, so its absence is not
mistaken for coverage:** `meta.adapters[].declared_confidence` is `float | None`,
so it is constrained by type — but `ADAPTERS.md` §2 states a range (`[0.0, 1.0]`)
that nothing enforces, and `SPEC.md` §6.1 branches on a minimum. That is the same
species of gap as the rows below, in a differently-typed field. It belongs to the
Phase 4 audit, and it is out of *this* enumeration only because widening the rule
to catch it would make the rule a judgement instead of a type test.

`RawRecord.line_number` and `Meta.schema_version` are model fields that are
**not** serialized at their object's path — the first deliberately (`SPEC.md`
§3.5: it depends on input order and the graph must not), the second because it is
written at the document root instead. Both are declared as such in the test, so
neither can quietly start or stop being written.

## The columns

**Stated** — a document says something about the *value* that a second
implementation could be held to: a rule, a vocabulary, a constraint, or an
explicit declaration that the field is free-form. **Naming a field and its type
in a `SPEC.md` block is not stating a contract**, and this column says `—` for
those. Where a statement is weaker than it looks, the *Relies on* note says so.

**Asserted** — measured at the schema boundary, not asserted from reading. The
method is below. A cell names one of three things:

- **test node ids** — tests that assert a *rule*: a property that holds for any
  input, so it survives a fixture being replaced;
- **`corpus pin`** — the value is compared against a committed expected graph or
  a fixture literal. A change is *detected*; nothing states what the value
  should be. A pin is real evidence and is not nothing, but it is not a
  contract, and for a cross-dialect field it is only worth what two independent
  adapters agreeing on it is worth;
- **`—`** — nothing. The field can be changed at the boundary and the suite
  stays green.

**Status** — derived mechanically from the other two, and checked:

| Status | Stated | Asserted |
|---|---|---|
| `stated + asserted` | yes | a rule test |
| `stated + pinned` | yes | `corpus pin` |
| `stated, unasserted` | yes | `—` |
| `unstated + asserted` | no | a rule test |
| `unstated + pinned` | no | `corpus pin` |
| `unstated, unmeasured` | no | `—` |

## Method — how "asserted" was measured

Each field was perturbed **in the serializer** — one field at a time, the value
changed or its type changed — and the whole suite was run. What went red is the
Asserted column; what stayed green is the finding.

This is the instrument that found the `Diagnostic.source` defect in the first
place: *no test asserted it for either unpaired code, so changing its type broke
zero tests* (2.14). It measures assertions on the **serialized** value, which is
the thing `0.9.x` publishes and the thing a stranger pins to.

**What it does not measure, stated so no row is over-read.** A field can be
asserted at the *model* level and still show `—` here — `meta.source_digest` and
`edges[].basis` both are. That is a real gap of its own (the serializer could
rename or drop the field and nothing would notice) but it is a *different* gap
from "nothing states or asserts this value anywhere", and the *Relies on* notes
keep the two apart.

Measured over the corpus and the captured fixtures at the commit that adds this
file; 39 perturbations, one per field plus three that were split per payload
side. The result is reproduced under *Measured* below, and the eleven green
fields are cross-checked against this table by the test.

---

## The inventory

### Root

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `schema_version` | `str` | `SPEC.md` §3.9, §7 | `tests/test_serialize.py::test_the_document_has_the_root_keys_and_says_which_schema`, `tests/test_serialize.py::test_a_freshly_built_graph_validates` | stated + asserted |
| `trace_id` | `str` | `SPEC.md` §7 | corpus pin | stated + pinned |

### `meta`

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `meta.spanweave_version` | `str` | — | — | unstated, unmeasured |
| `meta.source_digest` | `str \| None` | `SPEC.md` §3.9 | — | stated, unasserted |
| `meta.adapters[].id` | `str` | `ADAPTERS.md` §2 | — | stated, unasserted |
| `meta.adapters[].version` | `str` | `ADAPTERS.md` §2 | — | stated, unasserted |

### `nodes[]`

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `nodes[].id` | `str` | `SPEC.md` §3.6 | `tests/test_serialize.py::test_a_freshly_built_graph_validates`, `tests/test_conformance.py::test_every_rendering_builds_a_valid_graph` | stated + asserted |
| `nodes[].name` | `str` | `SPEC.md` §3.1 | corpus pin | stated + pinned |
| `nodes[].operation` | `str \| None` | `SPEC.md` §3.1 | corpus pin | stated + pinned |
| `nodes[].status_note` | `str \| None` | `SPEC.md` §3.1 | corpus pin | stated + pinned |
| `nodes[].attributes` | `Mapping[str, JsonValue]` | `SPEC.md` §3.2, `FIXTURES.md` §4.5 | `tests/test_conformance.py::test_a_dotted_erasure_names_a_key_that_exists`, `tests/test_conformance.py::test_no_declaration_outlives_the_disagreement_that_earned_it` | stated + asserted |
| `nodes[].inputs.mime` | `str \| None` | `SPEC.md` §3.3, `FIXTURES.md` §4.4 | `tests/test_conformance.py::test_a_declaration_that_names_state_cannot_erase_it`, `tests/test_conformance.py::test_the_cross_dialect_form_sets_aside_exactly_what_was_declared` | stated + asserted |
| `nodes[].inputs.value` | `JsonValue` | `SPEC.md` §3.3 | corpus pin | stated + pinned |
| `nodes[].inputs.raw` | `str \| None` | `SPEC.md` §3.3 | `tests/test_conformance.py::test_a_redacted_payload_keeps_the_marker_the_source_wrote` | stated + asserted |
| `nodes[].outputs.mime` | `str \| None` | `SPEC.md` §3.3, `FIXTURES.md` §4.4 | corpus pin | stated + pinned |
| `nodes[].outputs.value` | `JsonValue` | `SPEC.md` §3.3 | corpus pin | stated + pinned |
| `nodes[].outputs.raw` | `str \| None` | `SPEC.md` §3.3 | `tests/test_conformance.py::test_an_unparseable_payload_keeps_its_text_verbatim` | stated + asserted |
| `nodes[].usage.extra` | `Mapping[str, int]` | — | corpus pin | unstated + pinned |
| `nodes[].raw.source` | `JsonValue` | `SPEC.md` §3.5 | `tests/test_serialize.py::test_the_verbatim_source_round_trips_byte_for_byte`, `tests/test_determinism.py::test_every_record_of_the_worked_example_is_accounted_for`, `tests/test_conformance.py::test_every_rendering_accounts_for_every_record` | stated + asserted |
| `nodes[].raw.source_id` | `str \| None` | `SPEC.md` §3.5 | — | stated, unasserted |
| `nodes[].provenance.adapter_id` | `str` | `SPEC.md` §3.5 | corpus pin | stated + pinned |
| `nodes[].provenance.adapter_version` | `str` | — | — | unstated, unmeasured |
| `nodes[].provenance.dialect_note` | `str \| None` | `SPEC.md` §3.5 | — | stated, unasserted |

### `edges[]`

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `edges[].src` | `str` | `SPEC.md` §3.8 | `tests/test_serialize.py::test_a_freshly_built_graph_validates` | stated + asserted |
| `edges[].dst` | `str` | `SPEC.md` §3.8, §4.0 | `tests/test_serialize.py::test_a_dangling_link_is_allowed_because_links_leave_the_trace` | stated + asserted |
| `edges[].basis` | `str` | `SPEC.md` §3.8, §4.2.1, §4.3, §4.4 | corpus pin | stated + pinned |
| `edges[].adapter` | `str \| None` | `SPEC.md` §3.8 | — | stated, unasserted |

### `diagnostics[]`

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `diagnostics[].code` | `str` | `SPEC.md` §3.7 | `tests/test_codes.py::test_the_unpaired_codes_emit_the_object_the_spec_declares`, `tests/test_conformance.py::test_the_unpaired_diagnostics_name_the_tool_identically_in_every_dialect` | stated + asserted |
| `diagnostics[].message` | `str` | `SPEC.md` §3.7 | — | stated, unasserted |
| `diagnostics[].node_id` | `str \| None` | `SPEC.md` §3.7 | `tests/test_conformance.py::test_the_unpaired_diagnostics_name_the_tool_identically_in_every_dialect` | stated + asserted |
| `diagnostics[].source` | `JsonValue` | `SPEC.md` §3.7 | `tests/test_codes.py::test_the_unpaired_codes_emit_the_object_the_spec_declares`, `tests/test_conformance.py::test_the_unpaired_diagnostics_name_the_tool_identically_in_every_dialect` | stated + asserted |
| `diagnostics[].adapter` | `str \| None` | — | — | unstated, unmeasured |

### `annotations[]`

| Path | Type | Stated | Asserted | Status |
|---|---|---|---|---|
| `annotations[].namespace` | `str` | `SPEC.md` §8 | `tests/test_serialize.py::test_annotations_are_written_in_their_stated_order` | stated + asserted |
| `annotations[].node_id` | `str` | `SPEC.md` §8 | `tests/test_serialize.py::test_annotations_are_written_in_their_stated_order` | stated + asserted |
| `annotations[].key` | `str` | `SPEC.md` §8 | — | stated, unasserted |
| `annotations[].value` | `JsonValue` | `SPEC.md` §8 | `tests/test_serialize.py::test_annotations_round_trip_through_the_file` | stated + asserted |

---

## Relies on — what each field depends on that is not written down

One entry per row above, checked in both directions by the test. This is the
column the inventory exists for: not *"it is typed permissively"* but *what does
the library rely on that no document states and no test asserts?*

- `schema_version` — that a consumer can tell two serialized contracts apart by
  this value. It cannot: `"0.1"` names both the pre- and post-2.10
  `Diagnostic.source` contracts, and `0.9.x` publishes that. Nothing asserts
  that a change to what is serialized bumps it, and nothing could until the
  semantics are decided — which is `TASKS.md` 3.7, a halt.
- `trace_id` — that the id is the dialect's own, unchanged. §7 states which
  `trace_id` wins when an input carries several; nothing states that the value
  is transcribed rather than derived, and the boundary is pinned only.
- `meta.spanweave_version` — that it is `spanweave.__version__`, the version of
  the library that built this graph. No document says so, no test asserts it,
  and the serialized value can be rewritten with the suite green. It is the only
  field a consumer could use to correlate a graph with a release.
- `meta.source_digest` — that it is `sha256(input bytes).hexdigest()`, so a
  consumer can recompute it and compare. §3.9 states exactly that, and the only
  things measured are that a caller-supplied value passes through
  (`test_meta_records_the_adapter_and_the_digest_but_no_environment`, at the
  model) and that two different inputs differ
  (`test_the_digest_does_change_when_the_bytes_do`). Neither would notice the
  algorithm changing, or a prefix being added. The one use the field has is the
  one nothing checks.
- `meta.adapters[].id` — that it is the registered adapter's id, and that the id
  is stable, lowercase and space-free (`ADAPTERS.md` §2). It is the value a
  stranger reads to know which adapter read their trace. Nothing asserts either
  half, at the boundary or at the model.
- `meta.adapters[].version` — that it is the adapter's own version and moves
  independently of the library's (`ADAPTERS.md` §2). Unasserted; and nothing
  relates it to `nodes[].provenance.adapter_version`, which is the same fact
  written twice in one document.
- `nodes[].id` — that the §3.6 identity rule produced it and that ids are unique
  within the graph. Uniqueness and referential integrity are asserted by
  `validate()`; the *rule* is asserted at the model (`tests/test_ids.py`), not at
  the boundary.
- `nodes[].name` — that it is the operation name exactly as reported. See
  **F-B**: it is set aside by declaration in 16 of the 17 scenarios rendered in
  two dialects, and the 17th produces no graph — so `name` has **never** been
  compared across dialects, in any scenario, at any point in this project. Four
  renderings pin it. Nothing else touches it.
- `nodes[].operation` — that the tool, model or retriever name is written
  verbatim in the dialect's own spelling. Two dialects agree on it in 15 of 16
  compared scenarios, which is the strongest evidence any unstated field here
  has. What is unstated is the *name-space*: one captured trace carries
  `openai/gpt-oss-120b` and another `demo-embed`, and nothing says whether a
  provider prefix belongs in the value. `Diagnostic.source` now carries the same
  value on unpaired calls (§3.7), so a consumer sees it in two places.
- `nodes[].status_note` — that the error message is the reported one, verbatim,
  and is therefore *not* a matching surface. §3.10 says exactly that about error
  messages and says nothing about this field.
- `nodes[].attributes` — that `reported_kind` is the only key any adapter ever
  writes. §3.2 states it is the only key the *specification defines* and warns
  that a per-adapter key would become a per-adapter schema; nothing asserts that
  no adapter writes another one. The statement is one-directional and the gap it
  warns about is unguarded.
- `nodes[].inputs.mime` — that the value is the dialect's own mime string and
  that "indicates JSON" is decidable from it (§3.3 drives payload parsing off
  it). §3.3 gives two examples, not a vocabulary; `FIXTURES.md` §4.4 exists
  *because* two dialects spell it differently.
- `nodes[].inputs.value` — that it is the parsed payload when the mime is JSON
  and the string otherwise, and that its shape is the dialect's. Pinned per
  dialect through `expected/payloads/<dialect>.json`; declared dialect-varying in
  23 payload selectors across the corpus.
- `nodes[].inputs.raw` — that the unparsed source string survives, which is what
  makes a parse failure recoverable. Asserted through the redaction scenario
  only.
- `nodes[].outputs.mime` — as `inputs.mime`, and with **less**: the same
  perturbation that trips two declaration-mechanism tests on the input side trips
  only the pin on the output side. The asymmetry is not a decision anyone made.
- `nodes[].outputs.value` — as `inputs.value`.
- `nodes[].outputs.raw` — as `inputs.raw`, asserted through the malformed-JSON
  scenario only.
- `nodes[].usage.extra` — see **F-C**. That the key names are meaningful across
  dialects. They are not stated anywhere, they are each dialect's attribute
  suffix taken verbatim, the two adapters would therefore spell the same concept
  differently, `canonical()` compares the mapping, and it is **empty in every
  fixture in this repository**. The pin is on emptiness; the vocabulary is
  unmeasured by construction, exactly like `Edge.basis`.
- `nodes[].raw.source` — that the source record round-trips byte-for-byte
  (§3.5), which is the whole of losslessness. The best-covered field in the
  inventory: three rule tests, two of them structural gates.
- `nodes[].raw.source_id` — that it is the dialect's own id for the record, and
  therefore the thing `duplicate_source_id` is about. Present and non-null on
  every node of every fixture; erased by `canonical()`; asserted nowhere.
- `nodes[].provenance.adapter_id` — that it names the adapter that parsed *this*
  record, which is what makes a mixed-adapter graph readable. Pinned by one
  fixture literal.
- `nodes[].provenance.adapter_version` — that it is the adapter's version. No
  document states it, no test asserts it, and it duplicates
  `meta.adapters[].version` with nothing relating the two.
- `nodes[].provenance.dialect_note` — stated as deliberately free-form
  ("anything the adapter wants a human to know"), which is a real contract and
  not an absence. What is relied on is that free-form is *safe*: it is
  serialized, so whatever an adapter puts there is published. It is `None` on
  every node of every fixture and the string `dialect_note` appears in **no
  test** — a serialized field that has never carried a value.
- `edges[].src` — that it names a node in this graph. Asserted by `validate()`.
- `edges[].dst` — that it names a node in this graph **unless** the edge is a
  `link`, which may legally leave the trace (§4.0). Both halves asserted.
- `edges[].basis` — see **F-D**. That the string names the rule or field that
  produced the edge, in a vocabulary a consumer can match on across dialects.
  Four values exist; all four are the builder's; the two adapter-supplied bases
  are unreachable by the cross-dialect claim, and one of them is unreachable
  full stop.
- `edges[].adapter` — that it is the id of the adapter that asserted the
  relation, and `None` for a builder-derived edge. Erased by `canonical()`,
  asserted nowhere; the serialized value can be rewritten with the suite green.
- `diagnostics[].code` — that the code is the matching surface and comes from a
  closed registry. The best-stated field here: §3.7's table is checked against
  `diagnostics.CODES` in both directions.
- `diagnostics[].message` — that it is *not* a matching surface, so it can be
  improved without breaking a consumer. §3.10 states that rule for **error**
  messages; nothing states it for diagnostics, `canonical()` compares
  diagnostics by code and count so the message is outside the cross-dialect
  claim entirely, and every message in the suite can be rewritten with nothing
  red. `0.9.x` publishes it to strangers with no such notice.
- `diagnostics[].node_id` — that it is present exactly when the diagnostic is
  about one node. This is finding **F7** (2.4) — nothing states which codes are
  node-scoped — still unresolved, now visible as a field row.
- `diagnostics[].source` — see **F-E**. §3.7's table is the worked example of
  what "done" looks like *for two codes*. The catch-all row covering the other
  ten is stated and unasserted, and three of those ten do not match its words.
- `diagnostics[].adapter` — that it names the adapter that raised the
  diagnostic. Nothing states it, nothing asserts it, and the value can be
  invented at the boundary with the suite green.
- `annotations[].namespace` — that the consumer chose it and that `spanweave` is
  reserved (§8). The reservation is enforced at the API
  (`tests/test_graph.py::test_the_library_namespace_is_reserved`); the serialized
  value is asserted through the ordering test.
- `annotations[].node_id` — that it names a node of this graph. Nothing in
  `validate()` checks an annotation's target, unlike an edge's.
- `annotations[].key` — that annotations sort by `(namespace, node_id, key)`
  (§8). The only test that checks that order compares `(namespace, node_id)` and
  ignores `key`, so the third component of a stated sort key is unasserted, and
  the serialized key can be renamed with the suite green.
- `annotations[].value` — that it is JSON-serializable and survives a round trip
  (§8). Asserted.

---

## Measured — what a change at the schema boundary breaks

One perturbation per field, whole suite each time, at the commit that adds this
file. Reproduced so the Asserted column can be re-derived rather than trusted.

### The eleven fields nothing asserts

Changing any of these in `serialize.py` leaves the suite entirely green — **1179 passed, 2 skipped**, which is the suite as it stood immediately
before this file added its own:

```text
meta.spanweave_version
meta.source_digest
meta.adapters[].id
meta.adapters[].version
nodes[].raw.source_id
nodes[].provenance.adapter_version
nodes[].provenance.dialect_note
edges[].adapter
diagnostics[].message
diagnostics[].adapter
annotations[].key
```

Eleven of thirty-six. That is not a bug list — most of these fields are minor,
and one (`dialect_note`) is *stated* to be free-form. It is a measurement of how
far the permissive default reaches, and it is the same measurement that made
`Diagnostic.source`'s defect visible in Phase 2.

### The rest, with what went red

| Field | Distinct tests red |
|---|---|
| `schema_version` | 6 |
| `trace_id` | 2 |
| `nodes[].id` | 13 |
| `nodes[].name` | 1 |
| `nodes[].operation` | 1 |
| `nodes[].status_note` | 1 |
| `nodes[].attributes` | 5 |
| `nodes[].inputs.mime` | 3 |
| `nodes[].inputs.value` | 1 |
| `nodes[].inputs.raw` | 1 |
| `nodes[].outputs.mime` | 1 |
| `nodes[].outputs.value` | 1 |
| `nodes[].outputs.raw` | 1 |
| `nodes[].usage.extra` | 2 |
| `nodes[].raw.source` | 4 |
| `nodes[].provenance.adapter_id` | 1 |
| `edges[].src` | 5 |
| `edges[].dst` | 5 |
| `edges[].basis` | 1 |
| `diagnostics[].code` | 5 |
| `diagnostics[].node_id` | 1 |
| `diagnostics[].source` | 2 |
| `annotations[].namespace` | 1 |
| `annotations[].node_id` | 1 |
| `annotations[].value` | 1 |

Nine of these twenty-five go red in exactly one test, and in seven of the nine
that one test is the expected-graph comparison — a pin.

---

## Findings

Six rows carry more than a row. None of them is a contract; each is evidence a
Phase 4 contract would need.

### F-A. The permissive default reaches eleven of thirty-six serialized fields

The Phase 2 pattern, counted rather than described. Eleven fields cross the
schema boundary and can be changed with a green suite; four of those have no
document saying anything about their value either. `0.9.x` publishes all of
them.

### F-B. `nodes[].name` has never been compared across dialects

`canonical()` compares it. Sixteen of the seventeen scenarios rendered in both
dialects declare it dialect-varying in `expected/comparison.json`; the
seventeenth (`duplicate_span_ids`) is a scenario that must *not* build, so it
produces no graph to compare. The library's central claim — the same run,
described by any supported instrumentor, produces the same canonical graph —
has therefore never once been tested on `name`.

That is not a defect: `name` is the field two instrumentors are *least* likely
to agree on, which is why §4.4's declaration mechanism exists. It is a bound on
what the equivalence corpus proves, and it belongs on the record beside the "16
byte-identical canonical graphs" figure in 2.14, not underneath it.

### F-C. `Usage.extra` is a second `Edge.basis`, and 2.14 did not name it

Every property that makes `Edge.basis` unresolvable applies to `Usage.extra`'s
keys, and one more:

- **Adapter-supplied and dialect-derived verbatim.** Each adapter takes the
  attribute suffix after its own prefix. OpenInference's
  `llm.token_count.cache_read` becomes the key `cache_read`; the GenAI
  convention's `gen_ai.usage.cache_read_input_tokens` becomes
  `cache_read_input_tokens`. The same concept, two keys, and nothing in either
  adapter or any document says they should be one.
- **Compared.** `canonical()` keeps `usage`, so two dialects disagreeing on a
  key would fail equivalence.
- **Never non-empty.** `extra` is `{}` on every node of every conformance
  rendering and every captured trace in this repository. The disagreement is
  therefore unreachable: it cannot be observed by the corpus as it stands.
- **And nothing states the vocabulary at all.** §3.4's comment reads "cache
  reads, reasoning tokens, etc." — an illustration, not a key list.

No contract is written here, for 2.14's reason. What is recorded is that a
Phase 4 contract for this field is more likely than most to be a **shape**
change, because the honest resolutions — a stated key vocabulary, or a
declaration that keys are dialect-local and not comparable — both change what is
serialized or what `canonical()` compares. See *The halt condition*, below.

### F-D. `Edge.basis`, refined: the reference case is sharper than 2.14 recorded

2.14 recorded that both adapter-supplied bases are invisible to the
cross-dialect claim. Measured over all 39 buildable renderings, that
under-states it:

| `basis` | Kind | Supplied by | Stated | Asserted |
|---|---|---|---|---|
| `sibling start_time ordering` | `temporal` | builder | `SPEC.md` §4.3 | `tests/test_ordering.py` (model) |
| `sibling start_time ordering (tied, broken by node_id)` | `temporal` | builder | `SPEC.md` §4.3 | `tests/test_ordering.py` (model) |
| `span.parent_span_id` | `parent` | builder | `SPEC.md` §3.8 (as an example) | `tests/test_build.py` (model) |
| `tool_call_id` | `call_result` | builder | `SPEC.md` §4.4 | `tests/test_build.py` (model) |
| `tool_call_id in tool-result message` | `data` | builder | `SPEC.md` §4.2.1 (as a MUST) | `FIXTURES.md` §7 via `tests/test_docs.py` (model) |
| `span.link` | `link` | **adapter** (`SpanLink.basis` default) | nothing | `tests/test_openinference.py` (model) |
| — | `data` | **adapter** (`DeclaredDataEdge.basis`) | `ADAPTERS.md` §3 | **never produced** |

Two corrections to the record:

1. **No adapter emits a `DeclaredDataEdge` at all.** 2.14 says
   `DeclaredDataEdge.basis` is invisible "because `otel_genai` produces none".
   `openinference._data_edges` also returns `()`, and says why in its docstring:
   OpenInference never names both ends on one span either. So the field is not
   merely invisible to the cross-dialect claim — it is a required seam field
   that nothing has ever populated, in either dialect.
2. **Neither adapter has ever *chosen* a `SpanLink.basis`.** Both take the
   field's default, `"span.link"`. It is right in both, for the reason 2.14
   gives — it names an OTel record-level field rather than a dialect attribute —
   but no adapter author has yet made the decision the field exists to record.

The conclusion is 2.14's, unchanged and stronger: unresolvable today, Phase 4
with dialect three. What changes is the instrument. Dialect three does not test
the adapter-supplied basis vocabulary unless it emits an `EdgeKind.link` **and**
the corpus carries a `link` scenario it can render — which is currently blocked
by `span_links` pinning `kind: chain` (`expected/coverage.json`, and 2.16's
pending decision). A third dialect added without that is a third dialect that
leaves this row exactly where it is.

### F-E. `Diagnostic.source`'s catch-all row is stated and unasserted

§3.7's table names four codes and then says *everything else — the offending
fragment, verbatim*. Measured, the ten other codes emit:

| Code | `source` observed |
|---|---|
| `unknown_span_kind` | `str` — the dialect's kind string |
| `orphan_parent` | `str` — the missing parent's span id |
| `unmapped_attributes` | `list[str]` — attribute keys (declared) |
| `nonmonotonic_time` | `list[float]` — `[started_at, ended_at]` |
| `ordering_cycle` | `list[str]` — **spanweave node ids** |
| `missing_timestamp` | `null` |
| `payload_parse_failed` | `null` |
| `duplicate_source_id`, `malformed_record`, `multi_trace_input` | not emitted by any fixture |

Three of these do not match the catch-all's words. `missing_timestamp` and
`payload_parse_failed` carry **no fragment at all**; `ordering_cycle` carries a
list of ids the library computed, which is derived output rather than a verbatim
fragment of the input. `tests/test_codes.py` asserts the two unpaired codes, and
checks the table's other direction only as *declared shapes ⊆ real codes* — so
nothing would notice a code whose `source` shape changed, or one that started
carrying a fragment where it carries `null`.

This is the same species as the 2.10 defect it was written to fix, one level
down: the remedy stated the shape for the codes that motivated it and left a
prose catch-all over the rest.

### F-F. Three fields are the same fact written twice, with nothing relating them

`meta.adapters[].id` / `.version` and `nodes[].provenance.adapter_id` /
`.adapter_version` say the same thing at two granularities — deliberately, since
a graph may in principle carry nodes from more than one adapter. Nothing asserts
that a node's provenance names an adapter that appears in `meta.adapters`, and
three of the four fields are unasserted at the boundary. A consumer joining the
two would be relying on an invariant nobody has written or checked.

---

## The halt condition — tested, and not met

`TASKS.md` 3.2 halts **only if the inventory forces a type change**: a field
whose stated contract cannot be written without changing what is serialized.

**It is not met.** Every row above was recorded without writing a contract, and
no row required changing what is serialized in order to be *enumerated*. Naming
a field as unmeasured is not the same act as stating its contract, which is the
distinction the whole task rests on.

**Two rows are pre-registered as the likeliest to meet it in Phase 4**, and
naming them now is not the same as meeting the condition now:

- **`nodes[].usage.extra`** (F-C) — every honest resolution changes what is
  serialized or what `canonical()` compares.
- **`diagnostics[].source`** (F-E) — closing the catch-all means either stating a
  shape per code, which may change what three codes emit, or stating that some
  codes carry no source, which changes the table rather than the bytes. The
  second is cheap; the first is a shape change, and which one applies is not
  decidable without knowing what a third dialect's diagnostics look like.

**This is not a Phase 3 gate failure, and must not be recorded as one.** Phase
3's gate measures what a *confirmatory consumer* could not express (`AGENT.md`).
No consumer has run: 3.3 and 3.4 come after this task. Nothing here is evidence
for or against that gate in either direction.

## What Phase 4 inherits

The resolution half of 2.14's freeze instruction, and it needs an instrument
this phase does not have:

1. **Dialect three, run against the corpus**, which is already a freeze
   precondition (`ROADMAP.md` Phase 4). It is the only thing that can make an
   adapter-supplied vocabulary — `Edge.basis`, `Usage.extra`'s keys,
   `Node.operation`'s name-space — measurable rather than asserted by one author.
2. **A `link`-carrying scenario a second dialect can render** (F-D), without
   which dialect three leaves `Edge.basis` where it is.
3. **`schema_version`'s semantics** (`TASKS.md` 3.7), which every row above
   ultimately hangs from: whatever contract Phase 4 states, a consumer needs a
   value that tells it which contract it is holding.
4. **The eleven unasserted fields** (F-A) — for each, either a rule test at the
   boundary or a written statement that the field is free-form, as
   `dialect_note` already has.
