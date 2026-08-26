"""Unit tests for `scripts/release/*.py` — the pure functions extracted from
`release.yml`'s inline heredocs (CHANGELOG.md manipulation, Cargo.lock version
sync). A minimal local Git history verifies release-range selection; git-cliff
and the network remain isolated behind mocks or the actual release workflow.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
from unittest import mock

import pytest
from scripts.release.cargo_lock import bump_local_crate_version
from scripts.release.cargo_lock import main as cargo_lock_main
from scripts.release.changelog import (
    _cmd_autofill,
    _cmd_extract_notes,
    _cmd_promote,
    dedupe_generated_changes,
    extract_release_notes,
    git_cliff_range,
    insert_unreleased_body,
    promote_unreleased,
    unreleased_has_bullets,
)
from scripts.release.pull_cibuildwheel_images import (
    _parse_pinned_images,
    _pull_with_retry,
)

CLIFF_TOML = pathlib.Path(__file__).resolve().parents[1] / "cliff.toml"
GIT = shutil.which("git")
GIT_CLIFF = shutil.which("git-cliff")
RELEASE_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
)

_PARSER_ENTRY_RE = re.compile(
    r'\{\s*message\s*=\s*"((?:[^"\\]|\\.)*)"\s*,\s*(skip\s*=\s*true|group\s*=\s*"[^"]*")\s*\}'
)


def _run_git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert GIT is not None
    return subprocess.run(
        [GIT, "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: pathlib.Path, subject: str) -> str:
    tracked = repo / "tracked.txt"
    tracked.write_text(subject, encoding="utf-8")
    _run_git(repo, "add", tracked.name)
    _run_git(
        repo,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release-test@example.invalid",
        "commit",
        "-m",
        subject,
    )
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


# --- cibuildwheel image pre-pull --------------------------------------------


def test_parse_pinned_images_uses_exact_digest_for_native_architecture() -> None:
    config = """\
[x86_64]
manylinux_2_28 = quay.io/example/many@sha256:111 # release pin
musllinux_1_2 = quay.io/example/musl@sha256:222 # release pin
"""
    assert _parse_pinned_images(config, "AMD64") == (
        "quay.io/example/many@sha256:111",
        "quay.io/example/musl@sha256:222",
    )


def test_pull_with_retry_retries_a_transient_registry_failure() -> None:
    failed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
        ["docker", "pull"], returncode=1
    )
    succeeded: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
        ["docker", "pull"], returncode=0
    )
    with (
        mock.patch(
            "scripts.release.pull_cibuildwheel_images.subprocess.run",
            side_effect=[failed, succeeded],
        ) as run,
        mock.patch("scripts.release.pull_cibuildwheel_images.time.sleep") as sleep,
    ):
        _pull_with_retry("quay.io/example/image@sha256:123")

    assert run.call_count == 2
    sleep.assert_called_once_with(10)


def test_pull_with_retry_fails_after_three_attempts() -> None:
    failed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
        ["docker", "pull"], returncode=1
    )
    with (
        mock.patch(
            "scripts.release.pull_cibuildwheel_images.subprocess.run",
            return_value=failed,
        ) as run,
        mock.patch("scripts.release.pull_cibuildwheel_images.time.sleep") as sleep,
        pytest.raises(RuntimeError, match="after 3 attempts"),
    ):
        _pull_with_retry("quay.io/example/image@sha256:123")

    assert run.call_count == 3
    assert sleep.call_args_list == [mock.call(10), mock.call(20)]


def _cliff_commit_parsers() -> list[tuple[str, bool]]:
    """`(regex, is_skip)` pairs from `cliff.toml`'s `commit_parsers`, in file
    order. A deliberately tiny TOML reader (just enough for this one array of
    inline tables) — `tomllib` is 3.11+ and the floor is 3.10, same reasoning
    as `test_api_surface._section_version`. Un-escapes TOML's doubled
    backslashes (`\\\\d` -> `\\d`) back into a plain regex pattern.
    """
    text = CLIFF_TOML.read_text(encoding="utf-8")
    return [
        (re.sub(r"\\(.)", r"\1", raw_message), tail.strip().startswith("skip"))
        for raw_message, tail in _PARSER_ENTRY_RE.findall(text)
    ]


# --- cliff.toml: commit_parsers skip rules ----------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Initialize integration workspace for batch B-20260711T155830Z",
        "Open integration workspace for batch B-20260712T150224Z",
        "Initialize integration workspace",
        "Initialize integration workspace at batch base",
    ],
)
def test_cliff_toml_skips_integration_workspace_bookkeeping_commits(message: str) -> None:
    parsers = _cliff_commit_parsers()
    assert any(is_skip and re.match(pattern, message) for pattern, is_skip in parsers)


@pytest.mark.parametrize(
    "message",
    [
        "Add a new feature",
        "Fix a parsing bug",
        "Refactor the retry helper",
    ],
)
def test_cliff_toml_does_not_skip_user_facing_commits(message: str) -> None:
    parsers = _cliff_commit_parsers()
    matched_skip = any(is_skip and re.match(pattern, message) for pattern, is_skip in parsers)
    assert not matched_skip


# --- changelog: dedupe_generated_changes ------------------------------------


def test_dedupe_generated_changes_collapses_duplicate_bullets_in_a_section() -> None:
    generated = (
        "### Changed\n"
        "- Publish documentation site to GitHub Pages\n"
        "- Bump processkit dependency to 2.2.4\n"
        "- Bump processkit dependency to 2.2.4\n"
        "- Bump processkit dependency to 2.2.4\n"
    )
    result = dedupe_generated_changes(generated)
    assert result.count("Bump processkit dependency to 2.2.4") == 1
    assert "Publish documentation site to GitHub Pages" in result


def test_dedupe_generated_changes_drops_empty_bullets() -> None:
    generated = "### Changed\n- a real change\n- \n-\n"
    result = dedupe_generated_changes(generated)
    assert result == "### Changed\n- a real change"


def test_dedupe_generated_changes_drops_a_section_left_with_no_bullets() -> None:
    # A group whose only commits were bookkeeping/blank ends up empty after
    # per-line filtering; its now-content-free header should not survive as
    # a bare "### Changed" with nothing under it.
    generated = "### Added\n- a new thing\n\n### Changed\n-\n\n### Fixed\n- a bugfix\n"
    result = dedupe_generated_changes(generated)
    assert "### Changed" not in result
    assert "### Added\n- a new thing" in result
    assert "### Fixed\n- a bugfix" in result


def test_dedupe_generated_changes_preserves_order_and_distinct_bullets() -> None:
    generated = "### Added\n- first thing\n- second thing\n- third thing\n"
    result = dedupe_generated_changes(generated)
    assert result == generated.strip()


def test_dedupe_generated_changes_dedupes_independently_per_section() -> None:
    # The same wording repeated in two different groups is not a duplicate
    # across sections — only within one.
    generated = "### Added\n- shared wording\n\n### Fixed\n- shared wording\n"
    result = dedupe_generated_changes(generated)
    assert result.count("shared wording") == 2


# --- changelog: unreleased_has_bullets --------------------------------------


def test_unreleased_has_bullets_true_with_a_real_bullet() -> None:
    text = "## [Unreleased]\n\n### Added\n- did a thing\n\n## [1.0.0] - 2026-01-01\n"
    assert unreleased_has_bullets(text)


def test_unreleased_has_bullets_false_when_placeholder_only() -> None:
    text = "## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n"
    assert not unreleased_has_bullets(text)


def test_unreleased_has_bullets_false_when_header_missing() -> None:
    assert not unreleased_has_bullets("# Changelog\n\n## [1.0.0] - 2026-01-01\n")


# --- changelog: insert_unreleased_body --------------------------------------


def test_insert_unreleased_body_replaces_the_section() -> None:
    text = "## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n"
    result = insert_unreleased_body(text, "### Fixed\n- a generated bullet")
    assert "### Fixed\n- a generated bullet" in result
    assert "## [1.0.0] - 2026-01-01" in result
    # The placeholder body is gone.
    assert "### Added\n-\n" not in result


def test_insert_unreleased_body_raises_without_header() -> None:
    with pytest.raises(ValueError, match="Unreleased"):
        insert_unreleased_body("# Changelog\n\nnothing here\n", "generated")


# --- changelog: extract_release_notes ---------------------------------------


def test_extract_release_notes_keeps_only_headers_with_bullets() -> None:
    text = (
        "## [Unreleased]\n\n"
        "### Added\n- a new thing\n\n"
        "### Changed\n-\n\n"
        "### Fixed\n- a bugfix\n- another bugfix\n\n"
        "## [1.0.0] - 2026-01-01\n"
    )
    result = extract_release_notes(text)
    assert "### Added\n- a new thing" in result
    assert "### Fixed\n- a bugfix\n- another bugfix" in result
    # The empty "### Changed" section is dropped entirely.
    assert "### Changed" not in result


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        (
            "### Fixed\n- a wrapped fix\n  with its continuation\n",
            "### Fixed\n- a wrapped fix\n  with its continuation\n",
        ),
        (
            "### Fixed\n- first fix\n  first continuation\n- second fix\n  second continuation\n",
            "### Fixed\n- first fix\n  first continuation\n- second fix\n  second continuation\n",
        ),
        (
            "### Added\n- an addition\n  addition continuation\n\n"
            "### Changed\n  prose outside a bullet\n\n"
            "### Fixed\n- a fix\n  fix continuation\n",
            "### Added\n- an addition\n  addition continuation\n\n"
            "### Fixed\n- a fix\n  fix continuation\n",
        ),
    ],
)
def test_extract_release_notes_preserves_bullet_continuations(section: str, expected: str) -> None:
    text = f"## [Unreleased]\n\n{section}\n## [1.0.0] - 2026-01-01\n"
    assert extract_release_notes(text) == expected


def test_extract_release_notes_preserves_current_wrapped_fixed_entries() -> None:
    fixed_bullets = (
        "- Reject HTTP responses whose status token is not exactly three ASCII digits\n"
        "  in `wait_for_http`, even when a custom `expected_status` would accept a\n"
        "  loosely parsed short or long integer.\n"
        "- Update the bundled ProcessKit-rs core to 3.3.4 so an unconfirmed timeout,\n"
        "  cancellation, or pipeline teardown surfaces as `ProcessError` instead of a\n"
        "  misleading terminal outcome; Windows ConPTY rejects unrepresentable sizes\n"
        "  and rolls back failed startup, and Windows process-group enumeration errors\n"
        "  no longer look like clean completion. This retains the restricted/legacy\n"
        "  Linux cgroup thaw fix included since core 3.3.1.\n"
    )
    text = (
        "## [Unreleased]\n\n### Added\n-\n\n### Changed\n-\n\n"
        f"### Fixed\n\n{fixed_bullets}\n## [1.0.0] - 2026-01-01\n"
    )

    assert extract_release_notes(text) == f"### Fixed\n{fixed_bullets}"


def test_extract_release_notes_stops_continuation_at_non_continuation_content() -> None:
    text = (
        "## [Unreleased]\n\n"
        "### Fixed\n"
        "- a real fix\n"
        "  its continuation\n"
        "prose that ends the bullet block\n"
        "  indented prose outside the bullet\n\n"
        "## [1.0.0] - 2026-01-01\n"
    )

    assert extract_release_notes(text) == "### Fixed\n- a real fix\n  its continuation\n"


def test_extract_release_notes_raises_when_empty() -> None:
    text = "## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n"
    with pytest.raises(ValueError, match="empty"):
        extract_release_notes(text)


def test_extract_release_notes_raises_when_no_unreleased_header() -> None:
    with pytest.raises(ValueError, match="empty"):
        extract_release_notes("# Changelog\n\n## [1.0.0] - 2026-01-01\n")


# --- changelog: promote_unreleased -------------------------------------------


def test_promote_unreleased_opens_a_fresh_section_and_dates_the_release() -> None:
    text = (
        "## [Unreleased]\n\n"
        "### Added\n- a new thing\n\n"
        "## [0.9.0] - 2025-01-01\n\n"
        "[Unreleased]: https://example.com/compare/v0.9.0...HEAD\n"
        "[0.9.0]: https://example.com/compare/v0.8.0...v0.9.0\n"
    )
    result = promote_unreleased(
        text,
        version="1.0.0",
        tag="v1.0.0",
        prev_tag="v0.9.0",
        first_release=False,
        repo="https://example.com",
        date="2026-07-05",
    )
    assert "## [1.0.0] - 2026-07-05" in result
    assert "### Added\n- a new thing" in result  # the old body is preserved, now dated
    assert "[Unreleased]: https://example.com/compare/v1.0.0...HEAD" in result
    assert "[1.0.0]: https://example.com/compare/v0.9.0...v1.0.0" in result
    # A fresh, empty [Unreleased] section was opened above the dated release.
    assert result.index("## [Unreleased]") < result.index("## [1.0.0]")


def test_promote_unreleased_first_release_links_to_the_tag_not_a_compare() -> None:
    text = "## [Unreleased]\n\n### Added\n- init\n\n[Unreleased]: https://example.com/compare/v0.0.0...HEAD\n"
    result = promote_unreleased(
        text,
        version="1.0.0",
        tag="v1.0.0",
        prev_tag="v0.0.0",
        first_release=True,
        repo="https://example.com",
        date="2026-07-05",
    )
    assert "[1.0.0]: https://example.com/releases/tag/v1.0.0" in result
    assert "compare/v0.0.0...v1.0.0" not in result


def test_promote_unreleased_raises_without_unreleased_header() -> None:
    with pytest.raises(ValueError, match="Unreleased"):
        promote_unreleased(
            "# Changelog\n\nnothing here\n",
            version="1.0.0",
            tag="v1.0.0",
            prev_tag="v0.0.0",
            first_release=True,
            repo="https://example.com",
        )


def test_promote_unreleased_raises_on_a_duplicated_unreleased_header() -> None:
    # A regression pin: an uncapped `count` in the underlying `re.subn` matters
    # here — with `count=1` the first duplicate would be silently patched and
    # `n` would read 1, masking the corruption instead of raising.
    text = (
        "## [Unreleased]\n\n### Added\n- one\n\n"
        "## [Unreleased]\n\n### Added\n- two\n\n"
        "[Unreleased]: https://example.com/compare/v0.0.0...HEAD\n"
    )
    with pytest.raises(ValueError, match="Unreleased"):
        promote_unreleased(
            text,
            version="1.0.0",
            tag="v1.0.0",
            prev_tag="v0.0.0",
            first_release=True,
            repo="https://example.com",
        )


def test_promote_unreleased_raises_without_reference_link_line() -> None:
    text = "## [Unreleased]\n\n### Added\n- init\n"
    with pytest.raises(ValueError, match="reference link"):
        promote_unreleased(
            text,
            version="1.0.0",
            tag="v1.0.0",
            prev_tag="v0.0.0",
            first_release=True,
            repo="https://example.com",
        )


# --- cargo_lock: bump_local_crate_version -----------------------------------


def test_bump_local_crate_version_patches_only_the_local_entry() -> None:
    lock = (
        '[[package]]\nname = "processkit-py"\nversion = "1.0.0"\ndependencies = ["processkit"]\n'
        "\n"
        '[[package]]\nname = "processkit"\nversion = "1.2.0"\nsource = "registry+https://x"\n'
    )
    result = bump_local_crate_version(lock, "1.1.0")
    assert 'name = "processkit-py"\nversion = "1.1.0"' in result
    # The registry dependency (same name minus "-py") is untouched.
    assert 'name = "processkit"\nversion = "1.2.0"' in result


def test_bump_local_crate_version_raises_when_entry_missing() -> None:
    lock = '[[package]]\nname = "processkit"\nversion = "1.2.0"\nsource = "registry+https://x"\n'
    with pytest.raises(ValueError, match="expected one"):
        bump_local_crate_version(lock, "1.1.0")


def test_bump_local_crate_version_raises_when_multiple_entries() -> None:
    lock = (
        '[[package]]\nname = "processkit-py"\nversion = "1.0.0"\n'
        "\n"
        '[[package]]\nname = "processkit-py"\nversion = "1.0.0"\n'
    )
    with pytest.raises(ValueError, match="expected one"):
        bump_local_crate_version(lock, "1.1.0")


# --- CLI wrappers: explicit UTF-8 read + LF-only write ----------------------
#
# These pin the regression the task fixes: reading a non-ASCII CHANGELOG.md
# must not raise UnicodeDecodeError (default locale codec on Windows), and
# writing must never introduce CRLF (Windows' `write_text()` default), which
# would show as a whole-file diff under the repo's `eol=lf` normalization.


def test_cmd_extract_notes_reads_non_ascii_utf8_and_writes_lf_only(
    tmp_path: pathlib.Path,
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(
        (
            "## [Unreleased]\n\n### Added\n- a bugfix for “curly quotes” — café\n\n"
            "## [1.0.0] - 2026-01-01\n"
        ).encode()
    )
    out = tmp_path / "release-notes.md"
    args = argparse.Namespace(changelog=str(changelog), out=str(out))

    _cmd_extract_notes(args)

    written = out.read_bytes()
    assert b"\r\n" not in written
    assert "café".encode() in written


def test_cmd_promote_reads_non_ascii_utf8_and_writes_lf_only(tmp_path: pathlib.Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(
        (
            "## [Unreleased]\n\n### Added\n- a bugfix — café\n\n"
            "[Unreleased]: https://example.com/compare/v0.9.0...HEAD\n"
            "[0.9.0]: https://example.com/compare/v0.8.0...v0.9.0\n"
        ).encode()
    )
    args = argparse.Namespace(
        changelog=str(changelog),
        version="1.0.0",
        tag="v1.0.0",
        prev_tag="v0.9.0",
        first_release="false",
        repo="https://example.com",
    )

    _cmd_promote(args)

    written = changelog.read_bytes()
    assert b"\r\n" not in written
    assert "café".encode() in written


@pytest.mark.skipif(
    GIT is None or GIT_CLIFF is None,
    reason="git and git-cliff are required",
)
def test_first_release_real_git_cliff_includes_release_worthy_root_commit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    root_sha = _commit(repo, "Fix initial release notes")
    _run_git(repo, "tag", "v0.0.0", root_sha)
    changelog = repo / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n")
    assert GIT_CLIFF is not None

    legacy = subprocess.run(
        [
            GIT_CLIFF,
            "--config",
            str(CLIFF_TOML),
            "--strip",
            "all",
            "v0.0.0..HEAD",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert legacy.stdout.strip() == ""

    monkeypatch.chdir(repo)
    _cmd_autofill(
        argparse.Namespace(
            changelog=str(changelog),
            cliff_config=str(CLIFF_TOML),
            prev_tag="v0.0.0",
            first_release="true",
        )
    )

    written = changelog.read_text(encoding="utf-8")
    assert written.count("### Fixed") == 1
    assert written.count("Fix initial release notes") == 1


def test_release_workflow_passes_first_release_mode_without_synthetic_tag() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert '--first-release "${{ steps.version.outputs.first_release }}"' in workflow
    assert "Ensure previous tag exists (local only)" not in workflow
    assert 'git tag "$PREV_TAG"' not in workflow


@pytest.mark.skipif(GIT is None, reason="git is not installed")
def test_subsequent_release_range_excludes_previously_tagged_root(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    root_sha = _commit(repo, "Fix already released behavior")
    _run_git(repo, "tag", "v1.0.0", root_sha)
    next_sha = _commit(repo, "Fix next release behavior")

    commit_range = git_cliff_range(prev_tag="v1.0.0", first_release=False)
    assert commit_range is not None
    commits = _run_git(repo, "rev-list", commit_range).stdout.splitlines()
    subjects = _run_git(repo, "log", "--format=%s", commit_range).stdout.splitlines()

    assert commits == [next_sha]
    assert subjects == ["Fix next release behavior"]


def test_cmd_autofill_first_release_uses_full_history_once(
    tmp_path: pathlib.Path,
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliff.toml",
        prev_tag="v0.0.0",
        first_release="true",
    )
    completed = subprocess.CompletedProcess(
        args=["git-cliff"],
        returncode=0,
        stdout="### Fixed\n- Include the root commit in first-release notes\n",
    )

    with mock.patch("scripts.release.changelog.subprocess.run", return_value=completed) as run:
        _cmd_autofill(args)

    command = run.call_args.args[0]
    assert command == ["git-cliff", "--config", "cliff.toml", "--strip", "all"]
    written = changelog.read_text(encoding="utf-8")
    assert written.count("### Fixed") == 1
    assert written.count("Include the root commit in first-release notes") == 1


def test_cmd_autofill_empty_first_release_reports_full_history(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliff.toml",
        prev_tag="v0.0.0",
        first_release="true",
    )
    completed = subprocess.CompletedProcess(args=["git-cliff"], returncode=0, stdout="")

    with (
        mock.patch("scripts.release.changelog.subprocess.run", return_value=completed),
        pytest.raises(SystemExit),
    ):
        _cmd_autofill(args)

    captured = capsys.readouterr()
    assert "No release-worthy commits found in repository history" in captured.err
    assert "between v0.0.0 and HEAD" not in captured.err


def test_cmd_autofill_dedupes_git_cliffs_generated_body(tmp_path: pathlib.Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliff.toml",
        prev_tag="v0.9.0",
        first_release="false",
    )
    generated_stdout = (
        "### Changed\n"
        "- Bump processkit dependency to 2.2.4\n"
        "- Bump processkit dependency to 2.2.4\n"
        "\n"
        "### Fixed\n"
        "-\n"
    )
    completed = subprocess.CompletedProcess(
        args=["git-cliff"], returncode=0, stdout=generated_stdout
    )

    with mock.patch("scripts.release.changelog.subprocess.run", return_value=completed):
        _cmd_autofill(args)

    written = changelog.read_text(encoding="utf-8")
    assert written.count("Bump processkit dependency to 2.2.4") == 1
    assert "### Fixed" not in written


def test_cmd_autofill_surfaces_git_cliff_stderr_on_failure(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliffconfig.toml",
        prev_tag="v0.9.0",
        first_release="false",
    )
    err = subprocess.CalledProcessError(
        returncode=2,
        cmd=["git-cliff"],
        output="",
        stderr="error: invalid config file at cliffconfig.toml",
    )

    with (
        mock.patch("scripts.release.changelog.subprocess.run", side_effect=err),
        pytest.raises(SystemExit),
    ):
        _cmd_autofill(args)

    captured = capsys.readouterr()
    assert "invalid config file at cliffconfig.toml" in captured.err
    assert "exit code 2" in captured.err


def test_cmd_autofill_reports_empty_stderr_explicitly(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliffconfig.toml",
        prev_tag="v0.9.0",
        first_release="false",
    )
    err = subprocess.CalledProcessError(returncode=1, cmd=["git-cliff"], output="", stderr="")

    with (
        mock.patch("scripts.release.changelog.subprocess.run", side_effect=err),
        pytest.raises(SystemExit),
    ):
        _cmd_autofill(args)

    captured = capsys.readouterr()
    assert "stderr is empty" in captured.err


def test_cargo_lock_main_reads_utf8_and_writes_lf_only(tmp_path: pathlib.Path) -> None:
    lock = tmp_path / "Cargo.lock"
    lock.write_bytes(
        (
            '[[package]]\nname = "processkit-py"\nversion = "1.0.0"\n'
            "# a comment with a non-ASCII character: café\n"
        ).encode()
    )

    cargo_lock_main(["--new-version", "1.1.0", "--lock-path", str(lock)])

    written = lock.read_bytes()
    assert b"\r\n" not in written
    assert b'version = "1.1.0"' in written
    assert "café".encode() in written
