"""Loading the conformance corpus, and reducing a graph to canonical form.

The corpus encodes the library's central claim in a form that can fail:

    the same run, described by any supported instrumentor, produces the same
    canonical graph.

``canonical()`` erases what is legitimately dialect-specific **and nothing
else** (``FIXTURES.md`` §4): provenance, the verbatim source record, the
*encoding* of a payload, and the adapter fields on edges and meta. What
remains -- ids, kinds, operations, timestamps, statuses, payload states and
values, usage, every edge with its warrant and basis, the node order, and the
diagnostics by code and count -- is compared.

**Never weaken this to make a test pass.** That inverts the corpus: instead of
the fixtures testing the code, the code would be editing the fixtures. If a
dialect fails equivalence, either the adapter is wrong or the model is, and
finding out which is the entire value on offer.

A rendering is only *buildable* if its dialect has a registered adapter.
Between `TASKS.md` 2.8 and 2.13 that gap was real -- renderings landed before
the adapter that reads them -- and it was the one place this suite could go
quiet without going red. It is closed: every dialect the corpus names has an
adapter, and `Rendering.supported` survives as the guard that says so rather
than as a state anything is expected to be in.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spanweave.adapters import registered
from spanweave.ids import DERIVED_PREFIX

CORPUS = pathlib.Path(__file__).resolve().parent.parent / "fixtures/conformance"

#: Erased from every node: the source record differs by construction, and who
#: parsed it is not a property of the run.
ERASED_NODE_FIELDS = ("raw", "provenance")
#: Erased from every payload: the *encoding* of a payload is dialect-specific
#: even when its parsed value is not.
ERASED_PAYLOAD_FIELDS = ("raw",)
#: Erased from every edge: which adapter asserted it is not a property of the
#: relation.
ERASED_EDGE_FIELDS = ("adapter",)

#: The only `Payload` fields a scenario may declare dialect-varying
#: (`FIXTURES.md` §4.4). Fixed **here**, never read from a fixture, so that no
#: declaration can reach `state`: `absent` != `empty` != `redacted` is the
#: model's central honesty claim (`SPEC.md` §3.3), and two dialects disagreeing
#: about a payload's *state* must stay a finding rather than something a
#: comparison file can absorb.
DECLARABLE_PAYLOAD_FIELDS = frozenset({"value", "mime"})

#: The only node fields a scenario may erase **one key of**, by dotted path
#: (`FIXTURES.md` §4.5). Fixed here, never read from a fixture, and it is a
#: whitelist rather than a blacklist for one reason: `inputs` and `outputs`
#: are mappings too, so a dotted erasure that reached them would route
#: straight around §4.4's guarantee that `state` can never be set aside. The
#: narrow mechanism must not be reachable through the broad one.
DECLARABLE_NODE_MAPPINGS = frozenset({"attributes"})


def canonical(
    document: dict[str, Any],
    erase: tuple[str, ...] = (),
    drop_payloads: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """The dialect-independent form of a graph document.

    ``erase`` names what a scenario has declared dialect-varying in its
    ``scenario.md``: a node field (``name``), or **one key of one node
    mapping** by dotted path (``attributes.reported_kind``), and only where
    the scenario says so explicitly. A dotted path is honoured only into
    ``DECLARABLE_NODE_MAPPINGS``.

    ``drop_payloads`` maps a ``"<node id>.<inputs|outputs>"`` selector to the
    payload fields that scenario has declared dialect-varying (§4.4). **It is
    passed only by the cross-dialect comparison.** The within-dialect check
    passes nothing, so every declared field is still pinned there -- which is
    the whole reason a declaration costs the corpus no regression detection.
    """
    nodes = [_node(node, erase, drop_payloads or {}) for node in document["nodes"]]
    edges = [_without(edge, ERASED_EDGE_FIELDS) for edge in document["edges"]]
    labels = _positional_labels(document["nodes"])
    relabelled_edges = [_relabelled(edge, labels, ("src", "dst")) for edge in edges]
    if labels:
        # `SPEC.md` §5.2 sorts edges by `(kind, src, dst, basis)` -- over the
        # ids the graph actually carries, which for a derived id differ by
        # adapter by design. So two faithful renderings of a scenario with
        # two or more edges between derived-id nodes hold the SAME edges in
        # DIFFERENT orders, and claim 2 would fail on id-generation trivia --
        # exactly what `_positional_labels` exists to prevent, applied to
        # only half of what an id decides. Re-sorted on the labels, the order
        # is the one §5.2 describes, expressed in the only ids that are
        # comparable here. Untouched where no id was relabelled, so the
        # library's own edge order stays pinned everywhere it means anything
        # (`FIXTURES.md` §4.1).
        relabelled_edges.sort(
            key=lambda edge: (
                edge["kind"],
                edge["src"],
                edge["dst"],
                edge["basis"] or "",
            )
        )
    return {
        "meta": {
            "schema_version": document["schema_version"],
            "trace_id": document["trace_id"],
            "node_count": len(document["nodes"]),
            "edge_count": len(document["edges"]),
            "diagnostic_count": len(document["diagnostics"]),
        },
        "nodes": [_relabelled(node, labels, ("id",)) for node in nodes],
        "edges": relabelled_edges,
        "diagnostics": _by_code(document["diagnostics"]),
    }


def _positional_labels(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """§4.1's second rule: a **derived** id is compared by position, not value.

    `SPEC.md` §3.6 puts the adapter id into the material of a derived node id,
    so two faithful renderings of one run cannot produce the same one -- and a
    scenario in which any node gets a derived id would otherwise fail claim 2
    on id-generation trivia rather than on anything about the model. Positions
    are what remains comparable, and the node list is already in a
    deterministic order (`SPEC.md` §5.2).

    A dialect's **own** span id is untouched: renderings share those by
    convention (§4.1's first rule), and comparing them is the point.

    This mechanism was documented in `FIXTURES.md` §4.1 for two phases before
    any scenario produced a derived id, and in those two phases it was not
    implemented. It is now, and `duplicate_span_ids` is what uses it.
    """
    return {
        node["id"]: f"n{index}"
        for index, node in enumerate(nodes)
        if str(node["id"]).startswith(DERIVED_PREFIX)
    }


def anonymised(value: Any) -> Any:
    """§4.1's rule applied to a **consumer's** output rather than a graph.

    The example consumers carry node ids through into their own documents, so
    a scenario whose nodes get derived ids makes two faithful dialect
    renderings disagree there for the same reason `canonical()` exists: the
    adapter id is in the material (`SPEC.md` §3.6). Every `sw_` id is replaced
    by `n0`, `n1`, ... in order of first appearance -- which, for output that
    follows node order, is the same label `canonical()` gave it, so a consumer
    document can be compared against `expected/graph.json` directly.

    A dialect's own span id is left alone: that is the half of §4.1 the corpus
    still compares by value.
    """
    labels: dict[str, str] = {}

    def label(text: str) -> str:
        if not text.startswith(DERIVED_PREFIX):
            return text
        return labels.setdefault(text, f"n{len(labels)}")

    def walk(entry: Any) -> Any:
        if isinstance(entry, str):
            return label(entry)
        if isinstance(entry, Mapping):
            return {walk(key): walk(value) for key, value in entry.items()}
        if isinstance(entry, list):
            return [walk(item) for item in entry]
        if isinstance(entry, tuple):
            return tuple(walk(item) for item in entry)
        return entry

    return walk(value)


def _relabelled(
    entry: dict[str, Any], labels: Mapping[str, str], fields: tuple[str, ...]
) -> dict[str, Any]:
    if not labels:
        return entry
    return {
        key: labels.get(value, value) if key in fields else value
        for key, value in entry.items()
    }


def _node(
    node: dict[str, Any],
    erase: tuple[str, ...],
    drop_payloads: Mapping[str, frozenset[str]],
) -> dict[str, Any]:
    fields, keys = split_erasures(erase)
    kept = _without(node, (*ERASED_NODE_FIELDS, *fields))
    for mapping, erased in keys.items():
        if mapping in kept:
            kept[mapping] = _without(kept[mapping], tuple(sorted(erased)))
    for side in ("inputs", "outputs"):
        declared = drop_payloads.get(f"{node['id']}.{side}", frozenset())
        # Guarded rather than trusted: a declaration naming `state` would be
        # the one erasure this corpus must never make, and the guard belongs
        # where the erasure happens, not only where the fixture is read.
        declared = frozenset(declared) & DECLARABLE_PAYLOAD_FIELDS
        kept[side] = _without(kept[side], (*ERASED_PAYLOAD_FIELDS, *sorted(declared)))
    return kept


def split_erasures(
    erase: tuple[str, ...],
) -> tuple[tuple[str, ...], dict[str, frozenset[str]]]:
    """A scenario's `erase` list, split into whole fields and dotted keys.

    Public because the corpus tests assert on the split itself: an entry that
    names a mapping this corpus does not allow keys to be erased from is
    dropped **here**, so the guard sits where the erasure happens and not only
    where the fixture is read.
    """
    fields = tuple(entry for entry in erase if "." not in entry)
    keys: dict[str, set[str]] = {}
    for entry in erase:
        mapping, dot, key = entry.partition(".")
        if dot and mapping in DECLARABLE_NODE_MAPPINGS and key:
            keys.setdefault(mapping, set()).add(key)
    return fields, {mapping: frozenset(k) for mapping, k in keys.items()}


def _without(mapping: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key not in fields}


def _by_code(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diagnostics compared by code and count (`FIXTURES.md` §4)."""
    counts: dict[str, int] = {}
    for diagnostic in diagnostics:
        counts[diagnostic["code"]] = counts.get(diagnostic["code"], 0) + 1
    return [{"code": code, "count": counts[code]} for code in sorted(counts)]


#: Every dialect the corpus is expected to cover. A scenario must either
#: render each of these or declare in `expected/coverage.json` that it cannot
#: (`FIXTURES.md` §4.3). `otel_genai` was added at `TASKS.md` 2.13, and that
#: one line is what makes every scenario account for it.
#:
#: There is no longer a "pending" list beside this. There was one between 2.7
#: and 2.13, holding a dialect an adapter could read while the corpus did not
#: yet require coverage of it, and it is deleted rather than emptied: a
#: transitional mechanism left in place outlives its transition, and an empty
#: exemption list is an invitation to put something in it.
DIALECTS = ("openinference", "otel_genai")

#: What separates the dialect ids in the stem of a rendering **several**
#: adapters read: `openinference+otel_genai.jsonl`. A dialect is a property of
#: a record rather than of a file (`SPEC.md` §6.1), so one file can carry two
#: instrumentors' records, and the corpus needs a way to name that file's
#: contents without inventing a dialect for it. `+` is that way, and it is
#: deliberately **not** a member of `DIALECTS`: nothing is obliged to render a
#: mix, no adapter answers to the composite name, and the parts are the only
#: things a registry ever sees.
COMPOSITE = "+"


def dialect_parts(dialect: str) -> tuple[str, ...]:
    """The dialects a rendering's stem names -- one, or several joined by `+`."""
    return tuple(dialect.split(COMPOSITE))


@dataclass(frozen=True)
class Scenario:
    """One directory of `fixtures/conformance/`."""

    name: str
    path: pathlib.Path
    dialects: tuple[pathlib.Path, ...] = ()
    erase: tuple[str, ...] = field(default=())

    @property
    def expected_graph(self) -> dict[str, Any] | None:
        path = self.path / "expected/graph.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def expected_diagnostics(self) -> list[dict[str, Any]] | None:
        path = self.path / "expected/diagnostics.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["expected"]

    @property
    def expected_error(self) -> dict[str, Any] | None:
        """Some scenarios must NOT build. That is the assertion (§4.2)."""
        path = self.path / "expected/error.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def coverage(self) -> dict[str, Any]:
        """Dialects this scenario declares it cannot render (§4.3)."""
        path = self.path / "expected/coverage.json"
        if not path.exists():
            return {}
        declared = json.loads(path.read_text(encoding="utf-8"))
        return {
            dialect: entry
            for dialect, entry in declared.items()
            if not dialect.startswith("_")
        }

    @property
    def declaration(self) -> dict[str, Any]:
        """The §4.4 declaration: payloads dialects record differently, and why."""
        path = self.path / "expected/comparison.json"
        if not path.exists():
            return {}
        declared = json.loads(path.read_text(encoding="utf-8"))
        entry = declared.get("dialect_varying_payloads")
        return entry if isinstance(entry, dict) else {}

    @property
    def drop_payloads(self) -> dict[str, frozenset[str]]:
        """Selector -> declared fields, for the CROSS-DIALECT comparison only."""
        payloads = self.declaration.get("payloads", {})
        return {
            str(selector): frozenset(str(field) for field in fields)
            for selector, fields in payloads.items()
        }

    def overrides(self, dialect: str) -> dict[str, dict[str, Any]]:
        """This dialect's own values for the payloads declared above (§4.4).

        Absent means "agrees with `graph.json`". A dialect that differs and
        omits the file fails the within-dialect check loudly, which is why the
        declaration costs no regression detection.
        """
        path = self.path / f"expected/payloads/{dialect}.json"
        if not path.exists():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(selector): fields
            for selector, fields in loaded.items()
            if not str(selector).startswith("_")
        }

    def expected_graph_for(self, dialect: str) -> dict[str, Any] | None:
        """`graph.json` as this dialect expects it -- claim 1's target (§4)."""
        graph = self.expected_graph
        overrides = self.overrides(dialect)
        if graph is None or not overrides:
            return graph
        nodes = []
        for node in graph["nodes"]:
            node = dict(node)
            for side in ("inputs", "outputs"):
                fields = overrides.get(f"{node['id']}.{side}")
                if fields:
                    node[side] = {**node[side], **fields}
            nodes.append(node)
        return {**graph, "nodes": nodes}

    def rendering(self, dialect: str) -> pathlib.Path | None:
        for path in self.dialects:
            if path.stem == dialect:
                return path
        return None

    def declared_unrenderable(self, dialect: str) -> str | None:
        """The stated reason this dialect cannot render it, if it says so."""
        entry = self.coverage.get(dialect)
        if entry is None or entry.get("renderable", True):
            return None
        return str(entry.get("reason", ""))


def scenarios() -> tuple[Scenario, ...]:
    found = []
    for path in sorted(CORPUS.iterdir()):
        if not path.is_dir():
            continue
        dialects = (
            sorted((path / "dialects").glob("*"))
            if (path / "dialects").exists()
            else []
        )
        comparison = path / "expected/comparison.json"
        erase = ()
        if comparison.exists():
            erase = tuple(json.loads(comparison.read_text(encoding="utf-8"))["erase"])
        found.append(
            Scenario(name=path.name, path=path, dialects=tuple(dialects), erase=erase)
        )
    return tuple(found)


def adapter_backed() -> frozenset[str]:
    """Dialect ids the library can actually build a rendering of, today.

    Read from the registry rather than listed here, so it cannot disagree with
    what is installed.
    """
    return frozenset(adapter.id for adapter in registered())


@dataclass(frozen=True)
class Rendering:
    """One dialect file of one scenario -- the unit equivalence compares.

    The suite parametrizes over these rather than over scenarios, because
    "every dialect of this scenario agrees" is the claim, and a per-scenario
    parametrization can only ever check the first one.
    """

    scenario: Scenario
    dialect: str
    path: pathlib.Path

    @property
    def supported(self) -> bool:
        """Can the library read this rendering at all?

        Every dialect the stem names must have an adapter -- one name, or
        each part of a composite. A mixed rendering is buildable exactly when
        both of its halves are, which is the same question asked twice and
        never a new capability of the harness.
        """
        backed = adapter_backed()
        return all(part in backed for part in dialect_parts(self.dialect))

    @property
    def skip_reason(self) -> str:
        # Reachable only if a rendering is added for a dialect nothing can
        # read. That was a planned state until 2.13 and is a mistake now, so
        # the wording says so -- a skip that reads like a known condition is
        # a skip nobody investigates.
        return (
            f"no registered adapter for dialect {self.dialect!r}: "
            f"{self.scenario.name} renders it and nothing can read it. Since "
            f"TASKS.md 2.13 this is a defect, not a transition"
        )

    @property
    def label(self) -> str:
        return f"{self.scenario.name}[{self.dialect}]"


def renderings(collection: Sequence[Scenario]) -> tuple[Rendering, ...]:
    """Every dialect file present, adapter-backed or not.

    Deliberately *not* filtered to the supported ones: a rendering nothing can
    build must still appear in the suite, as a skip with a reason. Filtering
    here is precisely how a dialect's coverage would rot one file at a time.
    """
    return tuple(
        Rendering(scenario=scenario, dialect=path.stem, path=path)
        for scenario in collection
        for path in scenario.dialects
    )


def unsupported(collection: Sequence[Scenario]) -> tuple[Rendering, ...]:
    """The renderings the suite is currently skipping, in a stable order."""
    return tuple(
        rendering for rendering in renderings(collection) if not rendering.supported
    )
