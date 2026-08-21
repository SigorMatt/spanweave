"""spanweave — agentic-system telemetry into a deterministic, neutral graph.

The public API is exactly what this module exports; everything else is
internal and may be refactored freely (``CLAUDE.md``).

The library reads trace files and writes a graph. It assigns no roles, no
judgement, and no domain interpretation of any kind (``SPEC.md`` §1).
"""

__all__ = ["__version__"]

# Kept in step with ``pyproject.toml`` by ``tests/test_version.py``. The
# package deliberately does not read its version from installed metadata:
# ``spanweave`` must import and report a version from a source checkout too.
__version__ = "0.1.0"
