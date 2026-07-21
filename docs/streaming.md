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
- [Tee output to a file](#tee-output-to-a-file)
- [Live per-line callbacks](#live-per-line-callbacks)
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

# Sync setup, same live handle (the consuming verbs below have a sync twin too):
proc = Command("dev-server").start()        # or: Runner().start(Command("dev-server"))
# …or hand the tree to a group that owns its fate instead of the handle:
#   proc = group.start(Command("dev-server"))   # see Process groups

proc.pid              # int | None — None once the handle is consumed
proc.elapsed_seconds  # float | None — wall time since spawn
proc.owns_group       # True for a standalone start()/astart() handle; False under a group
```

Whichever way you start it, **consume the handle exactly one way** — each of
these comes in a sync/async pair (like everywhere else in this library) and
*spends* the handle (afterward the getters return `None` and a second
consuming verb raises):

| Verb pair | Returns | Use when |
| --- | --- | --- |
| `proc.outcome()` / `await proc.aoutcome()` | `Outcome` | you only need the exit; output is discarded |
| `proc.finish()` / `await proc.afinish()` | `Finished` | **after streaming stdout** — exit + captured stderr, *without* buffering stdout |
| `proc.output()` / `await proc.aoutput()` | `ProcessResult` | capture everything (same as the one-shot `output()`) |
| `proc.output_bytes()` / `await proc.aoutput_bytes()` | `BytesResult` | capture, stdout as `bytes` |
| `proc.profile(every_seconds)` / `await proc.aprofile(every_seconds)` | `RunProfile` | full outcome + CPU/memory samples; output discarded |
| `proc.shutdown(grace_seconds)` / `await proc.ashutdown(grace_seconds)` | `Outcome` | graceful signal → wait → hard-kill |

(`outcome`/`aoutcome`, not `wait`/`await` — `await` is a reserved word, so it
can't be a method name.) Use whichever half of a pair matches your calling
code — the sync half blocks the calling thread (the same interruptible driver
as `Command.output()`), the async half is a coroutine.

`Outcome` carries `code: int | None`, `signal: int | None`, `timed_out: bool`,
and `exited_zero: bool` (literal "exit code 0" — it has no `success_codes`
context; for the command's own verdict use `ProcessResult.is_success`). There is
also a synchronous `proc.kill()` (like `subprocess.Popen.kill()`) for "stop it
now, I'll read the code myself with `proc.outcome()` / `await proc.aoutcome()`."

`start()`, `astart()`, and `Runner().start()` put the child in a **private group
the handle owns**: tearing the handle down kills the whole tree, and
`shutdown()`/`ashutdown()` work on it — named to match
`ProcessGroup.shutdown()`/`ashutdown()`. The shared-group variant —
`group.start(cmd)` — gives the same handle, but the *group* controls the
tree's fate (`owns_group` is `False`), so `shutdown()`/`ashutdown()` raise
`Unsupported` there; tear such a child down via the group (or `kill()`). See
[Process groups](process-groups.md).

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
finished = await proc.afinish()
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

## Tee output to a file

Sometimes you want *both*: a live log written somewhere **and** the captured
result in hand — a build whose output tails into `build.log` while you still get
the final `ProcessResult` to inspect. `stdout_tee(sink)` / `stderr_tee(sink)` do
that in one line, with no manual loop over `stdout_lines()`:

```python
from processkit import Command

result = Command("cargo", ["build", "--release"]).stdout_tee("build.log").output()

# The file received the live stream, line by line, as it was produced …
assert open("build.log").read().startswith("   Compiling")
# … and capture is untouched — the tee does not steal output from the result.
print(result.stdout)          # the full captured stdout, same as without the tee
```

Each decoded line is written to the sink as it lands, followed by a `\n` (a CRLF
terminator is normalized to `\n`). The tee runs *independently* of capture, so
`result.stdout` still holds the whole output. It also works with the streaming
verbs — `start()` + `stdout_lines()` / `output_events()` — not just the one-shot
capture verbs; the same lines flow to the iterator and the sink.

The sink can also be a **Python writer** — any object with a `write()` method
(`io.StringIO`, `sys.stderr`, a text-mode file, a logger wrapper) — to mirror
the child's output straight into your own console, buffer, or logger while still
capturing it:

```python
import io
from processkit import Command

buf = io.StringIO()
result = Command("cargo", ["build", "--release"]).stdout_tee(buf).output()

# Each decoded line (plus a "\n") was passed to buf.write() as a str, live …
assert buf.getvalue().startswith("   Compiling")
# … and capture is still whole — the object is only mirrored to, never drained.
print(result.stdout)
```

Things to know:

- **A file path or a Python writer.** The sink is either a filesystem path (`str`
  or `os.PathLike[str]`) or an object with a callable `write()` — the two are
  told apart by whether the argument exposes `write` (neither `str` nor
  `pathlib.Path` does). A writer is a **text** sink: each decoded line is passed
  to `write()` as a `str`, so pass a text-mode object (`io.StringIO`,
  `sys.stderr`, a file opened in text mode, a logger wrapper), not a binary one
  (`io.BytesIO`, a `"wb"` file) whose `write(str)` would raise `TypeError`. The
  writer is **not** owned — it is never closed for you, so you keep using your
  `sys.stderr` / open file after the run. `append` tunes only how a *file path*
  is opened (see below); passing `append=True` with a writer raises `ValueError`
  rather than being silently ignored.
- **A file is opened now, at build time.** `stdout_tee(path)` opens the file
  the moment you call it (the crate takes a concrete sink, not a lazy factory),
  **not** when the command runs. So an unopenable path — a missing parent
  directory, a directory, a permission denial — raises the matching `OSError`
  (`FileNotFoundError`, `IsADirectoryError`, `PermissionError`, …) right at the
  builder call, before any run verb. (A writer object is used as-is, so nothing
  is opened — this timing applies only to the path form.)
- **Truncate by default, or append (file paths).** A file sink is created if
  absent and truncated; pass `append=True` to open it in append mode instead (to
  grow an existing log). Because the open handle is shared across re-runs of the
  *same* built `Command` (retries, a reused command, `Supervisor` incarnations),
  those sequential runs **append** to the one file with no delimiter, and
  concurrent clones (pipeline stages) **interleave**. For per-run separation,
  build a fresh `Command` (a fresh path) per run.
- **A slow sink applies backpressure, it does not block the runtime.** The tee
  write is awaited on the capture pump, so a slow disk slows the pump, fills the
  OS pipe, and makes the child block on its next write — rather than stalling the
  event loop. A Python writer gets the same treatment: each `write()` is
  dispatched to the runtime's blocking pool (re-acquiring the GIL there), so even
  a `write()` that *sleeps* applies backpressure without blocking the async event
  loop or deadlocking the runtime. A sink that blocks *forever* (not merely slow)
  parks the pump until teardown; a plain file or a prompt writer never does this.
- **A tee write error is isolated.** If a write to the sink fails mid-run, the
  tee is disabled for the rest of the run and a warning is emitted (under
  [`enable_logging()`](cookbook.md#see-what-processkit-runs-logging)) — the run
  itself and its captured result are unaffected, never broken by the sink. For a
  Python writer, a `write()` (or `flush()`) exception is additionally reported
  via `sys.unraisablehook`, so it is visible even without `enable_logging()`
  (and catchable in a test via a custom hook).
- **No-op unless the line pump runs.** The tee fires from the line-capture pump,
  so it is inert under `stdout("inherit")` / `stdout("null")` (no pump) and under
  `output_bytes()` (raw capture, no line pump). Reach for it with the line verbs
  — `output()` / `aoutput()`, `run()`, or `start()` + `stdout_lines()` /
  `output_events()`.

## Live per-line callbacks

`stdout_lines()` / `output_events()` are async-only — they hand back an async
iterator, so they need an event loop to drive. `on_stdout_line(callback)` /
`on_stderr_line(callback)` give the **synchronous** surface the same live
observation: `callback` runs on every decoded line *as it is produced*, even
while `.output()` / `.run()` is still blocking:

```python
from processkit import Command

def log_line(line: str) -> None:
    print("build:", line)

result = Command("cargo", ["build", "--release"]).on_stdout_line(log_line).output()
# "build: ..." printed live, one call per line, while output() was still blocking.
print(result.stdout)   # capture is untouched — the callback observes, it doesn't consume.
```

They work identically on the async verbs and on a streamed run (`start()`/
`astart()` + `stdout_lines()` / `output_events()`) — one callback, every path;
adding them does not turn the sync surface async-only, and does not replace the
streaming iterators (which stay the only way to *consume* lines one at a time
from Python — a callback only *observes*).

Things to know:

- **At most one handler per stream.** A repeat call **replaces** the previous
  one (builder semantics, like `timeout()`); compose inside a single Python
  callable to fan out to more than one observer.
- **A raising callback never derails the run.** An exception raised inside
  `callback` is reported via `sys.unraisablehook` (visible on stderr, or
  catchable in a test via a custom `sys.unraisablehook`) instead of
  propagating — the run and its captured result are unaffected either way.
- **No-op unless that stream's line pump runs**, same family as
  `stdout_tee`/`stderr_tee`: `on_stdout_line` is inert under
  `stdout("inherit")` / `stdout("null")` and under `output_bytes()` (stdout is
  captured raw there, bypassing the line pump). `on_stderr_line` is inert under
  `stderr("inherit")` / `stderr("null")` — but **not** under `output_bytes()`:
  that verb only bypasses the *stdout* line pump, stderr keeps decoding through
  it exactly as under `output()`.
- **Runs independently of `stdout_tee`/`stderr_tee`.** Set both and both fire
  per line — a callback and a file tee are not mutually exclusive.

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
finished = await proc.afinish()
assert finished.exited_zero
```

`ProcessStdin` is fully awaitable: `await write(bytes)`, `write_line(str)`
(newline + flush), `send_control(str)`, `flush()`, and `close()` (EOF).
`send_control()` accepts exactly one recognized control character and writes
the mapped control byte to the child's stdin pipe: for example,
`await stdin.send_control("c")` writes Ctrl-C (`\x03`) and
`await stdin.send_control("d")` writes Ctrl-D (`\x04`). Invalid input raises
`ValueError`.

This is a byte in a normal pipe, not a terminal signal. It only affects
children that read and interpret that byte from stdin; real terminal semantics
such as SIGINT/SIGTSTP delivery require a pseudoterminal, which `processkit`
does not provide yet.

`take_stdin()` **raises** `ProcessError` if the `Command` didn't
`keep_stdin_open()` or the writer was already taken — so a missing setup fails
right here, not later on a `None`.

**Not the same as `inherit_stdin()`.** `keep_stdin_open()` + `take_stdin()` hands
you a **crate-managed pipe** you write to from Python — the crate mediates every
byte. [`inherit_stdin()`](commands.md#standard-input) is the opposite: it gives
the child the parent's **real** stdin (the actual terminal / file / pipe this
process was launched with), so the crate touches nothing and there is no writer
to take (`take_stdin()` returns nothing there, exactly as for a run that never
kept stdin open). Reach for `inherit_stdin()` when a child must talk to the real
terminal — `git commit` opening `$EDITOR`, a password prompt — and for the
byte-by-byte conversational exchange above, `keep_stdin_open()`. The two are
**mutually exclusive**: setting both is rejected as a `ProcessError` at launch
(not when you build the `Command`).

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
await proc.aoutcome()
```

*Deeper: the non-interactive `stdin_text` / `stdin_bytes` sources never deadlock
— they're pumped on a background task. See [Running commands](commands.md).*

## Readiness probes

"Start a server, then use it" needs *ready*, not merely *started*. Five
free async helpers replace the arbitrary `asyncio.sleep`, each bounded by its
own deadline:

```python
from processkit import (
    Command,
    wait_until,
    wait_for_path,
    wait_for_port,
    wait_for_http,
    wait_for_line,
)

proc = await Command("my-server").astart()
lines = proc.stdout_lines()        # bind once — you reuse this same iterator

# 1. A line on stdout (returns the matching line) — a plain string is a
#    substring-match shorthand for a str-yielding iterator:
banner = await wait_for_line(lines, "listening on", timeout=10)
# …or a callable predicate, which also works over any async iterator, not
# just str lines (e.g. `proc.output_events()`'s OutputEvent items):
banner = await wait_for_line(lines, lambda l: "listening on" in l, timeout=10)

# 2. A TCP port accepting connections:
await wait_for_port("127.0.0.1", 8080, timeout=10)

# 3. An HTTP endpoint answering with an acceptable status (2xx by default) — a
#    stronger signal than the port alone, which a warming-up server accepts
#    while still replying 503. `expected_status` takes a set/range or a predicate:
await wait_for_http("127.0.0.1", 8080, "/health", timeout=10)

# 4. A path appearing on the filesystem (a unix socket, a pid file, …):
await wait_for_path("/run/my-server.sock", timeout=10)

# 5. Any predicate — sync bool OR an awaitable (a DB ping, …):
await wait_until(lambda: health_check_passes(), timeout=10, interval=0.1)

# ready — keep consuming from the SAME iterator:
async for line in lines:
    ...
```

(Named `wait_until`, not `wait_for` — the latter would collide with
`asyncio.wait_for`, whose semantics differ: it bounds one *awaitable*, not a
*polled predicate*.)

Semantics, deliberately uniform:

- A probe that can't pass within its deadline raises **`WaitTimeout`**
  (`ProcessError`, `TimeoutError`) — so `except TimeoutError` catches both run
  and readiness timeouts, and `.timeout_seconds` reads the configured deadline
  either way. `wait_for_port` additionally sets `.host`/`.port`, `wait_for_http`
  sets `.host`/`.port`/`.path`, and `wait_for_path` sets `.path`.
  `wait_for_port` / `wait_for_http` also chain the last failed attempt (a
  connection error, or — for `wait_for_http` — the last unexpected status) as
  `__cause__`.
- `wait_for_line` additionally raises `ProcessError` if the stdout stream ends
  *before* a match — no waiting out a 10s deadline on a dead server. It
  consumes items up to (and including) a match; iteration may continue
  afterward **only when a match was found** — exactly how far it advanced past
  the last inspected item on a timeout is unspecified, so don't rely on the
  iterator's position there. `wait_for_port` / `wait_for_http` / `wait_for_path`
  / `wait_until` don't touch the pipes at all.
- A failed probe **never kills the child** — you decide: retry, log, or tear
  down.
- `wait_until` / `wait_for_port` / `wait_for_http` / `wait_for_path` poll every
  `interval` seconds (`ValueError` if `interval <= 0`). A sync `wait_until`
  predicate runs on the event loop, so keep it non-blocking; for blocking work,
  pass an awaitable.

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

Or turn a whole run into a summary with `profile()`/`aprofile()`, which
samples the child every `every_seconds` until exit (the run's normal timeout
still applies; like `outcome()`/`aoutcome()`, the output is drained and
discarded, not returned). `RunProfile` is a **superset of `Outcome`**: it
carries the full `outcome` (`code` / `signal` / `timed_out`) *and* the
resource samples:

```python
proc = await Command("crunch").astart()
prof = await proc.aprofile(every_seconds=0.1)

print(
    f"exit={prof.code} signal={prof.signal} timed_out={prof.timed_out} "
    f"wall={prof.duration_seconds:.2f}s cpu={prof.cpu_time_seconds} "
    f"peak_rss={prof.peak_memory_bytes} "
    f"avg_cpu_cores={prof.avg_cpu_cores} ({prof.samples} samples)"
)
# prof.outcome is the same Outcome outcome()/aoutcome() would return.
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
  proc.output()` / `.outcome()` / `.finish()` / `.shutdown(...)` — or their
  `a`-prefixed async twins), the exit is a
  no-op — the verb already settled the run. Afterward the getters return `None`
  and a second consuming verb raises.
- **Prefer `shutdown()`/`ashutdown()` for a graceful stop.** `await proc.ashutdown(grace_seconds=5)`
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
