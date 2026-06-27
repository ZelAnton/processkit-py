# processkit cookbook

[‹ docs index](README.md)

Task-oriented snippets — *"I want to … → do this."* Every example assumes
`from processkit import …`. Each recipe is a quick hit; for the full treatment of
any area — every knob, the error semantics, the platform fine print — follow the
links into the [guide set](README.md): [Running commands](commands.md),
[Process groups](process-groups.md),
[Streaming & interactive I/O](streaming.md), [Pipelines](pipelines.md),
[Timeouts & cancellation](timeouts-and-cancellation.md),
[Supervision](supervision.md), [Testing your code](testing.md), and
[Platform support](platforms.md).

The whole library has two parallel surfaces: a **synchronous** one (plain method
names) and an **asyncio** one (the same names with an `a` prefix). Use whichever
fits your code; they share the same types and the same no-orphan guarantee.

`ProcessStdin`'s write methods and the `stdout_lines()` / `output_events()`
iterators are **async-only**. A `RunningProcess`'s *consuming* methods
(`wait`/`finish`/`output`/`output_bytes`/`profile`/`shutdown`) are coroutines with
no `a` prefix — they exist for streaming/interactive use, so there is no
synchronous twin to disambiguate from. Its `stdout_lines()` / `output_events()` /
`take_stdin()` / `kill()` are *synchronous* setup calls (it's the
iterator/handle they return that you await). A `RunningProcess` is still usable as
a **sync or async context manager** for deterministic teardown.

---

## Run a command and capture its output

A non-zero exit is *data*, not an exception:

```python
from processkit import Command

result = Command("git", ["rev-parse", "HEAD"]).output()
print(result.stdout.strip())   # the commit hash
print(result.code)             # 0
print(result.is_success)       # True
```

Async:

```python
result = await Command("git", ["rev-parse", "HEAD"]).aoutput()
```

## Require success and just get stdout

`run()` returns trimmed stdout and raises on a non-zero exit, a timeout, or a
signal-kill:

```python
commit = Command("git", ["rev-parse", "HEAD"]).run()      # or: await ....arun()
```

## Check whether a command succeeds

```python
clean = Command("git", ["diff", "--quiet"]).probe()   # True if exit 0, False if 1
code = Command("mytool").exit_code()                   # the raw exit code
```

## Accept non-zero exit codes

Some tools use non-zero as a normal result (`grep` 1 = no match, `diff` 1 =
differs). `success_codes` **replaces** the success set (default `{0}`) — list every
code you accept:

```python
differs = not Command("diff", ["a", "b"]).success_codes([0, 1]).probe()  # 0 same, 1 differs
Command("grep", ["needle", "file"]).success_codes([0, 1]).run()          # 1 (no match) is OK
```

`success_codes` affects `run()` and `result.is_success`; `exit_code()` (raw) and
`probe()` (0/1) are unchanged.

## Set a timeout

```python
result = Command("slow-tool").timeout(5.0).output()    # result.timed_out == True on expiry
Command("slow-tool").timeout(5.0).run()                # raises Timeout on expiry

# Graceful: signal, wait, then hard-kill.
Command("server").timeout(30.0).timeout_signal("term").timeout_grace(5.0).run()
```

## Pass input on stdin

```python
out = Command("tr", ["a-z", "A-Z"]).stdin_text("hello\n").run()   # "HELLO"
Command("sha256sum").stdin_bytes(b"\x00\x01\x02").run()
```

## Set the working directory and environment

```python
Command("ls").cwd("/tmp").output()
Command("printenv", ["TOKEN"]).env("TOKEN", "secret").run()

# Set several at once, or drop an inherited one:
Command("worker").envs({"HOST": "127.0.0.1", "PORT": "8080"}).run()
Command("worker").env_remove("HTTP_PROXY").run()

# Start from an empty environment (reproducible / locked-down child), then add
# back only what you need:
Command("untrusted-tool").env_clear().env("PATH", "/usr/bin").run()
```

## Capture binary (non-UTF-8) output

`output_bytes()` returns a `BytesResult` whose `stdout` is `bytes` (stderr stays
decoded text):

```python
result = Command("convert", ["in.png", "out:-"]).output_bytes()   # or: await ....aoutput_bytes()
png = result.stdout            # bytes
print(result.code, result.is_success)
```

## Cap captured output (untrusted children)

Bound how much output is retained. To bound the parent's **memory**, cap
`max_bytes` — a `max_lines`-only cap doesn't, because one newline-free flood is a
single (unbounded) line:

```python
from processkit import Command, OutputTooLarge

# Keep only the most recent 1 MiB; older output is dropped (the default):
tail = Command("chatty-tool").output_limit(max_bytes=1024 * 1024).output()

# For an untrusted child, treat hitting the byte cap as a failure:
try:
    Command("untrusted-tool").output_limit(max_bytes=8 * 1024 * 1024, on_overflow="error").run()
except OutputTooLarge as e:
    print(e.total_bytes, e.byte_limit)
```

`on_overflow` is `"drop_oldest"` (keep most recent, the default), `"drop_newest"`
(keep earliest), or `"error"` (raise `OutputTooLarge`). The cap applies to
line-captured output; raw `output_bytes()` stdout is never line-capped — bound a
flooding child with a `timeout()` instead.

## Stream output line by line (async)

```python
proc = await Command("my-build", ["--watch"]).astart()
async for line in proc.stdout_lines():
    print(line)
finished = await proc.finish()   # outcome + captured stderr
```

Interleaved stdout + stderr:

```python
async for event in proc.output_events():
    print(event.stream, event.text)   # "stdout" / "stderr"
```

## Tear a standalone process down deterministically

A `RunningProcess` is a context manager. Exiting the block kills the process —
for a standalone `astart()` / `start()` handle that means a hard kill of its
whole private tree — even if the block raises, without waiting on Python's GC:

```python
from processkit import Command, Runner

async with await Command("flaky-server").astart() as proc:
    async for line in proc.stdout_lines():
        if "ready" in line:
            break
# proc (and its children) are reaped here

# Sync handles work too:
with Runner().start(Command("worker")) as proc:
    ...                              # do other work
# proc torn down here
```

If you consume the handle inside the block (`await proc.output()` / `.wait()` /
`.finish()` / `.shutdown(...)`), exit is a no-op.

## Talk to a process interactively (async)

```python
proc = await Command("python", ["-i"]).keep_stdin_open().astart()
stdin = proc.take_stdin()
await stdin.write_line("print(1 + 1)")
await stdin.close()                  # EOF
async for line in proc.stdout_lines():
    print(line)
await proc.wait()
```

## Contain a process tree (no orphans)

Everything started in the group — and everything those processes spawn — is
reaped when the block exits:

```python
from processkit import Command, ProcessGroup

with ProcessGroup() as group:
    group.start(Command("dev-server"))
    group.start(Command("worker"))
    # ... use them ...
# the whole tree, grandchildren included, is gone here
```

Async:

```python
async with ProcessGroup() as group:
    await group.astart(Command("dev-server"))
```

## Cancel a run and reap its tree (async)

Cancelling the awaiting task — directly, or via `asyncio.wait_for` /
`asyncio.timeout` — tears the whole tree down:

```python
task = asyncio.ensure_future(Command("long-job").aoutput())
task.cancel()                        # the process tree is reaped; CancelledError propagates
```

## Wait for a server to be ready

```python
from processkit import Command, ProcessGroup, wait_for, wait_for_port, wait_for_line

async with ProcessGroup() as group:
    proc = await group.astart(Command("my-server"))
    await wait_for_port("127.0.0.1", 8080, timeout=10)        # poll the port
    # or wait for a log line:
    # await wait_for_line(proc.stdout_lines(), lambda l: "listening" in l, timeout=10)
    # or poll any (sync or async) condition:
    # await wait_for(lambda: health_check_passes(), timeout=10, interval=0.1)
```

## Build a shell-free pipeline

```python
top = (Command("ps", ["aux"]) | Command("grep", ["python"])).run()
# or: Command(...).pipe(Command(...)).run() / .arun()

# Binary tail (e.g. `... | gzip`): capture raw bytes.
blob = (Command("cat", ["big.txt"]) | Command("gzip")).output_bytes().stdout
```

A pipeline is run-to-completion (no `astart()` streaming) and has no
`output_limit` cap of its own — bound a flooding pipeline with `timeout()`. Set
per-stage `env`/`cwd` on each `Command` before piping.

## Run many commands at once

`output_all` runs a batch with bounded concurrency (default: CPU count) and
returns each result in input order. A command that fails to *spawn* (or hits an
I/O error) appears as a `ProcessError` in its slot (a non-zero exit is still data
on a `ProcessResult`):

```python
from processkit import Command, ProcessResult, output_all   # or: await aoutput_all(...)

results = output_all([Command("git", ["-C", d, "rev-parse", "HEAD"]) for d in repos],
                     concurrency=8)
heads = [r.stdout.strip() for r in results if isinstance(r, ProcessResult) and r.is_success]
```

`concurrency` bounds how many run *at once*, but every result is retained until the
whole batch returns — peak memory is the sum of all captured outputs, not just
`concurrency` of them. For a large or untrusted batch, cap each command's output
(`.output_limit(max_bytes=…)`).

For raw-bytes output use `output_all_bytes` / `aoutput_all_bytes` — the same
batch, with each slot a `BytesResult` (or a `ProcessError`).

## Wrap a CLI tool

`CliClient` binds a program to default timeout/env, so repeated calls pass only
their args:

```python
from processkit import CliClient

git = CliClient("git", default_timeout=30.0)
head = git.run(["rev-parse", "HEAD"])            # or: await git.arun([...])
clean = git.probe(["diff", "--quiet"])
```

For testable code, inject a `Runner` / `ScriptedRunner` at the `Command` level
instead — `CliClient` always uses the real runner.

## Keep a service alive (supervision)

```python
from processkit import Command, Supervisor

outcome = Supervisor(
    Command("flaky-worker"),
    restart="on_crash",        # "always" | "never" | "on_crash"
    max_restarts=10,
    backoff_initial=0.5,
    backoff_factor=2.0,
    max_backoff=30.0,
).run()                        # or: await ....arun()
print(outcome.restarts, outcome.stopped)
```

The `stop_when=` predicate receives each run's `ProcessResult` and returns a
bool; inspect the passed result rather than calling a synchronous run verb inside
it (a nested sync call from within the supervisor's own loop is unsupported). A
predicate that raises is reported via the unraisable hook and treated as "don't
stop".

## Sandbox an untrusted tree with resource limits

Enforced by the Windows Job Object or a Linux **cgroup-v2 root**. Under a
container / systemd session / non-root cgroup the kernel forbids them and
`ResourceLimit` is raised:

```python
from processkit import Command, ProcessGroup

# Lock down the command too: empty env (allowlisting PATH), cap output, and tie
# its lifetime to ours. All cross-platform.
tool = (
    Command("untrusted-tool")
    .env_clear().inherit_env(["PATH"])
    .kill_on_parent_death()          # die with us even without explicit teardown
    .output_limit(max_bytes=8 * 1024 * 1024)
)
with ProcessGroup(max_memory=512 * 1024 * 1024, max_processes=64, cpu_quota=1.0) as group:
    group.start(tool)
    stats = group.stats()
    print(stats.active_process_count, stats.peak_memory_bytes)
```

On POSIX you can also drop privileges to run as an unprivileged user — but set
**all three** of `gid` / `groups` / `uid` (builder order doesn't matter; the
crate applies them in the kernel-correct order, supplementary groups and gid
before uid):

```python
nobody = (
    Command("untrusted-tool")
    .gid(65534).groups([65534]).uid(65534)   # run as nobody:nogroup
)
```

Setting `uid` (and `gid`) **without** `groups([...])` leaves the child holding the
*parent's* supplementary groups — often including privileged ones (`0`/root,
`docker`, `wheel`, `sudo`) when launched from root or in CI — which is a real
sandbox escape. Always clear/replace the supplementary groups with `groups([...])`
(pass the unprivileged group, or `groups([])` to drop them entirely). These
builders make the **run raise `Unsupported` on Windows** (a privilege drop is
never silently skipped), so apply them only when targeting POSIX.

## Signal, suspend, or resume a tree

```python
with ProcessGroup() as group:
    group.start(Command("worker"))
    group.suspend()            # pause the whole tree
    group.resume()
    group.signal("term")       # term | kill | int | hup | quit | usr1 | usr2
    group.terminate_all()      # immediate hard kill
```

## Handle errors

```python
from processkit import NonZeroExit, Timeout, ProcessNotFound

try:
    Command("git", ["push"]).run()
except NonZeroExit as e:
    print(e.code, e.stderr)    # structured fields, not just a message
except Timeout as e:
    print(e.timeout_seconds)
except ProcessNotFound as e:
    print("missing:", e.program)
```

Every exception derives from `ProcessError`. Three also derive from the builtin
the stdlib raises for the same condition, so familiar `except` clauses work:
`Timeout` is also a `TimeoutError` (as `asyncio.TimeoutError` is),
`ProcessNotFound` is also a `FileNotFoundError` (as `subprocess` raises), and
`PermissionDenied` is also a `PermissionError`. The async readiness helpers
(`wait_for_port` / `wait_for_line`) raise builtin `TimeoutError`, so
`except TimeoutError` catches both run and readiness timeouts.

## Test code without spawning processes

Write your code against a runner, then inject a `ScriptedRunner` in tests:

```python
from processkit import Command, Reply, Runner, ScriptedRunner

def latest_commit(runner):
    return runner.run(Command("git", ["rev-parse", "HEAD"]))

# production
latest_commit(Runner())

# test
scripted = ScriptedRunner()
scripted.on(["git", "rev-parse"], Reply.ok("deadbeef"))
assert latest_commit(scripted) == "deadbeef"
```

`Reply.ok` / `.fail` / `.timeout` / `.signalled` / `.lines` / `.pending` cover
the outcomes; `ScriptedRunner.start()` even returns a streamable scripted
`RunningProcess`.

To capture *real* tool output once and replay it deterministically offline, use
`RecordReplayRunner` — both share the `Runner` verb surface:

```python
from processkit import RecordReplayRunner

rec = RecordReplayRunner.record("cassette.json")   # records via the real runner
recorded = latest_commit(rec)                       # spawns git once, captures it
rec.save()

rep = RecordReplayRunner.replay("cassette.json")   # offline; no process spawned
assert latest_commit(rep) == recorded
```

To assert on *what* your code ran (not just its output), inject a
`RecordingRunner` spy — it replies uniformly and records every call:

```python
from processkit import Command, RecordingRunner, Reply

def deploy(runner):
    runner.run(Command("git", ["push", "--tags"]))

spy = RecordingRunner.replying(Reply.ok(""))
deploy(spy)

inv = spy.only_call()                 # the one call (raises unless exactly one)
assert inv.program == "git"
assert inv.args == ["push", "--tags"]
```
