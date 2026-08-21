"""The invariant gates (TASKS.md 0.4-0.6), each watched failing.

Every gate is asserted twice: once against a **planted violation** -- a
synthetic module that deliberately breaks it -- and once against the real
package. The first assertion is the one that matters. A gate that has only
ever been seen passing is indistinguishable from a gate that cannot fail.

Rule implementations live in `tests/gates.py`.
"""

import pytest

from tests import gates

# --------------------------------------------------------------------------
# 0.4 -- safety gates
# --------------------------------------------------------------------------

PLANTED_NETWORK = [
    ("import socket", "socket"),
    ("import requests", "requests"),
    ("import httpx as client", "httpx"),
    ("from urllib.request import urlopen", "urllib.request"),
    ("from http.client import HTTPSConnection", "http.client"),
    ("import aiohttp", "aiohttp"),
]

PLANTED_UNSAFE = [
    ("import pickle", "pickle"),
    ("import marshal", "marshal"),
    ("from subprocess import run", "subprocess"),
    ("value = eval(payload)", "eval"),
    ("exec(payload)", "exec"),
    ("mod = __import__(name)", "__import__"),
    ("os.system(payload)", "os.system"),
    ("value = yaml.load(payload)", "yaml.load"),
]

PLANTED_HASH = [
    "bucket = hash(node_id)",
    "ordered = sorted(nodes, key=lambda n: hash(n.id))",
]


@pytest.mark.parametrize(("source", "expected"), PLANTED_NETWORK)
def test_no_network_gate_fails_on_a_planted_violation(source, expected):
    found = gates.check_source("planted.py", source, [gates.no_network])
    assert [v.rule for v in found] == ["no-network"]
    assert expected in found[0].detail


@pytest.mark.parametrize(("source", "expected"), PLANTED_UNSAFE)
def test_no_unsafe_gate_fails_on_a_planted_violation(source, expected):
    found = gates.check_source("planted.py", source, [gates.no_unsafe])
    assert [v.rule for v in found] == ["no-unsafe"]
    assert expected in found[0].detail


@pytest.mark.parametrize("source", PLANTED_HASH)
def test_no_hash_gate_fails_on_a_planted_violation(source):
    found = gates.check_source("planted.py", source, [gates.no_hash])
    assert [v.rule for v in found] == ["no-hash"]


def test_safety_gates_pass_on_things_that_merely_look_alike():
    # The gates must not fire on a docstring, a comment, or an identifier that
    # merely contains a banned word -- otherwise the first false positive gets
    # them switched off, which is worse than not having them.
    innocent = "\n".join(
        [
            '"""Reads sockets? No: this module reads files. Never calls eval."""',
            "# no pickle here either",
            "def hash_free_ordering(nodes):",
            "    return sorted(nodes, key=lambda n: n.id)",
            "digest = sha256(data).hexdigest()",
        ]
    )
    assert gates.check_source("innocent.py", innocent, gates.SAFETY_RULES) == []


def test_package_has_no_network_no_unsafe_and_no_hash():
    found = gates.check_package(gates.SAFETY_RULES)
    assert found == [], "\n".join(str(v) for v in found)


def test_the_gates_actually_scanned_something():
    # A gate that silently scans zero files passes forever. This is the
    # tripwire for that.
    assert len(gates.package_files()) >= 3


# --------------------------------------------------------------------------
# 0.5 -- neutrality + layering gates
# --------------------------------------------------------------------------

PLANTED_SEMANTICS = [
    # An identifier is how a judgement gets computed...
    ("def risk_of(node):\n    return 1", "risk"),
    ("max_severity = 3", "severity"),
    ("def rank(n):\n    return n.score", "score"),
    ("TOTAL_COST_USD = 0.0", "cost"),
    # ...and a string literal is how it reaches a consumer.
    ('LABELS = ["sensitive", "trusted"]', "sensitive"),
    ('ROLE = "sink"', "sink"),
    ('def note():\n    """Marks a tainted payload."""', "taint"),
    ('KIND = "malicious"', "malicious"),
]


@pytest.mark.parametrize(("source", "expected"), PLANTED_SEMANTICS)
def test_neutrality_gate_fails_on_a_planted_violation(source, expected):
    found = gates.check_source("spanweave/planted.py", source, [gates.neutrality])
    assert [v.rule for v in found] == ["neutrality"]
    assert expected in found[0].detail


def test_neutrality_gate_is_case_insensitive():
    found = gates.check_source(
        "spanweave/planted.py", 'LEVEL = "Severity"', [gates.neutrality]
    )
    assert len(found) == 1


def test_neutrality_gate_covers_every_banned_word():
    # A word silently dropped from the list is a hole nobody would notice, so
    # each one is exercised rather than trusted.
    for word in gates.SEMANTIC_VOCABULARY:
        source = f'MARKER = "{word}"'
        found = gates.check_source("spanweave/planted.py", source, [gates.neutrality])
        assert [v.rule for v in found] == ["neutrality"], word


def test_neutrality_gate_passes_on_neutral_vocabulary():
    neutral = "\n".join(
        [
            '"""Nodes, edges, warrants, payload states, diagnostics."""',
            "def level_of(diagnostic):",
            "    return diagnostic.level",
            'STATES = ("present", "empty", "absent", "redacted", "truncated")',
        ]
    )
    assert gates.check_source("spanweave/planted.py", neutral, [gates.neutrality]) == []


def test_package_carries_no_semantic_vocabulary():
    found = gates.check_package([gates.neutrality])
    assert found == [], "\n".join(str(v) for v in found)


PLANTED_DIALECT = [
    'ADAPTER_ID = "openinference"',
    "# fall back to the otel span id here",
    'TABLE = {"langfuse": _one, "langsmith": _two}',
    'if source == "logfire":\n    pass',
    'NAME = "vercel"',
]


@pytest.mark.parametrize("source", PLANTED_DIALECT)
def test_dialect_gate_fails_when_the_builder_names_a_dialect(source):
    found = gates.check_source(
        "spanweave/build.py", source, [gates.no_dialect_outside_adapters]
    )
    assert found and all(v.rule == "no-dialect-in-builder" for v in found)


@pytest.mark.parametrize("source", PLANTED_DIALECT)
def test_dialect_gate_permits_the_same_source_under_adapters(source):
    # The rule is scoped by module, not by syntax: dialect knowledge is not
    # forbidden, it is *located*. The identical line is legal one directory
    # over -- which is the whole design (DESIGN.md §3).
    found = gates.check_source(
        "spanweave/adapters/some_dialect.py",
        source,
        [gates.no_dialect_outside_adapters],
    )
    assert found == []


def test_dialect_gate_catches_a_dialect_keyed_table_a_lexical_scan_would_miss():
    # The failure this gate exists for: not an `if adapter_id == "..."`, but a
    # table that looks like ordinary dispatch and quietly makes the builder
    # dialect-aware.
    source = "\n".join(
        [
            "HANDLERS = {",
            '    "openinference": _handle_a,',
            '    "langfuse": _handle_b,',
            "}",
        ]
    )
    found = gates.check_source(
        "spanweave/build.py", source, [gates.no_dialect_outside_adapters]
    )
    assert len(found) == 2


def test_package_names_no_dialect_outside_adapters():
    found = gates.check_package([gates.no_dialect_outside_adapters])
    assert found == [], "\n".join(str(v) for v in found)
