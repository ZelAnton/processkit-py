"""Load and verify the exact release-artifact toolchain snapshot."""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence

SNAPSHOT_RELATIVE_PATH = pathlib.Path("scripts/release/toolchain.env")
REQUIRED_KEYS = (
    "CIBUILDWHEEL_VERSION",
    "MATURIN_VERSION",
    "TWINE_VERSION",
    "RUST_TOOLCHAIN",
)
_EXACT_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}")
_FLOATING_PACKAGE_RE = re.compile(
    r"(?:cibuildwheel|maturin|twine)[^\r\n]{0,24}(?:>=|<=|~=|(?<![=])>|(?<![=])<|\*)",
    re.IGNORECASE,
)


def load_snapshot(path: pathlib.Path) -> dict[str, str]:
    """Read a strict KEY=VERSION snapshot with exactly the required keys."""
    return load_snapshot_text(path.read_text(encoding="utf-8"))


def maturin_install_command(snapshot: Mapping[str, str]) -> list[str]:
    """Build the exact, snapshot-bound maturin installation command."""
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        f"maturin=={snapshot['MATURIN_VERSION']}",
    ]


def _workflow_job_steps(workflow: str, job_name: str) -> list[str]:
    lines = workflow.splitlines(keepends=True)
    marker = f"  {job_name}:"
    try:
        start = next(index for index, line in enumerate(lines) if line.rstrip() == marker)
    except StopIteration as error:
        raise ValueError(f"workflow job is missing: {job_name}") from error

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            end = index
            break
    job_lines = lines[start + 1 : end]
    try:
        steps_start = next(
            index for index, line in enumerate(job_lines) if line.rstrip() == "    steps:"
        )
    except StopIteration as error:
        raise ValueError(f"workflow job has no steps: {job_name}") from error

    step_starts = [
        index
        for index in range(steps_start + 1, len(job_lines))
        if job_lines[index].startswith("      - ")
    ]
    return [
        "".join(job_lines[start_index:end_index])
        for start_index, end_index in zip(
            step_starts, [*step_starts[1:], len(job_lines)], strict=True
        )
    ]


def _workflow_job_permissions(workflow: str, job_name: str) -> dict[str, str] | None:
    lines = workflow.splitlines()
    marker = f"  {job_name}:"
    try:
        start = next(index for index, line in enumerate(lines) if line.rstrip() == marker)
    except StopIteration as error:
        raise ValueError(f"workflow job is missing: {job_name}") from error

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            end = index
            break
    job_lines = lines[start + 1 : end]
    try:
        permissions_start = next(
            index for index, line in enumerate(job_lines) if line.rstrip() == "    permissions:"
        )
    except StopIteration:
        return None

    permissions: dict[str, str] = {}
    for line in job_lines[permissions_start + 1 :]:
        stripped = line.lstrip()
        indentation = len(line) - len(stripped)
        active = _without_unquoted_comment(stripped)
        if active and indentation <= 4:
            break
        if not active:
            continue
        if indentation != 6:
            raise ValueError(f"invalid job permission in {job_name}: {active}")
        key, separator, value = active.partition(":")
        if separator != ":" or not key or not value.strip() or key in permissions:
            raise ValueError(f"invalid job permission in {job_name}: {active}")
        permissions[key] = value.strip()
    return permissions


def _without_unquoted_comment(value: str) -> str:
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
            continue
        if character == "#" and not quote and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def _workflow_step_executable_commands(step: str) -> list[str]:
    lines = step.splitlines()
    executable: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        indentation = len(line) - len(stripped)
        active = _without_unquoted_comment(stripped)
        if not active:
            index += 1
            continue

        if indentation == 6 and active.startswith("- uses:"):
            executable.append(active[2:].strip())
            index += 1
            continue
        if indentation == 8 and active.startswith("run:"):
            value = active.removeprefix("run:").strip()
            if value not in {"|", "|-", "|+", ">", ">-", ">+"}:
                if value:
                    executable.append(value)
                index += 1
                continue

            folded = value.startswith(">")
            block_commands: list[str] = []
            index += 1
            while index < len(lines):
                block_line = lines[index]
                block_stripped = block_line.lstrip()
                block_indentation = len(block_line) - len(block_stripped)
                if block_stripped and block_indentation <= 8:
                    break
                block_active = _without_unquoted_comment(block_stripped)
                if block_active:
                    block_commands.append(block_active)
                index += 1
            if folded and block_commands:
                executable.append(" ".join(block_commands))
            else:
                executable.extend(block_commands)
            continue
        if indentation == 8 and active == "with:":
            index += 1
            while index < len(lines):
                field_line = lines[index]
                field_stripped = field_line.lstrip()
                field_indentation = len(field_line) - len(field_stripped)
                if field_stripped and field_indentation <= 8:
                    break
                field_active = _without_unquoted_comment(field_stripped)
                if (
                    field_indentation == 10
                    and field_active.startswith("toolchain:")
                    and field_active.removeprefix("toolchain:").strip()
                ):
                    executable.append(field_active)
                index += 1
            continue
        index += 1
    return executable


def _workflow_step_field(step: str, field: str) -> str | None:
    for line in step.splitlines():
        stripped = line.lstrip()
        indentation = len(line) - len(stripped)
        active = _without_unquoted_comment(stripped)
        if indentation == 6 and active.startswith("- "):
            active = active[2:].strip()
        elif indentation != 8:
            continue
        key, separator, value = active.partition(":")
        if separator == ":" and key == field:
            return value.strip() or None
    return None


def _normalize_workflow_condition(condition: str | None) -> str | None:
    if condition is None:
        return None
    normalized = condition.strip()
    if normalized.startswith("${{") and normalized.endswith("}}"):
        normalized = normalized[3:-2].strip()
    return " ".join(normalized.split())


def _workflow_step_matches_condition(step: str, required_condition: str | None) -> bool:
    actual = _normalize_workflow_condition(_workflow_step_field(step, "if"))
    if actual is not None and actual.casefold() == "false":
        return False
    if required_condition is None:
        return True
    return actual == _normalize_workflow_condition(required_condition)


def _check_load_before_consumers(
    errors: list[str],
    *,
    label: str,
    workflow: str,
    job_name: str,
    load_command: str,
    consumer_commands: Sequence[str],
    required_condition: str | None = None,
    required_shell: str | None = None,
) -> None:
    try:
        steps = _workflow_job_steps(workflow, job_name)
    except ValueError as error:
        errors.append(str(error))
        return

    executable_steps = [_workflow_step_executable_commands(step) for step in steps]
    matching_steps = [_workflow_step_matches_condition(step, required_condition) for step in steps]
    load_steps = [
        index
        for index, commands in enumerate(executable_steps)
        if matching_steps[index] and load_command in commands
    ]
    if len(load_steps) != 1:
        errors.append(f"{label}: expected one executable snapshot-load step")
        return
    load_index = load_steps[0]
    if required_shell is not None:
        actual_shell = _workflow_step_field(steps[load_index], "shell")
        if actual_shell != required_shell:
            errors.append(f"{label}: snapshot-load step must use shell: {required_shell}")
    for command in consumer_commands:
        consumer_steps = [
            index
            for index, commands in enumerate(executable_steps)
            if matching_steps[index] and command in commands
        ]
        if len(consumer_steps) != 1:
            errors.append(f"{label}: expected one executable consumer step: {command}")
        elif consumer_steps[0] <= load_index:
            errors.append(f"{label}: snapshot load must precede consumer: {command}")
        elif required_shell is not None:
            actual_shell = _workflow_step_field(steps[consumer_steps[0]], "shell")
            if actual_shell != required_shell:
                errors.append(f"{label}: consumer step must use shell: {required_shell}")


def release_toolchain_errors(
    root: pathlib.Path, overrides: Mapping[str, str] | None = None
) -> list[str]:
    """Return release-snapshot drift errors for repository consumers."""
    replacements = overrides or {}

    def read(relative: str) -> str:
        return replacements.get(relative, (root / relative).read_text(encoding="utf-8"))

    errors: list[str] = []
    snapshot_path = SNAPSHOT_RELATIVE_PATH.as_posix()
    try:
        snapshot_text = read(snapshot_path)
        snapshot = load_snapshot_text(snapshot_text)
    except ValueError as error:
        return [str(error)]

    build_workflow = read(".github/workflows/_build-dists.yml")
    ci_workflow = read(".github/workflows/ci.yml")
    release_workflow = read(".github/workflows/release.yml")
    test_release_workflow = read(".github/workflows/test-release.yml")
    pyproject = read("pyproject.toml")
    rust_toolchain = read("rust-toolchain.toml")

    expected_counts = {
        "build workflow snapshot loads": (
            build_workflow,
            "python scripts/release/toolchain.py export-github-env",
            2,
        ),
        "Linux image pre-pull cibuildwheel consumer": (
            build_workflow,
            'uvx --from "cibuildwheel==${CIBUILDWHEEL_VERSION}"',
            1,
        ),
        "wheel-build cibuildwheel consumer": (
            build_workflow,
            'uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}"',
            1,
        ),
        "sdist maturin consumer": (
            build_workflow,
            'uvx "maturin==${MATURIN_VERSION}"',
            1,
        ),
        "host Rust consumer": (
            build_workflow,
            "toolchain: ${{ env.RUST_TOOLCHAIN }}",
            1,
        ),
        "CI workflow snapshot loads": (
            ci_workflow,
            "python scripts/release/toolchain.py export-github-env",
            3,
        ),
        "CI cibuildwheel consumers": (
            ci_workflow,
            'uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}"',
            3,
        ),
        "release workflow snapshot load": (
            release_workflow,
            "python scripts/release/toolchain.py export-github-env",
            1,
        ),
        "PyPI twine consumer": (
            release_workflow,
            'uvx "twine==${TWINE_VERSION}"',
            1,
        ),
        "TestPyPI workflow snapshot load": (
            test_release_workflow,
            "python scripts/release/toolchain.py export-github-env",
            1,
        ),
        "TestPyPI twine consumer": (
            test_release_workflow,
            'uvx "twine==${TWINE_VERSION}"',
            1,
        ),
    }
    for label, (text, fragment, expected) in expected_counts.items():
        actual = text.count(fragment)
        if actual != expected:
            errors.append(f"{label}: expected {expected}, found {actual}")

    load_command = 'python scripts/release/toolchain.py export-github-env >> "$GITHUB_ENV"'
    ordering_checks = (
        (
            "wheel-build job",
            build_workflow,
            "build_wheels",
            (
                "toolchain: ${{ env.RUST_TOOLCHAIN }}",
                'uvx --from "cibuildwheel==${CIBUILDWHEEL_VERSION}" python '
                "scripts/release/pull_cibuildwheel_images.py",
                'uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}" --output-dir wheelhouse',
            ),
        ),
        (
            "sdist job",
            build_workflow,
            "build_sdist",
            ('uvx "maturin==${MATURIN_VERSION}" sdist --out dist',),
        ),
        (
            "CI musllinux wheel job",
            ci_workflow,
            "build-musllinux",
            (
                'uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}" '
                "--platform linux --output-dir wheelhouse",
            ),
        ),
        (
            "PyPI publish job",
            release_workflow,
            "publish",
            (
                'uvx "twine==${TWINE_VERSION}" check --strict '
                "./artifacts/*.whl ./artifacts/*.tar.gz",
            ),
        ),
        (
            "TestPyPI publish job",
            test_release_workflow,
            "publish_testpypi",
            ('uvx "twine==${TWINE_VERSION}" check --strict ./dist/*',),
        ),
    )
    for label, workflow, job_name, consumers in ordering_checks:
        _check_load_before_consumers(
            errors,
            label=label,
            workflow=workflow,
            job_name=job_name,
            load_command=load_command,
            consumer_commands=consumers,
        )

    _check_load_before_consumers(
        errors,
        label="CI Windows ARM64 wheel job",
        workflow=ci_workflow,
        job_name="test",
        load_command=load_command,
        consumer_commands=('uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}" --output-dir wheelhouse',),
        required_condition=("matrix.os == 'windows-11-arm' && matrix.python == '3.14t'"),
        required_shell="bash",
    )
    _check_load_before_consumers(
        errors,
        label="CI wheel-selector job",
        workflow=ci_workflow,
        job_name="build",
        load_command=load_command,
        consumer_commands=(
            'ids=$(uvx "cibuildwheel==${CIBUILDWHEEL_VERSION}" '
            "--print-build-identifiers --platform linux)",
        ),
        required_condition="matrix.os == 'ubuntu-latest'",
    )

    try:
        testpypi_permissions = _workflow_job_permissions(test_release_workflow, "publish_testpypi")
    except ValueError as error:
        errors.append(str(error))
    else:
        expected_permissions = {"contents": "read", "id-token": "write"}
        if testpypi_permissions != expected_permissions:
            errors.append("TestPyPI publish job must grant only contents: read and id-token: write")

    workflow_text = "\n".join(
        (build_workflow, ci_workflow, release_workflow, test_release_workflow)
    )
    if _FLOATING_PACKAGE_RE.search(workflow_text) is not None:
        errors.append("release workflows contain a floating package-tool version")
    if re.search(r"toolchain:\s*stable\b", build_workflow) is not None:
        errors.append("host Rust toolchain is floating")
    if '--default-toolchain "$RUST_TOOLCHAIN"' not in pyproject:
        errors.append("Linux containers do not install RUST_TOOLCHAIN")
    if re.search(r"--default-toolchain\s+stable\b", pyproject) is not None:
        errors.append("Linux container Rust toolchain is floating")

    pyproject_fragments = (
        'build-frontend = { name = "build", args = ["--no-isolation"] }',
        'before-build = "python {package}/scripts/release/toolchain.py install-maturin"',
        'environment-pass = ["RUST_TOOLCHAIN"]',
    )
    for fragment in pyproject_fragments:
        if pyproject.count(fragment) != 1:
            errors.append(f"missing or duplicated cibuildwheel snapshot consumer: {fragment}")

    rust_version = snapshot["RUST_TOOLCHAIN"]
    if rust_toolchain.count(f'channel = "{rust_version}"') != 1:
        errors.append("rust-toolchain.toml does not mirror RUST_TOOLCHAIN")
    for component in ("rustfmt", "clippy"):
        if component not in rust_toolchain:
            errors.append(f"rust-toolchain.toml is missing {component}")

    expected_prefix = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    expected_requirement = f"maturin=={snapshot['MATURIN_VERSION']}"
    if maturin_install_command(snapshot) != [*expected_prefix, expected_requirement]:
        errors.append("maturin install is not exact or snapshot-bound")
    probe_snapshot = {**snapshot, "MATURIN_VERSION": "0.0.1"}
    if maturin_install_command(probe_snapshot) != [*expected_prefix, "maturin==0.0.1"]:
        errors.append("maturin install does not follow the snapshot version")
    return errors


def load_snapshot_text(text: str) -> dict[str, str]:
    """Parse snapshot text through the same strict reader used on disk."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or key not in REQUIRED_KEYS:
            raise ValueError(f"invalid snapshot entry on line {line_number}: {raw_line!r}")
        if key in values:
            raise ValueError(f"duplicate snapshot key on line {line_number}: {key}")
        if _EXACT_VERSION_RE.fullmatch(value) is None:
            raise ValueError(f"{key} must be an exact X.Y.Z version, got {value!r}")
        values[key] = value
    missing = set(REQUIRED_KEYS) - values.keys()
    if missing:
        raise ValueError(f"snapshot is missing keys: {', '.join(sorted(missing))}")
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export-github-env", "install-maturin", "verify"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = pathlib.Path(__file__).resolve().parents[2]
    snapshot = load_snapshot(root / SNAPSHOT_RELATIVE_PATH)

    if args.command == "verify":
        errors = release_toolchain_errors(root)
        if errors:
            raise SystemExit("\n".join(errors))
        return 0
    if args.command == "export-github-env":
        errors = release_toolchain_errors(root)
        if errors:
            raise SystemExit("\n".join(errors))
        for key in REQUIRED_KEYS:
            print(f"{key}={snapshot[key]}")
        return 0

    subprocess.run(maturin_install_command(snapshot), check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
