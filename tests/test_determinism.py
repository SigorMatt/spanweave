"""Determinism + losslessness gates (TASKS.md 0.6), each watched failing.

The four properties live in `tests/determinism.py`. Here they are pointed at
deliberately broken fakes, so that every one is seen failing for the reason it
exists.

**Not yet pointed at the real pipeline.** There is none at Phase 0 — no
reader, no builder, no serializer. Task 1.8 wires these same four checks to
`spanweave build` over the worked example, unchanged. Writing them first is
deliberate: a determinism property invented *after* the code it judges tends
to describe the code.
"""

import itertools
import json

import pytest

from tests import determinism

RECORDS = [
    {"span_id": "s0", "name": "agent.run"},
    {"span_id": "s1", "name": "llm.plan"},
    {"span_id": "s2", "name": "tool.lookup"},
]


def _graph_of(records):
    """A minimal well-behaved graph: every record kept, verbatim, sorted."""
    nodes = [{"id": r["span_id"], "raw": {"source": r}} for r in records]
    return {"nodes": sorted(nodes, key=lambda n: n["id"]), "diagnostics": []}


def _canonical_dumps(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


# --------------------------------------------------------------------------
# 1. Build twice -> byte-identical
# --------------------------------------------------------------------------


def test_repeatable_holds_for_a_pure_build():
    determinism.assert_repeatable(lambda: _canonical_dumps(_graph_of(RECORDS)))


def test_repeatable_fails_when_a_counter_leaks_into_the_output():
    counter = itertools.count()

    def build():
        return _canonical_dumps({"build": next(counter)})

    with pytest.raises(determinism.PropertyFailed, match="differs from build #1"):
        determinism.assert_repeatable(build)


# --------------------------------------------------------------------------
# 2. Shuffle the input -> byte-identical graph
# --------------------------------------------------------------------------


def test_order_independence_holds_when_the_builder_sorts():
    determinism.assert_order_independent(RECORDS, _graph_of)


def test_order_independence_fails_when_the_builder_trusts_file_order():
    def build(records):
        # The classic bug: nodes emitted in arrival order.
        return {"nodes": [{"id": r["span_id"]} for r in records], "diagnostics": []}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


def test_order_independence_fails_when_dict_insertion_order_decides_it():
    def build(records):
        # The subtler bug, and the one this project is most exposed to: a
        # group-by whose output is emitted in dict insertion order. Sorted
        # *within* each group, arbitrary *between* them.
        groups: dict[str, list[str]] = {}
        for record in records:
            groups.setdefault(record["name"].split(".")[0], []).append(
                record["span_id"]
            )
        return {"nodes": [{"group": g, "ids": sorted(i)} for g, i in groups.items()]}

    with pytest.raises(determinism.PropertyFailed, match="order MUST NOT be"):
        determinism.assert_order_independent(RECORDS, build)


# --------------------------------------------------------------------------
# 3. Every input record accounted for
# --------------------------------------------------------------------------


def test_losslessness_holds_when_every_record_is_a_node():
    determinism.assert_every_record_accounted_for(RECORDS, _graph_of(RECORDS))


def test_losslessness_holds_when_a_diagnostic_explains_the_gap():
    graph = {
        "nodes": [],
        "diagnostics": [{"code": "unknown_span_kind", "source": r} for r in RECORDS],
    }
    determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_on_a_silently_dropped_record():
    graph = _graph_of(RECORDS[:-1])
    with pytest.raises(determinism.PropertyFailed, match="silently dropped"):
        determinism.assert_every_record_accounted_for(RECORDS, graph)


def test_losslessness_fails_when_a_record_is_prettified_on_the_way_in():
    # Losslessness is verbatim-ness, not merely presence: a node whose raw
    # source has been normalized has lost the thing raw exists to keep.
    tidied = [{"span_id": r["span_id"], "name": r["name"].title()} for r in RECORDS]
    with pytest.raises(determinism.PropertyFailed):
        determinism.assert_every_record_accounted_for(RECORDS, _graph_of(tidied))


# --------------------------------------------------------------------------
# 4. The writer is canonical
# --------------------------------------------------------------------------


def test_canonical_writer_passes():
    determinism.assert_canonical_json(_canonical_dumps)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"sort_keys": False}, "not sorted"),
        ({"sort_keys": True, "separators": (", ", ": ")}, "not compact"),
        ({"sort_keys": True, "ensure_ascii": True}, "escaped"),
    ],
)
def test_canonical_writer_fails_on_a_planted_violation(kwargs, expected):
    settings = {"ensure_ascii": False, "separators": (",", ":"), **kwargs}

    def dumps(value):
        return (json.dumps(value, **settings) + "\n").encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match=expected):
        determinism.assert_canonical_json(dumps)


def test_canonical_writer_fails_without_a_trailing_newline():
    def dumps(value):
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    with pytest.raises(determinism.PropertyFailed, match="trailing newline"):
        determinism.assert_canonical_json(dumps)
