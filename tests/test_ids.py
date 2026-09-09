"""Node identity (TASKS.md 1.4).

The point of these tests is that the same trace produces the same ids on any
machine, in any process, forever -- and that when it cannot, it says so
instead of overwriting something.
"""

import hashlib
import json
import subprocess
import sys

import pytest

from spanweave.errors import DuplicateNodeIdError
from spanweave.ids import DERIVED_PREFIX, assign, derive
from spanweave.model import NodeKind, RawRecord
from spanweave.read import record_digest
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
# Rule 3: a source key two records share (audit finding 2, batch A3)
# --------------------------------------------------------------------------


def a_record_span(source_key, span_id, source, line=1):
    return NormalizedSpan(
        source_key=source_key,
        span_id=span_id,
        kind=NodeKind.CHAIN,
        name="op",
        raw=RawRecord(source=source, line_number=line),
    )


def test_two_records_claiming_one_span_id_are_both_kept():
    # Previously a hard error, which refused the whole file for a duplicate
    # the dialect had no way to prevent. SPEC.md 3.7 has always said
    # `duplicate_source_id` fires here; until this rule it could not.
    spans = [
        a_record_span("s1", "s1", {"span_id": "s1", "name": "a"}),
        a_record_span("s1", "s1", {"span_id": "s1", "name": "b"}, line=2),
    ]
    assignment = assign(spans, "some_dialect", "t1")
    assert len(set(assignment.ids)) == 2
    assert assignment.duplicate_source_ids == ("s1",)
    assert all(node_id.startswith(DERIVED_PREFIX) for node_id in assignment.ids)


def test_a_shared_source_key_derives_from_the_record_not_its_position():
    # The alternative -- an ordinal -- would make the id depend on input
    # order, which CLAUDE.md 4 forbids outright.
    spans = [
        a_record_span("s1", "s1", {"span_id": "s1", "name": "a"}),
        a_record_span("s1", "s1", {"span_id": "s1", "name": "b"}, line=2),
    ]
    forwards = assign(spans, "some_dialect", "t1").ids
    backwards = assign(list(reversed(spans)), "some_dialect", "t1").ids
    assert forwards == tuple(reversed(backwards))


def test_a_unique_source_key_derives_exactly_as_it_always_did():
    # Rule 2's *material* is untouched, which is narrower than "no id moves":
    # see the test below for the record whose id rule 3 does move.
    spans = [a_record_span("1", None, {"name": "a"})]
    assert assign(spans, "some_dialect", "t1").ids == (
        derive("some_dialect", "t1", "1"),
    )


def test_a_key_a_second_record_also_claims_moves_that_record_off_rule_2():
    # What "rules 1 and 2 are untouched, so no node id the library produces
    # moves" (the A3 CHANGELOG entry, corrected in A8) missed. The rules are
    # untouched; an id is not. A record keyed `2` beside a record whose span
    # id is `2` shares that key, so it derives under rule 3 and lands on a
    # different id than rule 2 alone would have given it -- while the record
    # with the span id keeps rule 1 and notices nothing.
    #
    # Reachable when the fallback key was the record's 1-based index: review
    # concern 4 recorded exactly this pair. Batch A5 made the fallback the
    # record's canonical digest, so a trace file no longer reaches it, but
    # `assign` is public ground and a caller's two spans can still share a key.
    source = {"name": "a"}
    spans = [
        a_record_span("2", "2", {"span_id": "2", "name": "b"}),
        a_record_span("2", None, source, line=2),
    ]
    ids = assign(spans, "openinference", "t").ids
    assert ids[0] == "2"
    assert ids[1] == derive("openinference", "t", "2", record_digest(source))
    assert ids[1] != derive("openinference", "t", "2")
    # The id that moved, pinned: rule 2 on this key derives the literal the
    # review reported as the "before" half of the pair.
    assert derive("openinference", "t", "2") == "sw_fc49b046c1cd484d"


def test_the_records_content_is_what_separates_two_shared_keys():
    first = a_record_span("s1", "s1", {"span_id": "s1", "name": "a"})
    second = a_record_span("s1", "s1", {"span_id": "s1", "name": "b"}, line=2)
    third = a_record_span("s1", "s1", {"span_id": "s1", "name": "c"}, line=3)
    ids = assign([first, second, third], "some_dialect", "t1").ids
    again = assign([first, third, second], "some_dialect", "t1").ids
    assert ids[0] == again[0]
    assert ids[1] == again[2] and ids[2] == again[1]


# --------------------------------------------------------------------------
# Collisions are refused, not resolved
# --------------------------------------------------------------------------


def test_two_records_that_are_identical_in_every_respect_is_a_hard_error():
    # `a_span` gives both the same source record, so nothing -- not the
    # source key, not the content -- tells them apart. The reader collapses
    # such a pair before it reaches here (SPEC.md 7); reaching here at all
    # means a caller built the spans itself, and there is still nothing to
    # derive two ids from.
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


# --------------------------------------------------------------------------
# The formula is the spec's formula (September 2026 audit, batch A7)
# --------------------------------------------------------------------------
#
# `SPEC.md` §3.6 exists so that something other than this library can derive
# the same id. That claim is only worth as much as the text is exact, and the
# text omitted `ensure_ascii=False` until this batch -- so a reader who
# implemented it faithfully got a different id for every record carrying a
# non-ASCII character, with nothing here to notice. These tests reimplement
# the rules from the text, compare against the library on a record chosen to
# expose exactly that gap, and pin two literal ids so the formula cannot drift
# on either side without a failure that says so.


def spec_faithful_derive(adapter_id, trace_id, source_key, record=None):
    """`SPEC.md` §3.6 rules 2 and 3, written from the text and nothing else.

    Deliberately duplicated rather than imported: an implementation that calls
    `spanweave.ids.derive` agrees with it by construction and tests nothing.
    """
    material = "\x00".join((adapter_id, trace_id or "", source_key))
    if record is not None:
        canonical = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        material = "\x00".join((material, digest))
    return "sw_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


#: A record whose canonicalization differs between `ensure_ascii=False` and
#: the default: `{"name":"café"}` against `{"name":"café"}`.
NON_ASCII_RECORD = {"span_id": "s1", "name": "café"}


def test_the_spec_formula_derives_the_id_the_library_derives():
    assert derive("openinference", "t1", "1") == spec_faithful_derive(
        "openinference", "t1", "1"
    )


def test_the_spec_formula_agrees_on_a_record_that_is_not_ascii():
    # The case the spec's own text got wrong. Rule 3, because that is the
    # rule whose material contains the record's canonical digest.
    spans = [
        a_record_span("s1", "s1", NON_ASCII_RECORD),
        a_record_span("s1", "s1", {"span_id": "s1", "name": "b"}, line=2),
    ]
    assert assign(spans, "openinference", "t1").ids[0] == spec_faithful_derive(
        "openinference", "t1", "s1", NON_ASCII_RECORD
    )


def test_escaping_the_non_ascii_character_would_derive_a_different_id():
    # Why the word matters: this is the id the spec's text used to specify,
    # and it is not the id the library derives. Without this the two spellings
    # look interchangeable, which is how they came apart in the first place.
    escaped = json.dumps(NON_ASCII_RECORD, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(escaped.encode("utf-8")).hexdigest()
    material = "\x00".join(("openinference", "t1", "s1", digest))
    other = "sw_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    assert other != spec_faithful_derive("openinference", "t1", "s1", NON_ASCII_RECORD)


@pytest.mark.parametrize(
    ("expected", "source_key", "record"),
    [
        # Rule 2: the material is adapter, trace id, source key.
        ("sw_f3adffe8eba5ff98", "1", None),
        # Rule 3: the record's canonical digest joins the material.
        ("sw_202f2da54f3fb2c4", "s1", NON_ASCII_RECORD),
    ],
)
def test_a_derived_id_is_pinned_to_a_literal(expected, source_key, record):
    """The anchor. `canonical()` relabels derived ids to `n0`/`n1`, so no
    conformance expectation holds a real `sw_` string -- the whole corpus can
    stay green while the formula moves underneath it. These two literals are
    the only thing in the suite that cannot.
    """
    digest = None if record is None else record_digest(record)
    assert derive("openinference", "t1", source_key, digest) == expected
    assert spec_faithful_derive("openinference", "t1", source_key, record) == expected
