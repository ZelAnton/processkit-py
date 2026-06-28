# Streaming & interactive I/O

[‹ docs index](README.md)

The one-shot verbs in [Running commands](commands.md) — `output()`, `run()`,
`output_bytes()` — buffer the *whole* output and hand it back at exit. That is
exactly what you want for a `git rev-parse`. It is exactly what you *don't* want
for a long-running or conversational child: a dev server you watch, a build you
follow, an interpreter you talk to. For those, `await Command(...).astart()`
returns a live `RunningProcess` you drive yourself — stream stdout as it
arrives, write stdin incrementally, probe for readiness, profile a run, and tear
the tree down deterministically.

- [Lifecycle](#lifecycle)
- [Streaming stdout](#streaming-stdout)
- [Interleaved stdout and stderr](#interleaved-stdout-and-stderr)
- [Interactive stdin](#interactive-stdin)
- [Readiness probes](#readiness-probes)
- [Live introspection and per-run telemetry](#live-introspection-and-per-run-telemetry)
- [Deterministic teardown](#deterministic-teardown)

## Lifecycle

```python
from processkit import Command, Runner

# Async setup — the handle owns a private process tree:
proc = await Command("dev-server").astart()

# Sync setup, same live handle (the consuming verbs below are still async):
proc = Command("dev-server").start()        # or: Runner().start(Command("dev-server"))
# …or hand the tree to a group that owns its fate instead of the handle:
#   proc = group.start(Command("dev-server"))   # see Process groups

proc.pid              # int | None — None once the handle is consumed
proc.elapsed_seconds  # float | None — wall time since spawn
proc.owns_group       # True for a standalone start()/astart() handle; False under a group
```

Whichever way you start it, **consume the handle exactly one way** — each of
these is an async coroutine that *spends* the handle (afterward the getters
return `None` and a second consuming verb raises):

| Verb | Returns | Use when |
| --- | --- | --- |
| `await proc.wait()` | `Outcome` | you only need the exit; output is discarded |
| `await proc.finish()` | `Finished` | **after streaming stdout** — exit + captured stderr, *without* buffering stdout |
| `await proc.output()` | `ProcessResult` | capture everything (same as the one-shot `output()`) |
| `await proc.output_bytes()` | `BytesResult` | capture, stdout as `bytes` |
| `await proc.profile(every_seconds)` | `RunProfile` | full outcome + CPU/memory samples; output discarded |
| `await proc.shutdown(grace_seconds)` | `Outcome` | graceful signal → wait → hard-kill |

`Outcome` carries `code: int | None`, `signal: int | None`, `timed_out: bool`,
and `exited_zero: bool` (literal "exit code 0" — it has no `success_codes`
context; for the command's own verdict use `ProcessResult.is_success`). There is
also a synchronous `proc.kill()` (like `subprocess.Popen.kill()`) for "stop it
now, I'll `await proc.wait()` for the code myself."

`start()`, `astart()`, and `Runner().start()` put the child in a **private group
the handle owns**: tearing the handle down kills the whole tree. The shared-group variant —
`group.start(cmd)` — gives the same handle, but the *group* controls the tree's
fate (`owns_group` is `False`); see [Process groups](process-groups.md).

## Streaming stdout

`stdout_lines()` is a synchronous setup call that returns a `StdoutLines` async
iterator of decoded lines, yielded as the child produces them — no waiting for
exit, no full-output buffering:

```python
from processkit import Command

proc = await Command("cargo", ["build", "--release"]).astart()

async for line in proc.stdout_lines():
    print("build:", line)

# The stream ended (stdout closed). finish() collects the outcome and stderr —
# stderr was drained in the background the whole time, so a noisy child could
# never block on a full pipe.
finished = await proc.finish()
if not finished.exited_zero:
    print(finished.outcome.code, finished.stderr)
```

`Finished` exposes `outcome`, `stderr: str`, `code: int | None`, and
`exited_zero: bool` (same "exit code 0" meaning as `Outcome.exited_zero`). Things
to know:

- **Call `stdout_lines()` once.** stdout is consumed a single time; a second
  `stdout_lines()` / `output_events()` call, or a non-piped stdout, raises
  rather than yielding a silently-empty stream.
- **The command's `.timeout(d)` bounds the stream** on an own-group handle: at
  the deadline the tree is killed, the pipes close, and the iterator ends — a
  streamed run can't hang past its deadline. The following `finish()` reflects
  it (`outcome.timed_out`).
- For an *ad-hoc* bound, wrap the loop in `asyncio.timeout(...)` and let the
  [teardown](#deterministic-teardown) kill the tree (shown below).
- The line counters tick live: `proc.stdout_line_count` /
  `proc.stderr_line_count` are cheap progress gauges while you stream.

*Deeper: output buffering and capture limits apply to streamed runs too —
[Running commands](commands.md).*

## Interleaved stdout and stderr

When the *interleaving* matters — a `--watch` build that prints progress to
stdout and diagnostics to stderr — `output_events()` returns an `OutputEvents`
async iterator that merges both streams in arrival order:

```python
proc = await Command("vite", ["build", "--watch"]).astart()

async for ev in proc.output_events():
    tag = "ERR" if ev.is_stderr else "out"
    print(f"[{tag}] {ev.text}")     # ev.stream is "stdout" / "stderr"
```

Each `OutputEvent` has `stream: Literal["stdout", "stderr"]`, `is_stderr: bool`,
and `text: str`. Like
`stdout_lines()`, this consumes the pipes once — pick `stdout_lines()` *or*
`output_events()`, not both.

## Interactive stdin

Conversational tools — write a request, read the response, repeat. Keep stdin
open with `keep_stdin_open()` on the `Command`, then take the writer with
`take_stdin()`:

```python
# bc evaluates each stdin line and prints the result.
proc = await Command("bc").keep_stdin_open().astart()
stdin = proc.take_stdin()          # ProcessStdin (raises if stdin wasn't kept open)
answers = proc.stdout_lines()

await stdin.write_line("2 + 2")    # writes "2 + 2\n", flushed
print("=", await anext(answers))   # 4

await stdin.write_line("6 * 7")
print("=", await anext(answers))   # 42

await stdin.close()                # send EOF — bc exits (idempotent)
finished = await proc.finish()
assert finished.exited_zero
```

`ProcessStdin` is fully awaitable: `await write(bytes)`, `write_line(str)`
(newline + flush), `flush()`, and `close()` (EOF). `take_stdin()` **raises**
`ProcessError` if the `Command` didn't `keep_stdin_open()` or the writer was
already taken — so a missing setup fails right here, not later on a `None`.

**Avoid the full-duplex deadlock.** A child's stdout pipe has a finite OS
buffer; once it fills, the child blocks *writing* stdout until something reads
it. The `bc` exchange above is safe because it interleaves one small write with
one read. But if you push a *large* interactive stdin while nothing drains the
child's stdout, the child stops reading stdin (blocked on stdout), your `write`
parks waiting for stdin buffer space, and neither side progresses. When you both
feed a sizable stdin **and** the child talks back, drain stdout from one task
while writing stdin from another:

```python
import asyncio

proc = await Command("filter-tool").keep_stdin_open().astart()
stdin = proc.take_stdin()

async def feed():
    for chunk in big_payload:
        await stdin.write(chunk)
    await stdin.close()

async def drain():
    async for line in proc.stdout_lines():
        handle(line)

await asyncio.gather(feed(), drain())
await proc.wait()
```

*Deeper: the non-interactive `stdin_text` / `stdin_bytes` sources never deadlock
— they're pumped on a background task. See [Running commands](commands.md).*

## Readiness probes

"Start a server, then use it" needs *ready*, not merely *started*. Three
free async helpers replace the arbitrary `asyncio.sleep`, each bounded by its
own deadline:

```python
from processkit import Command, wait_for, wait_for_port, wait_for_line

proc = await Command("my-server").astart()
lines = proc.stdout_lines()        # bind once — you reuse this same iterator

# 1. A line on stdout (returns the matching line):
banner = await wait_for_line(lines, lambda l: "listening on" in l, timeout=10)

# 2. A TCP port accepting connections:
await wait_for_port("127.0.0.1", 8080, timeout=10)

# 3. Any predicate — sync bool OR an awaitable (an HTTP /health, a file, …):
await wait_for(lambda: health_check_passes(), timeout=10, interval=0.1)

# ready — keep consuming from the SAME iterator:
async for line in lines:
    ...
```

Semantics, deliberately uniform:

- A probe that can't pass within its deadline raises **`TimeoutError`** (the
  builtin — so `except TimeoutError` catches both run and readiness timeouts).
- `wait_for_line` additionally raises `ProcessError` if the stdout stream ends
  *before* a match — no waiting out a 10s deadline on a dead server. It consumes
  lines up to (and including) the match; iteration may continue afterward.
  `wait_for_port` / `wait_for` don't touch the pipes at all.
- A failed probe **never kills the child** — you decide: retry, log, or tear
  down.
- `wait_for` polls every `interval` seconds (`ValueError` if `interval <= 0`). A
  sync predicate runs on the event loop, so keep it non-blocking; for blocking
  work, pass an awaitable.

*Deeper: bounding the whole run (not just the wait) is
[Timeouts & cancellation](timeouts-and-cancellation.md).*

## Live introspection and per-run telemetry

A running child reports its own resource usage live; the getters are properties
(not calls), and each returns `None` once the handle is consumed:

```python
proc = await Command("crunch").astart()
proc.pid                 # int | None
proc.elapsed_seconds     # float | None — wall time
proc.cpu_time_seconds    # float | None — user + kernel so far
proc.peak_memory_bytes   # int | None
proc.stdout_line_count   # int | None — progress while you stream
```

Or turn a whole run into a summary with `profile()`, which samples the child
every `every_seconds` until exit (the run's normal timeout still applies; like
`wait()`, the output is drained and discarded, not returned). `RunProfile` is a
**superset of `wait()`**: it carries the full `outcome` (`code` / `signal` /
`timed_out`) *and* the resource samples:

```python
proc = await Command("crunch").astart()
prof = await proc.profile(every_seconds=0.1)

print(
    f"exit={prof.code} signal={prof.signal} timed_out={prof.timed_out} "
    f"wall={prof.duration_seconds:.2f}s cpu={prof.cpu_time_seconds} "
    f"peak_rss={prof.peak_memory_bytes} "
    f"avg_cpu_cores={prof.avg_cpu_cores} ({prof.samples} samples)"
)
# prof.outcome is the same Outcome a wait() would return.
# avg_cpu_cores = cpu / wall — e.g. 1.7 ≈ 1.7 cores busy
```

These read the *child process itself*, and availability follows the platform —
full CPU/memory on Windows and Linux, `None` where the kernel doesn't account
per-process cheaply. See [Platform support](platforms.md).

*Deeper: whole-tree (grandchildren included) resource stats live on
[Process groups](process-groups.md).*

## Deterministic teardown

A `RunningProcess` is a context manager — sync and async. For a standalone
`start()` / `astart()` / `Runner().start()` handle, exiting the block hard-kills
its whole private tree (best-effort; see [Platform support](platforms.md)), even
if the block raises, without waiting on Python's GC:

```python
async with await Command("flaky-server").astart() as proc:
    async for line in proc.stdout_lines():
        if "ready" in line:
            break
# proc and its whole private tree are reaped here
```

This composes with an *ad-hoc* time bound — wrap the loop, let the exit clean up:

```python
import asyncio

async with await Command("tail", ["-f", "app.log"]).astart() as proc:
    try:
        async with asyncio.timeout(5):
            async for line in proc.stdout_lines():
                print(line)
    except TimeoutError:
        pass
# context-manager exit kills the tree on the way out
```

Two rules close the loop:

- **A consumed handle is spent.** If you consume inside the block (`await
  proc.output()` / `.wait()` / `.finish()` / `.shutdown(...)`), the exit is a
  no-op — the verb already settled the run. Afterward the getters return `None`
  and a second consuming verb raises.
- **Prefer `shutdown()` for a graceful stop.** `await proc.shutdown(grace_seconds=5)`
  signals the tree, waits up to `grace_seconds`, then hard-kills — and returns
  the `Outcome`. Reach for the context manager when you just want the tree
  *gone*; reach for `shutdown()` when the child deserves a chance to flush.

Cancellation is plain asyncio here: `task.cancel()` on the task awaiting a
consuming verb tears the tree down and propagates `CancelledError`. The full
treatment — deadlines, cooperative shutdown — is in
[Timeouts & cancellation](timeouts-and-cancellation.md).

*Deeper: drive this entire surface with no subprocess at all — a
`ScriptedRunner.start()` returns a streamable handle whose canned lines flow
through the same pump. See [Testing your code](testing.md).*

---

Next: [Process groups](process-groups.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Cookbook](cookbook.md)
