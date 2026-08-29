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


# --------------------------------------------------------------------------
# Option B: `0.x` is one bucket, and pinning is on the library version
# --------------------------------------------------------------------------
#
# `TASKS.md` 3.7. The decision is only worth anything if the instruction it
# gives a consumer is followable and is actually written down where a consumer
# looks, so both are checked rather than assumed.

SPEC = (PYPROJECT.parent / "SPEC.md").read_text(encoding="utf-8")
README = (PYPROJECT.parent / "README.md").read_text(encoding="utf-8")


def test_the_spec_declares_the_unfrozen_bucket():
    # Stated, not implied. The failure this guards against is the document
    # quietly reverting to language that suggests `0.x` tracks changes.
    section = SPEC[SPEC.index("#### `schema_version` while unfrozen") :]
    section = section[: section.index("### 3.10")]
    assert "single unfrozen bucket" in section
    assert "does not track changes" in section.lower()
    assert "spanweave_version" in section


def test_the_field_the_spec_tells_a_consumer_to_pin_on_actually_exists():
    """B's instruction has to be followable from the graph file alone.

    If `meta.spanweave_version` were ever dropped, the advice "pin on the
    library version, not on `schema_version`" would send a consumer to a field
    that is not there -- and the only remaining discriminator would be one the
    project has just declared non-discriminating.
    """
    import pathlib

    import spanweave

    trace = PYPROJECT.parent / "fixtures/conformance/llm_tool_llm/dialects"
    document = spanweave.to_document(
        spanweave.build(pathlib.Path(trace / "openinference.jsonl"))
    )
    assert document["meta"]["spanweave_version"] == spanweave.__version__
    assert document["schema_version"] == spanweave.SCHEMA_VERSION


def test_both_reader_facing_surfaces_say_which_version_to_pin():
    from spanweave.cli import _SCHEMA_NOTICE

    assert "meta.spanweave_version" in _SCHEMA_NOTICE
    assert "not on" in _SCHEMA_NOTICE
    assert "Pin on the spanweave version" in README
