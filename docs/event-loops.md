# Async runtimes & event loops

[‹ docs index](./)

processkit's async surface is **asyncio-native**. Every `a`-prefixed verb
(`aoutput`, `arun`, `astart`, …) and every streaming handle (`stdout_lines()`,
`output_events()`, interactive stdin) is bridged onto the running asyncio event
loop by [`pyo3-async-runtimes`], so it needs a real asyncio loop underneath.
This page says exactly which runtimes provide one — and which don't.

- [Support at a glance](#support-at-a-glance)
- [asyncio & uvloop](#asyncio--uvloop)
- [anyio](#anyio)
- [trio](#trio)
- [Why asyncio-native](#why-asyncio-native)
- [The readiness helpers](#the-readiness-helpers)

## Support at a glance

| Runtime | Supported | Why |
|---|---|---|
| **asyncio** (stdlib) | Yes — native | The bridge targets it directly |
| **uvloop** | Yes | A drop-in asyncio loop policy — the bridge sees an ordinary running asyncio loop |
| **anyio** on the **asyncio** backend | Yes | anyio's asyncio backend runs a real asyncio loop; the bridged awaitables await normally |
| **anyio** on the **trio** backend | No | No asyncio loop is present |
| **trio** (native) | No | No asyncio loop, and the bridge has no trio backend |
| **curio** | No | Same reason as trio |

The dividing line is simple: **is a real asyncio event loop running?** If yes
(plain asyncio, uvloop, or anyio-on-asyncio), the whole async surface works
unchanged. If no (trio, anyio-on-trio, curio), the `a`-prefixed verbs can't be
awaited — the sync surface (`output()`, `run()`, `ProcessGroup`, …) still works
from any thread, since it doesn't touch an event loop at all.

## asyncio & uvloop

The default. Nothing to configure:

```python
import asyncio
from processkit import Command

async def main():
    result = await Command("git", ["rev-parse", "HEAD"]).aoutput()
    print(result.stdout.strip())

asyncio.run(main())
```

[uvloop] is a faster asyncio loop implementation, installed as the loop policy.
Because it *is* an asyncio loop, processkit needs no special handling — install
the policy and every verb behaves identically (only with faster I/O
scheduling):

```python
import asyncio
import uvloop
from processkit import Command

async def main():
    await Command("./build.sh").arun()

uvloop.install()      # or asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
asyncio.run(main())   # 3.12+: asyncio.run(main(), loop_factory=uvloop.new_event_loop)
```

## anyio

[anyio] runs on one of two backends. On its **default asyncio backend**,
processkit works today with no changes — anyio does not hide the underlying
asyncio loop, so the bridged awaitables await normally, and asyncio
cancellation (which anyio maps onto its own cancel scopes) still tears the tree
down:

```python
import anyio
from processkit import Command

async def main():
    result = await Command("git", ["status", "--short"]).aoutput()
    print(result.stdout)

anyio.run(main)   # default backend="asyncio" — supported
```

On the **trio backend** (`anyio.run(main, backend="trio")`) there is no asyncio
loop, so the `a`-prefixed verbs cannot be awaited — see below.

## trio

Native [trio] (and anyio's trio backend, and curio) are **not supported**. A
trio program runs trio's own scheduler, not an asyncio loop, so the awaitables
processkit hands back — `asyncio.Future`s produced by the asyncio-wired bridge —
aren't trio-awaitable, and the binding refuses with a clear "no running asyncio
event loop" error anyway. For a quick symptom-to-solution map, see
[Troubleshooting](troubleshooting.md#a-prefixed-verbs-report-no-running-asyncio-event-loop).

If you're on trio and need processkit, the pragmatic bridge is
[`trio-asyncio`], which runs an asyncio loop inside a trio program; processkit's
verbs then execute in that asyncio context. That is a user-side integration
this package does not ship or test — treat it as unsupported-but-possible, not
a guarantee. The reliable alternative is the **synchronous** surface
(`output()`, `run()`, `ProcessGroup`, …), which needs no event loop and is
usable from a trio worker thread.

## Why asyncio-native

This is a deliberate, standing decision (project ROADMAP, Open decision #2),
not an oversight or a v1-only stopgap:

- The async surface is bridged tokio ↔ asyncio by [`pyo3-async-runtimes`],
  which targets asyncio and ships **no trio backend**. Native trio would mean
  writing a loop-agnostic bridge from scratch.
- That bridge is the single highest-risk part of the binding. Re-implementing
  it against trio's cancellation model — level-triggered cancel scopes and
  checkpoints, versus asyncio's edge-triggered `CancelledError` — while
  preserving the [kill-on-cancel no-orphan guarantee](timeouts-and-cancellation.md#cancelling-an-awaited-async-run)
  is a research effort in its own right, on a binding whose whole thesis is to
  stay thin and *not* reimplement hard concurrency logic.
- The anyio ecosystem is not actually shut out — anyio-on-asyncio works — so
  the excluded slice is specifically the trio-family loops, a smaller segment.

The path if this is ever revisited: port the pure-Python readiness helpers to
anyio primitives first (cheap, and it makes `wait_for_port` / `wait_until`
loop-agnostic), then evaluate a loop-agnostic compiled bridge once
`pyo3-async-runtimes` grows a trio backend or a concrete demand signal appears.

## Interpreter shutdown and the async bridge

**Known limitation.** A program that `await`s a processkit verb and then
terminates *immediately* can crash at exit — a signal, no Python traceback,
*after* all of its real work has completed. This is a defect in the bridge,
not in your code; the mechanism, the exposure, and the way to avoid it are
below. It is documented rather than fixed because the fix is not available
inside this library today ("Why this isn't fixed here yet").

### The window

The bridge resolves each awaited `a`-verb from a **tokio runtime thread**, not
from the thread running your event loop. That thread attaches to the
interpreter and hands the result over with `loop.call_soon_threadsafe(...)`,
which queues the completion and *then* wakes the loop by writing to its
self-pipe — a write that releases the GIL. From that instant your coroutine
can resume and your program can run all the way to its end, while the bridge
thread is still inside the interpreter with a little work left: re-acquire the
GIL, return through those frames, drop its object references, release the GIL.

While the interpreter is alive that is harmless — the bridge thread gets its
GIL slot back in microseconds. While the interpreter is being **finalized** it
is not: CPython's shutdown assumes no foreign thread is still touching
interpreter state, and a thread that asks for the GIL after finalization has
begun is torn out from under itself. The observed symptom is a SIGSEGV inside
`Py_FinalizeEx`'s last `PyGC_Collect` pass, walking an object whose reference
count was corrupted underneath it. The window is narrow and needs a loaded
machine to open — reproduced at ~1.6% of runs on a 16-CPU Linux box
oversubscribed 4x, and once in this project's own CI — but it is real.

### Who is exposed

- **A program that keeps running, or does any real teardown after its last
  `await`.** Not exposed in practice: the bridge thread is long finished
  before shutdown starts.
- **A short-lived program whose last act is an `await`** — a script, a CI
  step, a `python -c` one-liner. This is the exposed shape, and the more
  loaded the machine, the wider the window.
- **The `python -m processkit` CLI itself.** Not exposed: it does not finalize
  the interpreter at all (see [How the wrapper
  terminates](cli.md#how-the-wrapper-terminates)).

### Avoiding it

The one *deterministic* remedy is to not finalize the interpreter: do your own
cleanup and terminate with `os._exit(code)`. Interpreter shutdown never runs,
so there is nothing for the bridge thread to race — on any platform and any
Python version. That is exactly what this project's own CLI does.

`os._exit` is a blunt instrument, though: it skips **everything** the
interpreter would otherwise do on the way out. Take over by hand whatever your
program actually relies on:

- **`ProcessGroup` teardown that has not happened yet.** On Linux/macOS the
  no-orphan guarantee is dispatched from the `with` / `async with` exit path;
  `os._exit` inside a still-open group leaks the tree (Windows Job Objects
  survive this — the kernel reaps on the last handle close). Exit your groups
  *before* exiting the process. This is the one item on this list that
  processkit itself cares about.
- `atexit` hooks — including ones libraries registered for you.
- `logging.shutdown()`, and with it every buffered `FileHandler` /
  `SMTPHandler` / queue handler.
- Buffered writes on any file object you have not flushed and closed —
  including `sys.stdout` / `sys.stderr`, which are block-buffered whenever
  they are redirected into a pipe.
- Coverage data (`coverage`, `pytest-cov`) for that process — measurement is
  written at shutdown.
- `tempfile.TemporaryDirectory` / `NamedTemporaryFile` cleanup, and any other
  `__del__` / `weakref` finalizer.
- `multiprocessing`'s own atexit join and the `resource_tracker` handoff.

So the honest shape is "clean up, then exit", not "call `os._exit` and hope":

```python
import asyncio
import logging
import os
import sys

from processkit import Command, ProcessGroup


async def main() -> int:
    async with ProcessGroup() as group:  # teardown happens here, not at exit
        result = await group.aoutput(Command("git", ["rev-parse", "HEAD"]))
    print(result.stdout.strip())
    return result.code or 0


if __name__ == "__main__":
    code = asyncio.run(main())
    logging.shutdown()  # from here down: what interpreter shutdown would
    sys.stdout.flush()  # otherwise have done for you, done by hand instead
    sys.stderr.flush()
    os._exit(code)
```

If that is too heavy for your program — and for most programs it is — the
practical alternative is simply **not exiting instantly after the last
`await`**: any real work after it (writing a report, closing resources,
`asyncio.run` returning into a longer-lived process) closes the window in
practice. That is a mitigation, not a guarantee.

### Why this isn't fixed here yet

The obvious in-library fix — count completions in flight and have an `atexit`
hook wait for the count to drain before finalization — needs a signal this
library cannot get today. The completion runs *inside*
`pyo3-async-runtimes`: `future_into_py` awaits the bridged future and then
dispatches the interpreter attach to a `spawn_blocking` thread without
awaiting it (`generic.rs` in 0.29.0). Everything processkit controls — the
future it hands over, the value that future produces — is finished *before*
that attach starts, so there is no point at which a counter could be
decremented to mean "the bridge thread has left the interpreter". Tokio's task
metrics do not see it either: the dispatching task completes immediately, and
blocking-pool work is not counted there.

Closing it properly therefore means either an upstream hook in
`pyo3-async-runtimes` or replacing the completion path with one that never
attaches from a foreign thread (resolve on the loop's own thread through a
file-descriptor wake-up) — a redesign of the single highest-risk component of
this binding, not a patch. Until then this is a recorded, documented
limitation with a deterministic user-side remedy, and the CLI — the one
short-lived program this project ships — already takes it. See the *Risk
register* in the project ROADMAP.

## The readiness helpers

The readiness helpers ([`wait_for_port`](streaming.md#readiness-probes),
`wait_for_line`, `wait_for_path`, `wait_until`) are pure Python but built on
asyncio primitives, so they follow the same rule as the rest of the surface:
they need a running asyncio loop (asyncio, uvloop, or anyio-on-asyncio). In
particular `wait_for_line` consumes a `RunningProcess` stream, which is itself
asyncio-bridged — so there is no configuration in which the streaming surface is
asyncio-only while the helpers are not.

`sample_stats` (see [Process groups](process-groups.md#live-monitoring)) is the
same story: pure Python built on `asyncio.sleep`, needing the same running
asyncio loop as everything else here.

---

Next: [Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Streaming & interactive I/O](streaming.md) ·
[Platform support](platforms.md) ·
[Cookbook](cookbook.md)

[`pyo3-async-runtimes`]: https://github.com/PyO3/pyo3-async-runtimes
[uvloop]: https://github.com/MagicStack/uvloop
[anyio]: https://anyio.readthedocs.io/
[trio]: https://trio.readthedocs.io/
[`trio-asyncio`]: https://github.com/python-trio/trio-asyncio
