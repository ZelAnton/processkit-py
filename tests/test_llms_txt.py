"""Drift guard for the generated LLM-facing docs (`docs/llms.txt`, `docs/llms-full.txt`).

Both files are produced by `scripts/gen_llms_txt.py` from `docs/SUMMARY.md`, the
chapter bodies, and `book.toml`, and are committed to the repo (like
`docs/api-reference.md`). Nothing regenerates them automatically, so these tests pin
the contract: the committed copies must match a fresh render, the annotated index
must list every real chapter (and none of the fileless DRAFT switcher links), and the
full text must concatenate every guide body except the Overview frontispiece.
"""

from __future__ import annotations

import pathlib

from scripts import gen_llms_txt

_DOCS = pathlib.Path(gen_llms_txt.__file__).resolve().parents[1] / "docs"
_LLMS = _DOCS / "llms.txt"
_LLMS_FULL = _DOCS / "llms-full.txt"

# The three implementation-switcher DRAFT entries in SUMMARY.md — bare `[Title]()`
# links with no chapter file — which both artifacts exclude.
_DRAFT_TITLES = ("Rust version", "Python wrapper", ".NET version")


def test_llms_files_are_up_to_date() -> None:
    # The committed files must match a byte-for-byte regeneration — otherwise a
    # guide's opening (or the chapter set) changed without rerunning the generator.
    assert gen_llms_txt.check(), (
        "docs/llms.txt / docs/llms-full.txt are stale. "
        "Regenerate them: python scripts/gen_llms_txt.py"
    )


def test_index_lists_every_real_chapter_and_no_drafts() -> None:
    index = _LLMS.read_text(encoding="utf-8")
    chapters = gen_llms_txt.parse_summary()

    # One annotated bullet per real chapter, each with a non-empty annotation.
    bullets = [line for line in index.splitlines() if line.startswith("- [")]
    assert len(bullets) == len(chapters)
    for chapter in chapters:
        assert f"[{chapter.title}](" in index, f"{chapter.title!r} missing from docs/llms.txt"
    for bullet in bullets:
        _, _, annotation = bullet.partition("): ")
        assert annotation.strip(), f"empty annotation in docs/llms.txt: {bullet!r}"

    # The DRAFT switchers have no file, so they are never chapters, hence never listed.
    real_titles = {chapter.title for chapter in chapters}
    for draft in _DRAFT_TITLES:
        assert draft not in real_titles
        assert f"[{draft}]" not in index


def test_full_text_excludes_overview_but_covers_the_guides() -> None:
    full = _LLMS_FULL.read_text(encoding="utf-8")

    # The Overview landing-page frontispiece body is left out of the full text.
    overview = (_DOCS / "README.md").read_text(encoding="utf-8").strip("\n")
    assert overview not in full

    # Every other chapter body is concatenated verbatim, in SUMMARY order.
    for chapter in gen_llms_txt.parse_summary():
        if chapter.path == "README.md":
            continue
        body = (_DOCS / chapter.path).read_text(encoding="utf-8").strip("\n")
        assert body in full, f"{chapter.path} body missing from docs/llms-full.txt"
