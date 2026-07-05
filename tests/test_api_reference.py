"""Drift guard for the generated API-reference page (`docs/api-reference.md`).

The page is a list of `mkdocstrings` autodoc directives (`::: processkit.<name>`),
one per public symbol, produced by `scripts/gen_api_reference.py` from the
package's `__all__`. Three things must stay in lockstep, and nothing enforces it
automatically:

1. the committed page == a fresh regeneration (someone changed the surface but
   forgot to rerun the generator);
2. every runtime-public symbol (`processkit.__all__` plus
   `processkit.testing.__all__`) is documented (a new symbol slipped in
   unreferenced);
3. no directive points at a symbol that is no longer public (a stale entry).

The generator reads the surface *statically* (so it can run in the extension-free
Docs CI); these tests additionally cross-check against the *imported* package, so
a skew between the static read and the compiled module can't hide.
"""

from __future__ import annotations

import pathlib
import re

from scripts import gen_api_reference

import processkit
import processkit.testing

_PAGE = pathlib.Path(processkit.__file__).resolve().parents[2] / "docs" / "api-reference.md"

# `::: processkit.Command` / `::: processkit.testing.ScriptedRunner`
_DIRECTIVE_RE = re.compile(r"^::: (processkit(?:\.testing)?)\.(\w+)$", re.MULTILINE)


def _runtime_surface() -> set[tuple[str, str]]:
    """Every public symbol as a `(module, name)` pair, from the imported package."""
    surface = {("processkit", name) for name in processkit.__all__}
    surface |= {("processkit.testing", name) for name in processkit.testing.__all__}
    return surface


def _page_directives() -> set[tuple[str, str]]:
    """Every `::: module.name` directive in the committed page as `(module, name)`."""
    text = _PAGE.read_text(encoding="utf-8")
    return {(m.group(1), m.group(2)) for m in _DIRECTIVE_RE.finditer(text)}


def test_api_reference_page_is_up_to_date() -> None:
    # The committed page must match a byte-for-byte regeneration — otherwise the
    # surface (or a section blurb) changed without rerunning the generator.
    assert gen_api_reference.check(), (
        "docs/api-reference.md is stale. Regenerate it: python scripts/gen_api_reference.py"
    )


def test_static_read_matches_runtime_all() -> None:
    # The generator reads `__all__` statically (AST); the package exposes it at
    # runtime. A skew would mean the generated page documents a different surface
    # than the one that actually imports.
    static_top, static_testing = gen_api_reference.read_public_surface()
    assert static_top == set(processkit.__all__)
    assert static_testing == set(processkit.testing.__all__)


def test_every_public_symbol_is_documented() -> None:
    # Coverage: no public symbol may be missing from the reference.
    missing = _runtime_surface() - _page_directives()
    assert not missing, f"public symbols absent from docs/api-reference.md: {sorted(missing)}"


def test_no_stale_directives() -> None:
    # Reverse: every directive must name a currently-public symbol, so a removed
    # or renamed export can't leave a dangling autodoc entry (which would fail the
    # strict site build with an unresolved symbol).
    stale = _page_directives() - _runtime_surface()
    assert not stale, f"docs/api-reference.md documents non-public symbols: {sorted(stale)}"
