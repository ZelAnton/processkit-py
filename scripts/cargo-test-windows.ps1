#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Runs Rust unit tests with uv's Python runtime available on Windows.

.DESCRIPTION
    PyO3's test binary links to the base Python DLL. A virtual environment does
    not place the directory containing that DLL on PATH, so a directly launched
    cargo test binary otherwise exits with STATUS_DLL_NOT_FOUND.

    Run `uv run maturin develop` first, then invoke this script from the project
    root. The Python base prefix is discovered from the interpreter selected by
    uv; no Python installation path is hardcoded.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$pythonInfo = & uv run python -c "import sys; print(sys.base_prefix); print(sys.executable)"
if ($LASTEXITCODE -ne 0) {
    throw "Could not query the Python interpreter selected by uv."
}
if ($pythonInfo.Count -lt 2) {
    throw "uv's Python interpreter returned incomplete runtime information."
}

$pythonBasePrefix = $pythonInfo[0].Trim()
$pythonExecutable = $pythonInfo[1].Trim()
if (-not (Test-Path -LiteralPath $pythonBasePrefix -PathType Container)) {
    throw "Python base prefix does not exist: $pythonBasePrefix"
}
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Python executable does not exist: $pythonExecutable"
}

# Select the same interpreter for PyO3's build configuration and make its base
# DLL (for example, python312.dll) discoverable when Windows starts the test exe.
$env:PYO3_PYTHON = $pythonExecutable
$env:PATH = "$pythonBasePrefix$([IO.Path]::PathSeparator)$env:PATH"

& cargo test --all-targets
exit $LASTEXITCODE
