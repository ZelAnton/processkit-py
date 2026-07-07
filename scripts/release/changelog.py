"""CHANGELOG.md manipulation for the release workflow: the `[Unreleased]`
section auto-fill (from `git-cliff`), release-notes extraction, and the
promote-to-a-dated-version step.

Each transformation is a pure function (text in, text out), unit-tested in
`tests/test_release_scripts.py`; the CLI wrappers below (`main()` /
`if __name__ == "__main__"`) do the file I/O, subprocess call, and
`::error::`-annotated exit that only make sense when actually running in the
workflow.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", re.M | re.S)


def unreleased_has_bullets(text: str) -> bool:
    """Whether the `[Unreleased]` section already has at least one real
    bullet (`- text`) — if so, the auto-fill step is a no-op (manual entries
    always win over a generated fill)."""
    m = UNRELEASED_RE.search(text)
    if not m:
        return False
    return any(re.match(r"^-\s+\S", ln) for ln in m.group(1).splitlines())


def insert_unreleased_body(text: str, generated: str) -> str:
    """Replace the (empty) `[Unreleased]` section's body with `generated`
    (git-cliff's output). Raises `ValueError` if the header is missing."""
    m = UNRELEASED_RE.search(text)
    if not m:
        raise ValueError("Could not find '## [Unreleased]' header in CHANGELOG.md")
    return text[: m.start(1)] + generated + "\n\n" + text[m.end(1) :]


def extract_release_notes(text: str) -> str:
    """Assemble `release-notes.md`'s content from the `[Unreleased]`
    section: keep a `### Header` only if it has at least one real bullet (an
    untouched placeholder header is dropped). Raises `ValueError` if the
    result would be empty — nothing release-worthy to publish."""
    m = UNRELEASED_RE.search(text)
    body = (m.group(1) if m else "").strip()

    parts = re.split(r"(?m)(^### .+$)", body)
    out: list[str] = []
    for i in range(1, len(parts), 2):
        header = parts[i]
        section = parts[i + 1] if i + 1 < len(parts) else ""
        bullets = [ln for ln in section.splitlines() if re.match(r"^-\s+\S", ln)]
        if bullets:
            if out:
                out.append("")
            out.append(header)
            out.extend(bullets)

    result = "\n".join(out).strip()
    if not result:
        raise ValueError("[Unreleased] section in CHANGELOG.md is empty")
    return result + "\n"


def promote_unreleased(
    text: str,
    *,
    version: str,
    tag: str,
    prev_tag: str,
    first_release: bool,
    repo: str,
    date: str | None = None,
) -> str:
    """Promote `[Unreleased]` to a dated `## [version] - date` heading and
    open a fresh, empty `[Unreleased]` section above it; update the
    reference-link footer to match. Raises `ValueError` if either the
    heading or the reference-link line is missing."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_unreleased = (
        "## [Unreleased]\n\n"
        "### Added\n-\n\n"
        "### Changed\n-\n\n"
        "### Fixed\n-\n\n"
        f"## [{version}] - {date}"
    )
    # No `count=1` on either `subn` below: an uncapped count reports EVERY
    # match, so a duplicated heading/link line is caught by the `n != 1` guard
    # instead of being silently patched once and left unnoticed (see the same
    # reasoning in `cargo_lock.bump_local_crate_version`).
    text, n = re.subn(r"^## \[Unreleased\]$", new_unreleased, text, flags=re.M)
    if n != 1:
        raise ValueError("Could not find '## [Unreleased]' header in CHANGELOG.md")

    # On the first release the previous tag (v0.0.0) is synthetic — created
    # locally to bound git-cliff and never pushed — so a compare link against
    # it would 404. Point the first version at its own tag instead.
    if first_release:
        versioned_link = f"[{version}]: {repo}/releases/tag/{tag}"
    else:
        versioned_link = f"[{version}]: {repo}/compare/{prev_tag}...{tag}"
    link_replacement = f"[Unreleased]: {repo}/compare/{tag}...HEAD\n" + versioned_link
    text, n = re.subn(r"^\[Unreleased\]:.*$", link_replacement, text, flags=re.M)
    if n != 1:
        raise ValueError("Could not find '[Unreleased]: ...' reference link in CHANGELOG.md")

    return text


def _fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def _cmd_autofill(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.changelog)
    text = path.read_text(encoding="utf-8")
    if unreleased_has_bullets(text):
        print("[Unreleased] already has manual entries; skipping auto-fill.")
        return

    print(f"[Unreleased] is empty; generating from git log since {args.prev_tag}...")
    result = subprocess.run(
        ["git-cliff", "--config", args.cliff_config, "--strip", "all", f"{args.prev_tag}..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    generated = result.stdout.strip()
    if not generated:
        _fail(
            f"No release-worthy commits found between {args.prev_tag} and HEAD. "
            "Either add a manual entry to [Unreleased] in CHANGELOG.md, or commit "
            "changes with a recognised prefix (Add/Fix/Refactor/Update/Remove/...)."
        )

    try:
        new_text = insert_unreleased_body(text, generated)
    except ValueError as err:
        _fail(str(err))
        return  # unreachable (_fail raises); satisfies type-checkers
    path.write_bytes(new_text.encode("utf-8"))
    print("----- auto-generated [Unreleased] body -----")
    print(generated)
    print("--------------------------------------------")


def _cmd_extract_notes(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.changelog)
    try:
        result = extract_release_notes(path.read_text(encoding="utf-8"))
    except ValueError as err:
        _fail(f"{err}. Add release notes before releasing.")
        return  # unreachable (_fail raises); satisfies type-checkers
    pathlib.Path(args.out).write_bytes(result.encode("utf-8"))
    print(f"----- {args.out} -----")
    print(result, end="")
    print("----------------------------")


def _cmd_promote(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.changelog)
    try:
        new_text = promote_unreleased(
            path.read_text(encoding="utf-8"),
            version=args.version,
            tag=args.tag,
            prev_tag=args.prev_tag,
            first_release=args.first_release == "true",
            repo=args.repo,
        )
    except ValueError as err:
        _fail(str(err))
        return  # unreachable (_fail raises); satisfies type-checkers
    path.write_bytes(new_text.encode("utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changelog", default="CHANGELOG.md")
    subparsers = parser.add_subparsers(dest="command", required=True)

    autofill = subparsers.add_parser("autofill", help="Fill [Unreleased] from git-cliff if empty")
    autofill.add_argument("--prev-tag", required=True)
    autofill.add_argument("--cliff-config", default="cliff.toml")
    autofill.set_defaults(func=_cmd_autofill)

    extract_notes = subparsers.add_parser("extract-notes", help="Write release-notes.md")
    extract_notes.add_argument("--out", default="release-notes.md")
    extract_notes.set_defaults(func=_cmd_extract_notes)

    promote = subparsers.add_parser("promote", help="Promote [Unreleased] to a dated version")
    promote.add_argument("--version", required=True)
    promote.add_argument("--tag", required=True)
    promote.add_argument("--prev-tag", required=True)
    promote.add_argument("--first-release", required=True, choices=["true", "false"])
    promote.add_argument("--repo", required=True)
    promote.set_defaults(func=_cmd_promote)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
