"""Benchmark suite (`pytest-benchmark`) — overhead vs `subprocess`.

Not part of the PR gate: `[tool.pytest.ini_options] testpaths` in
`pyproject.toml` is `["tests"]`, so an ordinary `pytest` run never collects
this directory. It runs on a schedule (and on manual dispatch) from the
`bench` job in `.github/workflows/nightly-hardening.yml`, which installs the
separate `bench` dependency-group and invokes `pytest benchmarks/
--benchmark-only` explicitly. See `benchmarks/README.md` to run it locally.
"""

from __future__ import annotations
