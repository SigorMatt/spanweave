"""The graph: nodes, edges, diagnostics, meta -- and nothing that judges them.

The output object. Immutable, deterministically ordered, and free of any
opinion about what any of it means (``SPEC.md`` §3.9).

The query surface arrives in task 1.7. What is here is the container itself
and the indexes every query will need, built once at construction because
iteration order is a correctness property in this library, not a detail
(``DESIGN.md`` §7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from spanweave.model import Diagnostic, Edge, Meta, Node, NodeId


@dataclass(frozen=True, slots=True)
class Graph:
    """One trace, normalized."""

    trace_id: str
    #: In deterministic order (`SPEC.md` §5.2).
    nodes: tuple[Node, ...] = ()
    #: Sorted by `(kind, src, dst, basis)`.
    edges: tuple[Edge, ...] = ()
    #: Sorted by `(code, node_id, message)`.
    diagnostics: tuple[Diagnostic, ...] = ()
    meta: Meta | None = None
    _index: Mapping[NodeId, Node] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {node.id: node for node in self.nodes})

    def node(self, node_id: NodeId) -> Node | None:
        """The node with this id, or ``None``.

        ``None`` rather than an exception because a `link` edge may legally
        point at a span that has no node here (`SPEC.md` §4): asking about a
        foreign target is a normal thing to do, not an error.
        """
        return self._index.get(node_id)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._index

    def __len__(self) -> int:
        return len(self.nodes)
