"""`CliClient` — a typed wrapper for a tool you call repeatedly, binding the
program plus default timeout/env so each verb takes just the per-call args.

It is deliberately NOT a `ProcessRunner` (its verbs take args, not a `Command`,
and it has no `start()`), so it is not interchangeable with the runner seam.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from processkit import CliClient, ProcessRunner

PY = sys.executable


def test_cli_client_run_and_defaults() -> None:
    client = CliClient(PY, default_env={"PK_CLI": "yes"})
    assert client.run(["-c", "print('cli-ok')"]) == "cli-ok"
    assert client.run(["-c", "import os; print(os.environ['PK_CLI'])"]) == "yes"
    assert client.exit_code(["-c", "import sys; sys.exit(2)"]) == 2
    assert client.probe(["-c", "import sys; sys.exit(0)"]) is True


def test_cli_client_async() -> None:
    async def scenario() -> str:
        return await CliClient(PY).arun(["-c", "print('async-cli')"])

    assert asyncio.run(scenario()) == "async-cli"


def test_cli_client_remaining_verbs() -> None:
    # Cover the CliClient verbs not exercised above: output_bytes + the async
    # capture/predicate twins.
    client = CliClient(PY)
    raw = client.output_bytes(["-c", "import sys; sys.stdout.buffer.write(b'\\x00\\x01')"])
    assert raw.stdout == b"\x00\x01"

    async def scenario() -> None:
        assert (await client.aoutput(["-c", "print('a')"])).stdout.strip() == "a"
        assert (await client.aoutput_bytes(["-c", "print('b')"])).stdout.strip() == b"b"
        assert await client.aexit_code(["-c", "import sys; sys.exit(4)"]) == 4
        assert await client.aprobe(["-c", "pass"]) is True

    asyncio.run(scenario())


def test_cli_client_default_timeout_applies() -> None:
    client = CliClient(PY, default_timeout=0.2)
    result = client.output(["-c", "import time; time.sleep(5)"])
    assert result.timed_out


def test_cli_client_default_env_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PK_CLI_RM", "present")
    client = CliClient(PY, default_env_remove=["PK_CLI_RM"])
    out = client.run(["-c", "import os; print(os.environ.get('PK_CLI_RM', 'GONE'))"])
    assert out == "GONE"


def test_cli_client_is_not_a_process_runner() -> None:
    # CliClient verbs take per-call args (not a Command) and it has no start()/
    # astart() — so it is deliberately NOT a ProcessRunner.
    assert not isinstance(CliClient("git"), ProcessRunner)
