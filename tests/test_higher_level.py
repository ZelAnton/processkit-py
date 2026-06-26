"""Phase 3 higher-level features: resource limits, signals/stats, pipelines,
supervision, and readiness probes.

Cross-platform-tolerant: features the running platform cannot enforce raise
`Unsupported` and are skipped rather than failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys

import pytest

from processkit import (
    Command,
    ProcessGroup,
    ResourceLimit,
    Supervisor,
    Unsupported,
    wait_for_line,
    wait_for_port,
)

PY = sys.executable


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


# --- resource limits ---


def test_invalid_resource_limit_raises() -> None:
    with pytest.raises(ResourceLimit):
        ProcessGroup(max_processes=0)
    with pytest.raises(ResourceLimit):
        ProcessGroup(memory_max=0)


def test_resource_limited_group_runs() -> None:
    # Limits are enforceable via the Windows Job Object or a Linux cgroup v2
    # *root*; under a container / systemd session / non-root cgroup the kernel's
    # "no internal processes" rule blocks them (raising ResourceLimit), and some
    # platforms don't support them at all (Unsupported). Skip where unenforceable.
    try:
        with ProcessGroup(max_processes=64, memory_max=512 * 1024 * 1024) as group:
            running = group.start(Command(PY, ["-c", "pass"]))
            assert running.pid is not None
    except (Unsupported, ResourceLimit):
        pytest.skip("resource limits not enforceable in this environment")


# --- signals / suspend / resume / terminate / stats ---


def test_group_suspend_resume_terminate() -> None:
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        try:
            group.suspend()
            group.resume()
        except Unsupported:
            pass
        group.terminate_all()


def test_group_signal() -> None:
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        with contextlib.suppress(Unsupported):
            group.signal("term")


def test_group_signal_unknown_name_rejected() -> None:
    with ProcessGroup() as group, pytest.raises(ValueError):
        group.signal("not-a-signal")  # type: ignore[arg-type]  # invalid on purpose


def test_group_stats() -> None:
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", "import time; time.sleep(2)"]))
        try:
            stats = group.stats()
        except Unsupported:
            pytest.skip("stats unsupported on this platform")
        assert stats.active_process_count >= 1
        assert stats.peak_memory_bytes is None or stats.peak_memory_bytes >= 0


# --- pipelines ---

_UPPER = "import sys; [print(line.strip().upper()) for line in sys.stdin]"


def test_pipeline_run_sync() -> None:
    pipe = Command(PY, ["-c", "print('a'); print('b'); print('c')"]) | Command(PY, ["-c", _UPPER])
    assert pipe.run() == "A\nB\nC"


def test_pipeline_run_async_and_pipe_method() -> None:
    async def scenario() -> str:
        pipe = Command(PY, ["-c", "print('x'); print('y')"]).pipe(Command(PY, ["-c", _UPPER]))
        return await pipe.arun()

    assert asyncio.run(scenario()) == "X\nY"


def test_pipeline_exit_code() -> None:
    pipe = Command(PY, ["-c", "print('hi')"]) | Command(PY, ["-c", "import sys; sys.exit(0)"])
    assert pipe.exit_code() == 0


# --- supervisor ---


def test_supervisor_never_restarts_on_success() -> None:
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    assert outcome.restarts == 0
    assert outcome.final_result.is_success


def test_supervisor_exhausts_restarts_on_crash() -> None:
    async def scenario() -> object:
        crash = Command(PY, ["-c", "import sys; sys.exit(1)"])
        sup = Supervisor(
            crash, restart="on_crash", max_restarts=2, backoff_initial=0.01, backoff_factor=1.0
        )
        return await sup.arun()

    outcome = asyncio.run(scenario())
    assert outcome.restarts == 2  # type: ignore[attr-defined]
    assert outcome.stopped == "restarts_exhausted"  # type: ignore[attr-defined]


def test_supervisor_stop_when_predicate() -> None:
    calls: list[int] = []

    def stop(result: object) -> bool:
        calls.append(1)
        return True  # stop after the first run

    outcome = Supervisor(Command(PY, ["-c", "print('x')"]), restart="always", stop_when=stop).run()
    assert outcome.stopped == "predicate"
    assert outcome.restarts == 0
    assert calls  # the predicate was actually invoked


def test_supervisor_run_is_once() -> None:
    sup = Supervisor(Command(PY, ["-c", "pass"]), restart="never")
    sup.run()
    from processkit import ProcessError

    with pytest.raises(ProcessError):
        sup.run()


# --- readiness probes ---


def test_wait_for_port_ready() -> None:
    port = _free_port()
    server = (
        f"import socket, time; "
        f"s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(10)"
    )

    async def scenario() -> None:
        async with ProcessGroup() as group:
            await group.astart(Command(PY, ["-c", server]))
            await wait_for_port("127.0.0.1", port, timeout=10.0)

    asyncio.run(scenario())


def test_wait_for_port_timeout() -> None:
    port = _free_port()  # nothing is listening

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_for_port("127.0.0.1", port, timeout=0.5)

    asyncio.run(scenario())


def test_wait_for_line_matches() -> None:
    code = (
        "import time; print('starting', flush=True); "
        "time.sleep(0.05); print('READY now', flush=True); time.sleep(5)"
    )

    async def scenario() -> str:
        proc = await Command(PY, ["-c", code]).astart()
        lines = proc.stdout_lines()
        matched = await wait_for_line(lines, lambda line: "READY" in line, timeout=10.0)
        proc.start_kill()
        await proc.wait()
        return matched

    assert "READY" in asyncio.run(scenario())
