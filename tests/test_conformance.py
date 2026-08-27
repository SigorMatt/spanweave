"""The conformance corpus (TASKS.md 1.9) -- the executable spec.

Every rendering in `fixtures/conformance/` is built and compared against the
**one** canonical graph its scenario declares — *every* rendering, not the
first one, which is what makes this the cross-dialect claim rather than a
round-trip of a single dialect (`TASKS.md` 2.7).

A rendering whose dialect has no registered adapter cannot be built. It is
**skipped with a reason**, never quietly dropped, and the header line from
`conftest.py` names it on every run. That state is transitional — 2.8 renders
a dialect, 2.9 adapts it — and the tripwire below is what stops it becoming
permanent.

If a scenario fails, the fix is upstream. Editing an expected graph to match
new code is how a corpus dies (`FIXTURES.md` §4, §8).
"""

import json

import pytest

import spanweave
from spanweave.errors import ERROR_CODES, SpanweaveError
from spanweave.serialize import canonical_bytes, dumps, to_document, validate
from tests import determinism
from tests.conformance import (
    CORPUS,
    DECLARABLE_PAYLOAD_FIELDS,
    DIALECTS,
    DIALECTS_PENDING_CORPUS_COVERAGE,
    Rendering,
    adapter_backed,
    canonical,
    renderings,
    scenarios,
    unsupported,
)

SCENARIOS = scenarios()
BUILDABLE = [s for s in SCENARIOS if s.dialects and s.expected_error is None]
FAILING = [s for s in SCENARIOS if s.expected_error is not None]
PENDING = [s for s in SCENARIOS if not s.dialects]

# The unit of the equivalence claim: one dialect file of one scenario. Both
# lists carry EVERY rendering present, including ones no adapter can read --
# those become visible skips inside `built()`, which is the point (§4.3).
BUILDABLE_RENDERINGS = renderings(BUILDABLE)
FAILING_RENDERINGS = renderings(FAILING)

# The seed corpus, from FIXTURES.md §3. Listed here as well so that a scenario
# quietly disappearing from the corpus fails a test rather than nothing.
STRUCTURAL = (
    "single_tool_call",
    "llm_tool_llm",
    "parallel_tools",
    "parallel_tool_calls",
    "nested_agents",
    "retriever_and_embedding",
    "span_links",
    "declared_data_edge",
)
DEGENERATE = (
    "missing_payloads",
    "empty_payload",
    "redacted_payload",
    "unpaired_tool_call",
    "orphan_parent",
    "clock_skew",
    "unknown_kind",
    "malformed_payload_json",
    "duplicate_span_ids",
    "cyclic_parents",
    "shuffled_order",
    "tool_call_history_echo",
    # Added at 2.10, not seeded: the corpus was 18-of-18 `status: "ok"` while
    # 20 real tool spans were 19 `unset` and 1 `error` (finding F6).
    "unset_and_error_status",
)


def ids(collection):
    return [scenario.name for scenario in collection]


def labels(collection):
    return [rendering.label for rendering in collection]


def built(rendering):
    """Build one rendering, or skip loudly if nothing can read its dialect.

    The skip is inside the test rather than a filter on the parametrization on
    purpose: a filtered-out rendering leaves no trace in the run, and "we chose
    not to check this" must not look like "there was nothing to check".
    """
    if not rendering.supported:
        pytest.skip(rendering.skip_reason)
    return spanweave.build(rendering.path)


# --------------------------------------------------------------------------
# The corpus itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", STRUCTURAL + DEGENERATE)
def test_every_seeded_scenario_exists(name):
    assert (CORPUS / name / "scenario.md").exists()


def test_the_corpus_holds_nothing_undeclared():
    # A scenario nobody described is a scenario nobody can review.
    assert sorted(s.name for s in SCENARIOS) == sorted(STRUCTURAL + DEGENERATE)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
def test_every_scenario_describes_itself(scenario):
    text = (scenario.path / "scenario.md").read_text(encoding="utf-8")
    assert text.startswith(f"# {scenario.name}")
    # Described semantics-free (FIXTURES.md §2): a scenario is a shape, not a
    # story about an attacker or a leak.
    for forbidden in ("attacker", "malicious", "exfiltrat", "victim"):
        assert forbidden not in text.lower()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_dialect_is_either_rendered_or_declared_unrenderable(scenario, dialect):
    """Silence is a failure (`FIXTURES.md` §4.3).

    Without this, "we could not express this in that dialect" and "somebody
    forgot" look identical, and a dialect's coverage could rot away one file
    at a time with nothing noticing.
    """
    rendered = scenario.rendering(dialect) is not None
    reason = scenario.declared_unrenderable(dialect)
    assert rendered != (reason is not None), (
        f"{scenario.name} must either render {dialect} or declare in "
        f"expected/coverage.json that it cannot, with a reason"
    )
    if reason is not None:
        # A declaration without a reason is just a missing file with extra
        # steps. The reason is what a reviewer checks.
        assert len(reason) > 20


FIXTURES_MD = CORPUS.parent.parent / "FIXTURES.md"


def _compared_bullet():
    """The `**Compared:**` bullet of `FIXTURES.md` §4, as text."""
    text = FIXTURES_MD.read_text(encoding="utf-8")
    start = text.index("- **Compared:**")
    return text[start : text.index("\n\n", start)]


def test_the_compared_list_names_every_field_that_is_compared():
    """`FIXTURES.md` §4's Compared list must be exact, not illustrative.

    It has been wrong twice in the same direction: `mime` was compared and
    unlisted for two phases, `attributes` for three. Neither was a drafting
    slip. A field is added to the model, `canonical()` keeps it because
    keeping is the DEFAULT, and prose is not where anyone looks -- so the gap
    is only found when a second dialect disagrees on it, which is years of
    latency for a contract error.

    This closes the loop the other way round: the code is the source of truth
    for what is compared, and the document must keep up with it.
    """
    scenario = next(s for s in BUILDABLE if s.name == "llm_tool_llm")
    # No `erase`: a scenario's declaration is orthogonal to what the contract
    # says is compared, and passing one here would hide `name`.
    graph = canonical(to_document(spanweave.build(scenario.rendering("openinference"))))
    bullet = _compared_bullet()

    kept = set()
    for node in graph["nodes"]:
        kept |= set(node)
        for side in ("inputs", "outputs"):
            kept |= set(node[side])
    for edge in graph["edges"]:
        kept |= set(edge)

    unlisted = sorted(field for field in kept if f"`{field}`" not in bullet)
    assert unlisted == [], (
        f"canonical() compares {unlisted}, which FIXTURES.md §4's Compared "
        f"list does not name. The list is exact, not illustrative -- add the "
        f"field to the document, or stop comparing it."
    )


def test_the_compared_list_names_nothing_that_is_erased():
    # The other direction, and the cheaper mistake to make while fixing the
    # first: a list that names an erased field would read as an assertion the
    # corpus makes and does not.
    bullet = _compared_bullet()
    for field in ("provenance", "adapter", "source_digest", "spanweave_version"):
        assert f"`{field}`" not in bullet, (
            f"the Compared list names {field!r}, which canonical() erases"
        )


def test_a_declared_unrenderable_dialect_really_has_no_rendering():
    # §4.3's other half. "Silence is a failure" is enforced only over
    # `DIALECTS`, which does not yet name `otel_genai` -- so until 2.13 flips
    # it, nothing would notice a scenario that BOTH renders a dialect and
    # declares it unrenderable. That contradiction is worse than either half
    # alone: the corpus would be testing the rendering while telling a reader
    # it does not exist.
    for scenario in SCENARIOS:
        for dialect in scenario.coverage:
            if scenario.declared_unrenderable(dialect) is None:
                continue
            assert scenario.rendering(dialect) is None, (
                f"{scenario.name} declares {dialect} unrenderable and renders it anyway"
            )


def test_the_corpus_is_not_uniformly_ok():
    # Finding F6 (`TASKS.md` 2.4), as a tripwire rather than a note. The 2b
    # consumer measured this corpus against real telemetry: every tool span
    # here was `ok` (18 of 18), and of 20 real tool spans none was (19 `unset`,
    # 1 `error`). A consumer that computes a success rate against the corpus
    # alone therefore reads a confident zero in production, and no test inside
    # the corpus could see it.
    #
    # This does not make the corpus representative -- nothing here can. It
    # makes the gap un-reintroducable: delete `unset_and_error_status` and this
    # goes red rather than quiet.
    statuses = set()
    notes = 0
    for rendering in BUILDABLE_RENDERINGS:
        if not rendering.supported:
            continue
        for node in to_document(spanweave.build(rendering.path))["nodes"]:
            if node["kind"] == "tool":
                statuses.add(node["status"])
            notes += node["status_note"] is not None
    assert {"unset", "error"} <= statuses, (
        f"every tool span in the corpus is {sorted(statuses)}; real telemetry "
        f"is not (finding F6)"
    )
    assert notes, "no node in the corpus carries a status_note"


def test_no_scenario_is_currently_unrenderable():
    # `declared_data_edge` was the only one, on the stated grounds that
    # OpenInference declared no producer->consumer relation. It does, in every
    # multi-turn trace (SPEC.md §4.2.1), so the scenario was rendered and its
    # coverage.json deleted -- which is the §4.3 lifecycle working.
    #
    # Kept as a tripwire: a new unrenderable scenario has to be argued for
    # rather than merely added, and the reason has to survive being checked
    # against observed output.
    assert ids(PENDING) == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
def test_a_scenario_expects_exactly_one_outcome(scenario):
    # Exactly one of graph.json or error.json -- never both, never neither
    # (`FIXTURES.md` §1). Neither would be indistinguishable from an
    # unfinished fixture; both would be a contradiction.
    has_graph = (scenario.path / "expected/graph.json").exists()
    has_error = scenario.expected_error is not None
    if not scenario.dialects:
        assert not has_graph and not has_error
        return
    assert has_graph != has_error


# --------------------------------------------------------------------------
# Declared dialect-varying payloads (FIXTURES.md 4.4)
# --------------------------------------------------------------------------

DECLARING = [s for s in SCENARIOS if s.declaration]


def test_only_dialect_files_live_under_dialects():
    # `scenarios()` treats every file in `dialects/` as a rendering, keyed by
    # its stem. A stray note or backup there would become a phantom dialect
    # that skips forever -- so provenance notes live beside `scenario.md`.
    for scenario in SCENARIOS:
        for path in scenario.dialects:
            assert path.suffix in (".jsonl", ".json"), (
                f"{scenario.name}: {path.name} is not a rendering; keep notes "
                f"outside dialects/"
            )


@pytest.mark.parametrize("scenario", DECLARING, ids=ids(DECLARING))
def test_a_declaration_says_which_payloads_and_why(scenario):
    declaration = scenario.declaration
    # A declaration without a reason is a missing comparison with extra steps
    # -- the same rule §4.3 applies to an unrenderable dialect, for the same
    # reason: the reason is what a reviewer checks.
    assert len(str(declaration.get("reason", ""))) > 40
    assert scenario.drop_payloads, f"{scenario.name} declares no payloads"


@pytest.mark.parametrize("scenario", DECLARING, ids=ids(DECLARING))
def test_a_declaration_never_reaches_payload_state(scenario):
    # `absent` != `empty` != `redacted` is the model's central honesty claim
    # (`SPEC.md` §3.3). Two dialects disagreeing about a payload's STATE must
    # stay a finding; no comparison file may absorb it. Guarded here AND in
    # `canonical()`, because a fixture is a likelier place to get this wrong
    # than the comparison code.
    for selector, fields in scenario.drop_payloads.items():
        undeclarable = sorted(fields - DECLARABLE_PAYLOAD_FIELDS)
        assert undeclarable == [], (
            f"{scenario.name}: {selector} declares {undeclarable}, which is "
            f"not declarable; only {sorted(DECLARABLE_PAYLOAD_FIELDS)} are"
        )


@pytest.mark.parametrize("scenario", DECLARING, ids=ids(DECLARING))
def test_a_declaration_names_payloads_that_exist(scenario):
    graph = scenario.expected_graph
    real = {
        f"{node['id']}.{side}"
        for node in graph["nodes"]
        for side in ("inputs", "outputs")
    }
    unknown = sorted(set(scenario.drop_payloads) - real)
    assert unknown == [], (
        f"{scenario.name}: declares payloads that do not exist: {unknown}"
    )


@pytest.mark.parametrize("scenario", DECLARING, ids=ids(DECLARING))
def test_a_declaration_never_covers_an_absent_payload(scenario):
    # An `absent` payload has no value and no mime, so declaring one sets
    # nothing aside and only makes the declaration look larger than it is.
    graph = scenario.expected_graph
    states = {
        f"{node['id']}.{side}": node[side]["state"]
        for node in graph["nodes"]
        for side in ("inputs", "outputs")
    }
    pointless = sorted(
        selector for selector in scenario.drop_payloads if states[selector] == "absent"
    )
    assert pointless == [], f"{scenario.name}: declares absent payloads: {pointless}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=ids(SCENARIOS))
def test_an_override_only_touches_what_the_scenario_declared(scenario):
    # An override that reached an undeclared payload would be a silent second
    # erasure -- a dialect quietly given its own expectation with nothing on
    # the record saying the dialects disagree.
    for dialect in sorted({p.stem for p in scenario.dialects}):
        for selector, fields in scenario.overrides(dialect).items():
            declared = scenario.drop_payloads.get(selector)
            assert declared is not None, (
                f"{scenario.name}/{dialect}: overrides {selector}, which "
                f"expected/comparison.json does not declare dialect-varying"
            )
            extra = sorted(set(fields) - declared)
            assert extra == [], (
                f"{scenario.name}/{dialect}: overrides {extra} on {selector}, "
                f"which the declaration does not cover"
            )


def test_no_declaration_outlives_the_disagreement_that_earned_it():
    # A declaration on which every buildable dialect already agrees is stale,
    # and stale is how an exemption becomes permanent. Vacuous with one
    # adapter; it starts biting when the second lands, which is when a
    # declaration could first be shown unnecessary.
    for scenario in CROSS_DIALECT:
        graphs = [
            canonical(to_document(spanweave.build(path)), scenario.erase)
            for path in scenario.dialects
            if path.stem in adapter_backed()
        ]
        for selector, fields in scenario.drop_payloads.items():
            node_id, side = selector.split(".")
            # Per FIELD, not per selector. A declaration that names `mime`
            # alongside a genuinely varying `value` would otherwise ride along
            # untested, and each field set aside should be one the corpus can
            # point at a disagreement for.
            for name in sorted(fields):
                seen = [_payload_of(g, node_id, side).get(name) for g in graphs]
                assert any(entry != seen[0] for entry in seen[1:]), (
                    f"{scenario.name}: {selector} declares {name!r} "
                    f"dialect-varying but every dialect agrees on it; narrow "
                    f"the declaration rather than carrying it (FIXTURES.md §4.4)"
                )


def _payload_of(graph, node_id, side):
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node[side]
    raise AssertionError(f"no node {node_id}")


# --- and the mechanism itself, exercised rather than described --------------
#
# The three otel_genai renderings that declare payloads are skipped until 2.9
# registers an adapter, so nothing in the corpus exercises §4.4 yet. These
# plant the situation instead, so the mechanism is not merely documented.


def _llm_tool_llm():
    return next(s for s in BUILDABLE if s.name == "llm_tool_llm")


def _one_payload_changed(tmp_path, text="Look up the order status."):
    """The corpus rendering with one DECLARED payload value altered."""
    scenario = _llm_tool_llm()
    source = scenario.rendering("openinference")
    path = tmp_path / "openinference.jsonl"
    path.write_text(
        source.read_text(encoding="utf-8").replace(text, "Look up something else."),
        encoding="utf-8",
    )
    return scenario, Rendering(scenario=scenario, dialect="openinference", path=path)


def test_claim_one_still_fails_on_a_changed_payload_that_is_declared(tmp_path):
    # The whole point of the narrow form. `s1.inputs` IS declared
    # dialect-varying, and its value must still be pinned: a declaration sets a
    # field aside for the CROSS-DIALECT claim only. Under the broad form this
    # assertion would be unwritable.
    scenario, changed = _one_payload_changed(tmp_path)
    assert "value" in scenario.drop_payloads["s1.inputs"]
    document = to_document(built(changed))
    assert canonical(document, scenario.erase) != scenario.expected_graph_for(
        "openinference"
    )


def test_the_cross_dialect_form_sets_aside_exactly_what_was_declared(tmp_path):
    scenario, changed = _one_payload_changed(tmp_path)
    plain = canonical(to_document(built(changed)), scenario.erase)
    dropped = canonical(
        to_document(built(changed)), scenario.erase, scenario.drop_payloads
    )
    # s0.inputs declares both, and both are gone.
    assert _payload_of(dropped, "s0", "inputs") == {"state": "present"}
    # s1.inputs declares `value` alone, so `mime` survives -- the declaration
    # is exactly the disagreement and no wider.
    assert "value" not in _payload_of(dropped, "s1", "inputs")
    assert _payload_of(dropped, "s1", "inputs")["mime"] == "application/json"
    # The TOOL payloads are declared nowhere, so nothing is set aside there.
    # That is the byte-for-byte agreement between the two captured traces
    # staying a tested claim rather than an erased one.
    assert "s2.inputs" not in scenario.drop_payloads
    assert _payload_of(dropped, "s2", "inputs") == _payload_of(plain, "s2", "inputs")
    assert "value" in _payload_of(dropped, "s2", "inputs")


def test_an_override_restores_a_dialect_s_own_expectation(tmp_path):
    # What a dialect that records a different fact supplies, so claim 1 keeps
    # its teeth for that dialect too.
    scenario = _llm_tool_llm()
    graph = scenario.expected_graph
    with_override = scenario.expected_graph_for("openinference")
    assert with_override == graph  # no override file: agrees with graph.json

    payloads = scenario.path / "expected/payloads"
    payloads.mkdir(exist_ok=True)
    marker = payloads / "planted_dialect.json"
    marker.write_text(
        json.dumps({"s1.inputs": {"mime": None, "value": ["something else"]}}),
        encoding="utf-8",
    )
    try:
        overridden = scenario.expected_graph_for("planted_dialect")
        assert _payload_of(overridden, "s1", "inputs")["value"] == ["something else"]
        assert _payload_of(overridden, "s1", "inputs")["mime"] is None
        # Everything not overridden is untouched, including `state`.
        assert _payload_of(overridden, "s1", "inputs")["state"] == "present"
        assert _payload_of(overridden, "s2", "inputs") == _payload_of(
            graph, "s2", "inputs"
        )
    finally:
        marker.unlink()
        if not any(payloads.iterdir()):
            payloads.rmdir()


def test_a_declaration_that_names_state_cannot_erase_it():
    # Belt and braces: `test_a_declaration_never_reaches_payload_state` fails
    # the fixture, and this proves canonical() would refuse to honour it even
    # if that test were deleted. `state` is the one field no mechanism here may
    # reach.
    scenario = _llm_tool_llm()
    document = to_document(spanweave.build(scenario.rendering("openinference")))
    smuggled = canonical(
        document, scenario.erase, {"s1.inputs": frozenset({"state", "value"})}
    )
    assert _payload_of(smuggled, "s1", "inputs") == {
        "state": "present",
        "mime": "application/json",
    }


# --------------------------------------------------------------------------
# The transitional gap: renderings no adapter can read (TASKS.md 2.7)
# --------------------------------------------------------------------------


def test_every_declared_dialect_has_an_adapter_that_can_read_it():
    # `DIALECTS` is what drives §4.3's "silence is a failure" rule. Naming a
    # dialect there that nothing can build would make the corpus demand
    # renderings no test could ever check -- coverage on paper only.
    missing = sorted(set(DIALECTS) - adapter_backed())
    assert missing == [], f"DIALECTS names {missing}, which no adapter reads"


def test_no_adapter_reads_a_dialect_the_corpus_does_not_account_for():
    """The tripwire 2.13 finally clears.

    An adapter whose dialect is absent from `DIALECTS` is an adapter the corpus
    does not require any scenario to cover: its renderings can be added, or
    quietly not added, and nothing goes red. That is the rot this whole
    mechanism exists to prevent.

    `DIALECTS_PENDING_CORPUS_COVERAGE` is the only way to hold that state, and
    it is a *declaration*, not an exemption -- the same shape §4.3 already uses
    for a scenario a dialect cannot render, and for the same reason: a declared
    gap is reviewable, a silent one is not. Empty is the only correct
    long-term value. **Do not add an entry to get a test green** -- add one
    only when a task explicitly says the corpus is not yet covering a new
    dialect, and delete it in the task that covers it.
    """
    assert adapter_backed() == set(DIALECTS) | set(DIALECTS_PENDING_CORPUS_COVERAGE)


def test_the_pending_list_holds_nothing_stale():
    # A dialect listed as pending that no adapter provides is a leftover, and
    # a leftover here silently widens the exemption above.
    assert set(DIALECTS_PENDING_CORPUS_COVERAGE) <= adapter_backed()
    assert not (set(DIALECTS_PENDING_CORPUS_COVERAGE) & set(DIALECTS))


def test_the_suite_reports_every_rendering_it_skipped_and_why():
    # The skip has to be *visible*, not merely correct: `conftest.py` puts it
    # in the pytest header on every run, and each skipped rendering is a
    # reported skip rather than an absent test.
    from tests import conftest

    header = "\n".join(conftest.pytest_report_header(None))
    skipped = unsupported(SCENARIOS)
    if not skipped:
        assert "skipping nothing" in header
        return
    for rendering in skipped:
        assert rendering.dialect in header
        assert rendering.scenario.name in header


def _planted(scenario, dialect, tmp_path, text=None):
    """A rendering that does not live in the corpus, for the two proofs below.

    Written to tmp rather than into `fixtures/`, because a fixture planted to
    prove a test has teeth is a fixture someone later mistakes for a real one.
    """
    source = scenario.rendering("openinference")
    path = tmp_path / f"{dialect}.jsonl"
    path.write_text(
        text if text is not None else source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return Rendering(scenario=scenario, dialect=dialect, path=path)


def test_a_second_rendering_that_disagrees_with_the_canonical_graph_fails(tmp_path):
    # Teeth. Without this the parametrization could be comparing nothing: with
    # one dialect per scenario today, "every rendering agrees" is vacuously
    # true, and would stay green if the comparison were broken.
    scenario = next(s for s in BUILDABLE if s.name == "llm_tool_llm")
    disagreeing = _planted(
        scenario,
        "openinference",
        tmp_path,
        text=scenario.rendering("openinference")
        .read_text(encoding="utf-8")
        .replace("Look up the order status.", "Look up something else."),
    )
    document = to_document(built(disagreeing))
    assert canonical(document, scenario.erase) != scenario.expected_graph


def test_a_rendering_for_an_adapterless_dialect_is_skipped_not_passed(tmp_path):
    # The failure mode this guards is not a wrong answer but a confident
    # silence: a rendering nothing can read must not slide through green.
    scenario = next(s for s in BUILDABLE if s.name == "llm_tool_llm")
    unreadable = _planted(scenario, "not_a_registered_dialect", tmp_path)
    assert not unreadable.supported
    assert "no registered adapter" in unreadable.skip_reason
    with pytest.raises(pytest.skip.Exception) as skipped:
        built(unreadable)
    assert "not_a_registered_dialect" in str(skipped.value)


# --------------------------------------------------------------------------
# The central assertion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_the_rendering_produces_its_scenario_s_canonical_graph(rendering):
    # CLAIM 1 -- fidelity within a dialect (`FIXTURES.md` §4). NOTHING declared
    # is set aside here: a payload a scenario declares dialect-varying is still
    # pinned, by `graph.json` or by that dialect's own override. This is the
    # claim with teeth, and it is why a §4.4 declaration costs the corpus no
    # regression detection at all.
    document = to_document(built(rendering))
    assert canonical(document, rendering.scenario.erase) == (
        rendering.scenario.expected_graph_for(rendering.dialect)
    )


def _cross_dialect_form(rendering):
    """A rendering's canonical graph with its scenario's §4.4 declarations set
    aside -- the form claim 2 compares."""
    return canonical(
        to_document(built(rendering)),
        rendering.scenario.erase,
        rendering.scenario.drop_payloads,
    )


CROSS_DIALECT = [
    scenario
    for scenario in BUILDABLE
    if len([d for d in scenario.dialects if d.stem in adapter_backed()]) > 1
]


@pytest.mark.parametrize("scenario", CROSS_DIALECT, ids=ids(CROSS_DIALECT))
def test_every_dialect_of_a_scenario_produces_the_same_canonical_graph(scenario):
    # CLAIM 2 -- the library's central claim, and the reason the corpus exists.
    # Same run, described by any supported instrumentor, one graph.
    #
    # Vacuous while only one dialect has an adapter, and deliberately written
    # so that it stops being vacuous the moment a second one is registered
    # rather than needing to be remembered then.
    forms = {
        path.stem: _cross_dialect_form(
            Rendering(scenario=scenario, dialect=path.stem, path=path)
        )
        for path in scenario.dialects
        if path.stem in adapter_backed()
    }
    first, *rest = sorted(forms)
    for other in rest:
        assert forms[first] == forms[other], (
            f"{scenario.name}: {first} and {other} disagree on a field neither "
            f"expected/comparison.json declares dialect-varying. That is a "
            f"finding about the adapter or about the model -- never a reason "
            f"to widen the erasure (FIXTURES.md §4)."
        )


def test_the_cross_dialect_claim_is_reported_as_vacuous_while_it_is():
    # Otherwise "0 scenarios compared across dialects" and "every scenario
    # agrees" render identically in a green run.
    multi = [s.name for s in CROSS_DIALECT]
    if not multi:
        assert len(adapter_backed()) < 2, (
            "two adapters are registered but no scenario renders both; the "
            "central claim is being asserted over nothing"
        )


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_the_rendering_produces_exactly_its_expected_diagnostics(rendering):
    document = to_document(built(rendering))
    assert canonical(document, rendering.scenario.erase)["diagnostics"] == (
        rendering.scenario.expected_diagnostics
    )


@pytest.mark.parametrize(
    "rendering", FAILING_RENDERINGS, ids=labels(FAILING_RENDERINGS)
)
def test_the_rendering_refuses_to_build(rendering):
    # §4.2's equivalence half: every dialect of a refusal scenario must refuse
    # the SAME way. A dialect that builds a graph where another refuses is a
    # finding about the model, not a fixture to relax.
    expectation = rendering.scenario.expected_error
    with pytest.raises(SpanweaveError) as failure:
        built(rendering)
    # Type AND code, never message text (`FIXTURES.md` §4.2). A fixture that
    # pinned a phrase would start pressuring the message to stay as written.
    assert type(failure.value).__name__ == expectation["error"]
    assert failure.value.code == expectation["code"]


@pytest.mark.parametrize(
    "rendering", FAILING_RENDERINGS, ids=labels(FAILING_RENDERINGS)
)
def test_a_refusal_still_says_something_useful_to_a_human(rendering):
    # The corpus does not pin the wording, so something else has to insist
    # there IS wording. Otherwise "matched by code" quietly licenses an empty
    # message.
    with pytest.raises(SpanweaveError) as failure:
        built(rendering)
    assert len(str(failure.value)) > 40


def test_every_expected_error_code_is_one_the_library_actually_raises():
    for scenario in FAILING:
        assert scenario.expected_error["code"] in ERROR_CODES


# --------------------------------------------------------------------------
# Properties every scenario must hold, not just the one it was written for
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_builds_a_valid_graph(rendering):
    assert validate(to_document(built(rendering))) == ()


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_is_byte_identical_on_a_rebuild(rendering):
    graph = built(rendering)
    determinism.assert_repeatable(lambda: dumps(graph))


@pytest.mark.parametrize(
    "rendering", BUILDABLE_RENDERINGS, ids=labels(BUILDABLE_RENDERINGS)
)
def test_every_rendering_accounts_for_every_record(rendering):
    graph = built(rendering)
    records = [
        json.loads(line)
        for line in rendering.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    determinism.assert_every_record_accounted_for(records, to_document(graph))


# --------------------------------------------------------------------------
# The two scenarios whose point lives outside the canonical graph
# --------------------------------------------------------------------------


#: Dialects in which `shuffled_order` and `llm_tool_llm` are BOTH rendered.
#: Derived, not listed: the pair below is only a determinism check in a dialect
#: where both halves exist, and a dialect added to one and not the other must
#: drop out rather than compare a scenario against a missing file.
TWINNED = sorted(
    {p.stem for p in (CORPUS / "shuffled_order/dialects").iterdir()}
    & {p.stem for p in (CORPUS / "llm_tool_llm/dialects").iterdir()}
    & adapter_backed()
)


def test_the_shuffle_pair_is_twinned_in_every_dialect_that_renders_either():
    # A dialect that renders one half and not the other would silently narrow
    # the check above to the dialects that happen to be complete.
    for name in ("shuffled_order", "llm_tool_llm"):
        rendered = {p.stem for p in (CORPUS / name / "dialects").iterdir()}
        assert rendered & adapter_backed() == set(TWINNED), (
            f"{name} renders {sorted(rendered)}; the shuffle pair must be "
            f"rendered in the same dialects on both sides"
        )


@pytest.mark.parametrize("dialect", TWINNED)
def test_a_shuffled_trace_is_byte_identical_to_its_ordered_twin(dialect):
    # Not merely equal: identical bytes. This is the single most valuable
    # determinism check in the corpus (SPEC.md §5.2) -- and it is run per
    # dialect, because "input line order does not matter" is a claim about the
    # library, not about one adapter's tolerance.
    erase = ("name",)

    def graph(name):
        path = CORPUS / name / f"dialects/{dialect}.jsonl"
        return canonical_bytes(canonical(to_document(spanweave.build(path)), erase))

    assert graph("shuffled_order") == graph("llm_tool_llm")


@pytest.mark.parametrize("dialect", TWINNED)
def test_a_shuffled_trace_really_is_a_reordering_of_its_twin(dialect):
    # Otherwise the test above proves nothing.
    def text(name):
        return (CORPUS / name / f"dialects/{dialect}.jsonl").read_text(encoding="utf-8")

    assert sorted(text("shuffled_order").splitlines()) == sorted(
        text("llm_tool_llm").splitlines()
    )
    assert text("shuffled_order") != text("llm_tool_llm")


def test_an_unparseable_payload_keeps_its_text_verbatim():
    # canonical() erases Payload.raw, because a payload's *encoding* is
    # dialect-specific -- so the scenario's central claim is checked here,
    # against the serialized graph rather than the canonical one.
    document = to_document(
        spanweave.build(CORPUS / "malformed_payload_json/dialects/openinference.jsonl")
    )
    outputs = document["nodes"][0]["outputs"]
    assert outputs["state"] == "present"
    assert outputs["value"] is None
    assert outputs["raw"] == '{"status": "shipp'


def test_a_redacted_payload_keeps_the_marker_the_source_wrote():
    document = to_document(
        spanweave.build(CORPUS / "redacted_payload/dialects/openinference.jsonl")
    )
    assert document["nodes"][0]["inputs"]["raw"] == "__REDACTED__"
