"""Property: `Pipeline` (`a | b | c` / `a.pipe(b).pipe(c)`) semantics documented
in `docs/pipelines.md` and pinned example-based in `tests/test_pipelines.py` --
exercised here over generated chains of variable length instead of a single
fixed shape.

Each chain stage is a tiny, deterministic `python -c` script (`_stage_script`):
it drains whatever stdin it was fed (mirroring
`tests/test_pipelines.py::test_pipeline_exit_code`'s own comment -- a
downstream that exits without reading can race an upstream write into a
spurious BrokenPipe), emits a known number of marker lines to stdout, writes
its own marker to stderr, then exits with a given code. Chains stay short (2-3
stages, few lines each) and every test caps `max_examples` explicitly -- these
spawn real subprocesses per example, so the shared `default`/`ci` profiles
(`tests/property/conftest.py`) are deliberately overridden down, the same way
`test_output_limit.py`'s real-spawn tests do.

Six invariants, one `@given` test each:

1. pipefail attribution: a non-last stage's failure is reported, not masked by
   a clean final stage.
2. stdout is always the last stage's, regardless of what earlier stages wrote.
3. `.unchecked_in_pipe()` exempts a stage's own unclean exit from attribution.
4. a per-stage `Command.timeout()` (head or intermediate) bounds the WHOLE
   chain's wall clock.
5. `a | b | c` and `.pipe(...).pipe(...)` build an equivalent `Pipeline`.
6. sync verbs and their `a`-prefixed asyncio twins agree on the same chain.
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processkit import BytesResult, Command, NonZeroExit, Pipeline, ProcessResult

PY = sys.executable

# Kept small on purpose: every example here spawns a handful of real
# subprocesses, so chain length and per-stage output stay modest -- no
# inflating per-example real-subprocess wall time.
_MAX_STAGES = 3
_MAX_LINES = 2
# 1..125: comfortably inside the POSIX 0-255 exit-code range on every
# platform, well clear of the 126/127/128+ shell-reserved band -- a plain,
# unambiguous "this stage failed" signal.
_STAGE_EXIT_CODE = st.integers(min_value=1, max_value=125)


def _marker(index: int) -> str:
    return f"S{index}"


def _stage_script(marker: str, num_lines: int, exit_code: int) -> str:
    return (
        "import sys\n"
        "sys.stdin.read()\n"
        f"for i in range({num_lines}):\n"
        f"    print('{marker}-' + str(i))\n"
        f"sys.stderr.write('{marker}\\n')\n"
        f"sys.exit({exit_code})\n"
    )


def _stage(index: int, num_lines: int, exit_code: int) -> Command:
    return Command(PY, ["-c", _stage_script(_marker(index), num_lines, exit_code)])


def _pipe_chain(commands: list[Command]) -> Pipeline:
    """Build `a | b | c ...` with the `|` operator."""
    pipeline = commands[0] | commands[1]
    for stage in commands[2:]:
        pipeline = pipeline | stage
    return pipeline


def _pipe_method_chain(commands: list[Command]) -> Pipeline:
    """The same chain, built with `.pipe(...)` instead of `|`."""
    pipeline = commands[0].pipe(commands[1])
    for stage in commands[2:]:
        pipeline = pipeline.pipe(stage)
    return pipeline


@settings(max_examples=10, deadline=None)
@given(n=st.integers(min_value=2, max_value=_MAX_STAGES), data=st.data())
def test_pipeline_pipefail_attributes_first_unclean_non_last_stage(
    n: int, data: st.DataObject
) -> None:
    # A single non-last stage's non-zero exit must be reported as the
    # pipeline's own code/stderr -- never masked by the final, successful
    # stage (unlike a shell `|`). Generalizes
    # test_pipelines.py::test_pipeline_pipefail_propagates_non_last_stage_failure
    # over generated chain length and failure position.
    fail_index = data.draw(st.integers(min_value=0, max_value=n - 2))
    fail_code = data.draw(_STAGE_EXIT_CODE)
    lines = data.draw(
        st.lists(st.integers(min_value=0, max_value=_MAX_LINES), min_size=n, max_size=n)
    )

    def build() -> list[Command]:
        return [_stage(i, lines[i], fail_code if i == fail_index else 0) for i in range(n)]

    result = _pipe_chain(build()).output()
    assert result.code == fail_code
    assert not result.is_success
    assert _marker(fail_index) in result.stderr
    for i in range(n):
        if i != fail_index:
            assert _marker(i) not in result.stderr

    with pytest.raises(NonZeroExit) as excinfo:
        _pipe_chain(build()).run()
    assert excinfo.value.code == fail_code


@settings(max_examples=10, deadline=None)
@given(n=st.integers(min_value=2, max_value=_MAX_STAGES), data=st.data())
def test_pipeline_stdout_is_the_last_stage_output(n: int, data: st.DataObject) -> None:
    # `run()`/`output()` return exactly the FINAL stage's stdout, no matter
    # what any upstream stage printed -- the pipeline never mixes stdout
    # across stages.
    other_lines = data.draw(
        st.lists(st.integers(min_value=0, max_value=_MAX_LINES), min_size=n - 1, max_size=n - 1)
    )
    last_lines = data.draw(st.integers(min_value=1, max_value=_MAX_LINES))
    expected = "\n".join(f"LAST-{i}" for i in range(last_lines))

    def build() -> list[Command]:
        commands = [_stage(i, other_lines[i], 0) for i in range(n - 1)]
        commands.append(Command(PY, ["-c", _stage_script("LAST", last_lines, 0)]))
        return commands

    assert _pipe_chain(build()).output().stdout == expected
    assert _pipe_chain(build()).run() == expected


@settings(max_examples=10, deadline=None)
@given(
    fail_code=_STAGE_EXIT_CODE,
    num_lines=st.integers(min_value=0, max_value=_MAX_LINES),
)
def test_pipeline_unchecked_in_pipe_exempts_stage_from_pipefail(
    fail_code: int, num_lines: int
) -> None:
    # A stage marked `.unchecked_in_pipe()` that exits non-zero must NOT be
    # attributed as the pipeline's failure -- compared directly against the
    # same chain minus the mark (docs/pipelines.md's canonical
    # `producer.unchecked_in_pipe() | head` shape, generalized over the
    # failing stage's exit code and output volume).
    upstream = Command(PY, ["-c", _stage_script(_marker(0), num_lines, fail_code)])
    downstream = Command(PY, ["-c", _stage_script(_marker(1), 1, 0)])

    checked = (upstream | downstream).output()
    assert checked.code == fail_code
    assert not checked.is_success

    exempted = (upstream.unchecked_in_pipe() | downstream).output()
    assert exempted.is_success
    assert exempted.code == 0


@settings(max_examples=10, deadline=None)
@given(n=st.integers(min_value=2, max_value=_MAX_STAGES), data=st.data())
def test_pipeline_stage_timeout_bounds_the_whole_chain(n: int, data: st.DataObject) -> None:
    # A per-stage `Command.timeout()` set on the head OR an intermediate
    # stage bounds the WHOLE chain's wall clock: a stage sleeping past its
    # own timeout yields a timed-out pipeline outcome rather than a hang or a
    # silently ignored deadline (docs/pipelines.md, "Timeouts bound the
    # chain"). Kept well above real subprocess-start latency (K-037: too-short
    # timeouts are flaky under a loaded CI runner).
    sleeper_index = data.draw(st.integers(min_value=0, max_value=n - 2))
    stage_timeout = 0.4
    sleep_seconds = 5.0

    commands: list[Command] = []
    for i in range(n):
        if i == sleeper_index:
            script = f"import sys, time\nsys.stdin.read()\ntime.sleep({sleep_seconds})\n"
            commands.append(Command(PY, ["-c", script]).timeout(stage_timeout))
        else:
            commands.append(_stage(i, 0, 0))

    started_at = time.monotonic()
    result = _pipe_chain(commands).output()
    elapsed_seconds = time.monotonic() - started_at

    assert result.timed_out
    assert not result.is_success
    assert elapsed_seconds < stage_timeout * 2.5


@settings(max_examples=10, deadline=None)
@given(n=st.integers(min_value=2, max_value=_MAX_STAGES), data=st.data())
def test_pipeline_composition_pipe_operator_equals_pipe_method(n: int, data: st.DataObject) -> None:
    # `a | b | c` and `a.pipe(b).pipe(c)` must build an equivalent Pipeline --
    # the same generated stage set run through both composition styles
    # yields the same ProcessResult (`==` compares every field but
    # duration_seconds/truncated, per the ProcessResult docstring) in the
    # all-clean case.
    #
    # When a non-last stage fails, a checked stage failure proactively tears
    # down every OTHER stage's sub-group (docs/pipelines.md;
    # test_pipelines.py::test_pipeline_stage_failure_proactively_tears_down_a_quiet_upstream),
    # including a downstream stage that hasn't finished writing its own
    # stdout yet -- so exactly how much of ITS output lands before the kill
    # is a genuine wall-clock race in the runtime itself, orthogonal to which
    # composition style built the chain (two independent real runs of the
    # SAME script can legitimately disagree on that partial tail). The
    # pipefail-ATTRIBUTED fields stay deterministic either way (locked onto
    # the failing stage's own, already-complete output), so compare those
    # instead of the full result in that case.
    fail_index = data.draw(st.one_of(st.none(), st.integers(min_value=0, max_value=n - 2)))
    fail_code = data.draw(_STAGE_EXIT_CODE) if fail_index is not None else 0
    lines = data.draw(
        st.lists(st.integers(min_value=0, max_value=_MAX_LINES), min_size=n, max_size=n)
    )

    def build() -> list[Command]:
        return [_stage(i, lines[i], fail_code if i == fail_index else 0) for i in range(n)]

    via_operator = _pipe_chain(build()).output()
    via_pipe_method = _pipe_method_chain(build()).output()

    if fail_index is None:
        assert via_operator == via_pipe_method
    else:
        assert via_operator.code == via_pipe_method.code == fail_code
        assert via_operator.is_success is False
        assert via_pipe_method.is_success is False
        assert via_operator.program == via_pipe_method.program
        assert via_operator.stderr == via_pipe_method.stderr


@settings(max_examples=10, deadline=None)
@given(data=st.data())
def test_pipeline_sync_and_async_verbs_agree(data: st.DataObject) -> None:
    # Same generated 2-stage chain driven through `run()`/`exit_code()`/
    # `output()`/`output_bytes()` and their `a`-prefixed asyncio twins
    # (`arun()`/`aexit_code()`/`aoutput()`/`aoutput_bytes()`) must agree on
    # every result. Per K-024, these builder methods are `Awaitable`-typed
    # but NOT `async def` -- `asyncio.run()` itself requires a genuine
    # coroutine, so each is awaited from a small `async def` wrapper (the
    # same shape `tests/test_pipelines.py`'s own async scenarios use), not
    # passed to `asyncio.run()` directly.
    fail_index = data.draw(st.one_of(st.none(), st.just(0)))
    # `probe()` maps only exit code 1 to False (other non-zero codes raise),
    # so use its predicate-failure code when exercising the failure branch.
    fail_code = 1 if fail_index is not None else 0
    lines = data.draw(
        st.lists(st.integers(min_value=1, max_value=_MAX_LINES), min_size=2, max_size=2)
    )

    def build() -> Pipeline:
        return _pipe_chain(
            [_stage(i, lines[i], fail_code if i == fail_index else 0) for i in range(2)]
        )

    async def async_exit_code() -> int:
        return await build().aexit_code()

    async def async_output() -> ProcessResult:
        return await build().aoutput()

    async def async_output_bytes() -> BytesResult:
        return await build().aoutput_bytes()

    async def async_run() -> str:
        return await build().arun()

    async def async_probe() -> bool:
        return await build().aprobe()

    assert build().exit_code() == asyncio.run(async_exit_code())

    if fail_index is None:
        assert build().output() == asyncio.run(async_output())
        assert build().output_bytes() == asyncio.run(async_output_bytes())
        assert build().probe() == asyncio.run(async_probe())
        assert build().run() == asyncio.run(async_run())
    else:
        sync_output = build().output()
        async_output_result = asyncio.run(async_output())
        assert sync_output.code == async_output_result.code
        assert sync_output.is_success == async_output_result.is_success
        assert sync_output.program == async_output_result.program
        assert sync_output.stderr == async_output_result.stderr

        sync_output_bytes = build().output_bytes()
        async_output_bytes_result = asyncio.run(async_output_bytes())
        assert sync_output_bytes.code == async_output_bytes_result.code
        assert sync_output_bytes.is_success == async_output_bytes_result.is_success
        assert sync_output_bytes.program == async_output_bytes_result.program
        assert sync_output_bytes.stderr == async_output_bytes_result.stderr

        assert build().probe() == asyncio.run(async_probe())
        with pytest.raises(NonZeroExit) as sync_exc:
            build().run()
        with pytest.raises(NonZeroExit) as async_exc:
            asyncio.run(async_run())
        assert sync_exc.value.code == async_exc.value.code == fail_code
        assert sync_exc.value.program == async_exc.value.program
        assert sync_exc.value.stderr == async_exc.value.stderr
