# Command-line usage

[‹ docs index](README.md)

Most of this package's value lives behind Python code — but sometimes the
caller is a shell script or a CI step, not a Python program. `python -m
processkit run` is a thin CLI wrapper over `Command` / `ProcessGroup` for
exactly that case: kill-on-exit containment and resource limits for a single
shell command, with no Python to write. `python -m processkit doctor` is its
read-only companion: a preflight diagnosis of what this environment's kernel
actually grants, without running anything (see
[below](#doctor-preflight-diagnose-the-environment)).

- [Basic usage](#basic-usage)
- [Flags](#flags)
- [Exit codes](#exit-codes)
- [Resource limits: hard cap or best effort?](#resource-limits-hard-cap-or-best-effort)
- [`doctor`: preflight-diagnose the environment](#doctor-preflight-diagnose-the-environment)
- [What you don't get here](#what-you-dont-get-here)

## Basic usage

```bash
python -m processkit run -- pytest -x
```

Everything after the **first** `--` is the child's own argv, untouched — a
second `--` in there belongs to the child, not to this wrapper:

```bash
python -m processkit run -- git log -- README.md
#                          ^ separator            ^ the child's own "--"
```

The child runs inside a `ProcessGroup`: even for one command, its whole
process tree — every grandchild it forks — is torn down when this wrapper
exits, and its stdout/stderr are inherited straight through to your terminal
(live, not buffered up and dumped at the end).

```bash
# Bound the whole run to 30 seconds.
python -m processkit run --timeout 30 -- pytest -x

# Cap memory and process count too (needs a real container — see below).
python -m processkit run --max-memory 536870912 --max-processes 64 -- ./build.sh
```

## Flags

| Flag | Maps to | Notes |
|---|---|---|
| `--timeout SECONDS` | `Command.timeout(seconds)` | Kills the whole tree once the deadline passes. |
| `--timeout-grace SECONDS` | `Command.timeout_grace(seconds)` | Signal first, hard-kill after `SECONDS`. Requires `--timeout`; a usage error otherwise. |
| `--max-memory BYTES` | `ProcessGroup(max_memory=...)` | Whole-tree memory cap. |
| `--max-processes N` | `ProcessGroup(max_processes=...)` | Fork-bomb ceiling for the tree. |
| `--cpu-quota FLOAT` | `ProcessGroup(cpu_quota=...)` | Fraction of a **single** core (`0.5` = half, `2.0` = two cores). |
| `--env-clear` | `Command.env_clear()` | Start the child with an empty environment. |
| `--inherit-env NAME` | `Command.inherit_env([...])` | Allow-list a parent variable through (implies `--env-clear`). Repeatable. |
| `--env KEY=VALUE` | `Command.env(key, value)` | Set/override a child environment variable. Repeatable. A value without `=` is a usage error. |
| `--cwd DIR` | `Command.cwd(dir)` | Run the child with `DIR` as its working directory. |

Every numeric flag rejects zero and negative values at the argument-parsing
stage (a usage error, not a traceback). See `docs/process-groups.md` and
`docs/commands.md` for what each underlying builder method does in full —
including how the environment builders (`env_clear` / `inherit_env` / `env`)
compose regardless of call order.

## Exit codes

This wrapper's own exit code mirrors the child's — plus a small set of
reserved codes for cases where there is no child exit code to report,
following the same convention GNU coreutils' `timeout` and POSIX shells use:

| Exit code | Meaning |
|---|---|
| *(the child's own code)* | Normal completion — passed through unchanged. |
| `124` | `--timeout` expired; the tree was killed. |
| `125` | An internal / containment failure (see below). |
| `126` | The program was found but could not be executed. |
| `127` | The program could not be found. |
| `128 + N` | The child was killed by signal `N` (POSIX only). |
| `128 + SIGINT` (`130`) | `python -m processkit` itself was interrupted (Ctrl+C). |

None of these ever surface as a raw Python traceback — every documented
processkit exception (`Timeout`, `Signalled`, `ProcessNotFound`,
`PermissionDenied`, `ResourceLimit`, `Unsupported`) is caught and turned into
one of the codes above, with a one-line message on stderr.

## Resource limits: hard cap or best effort?

`--max-memory` / `--max-processes` / `--cpu-quota` need a real container — a
Windows Job Object or a Linux **cgroup-v2 root** (see
[Process groups](process-groups.md#resource-limits-the-sandbox) and
[Platform support](platforms.md)). Inside an ordinary container, a systemd
user session, or on macOS, the kernel refuses these caps outright.

Rather than fail the whole run over a cap the environment can't grant, this
CLI **degrades**: it prints a warning to stderr and re-runs the child in a
plain, uncapped `ProcessGroup` — "contained, but uncapped" — the same
fallback `examples/04_sandbox_resource_limits.py` uses. The no-orphan
containment guarantee still applies either way; only the specific numeric
caps are dropped. If your script depends on the cap actually being enforced,
check stderr for that warning rather than assuming it always held.

## `doctor`: preflight-diagnose the environment

`--max-memory`/`--max-processes`/`--cpu-quota` depend on kernel primitives
that are not guaranteed to be there (see above) — until now, the only way to
find out was to run `run` for real and read a warning on stderr, or catch
`ResourceLimit`/`Unsupported` from the Python API. `python -m processkit
doctor` answers the same question up front, without running anything:

```bash
python -m processkit doctor
```

```text
processkit doctor
  containment mechanism : cgroup_v2
  resource limits        : available
  verdict: OK - containment and resource limits are both available (exit 0)
```

Degraded (containment holds, but the kernel refuses at least one resource
limit — the typical container / systemd user session / non-root cgroup /
macOS case; `--max-memory`, `--max-processes`, and `--cpu-quota` are probed
**independently**, since on Linux cgroup-v2 they are separate controllers
that can be unavailable one without the others):

```text
processkit doctor
  containment mechanism : process_group
  resource limits        : unavailable --max-memory (ResourceLimit: cgroup v2 root required)
  note: --max-memory/--max-processes/--cpu-quota need a Windows Job Object or
  a Linux cgroup-v2 root; the kernel typically refuses them inside
  containers, systemd user sessions, and non-root cgroups, and always on
  macOS (docs/cli.md#resource-limits-hard-cap-or-best-effort).
  verdict: DEGRADED - containment is enforced, but resource limits are not (exit 1)
```

It never spawns a child process — only constructs (and immediately drops) a
few throwaway `ProcessGroup` instances to see what the kernel actually
grants (one for the containment mechanism, one per resource-limit
controller). `doctor` has its own exit-code namespace, deliberately disjoint
from `run`'s codes above (`124`/`125`/`126`/`127`/`128 + signal`) *and* from
argparse's own usage-error code `2` (the same code `run` itself uses for a
bad invocation) — `doctor` never returns `2` as a diagnostic verdict, so a
CI gate can always read `2` as "you called this wrong", unambiguous from any
of the codes below:

| Exit code | Meaning |
|---|---|
| `0` | Resource limits are available (containment *and* all three caps hold). |
| `1` | Containment is enforced, but at least one resource limit is not — the same "contained, but uncapped" gap `run` degrades around. |
| `2` | *(not returned by `doctor` itself)* — a usage error, e.g. an unknown flag or `doctor`'s disallowed trailing command; reserved to keep it unambiguous from a real diagnostic result. |
| `3` | Containment itself is unavailable (should not happen on any supported platform). |
| `4` | A probe raised an unexpected operational error (`OSError`/`PermissionError`, e.g. failing to read cgroup state) rather than a definitive result — the environment's actual availability could not be determined. |

`doctor` takes no flags beyond `-h`/`--help` — in particular, no trailing
`-- PROGRAM ...` (it is diagnostic-only and never runs a command).

## What you don't get here

This is a v1, deliberately minimal wrapper — reach for the Python API
directly for anything beyond it: piping several commands together
([Pipelines](pipelines.md)), restart-on-crash supervision
([Supervision](supervision.md)), interactive stdin, line-by-line streaming
([Streaming & interactive I/O](streaming.md)), or running a batch of commands
concurrently (`output_all` / `aoutput_all`). There is also no `--dry-run`
mode yet — a plausible follow-up, not implemented today. There is also no
`--output-limit` flag: stdio here is always inherited straight through to
your terminal, so there is no captured-output buffer for
`Command.output_limit(...)` to bound in the first place — that method only
matters when a caller captures output via the Python API instead.

---

Next: [Process groups](process-groups.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Cookbook](cookbook.md)
