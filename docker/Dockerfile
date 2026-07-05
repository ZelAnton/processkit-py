# syntax=docker/dockerfile:1
#
# Local Linux test environment for processkit-py — mirrors the CI `test` job.
# It builds the PyO3 extension with a real Rust toolchain + uv and runs pytest,
# so you can exercise the Linux teardown / async-cancellation / SIGINT paths
# that the Windows test run skips, without leaving Windows.
#
# Use it through compose from the repo root (see compose.yaml):
#
#   docker compose run --build --rm test                 # full suite
#   docker compose run --build --rm test uv run pytest -q tests/test_async.py
#
# `--build` rebuilds the image so it picks up your latest source; BuildKit cache
# mounts keep the Rust/uv caches warm so rebuilds are incremental.

FROM rust:1-bookworm

# uv provisions the pinned Python, the virtualenv, dependencies, and the build.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
COPY . .

# Build the abi3 extension and install it into the venv. Cache mounts persist
# the cargo registry, the build target, and uv's download cache across rebuilds
# (they are not baked into the image, keeping it lean).
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/target \
    --mount=type=cache,target=/root/.cache/uv \
    uv run maturin develop

# `/root` defaults to `0700` (root-only), but the venv's `python` symlink resolves
# into `/root/.local/share/uv/python/...` (just provisioned above) — so a
# process that drops privilege to an unprivileged uid (see
# tests/test_command.py's privilege-drop test, exercised by the CI
# `test-privileged` job) cannot even traverse into `/root` to exec it, and fails
# with EACCES before the privilege-drop logic itself is exercised at all. Grant
# "traverse only" (`+x`, no `+r`) on `/root` itself (its own file listing stays
# private) and read+execute on the provisioned Python tree, which holds no
# secrets.
RUN chmod o+x /root && chmod -R o+rX /root/.local/share/uv/python

# Default to the full suite; override the command to scope it (see header).
CMD ["uv", "run", "pytest"]
