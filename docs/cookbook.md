# processkit cookbook

Task-oriented snippets — *"I want to … → do this."* Every example assumes
`from processkit import …`.

The whole library has two parallel surfaces: a **synchronous** one (plain method
names) and an **asyncio** one (the same names with an `a` prefix). Use whichever
fits your code; they share the same types and the same no-orphan guarantee.

`ProcessStdin` and the `stdout_lines()` / `output_events()` iterators are
**async-only**, as are a `RunningProcess`'s I/O and await methods
(`take_stdin`/`wait`/`finish`/`output`/`shutdown`): they exist for streaming and
interactive use, so they are coroutines with no `a` prefix (there is no
synchronous twin to disambiguate from). A `RunningProcess` is still usable as a
**sync or async context manager** for deterministic teardown.

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

## Set a timeout

```python
result = Command("slow-tool").timeout(5.0).output()    # result.timed_out == True on expiry
Command("slow-tool").timeout(5.0).run()                # raises Timeout on expiry
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

with ProcessGroup(memory_max=512 * 1024 * 1024, max_processes=64, cpu_quota=1.0) as group:
    group.start(Command("untrusted-tool"))
    stats = group.stats()
    print(stats.active_process_count, stats.peak_memory_bytes)
```

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

Every exception derives from `ProcessError`. Two also derive from the builtin
the stdlib raises for the same condition, so familiar `except` clauses work:
`Timeout` is also a `TimeoutError` (as `asyncio.TimeoutError` is) and
`ProcessNotFound` is also a `FileNotFoundError` (as `subprocess` raises). The
async readiness helpers (`wait_for_port` / `wait_for_line`) raise builtin
`TimeoutError`, so `except TimeoutError` catches both run and readiness timeouts.

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
