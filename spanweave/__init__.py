"""spanweave — agentic-system telemetry into a deterministic, neutral graph.

The public API is exactly what this module exports; everything else is
internal and may be refactored freely (``CLAUDE.md``).

The library reads trace files and writes a graph. It assigns no roles, no
judgement, and no domain interpretation of any kind (``SPEC.md`` §1).

The error types are part of that surface. ``SPEC.md`` §3.10 tells callers to
match on an error's ``code`` and never on its message; until a caller can write
``except SpanweaveError`` and read ``.code``, that instruction is impossible to
obey through the public API, and the only alternative is ``except Exception``
plus ``getattr(error, "code", None)`` -- which puts a missing file, a
permissions error and a trace the library deliberately refused in the same
branch. Found by the Phase 2b consumer (`TASKS.md` F4), which had written
exactly that workaround.
"""

from spanweave.annotate import Annotation, AnnotationStore
from spanweave.api import build
from spanweave.errors import (
    AdapterSelectionError,
    DuplicateNodeIdError,
    SpanweaveError,
    UnknownAdapterError,
)
from spanweave.graph import Graph
from spanweave.model import (
    Diagnostic,
    DiagnosticLevel,
    Edge,
    EdgeKind,
    Meta,
    Node,
    NodeKind,
    Payload,
    PayloadState,
    Provenance,
    RawRecord,
    Status,
    Usage,
    Warrant,
)
from spanweave.serialize import dump, dumps, to_document, validate
from spanweave.version import SCHEMA_FROZEN, SCHEMA_VERSION, __version__

__all__ = [
    "SCHEMA_FROZEN",
    "SCHEMA_VERSION",
    "AdapterSelectionError",
    "Annotation",
    "AnnotationStore",
    "Diagnostic",
    "DiagnosticLevel",
    "DuplicateNodeIdError",
    "Edge",
    "EdgeKind",
    "Graph",
    "Meta",
    "Node",
    "NodeKind",
    "Payload",
    "PayloadState",
    "Provenance",
    "RawRecord",
    "SpanweaveError",
    "Status",
    "UnknownAdapterError",
    "Usage",
    "Warrant",
    "__version__",
    "build",
    "dump",
    "dumps",
    "to_document",
    "validate",
]
