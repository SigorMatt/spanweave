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
