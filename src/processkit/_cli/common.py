"""Shared command construction and diagnostics for CLI subcommands."""

from __future__ import annotations

import argparse

from processkit import Command
from processkit._cli.output import emit_stderr


def _fail(message: str) -> None:
    emit_stderr(f"processkit: {message}")


def _parse_env_flags(
    parser: argparse.ArgumentParser, raw_pairs: list[str]
) -> list[tuple[str, str]]:
    """Parse repeated ``--env KEY=VALUE`` values as usage-checked pairs."""
    pairs: list[tuple[str, str]] = []
    for raw in raw_pairs:
        if "=" not in raw:
            parser.error(f"--env {raw!r}: expected KEY=VALUE")
        key, _, value = raw.partition("=")
        pairs.append((key, value))
    return pairs


def _apply_environment(
    command: Command,
    *,
    clear: bool,
    inherited: list[str],
    pairs: list[tuple[str, str]],
    cwd: str | None,
) -> Command:
    """Apply the CLI's shared environment and working-directory options."""
    if clear:
        command = command.env_clear()
    if inherited:
        command = command.inherit_env(inherited)
    for key, value in pairs:
        command = command.env(key, value)
    if cwd is not None:
        command = command.cwd(cwd)
    return command
