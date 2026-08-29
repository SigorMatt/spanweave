"""Version constants.

Kept in its own module so that every layer -- the CLI, the serializer, and the
package's public surface -- can read them without an import cycle.

``__version__`` is a literal rather than a read of installed metadata: the
library must report a version from a source checkout as well as from a wheel.
``tests/test_version.py`` keeps it in step with ``pyproject.toml``.
"""

__version__ = "0.9.0"

# The graph schema's own version, independent of the library's. It is "0.x"
# until the Phase 4 freeze and "1" after it (SPEC.md 3.9). While it is
# unfrozen we say so loudly and often -- in the README, in --help, and in the
# version number itself (CLAUDE.md 7) -- because publishing is reversible and
# freezing is not.
SCHEMA_VERSION = "0.1"
SCHEMA_FROZEN = False
