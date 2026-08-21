"""The version literal and the packaging metadata must not drift apart."""

import pathlib
import tomllib

import spanweave

PYPROJECT = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject():
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert spanweave.__version__ == metadata["project"]["version"]


def test_schema_version_is_unfrozen_and_says_so():
    # The schema stays unfrozen through the 0.9.x launch (CLAUDE.md 7). While
    # it is, the version number itself must say so: a "0.x" schema version is
    # part of how the claim is made, not just prose in the README.
    assert spanweave.SCHEMA_FROZEN is False
    assert spanweave.SCHEMA_VERSION.startswith("0.")
