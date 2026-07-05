"""Shared parsing for the documentation drift guard (`test_docs_snippets.py`).

Extracts every fenced ` ```python ` / ` ```py ` code block from `README.md` and
each `docs/*.md` guide, in document order. A block that is not a runnable
program on its own — pseudo-code, a fragment built around a literal `...`
elision, a made-up program name standing in for "your own server" — can opt
out of both the `compile()` and the mypy check by placing a marker comment on
its own line immediately above the opening fence:

    <!-- docs-snippet: incomplete -->
    ```python
    ...
    ```

The marker is an HTML comment, so it renders invisibly on the built site
(mkdocs strips it like any HTML comment) rather than becoming part of the
visible sample.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

#: Repo root: this file is `<root>/tests/_docs_snippets.py`.
ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every documentation page scanned for snippets: the top-level README plus
#: every guide under `docs/` — which itself includes `docs/README.md`, the
#: site home page, a different document from the repo-root `README.md`.
DOC_FILES: tuple[pathlib.Path, ...] = (
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
)

# A fenced block may be indented (e.g. nested under a numbered list item, as in
# docs/supervision.md) — the opening fence's own indentation is captured and
# stripped from every line of the body before it is treated as source.
_FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ \t]*)```(?P<lang>\S*)[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*```[ \t]*$")
_INCOMPLETE_MARKER_RE = re.compile(r"^[ \t]*<!--\s*docs-snippet:\s*incomplete\s*-->[ \t]*$")
_PYTHON_LANGS = frozenset({"python", "py"})

#: The synthetic wrapper this module writes around each snippet for the mypy
#: pass (`build_typecheck_source`) — kept as a named constant so the doc-line
#: mapping back from a generated file's line number to the original block's
#: line number (`wrapped_line_to_doc_line`) stays in lockstep with it.
WRAPPER_HEADER: tuple[str, ...] = (
    "from __future__ import annotations",
    "",
    "from processkit import *  # noqa: F401,F403",
    "from processkit.testing import *  # noqa: F401,F403",
    "",
    "",
    "async def _snippet() -> None:",
)


@dataclasses.dataclass(frozen=True)
class Snippet:
    """One fenced python code block extracted from a documentation page."""

    source: pathlib.Path
    #: 1-based line number of the opening fence in `source`.
    lineno: int
    #: The dedented block body, verbatim.
    code: str
    #: Whether the block is marked `<!-- docs-snippet: incomplete -->` and so
    #: is exempt from both the `compile()` and the mypy check.
    incomplete: bool

    @property
    def relative_source(self) -> str:
        # Real doc snippets always live under `ROOT`; a synthetic `Snippet`
        # built in a test fixture (e.g. from a `tmp_path` markdown file) does
        # not, so fall back to the raw path rather than raising.
        try:
            relative = self.source.relative_to(ROOT)
        except ValueError:
            return str(self.source)
        return str(relative).replace("\\", "/")

    @property
    def label(self) -> str:
        """`"docs/foo.md:123"` — how a failure identifies the offending block."""
        return f"{self.relative_source}:{self.lineno}"


def _dedent(body: list[str], indent: str) -> str:
    if not indent:
        return "\n".join(body)
    return "\n".join(line[len(indent) :] if line.startswith(indent) else line for line in body)


def extract_snippets(path: pathlib.Path) -> list[Snippet]:
    """Every fenced ` ```python `/` ```py ` block in `path`, in document order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    snippets: list[Snippet] = []
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN_RE.match(lines[i])
        if match is None or match.group("lang").lower() not in _PYTHON_LANGS:
            i += 1
            continue
        start = i
        indent = match.group("indent")
        body: list[str] = []
        i += 1
        while i < len(lines) and not _FENCE_CLOSE_RE.match(lines[i]):
            body.append(lines[i])
            i += 1
        # `i` now indexes the closing fence (or the end of file, for an
        # unterminated block — the compile check below will surface that
        # loudly rather than silently mis-parsing the rest of the page).
        i += 1
        preceding = lines[start - 1] if start > 0 else ""
        incomplete = _INCOMPLETE_MARKER_RE.match(preceding) is not None
        snippets.append(
            Snippet(
                source=path,
                lineno=start + 1,
                code=_dedent(body, indent),
                incomplete=incomplete,
            )
        )
    return snippets


def all_snippets() -> list[Snippet]:
    """Every python snippet across `DOC_FILES`, in file then document order."""
    result: list[Snippet] = []
    for path in DOC_FILES:
        result.extend(extract_snippets(path))
    return result


def build_typecheck_source(code: str) -> str:
    """Wrap a snippet body for the mypy pass.

    Every snippet is wrapped in an `async def` (so a snippet that itself uses a
    bare top-level `await` — valid in the doc's narrative context, e.g. inside
    an async REPL example — type-checks like any other), and each of the two
    imports is a wildcard import of the *real* public surface (`processkit` /
    `processkit.testing`), so a later snippet on the same guide page that
    reuses a name an earlier snippet imported (a common pattern: a page imports
    `Command` once near the top and reuses it, unqualified, in every snippet
    below) still resolves to its real type rather than reporting a spurious
    "not defined".
    """
    body_lines = code.splitlines() or [""]
    indented = ["    " + line if line.strip() else "" for line in body_lines]
    if not any(line.strip() for line in indented):
        indented = ["    pass"]
    return "\n".join([*WRAPPER_HEADER, *indented]) + "\n"


def wrapped_line_to_doc_line(snippet: Snippet, wrapped_lineno: int) -> int:
    """Map a line number in `build_typecheck_source(snippet.code)` back to the
    corresponding line in `snippet.source` (for translating mypy's output)."""
    return snippet.lineno + wrapped_lineno - len(WRAPPER_HEADER)
