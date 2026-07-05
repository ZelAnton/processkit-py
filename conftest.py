"""Repo-root conftest.

Enables pytest's bundled `pytester` plugin (not active by default) so
`tests/test_pytest_plugin.py` can run inner pytest sessions to exercise the
`processkit.pytest_plugin` fixtures and guard. `pytest_plugins` must live in the
root conftest, hence this top-level file rather than `tests/conftest.py`.
"""

from __future__ import annotations

pytest_plugins = ["pytester"]
