"""Corpus coverage, in the pytest header, on every run.

This began at `TASKS.md` 2.7 as a report on a **transitional** state: between
2.8 and 2.13 the corpus held renderings of a dialect no registered adapter
could read, and a skip is the one way a suite can stop checking something
without going red.

2.13 closed that state and deleted the declaration that held it. This file is
deliberately **not** deleted with it. What it reports is no longer a
transition — it is standing coverage, and the two things it now says are worth
seeing on every run:

* how much the corpus actually compares, so "the cross-dialect claim" cannot
  quietly become a claim about one dialect;
* whether anything is being skipped, which after 2.13 would be a defect rather
  than a known condition.

Reported here rather than under `-v` because a number nobody sees is a number
nobody checks.
"""

from tests.conformance import (
    DIALECTS,
    adapter_backed,
    renderings,
    scenarios,
    unsupported,
)


def pytest_report_header(config):
    del config
    found = scenarios()
    backed = sorted(adapter_backed())
    lines = [f"conformance dialects: declared={list(DIALECTS)} adapter-backed={backed}"]

    per_dialect = {}
    for rendering in renderings(found):
        per_dialect.setdefault(rendering.dialect, []).append(rendering)
    counted = ", ".join(
        f"{dialect} {len(per_dialect[dialect])}" for dialect in sorted(per_dialect)
    )
    both = sum(
        1
        for scenario in found
        if len([p for p in scenario.dialects if p.stem in adapter_backed()]) > 1
    )
    declared = sum(
        1
        for scenario in found
        for dialect in DIALECTS
        if scenario.declared_unrenderable(dialect) is not None
    )
    lines.append(
        f"conformance coverage: {len(found)} scenarios, renderings: {counted}; "
        f"{both} compared across dialects; {declared} declared unrenderable"
    )

    skipped = unsupported(found)
    if skipped:
        by_dialect: dict[str, list[str]] = {}
        for rendering in skipped:
            by_dialect.setdefault(rendering.dialect, []).append(rendering.scenario.name)
        for dialect in sorted(by_dialect):
            names = ", ".join(sorted(by_dialect[dialect]))
            lines.append(
                f"conformance SKIPPING {len(by_dialect[dialect])} rendering(s) of "
                f"{dialect!r} -- no registered adapter reads it: {names}. Since "
                f"TASKS.md 2.13 this is a DEFECT, not a transition"
            )
    else:
        lines.append("conformance skipping nothing: every rendering has an adapter")
    return lines
