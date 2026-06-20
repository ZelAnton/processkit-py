"""Tests for the extended surface: full environment control, output caps,
bytes output, and the stdlib-aliased exceptions."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from processkit import (
    BytesResult,
    Command,
    OutputTooLarge,
    ProcessError,
    ProcessNotFound,
    Timeout,
)

PY = sys.executable


# --- Environment control ----------------------------------------------------


def test_envs_sets_multiple() -> None:
    out = (
        Command(PY, ["-c", "import os; print(os.environ['A'], os.environ['B'])"])
        .envs({"A": "1", "B": "2"})
        .run()
    )
    assert out == "1 2"


def test_env_remove_drops_inherited() -> None:
    os.environ["PK_REMOVE_ME"] = "parent"
    try:
        out = (
            Command(PY, ["-c", "import os; print(os.environ.get('PK_REMOVE_ME', 'GONE'))"])
            .env_remove("PK_REMOVE_ME")
            .run()
        )
        assert out == "GONE"
    finally:
        del os.environ["PK_REMOVE_ME"]


def test_env_clear_starts_from_empty() -> None:
    os.environ["PK_CLEAR_MARKER"] = "parent"
    try:
        cmd = Command(
            PY, ["-c", "import os; print(os.environ.get('PK_CLEAR_MARKER', 'GONE'))"]
        ).env_clear()
        # The interpreter needs SystemRoot to spawn on Windows; re-add just that
        # (env var names are case-insensitive on Windows).
        if sys.platform == "win32":
            cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
        assert cmd.run() == "GONE"
    finally:
        del os.environ["PK_CLEAR_MARKER"]


# --- Bytes output -----------------------------------------------------------


def test_output_bytes_returns_raw_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(bytes([0, 1, 2, 255]))"
    result = Command(PY, ["-c", code]).output_bytes()
    assert isinstance(result, BytesResult)
    assert result.stdout == bytes([0, 1, 2, 255])
    assert isinstance(result.stderr, str)
    assert result.code == 0
    assert result.is_success
    assert not result.truncated


def test_aoutput_bytes_returns_raw_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(b'\\x00\\xff')"
        return await Command(PY, ["-c", code]).aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == b"\x00\xff"


# --- Output caps ------------------------------------------------------------


def test_output_limit_error_raises_output_too_large() -> None:
    code = "import sys\nfor i in range(1000):\n    print(i)"
    with pytest.raises(OutputTooLarge) as excinfo:
        Command(PY, ["-c", code]).output_limit(max_lines=10, on_overflow="error").run()
    assert excinfo.value.line_limit == 10
    assert excinfo.value.total_lines >= 1000


def test_output_limit_truncate_marks_truncated() -> None:
    code = "import sys\nfor i in range(1000):\n    print('x' * 80)"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output()
    assert result.is_success
    assert result.truncated


def test_output_limit_requires_a_cap() -> None:
    with pytest.raises(ValueError):
        Command(PY, ["-c", "pass"]).output_limit()


def test_output_limit_rejects_unknown_overflow() -> None:
    with pytest.raises(ValueError):
        # An invalid literal is the point of the test; mypy would flag it.
        Command(PY, ["-c", "pass"]).output_limit(max_bytes=10, on_overflow="nope")  # type: ignore[arg-type]


# --- Stdlib-aliased exceptions ----------------------------------------------


def test_timeout_is_a_timeout_error() -> None:
    assert issubclass(Timeout, TimeoutError)
    assert issubclass(Timeout, ProcessError)
    with pytest.raises(TimeoutError):
        Command(PY, ["-c", "import time; time.sleep(30)"]).timeout(0.2).run()


def test_process_not_found_is_a_file_not_found_error() -> None:
    assert issubclass(ProcessNotFound, FileNotFoundError)
    assert issubclass(ProcessNotFound, ProcessError)
    with pytest.raises(FileNotFoundError):
        Command("processkit-definitely-no-such-program-xyz").run()
