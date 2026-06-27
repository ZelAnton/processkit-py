"""Concurrent batch execution: `output_all` / `aoutput_all` and their `_bytes`
twins run many commands with bounded concurrency, returning each result — or a
`ProcessError` for a failed slot — in input order.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from processkit import (
    BytesResult,
    Command,
    ProcessError,
    ProcessNotFound,
    ProcessResult,
    aoutput_all,
    aoutput_all_bytes,
    output_all,
    output_all_bytes,
)
from processkit.testing import Reply, ScriptedRunner

PY = sys.executable

NO_SUCH = "processkit-no-such-binary-xyzzy"


def test_output_all_returns_results_in_order() -> None:
    results = output_all(
        [Command(PY, ["-c", "print(1)"]), Command(PY, ["-c", "print(2)"])],
        concurrency=2,
    )
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout.strip() for r in results if isinstance(r, ProcessResult)] == ["1", "2"]


def test_output_all_puts_spawn_failure_in_its_slot() -> None:
    results = output_all([Command(PY, ["-c", "print(1)"]), Command(NO_SUCH)])
    ok, failed = results[0], results[1]
    assert isinstance(ok, ProcessResult)
    assert ok.stdout.strip() == "1"
    assert isinstance(failed, ProcessNotFound)
    assert isinstance(failed, ProcessError)


def test_output_all_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(b'\\x00\\x01')"
    results = output_all_bytes([Command(PY, ["-c", code])])
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x00\x01"


def test_aoutput_all() -> None:
    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(PY, ["-c", "print(9)"])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, ProcessResult)
    assert first.stdout.strip() == "9"


def test_aoutput_all_bytes() -> None:
    async def scenario() -> list[BytesResult | ProcessError]:
        code = "import sys; sys.stdout.buffer.write(b'\\x02\\x03')"
        return await aoutput_all_bytes([Command(PY, ["-c", code])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x02\x03"


# --- runner injection (C1) ---------------------------------------------------


def test_output_all_accepts_injected_runner() -> None:
    # A NO_SUCH program would fail to spawn for real; with a ScriptedRunner
    # fallback wired in, no real process runs at all and the scripted reply
    # surfaces — proving the batch actually drove every command through the
    # injected runner, not the real one.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("scripted"))
    results = output_all([Command(NO_SUCH), Command(NO_SUCH)], runner=runner)
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout for r in results if isinstance(r, ProcessResult)] == ["scripted", "scripted"]


def test_output_all_bytes_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("bytes-scripted"))
    results = output_all_bytes([Command(NO_SUCH)], runner=runner)
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"bytes-scripted"


def test_aoutput_all_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("async-scripted"))

    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(NO_SUCH)], runner=runner)

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, ProcessResult)
    assert first.stdout == "async-scripted"


def test_aoutput_all_bytes_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("async-bytes-scripted"))

    async def scenario() -> list[BytesResult | ProcessError]:
        return await aoutput_all_bytes([Command(NO_SUCH)], runner=runner)

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"async-bytes-scripted"


def test_output_all_rejects_unsupported_runner_object() -> None:
    with pytest.raises(TypeError):
        output_all([Command(PY, ["-c", "pass"])], runner=object())  # type: ignore[arg-type]
