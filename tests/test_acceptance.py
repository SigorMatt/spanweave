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
# What ships actually runs
# --------------------------------------------------------------------------


def test_the_installed_console_script_reports_its_version():
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
