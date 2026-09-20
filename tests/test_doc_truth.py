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
import itertools
import json
import pathlib
import re
import shlex
from dataclasses import dataclass

import pytest

import spanweave
from spanweave.adapters import registered
from tests.conformance import CORPUS, adapter_backed, dialect_parts, scenarios
from tests.corpus_census import (
    FRACTIONAL_FIGURES,
    Census,
    Printed,
    census,
    figure_names,
    figures,
    fractional_figure_names,
    render,
    report,
)

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
    """`durable_documents()`, not `documents()`, and for the stated reason.

    The exclusion `durable_documents()` applies is that `reviews/` and
    `patches/` hold text copied **verbatim**, so what they say is a record of
    a moment rather than a claim made now. That argument is about the text,
    not about the shape of the thing it names, so it covers a make target
    exactly as it covers a path: the cold review of the Qodo round
    (`reviews/2026-09-20-qodo.md`) says what it *did not* check, and one of
    the things it names is a `demo` target this Makefile has never had.
    Archiving that sentence is reporting what a reviewer wrote. Editing it to
    make a gate green would be forging a review, and leaving the gate reading
    it would fail every clean checkout from the moment the file was tracked.

    The exclusion stays narrow on purpose. It is two directories, both of
    which exist to hold quoted text, and every other document -- `README.md`,
    `SPEC.md`, `TASKS.md`, `CONTRIBUTING.md`, the Makefile's own neighbours --
    is still scanned, so a target that does not exist, named by anything that
    is speaking for the project today, is still red.
    """
    targets = makefile_targets()
    assert {"check", "conformance"} <= targets, "Makefile parse produced nothing"
    named: dict[str, set[str]] = {}
    for path in durable_documents():
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


# -- The durable record, held to the tracked tree --------------------------
#
# `TASKS.md`'s September 2026 audit section cited its cold review as
# `patches/REVIEW-2026-09-10.md`, and `patches/` is untracked scratch: a clean
# checkout had the citation and not the review, and the two concerns that
# lived only in that file were lost with it. The general rule is the one this
# encodes -- a document written to outlive a work series may only point at
# files the repository actually carries.

#: Directories that archive text verbatim, and so quote paths as they stood.
VERBATIM_PARTS = frozenset({"patches", "reviews"})


def durable_documents() -> list[pathlib.Path]:
    """Documents that outlive a series, so their citations must resolve later.

    One exclusion, because the excluded text is a record of a moment rather
    than a claim made now: `reviews/` and `patches/` hold cold reviews copied
    verbatim, and a review that says a file was untracked *when it was read*
    is reporting, not citing.

    A second exclusion stood here while the September 2026 audit-fix series
    ran -- `WORKPLAN.md`, a series' own execution state, which owned
    `patches/` as its scratch drop and was written to be deleted at series
    close. That is exactly why nothing durable was allowed to depend on it,
    and it is gone: the series closed and the file went with it (`TASKS.md`,
    *September 2026 audit*). It has gone four times now, coming back for
    each reopening, so the exclusion is a fixture of a **series**, not of a
    file: a future series' plan file needs it back.
    """
    return [
        path
        for path in documents()
        if not VERBATIM_PARTS & set(path.relative_to(ROOT).parts)
    ]


def test_a_durable_document_cites_no_untracked_scratch_path():
    """A *file* under `patches/`, not the directory's name.

    Saying that a review was written to `patches/` and is therefore absent
    from a clean checkout is the explanation; `patches/REVIEW-2026-09-10.md`
    offered as the full text is the citation that does not resolve.
    """
    scratch: dict[str, set[str]] = {}
    for path in durable_documents():
        for span in code_spans(path.read_text(encoding="utf-8")):
            for match in re.finditer(r"\bpatches/\S+", span):
                scratch.setdefault(match.group(0), set()).add(
                    str(path.relative_to(ROOT))
                )
    assert not scratch, (
        "a document meant to outlive its work series points into `patches/`, "
        "which is untracked scratch and absent from a clean checkout. Copy "
        "the file into `reviews/` and cite it there.\n"
        f"  {scratch}"
    )


def test_every_review_a_document_cites_is_in_the_repository():
    cited: dict[str, set[str]] = {}
    for path in durable_documents():
        for span in code_spans(path.read_text(encoding="utf-8")):
            for match in re.finditer(r"\breviews/[A-Za-z0-9._-]+\.md\b", span):
                cited.setdefault(match.group(0), set()).add(str(path.relative_to(ROOT)))
    assert cited, "no document cites a review; the scan found nothing"
    missing = {
        review: sorted(where)
        for review, where in cited.items()
        if not (ROOT / review).is_file()
    }
    assert not missing, f"documents cite reviews that are not in the tree: {missing}"


# -- `CONTRACTS.md` against `SPEC.md` --------------------------------------
#
# `CONTRACTS.md` is an enumeration, not a set of contracts: each row records
# what *states* and what *asserts* one serialized field, and says `unstated,
# unmeasured` where nothing does (`AGENT.md`). A row is therefore a claim
# about `SPEC.md`, and it goes stale the moment `SPEC.md` states the field --
# silently, because the inventory is prose and the spec is prose.
#
# It did. `e6394e2` added the paragraph to `SPEC.md` §3.7 that states what
# `diagnostics[].adapter` means, and added tests asserting it, while
# `CONTRACTS.md` went on saying "nothing states it, nothing asserts it, and
# the value can be invented at the boundary with the suite green". The cold
# review of that commit found it by reading both files; nothing in the suite
# could have (`reviews/2026-09-20-qodo.md`, T6).

#: A paragraph that opens by naming a field in a code span is `SPEC.md`
#: stating that field: "`adapter` names whose records...", "`basis` records
#: what rule made it". Bold is allowed around it -- the spec emphasizes some
#: of these -- and nothing else is: a name inside a sentence, in a type
#: sketch, or in a table cell is the field being *mentioned*, which is not
#: the same act.
SPEC_STATEMENT = re.compile(
    r"^(?:\*\*)?`([A-Za-z_][A-Za-z0-9_.]*)`(?:\*\*)?\s+[a-zA-Z]", re.M
)

#: What must stand beside a row that keeps saying `unstated` about a field
#: the spec states: a note saying when that stopped being true. It is beside
#: the row and not in it because the Status cell is derived from the row's own
#: two cells by `tests/test_contracts.py`, which is a different guard and a
#: good one -- text appended to that cell makes it stop following from them.
STATED_SINCE = "stated by SPEC §"


def spec_stated_fields() -> set[str]:
    """Field names `SPEC.md` opens a paragraph to state."""
    return {match.group(1) for match in SPEC_STATEMENT.finditer(read("SPEC.md"))}


def contracts_noted_fields() -> set[str]:
    """Fields `CONTRACTS.md` carries a `STATED_SINCE` note about.

    Read per block, where a block is a paragraph or one `- ` bullet, so a note
    counts for the field it actually names and not for its neighbour.
    """
    blocks = re.split(r"\n\s*\n|\n(?=- )", read("CONTRACTS.md"))
    noted: set[str] = set()
    for block in blocks:
        if STATED_SINCE not in block:
            continue
        noted.update(re.findall(r"`([A-Za-z_][A-Za-z0-9_.\[\]]*)`", block))
    return noted


def contracts_rows() -> list[tuple[str, str]]:
    """Each `CONTRACTS.md` inventory row as `(field path, status cell)`."""
    rows = []
    for line in read("CONTRACTS.md").splitlines():
        # `str \| None` is one cell: in a GitHub table a pipe inside a cell is
        # escaped, and splitting on it unescaped turns a five-column row into
        # a six-column one -- which is how the first spelling of this check
        # read the `diagnostics[].adapter` row as no row at all and passed.
        cells = [cell.strip() for cell in line.replace(r"\|", "\x00").split("|")]
        if len(cells) == 7 and cells[1].startswith("`") and cells[1].endswith("`"):
            rows.append((cells[1].strip("`"), cells[5]))
    return rows


def test_no_contracts_row_calls_a_field_unstated_that_the_spec_now_states():
    """The check the `diagnostics[].adapter` drift needed, kept narrow.

    It reads the two documents against each other rather than either against
    itself, which is the only way this class of drift is visible: both files
    were internally consistent the whole time.

    It does **not** demand the row be rewritten. A row's `Stated` and
    `Asserted` columns are a *measurement*, taken at `TASKS.md` 3.2 and a
    human's to re-run; overwriting one because the spec moved would destroy
    the dated reading rather than correct it. What it demands is a note
    naming the spec section and the commit, standing beside the row -- beside
    and not inside, because `tests/test_contracts.py` derives the Status cell
    from the row's own two cells, and a cell with a note appended stops
    following from them.

    The match is on the field's **leaf** name, because that is what `SPEC.md`
    writes: §3.7 says "`adapter` names whose records...", not
    "`diagnostics[].adapter`". A leaf shared by two structures therefore
    reads as a match for both, which is a prompt to re-read the row, not a
    verdict on it; the failure names the row and the reader decides.
    """
    rows = contracts_rows()
    assert rows, "CONTRACTS.md parsed to no rows; the scan found nothing"
    stated = spec_stated_fields()
    assert "adapter" in stated, (
        "SPEC.md no longer opens a paragraph stating `adapter`, so this "
        "check's reading of what 'the spec states a field' looks like has "
        "gone stale. Move it with the spec rather than deleting either"
    )
    noted = contracts_noted_fields()
    stale = sorted(
        path
        for path, status in rows
        if "unstated" in status and path.split(".")[-1] in stated and path not in noted
    )
    assert not stale, (
        "CONTRACTS.md calls a field `unstated` that SPEC.md now states in a "
        "paragraph of its own. The row is an enumeration and its measurement "
        f"stands; add a note saying {STATED_SINCE!r} and which commit, so the "
        "row records when it stopped being true instead of asserting "
        f"something false about the repository:\n  {stale}"
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


def corpus_counts() -> tuple[int, int, int, int, int]:
    """(scenarios, in two dialects, in one, declaring `name`, mixed).

    "Mixed" is the fifth number and it is not a dialect: a rendering whose
    stem names several adapters (`openinference+otel_genai`) is one file two
    adapters read, which is a shape rather than a coverage gap. Counting it
    among the single-dialect scenarios would make the README say four
    scenarios are rendered in one dialect when one of them is rendered in
    none.
    """
    backed = adapter_backed()
    found = scenarios()
    cross = [
        scenario
        for scenario in found
        if len([p for p in scenario.dialects if p.stem in backed]) > 1
    ]
    mixed = [
        scenario
        for scenario in found
        if any(len(dialect_parts(p.stem)) > 1 for p in scenario.dialects)
    ]
    declaring = [
        scenario
        for scenario in cross
        if (scenario.path / "expected/comparison.json").exists()
        and "name"
        in (scenario.path / "expected/comparison.json").read_text(encoding="utf-8")
    ]
    return (
        len(found),
        len(cross),
        len(found) - len(cross) - len(mixed),
        len(declaring),
        len(mixed),
    )


def test_the_readme_conformance_numbers_are_the_corpus_s_numbers():
    """Every figure in the section carrying the library's central claim.

    The claim this section makes is the reason the project exists, so the
    numbers qualifying it are the ones a reader is least able to check and
    most entitled to trust. The section previously said every scenario is
    expressed in multiple dialects; four are not, each for a declared reason.
    """
    total, cross, single, declaring, mixed = corpus_counts()
    assert total > 0 and cross > 0 and single > 0 and declaring > 0 and mixed > 0
    text = section(read("README.md"), "\n## Conformance")
    for claim in (
        f"holds\n**{total}** scenarios",
        f"**{cross}** are rendered in both dialects",
        f"The other **{single}** are rendered in one",
        f"And **{mixed}** is rendered as a single trace carrying **both**",
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


# -- The Python floor: stated in prose, enforced by packaging ---------------


def declared_python_floor() -> tuple[int, int]:
    """`pyproject.toml`'s `requires-python` floor, as a version tuple.

    Read with stdlib `tomllib` -- available since 3.11, which is the floor
    this function reads, so the test cannot run on an interpreter the package
    refuses anyway.
    """
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as handle:
        spec = tomllib.load(handle)["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec.strip())
    assert match, (
        f"requires-python is {spec!r}, which this test cannot read. It parses "
        f"a bare `>=X.Y` floor on purpose: a range or a set of exclusions is a "
        f"packaging decision worth a human reading, not a regex widening."
    )
    return int(match.group(1)), int(match.group(2))


def test_the_python_floor_the_readme_states_is_the_floor_the_package_declares():
    """`TASKS.md` 3.10 step 8's cold read, second finding -- and it was wrong.

    `gpt-oss-120b`, reading the published page cold, observed that Python 3.11+
    appears only in the Install paragraph and concluded that a reader on 3.10
    therefore gets an import error. Measured rather than accepted: they do not.
    `pip` refuses before anything is installed, naming the reason and exiting
    non-zero, because `requires-python` is declared and travels into the
    wheel's `METADATA`. The observation is recorded as **refuted** at 3.11.

    What made it worth a test anyway is the *shape* of the refutation: the
    reassurance rests entirely on a packaging field, and no test asserted that
    field. A prose claim resting on an unasserted field is this project's
    recurring defect (this file's own docstring). Dropping the floor, or
    letting the README's number drift from it, would make the answer given at
    3.11 false with nothing red.

    The classifiers are held to the same floor for the same reason: they are
    what an index renders, and a classifier below the floor advertises support
    the package refuses to install.
    """
    floor = declared_python_floor()
    stated = re.search(r"Python (\d+)\.(\d+)\+", read("README.md"))
    assert stated, (
        "README.md no longer states a Python floor. It is the only place a "
        "reader is told one before pip tells them."
    )
    assert (int(stated.group(1)), int(stated.group(2))) == floor, (
        f"README states Python {stated.group(1)}.{stated.group(2)}+ and "
        f"pyproject.toml declares >={floor[0]}.{floor[1]}. pip enforces the "
        f"second; the reader reads the first."
    )
    classifiers = [
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(
            r"Programming Language :: Python :: (\d+)\.(\d+)",
            read("pyproject.toml"),
        )
    ]
    assert classifiers, "pyproject.toml names no Python version classifier"
    assert min(classifiers) == floor, (
        f"the lowest Python classifier is {min(classifiers)} and the declared "
        f"floor is {floor}. An index renders the classifiers; pip obeys the "
        f"floor. They must not disagree."
    )


# -- The CLI's hint, held to the paths the documents actually quote ----------
#
# `0.9.1` candidate C1. `spanweave` prints a second, secondary line when a
# missing file's path is one of ours, and "ours" is a prefix constant in
# `spanweave/cli.py`. A constant is exactly the kind of thing that goes on
# being true about a document that has since changed -- the failure this whole
# file exists for -- so the population is DERIVED from the documents here
# rather than restated, and the hint cannot outlive the README that motivates
# it.
#
# The prefix stops at the directory rather than naming a worked example,
# because `cli.py` is not under `spanweave/adapters/` and every real example
# path names a dialect (`tests/gates.py`, `no_dialect_outside_adapters`).

READER_SUBCOMMANDS = frozenset({"build", "inspect", "validate"})

#: Flags whose value is a path the reader WRITES, not one they must already
#: have. `-o graph.json` is not a missing-input case.
OUTPUT_FLAGS = frozenset({"-o", "--output"})


def documented_example_paths(
    paths: list[pathlib.Path] | None = None,
) -> dict[str, set[str]]:
    """Every existing file a document hands to `spanweave` inside a fence.

    These are precisely the paths a reader pastes. One that exists here and is
    absent from an install is the C1 situation; one that does not exist at all
    is a placeholder (`<trace>`) or an output (`graph.json`) and is neither.
    """
    found: dict[str, set[str]] = {}
    scanned = documents() if paths is None else paths
    for path in scanned:
        for line in fenced_lines(path.read_text(encoding="utf-8")):
            command = line[2:] if line.startswith("$ ") else line
            if not re.search(r"\bspanweave\b", command):
                continue
            try:
                argv = shlex.split(command)
            except ValueError:
                continue
            if "spanweave" not in argv:
                continue
            argv = argv[argv.index("spanweave") + 1 :]
            if not argv or argv[0] not in READER_SUBCOMMANDS:
                continue
            skip = False
            for token in argv[1:]:
                if skip:
                    skip = False
                    continue
                if token in OUTPUT_FLAGS:
                    skip = True
                    continue
                if token.startswith("-") or not (ROOT / token).is_file():
                    continue
                found.setdefault(token, set()).add(path.name)
    # The Python block is the same paste by another route.
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^```python\n(.*?)^```", text, re.M | re.S):
            for literal in re.findall(r"""["']([^"'\n]+)["']""", match.group(1)):
                if "/" in literal and (ROOT / literal).is_file():
                    found.setdefault(literal, set()).add(path.name)
    return found


def uncovered(quoted: dict[str, set[str]]) -> dict[str, list[str]]:
    """The quoted paths the CLI's hint would say nothing about."""
    from spanweave.cli import _corpus_hint

    return {
        path: sorted(where)
        for path, where in quoted.items()
        if _corpus_hint(FileNotFoundError(2, "No such file or directory", path)) is None
    }


def test_the_cli_hint_covers_every_example_path_the_documents_quote():
    quoted = documented_example_paths()
    assert quoted, (
        "no document hands `spanweave` a path that exists in this tree. Either "
        "the scan broke or the quickstart stopped showing a runnable command; "
        "both are findings, and a vacuous guard is neither."
    )
    missed = uncovered(quoted)
    assert not missed, (
        f"documents hand `spanweave` example paths the CLI's hint does not "
        f"cover: {missed}. A reader who installed from an index and pasted one "
        f"of these gets the bare OSError -- the exact `0.9.1` C1 case. Either "
        f"widen `_DOCUMENTED_CORPUS_PREFIXES` in spanweave/cli.py or stop "
        f"quoting the path."
    )


def test_the_scan_finds_the_command_the_readme_actually_opens_with():
    """Non-vacuity, keyed to the document rather than to the prefix.

    Deliberately NOT "every path found starts with `fixtures/`": that would
    restate the constant this test exists to derive, and a corpus that moved
    would fail here as well as there, teaching whoever moved it to edit both.
    """
    from tests.readme_quickstart import shell_steps

    opening = next(
        step for step in shell_steps() if step.argv[1:2] and step.argv[1] == "inspect"
    )
    assert opening.argv[2] in documented_example_paths(), (
        f"the README's first `spanweave inspect` names {opening.argv[2]!r} and "
        f"the scan did not find it, so the coverage check above is measuring "
        f"something other than the paste it is written about"
    )


def test_an_uncovered_quoted_path_is_caught(tmp_path):
    """The plant. A guard that has never fired is a guard nobody has read.

    Written against a file that really is in this repository and really is not
    in the wheel -- so the situation is the C1 one exactly -- in a document the
    scan is pointed at, rather than by editing one this project ships.
    """
    planted = tmp_path / "PLANTED.md"
    planted.write_text(
        "```\n$ spanweave inspect tests/serialized_shape.json\n```\n",
        encoding="utf-8",
    )
    quoted = documented_example_paths([planted])
    assert "tests/serialized_shape.json" in quoted, "the scan missed the plant"
    assert uncovered(quoted) == {"tests/serialized_shape.json": ["PLANTED.md"]}


# -- The digest formula, as stated against as computed ---------------------
#
# `SPEC.md` §3.6 is the one contract where an approximate statement is a
# defect rather than a rounding: a reimplementation that follows the text has
# to derive the same node id, byte for byte, or two tools disagree about what
# a record is called. The text omitted `ensure_ascii=False` -- which the
# library has always passed -- until the September 2026 audit series (batch
# A7), so `{"name": "café"}` had two different "correct" ids, one per source.
#
# Scoped to `SPEC.md` on purpose: it is the source of truth for the formula,
# and the only other place the old text survives is the audit review that
# reported the mismatch, where quoting what the spec used to say is the point.

#: The one canonicalization, spelled the one way. `SPEC.md` §3.6 rule 3 and §7
#: both state it, and `spanweave/read.py:record_digest` computes it.
CANONICAL_DIGEST_CALL = (
    'json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
)


def test_the_spec_states_the_canonical_digest_the_library_computes():
    stated = [
        span for span in code_spans(read("SPEC.md")) if "json.dumps(record" in span
    ]
    assert len(stated) >= 2, (
        f"SPEC.md states the canonical digest formula {len(stated)} time(s); "
        f"§3.6 rule 3 and §7 each state it, so fewer than two means one of "
        f"them stopped saying it -- or wrapped it across a line, where "
        f"`code_spans` cannot see it and neither can this check"
    )
    wrong = [span for span in stated if span != CANONICAL_DIGEST_CALL]
    assert wrong == [], (
        f"SPEC.md states the canonical digest as {wrong!r}, and the library "
        f"computes {CANONICAL_DIGEST_CALL!r}. A reimplementation that followed "
        f"the text would derive a different node id for any record containing "
        f"a non-ASCII character (`SPEC.md` §3.6)"
    )


def test_the_library_computes_the_digest_the_spec_states():
    source = read("spanweave/read.py")
    assert CANONICAL_DIGEST_CALL in source, (
        f"`spanweave/read.py` no longer contains the call SPEC.md §3.6 states "
        f"verbatim ({CANONICAL_DIGEST_CALL!r}). If the canonicalization moved, "
        f"the spec moves with it in the same change; if only its spelling "
        f"moved, this constant does. `tests/test_ids.py` checks the two agree "
        f"on values, which is the claim -- this one keeps the text honest too"
    )


# -- Refusal scenarios, claimed against held -------------------------------
#
# `FIXTURES.md` §4.2 and the corpus README each state, in a sentence, that the
# corpus holds no scenario that must not build. Both said the opposite of that
# for as long as it took someone to re-read them (batch A3 emptied the set;
# the corpus README was still describing `duplicate_span_ids` as a refusal a
# run later). The sentence is cheap to check against the directory, so it is
# checked in both directions -- a corpus that gains a refusal fixture fails
# here too, which is the half that keeps this from becoming decoration.

#: The claim, verbatim, in each document that makes it.
NO_REFUSAL_CLAIMS = {
    "FIXTURES.md": "**No scenario carries one today.**",
    "fixtures/conformance/README.md": (
        "**No scenario in this corpus carries an `expected/error.json` today**"
    ),
}


def test_the_documents_are_right_about_which_scenarios_must_not_build():
    refusing = sorted(
        scenario.name for scenario in scenarios() if scenario.expected_error is not None
    )
    for relative, claim in NO_REFUSAL_CLAIMS.items():
        claimed_empty = claim in read(relative)
        assert claimed_empty == (refusing == []), (
            f"{relative} {'says' if claimed_empty else 'no longer says'} the "
            f"corpus holds no scenario that must not build, and it holds "
            f"{refusing or 'none'}. Whichever moved, the other follows in the "
            f"same change (`FIXTURES.md` §4.2)"
        )


# -- `missing_trace_id`, scope claimed against scope measured ---------------
#
# Batch A4 gave the builder a diagnostic for an input that identifies no
# trace, and fenced it in two places nobody reads to learn what the library
# does: a commit body and a CHANGELOG entry. The fence has two sides. It is
# **one per graph**, never one per record; and it fires **only** when the
# built graph reports no trace id at all, so a record carrying none among
# records that do is not diagnosed -- that graph has a trace id, and nothing
# about it is missing.
#
# The September 2026 review (batch A9) found that `SPEC.md` -- the one
# document a consumer reads for what a code means -- stated the first side
# and never the second. A reader could reasonably have expected a diagnostic
# per id-less record and written a consumer around it.
#
# Correcting the sentence would leave a sentence that expires again, so it is
# checked here against both sides of the behaviour it describes: the row must
# say it, and the library must do it.

#: The limit, verbatim, in the row `SPEC.md` §3.7 gives the code.
MISSING_TRACE_ID_SCOPE = (
    "only when the built graph reports no trace id at all; "
    "a record carrying none among records that do is not diagnosed"
)


def a_trace_record(span_id: str, trace_id: str | None) -> dict[str, object]:
    """One OpenInference record, with or without the trace id field."""
    record: dict[str, object] = {
        "span_id": span_id,
        "parent_id": None,
        "name": "a",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": {"openinference.span.kind": "AGENT"},
    }
    if trace_id is not None:
        record["trace_id"] = trace_id
    return record


def missing_trace_id_count(records: list[dict[str, object]], path: pathlib.Path) -> int:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    graph = spanweave.build(path)
    return len([d for d in graph.diagnostics if d.code == "missing_trace_id"])


def test_the_spec_states_the_scope_the_missing_trace_id_diagnostic_keeps():
    # The code table only: §3.7 also tables each code's `source` shape, and
    # that row answers a different question.
    code_table = section(read("SPEC.md"), "### 3.7").split("#### ")[0]
    rows = [
        line
        for line in code_table.splitlines()
        if line.startswith("| `missing_trace_id` |")
    ]
    assert len(rows) == 1, (
        f"`SPEC.md` §3.7's code table gives `missing_trace_id` {len(rows)} "
        f"row(s); it is one code and gets one row, and this check reads that "
        f"row for the scope the library actually keeps"
    )
    assert MISSING_TRACE_ID_SCOPE in rows[0], (
        f"`SPEC.md` §3.7 no longer states where `missing_trace_id` stops "
        f"({MISSING_TRACE_ID_SCOPE!r}). The limit is real -- the test below "
        f"measures it -- and §3.7 is where a consumer reads what a code "
        f"means, so an unstated limit is a limit nobody can rely on"
    )


def test_the_library_keeps_the_scope_the_spec_states(tmp_path):
    # Side one: a graph that reports no trace id says so, once.
    none_at_all = missing_trace_id_count(
        [a_trace_record(f"s{index}", None) for index in range(3)],
        tmp_path / "none_at_all.jsonl",
    )
    assert none_at_all == 1, (
        f"an input where no record carries a trace id produced "
        f"{none_at_all} `missing_trace_id` diagnostics; `SPEC.md` §3.7 and §7 "
        f"say one per graph, never one per record"
    )
    # Side two: one record short of an id is not that case at all.
    one_short = missing_trace_id_count(
        [a_trace_record("s0", "t1"), a_trace_record("s1", None)],
        tmp_path / "one_short.jsonl",
    )
    assert one_short == 0, (
        f"a record carrying no trace id among records that do produced "
        f"{one_short} `missing_trace_id` diagnostic(s); that graph has a "
        f"trace id and nothing about it is missing (`SPEC.md` §3.7)"
    )


# -- `operation` and the names no dialect reads into it ---------------------
#
# Batch H1 measured that `Node.operation` is `None` on every `agent`, `chain`
# and `retriever` node the corpus produces, in both dialects, and asked
# whether it should stay that way (`OPEN_QUESTIONS.md` §15). The decision
# (`TASKS.md`, September 2026 audit, 2026-09-10) was option C: it stays, and
# the non-mapping becomes a rule in `SPEC.md` rather than a sentence in an
# adapter docstring.
#
# Two things are checked here, because a rule stated only in prose expires the
# way every other sentence in this file expired. §3.1 must state it; and the
# library must do it, on both dialects, with the declined name still reachable
# where §3.1 says a consumer will find it.
#
# The second half also pins the *precision*: the rule is about name
# attributes, not about the field being empty on those kinds. An agent span
# that carries a model attribute gets the model, in both dialects. Suppressing
# `operation` by kind would satisfy a careless reading of the rule and would
# be a different library.

#: The rule, verbatim, in `SPEC.md` §3.1.
OPERATION_NAME_RULE = (
    "**No dialect's agent, chain or retriever name is read into `operation`.**"
)

#: The `gen_ai.agent.name` attribute OTel GenAI states and the adapter declines.
GENAI_AGENT_NAME = "gen_ai.agent.name"


def spec_operation_subsection() -> str:
    """The text of §3.1's `operation` subsection, and nothing else."""
    spec = read("SPEC.md")
    start = spec.index("#### `operation`")
    return spec[start : spec.index("#### Timestamps", start)]


def openinference_span(kind: str, extra: dict[str, object]) -> dict[str, object]:
    attributes: dict[str, object] = {"openinference.span.kind": kind}
    attributes.update(extra)
    return {
        "trace_id": "t1",
        "span_id": "s0",
        "parent_id": None,
        "name": "agent.run",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": attributes,
    }


def otel_genai_span(operation: str, extra: dict[str, object]) -> dict[str, object]:
    attributes: dict[str, object] = {"gen_ai.operation.name": operation}
    attributes.update(extra)
    return {
        "trace_id": "t1",
        "span_id": "s0",
        "parent_id": None,
        "name": f"{operation} agent.run",
        "start_time": 1.0,
        "end_time": 2.0,
        "status": "OK",
        "attributes": attributes,
    }


def one_node(record: dict[str, object], adapter: str, path: pathlib.Path):
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    graph = spanweave.build(path, adapter=adapter)
    assert len(graph.nodes()) == 1, (
        f"{adapter} produced {len(graph.nodes())} nodes for one record; this "
        f"check is about the one node's `operation` and needs exactly one"
    )
    return graph


def test_the_spec_states_which_names_never_reach_operation():
    subsection = spec_operation_subsection()
    assert OPERATION_NAME_RULE in subsection, (
        f"`SPEC.md` §3.1 no longer states the rule ({OPERATION_NAME_RULE!r}). "
        f"It is the whole content of the H1 decision (`OPEN_QUESTIONS.md` §15, "
        f"`TASKS.md`), and §3.1 is where a consumer reads what a field "
        f"holds -- an unstated rule is one an adapter can quietly break"
    )
    assert "raw.source" in subsection and "unmapped_attributes" in subsection, (
        "`SPEC.md` §3.1 states the non-mapping without saying where the "
        "declined name survives. Both halves are the decision: the value in "
        "`raw.source` (§3.5), the fact of declining it in an "
        "`unmapped_attributes` diagnostic (§3.7)"
    )
    # The defect H1 found in passing: §3.1's own field list promised a name
    # no dialect states. The comment beside the field is what a reader sees
    # first, so it is what this reads.
    declaration = [
        line
        for line in section(read("SPEC.md"), "### 3.1 Node").splitlines()
        if line.strip().startswith("operation:")
    ]
    assert len(declaration) == 1, (
        f"`SPEC.md` §3.1 declares `operation` {len(declaration)} times; it is "
        f"one field on `Node` and gets one line"
    )
    assert "retriever" not in declaration[0], (
        f"`SPEC.md` §3.1 promises a retriever name again ({declaration[0]!r}). "
        f"No dialect this library reads states one -- OTel GenAI names the "
        f"operation, `retrieval`, not the retriever -- so the promise cannot "
        f"be kept (`OPEN_QUESTIONS.md` §15(b))"
    )


def test_no_dialect_reads_an_agent_chain_or_retriever_name_into_operation(tmp_path):
    # OpenInference: the name is the span `name` and nothing else, on all
    # three kinds. Nothing is read into `operation`.
    for index, kind in enumerate(("AGENT", "CHAIN", "RETRIEVER")):
        graph = one_node(
            openinference_span(kind, {}),
            "openinference",
            tmp_path / f"oi_{index}.jsonl",
        )
        node = graph.nodes()[0]
        assert node.operation is None, (
            f"an OpenInference {kind} span put {node.operation!r} in "
            f"`operation`; `SPEC.md` §3.1 says only a tool or model name "
            f"reaches that field, and this span states neither"
        )
        assert node.raw.source["name"] == "agent.run", (
            "the span name is the only place OpenInference states this "
            "thing's identity, and `raw.source` is where `SPEC.md` §3.1 says "
            "a consumer finds a name the library declined to normalize"
        )

    # OTel GenAI: `gen_ai.agent.name` is stated, declined, and still reachable.
    graph = one_node(
        otel_genai_span("invoke_agent", {GENAI_AGENT_NAME: "agent.run"}),
        "otel_genai",
        tmp_path / "genai_agent.jsonl",
    )
    node = graph.nodes()[0]
    assert node.operation is None, (
        f"the `otel_genai` adapter read a declined name into `operation` "
        f"({node.operation!r}). `SPEC.md` §3.1 states the non-mapping, and "
        f"`OPEN_QUESTIONS.md` §15(f) measured what breaks if it is undone: "
        f"11 of 18 cross-dialect scenarios diverge"
    )
    assert node.raw.source["attributes"][GENAI_AGENT_NAME] == "agent.run", (
        f"{GENAI_AGENT_NAME} is not verbatim in `raw.source`. §3.1's whole "
        f"claim is that declining to normalize a name does not lose it"
    )
    unmapped = [
        d
        for d in graph.diagnostics
        if d.code == "unmapped_attributes" and GENAI_AGENT_NAME in (d.source or ())
    ]
    assert len(unmapped) == 1, (
        f"{GENAI_AGENT_NAME} was declined without being announced "
        f"({len(unmapped)} `unmapped_attributes` diagnostics name it). "
        f"`raw.source` is where a consumer finds the name; the diagnostic is "
        f"how a consumer learns to look (`SPEC.md` §3.1)"
    )

    # A GenAI retrieval span states no retriever name to decline, so the
    # third of §3.1's formerly promised names has nothing behind it either.
    graph = one_node(
        otel_genai_span("retrieval", {}), "otel_genai", tmp_path / "genai_retr.jsonl"
    )
    assert graph.nodes()[0].operation is None, (
        f"a GenAI `retrieval` span produced `operation` "
        f"{graph.nodes()[0].operation!r}; the convention names the operation, "
        f"not the retriever, so there is no name for the field to hold"
    )


def test_the_rule_is_about_name_attributes_not_about_the_kind(tmp_path):
    # `SPEC.md` §3.1's first precision, measured on both dialects: an agent
    # span that also names a model gets the model. That is the ordinary rule,
    # it is symmetric, and it is why the corpus's `null`s are a property of
    # the fixtures rather than of the kind (`OPEN_QUESTIONS.md` §15(b)).
    openinference = one_node(
        openinference_span("AGENT", {"llm.model_name": "m1"}),
        "openinference",
        tmp_path / "oi_model.jsonl",
    )
    otel_genai = one_node(
        otel_genai_span(
            "invoke_agent",
            {GENAI_AGENT_NAME: "agent.run", "gen_ai.request.model": "m1"},
        ),
        "otel_genai",
        tmp_path / "genai_model.jsonl",
    )
    both = (openinference.nodes()[0].operation, otel_genai.nodes()[0].operation)
    assert both == ("m1", "m1"), (
        f"an agent span carrying a model attribute produced `operation` "
        f"{both} in (openinference, otel_genai); `SPEC.md` §3.1 says the rule "
        f"is about name attributes and not about the kind, and that both "
        f"dialects agree here -- if that stopped being true the spec's "
        f"precision is wrong, and if it became `None` the field was "
        f"suppressed by kind, which §3.1 does not say"
    )


# -- The freeze gates ROADMAP.md states, held to what they count ------------
#
# Batch G5 landed three subsections in `ROADMAP.md` Phase 4: the outside-use
# gate, the announcement task, and the rule that no question or batch which
# moves a serialized field may be open at the freeze. Two of them record
# **measured absences**, and an absence is the most perishable claim a document
# can make -- it is true until the corpus grows, and nothing about growing a
# corpus reminds anyone to reread a roadmap. So both are recomputed here.


#: The pointer batch G2 added under Phase 4's raw-OTLP-JSON bullet, verbatim.
#: G3 judged it and kept it (`OPEN_QUESTIONS.md` §14(j)); this is what "kept"
#: means to a later editor who never read that memo.
G2_POINTER = (
    "Raw OTLP JSON is pulled forward by the September 2026 audit as batches "
    # The en dash is the document's; escaped so this stays a verbatim
    # quotation without tripping the ambiguous-character lint.
    "F1\u2013F2, which ask whether the envelope is a container format for the "
    "reader rather than a dialect for an adapter"
)


def flat(text: str) -> str:
    return " ".join(text.split())


def test_the_roadmap_still_carries_the_pointer_g2_added():
    """A sentence three later batches were told to preserve, held rather than
    remembered. It is the only place `ROADMAP.md` says its own raw-OTLP-JSON
    bullet is being reinterpreted elsewhere.
    """
    assert G2_POINTER in flat(read("ROADMAP.md")), (
        "ROADMAP.md no longer carries G2's pointer under the raw OTLP JSON "
        "bullet. If F1 has since decided the question, the sentence should be "
        "replaced by what was decided -- not dropped, which leaves the bullet "
        "silent about work that changes what it means"
    )


def test_the_freeze_bullet_names_three_gates_and_each_one_has_a_section():
    """`ROADMAP.md`'s freeze bullet promises "the three gates below"."""
    phase_four = flat(section(read("ROADMAP.md"), "\n## Phase 4"))
    for clause in (
        "**the outside-use gate below is met**",
        "**a third dialect is rendered in the conformance corpus**",
        "**every open model question in `OPEN_QUESTIONS.md` is decided**",
        "see the three gates below",
    ):
        assert clause in phase_four, (
            f"the freeze bullet no longer says {clause!r}. The three "
            f"conditions and the pointer to them move together or the bullet "
            f"promises a gate the file does not state"
        )
    for heading in (
        "### The third dialect is a freeze precondition",
        '### "Real outside users" is a stated gate, not a hope',
        "### No open model question survives the freeze",
    ):
        assert flat(heading) in phase_four, (
            f"Phase 4 has no {heading!r} section, but the freeze bullet sends "
            f"a reader to three gates"
        )
    assert "The floor is **not evidence**" in phase_four, (
        "the outside-use gate no longer says its 30-day floor is not "
        "evidence. That clause is the whole reason the floor sits outside the "
        "count of conditions rather than inside it"
    )


def test_the_two_weaker_statements_of_the_outside_use_gate_point_at_it():
    """The through-line and Phase 3's *Freeze later, on evidence* each stated
    this condition in their own words, at their own strength. G1 found three
    statements of one gate and no way to tell which one bound. They now point.
    """
    roadmap = flat(read("ROADMAP.md"))
    name = '*"Real outside users" is a stated gate, not a hope*'
    assert roadmap.count(name) >= 2, (
        "the through-line and Phase 3's *Freeze later, on evidence* are "
        "supposed to point at the outside-use gate by name rather than "
        "restate it; fewer than two pointers means one of them has grown its "
        "own version of the condition again"
    )


def dialect_claims_over_the_committed_corpus() -> tuple[int, int, dict[int, int], int]:
    """Files, records, how many adapters claim each record, and mixed files.

    Counted by `tests/corpus_census.py`, which takes its file list from `git
    ls-files` rather than walking the tree: the numbers below are asserted by
    documents as things a stranger recomputes from a checkout, and a walk
    counts whatever is lying in the working directory. That is not
    hypothetical -- it is how `57 files / 177 records` reached five commit
    bodies (batch R5). The plant at the end of this file holds the line.

    The claim is made with `detect([record])`, which `OPEN_QUESTIONS.md`
    §12(d) measured against a direct marker scan over the whole corpus with
    zero disagreements -- so this counts what an adapter would actually do,
    not what a regex over attribute keys says it would.
    """
    counted = census()
    return counted.files, counted.records, counted.claims, counted.mixed_files


def test_the_roadmap_records_the_mixed_dialect_absence_the_corpus_shows():
    """The measurement the mixed-instrumentation precondition rests on.

    `ROADMAP.md` states it over the corpus **this repository carries**, on
    purpose: `OPEN_QUESTIONS.md` §12(c)'s wider 57/177 was a scan of a working
    tree that included local capture output git ignores, and a number nobody
    can recompute from a checkout is the kind of claim this file exists to
    stop. The zero is the same in both.
    """
    files, records, claims, mixed_files = dialect_claims_over_the_committed_corpus()
    stated = re.search(
        r"\*\*(\d+)\*\* trace files, \*\*(\d+)\*\* records",
        flat(read("ROADMAP.md")),
    )
    assert stated is not None, (
        "ROADMAP.md no longer states the size of the corpus its "
        "mixed-dialect absence was measured over, so the absence is a claim "
        "about nothing in particular"
    )
    assert (int(stated.group(1)), int(stated.group(2))) == (files, records), (
        f"ROADMAP.md says the corpus is {stated.group(1)} files and "
        f"{stated.group(2)} records; it is {files} files and {records} "
        f"records. The sentence is stale, which for an absence means the "
        f"absence was never re-measured over what was added"
    )
    assert claims.get(2, 0) == 0, (
        f"{claims[2]} corpus records are now claimed by both adapters. That "
        f"is the mixed-dialect shape ROADMAP.md and OPEN_QUESTIONS.md §12(c) "
        f"both record as never observed here -- the roadmap sentence is now "
        f"false and E's precondition has a fixture behind it"
    )
    assert claims.get(1, 0) == records, (
        f"only {claims.get(1, 0)} of {records} corpus records are claimed by "
        f"exactly one adapter; ROADMAP.md says every record is"
    )
    assert "**0** records carry both dialects' markers" in flat(read("ROADMAP.md")), (
        "ROADMAP.md no longer states the zero itself, which is the half of "
        "the measurement the freeze rule turns on"
    )
    # The fourth number, added with `mixed_instrumentation` (batch E3). The
    # zero above is about RECORDS and stayed zero; what the corpus gained is a
    # FILE holding two dialects, and a document that recorded only the zero
    # would now read as "no mixed trace here" while one sits in `fixtures/`.
    assert f"**{mixed_files}** file carries records of both" in flat(
        read("ROADMAP.md")
    ) or f"**{mixed_files}** files carry records of both" in flat(read("ROADMAP.md")), (
        f"{mixed_files} corpus file(s) carry records of both dialects and "
        f"ROADMAP.md does not say so. The absence it records is about the "
        f"OUTSIDE world; a constructed fixture does not refute it, and "
        f"leaving it unstated makes the sentence read as though the "
        f"repository holds no such file at all"
    )
    assert "Constructed is not observed" in flat(read("ROADMAP.md")), (
        "ROADMAP.md no longer distinguishes the constructed fixture from an "
        "observation. That distinction is the whole reason both numbers are "
        "stated"
    )


def test_the_roadmap_records_the_agent_span_absence_the_captures_show():
    """The second measured absence, over a **different** corpus.

    Not the fixture corpus counted above: the three captured traces. Recorded
    beside the first one at `OPEN_QUESTIONS.md` §14(h) item 4 by batch H2, and
    it bears on the freeze because §15's option B would normalize an attribute
    whose cross-dialect behaviour nobody here has observed.
    """
    captured = sorted((ROOT / "fixtures/captured").glob("*.jsonl"))
    records = sum(
        1
        for path in captured
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    agents = sum(
        1
        for path in captured
        for node in spanweave.build(path).nodes()
        if node.kind is spanweave.NodeKind.AGENT
    )
    stated = re.search(
        r"the three captured traces in `fixtures/captured/`, \*\*(\d+)\*\* "
        r"records, which carry \*\*(\d+)\*\* `agent` spans",
        flat(read("ROADMAP.md")),
    )
    assert stated is not None, (
        "ROADMAP.md no longer states the captured corpus its agent-span "
        "absence was measured over"
    )
    assert len(captured) == 3, (
        f"ROADMAP.md says three captured traces; there are {len(captured)}. A "
        f"fourth capture is exactly the event that could overturn the "
        f"absence, so the sentence has to be re-measured rather than reworded"
    )
    assert (int(stated.group(1)), int(stated.group(2))) == (records, agents), (
        f"ROADMAP.md says {stated.group(1)} captured records carrying "
        f"{stated.group(2)} agent spans; the captures hold {records} and "
        f"{agents}"
    )
    harness = read("capture/backends.py")
    for builder in ("def agent_span_attributes", "def genai_agent_span_attributes"):
        assert builder in harness, (
            f"`capture/backends.py` no longer defines `{builder}`, which is "
            f"the whole evidence for ROADMAP.md's claim that none of the "
            f"captured agent spans came from an instrumentor. If an "
            f"instrumentor emits them now, the absence has ended and the "
            f"roadmap says so"
        )


# The census the sentences above and below are counted from reads git's file
# list, not the working tree (`tests/corpus_census.py`). Five commits of the
# September 2026 audit series cited `57 files / 177 records`, a pair measured
# on a tree holding local capture output git ignores, and no reader could
# reproduce it. A walk cannot hold that line -- it counts whatever is lying in
# the directory -- so the plant below is the property, not a nicety.
def test_the_corpus_census_counts_only_what_git_tracks(tmp_path):
    """An untracked trace under `fixtures/` must not move a stated number.

    Planted in the real corpus directory on purpose: a temporary copy would
    prove something about a temporary directory, and the sentences in
    `ROADMAP.md` and `OPEN_QUESTIONS.md` are about this one.
    """
    del tmp_path
    before = dialect_claims_over_the_committed_corpus()
    planted = ROOT / "fixtures/conformance/llm_tool_llm/dialects/_r5_plant.jsonl"
    assert not planted.exists(), f"{planted} exists; a previous run left it"
    planted.write_text(
        '{"span_id": "planted", "attributes": {"openinference.span.kind": "LLM"}}\n',
        encoding="utf-8",
    )
    try:
        after = dialect_claims_over_the_committed_corpus()
    finally:
        planted.unlink()
    assert after == before, (
        f"an untracked file under `fixtures/` moved the census from {before} "
        f"to {after}. Every document that states a corpus size states one a "
        f"stranger is supposed to recompute from a checkout, and a working-"
        f"tree walk counts what a checkout does not contain -- which is "
        f"exactly how `57 files / 177 records` got written down five times"
    )


def test_the_open_questions_census_is_the_tracked_census():
    """§12's figures, recomputed rather than believed.

    §12(c) is the measurement the freeze precondition rests on, §12(d) is the
    cross-check that `detect([record])` classifies a record the way a direct
    marker scan does, and §12(f) is what the corpus says about ids. All three
    stated a working-tree pair until batch R5; all three are counted here from
    `git ls-files`.
    """
    counted = census()
    text = flat(read("OPEN_QUESTIONS.md"))

    stated = re.search(
        r"scanned end to end — \*\*(\d+)\*\* files, \*\*(\d+)\*\* records "
        r"\(tracked files only\)",
        text,
    )
    assert stated is not None, (
        "OPEN_QUESTIONS.md §12(c) no longer states the size of the corpus its "
        "mixed-dialect absence was measured over, qualified as tracked. The "
        "qualifier is half the claim: an unqualified pair is what five commit "
        "bodies got wrong"
    )
    assert (int(stated.group(1)), int(stated.group(2))) == (
        counted.files,
        counted.records,
    ), (
        f"§12(c) says {stated.group(1)} files and {stated.group(2)} records; "
        f"the tracked corpus is {counted.files} and {counted.records}"
    )
    for adapter_id, files in sorted(counted.sole_dialect_files.items()):
        assert f"**{files}** are `{adapter_id}`-only" in text, (
            f"§12(c) does not say that {files} corpus files are "
            f"{adapter_id}-only, which is what the census counts"
        )

    disagreements = re.search(
        r"over all \*\*(\d+)\*\* tracked corpus records: \*\*(\d+) disagreements\*\*",
        text,
    )
    assert disagreements is not None, (
        "OPEN_QUESTIONS.md §12(d) no longer states the marker-scan cross-check "
        "over a stated number of records"
    )
    assert (
        int(disagreements.group(1)),
        int(disagreements.group(2)),
    ) == (counted.records, counted.marker_disagreements), (
        f"§12(d) claims {disagreements.group(2)} disagreement(s) over "
        f"{disagreements.group(1)} records; re-run over the tracked corpus it "
        f"is {counted.marker_disagreements} over {counted.records}. A "
        f"disagreement means `detect([record])` and the marker it scans for "
        f"have parted company, which is the whole basis of per-record dispatch"
    )

    ids = re.search(
        r"of the \*\*(\d+)\*\* tracked corpus records, \*\*(\d+)\*\* carry a "
        r"`span_id` and \*\*(\d+)\*\* of those are trace-unique",
        text,
    )
    assert ids is not None, (
        "OPEN_QUESTIONS.md §12(f) no longer states how much of the corpus "
        "takes `SPEC.md` §3.6 rule 1. It said *177 of 177* -- every record -- "
        "which stopped being true the moment batch A5 added a span-id-less "
        "scenario, and nothing recomputed it"
    )
    assert tuple(int(group) for group in ids.groups()) == (
        counted.records,
        counted.with_span_id,
        counted.trace_unique_span_id,
    ), (
        f"§12(f) says {ids.groups()}; the tracked corpus is "
        f"({counted.records}, {counted.with_span_id}, "
        f"{counted.trace_unique_span_id})"
    )


#: Every census figure no reader can reproduce, and the words that mark a
#: mention of one as history rather than as a claim. `57 files / 177 records`
#: was measured on a working tree holding git-ignored capture output; it
#: reached five commit bodies, which cannot be rewritten, so the durable
#: documents say what it was and what it recomputes to instead (batch R5).
#:
#: The rest of the family, added by batch R9, was found the same way and is
#: wrong the same way: C3's timestamp sweep and D2's `data`-edge sweep both
#: named `capture/_scratch/fleet/` as half their scope, F1's `64 of 64` counted
#: `*.jsonl` files a checkout does not have, and F1's `46 malformed_record`
#: counted an OTLP export `probe1.py` wrote to a temporary directory.
#:
#: `capture/_scratch` is deliberately **not** a history marker. Naming the
#: git-ignored directory is what these paragraphs did while asserting the
#: figure -- it was the defect, not the disclaimer.
#:
#: This list is hand-written and covers the working-tree values only; the
#: values later batches retired (`139`, `135`, `151`, `50`, `64`) are held by
#: `test_no_durable_document_asserts_a_retired_figure_in_a_live_sentence`,
#: which derives them from `RETIRED_CENSUS_FIGURES` rather than from here
#: (run-5 review 1.2).
WORKING_TREE_CENSUS = re.compile(
    r"\b177\b"
    r"|\b57 (?:files|corpus files)\b"
    r"|\b154 (?:timestamp|values|corpus literals)\b"
    r"|\b17 captured\b"
    r"|\b41 sibling pairs\b"
    r"|\b15 captured files\b"
    r"|\b24 data edges\b"
    r"|\b24 of them\b"
    r"|\b64 of 64\b"
    r"|\b46 malformed"
)


def unemphasized(text: str) -> str:
    """The text with markdown emphasis removed, so a figure is one token.

    `**24** \\`data\\` edges` and `24 data edges` are the same claim, and a
    guard that only catches the second spelling catches nothing: every one of
    these figures is written bold in at least one of the places it appears.
    """
    return text.replace("**", "").replace("*", "").replace("`", "")


CENSUS_HISTORY_MARKERS = (
    "working tree",
    "working-tree",
    "checkout",
    "batch R5",
    "batch R9",
)


def test_the_cited_corpus_figures_are_the_tracked_census():
    """R5's rule, applied to the four figures its own grep did not name.

    R5 searched for the `57 files / 177 records` family and fixed it. The rest
    of the durable documents carried four more figures with the same defect and
    batch R9 recomputes them here: C3's timestamp sweep and D2's `data`-edge
    sweep both named `capture/_scratch/fleet/` as half their scope, F1's
    `64 of 64` counted `*.jsonl` files a checkout does not have, and F1's
    `46 malformed_record` counted lines of an export `probe1.py` wrote to a
    temporary directory.

    Every figure below is asserted with the same "(tracked files only)"
    qualifier G5 and R5 used, and every one is recomputed from `git ls-files`
    rather than believed.
    """
    counted = census()
    captured = counted.captured_timestamps
    whole = counted.timestamps
    edges = counted.captured_receipts
    exports = {export.path: export for export in counted.indented_exports}
    indented = exports.get(
        "fixtures/conformance/otlp_container/dialects/openinference.json"
    )
    assert indented is not None, (
        "no tracked OTLP JSON document opens on `resourceSpans` any more, so "
        "§16(a)'s per-line diagnostic count is measured over nothing again -- "
        "which is exactly the state batch R9 found it in"
    )
    scan = counted.head_scan
    questions = flat(read("OPEN_QUESTIONS.md"))
    changelog = flat(read("CHANGELOG.md"))
    scenario = flat(read("fixtures/conformance/receipt_redeclared/scenario.md"))
    notes = flat(read("fixtures/conformance/receipt_redeclared/otel_genai.notes.md"))

    cited: tuple[tuple[str, str, str, tuple[int, ...]], ...] = (
        (
            "OPEN_QUESTIONS.md §2, C3's captured sweep",
            questions,
            r"Across the \*\*(\d+)\*\* captured trace files a checkout carries "
            r"\(`fixtures/captured/`, tracked files only\): \*\*(\d+)\*\* "
            r"timestamp values, \*\*(\d+)\*\* above 1e11",
            (len(counted.captured), captured.literals, captured.above_ceiling),
        ),
        (
            "OPEN_QUESTIONS.md §2, the sibling gap",
            questions,
            r"\*\*(\d+)\*\* sibling pairs, minimum gap \*\*(\d+) µs\*\*",
            (captured.sibling_pairs, captured.minimum_sibling_gap_us or 0),
        ),
        (
            "OPEN_QUESTIONS.md §2, the widened sweep",
            questions,
            r"\*\*(\d+)\*\* of the tracked corpus's \*\*(\d+)\*\* timestamp "
            r"literals sit above the line",
            (whole.above_ceiling, whole.literals),
        ),
        (
            "OPEN_QUESTIONS.md §2, round-tripping",
            questions,
            r"the \*\*(\d+)\*\* literals that differ from it, of \*\*(\d+)\*\* "
            r"in the tracked corpus",
            (whole.differing_from_shortest_repr, whole.literals),
        ),
        (
            "OPEN_QUESTIONS.md §2(c), the falsifying scan",
            questions,
            r"The captured traces today, tracked files only: \*\*(\d+)\*\* "
            r"values, \*\*0\*\* hits; \*\*(\d+)\*\* sibling pairs",
            (captured.literals, captured.sibling_pairs),
        ),
        (
            "OPEN_QUESTIONS.md §11, D2's `data` edges",
            questions,
            r"across the \*\*(\d+)\*\* captured files a checkout carries "
            r"\(`fixtures/captured/`, tracked files only\), every one of which "
            r"produces `data` edges, there are \*\*(\d+)\*\* `data` edges",
            (edges.files, edges.data_edges),
        ),
        (
            "OPEN_QUESTIONS.md §16(a), the per-line diagnostic count",
            questions,
            r"\*\*(\d+)\*\* times for "
            r"`fixtures/conformance/otlp_container/dialects/openinference\.json`",
            (indented.lines_that_are_not_json,),
        ),
        (
            "OPEN_QUESTIONS.md §16(k), the head scan",
            questions,
            r"\*\*(\d+) of (\d+)\*\* tracked `\*\.jsonl` files begin with",
            (scan.beginning_with_brace, scan.files),
        ),
        (
            "OPEN_QUESTIONS.md §16(k), the first member key",
            questions,
            r"first record is `trace_id` in \*\*(\d+) of (\d+)\*\*",
            (scan.first_member_key_trace_id, scan.files),
        ),
        (
            "CHANGELOG.md, C3's entry",
            changelog,
            r"\*\*(\d+)\*\* timestamp values across the \*\*(\d+)\*\* captured "
            r"files a checkout carries",
            (captured.literals, len(counted.captured)),
        ),
        (
            "CHANGELOG.md, D2's entry",
            changelog,
            r"first receipt -- \*\*(\d+)\*\* across the \*\*(\d+)\*\* captured "
            r"files a checkout carries \(tracked files only\)",
            (edges.data_edges, edges.files),
        ),
        (
            "CHANGELOG.md, F2's entry",
            changelog,
            r"\*\*(\d+)\*\* of them for the indented export",
            (indented.lines_that_are_not_json,),
        ),
        (
            "receipt_redeclared/scenario.md",
            scenario,
            r"across the (\d+) captured files a checkout carries \(tracked files "
            r"only\) there are (\d+) `data` edges",
            (edges.files, edges.data_edges),
        ),
        (
            "receipt_redeclared/otel_genai.notes.md",
            notes,
            r"§11: (\d+) captured files, (\d+) `data` edges",
            (edges.files, edges.data_edges),
        ),
    )

    for where, text, pattern, expected in cited:
        found = re.search(pattern, text)
        assert found is not None, (
            f"{where} no longer states its figure in the shape this test "
            f"recomputes ({pattern!r}). The sentence is only evidence while a "
            f"stranger can check it, so a rewording that hides it from the "
            f"census is a rewording that has to change this test too"
        )
        assert tuple(int(group) for group in found.groups()) == expected, (
            f"{where} states {found.groups()}; `tests/corpus_census.py` counts "
            f"{expected} over the tracked tree"
        )

    assert edges.files_with_data_edges == edges.files, (
        "OPEN_QUESTIONS.md §11 and receipt_redeclared/scenario.md say every "
        "captured file a checkout carries produces a `data` edge; the census "
        f"finds {edges.files_with_data_edges} of {edges.files} that do"
    )
    assert edges.redeclared_receipts == 0, (
        "a captured trace now carries a call id received by more than one "
        "span. That is the shape `SPEC.md` §4.2.1's rank exists for, and "
        "§11, its scenario and its notes all say it has only ever been "
        "constructed -- so this is an observation, and those three sentences "
        "are now wrong in a way no arithmetic fixes"
    )


def test_no_durable_document_states_the_working_tree_census_as_a_fact():
    """The stale pair may be quoted as history; it may not be asserted.

    Paragraph-scoped, because that is the unit a reader takes a claim from: a
    provenance note three paragraphs away does not stop the sentence in front
    of them from being wrong. Verbatim blockquotes are exempt -- they are
    records of a moment, like `reviews/`, and rewriting one would be a
    falsification rather than a correction -- so where a quote carries the old
    pair, the editorial line around it is what carries the correction.
    """
    offenders: list[str] = []
    for path in durable_documents():
        for paragraph in path.read_text(encoding="utf-8").split("\n\n"):
            if any(line.lstrip().startswith(">") for line in paragraph.splitlines()):
                continue
            if not WORKING_TREE_CENSUS.search(unemphasized(paragraph)):
                continue
            if any(marker in paragraph for marker in CENSUS_HISTORY_MARKERS):
                continue
            offenders.append(f"{path.relative_to(ROOT)}: {flat(paragraph)[:120]}")
    assert not offenders, (
        "these paragraphs state a corpus census a reader cannot reproduce "
        "from a checkout, with nothing marking it as history: "
        + "; ".join(offenders)
        + ". `57 files / 177 records` counted a working tree holding the "
        "git-ignored `capture/_scratch/`; `tests/corpus_census.py` counts "
        "what git tracks, and a document either states that figure or says "
        "which one it is quoting and why"
    )


#: A figure family: the shape the documents write a census figure in, and the
#: census figure names its capture groups must equal.
#:
#: The pair shape names itself, so it is scanned everywhere; most of the rest
#: are single numbers that mean nothing on their own (`4 data edges` is a
#: census figure in one paragraph and a worked example in the next), so they
#: are scanned only inside a paragraph that states the census's own scope --
#: `CENSUS_SCOPE` below, which is the qualifier G5 and R5 made every one of
#: those sentences carry. A few are self-naming in their own words (*carry a
#: `span_id`*, *`openinference`-only*) and are scanned everywhere too, because
#: the sentences that state them do not carry the scope phrase.
#:
#: A number is written `(?<![\d,./-])(\d+)` so that `n(n-1)/2 data edges` and
#: `1,225 data edges` are not read as the census's four.
@dataclass(frozen=True, slots=True)
class CensusFigureFamily:
    """One spelling of one census figure, and what it has to equal."""

    #: What this family is called in a failure message.
    name: str
    #: The regex, matched against `flat(unemphasized(paragraph))`. Groups that
    #: match are the figure; alternatives may each carry their own group.
    pattern: str
    #: Whether a paragraph must state the census's scope before this family is
    #: read out of it.
    requires_scope: bool
    #: One entry per matched capture group, in order: the `corpus_census`
    #: figure names whose value that group may be. This is the half that makes
    #: the guard derived rather than remembered -- every figure the census
    #: computes has to appear in some slot, or
    #: `test_every_figure_the_census_computes_is_guarded_by_a_family` fails.
    slots: tuple[tuple[str, ...], ...]
    #: A sentence this family must read, with planted values, proving the
    #: pattern matches the spelling it was written for. A family whose regex
    #: silently stopped matching is a family that guards nothing.
    example: str
    #: The values `example` plants, in group order.
    example_values: tuple[int, ...]


CENSUS_FIGURE_FAMILIES: tuple[CensusFigureFamily, ...] = (
    CensusFigureFamily(
        "corpus files / records",
        r"(?<![\d,./-])(\d+) (?:(?:trace|corpus|captured|tracked|committed|fixture) )*"
        r"files?\s*(?:/|,|and|--|—|-|:)\s*(\d+) records?\b",
        False,
        (("files",), ("records",)),
        "The corpus holds 99 files, 999 records.",
        (99, 999),
    ),
    # The census prints the pair a second time as `54/155`, and S3's recount
    # sentence in `CHANGELOG.md` writes it that way (`52/151 -> 54/155`). A
    # bare `N/M` means nothing out of scope, so this one needs the scope phrase,
    # and `Phase 0/1` -- the one other `N/M` a scoped paragraph holds -- is a
    # roadmap phase pair, not a figure.
    CensusFigureFamily(
        "corpus files / records as N/M",
        r"(?<![\d,./-])(?<![Pp]hase )(\d+)/(\d+)(?![\d/])",
        True,
        (("files",), ("records",)),
        "Over the tracked corpus: 99/999.",
        (99, 999),
    ),
    CensusFigureFamily(
        "corpus records in a ratio",
        r"of (?:the )?(\d+) tracked (?:corpus )?records\b"
        r"|of (?:the )?(\d+) records carry\b",
        False,
        (("records",),),
        "of the 999 tracked corpus records, 99 carry a `span_id`",
        (999,),
    ),
    CensusFigureFamily(
        "records carrying a span id",
        r"(?<![\d,./-])(\d+) of (?:the )?\d+ (?:tracked )?(?:corpus )?records carry "
        r"(?:one|a span_id)"
        r"|(?<![\d,./-])(\d+) carry a span_id"
        r"|(?<![\d,./-])(\d+) (?:records? )?carrying a span[ _]id",
        False,
        (("with_span_id",),),
        "of the 999 tracked corpus records, 99 carry a `span_id`",
        (99,),
    ),
    CensusFigureFamily(
        "trace-unique span ids",
        r"(?<![\d,./-])(\d+) of those (?:are )?trace-unique"
        r"|(?<![\d,./-])(\d+) of (?:the )?\d+ tracked records take rule 1"
        r"|(?<![\d,./-])(\d+) trace-unique\b",
        False,
        (("trace_unique_span_id",),),
        "and 99 of those are trace-unique",
        (99,),
    ),
    CensusFigureFamily(
        "records claimed by both dialects' markers",
        r"(?<![\d,./-])(\d+) (?:records? )?carry(?:ing)? both (?:dialects' )?markers",
        False,
        (("records_claimed_by_two_adapters",),),
        "99 records carry both markers.",
        (99,),
    ),
    CensusFigureFamily(
        "records claimed by neither dialect's markers",
        r"(?<![\d,./-])(\d+) records? carry neither\b",
        False,
        (("records_claimed_by_no_adapter",),),
        "99 records carry neither.",
        (99,),
    ),
    CensusFigureFamily(
        "files carrying both dialects",
        r"(?<![\d,./-])(\d+) (?:corpus )?files?,? (?:now )?carr(?:y|ies) "
        r"(?:records of both|both dialects|both markers)",
        False,
        (("mixed_files",),),
        "99 files carry records of both",
        (99,),
    ),
    CensusFigureFamily(
        "single-dialect files",
        r"(?<![\d,./-])(\d+) are (?:openinference|otel_genai)-only",
        False,
        (("sole_dialect_files",),),
        "99 are `openinference`-only and 99 are `otel_genai`-only",
        (99,),
    ),
    CensusFigureFamily(
        "dialect claims",
        r"(?<![\d,./-])(\d+) records?(?:\(s\))? claimed by (\d+) adapters?",
        True,
        (("claims",), ("claims.keys",)),
        "Over the tracked corpus: 999 records claimed by 9 adapters.",
        (999, 9),
    ),
    CensusFigureFamily(
        "marker-scan disagreements",
        r"(?<![\d,./-])(\d+) disagreements?\b",
        True,
        (("marker_disagreements",),),
        "Over the tracked corpus: 99 disagreements.",
        (99,),
    ),
    CensusFigureFamily(
        "captured files",
        r"(?<![\d,./-])(\d+) captured (?:trace )?files?\b",
        True,
        (("captured_file_count", "captured_receipts.files"),),
        "Over the tracked corpus: 99 captured trace files.",
        (99,),
    ),
    CensusFigureFamily(
        "corpus `*.jsonl` files",
        r"(?:carries|holds) (\d+) \.jsonl files",
        True,
        (("jsonl_files", "head_scan.files"),),
        "A checkout carries 99 `*.jsonl` files (tracked files only).",
        (99,),
    ),
    # `50 -> 52 tracked *.jsonl` (S3's recount) and the census's own
    # `52 tracked *.jsonl` lines. Self-naming, so read everywhere: the words
    # *tracked `*.jsonl`* are the scope. Either count may be meant -- the
    # corpus's `*.jsonl` and every one in the tree are both 52 today.
    CensusFigureFamily(
        "tracked `*.jsonl` files",
        r"(?<![\d,./-])(\d+) tracked \.jsonl\b",
        False,
        (("jsonl_files", "head_scan.files"),),
        "99 tracked `*.jsonl` files.",
        (99,),
    ),
    CensusFigureFamily(
        "timestamp literals",
        r"(?<![\d,./-])(\d+) timestamp (?:values|literals)\b",
        True,
        (("timestamps.literals", "captured_timestamps.literals"),),
        "Over the tracked corpus: 99 timestamp values.",
        (99,),
    ),
    CensusFigureFamily(
        "timestamp literals above the unit ceiling",
        r"(?<![\d,./-])(\d+) above 1e\+?11"
        r"|(?<![\d,./-])(\d+) of the tracked corpus's \d+ timestamp literals sit "
        r"above",
        True,
        (("timestamps.above_ceiling", "captured_timestamps.above_ceiling"),),
        "Over the tracked corpus: 99 above 1e11.",
        (99,),
    ),
    CensusFigureFamily(
        "literals differing from their shortest float repr",
        r"(?<![\d,./-])(\d+) whose shortest float repr differs"
        r"|(?<![\d,./-])(\d+) literals that differ from it",
        True,
        (
            (
                "timestamps.differing_from_shortest_repr",
                "captured_timestamps.differing_from_shortest_repr",
            ),
        ),
        "Over the tracked corpus: 99 whose shortest float repr differs.",
        (99,),
    ),
    CensusFigureFamily(
        "floats carrying two literals",
        r"(?<![\d,./-])(\d+) pairs? of distinct literals collapsing"
        r"|(?<![\d,./-])(\d+) floats? carry(?:ing)? two",
        True,
        (
            (
                "timestamps.floats_carrying_two_literals",
                "captured_timestamps.floats_carrying_two_literals",
            ),
        ),
        "Over the tracked corpus: 99 pairs of distinct literals collapsing.",
        (99,),
    ),
    CensusFigureFamily(
        "sibling pairs",
        r"(?<![\d,./-])(\d+) sibling pairs\b",
        True,
        (("timestamps.sibling_pairs", "captured_timestamps.sibling_pairs"),),
        "Over the tracked corpus: 99 sibling pairs.",
        (99,),
    ),
    CensusFigureFamily(
        "minimum sibling gap",
        r"minimum gap (?:of )?(\d+) µs",
        True,
        (
            (
                "timestamps.minimum_sibling_gap_us",
                "captured_timestamps.minimum_sibling_gap_us",
            ),
        ),
        "Over the tracked corpus: minimum gap 99 µs.",
        (99,),
    ),
    CensusFigureFamily(
        "`data` edges",
        r"(?<![\d,./-])(\d+) data edges\b",
        True,
        (("captured_receipts.data_edges",),),
        "Over the tracked corpus: 99 `data` edges.",
        (99,),
    ),
    CensusFigureFamily(
        "files producing a `data` edge",
        r"(?<![\d,./-])(\d+) of (?:the )?\d+ (?:captured )?files? produce a data edge"
        r"|(?<![\d,./-])(\d+) files? with data edges",
        True,
        (("captured_receipts.files_with_data_edges",),),
        "Over the tracked corpus: 99 of 99 captured files produce a `data` edge.",
        (99,),
    ),
    CensusFigureFamily(
        "re-declared receipts",
        r"(?<![\d,./-])(\d+) re-declarations?\b"
        r"|(?<![\d,./-])(\d+) re-declared receipts?\b",
        True,
        (("captured_receipts.redeclared_receipts",),),
        "Over the tracked corpus: 99 re-declarations.",
        (99,),
    ),
    CensusFigureFamily(
        "tracked `*.jsonl` head scan",
        r"(?<![\d,./-])(\d+) of (\d+) tracked \.jsonl",
        True,
        (
            ("head_scan.beginning_with_brace", "head_scan.first_member_key_trace_id"),
            ("head_scan.files",),
        ),
        "Over the tracked corpus: 99 of 999 tracked `*.jsonl` files begin with `{`.",
        (99, 999),
    ),
    CensusFigureFamily(
        "lines of an indented export",
        r"(?<![\d,./-])(\d+) lines, (\d+) of them not JSON",
        True,
        (
            ("indented_exports[].lines",),
            ("indented_exports[].lines_that_are_not_json",),
        ),
        "Over the tracked corpus: 99 lines, 999 of them not JSON.",
        (99, 999),
    ),
    CensusFigureFamily(
        "`malformed_record` diagnostics for an indented export",
        r"(?<![\d,./-])(\d+) malformed_record\b"
        r"|malformed_record (?:diagnostic )?per line \((\d+)"
        r"|(?<![\d,./-])(\d+) of them for the indented export"
        r"|(?<![\d,./-])(\d+) times for",
        True,
        (("indented_exports[].lines_that_are_not_json",),),
        "Over the tracked corpus: 99 `malformed_record` diagnostics.",
        (99,),
    ),
)

#: What marks a paragraph as counting the corpus rather than reasoning about
#: it. Every sentence R5 and R9 rewrote carries one of these, because stating
#: the scope was half of what those batches were for.
CENSUS_SCOPE = (
    "tracked files only",
    "tracked corpus",
    "checkout carries",
    "checkout now carries",
    "tracked .jsonl",
)

#: The figures that were measured over a working tree and no longer recompute,
#: by family. A durable document may still *name* one -- five commit bodies
#: carry them and cannot be rewritten -- so this test allows the value and
#: leaves the "say it is history" half to
#: `test_no_durable_document_asserts_a_retired_figure_in_a_live_sentence`,
#: which is derived from this dict (batch S9), and to
#: `test_no_durable_document_states_the_working_tree_census_as_a_fact` for the
#: bare spellings of the working-tree pair no family reads (`177` alone). The
#: tests divide the work: those say a retired figure must be marked as
#: history, this one says a figure that is neither the census's nor retired is
#: simply wrong.
RETIRED_CENSUS_FIGURES: dict[str, set[tuple[int, ...]]] = {
    # `57 files / 177 records` was the working-tree scan; `43 files / 117
    # records` was what git tracked at the time and `14 files / 60 records` the
    # git-ignored `capture/_scratch/` difference between them (batch R5).
    #
    # `52 files / 151 records` was the tracked corpus from batch R5 until batch
    # S3 added the two `empty_ids` renderings. It is retired rather than
    # rewritten because the sentences that still hold it are `CHANGELOG.md`
    # entries recording what a *past* batch asserted: R5 really did move the
    # documents to 52/151, and saying it moved them to 54/155 would be a
    # falsification rather than a correction. Every present-tense citation was
    # recomputed in S3's commit. A **new** live sentence stating 52/151 passes
    # this scan; it fails the derived history test, unless the sentence itself
    # names a batch or says it is history -- the standing price of the
    # retirement mechanism, stated here rather than left to be discovered.
    "corpus files / records": {(57, 177), (43, 117), (14, 60), (52, 151)},
    # The same pair, quoted as a ratio: `0 of 117 tracked corpus records`
    # (`TASKS.md`) and `177 of 177` (`OPEN_QUESTIONS.md` §12(f)'s provenance).
    # `151` joins them for the reason above (batch S3).
    "corpus records in a ratio": {(117,), (177,), (151,)},
    # The same pairs in the census's `N/M` spelling (batch S9 gave it a
    # family; S3's recount sentence and the provenance notes write them so).
    #
    # `54/155` was the tracked corpus from batch S3 until batch S10 added the
    # two `empty_link_target` renderings, and S3's `CHANGELOG.md` entry
    # records it in this spelling; retired for the reason `52/151` was.
    "corpus files / records as N/M": {
        (57, 177),
        (43, 117),
        (14, 60),
        (52, 151),
        (54, 155),
    },
    # R5's pair of span-id figures, superseded by S3's two records: an empty
    # `span_id` is no span id (`SPEC.md` §3.6), so the corpus went 139 -> 141
    # carrying one and 135 -> 137 trace-unique while gaining two records that
    # carry neither.
    #
    # S3's own pair, superseded the same way by S10's four records, all of
    # which state a usable span id: 141 -> 145 carrying one, 137 -> 141
    # trace-unique. S3's `CHANGELOG.md` entry records the pair it measured.
    "records carrying a span id": {(139,), (141,)},
    "trace-unique span ids": {(135,), (137,)},
    # C3 said "the 17 captured trace files"; D2 said 15 (batch R9).
    "captured files": {(17,), (15,)},
    # S3 measured 308 over the tracked corpus; S10's four records add 8.
    "timestamp literals": {(154,), (308,)},
    "sibling pairs": {(41,)},
    "minimum sibling gap": {(81,)},
    "`data` edges": {(24,)},
    # F1's `64 of 64` counted `*.jsonl` files a checkout does not carry, and
    # R9's `50 of 50` was the tracked count until S3 added two renderings.
    "tracked `*.jsonl` head scan": {(64, 64), (50, 50)},
    "corpus `*.jsonl` files": {(64,)},
    # Both, in the `N tracked *.jsonl` spelling batch S9 gave a family.
    # S3's `52` joins them: S10 added two renderings.
    "tracked `*.jsonl` files": {(64,), (50,), (52,)},
    # F1's `46` counted the lines of an export `probe1.py` never committed.
    "`malformed_record` diagnostics for an indented export": {(46,)},
}


def census_figures(
    paragraph: str, scoped: bool | None = None
) -> list[tuple[str, tuple[int, ...]]]:
    """Every corpus figure a paragraph asserts, by family, in reading order.

    `paragraph` is raw markdown: emphasis and code spans are stripped here, so
    that `**52** files / **151** records`, a table cell, and a plain sentence
    are all read as one claim. That is the half of R5's guard the run-3 review
    called weak -- a figure is bold in at least one of the places it appears.

    `scoped` overrides the scope test, for a caller reading one sentence of a
    paragraph whose scope phrase sits in another sentence.
    """
    text = flat(unemphasized(paragraph))
    if scoped is None:
        scoped = any(marker in text for marker in CENSUS_SCOPE)
    found: list[tuple[str, tuple[int, ...]]] = []
    for family in CENSUS_FIGURE_FAMILIES:
        if family.requires_scope and not scoped:
            continue
        for match in re.finditer(family.pattern, text):
            found.append(
                (family.name, tuple(int(group) for group in match.groups() if group))
            )
    return found


def stated_census_figures(counted: Census) -> dict[str, set[tuple[int, ...]]]:
    """What each family's numbers are, over the tracked tree, derived.

    A family gets a *set*, not a value, because a slot may legitimately hold
    more than one of the census's figures: the whole tracked corpus and the
    captured subset are both in the documents at once, and the head scan's two
    counts share a spelling. The set is the product of the slots, so a
    two-number family accepts exactly the combinations the census produces.
    """
    counts = figures(counted)
    stated: dict[str, set[tuple[int, ...]]] = {}
    for family in CENSUS_FIGURE_FAMILIES:
        options = [
            sorted({value for name in slot for value in counts[name]})
            for slot in family.slots
        ]
        stated[family.name] = {tuple(values) for values in itertools.product(*options)}
    return stated


def test_every_figure_the_census_computes_is_guarded_by_a_family():
    """The gate the fixed list never had, and the reason this shape replaced it.

    Batch `audit-R9` widened doc-truth from "figures at listed *sites*" to "a
    corpus figure *anywhere*", and `TASKS.md` recorded the class as closed. It
    was not: `CENSUS_FIGURE_PATTERNS` was a hand-written list of eight regex
    families, and `tests/corpus_census.py` computed figures no family matched.
    The run-4 review planted wrong values for eighteen figures one at a time
    and **five stayed green** with the whole suite passing -- records carrying
    a span id, trace-unique span ids, and three zero-valued figures (review
    finding F1).

    A hand-written list cannot report what it omits. So the list of figures is
    no longer written down: `corpus_census.figure_names()` derives it from the
    `Census` type itself, and this test requires every derived name to appear
    in some family's slot. Adding a figure to the census now fails here until a
    family covers it, and a family may not name a figure the census does not
    compute -- which is the property that keeps the guard from narrowing again
    as the census grows.
    """
    computed = set(figure_names())
    guarded = {
        name
        for family in CENSUS_FIGURE_FAMILIES
        for slot in family.slots
        for name in slot
    }
    assert computed - guarded == set(), (
        "`tests/corpus_census.py` computes these figures and no family in "
        "`CENSUS_FIGURE_FAMILIES` matches any spelling of them, so a document "
        "may cite one and no test will ever recompute it: "
        + ", ".join(sorted(computed - guarded))
        + ". That is review finding F1 exactly -- add a family with the "
        "spelling the documents use, or, if the figure cannot be pinned by "
        "value, say so here rather than leaving it silently uncovered"
    )
    assert guarded - computed == set(), (
        "these families name a census figure that no longer exists, so they "
        "guard nothing and their `stated_census_figures` lookup would raise: "
        + ", ".join(sorted(guarded - computed))
    )


def test_the_census_computes_no_fractional_figure_without_a_stated_guard():
    """The one class a value-matching regex cannot reach, named rather than lost.

    A regex over a document matches digits, so a figure that is not a whole
    number cannot be pinned the way the rest are. `corpus_census` names every
    such figure and the whole-number figure that does pin it; this test holds
    that mapping to what the walk actually finds, so a **new** fractional
    figure fails here instead of becoming the next quiet gap.
    """
    assert set(fractional_figure_names()) == set(FRACTIONAL_FIGURES), (
        "the census's fractional figures are "
        f"{sorted(fractional_figure_names())} but `FRACTIONAL_FIGURES` names "
        f"{sorted(FRACTIONAL_FIGURES)}. A fractional figure is guarded only "
        "through a whole-number figure derived from it; say which one, or it "
        "is guarded by nothing"
    )


def test_every_corpus_figure_a_durable_document_asserts_is_the_census():
    """The sibling of the site-by-site tests above, scanned rather than listed.

    `test_the_open_questions_census_is_the_tracked_census` and
    `test_the_cited_corpus_figures_are_the_tracked_census` recompute the
    figures at the sites they name. The run-3 cold review showed what that
    leaves open: deliberately wrong pairs planted in `OPEN_QUESTIONS.md`
    §13(h), §14 and §14(h), in `CHANGELOG.md` twice and in `TASKS.md` note 7
    left every test in this file green, because those sites are not on either
    list -- so a copy of the census can rot in place exactly the way
    `57 files / 177 records` did, which is the defect batch R5 existed to end.

    This test names no site. It scans every durable document for a figure in
    one of the census's families and requires it to be a number the census
    computes, or one of the retired numbers above, which the drift test then
    requires to be marked as history. Adding a new sentence that cites the
    corpus therefore needs no test edit, and copying an old one somewhere new
    cannot outlive the number it copied.

    **What it does not do**, since the last widening of this guard was recorded
    more broadly than it held: it reads the *spellings* the families carry, not
    every number in every sentence. A figure written in words a family does not
    match is invisible here -- which is why every family carries an `example`
    that proves its pattern still reads the sentence it was written for, and
    why the family list is checked against the census rather than maintained by
    hand.
    """
    counted = census()
    stated = stated_census_figures(counted)
    offenders: list[str] = []
    for path in durable_documents():
        for paragraph in path.read_text(encoding="utf-8").split("\n\n"):
            if any(line.lstrip().startswith(">") for line in paragraph.splitlines()):
                continue
            for family, values in census_figures(paragraph):
                if values in stated[family] or values in RETIRED_CENSUS_FIGURES.get(
                    family, set()
                ):
                    continue
                offenders.append(
                    f"{path.relative_to(ROOT)} states {family} as "
                    f"{', '.join(str(value) for value in values)}; the census "
                    f"counts {sorted(stated[family])} -- "
                    f"{flat(unemphasized(paragraph))[:120]}"
                )
    assert not offenders, (
        "these paragraphs state a corpus figure that is neither what "
        "`tests/corpus_census.py` counts over the tracked tree nor a retired "
        "figure the documents quote as history:\n  " + "\n  ".join(offenders)
    )


# -- What the census prints is what the families read ------------------------
#
# The run-5 review planted four wrong figures in one `CHANGELOG.md` sentence --
# `52/151 -> 854/955`, `941 carrying a span id`, `937 trace-unique`,
# `50 -> 952 tracked *.jsonl` -- and the whole suite stayed green, while a fifth
# plant in the same sentence (`908 timestamp literals`) went red. Every one of
# the four figures had a family; none of the four *spellings* did. The gate
# above derives the figures from `Census`, so it cannot say which spellings a
# family misses: a hand-written family list is still a hand-written list of
# spellings, and it cannot report what it omits.
#
# The spelling a document copies first is the one the census prints. So the
# census's output is now data (`corpus_census.report`), and the two tests below
# derive from it: every figure the census computes is printed, and every figure
# printed is read back, under its own name, by a family. A printed figure no
# family reads fails here, in the census's own words, before any document has
# copied it.

#: A value no census figure takes and no document states, planted in place of
#: one printed figure at a time.
PRINTED_SENTINEL = 918273645


def printed_figures() -> list[tuple[int, int, Printed]]:
    """(line, position, figure) for every figure the census prints."""
    return [
        (row, column, part)
        for row, line in enumerate(report(census()))
        for column, part in enumerate(line)
        if isinstance(part, Printed)
    ]


def test_every_figure_the_census_computes_is_printed():
    """The half that makes the printed-spelling gate below reach every figure.

    A figure the census computes and does not print has no printed spelling,
    so the gate below would have nothing to derive a family from for it.
    """
    printed = {part.name for _, _, part in printed_figures()}
    computed = set(figure_names())
    assert computed - printed == set(), (
        "`tests/corpus_census.py` computes these figures and `report()` never "
        "prints them, so no printed spelling of them is held to a family: "
        + ", ".join(sorted(computed - printed))
    )
    assert printed - computed == set(), (
        "`report()` prints these under a name the census does not compute: "
        + ", ".join(sorted(printed - computed))
    )


def test_every_figure_the_census_prints_is_read_by_a_family():
    """Each printed figure, replaced by a sentinel, is read back under its name.

    One figure at a time, so that a line printing three figures proves all
    three rather than whichever one a family happens to reach. The line is
    read as a scope-stating paragraph, because the census's output *is* the
    tracked-corpus scope.
    """
    families = {family.name: family for family in CENSUS_FIGURE_FAMILIES}
    lines = report(census())
    unread: list[str] = []
    for row, column, part in printed_figures():
        planted = list(lines[row])
        planted[column] = Printed(part.name, PRINTED_SENTINEL)
        text = render(tuple(planted))
        read_back = any(
            value == PRINTED_SENTINEL and part.name in families[family].slots[index]
            for family, values in census_figures(text, scoped=True)
            for index, value in enumerate(values)
        )
        if not read_back:
            unread.append(f"{part.name} in {text.strip()!r}")
    assert not unread, (
        "the census prints these figures in a spelling no family in "
        "`CENSUS_FIGURE_FAMILIES` reads under that figure's name, so a "
        "document that copies the census's own words can state any value "
        "there and no test will recompute it:\n  " + "\n  ".join(unread)
    )


# -- A retired figure in a live sentence -------------------------------------
#
# `RETIRED_CENSUS_FIGURES` lets the scan above accept a superseded value, and
# the docstring there says the other half -- "a retired figure must be marked
# as history" -- belongs to
# `test_no_durable_document_states_the_working_tree_census_as_a_fact`. That
# test reads `WORKING_TREE_CENSUS`, a hand-written alternation over the
# *working-tree* values only; it never learned `139`, `135`, `151`, `50` or
# `64`, so the run-5 review planted `137 of the 155 -> 135` and
# `carries 52 -> 64` in `OPEN_QUESTIONS.md` and both stayed green (review
# finding 1.2). The check below is derived from the dict instead: a retired
# value is found by the family it is retired from, and is allowed only in a
# sentence that marks it as history.
#
# The unit is the *sentence*, not the paragraph. `OPEN_QUESTIONS.md`'s
# rule-1 line names batch R5 in the clause before the colon and states today's
# figure in the clause after it; a paragraph-wide marker would let the second
# clause state anything the dict holds. A figure written to the left of an
# arrow (`139 -> 141`) is the superseded side of a recount and is history by
# its spelling.

#: What marks a sentence as quoting a retired figure rather than asserting it.
#: `checkout` is not here, unlike in `CENSUS_HISTORY_MARKERS`: *"a checkout
#: carries"* is the live scope phrase every present-tense citation uses, so a
#: marker that matched it would exempt exactly the sentences this test is for.
#: The rest say, in the sentence itself, whose figure it was or when.
RETIRED_HISTORY_MARKERS = re.compile(
    "|".join(
        re.escape(marker)
        for marker in (*CENSUS_HISTORY_MARKERS, "history", "then-", "of the day")
        if marker != "checkout"
    )
    # A batch named in the sentence -- `R5 made`, `C3's sweep`, `audit-R9` --
    # attributes the figure to that batch's moment rather than to today.
    + r"|\b(?:audit-)?[A-Z]\d{1,2}\b"
)

#: A sentence ends at terminal punctuation or a semicolon followed by space;
#: `SPEC.md` and `3.6` are not boundaries. A colon is not one either: the
#: clause after a colon is usually the figure the clause before introduced.
SENTENCE_BOUNDARY = re.compile(r"(?<=[.;!?])\s+")

#: The superseded side of a recount: whatever sits immediately left of `->`.
LEFT_OF_AN_ARROW = re.compile(r"\S+\s*(?:->|→)\s*")


def retired_figures_asserted(
    paragraph: str, stated: dict[str, set[tuple[int, ...]]]
) -> list[tuple[str, tuple[int, ...], str]]:
    """(family, values, sentence) for each retired figure a paragraph asserts."""
    text = flat(unemphasized(paragraph))
    scoped = any(marker in text for marker in CENSUS_SCOPE)
    found: list[tuple[str, tuple[int, ...], str]] = []
    for sentence in SENTENCE_BOUNDARY.split(text):
        if RETIRED_HISTORY_MARKERS.search(sentence):
            continue
        for family, values in census_figures(
            LEFT_OF_AN_ARROW.sub("", sentence), scoped=scoped
        ):
            if values in stated[family]:
                continue
            if values in RETIRED_CENSUS_FIGURES.get(family, set()):
                found.append((family, values, sentence))
    return found


def test_every_retired_figure_is_one_its_family_reads_in_a_live_sentence():
    """Each value in `RETIRED_CENSUS_FIGURES`, planted, is caught.

    The derivation is only as wide as the families: a retired value its family
    cannot read would be accepted by nothing and flagged by nothing. So each
    one is planted into its family's own example sentence, which states no
    history, and must come back as a retired figure asserted live.
    """
    stated = stated_census_figures(census())
    families = {family.name: family for family in CENSUS_FIGURE_FAMILIES}
    missed: list[str] = []
    for name, retired in sorted(RETIRED_CENSUS_FIGURES.items()):
        family = families[name]
        for values in sorted(retired):
            swap = {
                str(old): str(new)
                for old, new in zip(family.example_values, values, strict=True)
            }
            planted = re.sub(
                r"(?<![\d.])\d+(?!\d|\.\d|e\d)",
                lambda match, swap=swap: swap.get(match.group(), match.group()),
                family.example,
            )
            if not any(
                (found, value) == (name, values)
                for found, value, _ in retired_figures_asserted(planted, stated)
            ):
                missed.append(f"{name} {values} in {planted!r}")
    assert not missed, (
        "these retired figures are not caught when a live sentence asserts "
        "them, so `RETIRED_CENSUS_FIGURES` accepts them everywhere and nothing "
        "requires them to be marked as history:\n  " + "\n  ".join(missed)
    )


def test_no_durable_document_asserts_a_retired_figure_in_a_live_sentence():
    """The history-marking half of the retirement, derived from the dict."""
    stated = stated_census_figures(census())
    offenders: list[str] = []
    for path in durable_documents():
        for paragraph in path.read_text(encoding="utf-8").split("\n\n"):
            if any(line.lstrip().startswith(">") for line in paragraph.splitlines()):
                continue
            for family, values, sentence in retired_figures_asserted(paragraph, stated):
                offenders.append(
                    f"{path.relative_to(ROOT)} states {family} as "
                    f"{', '.join(str(value) for value in values)}, a retired "
                    f"figure, in a sentence that does not say it is history -- "
                    f"{sentence[:160]}"
                )
    assert not offenders, (
        "these sentences assert a figure `RETIRED_CENSUS_FIGURES` retired, "
        "with nothing marking it as history; the census counts "
        "something else today:\n  " + "\n  ".join(offenders)
    )


def test_every_figure_family_still_reads_the_sentence_it_was_written_for():
    """Each family's regex, proven against the spelling it exists to match.

    A family that covers a census figure on paper and matches no sentence in
    practice is the same defect as no family at all, and it is invisible: the
    scan above reports what it finds, never what it failed to find. So every
    family carries one sentence with planted values and has to read it.
    """
    for family in CENSUS_FIGURE_FAMILIES:
        found = census_figures(family.example)
        assert (family.name, family.example_values) in found, (
            f"the {family.name} family no longer reads its own example "
            f"{family.example!r} as {family.example_values}; it read {found}. "
            f"A family that matches nothing guards nothing"
        )


def test_the_corpus_figure_scan_reads_emphasis_tables_and_separators():
    """The matcher, proven against the spellings the documents actually use.

    A guard that only matches one spelling of a figure is a guard that a
    reformatting silently disables, which is the run-3 review's second half of
    this finding. Bold, a table cell, and each separator the tree uses are all
    one claim, and a figure inside a scope-stating paragraph is read for every
    family.
    """
    for spelling in (
        "The corpus holds **99** files, **999** records.",
        "| corpus | 99 files / 999 records |",
        "scanned end to end — 99 files and 999 records",
        "a working tree of 99 trace files: 999 records",
        "`99` corpus files -- `999` records",
    ):
        assert ("corpus files / records", (99, 999)) in census_figures(spelling), (
            f"the corpus-pair scan does not read {spelling!r} as a claim about "
            f"the corpus, so a document may state it and no test will notice"
        )

    unscoped = (
        "A four-turn loop transcribing every earlier turn produces **888** "
        "`data` edges and **888** timestamp values, none of them counted over "
        "anything this repository carries."
    )
    assert not census_figures(unscoped), (
        "the scoped families were read out of a paragraph that never says "
        "which scope it counted, which is how a worked example becomes a "
        "false failure"
    )


# -- The digit limit is the library's, and the documents say so -------------
#
# Batch R14 named the interpreter's integer-string digit limit as an input to
# the graph; batch S8 removed the input (`SPEC.md` §5.3): the library owns a
# constant, counts digits against it, and builds one graph under every
# setting, measured in `tests/test_determinism.py`. What is held here is that
# the documents say the second thing and have stopped saying the first --
# advice to pin the setting would now be advice to do something pointless, and
# a reader following it would conclude the guarantee still needs it.

#: What each document that states the rule must name.
DIGIT_LIMIT_SPELLINGS = ("PYTHONINTMAXSTRDIGITS", "sys.get_int_max_str_digits")


def test_the_determinism_section_states_the_librarys_digit_limit():
    from spanweave.jsoncodec import DIGIT_LIMIT

    determinism = section(read("SPEC.md"), "\n## 5. Determinism")
    stated = f"`DIGIT_LIMIT` in\n`spanweave/jsoncodec.py` is **{DIGIT_LIMIT}**"
    assert stated in determinism, (
        f"SPEC.md §5.3 does not state the library's digit limit as "
        f"{DIGIT_LIMIT}, which is what `spanweave/jsoncodec.py` applies"
    )
    for spelling in DIGIT_LIMIT_SPELLINGS:
        assert spelling in determinism, (
            f"SPEC.md §5 does not name {spelling!r}: the section has to say "
            f"which interpreter setting the guarantee no longer depends on"
        )


def test_the_environment_contract_names_the_setting_it_does_not_depend_on():
    runtime = section(read("ENVIRONMENT.md"), "\n## Runtime")
    for spelling in DIGIT_LIMIT_SPELLINGS:
        assert spelling in runtime, (
            f"ENVIRONMENT.md's Runtime section does not name {spelling!r}; a "
            f"reader who knows the interpreter setting exists looks there for "
            f"whether it matters"
        )


@pytest.mark.parametrize("document", ["SPEC.md", "README.md", "ENVIRONMENT.md"])
def test_no_document_tells_a_caller_to_pin_the_digit_limit(document):
    from spanweave.jsoncodec import DIGIT_LIMIT

    text = read(document)
    for retired in (
        f"PYTHONINTMAXSTRDIGITS={DIGIT_LIMIT}",
        "input to the graph",
        "not the input bytes",
    ):
        assert retired not in text, (
            f"{document} still says {retired!r}. Since batch S8 the digit "
            f"limit is the library's constant and no interpreter setting "
            f"changes a graph (`SPEC.md` §5.3)"
        )


def test_no_test_hard_codes_the_digit_limit_it_is_supposed_to_derive():
    """The defect R14 fixed, kept fixed.

    R1's seven digit-limit tests wrote 4300 and 5000 as constants and every
    one of them went red on a legally configured interpreter. Since S8 the
    boundary is the library's constant; a test that writes it down stops
    testing the rule the day the constant moves, and a test that moves the
    interpreter's limit by hand can leave the process changed for every test
    after it.
    """
    helper = "tests/digit_limit.py"
    literal = re.compile(r"""["']9["']\s*\*\s*\d{3,}""")
    # Spelled in halves so the gate does not match its own source: this file
    # is a test file, and it is not exempt from the rule it enforces.
    moves_it = "sys.set_int_max_str_" + "digits("
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            assert not literal.search(line), (
                f"{path.name}:{number} hard-codes a digit-limit boundary: "
                f"{line.strip()!r}. The boundary is the library's constant "
                f"(`SPEC.md` §5.3); derive it through {helper}"
            )
            assert moves_it not in line, (
                f"{path.name}:{number} moves the interpreter's digit limit "
                f"directly: {line.strip()!r}. It is process-wide; a test that "
                f"needs another setting runs a subprocess under "
                f"PYTHONINTMAXSTRDIGITS, as `tests/test_determinism.py` does"
            )


# -- The exit codes and the failure line, held to the CLI --------------------
#
# Run-3 review F4. Exit codes lived in a comment in `spanweave/cli.py` and
# nowhere a reader looks; the error `code` §3.10 makes a public contract never
# reached stderr at all. Both are documented now, and both are recomputed here
# rather than restated -- a documented exit code that the CLI stopped using is
# the failure this whole file exists for.


def exit_codes_the_cli_uses():
    """Every status `spanweave` can exit with, read off the CLI itself.

    `2` is argparse's, not this library's, so it is obtained the way a caller
    would meet it: by making the usage error and reading what argparse chose.
    """
    from spanweave.cli import EXIT_FAILED, EXIT_OK, main

    with pytest.raises(SystemExit) as usage:
        main(["no-such-subcommand"])
    return {EXIT_OK, EXIT_FAILED, int(usage.value.code or 0)}


def exit_code_rows(text):
    """The first column of every `| \\`0\\` |`-shaped row in some markdown."""
    return {int(found) for found in re.findall(r"^\|\s*`(\d+)`\s*\|", text, re.M)}


def test_the_documents_state_every_exit_code_the_cli_uses():
    used = exit_codes_the_cli_uses()
    assert used == {0, 1, 2}, (
        f"the CLI exits with {sorted(used)}. That is a change to a documented "
        f"contract (`SPEC.md` §7, *Exit codes*), so the tables move with it"
    )
    for where, heading in (
        ("README.md", "\n## Exit codes"),
        ("SPEC.md", "\n### Exit codes"),
    ):
        text = read(where)
        assert heading in text, (
            f"{where} no longer has an {heading.strip()} section. Exit codes "
            f"lived only in a source comment once; that is what F4 found"
        )
        documented = exit_code_rows(section(text, heading))
        assert documented == used, (
            f"{where}'s exit-code table states {sorted(documented)} and the "
            f"CLI exits with {sorted(used)}"
        )


def test_the_readme_shows_the_failure_line_the_cli_actually_prints(tmp_path, capsys):
    """The transcript under *Exit codes*, run rather than believed.

    The README shows one refusal in full because the bracket is the whole
    point of the section, and a shown line nobody runs is how the quickstart
    came to open with a file that did not exist (`tests/readme_quickstart.py`).
    Wrapping is not part of the claim, so both sides are flattened; everything
    else -- the code, the adapters, their declared confidence -- is compared
    exactly, and is whatever the library says today.
    """
    from spanweave.cli import main

    body = section(read("README.md"), "\n## Exit codes")
    fences = re.findall(r"^```\n(.*?)^```", body, re.M | re.S)
    transcripts = [fence for fence in fences if fence.lstrip().startswith("$ ")]
    assert len(transcripts) == 1, (
        "the README's Exit codes section no longer shows exactly one "
        "transcript, so this test is comparing something other than the line "
        "a reader is shown"
    )
    lines = transcripts[0].splitlines()
    argv = shlex.split(lines[0][2:])[1:]
    assert argv[0] == "build", argv
    named = argv[-1]
    trace = tmp_path / named
    trace.write_text('{"hello":"world"}\n', encoding="utf-8")

    assert main([*argv[:-1], str(trace)]) == 1
    printed = flat(capsys.readouterr().err)
    shown = flat("\n".join(lines[1:])).replace(named, str(trace))
    assert printed == shown, (
        f"the README shows\n  {shown}\nand the CLI prints\n  {printed}"
    )
