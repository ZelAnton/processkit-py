# Dev task runner for processkit — one canonical command per dev-cycle step.
#
# Why `just` and not `nox`/`poe`: several of these steps aren't Python at all
# (cargo, mdbook, a PowerShell script for the Windows Rust-test workaround), so
# a Python-task runner would need a Python interpreter bootstrapped just to shell
# out to non-Python tools. `just` is a single cross-platform binary with no
# Python-environment dependency, so it works identically before and after
# `uv run maturin develop` and regardless of which interpreter is active.
#
# Install: https://github.com/casey/just#installation (or `cargo install just`,
# `uv tool install rust-just`, `winget install --id Casey.Just`, `brew install just`).
#
# Every recipe below only wraps an existing canonical command (see
# CONTRIBUTING.md and .github/workflows/ci.yml) — it introduces no new
# formatting/testing/build logic of its own.

# `just` otherwise looks for `sh` even on Windows, where this repository's
# documented shell and helper scripts use PowerShell 7.
set windows-shell := ["pwsh", "-NoLogo", "-Command"]

# List available recipes (default when `just` is run with no arguments).
default:
    just --list

# Build the Rust extension and install it in-place (required before test/rust-test).
build:
    uv run maturin develop

# Run the Python test suite (requires `just build` first).
test:
    uv run pytest

# Apply ruff formatting.
fmt:
    uv run ruff format .

# Check formatting and lint (the read-only gate CI enforces; use `just fmt` to fix).
lint:
    uv run ruff format --check .
    uv run ruff check .

# Type-check: mypy --strict, then stubtest the compiled extension against the stub.
typecheck:
    uv run mypy
    uv run python -m mypy.stubtest processkit --ignore-disjoint-bases --allowlist stubtest-allowlist.txt

# Rust unit tests (Linux/macOS only — on Windows use `just rust-test-windows`).
rust-test:
    cargo test --all-targets

# Rust unit tests (Windows only, after `just build` — on Linux/macOS use `just rust-test`).
rust-test-windows:
    pwsh ./scripts/cargo-test-windows.ps1

# Build the mdBook documentation site and validate rendered local links/anchors.
docs:
    mdbook build
    uv run python scripts/check_docs_links.py book

# Regenerate docs/api-reference.md from the type stub.
api-ref:
    uv run python scripts/gen_api_reference.py

# Verify docs/api-reference.md is up to date without rewriting it (CI-style check).
api-ref-check:
    uv run python scripts/gen_api_reference.py --check

# Run the benchmark suite (benchmarks/, pytest-benchmark; separate from `just test`).
bench:
    uv sync --group bench
    uv run pytest benchmarks/ --benchmark-only -p no:xdist -o addopts=""

# Run the test suite in the Linux Docker container (covers cgroup/process-group teardown, async cancellation, and Ctrl+C paths skipped on Windows).
docker-test:
    docker compose run --build --rm test
