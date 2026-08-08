"""In-process tests for the CLI's pure parsing and reporting helpers."""

from __future__ import annotations

import argparse
import errno
import io
import pathlib
import sys
from typing import Self, cast

import pytest

from processkit import Command, ResourceLimit, Unsupported
from processkit._cli import common, doctor, exit_codes, output, parser


class _RecordingCommand:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def env_clear(self) -> Self:
        self.calls.append(("env_clear",))
        return self

    def inherit_env(self, names: list[str]) -> Self:
        self.calls.append(("inherit_env", names))
        return self

    def env(self, key: str, value: str) -> Self:
        self.calls.append(("env", key, value))
        return self

    def cwd(self, path: str) -> Self:
        self.calls.append(("cwd", path))
        return self


class _FailingStream:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def write(self, _text: str) -> int:
        raise self.error


class _FlushFailingStream:
    """Accepts the write, then fails the per-line flush that follows it.

    `_FailingStream` above never reaches `_emit`'s flush: its `write` raises
    first. A receiver that goes away (or a device that fills up) between the two
    calls is a real case for the streaming re-emitters, which flush after every
    line, so it needs a stream that gets past `write`.
    """

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.written: list[str] = []

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        raise self.error


def _epipe_oserror() -> OSError:
    """A plain `OSError` carrying `EPIPE`, which its constructor cannot express.

    `OSError(errno.EPIPE, "...")` is *not* one: CPython's constructor maps a
    2-argument `OSError` onto the matching subclass and hands back a
    `BrokenPipeError`, which `_emit` catches one clause earlier. The
    `errno == EPIPE` arm of its `except OSError` therefore only ever sees an
    error raised as a bare `OSError` whose `errno` was set on the instance --
    the shape a foreign file-like object standing in for `sys.stdout` raises.
    """
    error = OSError("pipe closed")
    error.errno = errno.EPIPE
    return error


def test_split_child_argv_preserves_the_child_tail() -> None:
    assert parser._split_child_argv(["run", "--timeout", "1", "--", "tool", "--", "x"]) == (
        ["run", "--timeout", "1"],
        ["tool", "--", "x"],
    )
    assert parser._split_child_argv(["doctor", "--json"]) == (["doctor", "--json"], [])


def test_numeric_and_scheduling_parsers_accept_valid_values() -> None:
    assert parser._positive_int("4") == 4
    assert parser._positive_float("0.25") == 0.25
    assert parser._io_priority("idle") == ("idle", None)
    assert parser._io_priority("best_effort:7") == ("best_effort", 7)
    assert parser._cpu_affinity("3,1,3") == [3, 1, 3]


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parser._positive_int(value)


@pytest.mark.parametrize(
    ("subcommand", "option", "destination", "maximum"),
    [
        ("run", "--max-memory", "max_memory", (1 << 64) - 1),
        ("run", "--max-processes", "max_processes", (1 << 32) - 1),
        ("supervise", "--max-memory", "max_memory", (1 << 64) - 1),
        ("supervise", "--max-processes", "max_processes", (1 << 32) - 1),
        ("supervise", "--max-restarts", "max_restarts", (1 << 32) - 1),
    ],
)
def test_bounded_resource_integer_parsers_accept_binding_upper_bound(
    subcommand: str, option: str, destination: str, maximum: int
) -> None:
    top, _, _, _ = parser._build_parser()
    args = top.parse_args([subcommand, option, str(maximum)])
    assert getattr(args, destination) == maximum


@pytest.mark.parametrize(
    ("subcommand", "option", "destination"),
    [
        ("run", "--max-memory", "max_memory"),
        ("run", "--max-processes", "max_processes"),
        ("supervise", "--max-memory", "max_memory"),
        ("supervise", "--max-processes", "max_processes"),
        ("supervise", "--max-restarts", "max_restarts"),
    ],
)
def test_bounded_resource_integer_parsers_accept_binding_lower_bound(
    subcommand: str, option: str, destination: str
) -> None:
    top, _, _, _ = parser._build_parser()
    args = top.parse_args([subcommand, option, "1"])
    assert getattr(args, destination) == 1


@pytest.mark.parametrize(
    ("subcommand", "option", "value"),
    [
        ("run", "--max-memory", 1 << 64),
        ("run", "--max-processes", 1 << 32),
        ("supervise", "--max-memory", 1 << 64),
        ("supervise", "--max-processes", 1 << 32),
        ("supervise", "--max-restarts", 1 << 32),
    ],
)
def test_bounded_resource_integer_parsers_reject_first_value_above_binding_bound(
    subcommand: str, option: str, value: int
) -> None:
    top, _, _, _ = parser._build_parser()
    with pytest.raises(SystemExit) as exc_info:
        top.parse_args([subcommand, option, str(value)])
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    ("subcommand", "option"),
    [
        ("run", "--max-memory"),
        ("run", "--max-processes"),
        ("supervise", "--max-memory"),
        ("supervise", "--max-processes"),
        ("supervise", "--max-restarts"),
    ],
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_bounded_resource_integer_parsers_preserve_non_positive_rejection(
    subcommand: str, option: str, value: str
) -> None:
    top, _, _, _ = parser._build_parser()
    with pytest.raises(SystemExit) as exc_info:
        top.parse_args([subcommand, option, value])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "+inf", "-inf"])
def test_positive_float_rejects_non_positive_or_non_finite_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parser._positive_float(value)


@pytest.mark.parametrize("value", ["idle:1", "best_effort", "best_effort:x", "real_time:8"])
def test_io_priority_rejects_malformed_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parser._io_priority(value)


@pytest.mark.parametrize("value", ["", "1,", "-1", "one"])
def test_cpu_affinity_rejects_malformed_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parser._cpu_affinity(value)


def test_build_parser_maps_cli_values_without_running_a_child() -> None:
    top, _, _, _ = parser._build_parser()
    args = top.parse_args(
        [
            "run",
            "--timeout",
            "1.5",
            "--io-priority",
            "real_time:2",
            "--cpu-affinity",
            "0,2",
        ]
    )
    assert args.subcommand == "run"
    assert args.timeout == 1.5
    assert args.io_priority == ("real_time", 2)
    assert args.cpu_affinity == [0, 2]


def test_environment_helpers_merge_files_then_flags(tmp_path: pathlib.Path) -> None:
    env_file = tmp_path / "tool.env"
    env_file.write_text("\ufeff# comment\n A =first\nEMPTY=\n", encoding="utf-8")
    arg_parser = argparse.ArgumentParser(prog="processkit")
    assert common._parse_environment(
        arg_parser,
        [str(env_file)],
        ["A=override", "B=two=parts"],
    ) == [("A", "first"), ("EMPTY", ""), ("A", "override"), ("B", "two=parts")]


@pytest.mark.parametrize("raw", ["MISSING_EQUALS", "=missing-key"])
def test_environment_flags_report_usage_errors(raw: str) -> None:
    arg_parser = argparse.ArgumentParser(prog="processkit")
    with pytest.raises(SystemExit) as exc_info:
        common._parse_env_flags(arg_parser, [raw])
    assert exc_info.value.code == 2


def test_environment_file_reports_the_source_line(tmp_path: pathlib.Path) -> None:
    env_file = tmp_path / "bad.env"
    env_file.write_text("OK=1\nbroken\n", encoding="utf-8")
    arg_parser = argparse.ArgumentParser(prog="processkit")
    with pytest.raises(SystemExit) as exc_info:
        common._parse_env_files(arg_parser, [str(env_file)])
    assert exc_info.value.code == 2


def test_apply_environment_preserves_cli_order() -> None:
    recording = _RecordingCommand()
    result = cast(
        _RecordingCommand,
        common._apply_environment(
            cast(Command, recording),
            clear=True,
            inherited=["PATH"],
            pairs=[("A", "1"), ("A", "2")],
            cwd="work",
        ),
    )
    assert result is recording
    assert recording.calls == [
        ("env_clear",),
        ("inherit_env", ["PATH"]),
        ("env", "A", "1"),
        ("env", "A", "2"),
        ("cwd", "work"),
    ]


def test_emit_writes_one_line_and_handles_a_missing_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    assert output.emit_stdout("hello")
    assert stream.getvalue() == "hello\n"
    monkeypatch.setattr(sys, "stdout", None)
    assert not output.emit_stdout("ignored")


@pytest.mark.parametrize(
    "error",
    [BrokenPipeError(), _epipe_oserror()],
)
def test_emit_treats_a_vanished_receiver_as_nonfatal(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    monkeypatch.setattr(sys, "stderr", _FailingStream(error))
    assert not output.emit_stderr("hello")
    assert sys.stderr is None


@pytest.mark.parametrize(
    "stream",
    [_FailingStream(OSError(errno.EIO, "device failed")), io.StringIO()],
)
def test_emit_wraps_other_write_failures(
    monkeypatch: pytest.MonkeyPatch, stream: _FailingStream | io.StringIO
) -> None:
    if isinstance(stream, io.StringIO):
        stream.close()
    monkeypatch.setattr(sys, "stderr", stream)
    with pytest.raises(output.OutputWriteError):
        output.emit_stderr("hello")
    assert sys.stderr is None


@pytest.mark.parametrize(
    "error",
    [BrokenPipeError(), _epipe_oserror()],
)
def test_emit_treats_a_receiver_lost_at_flush_as_nonfatal(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    stream = _FlushFailingStream(error)
    monkeypatch.setattr(sys, "stderr", stream)
    assert not output.emit_stderr("hello")
    assert stream.written == ["hello\n"]
    assert sys.stderr is None


@pytest.mark.parametrize(
    "error",
    [OSError(errno.EIO, "device failed"), ValueError("I/O operation on closed file")],
)
def test_emit_wraps_other_flush_failures(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    stream = _FlushFailingStream(error)
    monkeypatch.setattr(sys, "stderr", stream)
    with pytest.raises(output.OutputWriteError, match="could not flush stderr"):
        output.emit_stderr("hello")
    assert stream.written == ["hello\n"]
    assert sys.stderr is None


def test_doctor_payload_has_stable_host_and_error_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = {
        "mechanism": "job_object",
        "soft_stop_scope": "whole_tree",
        "parent_death_cleanup": "whole_tree",
        "crate_version": "3.1.0",
    }
    monkeypatch.setattr(doctor, "_host_containment_payload", lambda: host)
    payload = doctor._doctor_json_payload(
        mechanism="job_object",
        verdict="ERROR",
        exit_code=exit_codes.EXIT_DOCTOR_PROBE_ERROR,
        resource_limits={"max_memory": False},
        error_probe_failures=["probe failed"],
    )
    assert payload["host_containment"] == host
    assert payload["error_probe_failures"] == ["probe failed"]
    assert payload["exit_code"] == 4


class _DoctorGroup:
    mechanism = "job_object"


def _doctor_host() -> dict[str, str]:
    return {
        "mechanism": "job_object",
        "soft_stop_scope": "whole_tree",
        "parent_death_cleanup": "whole_tree",
        "crate_version": "3.1.0",
    }


def test_doctor_text_report_covers_the_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []
    monkeypatch.setattr(doctor, "ProcessGroup", lambda **_kwargs: _DoctorGroup())
    monkeypatch.setattr(doctor, "_host_containment_payload", _doctor_host)
    monkeypatch.setattr(doctor, "emit_stdout", lines.append)
    assert doctor._doctor() == exit_codes.EXIT_DOCTOR_OK
    assert any("graceful-stop scope" in line for line in lines)
    assert any("resource limits        : available" in line for line in lines)


def test_doctor_json_reports_an_unavailable_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict[str, object]] = []

    def construct(**kwargs: object) -> _DoctorGroup:
        if kwargs.get("max_memory") is not None:
            raise ResourceLimit("memory controller unavailable")
        return _DoctorGroup()

    monkeypatch.setattr(doctor, "ProcessGroup", construct)
    monkeypatch.setattr(doctor, "_host_containment_payload", _doctor_host)
    monkeypatch.setattr(doctor, "_emit_doctor_json", payloads.append)
    assert doctor._doctor(json_output=True) == exit_codes.EXIT_DOCTOR_LIMITS_UNAVAILABLE
    assert payloads[0]["verdict"] == "DEGRADED"
    assert payloads[0]["resource_limits"] == {
        "max_memory": False,
        "max_processes": True,
        "cpu_quota": True,
    }


def test_doctor_distinguishes_a_limit_probe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    lines: list[str] = []

    def construct(**kwargs: object) -> _DoctorGroup:
        if kwargs.get("max_processes") is not None:
            raise OSError("cannot read pids.max")
        if kwargs.get("max_memory") is not None:
            raise Unsupported("memory unavailable")
        return _DoctorGroup()

    monkeypatch.setattr(doctor, "ProcessGroup", construct)
    monkeypatch.setattr(doctor, "_host_containment_payload", _doctor_host)
    monkeypatch.setattr(doctor, "emit_stdout", lines.append)
    assert doctor._doctor() == exit_codes.EXIT_DOCTOR_PROBE_ERROR
    assert any("error probing" in line for line in lines)
    assert any("also unavailable" in line for line in lines)


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_verdict"),
    [
        (Unsupported("no containment"), exit_codes.EXIT_DOCTOR_NO_CONTAINMENT, "UNAVAILABLE"),
        (OSError("probe failed"), exit_codes.EXIT_DOCTOR_PROBE_ERROR, "ERROR"),
    ],
)
def test_doctor_json_reports_mechanism_probe_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_code: int,
    expected_verdict: str,
) -> None:
    payloads: list[dict[str, object]] = []

    def construct(**_kwargs: object) -> _DoctorGroup:
        raise error

    monkeypatch.setattr(doctor, "ProcessGroup", construct)
    monkeypatch.setattr(doctor, "_host_containment_payload", _doctor_host)
    monkeypatch.setattr(doctor, "_emit_doctor_json", payloads.append)
    assert doctor._doctor(json_output=True) == expected_code
    assert payloads[0]["verdict"] == expected_verdict


def test_cli_exit_code_namespaces_are_disjoint() -> None:
    run_codes = {
        exit_codes.EXIT_IDLE_TIMEOUT,
        exit_codes.EXIT_TIMEOUT,
        exit_codes.EXIT_INTERNAL_ERROR,
        exit_codes.EXIT_NOT_EXECUTABLE,
        exit_codes.EXIT_NOT_FOUND,
    }
    supervise_codes = {
        exit_codes.EXIT_SUPERVISE_INTERNAL_ERROR,
        exit_codes.EXIT_SUPERVISE_RESTARTS_EXHAUSTED,
        exit_codes.EXIT_SUPERVISE_GAVE_UP,
    }
    doctor_codes = {
        exit_codes.EXIT_DOCTOR_OK,
        exit_codes.EXIT_DOCTOR_LIMITS_UNAVAILABLE,
        exit_codes.EXIT_DOCTOR_USAGE_ERROR,
        exit_codes.EXIT_DOCTOR_NO_CONTAINMENT,
        exit_codes.EXIT_DOCTOR_PROBE_ERROR,
    }
    assert run_codes.isdisjoint(supervise_codes | doctor_codes)
    assert supervise_codes.isdisjoint(doctor_codes)
    assert exit_codes.EXIT_OUTPUT_LOST not in run_codes | supervise_codes | doctor_codes
