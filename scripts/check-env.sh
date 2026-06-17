#!/usr/bin/env bash
#
# Checks this machine can build and test processkit-py.
# POSIX counterpart of scripts/check-env.ps1 — use whichever matches your shell.
#
# Verifies that uv and the Rust toolchain (cargo/rustc) are on PATH. uv drives
# the Python side; Rust is required to compile the PyO3 extension via maturin.
# Exits 0 when ready; prints install commands and exits 1 when a tool is missing.
#
# Usage: bash ./scripts/check-env.sh

set -euo pipefail
case "${1:-}" in -h|--help) sed -n '2,13p' "$0"; exit 0 ;; esac

problems=()
echo "==> Checking environment for processkit-py development"

# Required: uv (build/test/lint/format driver). It bootstraps the pinned Python
# itself, so no separate `python` is needed on PATH.
if command -v uv >/dev/null 2>&1; then
  echo "    $(uv --version)"
else
  problems+=("uv ('uv' is not on PATH)")
fi

# Required: Rust toolchain (cargo/rustc) for compiling the PyO3 extension via maturin.
if command -v cargo >/dev/null 2>&1; then
  echo "    $(cargo --version)"
else
  problems+=("Rust toolchain ('cargo' is not on PATH)")
fi

# Soft: git is needed for the VCS workflow but not the build.
command -v git >/dev/null 2>&1 || \
  echo "    note: git is not on PATH — needed for version control workflow."

if [ ${#problems[@]} -eq 0 ]; then
  echo
  echo "Environment ready."
  echo "Next: uv run maturin develop && uv run pytest"
  exit 0
fi

echo
echo "Environment NOT ready. Missing:"
for p in "${problems[@]}"; do echo "  - $p"; done
echo
echo "Install uv:"
echo "  Windows : winget install --id=astral-sh.uv -e   (or: irm https://astral.sh/uv/install.ps1 | iex)"
echo "  macOS   : brew install uv                        (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
echo "  Linux   : curl -LsSf https://astral.sh/uv/install.sh | sh"
echo "  (any OS) : see https://docs.astral.sh/uv/getting-started/installation/"
echo
echo "Install Rust toolchain: https://rustup.rs/"
exit 1
