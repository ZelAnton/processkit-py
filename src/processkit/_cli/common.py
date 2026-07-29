"""Shared command construction and diagnostics for CLI subcommands."""

from __future__ import annotations

import argparse
import pathlib

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
        if not key:
            parser.error(f"--env {raw!r}: key must not be empty")
        pairs.append((key, value))
    return pairs


def _parse_env_files(parser: argparse.ArgumentParser, paths: list[str]) -> list[tuple[str, str]]:
    """Read docker-style env files in order, with usage-quality diagnostics."""
    pairs: list[tuple[str, str]] = []
    for raw_path in paths:
        path = pathlib.Path(raw_path)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            parser.error(f"--env-file {raw_path!r}: could not read file: {exc}")
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                parser.error(f"--env-file {raw_path!r}, line {line_number}: expected KEY=VALUE")
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                parser.error(f"--env-file {raw_path!r}, line {line_number}: key must not be empty")
            pairs.append((key, value))
    return pairs


def _parse_environment(
    parser: argparse.ArgumentParser, env_files: list[str], raw_pairs: list[str]
) -> list[tuple[str, str]]:
    """Merge files in order, then explicit ``--env`` overrides."""
    return _parse_env_files(parser, env_files) + _parse_env_flags(parser, raw_pairs)


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
