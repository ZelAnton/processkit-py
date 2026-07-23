"""Tests for the rendered mdBook local-link guard."""

from pathlib import Path

from scripts.check_docs_links import check_book


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_check_book_accepts_existing_pages_and_fragments(tmp_path: Path) -> None:
    _write(tmp_path / "index.html", '<a href="guide.html#usage">guide</a>')
    _write(tmp_path / "guide.html", '<h2 id="usage">Usage</h2><a href="./">home</a>')

    assert check_book(tmp_path) == []


def test_check_book_reports_missing_targets_and_fragments(tmp_path: Path) -> None:
    _write(
        tmp_path / "index.html",
        '<a href="missing.html">missing</a><a href="guide.html#wrong">wrong</a>',
    )
    _write(tmp_path / "guide.html", '<h2 id="right">Right</h2>')

    assert check_book(tmp_path) == [
        "index.html -> missing.html: missing target",
        "index.html -> guide.html#wrong: missing fragment",
    ]
