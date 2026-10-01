"""What changed between two versions of a live graph, and the journal behind it.

``SPEC.md`` §10.6 defines a delta as the set difference of two prefix graphs:
``delta(a, b) = graph(b) - graph(a)``, per collection. That definition is the
contract; everything here is an implementation of it and has to agree with it.
The agreement is not asserted by inspection -- ``tests/delta_oracle.py``
materializes both graphs, diffs them the slow obvious way, and
``tests/test_conformance.py`` runs that oracle against this code at every
version of every rendering in the corpus.

The implementation is a **journal**: every ``feed`` appends the difference that
arrival made, and ``delta(since=v)`` folds the entries after `v`. Folding is
where a delta stops being a log and becomes a summary of two endpoints -- an
``unpaired_call`` opened at version 12 and resolved at 14 is in neither
``graph(11)`` nor ``graph(15)``, so the fold must **cancel** it rather than
report both halves (``OPEN_QUESTIONS.md`` §18).

Two things are deliberately *not* journalled, because they are functions of the
node and edge sets rather than facts of their own: canonical order, and the
``ordering_cycle`` diagnostic that the same topological sort reports
(``SPEC.md`` §5.2). Both are computed at the two endpoints from the sets, by
``build.in_order`` -- the batch builder's own rule, so a folded graph cannot be
ordered by a second one.

Nothing here knows that a dialect exists, and nothing here judges anything: a
delta is three collections and two scalars, counted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Generic, Literal, TypeVar

from spanweave import build
from spanweave.diagnostics import DiagnosticCollector
from spanweave.errors import DeltaUnavailableError
from spanweave.graph import Graph
from spanweave.model import (
    AdapterInfo,
    Diagnostic,
    Edge,
    EdgeKind,
    Node,
    NodeId,
)

#: How a collection's items are grouped. A tuple of plain strings so that it is
#: both hashable and **sortable**: a deterministic iteration order over the
#: groups is what keeps a fold independent of dict insertion order
#: (`CLAUDE.md` 4). `None` is written as `""` for the same reason -- `None` does
#: not sort against a string.
Key = tuple[str, ...]

_Item = TypeVar("_Item", Node, Edge, Diagnostic)

#: The retention vocabulary of `Builder.retain` (`SPEC.md` §10.8).
Retention = int | Literal["all"]


def node_key(node: Node) -> Key:
    return (node.id,)


def edge_key(edge: Edge) -> Key:
    """An edge's identity: unique in a graph, since edges deduplicate on it."""
    return edge.identity


def diagnostic_key(item: Diagnostic) -> Key:
    """A diagnostic's group -- coarse on purpose.

    It deliberately leaves out ``source``, which can be any JSON value the
    input contained and so is neither reliably hashable nor safe to walk to an
    arbitrary depth (`SPEC.md` §7). Nothing is lost: items inside a group are
    compared by **value**, so two diagnostics that agree on everything here and
    differ in their source are two items in one group and stay distinguishable.
    """
    return (
        item.code,
        item.node_id or "",
        str(item.level),
        item.message,
        item.adapter or "",
    )


# --------------------------------------------------------------------------
# The three collections a graph holds, and what changed in them
# --------------------------------------------------------------------------


class Ledger(Generic[_Item]):
    """One collection of a graph, grouped by key, with a change being recorded.

    A *multiset*, not a set: the diagnostic collector deduplicates nothing
    (`spanweave/diagnostics.py`), so two equal diagnostics are two diagnostics
    and a ledger that collapsed them would disagree with the graph.

    Recording works by snapshotting a group the first time an arrival touches
    it and comparing at the end, so an arrival that touches one group does the
    work of one group. It is also what makes the record of a *restating*
    arrival honest rather than small: restating clears every group, so every
    group is snapshotted, and the entry describes the whole state
    (`SPEC.md` §10.7).

    The same snapshot is what `rollback` undoes an arrival from, which is why
    it is one mechanism and not two: every way of changing this collection goes
    through `_touch` first, so traffic added here later is reversible without
    anything else having to be kept in step (`SPEC.md` §10.5).
    """

    def __init__(self, key: Callable[[_Item], Key]) -> None:
        self._key: Callable[[_Item], Key] = key
        self._groups: dict[Key, list[_Item]] = {}
        self._before: dict[Key, tuple[_Item, ...]] = {}

    def add(self, item: _Item) -> None:
        key = self._key(item)
        self._touch(key)
        self._groups.setdefault(key, []).append(item)

    def drop(self, item: _Item) -> None:
        key = self._key(item)
        self._touch(key)
        group = self._groups[key]
        group.remove(item)
        if not group:
            del self._groups[key]

    def clear(self) -> None:
        for key in list(self._groups):
            self._touch(key)
        self._groups.clear()

    def items(self) -> list[_Item]:
        """Everything held, groups in key order. One item per group for edges."""
        return [item for key in sorted(self._groups) for item in self._groups[key]]

    def begin(self) -> None:
        self._before.clear()

    def end(self) -> tuple[tuple[_Item, ...], tuple[_Item, ...]]:
        """`(added, removed)` since `begin`, groups in key order."""
        added: list[_Item] = []
        removed: list[_Item] = []
        for key in sorted(self._before):
            was = list(self._before[key])
            for item in self._groups.get(key, ()):
                if item in was:
                    was.remove(item)
                else:
                    added.append(item)
            removed.extend(was)
        self._before.clear()
        return tuple(added), tuple(removed)

    def rollback(self) -> None:
        """Every group back where `begin` found it; the snapshot cleared.

        The undo of `end`, over exactly the same snapshot: a group `add`,
        `drop` or `clear` touched is restored to the value it held when the
        arrival opened, and a group none of them touched cannot have moved. So
        this is total over whatever an arrival did, in whatever order and
        however many times (`SPEC.md` §10.5).
        """
        for key, was in self._before.items():
            if was:
                self._groups[key] = list(was)
            else:
                self._groups.pop(key, None)
        self._before.clear()

    def _touch(self, key: Key) -> None:
        if key not in self._before:
            self._before[key] = tuple(self._groups.get(key, ()))


class Contributions(Generic[_Item]):
    """What each key contributes to a `Ledger`, with the same snapshot rule.

    `Ledger` holds the items; this holds the attribution that lets one key's
    contribution be *replaced* -- which is what the absorber restates a key
    with. It is separate because the two are keyed differently: a ledger groups
    by an item's own identity, and this groups by the absorber's key (a
    record's position, a call id, a sibling group).

    Snapshotted on first touch, exactly as a ledger group is, so that
    `rollback` puts both halves of a collection back together and a refused
    arrival cannot leave one of them describing the other (`SPEC.md` §10.5).
    """

    def __init__(self) -> None:
        self._now: dict[Key, tuple[_Item, ...]] = {}
        self._before: dict[Key, tuple[_Item, ...]] = {}

    def replace(self, key: Key, items: Sequence[_Item]) -> tuple[_Item, ...]:
        """Record what `key` contributes now; answer what it contributed."""
        was = self._now.get(key, ())
        self._before.setdefault(key, was)
        if items:
            self._now[key] = tuple(items)
        else:
            self._now.pop(key, None)
        return was

    def clear(self) -> None:
        for key, items in self._now.items():
            self._before.setdefault(key, items)
        self._now.clear()

    def begin(self) -> None:
        self._before.clear()

    def end(self) -> None:
        self._before.clear()

    def rollback(self) -> None:
        for key, was in self._before.items():
            if was:
                self._now[key] = was
            else:
                self._now.pop(key, None)
        self._before.clear()


class Tally:
    """The three collections a graph holds, kept current as records arrive.

    The absorber keeps its own per-key dicts, because the order it assembles
    them in is the graph's byte order and that is a contract (`SPEC.md` §5.2).
    This is the *journal's* accounting of the same three collections, and the
    two agreeing is not asserted by reading them side by side: conformance gate
    2 diffs two materialized graphs and compares the answer with what this
    produced, at every version of every rendering in the corpus.

    Keyed by the same keys the absorber restates -- a record's position, a call
    id, a sibling group -- so setting a key is the whole of "what this arrival
    changed here".
    """

    def __init__(self) -> None:
        self.nodes: Ledger[Node] = Ledger(node_key)
        self.edges: Ledger[Edge] = Ledger(edge_key)
        self.diagnostics: Ledger[Diagnostic] = Ledger(diagnostic_key)
        self._edges_for: Contributions[Edge] = Contributions()
        self._diagnostics_for: Contributions[Diagnostic] = Contributions()

    def add_node(self, node: Node) -> None:
        self.nodes.add(node)

    def set_edges(self, key: Key, edges: Sequence[Edge]) -> None:
        """What this key contributes now, replacing what it contributed before."""
        for edge in self._edges_for.replace(key, edges):
            self.edges.drop(edge)
        for edge in edges:
            self.edges.add(edge)

    def set_diagnostics(self, key: Key, items: Sequence[Diagnostic]) -> None:
        for item in self._diagnostics_for.replace(key, items):
            self.diagnostics.drop(item)
        for item in items:
            self.diagnostics.add(item)

    def clear(self) -> None:
        """Everything derived, gone -- what a restating arrival does (§10.2)."""
        self._edges_for.clear()
        self._diagnostics_for.clear()
        self.nodes.clear()
        self.edges.clear()
        self.diagnostics.clear()

    def begin(self) -> None:
        self._edges_for.begin()
        self._diagnostics_for.begin()
        self.nodes.begin()
        self.edges.begin()
        self.diagnostics.begin()

    def rollback(self) -> None:
        """Undo everything since `begin`, in all five halves of all three
        collections. The one rollback every change to this state goes through
        (`SPEC.md` §10.5)."""
        self._edges_for.rollback()
        self._diagnostics_for.rollback()
        self.nodes.rollback()
        self.edges.rollback()
        self.diagnostics.rollback()

    def end(self, before: Facts, after: Facts, restated: bool) -> Change:
        self._edges_for.end()
        self._diagnostics_for.end()
        nodes_added, nodes_removed = self.nodes.end()
        edges_added, edges_removed = self.edges.end()
        opened, resolved = self.diagnostics.end()
        return Change(
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            edges_added=edges_added,
            edges_removed=edges_removed,
            diagnostics_opened=opened,
            diagnostics_resolved=resolved,
            before=before,
            after=after,
            restated=restated,
        )


@dataclass(frozen=True, slots=True)
class Facts:
    """What a graph says that no collection of it holds (`SPEC.md` §10.6).

    ``whole_input`` is not one of them -- it never reaches a graph. It is the
    adapter a statement about the whole input may name (`SPEC.md` §3.7), and it
    is carried because the endpoint recomputation of `ordering_cycle` needs the
    value that was current *then*, not the one that is current now.
    """

    trace_id: str = ""
    adapters: tuple[AdapterInfo, ...] = ()
    whole_input: str | None = None


@dataclass(frozen=True, slots=True)
class Change:
    """One journal entry: what one arrival changed.

    ``restated`` is the entry's own honesty. An arrival that changes one of the
    three whole-input facts re-derives every node id (`SPEC.md` §10.2), so the
    sets below describe the whole state rather than a corner of it; reporting
    such an arrival as a local diff would describe an event that did not
    happen (§10.7).
    """

    nodes_added: tuple[Node, ...] = ()
    nodes_removed: tuple[Node, ...] = ()
    edges_added: tuple[Edge, ...] = ()
    edges_removed: tuple[Edge, ...] = ()
    diagnostics_opened: tuple[Diagnostic, ...] = ()
    diagnostics_resolved: tuple[Diagnostic, ...] = ()
    before: Facts = field(default_factory=Facts)
    after: Facts = field(default_factory=Facts)
    restated: bool = False


class Net(Generic[_Item]):
    """Added and removed over a window of entries, cancelling as they fold in.

    The cancellation is the point, and it is one rule: an item removed by an
    earlier entry and added back by a later one was never different at the
    endpoints, so it belongs in neither collection (`SPEC.md` §10.6).
    """

    def __init__(self, key: Callable[[_Item], Key]) -> None:
        self._key: Callable[[_Item], Key] = key
        self._added: dict[Key, list[_Item]] = {}
        self._removed: dict[Key, list[_Item]] = {}

    def add(self, item: _Item) -> None:
        if not self._cancel(self._removed, item):
            self._added.setdefault(self._key(item), []).append(item)

    def remove(self, item: _Item) -> None:
        if not self._cancel(self._added, item):
            self._removed.setdefault(self._key(item), []).append(item)

    def added(self) -> tuple[_Item, ...]:
        return self._flattened(self._added)

    def removed(self) -> tuple[_Item, ...]:
        return self._flattened(self._removed)

    def _cancel(self, against: dict[Key, list[_Item]], item: _Item) -> bool:
        key = self._key(item)
        group = against.get(key)
        if group is None or item not in group:
            return False
        group.remove(item)
        if not group:
            del against[key]
        return True

    def _flattened(self, groups: dict[Key, list[_Item]]) -> tuple[_Item, ...]:
        return tuple(item for key in sorted(groups) for item in groups[key])


# --------------------------------------------------------------------------
# The delta itself
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BasisRewrite:
    """One edge whose `basis` changed: the same relation, a different reason.

    Not a fact of its own. An edge's identity includes its basis (`SPEC.md`
    §3.8), so a rewrite is one edge removed and one added; this names the pair
    so that a consumer does not have to rediscover it, and `Delta` computes it
    from the edge sets rather than carrying it, which is why it cannot
    disagree with them (§10.6).
    """

    src: NodeId
    dst: NodeId
    kind: EdgeKind
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class Delta:
    """The difference between two versions of a live graph (`SPEC.md` §10.6).

    Produced **only** by ``Builder.delta(since=v)``: ``feed`` returns the new
    version and never this (§10). Every collection is in the graph's own
    canonical order (§5.2), so two deltas over one window are equal or they
    disagree -- there is no order to argue about.

    What it does not carry: annotations, because a builder never makes one and
    they are the consumer's own (§8); canonical order, because that is a
    function of the nodes and the edges and ``fold`` recomputes it; and any
    version number on any graph, which §10.1 promises stays absent.
    """

    since: int
    until: int
    nodes_added: tuple[Node, ...] = ()
    nodes_removed: tuple[Node, ...] = ()
    edges_added: tuple[Edge, ...] = ()
    edges_removed: tuple[Edge, ...] = ()
    diagnostics_opened: tuple[Diagnostic, ...] = ()
    diagnostics_resolved: tuple[Diagnostic, ...] = ()
    trace_id_before: str = ""
    trace_id_after: str = ""
    adapters_before: tuple[AdapterInfo, ...] = ()
    adapters_after: tuple[AdapterInfo, ...] = ()
    #: Did the nodes **both** versions hold move relative to each other? Not
    #: "are the two orders different", which one appended node makes true and
    #: which would say nothing a consumer could act on.
    order_changed: bool = False
    #: Did an arrival in this window re-derive every node id (`SPEC.md` §10.7)?
    restated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes_added", _sorted_nodes(self.nodes_added))
        object.__setattr__(self, "nodes_removed", _sorted_nodes(self.nodes_removed))
        object.__setattr__(self, "edges_added", _sorted_edges(self.edges_added))
        object.__setattr__(self, "edges_removed", _sorted_edges(self.edges_removed))
        object.__setattr__(
            self, "diagnostics_opened", _sorted_diagnostics(self.diagnostics_opened)
        )
        object.__setattr__(
            self, "diagnostics_resolved", _sorted_diagnostics(self.diagnostics_resolved)
        )
        object.__setattr__(
            self, "adapters_before", _sorted_adapters(self.adapters_before)
        )
        object.__setattr__(
            self, "adapters_after", _sorted_adapters(self.adapters_after)
        )

    @property
    def changed(self) -> bool:
        """Did anything move at all? A window with nothing in it is not an error."""
        return bool(
            self.nodes_added
            or self.nodes_removed
            or self.edges_added
            or self.edges_removed
            or self.diagnostics_opened
            or self.diagnostics_resolved
            or self.order_changed
            or self.trace_id_before != self.trace_id_after
            or self.adapters_before != self.adapters_after
        )

    @property
    def basis_rewritten(self) -> tuple[BasisRewrite, ...]:
        """The relations whose reason changed, as pairs over the edge sets."""
        gone: dict[tuple[str, str, str], Edge] = {}
        for edge in self.edges_removed:
            gone.setdefault((edge.src, edge.dst, str(edge.kind)), edge)
        came: dict[tuple[str, str, str], Edge] = {}
        for edge in self.edges_added:
            came.setdefault((edge.src, edge.dst, str(edge.kind)), edge)
        return tuple(
            BasisRewrite(
                src=gone[where].src,
                dst=gone[where].dst,
                kind=gone[where].kind,
                before=gone[where].basis,
                after=came[where].basis,
            )
            for where in sorted(gone.keys() & came.keys())
        )

    def fold(self, graph: Graph) -> Graph:
        """Apply this difference to the graph at ``since`` (`SPEC.md` §10.6).

        Byte-for-byte equal to the builder's own graph at ``until``, which is
        the corpus's third claim about the live builder (`FIXTURES.md` §4).

        A graph carries no version, so this **cannot** check it was handed the
        right one. What it does check is that the difference applies: something
        it must remove and cannot find, or something it adds that is already
        there, is a `ValueError` rather than a quietly wrong graph.
        """
        if graph.meta is None:
            raise ValueError(
                "a delta folds onto a graph that carries its `meta`; this one "
                "carries none, so there is nothing to count from"
            )
        nodes = {node.id: node for node in graph.nodes()}
        for node in self.nodes_removed:
            if nodes.get(node.id) != node:
                raise ValueError(_absent("node", node.id))
            del nodes[node.id]
        for node in self.nodes_added:
            if node.id in nodes:
                raise ValueError(_present("node", node.id))
            nodes[node.id] = node

        edges = {edge.identity: edge for edge in graph.edges()}
        for edge in self.edges_removed:
            if edges.get(edge.identity) != edge:
                raise ValueError(_absent("edge", _edge_name(edge)))
            del edges[edge.identity]
        for edge in self.edges_added:
            if edge.identity in edges:
                raise ValueError(_present("edge", _edge_name(edge)))
            edges[edge.identity] = edge

        diagnostics = list(graph.diagnostics)
        for item in self.diagnostics_resolved:
            if item not in diagnostics:
                raise ValueError(_absent("diagnostic", item.code))
            diagnostics.remove(item)
        diagnostics.extend(self.diagnostics_opened)
        diagnostics.sort(key=lambda item: item.sort_key)

        ordered_edges = build.deduplicated(list(edges.values()))
        ordered = ordering(tuple(nodes.values()), ordered_edges, None)[0]
        return Graph.of(
            trace_id=self.trace_id_after,
            nodes=ordered,
            edges=ordered_edges,
            diagnostics=tuple(diagnostics),
            meta=replace(
                graph.meta,
                adapters=self.adapters_after,
                node_count=len(ordered),
                edge_count=len(ordered_edges),
                diagnostic_count=len(diagnostics),
            ),
            annotations=graph.annotations,
        )


def _absent(what: str, named: str) -> str:
    return (
        f"this delta removes a {what} ({named}) that the graph it was folded "
        f"onto does not hold as stated. A graph carries no version "
        f"(`SPEC.md` §10.1), so the likely cause is folding onto a graph that "
        f"is not the `since` version. Nothing was folded"
    )


def _present(what: str, named: str) -> str:
    return (
        f"this delta adds a {what} ({named}) that the graph it was folded onto "
        f"already holds -- the same delta folded twice, or a graph that is not "
        f"the `since` version. Nothing was folded"
    )


def _edge_name(edge: Edge) -> str:
    return f"{edge.kind} {edge.src!r} -> {edge.dst!r}"


def _sorted_nodes(nodes: Iterable[Node]) -> tuple[Node, ...]:
    return tuple(sorted(nodes, key=lambda node: node.id))


def _sorted_edges(edges: Iterable[Edge]) -> tuple[Edge, ...]:
    return tuple(sorted(edges, key=lambda edge: edge.sort_key))


def _sorted_diagnostics(items: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(items, key=diagnostic_key))


def _sorted_adapters(adapters: Iterable[AdapterInfo]) -> tuple[AdapterInfo, ...]:
    return tuple(sorted(adapters, key=lambda adapter: adapter.sort_key))


def ordering(
    nodes: Sequence[Node], edges: Sequence[Edge], whole_input: str | None
) -> tuple[tuple[Node, ...], tuple[Diagnostic, ...]]:
    """Canonical order, and the one diagnostic the same sort reports.

    `build.in_order` is the batch builder's rule and this calls **it**, so a
    folded graph and a materialized one cannot be ordered by two rules
    (`SPEC.md` §5.2). Both results are functions of the node and edge sets
    alone, which is why neither is journalled.
    """
    collector = DiagnosticCollector()
    ordered = build.in_order(nodes, edges, collector, whole_input)
    return ordered, collector.collected()


def order_moved(before: Sequence[Node], after: Sequence[Node]) -> bool:
    """Did the nodes both orders hold change position relative to each other?"""
    shared = {node.id for node in before} & {node.id for node in after}
    return _kept(before, shared) != _kept(after, shared)


def _kept(ordered: Sequence[Node], shared: set[NodeId]) -> tuple[NodeId, ...]:
    return tuple(node.id for node in ordered if node.id in shared)


# --------------------------------------------------------------------------
# The journal
# --------------------------------------------------------------------------


class Journal:
    """One entry per arrival, and the policy that decides which are kept.

    Retention is the caller's (`SPEC.md` §10.8) because only the caller knows
    how far behind its consumers run. What is not the caller's is what happens
    when it asks about a version it told the journal to forget: that is refused
    with `delta_unavailable`, never answered with the part that survived.
    """

    def __init__(self) -> None:
        self._entries: dict[int, Change] = {}
        self._keep: Retention = "all"

    def retain(self, versions: Retention, version: int) -> None:
        if not (versions == "all" or (isinstance(versions, int) and versions >= 0)):
            raise ValueError(
                f"retention is a count of versions, 0, or 'all'; {versions!r} "
                f"is none of those (`SPEC.md` §10.8)"
            )
        self._keep = versions
        self._trim(version)

    def record(self, version: int, entry: Change) -> None:
        self._entries[version] = entry
        self._trim(version)

    def oldest(self, version: int) -> int:
        """The oldest `since` this journal can still answer about."""
        if isinstance(self._keep, int):
            return max(0, version - self._keep)
        return 0

    def fold(self, since: int, version: int, current: Facts) -> Change:
        """The entries after ``since``, folded into one net change.

        ``current`` is what the two scalar facts are **now**, and it is what an
        empty window reports on both sides: `delta(since=version)` is the empty
        delta, not a delta from nothing (`SPEC.md` §10.6).
        """
        if since >= version:
            return Change(before=current, after=current)
        nodes: Net[Node] = Net(node_key)
        edges: Net[Edge] = Net(edge_key)
        diagnostics: Net[Diagnostic] = Net(diagnostic_key)
        restated = False
        before = self._entries[since + 1].before
        after = before
        for step in range(since + 1, version + 1):
            entry = self._entries[step]
            for node in entry.nodes_removed:
                nodes.remove(node)
            for node in entry.nodes_added:
                nodes.add(node)
            for edge in entry.edges_removed:
                edges.remove(edge)
            for edge in entry.edges_added:
                edges.add(edge)
            for item in entry.diagnostics_resolved:
                diagnostics.remove(item)
            for item in entry.diagnostics_opened:
                diagnostics.add(item)
            restated = restated or entry.restated
            after = entry.after
        return Change(
            nodes_added=nodes.added(),
            nodes_removed=nodes.removed(),
            edges_added=edges.added(),
            edges_removed=edges.removed(),
            diagnostics_opened=diagnostics.added(),
            diagnostics_resolved=diagnostics.removed(),
            before=before,
            after=after,
            restated=restated,
        )

    def held(self, since: int, version: int) -> None:
        """Refuse a `since` the policy dropped (`SPEC.md` §10.8)."""
        oldest = self.oldest(version)
        if since < oldest:
            raise DeltaUnavailableError(
                f"the journal no longer holds version {since}: retention is "
                f"{self._keep!r}, so the oldest version it can answer about is "
                f"{oldest}. Nothing approximate is offered in its place -- an "
                f"incomplete delta is indistinguishable from a complete one"
            )

    def _trim(self, version: int) -> None:
        if not isinstance(self._keep, int):
            return
        oldest = self.oldest(version)
        for step in [step for step in self._entries if step <= oldest]:
            del self._entries[step]
