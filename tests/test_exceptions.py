"""Exception contracts: the `ProcessError` hierarchy, the stdlib-aliased bases,
the structured fields carried on raised instances, and the message-redaction
boundary.

These pin the *type* contract (bases, fields, what the message may carry); the
static drift guard in ``test_api_surface.py`` cannot see fields set at raise time,
so they are pinned here by actually raising each exception.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

import processkit
from processkit import (
    Command,
    NonZeroExit,
    OutputTooLarge,
    PermissionDenied,
    ProcessError,
    ProcessNotFound,
    Signalled,
    Timeout,
)

from .conftest import NO_SUCH_DIRECTORY, NO_SUCH_PROGRAM, PY


def _stub_declared_attrs(exc_type: type) -> set[str]:
    """Attribute names the stub declares for this exception class (AnnAssign
    class-body statements only — methods/dunders excluded)."""
    stub_path = pathlib.Path(processkit.__file__).with_name("_processkit.pyi")
    tree = ast.parse(stub_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == exc_type.__name__:
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError(f"{exc_type.__name__} not found in _processkit.pyi")


def _assert_no_phantom_stub_attrs(exc: BaseException) -> None:
    """Every attribute the stub declares for this exception's type must
    actually be present on the raised instance — a stub-only "phantom"
    attribute (declared in the `.pyi` but never actually `setattr`'d by
    `map_err`) would type-check yet raise `AttributeError` at runtime."""
    declared = _stub_declared_attrs(type(exc))
    actual = set(vars(exc))
    missing = declared - actual
    assert not missing, f"{type(exc).__name__}: stub declares phantom attrs {sorted(missing)}"


# --- hierarchy + stdlib aliasing --------------------------------------------


def test_exception_hierarchy() -> None:
    for exc in (NonZeroExit, Timeout, ProcessNotFound):
        assert issubclass(exc, ProcessError)


def test_timeout_is_a_timeout_error() -> None:
    assert issubclass(Timeout, TimeoutError)
    assert issubclass(Timeout, ProcessError)
    with pytest.raises(TimeoutError):
        Command(PY, ["-c", "import time; time.sleep(30)"]).timeout(0.2).run()


def test_process_not_found_is_a_file_not_found_error() -> None:
    assert issubclass(ProcessNotFound, FileNotFoundError)
    assert issubclass(ProcessNotFound, ProcessError)
    with pytest.raises(FileNotFoundError):
        Command(NO_SUCH_PROGRAM).run()


# --- structured fields per exception ----------------------------------------


def test_nonzero_exit_carries_structured_fields() -> None:
    code = "import sys; print('to-out'); sys.stderr.write('to-err'); sys.exit(5)"
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", code]).run()
    err = excinfo.value
    assert err.code == 5
    assert "to-out" in err.stdout
    assert "to-err" in err.stderr
    assert "python" in err.program.lower() or err.program == PY
    _assert_no_phantom_stub_attrs(err)


def test_timeout_error_carries_timeout_seconds() -> None:
    with pytest.raises(Timeout) as excinfo:
        Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).run()
    # This is the *configured* deadline, not the elapsed time (which would differ
    # from 0.3 by tens of milliseconds) — a tight tolerance only absorbs the
    # Duration<->f64 round trip, not measurement noise, so it still distinguishes
    # the two.
    assert excinfo.value.timeout_seconds == pytest.approx(0.3, abs=1e-9)
    # The other structured fields are attached too (partial output + program).
    assert isinstance(excinfo.value.stdout, str)
    assert isinstance(excinfo.value.stderr, str)
    assert excinfo.value.program
    _assert_no_phantom_stub_attrs(excinfo.value)


def test_process_not_found_carries_program() -> None:
    with pytest.raises(ProcessNotFound) as excinfo:
        Command(NO_SUCH_PROGRAM).output()
    assert NO_SUCH_PROGRAM in excinfo.value.program
    _assert_no_phantom_stub_attrs(excinfo.value)


def test_bad_cwd_is_not_misclassified_as_process_not_found() -> None:
    # A missing working directory is a `Spawn` failure, NOT a missing *program*: it
    # must surface as a plain ProcessError, never ProcessNotFound/FileNotFoundError
    # (which would mislead an `except FileNotFoundError` "program is optional" path).
    # The program here exists; only its cwd does not.
    with pytest.raises(ProcessError) as excinfo:
        Command(PY, ["-c", "pass"]).cwd(NO_SUCH_DIRECTORY).run()
    assert not isinstance(excinfo.value, ProcessNotFound)
    assert not isinstance(excinfo.value, FileNotFoundError)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal-kill semantics")
def test_signalled_carries_structured_fields() -> None:
    # A child that kills itself with a signal surfaces as `Signalled` carrying the
    # signal number plus the captured streams (not a generic NonZeroExit).
    killer = Command(PY, ["-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"])
    with pytest.raises(Signalled) as excinfo:
        killer.run()
    exc = excinfo.value
    assert exc.signal is not None and exc.signal > 0
    assert isinstance(exc.stdout, str) and isinstance(exc.stderr, str)
    assert exc.program
    _assert_no_phantom_stub_attrs(exc)


def test_nonzero_exit_over_output_bytes_carries_stdout_bytes() -> None:
    # A checking verb over the bytes path (`BytesResult.ensure_success()`) raises
    # `NonZeroExit` carrying the EXACT raw stdout bytes on `stdout_bytes` (crate
    # 2.1.0's `Error::stdout_bytes()`), even when that stdout isn't valid UTF-8 —
    # `.stdout` (the lossy text) would mangle it, `.stdout_bytes` is exact.
    code = "import sys; sys.stdout.buffer.write(bytes([0, 255, 1, 254])); sys.exit(3)"
    result = Command(PY, ["-c", code]).output_bytes()  # a non-zero exit is data here
    assert result.stdout == bytes([0, 255, 1, 254])
    with pytest.raises(NonZeroExit) as excinfo:
        result.ensure_success()
    exc = excinfo.value
    assert exc.code == 3
    assert exc.stdout_bytes == bytes([0, 255, 1, 254])
    _assert_no_phantom_stub_attrs(exc)


def test_text_path_nonzero_exit_has_stdout_bytes_none() -> None:
    # The companion to the above: on the text path (`run()`/`output()`)
    # `stdout_bytes` is present but `None` — the attribute is always set (so the
    # `stdout_bytes: bytes | None` stub never lies with an `AttributeError`), it
    # just carries no raw bytes there because `.stdout` is already the full text.
    code = "import sys; print('to-out'); sys.exit(7)"
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", code]).run()
    assert excinfo.value.stdout_bytes is None
    _assert_no_phantom_stub_attrs(excinfo.value)


def test_output_too_large_carries_byte_fields() -> None:
    # The byte-cap overflow path carries `max_bytes`/`total_bytes` (the line-cap
    # path is covered elsewhere). Pins those two fields against a silent rename;
    # `max_bytes`/`max_lines` mirror the `output_limit(...)` builder kwargs.
    flood = Command(PY, ["-c", "import sys; sys.stdout.write('x' * 100_000)"])
    with pytest.raises(OutputTooLarge) as excinfo:
        flood.output_limit(max_bytes=1024, on_overflow="error").run()
    exc = excinfo.value
    assert exc.max_bytes == 1024
    assert exc.total_bytes >= 1024
    assert exc.program
    _assert_no_phantom_stub_attrs(exc)


# --- message redaction (security boundary) ----------------------------------


def test_exception_message_redaction_boundary() -> None:
    # The exception *message* (str(exc)) must never carry argv or stdout; it may
    # carry a BOUNDED stderr excerpt. Pins the boundary so an upstream Display
    # change that started dumping argv/stdout (or unbounding stderr) is caught —
    # the raw values stay only on the structured fields (documented caveat).
    code = "import sys; print('STDOUT-SECRET-xyz'); sys.stderr.write('e' * 50000); sys.exit(7)"
    cmd = Command(PY, ["-c", code, "--token=ARGV-SECRET-abc"])
    with pytest.raises(NonZeroExit) as excinfo:
        cmd.run()
    msg = str(excinfo.value)
    assert "ARGV-SECRET-abc" not in msg, "argv must not appear in the exception message"
    assert "STDOUT-SECRET-xyz" not in msg, "stdout must not appear in the exception message"
    assert len(msg) < 2000, f"stderr excerpt must stay bounded, got {len(msg)} chars"
    # The full output is still available on the structured field.
    assert "STDOUT-SECRET-xyz" in excinfo.value.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec-bit permission semantics")
def test_permission_denied_on_non_executable(tmp_path: pathlib.Path) -> None:
    script = tmp_path / "not_exec.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o644)  # readable but not executable
    # `PermissionDenied` (concrete, not the builtin `PermissionError` it also
    # subclasses) so mypy sees `.program` directly, with no `type: ignore` needed.
    with pytest.raises(PermissionDenied) as excinfo:
        Command(str(script)).run()
    assert isinstance(excinfo.value, ProcessError)
    assert isinstance(excinfo.value, PermissionError)  # the stdlib-aliased base
    assert excinfo.value.program
    _assert_no_phantom_stub_attrs(excinfo.value)


def test_permission_denied_program_has_a_class_level_none_default() -> None:
    # The `Io`-sourced permission denial (no program named — e.g. an OS
    # refusing a group signal) isn't practically reachable in a hermetic
    # test (no double produces it, and the crate's `Error` is
    # `#[non_exhaustive]`, so it can't be constructed directly here either).
    # This pins the class-level default itself (mirroring
    # `Timeout.timeout_seconds`'s own default): a bare, un-raised
    # `PermissionDenied` reads `.program` as `None` rather than raising
    # `AttributeError`, so that path — whenever it *is* hit — behaves per the
    # `program: str | None` stub instead of crashing on attribute access.
    assert PermissionDenied("no program named").program is None
