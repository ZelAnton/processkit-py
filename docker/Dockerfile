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

# Download the pinned uv release archive and verify it before extracting or
# executing the binary. TARGETARCH keeps the harness usable on amd64 and arm64.
ARG UV_VERSION=0.12.5
ARG TARGETARCH
RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) uv_target="x86_64-unknown-linux-gnu"; uv_sha256="68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2" ;; \
        arm64) uv_target="aarch64-unknown-linux-gnu"; uv_sha256="9bf43b4d1a07665bf64d4c4e710930b382321a785e0eb10aac07f46471f86a31" ;; \
        *) echo "Unsupported Docker target architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    archive="uv-${uv_target}.tar.gz"; \
    archive_path="/tmp/${archive}"; \
    curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --retry-delay 2 \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${archive}" \
        -o "$archive_path"; \
    printf '%s  %s\n' "$uv_sha256" "$archive_path" | sha256sum -c -; \
    tar -xzf "$archive_path" -C /tmp; \
    install -m 0755 "/tmp/uv-${uv_target}/uv" /usr/local/bin/uv; \
    install -m 0755 "/tmp/uv-${uv_target}/uvx" /usr/local/bin/uvx; \
    rm -rf "/tmp/uv-${uv_target}" "$archive_path"
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
