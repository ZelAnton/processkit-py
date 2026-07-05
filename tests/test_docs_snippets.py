"""Drift guard for the python code samples in `README.md` and `docs/*.md`.

The guides are a large, showcase part of the project (the README plus ten
guides in `docs/`, with a snippet for nearly every capability), but the only
existing gate on them is `mkdocs build --strict` (broken links/anchors) — the
*code* in a sample is never executed or even parsed, so a renamed method or a
changed signature leaves a stale example shipping silently (this has already
happened and was only ever caught by manual review).

Two checks run over every fenced ` ```python ` block (`tests/_docs_snippets.py`
does the extraction):

1. `compile()` — every block must at least be syntactically valid python
   (`test_snippet_compiles`). This is the hard gate.
2. mypy, best-effort — every block is wrapped and type-checked against the
   real `processkit` stub (`test_snippets_typecheck`), catching the drift
   classes `compile()` cannot see (a renamed keyword argument, a changed
   return/attribute type, a removed method). Unresolved bare names (a snippet
   invents `health_check()` or `my-server` to stand in for the reader's own
   code) are not an error here — only genuine mismatches against the real,
   imported `processkit` surface are.

A block that is not a runnable program on its own — pseudo-code, a fragment
built around a literal `...` elision — is excluded from both by a
`<!-- docs-snippet: incomplete -->` marker immediately above its fence (see
`tests/_docs_snippets.py` for the exact syntax); no page currently needs it,
but the mechanism is exercised directly below
(`test_incomplete_marker_excludes_the_block`) so a future truly-fragmentary
example has somewhere to opt out without weakening the gate for everything
else.
"""

from __future__ import annotations

import ast
import pathlib
import re
import textwrap

import pytest
from mypy import api as mypy_api

from ._docs_snippets import (
    DOC_FILES,
    Snippet,
    all_snippets,
    build_typecheck_source,
    extract_snippets,
    wrapped_line_to_doc_line,
)

_SNIPPETS = all_snippets()
_CHECKABLE = [s for s in _SNIPPETS if not s.incomplete]

#: The dedicated, deliberately non-strict mypy config for the snippet pass —
#: separate from `[tool.mypy]` in pyproject.toml (which is `strict = true` for
#: `src`/`tests`/`scripts`): a doc snippet is a terse illustration, not
#: production code, so it is not held to "every function is annotated"
#: (`no-untyped-def`/`no-untyped-call`) or "every name resolves"
#: (`name-defined` — snippets routinely call an invented `health_check()`
#: standing in for the reader's own code). `mypy_path` still points at the
#: real `src/`, so the surface it checks against (`processkit`'s actual
#: `.pyi`) is the one this repo ships, not whatever happens to be installed.
_MYPY_CONFIG_TEMPLATE = """\
[mypy]
python_version = 3.12
ignore_missing_imports = True
mypy_path = {src}
explicit_package_bases = True
namespace_packages = True
disable_error_code = name-defined, var-annotated
"""

_MYPY_OUTPUT_LOCATION_RE = re.compile(r"^(?P<file>.+\.py):(?P<line>\d+):(?P<rest>.*)$")


def test_doc_files_are_populated() -> None:
    # Guard against a false green if the file list breaks (e.g. docs/ moves).
    assert DOC_FILES, "no documentation files configured"
    for path in DOC_FILES:
        assert path.is_file(), f"configured documentation file is missing: {path}"


def test_docs_snippets_found() -> None:
    # Guard against a false green from a broken fence parser (zero blocks found
    # across the whole doc set would otherwise report "0 passed", silently).
    assert _SNIPPETS, "no python code blocks found across README.md / docs/*.md"


@pytest.mark.parametrize("snippet", _CHECKABLE, ids=lambda s: s.label)
def test_snippet_compiles(snippet: Snippet) -> None:
    try:
        compile(snippet.code, snippet.label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    except SyntaxError as exc:
        pytest.fail(
            f"{snippet.label}: not valid python ({exc.msg}, line {exc.lineno} of the block).\n"
            "If this block is deliberately incomplete/pseudo-code, mark it with "
            "`<!-- docs-snippet: incomplete -->` on the line directly above the fence "
            "(see tests/_docs_snippets.py).\n--- block ---\n" + snippet.code
        )


def _translate_mypy_location(line: str, files: dict[str, Snippet]) -> str:
    """Rewrite a `<generated-file>:<line>: ...` mypy output line to point at
    the original `docs/foo.md:123` position, so a failure is actionable
    without knowing about the generated temp files at all."""
    match = _MYPY_OUTPUT_LOCATION_RE.match(line)
    if match is None:
        return line
    snippet = files.get(pathlib.Path(match.group("file")).name)
    if snippet is None:
        return line
    doc_line = wrapped_line_to_doc_line(snippet, int(match.group("line")))
    return f"{snippet.label} (doc line {doc_line}):{match.group('rest')}"


def run_mypy_over_snippets(
    snippets: list[Snippet], tmp_path: pathlib.Path
) -> tuple[int, list[str]]:
    """Type-check `snippets` (already syntactically valid) as a single mypy
    invocation over generated files under `tmp_path`.

    Returns mypy's exit status and its output with generated-file positions
    translated back to `docs/foo.md:123` doc positions.
    """
    files: dict[str, Snippet] = {}
    for index, snippet in enumerate(snippets):
        name = f"snippet_{index:04d}.py"
        (tmp_path / name).write_text(build_typecheck_source(snippet.code), encoding="utf-8")
        files[name] = snippet

    src_dir = pathlib.Path(__file__).resolve().parent.parent / "src"
    config_path = tmp_path / "mypy.ini"
    config_path.write_text(_MYPY_CONFIG_TEMPLATE.format(src=src_dir), encoding="utf-8")

    stdout, stderr, exit_status = mypy_api.run(["--config-file", str(config_path), str(tmp_path)])
    output = [
        _translate_mypy_location(line, files)
        for line in (*stdout.splitlines(), *stderr.splitlines())
        if line.strip()
    ]
    return exit_status, output


def test_snippets_typecheck(tmp_path: pathlib.Path) -> None:
    # Only snippets that are already known-valid python — a syntax error is
    # `test_snippet_compiles`'s job to report, not this one's.
    valid: list[Snippet] = []
    for snippet in _CHECKABLE:
        try:
            compile(snippet.code, snippet.label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        except SyntaxError:
            continue
        valid.append(snippet)
    if not valid:
        pytest.skip("no syntactically-valid snippets to type-check")

    exit_status, output = run_mypy_over_snippets(valid, tmp_path)
    assert exit_status == 0, (
        "mypy found issues in documentation snippets (a genuinely non-standalone "
        "example — e.g. one that only makes sense continuing an earlier snippet's "
        "setup — can be marked `<!-- docs-snippet: incomplete -->` above its fence):\n"
        + "\n".join(output)
    )


def test_incomplete_marker_excludes_the_block(tmp_path: pathlib.Path) -> None:
    # A block marked `incomplete` is parsed (so its presence is still visible)
    # but flagged, so callers filter it out of both checks above — proven here
    # with a block whose body is not even valid python, showing the marker is
    # load-bearing (an *unmarked* copy of the same block is caught below).
    doc = tmp_path / "sample.md"
    doc.write_text(
        textwrap.dedent(
            """\
            # Sample

            <!-- docs-snippet: incomplete -->
            ```python
            def handler(request):
                ... # elided: the reader fills this in
                return
            def broken(:
            ```

            ```python
            from processkit import Command

            Command("git", ["status"]).run()
            ```
            """
        ),
        encoding="utf-8",
    )
    snippets = extract_snippets(doc)
    assert [s.incomplete for s in snippets] == [True, False]
    with pytest.raises(SyntaxError):
        compile(snippets[0].code, "sample.md", "exec")
    compile(snippets[1].code, "sample.md", "exec")  # the unmarked block is fine


def test_compile_check_catches_syntax_drift(tmp_path: pathlib.Path) -> None:
    # Simulates the drift `test_snippet_compiles` exists to catch — a stale
    # example whose code no longer parses — without mutating the real docs.
    doc = tmp_path / "sample.md"
    doc.write_text(
        textwrap.dedent(
            """\
            # Sample

            ```python
            result = Command("git", ["status"]).run(
            ```
            """
        ),
        encoding="utf-8",
    )
    (snippet,) = extract_snippets(doc)
    assert not snippet.incomplete
    with pytest.raises(SyntaxError):
        compile(snippet.code, snippet.label, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def test_typecheck_catches_api_drift(tmp_path: pathlib.Path) -> None:
    # Simulates the drift `test_snippets_typecheck` exists to catch — a
    # renamed/removed method and a parameter whose type changed — against the
    # real, installed `processkit` stub.
    drifted = Snippet(
        source=tmp_path / "sample.md",
        lineno=1,
        code=(
            "from processkit import Command, ProcessGroup\n"
            'Command("git").this_method_does_not_exist()\n'
            'ProcessGroup(max_memory="not-an-int")\n'
        ),
        incomplete=False,
    )
    exit_status, output = run_mypy_over_snippets([drifted], tmp_path)
    assert exit_status != 0, "expected the injected API drift to fail mypy"
    joined = "\n".join(output)
    assert "this_method_does_not_exist" in joined
    assert "max_memory" in joined
