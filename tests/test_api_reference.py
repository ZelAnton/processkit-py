"""Drift guard for the generated API-reference page (`docs/api-reference.md`).

The page is static Markdown — one `### \\`Name\\`` heading (plus a signature and
docstring) per public symbol, produced by `scripts/gen_api_reference.py` from the
package's `__all__`. Class members render one level deeper (`#### \\`member\\``), so
matching the top-level `###` headings recovers exactly the documented surface.
Three things must stay in lockstep, and nothing enforces it automatically:

1. the committed page == a fresh regeneration (someone changed the surface but
   forgot to rerun the generator);
2. every runtime-public symbol (`processkit.__all__` plus
   `processkit.testing.__all__`) is documented (a new symbol slipped in
   unreferenced);
3. no heading names a symbol that is no longer public (a stale entry).

The generator reads the surface *statically* (via griffe, so it can run without
the compiled extension); these tests additionally cross-check against the
*imported* package, so a skew between the static read and the compiled module
can't hide. The page does not encode each symbol's module, so the coverage checks
compare bare names — module placement is enforced separately by
`gen_api_reference._validate_sections` and `test_static_read_matches_runtime_all`.
"""

from __future__ import annotations

import pathlib
import re

from scripts import gen_api_reference

import processkit
import processkit.testing

_PAGE = pathlib.Path(processkit.__file__).resolve().parents[2] / "docs" / "api-reference.md"

# A top-level symbol heading: `### \`Command\``. The exactly-three-`#` anchor means
# class-member headings (`#### \`arg\``) and section titles (`## ...`) never match.
_SYMBOL_RE = re.compile(r"^### `(\w+)`$", re.MULTILINE)


def _public_names() -> set[str]:
    """Every public symbol's bare name, from the imported package (both modules)."""
    return set(processkit.__all__) | set(processkit.testing.__all__)


def _documented_symbols() -> set[str]:
    """Every top-level symbol heading in the committed page, by name."""
    text = _PAGE.read_text(encoding="utf-8")
    return {m.group(1) for m in _SYMBOL_RE.finditer(text)}


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
    missing = _public_names() - _documented_symbols()
    assert not missing, f"public symbols absent from docs/api-reference.md: {sorted(missing)}"


def test_no_stale_symbols() -> None:
    # Reverse: every symbol heading must name a currently-public symbol, so a
    # removed or renamed export can't leave a dangling reference entry.
    stale = _documented_symbols() - _public_names()
    assert not stale, f"docs/api-reference.md documents non-public symbols: {sorted(stale)}"
