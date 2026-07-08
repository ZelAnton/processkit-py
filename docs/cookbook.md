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

## Feed a large file to stdin without loading it into memory

```python
# Streams straight from disk to the child — no full read into Python bytes,
# so this works just as well for a multi-gigabyte dump/archive/log.
Command("psql", ["mydb"]).stdin_file("dump.sql").run()
Command("tar", ["-xf", "-"]).stdin_file("archive.tar").cwd("/tmp/extract").run()
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
    print(e.total_bytes, e.max_bytes)
```

`on_overflow` is `"drop_oldest"` (keep most recent, the default), `"drop_newest"`
(keep earliest), or `"error"` (raise `OutputTooLarge`). A `max_lines` cap bounds
only line-captured output (raw bytes have no line count), but a `max_bytes` cap
also bounds the raw stdout of `output_bytes()` / `aoutput_bytes()` (since processkit
2.1.0): over the byte ceiling it either raises `OutputTooLarge` (`on_overflow="error"`)
or keeps a bounded head/tail with `BytesResult.truncated` set.

## Stream output line by line (async)

```python
proc = await Command("my-build", ["--watch"]).astart()
async for line in proc.stdout_lines():
    print(line)
finished = await proc.afinish()   # outcome + captured stderr
```

Interleaved stdout + stderr:

```python
async for event in proc.output_events():
    print(event.stream, event.text)   # "stdout" / "stderr"
```

## Stream a log to a file and still get the captured result

`stdout_tee(path)` / `stderr_tee(path)` write the live stream to a file *and*
leave the full output in the captured result — no manual `stdout_lines()` loop,
and the one-shot verbs (`output()`, `run()`) still work:

```python
from processkit import Command

result = Command("cargo", ["build"]).stdout_tee("build.log").output()
# build.log has the live, line-by-line stream; result.stdout has the whole thing.
print(result.stdout)                 # capture is untouched — the tee is a copy
```

The file is opened **when you call the builder** (a bad path raises `OSError`
there, not at run) and truncated by default — pass `append=True` to grow an
existing log. Separate files for each stream:

```python
Command("noisy-tool").stdout_tee("out.log").stderr_tee("err.log").run()
```

The sink is a **file path**, not an arbitrary Python writer (teeing to a Python
object is a deferred feature) — if you need the lines *in Python*, loop over
`stdout_lines()` instead. See [Streaming](streaming.md#tee-output-to-a-file) for
backpressure, the no-op conditions, and write-error isolation.

## Get live progress from a synchronous run

`stdout_lines()` / `output_events()` need an event loop; `on_stdout_line(callback)`
/ `on_stderr_line(callback)` give the plain, **blocking** `.output()` / `.run()`
call the same live view — `callback` fires on every decoded line as it streams
in, not just once the run finishes:

```python
from processkit import Command

result = (
    Command("cargo", ["build", "--release"])
    .on_stdout_line(lambda line: print("build:", line))
    .output()
)
# capture is untouched — result.stdout still has the whole output.
```

Works the same on the async verbs and on a streamed run — one callback, every
path. A raising callback never derails the run (it goes to
`sys.unraisablehook` instead). See
[Streaming](streaming.md#live-per-line-callbacks) for the no-op conditions and
the one-handler-per-stream rule.

## Tear a standalone process down deterministically

A `RunningProcess` is a context manager. Exiting the block kills the process —
for a standalone `astart()` / `start()` handle that means a hard kill of its
whole private tree — even if the block raises, without waiting on Python's GC:

```python
from processkit import Command

async with await Command("flaky-server").astart() as proc:
    async for line in proc.stdout_lines():
        if "ready" in line:
            break
# proc (and its children) are reaped here

# Sync handles work too — start() is the synchronous twin of astart():
with Command("worker").start() as proc:
    ...                              # do other work
# proc torn down here
```

If you consume the handle inside the block (`proc.output()`/`.outcome()`/
`.finish()`/`.shutdown(...)`, or their `a`-prefixed async twins), exit is a
no-op.

## Talk to a process interactively (async)

```python
proc = await Command("python", ["-i"]).keep_stdin_open().astart()
stdin = proc.take_stdin()
await stdin.write_line("print(1 + 1)")
await stdin.close()                  # EOF
async for line in proc.stdout_lines():
    print(line)
await proc.aoutcome()
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
from processkit import Command, ProcessGroup, wait_until, wait_for_path, wait_for_port, wait_for_line

async with ProcessGroup() as group:
    proc = await group.astart(Command("my-server"))
    await wait_for_port("127.0.0.1", 8080, timeout=10)        # poll the port
    # or wait for a log line (a plain string is a substring-match shorthand):
    # await wait_for_line(proc.stdout_lines(), "listening", timeout=10)
    # or wait for a unix socket / pid file to appear:
    # await wait_for_path("/run/my-server.sock", timeout=10)
    # or poll any (sync or async) condition:
    # await wait_until(lambda: health_check_passes(), timeout=10, interval=0.1)
```

## Wait for a unix socket or pid file to appear

Some daemons (Docker, PostgreSQL, many others) announce readiness by creating
a file — a unix-domain socket or a pid file — rather than accepting a TCP
connection or logging a line:

```python
from pathlib import Path
from processkit import Command, ProcessGroup, wait_for_path

socket_path = Path("/run/my-daemon.sock")

async with ProcessGroup() as group:
    await group.astart(Command("my-daemon", ["--socket", str(socket_path)]))
    await wait_for_path(socket_path, timeout=10, interval=0.05)
    # socket_path now exists — connect to it
```

A `WaitTimeout` (also a `TimeoutError`) is raised if the path never appears
within `timeout` seconds — it carries `.path` for diagnostics.

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

All four accept `runner=` too, driving the whole batch through a double (see
[Test code without spawning processes](#test-code-without-spawning-processes))
instead of the real runner — no real processes spawned in a batch test.

## Wrap a CLI tool

`CliClient` binds a program to default timeout/env, so repeated calls pass only
their args:

```python
from processkit import CliClient

git = CliClient("git", default_timeout=30.0)
head = git.run(["rev-parse", "HEAD"])            # or: await git.arun([...])
clean = git.probe(["diff", "--quiet"])
```

For testable code, pass `runner=` (a `ScriptedRunner` and friends from
`processkit.testing`) to drive every verb through a double instead of the real
runner — see [Testing your code](testing.md#wrapping-a-cli-tool-cliclient).

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

`Supervisor` also accepts `runner=` — pass a `ScriptedRunner` with
`.on_sequence(...)` (fail a few times, then succeed) to test a restart/backoff
policy hermetically, with no real flaky process behind it.

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
    group.kill_all()           # immediate hard kill
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
(`wait_for_port` / `wait_for_line` / `wait_for_path` / `wait_until`) raise
builtin `TimeoutError`, so `except TimeoutError` catches both run and
readiness timeouts.

## Test code without spawning processes

Write your code against a runner, then inject a `ScriptedRunner` in tests. The
doubles live in the `processkit.testing` submodule; `Runner` is top-level:

```python
from processkit import Command, Runner
from processkit.testing import Reply, ScriptedRunner

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
`RunningProcess`. `.on_sequence(prefix, replies)` scripts a *sequence* of
replies for successive matching calls (fail once, then succeed — the shape a
retry/supervision test needs), repeating the last reply once exhausted.

`output_all`/`aoutput_all` (and their `_bytes` twins), `Supervisor`, and
`CliClient` all accept the same doubles via a `runner=` keyword, so batches,
supervised commands, and CLI wrappers are just as testable as raw `Command`
code — see [Testing your code](testing.md) for the full picture.

To capture *real* tool output once and replay it deterministically offline, use
`RecordReplayRunner` — both share the `Runner` verb surface:

```python
from processkit.testing import RecordReplayRunner

rec = RecordReplayRunner.record("cassette.json")   # records via the real runner
recorded = latest_commit(rec)                       # spawns git once, captures it
rec.save()

rep = RecordReplayRunner.replay("cassette.json")   # offline; no process spawned
assert latest_commit(rep) == recorded
```

To assert on *what* your code ran (not just its output), inject a
`RecordingRunner` spy — it replies uniformly and records every call:

```python
from processkit import Command
from processkit.testing import RecordingRunner, Reply

def deploy(runner):
    runner.run(Command("git", ["push", "--tags"]))

spy = RecordingRunner.replying(Reply.ok(""))
deploy(spy)

inv = spy.only_call()                 # the one call (raises unless exactly one)
assert inv.program == "git"
assert inv.args == ["push", "--tags"]
```

For a `--dry-run`/`--echo` mode — assert on (or print) the *rendered command
line*, with no reply to script and no output to replay — inject a
`DryRunRunner`. It never spawns, renders each command to its display-quoted
line, and returns a synthetic success:

```python
from processkit import Command
from processkit.testing import DryRunRunner

def prune(runner):
    runner.run(Command("rm", ["-rf", "build"]))

dry = DryRunRunner()
prune(dry)
assert dry.only_command() == "rm -rf build"   # nothing spawned
# dry.on_invocation(print) would echo each line live instead.
```

## Use the pytest fixtures

Installing processkit registers a pytest plugin (via a `pytest11` entry point) —
nothing to add to `conftest.py`. It hands you the doubles as fixtures, so
injecting one is a single parameter:

```python
from processkit import Command
from processkit.testing import Reply

def latest_commit(runner):
    return runner.run(Command("git", ["rev-parse", "HEAD"]))

def test_latest_commit(scripted_runner):        # fixture: a fresh ScriptedRunner
    scripted_runner.on(["git", "rev-parse"], Reply.ok("deadbeef"))
    assert latest_commit(scripted_runner) == "deadbeef"

def test_deploy_pushes_tags(recording_runner):  # fixture: a RecordingRunner spy
    recording_runner.run(Command("git", ["push", "--tags"]))
    assert recording_runner.only_call().args == ["push", "--tags"]
```

The `record_replay_runner` fixture serves a per-test cassette — replay by
default, record with `pytest --processkit-record` (or the `PROCESSKIT_RECORD`
env var / `processkit_record` ini). Point `processkit_cassette_dir` (ini) at a
committed fixtures directory to keep cassettes. Mark a test
`@pytest.mark.no_real_spawn` to make any real spawn inside it fail loudly. Full
details in [Testing your code](testing.md#the-pytest-plugin-ready-made-fixtures).

## See what processkit runs (logging)

Opt in once with `enable_logging()` and `processkit` forwards its internal run
events to Python's `logging`:

```python
import logging
from processkit import Command, enable_logging

logging.basicConfig(level=logging.DEBUG)
enable_logging()        # idempotent; returns False if another library already
                        # owns the process-global tracing subscriber

Command("git", ["rev-parse", "HEAD"]).run()
# DEBUG:processkit:child spawned program=git pid=Some(12345) mechanism=…
# DEBUG:processkit:process exited program=git outcome=Exited(0) elapsed_ms=7
```

(`mechanism` is the platform's containment — `JobObject` on Windows, a process
group / cgroup on POSIX. Fields are forwarded verbatim, so `pid` shows the core's
`Some(…)` rendering.)

Records land on the `processkit` logger (filter it like any other) — DEBUG for a
normal run, WARNING for an edge case. **argv and env are never logged** (the core
omits them — they routinely carry secrets). It's a deliberate **opt-in**: enabling
it installs a process-global subscriber and adds a little per-run overhead, so it's
a debugging/observability switch, off by default.
