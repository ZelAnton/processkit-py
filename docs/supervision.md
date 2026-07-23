# Supervision

[‹ docs index](./)

A [`timeout`](timeouts-and-cancellation.md) or a cancelled task *bounds one run* — it
caps a single invocation, and then it's over. A `Supervisor` answers the opposite
need: *keep a long-lived child alive*. It runs a [`Command`](commands.md), and
whenever that command exits it restarts it per policy — with a bounded restart count
and exponential, jittered backoff — until a stop condition is met. Think of it as a
pocket `systemd`/`runit`: a keeper loop you can drop into a script. It is
platform-agnostic.

- [A supervised server](#a-supervised-server)
- [Restart policies](#restart-policies)
- [Backoff and jitter](#backoff-and-jitter)
- [Stopping: the predicate](#stopping-the-predicate)
- [Reading the outcome](#reading-the-outcome)
- [Liveness health checks](#liveness-health-checks)
- [Sync vs async](#sync-vs-async)

## A supervised server

The supervisor takes a normal `Command` — build it with all the usual knobs (args,
`env`, `cwd`, `timeout`, …) and they apply to *every* restart:

```python
from processkit import Command, Supervisor

outcome = Supervisor(
    Command("my-server", ["--port", "8080"]).env("LOG", "info"),
    restart="on_crash",        # the default
    max_restarts=5,            # default: unlimited
    backoff_initial=0.2,       # seconds; base delay (default 0.2)
    backoff_factor=2.0,        # multiplier (default 2.0)
    max_backoff=30.0,          # seconds; cap (default 30.0)
).run()                        # or: await ....arun()

print(outcome.restarts, outcome.stopped)
```

Each restart is one full captured run of the command. The one-shot stdin caveat
applies from the second run onward — see [Running commands](commands.md). Leave a
knob unset (`None`) and the crate default shown above is used.

Contrast this with a one-shot run wrapped in a hand-rolled `while True:` loop: you'd
reimplement backoff, jitter, and the stop gates yourself. The supervisor *is* that
loop, written once and correctly.

## Restart policies

`restart=` decides what is worth restarting. A **crash** is any run that is not a
success — an exit code outside the accepted set (default `{0}`, widened by the
command's [`success_codes`](commands.md)), a timeout, or a signal-kill:

| `restart=` | Restarts after… |
|---|---|
| `"on_crash"` *(default)* | crashes only; a clean exit ends supervision (`stopped == "policy_satisfied"`) |
| `"always"` | every completed run, clean or not — pair with `stop_when=`/`max_restarts=` or it loops forever |
| `"never"` | nothing: one run, reported as-is |

Because `success_codes` defines success, a command built with `.success_codes([0, 2])` that
exits `2` is *clean*, so `"on_crash"` treats it as a satisfied policy, not a crash.

## Backoff and jitter

Between restarts the supervisor sleeps. The *n*-th restart (0-based) waits:

```text
delay(n) = min(backoff_initial × backoff_factor**n, max_backoff) × jitter
```

with `jitter` drawn uniformly from `[0.5, 1.5)` per restart. With the defaults
(`0.2`, `2.0`, cap `30.0`):

```text
restart #0 → ~0.2s   #1 → ~0.4s   #2 → ~0.8s … #7 → ~25.6s   #8+ → 30.0s (cap)
```

Jitter is **on by default** so a fleet of supervised workers knocked over by one
incident doesn't stampede back in lockstep. Pass `jitter=False` for deterministic
delays (handy in tests). `backoff_factor` is a finite multiplier `>= 1.0`, and it
rides along with `backoff_initial` — set the base to opt into a custom schedule.

## Stopping: the predicate

Four gates are checked, in order, after every completed run:

1. **`stop_when=`** — a callable handed each run's [`ProcessResult`](commands.md);
   returning `True` ends supervision *regardless of policy* (`stopped ==
   "predicate"`). The classic "exit 0 is done" under `restart="always"`:

   ```python
   outcome = Supervisor(
       Command("flaky-worker"),
       restart="always",
       stop_when=lambda r: r.code == 0,   # stop on the first clean exit
   ).run()
   ```

2. **The policy** — `"on_crash"` stops on a clean exit; `"never"` stops after one run.
3. **`give_up_when=`** — a callable consulted only for a crash the policy would
   otherwise restart, ahead of `max_restarts=` and the storm guard. It classifies a
   *permanent* failure so supervision gives up instead of restarting forever. It
   receives one argument mirroring the crate's `GiveUpAttempt` sum type, dispatched
   with `isinstance`: a `ProcessResult` for a crashed run that produced a result
   (classify by e.g. `attempt.code`), or a `ProcessError` subclass for a launch that
   never produced one (classify by e.g. `isinstance(attempt, ProcessNotFound)` for a
   missing binary). Returning `True` for a crash verdict stops with
   `outcome.stopped == "gave_up"`; a launch-failure verdict has no result to report
   and surfaces the classified error directly from `run()`/`arun()`.
4. **`max_restarts=n`** — at most *n* restarts (= *n + 1* total runs); an exhausted
   budget reports the last result (`stopped == "restarts_exhausted"`).
   `max_restarts=0` means exactly one run.

Two honest caveats about `stop_when=`:

- **Inspect the passed result — don't call a synchronous run verb inside it.** Read
  `r.code` / `r.is_success` / `r.stdout` off the argument. The predicate runs *on*
  the runtime, so a nested sync call (`Command(...).run()`/`.probe()`/…) can't drive
  the runtime again — it raises a clear `ProcessError` ("cannot call a synchronous
  processkit verb from inside an async context or a callback"). That error is then
  surfaced through the unraisable hook (next bullet), so the supervisor keeps going
  rather than stopping — i.e. a sync verb in the predicate is a no-op stop gate, not
  a crash. If you must run a check, precompute it before the supervised run, or use
  the result handed to the predicate.
- **A predicate that raises does not stop supervision.** The exception is surfaced
  through Python's [unraisable hook](https://docs.python.org/3/library/sys.html#sys.unraisablehook)
  and treated as "don't stop" — a buggy predicate degrades to *keep going*, it does
  not crash the supervisor.

## Reading the outcome

`run()` (and `arun()`) resolve to a `SupervisionOutcome`:

```python
outcome.final_result   # ProcessResult of the LAST run
outcome.restarts       # restarts performed (run #1 is not a restart)
outcome.stopped        # "policy_satisfied" | "predicate" | "restarts_exhausted"
                        # | "gave_up" | "unhealthy" | "unknown" (forward-compat
                        # fallback, not emitted by the pinned crate version)
outcome.storm_pauses   # how many failure-storm pauses were taken (see below)
outcome.liveness_kills # how many wedged incarnations a health check force-killed
                        # (see "Liveness health checks"; 0 unless one is enabled)
```

A returned outcome means supervision *concluded*, not that the child succeeded —
inspect `final_result` (e.g. `outcome.final_result.is_success`) for the child's own
verdict.

`final_result.stdout` is the **last run's** output, and for a long-lived
supervised process it is kept to a bounded tail (the most recent ~1000 lines)
rather than buffered in full — so `final_result.truncated` may be `True`. Treat it
as a diagnostic tail, not a complete transcript. Widen or re-bound the cap with
`Supervisor`'s own `capture_max_bytes=`/`capture_max_lines=`/`capture_on_overflow=`
constructor kwargs (mirroring `Command.output_limit`'s kwargs — set at least one
of the two cap sizes), or give the base `Command` an explicit
[`output_limit`](commands.md) (respected as-is) before wrapping it in a
`Supervisor`; otherwise stream the process yourself.

## The failure-storm guard

Backoff slows individual restarts; the **failure-storm guard** distinguishes "fails
once in a blue moon" from "crash-looping" and takes a single collective pause
instead of hammering restarts at backoff speed. It is **off by default** — enable
it by setting `storm_pause`:

```python
outcome = Supervisor(
    Command("flaky-worker"),
    restart="on_crash",
    storm_pause=30.0,          # ENABLES the guard: pause 30s when a storm is detected
    failure_threshold=5.0,     # decaying failure score that trips the pause (optional)
    failure_decay=60.0,        # the score halves every 60s (optional)
).run()

if outcome.storm_pauses:
    log.warning("flaky-worker crash-looped: %d storm pauses", outcome.storm_pauses)
```

Each failure adds to a score that decays every `failure_decay`; once it crosses
`failure_threshold` the supervisor takes one `storm_pause` and increments
`outcome.storm_pauses`. With `storm_pause` unset, the guard is inactive and
`storm_pauses` stays `0` — only the per-restart `backoff` and the lifetime
`max_restarts` cap apply.

A `Supervisor` is single-shot: `run()`/`arun()` consume it, so build a fresh one to
supervise again.

## Liveness health checks

Restart policies react to a process that *exits*. But a long-lived service can wedge
*without* exiting — a deadlocked server, a stuck event loop, a worker that stopped
answering — and an exit-driven policy would happily call that "still running" forever.
A **liveness health check** closes that blind spot: an opt-in probe, re-run on a fixed
cadence, that force-restarts the child when it stops looking healthy. It is the
`Supervisor`'s take on systemd's `WatchdogSec` or a container liveness probe, and it is
**off by default**.

```python
import socket

from processkit import Command, Supervisor


def is_healthy() -> bool:
    # A fast, non-blocking liveness probe: can we still reach the server's port?
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=0.5):
            return True
    except OSError:
        return False


outcome = Supervisor(
    Command("my-server", ["--port", "8080"]),
    health_check=is_healthy,       # sync () -> bool; True == healthy
    health_check_interval=5.0,     # seconds between probes — REQUIRED with health_check
    health_check_failures=3,       # consecutive failures before a force-restart (default 3)
    max_restarts=10,
).run()

print(outcome.liveness_kills)      # wedged incarnations that were force-killed
```

`health_check=` is a **synchronous** callable `() -> bool` — *not* a coroutine —
returning `True` for healthy. It is the liveness twin of `stop_when=`/`give_up_when=`
and runs on the supervision runtime, so keep it fast and non-blocking (a quick socket
connect, an HTTP `/healthz` GET, a heartbeat-file check); a slow probe merely stretches
the effective cadence. `health_check_interval=` is its **required** partner — the crate
takes probe and cadence together, so passing either one alone raises `ValueError`. The
first probe fires one interval *after* an incarnation starts (startup grace), then
repeats for that incarnation's life; a healthy child is never disturbed.

A probe that fails `health_check_failures=` checks **in a row** (default `3`; one
healthy probe resets the streak, so a single blip is forgiven) force-restarts the
child. A failed streak is treated **exactly like a crash**: it flows through the restart
policy, `backoff`, the storm guard, and `max_restarts` just as a real crash would — but
it does *not* consult `stop_when=` (there is no cleanly-completed run to judge). So:

- under `restart="never"`, the single force-killed run is the final one, reported as
  `outcome.stopped == "unhealthy"`;
- under a restart-wanting policy (`"on_crash"`/`"always"`), it restarts and surfaces —
  if it ends supervision at all — as the usual `"gave_up"` / `"restarts_exhausted"`.

Either way each force-kill is counted in `outcome.liveness_kills` (and, because it
counts as a crash, is also reflected in `outcome.restarts` when the policy restarted
it), and the final synthetic result is a non-success signal-kill. A probe that *raises*
or returns a non-`bool` cannot answer "healthy": it is treated as unhealthy **and** its
error is surfaced to the caller from `run()`/`arun()` — not swallowed into a spurious
liveness kill — the same fail-loud contract as `stop_when=`/`give_up_when=`.

## Sync vs async

Both verbs return the same `SupervisionOutcome`; pick the one that matches your call
site. Durations are plain floats of seconds throughout.

```python
# Synchronous — blocks the calling thread (Ctrl+C interrupts it):
outcome = Supervisor(Command("my-server"), max_restarts=3).run()

# Asyncio — awaitable, integrates with the event loop:
outcome = await Supervisor(Command("my-server"), max_restarts=3).arun()
```

**`arun()` is lazy — nothing runs until you `await` it.** Like every
`a`-prefixed verb, `arun()` returns an awaitable that starts no supervision
until it is first awaited. So an `arun()` you build but never await — a
dropped awaitable, or `asyncio.ensure_future(sv.arun())` you never follow up
on — starts no restart loop at all; dropping it releases the supervisor and
every `stop_when=`/`give_up_when=` callback it captured, rather than pinning
them (and whatever they close over) for the life of the interpreter. The flip
side is that an unawaited `arun()` never supervises anything, so `await` what
it returns — and, for an unbounded `restart="always"`, give it a
`max_restarts=`/`stop_when=` so supervision also has a defined end:

```python
# Bounded and awaited — runs, then stops after at most 5 restarts:
outcome = await Supervisor(Command("flaky-worker"), restart="always", max_restarts=5).arun()

# Backgrounded — keep the task and await it, so supervision actually runs:
task = asyncio.ensure_future(Supervisor(Command("flaky-worker"), restart="always", max_restarts=5).arun())
outcome = await task
```

A `Supervisor` keeps *one* command alive across restarts; to contain a whole *tree*
of processes under kill-on-exit semantics, reach for a
[process group](process-groups.md) instead. To exercise restart/stop logic without
spawning anything real, see [Testing your code](testing.md), and for the broader
task-oriented recipes, the [Cookbook](cookbook.md).

---

Next: [Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Process groups](process-groups.md) · [Cookbook](cookbook.md)
