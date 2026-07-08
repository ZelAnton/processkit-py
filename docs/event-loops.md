# Async runtimes & event loops

[‹ docs index](README.md)

processkit's async surface is **asyncio-native**. Every `a`-prefixed verb
(`aoutput`, `arun`, `astart`, …) and every streaming handle (`stdout_lines()`,
`output_events()`, interactive stdin) is bridged onto the running asyncio event
loop by [`pyo3-async-runtimes`], so it needs a real asyncio loop underneath.
This page says exactly which runtimes provide one — and which don't.

- [Support at a glance](#support-at-a-glance)
- [asyncio & uvloop](#asyncio-uvloop)
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
event loop" error anyway.

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

## The readiness helpers

The readiness helpers ([`wait_for_port`](streaming.md#readiness-probes),
`wait_for_line`, `wait_for_path`, `wait_until`) are pure Python but built on
asyncio primitives, so they follow the same rule as the rest of the surface:
they need a running asyncio loop (asyncio, uvloop, or anyio-on-asyncio). In
particular `wait_for_line` consumes a `RunningProcess` stream, which is itself
asyncio-bridged — so there is no configuration in which the streaming surface is
asyncio-only while the helpers are not.

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
