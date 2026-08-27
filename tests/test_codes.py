"""The code tables in SPEC.md and the code tables in the library must agree.

Both diagnostic codes (`SPEC.md` §3.7) and error codes (§3.10) are a public
contract from `0.9.x`: consumers match on them, so adding one is deliberate and
renaming one after the freeze needs a version bump. That makes drift between
the spec and the code a contract break rather than a documentation lapse, and
drift is exactly what nobody notices.

`spanweave/diagnostics.py` claimed a test asserted this. Until this file, none
did — found in Phase 1 review.
"""

import pathlib
import re

from spanweave import diagnostics
from spanweave.errors import (
    ERROR_CODES,
    AdapterSelectionError,
    DuplicateNodeIdError,
    SpanweaveError,
    UnknownAdapterError,
)

SPEC = (pathlib.Path(__file__).resolve().parent.parent / "SPEC.md").read_text(
    encoding="utf-8"
)

ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.MULTILINE)


def codes_in(section: str, until: str) -> set[str]:
    """Every code named in the first column of a table in one SPEC section."""
    start = SPEC.index(section)
    return set(ROW.findall(SPEC[start : SPEC.index(until, start)]))


def test_the_diagnostic_codes_match_the_spec():
    assert codes_in("### 3.7 Diagnostic", "### 3.8") == set(diagnostics.CODES)


def test_the_error_codes_match_the_spec():
    assert codes_in("### 3.10 Errors", "## 4.") == set(ERROR_CODES)


def test_the_code_tables_have_no_duplicates():
    assert len(diagnostics.CODES) == len(set(diagnostics.CODES))
    assert len(ERROR_CODES) == len(set(ERROR_CODES))


def test_every_error_type_carries_a_registered_code():
    for error_type in (
        SpanweaveError,
        AdapterSelectionError,
        UnknownAdapterError,
        DuplicateNodeIdError,
    ):
        if error_type is SpanweaveError:
            continue  # the base class's placeholder is not a contract
        assert error_type.code in ERROR_CODES


def test_an_error_reports_the_cause_not_just_the_type():
    # The point of codes: one type, several causes, and a caller that wants to
    # retry an ambiguous input with --adapter but fail hard on a broken
    # adapter must be able to tell them apart without reading English.
    ambiguous = AdapterSelectionError("two adapters tied")
    broken = AdapterSelectionError("adapter raised", code="adapter_detect_failed")
    assert type(ambiguous) is type(broken)
    assert ambiguous.code != broken.code


def test_the_message_is_not_the_matching_surface():
    error = DuplicateNodeIdError("anything at all")
    assert error.code == "duplicate_node_id"
    assert str(error) == "anything at all"


# --------------------------------------------------------------------------
# The rule has to be followable through the public API (TASKS.md F4)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.10 instructs callers to match on the code and never on the
# message. A caller can only do that if it can get hold of an error object it
# knows carries one -- which means `except SpanweaveError`. Until these were
# exported the instruction was impossible to obey through the public API: the
# only route was `except Exception` plus `getattr(error, "code", None)`, which
# puts a missing file, a permissions error and a trace the library
# deliberately refused in one branch and distinguishes them by an absence.
#
# Found by the Phase 2b consumer, which had written exactly that workaround.

TYPE_COLUMN = re.compile(r"^\|\s*`[a-z_]+`\s*\|\s*`([A-Za-z]+)`\s*\|", re.MULTILINE)


def types_named_in_the_spec() -> set[str]:
    start = SPEC.index("### 3.10 Errors")
    return set(TYPE_COLUMN.findall(SPEC[start : SPEC.index("## 4.", start)]))


def test_every_error_type_the_spec_names_is_on_the_public_api():
    import spanweave

    named = types_named_in_the_spec()
    assert named, "the §3.10 table named no types -- the regex has gone stale"
    for name in named | {"SpanweaveError"}:
        assert hasattr(spanweave, name), f"{name} is in SPEC.md §3.10 but not exported"
        assert name in spanweave.__all__, f"{name} is importable but not in __all__"


def test_a_public_api_only_caller_can_obey_the_rule_as_written():
    # The whole point, written the way a consumer would write it: catch the
    # library's own error, read the code, never touch the message.
    from spanweave import AdapterSelectionError, SpanweaveError

    def build_a_trace():
        raise AdapterSelectionError("two adapters tied", code="adapter_ambiguous")

    try:
        build_a_trace()
    except SpanweaveError as error:
        assert error.code == "adapter_ambiguous"
    else:  # pragma: no cover - the raise above is unconditional
        raise AssertionError("the library's error type did not catch it")


def test_the_exported_types_are_the_same_objects_as_the_internal_ones():
    # An export that shadowed the real class would make `except` silently
    # miss -- the exact failure this fix exists to remove.
    import spanweave
    from spanweave import errors

    assert spanweave.SpanweaveError is errors.SpanweaveError
    assert spanweave.AdapterSelectionError is errors.AdapterSelectionError
    assert spanweave.UnknownAdapterError is errors.UnknownAdapterError
    assert spanweave.DuplicateNodeIdError is errors.DuplicateNodeIdError


def test_something_that_is_not_the_librarys_error_is_not_caught_by_it():
    # The distinction that was unavailable before: a missing file is not a
    # trace the library refused, and a consumer is entitled to say so.
    from spanweave import SpanweaveError

    assert not isinstance(FileNotFoundError("no such file"), SpanweaveError)


# --------------------------------------------------------------------------
# `source`'s shape, which is per code and therefore has to be stated
# --------------------------------------------------------------------------


def source_shapes() -> dict[str, str]:
    """`SPEC.md` §3.7's `source` table: code -> the shape column, verbatim."""
    start = SPEC.index("#### `source`, per code")
    block = SPEC[start : SPEC.index("### 3.8", start)]
    return {
        code: shape.strip()
        for code, shape in re.findall(r"^\|\s*`([a-z_]+)`\s*\|([^|]*)\|", block, re.M)
    }


def test_every_code_with_a_declared_source_shape_is_a_real_code():
    # A shape documented for a code that does not exist is a contract nobody
    # can meet, and reads as coverage.
    assert set(source_shapes()) <= set(diagnostics.CODES)


def test_the_unpaired_codes_emit_the_object_the_spec_declares():
    """`source` is `JsonValue`, so only this keeps the document honest.

    The type permits anything, which means the contract lives entirely in
    §3.7's table -- and a table nothing checks is how `FIXTURES.md` §4's
    Compared list went wrong three times.
    """
    import spanweave
    from spanweave.serialize import to_document

    corpus = pathlib.Path(__file__).resolve().parent.parent / "fixtures/conformance"
    shapes = source_shapes()
    seen = set()
    for dialect in ("openinference", "otel_genai"):
        path = corpus / f"unpaired_tool_call/dialects/{dialect}.jsonl"
        for entry in to_document(spanweave.build(path))["diagnostics"]:
            code = entry["code"]
            if code not in (diagnostics.UNPAIRED_CALL, diagnostics.UNPAIRED_RESULT):
                continue
            seen.add(code)
            assert "call_id" in shapes[code] and "operation" in shapes[code], (
                f"SPEC.md §3.7 does not declare an object source for {code}"
            )
            assert sorted(entry["source"]) == ["call_id", "operation"]
            assert isinstance(entry["source"]["call_id"], str)
    assert seen == {diagnostics.UNPAIRED_CALL, diagnostics.UNPAIRED_RESULT}
