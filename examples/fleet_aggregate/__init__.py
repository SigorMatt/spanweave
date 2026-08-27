"""A fleet rollup: many traces in, one set of counts out.

This is the Phase 2b **adversarial** consumer (`TASKS.md` 2.3). It exists to
attack `PREDICTIONS.md` P5 -- *one trace = one graph* -- by being the thing
that prediction says will hurt: a consumer that wants every trace at once.

Two rules it keeps, because breaking either would fake a generality the
library has not earned:

* **Public API only** -- exactly what ``spanweave/__init__.py`` exports.
  Reaching into an internal module would answer a question nobody asked.
* **Dialect-neutral** -- it reads the *model* (kinds, statuses, operations,
  diagnostic codes) and never a dialect's payload shape. Where that costs it
  an answer, it says so in ``limits`` rather than reaching into
  ``Payload.value`` and quietly becoming an OpenInference tool.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable, Mapping
from typing import Any

from spanweave import Diagnostic, Graph, NodeKind, SpanweaveError, Status, build

#: Why a rollup line is missing, in the output, machine-readable. The library
#: degrades honestly (`CLAUDE.md` 2); a consumer that swallowed the gap would
#: undo that one layer up.
#:
#: **This finding is closed** (F5 / `PREDICTIONS.md` O1). It read:
#:
#: > `unfulfilled_calls.by_tool` is empty: `unpaired_call` names the requesting
#: > node and the call id, and a call that was requested but never ran has no
#: > node, so the tool it asked for is not on the graph. Recovering it means
#: > parsing the requesting node's outputs payload -- one dialect's shape, in a
#: > consumer that must not know one.
#:
#: `SPEC.md` §3.7 now states the tool name on the diagnostic itself, so the
#: rollup below is populated from `source["operation"]` and no payload is
#: walked. Kept only for the case the library still cannot answer: a dialect
#: that names no tool at all, where the honest output is a labelled bucket
#: rather than a silently smaller total.
UNNAMED_CALLS = (
    "some unfulfilled calls are counted under `(dialect named no tool)`: the "
    "diagnostic carried `operation: null`, meaning the instrumentor stated an "
    "id and no name. That is a gap in the trace, not in the rollup, and it is "
    "bucketed rather than dropped so the by_tool total still reconciles."
)

#: The bucket above. Named rather than spelled inline, because a consumer
#: filtering it out needs something stable to filter on.
UNNAMED_TOOL = "(dialect named no tool)"


class TraceFailure:
    """A trace that did not build.

    A fleet consumer needs failures *in* the rollup, not raised out of it: one
    malformed trace must not cost you the other ten thousand. The library has
    no such record -- a structural problem raises (`SPEC.md` §3.10) rather than
    producing a graph plus a diagnostic -- so the consumer invents one.
    """

    def __init__(self, source: str, error: BaseException) -> None:
        self.source = source
        self.error = error
        # `SPEC.md` §3.10: match on the code, never on the message -- and the
        # type is what says whether there IS a code. A trace the library
        # deliberately refused and a file that was not there are different
        # facts about a fleet, and before `SpanweaveError` was exported this
        # consumer could not tell them apart: it read `.code` off whatever it
        # caught, and an absent attribute is not a statement (`TASKS.md` F4).
        self.refused = isinstance(error, SpanweaveError)
        self.code = error.code if isinstance(error, SpanweaveError) else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "error": type(self.error).__name__,
            # True: the library read this trace and refused it, and `code`
            # says why. False: something else went wrong -- a missing file, a
            # permissions error -- and there is no code to match on.
            "refused": self.refused,
            "code": self.code,
            "message": str(self.error),
        }


class Fleet:
    """Counts across many graphs.

    Deliberately accumulating rather than holding every graph: a real fleet is
    larger than memory, and the shape of the API you *want* shows up more
    clearly when you cannot cheat by keeping everything.
    """

    def __init__(self) -> None:
        self.given = 0
        self.built = 0
        self.trace_ids: collections.Counter[str] = collections.Counter()
        self.node_kinds: collections.Counter[str] = collections.Counter()
        self.diagnostics: collections.Counter[str] = collections.Counter()
        self.tool_calls: collections.Counter[str] = collections.Counter()
        self.tool_status: collections.Counter[tuple[str, str]] = collections.Counter()
        self.models: collections.Counter[str] = collections.Counter()
        self.unfulfilled_calls = 0
        self.unfulfilled_calls_by_model: collections.Counter[str] = (
            collections.Counter()
        )
        self.unfulfilled_calls_by_tool: collections.Counter[str] = collections.Counter()
        self.unfulfilled_results = 0
        self.failures: list[TraceFailure] = []

    # -- accumulation ------------------------------------------------------

    def add(self, source: str, graph: Graph) -> None:
        self.built += 1
        self.trace_ids[graph.trace_id] += 1

        for node in graph.nodes():
            self.node_kinds[str(node.kind)] += 1
            operation = node.operation
            if operation is None:
                continue
            if node.kind is NodeKind.TOOL:
                self.tool_calls[operation] += 1
                self.tool_status[(operation, str(node.status))] += 1
            elif node.kind is NodeKind.LLM:
                self.models[operation] += 1

        for diagnostic in graph.diagnostics:
            self.diagnostics[diagnostic.code] += 1
            # Counted separately because these two are the fleet questions
            # people actually ask -- "what got requested and never ran" and
            # "what came back that nobody asked for".
            if diagnostic.code == "unpaired_call":
                self.unfulfilled_calls += 1
                self.unfulfilled_calls_by_model[_asker(graph, diagnostic)] += 1
                self.unfulfilled_calls_by_tool[_asked_for(diagnostic)] += 1
            elif diagnostic.code == "unpaired_result":
                self.unfulfilled_results += 1

    def fail(self, source: str, error: BaseException) -> None:
        self.failures.append(TraceFailure(source, error))

    # -- output ------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """The rollup, in a form that sorts the same way every time."""
        limits: list[str] = []
        if self.unfulfilled_calls_by_tool[UNNAMED_TOOL]:
            limits.append(UNNAMED_CALLS)

        return {
            "traces": {
                "given": self.given,
                "built": self.built,
                "unbuildable": len(self.failures),
                "distinct_trace_ids": len(self.trace_ids),
            },
            # Every kind, including the zeros: a fleet's rollup schema must not
            # change shape because one fleet happened to contain no retrievers.
            "node_kinds": {
                str(kind): self.node_kinds[str(kind)] for kind in sorted(NodeKind)
            },
            "diagnostics": _sorted(self.diagnostics),
            "tools": {
                name: {
                    "calls": self.tool_calls[name],
                    "errors": self.tool_status[(name, str(Status.ERROR))],
                    "ok": self.tool_status[(name, str(Status.OK))],
                    "unset": self.tool_status[(name, str(Status.UNSET))],
                }
                for name in sorted(self.tool_calls)
            },
            "models": _sorted(self.models),
            "unfulfilled_calls": {
                "total": self.unfulfilled_calls,
                # Answerable: the diagnostic names the node that asked, and
                # `Node.operation` on an `llm` is the model (`SPEC.md` §3.1).
                "by_model": _sorted(self.unfulfilled_calls_by_model),
                # Answerable since `SPEC.md` §3.7 put the tool name on the
                # diagnostic. This line was empty for a whole phase and the
                # emptiness was the finding (F5): the graph knew who asked and
                # not what for. Read off `source`; no payload is walked, so it
                # is the same one line of code in every dialect.
                "by_tool": _sorted(self.unfulfilled_calls_by_tool),
            },
            "unfulfilled_results": self.unfulfilled_results,
            "unbuildable": [
                failure.as_dict()
                for failure in sorted(self.failures, key=lambda f: f.source)
            ],
            "limits": limits,
        }


def _asked_for(diagnostic: Diagnostic) -> str:
    """Which tool this unfulfilled call asked for (`SPEC.md` §3.7).

    Defensive about the shape rather than trusting it: `Diagnostic.source` is
    typed `JsonValue`, so a library older than the §3.7 table -- or a future
    code reusing this counter -- would put a bare string here. An unreadable
    source becomes a labelled bucket, never a dropped count.
    """
    source = diagnostic.source
    if not isinstance(source, dict):
        return UNNAMED_TOOL
    named = source.get("operation")
    return named if isinstance(named, str) else UNNAMED_TOOL


def _asker(graph: Graph, diagnostic: Diagnostic) -> str:
    """Which model left this call unfulfilled.

    A diagnostic may carry no node at all (`ordering_cycle` is graph-scoped),
    and `Graph.node` returns `None` for an id the graph does not hold, so both
    are named rather than assumed away.
    """
    if diagnostic.node_id is None:
        return "(no node on the diagnostic)"
    node = graph.node(diagnostic.node_id)
    if node is None:
        return "(node not in this graph)"
    return node.operation or f"(unnamed {node.kind})"


def _sorted(counter: Mapping[str, int]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def aggregate(sources: Iterable[str]) -> Fleet:
    """Build every trace and roll the results up. Never raises for one trace."""
    fleet = Fleet()
    for source in sources:
        fleet.given += 1
        try:
            graph = build(source)
        # Still broad on purpose -- one bad trace must not cost the other
        # 10,000, and `build` can meet an unreadable file as easily as an
        # unreadable trace. What changed is that `TraceFailure` can now tell
        # the two apart, because `SpanweaveError` is on the public API.
        except Exception as error:
            fleet.fail(source, error)
            continue
        fleet.add(source, graph)
    return fleet
