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
