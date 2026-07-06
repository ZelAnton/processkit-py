"""Generate `docs/api-reference.md` — the site's per-symbol API reference.

The page itself carries no hand-written signatures or prose docstrings: it is a
list of `mkdocstrings` autodoc directives (`::: processkit.<name>`), grouped into
sections. `mkdocstrings` renders each one from the type stub
(`src/processkit/_processkit.pyi`) and the pure-Python shim modules
(`_aio.py` / `_protocols.py` / `_types.py` / `testing.py`) via griffe's *static*
(AST) analysis — so the reference is the stub + docstrings, and cannot silently
drift from them. The Docs CI job builds with `--no-install-project` (the compiled
`_processkit` extension is never importable there); `allow_inspection: false` in
`mkdocs.yml` keeps griffe reading the `.pyi`, so this same file works in CI.

The *source of truth for the surface* is `processkit.__all__` (plus
`processkit.testing.__all__`), read here statically from the module sources. The
curated `SECTIONS` below decide the grouping and order; `build_page()` fails
loudly if that grouping ever diverges from the real `__all__` (a symbol added,
removed, or renamed but not reflected here), so the reference cannot silently
omit — or invent — a public symbol.

Usage:
    python scripts/gen_api_reference.py            # (re)write docs/api-reference.md
    python scripts/gen_api_reference.py --check     # exit 1 if the committed page is stale

`tests/test_api_reference.py` is the runtime drift guard: it runs the `--check`
logic and cross-checks the committed page against the *imported* package's
`__all__`, catching any skew between the static read here and the compiled module.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from dataclasses import dataclass

# Repo root: this file is `<root>/scripts/gen_api_reference.py`.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PKG = _ROOT / "src" / "processkit"
_PAGE = _ROOT / "docs" / "api-reference.md"

_TOP_MODULE = "processkit"
_TESTING_MODULE = "processkit.testing"


@dataclass(frozen=True)
class Section:
    """One `##` section of the reference: a title, an intro paragraph, the
    ordered public names it documents, and the module they are imported from
    (`processkit`, or `processkit.testing` for the test doubles)."""

    title: str
    intro: str
    members: tuple[str, ...]
    module: str = _TOP_MODULE


# The curated grouping/order. Every name in `processkit.__all__` must appear in a
# `processkit` section exactly once, and every name in `processkit.testing.__all__`
# in a `processkit.testing` section exactly once — `build_page()` enforces both.
SECTIONS: tuple[Section, ...] = (
    Section(
        "Building & running commands",
        "Construct a command and run it — capturing everything, or checking for "
        "success — synchronously or with the `a`-prefixed asyncio twins. "
        "`CliClient` binds a program to reusable defaults; `Pipeline` chains "
        "commands shell-free; `RunningProcess` is the live handle a started child "
        "hands back.",
        ("Command", "CliClient", "Pipeline", "RunningProcess"),
    ),
    Section(
        "Results & outcomes",
        "What a finished (or streamed) run reports back. A non-zero exit, a "
        "timeout, and a signal-kill are all *data* on these types — never raised "
        "by the capturing verbs.",
        ("ProcessResult", "BytesResult", "Outcome", "Finished", "RunProfile"),
    ),
    Section(
        "Streaming & interactive I/O",
        "The live handles a started `RunningProcess` hands out: async iterators "
        "over its output (line by line, or as interleaved stdout/stderr events) "
        "and a writable stdin.",
        ("StdoutLines", "OutputEvents", "OutputEvent", "ProcessStdin"),
    ),
    Section(
        "Process groups",
        "Kill-on-drop containment for a whole process tree — start children into "
        "it, signal or suspend the group, and reap the entire tree "
        "(grandchildren included) on exit.",
        ("ProcessGroup", "ProcessGroupStats"),
    ),
    Section(
        "Supervision",
        "Keep a command alive: restart it per a policy, with backoff and jitter, "
        "until a stop condition is met.",
        ("Supervisor", "SupervisionOutcome"),
    ),
    Section(
        "Cancellation",
        "A portable cancel switch, wired into a run via `Command.cancel_on()`, "
        "`Pipeline.cancel_on()`, or `CliClient`'s `default_cancel_on=`.",
        ("CancellationToken",),
    ),
    Section(
        "Batch execution",
        "Run many commands with bounded concurrency, returning each result — or a "
        "`ProcessError` for a spawn/I/O failure — in input order.",
        ("output_all", "output_all_bytes", "aoutput_all", "aoutput_all_bytes"),
    ),
    Section(
        "Readiness helpers",
        "Asyncio helpers that wait for a condition — a matching output line, an "
        "open TCP port, or any polled predicate — bounded by a deadline.",
        ("wait_until", "wait_for_line", "wait_for_port", "WaitTimeout"),
    ),
    Section(
        "Observability",
        "Opt-in bridging of the core's per-run `tracing` events to Python `logging`.",
        ("enable_logging",),
    ),
    Section(
        "The runner seam",
        "The dependency-injection seam: annotate your code against a protocol, "
        "inject the real `Runner` in production and a test double (see the "
        "Testing section) in tests. `ProcessRunner` is the capture/check verbs; "
        "`StreamingRunner` adds `start`/`astart`.",
        ("ProcessRunner", "StreamingRunner", "Runner"),
    ),
    Section(
        "Exceptions",
        "Every error raised by the package descends from `ProcessError`, so a "
        "single `except ProcessError` catches them all. `Timeout`, "
        "`ProcessNotFound`, and `PermissionDenied` also subclass a builtin "
        "(`TimeoutError` / `FileNotFoundError` / `PermissionError`, each itself "
        "an `OSError`), so the stdlib `except` clauses catch them too.",
        (
            "ProcessError",
            "NonZeroExit",
            "Timeout",
            "Signalled",
            "ProcessNotFound",
            "PermissionDenied",
            "ResourceLimit",
            "Unsupported",
            "OutputTooLarge",
            "Cancelled",
        ),
    ),
    Section(
        "Type aliases",
        "Exported so your own wrappers can annotate against the same types the API accepts.",
        (
            "Args",
            "LineTerminatorName",
            "Priority",
            "ReadableBuffer",
            "RetryIf",
            "SignalName",
            "StrPath",
        ),
    ),
    Section(
        "Testing",
        "Runner test doubles, in the `processkit.testing` submodule. Inject one "
        "in tests — all satisfy the `ProcessRunner` protocol — so the code under "
        "test spawns no real processes.",
        (
            "ScriptedRunner",
            "RecordReplayRunner",
            "RecordingRunner",
            "DryRunRunner",
            "Reply",
            "Invocation",
        ),
        module=_TESTING_MODULE,
    ),
)

_HEADER = """\
# API reference

The complete, per-symbol reference for the public `processkit` surface —
every class, function, protocol, type alias, and exception exported by the
package, plus the `processkit.testing` submodule.

It is generated from the type stub (`processkit/_processkit.pyi`) and the
docstrings, the same source your IDE and `mypy` read, so it cannot drift from
the real API. The narrative [guides](README.md) explain how the pieces compose;
this page is the exhaustive index. Both surfaces are covered together: the
synchronous verbs and their `a`-prefixed asyncio twins.
"""


def _read_all(module_file: pathlib.Path) -> list[str]:
    """Extract the `__all__` string list from a module source file, statically
    (via `ast`, no import). Raises `ValueError` if it is missing or not a plain
    list of string literals."""
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            raise ValueError(f"__all__ in {module_file} is not a list literal")
        names: list[str] = []
        for element in node.value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                raise ValueError(f"__all__ in {module_file} has a non-string entry")
            names.append(element.value)
        return names
    raise ValueError(f"no __all__ found in {module_file}")


def read_public_surface(pkg_dir: pathlib.Path = _PKG) -> tuple[set[str], set[str]]:
    """The public surface, read statically from the package sources:
    `(processkit.__all__, processkit.testing.__all__)` as sets."""
    top = set(_read_all(pkg_dir / "__init__.py"))
    testing = set(_read_all(pkg_dir / "testing.py"))
    return top, testing


def _validate_sections(top: set[str], testing: set[str]) -> None:
    """Fail loudly if `SECTIONS` no longer matches the real public surface — a
    symbol added to (or removed from) `__all__` without being placed here, a
    duplicate, or a name grouped under the wrong module."""
    grouped_top: list[str] = []
    grouped_testing: list[str] = []
    for section in SECTIONS:
        bucket = grouped_testing if section.module == _TESTING_MODULE else grouped_top
        bucket.extend(section.members)

    for label, grouped, expected in (
        ("processkit.__all__", grouped_top, top),
        ("processkit.testing.__all__", grouped_testing, testing),
    ):
        duplicates = sorted({n for n in grouped if grouped.count(n) > 1})
        if duplicates:
            raise ValueError(
                f"SECTIONS lists these {label} symbols more than once: {duplicates}. "
                "Each public symbol must appear in exactly one section."
            )
        grouped_set = set(grouped)
        missing = sorted(expected - grouped_set)
        extra = sorted(grouped_set - expected)
        if missing or extra:
            raise ValueError(
                f"SECTIONS is out of sync with {label}. "
                f"Missing (add to a section): {missing}. "
                f"Not in {label} (remove or fix): {extra}."
            )


def build_page(pkg_dir: pathlib.Path = _PKG) -> str:
    """Render the full `docs/api-reference.md` text (LF-terminated). Raises
    `ValueError` via `_validate_sections` if the curated grouping has drifted
    from the real public surface."""
    top, testing = read_public_surface(pkg_dir)
    _validate_sections(top, testing)

    parts: list[str] = [_HEADER]
    for section in SECTIONS:
        block = [f"## {section.title}", "", section.intro, ""]
        block.extend(f"::: {section.module}.{name}\n" for name in section.members)
        parts.append("\n".join(block))
    # One blank line between blocks; exactly one trailing newline.
    return "\n".join(parts).rstrip("\n") + "\n"


def check(pkg_dir: pathlib.Path = _PKG, page: pathlib.Path = _PAGE) -> bool:
    """True if the committed page matches a fresh render (byte-for-byte, LF)."""
    if not page.is_file():
        return False
    rendered = build_page(pkg_dir)
    return page.read_bytes() == rendered.encode("utf-8")


def write(pkg_dir: pathlib.Path = _PKG, page: pathlib.Path = _PAGE) -> None:
    """Render and write the page with LF line endings (never Windows CRLF, which
    would show as a whole-file diff under the repo's `eol=lf` normalization)."""
    page.write_bytes(build_page(pkg_dir).encode("utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if docs/api-reference.md is stale instead of writing it.",
    )
    args = parser.parse_args(argv)

    if args.check:
        if check():
            print("docs/api-reference.md is up to date.")
            return
        print(
            "docs/api-reference.md is out of date. "
            "Regenerate it with: python scripts/gen_api_reference.py",
            file=sys.stderr,
        )
        raise SystemExit(1)

    write()
    print(f"Wrote {_PAGE.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
