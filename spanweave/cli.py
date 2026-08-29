"""Command-line entrypoint (``spanweave``).

The CLI is the thinnest possible layer over the library: argument parsing and
I/O, nothing else (``DESIGN.md`` §2). It writes to stdout and to files the
caller named, and to nothing else.

``inspect``'s output is a human summary and is **not** a stable contract; the
graph file is. Everything it prints is a count of something the graph already
says, so nothing there is a judgement about the trace.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Iterable, Sequence

from spanweave import api, serialize
from spanweave.adapters import registered
from spanweave.errors import SpanweaveError
from spanweave.model import JsonValue
from spanweave.version import SCHEMA_FROZEN, SCHEMA_VERSION, __version__

# Exit codes. 0 success, 1 a refusal or an unimplemented path, 2 argparse's own
# usage error (argparse chooses that one, not us).
EXIT_OK = 0
EXIT_FAILED = 1

# While unfrozen, `schema_version` is one bucket for the whole of 0.x and does
# NOT track changes to the serialized graph (`SPEC.md` §3.9). Saying "pin your
# version" without saying WHICH one is how a reader ends up pinning the field
# that never moves, so the notice names the one that does.
_SCHEMA_NOTICE = (
    f"Graph schema version {SCHEMA_VERSION} is NOT FROZEN: it may change in any "
    "release before 1.0.0, and 0.x is a single bucket that does not track those "
    "changes. Pin on the spanweave version (meta.spanweave_version), not on "
    "schema_version."
    if not SCHEMA_FROZEN
    else f"Graph schema version {SCHEMA_VERSION}."
)

_DESCRIPTION = (
    "Normalize agentic-system execution telemetry into one deterministic, "
    "semantically neutral graph."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spanweave",
        description=_DESCRIPTION,
        epilog=_SCHEMA_NOTICE,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"spanweave {__version__} (graph schema {SCHEMA_VERSION}"
        + ("; UNFROZEN)" if not SCHEMA_FROZEN else ")"),
    )
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    build = subcommands.add_parser(
        "build",
        help="build a graph from a trace",
        description="Build a graph from a trace file, or from stdin with '-'.",
        epilog=_SCHEMA_NOTICE,
    )
    build.add_argument("trace", help="path to a trace file, or '-' for stdin")
    build.add_argument(
        "--adapter",
        metavar="ID",
        help="skip detection and use this adapter (see 'spanweave adapters')",
    )
    build.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="write the graph here instead of to stdout",
    )
    build.add_argument(
        "--no-temporal",
        action="store_true",
        help="omit derived temporal edges",
    )

    inspect = subcommands.add_parser(
        "inspect",
        help="summarize a trace or a built graph",
        description=(
            "Print a human summary: counts by node kind, edges by kind and "
            "warrant, diagnostics grouped by code. Informational; not a "
            "stable contract."
        ),
    )
    inspect.add_argument("path", help="a trace file or a built graph.json")
    inspect.add_argument(
        "--adapter",
        metavar="ID",
        help="skip detection and use this adapter (traces only)",
    )

    validate = subcommands.add_parser(
        "validate",
        help="check that a graph file is well-formed",
        description="Read a built graph and report whether it is well-formed.",
    )
    validate.add_argument("graph", help="path to a graph.json")

    subcommands.add_parser(
        "adapters",
        help="list the registered adapters",
        description="List every registered adapter with its own version.",
    )

    return parser


def _read_document(path: str) -> JsonValue | None:
    """A built graph, if that is what this file is. Otherwise ``None``.

    Told apart by content rather than by extension: a graph document is a
    single JSON object carrying a ``schema_version``. Anything else is a
    trace, and is handed to the reader, which knows two container formats.
    """
    if path == "-":
        return None
    try:
        document = json.loads(pathlib.Path(path).read_bytes())
    except (ValueError, OSError):
        return None
    if isinstance(document, dict) and "schema_version" in document:
        return document
    return None


def _do_build(args: argparse.Namespace) -> int:
    graph = api.build(args.trace, adapter=args.adapter, temporal=not args.no_temporal)
    if args.output:
        serialize.dump(graph, pathlib.Path(args.output))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(serialize.dumps(graph))
    return EXIT_OK


def _do_inspect(args: argparse.Namespace) -> int:
    document = _read_document(args.path)
    if document is None:
        graph = api.build(args.path, adapter=args.adapter)
        document = serialize.to_document(graph)
    for line in _summarize(document):
        print(line)
    return EXIT_OK


def _do_validate(args: argparse.Namespace) -> int:
    try:
        document = json.loads(pathlib.Path(args.graph).read_bytes())
    except ValueError as failure:
        print(f"{args.graph}: not valid JSON ({failure})", file=sys.stderr)
        return EXIT_FAILED
    problems = serialize.validate(document)
    for problem in problems:
        print(f"{args.graph}: {problem}", file=sys.stderr)
    if problems:
        return EXIT_FAILED
    print(f"{args.graph}: valid")
    return EXIT_OK


def _do_adapters(_: argparse.Namespace) -> int:
    for adapter in registered():
        print(f"{adapter.id}\t{adapter.version}")
    return EXIT_OK


def _summarize(document: JsonValue) -> list[str]:
    """Counts, and only counts. Informational, never a stable contract."""
    nodes = document.get("nodes", [])
    edges = document.get("edges", [])
    diagnostics = document.get("diagnostics", [])
    meta = document.get("meta") or {}

    lines = [
        f"trace: {document.get('trace_id') or '(none reported)'}",
        f"schema: {document.get('schema_version')}"
        + ("  (NOT FROZEN)" if not SCHEMA_FROZEN else ""),
        "adapters: "
        + (
            ", ".join(
                f"{a.get('id')} {a.get('version')}" for a in meta.get("adapters", [])
            )
            or "(none)"
        ),
        "",
        f"nodes: {len(nodes)}",
    ]
    lines.extend(_tally("  ", (str(node.get("kind")) for node in nodes)))

    lines.append(f"edges: {len(edges)}")
    lines.extend(
        _tally(
            "  ",
            (f"{edge.get('kind')} ({edge.get('warrant')})" for edge in edges),
        )
    )

    lines.append("payloads:")
    lines.extend(
        _tally(
            "  inputs  ", (str(node.get("inputs", {}).get("state")) for node in nodes)
        )
    )
    lines.extend(
        _tally(
            "  outputs ", (str(node.get("outputs", {}).get("state")) for node in nodes)
        )
    )

    lines.append(f"diagnostics: {len(diagnostics)}")
    lines.extend(_tally("  ", (str(item.get("code")) for item in diagnostics)))
    return lines


def _tally(indent: str, values: Iterable[str]) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [f"{indent}{name}: {counts[name]}" for name in sorted(counts)]


COMMANDS = {
    "build": _do_build,
    "inspect": _do_inspect,
    "validate": _do_validate,
    "adapters": _do_adapters,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    try:
        return COMMANDS[args.command](args)
    except SpanweaveError as failure:
        # The deliberate refusals: an ambiguous input, a duplicate id. They
        # are messages, not tracebacks -- the caller can act on them.
        print(f"spanweave {args.command}: {failure}", file=sys.stderr)
        return EXIT_FAILED
    except OSError as failure:
        print(f"spanweave {args.command}: {failure}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
