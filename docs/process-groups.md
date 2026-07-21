# Process groups

[‹ docs index](README.md)

A `ProcessGroup` ties the lifetime of a whole child-process **tree** to a
context manager: every process you start in the group — and everything *those*
processes spawn — is killed when the block exits. A returning, raising, or
cancelled owner never leaks subprocesses, because the kernel object that
contains the tree (a Windows Job Object, a Linux cgroup, or a POSIX process
group) catches grandchildren you never knew about.

You rarely need an explicit group for one-shot runs: a standalone
`Command(...).astart()` / `Runner().start(...)` handle already owns a *private*
tree that its own context manager reaps (see [Running commands](commands.md)).
Reach for `ProcessGroup` when several children should **share one fate**, or
when you want the group verbs below — whole-tree signals, suspend/resume,
member listing, resource limits, and stats.

- [Creating a group and the mechanism](#creating-a-group-and-the-mechanism)
- [Spawning into the group](#spawning-into-the-group)
- [Tearing down](#tearing-down)
- [Signalling the whole tree](#signalling-the-whole-tree)
- [Suspending and resuming](#suspending-and-resuming)
- [Inspecting members](#inspecting-members)
- [Resource limits: the sandbox](#resource-limits-the-sandbox)
- [Stats](#stats)
- [Live monitoring](#live-monitoring)

## Creating a group and the mechanism

The constructor is keyword-only. With no arguments you get a plain container
with the default graceful-shutdown grace (a short window, then escalate to a
hard kill):

```python
from processkit import ProcessGroup

with ProcessGroup() as group:
    print(group.mechanism)   # "job_object" | "cgroup_v2" | "process_group"
```

`mechanism` reports what you actually got at runtime. On a Linux host without
cgroup-v2 delegation it quietly reads `"process_group"` instead of
`"cgroup_v2"` — the same fallback that decides which features below are
available. See [Platform support](platforms.md) for the per-OS matrix; the
short version is *Windows strongest, macOS weakest.*

Tune the teardown timing at construction:

```python
group = ProcessGroup(shutdown_grace=10.0, escalate_to_kill=True)
```

`shutdown_grace` is a float of **seconds**. The resource-limit keywords
(`max_memory`, `max_processes`, `cpu_quota`) are covered under
[Resource limits](#resource-limits-the-sandbox).

## Spawning into the group

`start()` (sync) and `astart()` (async) put a full `Command` — capture,
streaming, timeouts, all of it — into the **shared** group and hand back a
`RunningProcess`:

```python
from processkit import Command, ProcessGroup

with ProcessGroup() as group:
    server = group.start(Command("dev-server"))
    worker = group.start(Command("worker"))
    # ... use them ...
# both, and every grandchild they forked, are gone here
```

```python
async with ProcessGroup() as group:
    server = await group.astart(Command("dev-server"))
```

A child started into a shared group does **not** own a private tree: its
`owns_group` is `False`. That distinction matters for teardown. Exiting *that
child's* own context manager (or dropping it) kills only that one child; it is
the **group's** teardown that reaps the whole tree.

```python
with ProcessGroup() as group:
    proc = group.start(Command("worker"))
    assert proc.owns_group is False
    with proc:                # this block kills only `proc`...
        ...
    # ...but other group members keep running until the group exits
```

The streaming and consuming surface of the returned `RunningProcess`
(`stdout_lines()`, `take_stdin()`, `outcome()`/`aoutcome()`, `finish()`/
`afinish()`, …) is documented in [Streaming & interactive I/O](streaming.md).

Since a `ProcessGroup` is itself a runner, you can also run a one-shot command
as a shared member without ever getting a `RunningProcess` handle back — the
same verb surface `Runner`/`ScriptedRunner`/… expose:

```python
with ProcessGroup() as group:
    result = group.output(Command("check-something"))   # a non-zero exit is data
    version = group.run(Command("tool", ["--version"]))  # requires a zero exit
```

## Tearing down

Prefer the context manager — its exit path is the no-orphan guarantee. For
explicit control you also have three verbs:

| Verb | What it does |
|---|---|
| `with` / `async with` exit | **Graceful** teardown of the whole tree — the same as `shutdown()` (signal → wait up to `shutdown_grace` → hard-kill survivors if `escalate_to_kill`). Always on, even if the block raises. |
| `group.kill_all()` | Immediate hard kill of the whole tree, mid-flight; idempotent. |
| `group.shutdown()` / `await group.ashutdown()` | **Graceful**: signal → wait up to `shutdown_grace` → hard-kill survivors if `escalate_to_kill`. |

```python
group = ProcessGroup(shutdown_grace=5.0, escalate_to_kill=True)
with group:
    group.start(Command("my-service"))
    ...
    group.shutdown()    # SIGTERM, give it 5s to flush, then SIGKILL stragglers
```

```python
async with ProcessGroup(shutdown_grace=5.0) as group:
    await group.astart(Command("my-service"))
    await group.ashutdown()
```

A child that handles `SIGTERM` and exits ends the grace **early** —
`shutdown` / `ashutdown` returns as soon as the tree is empty, not after the
full timeout. Use `kill_all()` when you want the tree gone *now* with no
grace at all.

**The no-orphan guarantee and its platform asymmetry.** The `with` /
`async with` exit path reaps the tree on every platform, and so does cancelling
an awaited run (`task.cancel()`, `asyncio.wait_for`, `asyncio.timeout`).
**Surviving a hard kill of the Python parent itself** — `SIGKILL`,
`os._exit` — is a *Windows-only* property, enforced by the kernel's
`KILL_ON_JOB_CLOSE`; on Linux and macOS teardown runs from the normal exit
path, which a hard kill skips. There is **no** Python destructor guarantee:
`__del__` and `atexit` do not run under `SIGKILL` / `os._exit`, so never lean on
them. Lean on the context manager. Full matrix in
[Platform support](platforms.md).

**The `process_group` backend's `setsid()`/`setpgid()` escape.** On
macOS/BSD, and on Linux whenever the group falls back from `cgroup_v2` to
`process_group` (no cgroup-v2 delegation — see
[the mechanism](#creating-a-group-and-the-mechanism)), every teardown path
above — the graceful `with`-exit *and* `kill_all()` — reaches the tree via
`killpg` against the POSIX process group. A child that calls `setsid()` or
`setpgid()` to leave that group before teardown runs is no longer a member,
so `killpg` does not reach it: it survives even a normal, non-crashing
`with`-exit, not just a hard kill of the parent. This is the standard trick
hostile code uses to outlive a sandbox; an ordinary double-fork that never
calls `setsid()`/`setpgid()` stays in the group and is reaped normally. The
Windows Job Object and the Linux cgroup-v2 backend have no such escape —
membership there is kernel-tracked, not session-based, so a descendant
cannot opt itself out. If a child appears to have escaped, see
[Troubleshooting](troubleshooting.md#a-child-escaped-a-posix-process-group-with-setsid).

*Deeper: keeping a service alive across crashes is [Supervision](supervision.md).*

## Signalling the whole tree

`signal(name)` broadcasts a POSIX signal to every member. Accepted names are
`"term"`, `"kill"`, `"int"`, `"hup"`, `"quit"`, `"usr1"`, `"usr2"`:

```python
with ProcessGroup() as group:
    group.start(Command("my-server"))
    group.signal("hup")     # "reload your configuration"
    group.signal("usr1")    # whatever the tool defines
```

`signal("kill")` and `kill_all()` take the same *atomic* whole-tree kill
path, so they cannot miss a process forked mid-broadcast. Every other signal is
a best-effort per-member broadcast against a tree that may be forking at that
instant.

Signals are POSIX-real on Linux, macOS, and BSD. On **Windows** only `"kill"`
maps onto the Job Object terminate; **every other name, including `"term"`,
raises `Unsupported`.** Catch it if you target multiple platforms:

```python
from processkit import Unsupported

try:
    group.signal("hup")
except Unsupported:
    ...   # no SIGHUP on this platform — reload some other way
```

## Suspending and resuming

Freeze a tree (to snapshot it, to starve a runaway while you investigate, to
pause background work), then thaw it:

```python
with ProcessGroup() as group:
    group.start(Command("cpu-hog"))
    group.suspend()     # the whole tree stops consuming CPU
    # ... inspect, snapshot, wait for the user ...
    group.resume()
```

Suspend/resume work on every current backend (anywhere a container exists — all
supported platforms). Two gotchas bite in practice:

- **Resume before starting new work.** Under the cgroup mechanism a child
  spawned into a *frozen* group starts frozen, and `start()` may not return
  until you `resume()`.
- **Resume before a graceful shutdown.** `shutdown` opens with a signal a
  frozen tree can't act on, so it would wait out the whole `shutdown_grace`.
  An immediate hard kill (`kill_all()` or `signal("kill")`) works on a frozen
  tree regardless; the `with`-exit is itself a graceful shutdown, so it carries
  the same caveat — `resume()` first.

## Inspecting members

`members()` returns the live member pids as a point-in-time snapshot:

```python
with ProcessGroup() as group:
    group.start(Command("worker-a"))
    group.start(Command("worker-b"))
    print(group.members())   # e.g. [4123, 4124]
```

What "members" means depends on the mechanism. On Windows and the Linux cgroup
backend it is the **whole tree** — every descendant pid. On the POSIX
process-group backends (macOS/BSD, Linux without cgroup) it is the tracked
group *leaders*, one pid per started child; their descendants are contained but
not enumerated. A tree that is forking races the snapshot.

`members_info()` returns that **same** set of members — the same point-in-time
snapshot, the same mechanism-dependent matrix above — but carries each pid in a
`MemberInfo` alongside best-effort metadata (parent pid, image name, start time):

```python
with ProcessGroup() as group:
    group.start(Command("worker"))
    for member in group.members_info():
        print(member.pid, member.ppid, member.exe_name, member.start_time)
```

Every field beyond `pid` is `None` wherever the platform can't report it —
`ppid`/`exe_name`/`start_time` are populated on Windows, Linux, and macOS, and
are all `None` on the BSDs (no wired-up per-process reader). Values are never
fabricated: a member that exits mid-snapshot is simply omitted rather than
reported with invented fields.

`start_time` is **not** a wall-clock timestamp — it is an *opaque per-process
identity token* whose unit and epoch are platform-specific (a Windows creation
`FILETIME`, Linux clock ticks since boot, macOS microseconds since the Unix
epoch). Do not interpret it or compare it across platforms; its sole use is
pairing with `pid` — two snapshots whose `pid` *and* `start_time` both match name
the same process instance — to tell a recycled pid apart from the original. And,
like the crate's `tracing` output, `MemberInfo` deliberately never carries the
raw command line or environment on any platform: an argv routinely holds
secrets, and redaction is a policy the consumer must own.

## Resource limits: the sandbox

The three limit keywords turn the group into a sandbox. They are a property of
the group, set once at construction and enforced by the same kernel object that
contains the tree:

```python
from processkit import Command, ProcessGroup

with ProcessGroup(
    max_memory=512 * 1024 * 1024,   # bytes, whole tree
    max_processes=64,               # fork-bomb ceiling
    cpu_quota=1.0,                  # one core (0.5 = half, 2.0 = two)
) as group:
    group.start(Command("untrusted-tool"))
```

`cpu_quota` is a fraction of a **single** core. On Windows it is converted
against the host CPU count and is approximate (a CPU-*rate* cap, not a hard
quota); on the Linux cgroup it is exact.

Limits need a **real container** — a Windows Job Object or a Linux **cgroup-v2
root**. If a requested cap can't be enforced, the constructor raises
`ResourceLimit` rather than handing you a silently-unbounded group:

```python
from processkit import ResourceLimit

try:
    group = ProcessGroup(max_memory=256 * 1024 * 1024)
except ResourceLimit:
    ...   # no Job Object / cgroup-v2 root here — limits unavailable
```

On Linux this requires the process to run at the real cgroup-v2 root. The
kernel's "no internal processes" rule forbids it under a container, a systemd
session/scope/service, or any non-root cgroup — so an ordinary container fails
too. macOS/BSD and the Linux process-group fallback have **no** whole-tree
limits at all. The prerequisites live in [Platform support](platforms.md); pair
limits with a locked-down `Command` (`env_clear().inherit_env(["PATH"])`,
`output_limit(...)`) per the [Cookbook](cookbook.md). For a quick diagnosis of a
`ResourceLimit` failure in those environments, see
[Troubleshooting](troubleshooting.md#resourcelimit-under-docker-systemd-or-a-non-root-cgroup).

## Stats

`stats()` returns a point-in-time `ProcessGroupStats` snapshot:

```python
with ProcessGroup() as group:
    group.start(Command("worker"))
    snap = group.stats()
    print(snap.active_process_count)    # int
    print(snap.peak_memory_bytes)       # int | None
    print(snap.total_cpu_time_seconds)  # float | None
```

`active_process_count` is always available. `peak_memory_bytes` and
`total_cpu_time_seconds` are populated only where the kernel accounts for the
whole tree (Windows, Linux cgroup); on the process-group backends they stay
`None` and only the count is reported.

For a single run's end-to-end resource profile, use `RunningProcess.profile()`,
covered in [Streaming & interactive I/O](streaming.md).

## Live monitoring

`stats()` alone is a snapshot you poll yourself. `sample_stats(group, every)`
turns that into a periodic series — a pure-Python async generator (no
`ProcessGroup` verb of its own) built directly on `stats()`, for a dashboard,
adaptive throttling, or an alert as the tree approaches a resource cap:

```python
from processkit import Command, ProcessGroup, sample_stats

async with ProcessGroup(max_memory=512 * 1024 * 1024) as group:
    await group.astart(Command("untrusted-tool"))
    async for snap in sample_stats(group, every=1.0):
        print(snap.active_process_count, snap.peak_memory_bytes)
        if snap.active_process_count == 0:
            break
```

The first snapshot is taken immediately, then one every `every` seconds, for as
long as you keep consuming — there is no overall deadline; `break` out of the
loop (or otherwise stop iterating) when you're done.

**Fused, and louder than the crate's stream.** The crate's `StatsSampler`
swallows the error on the first failed sample and the series just ends
silently. This generator instead lets `stats()`'s own exception (e.g.
`ProcessError` — "ProcessGroup is already closed" — once the group has torn
down) propagate out of the `async for` untouched, so you learn *why* the
series stopped instead of just that it did. That failure still ends the
series for good: the exception is never retried, and — because it is an
ordinary Python async generator — a further iteration attempt afterwards
raises `StopAsyncIteration` rather than calling `stats()` again. If the group
is already closed/invalid before you ever start iterating, that same
exception surfaces on the very first `async for` step, not as a silently
empty series.

*Deeper: testing code that drives a group without spawning is
[Testing your code](testing.md).*

---

Next: [Streaming & interactive I/O](streaming.md) ·
[Supervision](supervision.md) · [Platform support](platforms.md) ·
[Cookbook](cookbook.md)
