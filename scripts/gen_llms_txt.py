"""Generate `docs/llms.txt` and `docs/llms-full.txt` — the site's LLM-facing index.

The project's audience is agent/LLM-framework developers, and much of the first
contact with a library today is mediated by an AI assistant. These two files
follow the [llmstxt.org](https://llmstxt.org/) convention so an assistant gets a
precise, current slice of the guides — the honest-results / containment /
sync-and-async-pairs semantics — instead of guessing from the README:

* `docs/llms.txt` — an **annotated index**. An H1 project name (from `book.toml`'s
  `[book].title`), a blockquote summary (from `[book].description`), then a `## Docs`
  list of every real documentation chapter in `docs/SUMMARY.md` order. Each entry is
  `- [Title](url): one-line annotation`, where `url` is the site-absolute URL
  (`[output.html].site-url`, `/processkit-py/`, joined with the chapter's rendered
  `.html` path) and the annotation is the guide's own first sentence — never invented.
* `docs/llms-full.txt` — the **full text**: the chapter bodies concatenated verbatim
  (no rendering, no minification) in the same `docs/SUMMARY.md` order, separated by a
  `---` rule.

Two membership rules, kept identical here and in `tests/test_llms_txt.py`:

* The four DRAFT prefix entries in `docs/SUMMARY.md` — the implementation switchers
  `[Rust version]()` / `[CLI Runner]()` / `[Python wrapper]()` /
  `[.NET version]()` — have no chapter file (empty `()` link targets) and are
  excluded from *both* files.
* `docs/README.md` (the "Overview" landing page) is *listed* in `llms.txt` — it is a
  real rendered chapter worth pointing an assistant at — but its *body* is excluded
  from `llms-full.txt`. That page is the site frontispiece (cover image, CI/PyPI
  badges, marketing prose, a 60-second tour); its substance is already carried by the
  `llms.txt` blockquote summary, so concatenating it into the full text would add
  chrome, not guide content. Every other chapter (including the generated
  `api-reference.md` and the contributor `internals.md`) is included in full.

Like `docs/api-reference.md` (see `scripts/gen_api_reference.py`), both files are
committed to the repo — not generated only at deploy — and a drift guard
(`tests/test_llms_txt.py`) fails if the committed copies go stale. `docs/` is the
mdBook `src` (`book.toml`), so both `.txt` files are copied verbatim into `book/` as
static assets on build, with no change to `.github/workflows/docs.yml`.

Usage:
    python scripts/gen_llms_txt.py            # (re)write docs/llms.txt + docs/llms-full.txt
    python scripts/gen_llms_txt.py --check     # exit 1 if either committed file is stale
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass

# Repo root: this file is `<root>/scripts/gen_llms_txt.py`.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DOCS = _ROOT / "docs"
_SUMMARY = _DOCS / "SUMMARY.md"
_BOOK_TOML = _ROOT / "book.toml"
_LLMS = _DOCS / "llms.txt"
_LLMS_FULL = _DOCS / "llms-full.txt"

# The landing page: listed in the index, but its body is left out of the full text.
_OVERVIEW = "README.md"

# An HTML comment block — stripped before any Markdown parsing so example link
# syntax quoted inside a comment (SUMMARY.md documents its own `[Title]()` drafts
# in a comment) can never be mistaken for a real chapter entry.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# A Markdown link `[text](target)`. A DRAFT switcher has an empty target `()`.
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")

# Inline image / link, used only to recognize (and skip) the non-prose "chrome"
# lines that lead a page: the `[docs index](./)` back-nav, the README cover
# image, and the README badge row.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_INLINE_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")

# A sentence boundary: `.`/`?`/`!` followed by whitespace and the start of a new
# sentence (a capital letter, or an opening quote/emphasis/link/code marker). Keeps
# the annotation to the guide's honest first sentence without splitting on an
# abbreviation's period (those are followed by a lowercase word) or a decimal point.
_SENTENCE_END = re.compile(r'(?<=[.?!])\s+(?=[A-Z"\'`*\[])')


@dataclass(frozen=True)
class Chapter:
    """One real `docs/SUMMARY.md` entry: its sidebar title and its `docs/`-relative
    Markdown path (a DRAFT switcher, with no file, never becomes a `Chapter`)."""

    title: str
    path: str


def parse_summary(summary: pathlib.Path = _SUMMARY) -> list[Chapter]:
    """Read ordered real chapters from `summary`.

    Every `[Title](file.md)` entry is returned in document order, with fileless
    DRAFT switcher links dropped. Comments are stripped first so documented link
    syntax inside a comment cannot be read as a chapter.
    """
    text = _COMMENT.sub("", summary.read_text(encoding="utf-8"))
    chapters: list[Chapter] = []
    for match in _LINK.finditer(text):
        title, target = match.group(1), match.group(2)
        if target:  # a DRAFT switcher's target is empty — skip it
            chapters.append(Chapter(title, target))
    return chapters


def _book_value(text: str, key: str) -> str:
    """The value of a top-level `key = "value"` line in `book.toml`."""
    match = re.search(rf'(?m)^{re.escape(key)}\s*=\s*"(.*)"\s*$', text)
    if match is None:
        raise ValueError(f'book.toml is missing a `{key} = "..."` entry')
    return match.group(1)


def _load_book_meta(book_toml: pathlib.Path = _BOOK_TOML) -> tuple[str, str, str]:
    """Load `(title, description, site_url)` from `book_toml`.

    `title` and `description` live under `[book]`; `site-url` lives under
    `[output.html]`. Each is a plain quoted scalar. A tiny reader on purpose: like
    `gen_api_reference.py` it adds no parse dependency, and it keeps the 3.10 floor
    a `tomllib` (3.11+) import would drop for this dev script.
    """
    text = book_toml.read_text(encoding="utf-8")
    return (
        _book_value(text, "title"),
        _book_value(text, "description"),
        _book_value(text, "site-url"),
    )


def _chapter_url(site_url: str, path: str) -> str:
    """The site-absolute URL of a chapter: `site_url` + its rendered `.html` file.
    `README.md` renders to the book's `index.html` root, every other `foo.md` to
    `foo.html`. `site_url` from `book.toml` carries its own trailing slash."""
    rendered = "index.html" if path == _OVERVIEW else path.removesuffix(".md") + ".html"
    return site_url + rendered


def _is_chrome(line: str) -> bool:
    """True for a leading non-prose line — an image, a badge, or a standalone link
    (the `[docs index](./)` back-nav) — i.e. nothing remains once images and links
    are removed."""
    return _INLINE_LINK.sub("", _IMAGE.sub("", line)).strip() == ""


def _first_paragraph(markdown: str) -> str:
    """The guide's first prose paragraph, its wrapped lines joined into one line.
    Skips the leading H1, any HTML comment, and the page's chrome (cover image,
    badge row, back-nav link)."""
    started = False
    in_comment = False
    paragraph: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        if not started:
            if line == "" or line.startswith("# ") or _is_chrome(line):
                continue
            started = True
            paragraph.append(line)
        elif line == "":
            break
        else:
            paragraph.append(line)
    return " ".join(paragraph)


def _annotation(chapter_path: pathlib.Path) -> str:
    """A guide's one-line annotation: the first sentence of its first prose
    paragraph, verbatim (Markdown inline formatting preserved), never invented."""
    return _SENTENCE_END.split(_first_paragraph(chapter_path.read_text(encoding="utf-8")), 1)[0]


def build_index(docs: pathlib.Path = _DOCS) -> str:
    """Render the docs tree's `llms.txt` annotated index (LF-terminated).

    Chapter order comes from `docs/SUMMARY.md`, and book metadata comes from
    `book.toml` beside the supplied docs directory.
    """
    summary = docs / "SUMMARY.md"
    book_toml = docs.parent / "book.toml"
    title, description, site_url = _load_book_meta(book_toml)
    lines = [f"# {title}", "", f"> {description}", "", "## Docs", ""]
    for chapter in parse_summary(summary):
        url = _chapter_url(site_url, chapter.path)
        annotation = _annotation(docs / chapter.path)
        lines.append(f"- [{chapter.title}]({url}): {annotation}")
    return "\n".join(lines) + "\n"


def build_full(docs: pathlib.Path = _DOCS) -> str:
    """Render the docs tree's `llms-full.txt` (LF-terminated).

    Chapter bodies are concatenated verbatim in the supplied docs directory's
    `SUMMARY.md` order and separated by `---`; the Overview is left out.
    """
    summary = docs / "SUMMARY.md"
    bodies: list[str] = []
    for chapter in parse_summary(summary):
        if chapter.path == _OVERVIEW:
            continue
        bodies.append((docs / chapter.path).read_text(encoding="utf-8").strip("\n"))
    return "\n\n---\n\n".join(bodies) + "\n"


def check(
    docs: pathlib.Path = _DOCS, index: pathlib.Path = _LLMS, full: pathlib.Path = _LLMS_FULL
) -> bool:
    """True if both files match a fresh render from `docs`, byte-for-byte (LF)."""
    return (
        index.is_file()
        and full.is_file()
        and index.read_bytes() == build_index(docs).encode("utf-8")
        and full.read_bytes() == build_full(docs).encode("utf-8")
    )


def write(
    docs: pathlib.Path = _DOCS, index: pathlib.Path = _LLMS, full: pathlib.Path = _LLMS_FULL
) -> None:
    """Render and write both files with LF line endings (never Windows CRLF, which
    would show as a whole-file diff under the repo's `eol=lf` normalization)."""
    index.write_bytes(build_index(docs).encode("utf-8"))
    full.write_bytes(build_full(docs).encode("utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if docs/llms.txt or docs/llms-full.txt is stale instead of rewriting them.",
    )
    args = parser.parse_args(argv)

    if args.check:
        if check():
            print("docs/llms.txt and docs/llms-full.txt are up to date.")
            return
        print(
            "docs/llms.txt / docs/llms-full.txt are out of date. "
            "Regenerate them with: python scripts/gen_llms_txt.py",
            file=sys.stderr,
        )
        raise SystemExit(1)

    write()
    print(f"Wrote {_LLMS.relative_to(_ROOT)} and {_LLMS_FULL.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
