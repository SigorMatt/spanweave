"""`CONTRACTS.md` must name every permissively-typed serialized field.

The inventory is only worth what its currency is worth. A field added to the
model, serialized, and left out of the document is precisely the failure the
inventory exists to record — so the document is checked against the model
rather than maintained beside it.

Both directions, as `FIXTURES.md` §4's Compared list is checked
(`test_the_compared_list_names_every_field_that_is_compared`), and for the same
reason: that list was wrong twice in the same direction because *keeping is the
default*, and prose is not where anyone looks.

What is checked here:

* the object map below matches a real graph document, in both directions, so
  the enumeration cannot silently miss a nested object;
* every serialized key of every object is a field of that object's model type,
  and every model field is either serialized or declared unserialized with a
  reason;
* every permissively-typed serialized field has a row, and every row names a
  permissively-typed serialized field;
* each row's declared type is the model's type, spelled the same way;
* each row's status is derived from its own Stated and Asserted cells;
* every document and section a row cites exists, and every test node id a row
  cites is a test that exists;
* the *Relies on* list covers exactly the rows, because a row without one
  records that a field is typed permissively and nothing more, which is the
  thing `TASKS.md` 3.2 says is not the deliverable;
* the eleven fields the document reports as unasserted are exactly the rows
  whose Asserted cell is empty.

`TASKS.md` 3.2. This file states no contract; it keeps the enumeration honest.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import re
import types
import typing

import pytest

import spanweave
from spanweave import annotate, model
from spanweave.graph import Graph
from spanweave.serialize import to_document
from tests.conformance import CORPUS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = (ROOT / "CONTRACTS.md").read_text(encoding="utf-8")

#: Every object a graph document contains, and the model type it is written
#: from. Hand-written, and checked against a real document in both directions
#: below -- so it cannot drift from the serializer or from the model.
OBJECTS: dict[str, type] = {
    "meta": model.Meta,
    "meta.adapters[]": model.AdapterInfo,
    "nodes[]": model.Node,
    "nodes[].inputs": model.Payload,
    "nodes[].outputs": model.Payload,
    "nodes[].usage": model.Usage,
    "nodes[].raw": model.RawRecord,
    "nodes[].provenance": model.Provenance,
    "edges[]": model.Edge,
    "diagnostics[]": model.Diagnostic,
    "annotations[]": annotate.Annotation,
}

#: The two root scalars, which belong to no serialized object.
#: `schema_version` is `Meta`'s field written at the root instead of under
#: `meta`; `trace_id` is the graph's own.
ROOT_FIELDS: dict[str, tuple[type, str]] = {
    "schema_version": (model.Meta, "schema_version"),
    "trace_id": (Graph, "trace_id"),
}

#: Model fields that are deliberately NOT serialized at their object's path.
#: Declared rather than inferred, so that a field quietly starting or stopping
#: being written goes red here.
NOT_SERIALIZED: dict[str, set[str]] = {
    # Written at the document root instead (see ROOT_FIELDS).
    "meta": {"schema_version"},
    # It depends on input order and the graph must not (`SPEC.md` §3.5).
    "nodes[].raw": {"line_number"},
}

SERIALIZED_TYPES = set(OBJECTS.values())

#: The closed status vocabulary, and the (stated, asserted) pair each stands
#: for. `pinned` means a committed expected graph or fixture literal compares
#: the value: a change is detected, nothing states what the value should be.
STATUSES = {
    (True, "rule"): "stated + asserted",
    (True, "pin"): "stated + pinned",
    (True, "none"): "stated, unasserted",
    (False, "rule"): "unstated + asserted",
    (False, "pin"): "unstated + pinned",
    (False, "none"): "unstated, unmeasured",
}


# --------------------------------------------------------------------------
# Reading the model
# --------------------------------------------------------------------------


def _is_optional(annotation: object) -> bool:
    return typing.get_origin(annotation) in (
        types.UnionType,
        typing.Union,
    ) and type(None) in typing.get_args(annotation)


def _strip_optional(annotation: object) -> object:
    if typing.get_origin(annotation) in (types.UnionType, typing.Union):
        rest = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(rest) == 1:
            return rest[0]
    return annotation


def _is_leaf(annotation: object) -> bool:
    """False for a field that is itself one of the serialized objects."""
    base = _strip_optional(annotation)
    if base in SERIALIZED_TYPES:
        return False
    if typing.get_origin(base) in (tuple, list):
        return not any(arg in SERIALIZED_TYPES for arg in typing.get_args(base))
    return True


def _is_permissive(annotation: object) -> bool:
    """`CONTRACTS.md`'s scope rule, as a type test rather than a judgement."""
    base = _strip_optional(annotation)
    if base is typing.Any:  # JsonValue
        return True
    if isinstance(base, type) and issubclass(base, enum.Enum):
        return False
    if base is str:
        return True
    if base in (int, float, bool):
        return False
    # A Mapping / dict / list / tuple of anything: the key or element
    # vocabulary is open even where the values are typed.
    return typing.get_origin(base) is not None


def _name(base: object) -> str:
    if base is typing.Any:
        return "JsonValue"
    origin = typing.get_origin(base)
    if origin is None:
        return getattr(base, "__name__", str(base))
    args = ", ".join(_name(arg) for arg in typing.get_args(base))
    return f"{getattr(origin, '__name__', str(origin))}[{args}]"


def _render(annotation: object) -> str:
    text = _name(_strip_optional(annotation))
    return f"{text} | None" if _is_optional(annotation) else text


def permissive_fields() -> dict[str, str]:
    """Every permissively-typed serialized field, path -> type, from the model."""
    found = {}
    for key, (owner, field_name) in ROOT_FIELDS.items():
        annotation = typing.get_type_hints(owner)[field_name]
        if _is_permissive(annotation):
            found[key] = _render(annotation)
    for path, owner in OBJECTS.items():
        hints = typing.get_type_hints(owner)
        for field in dataclasses.fields(owner):
            if field.name in NOT_SERIALIZED.get(path, set()):
                continue
            annotation = hints[field.name]
            if _is_leaf(annotation) and _is_permissive(annotation):
                found[f"{path}.{field.name}"] = _render(annotation)
    return found


# --------------------------------------------------------------------------
# Reading a real document
# --------------------------------------------------------------------------


def _documents() -> list[dict[str, object]]:
    built = []
    paths = sorted(CORPUS.glob("*/dialects/*.jsonl")) + sorted(
        (ROOT / "fixtures/captured").glob("*.jsonl")
    )
    for path in paths:
        try:
            built.append(to_document(spanweave.build(path)))
        except spanweave.SpanweaveError:
            # A scenario that must not build (`FIXTURES.md` §4.2). It has no
            # document to read, which is the assertion elsewhere.
            continue
    assert built, "no fixture produced a document to read the schema from"
    return built


DOCUMENTS = _documents()


def observed() -> dict[str, set[str]]:
    """Path -> every key seen at it, unioned over every fixture."""
    seen: dict[str, set[str]] = {}

    def note(path: str, value: object) -> None:
        assert isinstance(value, dict)
        seen.setdefault(path, set()).update(value)

    for document in DOCUMENTS:
        meta = document["meta"]
        if isinstance(meta, dict):
            note("meta", meta)
            for adapter in meta["adapters"]:
                note("meta.adapters[]", adapter)
        for node in document["nodes"]:
            note("nodes[]", node)
            for side in ("inputs", "outputs"):
                note(f"nodes[].{side}", node[side])
            if node["usage"] is not None:
                note("nodes[].usage", node["usage"])
            note("nodes[].raw", node["raw"])
            note("nodes[].provenance", node["provenance"])
        for edge in document["edges"]:
            note("edges[]", edge)
        for diagnostic in document["diagnostics"]:
            note("diagnostics[]", diagnostic)
    # No committed fixture carries an annotation, so the one object a graph
    # can hold and a trace cannot produce is exercised here rather than
    # left absent -- an object missing from the map because nothing built one
    # is the gap this check exists to close.
    annotated = spanweave.build(CORPUS / "llm_tool_llm/dialects/openinference.jsonl")
    annotated = annotated.annotate("s1", "my_evals", "k", 1)
    for entry in to_document(annotated)["annotations"]:
        note("annotations[]", entry)
    return seen


OBSERVED = observed()


def test_the_object_map_names_every_object_a_document_contains():
    assert sorted(OBSERVED) == sorted(OBJECTS)


def test_every_serialized_key_is_a_field_of_its_model_type():
    for path, owner in OBJECTS.items():
        fields = {field.name for field in dataclasses.fields(owner)}
        unknown = sorted(OBSERVED[path] - fields)
        assert unknown == [], (
            f"the serializer writes {unknown} under {path!r}, which is not a "
            f"field of {owner.__name__}: the inventory reads types from the "
            f"model, so a key with no field behind it cannot be classified"
        )


def test_every_model_field_is_serialized_or_declared_unserialized():
    for path, owner in OBJECTS.items():
        fields = {field.name for field in dataclasses.fields(owner)}
        missing = sorted(fields - OBSERVED[path] - NOT_SERIALIZED.get(path, set()))
        assert missing == [], (
            f"{owner.__name__}.{missing} is not written under {path!r} and is "
            f"not declared unserialized. Losslessness is an invariant "
            f"(`CLAUDE.md` 2): a model field that quietly stops being "
            f"serialized is a silent drop"
        )


def test_no_declared_unserialized_field_is_serialized_after_all():
    # The other direction, and the cheaper mistake: a declaration that has
    # gone stale reads as a deliberate omission and is not one.
    for path, declared in NOT_SERIALIZED.items():
        assert declared & OBSERVED[path] == set(), (
            f"{path!r} declares {sorted(declared & OBSERVED[path])} "
            f"unserialized and writes it"
        )


# --------------------------------------------------------------------------
# Reading CONTRACTS.md
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Row:
    path: str
    type: str
    stated: str
    asserted: str
    status: str


#: A `|` inside a cell is escaped in Markdown, and a `str \| None` type cell
#: would otherwise split into two.
ESCAPED = "\x00"


def _cells(line: str) -> list[str]:
    line = line.strip().replace(r"\|", ESCAPED).strip("|")
    return [cell.strip().replace(ESCAPED, "|") for cell in line.split("|")]


def inventory() -> str:
    """The `## The inventory` section, and nothing else.

    Sliced rather than filtered by shape: the findings below carry tables of
    their own, and a row dropped because its status cell had a typo would be a
    row this file silently stopped checking.
    """
    start = CONTRACTS.index("## The inventory")
    return CONTRACTS[start : CONTRACTS.index("\n## Relies on", start)]


def rows() -> tuple[Row, ...]:
    """Every inventory row of the document."""
    found = []
    for line in inventory().splitlines():
        if not line.startswith("| `"):
            continue
        cells = _cells(line)
        if len(cells) != 5:
            continue
        found.append(
            Row(
                path=cells[0].strip("`"),
                type=cells[1].strip("`"),
                stated=cells[2],
                asserted=cells[3],
                status=cells[4],
            )
        )
    return tuple(found)


ROWS = rows()


def test_the_document_has_a_row_for_every_permissively_typed_serialized_field():
    """The direction the Compared list got wrong: keeping is the default.

    A field added to the model and serialized is published by `0.9.x` whether
    or not anyone remembered to write it down, and an unstated serialized
    field is what strangers pin behavior to.
    """
    missing = sorted(set(permissive_fields()) - {row.path for row in ROWS})
    assert missing == [], (
        f"CONTRACTS.md has no row for {missing}. Every permissively-typed "
        f"serialized field needs one -- an honest 'unstated, unmeasured' row "
        f"is the deliverable for a field with no evidence (`TASKS.md` 3.2)"
    )


def test_the_document_names_nothing_that_is_not_one():
    # A row for a field that has been removed, or tightened to a closed type,
    # reads as coverage of something that is no longer there.
    extra = sorted({row.path for row in ROWS} - set(permissive_fields()))
    assert extra == [], (
        f"CONTRACTS.md has rows for {extra}, which are not permissively-typed "
        f"serialized fields today"
    )


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.path)
def test_each_row_declares_the_type_the_model_declares(row):
    assert row.type == permissive_fields()[row.path]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.path)
def test_each_row_s_status_follows_from_its_own_cells(row):
    stated = row.stated != "—"
    if "::" in row.asserted:
        evidence = "rule"
    elif "corpus pin" in row.asserted:
        evidence = "pin"
    else:
        assert row.asserted == "—", (
            f"{row.path}: an Asserted cell is a test node id, `corpus pin`, "
            f"or `—`; got {row.asserted!r}"
        )
        evidence = "none"
    assert row.status == STATUSES[(stated, evidence)], (
        f"{row.path} says {row.status!r}; its own cells say "
        f"{STATUSES[(stated, evidence)]!r}"
    )


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.path)
def test_every_document_a_row_cites_says_something_there(row):
    """A citation that resolves to nothing is how `Stated` stops meaning anything."""
    cited = re.findall(r"`([A-Za-z_]+\.md)`((?:\s*§[\d.]+,?)*)", row.stated)
    for name, section in cited:
        document = ROOT / name
        assert document.exists(), f"{row.path} cites {name}, which does not exist"
        text = document.read_text(encoding="utf-8")
        for number in re.findall(r"§([\d.]+)", section):
            assert re.search(rf"^#{{2,4}} {re.escape(number)}[. ]", text, re.M), (
                f"{row.path} cites {name} §{number}, which has no such section"
            )


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.path)
def test_every_test_a_row_cites_exists(row):
    for path, name in re.findall(r"`(tests/[a-z_]+\.py)::([a-z_0-9]+)`", row.asserted):
        source = ROOT / path
        assert source.exists(), f"{row.path} cites {path}, which does not exist"
        assert f"def {name}(" in source.read_text(encoding="utf-8"), (
            f"{row.path} cites {path}::{name}, which is not a test there"
        )


# --------------------------------------------------------------------------
# The prose the rows exist for
# --------------------------------------------------------------------------

RELIES_ON = re.compile(r"^- `([^`]+)` — ", re.MULTILINE)


def relies_on() -> set[str]:
    start = CONTRACTS.index("## Relies on")
    section = CONTRACTS[start : CONTRACTS.index("\n## ", start)]
    return set(RELIES_ON.findall(section))


def test_every_row_says_what_is_relied_on():
    """`TASKS.md` 3.2: "it is typed permissively" is not the useful output.

    The note is the deliverable -- what the library depends on that no
    document states and no test asserts. A row without one records the type
    and nothing else.
    """
    missing = sorted({row.path for row in ROWS} - relies_on())
    assert missing == [], f"no `Relies on` note for {missing}"


def test_the_relies_on_list_names_nothing_that_is_not_a_row():
    extra = sorted(relies_on() - {row.path for row in ROWS})
    assert extra == [], f"`Relies on` names {extra}, which have no row"


def unasserted_block() -> set[str]:
    start = CONTRACTS.index("### The eleven fields nothing asserts")
    block = CONTRACTS[CONTRACTS.index("```text", start) + len("```text") :]
    return set(block[: block.index("```")].split())


def test_the_reported_unasserted_fields_are_the_rows_with_no_assertion():
    """The document's own headline count, checked against its own table.

    Both directions: a field that acquires an assertion must leave the block,
    and one that loses its last assertion must enter it. Neither can be done
    by editing one half.
    """
    assert unasserted_block() == {row.path for row in ROWS if row.asserted == "—"}
