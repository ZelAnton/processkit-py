"""Sync `Cargo.lock`'s local binding-crate entry to the release version — the
one piece of `release.yml`'s manifest bump that needs more than a `sed`
one-liner (`pyproject.toml`/`Cargo.toml` stay inline `sed`; a single-line
version-string substitution has no unit-testing value).
"""

from __future__ import annotations

import argparse
import pathlib
import re


def bump_local_crate_version(
    lock_text: str, new_version: str, crate_name: str = "processkit-py"
) -> str:
    """Bump ONLY the local (path) binding-crate's `version` field in a
    `Cargo.lock` text blob — matched by an exact `[[package]]\\nname =
    "<crate_name>"\\nversion = "..."` block. Raises `ValueError` unless
    exactly one such entry exists.

    The binding crate (`processkit-py`) is named distinctly from the
    `processkit` registry dependency it wraps, so an ordinary name match is
    unambiguous here — no negative-lookahead needed to tell a sourceless
    local entry apart from a same-named registry one (as an earlier version
    of this script needed, back when both crates shared the `processkit`
    name).
    """
    pattern = re.compile(
        rf'(\[\[package\]\]\nname = "{re.escape(crate_name)}"\nversion = ")[^"]+(")'
    )
    # No `count=1`: an uncapped `subn` counts EVERY match, so a duplicate (or
    # missing) entry is caught by the `n != 1` guard below instead of being
    # silently patched once and left unnoticed — `count=1` would cap the
    # substitution at one before `n` could ever exceed it, defeating the guard
    # for the "more than one entry" case (only "zero" would still be caught).
    text, n = pattern.subn(rf"\g<1>{new_version}\g<2>", lock_text)
    if n != 1:
        raise ValueError(f"expected one local {crate_name} Cargo.lock entry, patched {n}")
    return text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-version", required=True)
    parser.add_argument("--lock-path", default="Cargo.lock")
    parser.add_argument("--crate-name", default="processkit-py")
    args = parser.parse_args(argv)

    path = pathlib.Path(args.lock_path)
    path.write_text(bump_local_crate_version(path.read_text(), args.new_version, args.crate_name))


if __name__ == "__main__":
    main()
