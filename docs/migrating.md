# Coming from `subprocess`

[‹ docs index](README.md)

You already know `subprocess` (or `asyncio.subprocess`). This guide maps the
patterns you write today onto their `processkit` equivalents, so porting existing
code is mechanical — and then shows the one thing the stdlib can't do that is the
reason to switch: **containing the whole process tree**.

Every snippet assumes `from processkit import ...`. For the full treatment of any
verb, follow the links into [Running commands](commands.md).

## The mental-model shift

`subprocess` couples *running* a command with *deciding whether it failed*:
`run(...)` gives you a `returncode` to inspect, `run(..., check=True)` raises. In
`processkit` those are two different verbs:

- `Command(...).output()` **captures** the result — a non-zero exit, a timeout, and
  a signal-kill are all **data** on a `ProcessResult`, never an exception.
- `Command(...).run()` **requires success** — it returns trimmed stdout and raises a
  typed exception on a non-zero exit, a timeout, or a signal-kill.

Pick the verb by what you want; you no longer thread a `check=` flag through.
See [Picking a verb](commands.md#picking-a-verb) for the full set.

## Running a command (sync)

| You wrote (`subprocess`) | Now write (`processkit`) |
|---|---|
| `run(cmd, capture_output=True, text=True)` → inspect `.returncode` / `.stdout` | `Command(prog, args).output()` → `ProcessResult` (`.code`, `.stdout`, `.is_success`, `.timed_out`) |
| `run(cmd, capture_output=True, text=True, check=True).stdout` | `Command(prog, args).run()` (returns **trimmed** stdout, raises on failure) |
| `run(cmd).returncode` | `Command(prog, args).exit_code()` (raw code) |
| `run(cmd).returncode == 0` | `Command(prog, args).output().is_success` (total); `.probe()` is a shortcut for `0`/`1`-exit predicate tools |
| `run(cmd, capture_output=True).stdout` (bytes) | `Command(prog, args).output_bytes()` → `BytesResult` (`.stdout` is `bytes`) |

```python
from processkit import Command

# subprocess: subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
result = Command("git", ["rev-parse", "HEAD"]).output()
print(result.stdout.strip(), result.code, result.is_success)

# subprocess: subprocess.run([...], check=True, capture_output=True, text=True).stdout
commit = Command("git", ["rev-parse", "HEAD"]).run()   # trimmed stdout, raises on failure
```

Note the two differences from `run()` in `subprocess`: `.output().stdout` is the
**full** captured text (not stripped — strip it yourself), while `.run()` returns
it **trimmed**; and a non-zero exit is only an error for `.run()`, never for
`.output()`.

One more divergence to know: unlike `subprocess`'s numeric `.returncode`, the
*checking* verbs (`exit_code`, `probe`, `run`) **raise** on a timeout or a
signal-kill instead of returning a code (and `probe()` also raises on any exit code
other than `0`/`1`). Reach for `.output()` when you want an abnormal exit as
inspectable data (`.timed_out`, `.signal`) rather than an exception.

## The common flags

| `subprocess` keyword | `processkit` builder |
|---|---|
| `timeout=5` | `.timeout(5.0)` — captured on `.output()` (`result.timed_out`), raised by `.run()` |
| `input="text"` / `input=b"..."` | `.stdin_text("text")` / `.stdin_bytes(b"...")` |
| `cwd="/path"` | `.cwd("/path")` |
| `env={...}` (**replaces** the whole environment) | `.env_clear().envs({...})` |
| add/override one variable on the inherited env | `.env("KEY", "value")` / `.envs({...})` |
| — (no equivalent) | `.success_codes([0, 1])` — **replaces** the success set with the listed codes (`grep`/`diff`) |

```python
# subprocess: subprocess.run(["slow"], timeout=5) -> raises TimeoutExpired
Command("slow").timeout(5.0).run()                       # raises Timeout on expiry
result = Command("slow").timeout(5.0).output()           # result.timed_out is True instead

# subprocess: subprocess.run(["tr","a-z","A-Z"], input="hello\n", text=True)
Command("tr", ["a-z", "A-Z"]).stdin_text("hello\n").run()

# subprocess: subprocess.run(["grep","x","f"], check=True)  # exit 1 = "no match" -> would raise
Command("grep", ["x", "f"]).success_codes([0, 1]).run()  # 1 (no match) is not a failure
```

`env=` in `subprocess` **replaces** the entire environment; the direct equivalent
is `.env_clear().envs({...})`. To *add to* the inherited environment (the more
common intent), use `.env(...)` / `.envs(...)` without `env_clear()`. More in
[Environment and sandboxing](commands.md#environment-and-sandboxing).

## Shell pipelines, without the shell

`subprocess` pipelines usually mean `shell=True` (and a shell-injection footgun) or
hand-wiring two `Popen`s. `processkit` pipes are shell-free:

```python
# subprocess: subprocess.run("ps aux | grep python", shell=True)
from processkit import Command

out = (Command("ps", ["aux"]) | Command("grep", ["python"])).run()
```

See [Pipelines](pipelines.md) for pipefail attribution and binary tails.

## Async

If you reach for `asyncio.subprocess`, every verb has an `a`-prefixed twin that
shares the same types:

```python
# asyncio: proc = await asyncio.create_subprocess_exec("git","status", stdout=PIPE)
#          out, _ = await proc.communicate()
result = await Command("git", ["status", "--short"]).aoutput()

# Streaming stdout line by line (asyncio-native):
proc = await Command("my-build", ["--watch"]).astart()
async for line in proc.stdout_lines():
    print(line)
finished = await proc.finish()
```

Streaming, interactive stdin, and readiness probes are covered in
[Streaming & interactive I/O](streaming.md).

## Exceptions

The exception hierarchy is independent, but the three that mirror a stdlib builtin
also *subclass* it — so your existing `except` clauses keep working:

| `subprocess` raises | `processkit` raises | Also a subclass of |
|---|---|---|
| `CalledProcessError` (from `check=True`) | `NonZeroExit` (`.code`, `.stderr`) | — |
| `TimeoutExpired` | `Timeout` (`.timeout_seconds`) | `TimeoutError` |
| `FileNotFoundError` (missing program) | `ProcessNotFound` (`.program`) | `FileNotFoundError` |
| `PermissionError` | `PermissionDenied` (`.program`) | `PermissionError` |

```python
# This subprocess-style handler keeps working, because ProcessNotFound *is* a
# FileNotFoundError and Timeout *is* a TimeoutError:
from processkit import Command

try:
    Command("mytool").timeout(5.0).run()
except FileNotFoundError:
    print("not installed")
except TimeoutError:
    print("timed out")
```

Every exception derives from `ProcessError`; see [Errors](commands.md#errors).

## What you actually gain: containing the tree

Everything above is convenience — the *reason* to switch is that `subprocess` and
`asyncio.subprocess` reach only the **direct child**. The processes *it* spawns (a
build tool's compilers, the real payload behind a `sh -c` wrapper, a test's helper
servers) survive a timeout, an exception, or a cancelled task and keep running as
orphans. `processkit` spawns every child into the operating system's own
containment primitive, so teardown is one kernel operation over the whole tree:

```python
from processkit import Command, ProcessGroup

with ProcessGroup() as group:
    group.start(Command("dev-server"))
    group.start(Command("worker"))
    # ... use them ...
# leaving the block reaps the whole tree — grandchildren included
```

Even a single one-shot verb gets this for free: `Command(...).output()` runs inside
a private group that dies with the call, and cancelling an awaited `aoutput()`
reaps its tree. On top of the guarantee you also get whole-tree **resource limits**
(memory / process-count / CPU caps) for sandboxing untrusted children — something
`subprocess` cannot express at all. See [Process groups](process-groups.md) and
[Resource limits](process-groups.md#resource-limits-the-sandbox).

## When to stay with `subprocess`

`processkit` earns its place when you run process *trees*, need them reaped
reliably, or want resource-limited sandboxes. If you only ever run leaf commands
that never spawn children of their own, don't need async cancellation to be
leak-safe, and want zero third-party dependencies, the stdlib is a perfectly good
choice — `processkit` is deliberately **not** a general `subprocess`-convenience
replacement. The wedge is the no-orphan guarantee.

---

Next: [Running commands](commands.md) · [Cookbook](cookbook.md)
