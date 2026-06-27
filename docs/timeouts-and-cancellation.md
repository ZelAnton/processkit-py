# Timeouts & cancellation

[‹ docs index](README.md)

Two ways a run can end early, with two different philosophies:

- a **timeout** is part of the run's contract, so its expiry is *data* — captured
  on the capture verbs, raised on the success verbs;
- a **cancellation** is an *abandonment* — the caller changed its mind, so the
  run's tree is torn down and there is no result to inspect. Sync →
  `KeyboardInterrupt`; async → `asyncio.CancelledError`.

The one thing to internalize first: the **same deadline** surfaces differently
*by verb* — captured as `timed_out` on the capture verbs, raised as `Timeout` on
the success verbs. Cancellation is never captured: it is always terminal.

- [Setting a timeout](#setting-a-timeout)
- [Graceful timeout](#graceful-timeout)
- [Interrupting a blocked sync call (Ctrl+C)](#interrupting-a-blocked-sync-call-ctrlc)
- [Cancelling an awaited async run](#cancelling-an-awaited-async-run)
- [Timeout vs. cancellation](#timeout-vs-cancellation)
- [Readiness-probe timeouts are separate](#readiness-probe-timeouts-are-separate)

## Setting a timeout

`.timeout(seconds)` bounds the whole run and kills the **entire process tree** at
the deadline — a wrapper script's grandchildren die too, not just the direct
child. Durations are plain floats of seconds.

Where the expiry lands depends only on the verb:

```python
from processkit import Command

# Capture verbs: the deadline is DATA. The run does not raise.
result = Command("slow-tool").timeout(5.0).output()
if result.timed_out:
    print("killed at the deadline; partial output:", result.stdout)

# Success verbs: the deadline is an ERROR.
Command("slow-tool").timeout(5.0).run()   # raises Timeout on expiry
```

Async is identical with the `a`-prefixed verbs:

```python
result = await Command("slow-tool").timeout(5.0).aoutput()   # result.timed_out
```

| Verb | Deadline expiry becomes |
|---|---|
| `output()` / `aoutput()`, `output_bytes()` / `aoutput_bytes()` | a result with `result.timed_out == True`, `result.code == None`, partial output kept |
| `run()` / `arun()`, `exit_code()`, `probe()` | raises `Timeout` (partial output attached) |

The `Timeout` exception carries structured fields — `program`,
`timeout_seconds`, `stdout`, `stderr` — so a hung tool's last words survive the
kill:

```python
from processkit import Timeout

try:
    Command("slow-tool").timeout(5.0).run()
except Timeout as e:
    print(e.program, e.timeout_seconds)
    print("last output before the kill:", e.stderr)
```

`Timeout` is **also** a builtin `TimeoutError`, so `except TimeoutError` catches
it too — handy for callers that don't import the processkit hierarchy.

*Deeper: [Running commands](commands.md) for the full verb surface.*

## Graceful timeout

By default the deadline **hard-kills** at once. `.timeout_grace(g)` instead asks
the tree to clean up first: at the deadline it sends the terminate signal, gives
the tree up to `g` seconds to exit, then hard-kills whatever is still alive.

```python
# At 30s: send SIGTERM, wait up to 5s, then SIGKILL the tree.
Command("server").timeout(30.0).timeout_grace(5.0).run()
```

Choose the first signal with `.timeout_signal(name)` — one of `term` (default),
`kill`, `int`, `hup`, `quit`, `usr1`, `usr2`:

```python
Command("nginx").timeout(30.0).timeout_signal("quit").timeout_grace(5.0).run()
```

A signal-handling child that exits early ends the grace early. `result.timed_out`
is `True` (or `Timeout` is raised) regardless of whether the child obeyed the
signal or was hard-killed after the grace — the **deadline** is what fired, not
the manner of death. This is the same SIGTERM → wait → SIGKILL tier that
[Process groups](process-groups.md) use for graceful shutdown.

Mind the platform asymmetry: Windows has no signal tier, so `timeout_grace` /
`timeout_signal` are accepted but the deadline kills the job atomically. See
[Platform support](platforms.md).

## Interrupting a blocked sync call (Ctrl+C)

A synchronous verb blocked on a child honors **Ctrl+C** (SIGINT). Instead of
hanging until the child decides to exit, it raises `KeyboardInterrupt` *promptly*
and tears down the run's process tree on the way out:

```python
try:
    Command("long-batch-job").run()     # blocks here…
except KeyboardInterrupt:
    # Ctrl+C: the child tree is already reaped; the exception is re-raised at once.
    print("interrupted by the user")
```

This holds for every sync verb (`output()`, `run()`, `exit_code()`, `probe()`,
…) — no orphaned grandchildren are left behind.

> **Main-thread only.** CPython delivers signals to the main thread, so this
> prompt `Ctrl+C` interruption works only when the sync verb runs on the main
> thread. A sync verb called from a `threading.Thread` (more tempting on a
> free-threaded build) blocks until the child exits — it cannot observe the
> signal. Off the main thread, prefer the async API and cancel the task.

The async surface uses task cancellation instead, below.

## Cancelling an awaited async run

Cancelling the task awaiting a run — directly with `task.cancel()`, or via
`asyncio.wait_for(...)` / `asyncio.timeout(...)` — tears down the **whole process
tree** and surfaces as `asyncio.CancelledError`:

```python
import asyncio
from processkit import Command

# Direct cancel: stop a run from elsewhere.
task = asyncio.ensure_future(Command("long-export").aoutput())
# ... later — a shutdown handler, a sibling failure, a UI action ...
task.cancel()                  # the tree is reaped; awaiting `task` raises CancelledError

# Caller-side deadline via asyncio: the run is cancelled, then re-raised to you.
try:
    await asyncio.wait_for(Command("long-export").arun(), timeout=10)
except TimeoutError:           # asyncio re-raises the cancellation as TimeoutError
    ...                        # the run's process tree was already torn down
```

`asyncio.wait_for` (and `asyncio.timeout`, 3.11+) cancel the inner run exactly
like `task.cancel()`, then translate the cancellation into a builtin
`TimeoutError` at the `await` boundary — so *inside*, the run was cancelled, even
though *you* catch `TimeoutError`. Either way the tree is gone.

**Cancellation surfaces as `asyncio.CancelledError`** when you cancel through
asyncio itself, as above (a `BaseException`, deliberately not a
`ProcessError`) — there is no separate processkit exception on this path.

## Cancelling with an explicit `CancellationToken`

For a cancel switch that isn't tied to one asyncio task — shared across
several runs, fired from sync code, or from a different task entirely — wire
a `CancellationToken` instead:

```python
from processkit import Command, Cancelled, CancellationToken

token = CancellationToken()
cmd = Command("long-export").cancel_on(token)

# elsewhere — a signal handler, a UI action, another task:
token.cancel()

try:
    await cmd.arun()   # (or cmd.run() from sync code)
except Cancelled:
    ...  # the whole tree was already torn down
```

Unlike asyncio cancellation, this surfaces as `Cancelled` — a `ProcessError`
subclass carrying `.program`, catchable alongside every other processkit
exception, on *either* the sync or async surface. A cancelled token stays
cancelled forever (never use it to mean "pause" — see
[`ProcessGroup.suspend()`/`resume()`](process-groups.md) for that), and a
cancelled run is never retried (`Command.retry()`) or restarted
(`Supervisor`) — another attempt could only fail the same way.

`Command.cancel_on()` **replaces** any previously set token (last write
wins); the *gap-fill* containers `Pipeline.cancel_on()` and `CliClient`'s
`default_cancel_on=` leave an explicit per-stage/per-command token intact,
only filling in where none was set — the same gap-fill convention
`default_timeout` uses. `token.child_token()` derives a token cancelled
automatically when the parent fires, but cancellable independently — for
scoping a broader shutdown token down to one operation while still reacting
to the parent.

## Timeout vs. cancellation

The two can both stop a run, but they are different kinds of event:

| | Timeout | asyncio cancellation | `CancellationToken` |
|---|---|---|---|
| Meaning | the deadline was part of the contract | the caller abandoned the run | an explicit cancel switch fired |
| Capture verbs (`output*`) | captured as `result.timed_out` | terminal — no result | terminal — no result |
| Success verbs (`run`/`exit_code`/`probe`) | raises `Timeout` | terminal — no result | raises `Cancelled` |
| Sync surface | `Timeout` | `KeyboardInterrupt` | `Cancelled` |
| Async surface | `Timeout` | `asyncio.CancelledError` | `Cancelled` |

A timeout still leaves something to inspect on the capture verbs; a cancellation
never does — the run was abandoned, so there is nothing to report but the
cancellation itself. **When a cancel and a timeout race on the same run,
cancellation wins:** you asked the run to stop mattering, so no `timed_out`
result is synthesized.

On a shared [ProcessGroup](process-groups.md) handle, a timeout or cancellation
that hits one child kills **that child only** — the group's siblings keep
running.

## Readiness-probe timeouts are separate

The `timeout` on the readiness helpers — `wait_until`, `wait_for_port`,
`wait_for_line` — is a **different deadline** from a run timeout. It bounds how
long you wait for a *condition*, and on expiry it raises `WaitTimeout` (also a
builtin `TimeoutError`) **without killing the child** — the process keeps
running; only your wait gave up:

```python
from processkit import wait_for_port

await wait_for_port("127.0.0.1", 8080, timeout=10)   # TimeoutError if not listening in 10s
```

Because `Timeout` is itself a `TimeoutError`, a single `except TimeoutError`
catches both a run timeout and a readiness timeout — but only the run timeout
reaped a tree.

*Deeper: [Streaming & interactive I/O](streaming.md).*

## Bounding pipelines & tuning group shutdown

- A [pipeline](pipelines.md) bounds the **whole chain** with
  `Pipeline.timeout(seconds)`; the same captured-vs-raised rule applies to
  whichever verb you finish it with.
- A [ProcessGroup](process-groups.md)'s graceful teardown timing is set at
  construction with `shutdown_grace=` and `escalate_to_kill=`, independent of
  any per-run timeout. Note: cancelling an in-flight `await group.ashutdown()` (or
  an `async with` exit) falls back to an immediate hard kill — the tree is still
  reaped (no orphan), but the *graceful* signal-then-wait window is skipped.

## Keeping a flaky thing alive

A timeout stops a single run; it does not restart anything, and the Python
binding has **no per-command retry**. If you want a run replayed on transient
failure, or a *service* kept alive across crashes, that is
[Supervision](supervision.md) — `Supervisor(...)` with a restart policy and
backoff.

---

Next: [Supervision](supervision.md) ·
[Streaming & interactive I/O](streaming.md) ·
[Process groups](process-groups.md) ·
[Cookbook](cookbook.md)
