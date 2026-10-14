"""What `ADAPTERS.md` §7 says about the zoo, re-derived from the zoo (batch T6).

Batch T6 answers the probes `PROBES.md` (`SigorMatt/spanweave-zoo` at
`tests.zoo_census.ZOO_PIN`) left *to establish* about what the adapters map --
S5, S6, S9, S14, S16, S17, S19, S20, S22 -- with readings in `ADAPTERS.md` §7,
and every reading that states a number or a set is held to the corpus here:

* **The documented key list.** `ADAPTERS.md` §7.1 and §7.2 give, per adapter,
  every attribute key the zoo's twelve captures leave unmapped since batches
  T3 and T4 -- indices folded to `<n>` -- with the projects that leave it, and
  each key the audit saw that T3 or T4 took out of `unmapped_attributes`. The
  test parses those tables and holds them equal to what the adapters report
  over every record of every capture: a key added, dropped or moved to the
  wrong project fails here.
* **The in-process envelope read** (`WORKPLAN.md` §3, T3: pinned at T6).
  `spanweave.envelope(node.raw.source)` reads every node of every capture,
  batch and `Builder` alike, because `raw.source` is the record the reader
  marked (`SPEC.md` §7). A JSON round trip is not that record and is out of
  this contract; what it keeps is `raw.source` verbatim, and the test holds
  that the level objects it carries are the ones `envelope` read.
* **The readings' numbers** (§7.3): the `llm`-in-`llm` nesting and the scopes
  at each end (S6, S17), the absence of any call id on a tool span (S9, S5),
  the `llm` node's normalized attributes (S20), and the four OpenInference
  kinds that stay `unknown` (S14).
"""

from __future__ import annotations

import collections
import json
import pathlib
import re

import pytest

import spanweave
from spanweave.adapters.openinference import OpenInferenceAdapter
from spanweave.api import graph_from_records
from tests import zoo_census
from tests.zoo_census import CAPTURES, Capture

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADAPTERS_MD = ROOT / "ADAPTERS.md"
IDS = [capture.run for capture in CAPTURES]

#: The section the tables live in, and the subsection that names each adapter.
SECTION = re.compile(r"^## 7\. ", re.MULTILINE)
SUBSECTION = re.compile(r"^### 7\.\d+ `([a-z_]+)`", re.MULTILINE)
#: `| `key` | Z1, Z3 | disposition ... |`
ROW = re.compile(r"^\| `([^`]+)` \| ([^|]+?) \| (.+) \|$")
#: The OTLP envelope's keys the adapters reported before T3 and T4, as the
#: audit named them (`PROBES.md` S4, S7, S8, S11), and the `raw.source` key
#: each one names.
TAKEN_OUT = {
    "<record>.flags": "flags",
    "<record>.kind": "kind",
    "<record>.resource_spans": "resource_spans",
    "<record>.scope_spans": "scope_spans",
    "<record>.droppedAttributesCount": "droppedAttributesCount",
    "<record>.events": "events",
}
INDEX = re.compile(r"\.\d+(?=\.|$)")


def _project(capture: Capture) -> str:
    return capture.run.split("/", 1)[0].upper()


def _graphs() -> list[tuple[Capture, spanweave.Graph]]:
    return [
        (capture, graph_from_records([r.record for r in zoo_census.records(capture)]))
        for capture in CAPTURES
    ]


def _documented() -> dict[str, dict[str, tuple[frozenset[str], str]]]:
    """`ADAPTERS.md` §7's tables: adapter -> key -> (projects, disposition)."""
    text = ADAPTERS_MD.read_text(encoding="utf-8")
    start = SECTION.search(text)
    assert start is not None, "ADAPTERS.md has no section 7"
    section = text[start.end() :]
    heads = list(SUBSECTION.finditer(section))
    tables: dict[str, dict[str, tuple[frozenset[str], str]]] = {}
    for head, after in zip(heads, [*heads[1:], None], strict=True):
        body = section[head.end() : after.start() if after else len(section)]
        rows: dict[str, tuple[frozenset[str], str]] = {}
        for line in body.splitlines():
            match = ROW.match(line)
            if match is None:
                continue
            key, projects, disposition = match.groups()
            assert key not in rows, f"{key} listed twice under {head.group(1)}"
            rows[key] = (
                frozenset(p.strip() for p in projects.split(",")),
                disposition,
            )
        tables[head.group(1)] = rows
    return tables


def _observed() -> tuple[
    dict[str, dict[str, set[str]]], dict[str, dict[str, set[str]]]
]:
    """What the adapters leave unmapped on the zoo, and the envelope keys the
    records claimed by each adapter carry -- adapter -> key -> projects."""
    unmapped: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    carried: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for capture, graph in _graphs():
        for diagnostic in graph.diagnostics:
            if diagnostic.code != "unmapped_attributes":
                continue
            assert diagnostic.adapter is not None, diagnostic
            assert isinstance(diagnostic.source, list | dict)
            for key in diagnostic.source:
                folded = INDEX.sub(".<n>", str(key))
                unmapped[diagnostic.adapter][folded].add(_project(capture))
        for node in graph.nodes():
            adapter = node.provenance.adapter_id
            if adapter is None:
                continue
            assert isinstance(node.raw.source, dict)
            for documented, key in TAKEN_OUT.items():
                if key in node.raw.source:
                    carried[adapter][documented].add(_project(capture))
    return unmapped, carried


# --- The documented key list --------------------------------------------------


def test_adapters_md_lists_every_key_the_zoo_leaves_unmapped_and_no_other():
    documented = _documented()
    unmapped, carried = _observed()
    assert set(documented) == set(unmapped) == {"openinference", "otel_genai"}
    for adapter, rows in documented.items():
        reported = {
            key: projects
            for key, (projects, disposition) in rows.items()
            if disposition.startswith("reported, not mapped")
        }
        taken_out = {
            key: projects
            for key, (projects, disposition) in rows.items()
            if disposition.startswith(("mapped at T3", "mapped at T4"))
        }
        assert set(reported) | set(taken_out) == set(rows), adapter
        # Every key the adapter leaves unmapped, on exactly the projects that
        # leave it -- and no key it does not.
        assert reported == {
            key: frozenset(projects) for key, projects in unmapped[adapter].items()
        }, adapter
        # Every envelope key T3/T4 took out is listed where the records carry
        # it, and no diagnostic names it any more.
        assert taken_out == {
            key: frozenset(projects) for key, projects in carried[adapter].items()
        }, adapter
        assert not set(taken_out) & set(unmapped[adapter]), adapter


# --- The in-process envelope read (WORKPLAN.md §3, T3; pinned here) ----------


def _builder_graph(feed: list[spanweave.model.JsonValue]) -> spanweave.Graph:
    builder = spanweave.Builder()
    for record in feed:
        builder.feed(record)
    return builder.graph()


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_envelope_reads_every_node_s_raw_source_in_process(capture):
    """Behaviour T3 measured and did not pin: this passes on the parent."""
    feed = [r.record for r in zoo_census.records(capture)]
    for graph in (graph_from_records(feed), _builder_graph(feed)):
        scopes: set[str] = set()
        document = json.loads(spanweave.dumps(graph))
        serialized = {node["id"]: node["raw"]["source"] for node in document["nodes"]}
        for node in graph.nodes():
            read = spanweave.envelope(node.raw.source)
            assert read.trace_id == capture.trace_id, node.id
            scope = read.scope.get("scope")
            assert isinstance(scope, dict), node.id
            scopes.add(scope["name"])
            # After a JSON round trip `raw.source` is a plain object, and the
            # levels are what it carries, verbatim (ADAPTERS.md §7.3).
            source = serialized[node.id]
            assert source.get("scope_spans", {}) == read.scope, node.id
            assert source.get("resource_spans", {}) == read.resource, node.id
        assert scopes == capture.scopes


# --- The readings' numbers (ADAPTERS.md §7.3) --------------------------------


def _scope(node: spanweave.Node) -> str:
    scope = spanweave.envelope(node.raw.source).scope["scope"]
    assert isinstance(scope, dict)
    return str(scope["name"])


#: S6, S17: `llm`-in-`llm` parent edges per capture, by (parent scope, child
#: scope).
NESTED = {
    "Z1": {},
    "Z2": {("llama_index", "llama_index"): 2},
    "Z3": {("openai_agents", "openai"): 25},
    "Z4": {},
    "Z5": {},
    "Z6": {},
}


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_an_llm_node_nested_in_another_is_one_parent_edge_and_nothing_else(capture):
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    nodes = {node.id: node for node in graph.nodes()}
    nested: collections.Counter[tuple[str, str]] = collections.Counter()
    prefix = "openinference.instrumentation."
    for edge in graph.edges():
        src, dst = nodes.get(edge.src), nodes.get(edge.dst)
        if src is None or dst is None:
            continue
        if src.kind is dst.kind is spanweave.NodeKind.LLM:
            # Nothing between two `llm` nodes says "one call": the `parent`
            # edge the records state, and §4.3's order between siblings.
            assert edge.kind in (spanweave.EdgeKind.PARENT, spanweave.EdgeKind.TEMPORAL)
            if edge.kind is spanweave.EdgeKind.PARENT:
                ends = (_scope(src), _scope(dst))
                nested[tuple(e.removeprefix(prefix) for e in ends)] += 1
    assert dict(nested) == NESTED[_project(capture)]


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_no_tool_span_states_a_call_id_and_no_call_is_paired(capture):
    """S9, S5: nothing in these exports a tool span can be paired by."""
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    tools = graph.nodes(kind=spanweave.NodeKind.TOOL)
    for node in tools:
        assert isinstance(node.raw.source, dict)
        attributes = node.raw.source["attributes"]
        assert isinstance(attributes, dict)
        assert not [k for k in attributes if re.search(r"(^|[._])(call_)?id$", k)]
    assert not [e for e in graph.edges() if e.kind is spanweave.EdgeKind.CALL_RESULT]
    if _project(capture) == "Z4":
        # S5: the GenAI handler exports no tool span at all.
        assert tools == ()


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_an_llm_node_s_normalized_attributes_are_its_model_alone(capture):
    """S20: no agent identity on an `llm` node -- a model, or nothing (S10)."""
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    for node in graph.nodes(kind=spanweave.NodeKind.LLM):
        assert set(node.attributes) <= {"model"}, node.id


@pytest.mark.parametrize("kind", ["PROMPT", "RERANKER", "GUARDRAIL", "EVALUATOR"])
def test_four_openinference_kinds_are_unknown_with_the_kind_kept(kind):
    """S14: §3.2's closed enum; the dialect's string is `reported_kind`."""
    record = {
        "trace_id": "t",
        "span_id": "s",
        "name": kind.lower(),
        "attributes": {"openinference.span.kind": kind},
    }
    (span,) = OpenInferenceAdapter().parse([record])
    assert span.kind is spanweave.NodeKind.UNKNOWN
    assert span.attributes["reported_kind"] == kind
    assert [d.code for d in span.diagnostics] == ["unknown_span_kind"]
