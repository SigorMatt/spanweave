"""spanweave — agentic-system telemetry into a deterministic, neutral graph.

The public API is exactly what this module exports; everything else is
internal and may be refactored freely (``CLAUDE.md``).

The library reads trace files and writes a graph. It assigns no roles, no
judgement, and no domain interpretation of any kind (``SPEC.md`` §1).
"""

from spanweave.annotate import Annotation, AnnotationStore
from spanweave.api import build
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
    "Annotation",
    "AnnotationStore",
    "Diagnostic",
    "DiagnosticLevel",
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
    "Status",
    "Usage",
    "Warrant",
    "__version__",
    "build",
    "dump",
    "dumps",
    "to_document",
    "validate",
]
