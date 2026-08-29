"""The shape tripwire (`TASKS.md` 3.7, Option C).

`SCHEMA_VERSION` is `"0.1"` and stays `"0.1"` for the whole of `0.x`
(Option B), so the version number cannot be what stops a change to the
serialized graph from shipping unnoticed. This is what stops it: the shape is
committed, and moving it fails the build until the artifact is regenerated in
the same change, which puts the move in the diff where a reviewer meets it.

Two things have to be true for that to be worth having, and both are tested
here rather than asserted in prose:

* **It fires when the shape moves.** Three plants, one of them a replay of the
  exact change that shipped unnoticed at `a953a1f`.
* **It stays silent when the corpus grows.** A tripwire that goes off every
  time somebody adds a fixture is switched off within a month. Proved twice:
  once concretely, by adding a fixture and watching nothing move, and once
  generally, by recording every file the instrument opens and showing that
  none of them is in `fixtures/`. The second is the one that makes "cannot"
  true rather than "did not".
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import shutil

import pytest

from spanweave import serialize
from spanweave.model import Payload
from tests import schema_shape

CORPUS = schema_shape.REPO / "fixtures/conformance"


def committed() -> dict:
    return json.loads(schema_shape.ARTIFACT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The tripwire itself
# --------------------------------------------------------------------------


def test_the_committed_shape_is_the_shape_the_library_serializes():
    """THE gate. If this fails, the serialized graph changed.

    That is not automatically wrong -- the schema is unfrozen and changes are
    expected. It is a change that must be *seen*: regenerate with
    `make shape`, commit the diff in the same change, and say in the task
    record what moved and why. Under Option B the version number will not say
    it for you, and after the freeze this is what additive-only is measured
    against.
    """
    problems = schema_shape.differences(committed(), schema_shape.shape())
    assert not problems, (
        "the serialized graph's shape has moved:\n  "
        + "\n  ".join(problems)
        + "\n\nRegenerate with `make shape` and commit the diff in the same "
        "change (TASKS.md 3.7)."
    )


def test_the_artifact_is_written_the_way_the_repo_writes_json():
    """Committed so a human reads the diff, so the encoding must be stable."""
    text = schema_shape.ARTIFACT.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text == json.dumps(committed(), indent=1, sort_keys=True) + "\n"


# --------------------------------------------------------------------------
# It fires: three plants
# --------------------------------------------------------------------------


def test_it_fires_on_the_rename_that_actually_shipped_unnoticed():
    """`a953a1f` replayed: `meta.adapters[].confidence` -> `declared_confidence`.

    This shipped under `schema_version` `"0.1"` and nothing caught it, because
    `canonical()` drops `meta.adapters` whole -- the corpus, both dialects and
    the equivalence test were structurally incapable of seeing it.
    """
    before = schema_shape.key_tree()
    assert "$.meta.adapters[].declared_confidence" in before

    original = serialize._meta

    def renamed(meta):
        document = original(meta)
        if document is not None:
            for adapter in document["adapters"]:
                adapter["confidence"] = adapter.pop("declared_confidence")
        return document

    serialize._meta = renamed
    try:
        problems = schema_shape.differences(committed(), schema_shape.shape())
    finally:
        serialize._meta = original

    assert any("declared_confidence" in problem for problem in problems), problems
    assert any("confidence" in problem for problem in problems), problems


def test_it_fires_when_a_declared_type_changes(monkeypatch):
    """The other half: a type moves while every key stays where it was."""
    field = Payload.__dataclass_fields__["mime"]
    assert field.type == "str | None"

    monkeypatch.setattr(field, "type", "str", raising=False)
    problems = schema_shape.differences(committed(), schema_shape.shape())

    assert any("Payload" in problem and "mime" in problem for problem in problems), (
        problems
    )


def test_it_fires_when_a_key_is_added(monkeypatch):
    """A new serialized field is a shape change even when nothing else moves."""
    original = serialize._edge
    monkeypatch.setattr(
        serialize, "_edge", lambda edge: {**original(edge), "weight": 1.0}
    )

    problems = schema_shape.differences(committed(), schema_shape.shape())
    assert any("$.edges[].weight" in problem for problem in problems), problems


def test_the_unpaired_source_shape_is_pinned_where_it_is_actually_declared():
    """`9e79658`'s change is caught by section 5, not by the key tree.

    `diagnostics[].source` is `JsonValue`: no annotation and no type checker
    can see it move from a bare string to an object. `SPEC.md` §3.7 is where
    that shape is stated and `tests/test_codes.py` is what holds the library
    to §3.7, so pinning the table is what closes the loop.
    """
    declared = committed()["diagnostic_source"]
    for code in ("unpaired_call", "unpaired_result"):
        assert "call_id" in declared[code] and "operation" in declared[code]
    # And the catch-all row, which 3.2 found was false for three codes.
    assert "everything else" in declared


# --------------------------------------------------------------------------
# It stays silent: corpus growth cannot reach it
# --------------------------------------------------------------------------


def test_adding_a_fixture_does_not_move_the_shape():
    """The concrete plant: a real new scenario, added and then removed."""
    before = schema_shape.shape()
    planted = CORPUS / "_plant_added_by_a_test"
    if planted.exists():  # pragma: no cover - only after a crashed run
        shutil.rmtree(planted)

    try:
        (planted / "dialects").mkdir(parents=True)
        (planted / "expected").mkdir()
        (planted / "dialects/openinference.jsonl").write_text(
            json.dumps(
                {
                    "trace_id": "plant",
                    "span_id": "p0",
                    "name": "plant",
                    "attributes": {"openinference.span.kind": "TOOL"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (planted / "scenario.md").write_text("# a plant\n", encoding="utf-8")
        assert schema_shape.shape() == before
    finally:
        # Inside the try from the first mkdir: a corpus this suite left a
        # half-written scenario in would fail every conformance run after it.
        shutil.rmtree(planted, ignore_errors=True)

    assert not planted.exists()
    assert schema_shape.shape() == before


def test_the_instrument_never_reads_the_corpus(monkeypatch):
    """The general form, and the one that makes it *cannot* rather than *did not*.

    One plant proves one fixture is harmless. This proves every fixture is,
    by showing the instrument does not open a file under `fixtures/` at all --
    so there is no fixture, present or future, that could move the artifact.
    """
    opened: list[pathlib.Path] = []
    original = pathlib.Path.read_text

    def watched(self, *args, **kwargs):
        opened.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", watched)
    schema_shape.shape()

    assert opened, "the instrument read nothing at all -- has it stopped working?"
    inside = [path for path in opened if "fixtures" in path.parts]
    assert not inside, f"the instrument read the corpus: {inside}"


def test_the_passthrough_boundary_is_committed_not_just_coded():
    """Widening `PASSTHROUGH` is how someone would blind this without a trace.

    The list is in the artifact, so adding an entry -- which stops a whole
    region of the document being watched -- shows up as a diff rather than as
    a one-line constant change nobody reviews.
    """
    assert committed()["passthrough"] == list(schema_shape.PASSTHROUGH)
    assert committed()["declared_elsewhere"] == list(schema_shape.DECLARED_ELSEWHERE)


def test_every_passthrough_path_is_a_real_serialized_path():
    """A boundary entry naming a path that does not exist watches nothing.

    That is how the list rots: a field is renamed, its `PASSTHROUGH` entry
    goes stale, and the region it was meant to exclude is now compared while
    the list still claims otherwise -- or the reverse.
    """
    tree = schema_shape.key_tree()
    for path in (*schema_shape.PASSTHROUGH, *schema_shape.DECLARED_ELSEWHERE):
        assert path in tree, f"{path} is not a path this library serializes"


def test_every_serialized_model_is_in_the_recorded_set():
    """A model class that reaches the document but not `SERIALIZED_MODELS`
    would have its declared types unwatched."""
    recorded = {cls.__name__ for cls in schema_shape.SERIALIZED_MODELS}
    for cls in schema_shape.SERIALIZED_MODELS:
        assert dataclasses.is_dataclass(cls)
    assert recorded == set(committed()["model"])


@pytest.mark.parametrize("section", ("document", "model", "vocabularies"))
def test_no_section_is_empty(section):
    """An instrument that silently starts measuring nothing is worse than none.

    `tests/test_gates.py` makes the same argument about a gate that scans an
    empty set; this is that argument applied to this file.
    """
    assert committed()[section]
