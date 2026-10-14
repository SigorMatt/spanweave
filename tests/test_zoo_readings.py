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
* **The in-process envelope read** (`TASKS.md`, *The stranger's-trace
  series*, decisions, T3: pinned at T6).
  `spanweave.envelope(node.raw.source)` reads every node of every capture,
  batch and `Builder` alike, because `raw.source` is the record the reader
  marked (`SPEC.md` §7). A JSON round trip is not that record and is out of
  this contract; what it keeps is `raw.source` verbatim, and the test holds
  that the level objects it carries are the ones `envelope` read.
* **Every disposition, in full** (decisions 2026-10-14g, commit 12). Each
  row's disposition is compared whole against `DISPOSITIONS`, not by its
  first words: a reason rewritten, or a batch moved, fails here.
* **The readings' numbers** (§7.4). Every number §7 states is a row of §7.4's
  table, which the test parses and re-derives from the zoo row by row; §7's
  prose states none of its own, and the test fails if it does. The corpus
  numbers the CHANGELOG cites (captures, agents, envelope keys) are
  `CORPUS`, held to the zoo and to every place the CHANGELOG states them.
* **The readings' facts** (§7.3): the `llm`-in-`llm` nesting and the scopes
  and names at each end (S6, S17), the absence of any call id on a tool span
  (S9, S5), the `llm` node's normalized attributes (S20), the OpenInference
  kinds that stay `unknown` (S14) and Z1's nodes that are its case, every Z6
  `llm` node's scope and the delegation tool a coworker's sits under, the two
  spellings of Z6's delegate tool, the `llm` node Z4's unpaired call is
  requested by, and each Z2 `acall` as the only child of its `call_tool`.
* **S13, after the close** (decisions 2026-10-14e, commit 1). Z5's real and
  recorded graphs, with the ids and times the exporter generated masked,
  differ at exactly the paths `S13_DIFFERENCES` lists and nowhere else, byte
  for byte.
"""

from __future__ import annotations

import collections
import functools
import json
import pathlib
import re
from collections.abc import Callable
from typing import Any

import pytest

import spanweave
from spanweave.adapters.openinference import KINDS, OpenInferenceAdapter
from spanweave.api import graph_from_records
from tests import zoo_census
from tests.zoo_census import CAPTURES, Capture

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADAPTERS_MD = ROOT / "ADAPTERS.md"
IDS = [capture.run for capture in CAPTURES]

#: The section the tables live in, the subsection that names each adapter, and
#: any heading -- the end of a subsection's body.
SECTION = re.compile(r"^## 7\. ", re.MULTILINE)
SUBSECTION = re.compile(r"^### 7\.\d+ `([a-z_]+)`", re.MULTILINE)
HEADING = re.compile(r"^#{1,3} ", re.MULTILINE)
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

#: Every row's disposition in `ADAPTERS.md` §7.1 and §7.2, in full: adapter ->
#: key -> the text after the projects. Compared whole, so a reason rewritten or
#: a key moved to another batch fails, not only a key moved between "reported"
#: and "mapped" (decisions 2026-10-14g, commit 12; R-18).
REPORTED = "reported, not mapped: "
NO_FIELD = REPORTED + "no field"
MESSAGE = REPORTED + "message content, as above"


def _envelope(probe: str) -> dict[str, str]:
    """The four envelope keys T3 took out, as each adapter's table gives them."""
    cite = f"(`SPEC.md` §7; {probe})"
    verbatim = f"mapped at T3: the OTLP envelope, verbatim in `raw.source` {cite}"
    return {
        "<record>.flags": verbatim,
        "<record>.kind": verbatim,
        "<record>.resource_spans": (
            "mapped at T3: the envelope's resource level, read as "
            f"`envelope(record).resource` {cite}"
        ),
        "<record>.scope_spans": (
            "mapped at T3: the envelope's scope level, read as "
            f"`envelope(record).scope` {cite}"
        ),
    }


DISPOSITIONS: dict[str, dict[str, str]] = {
    "openinference": {
        **_envelope("S7"),
        "<record>.droppedAttributesCount": (
            "mapped at T3: the `attributes_dropped` diagnostic (`SPEC.md` §3.7; S8)"
        ),
        "<record>.events": (
            "mapped at T4: one `exception_event` or `span_event` diagnostic per "
            "event (`SPEC.md` §3.7, §7; S11, S17)"
        ),
        "agent.name": REPORTED
        + "an agent's name is declined from `operation` (`SPEC.md` §3.1). An "
        "`llm` node carries no agent identity (S20; §7.3)",
        "crew_agents": NO_FIELD,
        "crew_id": NO_FIELD,
        "crew_inputs": NO_FIELD,
        "crew_key": NO_FIELD,
        "crew_tasks": NO_FIELD,
        "graph.node.id": REPORTED
        + "it names the framework's node in a sequence, not a span. See "
        "`graph.node.parent_id` (S19)",
        "graph.node.parent_id": REPORTED
        + "it names the previous agent in the crew's sequence, while the span's "
        "stated parent is the kickoff. It states a sequence, not containment. A "
        "`parent` edge is the span's stated parent (`SPEC.md` §4.0), and no "
        "`EdgeKind` holds a second structure, so the sequence appears only as "
        "§4.3's `temporal` order of the siblings (S19)",
        "llm.finish_reason": NO_FIELD,
        "llm.input_messages.<n>.message.content": REPORTED
        + "a message is payload content, not a node (`OPEN_QUESTIONS.md` §2). "
        "Payloads come from `input.value` / `output.value` (`SPEC.md` §3.3)",
        "llm.input_messages.<n>.message.contents.<n>.message_content.text": MESSAGE,
        "llm.input_messages.<n>.message.contents.<n>.message_content.type": MESSAGE,
        "llm.input_messages.<n>.message.name": MESSAGE,
        "llm.input_messages.<n>.message.role": REPORTED
        + "a role is read only to decide whether a `tool_call_id` beside it is a "
        "tool result (`SPEC.md` §4.2.1). With no such id beside it, it decided "
        "nothing (§3, *Losslessness*)",
        "llm.input_messages.<n>.message.tool_call_id": REPORTED
        + "a tool-result id is read only when its message's `role` is `tool` "
        "(`SPEC.md` §4.2.1). The openai-agents instrumentor's message states no "
        "`role`, so nothing decided it",
        "llm.input_messages.<n>.message.tool_calls.<n>.tool_call.function.arguments": (
            REPORTED
            + "an echo of an earlier request in the resent history (`SPEC.md` §4.4)"
        ),
        "llm.input_messages.<n>.message.tool_calls.<n>.tool_call.function.name": (
            REPORTED + "an echo, as above"
        ),
        "llm.input_messages.<n>.message.tool_calls.<n>.tool_call.id": REPORTED
        + "an echo of a reference is not the reference (`SPEC.md` §4.4)",
        "llm.invocation_parameters": NO_FIELD,
        "llm.output_messages.<n>.message.content": MESSAGE
        + ". The span's output payload is `output.value`",
        "llm.output_messages.<n>.message.contents.<n>.message_content.text": MESSAGE,
        "llm.output_messages.<n>.message.contents.<n>.message_content.type": MESSAGE,
        "llm.output_messages.<n>.message.role": MESSAGE,
        "llm.output_messages.<n>.message.tool_calls.<n>.tool_call.function.arguments": (
            REPORTED
            + "the call's id is mapped (`call_ids`, requester, `SPEC.md` §4.4), and "
            "its function name is read into `unpaired_call`'s `source`. No field "
            "holds the arguments"
        ),
        "llm.prompt_template.template": NO_FIELD
        + ". It is on Z1's `PROMPT` spans, which are `unknown` nodes (S14; §7.3)",
        "llm.prompt_template.variables": REPORTED + "as above",
        "llm.provider": NO_FIELD,
        "llm.system": NO_FIELD,
        "llm.tools.<n>.tool.json_schema": NO_FIELD,
        "metadata": NO_FIELD,
        "task_id": NO_FIELD,
        "task_key": NO_FIELD,
        "tool.cache_function": NO_FIELD,
        "tool.current_usage_count": NO_FIELD,
        "tool.description": NO_FIELD,
        "tool.description_updated": NO_FIELD,
        "tool.parameters": NO_FIELD,
        "tool.result_as_answer": NO_FIELD,
    },
    "otel_genai": {
        **_envelope("S4"),
        "gen_ai.provider.name": NO_FIELD,
        "gen_ai.response.id": NO_FIELD,
        "gen_ai.response.model": REPORTED
        + "`operation` takes the model from `gen_ai.request.model` (`SPEC.md` "
        "§3.1). The response's model is a second statement, and no field holds it",
        "server.address": NO_FIELD,
        "server.port": NO_FIELD,
    },
}


def _project(capture: Capture) -> str:
    return capture.run.split("/", 1)[0].upper()


@functools.cache
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
    for head in heads:
        end = HEADING.search(section, head.end())
        body = section[head.end() : end.start() if end else len(section)]
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
        # Each disposition, whole: the batch, the reason and its citations.
        assert {
            key: disposition for key, (_, disposition) in rows.items()
        } == DISPOSITIONS[adapter], adapter
        reported = {
            key: projects
            for key, (projects, disposition) in rows.items()
            if disposition.startswith(REPORTED)
        }
        taken_out = {
            key: projects
            for key, (projects, disposition) in rows.items()
            if disposition.startswith(("mapped at T3: ", "mapped at T4: "))
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


# --- The in-process envelope read (TASKS.md, stranger's-trace, T3) -----------


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


# --- The readings' numbers (ADAPTERS.md §7.4) --------------------------------

LLM = spanweave.NodeKind.LLM
TOOL = spanweave.NodeKind.TOOL
UNKNOWN = spanweave.NodeKind.UNKNOWN
PARENT = spanweave.EdgeKind.PARENT
TEMPORAL = spanweave.EdgeKind.TEMPORAL
#: §7.4, the table every number §7 states is a row of.
NUMBERS = re.compile(r"^### 7\.4 ", re.MULTILINE)
#: `| number | where | value |`
NUMBER_ROW = re.compile(r"^\| (.+?) \| (.+?) \| (\d+) \|$")
#: The corpus numbers the CHANGELOG cites: noun -> number. §7.4 states each
#: too, and `test_adapters_md_s_numbers_are_the_zoo_s` derives them.
CORPUS = {"captures": 12, "agents": 6, "OTLP envelope keys": 6}
#: The number words a document spells a count in.
WORDS = [
    *("zero", "one", "two", "three", "four", "five", "six", "seven", "eight"),
    *("nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen"),
    *("sixteen", "seventeen", "eighteen", "nineteen", "twenty"),
]
CHANGELOG_MD = ROOT / "CHANGELOG.md"


def _scope(node: spanweave.Node) -> str:
    scope = spanweave.envelope(node.raw.source).scope["scope"]
    assert isinstance(scope, dict)
    return str(scope["name"])


def _parent_of(graph: spanweave.Graph) -> dict[str, spanweave.Node]:
    """Each node id that has a `parent` edge -> the node at its other end."""
    nodes = {node.id: node for node in graph.nodes()}
    return {e.dst: nodes[e.src] for e in graph.edges() if e.kind is PARENT}


def _nested(graph: spanweave.Graph) -> list[tuple[spanweave.Node, spanweave.Node]]:
    """Every `(parent, child)` `parent` edge with an `llm` node at both ends."""
    parent_of = _parent_of(graph)
    return [
        (parent_of[node.id], node)
        for node in graph.nodes(kind=LLM)
        if node.id in parent_of and parent_of[node.id].kind is LLM
    ]


def _unpaired(graph: spanweave.Graph) -> list[spanweave.Diagnostic]:
    return [d for d in graph.diagnostics if d.code == "unpaired_call"]


#: §7.4's per-graph rows: the row's *Number* -> its count on one graph.
PER_GRAPH: dict[str, Callable[[spanweave.Graph], int]] = {
    "`llm` nodes": lambda graph: len(graph.nodes(kind=LLM)),
    "scopes": lambda graph: len({_scope(node) for node in graph.nodes()}),
    "`llm` nodes with an `llm` parent": lambda graph: len(_nested(graph)),
    "`unpaired_call`": lambda graph: len(_unpaired(graph)),
    "`unknown` nodes": lambda graph: len(graph.nodes(kind=UNKNOWN)),
    "model-less `llm` nodes": lambda graph: sum(
        "model" not in node.attributes for node in graph.nodes(kind=LLM)
    ),
    "`temporal` edges": lambda graph: sum(e.kind is TEMPORAL for e in graph.edges()),
}
#: §7.4's rows, each `(number, where)`: a row dropped fails as one added does.
ROWS = {
    ("captures", "the zoo"),
    ("agents", "the zoo"),
    ("OTLP envelope keys mapped at T3/T4", "the zoo"),
    ("`llm` nodes", "Z4"),
    ("scopes", "Z3"),
    ("scopes", "Z4"),
    ("scopes", "Z6"),
    ("`llm` nodes with an `llm` parent", "Z2"),
    ("`llm` nodes with an `llm` parent", "Z3"),
    ("`llm` nodes with an `llm` parent", "Z6"),
    ("`unpaired_call`", "Z1"),
    ("`unpaired_call`", "Z2"),
    ("`unpaired_call`", "Z3"),
    ("`unpaired_call`", "Z4"),
    ("`unpaired_call`", "Z6 real"),
    ("`unpaired_call`", "Z6 recorded"),
    ("`unknown` nodes", "Z1"),
    ("model-less `llm` nodes", "Z3"),
    ("`temporal` edges", "Z2"),
}


def _section() -> str:
    text = ADAPTERS_MD.read_text(encoding="utf-8")
    start = SECTION.search(text)
    assert start is not None, "ADAPTERS.md has no section 7"
    return text[start.start() :]


def _numbers() -> dict[tuple[str, str], int]:
    """`ADAPTERS.md` §7.4's table: `(number, where)` -> value."""
    section = _section()
    head = NUMBERS.search(section)
    assert head is not None, "ADAPTERS.md has no §7.4"
    end = HEADING.search(section, head.end())
    rows: dict[tuple[str, str], int] = {}
    for line in section[head.end() : end.start() if end else None].splitlines():
        match = NUMBER_ROW.match(line)
        if match is not None:
            number, where, value = match.groups()
            assert (number, where) not in rows, f"{number} at {where} listed twice"
            rows[(number, where)] = int(value)
    return rows


def _corpus() -> dict[str, int]:
    """The corpus numbers, from the zoo: captures, agents, and the envelope
    keys T3/T4 took out of `unmapped_attributes` that its records carry."""
    _, carried = _observed()
    return {
        "captures": len(CAPTURES),
        "agents": len({_project(capture) for capture in CAPTURES}),
        "OTLP envelope keys": len({key for keys in carried.values() for key in keys}),
    }


def _where(capture: Capture) -> set[str]:
    """The *Where* values a capture answers to: its project, and the capture."""
    project = _project(capture)
    return {project, f"{project} {capture.run.rsplit('-', 1)[1]}"}


def test_adapters_md_s_numbers_are_the_zoo_s():
    """Every row of §7.4, re-derived from the zoo; and no row missing."""
    documented = _numbers()
    assert set(documented) == ROWS
    corpus = _corpus()
    assert corpus == CORPUS
    by_name = {
        "captures": corpus["captures"],
        "agents": corpus["agents"],
        "OTLP envelope keys mapped at T3/T4": corpus["OTLP envelope keys"],
    }
    graphs = _graphs()
    for (number, where), value in sorted(documented.items()):
        if where == "the zoo":
            assert by_name[number] == value, (number, where)
            continue
        held = [
            PER_GRAPH[number](graph)
            for capture, graph in graphs
            if where in _where(capture)
        ]
        assert held, f"no capture is {where}"
        assert held == [value] * len(held), (number, where, held)


#: What §7's prose may carry that reads like a number and is a name: a
#: backticked span, a section (§3.7), a probe, project or batch (S5, Z1, T3),
#: a decision's option.
NAMES = re.compile(r"`[^`]*`|§\d+(?:\.\d+)*|\b[SZT]\d+\b|\boption \d+\b")
#: A number in prose: a digit, or a count spelled out. "one" is not one here:
#: §7 uses it as a pronoun and an article ("one nested in the other", "one
#: crew"), never as a count it cites.
SPELLED = re.compile(r"\d|\b(?:" + "|".join(w for w in WORDS if w != "one") + r")\b")


def test_adapters_md_s_prose_states_no_number_of_its_own():
    """§7's numbers live in its tables, where the tests read them (R-18)."""
    prose = " ".join(
        HEADING.sub("", re.sub(r"^#+ [\d.]+", "", line))
        for line in _section().splitlines()
        if not line.startswith("|")
    )
    stated = SPELLED.findall(NAMES.sub("", prose).lower())
    assert stated == [], "a number in ADAPTERS.md §7's prose, not in §7.4"


def test_the_changelog_states_the_corpus_numbers_the_test_holds():
    """CHANGELOG cites the zoo's captures, agents and envelope keys by number:
    each place it does, the number is `CORPUS`'s (R-18)."""
    changelog = " ".join(CHANGELOG_MD.read_text(encoding="utf-8").split())
    words = "|".join(WORDS)
    for noun, number in CORPUS.items():
        stated = re.findall(rf"\b({words}) {noun}\b", changelog, re.IGNORECASE)
        assert stated, f"CHANGELOG cites no number of {noun}"
        assert {word.lower() for word in stated} == {WORDS[number]}, noun


# --- The readings' facts (ADAPTERS.md §7.3) ----------------------------------

#: S6, S17: the scopes at the two ends of each `llm`-in-`llm` `parent` edge
#: (§7.4 counts the edges).
NESTED = {
    "Z1": set(),
    "Z2": {("llama_index", "llama_index")},
    "Z3": {("openai_agents", "openai")},
    "Z4": set(),
    "Z5": set(),
    "Z6": set(),
}


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_an_llm_node_nested_in_another_is_one_parent_edge_and_nothing_else(capture):
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    nodes = {node.id: node for node in graph.nodes()}
    prefix = "openinference.instrumentation."
    for edge in graph.edges():
        src, dst = nodes.get(edge.src), nodes.get(edge.dst)
        if src is not None and dst is not None and src.kind is dst.kind is LLM:
            # Nothing between two `llm` nodes says "one call": the `parent`
            # edge the records state, and §4.3's order between siblings.
            assert edge.kind in (PARENT, TEMPORAL)
    ends = {
        (_scope(parent).removeprefix(prefix), _scope(child).removeprefix(prefix))
        for parent, child in _nested(graph)
    }
    assert ends == NESTED[_project(capture)]


def _project_graphs(project: str) -> list[tuple[Capture, spanweave.Graph]]:
    graphs = [(c, g) for c, g in _graphs() if _project(c) == project]
    runs = [capture.run.rsplit("-", 1)[1] for capture, _ in graphs]
    assert runs == ["real", "recorded"], project
    return graphs


def test_z3_s_nesting_is_a_generation_over_a_chat_completion():
    """S6: every nested pair on Z3 is openai-agents' `generation` over the
    OpenAI client's `ChatCompletion`."""
    for capture, graph in _project_graphs("Z3"):
        pairs = {(parent.name, child.name) for parent, child in _nested(graph)}
        assert pairs == {("generation", "ChatCompletion")}, capture.run


def test_z2_s_nesting_is_astream_chat_in_astream_chat():
    """S17: every nested pair on Z2 is an `astream_chat` in an `astream_chat`."""
    for capture, graph in _project_graphs("Z2"):
        pairs = {(parent.name, child.name) for parent, child in _nested(graph)}
        assert pairs == {("OpenAILike.astream_chat", "OpenAILike.astream_chat")}, (
            capture.run
        )


def test_every_z6_llm_node_is_the_openai_client_s():
    """S6: CrewAI writes no `llm` span on Z6; the OpenAI client writes each."""
    for capture, graph in _project_graphs("Z6"):
        scopes = {_scope(node) for node in graph.nodes(kind=LLM)}
        assert scopes == {"openinference.instrumentation.openai"}, capture.run


#: S20: per Z6 capture, the tool node each `llm` node with a `tool` parent sits
#: under, by `operation`, in graph order -- the coworker's `ChatCompletion`
#: under the delegation tool that handed it the work.
COWORKERS = {
    "z6/2026-10-14-real": [
        "Delegate work to coworker",
        "Delegate work to coworker",
        "Ask question to coworker",
    ],
    "z6/2026-10-14-recorded": ["Delegate work to coworker"],
}


def test_z6_s_coworker_llm_node_has_a_parent_edge_to_the_delegation_tool():
    for capture, graph in _project_graphs("Z6"):
        parent_of = _parent_of(graph)
        under = [
            parent_of[node.id]
            for node in graph.nodes(kind=LLM)
            if node.id in parent_of and parent_of[node.id].kind is TOOL
        ]
        # Each a `ChatCompletion`, as the delegator's are (§7.3, S20).
        assert {node.name for node in graph.nodes(kind=LLM)} == {"ChatCompletion"}
        assert [tool.operation for tool in under] == COWORKERS[capture.run]


#: S9: Z6's delegate tool as its span names it (`tool.name`, read into
#: `operation`) and as a model requests it (the function name `unpaired_call`
#: reads into its `source`).
DELEGATE = ("Delegate work to coworker", "delegate_work_to_coworker")


def test_z6_spells_the_delegate_tool_two_ways():
    spelled, requested = DELEGATE
    for capture, graph in _project_graphs("Z6"):
        operations = {node.operation for node in graph.nodes(kind=TOOL)}
        requests = set()
        for diagnostic in _unpaired(graph):
            assert isinstance(diagnostic.source, dict)
            requests.add(diagnostic.source["operation"])
        assert spelled in operations and spelled not in requests, capture.run
        assert requested in requests and requested not in operations, capture.run


def test_z4_s_second_llm_node_requests_book_table():
    """S5: the one call Z4 leaves unpaired is the second `llm` node's."""
    for capture, graph in _project_graphs("Z4"):
        position = {node.id: i for i, node in enumerate(graph.nodes(kind=LLM))}
        requested = []
        for diagnostic in _unpaired(graph):
            assert isinstance(diagnostic.source, dict)
            assert diagnostic.node_id is not None
            requested.append(
                (position[diagnostic.node_id], diagnostic.source["operation"])
            )
        assert requested == [(1, "book_table")], capture.run


def test_each_z2_acall_is_the_only_child_of_its_call_tool():
    """S16: each `acall` tool node, alone under its own `call_tool` chain."""
    for capture, graph in _project_graphs("Z2"):
        parent_of = _parent_of(graph)
        children = collections.Counter(parent.id for parent in parent_of.values())
        acalls = graph.nodes(kind=TOOL)
        assert acalls, capture.run
        for node in acalls:
            assert node.name == "FunctionTool.acall", node.id
            parent = parent_of[node.id]
            assert parent.name == "BaseWorkflowAgent.call_tool", node.id
            assert children[parent.id] == 1, node.id


@pytest.mark.parametrize("capture", CAPTURES, ids=IDS)
def test_no_tool_span_states_a_call_id_and_no_call_is_paired(capture):
    """S9, S5: nothing in these exports a tool span can be paired by."""
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    tools = graph.nodes(kind=TOOL)
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
    for node in graph.nodes(kind=LLM):
        assert set(node.attributes) <= {"model"}, node.id


#: S14: the OpenInference kinds `NodeKind` has no member for, as §7.3 names
#: them.
UNKNOWN_KINDS = ("PROMPT", "RERANKER", "GUARDRAIL", "EVALUATOR")
#: §7.3's S14 reading, whose heading names them.
UNKNOWN_READING = re.compile(
    r"^- \*\*((?:`[A-Z]+`,? (?:and )?)+)are `unknown` by design\*\*", re.MULTILINE
)


def test_adapters_md_names_the_kinds_that_stay_unknown():
    """S14: the kinds §7.3 names are the ones the adapter does not map."""
    match = UNKNOWN_READING.search(_section())
    assert match is not None, "ADAPTERS.md §7.3 has no S14 reading"
    assert tuple(re.findall(r"`([A-Z]+)`", match.group(1))) == UNKNOWN_KINDS
    assert not set(UNKNOWN_KINDS) & set(KINDS)


@pytest.mark.parametrize("kind", UNKNOWN_KINDS)
def test_four_openinference_kinds_are_unknown_with_the_kind_kept(kind):
    """S14: §3.2's closed enum; the dialect's string is `reported_kind`."""
    record = {
        "trace_id": "t",
        "span_id": "s",
        "name": kind.lower(),
        "attributes": {"openinference.span.kind": kind},
    }
    (span,) = OpenInferenceAdapter().parse([record])
    assert span.kind is UNKNOWN
    assert span.attributes["reported_kind"] == kind
    assert [d.code for d in span.diagnostics] == ["unknown_span_kind"]


def test_z1_s_unknown_nodes_are_prompt_templates():
    """S14: the zoo's case -- Z1's `unknown` nodes, each a `ChatPromptTemplate`
    reporting `PROMPT`."""
    for capture, graph in _project_graphs("Z1"):
        unknown = [
            (node.name, node.attributes.get("reported_kind"))
            for node in graph.nodes(kind=UNKNOWN)
        ]
        assert unknown == [("ChatPromptTemplate", "PROMPT")] * len(unknown)
        assert unknown, capture.run


# --- S13: Z5's real and recorded graphs (TASKS.md, stranger's-trace) --------

#: Z5's two captures: one agent, one script, a real model and a recorded one.
Z5 = tuple(capture for capture in CAPTURES if _project(capture) == "Z5")
#: The `raw.source` keys that carry a node's times as the record stated them.
RAW_TIMES = ("start_time", "end_time")


def _z5_masked(capture: Capture) -> dict[str, object]:
    """Z5's graph with what the exporter generated masked, and nothing else.

    Masked, as the S13 decision names them (decisions 2026-10-14e, commit 1):
    the trace id; every node id and every parent id, by the node's position
    in `started_at` order -- an absent parent by the position of the node that
    states it; and every time -- `started_at`, `ended_at`, each diagnostic's
    `source.time`, and the `raw.source` fields that carry those values
    (`start_time`, `end_time`, each event's `timeUnixNano`). An id is masked
    wherever the serialized graph carries it, a diagnostic's message included.
    `edges` and `diagnostics` are serialized in an order the ids decide, so
    once the ids are masked each is put in the order of its masked entries.
    """
    graph = graph_from_records([r.record for r in zoo_census.records(capture)])
    nodes = sorted(graph.nodes(), key=lambda node: node.started_at or 0.0)
    # The premise the positions rest on: the graph's own order is start order.
    assert [node.id for node in graph.nodes()] == [node.id for node in nodes]
    masks = {capture.trace_id: "<trace>"}
    masks.update({node.id: f"<node {i}>" for i, node in enumerate(nodes)})
    for i, node in enumerate(nodes):
        parent = spanweave.envelope(node.raw.source).parent_id
        if parent is not None and parent not in masks:
            masks[parent] = f"<parent of node {i}>"
    text = spanweave.dumps(graph).decode("utf-8")
    for value, mask in masks.items():
        text = text.replace(value, mask)
    document = json.loads(text)
    for node in document["nodes"]:
        node["started_at"] = node["ended_at"] = "<time>"
        source = node["raw"]["source"]
        for key in RAW_TIMES:
            if key in source:
                source[key] = "<time>"
        for event in source.get("events", []):
            event["timeUnixNano"] = "<time>"
    for diagnostic in document["diagnostics"]:
        if isinstance(diagnostic["source"], dict) and "time" in diagnostic["source"]:
            diagnostic["source"]["time"] = "<time>"
    for key in ("edges", "diagnostics"):
        document[key].sort(key=lambda entry: json.dumps(entry, sort_keys=True))
    return document


Path = tuple[str | int, ...]


def _differences(
    real: object, recorded: object, path: Path = ()
) -> dict[Path, tuple[object, object]]:
    """Every path at which two JSON documents differ, with both values."""
    if type(real) is not type(recorded):
        return {path: (real, recorded)}
    found: dict[Path, tuple[object, object]] = {}
    if isinstance(real, dict) and isinstance(recorded, dict):
        for key in sorted(set(real) | set(recorded)):
            if key not in real or key not in recorded:
                missing = "<missing>"
                found[(*path, key)] = (
                    real.get(key, missing),
                    recorded.get(key, missing),
                )
            else:
                found.update(_differences(real[key], recorded[key], (*path, key)))
    elif isinstance(real, list) and isinstance(recorded, list):
        if len(real) != len(recorded):
            found[(*path, "<length>")] = (len(real), len(recorded))
        for i, (a, b) in enumerate(zip(real, recorded, strict=False)):
            found.update(_differences(a, b, (*path, i)))
    elif real != recorded:
        found[path] = (real, recorded)
    return found


def _metadata(step: int, namespace: str, echoed: bool) -> str:
    """The `metadata` attribute LangGraph's instrumentor wrote on a Z5 span."""
    echo = f', "checkpoint_ns": "fetch:{namespace}"' if echoed else ""
    return (
        f'{{"ls_integration": "langgraph", "langgraph_step": {step}, '
        '"langgraph_node": "fetch", "langgraph_triggers": ["branch:to:fetch"], '
        '"langgraph_path": ["__pregel_pull", "fetch"], '
        f'"langgraph_checkpoint_ns": "fetch:{namespace}"{echo}}}'
    )


#: LangGraph's checkpoint namespace, a UUID per graph step: (real, recorded).
STEP_1 = (
    "13c8cbdc-e06c-6927-60b8-a6f5cfee2d2f",
    "e884de76-fa1f-0901-db68-19647c7fb66c",
)
STEP_2 = (
    "f99eb4f6-24b7-ba6a-d068-37e54a2e9909",
    "c7ae6562-c7f2-7791-f2dc-9e87927276e5",
)
#: The SDK's `service.instance.id`, a UUID per process: (real, recorded).
INSTANCE = (
    "87de38a6-473a-4b0e-8ae1-2d4d738fdb8b",
    "2728ccd6-0b17-4ca7-885f-8b8009e66799",
)
#: Per node, in start order: (langgraph step, its namespaces, `checkpoint_ns`
#: echoed). Nodes 1 and 3 are the `http_get` tool spans.
METADATA = {
    0: (1, STEP_1, False),
    1: (1, STEP_1, True),
    2: (1, STEP_1, False),
    3: (2, STEP_2, True),
}
RESOURCE_ATTRIBUTE = ("raw", "source", "resource_spans", "resource", "attributes")
#: S13's answer: what still differs once the exporter's ids and times are
#: masked. Two values, neither one the decision named: the SDK's
#: `service.instance.id` on every node's resource, and LangGraph's checkpoint
#: namespace inside every node's `metadata` attribute. Everything else --
#: names, kinds, payloads, statuses, the exception messages and stacktraces,
#: edges, diagnostics, meta -- is equal.
S13_DIFFERENCES: dict[Path, tuple[object, object]] = {
    **{
        ("nodes", i, "raw", "source", "attributes", "metadata"): (
            _metadata(step, real, echoed),
            _metadata(step, recorded, echoed),
        )
        for i, (step, (real, recorded), echoed) in METADATA.items()
    },
    **{
        ("nodes", i, *RESOURCE_ATTRIBUTE, 3, "value", "stringValue"): INSTANCE
        for i in range(4)
    },
}


def test_z5_s_real_and_recorded_graphs_differ_past_ids_and_times_in_two_uuids():
    """S13: past the exporter's ids and times, two generated UUIDs and no more."""
    assert [c.run for c in Z5] == ["z5/2026-10-13-real", "z5/2026-10-13-recorded"]
    real, recorded = (_z5_masked(capture) for capture in Z5)
    assert _differences(real, recorded) == S13_DIFFERENCES
    # The list is the whole difference, byte for byte: with those values
    # carried across, the two serialized graphs are the same bytes.
    for (*parents, last), (value, _) in S13_DIFFERENCES.items():
        target: Any = recorded
        for step in parents:
            target = target[step]
        target[last] = value
    assert json.dumps(real, sort_keys=True) == json.dumps(recorded, sort_keys=True)
