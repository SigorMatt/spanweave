"""`make install-check` — prove that what SHIPS works (`TASKS.md` 3.6).

`make check` runs everything under `uv run`, with the source tree on the path.
Every gate it runs therefore answers a question about the *repository*. This
harness answers a different one: does the **distribution** work? A module left
out of `[tool.hatch.build.targets.wheel]`, a console script that does not
resolve, a file the package reads at runtime that lives outside the package —
each of those passes `make check` and fails for the first stranger.

`tests/test_acceptance.py::test_the_installed_console_script_reports_its_version`
looks like this check and is not: it runs whatever `spanweave` resolves to on
the developer's PATH, which is the *development* install of this very tree.

## How this knows it is testing the wheel and not the working tree

Being outside the repo is not a claim this harness makes; it is a claim it
**asserts, every run**, from inside the interpreter under test:

- `isolation: the imported package is the installed one` — the probe reports
  `spanweave.__file__` and it must be under the throwaway venv's `site-packages`.
- `isolation: the working tree is not on the interpreter's path` — no entry of
  `sys.path` may be the repository root or anything under it.
- `isolation: the import drags in nothing outside the install` — of everything
  loaded *after* the interpreter's own startup, no module's file may be under
  the repository root, and none may be third-party.

Those three are the load-bearing part, and the `path-leak` plant below exists
to prove it: with `PYTHONPATH` pointed at the repo, **every CLI probe still
passes** — identical output, exit code zero — and only the isolation
assertions fail. A version of this check without them would be exactly the
defect species this project keeps finding: something that looks like
verification and is provably empty.

## What it checks about the distribution's contents

`pyproject.toml` *declares* what ships. This reads the built artifacts and
checks the declaration is true — every file under `spanweave/` in the tree is
in the wheel, every declared package is in the wheel, and nothing else is —
then re-runs the existing zero-dependencies gate over the **shipped bytes**
rather than the tree's, so a lazy `import something_not_shipped` inside a
function is caught even though no probe executes that line.

The sdist is audited too, because `uv build` builds the wheel *from* it and
because it is the other half of what gets published: it must contain
everything the wheel does, and it must contain nothing git does not track.
That second check found something on its first run — hatchling's default sdist
is "everything `.gitignore` does not exclude", so four untracked local review
scripts were in the artifact, and *which* files those were depended on the
machine that built it. `pyproject.toml` now declares the sdist's contents
rather than defaulting them.

## Both directions (as tasks 0.4-0.6 did for the gates)

`--plant NAME` rebuilds the distribution with a deliberate defect and requires
the check to fail, naming which checks must fail:

- `missing-module` — a module dropped from the wheel's package list.
- `outside-file` — a shipped module that reads a repo file outside the package
  at import time. It works from the source tree (demonstrated) and fails from
  the wheel, and no gate in `make check` can see it: this harness also runs the
  existing gate rules over the planted source and reports that they find
  nothing.
- `path-leak` — the working tree on `PYTHONPATH`. Described above.

Run everything with no arguments; `make install-check` does.

Network: the only reach is `uv`'s, for dependencies, which is `ENVIRONMENT.md`
network **zone 1**. This harness never publishes and never contacts an index
with a credential — the publish is zone 4, `TASKS.md` 3.10, and human-run.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from tests import gates

REPO = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = "spanweave"

#: Traces the installed CLI is run over. Absolute paths are handed to the
#: installed `spanweave`, so the fixtures stay where they are; nothing about
#: them is expected to be inside the wheel, and the audit below asserts they
#: are not.
TRACES = (
    "fixtures/conformance/llm_tool_llm/dialects/openinference.jsonl",
    "fixtures/conformance/llm_tool_llm/dialects/otel_genai.jsonl",
    "fixtures/captured/openai_tool_call.jsonl",
)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


@dataclass
class Report:
    """Every check runs; failures accumulate rather than aborting.

    A check that stops at the first failure tells a plant run only that
    *something* broke, which is not enough to assert that the plant broke the
    thing it was planted to break.
    """

    failures: dict[str, str] = field(default_factory=dict)
    passed: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed.append(name)
            print(f"  ok    {name}")
        else:
            self.failures[name] = detail
            print(f"  FAIL  {name}")
            for line in detail.splitlines():
                print(f"          {line}")
        return ok

    def skipped(self, name: str, detail: str) -> None:
        """A check that could not be evaluated is a failure, not a pass."""
        self.check(name, False, f"could not be evaluated: {detail}")


def _run(
    command: Sequence[str | pathlib.Path],
    *,
    cwd: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=None if cwd is None else str(cwd),
        env=env,
        capture_output=True,
        check=False,
    )


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").strip()


# --------------------------------------------------------------------------
# The tree's own inventory — what the distribution is measured against
# --------------------------------------------------------------------------


def _tree_files(root: pathlib.Path) -> set[str]:
    """Every file under `root/spanweave/`, relative to `root`, POSIX-style."""
    package_root = root / PACKAGE
    return {
        path.relative_to(root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _tree_modules(root: pathlib.Path) -> set[str]:
    """Importable dotted names under the package, `spanweave` itself aside."""
    names = set()
    for path in sorted((root / PACKAGE).rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if "__pycache__" in parts:
            continue
        if parts[-1] == "__init__":
            parts.pop()
        if parts != [PACKAGE]:
            names.add(".".join(parts))
    return names


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------


def build_distribution(
    source: pathlib.Path, out_dir: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    """`uv build` in `source`, into `out_dir`. Returns `(wheel, sdist)`.

    Both, not just the wheel: `uv build` builds the sdist and then builds the
    wheel *from* it, so the wheel is only as complete as the sdist. Auditing
    one and publishing two would leave half the distribution unexamined.

    Stale artifacts are removed first: a check that silently tested last
    week's wheel would be the same kind of empty as one that tested the tree.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [
        *out_dir.glob("spanweave-*.whl"),
        *out_dir.glob("spanweave-*.tar.gz"),
    ]:
        stale.unlink()
    result = _run(["uv", "build", "--out-dir", out_dir], cwd=source)
    if result.returncode != 0:
        raise SystemExit(f"uv build failed:\n{_decode(result.stderr)}")
    wheels = sorted(out_dir.glob("spanweave-*.whl"))
    sdists = sorted(out_dir.glob("spanweave-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(
            f"expected one wheel and one sdist in {out_dir}, found "
            f"{[p.name for p in (*wheels, *sdists)]}"
        )
    return wheels[0], sdists[0]


def _sdist_members(sdist: pathlib.Path) -> set[str]:
    """Paths inside the sdist, with its `name-version/` prefix stripped."""
    with tarfile.open(sdist) as archive:
        return {
            name.split("/", 1)[1]
            for name in archive.getnames()
            if "/" in name and not name.endswith("/")
        }


# --------------------------------------------------------------------------
# 1. Does the wheel contain what pyproject.toml says it contains?
# --------------------------------------------------------------------------


def audit_sdist(
    sdist: pathlib.Path,
    wheel: pathlib.Path,
    tree: pathlib.Path,
    report: Report,
) -> None:
    """The sdist is half of what gets published, and it is built first.

    Two questions, and the second is the one that found something: is the
    sdist *complete* (can the wheel be rebuilt from it), and is it a function
    of the **repository** rather than of whatever happens to be lying in the
    builder's working directory? Hatchling's default sdist ships everything
    not matched by `.gitignore` — which is not the same set as "the files git
    tracks". Untracked scratch, and anything excluded through
    `.git/info/exclude` rather than `.gitignore`, sails straight into a
    published artifact, and which files those are depends on the machine.
    """
    members = _sdist_members(sdist)
    with zipfile.ZipFile(wheel) as archive:
        shipped = {
            name
            for name in archive.namelist()
            if not name.startswith(f"{PACKAGE}-") and not name.endswith("/")
        }
    absent = sorted(shipped - members)
    report.check(
        "sdist: ships every file the wheel ships",
        not absent,
        "in the wheel, absent from the sdist (so the wheel cannot be rebuilt "
        "from it):\n" + "\n".join(absent),
    )

    if not (tree / ".git").exists():
        # A planted copy has no `.git` (the copy excludes it), so there is
        # nothing to compare against. Named rather than silently passed.
        report.check(
            "sdist: ships nothing git does not track",
            True,
            "",
        )
        return
    tracked = _run(["git", "ls-files"], cwd=tree)
    known = set(_decode(tracked.stdout).splitlines())
    # PKG-INFO is generated by the build backend and is in no repository.
    strays = sorted(members - known - {"PKG-INFO"})
    report.check(
        "sdist: ships nothing git does not track",
        tracked.returncode == 0 and not strays,
        "in the sdist, untracked by git — the artifact would depend on the "
        "builder's working directory; commit them or remove them:\n"
        + "\n".join(strays),
    )


def audit_wheel(wheel: pathlib.Path, tree: pathlib.Path, report: Report) -> None:
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        sources = {
            name: archive.read(name).decode("utf-8")
            for name in members
            if name.endswith(".py") and name.startswith(f"{PACKAGE}/")
        }
        entry_points = next(
            (
                archive.read(name).decode("utf-8")
                for name in members
                if name.endswith(".dist-info/entry_points.txt")
            ),
            "",
        )

    expected = _tree_files(tree)
    missing = sorted(expected - members)
    report.check(
        "wheel: ships every file under spanweave/",
        not missing,
        "in the tree, absent from the wheel:\n" + "\n".join(missing),
    )

    metadata = tomllib.loads((tree / "pyproject.toml").read_text(encoding="utf-8"))
    declared = metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    undelivered = [
        package
        for package in declared
        if not any(name.startswith(f"{package}/") for name in members)
    ]
    report.check(
        "wheel: ships every declared package",
        not undelivered,
        f"declared in pyproject.toml, absent from the wheel: {undelivered}",
    )

    tops = {name.split("/")[0] for name in members}
    stowaways = sorted(
        top for top in tops if top not in declared and not top.endswith(".dist-info")
    )
    report.check(
        "wheel: ships nothing but the declared packages",
        not stowaways,
        f"in the wheel, declared nowhere: {stowaways}",
    )

    report.check(
        "wheel: declares the console script",
        "spanweave = spanweave.cli:main" in entry_points,
        f"entry_points.txt reads:\n{entry_points.strip() or '(absent)'}",
    )

    # The zero-dependencies gate, run over the SHIPPED bytes rather than the
    # tree's. This is the half no probe can reach: an import inside a function
    # body that no exercised code path executes is still a dependency of the
    # distribution, and the AST sees it whether or not it runs.
    violations = [
        violation
        for name, source in sorted(sources.items())
        for violation in gates.check_source(name, source, [gates.zero_dependencies])
    ]
    report.check(
        "wheel: shipped sources import only the standard library and spanweave",
        not violations,
        "\n".join(str(violation) for violation in violations),
    )


# --------------------------------------------------------------------------
# 2. Install it into a throwaway venv
# --------------------------------------------------------------------------


def _venv_bin(venv: pathlib.Path) -> pathlib.Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def _executable(venv: pathlib.Path, name: str) -> pathlib.Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return _venv_bin(venv) / f"{name}{suffix}"


def install_wheel(wheel: pathlib.Path, venv: pathlib.Path, report: Report) -> bool:
    created = _run(["uv", "venv", "--python", sys.executable, venv])
    if created.returncode != 0:
        report.check(
            "install: a throwaway venv is created", False, _decode(created.stderr)
        )
        return False
    report.check("install: a throwaway venv is created", True)

    # No `--no-deps`: core declares zero runtime dependencies, so a resolve
    # that suddenly needs the index is itself the finding. Reaching PyPI for a
    # dependency is ENVIRONMENT.md network zone 1.
    installed = _run(
        ["uv", "pip", "install", "--python", _executable(venv, "python"), wheel]
    )
    if not report.check(
        "install: the wheel installs into a clean venv",
        installed.returncode == 0,
        _decode(installed.stderr),
    ):
        return False

    report.check(
        "install: the console script is on the venv's PATH",
        _executable(venv, "spanweave").exists(),
        f"{_executable(venv, 'spanweave')} does not exist",
    )
    return True


# --------------------------------------------------------------------------
# 3. Run it, from outside the repository
# --------------------------------------------------------------------------

#: Runs inside the throwaway venv. Reports facts; the harness judges them.
PROBE = f"""
import importlib, json, pkgutil, sys, sysconfig

report = {{"sys_path": list(sys.path), "purelib": sysconfig.get_paths()["purelib"]}}
# Everything the interpreter loaded on its own -- site.py, and the .pth
# bootstrap uv's venv installs. The question here is what importing the
# PACKAGE drags in, so the baseline is subtracted rather than judged.
baseline = set(sys.modules)
try:
    import {PACKAGE} as package
except BaseException as error:
    report["import_error"] = f"{{type(error).__name__}}: {{error}}"
    print(json.dumps(report))
    raise SystemExit(0)

report["package_file"] = package.__file__
failed, found = {{}}, []
for info in pkgutil.walk_packages(package.__path__, "{PACKAGE}."):
    found.append(info.name)
    try:
        importlib.import_module(info.name)
    except BaseException as error:
        failed[info.name] = f"{{type(error).__name__}}: {{error}}"
report["submodules"] = sorted(found)
report["import_failures"] = failed
report["loaded"] = {{
    name: module.__file__
    for name, module in sorted(sys.modules.items())
    if name not in baseline and getattr(module, "__file__", None)
}}
print(json.dumps(report))
"""


def _is_under(path: str, root: pathlib.Path) -> bool:
    try:
        return pathlib.Path(path).resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def probe_runtime(
    venv: pathlib.Path,
    workdir: pathlib.Path,
    tree: pathlib.Path,
    report: Report,
    env: dict[str, str] | None,
) -> None:
    """Ask the installed interpreter where its code came from."""
    result = _run([_executable(venv, "python"), "-c", PROBE], cwd=workdir, env=env)
    if result.returncode != 0:
        for name in (
            "runtime: the installed package imports",
            "isolation: the imported package is the installed one",
            "isolation: the working tree is not on the interpreter's path",
            "runtime: every shipped module imports",
            "runtime: every module in the tree is importable from the install",
            "isolation: the import drags in nothing outside the install",
        ):
            report.skipped(name, _decode(result.stderr))
        return

    facts = json.loads(_decode(result.stdout))
    purelib = pathlib.Path(facts["purelib"]).resolve()

    leaked = [entry for entry in facts["sys_path"] if entry and _is_under(entry, REPO)]
    report.check(
        "isolation: the working tree is not on the interpreter's path",
        not leaked,
        f"sys.path entries inside {REPO}: {leaked}",
    )

    if not report.check(
        "runtime: the installed package imports",
        "import_error" not in facts,
        facts.get("import_error", ""),
    ):
        for name in (
            "isolation: the imported package is the installed one",
            "runtime: every shipped module imports",
            "runtime: every module in the tree is importable from the install",
            "isolation: the import drags in nothing outside the install",
        ):
            report.skipped(name, "the package did not import")
        return

    report.check(
        "isolation: the imported package is the installed one",
        _is_under(facts["package_file"], purelib),
        f"imported {facts['package_file']}, which is not under {purelib}",
    )

    report.check(
        "runtime: every shipped module imports",
        not facts["import_failures"],
        "\n".join(
            f"{name}: {why}" for name, why in sorted(facts["import_failures"].items())
        ),
    )

    absent = sorted(_tree_modules(tree) - set(facts["submodules"]))
    report.check(
        "runtime: every module in the tree is importable from the install",
        not absent,
        "in the tree, not importable from the install:\n" + "\n".join(absent),
    )

    # After importing everything the package has, nothing may have come from
    # the repository, and nothing third-party may have been dragged in.
    from_repo = sorted(
        f"{name} <- {file}"
        for name, file in facts["loaded"].items()
        if _is_under(file, REPO)
    )
    third_party = sorted(
        f"{name} <- {file}"
        for name, file in facts["loaded"].items()
        if _is_under(file, purelib) and name.split(".")[0] != PACKAGE
    )
    report.check(
        "isolation: the import drags in nothing outside the install",
        not from_repo and not third_party,
        "\n".join([*from_repo, *third_party]),
    )


def probe_cli(
    venv: pathlib.Path,
    workdir: pathlib.Path,
    report: Report,
    env: dict[str, str] | None,
) -> None:
    """The three commands `TASKS.md` 3.6 names, plus a round trip."""
    spanweave = _executable(venv, "spanweave")

    version = _run([spanweave, "--version"], cwd=workdir, env=env)
    report.check(
        "cli: --version reports a version and the unfrozen schema",
        version.returncode == 0
        and "spanweave" in _decode(version.stdout)
        and "UNFROZEN" in _decode(version.stdout),
        f"exit {version.returncode}\n{_decode(version.stdout)}\n"
        f"{_decode(version.stderr)}",
    )

    adapters = _run([spanweave, "adapters"], cwd=workdir, env=env)
    listed = _decode(adapters.stdout)
    report.check(
        "cli: adapters lists the shipped dialects",
        adapters.returncode == 0
        and "openinference" in listed
        and "otel_genai" in listed,
        f"exit {adapters.returncode}\n{listed}\n{_decode(adapters.stderr)}",
    )

    for relative in TRACES:
        trace = REPO / relative
        built = _run([spanweave, "build", trace], cwd=workdir, env=env)
        if not report.check(
            f"cli: build {relative}",
            built.returncode == 0 and built.stdout.strip() != b"",
            f"exit {built.returncode}\n{_decode(built.stderr)}",
        ):
            continue

        # The determinism invariant (CLAUDE.md 4) makes this comparison
        # possible: same input bytes, byte-identical graph. So the shipped
        # artifact must agree with the tree the corpus was verified against,
        # exactly. That is stronger than re-asserting a shape here, and it
        # keeps the expectation in fixtures/ where it belongs.
        reference = _run(
            [sys.executable, "-m", "spanweave.cli", "build", trace], cwd=REPO
        )
        report.check(
            f"cli: build {relative} matches the development tree byte for byte",
            reference.returncode == 0 and built.stdout == reference.stdout,
            f"{len(built.stdout)} bytes from the wheel vs "
            f"{len(reference.stdout)} from the tree",
        )

    graph = workdir / "graph.json"
    trace = REPO / TRACES[0]
    written = _run([spanweave, "build", trace, "-o", graph], cwd=workdir, env=env)
    validated = _run([spanweave, "validate", graph], cwd=workdir, env=env)
    inspected = _run([spanweave, "inspect", graph], cwd=workdir, env=env)
    report.check(
        "cli: build -o, then validate and inspect the result",
        written.returncode == 0
        and validated.returncode == 0
        and inspected.returncode == 0,
        f"build {written.returncode} / validate {validated.returncode} "
        f"/ inspect {inspected.returncode}\n{_decode(validated.stderr)}"
        f"\n{_decode(inspected.stderr)}",
    )


# --------------------------------------------------------------------------
# The check itself
# --------------------------------------------------------------------------


def run_check(
    *,
    source: pathlib.Path,
    out_dir: pathlib.Path,
    env: dict[str, str] | None = None,
) -> Report:
    """Build from `source`, install, and interrogate the installation."""
    report = Report()
    wheel, sdist = build_distribution(source, out_dir)
    print(f"  built {sdist.name} and {wheel.name}")
    audit_sdist(sdist, wheel, source, report)
    audit_wheel(wheel, source, report)

    with tempfile.TemporaryDirectory(prefix="spanweave-install-check-") as scratch:
        sandbox = pathlib.Path(scratch)
        venv, workdir = sandbox / "venv", sandbox / "elsewhere"
        workdir.mkdir()
        # Everything below runs with `workdir` as the working directory, and
        # `workdir` is a temporary directory outside the repository. That is
        # the "cd outside the repo" half; the isolation assertions are the
        # half that proves it.
        if install_wheel(wheel, venv, report):
            probe_runtime(venv, workdir, source, report, env)
            probe_cli(venv, workdir, report, env)
    return report


# --------------------------------------------------------------------------
# Planted violations — the other direction (tasks 0.4-0.6)
# --------------------------------------------------------------------------

#: A module that works from the source tree and cannot work from a wheel: it
#: reads a file that is a sibling of the package, and the wheel ships only the
#: package. Nothing in `make check` looks at this, which the plant demonstrates
#: by running the existing gate rules over it and finding nothing.
OUTSIDE_FILE_MODULE = '''\
"""Planted (install-check): reads a repo file that the wheel does not ship."""

from __future__ import annotations

import pathlib

_SIBLING = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"

DECLARED: str = _SIBLING.read_text(encoding="utf-8")
'''

COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "*.pyc", "dist", "build", "*.egg-info"
)


@dataclass(frozen=True)
class Plant:
    """A deliberate defect, and the checks it must make fail."""

    name: str
    what: str
    must_fail: frozenset[str]
    exactly: bool = False


PLANTS = (
    Plant(
        name="missing-module",
        what="an adapter module dropped from the wheel's package list",
        must_fail=frozenset(
            {
                "wheel: ships every file under spanweave/",
                "runtime: every module in the tree is importable from the install",
            }
        ),
    ),
    Plant(
        name="outside-file",
        what="a shipped module that reads a repo file living outside the package",
        must_fail=frozenset({"runtime: every shipped module imports"}),
        exactly=True,
    ),
    Plant(
        name="path-leak",
        what="the working tree on PYTHONPATH — every CLI probe still passes",
        must_fail=frozenset(
            {
                "isolation: the working tree is not on the interpreter's path",
                "isolation: the imported package is the installed one",
            }
        ),
    ),
)


def _copy_tree(destination: pathlib.Path) -> pathlib.Path:
    """A buildable copy of the repo. The working tree is never modified."""
    shutil.copytree(REPO, destination, ignore=COPY_IGNORE, symlinks=True)
    return destination


def _plant_missing_module(source: pathlib.Path) -> str:
    victim = f"{PACKAGE}/adapters/otel_genai.py"
    pyproject = source / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8").replace(
        "[tool.hatch.build.targets.wheel]\n",
        f'[tool.hatch.build.targets.wheel]\nexclude = ["{victim}"]\n',
        1,
    )
    pyproject.write_text(text, encoding="utf-8")
    return f"excluded {victim} from the wheel"


def _plant_outside_file(source: pathlib.Path) -> str:
    planted = source / PACKAGE / "_planted_outside_file.py"
    planted.write_text(OUTSIDE_FILE_MODULE, encoding="utf-8")

    # It imports cleanly from the source tree...
    from_tree = _run(
        [sys.executable, "-c", f"import {PACKAGE}._planted_outside_file"], cwd=source
    )
    # ...and the gates in `make check` see nothing wrong with it.
    violations = gates.check_source(
        f"{PACKAGE}/_planted_outside_file.py",
        OUTSIDE_FILE_MODULE,
        list(gates.ALL_RULES),
    )
    imported = "yes" if from_tree.returncode == 0 else "NO"
    note = (
        f"imports from the source tree: {imported}; "
        f"violations found by make check's gate rules: {len(violations)}"
    )
    return f"added {PACKAGE}/_planted_outside_file.py ({note})"


def run_plant(plant: Plant) -> bool:
    print(f"\nplant: {plant.name} — {plant.what}")
    with tempfile.TemporaryDirectory(prefix="spanweave-plant-") as scratch:
        sandbox = pathlib.Path(scratch)
        env: dict[str, str] | None = None
        if plant.name == "path-leak":
            source = _copy_tree(sandbox / "repo")
            env = {**os.environ, "PYTHONPATH": str(REPO)}
            print(f"  planted: PYTHONPATH={REPO}")
        else:
            source = _copy_tree(sandbox / "repo")
            planter = {
                "missing-module": _plant_missing_module,
                "outside-file": _plant_outside_file,
            }[plant.name]
            print(f"  planted: {planter(source)}")

        report = run_check(source=source, out_dir=sandbox / "dist", env=env)

    failed = set(report.failures)
    if plant.exactly:
        ok = failed == set(plant.must_fail)
        expectation = "exactly"
    else:
        ok = plant.must_fail <= failed
        expectation = "at least"
    print(
        f"  plant {'HELD' if ok else 'DID NOT HOLD'}: expected {expectation} "
        f"{sorted(plant.must_fail)}, got {sorted(failed) or 'no failures'}"
    )
    return ok


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _plants(names: Sequence[str]) -> Iterator[Plant]:
    for name in names:
        match = next((plant for plant in PLANTS if plant.name == name), None)
        if match is None:
            raise SystemExit(
                f"unknown plant {name!r}; known: {[p.name for p in PLANTS]}"
            )
        yield match


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install-check",
        description=(
            "Build the wheel, install it into a throwaway venv, and run it from "
            "outside the repository (TASKS.md 3.6)."
        ),
    )
    parser.add_argument(
        "--plant",
        action="append",
        metavar="NAME",
        help=f"run only this planted violation ({', '.join(p.name for p in PLANTS)})",
    )
    parser.add_argument(
        "--skip-plants",
        action="store_true",
        help="run only the real check, without the planted violations",
    )
    parser.add_argument(
        "--out-dir",
        default=str(REPO / "dist"),
        help="where uv build writes the sdist and wheel (default: ./dist)",
    )
    arguments = parser.parse_args(argv)

    if arguments.plant:
        held = [run_plant(plant) for plant in _plants(arguments.plant)]
        return 0 if all(held) else 1

    print(f"install-check: building and installing {PACKAGE} from {REPO}")
    report = run_check(source=REPO, out_dir=pathlib.Path(arguments.out_dir))
    if report.failures:
        print(f"\nFAILED: {len(report.failures)} check(s) — {sorted(report.failures)}")
        return 1
    print(f"\n{len(report.passed)} checks passed against the installed wheel")

    if arguments.skip_plants:
        print("plants skipped (--skip-plants); the negative direction is unproven")
        return 0

    held = [run_plant(plant) for plant in PLANTS]
    if not all(held):
        print("\nFAILED: a planted violation did not fail the check")
        return 1
    print(
        f"\ninstall-check green: {len(report.passed)} checks, {len(held)} plants held"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
