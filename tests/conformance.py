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

A rendering is only *buildable* if its dialect has a registered adapter. That
gap is transitional -- `TASKS.md` 2.8 lands renderings before 2.9 lands the
adapter that reads them -- and it is the one place this suite could go quiet
without going red. So the gap is named (`Rendering.supported`), reported
(`tests/conftest.py` puts it in the pytest header, and each such rendering is
an explicitly skipped test rather than an absent one), and fenced by the
tripwire in `test_conformance.py`.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spanweave.adapters import registered

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

#: Dialects a registered adapter can read but `DIALECTS` does not yet name --
#: so the corpus is NOT yet requiring any scenario to cover them.
#:
#: Transitional and declared, in the shape `FIXTURES.md` §4.3 already uses for
#: a scenario a dialect cannot render, and for the same reason: a declared gap
#: is reviewable, a silent one rots. **Empty is the only correct long-term
#: value.** `TASKS.md` 2.13 flips `DIALECTS` and deletes this. Never add an
#: entry to make a test green.
DIALECTS_PENDING_CORPUS_COVERAGE: tuple[str, ...] = ()


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
        return self.dialect in adapter_backed()

    @property
    def skip_reason(self) -> str:
        return (
            f"no registered adapter for dialect {self.dialect!r}: "
            f"{self.scenario.name} renders it, but nothing can read it yet "
            f"(TASKS.md 2.8 renders, 2.9 adapts, 2.13 closes)"
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
