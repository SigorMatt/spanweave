"""Make the conformance suite's transitional gap loud (`TASKS.md` 2.7).

Between `TASKS.md` 2.8 and 2.9 the corpus holds renderings of a dialect no
registered adapter can read. Those renderings are skipped, and a skip is the
one way this suite can stop checking something without going red — so it is
reported here, in the pytest header, on **every** run rather than only under
`-v`. The alternative is a corpus whose coverage rots one file at a time with
nothing saying so.

2.13 retires the whole mechanism, this file included.
"""

from tests.conformance import DIALECTS, adapter_backed, scenarios, unsupported


def pytest_report_header(config):
    del config
    backed = sorted(adapter_backed())
    skipped = unsupported(scenarios())
    lines = [f"conformance dialects: declared={list(DIALECTS)} adapter-backed={backed}"]
    if skipped:
        by_dialect: dict[str, list[str]] = {}
        for rendering in skipped:
            by_dialect.setdefault(rendering.dialect, []).append(rendering.scenario.name)
        for dialect in sorted(by_dialect):
            names = ", ".join(sorted(by_dialect[dialect]))
            lines.append(
                f"conformance SKIPPING {len(by_dialect[dialect])} rendering(s) of "
                f"{dialect!r} -- no registered adapter reads it: {names}"
            )
    else:
        lines.append("conformance skipping nothing: every rendering has an adapter")
    return lines
