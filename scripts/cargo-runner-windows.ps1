#!/usr/bin/env pwsh
# =============================================================================
# Cargo `runner` shim for the Windows targets — wired up in .cargo/config.toml.
#
# Cargo starts every binary it builds for a target through that target's
# `runner`, so this script wraps each Windows test/example binary and makes a
# bare `cargo test` behave like the explicit scripts/cargo-test-windows.ps1
# without anyone having to remember that the wrapper exists.
#
# The problem it removes: the test binary links the stable-ABI Python DLL
# (`python3.dll`, from PyO3's `abi3-py310` feature in Cargo.toml). uv keeps that
# DLL next to the base interpreter it provisioned, and a virtual environment does
# not put that directory on PATH — so the Windows loader cannot resolve the
# import and kills the process with STATUS_DLL_NOT_FOUND (0xC0000135) behind a
# modal "The code execution cannot proceed because python3.dll was not found"
# System Error box. In a headless CI/agent session that dialog waits forever for
# an OK nobody will click.
#
# Two deliberate shapes:
#
#   * No param()/[CmdletBinding()] block. Cargo appends the binary and then the
#     libtest arguments; they must reach $args verbatim, and a param block would
#     try to bind tokens like `--exact` or `-q` as PowerShell parameters.
#   * Fail-open interactively, fail-closed in automation. At a developer's
#     prompt a shim that refuses to start a binary would be a worse failure than
#     the one it prevents, so a lookup that does not work out only prints a
#     diagnostic and runs the binary anyway. In CI that trade inverts: a silently
#     degraded lookup there is invisible, and the test would pass on whatever
#     Python the runner image happens to have on PATH — so the same situation
#     exits nonzero instead. See PROCESSKIT_RUNNER_REQUIRE_PYTHON below.
#
# Environment variables it honours:
#
#   PROCESSKIT_PYTHON_DLL_DIR        Pre-resolved directory holding python3*.dll.
#                                    Set it to skip the lookup (this is how
#                                    scripts/cargo-test-windows.ps1 hands its own
#                                    result down to the nested Cargo runner), or
#                                    to point at an interpreter of your choice.
#   PROCESSKIT_RUNNER_ERROR_DIALOGS  Set to 1 to keep Windows' error dialogs for
#                                    the child, e.g. to attach a JIT debugger to
#                                    a crashing test.
#   PROCESSKIT_RUNNER_REQUIRE_PYTHON 1/true/yes/on: a lookup that cannot produce
#                                    a directory with a python3*.dll in it is
#                                    fatal (exit 3) instead of a warning.
#                                    0/false/no/off: never fatal. Unset: follows
#                                    $env:CI, so every automated context is
#                                    fail-closed by default and cannot silently
#                                    lose this fix, while interactive use keeps
#                                    the forgiving behaviour.
#
# Exit codes of its own (anything else comes from the binary it started):
#   2   Cargo did not pass a target executable — the script was run by hand.
#   3   Required Python runtime unavailable (see above).
#   127 The target executable could not be started at all.
# =============================================================================

$ErrorActionPreference = 'Stop'

# Accepts the usual spellings on both sides so this reads the same as any other
# boolean switch in CI configuration; anything else non-empty counts as "on".
function Test-ProcesskitTruthy {
    param([string] $Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return $Value.Trim() -notin @('0', 'false', 'no', 'off')
}

$requirePython = if ($null -ne $env:PROCESSKIT_RUNNER_REQUIRE_PYTHON) {
    Test-ProcesskitTruthy $env:PROCESSKIT_RUNNER_REQUIRE_PYTHON
} else {
    Test-ProcesskitTruthy $env:CI
}

if ($args.Count -lt 1) {
    [Console]::Error.WriteLine(
        'cargo-runner-windows.ps1: expected the target executable as the first argument. ' +
        'Cargo passes it automatically; this script is not meant to be run by hand.')
    exit 2
}

$executable = $args[0]
$forwarded = @($args | Select-Object -Skip 1)

# -----------------------------------------------------------------------------
# 1. Defense in depth: no modal error box for anything we launch.
#
# SEM_FAILCRITICALERRORS (0x0001) covers the loader's "DLL was not found" hard
# error, SEM_NOGPFAULTERRORBOX (0x0002) the crash dialog. A child process
# inherits its parent's error mode unless it is created with
# CREATE_DEFAULT_ERROR_MODE, so setting it here also covers the test binary and
# whatever it spawns. Failures are reported as exit codes instead of blocking on
# a dialog — the right trade for a test process, and the reason this is scoped to
# processes started by this shim rather than done globally through WER's
# registry `DontShowUI`, which would also swallow real crash reports machine-wide.
# -----------------------------------------------------------------------------
if ($env:PROCESSKIT_RUNNER_ERROR_DIALOGS -ne '1') {
    try {
        if (-not ('ProcesskitDev.WindowsErrorMode' -as [type])) {
            Add-Type -Namespace 'ProcesskitDev' -Name 'WindowsErrorMode' -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetErrorMode(uint uMode);
'@
        }
        [void][ProcesskitDev.WindowsErrorMode]::SetErrorMode(0x0001 -bor 0x0002)
    } catch {
        [Console]::Error.WriteLine(
            "cargo-runner-windows.ps1: could not suppress Windows error dialogs ($($_.Exception.Message)); continuing.")
    }
}

# -----------------------------------------------------------------------------
# 2. Best effort: put the base Python DLL directory on PATH for the child.
# -----------------------------------------------------------------------------
$dllDir = $env:PROCESSKIT_PYTHON_DLL_DIR
if ($dllDir -and -not (Test-Path -LiteralPath $dllDir -PathType Container)) {
    [Console]::Error.WriteLine(
        "cargo-runner-windows.ps1: PROCESSKIT_PYTHON_DLL_DIR does not exist: $dllDir; resolving the interpreter instead.")
    $dllDir = $null
}

if (-not $dllDir) {
    try {
        . "$PSScriptRoot/python-runtime.ps1"
        # No -AllowSync: a Cargo runner runs per binary and must stay side-effect
        # free — it may look the environment up, never build or change it.
        $dllDir = (Get-ProcesskitPythonRuntime).BasePrefix
    } catch {
        [Console]::Error.WriteLine("cargo-runner-windows.ps1: $($_.Exception.Message)")
        if ($requirePython) {
            [Console]::Error.WriteLine(
                'cargo-runner-windows.ps1: not starting the binary — this context asks for a resolved Python ' +
                'runtime (PROCESSKIT_RUNNER_REQUIRE_PYTHON/CI). Running it anyway would either fail with ' +
                'STATUS_DLL_NOT_FOUND or, worse, quietly succeed against some unrelated Python that happens ' +
                'to be on PATH, hiding the broken lookup. Set PROCESSKIT_RUNNER_REQUIRE_PYTHON=0 to run it regardless.')
            exit 3
        }
        [Console]::Error.WriteLine(
            'cargo-runner-windows.ps1: starting the binary anyway — expect STATUS_DLL_NOT_FOUND (0xC0000135) ' +
            'if it links the Python DLL.')
    }
}

if ($dllDir) {
    if (-not (Get-ChildItem -LiteralPath $dllDir -Filter 'python3*.dll' -File -ErrorAction SilentlyContinue)) {
        [Console]::Error.WriteLine(
            "cargo-runner-windows.ps1: no python3*.dll under $dllDir; the binary may still fail to start.")
        if ($requirePython) {
            [Console]::Error.WriteLine(
                'cargo-runner-windows.ps1: not starting the binary — see the PROCESSKIT_RUNNER_REQUIRE_PYTHON note above.')
            exit 3
        }
    }

    $separator = [IO.Path]::PathSeparator
    if (($env:PATH -split $separator) -notcontains $dllDir) {
        $env:PATH = "$dllDir$separator$env:PATH"
    }
    # Hand the answer down: a nested `cargo test` (or a test that shells out to
    # one) reuses it instead of resolving the interpreter all over again.
    $env:PROCESSKIT_PYTHON_DLL_DIR = $dllDir
}

# -----------------------------------------------------------------------------
# 3. Run the binary Cargo asked for and report its exit code as our own.
#
# 'Continue' so a failing test (a nonzero native exit code) stays an ordinary
# result to forward rather than a PowerShell error, on every host regardless of
# $PSNativeCommandUseErrorActionPreference.
#
# $LASTEXITCODE is cleared first because PowerShell leaves it untouched when a
# binary never starts at all (deleted between build and run, blocked by AV or
# policy, not a valid image). Without the reset it would still hold the 0 from
# the interpreter lookup above, and this shim would report a pass for a test that
# never ran — the one failure mode a test wrapper must not have.
# -----------------------------------------------------------------------------
$ErrorActionPreference = 'Continue'
$global:LASTEXITCODE = $null

& $executable @forwarded

if ($null -eq $global:LASTEXITCODE) {
    [Console]::Error.WriteLine("cargo-runner-windows.ps1: could not start $executable")
    exit 127
}
exit $global:LASTEXITCODE
