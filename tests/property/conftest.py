"""Hypothesis profile configuration for `tests/property/`.

Kept separate from the example-based suite (`tests/conftest.py`) since it is
only meaningful where `@given(...)` is actually used. Two profiles balance
thorough local exploration against a bounded, deterministic CI budget:

- ``"default"`` (interactive/local runs): a generous example count, no
  per-example wall-clock deadline.
- ``"ci"`` (any CI runner — detected via the ``CI`` env var every major CI
  provider, including GitHub Actions, sets): fewer examples (bounded runtime
  against real subprocess spawns in some of these tests) and
  ``derandomize=True`` — the exact same set of inputs is explored on every
  run, so a CI failure reproduces byte-for-byte from a local
  ``HYPOTHESIS_PROFILE=ci`` run of the same test, with no dependence on the
  (gitignored, per-machine) ``.hypothesis/`` example database.

``deadline=None`` in both profiles: nothing here races a per-example
wall-clock budget on purpose — the whole-test hang guard is `pytest-timeout`
(configured in `pyproject.toml`), which already bounds a genuine hang; a
per-example Hypothesis deadline on top would only add flakiness under load
(a busy CI runner, contending `pytest-xdist` workers) without catching
anything a real bug wouldn't already trip via a returned wrong value.

``HYPOTHESIS_PROFILE`` overrides the auto-detected default explicitly (e.g.
``HYPOTHESIS_PROFILE=ci uv run pytest`` to reproduce a CI run's example set
locally).
"""

from __future__ import annotations

import os

from hypothesis import settings

settings.register_profile("default", max_examples=100, deadline=None, print_blob=True)
settings.register_profile(
    "ci",
    max_examples=25,
    deadline=None,
    derandomize=True,
    print_blob=True,
)

_auto_default = "ci" if os.environ.get("CI") else "default"
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", _auto_default))
