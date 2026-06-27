"""`CliClient` — a typed wrapper for a tool you call repeatedly, binding the
program plus default timeout/env so each verb takes just the per-call args
(or a customized `Command` from `command()` — the `IntoCommand` path).

Its verbs share *names* with the runner seam (`output`/`run`/`exit_code`/
`probe`, `a`-prefixed twins) but not the runner seam's *signature* — a plain
arg list, not a bare `Command` (that only arrives via `command()`'s
IntoCommand path) — so it is still not interchangeable with the runner seam,
and has no `start()`/`astart()` at all. Note the asymmetry this creates with
`isinstance`: `ProcessRunner` (`Protocol`, `@runtime_checkable`) only checks
method *names* at runtime, not parameter types, so
`isinstance(CliClient(...), ProcessRunner)` is `True` despite the signature
mismatch — a well-known `Protocol` limitation, not a bug. `StreamingRunner`
(which adds `start`/`astart`) correctly reads `False`, since those names are
genuinely absent.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from processkit import (
    CancellationToken,
    Cancelled,
    CliClient,
    Command,
    ProcessRunner,
    StreamingRunner,
)
from processkit.testing import Reply, ScriptedRunner

from .conftest import NO_SUCH_PROGRAM, PY


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


def test_cli_client_default_env_overrides_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    # `default_env` must MERGE over the inherited environment (override an
    # existing value), not just add a key that was previously absent —
    # previously untested (the only default_env test used a brand-new key).
    monkeypatch.setenv("PK_CLI_OVERRIDE", "inherited")
    client = CliClient(PY, default_env={"PK_CLI_OVERRIDE": "overridden"})
    out = client.run(["-c", "import os; print(os.environ['PK_CLI_OVERRIDE'])"])
    assert out == "overridden"


def test_cli_client_default_env_remove_wins_over_default_env_same_key() -> None:
    # Same-key precedence between the two *static* channels: the binding
    # applies every `default_env` entry, then every `default_env_remove` entry
    # (matching the crate's "last registration wins" rule for the static
    # channel) — so a key present in both ends up removed, not set.
    client = CliClient(PY, default_env={"PK_CLI_BOTH": "set"}, default_env_remove=["PK_CLI_BOTH"])
    out = client.run(["-c", "import os; print(os.environ.get('PK_CLI_BOTH', 'GONE'))"])
    assert out == "GONE"


# --- retry (C2) --------------------------------------------------------------


def test_cli_client_default_retry_recovers_from_timeout(tmp_path: pathlib.Path) -> None:
    # Mirrors `test_retry_on_timeout_recovers_and_returns_success` for
    # `Command.retry()`, but wired client-wide via `default_retry_if=`.
    counter = tmp_path / "n"
    code = (
        "import pathlib, sys, time\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "if n == 0:\n"
        "    time.sleep(30)\n"
        "sys.exit(0)\n"
    )
    client = CliClient(
        PY,
        default_timeout=3.0,
        default_retry_if="transient_or_timeout",
        default_max_retries=1,
        default_initial_backoff=0.01,
        default_jitter=False,
    )
    assert client.run(["-c", code]) == ""
    assert counter.read_text() == "2"


def test_cli_client_retry_tuning_knob_without_retry_if_raises() -> None:
    # `default_retry_if` is the required opt-in gate (mirrors `Command.retry()`'s
    # required `retry_if`) — a tuning knob alone would otherwise be a silently
    # ignored no-op.
    with pytest.raises(ValueError, match="default_retry_if"):
        CliClient(PY, default_max_retries=5)


def test_cli_client_retry_rejects_unknown_retry_if() -> None:
    with pytest.raises(ValueError, match="retry_if"):
        CliClient(PY, default_retry_if="bogus")  # type: ignore[arg-type]


# --- command() / IntoCommand path (C7 batch A) -------------------------------


def test_cli_client_command_returns_a_defaulted_command() -> None:
    client = CliClient(PY, default_timeout=5.0)
    cmd = client.command(["-c", "print('hi')"])
    assert isinstance(cmd, Command)
    # The client's default_timeout is pre-applied (not just the args).
    result = cmd.output()
    assert result.stdout.strip() == "hi"


def test_cli_client_run_accepts_a_customized_command() -> None:
    # The IntoCommand path: build via command(), chain a builder, then run it —
    # not just a plain arg list.
    client = CliClient(PY)
    cmd = client.command(["-c", "import os; print(os.environ['PK_CUSTOM'])"]).env(
        "PK_CUSTOM", "custom-value"
    )
    assert client.run(cmd) == "custom-value"


def test_cli_client_customized_command_keeps_its_own_explicit_timeout() -> None:
    # A caller-supplied Command's own explicit timeout wins over the client's
    # default_timeout — only the gaps get filled, matching the crate's
    # apply_defaults contract.
    client = CliClient(PY, default_timeout=0.05)
    cmd = client.command(["-c", "import time; time.sleep(0.3)"]).timeout(5.0)
    result = client.output(cmd)
    assert not result.timed_out


def test_cli_client_async_verbs_accept_a_customized_command() -> None:
    client = CliClient(PY)

    async def scenario() -> str:
        cmd = client.command(["-c", "print('async-cmd')"])
        return await client.arun(cmd)

    assert asyncio.run(scenario()) == "async-cmd"


def test_cli_client_args_accept_path_like_elements() -> None:
    # C6: argv element typing is unified with Command's own (str or any
    # os.PathLike[str]) — previously CliClient's Rust binding was str-only
    # (Vec<String>), unlike Command's Vec<PathBuf>.
    p = pathlib.Path("-c")
    client = CliClient(PY)
    assert client.run([p, "print('path-like arg')"]) == "path-like arg"
    cmd = client.command([p, "print('via command()')"])
    assert client.run(cmd) == "via command()"


# --- default_env_fn (C7 batch A) ---------------------------------------------


def test_cli_client_default_env_fn_resolves_fresh_per_build() -> None:
    calls = 0

    def resolver() -> str:
        nonlocal calls
        calls += 1
        return f"token-{calls}"

    client = CliClient(PY, default_env_fn={"PK_TOKEN": resolver})
    first = client.run(["-c", "import os; print(os.environ['PK_TOKEN'])"])
    second = client.run(["-c", "import os; print(os.environ['PK_TOKEN'])"])
    assert first == "token-1"
    assert second == "token-2"  # resolved fresh per built command


def test_cli_client_default_env_fn_yields_to_an_explicit_env() -> None:
    # An explicit per-call env still wins — default_env_fn only fills the gap,
    # like every other CliClient default.
    client = CliClient(PY, default_env_fn={"PK_TOKEN": lambda: "from-resolver"})
    cmd = client.command(["-c", "import os; print(os.environ['PK_TOKEN'])"]).env(
        "PK_TOKEN", "explicit"
    )
    assert client.run(cmd) == "explicit"


# --- default_cancel_on (C7 batch B) ------------------------------------------


def test_cli_client_default_cancel_on_tears_down_the_run() -> None:
    async def scenario() -> None:
        token = CancellationToken()
        client = CliClient(PY, default_cancel_on=token)
        task = asyncio.ensure_future(client.arun(["-c", "import time; time.sleep(30)"]))
        await asyncio.sleep(0.2)
        token.cancel()
        with pytest.raises(Cancelled):
            await task

    asyncio.run(scenario())


def test_cli_client_default_cancel_on_yields_to_an_explicit_per_command_token() -> None:
    # Gap-fill (not override): a per-command cancel_on() wins over the
    # client's default_cancel_on — firing the CLIENT's token must not affect
    # a command that already has its own.
    async def scenario() -> str:
        client_token = CancellationToken()
        own_token = CancellationToken()
        client = CliClient(PY, default_cancel_on=client_token)
        cmd = client.command(["-c", "print('unaffected')"]).cancel_on(own_token)
        client_token.cancel()
        return await client.arun(cmd)

    assert asyncio.run(scenario()) == "unaffected"


def test_cli_client_satisfies_process_runner_by_name_only() -> None:
    # `ProcessRunner`'s runtime `isinstance` check (via `@runtime_checkable`)
    # only inspects method *names*, not parameter types — so CliClient (same
    # verb names, different signature: `args` not `Command`) structurally
    # satisfies it at runtime despite not being genuinely interchangeable.
    # This is a documented Python `Protocol` limitation, pinned here so it
    # doesn't look like an accidental regression later.
    assert isinstance(CliClient("git"), ProcessRunner)


def test_cli_client_is_not_a_streaming_runner() -> None:
    # `StreamingRunner` adds `start`/`astart`, which CliClient genuinely lacks
    # by name (not just by signature) — so it is NOT a `StreamingRunner`, and
    # the two are not interchangeable at the streaming seam.
    assert not isinstance(CliClient("git"), StreamingRunner)


# --- runner injection (C1) ---------------------------------------------------


def test_cli_client_accepts_injected_runner() -> None:
    # "no-such-tool" would fail to spawn for real; with a ScriptedRunner
    # injected, every verb runs through it instead — no real process, and the
    # scripted reply is what comes back.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("cli-scripted"))
    client = CliClient(NO_SUCH_PROGRAM, runner=runner)
    assert client.run(["--version"]) == "cli-scripted"


def test_cli_client_rejects_unsupported_runner_object() -> None:
    with pytest.raises(TypeError):
        CliClient(PY, runner=object())  # type: ignore[arg-type]
