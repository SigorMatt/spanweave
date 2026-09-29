"""The definition of a delta, written as a checkpoint diff of two graphs.

`SPEC.md` §10.6 defines `delta(a, b)` as the set difference `graph(b) - graph(a)`
and says that anything computing it faster is an implementation which must agree
with the definition. This module *is* the definition: it materializes both
graphs and diffs them, knowing nothing about how the journal is kept.

So it is deliberately slow and deliberately dumb. Multiset difference by list
removal, node comparison by value against a list: every shortcut here would be
a chance to share a mistake with the thing under test, which is the one thing a
test oracle may not do (`OPEN_QUESTIONS.md` §18, "the checkpoint diff as the
test oracle").

One field it cannot compute is `restated`. Whether an arrival re-derived every
node id is a fact about the *arrival*, and two graphs do not carry it -- a
restatement whose ids all happen to land in the same place looks, from the
endpoints, like nothing at all. So the caller hands it in, and
`tests/test_live.py` pins separately when it is true.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from spanweave.delta import Delta
from spanweave.graph import Graph
from spanweave.model import Diagnostic, Edge, Node, NodeId

_Item = TypeVar("_Item", Node, Edge, Diagnostic)


def difference(after: Sequence[_Item], before: Sequence[_Item]) -> list[_Item]:
    """Everything in `after` that `before` does not account for.

    Multiset, not set: diagnostics are collected into a list and nothing
    deduplicates them (`spanweave/diagnostics.py`), so two identical
    diagnostics are two diagnostics and a diff that collapsed them would
    disagree with the graph.
    """
    unmatched = list(before)
    found: list[_Item] = []
    for item in after:
        if item in unmatched:
            unmatched.remove(item)
        else:
            found.append(item)
    return found


def order_moved(before: Graph, after: Graph) -> bool:
    """Did the nodes both graphs hold change their order relative to each other?

    Not "are the two orders different", which a single added node makes true
    and which would say nothing. The question a consumer asks is whether what
    it already had has moved (`SPEC.md` §10.6).
    """
    shared = set(before.topo_order) & set(after.topo_order)
    return _kept(before.topo_order, shared) != _kept(after.topo_order, shared)


def _kept(order: Sequence[NodeId], shared: set[NodeId]) -> tuple[NodeId, ...]:
    return tuple(node_id for node_id in order if node_id in shared)


def checkpoint_delta(
    before: Graph | None,
    after: Graph,
    *,
    since: int,
    until: int,
    restated: bool,
) -> Delta:
    """`after - before`, per collection. `None` is the graph before version 1."""
    old_nodes = before.nodes() if before is not None else ()
    old_edges = before.edges() if before is not None else ()
    old_diagnostics = before.diagnostics if before is not None else ()
    old_trace_id = before.trace_id if before is not None else ""
    old_adapters = (
        before.meta.adapters if before is not None and before.meta is not None else ()
    )
    return Delta(
        since=since,
        until=until,
        nodes_added=tuple(difference(after.nodes(), old_nodes)),
        nodes_removed=tuple(difference(old_nodes, after.nodes())),
        edges_added=tuple(difference(after.edges(), old_edges)),
        edges_removed=tuple(difference(old_edges, after.edges())),
        diagnostics_opened=tuple(difference(after.diagnostics, old_diagnostics)),
        diagnostics_resolved=tuple(difference(old_diagnostics, after.diagnostics)),
        trace_id_before=old_trace_id,
        trace_id_after=after.trace_id,
        adapters_before=tuple(old_adapters),
        adapters_after=tuple(after.meta.adapters if after.meta is not None else ()),
        order_changed=(order_moved(before, after) if before is not None else False),
        restated=restated,
    )
