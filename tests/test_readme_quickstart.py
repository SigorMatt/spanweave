"""The README's quickstart, run verbatim (`TASKS.md` 3.9).

Two altitudes, deliberately, because they answer different questions and the
cheap one must be in the gate every task runs:

* **Here** — against the source tree, inside `make check`. Answers *is the
  README's code correct?* A change to the CLI's output or to the query surface
  fails on the commit that makes it, not weeks later.
* **`tests/install_check.py`** — against the wheel installed into a throwaway
  venv, from a directory outside the repository, inside `make install-check`.
  Answers *does the path a stranger walks work?* That is the one 3.9 is really
  about, and it costs a build and a venv, which is why it is not here.

Neither asserts a **duration**. `make stranger` measures that, because a
wall-clock assertion in a test suite is a flake generator and would be tuned
until it stopped meaning anything -- and the exit criterion it would be
guarding ("~60 seconds") is a claim about a human's first minute, not about
this machine's load average. The steps are tested; the number is measured and
recorded at the task.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from tests.readme_quickstart import (
    README,
    ROOT,
    PythonBlock,
    ShellStep,
    normalize,
    python_blocks,
    shell_steps,
)


@pytest.fixture
def checkout(tmp_path: pathlib.Path) -> pathlib.Path:
    """A working directory that looks like a checkout, minus the source tree.

    The quickstart's paths are repo-relative, so they need `fixtures/`. They
    must **not** get `spanweave/`: with the package directory present, `python
    -c` would import the working tree and the run would say nothing about what
    is installed. That is not hypothetical -- it is what happens if a reader
    follows the README's own `cd spanweave && pip install .` and then runs the
    quickstart without leaving the directory.
    """
    (tmp_path / "fixtures").symlink_to(ROOT / "fixtures")
    return tmp_path


def _cli(step: ShellStep, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    assert step.argv[0] == "spanweave", (
        f"the quickstart runs {step.argv[0]!r}; this harness only knows the "
        f"`spanweave` console script"
    )
    # Combined, in stream order, because a README shell transcript shows what
    # a terminal shows. `spanweave build -o` writes "wrote <path>" to stderr
    # (the graph goes to stdout when no `-o` is given, so the notice must not
    # contaminate it) and a transcript that silently dropped it would be
    # showing the reader something their terminal will not.
    return subprocess.run(
        [sys.executable, "-m", "spanweave.cli", *step.argv[1:]],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def test_the_quickstart_actually_has_steps_to_run():
    # Non-vacuity: every test below iterates the parse, so an empty parse would
    # turn the whole file green while checking nothing. This is the shape 3.8
    # kept finding -- something that looks like coverage and is provably empty.
    assert len(shell_steps()) >= 2
    assert len(python_blocks()) >= 1
    assert all(block.expected for block in python_blocks())
    assert all(step.expected for step in shell_steps())


@pytest.mark.parametrize(
    "step", shell_steps(), ids=lambda step: step.argv[1] if step.argv else "?"
)
def test_each_shell_step_runs_and_prints_what_the_readme_shows(
    step: ShellStep, checkout: pathlib.Path
):
    result = _cli(step, checkout)
    assert result.returncode == 0, (
        f"`{step.command}` failed with exit {result.returncode}. The README is "
        f"wrong, not this test (TASKS.md 3.9).\n{result.stdout}"
    )
    assert normalize(result.stdout) == normalize(step.expected), (
        f"`{step.command}` printed something other than the README shows.\n"
        f"--- README ---\n{normalize(step.expected)}\n"
        f"--- actual ---\n{normalize(result.stdout)}"
    )


@pytest.mark.parametrize("block", python_blocks(), ids=lambda _: "quickstart")
def test_each_python_block_runs_and_prints_what_the_readme_shows(
    block: PythonBlock, checkout: pathlib.Path
):
    result = subprocess.run(
        [sys.executable, "-c", block.source],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"the README's Python block failed with exit {result.returncode}. The "
        f"README is wrong, not this test (TASKS.md 3.9).\n{result.stderr}"
    )
    assert normalize(result.stdout) == normalize(block.expected), (
        f"the README's Python block printed something else.\n"
        f"--- README ---\n{normalize(block.expected)}\n"
        f"--- actual ---\n{normalize(result.stdout)}"
    )


def test_the_checkout_path_matches_the_projects_own_metadata():
    """The two install steps a test *can* reach without a network.

    `git clone <url>` and `cd <dir>` cannot be executed here -- zone 2 is "no
    network, ever" and this suite is inside it. What can be checked is that the
    URL is the one the project declares and that the directory it produces is
    the one the next line changes into. Both are exactly the kind of claim that
    survives a rename of the repository by staying quietly wrong.
    """
    import tomllib

    readme = README.read_text(encoding="utf-8")
    block = readme[readme.index("From a checkout:") :]
    commands = [
        line[2:]
        for line in block[: block.index("```", block.index("```") + 3)].splitlines()
        if line.startswith("$ ")
    ]
    assert len(commands) == 3, f"the checkout path is no longer three steps: {commands}"

    clone, change, install = commands
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    homepage = metadata["project"]["urls"]["Homepage"]
    assert clone == f"git clone {homepage}", (
        f"the README clones {clone.removeprefix('git clone ')!r}; pyproject "
        f"declares the project lives at {homepage!r}"
    )
    assert change == f"cd {homepage.rstrip('/').rsplit('/', 1)[-1]}", (
        f"`{change}` does not enter the directory `{clone}` creates"
    )
    assert install.startswith("pip install"), install


def test_every_path_the_quickstart_names_is_a_file_that_ships():
    """The defect this task found, kept as a tripwire of its own.

    Both blocks read `trace.jsonl`. Nothing checked that the file existed
    because nothing ran the blocks, and a path that resolves on the author's
    machine and nowhere else is the same species: it would pass the runs above
    on a developer's laptop and fail for the stranger. So the paths are
    resolved against the repository explicitly, and each must be tracked --
    which is what makes "ships in this repository" true rather than hopeful.
    """
    quoted = {
        word.strip("\"'")
        for block in python_blocks()
        for word in block.source.split()
        if "fixtures/" in word
    } | {
        argument
        for step in shell_steps()
        for argument in step.argv
        if "fixtures/" in argument
    }
    assert quoted, "the quickstart names no fixture; the scan found nothing"
    tracked = subprocess.run(
        ["git", "ls-files", "fixtures"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for path in sorted(quoted):
        assert (ROOT / path).is_file(), (
            f"the quickstart names {path}, which is not a file"
        )
        assert path in tracked, (
            f"the quickstart names {path}, which git does not track -- so it "
            f"is not in the sdist and does not ship"
        )
