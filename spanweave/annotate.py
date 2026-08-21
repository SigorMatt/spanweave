"""Consumer annotations.

The library has no opinion about what a trace means. This is where a consumer
puts theirs, without forking the model (``SPEC.md`` §8).

Three properties make that safe:

* **Namespaced.** ``"my_evals"`` and someone else's labels sit side by side
  and never collide.
* **Immutable.** Annotating returns a *new* graph. The original is unchanged,
  which is what keeps determinism intact and pipelines composable.
* **Ignored.** The library never reads an annotation to change its own
  behavior. It has no idea what is in there, and that is the entire point.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spanweave.model import JsonValue, NodeId

if TYPE_CHECKING:  # pragma: no cover - typing only, and deliberately so:
    # a runtime import would make this module and `graph` circular.
    from spanweave.graph import Graph

#: Reserved for the library, which writes nothing into it in v1. Reserved
#: means reserved: annotating into it is refused, so that a future
#: `spanweave` annotation cannot collide with something a consumer already
#: put there.
RESERVED_NAMESPACE = "spanweave"


@dataclass(frozen=True, slots=True)
class Annotation:
    """One consumer-supplied fact about one node."""

    namespace: str
    node_id: NodeId
    key: str
    value: JsonValue

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """`(namespace, node_id, key)` -- the serialized order (`SPEC.md` §8)."""
        return (self.namespace, self.node_id, self.key)


@dataclass(frozen=True, slots=True)
class AnnotationStore:
    """Every annotation on a graph, in one deterministic order."""

    entries: tuple[Annotation, ...] = ()
    _index: Mapping[tuple[str, str], Mapping[str, JsonValue]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.entries, key=lambda entry: entry.sort_key))
        object.__setattr__(self, "entries", ordered)
        index: dict[tuple[str, str], dict[str, JsonValue]] = {}
        for entry in ordered:
            index.setdefault((entry.namespace, entry.node_id), {})[entry.key] = (
                entry.value
            )
        object.__setattr__(self, "_index", index)

    def with_entry(self, entry: Annotation) -> AnnotationStore:
        """A new store. Setting the same key twice replaces the value."""
        kept = [
            existing for existing in self.entries if existing.sort_key != entry.sort_key
        ]
        return AnnotationStore(entries=(*kept, entry))

    def for_node(self, node_id: NodeId, namespace: str) -> Mapping[str, JsonValue]:
        return dict(self._index.get((namespace, node_id), {}))

    def nodes_with(self, namespace: str, key: str, value: JsonValue) -> frozenset[str]:
        return frozenset(
            entry.node_id
            for entry in self.entries
            if entry.namespace == namespace
            and entry.key == key
            and entry.value == value
        )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterable[Annotation]:
        return iter(self.entries)


def check_serializable(value: JsonValue) -> None:
    """Annotation values must survive a round trip through the graph file."""
    try:
        json.dumps(value, sort_keys=True)
    except (TypeError, ValueError) as failure:
        raise ValueError(
            f"annotation values must be JSON-serializable so they survive "
            f"serialization; {type(value).__name__} is not ({failure})"
        ) from failure


def annotate(
    graph: Graph, node_id: NodeId, namespace: str, key: str, value: JsonValue
) -> Graph:
    """Attach a namespaced fact to a node, returning a **new** graph.

    The copy is a real copy: annotating N nodes builds N graphs. That is what
    immutability actually takes at this scale, and immutability is what makes
    one graph safe to hand to two consumers at once.
    """
    if namespace == RESERVED_NAMESPACE:
        raise ValueError(
            f"the {RESERVED_NAMESPACE!r} namespace is reserved by the library; "
            f"use your own (for example your tool's name) so that nothing the "
            f"library adds later can collide with what you put there"
        )
    if not namespace:
        raise ValueError("an annotation needs a namespace; consumers do not share one")
    if graph.node(node_id) is None:
        raise ValueError(
            f"there is no node {node_id!r} in this graph, so an annotation on "
            f"it would never be read by anything"
        )
    check_serializable(value)
    entry = Annotation(namespace=namespace, node_id=node_id, key=key, value=value)
    return dataclasses.replace(graph, annotations=graph.annotations.with_entry(entry))
