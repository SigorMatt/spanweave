"""Node identity (TASKS.md 1.4).

The point of these tests is that the same trace produces the same ids on any
machine, in any process, forever -- and that when it cannot, it says so
instead of overwriting something.
"""

import subprocess
import sys

import pytest

from spanweave.errors import DuplicateNodeIdError
from spanweave.ids import DERIVED_PREFIX, assign, derive
from spanweave.model import NodeKind, RawRecord
from spanweave.seam import NormalizedSpan


def a_span(source_key, span_id=None, line=1):
    return NormalizedSpan(
        source_key=source_key,
        span_id=span_id,
        kind=NodeKind.CHAIN,
        name="op",
        raw=RawRecord(source={"span_id": span_id}, line_number=line),
    )


# --------------------------------------------------------------------------
# Rule 1: the dialect's own id, unchanged
# --------------------------------------------------------------------------


def test_a_unique_span_id_is_used_unchanged():
    spans = [a_span("s0", "s0"), a_span("s1", "s1")]
    assert assign(spans, "some_dialect", "t1").ids == ("s0", "s1")


def test_ids_do_not_depend_on_the_adapter_or_trace_when_the_dialect_has_them():
    spans = [a_span("s0", "s0")]
    assert assign(spans, "one", "t1").ids == assign(spans, "two", "t2").ids


# --------------------------------------------------------------------------
# Rule 2: derived, and stable
# --------------------------------------------------------------------------


def test_a_span_with_no_id_gets_a_derived_one():
    node_id = assign([a_span("1")], "some_dialect", "t1").ids[0]
    assert node_id.startswith(DERIVED_PREFIX)
    assert len(node_id) == len(DERIVED_PREFIX) + 16


def test_derived_ids_are_stable_across_runs():
    assert derive("some_dialect", "t1", "1") == derive("some_dialect", "t1", "1")


def test_derived_ids_are_stable_across_processes():
    # The failure this guards against is invisible within one process: a
    # salted hash agrees with itself all day and disagrees with tomorrow.
    program = (
        "from spanweave.ids import derive;print(derive('some_dialect', 't1', '1'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == derive("some_dialect", "t1", "1")


@pytest.mark.parametrize(
    ("adapter", "trace", "key"),
    [("other", "t1", "1"), ("some_dialect", "t2", "1"), ("some_dialect", "t1", "2")],
)
def test_every_ingredient_changes_the_derived_id(adapter, trace, key):
    assert derive(adapter, trace, key) != derive("some_dialect", "t1", "1")


def test_a_missing_trace_id_still_derives_an_id():
    assert derive("some_dialect", None, "1").startswith(DERIVED_PREFIX)


def test_derived_ids_do_not_depend_on_input_order():
    spans = [a_span("1"), a_span("2"), a_span("3")]
    forwards = assign(spans, "some_dialect", "t1").ids
    backwards = assign(list(reversed(spans)), "some_dialect", "t1").ids
    assert set(forwards) == set(backwards)
    assert forwards == tuple(reversed(backwards))


# --------------------------------------------------------------------------
# Collisions are refused, not resolved
# --------------------------------------------------------------------------


def test_two_records_claiming_one_span_id_is_a_hard_error():
    spans = [a_span("s1", "s1", line=1), a_span("s1", "s1", line=2)]
    with pytest.raises(DuplicateNodeIdError) as failure:
        assign(spans, "some_dialect", "t1")
    message = str(failure.value)
    # Actionable: which id, which records.
    assert "s1" in message
    assert "record 1" in message and "record 2" in message


def test_the_error_names_refusing_to_overwrite():
    spans = [a_span("s1", "s1"), a_span("s1", "s1", line=2)]
    with pytest.raises(DuplicateNodeIdError, match="Refusing to overwrite"):
        assign(spans, "some_dialect", "t1")


def test_a_duplicated_span_id_never_silently_wins():
    spans = [a_span("s1", "s1"), a_span("s1", "s1", line=2), a_span("s2", "s2")]
    with pytest.raises(DuplicateNodeIdError):
        assign(spans, "some_dialect", "t1")


def test_distinct_source_keys_behind_one_span_id_are_reported_not_refused():
    # The dialect's ids are not unique, but the records are distinguishable,
    # so both survive -- with the duplication reported.
    spans = [a_span("1", "s1"), a_span("2", "s1")]
    assignment = assign(spans, "some_dialect", "t1")
    assert assignment.duplicate_source_ids == ("s1",)
    assert len(set(assignment.ids)) == 2
    assert all(node_id.startswith(DERIVED_PREFIX) for node_id in assignment.ids)


def test_nothing_is_reported_when_ids_are_unique():
    assignment = assign([a_span("s0", "s0"), a_span("s1", "s1")], "some_dialect", "t1")
    assert assignment.duplicate_source_ids == ()


def test_an_empty_input_assigns_nothing():
    assert assign([], "some_dialect", "t1").ids == ()
