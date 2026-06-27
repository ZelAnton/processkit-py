"""Sync `Command` surface — real subprocess runs against the host interpreter.

Using ``sys.executable`` keeps these portable across Windows / Linux / macOS
without assuming any system binary is present.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

from processkit import Command, NonZeroExit, ProcessError, ProcessNotFound, Timeout

PY = sys.executable


def test_output_captures_stdout_and_code() -> None:
    result = Command(PY, ["-c", "print('hello')"]).output()
    assert result.stdout.strip() == "hello"
    assert result.code == 0
    assert result.is_success
    assert not result.timed_out
    assert result.signal is None
    assert result.duration_seconds >= 0.0


def test_run_returns_trimmed_stdout() -> None:
    assert Command(PY, ["-c", "print('hi')"]).run() == "hi"


def test_combined_is_a_property_with_both_streams() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    result = Command(PY, ["-c", code]).output()
    # `combined` is a property (bare attribute, not a call): calling it would
    # `TypeError` on the returned str — pins the method->property change, which the
    # name-only drift guard cannot catch.
    combined = result.combined
    assert isinstance(combined, str)
    assert "out" in combined and "err" in combined


def test_output_nonzero_exit_is_data_not_error() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output()
    assert result.code == 3
    assert not result.is_success


def test_run_raises_on_nonzero_exit() -> None:
    with pytest.raises(NonZeroExit):
        Command(PY, ["-c", "import sys; sys.exit(3)"]).run()


def test_exit_code() -> None:
    assert Command(PY, ["-c", "import sys; sys.exit(7)"]).exit_code() == 7


def test_probe_true_and_false() -> None:
    assert Command(PY, ["-c", "import sys; sys.exit(0)"]).probe() is True
    assert Command(PY, ["-c", "import sys; sys.exit(1)"]).probe() is False


def test_missing_program_raises_process_not_found() -> None:
    with pytest.raises(ProcessNotFound):
        Command("processkit-no-such-binary-xyzzy").output()


def test_timeout_is_captured_by_output() -> None:
    result = Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).output()
    assert result.timed_out
    assert result.code is None
    assert not result.is_success


def test_timeout_is_raised_by_run() -> None:
    with pytest.raises(Timeout):
        Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).run()


def test_invalid_timeout_rejected() -> None:
    # Zero, negative, non-finite, and a value that overflows the underlying
    # Duration must all be rejected cleanly (never a Rust panic).
    for bad in (0.0, -1.0, float("inf"), float("nan"), 1e300):
        with pytest.raises(ValueError):
            Command(PY).timeout(bad)


def test_builder_chaining_returns_new_command() -> None:
    base = Command(PY)
    chained = base.arg("-c").arg("print(1 + 1)")
    assert chained.output().stdout.strip() == "2"
    # The original is untouched (builder methods return a new Command). The
    # redacted repr shows the arg COUNT (not values), still 0 on the base.
    assert "args: 0" in repr(base)


def test_cwd_is_applied() -> None:
    result = Command(PY, ["-c", "import os; print(os.getcwd())"]).cwd(os.getcwd()).output()
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(os.getcwd())


def test_accepts_pathlike_program_and_cwd(tmp_path: pathlib.Path) -> None:
    # A pathlib.Path (os.PathLike) is accepted for both program and cwd, not
    # just str — matching Python's subprocess conventions.
    result = (
        Command(pathlib.Path(PY), ["-c", "import os; print(os.getcwd())"]).cwd(tmp_path).output()
    )
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(str(tmp_path))


def test_env_is_applied() -> None:
    code = "import os; print(os.environ.get('PROCESSKIT_TEST', 'unset'))"
    result = Command(PY, ["-c", code]).env("PROCESSKIT_TEST", "applied").output()
    assert result.stdout.strip() == "applied"


def test_exception_hierarchy() -> None:
    for exc in (NonZeroExit, Timeout, ProcessNotFound):
        assert issubclass(exc, ProcessError)


def test_nonzero_exit_carries_structured_fields() -> None:
    code = "import sys; print('to-out'); sys.stderr.write('to-err'); sys.exit(5)"
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", code]).run()
    err = excinfo.value
    assert err.code == 5
    assert "to-out" in err.stdout
    assert "to-err" in err.stderr
    assert "python" in err.program.lower() or err.program == PY


def test_timeout_error_carries_timeout_seconds() -> None:
    with pytest.raises(Timeout) as excinfo:
        Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).run()
    assert excinfo.value.timeout_seconds == pytest.approx(0.3, abs=0.05)
    # The other structured fields are attached too (partial output + program).
    assert isinstance(excinfo.value.stdout, str)
    assert isinstance(excinfo.value.stderr, str)
    assert excinfo.value.program


def test_process_not_found_carries_program() -> None:
    with pytest.raises(ProcessNotFound) as excinfo:
        Command("processkit-no-such-binary-xyzzy").output()
    assert "processkit-no-such-binary-xyzzy" in excinfo.value.program


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT-to-self delivery differs on Windows")
def test_sync_run_is_interruptible() -> None:
    # A blocked sync run must honour Ctrl+C: fire SIGINT from a helper thread
    # while the main thread blocks in run(), and confirm it raises promptly
    # instead of waiting out the 30s child.
    import os
    import signal
    import threading
    import time

    def fire_sigint() -> None:
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)

    firer = threading.Thread(target=fire_sigint)
    firer.start()
    started = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            Command(PY, ["-c", "import time; time.sleep(30)"]).run()
    finally:
        firer.join()
    assert time.monotonic() - started < 10.0
