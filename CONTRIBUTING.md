# Contributing to processkit

Thanks for your interest in improving **processkit**.

Before diving into the code, read [`docs/internals.md`](docs/internals.md) —
the architecture reference: the binding-crate/Python-package layering, the
boundary between this repo and the upstream `processkit` crate, the Python →
PyO3 → crate → typed-exception call flow, the module conventions
(`register(m)`, `runner_pymethods!`, config-as-kwargs, sync/async verb
parity), and how the stub/runtime/`__all__` drift guard works.

## Prerequisites

- Python 3.12 (uv provisions the exact interpreter pinned in `.python-version`).
- [uv](https://docs.astral.sh/uv/) on your PATH — run `scripts/check-env.sh`
  (or `scripts/check-env.ps1`) to confirm.
- A Rust toolchain — install via [rustup](https://rustup.rs/).
- [`just`](https://github.com/casey/just#installation) — the dev task runner
  used below (`cargo install just`, `uv tool install rust-just`,
  `winget install --id Casey.Just`, or `brew install just` all work).

## Build and test

The [`justfile`](justfile) is the single canonical entry point for every dev-cycle
command below; run `just --list` for the full, up-to-date list with descriptions.

```sh
just build              # build the Rust extension and install it in-place
just test               # run the tests (requires `just build` first)
just rust-test          # Rust unit tests (Linux/macOS)
just rust-test-windows  # Rust unit tests (Windows; after `just build`)
just fmt                # apply ruff formatting
just lint               # ruff format --check + ruff check
just typecheck          # mypy --strict, then stubtest against the compiled extension
just docs               # build the mdBook site
just api-ref            # regenerate docs/api-reference.md
just bench              # run the benchmark suite
```

For a release wheel, use `uv run maturin build --release --out dist` directly (not
part of the day-to-day dev cycle, so it has no `just` recipe).

`ruff check`, `mypy --strict`, and `pytest` (with warnings promoted to errors)
are the gates CI enforces, so run them locally before opening a pull request.
CI additionally runs `cargo fmt --check`, `cargo clippy -- -D warnings`, and
the Rust unit tests. On Windows, `just rust-test-windows` obtains uv's selected
Python base prefix programmatically and adds it to `PATH`, allowing the Cargo
test binary to find the base Python DLL without a machine-specific path.

## Pre-commit (optional but recommended)

A [pre-commit](https://pre-commit.com/) config mirrors the formatting/lint gates
so they run automatically on `git commit`:

```sh
uv run pre-commit install        # set up the git hook (once)
uv run pre-commit run --all-files  # run against the whole tree
```

It runs ruff (lint + format) and `cargo fmt`; `cargo clippy` and the test suite
stay in CI (too slow for a commit hook). Keep hook versions current with
`uv run pre-commit autoupdate`.

## Testing on Linux with Docker

Some behaviour only runs on Linux/macOS — the cgroup/process-group teardown,
async cancellation, and the `Ctrl+C` interrupt test are skipped on Windows. To
exercise them from a Windows (or any) host, run the suite in a container:

```sh
docker compose run --build --rm test
```

(`just docker-test` wraps the same command.) This builds the PyO3 extension
with a real Rust toolchain + uv and runs `pytest` on Linux. The container is
`privileged` so the crate selects the `cgroup_v2`
mechanism — the same path CI's Linux runner uses; drop `privileged` in
[`compose.yaml`](compose.yaml) to test the `process_group` fallback instead.
Append a command to scope the run:

```sh
docker compose run --build --rm test uv run pytest -q tests/test_async.py
```

It needs a Docker-compatible engine (Docker Desktop, Rancher Desktop, …) and
writes nothing to your working tree. It complements — does not replace — the
native `uv run pytest`, which is faster for day-to-day work.

## Conventions

- **Formatting and linting** are governed by [`ruff`](https://docs.astral.sh/ruff/)
  (config in [`pyproject.toml`](pyproject.toml)). Run `just fmt` to apply
  formatting; don't reformat code you are not changing.
- **Dependencies** are declared in `pyproject.toml` and pinned in `uv.lock`
  (commit the lockfile). Add them with `uv add`, not by hand.
- The authoritative bar is simply what CI enforces — `ruff`, `mypy --strict`, and
  warning-free `pytest`, plus `cargo fmt` / `clippy` on the Rust side — all
  configured in [`pyproject.toml`](pyproject.toml); run the
  [gates above](#build-and-test) locally before opening a pull request.
- **Docs are built here, not published here.** `docs.yml` runs `mkdocs build
  --strict` as a link/anchor check only; this repo does not deploy to GitHub
  Pages or anywhere else (a separate project owns docs publishing). Do not
  add a Pages/`mike`/`gh-pages` deploy step back — see RELEASING.md's "Docs
  site" note.

## Changelog

Every user-visible change ships its [`CHANGELOG.md`](CHANGELOG.md) entry in the
same change set, under `## [Unreleased]`. Write the bullet for a consumer of the
library, not the implementer. Pure internal refactors are exempt.

## Pull requests

- Keep changes focused; unrelated cleanups belong in their own PR.
- Ensure CI (lint, type-check, and tests on Linux, Windows, macOS) passes.
- Fill in the pull-request checklist.
