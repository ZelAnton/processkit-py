#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Shared lookup of the Python runtime this checkout builds and tests against.

.DESCRIPTION
    Dot-source this file — it only defines functions and runs nothing by itself:

        . "$PSScriptRoot/python-runtime.ps1"

    Both Windows entry points into the Rust tests need the same two facts: which
    interpreter uv selected for this project, and which directory holds the base
    Python DLL a PyO3 binary links against (`python3.dll` for the abi3 build;
    `python312.dll` and friends for a version-specific one).

      * scripts/cargo-runner-windows.ps1 — the Cargo `runner` shim wired up in
        .cargo/config.toml, which every Windows test binary goes through;
      * scripts/cargo-test-windows.ps1 — the explicit script alias.

    Keeping the lookup in one place is the point: the answer cannot drift between
    the automatic path and the explicit one, and no Python installation path is
    ever hardcoded to one machine.
#>

function Get-ProcesskitPythonRuntime {
    <#
    .SYNOPSIS
        Resolves the interpreter and base prefix for this checkout.

    .DESCRIPTION
        Returns an object with:

          BasePrefix — `sys.base_prefix`: on Windows the directory that holds the
                       base interpreter and its `python3*.dll`, i.e. exactly what
                       has to be on PATH for a PyO3 binary to start.
          Executable — `sys.executable`: the interpreter itself, suitable for
                       PYO3_PYTHON.
          Source     — how it was resolved, for diagnostics.

        Throws when neither source below can answer.

    .PARAMETER AllowSync
        Allow `uv run` to create or refresh the project environment on the way.
        Off by default: the Cargo runner must never turn a `cargo test` into an
        implicit rebuild of the Python environment behind the developer's back.
        Explicitly invoked developer commands pass it.
    #>
    [CmdletBinding()]
    param(
        [switch] $AllowSync
    )

    # Function-scoped: uv writes progress and warnings to stderr as a matter of
    # course, and a native command's stderr must not be fatal here — its exit
    # code is the failure signal. The caller's preference is untouched.
    $ErrorActionPreference = 'Continue'

    $problems = @()
    $basePrefix = $null
    $executable = $null
    $source = $null

    # 1. Authoritative: ask uv which interpreter this project runs on. This is the
    #    same query the repository has always used, so the Rust tests cannot end up
    #    on a different interpreter than `uv run pytest`.
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($uv) {
        $uvArgs = @('run')
        if (-not $AllowSync) { $uvArgs += '--no-sync' }
        $uvArgs += @('python', '-c', 'import sys; print(sys.base_prefix); print(sys.executable)')

        $lines = @(& $uv.Source @uvArgs 2>$null | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
        if ($LASTEXITCODE -ne 0) {
            $problems += "``uv run`` exited with code $LASTEXITCODE"
        } elseif ($lines.Count -lt 2) {
            $problems += "``uv run`` returned incomplete runtime information"
        } else {
            $basePrefix = $lines[0]
            $executable = $lines[1]
            $source = if ($AllowSync) { 'uv run' } else { 'uv run --no-sync' }
        }
    } else {
        $problems += 'uv is not on PATH'
    }

    # 2. Fallback: the virtual environment records the interpreter it was created
    #    from (`home` in pyvenv.cfg), which keeps a missing/older uv — or a plain
    #    `python -m venv` — from turning into a mystery DLL failure.
    if (-not $basePrefix) {
        $venv = $env:VIRTUAL_ENV
        if (-not $venv) {
            $root = Split-Path -Parent $PSScriptRoot
            if ($env:UV_PROJECT_ENVIRONMENT) {
                $venv = if ([IO.Path]::IsPathRooted($env:UV_PROJECT_ENVIRONMENT)) {
                    $env:UV_PROJECT_ENVIRONMENT
                } else {
                    Join-Path $root $env:UV_PROJECT_ENVIRONMENT
                }
            } else {
                $venv = Join-Path $root '.venv'
            }
        }

        $pyvenvCfg = Join-Path $venv 'pyvenv.cfg'
        if (Test-Path -LiteralPath $pyvenvCfg -PathType Leaf) {
            $homeEntry = Get-Content -LiteralPath $pyvenvCfg |
                Select-String -Pattern '^\s*home\s*=\s*(.+?)\s*$' |
                Select-Object -First 1
            if ($homeEntry) {
                # `home` is the directory of the base interpreter — on Windows that
                # is also where its python3*.dll lives.
                $basePrefix = $homeEntry.Matches[0].Groups[1].Value
                $executable = Join-Path $venv 'Scripts/python.exe'
                if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
                    $executable = Join-Path $venv 'bin/python'
                }
                $source = "pyvenv.cfg in $venv"
            } else {
                $problems += "no ``home`` entry in $pyvenvCfg"
            }
        } else {
            $problems += "no virtual environment at $venv"
        }
    }

    if (-not $basePrefix) {
        throw ("Could not determine the Python runtime for this checkout ({0}). " -f ($problems -join '; ') +
            'Create the environment with `uv sync` (or `just build`) and try again.')
    }
    if (-not (Test-Path -LiteralPath $basePrefix -PathType Container)) {
        throw "Python base prefix does not exist: $basePrefix (resolved from $source)."
    }

    [pscustomobject]@{
        BasePrefix = $basePrefix
        Executable = $executable
        Source     = $source
    }
}
