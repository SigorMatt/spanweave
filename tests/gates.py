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
import sys
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
# 0.5 -- neutrality + layering gates (CLAUDE.md 1 and 6)
# --------------------------------------------------------------------------

# THE BANNED LIST. Maintained here and nowhere else (TASKS.md 0.5).
#
# Core assigns no roles, no severity, no risk, no cost, and no quality
# judgement. That is the product, not a preference: the library is depend-able
# precisely because it takes no position (CLAUDE.md 1). Semantics arrive as
# vocabulary long before they arrive as logic, so the vocabulary is what is
# gated -- in identifiers AND in string literals, because a string literal is
# how a judgement reaches a consumer.
#
# Matching is substring and case-insensitive, so `severity`, `Severity`, and
# `max_severity` all fail. That is deliberate: a gate with a clever exemption
# rule is a gate someone will argue with.
#
# A deliberate exception requires a spec change, and there are none. The one
# collision found so far -- `Diagnostic.severity` in SPEC.md 3.7 -- was
# resolved by renaming the field to `level` rather than by carving a hole here,
# because an absolute gate is worth more than a word.
#
# These belong to consumers, and `examples/` (outside the package) is free to
# use every one of them (DESIGN.md 8).
SEMANTIC_VOCABULARY = (
    "severity",
    "risk",
    "secret",
    "sensitive",
    "sink",
    "taint",
    "vulnerab",
    "attack",
    "malicious",
    "threat",
    "cost",
    "price",
    "usd",
    "score",
    "quality",
    "hallucinat",
)

# Dialect ids. Legal under spanweave/adapters/ and nowhere else: the builder
# owns graphs and must never learn a dialect name (DESIGN.md 3). The rule is
# scoped by MODULE, not by syntax, because a lexical scan is fooled by a
# dialect-keyed dict inside the builder -- the shape of this check matters as
# much as its existence (TASKS.md 0.5).
DIALECT_IDS = (
    "openinference",
    "otel",
    "langfuse",
    "langsmith",
    "logfire",
    "vercel",
)


def _identifiers(tree: ast.AST) -> Iterator[tuple[str, int, str]]:
    """Every name a module defines or mentions, with its line."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id, node.lineno, "identifier"
        elif isinstance(node, ast.Attribute):
            yield node.attr, node.lineno, "attribute"
        elif isinstance(node, ast.arg):
            yield node.arg, node.lineno, "argument"
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.name, node.lineno, "definition"
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield node.arg, node.lineno, "keyword"
        elif isinstance(node, ast.alias):
            yield node.name, node.lineno, "import"
            if node.asname is not None:
                yield node.asname, node.lineno, "import"
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            yield node.name, node.lineno, "except name"


def _string_literals(tree: ast.AST) -> Iterator[tuple[str, int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno, "string literal"


def neutrality(path: str, source: str, tree: ast.AST) -> list[Violation]:
    found = []
    for text, line, what in [*_identifiers(tree), *_string_literals(tree)]:
        lowered = text.lower()
        for word in SEMANTIC_VOCABULARY:
            if word in lowered:
                found.append(
                    Violation(
                        "neutrality",
                        path,
                        line,
                        f"{what} carries the semantic word {word!r}; core "
                        f"assigns no such judgement -- it belongs in a "
                        f"consumer (CLAUDE.md 1)",
                    )
                )
    return found


def _under_adapters(path: str) -> bool:
    parts = pathlib.PurePath(path).parts
    return "adapters" in parts


def no_dialect_outside_adapters(
    path: str, source: str, tree: ast.AST
) -> list[Violation]:
    """A dialect id anywhere in the package but `adapters/` is a seam breach.

    Scanned lexically over the whole file, comments included: the builder
    mentioning a dialect *at all* is the smell this catches, and a comment is
    where the first one usually appears.
    """
    if _under_adapters(path):
        return []
    found = []
    for number, line in enumerate(source.splitlines(), start=1):
        lowered = line.lower()
        for dialect in DIALECT_IDS:
            if dialect in lowered:
                found.append(
                    Violation(
                        "no-dialect-in-builder",
                        path,
                        number,
                        f"names the dialect {dialect!r} outside "
                        f"spanweave/adapters/; below the seam nothing knows a "
                        f"dialect exists (DESIGN.md 3)",
                    )
                )
    return found


NEUTRALITY_RULES = (neutrality, no_dialect_outside_adapters)


# --------------------------------------------------------------------------
# 0.8 -- the dependency gate (ENVIRONMENT.md, CLAUDE.md coding conventions)
# --------------------------------------------------------------------------


def zero_dependencies(path: str, source: str, tree: ast.AST) -> list[Violation]:
    """Core imports the standard library and itself. Nothing else.

    "Zero runtime dependencies" is a hard constraint, not a current state
    (`DESIGN.md` §7): a library meant to sit underneath other people's tools
    must not drag a tree into them. Adding one is a halt point (`AGENT.md`),
    so it is worth more than a line in `pyproject.toml` that nothing reads.
    """
    found = []
    for imported, line in _imported_modules(tree):
        top = imported.split(".")[0]
        if top in ("spanweave", "__future__") or top in sys.stdlib_module_names:
            continue
        found.append(
            Violation(
                "zero-dependencies",
                path,
                line,
                f"imports {top!r}, which is neither the standard library nor "
                f"spanweave itself; core has zero runtime dependencies and "
                f"adding one is a halt point (ENVIRONMENT.md)",
            )
        )
    return found


ALL_RULES = (*SAFETY_RULES, *NEUTRALITY_RULES, zero_dependencies)


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
