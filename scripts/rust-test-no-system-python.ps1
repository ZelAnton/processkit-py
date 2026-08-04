#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Runs the Rust tests with every system Python hidden — the regression guard
    for the Cargo runner shim.

.DESCRIPTION
    `cargo test` on Windows only works because .cargo/config.toml routes each test
    binary through scripts/cargo-runner-windows.ps1, which puts the directory of
    uv's base `python3.dll` on that process's PATH.

    Running `cargo test` on a machine that happens to have a Python on PATH does
    not test that at all: the loader finds `python3.dll` next to that unrelated
    interpreter, so the tests pass whether the shim did its job, did nothing, or
    was deleted. A GitHub `windows-latest` image is exactly such a machine, and
    so is a typical developer box.

    This script removes that confound. It strips every directory that provides a
    `python*.exe` or a `python3*.dll` from PATH, clears the environment variables
    that would point PyO3 or the shim at an interpreter, and only then runs
    `cargo test`. Now the sole remaining source of `python3.dll` is the shim, so:

      * a shim that cannot resolve the interpreter fails the run outright
        (PROCESSKIT_RUNNER_REQUIRE_PYTHON below, which this script turns on);
      * a shim that resolves it but stops prepending it to PATH fails the run
        with STATUS_DLL_NOT_FOUND — as an exit code, not a modal dialog, because
        the shim also sets SEM_FAILCRITICALERRORS;
      * a run that goes green really did exercise the fix.

    It doubles as the check behind one documented promise in CONTRIBUTING.md: a
    bare `cargo test` needs no interpreter on PATH *at build time* either. PyO3
    0.29 builds this crate's `abi3-py310` configuration for Windows without any
    interpreter (`make_interpreter_config`'s stable-ABI fallback, reachable
    because `require_libdir_for_target` is false for Windows targets — they use
    `raw-dylib` and need no import library). PYO3_PYTHON is deliberately left
    unset here so that this stays true rather than merely believed.

    CI runs this (see .github/workflows/ci.yml, job `rust-test (windows)`); run it
    locally the same way — `just rust-test-no-system-python` — to reproduce a CI
    failure:

        pwsh ./scripts/rust-test-no-system-python.ps1
        pwsh ./scripts/rust-test-no-system-python.ps1 --no-fail-fast
        pwsh ./scripts/rust-test-no-system-python.ps1 -- --nocapture

    Every argument is appended to `cargo test --all-targets` verbatim, so both
    Cargo flags and (after a `--`) libtest flags work. That verbatim passthrough
    is why this script has no param() block, exactly as in
    scripts/cargo-runner-windows.ps1: PowerShell would otherwise try to bind
    tokens like `--nocapture` as parameters of its own.

    `uv`, `cargo` and `pwsh` must stay reachable after the strip — the script
    verifies that instead of failing later in a confusing way. Run
    `uv sync` (or `just build`) first, so uv has an environment to report.
#>

$ErrorActionPreference = 'Stop'

$separator = [IO.Path]::PathSeparator

function Test-DirectoryProvidesPython {
    param([string] $Directory)

    foreach ($pattern in 'python*.exe', 'python3*.dll') {
        # -ErrorAction SilentlyContinue: PATH routinely lists directories that do
        # not exist or cannot be read, and neither is this script's problem.
        if (Get-ChildItem -LiteralPath $Directory -Filter $pattern -File -ErrorAction SilentlyContinue) {
            return $true
        }
    }
    return $false
}

function Get-PythonOnPath {
    Get-Command 'python', 'python3', 'python3.exe', 'python.exe' `
        -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}

$removed = [System.Collections.Generic.List[string]]::new()

# Two passes over two different signals, because neither alone is enough:
# scanning directory contents misses Windows' app-execution aliases (zero-byte
# reparse points under WindowsApps that Get-ChildItem does not always report),
# while asking Get-Command only ever reveals the first match. So: strip by
# content, then keep stripping whatever `python`/`python3` still resolves to
# until nothing does. The loop is bounded so a directory that somehow cannot be
# removed turns into an error rather than a hang.
$kept = @($env:PATH -split $separator | Where-Object { $_ } | Where-Object {
        if (Test-DirectoryProvidesPython $_) { $removed.Add($_); $false } else { $true }
    })
$env:PATH = $kept -join $separator

for ($attempt = 0; $attempt -lt 16; $attempt++) {
    $stillThere = Get-PythonOnPath
    if (-not $stillThere) { break }

    $directory = Split-Path -Parent $stillThere.Source
    if (-not $directory -or $removed -contains $directory) {
        throw "Could not hide $($stillThere.Source) from PATH."
    }
    $removed.Add($directory)
    $env:PATH = (@($env:PATH -split $separator | Where-Object { $_ -and $_ -ne $directory }) -join $separator)
}

# PyO3 picks the build interpreter from PYO3_PYTHON, then VIRTUAL_ENV/
# CONDA_PREFIX, then PATH; the shim honours a pre-resolved directory. Clear all
# of them so nothing but the shim's own lookup is left.
foreach ($name in 'PYO3_PYTHON', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'PROCESSKIT_PYTHON_DLL_DIR') {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}

# Fail closed: an interpreter lookup that does not work out must fail this run
# rather than print a diagnostic into a log nobody reads. Honour an explicit
# override so the script stays usable for debugging the fail-open path itself.
if ($null -eq $env:PROCESSKIT_RUNNER_REQUIRE_PYTHON) {
    $env:PROCESSKIT_RUNNER_REQUIRE_PYTHON = '1'
}

# --- Verify the setup before trusting the result it produces -----------------

$leftovers = @($env:PATH -split $separator | Where-Object { $_ } | Where-Object {
        Get-ChildItem -LiteralPath $_ -Filter 'python3*.dll' -File -ErrorAction SilentlyContinue
    })
if ($leftovers) {
    throw ("PATH still offers python3*.dll from: {0}. This run would prove nothing, " -f ($leftovers -join ', ') +
        'because the test binary could load the DLL without the shim.')
}

$stillResolvable = Get-PythonOnPath
if ($stillResolvable) {
    throw "PATH still resolves a Python interpreter: $($stillResolvable.Source)."
}

foreach ($required in 'cargo', 'pwsh', 'uv') {
    if (-not (Get-Command $required -CommandType Application -ErrorAction SilentlyContinue)) {
        throw ("Stripping Python from PATH also removed ``$required``, which this check needs " +
            '(cargo builds, pwsh runs the Cargo runner, uv answers which interpreter the project uses).')
    }
}

Write-Host 'Removed from PATH for this process:'
foreach ($directory in $removed) { Write-Host "  $directory" }
Write-Host 'No python*.exe and no python3*.dll are reachable through PATH any more,'
Write-Host 'so the only way the test binary can start is scripts/cargo-runner-windows.ps1.'
Write-Host ''

# The one Windows loader directory PATH does not cover is the binary's own, and
# that one is Cargo's target directory — nothing puts a python3.dll there.
#
# 'Continue' so a failing test (a nonzero native exit code) stays an ordinary
# result to forward rather than a PowerShell error, on every host regardless of
# $PSNativeCommandUseErrorActionPreference.
#
# $LASTEXITCODE is cleared first for the same reason scripts/cargo-runner-windows.ps1
# does it: PowerShell leaves it untouched when a command never starts at all, and
# nothing native has run in this script yet, so `exit $LASTEXITCODE` would exit 0
# and report a pass for a check that never happened.
$ErrorActionPreference = 'Continue'
$global:LASTEXITCODE = $null

& cargo test --all-targets @args

if ($null -eq $global:LASTEXITCODE) {
    [Console]::Error.WriteLine('rust-test-no-system-python.ps1: cargo did not run.')
    exit 127
}
exit $global:LASTEXITCODE
