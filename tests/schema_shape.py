"""The serialized shape of a graph, derived so that corpus growth cannot move it.

This is `TASKS.md` 3.7's Option C: the tripwire. `SCHEMA_VERSION` is `"0.1"`
and, under Option B, stays `"0.1"` for the whole of `0.x` -- so the version
number cannot be what stops a shape change from shipping unnoticed. This can.

**What went wrong without it.** Two changes to the serialized graph shipped
under one `schema_version`, and neither was caught by anything:

- `a953a1f` renamed `meta.adapters[].confidence` to `declared_confidence`.
  Invisible to the corpus, because `canonical()` drops `meta.adapters` whole,
  so both dialects and the equivalence test were *structurally incapable* of
  noticing it. Its own commit message says "cheap now, a version bump after
  the freeze"; the bump never came.
- `9e79658` changed `diagnostics[].source` on the unpaired codes from a bare
  string to `{"call_id", "operation"}`. The declared type is `JsonValue`, so
  no type checker and no annotation could see it either.

Neither was a bad decision. Both were invisible, and invisible is the defect.

**The decided scope (`TASKS.md` 3.7): shape, never contents.** Field names,
types and nesting are the shape. What a trace happened to contain is not. That
line is what makes this instrument survivable -- a tripwire that fires every
time somebody adds a fixture is switched off within a month, and then it
guards nothing.

**How the line is held: nothing here reads the corpus.** Not one fixture, not
one trace, not one built graph from a file. Every section below is derived
from the library's own code and documents, so adding, changing or deleting a
fixture *cannot* move this artifact -- not "is unlikely to", cannot.
`tests/test_schema_shape.py` proves that with a plant rather than asserting it.

The five sections, and what each one would have caught:

1. `document` -- the serialized key tree: every path the serializer emits, and
   whether it is an object, an array, or a leaf. Built by serializing a
   synthetic specimen graph constructed *here*, never one read from a file.
   Catches a rename, an addition, a removal, a re-nesting. **Catches `a953a1f`.**
2. `model` -- every serialized model dataclass, field by field, with its
   declared annotation. Catches a type change the key tree cannot see, and
   catches a model-level rename. **Also catches `a953a1f`.**
3. `vocabularies` -- the closed enums and the diagnostic code tuple. Extending
   either is already a halt point (`AGENT.md`); this makes it show up in a
   diff as well as in a review.
4. `passthrough` -- the decided boundary itself, committed rather than buried
   in this file's constants. These are the regions whose *contents* the
   library copies rather than constructs: trace payload, and the one
   consumer-supplied value. Their container is pinned; nothing below it is.
   Widening this list is how someone would silently blind the instrument, so
   the list lives in the artifact where widening it shows up as a diff.
5. `diagnostic_source` -- `SPEC.md` §3.7's `source`-per-code table, normalized.
   `source` is `JsonValue`, so its shape is not in any annotation; §3.7 is
   where it is stated, and `tests/test_codes.py` is what holds the library to
   §3.7. Pinning the table closes the loop. **Catches `9e79658`.**

Section 5 reads a document rather than the code, which is a real weakness and
is named rather than hidden: it catches a `source` shape change only because
`test_codes.py` forces §3.7 to move when the library does. Two instruments in
series, and this file is only one of them.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import Any

from spanweave import diagnostics
from spanweave.annotate import Annotation, AnnotationStore
from spanweave.graph import Graph
from spanweave.model import (
    AdapterInfo,
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
from spanweave.serialize import to_document
from spanweave.version import SCHEMA_VERSION

REPO = pathlib.Path(__file__).resolve().parent.parent
ARTIFACT = pathlib.Path(__file__).resolve().parent / "serialized_shape.json"

#: Serialized regions whose CONTENTS the library copies rather than constructs
#: -- trace payload, and `annotations[].value`, which the consumer supplies.
#: The container is part of the shape; what is inside it is not, and must not
#: be, or every fixture becomes a schema change.
#:
#: This is the boundary `TASKS.md` 3.7 decided. It is committed into the
#: artifact (section 4) because widening it is exactly how someone would blind
#: this instrument without appearing to change anything.
PASSTHROUGH = (
    "$.annotations[].value",
    "$.nodes[].attributes",
    "$.nodes[].inputs.raw",
    "$.nodes[].inputs.value",
    "$.nodes[].outputs.raw",
    "$.nodes[].outputs.value",
    "$.nodes[].raw.source",
    "$.nodes[].usage.extra",
)

#: Serialized paths whose shape is declared in section 5 rather than by the
#: specimen. `diagnostics[].source` is `JsonValue` and its shape is per code
#: (`SPEC.md` §3.7), so whatever the specimen happens to carry is the
#: specimen's choice and not the library's claim. Recording the specimen's
#: choice here would read as a guarantee the library does not make.
DECLARED_ELSEWHERE = ("$.diagnostics[].source",)

#: Every dataclass that reaches the serialized document. `AnnotationStore` and
#: `Graph` are containers rather than serialized shapes and are covered by the
#: key tree instead.
SERIALIZED_MODELS = (
    AdapterInfo,
    Annotation,
    Diagnostic,
    Edge,
    Meta,
    Node,
    Payload,
    Provenance,
    RawRecord,
    Usage,
)


# --------------------------------------------------------------------------
# 1. The serialized key tree
# --------------------------------------------------------------------------


def specimen() -> Graph:
    """A graph built HERE, populating every optional field.

    Constructed rather than read, and that is the whole point: no fixture can
    reach this, so no fixture can move the key tree. Every nullable field is
    given a value, because a `None` would serialize to `null` and hide the key
    it belongs to behind an indistinguishable leaf.
    """
    payload = Payload(
        state=PayloadState.PRESENT,
        mime="application/json",
        value={"specimen": True},
        raw='{"specimen": true}',
    )
    common: dict[str, Any] = {
        "kind": NodeKind.LLM,
        "name": "specimen",
        "raw": RawRecord(source={"specimen": True}, source_id="src", line_number=1),
        "provenance": Provenance(
            adapter_id="specimen",
            adapter_version="0.0.0",
            dialect_note="a note",
        ),
        "operation": "op",
        "started_at": 0.0,
        "ended_at": 1.0,
        "status": Status.OK,
        "status_note": "a note",
        "inputs": payload,
        "outputs": payload,
        "usage": Usage(
            input_tokens=1, output_tokens=1, total_tokens=2, extra={"cached": 1}
        ),
        "attributes": {"specimen": True},
    }
    return Graph.of(
        trace_id="specimen",
        nodes=(Node(id="a", **common), Node(id="b", **common)),
        edges=(
            Edge(
                src="a",
                dst="b",
                kind=EdgeKind.PARENT,
                warrant=Warrant.EXPLICIT,
                basis="specimen",
                adapter="specimen",
            ),
        ),
        diagnostics=(
            Diagnostic(
                code=diagnostics.UNPAIRED_CALL,
                message="a message",
                level=DiagnosticLevel.WARNING,
                node_id="a",
                source={"call_id": "c", "operation": "op"},
                adapter="specimen",
            ),
        ),
        meta=Meta(
            schema_version=SCHEMA_VERSION,
            spanweave_version="0.0.0",
            adapters=(
                AdapterInfo(id="specimen", version="0.0.0", declared_confidence=0.5),
            ),
            source_digest="0" * 64,
            node_count=2,
            edge_count=1,
            diagnostic_count=1,
        ),
        annotations=AnnotationStore(
            entries=(
                Annotation(
                    namespace="ns", node_id="a", key="k", value={"specimen": True}
                ),
            )
        ),
    )


def key_tree() -> dict[str, str]:
    """Every serialized path, and what kind of thing sits at it.

    Types of *leaves* are deliberately absent: they would be the specimen's
    types, not the library's, and the library's are section 2's job.
    """
    tree: dict[str, str] = {}

    def walk(path: str, value: Any) -> None:
        if path in PASSTHROUGH:
            tree[path] = "passthrough"
            return
        if path in DECLARED_ELSEWHERE:
            tree[path] = "per-code (see diagnostic_source)"
            return
        if isinstance(value, dict):
            tree[path] = "object"
            for key in sorted(value):
                walk(f"{path}.{key}", value[key])
        elif isinstance(value, list):
            tree[path] = "array"
            for item in value:
                walk(f"{path}[]", item)
        else:
            tree[path] = "leaf"

    walk("$", to_document(specimen()))
    return tree


# --------------------------------------------------------------------------
# 2. The declared model
# --------------------------------------------------------------------------


def model_fields() -> dict[str, dict[str, str]]:
    """Every serialized dataclass, field by field, with its annotation.

    Private fields are skipped: they are not serialized, so moving one is not
    a schema change and should not read as one.
    """
    return {
        cls.__name__: {
            f.name: str(f.type)
            for f in dataclasses.fields(cls)
            if not f.name.startswith("_")
        }
        for cls in sorted(SERIALIZED_MODELS, key=lambda c: c.__name__)
    }


# --------------------------------------------------------------------------
# 3. The closed vocabularies
# --------------------------------------------------------------------------


def vocabularies() -> dict[str, list[str]]:
    """The closed enums, plus the diagnostic codes.

    Extending any of these is already a halt point (`AGENT.md`). Recording
    them means a reviewer sees it in the diff as well as in the prose.
    """
    enums = (
        DiagnosticLevel,
        EdgeKind,
        NodeKind,
        PayloadState,
        Status,
        Warrant,
    )
    recorded: dict[str, list[str]] = {
        enum.__name__: [member.value for member in enum] for enum in enums
    }
    recorded["diagnostic_codes"] = sorted(diagnostics.CODES)
    return recorded


# --------------------------------------------------------------------------
# 5. `source`, per code, as SPEC.md §3.7 states it
# --------------------------------------------------------------------------

_ROW = re.compile(r"^\|\s*`?([a-z_ ]+?)`?\s*\|(.+?)\|\s*$", re.M)
_BACKTICKED = re.compile(r"`([^`]+)`")


def diagnostic_source_shapes() -> dict[str, str]:
    """`SPEC.md` §3.7's `source` table, reduced to its structural claim.

    The prose after an em dash is explanation and is dropped, so rewording a
    justification does not read as a schema change. What is kept is the
    declared shape itself -- the first backticked token, or the whole cell
    where the row states its shape in words (the catch-all does).
    """
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
    start = spec.index("#### `source`, per code")
    block = spec[start : spec.index("### 3.8", start)]

    shapes: dict[str, str] = {}
    for code, cell in _ROW.findall(block):
        if code in ("Code", "---"):
            continue
        backticked = _BACKTICKED.search(cell)
        shape = backticked.group(1) if backticked else cell.split("—")[0]
        shapes[code.strip()] = " ".join(shape.split())
    return shapes


# --------------------------------------------------------------------------
# The artifact
# --------------------------------------------------------------------------


def shape() -> dict[str, Any]:
    """The whole committed shape. Nothing here reads a fixture."""
    return {
        "_": (
            "The SHAPE of a serialized graph -- field names, types, nesting. "
            "Never its contents. Regenerate with `make shape` and commit the "
            "diff in the same change (tests/schema_shape.py, TASKS.md 3.7)."
        ),
        "document": key_tree(),
        "model": model_fields(),
        "vocabularies": vocabularies(),
        "passthrough": list(PASSTHROUGH),
        "declared_elsewhere": list(DECLARED_ELSEWHERE),
        "diagnostic_source": diagnostic_source_shapes(),
    }


def differences(committed: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every way the two disagree, as sentences a reviewer can act on."""
    problems: list[str] = []
    for section in sorted(set(committed) | set(current)):
        if section == "_":
            continue
        was, now = committed.get(section), current.get(section)
        if was == now:
            continue
        if isinstance(was, dict) and isinstance(now, dict):
            for key in sorted(set(was) | set(now)):
                if was.get(key) == now.get(key):
                    continue
                if key not in was:
                    problems.append(f"{section}: {key} added, as {now[key]!r}")
                elif key not in now:
                    problems.append(f"{section}: {key} removed (was {was[key]!r})")
                else:
                    problems.append(
                        f"{section}: {key} was {was[key]!r}, now {now[key]!r}"
                    )
        else:
            problems.append(f"{section}: was {was!r}, now {now!r}")
    return problems


def write() -> None:
    """Regenerate the committed artifact. `make shape`."""
    import json

    ARTIFACT.write_text(
        json.dumps(shape(), indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":  # pragma: no cover - a maintenance entry point
    write()
    print(f"wrote {ARTIFACT.relative_to(REPO)}")
