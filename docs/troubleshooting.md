# Troubleshooting & FAQ

[‹ docs index](./)

Use this page to map a symptom to the guide that explains the full platform or
runtime contract. The entries are deliberately short; follow the links for the
complete behavior and examples.

## `ResourceLimit` under Docker, systemd, or a non-root cgroup

On Linux, whole-tree limits require a real cgroup-v2 root; the kernel's "no
internal processes" rule rejects the setup from a container, systemd
session/scope/service, or another non-root cgroup. Check whether the process is
at the cgroup root or has delegated controllers, then see [Resource limits: the
sandbox](process-groups.md#resource-limits-the-sandbox) and [Platform support](platforms.md#resource-limits-processgroupmax_memory-max_processes-cpu_quota).

## `Unsupported` from `signal("term")` on Windows

Windows Job Objects can terminate the whole job, but they do not deliver POSIX
signals, so only `signal("kill")` is supported and `"term"` raises
`Unsupported`. Use a platform-appropriate shutdown path; see [Signalling the
whole tree](process-groups.md#signalling-the-whole-tree) and [Platform
support](platforms.md#signals-suspendresume-stats).

## A child escaped a POSIX process group with `setsid()`

`ProcessGroup.mechanism` honestly reports `"process_group"` when Linux cannot
use cgroup-v2 delegation and falls back to a POSIX process group. A child that
calls `setsid()` or `setpgid()` leaves that group, so `killpg` cannot reach it;
see [Tearing down](process-groups.md#tearing-down) for the escape boundary and
the stronger backends.

## `a`-prefixed verbs report no running asyncio event loop

The async surface is asyncio-native, so `aoutput()`, `arun()`, and related
verbs need an active asyncio loop; native trio, curio, and anyio on trio do not
provide one. Use asyncio/uvloop or the synchronous surface as appropriate; see
[Async runtimes & event loops](event-loops.md#support-at-a-glance).

## `record_replay_runner` cassette not found

The pytest fixture replays by default, so a missing cassette means it has not
been recorded at the expected fixture path. Run pytest once with
`--processkit-record` and configure `processkit_cassette_dir` if the cassette
must persist; see [Record/replay cassettes:
RecordReplayRunner](testing.md#recordreplay-cassettes-recordreplayrunner).

## Privilege drop sets `uid` but not `gid` and `groups`

Dropping only `uid` leaves the inherited supplementary groups in place, which
can retain privileges you meant to remove. Set `groups`, then `gid`, then `uid`;
see [Sandboxing untrusted tools](sandboxing.md) and [Privileges and spawn
flags](commands.md#privileges-and-spawn-flags).

## The parent is hard-killed with `SIGKILL` or `os._exit`

Normal context-manager teardown cannot run after a hard kill; only Windows Job
Objects retain a kernel-enforced whole-tree cleanup when their last handle
closes. Linux and macOS/BSD are best-effort in that case, so design the child
lifetime accordingly; see [Tearing down](process-groups.md#tearing-down) and
[Platform support](platforms.md#teardown-the-no-orphan-guarantee).
