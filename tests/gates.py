"""The invariant gates, as reusable checks over source text.

These encode the parts of `CLAUDE.md` that a change can violate *while passing
every other test*: neutrality, no-network, no-unsafe-deserialization, no
`hash()`, and the adapter/builder seam. They are AST checks rather than greps
wherever the AST can see the thing, because a grep is fooled by a comment and
an AST is not.

The rules live here, separately from `test_gates.py`, so that each one can be
run against a **planted violation** -- a synthetic module that deliberately
breaks it -- as well as against the real package. A gate nobody has watched
fail is a gate nobody knows works.

This module is in `tests/`, not in `spanweave/`, on purpose: it necessarily
contains the very words it bans.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "spanweave"
ADAPTERS_DIR = PACKAGE_ROOT / "adapters"


@dataclass(frozen=True)
class Violation:
    """One gate failure, located precisely enough to fix."""

    rule: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}"


# --------------------------------------------------------------------------
# 0.4 -- safety gates (CLAUDE.md 4 and 5)
# --------------------------------------------------------------------------

# Core reads files and stdin and writes files and stdout. It never opens a
# socket, never fetches a URL, never listens. That claim is only worth making
# if it is structural (ENVIRONMENT.md, network zones).
NETWORK_MODULES = (
    "requests",
    "httpx",
    "socket",
    "urllib.request",
    "http.client",
    "aiohttp",
)

# Trace payloads are hostile input (SECURITY.md). Nothing in them is ever
# executed, imported, or deserialized into objects.
UNSAFE_MODULES = ("pickle", "marshal", "subprocess")
UNSAFE_CALLS = ("eval", "exec", "__import__", "os.system", "yaml.load")


def _dotted_name(node: ast.expr) -> str | None:
    """Render `os.system` / `yaml.load` / `eval` as a dotted string."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _imported_modules(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module, node.lineno
            for alias in node.names:
                yield f"{node.module}.{alias.name}", node.lineno


def _matches_module(imported: str, banned: str) -> bool:
    return imported == banned or imported.startswith(banned + ".")


def no_network(path: str, source: str, tree: ast.AST) -> list[Violation]:
    found = []
    for imported, line in _imported_modules(tree):
        for banned in NETWORK_MODULES:
            if _matches_module(imported, banned):
                found.append(
                    Violation(
                        "no-network",
                        path,
                        line,
                        f"imports {imported!r}; core opens no sockets, ever "
                        f"(CLAUDE.md 5)",
                    )
                )
    return found


def no_unsafe(path: str, source: str, tree: ast.AST) -> list[Violation]:
    found = []
    for imported, line in _imported_modules(tree):
        for banned in UNSAFE_MODULES:
            if _matches_module(imported, banned):
                found.append(
                    Violation(
                        "no-unsafe",
                        path,
                        line,
                        f"imports {imported!r}; trace content is never "
                        f"deserialized into objects or executed (SECURITY.md)",
                    )
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if name in UNSAFE_CALLS:
            found.append(
                Violation(
                    "no-unsafe",
                    path,
                    node.lineno,
                    f"calls {name}(); trace content is never executed (SECURITY.md)",
                )
            )
    return found


def no_hash(path: str, source: str, tree: ast.AST) -> list[Violation]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted_name(node.func) == "hash":
            found.append(
                Violation(
                    "no-hash",
                    path,
                    node.lineno,
                    "calls the builtin hash(); it is salted per process and "
                    "would silently break determinism across runs "
                    "(CLAUDE.md 4)",
                )
            )
    return found


SAFETY_RULES = (no_network, no_unsafe, no_hash)


# --------------------------------------------------------------------------
# Running a rule set
# --------------------------------------------------------------------------

Rule = Callable[[str, str, ast.AST], list[Violation]]


def check_source(path: str, source: str, rules: Sequence[Rule]) -> list[Violation]:
    """Run `rules` over one module's source. Used for planted violations too."""
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    seen: set[tuple[str, int]] = set()
    for rule in rules:
        for violation in rule(path, source, tree):
            # One violation per rule per line. `from urllib.request import
            # urlopen` matches the ban twice -- as a module and as a member --
            # and reporting it twice would say nothing extra.
            key = (violation.rule, violation.line)
            if key in seen:
                continue
            seen.add(key)
            found.append(violation)
    return found


def package_files() -> list[pathlib.Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def check_package(rules: Sequence[Rule]) -> list[Violation]:
    found: list[Violation] = []
    for file in package_files():
        relative = str(file.relative_to(PACKAGE_ROOT.parent))
        found.extend(check_source(relative, file.read_text(encoding="utf-8"), rules))
    return found
