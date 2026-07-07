"""Tests for scripts/ci-privileged-guard.py's PASS/FAIL classification."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci-privileged-guard.py"


def _load_guard_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_privileged_guard", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard_module()


def _write_junit(tmp_path: Path, testcase_body: str) -> Path:
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.test_command" name="test_privilege_drop">{testcase_body}</testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    return junit_path


def test_passing_testcase_with_system_out_and_properties_is_not_flagged(
    tmp_path: Path,
) -> None:
    junit_path = _write_junit(
        tmp_path,
        "<system-out>captured stdout</system-out>"
        "<system-err>captured stderr</system-err>"
        '<properties><property name="foo" value="bar"/></properties>',
    )
    exit_code = guard.main(
        [
            "ci-privileged-guard.py",
            str(junit_path),
            "tests/test_command.py::test_privilege_drop",
        ]
    )
    assert exit_code == 0


def test_skipped_testcase_is_still_flagged(tmp_path: Path) -> None:
    junit_path = _write_junit(tmp_path, '<skipped message="skipped for a reason"/>')
    exit_code = guard.main(
        [
            "ci-privileged-guard.py",
            str(junit_path),
            "tests/test_command.py::test_privilege_drop",
        ]
    )
    assert exit_code == 1


def test_failed_testcase_is_still_flagged(tmp_path: Path) -> None:
    junit_path = _write_junit(tmp_path, '<failure message="boom">traceback</failure>')
    exit_code = guard.main(
        [
            "ci-privileged-guard.py",
            str(junit_path),
            "tests/test_command.py::test_privilege_drop",
        ]
    )
    assert exit_code == 1


def test_errored_testcase_is_still_flagged(tmp_path: Path) -> None:
    junit_path = _write_junit(tmp_path, '<error message="boom">traceback</error>')
    exit_code = guard.main(
        [
            "ci-privileged-guard.py",
            str(junit_path),
            "tests/test_command.py::test_privilege_drop",
        ]
    )
    assert exit_code == 1


def test_missing_testcase_is_flagged(tmp_path: Path) -> None:
    junit_path = _write_junit(tmp_path, "")
    exit_code = guard.main(
        [
            "ci-privileged-guard.py",
            str(junit_path),
            "tests/test_command.py::test_does_not_exist",
        ]
    )
    assert exit_code == 1
