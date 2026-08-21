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
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

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


def canonical(document: dict[str, Any], erase: tuple[str, ...] = ()) -> dict[str, Any]:
    """The dialect-independent form of a graph document.

    ``erase`` names extra node fields a scenario has declared dialect-varying
    in its ``scenario.md`` -- ``name`` is the only one so far, and only where
    the scenario says so explicitly.
    """
    return {
        "meta": {
            "schema_version": document["schema_version"],
            "trace_id": document["trace_id"],
            "node_count": len(document["nodes"]),
            "edge_count": len(document["edges"]),
            "diagnostic_count": len(document["diagnostics"]),
        },
        "nodes": [_node(node, erase) for node in document["nodes"]],
        "edges": [_without(edge, ERASED_EDGE_FIELDS) for edge in document["edges"]],
        "diagnostics": _by_code(document["diagnostics"]),
    }


def _node(node: dict[str, Any], erase: tuple[str, ...]) -> dict[str, Any]:
    kept = _without(node, (*ERASED_NODE_FIELDS, *erase))
    for side in ("inputs", "outputs"):
        kept[side] = _without(kept[side], ERASED_PAYLOAD_FIELDS)
    return kept


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
#: (`FIXTURES.md` §4.3). Phase 2 adds the second entry here, and that addition
#: is what makes every scenario account for it.
DIALECTS = ("openinference",)


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
