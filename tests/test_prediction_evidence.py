"""The measurements `TASKS.md` 3.5 hands the human for P3 and P4.

3.5 assembles evidence; it does not mark a prediction, and it does not touch
`PREDICTIONS.md`. What it *does* produce is a set of counts, and a count quoted
in a record rots the moment the corpus moves — which is why 3.3's perturbation
count was made executable in a follow-up rather than left as prose. Every number
3.5's record states about P3 or P4 is asserted here, with a non-vacuity floor
where a count could go quietly to zero.

Two of these tests deliberately construct a state the library forbids, to
measure what a consumer would do if the prohibition were lifted:

* `test_a_derived_data_edge_cannot_be_constructed` asserts the refusal itself —
  the combination `PREDICTIONS.md` P3 calls "already expressible honestly" does
  not currently exist, and `SPEC.md` §4.1 says so in the same commit that wrote
  the prediction.
* `test_the_only_consumer_reading_data_edges_does_not_filter_on_warrant`
  bypasses that refusal with `object.__setattr__` — **a simulation of the
  `--infer-data-edges` world, not a use of the library** — and shows the one
  consumer that reads `data` edges labels the result `(declared)` regardless.

Nothing here writes a fixture, edits an `expected/graph.json`, or changes
anything under `spanweave/`.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from examples import cost_latency, trajectory_dump
from examples.trajectory_dump.__main__ import report
from spanweave import Graph, build
from spanweave.model import Edge, EdgeKind, Warrant

REPO = pathlib.Path(__file__).resolve().parent.parent
CORPUS = REPO / "fixtures" / "conformance"
CAPTURED = REPO / "fixtures" / "captured"

#: The kinds a node's position is sorted over (`spanweave/build.py`
#: ``ORDERING_KINDS``). Restated rather than imported so that a change to the
#: builder's ordering shows up here as a failure instead of being followed.
ORDERING_KINDS = (EdgeKind.PARENT, EdgeKind.CALL_RESULT)


def _every_committed_trace() -> list[str]:
    return [
        str(path)
        for path in sorted(CORPUS.glob("*/dialects/*.jsonl"))
        + sorted(CAPTURED.glob("*.jsonl"))
    ]


def _buildable() -> list[tuple[str, Graph]]:
    built = []
    for path in _every_committed_trace():
        try:
            built.append((path, build(path)))
        except Exception:  # `duplicate_span_ids` refuses, by design
            continue
    return built


def _multi_node() -> list[tuple[str, Graph]]:
    return [(path, graph) for path, graph in _buildable() if len(graph.nodes()) > 1]


# -- P3: every `data` edge in the corpus is one the telemetry declared ------


def test_every_data_edge_in_the_corpus_is_declared():
    """P3 is about *inferred* `data` edges. The corpus contains none."""
    edges = [
        edge for _, graph in _buildable() for edge in graph.edges(kind=EdgeKind.DATA)
    ]
    carrying = [path for path, graph in _buildable() if graph.edges(kind=EdgeKind.DATA)]

    assert len(edges) == 12, "the count 3.5's record states"
    assert len(carrying) == 11, "traces carrying at least one"
    assert {str(edge.warrant) for edge in edges} == {"explicit"}
    assert {edge.basis for edge in edges} == {"tool_call_id in tool-result message"}
    # Non-vacuity: the three captured traces each carry one, so this cannot
    # pass by the corpus losing its `data` edges.
    assert sum(1 for path in carrying if "captured" in path) == 3


def test_a_derived_data_edge_cannot_be_constructed():
    """The state P3 calls "already expressible honestly" raises (`SPEC.md` §4.1).

    ---

    **The pattern this is the fourth instance of, named here at the pin rather
    than a fourth time in a fourth task record** — the ruling that put the
    third instance in
    `tests/test_example_cost_latency.py::test_usage_extra_is_non_empty_on_the_committed_corpus`
    rather than in a record applies unchanged.

    `PREDICTIONS.md` P3 states, as its class, that `--infer-data-edges`
    *"uses an existing `EdgeKind` and an existing warrant, so by the letter of
    the rule it is operational"*. `SPEC.md` §4.1 — **in the same seed commit,
    `c266c9e`** — already said the opposite: *"If a rule is ever added that
    infers a relation of an explicit-only kind, it does not become that kind —
    it becomes a new kind, through a spec change."* A new `EdgeKind` is a
    **shape** change and an `AGENT.md` halt point. `ALLOWED_WARRANTS` has
    enforced §4.1's side since the first implementation commit (`d8e2c37`).

    Same species as the three named at that other pin: a prose claim about
    this project's own artifacts that nothing recomputed. One step more
    general again, and worth the widening — the first three were **quantifiers
    over the corpus**, true when written and expiring silently as the corpus
    grew. This one is a claim about the **model's own types**, and it was
    never true: it did not expire, it arrived wrong, in the file this project
    wrote to catch itself being wrong about its own design.

    The remedy is the same for the fourth time: a test, not a corrected
    sentence.
    """
    with pytest.raises(ValueError) as raised:
        Edge(
            src="a",
            dst="b",
            kind=EdgeKind.DATA,
            warrant=Warrant.DERIVED,
            basis="normalized value containment",
        )
    assert "explicit-only" in str(raised.value)
    assert "4.1" in str(raised.value)


def test_the_only_consumer_reading_data_edges_does_not_filter_on_warrant():
    """P3's premise is that consumers filter on warrant. The one that could, doesn't.

    The forced warrant below cannot happen today — it is constructed past the
    validator on purpose, to answer what the transcript would say if
    `--infer-data-edges` existed. It says `(declared)`.
    """
    source = str(CORPUS / "parallel_tools" / "dialects" / "openinference.jsonl")
    graph = build(source)
    ids = [node.id for node in graph.nodes()]
    assert not graph.edges(kind=EdgeKind.DATA), "this scenario declares none"

    inferred = Edge(
        src=ids[1],
        dst=ids[2],
        kind=EdgeKind.DATA,
        warrant=Warrant.EXPLICIT,
        basis="normalized value containment",
    )
    object.__setattr__(inferred, "warrant", Warrant.DERIVED)
    perturbed = Graph.of(
        graph.trace_id,
        graph.nodes(),
        tuple(sorted([*graph.edges(), inferred], key=lambda e: e.sort_key)),
        graph.diagnostics,
        graph.meta,
    )
    assert [str(e.warrant) for e in perturbed.edges(kind=EdgeKind.DATA)] == ["derived"]

    lines = [
        line
        for line in report(trajectory_dump.flatten(source, perturbed)).splitlines()
        if "feeds" in line
    ]
    assert len(lines) == 1
    assert "(declared)" in lines[0], "the label is a literal, not a warrant read"


def test_no_phase_3_consumer_reads_a_data_edge_it_did_not_receive():
    """3.3 F-5 and 3.4 O-d, as a check rather than a sentence."""
    source = str(CORPUS / "llm_tool_llm" / "dialects" / "openinference.jsonl")
    graph = build(source)
    declared = graph.edges(kind=EdgeKind.DATA)
    assert len(declared) == 1

    transcript = trajectory_dump.flatten(source, graph).as_dict()
    feeds = [step for step in transcript["steps"] if step["feeds"]]
    assert len(feeds) == 1, "the dumper reports the declared edge"

    attribution = cost_latency.attribute_graph(source, graph).as_dict()
    assert "feeds" not in json.dumps(attribution), "the attributor reads no data edges"


# -- P4: neither consumer's numbers need the order; both consumers' bytes do -


def _canonical(document: dict, list_keys: tuple[str, ...], drop: frozenset) -> str:
    """The document with every list order and the step index removed."""
    copy = json.loads(json.dumps(document))
    for key in list_keys:
        value = copy.get(key)
        if isinstance(value, list):
            stripped = [
                {k: v for k, v in item.items() if k not in drop}
                if isinstance(item, dict)
                else item
                for item in value
            ]
            copy[key] = sorted(
                stripped, key=lambda item: json.dumps(item, sort_keys=True)
            )
    return json.dumps(copy, sort_keys=True)


def test_reordering_the_nodes_changes_both_consumers_output_and_neither_result():
    """P4, measured: the bytes move, the values do not."""
    bytes_moved = substance_held = 0
    traces = _multi_node()
    for source, graph in traces:
        reordered = Graph.of(
            graph.trace_id,
            tuple(reversed(graph.nodes())),
            graph.edges(),
            graph.diagnostics,
            graph.meta,
        )
        before_t = trajectory_dump.flatten(source, graph).as_dict()
        after_t = trajectory_dump.flatten(source, reordered).as_dict()
        before_c = cost_latency.attribute_graph(source, graph).as_dict()
        after_c = cost_latency.attribute_graph(source, reordered).as_dict()

        if before_t != after_t and before_c != after_c:
            bytes_moved += 1
        held_t = _canonical(before_t, ("steps",), frozenset({"index"})) == _canonical(
            after_t, ("steps",), frozenset({"index"})
        )
        keys = ("steps", "roots", "limits")
        held_c = _canonical(before_c, keys, frozenset()) == _canonical(
            after_c, keys, frozenset()
        )
        if held_t and held_c:
            substance_held += 1

    assert len(traces) == 30
    assert bytes_moved == 30, "both consumers' serialized output is order-dependent"
    assert substance_held == 30, "no per-node value or total depends on the order"


def test_the_emitted_order_is_a_choice_on_most_traces():
    """A topological order is not unique; the tie-break decides — how often it does."""
    a_choice_was_made = 0
    a_start_time_tie = 0
    tied_traces = []
    for source, graph in _multi_node():
        by_id = {node.id: node for node in graph.nodes()}
        incoming = dict.fromkeys(by_id, 0)
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        for edge in graph.edges():
            if edge.kind in ORDERING_KINDS and edge.src in by_id and edge.dst in by_id:
                outgoing[edge.src].append(edge.dst)
                incoming[edge.dst] += 1

        def tie_break(node):
            start = node.started_at if node.started_at is not None else float("inf")
            return (start, node.id)

        ready = sorted((by_id[i] for i in by_id if incoming[i] == 0), key=tie_break)
        chose = tied = False
        while ready:
            if len(ready) > 1:
                chose = True
                if tie_break(ready[0])[0] == tie_break(ready[1])[0]:
                    tied = True
            node = ready.pop(0)
            released = []
            for target in outgoing[node.id]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    released.append(by_id[target])
            if released:
                ready = sorted([*ready, *released], key=tie_break)
        a_choice_was_made += chose
        if tied:
            a_start_time_tie += 1
            tied_traces.append(source)

    assert a_choice_was_made == 22, "traces where two nodes were ready at once"
    assert a_start_time_tie == 2, "traces where equal start times forced the id rule"
    assert all("parallel_tools/" in source for source in tied_traces)


def test_edge_order_reaches_the_transcript_and_not_the_attribution():
    """The second half of P4's noticing question: edge order, not just node order."""
    transcript_moved = []
    attribution_moved = []
    for source, graph in _multi_node():
        reordered = Graph.of(
            graph.trace_id,
            graph.nodes(),
            tuple(reversed(graph.edges())),
            graph.diagnostics,
            graph.meta,
        )
        if (
            trajectory_dump.flatten(source, graph).as_dict()
            != trajectory_dump.flatten(source, reordered).as_dict()
        ):
            transcript_moved.append(source)
        if (
            cost_latency.attribute_graph(source, graph).as_dict()
            != cost_latency.attribute_graph(source, reordered).as_dict()
        ):
            attribution_moved.append(source)

    assert len(transcript_moved) == 2
    assert all("parallel_tool_calls/" in source for source in transcript_moved)
    assert attribution_moved == []

    # And what moved: the ids of the results one call produced, in edge order.
    source = str(CORPUS / "parallel_tool_calls" / "dialects" / "openinference.jsonl")
    graph = build(source)
    reordered = Graph.of(
        graph.trace_id,
        graph.nodes(),
        tuple(reversed(graph.edges())),
        graph.diagnostics,
        graph.meta,
    )
    before = [
        step.fulfilled_by
        for step in trajectory_dump.flatten(source, graph).steps
        if step.fulfilled_by
    ]
    after = [
        step.fulfilled_by
        for step in trajectory_dump.flatten(source, reordered).steps
        if step.fulfilled_by
    ]
    assert before == [("s2", "s3")]
    assert after == [("s3", "s2")]
