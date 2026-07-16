"""Unit tests for `scripts/release/*.py` — the pure functions extracted from
`release.yml`'s inline heredocs (CHANGELOG.md manipulation, Cargo.lock version
sync). These never touch git, git-cliff, or the network; the CLI wrappers
that do are exercised only by an actual release run.
"""

from __future__ import annotations

import argparse
import pathlib
import re
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
    insert_unreleased_body,
    promote_unreleased,
    unreleased_has_bullets,
)

CLIFF_TOML = pathlib.Path(__file__).resolve().parents[1] / "cliff.toml"

_PARSER_ENTRY_RE = re.compile(
    r'\{\s*message\s*=\s*"((?:[^"\\]|\\.)*)"\s*,\s*(skip\s*=\s*true|group\s*=\s*"[^"]*")\s*\}'
)


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


def test_cmd_autofill_dedupes_git_cliffs_generated_body(tmp_path: pathlib.Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [Unreleased]\n\n### Added\n-\n\n## [1.0.0] - 2026-01-01\n")
    args = argparse.Namespace(
        changelog=str(changelog),
        cliff_config="cliff.toml",
        prev_tag="v0.9.0",
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
