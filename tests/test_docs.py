"""Documents that quote a fixture must be checkable against it.

`FIXTURES.md` §7 quotes the `llm_tool_llm` rendering and then makes claims
about the graph it produces. Nothing checked either, so when the fixture was
corrected against a captured trace the document silently kept the old
rendering — and kept asserting, underneath it, a restraint the telemetry had
never asked for. A document that quotes an artifact and drifts from it is a
document that will eventually lie, and prose is exactly where nobody looks.

`tests/test_codes.py` established the pattern for `SPEC.md`'s code tables:
parse the doc, compare to the artifact, fail on drift. This is the same
pattern for quoted fixture content.
"""

import json
import pathlib
import re

import spanweave
from tests.conformance import CORPUS

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES_MD = (ROOT / "FIXTURES.md").read_text(encoding="utf-8")
WORKED = CORPUS / "llm_tool_llm/dialects/openinference.jsonl"

BLOCK = re.compile(r"```jsonl\n(.*?)```", re.S)


def quoted_blocks(text: str) -> list[str]:
    return [match.group(1) for match in BLOCK.finditer(text)]


def test_the_worked_example_is_the_fixture_verbatim():
    blocks = quoted_blocks(FIXTURES_MD)
    assert len(blocks) == 1, "a new quoted block needs a check of its own"
    assert blocks[0].rstrip("\n") == WORKED.read_text(encoding="utf-8").rstrip("\n")


def test_every_quoted_jsonl_block_in_the_docs_is_a_real_fixture():
    # A block that matches no fixture is either drift or an invention, and
    # both are the failure this file exists for.
    renderings = {
        path.read_text(encoding="utf-8").strip()
        for path in CORPUS.glob("*/dialects/*.jsonl")
    }
    for markdown in sorted(ROOT.glob("*.md")):
        for block in quoted_blocks(markdown.read_text(encoding="utf-8")):
            assert block.strip() in renderings, f"{markdown.name} quotes no fixture"


def worked_example_section() -> str:
    start = FIXTURES_MD.index("## 7. Worked example")
    return FIXTURES_MD[start : FIXTURES_MD.index("## 8.", start)]


def test_the_edges_the_document_claims_are_the_edges_that_are_built():
    section = worked_example_section()
    graph = spanweave.build(WORKED)
    for edge in graph.edges():
        # Each edge must be findable in the prose by kind, warrant and basis.
        claim = f"`{edge.kind.value}` {edge.warrant.value}, basis `{edge.basis}`"
        assert claim in section, f"§7 does not mention {claim}"
    # And the prose must not claim a kind the graph does not have.
    built = {edge.kind.value for edge in graph.edges()}
    for kind in ("parent", "call_result", "data", "link", "temporal"):
        if f"- `{kind}` " in section:
            assert kind in built, f"§7 claims a {kind} edge the graph does not build"


def test_the_diagnostics_the_document_claims_are_the_ones_produced():
    section = worked_example_section()
    graph = spanweave.build(WORKED)
    codes = {d.code for d in graph.diagnostics}
    if codes:
        for code in codes:
            assert code in section, f"§7 does not mention the {code} diagnostic"
        assert "**Diagnostics:** none" not in section
    else:
        assert "**Diagnostics:** none" in section


def test_the_attribute_counts_the_document_implies_match_the_fixture():
    # The drift that actually happened: the document kept a 6-attribute s3
    # while the fixture grew to 19. Counting is the cheapest thing that would
    # have caught it.
    quoted = [
        json.loads(line)
        for line in quoted_blocks(FIXTURES_MD)[0].splitlines()
        if line.strip()
    ]
    actual = [
        json.loads(line)
        for line in WORKED.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [len(r["attributes"]) for r in quoted] == [
        len(r["attributes"]) for r in actual
    ]


def test_the_document_does_not_still_claim_the_telemetry_stated_nothing():
    # The specific false sentence, kept as a tripwire: the telemetry DID
    # declare that the tool result reached the second LLM call, and the graph
    # now says so (SPEC.md §4.2.1).
    section = worked_example_section()
    assert "The\ntelemetry did not state it" not in section
    assert "data" in section
