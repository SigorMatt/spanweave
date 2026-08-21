"""Command-line entrypoint (``spanweave``).

The CLI is the thinnest possible layer over the library: argument parsing and
I/O, nothing else (``DESIGN.md`` §2). It writes to stdout and to files the
caller named, and to nothing else.

At this stage the subcommands parse their full argument surface (``SPEC.md``
§7) and exit with "not implemented". Declaring the surface before implementing
it keeps the CLI honest about what it will accept, and keeps later tasks from
quietly reshaping it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from spanweave.version import SCHEMA_FROZEN, SCHEMA_VERSION, __version__

# Exit codes. 0 success, 1 a refusal or an unimplemented path, 2 argparse's own
# usage error (argparse chooses that one, not us).
EXIT_OK = 0
EXIT_FAILED = 1

_SCHEMA_NOTICE = (
    f"Graph schema version {SCHEMA_VERSION} is NOT FROZEN: it may change in any "
    "release before 1.0.0. Pin your version."
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


def _not_implemented(command: str) -> int:
    print(f"spanweave {command}: not implemented yet", file=sys.stderr)
    return EXIT_FAILED


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    command: str = args.command
    return _not_implemented(command)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
