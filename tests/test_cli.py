"""The CLI's argument surface. Behavior arrives in Phase 1; the shape is now."""

import pytest

from spanweave.cli import main


def test_version_exits_zero_and_names_the_schema(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    printed = capsys.readouterr().out
    assert "spanweave" in printed
    # The unfrozen schema is announced in --version itself (CLAUDE.md 7).
    assert "UNFROZEN" in printed


def test_no_command_prints_help_and_exits_zero(capsys):
    assert main([]) == 0
    assert "usage: spanweave" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["build", "inspect", "validate", "adapters"])
def test_every_subcommand_parses_and_exits_cleanly(command, capsys):
    argv = [command] if command == "adapters" else [command, "trace.jsonl"]
    assert main(argv) == 1
    assert "not implemented" in capsys.readouterr().err


def test_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        main(["nope"])
    assert exit_info.value.code == 2
