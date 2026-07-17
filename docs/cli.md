# Command-line usage

[‹ docs index](README.md)

Most of this package's value lives behind Python code — but sometimes the
caller is a shell script or a CI step, not a Python program. `python -m
processkit run` is a thin CLI wrapper over `Command` / `ProcessGroup` for
exactly that case: kill-on-exit containment and resource limits for a single
shell command, with no Python to write.

- [Basic usage](#basic-usage)
- [Flags](#flags)
- [Exit codes](#exit-codes)
- [Resource limits: hard cap or best effort?](#resource-limits-hard-cap-or-best-effort)
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
