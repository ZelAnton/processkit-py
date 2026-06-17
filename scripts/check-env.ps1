#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Checks this machine can build and test processkit-py.

.DESCRIPTION
    POSIX counterpart: scripts/check-env.sh — use whichever matches your shell.

    Verifies that uv and the Rust toolchain are on PATH. uv drives the Python
    side (provisions the interpreter, manages the virtualenv, runs lint/test/build);
    rustc/cargo is required to compile the PyO3 extension via maturin.

    Prints "Environment ready" and exits 0 on success; if a tool is missing it
    prints install commands and exits 1 — install the missing tool, then re-run:

        pwsh ./scripts/check-env.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$problems = @()

Write-Host "==> Checking environment for processkit-py development" -ForegroundColor Cyan

# Required: uv (build/test/lint/format driver). It bootstraps the pinned Python
# itself, so no separate `python` is needed on PATH.
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "    $(uv --version)" -ForegroundColor DarkGray
} else {
    $problems += "uv ('uv' is not on PATH)"
}

# Required: Rust toolchain (cargo/rustc) for compiling the PyO3 extension via maturin.
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    Write-Host "    $(cargo --version)" -ForegroundColor DarkGray
} else {
    $problems += "Rust toolchain ('cargo' is not on PATH)"
}

# Soft: git is needed for the VCS workflow but not the build.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "    note: git is not on PATH — needed for version control workflow." -ForegroundColor DarkGray
}

if ($problems.Count -eq 0) {
    Write-Host ""
    Write-Host "Environment ready." -ForegroundColor Green
    Write-Host "Next: uv run maturin develop && uv run pytest" -ForegroundColor DarkGray
    exit 0
}

Write-Host ""
Write-Host "Environment NOT ready. Missing:" -ForegroundColor Red
foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Red }
Write-Host ""
Write-Host "Install uv:" -ForegroundColor Yellow
Write-Host "  Windows : winget install --id=astral-sh.uv -e   (or: irm https://astral.sh/uv/install.ps1 | iex)"
Write-Host "  macOS   : brew install uv                        (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
Write-Host "  Linux   : curl -LsSf https://astral.sh/uv/install.sh | sh"
Write-Host "  (any OS) : see https://docs.astral.sh/uv/getting-started/installation/"
Write-Host ""
Write-Host "Install Rust toolchain: https://rustup.rs/" -ForegroundColor Yellow
exit 1
