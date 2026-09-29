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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spanweave import jsoncodec
from spanweave.model import JsonValue, NodeId

if TYPE_CHECKING:  # pragma: no cover - typing only, and deliberately so:
    # a runtime import would make this module and `graph` circular.
    from spanweave.graph import Graph

#: Reserved for the library, which writes nothing into it in v1. Reserved
#: means reserved: annotating into it is refused, so that a future
#: `spanweave` annotation cannot collide with something a consumer already
#: put there.
RESERVED_NAMESPACE = "spanweave"

#: One entry of a batch: the arguments of `annotate`, in the same order. A
#: plain tuple rather than a type of its own, because a batch is a way of
#: *calling* the annotation API, not a new thing in the model.
AnnotationEntry = tuple[NodeId, str, str, JsonValue]


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

    def with_entries(self, entries: Iterable[Annotation]) -> AnnotationStore:
        """A new store carrying a whole batch, built once rather than N times.

        The result is what repeated `with_entry` would produce: within the
        batch the **last** entry for a `(namespace, node_id, key)` wins, just
        as setting the same key twice does, and it replaces anything this
        store already held for that key.
        """
        incoming: dict[tuple[str, str, str], Annotation] = {}
        for entry in entries:
            incoming[entry.sort_key] = entry
        kept = [
            existing for existing in self.entries if existing.sort_key not in incoming
        ]
        return AnnotationStore(entries=(*kept, *incoming.values()))

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
    """Annotation values must survive a round trip through the graph file.

    Refused, with ``ValueError``: a value the encoder cannot write, and a value
    it can write but the library cannot read back -- an integer, at any depth,
    of more than ``jsoncodec.DIGIT_LIMIT`` digits (`SPEC.md` §5.3, §8). The
    encoder writes such an integer whole under every interpreter setting, and
    the reader refuses every literal that long, so accepting it here would
    produce a graph file that ``loads`` and ``spanweave validate`` refuse.
    Digits are counted exactly as the reader counts a literal's -- the sign is
    not one -- and without asking the interpreter to convert the integer, so
    the answer is the same under every setting.

    *The* encoder, not a laxer stand-in, and at *the* depth, not at the top of
    a document of one value: the probe runs ``jsoncodec.canonical_dump``,
    which is the policy a graph file is written under, over
    ``_where_the_document_puts_it(value)``, which is the nesting the graph
    file wraps an annotation's value in. A value is therefore refused here
    exactly when writing the graph would have refused it, rather than being
    accepted and leaving the caller a graph it cannot write -- which is what a
    probe without ``allow_nan=False`` did to ``NaN``, ``inf`` and ``-inf``
    (run-6 review S8.4), and what a probe at the top level did to a value
    nested within three levels of the encoder's ceiling (run-7 review T2).

    A mapping key that is not a string is refused first and named as that. It
    is the one shape the encoder does not refuse and does not preserve: ``json``
    coerces an integer key to a string, so the annotation does not come back
    as it went in; and a key long enough that ``str()`` itself refuses it under
    a lowered interpreter limit would otherwise reach the writer as a bare
    ``ValueError`` and be reported there as a value that refers back to itself.
    """
    unstringly = _non_string_key(value)
    if unstringly is not None:
        raise ValueError(
            f"annotation values must be JSON-serializable so they survive "
            f"serialization; {type(value).__name__} is not (a mapping key of "
            f"type {unstringly.__name__} is not a string, and a JSON object "
            f"is keyed by strings only, so it would not be read back as it "
            f"was written)"
        )
    try:
        jsoncodec.encode(_where_the_document_puts_it(value), jsoncodec.canonical_dump)
    # RecursionError is how `json` reports nesting it will not descend -- the
    # same fact as a `ValueError`, reported as a different exception, and this
    # check exists precisely to catch what the graph file could not hold.
    except (TypeError, ValueError, RecursionError) as failure:
        raise ValueError(
            f"annotation values must be JSON-serializable so they survive "
            f"serialization; {type(value).__name__} is not ({failure})"
        ) from failure
    unreadable = _unreadable_integer(value)
    if unreadable is not None:
        digits = len(jsoncodec.integer_text(abs(unreadable)))
        raise ValueError(
            f"annotation values must be JSON-serializable so they survive "
            f"serialization; {type(value).__name__} is not (an integer of "
            f"{digits} digits is longer than the {jsoncodec.DIGIT_LIMIT} digits "
            f"spanweave reads (`SPEC.md` §5.3))"
        )


def _where_the_document_puts_it(value: JsonValue) -> JsonValue:
    """``value`` inside the containers a graph document wraps it in.

    The graph file is an object whose ``annotations`` key holds an array of
    objects, and the value is one object's ``value`` (`SPEC.md` §8). Three
    containers, so the encoder meets the value three levels lower than a probe
    of the bare value does -- and depth is the one thing an encoder refuses
    that a probe of the bare value cannot see, because every other refusal is
    a property of the value itself and is the same wherever it sits.

    The shape is restated here rather than imported because ``serialize``
    imports this module, so importing it back would be the upward import
    `CLAUDE.md` and `DESIGN.md` §2 forbid. It is not left to drift for that:
    `tests/test_serialize.py` derives the wrapping from ``to_document`` of a
    real annotated graph and fails if it stops matching this.

    The sibling keys are the ones ``serialize`` writes, with the values an
    entry always has -- strings -- so that the probe encodes the object the
    writer will encode rather than a smaller one. None of them can change the
    outcome: they are shallower than ``value`` and they always encode.
    """
    return {
        "annotations": [
            {"namespace": "", "node_id": "", "key": "", "value": value},
        ],
    }


def _non_string_key(value: JsonValue) -> type | None:
    """The type of a mapping key in ``value`` that is not a string, if any.

    The type, not the key: rendering the key is the very thing that can raise
    here, and this runs *before* the encoder rather than after it, so it can
    rely on nothing the encoder would have established. Hence iterative, and
    it remembers the containers it is already inside -- a value that refers
    back to itself ends the walk and is reported by the encoder, which is the
    check that owns that fact.
    """
    seen: set[int] = set()
    stack: list[JsonValue] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key in current:
                if not isinstance(key, str):
                    return type(key)
            inside: list[JsonValue] = list(current.values())
        elif isinstance(current, list | tuple):
            inside = list(current)
        else:
            continue
        if id(current) in seen:
            continue
        seen.add(id(current))
        stack.extend(inside)
    return None


#: The smallest magnitude with more digits than the library reads. Compared
#: by arithmetic, which no interpreter setting governs.
_FIRST_UNREADABLE = 10**jsoncodec.DIGIT_LIMIT


def _unreadable_integer(value: JsonValue) -> int | None:
    """An integer in ``value`` the reader would refuse, if there is one.

    Called only on a value the encoder has written, so it holds no cycle and
    no nesting the encoder would not descend; iterative all the same, so that
    it meets no depth ceiling of its own. Keys are not searched: the encoder
    writes a key as a string, and a string is read back whatever its length.
    """
    stack: list[JsonValue] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, bool):
            continue
        if isinstance(current, int):
            if abs(current) >= _FIRST_UNREADABLE:
                return current
        elif isinstance(current, Mapping):
            stack.extend(current.values())
        elif isinstance(current, list | tuple):
            stack.extend(current)
    return None


def _checked(
    graph: Graph, node_id: NodeId, namespace: str, key: str, value: JsonValue
) -> Annotation:
    """One entry, refused here if it could never be read back."""
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
    return Annotation(namespace=namespace, node_id=node_id, key=key, value=value)


def annotate(
    graph: Graph, node_id: NodeId, namespace: str, key: str, value: JsonValue
) -> Graph:
    """Attach a namespaced fact to a node, returning a **new** graph.

    What gets copied is the *annotations*. Nodes and edges are the one thing
    an annotation cannot change, so the new graph shares their lookup
    structures with the old one rather than rebuilding them: annotating stays
    immutable without a pass over the whole graph on every call (`SPEC.md` §8).
    """
    entry = _checked(graph, node_id, namespace, key, value)
    return graph._with_annotations(graph.annotations.with_entry(entry))


def annotate_many(graph: Graph, entries: Iterable[AnnotationEntry]) -> Graph:
    """A whole batch of facts, in one new graph.

    Defined as `annotate` applied to each entry in order, and equal to it
    (`SPEC.md` §8): of two entries naming the same
    `(namespace, node_id, key)`, the later one wins. Every entry is checked
    before any of them is kept, so a refused entry loses the caller the batch
    rather than leaving a graph carrying half of it.
    """
    prepared = [_checked(graph, *entry) for entry in entries]
    return graph._with_annotations(graph.annotations.with_entries(prepared))
