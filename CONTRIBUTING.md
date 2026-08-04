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
- On Windows only: [PowerShell 7](https://aka.ms/powershell) (`pwsh`) on your
  PATH. It is the shell this repository's helper scripts and `just` recipes use,
  and Cargo starts the Rust test binaries through one of them — see
  [Build and test](#build-and-test).

## Build and test

The [`justfile`](justfile) is the single canonical entry point for every dev-cycle
command below; run `just --list` for the full, up-to-date list with descriptions.

```sh
just build              # build the Rust extension and install it in-place
just test               # run the tests (requires `just build` first)
just rust-test          # Rust unit tests (all platforms, Windows included)
just rust-test-windows  # Windows alias of the above that also pins PYO3_PYTHON
just fmt                # apply ruff formatting
just lint               # ruff format --check + ruff check
just typecheck          # mypy --strict, then stubtest against the compiled extension
just docs               # build the mdBook site and validate rendered links
just api-ref            # regenerate docs/api-reference.md
just leak-test          # run the serial memory/reference-stability suite (nightly hardening)
just bench              # run the benchmark suite
```

For a release wheel, use `uv run maturin build --release --out dist` directly (not
part of the day-to-day dev cycle, so it has no `just` recipe).

`ruff check`, `mypy --strict`, and `pytest` (with warnings promoted to errors)
are the gates CI enforces, so run them locally before opening a pull request.
CI additionally runs `cargo fmt --check`, `cargo clippy -- -D warnings`, and
the Rust unit tests.

### Rust tests on Windows

`cargo test` needs nothing special on Windows — no `PATH` edits, no wrapper to
remember, no Python of your own beyond the one `uv sync` provisions.
[`.cargo/config.toml`](.cargo/config.toml) registers
[`scripts/cargo-runner-windows.ps1`](scripts/cargo-runner-windows.ps1) as Cargo's
`runner` for the Windows targets, so Cargo starts *every* test binary through it.
The shim asks uv which interpreter this project uses and prepends the directory
holding its base Python DLL to that process's `PATH`. Without it the binary
cannot resolve `python3.dll` (PyO3 links it for the abi3 build, and a virtualenv
does not put its directory on `PATH`): it dies with `STATUS_DLL_NOT_FOUND`
behind a modal *"python3.dll was not found"* dialog — which, in a headless CI or
agent session, waits forever for an OK nobody will click. As a second line of
defense the shim also turns Windows' error dialogs off for the binaries it
starts, so such a failure is always an exit code rather than a hang; set
`PROCESSKIT_RUNNER_ERROR_DIALOGS=1` to keep the dialogs, e.g. to attach a
just-in-time debugger to a crashing test.

The *build* needs no interpreter of its own either — worth spelling out, because
PyO3 normally looks one up (`PYO3_PYTHON`, then `VIRTUAL_ENV`/`CONDA_PREFIX`,
then `python`/`python3` on `PATH`; an unactivated `.venv` is not in that list, so
you would expect a bare `cargo test` to fail here). It does not, because this
crate's `abi3-py310` build links `python3.dll` through `raw-dylib` on Windows:
PyO3 0.29 needs neither an import library nor a working interpreter for that and
falls back to its stable-ABI configuration. A `uv sync`'d checkout therefore
builds and runs `cargo test` on a machine whose only Python belongs to uv. If you
*do* have a `python` on `PATH`, PyO3 will build against it instead — which is
what the wrapper below is for.

Neither promise is left to trust. CI runs
[`scripts/rust-test-no-system-python.ps1`](scripts/rust-test-no-system-python.ps1),
which strips every directory offering a `python*.exe`/`python3*.dll` from `PATH`,
verifies none is left, and only then runs `cargo test --all-targets`. That makes
the shim the only possible source of the DLL, so a regression in it turns the
build red instead of passing on some unrelated system Python — and it keeps the
build-side claim above honest too, since `PYO3_PYTHON` is left unset. The script
also sets `PROCESSKIT_RUNNER_REQUIRE_PYTHON`, which makes the shim's
(deliberately fail-open) interpreter lookup fatal; the shim turns that on by
itself whenever `CI` is set, so no automated context can quietly lose the fix.
Run it locally as `just rust-test-no-system-python` to reproduce a CI failure, or
to see for yourself that the shim is load-bearing.

`just rust-test-windows` runs
[`scripts/cargo-test-windows.ps1`](scripts/cargo-test-windows.ps1), which stays
supported and adds the one thing a runner cannot: it pins `PYO3_PYTHON`, so the
*build* also uses uv's interpreter rather than whichever `python` comes first on
`PATH`. Both paths resolve the interpreter through the same helper
(`scripts/python-runtime.ps1`), so they cannot drift apart.

One practical cost of keeping both entry points: `PYO3_PYTHON` is a
`rerun-if-env-changed` input of PyO3's build script, so alternating
`just rust-test` (which leaves it unset) with `just rust-test-windows` (which
pins it) recompiles `pyo3-ffi`, `pyo3`, `pyo3-async-runtimes` and this crate
every time you switch. Stick to one of them within a working session; CI pays
that rebuild exactly once, on purpose, to keep both of its checks meaningful.

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
- **Upgrading the `processkit` core** (the Rust crate this binding wraps) is a
  deliberate review step, never a transitive pickup: the crate has historically
  grown public surface and changed behaviour even in patch releases, so the
  release notes alone are not a sufficient basis for a bump. The crate ships a
  `public-api.txt` in its sources, so diff the two versions in the registry
  cache — `~/.cargo/registry/src/*/processkit-<old>/public-api.txt` against
  `.../processkit-<new>/public-api.txt` (`$env:USERPROFILE\.cargo\...` on
  Windows) — and read the accompanying `CHANGELOG.md` there; then check the
  actual signatures in `src/` for anything the diff flags. Update
  `Cargo.toml`'s requirement and comment, commit the resulting `Cargo.lock`, and
  give the change its own CHANGELOG entry when any of it is user-visible.
- The authoritative bar is simply what CI enforces — `ruff`, `mypy --strict`, and
  warning-free `pytest`, plus `cargo fmt` / `clippy` on the Rust side — all
  configured in [`pyproject.toml`](pyproject.toml); run the
  [gates above](#build-and-test) locally before opening a pull request.
- **Docs are built and published here.** `docs.yml` builds the mdBook site,
  validates rendered local links and anchors, and publishes successful
  `main` builds to GitHub Pages. Pull requests run the same build and link
  checks without deploying. Run `just docs` locally and open
  `book/index.html`; see RELEASING.md's "Docs site" note for the live URL and
  preview command.

## Changelog

Every user-visible change ships its [`CHANGELOG.md`](CHANGELOG.md) entry in the
same change set, under `## [Unreleased]`. Write the bullet for a consumer of the
library, not the implementer. Pure internal refactors are exempt.

## Pull requests

- Keep changes focused; unrelated cleanups belong in their own PR.
- Ensure CI (lint, type-check, and tests on Linux, Windows, macOS) passes.
- Fill in the pull-request checklist.
