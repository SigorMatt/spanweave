"""spanweave — agentic-system telemetry into a deterministic, neutral graph.

The public API is exactly what this module exports; everything else is
internal and may be refactored freely (``CLAUDE.md``).

The library reads trace files and writes a graph. It assigns no roles, no
judgement, and no domain interpretation of any kind (``SPEC.md`` §1).
"""

from spanweave.version import SCHEMA_FROZEN, SCHEMA_VERSION, __version__

__all__ = ["SCHEMA_FROZEN", "SCHEMA_VERSION", "__version__"]
