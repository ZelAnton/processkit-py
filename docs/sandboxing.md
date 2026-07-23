# Sandboxing untrusted tools

[‹ docs index](./)

Agent/LLM frameworks routinely hand a model the ability to run a "tool" it
picked itself, with arguments it generated itself — a shell command, a code
interpreter, a scraper. That tool is, by construction, less trusted than code
you wrote: it should never be able to outlive your process, exhaust the host,
or run forever. This guide is not a new capability — it is a **composition** of
pieces documented individually elsewhere: [Running commands](commands.md)
(environment, output caps), [Process groups](process-groups.md) (whole-tree
resource limits), and [Timeouts & cancellation](timeouts-and-cancellation.md)
(deadlines). It ties them into one recipe, a checklist, and — most
importantly — an honest statement of what this buys you and what it does not.

- [The threat model](#the-threat-model)
- [The recipe](#the-recipe)
  - [1. Locked-down environment](#1-locked-down-environment)
  - [2. Bounded output](#2-bounded-output)
  - [3. Whole-tree resource limits](#3-whole-tree-resource-limits)
  - [4. A timeout](#4-a-timeout)
  - [5. Teardown](#5-teardown)
- [Checklist: run an untrusted tool safely](#checklist-run-an-untrusted-tool-safely)
- [Full example](#full-example)

## The threat model

Be precise about what a `ProcessGroup` sandbox is — and is not — before
leaning on it for anything that matters.

**processkit protects against:**

- **Process-tree leakage — on Windows, and on Linux at a cgroup-v2 root.**
  Every process the tool spawns, and everything *that* spawns, dies when the
  sandbox exits — enforced by the kernel container (Job Object / cgroup v2),
  not a best-effort signal to one pid. The `process_group` backend — macOS/BSD
  always, and Linux whenever it falls back from cgroup v2 without delegation
  (see [the mechanism](process-groups.md#creating-a-group-and-the-mechanism))
  — is **not** in this category: its teardown is `killpg`, which cannot reach
  a child that called `setsid()`/`setpgid()` to leave the group before
  teardown runs — a standard daemonization trick, and exactly how hostile
  code escapes it. (An ordinary double-fork that never calls
  `setsid()`/`setpgid()` stays in the group and is still reaped.) See [the
  no-orphan guarantee and its escape](process-groups.md#tearing-down).
- **Resource exhaustion — only when the kernel container is real.**
  Whole-tree memory, process-count (fork bombs), and CPU caps are enforced by
  the kernel on Windows, and on Linux only when this process runs at a
  **cgroup-v2 root** (see
  [Resource limits](process-groups.md#resource-limits-the-sandbox)). A
  container, a systemd session/scope/service, or any non-root cgroup gets you
  nothing — the kernel's "no internal processes" rule forbids delegation
  there — same as macOS/BSD having no whole-tree limit primitive at all (see
  [Platform support](platforms.md)). The Python API fails closed:
  `ProcessGroup(...)` raises `ResourceLimit` / `Unsupported` rather than
  handing back a silently-uncapped group. `python -m processkit`, however,
  catches that and silently re-spawns the child in an **uncapped**
  `ProcessGroup()`, only warning on stderr (see [Resource limits: hard cap or
  best effort?](cli.md#resource-limits-hard-cap-or-best-effort)) — if the cap
  exists to contain hostile code, treat that stderr warning as a hard
  failure, not something to shrug off and continue. Captured output is
  bounded independently of these caps, so a chatty or malicious child cannot
  grow the parent's memory without limit (see
  [Bounding captured output](commands.md#bounding-captured-output)).
- **Runaway execution time.** A timeout kills the whole tree at a deadline —
  see [Timeouts & cancellation](timeouts-and-cancellation.md).
- **Ambient credential/environment leakage.** `env_clear()` /
  `inherit_env([...])` starts the child from nothing rather than handing it
  the parent's full environment, secrets included — see
  [Environment and sandboxing](commands.md#environment-and-sandboxing). On
  POSIX you can additionally drop privileges — see
  [Privileges and spawn flags](commands.md#privileges-and-spawn-flags).

**processkit does NOT protect against:**

- **Filesystem access.** The tool can read and write anything the OS
  permits its (possibly privilege-dropped) user to touch. processkit does not
  chroot, bind-mount, or otherwise virtualize the filesystem.
- **Network access.** No firewalling or network namespace is applied; a
  sandboxed tool can still make outbound connections unless you restrict that
  another way (a container, a network policy, an egress proxy).
- **Syscall/namespace isolation.** This is not seccomp, and not a
  PID/mount/user-namespace container. A Job Object, cgroup, or process group
  bounds a *tree*'s lifetime and resource consumption — it does not restrict
  *which* syscalls the tree may issue.
- **Vetting the tool's behavior.** processkit does not sanitize, statically
  analyze, or judge what the program does — it bounds the blast radius (time,
  memory, CPU, process count, orphaned children), not the tool's actions
  within those bounds.

**In short:** this is *resource and lifetime* containment, not *security*
isolation. If you need syscall, filesystem, or network isolation, pair
processkit with an actual sandbox — a container, a VM, gVisor, a seccomp
profile, a restricted service account — processkit composes cleanly with any
of those; it just spawns and bounds whatever program you point it at. Do not
let this guide's checklist read as "fully isolated" — it is not.

## The recipe

Compose these five ingredients, in this order, for a locked-down run of an
untrusted tool:

```python
from processkit import Command, ProcessGroup, ResourceLimit, Unsupported

tool = (
    Command("untrusted-tool")
    .env_clear().inherit_env(["PATH"])                              # 1
    .output_limit(max_bytes=8 * 1024 * 1024, on_overflow="error")    # 2
    .timeout(30.0)                                                   # 4
    .kill_on_parent_death()
)

try:
    with ProcessGroup(                                              # 3
        max_memory=512 * 1024 * 1024, max_processes=64, cpu_quota=1.0,
    ) as group:
        group.start(tool)
        ...
    # 5. the `with` block's exit reaps the whole tree here — no orphans, ever.
except (ResourceLimit, Unsupported) as exc:
    ...   # no Job Object / cgroup-v2 root here (container, non-root cgroup, macOS)
```

### 1. Locked-down environment

Start the child from nothing and allow-list only what it needs — never hand
an untrusted tool the parent's full environment (which routinely carries
credentials). Full treatment, including the ordering of `env`/`env_remove`
on top: [Environment and sandboxing](commands.md#environment-and-sandboxing).

### 2. Bounded output

Cap `max_bytes` so a chatty or malicious tool cannot grow the parent's memory
without bound (a `max_lines`-only cap does not — one newline-free flood is a
single, unbounded line). `on_overflow="error"` turns hitting the cap into a
failure rather than a silent drop, which is usually what you want for a tool
you don't trust. Full treatment: [Bounding captured output](commands.md#bounding-captured-output).

### 3. Whole-tree resource limits

`max_memory` / `max_processes` / `cpu_quota` on the `ProcessGroup` cap the
*whole tree* — not just the direct child — at the kernel level. This needs a
real container (a Windows Job Object or a Linux cgroup-v2 root); where one
isn't available, the constructor raises `ResourceLimit` rather than handing
back a silently-unbounded group. Full treatment, including the platform
matrix: [Resource limits: the sandbox](process-groups.md#resource-limits-the-sandbox).

### 4. A timeout

Untrusted code should never run unbounded. `.timeout(seconds)` kills the
whole process tree at the deadline; pair it with `.timeout_grace(...)` for a
graceful signal-then-kill if the tool might want to clean up first. Full
treatment: [Timeouts & cancellation](timeouts-and-cancellation.md).

### 5. Teardown

Prefer the context manager (`with ProcessGroup() as group: ...` / `with
Command(...).start() as proc: ...`) over any manual verb — its exit path is
the no-orphan guarantee, on every platform, even if the block raises. Never
lean on `__del__` / `atexit`: neither runs if the parent itself is hard-killed.
Full treatment: [Tearing down](process-groups.md#tearing-down).

## Checklist: run an untrusted tool safely

- [ ] Environment locked down: `env_clear()` + `inherit_env([...])` (or an
      explicit allow-list built from `env(...)` calls) — never inherit the
      parent's full environment into an untrusted child.
- [ ] Captured output bounded: `output_limit(max_bytes=...)` — a
      `max_lines`-only cap does not bound memory.
- [ ] Whole-tree resource limits set on a `ProcessGroup`: `max_memory`,
      `max_processes`, `cpu_quota` — with `ResourceLimit` / `Unsupported`
      handled where the kernel container isn't available.
- [ ] A timeout set (`Command.timeout(...)`, and `Pipeline.timeout(...)` for a
      piped chain) — untrusted code should never run unbounded.
- [ ] Teardown via a context manager, never `__del__` / `atexit`.
- [ ] `kill_on_parent_death()` set on the tool, so it dies even if your own
      process crashes before teardown runs — on POSIX this covers only the
      **direct child** (Linux `PR_SET_PDEATHSIG`; not inherited by
      grandchildren, resettable by the child itself via
      `prctl(PR_SET_PDEATHSIG, 0)`, and cleared by credential changes or by
      executing a setuid/setgid/capability-bearing binary; ordinary `execve`
      preserves it), and
      is a documented no-op on macOS/BSD. A tree-wide guarantee against a
      hard kill of your own process is Windows-only (Job Object). See
      [Privileges and spawn flags](commands.md#privileges-and-spawn-flags).
- [ ] (POSIX only, if running as a privileged user) privileges dropped with
      all three of `uid` / `gid` / `groups([...])` set together — `uid` alone
      leaves the child holding the parent's supplementary groups. For this
      incomplete-drop symptom, see
      [Troubleshooting](troubleshooting.md#privilege-drop-sets-uid-but-not-gid-and-groups).
- [ ] Read [the threat model](#the-threat-model) above — this checklist buys
      resource and lifetime containment, not syscall/filesystem/network
      isolation.

## Full example

`examples/04_sandbox_resource_limits.py` runs this recipe end to end for an
agent making a couple of tool calls in one sandboxed session: a locked-down,
output-capped, per-call-timeout command; whole-tree memory/process/CPU limits
on the shared group; and teardown on context-manager exit — degrading
gracefully to "contained, but uncapped" where the kernel container isn't
available (a container, a non-root cgroup, macOS).

```bash
python examples/04_sandbox_resource_limits.py
```

---

Next: [Process groups](process-groups.md) · [Running commands](commands.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Cookbook](cookbook.md) · [Platform support](platforms.md)
