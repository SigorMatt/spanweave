"""The acceptance harness (TASKS.md 0.8), and the checks that keep it honest.

`make check` is the gate a change must pass. That makes its *composition* a
thing worth testing: a gate silently dropped from the harness is indis-
tinguishable from a gate that passes. These tests read the Makefile and the CI
workflow and assert that the harness still runs what it claims to run.

They also assert the two Phase 0 claims that no other test covers: the
installed console script works, and core imports nothing but the standard
library.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

from tests import gates

REPO = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _recipe(target: str) -> str:
    """The prerequisites and commands of one Makefile target."""
    lines = MAKEFILE.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"{target}:"):
            body = [line]
            for following in lines[index + 1 :]:
                if following and not following.startswith(("\t", " ", "#")):
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"the Makefile has no {target!r} target")


# --------------------------------------------------------------------------
# The harness runs what it says it runs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("prerequisite", ["lint", "types", "test", "gates"])
def test_check_depends_on_every_stage(prerequisite):
    assert prerequisite in _recipe("check").splitlines()[0]


def test_check_smoke_tests_the_installed_entrypoint():
    assert "spanweave --version" in _recipe("check")


def test_lint_checks_formatting_as_well_as_rules():
    recipe = _recipe("lint")
    assert "ruff check" in recipe
    assert "ruff format --check" in recipe


def test_types_runs_mypy_over_the_package():
    assert "mypy spanweave" in _recipe("types")


def test_gates_runs_the_gate_suites():
    recipe = _recipe("gates")
    # 0.4/0.5 live in test_gates.py, 0.6 in test_determinism.py. Both are
    # named explicitly so that a failure says which invariant broke rather
    # than "some test failed".
    assert "tests/test_gates.py" in recipe
    assert "tests/test_determinism.py" in recipe


def test_ci_runs_the_same_harness_rather_than_its_own():
    assert "uv sync --extra dev" in WORKFLOW
    assert "make check" in WORKFLOW


def test_ci_still_covers_every_supported_python():
    # A library underneath other people's tools must not narrow their runtime
    # (ENVIRONMENT.md).
    for version in ("3.11", "3.12", "3.13"):
        assert f'"{version}"' in WORKFLOW


# --------------------------------------------------------------------------
# The other harness: what SHIPS, not what the tree does (TASKS.md 3.6)
# --------------------------------------------------------------------------


def test_install_check_builds_and_runs_the_distribution():
    assert "tests.install_check" in _recipe("install-check")


def test_install_check_is_not_folded_into_check():
    # `check` is the fast gate a task must pass; install-check builds a wheel
    # and a venv. They also answer different questions, and merging them would
    # make a slow gate out of the one that has to run constantly. CI runs both.
    assert "install-check" not in _recipe("check").splitlines()[0]


def test_ci_runs_install_check_as_well_as_check():
    # The packaging break that install-check exists to catch passes every
    # other gate, so CI running only `make check` would leave it uncaught
    # until a stranger hit it.
    assert "make install-check" in WORKFLOW


def test_install_check_asserts_its_own_isolation():
    """The check must not merely *be* outside the tree — it must say so.

    A wheel check that runs with the repository on `sys.path` passes for the
    wrong reason and is indistinguishable from one that works. These three
    assertions are what make the harness non-vacuous, and `--plant path-leak`
    is what proves they are live; this test is here so that deleting one of
    them fails a gate rather than quietly emptying the check.
    """
    source = (REPO / "tests/install_check.py").read_text(encoding="utf-8")
    for claim in (
        "isolation: the working tree is not on the interpreter's path",
        "isolation: the imported package is the installed one",
        "isolation: the import drags in nothing outside the install",
    ):
        assert claim in source


def test_install_check_plants_a_violation_for_each_direction_it_claims():
    from tests import install_check

    assert {plant.name for plant in install_check.PLANTS} == {
        "missing-module",
        "outside-file",
        "path-leak",
        # `TASKS.md` 3.11, amendment 1: the wheel embeds `README.md` in
        # `METADATA`, so editing the README changes the wheel. A record twice
        # claimed otherwise and sent the next publisher into a stop-and-find-out
        # over an expected difference. The plant redirects pyproject's `readme`
        # and must fail that check and nothing else.
        "readme-decoupled",
    }
    # A plant that expects nothing to fail would "hold" against a check that
    # does nothing at all.
    assert all(plant.must_fail for plant in install_check.PLANTS)


def test_the_sdist_contents_are_declared_rather_than_defaulted():
    """Hatchling's default sdist is a function of the builder's directory.

    It ships everything `.gitignore` does not exclude — which is not the set
    of files this repository tracks. Four untracked local review scripts were
    in the artifact before this was declared (TASKS.md 3.6).
    """
    import tomllib

    metadata = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    sdist = metadata["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert "/spanweave" in sdist["include"]


# --------------------------------------------------------------------------
# What ships actually runs
# --------------------------------------------------------------------------


def test_the_installed_console_script_reports_its_version():
    """The *development* install, and only that.

    `shutil.which` resolves to whatever is on this environment's PATH, which
    under `uv run` is this very tree. So this proves the entrypoint is wired
    up; it proves nothing about the distribution. `make install-check` is the
    check that does (TASKS.md 3.6), and it is a separate target because the
    resemblance between the two is exactly what made this one look sufficient.
    """
    executable = shutil.which("spanweave")
    command = [executable] if executable else [sys.executable, "-m", "spanweave.cli"]
    result = subprocess.run(
        [*command, "--version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "spanweave" in result.stdout
    assert "UNFROZEN" in result.stdout


# --------------------------------------------------------------------------
# Zero runtime dependencies
# --------------------------------------------------------------------------


def test_core_imports_nothing_but_the_standard_library():
    found = gates.check_package([gates.zero_dependencies])
    assert found == [], "\n".join(str(v) for v in found)


@pytest.mark.parametrize(
    "source", ["import yaml", "from pydantic import BaseModel", "import networkx as nx"]
)
def test_the_dependency_gate_fails_on_a_planted_import(source):
    found = gates.check_source(
        "spanweave/planted.py", source, [gates.zero_dependencies]
    )
    assert [v.rule for v in found] == ["zero-dependencies"]


def test_pyproject_declares_no_runtime_dependencies():
    import tomllib

    metadata = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["dependencies"] == []
