# Supervision

[‹ docs index](README.md)

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

Three gates are checked, in order, after every completed run:

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
3. **`max_restarts=n`** — at most *n* restarts (= *n + 1* total runs); an exhausted
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
outcome.storm_pauses   # always 0 — the failure-storm guard is not enabled in this binding
```

A returned outcome means supervision *concluded*, not that the child succeeded —
inspect `final_result` (e.g. `outcome.final_result.is_success`) for the child's own
verdict.

`storm_pauses` is reported for parity with the crate's outcome, but the Python
`Supervisor` does **not** enable the crate's opt-in failure-storm guard (and exposes
no knob to configure it), so it is **always `0`** — only the per-restart `backoff`
and the lifetime `max_restarts` cap apply. If you need a crash-loop circuit-breaker
on top of those, build it yourself from `outcome.restarts` and the per-run results.

A `Supervisor` is single-shot: `run()`/`arun()` consume it, so build a fresh one to
supervise again.

## Sync vs async

Both verbs return the same `SupervisionOutcome`; pick the one that matches your call
site. Durations are plain floats of seconds throughout.

```python
# Synchronous — blocks the calling thread (Ctrl+C interrupts it):
outcome = Supervisor(Command("my-server"), max_restarts=3).run()

# Asyncio — awaitable, integrates with the event loop:
outcome = await Supervisor(Command("my-server"), max_restarts=3).arun()
```

A `Supervisor` keeps *one* command alive across restarts; to contain a whole *tree*
of processes under kill-on-exit semantics, reach for a
[process group](process-groups.md) instead. To exercise restart/stop logic without
spawning anything real, see [Testing your code](testing.md), and for the broader
task-oriented recipes, the [Cookbook](cookbook.md).

---

Next: [Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Process groups](process-groups.md) · [Cookbook](cookbook.md)
