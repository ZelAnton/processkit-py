#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Runs Rust unit tests with uv's Python runtime available on Windows.

.DESCRIPTION
    PyO3's test binary links to the base Python DLL. A virtual environment does
    not place the directory containing that DLL on PATH, so a directly launched
    cargo test binary otherwise exits with STATUS_DLL_NOT_FOUND.

    That part is no longer this script's job: .cargo/config.toml routes every
    Windows test binary through scripts/cargo-runner-windows.ps1, so a plain
    `cargo test --all-targets` already finds the DLL. This script stays as the
    explicit, named entry point (`just rust-test-windows`, CI, muscle memory) and
    adds the one thing a runner cannot do — it pins PYO3_PYTHON, so the *build*
    also uses the interpreter uv selected instead of whichever `python` happens to
    come first on PATH.

    Both paths resolve the interpreter through the same helper
    (scripts/python-runtime.ps1); no Python installation path is hardcoded.

    Run `uv run maturin develop` first, then invoke this script from the project
    root.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/python-runtime.ps1"

# -AllowSync: this script is an explicit developer command, so letting uv create
# or refresh the environment on the way is expected here (the Cargo runner, which
# runs per binary, deliberately does not).
$runtime = Get-ProcesskitPythonRuntime -AllowSync

if (-not (Test-Path -LiteralPath $runtime.Executable -PathType Leaf)) {
    throw "Python executable does not exist: $($runtime.Executable)"
}

# Select the same interpreter for PyO3's build configuration and make its base
# DLL (for example, python312.dll) discoverable when Windows starts the test exe.
$env:PYO3_PYTHON = $runtime.Executable
$separator = [IO.Path]::PathSeparator
if (($env:PATH -split $separator) -notcontains $runtime.BasePrefix) {
    $env:PATH = "$($runtime.BasePrefix)$separator$env:PATH"
}
# Hand the resolved directory to the Cargo runner below, which then skips its own
# lookup instead of querying uv a second time.
$env:PROCESSKIT_PYTHON_DLL_DIR = $runtime.BasePrefix

& cargo test --all-targets
exit $LASTEXITCODE
