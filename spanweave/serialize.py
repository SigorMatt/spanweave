"""Canonical JSON for a graph, and a check that a graph file is well-formed.

Determinism ends here or it does not exist: two runs can agree on every node
and still disagree on bytes if the writer is careless. So the encoding is
fixed and asserted -- sorted keys, compact separators, non-ASCII kept as text,
one trailing newline (``SPEC.md`` §5.2).

What is written out is deliberately free of the operator's environment: no
build timestamp, no hostname, no username, no file path. Those would break
byte-identical determinism and leak where the graph was built, and neither is
anything a consumer asked for.

**The schema is not frozen.** It freezes in Phase 4, deliberately after the
``0.9.x`` launch, because publishing is reversible and freezing is not.
"""

from __future__ import annotations

import json
import math
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from spanweave import jsoncodec
from spanweave.annotate import AnnotationStore
from spanweave.errors import GraphNotSerializableError
from spanweave.graph import Graph
from spanweave.model import (
    Diagnostic,
    Edge,
    JsonValue,
    Meta,
    Node,
    Payload,
    Usage,
)
from spanweave.version import SCHEMA_VERSION

#: The root keys of a graph document, in the order a reader meets them once
#: the keys are sorted (which they always are).
ROOT_KEYS = (
    "annotations",
    "diagnostics",
    "edges",
    "meta",
    "nodes",
    "schema_version",
    "trace_id",
)


def _a_non_finite_number(value: object) -> float | None:
    """A non-finite number inside ``value``, or ``None`` if it holds none.

    ``json.dumps`` answers two entirely different facts with one
    ``ValueError``: a number RFC 8259 cannot write, and a value that refers
    back to itself. The refusal below has to say which it met, and it decides
    by looking at the value rather than by reading the interpreter's message,
    which is no more a contract than any other message (`SPEC.md` §3.10).

    Iterative, and it remembers the containers it is already inside -- so the
    self-referential value, which is the other case, ends the walk instead of
    running forever.
    """
    seen: set[int] = set()
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, float):
            if not math.isfinite(current):
                return current
            continue
        if isinstance(current, Mapping):
            # Keys as well as values: a mapping keyed by a non-finite float
            # defeats the encoder in exactly the same way, and a walk that
            # looked only at values would report that one as a cycle.
            inside: Iterable[object] = [*current, *current.values()]
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            inside = current
        else:
            continue
        if id(current) in seen:
            continue
        seen.add(id(current))
        stack.extend(inside)
    return None


def _stdlib_canonical(value: JsonValue) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        # RFC 8259 has no `Infinity` and no `NaN`; Python's encoder writes
        # them anyway unless told not to. A document carrying one is the
        # worst outcome available -- it is produced, it looks written, and
        # a strict parser on the other end refuses it -- so it is a
        # refusal here instead (`SPEC.md` §7).
        allow_nan=False,
    )


def canonical_bytes(value: JsonValue) -> bytes:
    """The one encoder. Everything written by this library goes through it.

    Deep nesting is the one input that can defeat it. The reader contains what
    the *parser* will not descend (`SPEC.md` §7); the encoder meets the value
    four levels lower down -- inside the document, inside a node, inside a
    payload -- so a value that arrived intact can still fail to leave. How
    much room there is for those four levels is the interpreter's answer and
    not this library's, and it differs by container shape: §7 carries the
    measured table, in which CPython 3.11-3.13 give the parser and the
    encoder the same ceiling while 3.14 gives the encoder ~2,900 levels
    *less* for nested dicts -- the shape a graph document has at every level.
    The guard depends on none of that: `json.dumps` reports depth as
    ``RecursionError``, which is not a ``ValueError``, and uncontained it
    escapes as an interpreter traceback from a build that had read its input
    without complaint. The ``ValueError`` arm is two facts wearing one
    exception type -- a number RFC 8259 cannot write, and a value that refers
    back to itself -- and the refusal names which of them it actually met.

    It becomes a refusal rather than a diagnostic because there is nothing to
    degrade to: the offending value may be a node's verbatim source record, and
    dropping it to get past this is the one thing losslessness forbids
    (`CLAUDE.md` 2). Naming it (`SPEC.md` §3.10) is what a caller can act on.
    """
    try:
        # Through `jsoncodec.encode`, so that an integer the library read is
        # written whole whatever the interpreter's own digit limit is set to
        # (`SPEC.md` §5.3). The encoder and its arguments are unchanged.
        text = jsoncodec.encode(value, _stdlib_canonical)
    except ValueError as failure:
        if _a_non_finite_number(value) is None:
            # The other thing `json.dumps` raises `ValueError` for. Nothing
            # the reader parses can hold a cycle -- JSON has no way to write
            # one -- so this graph was assembled in memory, and a refusal that
            # named the wrong fact would send its caller looking for a value
            # that is not there.
            raise GraphNotSerializableError(
                f"the graph could not be encoded: a value refers back to "
                f"itself ({failure}), and JSON has no way to write that. "
                f"Nothing was written, and nothing was dropped to try -- the "
                f"record a node carries is verbatim or it is nothing"
            ) from failure
        raise GraphNotSerializableError(
            f"the graph could not be encoded: it holds a number JSON has no "
            f"way to write ({failure}). A timestamp is never carried in that "
            f"state (`SPEC.md` §3.1), so this is a value inside a node's "
            f"verbatim source record -- and that record is verbatim or it is "
            f"nothing. Nothing was written"
        ) from failure
    except RecursionError as failure:
        raise GraphNotSerializableError(
            f"the graph could not be encoded: a value nests deeper than this "
            f"interpreter's JSON encoder will descend ({failure}). Nothing was "
            f"written, and nothing was dropped to try -- the record a node "
            f"carries is verbatim or it is nothing"
        ) from failure
    return (text + "\n").encode("utf-8")


def to_document(graph: Graph) -> dict[str, Any]:
    """The graph as plain JSON data."""
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": graph.trace_id,
        "meta": _meta(graph.meta),
        "nodes": [_node(node) for node in graph.nodes()],
        "edges": [_edge(edge) for edge in graph.edges()],
        "diagnostics": [_diagnostic(item) for item in graph.diagnostics],
        "annotations": _annotations(graph.annotations),
    }


def dumps(graph: Graph) -> bytes:
    """Canonical bytes for a graph."""
    return canonical_bytes(to_document(graph))


def dump(graph: Graph, path: pathlib.Path) -> None:
    """Write a graph. The only file this library ever creates."""
    path.write_bytes(dumps(graph))


def _meta(meta: Meta | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    return {
        "spanweave_version": meta.spanweave_version,
        "adapters": [
            {
                "id": adapter.id,
                "version": adapter.version,
                "declared_confidence": adapter.declared_confidence,
            }
            for adapter in sorted(meta.adapters, key=lambda item: item.sort_key)
        ],
        "source_digest": meta.source_digest,
        "node_count": meta.node_count,
        "edge_count": meta.edge_count,
        "diagnostic_count": meta.diagnostic_count,
    }


def _node(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": str(node.kind),
        "name": node.name,
        "operation": node.operation,
        "started_at": node.started_at,
        "ended_at": node.ended_at,
        "status": str(node.status),
        "status_note": node.status_note,
        "inputs": _payload(node.inputs),
        "outputs": _payload(node.outputs),
        "usage": _usage(node.usage),
        "attributes": dict(node.attributes),
        "raw": {
            # Verbatim. Round-tripping this reproduces the input record, which
            # is the whole of losslessness (SPEC.md §3.5). `line_number` is
            # deliberately absent: it depends on input order, and the graph
            # must not.
            "source": node.raw.source,
            "source_id": node.raw.source_id,
        },
        "provenance": {
            "adapter_id": node.provenance.adapter_id,
            "adapter_version": node.provenance.adapter_version,
            "dialect_note": node.provenance.dialect_note,
        },
    }


def _payload(payload: Payload) -> dict[str, Any]:
    return {
        "state": str(payload.state),
        "mime": payload.mime,
        "value": payload.value,
        "raw": payload.raw,
    }


def _usage(usage: Usage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "extra": dict(usage.extra),
    }


def _edge(edge: Edge) -> dict[str, Any]:
    return {
        "src": edge.src,
        "dst": edge.dst,
        "kind": str(edge.kind),
        "warrant": str(edge.warrant),
        "basis": edge.basis,
        "adapter": edge.adapter,
    }


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "level": str(diagnostic.level),
        "message": diagnostic.message,
        "node_id": diagnostic.node_id,
        "source": diagnostic.source,
        "adapter": diagnostic.adapter,
    }


def _annotations(store: AnnotationStore) -> list[dict[str, Any]]:
    return [
        {
            "namespace": entry.namespace,
            "node_id": entry.node_id,
            "key": entry.key,
            "value": entry.value,
        }
        for entry in store.entries
    ]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(document: JsonValue) -> tuple[str, ...]:
    """Everything wrong with a graph document, as plain sentences.

    Returns an empty tuple for a good document. It never raises: being handed
    something that is not a graph is one of the things it is for.
    """
    if not isinstance(document, dict):
        return ("this is not a graph document: the top level is not an object",)

    problems: list[str] = []
    for key in ROOT_KEYS:
        if key not in document:
            problems.append(f"missing top-level key {key!r}")
    if problems:
        return tuple(problems)

    version = document["schema_version"]
    if version != SCHEMA_VERSION:
        problems.append(
            f"schema_version is {version!r}, and this build writes "
            f"{SCHEMA_VERSION!r}; the schema is not frozen until 1.0, so "
            f"graphs from other versions may differ"
        )

    nodes = document["nodes"]
    edges = document["edges"]
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return (*problems, "'nodes' and 'edges' must both be arrays")

    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes):
        problems.append("every node must be an object with an id")
    if len(set(ids)) != len(ids):
        problems.append("node ids are not unique")

    known = set(ids)
    for edge in edges:
        if not isinstance(edge, dict):
            problems.append("every edge must be an object")
            continue
        if edge.get("src") not in known:
            problems.append(
                f"edge {edge.get('kind')} {edge.get('src')!r} -> "
                f"{edge.get('dst')!r} starts at a node that is not here"
            )
        # A `link` edge may legally leave the trace (SPEC.md §4), so its
        # target is not required to be present. Nothing else may dangle.
        if edge.get("kind") != "link" and edge.get("dst") not in known:
            problems.append(
                f"edge {edge.get('kind')} {edge.get('src')!r} -> "
                f"{edge.get('dst')!r} ends at a node that is not here"
            )

    problems.extend(_ordering_problems(edges, document["diagnostics"]))
    problems.extend(_count_problems(document))
    return tuple(problems)


def _ordering_problems(edges: Sequence[JsonValue], diagnostics: JsonValue) -> list[str]:
    problems = []
    keys = [
        (e.get("kind"), e.get("src"), e.get("dst"), e.get("basis"))
        for e in edges
        if isinstance(e, dict)
    ]
    if keys != sorted(keys):
        problems.append("edges are not in canonical order (kind, src, dst, basis)")
    if len(set(keys)) != len(keys):
        problems.append("edges are not unique on (src, dst, kind, basis)")
    if isinstance(diagnostics, list):
        found = [
            (d.get("code"), d.get("node_id") or "", d.get("message"))
            for d in diagnostics
            if isinstance(d, dict)
        ]
        if found != sorted(found):
            problems.append(
                "diagnostics are not in canonical order (code, node_id, message)"
            )
    return problems


def _count_problems(document: Mapping[str, JsonValue]) -> list[str]:
    meta = document.get("meta")
    if not isinstance(meta, dict):
        return ["'meta' is missing or is not an object"]
    problems = []
    for key, collection in (
        ("node_count", "nodes"),
        ("edge_count", "edges"),
        ("diagnostic_count", "diagnostics"),
    ):
        stated = meta.get(key)
        actual = len(document[collection])
        if stated != actual:
            problems.append(
                f"meta.{key} says {stated} but there are {actual} {collection}"
            )
    for forbidden in ("built_at", "hostname", "username", "path", "source_path"):
        if forbidden in meta:
            problems.append(
                f"meta.{forbidden} must not be written: it would break "
                f"byte-identical determinism and leak the operator's "
                f"environment"
            )
    return problems
