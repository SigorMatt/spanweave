"""Claims a document makes *about the tree*, checked against the tree.

`tests/test_docs.py` holds documents to the fixtures they **quote**. This file
holds them to what they **assert**: counts, directory contents, commands,
adapters, and the state of the world at the moment someone reads them.

The failure mode is one this project has now hit five times, and the fifth was
`TASKS.md` 3.7's key rename, which a commit message deferred *in writing* and
nobody came back for. A document states something true when written. The tree
moves. Nothing recomputes the sentence, because prose is not executable and
prose is exactly where nobody looks. The sentence is now false, and it stays
false until a stranger reads it -- which, at `0.9.x`, is the first time these
files are read by anyone who cannot check them against the tree.

**The remedy is a test, not a correction.** A corrected sentence is a sentence
that will expire again; a recomputed one cannot. That is not a slogan here --
it is the measured record: `ENVIRONMENT.md`'s stale `examples/` line was
noticed and deferred in **four** consecutive sessions (3.3, 3.4, 3.5, and 3.5's
follow-ups), each of which wrote down that it was stale rather than fixing it.
Four correct observations, zero repairs. `README.md`'s Status section survived
the whole of Phase 2 and Phase 3 describing Phase 2 as upcoming. A test would
have failed on the commit that made either one wrong.

So every correction made at `TASKS.md` 3.8 has a test here, or a recorded
reason why it cannot have one.

**What cannot be tested here, said plainly.** Whether prose *reads* correctly
to someone arriving cold is a human judgement and no assertion substitutes for
it. What is mechanizable is narrower and still worth the whole file: that a
number matches what it counts, that a named file exists, that a named command
runs, that a claimed emptiness is empty, and that a document does not promise
something the project has not done yet.
"""

from __future__ import annotations

import ast
import pathlib
import re

import spanweave
from spanweave.adapters import registered
from tests.conformance import CORPUS, adapter_backed, scenarios

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Directories that hold no document this project authored.
IGNORED_PARTS = frozenset(
    {".venv", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "out", "dist"}
)


def documents() -> list[pathlib.Path]:
    """Every markdown file this repository authors, in a stable order."""
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not IGNORED_PARTS & set(path.relative_to(ROOT).parts)
    )


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def section(markdown: str, heading: str) -> str:
    """The text under one `##` heading, up to the next one of any level."""
    start = markdown.index(heading)
    rest = markdown[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def fenced_lines(markdown: str) -> list[str]:
    """Lines inside ``` fences: the commands a reader would actually run."""
    lines: list[str] = []
    inside = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def code_spans(markdown: str) -> list[str]:
    """Fenced lines plus inline `code`, which is where prose names a command.

    **Bound, stated rather than silently carried:** inline spans are matched
    line by line, so a span wrapped across a line break is invisible here.
    Widening it was tried at `TASKS.md` 3.10 and reverted the same hour: over
    a 460 KB file of blockquoted records, pairing backticks across lines makes
    a stray one swallow paragraphs, and "make the" and "make it" arrive as
    targets. A scanner that has to be loosened to stay quiet is a scanner on
    its way to being switched off, so the narrow version stays and the gap is
    written down.

    Nothing depends on the gap being closed: the one check that needed a
    wrapped span -- the Install section's `make` targets -- reads the raw
    section against the Makefile's closed set of targets instead, which is
    precise because the candidates are enumerable.
    """
    spans = fenced_lines(markdown)
    inside = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if not inside:
            spans.extend(re.findall(r"`([^`]+)`", line))
    return spans


# -- The install line that must not exist yet ------------------------------
#
# `AGENT.md` and `TASKS.md` 3.10 both say it: no document gains a
# `pip install spanweave` line until the publish has happened. A README
# promising an install that 404s is the first thing a stranger tries, and it is
# this project's own recurring failure -- a claim written ahead of its
# condition -- shipped to someone who cannot check it.

INDEX_INSTALL = re.compile(
    r"\b(?:pip|uv pip|pipx)\s+install\s+(?:-[^\s]+\s+)*spanweave(?![-/.\w])"
    r"|\buv\s+add\s+spanweave\b"
    r"|\bpoetry\s+add\s+spanweave\b"
)

#: The checkbox that says the publish happened. `TASKS.md` 3.10 is the only
#: place in the repository that records it, and ticking it is the same act as
#: making the install line true -- which is why the permission is keyed to it
#: rather than to a flag someone would have to remember to flip.
PUBLISH_TASK = re.compile(r"^- \[( |x)\] \*\*3\.10 Publish", re.M)


def publish_has_happened() -> bool:
    match = PUBLISH_TASK.search(read("TASKS.md"))
    assert match is not None, (
        "TASKS.md no longer contains the 3.10 publish checkbox this test reads. "
        "It is the repository's only record of whether `pip install spanweave` "
        "resolves; without it this test passes vacuously."
    )
    return match.group(1) == "x"


def test_no_document_promises_an_install_that_does_not_resolve_yet():
    """Scanned inside code fences only, and the distinction is load-bearing.

    A fenced line is a command a reader will paste. An inline `pip install
    spanweave` in prose is usually this rule *being stated* -- `AGENT.md`,
    `ROADMAP.md`, `TASKS.md` and `README.md` all mention the string in order to
    forbid or defer it, and a test that could not tell those apart would have
    to be switched off.
    """
    offenders = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in documents()
        for line in fenced_lines(path.read_text(encoding="utf-8"))
        if INDEX_INSTALL.search(line)
    ]
    if publish_has_happened():
        return
    assert not offenders, (
        "a document offers an install from a package index, but TASKS.md 3.10 "
        "(the publish) is still unchecked, so the command does not resolve:\n"
        + "\n".join(offenders)
    )


def test_the_readme_says_what_is_true_of_the_index_install_in_both_directions():
    """The guard runs **both** ways, which it did not when 3.8 wrote it.

    3.8 keyed the prohibition to `TASKS.md` 3.10's checkbox: no index install
    line until the publish has happened. Preparing 3.10 found the other half
    missing. The README currently states *"`spanweave` is not on PyPI yet"* --
    true today, and **false the second the upload succeeds**. Nothing required
    that sentence to go, so the publish would have left the front door saying
    the package cannot be installed the way it now can. That is this project's
    recurring failure with the polarity reversed: a claim written ahead of its
    condition, rotting at the moment the condition arrives.

    Worse, 3.8's own `test_the_readme_has_an_install_section_naming_the_version`
    asserted the sentence was *present*, unconditionally -- so a human doing
    the right thing after publishing would have hit a red suite and had to edit
    a test to describe reality. A gate that must be edited to allow the correct
    change is a gate on its way to being deleted.

    So the checkbox now drives both directions, and ticking it is still the
    same act as making the line true.
    """
    install = section(read("README.md"), "\n## Install")
    published = publish_has_happened()
    if not published:
        assert "not on PyPI yet" in install, (
            "TASKS.md 3.10 is unchecked, so the README must say the index "
            "install does not exist yet -- an omission a reader routes around "
            "by guessing the index name"
        )
        return
    assert "not on PyPI yet" not in install, (
        "TASKS.md 3.10 is checked, so spanweave IS on PyPI and the README's "
        "Install section still says it is not. Publishing without this edit "
        "ships a false front door."
    )
    assert any(INDEX_INSTALL.search(line) for line in fenced_lines(install)), (
        "TASKS.md 3.10 is checked, so the README must offer the index install "
        "a reader will actually use, not only the checkout and wheel paths"
    )
    # The step 4 cold read's one real finding, carried here so it cannot go
    # missing the way `a953a1f`'s written-down deferral did (3.7). Once the
    # package is on an index, most readers of this section have a wheel and no
    # Makefile, so a `make` target named here sends them to a command they
    # cannot run. Development keeps its targets; it is written for a checkout.
    targets = makefile_targets()
    named = {
        match.group(1)
        for match in re.finditer(r"\bmake\s+([a-z][a-z-]+)", " ".join(install.split()))
        if match.group(1) in targets
    }
    assert not named, (
        f"TASKS.md 3.10 is checked, so readers of the Install section arrive "
        f"from a package index with no Makefile — but it still names "
        f"{sorted(named)}. Say what it means for them, or say nothing; the "
        f"target belongs under Development (TASKS.md 3.10, step 8)."
    )


def test_the_forbidden_install_matcher_actually_matches():
    # Non-vacuity. A guard that cannot fire is worse than no guard, because it
    # reads as coverage.
    for planted in (
        "$ pip install spanweave",
        "uv pip install spanweave",
        "pip install --upgrade spanweave",
        "uv add spanweave",
        "poetry add spanweave",
    ):
        assert INDEX_INSTALL.search(planted), planted
    for allowed in (
        "pip install .",
        "pip install dist/spanweave-0.9.0-py3-none-any.whl",
        "pip install -e .",
        "uv sync --extra dev",
    ):
        assert not INDEX_INSTALL.search(allowed), allowed


# -- The install section that must exist -----------------------------------


def test_the_readme_has_an_install_section_naming_the_version_it_ships():
    install = section(read("README.md"), "\n## Install")
    wheel = f"spanweave-{spanweave.__version__}-py3-none-any.whl"
    assert wheel in install, (
        f"README's Install section does not name {wheel}. The wheel filename "
        f"carries the version, so a version bump that forgets the README makes "
        f"the documented command fail on a file that does not exist."
    )
    assert "pip install ." in install
    # Whether the index install exists yet is the *other* test's business, in
    # both directions. Asserting the "not on PyPI yet" sentence here as well
    # would make this one go red at the publish, for a document that had just
    # been corrected -- see
    # test_the_readme_says_what_is_true_of_the_index_install_in_both_directions.


# -- Commands that must exist ----------------------------------------------


def makefile_targets() -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"^([A-Za-z][A-Za-z0-9_-]*):", read("Makefile"), re.M)
    }


def test_every_make_target_a_document_names_exists():
    targets = makefile_targets()
    assert {"check", "conformance"} <= targets, "Makefile parse produced nothing"
    named: dict[str, set[str]] = {}
    for path in documents():
        for span in code_spans(path.read_text(encoding="utf-8")):
            for match in re.finditer(r"\bmake\s+([a-z][a-z-]+)", span):
                named.setdefault(match.group(1), set()).add(str(path.relative_to(ROOT)))
    assert named, "no document names a make target; the scan found nothing"
    missing = {
        target: sorted(where)
        for target, where in named.items()
        if target not in targets
    }
    assert not missing, f"documents name make targets that do not exist: {missing}"


def test_every_cli_subcommand_a_document_invokes_exists():
    """Fenced lines only, unlike the make scan above, and for a stated reason.

    Prose names commands that deliberately do not exist: `SPEC.md` §7 and
    `OPEN_QUESTIONS.md` §4 both discuss a `spanweave split` that is **deferred
    by decision**. Naming an unbuilt command while saying it is unbuilt is
    honest; putting it in a fenced block a reader pastes is not.
    """
    from spanweave.cli import COMMANDS

    subcommands = set(COMMANDS)
    assert subcommands, "no subcommands found; the CLI dispatch table is empty"

    invoked: dict[str, set[str]] = {}
    for path in documents():
        for line in fenced_lines(path.read_text(encoding="utf-8")):
            for match in re.finditer(r"(?:^|\$\s*)spanweave\s+([a-z][a-z-]+)", line):
                invoked.setdefault(match.group(1), set()).add(
                    str(path.relative_to(ROOT))
                )
    assert invoked, "no document invokes the CLI; the scan found nothing"
    missing = {
        name: sorted(where)
        for name, where in invoked.items()
        if name not in subcommands
    }
    assert not missing, f"documents invoke subcommands that do not exist: {missing}"


# -- The document map, held to the documents -------------------------------


def test_the_readme_document_table_lists_every_document_and_no_ghosts():
    table = section(read("README.md"), "\n## Documents")
    listed = set(re.findall(r"^\| `([^`]+\.md)` \|", table, re.M))
    assert listed, "the README's Documents table parsed to nothing"
    on_disk = {path.name for path in ROOT.glob("*.md")} - {"README.md"}
    assert listed == on_disk, (
        "the README's Documents table has drifted from the repository root.\n"
        f"  listed but absent: {sorted(listed - on_disk)}\n"
        f"  present but unlisted: {sorted(on_disk - listed)}"
    )


# -- Status: what ships, in the present tense ------------------------------


def test_the_readme_status_names_every_adapter_that_ships():
    status = section(read("README.md"), "\n## Status")
    for adapter in registered():
        assert adapter.id in status, (
            f"the README's Status section does not mention the {adapter.id!r} "
            f"adapter, which is registered and ships"
        )


def test_the_examples_use_only_the_public_api_the_readme_claims():
    """Status says the consumers read fixtures "through the public API and
    nothing else". That is a claim about code, so it is checked against code.

    `CLAUDE.md`: the public API is exactly what `spanweave/__init__.py`
    exports. An example that reaches past it is either a finding about the API
    (which is how the error types got exported at all -- `TASKS.md` 2.4's F4)
    or a shortcut, and the two look identical until someone checks.
    """
    public = set(spanweave.__all__)
    assert public, "spanweave exports nothing; the introspection broke"
    offenders: list[str] = []
    for source in sorted((ROOT / "examples").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for statement in ast.walk(tree):
            if isinstance(statement, ast.ImportFrom):
                module = statement.module or ""
                if module == "spanweave":
                    for alias in statement.names:
                        if alias.name not in public:
                            offenders.append(f"{source.name}: {alias.name}")
                elif module.startswith("spanweave."):
                    offenders.append(f"{source.name}: from {module}")
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name.startswith("spanweave."):
                        offenders.append(f"{source.name}: import {alias.name}")
    assert not offenders, (
        "an example reaches past the public API, which the README says none "
        f"of them does: {offenders}"
    )


def test_the_readme_status_is_not_written_in_phase_numbers():
    """The rule that would have caught the section this task found stale.

    Status said *"Phase 1 is the vertical slice ... A second adapter ... is
    Phase 2"* for the whole of Phases 2 and 3. It was true when written. A
    phase number is a promise with an expiry date and no alarm: internal
    sequencing, meaningless to a stranger, and guaranteed to age. The Status
    section states what exists, in the present tense, or it is wrong again in
    a month.
    """
    status = section(read("README.md"), "\n## Status")
    assert "Phase" not in status, (
        "the README's Status section is written in phase numbers again. State "
        "what exists today; phase sequencing lives in ROADMAP.md, which is for "
        "us, not for a reader who just installed this."
    )


# -- Counts, recomputed rather than reread ---------------------------------


def corpus_counts() -> tuple[int, int, int, int]:
    """(scenarios, rendered in two dialects, rendered in one, declaring `name`)."""
    backed = adapter_backed()
    found = scenarios()
    cross = [
        scenario
        for scenario in found
        if len([p for p in scenario.dialects if p.stem in backed]) > 1
    ]
    declaring = [
        scenario
        for scenario in cross
        if (scenario.path / "expected/comparison.json").exists()
        and "name"
        in (scenario.path / "expected/comparison.json").read_text(encoding="utf-8")
    ]
    return len(found), len(cross), len(found) - len(cross), len(declaring)


def test_the_readme_conformance_numbers_are_the_corpus_s_numbers():
    """Every figure in the section carrying the library's central claim.

    The claim this section makes is the reason the project exists, so the
    numbers qualifying it are the ones a reader is least able to check and
    most entitled to trust. The section previously said every scenario is
    expressed in multiple dialects; four are not, each for a declared reason.
    """
    total, cross, single, declaring = corpus_counts()
    assert total > 0 and cross > 0 and single > 0 and declaring > 0
    text = section(read("README.md"), "\n## Conformance")
    for claim in (
        f"holds\n**{total}** scenarios",
        f"**{cross}** are rendered in both dialects",
        f"The other **{single}** are rendered in one",
        f"**{declaring} of those {cross} cross-dialect scenarios declare it**",
    ):
        flattened = claim.replace("\n", " ")
        assert flattened in " ".join(text.split()), (
            f"README's Conformance section does not state {flattened!r}; the "
            f"corpus says it should"
        )


def test_the_quickstart_warns_where_it_uses_the_field_the_corpus_cannot_check():
    """The bound has to be where the reader is, not only where it is true.

    `nodes[].name` is the one field the cross-dialect comparison sets aside
    (`CONTRACTS.md` F-B, `FIXTURES.md` §4.4), and 3.2's follow-ups propagated
    that bound to six places. Every one of them is a place a reader arrives at
    *after* deciding what to do -- and the README's opening example prints
    `node.name` as the very first thing it does, roughly two hundred lines
    above the section that qualifies it. A stranger who copies the block and
    matches on `name` across two dialects has been told nothing.

    So: if the quickstart uses the field, the quickstart carries the pointer.
    """
    readme = read("README.md")
    quickstart = readme[: readme.index("\n## Install")]
    if "node.name" not in quickstart:
        return
    assert "corpus does not compare it" in quickstart, (
        "the README's opening example prints `node.name` without pointing at "
        "the Conformance section that bounds it"
    )


def test_every_scenario_rendered_in_one_dialect_declares_why():
    """The claim behind the number: silence is a failure (`FIXTURES.md` §4.3).

    "4 are rendered in one dialect" is only honest if none of the four is an
    adapter nobody got round to. That is what `coverage.json` is for, and the
    README now tells a reader it exists.
    """
    backed = adapter_backed()
    for scenario in scenarios():
        rendered = {p.stem for p in scenario.dialects} & backed
        for dialect in backed - rendered:
            reason = scenario.declared_unrenderable(dialect)
            assert reason is not None, (
                f"{scenario.name} has no {dialect} rendering and no declaration"
            )


def test_the_corpus_readme_names_every_scenario_it_holds():
    """A hand-maintained list beside the directory it lists.

    `fixtures/conformance/README.md` tells a reader to read the pytest header
    rather than a list "which would go stale" -- and then carries a list. It is
    complete today. Nothing recomputed it, which is the same shape as every
    other claim in this file, so it is recomputed here.

    Only one direction is asserted: every scenario must appear. The reverse
    would trip over ordinary backticked prose in the same section, and a
    guard that has to be loosened to stay quiet is a guard on its way to being
    deleted.
    """
    text = (CORPUS / "README.md").read_text(encoding="utf-8")
    listing = text[text.index("## Scenarios") :]
    on_disk = sorted(path.name for path in CORPUS.iterdir() if path.is_dir())
    assert on_disk, "the corpus holds no scenario; the scan found nothing"
    missing = [name for name in on_disk if f"`{name}`" not in listing]
    assert not missing, (
        f"fixtures/conformance/README.md does not name {missing}, which the "
        f"corpus holds"
    )


# -- fixtures/captured/, whose whole subject is provenance ------------------


NUMBER_WORDS = {
    0: "none",
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
}


def test_the_captured_readme_does_not_claim_an_emptiness_that_ended():
    """It said *"Currently empty -- the first one lands at `TASKS.md` 1.9"*.

    Three traces have landed since. The sentence was corrected when the third
    was promoted; nothing would have caught it if it had not been. A stale
    claim in the one directory whose subject is provenance is worse than a
    stale claim anywhere else, because provenance is the thing that directory
    is asking to be believed about.
    """
    captured = ROOT / "fixtures/captured"
    traces = sorted(captured.glob("*.jsonl"))
    text = (captured / "README.md").read_text(encoding="utf-8")

    if traces:
        for phrase in ("Currently empty", "currently empty", "is empty"):
            assert phrase not in text, (
                f"fixtures/captured/README.md claims {phrase!r} while holding "
                f"{len(traces)} trace(s)"
            )
        assert f"{NUMBER_WORDS[len(traces)]} are present" in text, (
            f"fixtures/captured/README.md does not say "
            f"{NUMBER_WORDS[len(traces)]!r} are present; there are {len(traces)}"
        )
    for trace in traces:
        assert trace.name in text, f"{trace.name} is not named in the README"
        provenance = trace.with_suffix(".provenance.md")
        assert provenance.exists(), (
            f"{trace.name} has no provenance file, which rule 2 of that same "
            f"README requires"
        )


# -- ENVIRONMENT.md's repo layout, held to the repo -------------------------


def test_the_environment_examples_line_names_every_example():
    """The line four consecutive sessions noticed was stale and did not fix.

    It read *"the confirmatory ones in Phase 3"* from before either existed
    until after both did.
    """
    layout = section(read("ENVIRONMENT.md"), "\n## Repo layout")
    start = layout.index("- `examples/`")
    entry = layout[start : layout.index("\n- ", start + 1)]
    present = {
        path.name
        for path in (ROOT / "examples").iterdir()
        if path.is_dir() and not path.name.startswith("_")
    }
    assert present, "examples/ holds no consumer; the scan found nothing"
    for name in sorted(present):
        assert name in entry, (
            f"ENVIRONMENT.md's examples/ entry does not name {name!r}. That "
            f"entry is the repo layout contract; an example it omits is an "
            f"example nobody agreed to."
        )


# -- The quantifier that expired, and the documents that carried it ---------


def usage_extra_over_the_committed_corpus() -> dict[str, dict[str, int]]:
    """Every node with a non-empty `Usage.extra`, keyed by node id."""
    found: dict[str, dict[str, int]] = {}
    sources = sorted((ROOT / "fixtures/captured").glob("*.jsonl")) + sorted(
        CORPUS.glob("*/dialects/*.jsonl")
    )
    for source in sources:
        try:
            graph = spanweave.build(source)
        except spanweave.SpanweaveError:
            # `duplicate_span_ids` refuses by design (SPEC.md §3.6). A refusal
            # is a scenario, not a gap in this sweep.
            continue
        for node in graph.nodes():
            if node.usage is not None and node.usage.extra:
                found[node.id] = dict(node.usage.extra)
    return found


#: The sentence that expired, in both the phrasings it shipped in. Whitespace
#: is normalized before matching so a reflow cannot hide it.
RETIRED_QUANTIFIER = re.compile(
    r"`\{\}` on every node of every (?:conformance rendering and every "
    r"captured trace|fixture in the repository)"
)

#: A correction has to be able to quote what it corrected, or the record of
#: what went wrong is lost with the sentence. These are the markers that turn
#: an occurrence into a quotation rather than a claim.
CORRECTION_MARKERS = (
    "previously\nread",
    "previously read",
    "Corrected from",
    "Corrected at",
    "used to read",
    "said the opposite",
)


def retired_quantifier_occurrences(text: str) -> list[int]:
    flat = " ".join(text.split())
    return [match.start() for match in RETIRED_QUANTIFIER.finditer(flat)]


def quotes_rather_than_asserts(text: str, start: int) -> bool:
    flat = " ".join(text.split())
    window = flat[max(0, start - 400) : start]
    return any(" ".join(m.split()) in window for m in CORRECTION_MARKERS)


def test_the_documents_no_longer_claim_usage_extra_is_always_empty():
    """`CONTRACTS.md` F-C and `ROADMAP.md` Phase 4 row 5, corrected at 3.8.

    Both stated a corpus-wide quantifier -- *"`{}` on every node of every
    fixture in the repository"* -- that was true when written and expired when
    a captured trace landed carrying `llm.token_count.prompt_details.cache_read`.
    3.4's consumer found it (F-1) and, being a `[consumers]` session, correctly
    left the edit to whoever owned those documents. Nobody did: `[contract]`
    had no unchecked task left. So it is fixed here, and held here.
    """
    populated = usage_extra_over_the_committed_corpus()
    assert populated, (
        "no node in the committed corpus carries a non-empty Usage.extra. If "
        "that is now true, both documents need correcting in the other "
        "direction -- and this test is why you know."
    )
    values = sorted(value for extra in populated.values() for value in extra.values())
    for name in ("CONTRACTS.md", "ROADMAP.md"):
        text = read(name)
        for value in values:
            assert str(value) in text, (
                f"{name} does not carry the measured value {value}; the "
                f"sentence describing Usage.extra has drifted from the corpus"
            )
        for start in retired_quantifier_occurrences(text):
            assert quotes_rather_than_asserts(text, start), (
                f"{name} asserts the retired quantifier again at offset "
                f"{start}. It may appear only as a quotation of what it "
                f"replaced -- which is how a correction stays legible without "
                f"becoming a fresh claim."
            )
