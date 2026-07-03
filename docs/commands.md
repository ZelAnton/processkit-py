# Running commands

[‹ docs index](README.md)

`Command` is the entry point of the runner layer: a builder that describes *what*
to run and *how*, plus a family of verbs that decide *what you get back*. Every
one-shot verb spawns the child into a fresh, private, kill-on-exit process tree,
so an early return, an exception, or a cancelled task can never leak a child.

- [The two surfaces: sync and async](#the-two-surfaces-sync-and-async)
- [Picking a verb](#picking-a-verb)
- [Program, arguments, working directory](#program-arguments-working-directory)
- [Environment and sandboxing](#environment-and-sandboxing)
- [Standard input](#standard-input)
- [Redirecting stdout and stderr](#redirecting-stdout-and-stderr)
- [Text decoding](#text-decoding)
- [Bounding captured output](#bounding-captured-output)
- [Timeouts](#timeouts)
- [Privileges and spawn flags](#privileges-and-spawn-flags)
- [Results](#results)
- [Errors](#errors)
- [Pipelines](#pipelines)

## The two surfaces: sync and async

The capture verbs come in two flavors: a **synchronous** one with a plain name,
and an **asyncio** one with the same name under an `a` prefix. They share the same
builder, the same result types, and the same no-orphan guarantee — pick whichever
fits the call site. (`start()` / `astart()` hand back a live `RunningProcess` for
streaming and interactive I/O — see [Streaming & interactive I/O](streaming.md).
That handle's *consuming* verbs (`wait` / `finish` / `output` / …) are async
coroutines, so the sync `start()` is mainly for spawning a scoped background child
you watch via its live properties and tear down with a `with` block.)

```python
from processkit import Command

head = Command("git", ["rev-parse", "HEAD"]).run()          # sync
head = await Command("git", ["rev-parse", "HEAD"]).arun()    # asyncio
```

The rest of this guide shows the sync form and only repeats the async form where
the behavior differs. A blocked synchronous call **on the main thread** is
interruptible by Ctrl+C: it raises `KeyboardInterrupt` and reaps the process tree
on the way out (off the main thread CPython can't deliver the signal — use the
async API or a `timeout()` there). *Deeper:
[Timeouts & cancellation](timeouts-and-cancellation.md).*

## Picking a verb

| Verb | Returns | Non-zero exit | Timeout / signal-kill | Use when |
|---|---|---|---|---|
| `output()` | `ProcessResult` | captured (`.code`) | captured (`.timed_out` / `.signal`) | You want to inspect the outcome yourself |
| `output_bytes()` | `BytesResult` | captured | captured | stdout is binary (images, archives) |
| `run()` | trimmed stdout `str` | raises `NonZeroExit` | raises `Timeout` / `Signalled` | "Give me the answer, or fail" |
| `exit_code()` | `int` (raw) | returns the code | raises (no `-1` sentinel) | The exit code *is* the answer |
| `probe()` | `bool` | `0`→`True`, `1`→`False`, else raises | raises | Predicate tools: `git diff --quiet`, `grep -q` |
| `start()` / `astart()` | `RunningProcess` | — | — | Streaming / interactive I/O — see [Streaming](streaming.md) |

The capturing verbs (`output`, `output_bytes`) treat a non-zero exit, a timeout,
and a signal-kill as **data** — they never raise on the child's outcome. The
checking verbs (`run`, `exit_code`, `probe`) turn those into exceptions. Async
twins: `aoutput`, `aoutput_bytes`, `arun`, `aexit_code`, `aprobe`, `astart`.

```python
result = Command("git", ["merge", "feature"]).output()
print(result.code, result.is_success, result.stdout)   # nothing raised
```

## Program, arguments, working directory

Arguments are a list — there is **no shell** between you and the child, so no
quoting, no word-splitting, and no injection surface. Build them up one at a time
or in bulk; `cwd` sets the working directory. The program, the arguments, and
`cwd` accept a `str` or any `os.PathLike[str]` (e.g. `pathlib.Path`) — so a `Path`
argument needs no `str()`. (`bytes` paths are not accepted.)

```python
from pathlib import Path

out = (
    Command("git")
    .arg("log")                       # one at a time...
    .args(["--oneline", "-n", "10"])  # ...or in bulk
    .cwd(Path("/srv/repo"))           # run there
    .run()
)
```

The program name reaches the OS verbatim: a bare name is resolved on `PATH` by
the OS, and `cwd` does **not** re-anchor a *relative* program path against the new
directory. Pass an absolute program path when you combine a relative tool with a
`cwd`.

## Environment and sandboxing

The environment builders compose, applied in a fixed order at spawn:

```python
# Mutate the inherited environment.
Command("worker").env("RUST_LOG", "debug").env_remove("HTTP_PROXY").run()
Command("worker").envs({"HOST": "127.0.0.1", "PORT": "8080"}).run()

# Allow-list: clear everything, then copy only the named parent variables.
Command("sandboxed-tool").inherit_env(["PATH", "HOME", "LANG"]).env("MODE", "ci").run()

# Scorched earth: the child starts with an empty environment.
Command("hermetic-tool").env_clear().env("PATH", "/usr/bin").run()
```

`inherit_env` is the sandboxing middle ground: it implies `env_clear`, then copies
the listed variables *from the parent at each spawn* (a re-run sees fresh values),
and repeated calls accumulate names. A name the parent doesn't have is skipped,
not set to empty. Explicit `env` / `env_remove` still apply on top.

## Standard input

By default stdin is **closed at spawn** — the child reads EOF immediately and can
never hang waiting for input. Feed a one-shot payload with `stdin_text` (a `str`)
or `stdin_bytes` (raw `bytes`):

```python
loud = Command("tr", ["a-z", "A-Z"]).stdin_text("hello\n").run()   # "HELLO"
Command("sha256sum").stdin_bytes(b"\x00\x01\x02").run()
```

The payload is written on a background task, so a large input can't deadlock
against the child's own output; the pipe is closed afterward to signal EOF.

For a conversational, request/response exchange — write a line, read the answer,
repeat — call `keep_stdin_open()` and drive the process through the streaming API
instead. *Deeper: [Streaming & interactive I/O](streaming.md).*

## Redirecting stdout and stderr

Each stream defaults to `"pipe"` (captured). You can also `"inherit"` the
parent's stream or send it to `"null"`:

```python
Command("long-build").stdout("inherit").stderr("inherit").start()
```

This matters: the one-shot capturing verbs (`output`, `output_bytes`, `run`,
`exit_code`, `probe`) need a piped stdout to do their job. If you set stdout to
`"inherit"` or `"null"`, those verbs **raise** — only `start()` / `astart()` plus
streaming work with a non-piped stdout, because there is nothing to capture. Redirect
streams only when you intend to stream or to discard.

## Text decoding

Output is decoded line by line, UTF-8 by default; invalid bytes become `U+FFFD`
rather than raising. Legacy-encoding tools can override per stream. Labels are
**WHATWG encoding labels** (as the web platform uses) — e.g. `"iso-8859-1"`,
`"windows-1252"`, `"windows-1251"`, `"shift_jis"`. Common **Python codec
aliases** are accepted too (`"latin_1"`, `"utf_8"`, `"euc_jp"`, …), normalized to
the WHATWG form. One caveat to know: WHATWG's `"iso-8859-1"` (and the Python
`"latin_1"` that maps to it) decodes as **windows-1252**, which differs from
strict ISO-8859-1 only in the `0x80`–`0x9F` range. The Windows ANSI code page
(`"mbcs"`/`"ansi"`) has no portable label — pass it explicitly (e.g.
`"windows-1251"`). An unmappable label raises `ValueError` naming the WHATWG form.

```python
out = Command("legacy-tool").encoding("shift_jis").output()        # both streams
out = Command("tool").stdout_encoding("iso-8859-1").output()       # ...or each its own
# .stderr_encoding(...) sets stderr independently
```

When stdout is genuinely binary, skip decoding entirely with `output_bytes()`
(below) instead of guessing an encoding.

## Bounding captured output

Captured lines are held in memory; a multi-gigabyte log would grow the buffer to
match. `output_limit` bounds *retention* — the pipe is always fully drained, so
the child never blocks on a full buffer.

```python
from processkit import Command, OutputTooLarge

# Keep only the most recent 1 MiB; older output is dropped (the default).
tail = Command("chatty-tool").output_limit(max_bytes=1024 * 1024).output()

# For an untrusted child, treat hitting the cap as a failure.
try:
    Command("untrusted-tool").output_limit(
        max_bytes=8 * 1024 * 1024, on_overflow="error"
    ).run()
except OutputTooLarge as e:
    print(e.total_bytes, e.max_bytes)
```

`on_overflow` is `"drop_oldest"` (keep the newest, the default), `"drop_newest"`
(freeze the head), or `"error"` (raise `OutputTooLarge`). To bound the parent's
**memory** against an untrusted child, cap `max_bytes`: a `max_lines`-only cap
does *not*, because one newline-free flood is a single, unbounded line. The cap
applies to line-captured output; the raw stdout from `output_bytes()` is never
line-capped — bound a flooding child there with a `timeout()` instead.

## Timeouts

```python
result = Command("slow-tool").timeout(5.0).output()   # result.timed_out is True on expiry
Command("slow-tool").timeout(5.0).run()               # raises Timeout on expiry

# Graceful shutdown: send a signal, wait, then hard-kill.
Command("server").timeout(30.0).timeout_signal("term").timeout_grace(5.0).run()
```

Durations are floats of seconds — never a duration object. `timeout` kills the
whole process tree at the deadline; on the capturing verbs the expiry is captured
(`ProcessResult.timed_out`), on the checking verbs it raises `Timeout`. The
signal name in `timeout_signal` is one of `term | kill | int | hup | quit | usr1
| usr2`. *Deeper: [Timeouts & cancellation](timeouts-and-cancellation.md).*

## Privileges and spawn flags

Spawn-time controls for sandboxing and service launch:

```python
# POSIX: drop privileges (groups and gid before uid) and detach.
(
    Command("worker")
    .gid(1000).groups([1000]).uid(1000)   # a correct drop sets all three
    .setsid()                             # new session: survives the controlling terminal
    .run()
)

# Windows: don't flash a console window from a GUI app.
Command("helper").create_no_window().run()

# Take the direct child down even if THIS process is killed before teardown runs.
Command("worker").kill_on_parent_death().start()
```

Platform honesty, not silent no-ops:

- `uid` / `gid` / `groups` / `setsid` are **POSIX-only**. On Windows the run
  raises `Unsupported` rather than silently skipping a privilege drop. A correct
  drop sets all three of `uid`/`gid`/`groups` — dropping the uid alone leaves the
  child holding the parent's (often root's) supplementary groups.
- `create_no_window` is a harmless no-op outside Windows.
- `kill_on_parent_death` is best-effort by design: kernel-guaranteed on Windows,
  `PR_SET_PDEATHSIG` on the direct child on Linux, a documented no-op on
  macOS/BSD. The graceful `with`-block teardown holds everywhere regardless.

processkit wires **pipes**, not a pseudo-terminal, so a tool that *demands* a tty
(an `ssh`/`sudo` password prompt) won't get one. Drive such tools
non-interactively — key-based auth, `ssh -o BatchMode=yes`,
`GIT_TERMINAL_PROMPT=0`, or a known answer fed over
[interactive stdin](streaming.md). *Deeper: [Platform support](platforms.md).*

## Results

The capturing verbs hand back a `ProcessResult`:

```python
r = Command("git", ["merge", "feature"]).output()

r.stdout            # str (decoded)
r.stderr            # str
r.code              # int | None — None means killed (timeout / signal), no code
r.signal            # int | None — the signal number on Unix, else None
r.is_success        # code is in success_codes (default {0})
r.timed_out         # the run's own deadline expired
r.program           # the program name, for diagnostics
r.duration_seconds  # wall-clock duration
r.truncated         # an output_limit cap dropped output
r.combined          # stdout + stderr concatenated (property)
```

`output_bytes()` returns a `BytesResult` with the same fields (minus `combined`,
which can't join `bytes` stdout with `str` stderr), except `stdout` is raw `bytes`
(stderr stays decoded `str`). On a `BytesResult`, `truncated` refers to **stderr**
only — the raw bytes stdout is never line-capped.

```python
png = Command("convert", ["in.png", "png:-"]).output_bytes().stdout   # bytes
```

By default the success set is `{0}`. `success_codes([...])` **replaces** it — list
every code you accept. It affects `run()` and `is_success`, but **not**
`exit_code()` (always the raw int) or `probe()` (always 0/1). An empty sequence
raises `ValueError` (it would accept nothing).

```python
# diff exits 1 when files differ; treat that as success, not a failure.
differs = not Command("diff", ["a.txt", "b.txt"]).success_codes([0, 1]).probe()
Command("grep", ["needle", "log"]).success_codes([0, 1]).run()   # 1 (no match) is OK
```

## Errors

Every exception derives from `ProcessError`. The checking verbs raise these; the
capturing verbs do not. Each carries **structured fields**, not just a message:

| Exception | Raised when | Fields |
|---|---|---|
| `NonZeroExit` | a checking verb saw a non-success exit code | `program`, `code`, `stdout`, `stderr` |
| `Timeout` | the run's deadline killed it | `program`, `timeout_seconds`, `stdout`, `stderr` |
| `Signalled` | the process was killed by a signal | `program`, `signal`, `stdout`, `stderr` |
| `ProcessNotFound` | the program couldn't be located / spawned | `program` |
| `PermissionDenied` | the program couldn't be spawned for lack of permission (e.g. a non-executable file) | `program` |
| `OutputTooLarge` | an `on_overflow="error"` cap was crossed | `program`, `max_lines`, `max_bytes`, `total_lines`, `total_bytes` |
| `ResourceLimit` | a memory / process / CPU cap was invalid or couldn't be enforced | — (reason is `str(exc)`) |
| `Unsupported` | the platform can't perform the requested operation | `operation` |

```python
from processkit import Command, NonZeroExit, Timeout, ProcessNotFound

try:
    Command("git", ["push"]).run()
except NonZeroExit as e:
    print(e.code, e.stderr)        # structured, not a parsed message
except Timeout as e:
    print(e.timeout_seconds)
except ProcessNotFound as e:
    print("missing:", e.program)
```

Three exceptions also derive from the builtin the stdlib raises for the same
condition, so familiar `except` clauses keep working: `Timeout` is also a
`TimeoutError` (as `asyncio.TimeoutError` is), `ProcessNotFound` is also a
`FileNotFoundError` (what `subprocess` raises), and `PermissionDenied` is also a
`PermissionError`. Note that cancelling an *awaited*
run via asyncio (`task.cancel()`, `asyncio.wait_for`, `asyncio.timeout`) surfaces
as `asyncio.CancelledError` and still reaps the tree.

### Secrets in diagnostics

`repr(Command(...))` is **redacted**: it shows the program, the argument *count*,
and env variable *names* — never argv values or env values. So a secret passed as
a flag or an `env(...)` value does **not** leak through a REPL echo, an `%r` log,
or a traceback frame.

The remaining channels carry raw values, so handle them with care:

- **Exception `stdout` / `stderr` fields carry the child's raw output verbatim**,
  and the exception *message* appends a **bounded last-line excerpt** of the
  captured output (stderr's last line, or stdout's when stderr is blank) — so if a
  tool echoes a token on failure, it can land in both. Don't forward exception
  text/fields to a low-trust log sink unredacted.
- **argv is visible to the OS** regardless of this library — any local user can
  read it via `ps` / `/proc/<pid>/cmdline` while the child runs. So for real
  secrets, prefer `env(...)` over a command-line flag: the env *value* is kept out
  of the `repr` and out of record/replay cassettes (only the variable name is
  recorded), and isn't exposed in the process listing.

## Pipelines

To connect stages `a | b | c` without a shell, use a `Pipeline` — either the `|`
operator or `.pipe()`. It runs to completion and exposes the same verbs:

```python
top = (Command("ps", ["aux"]) | Command("grep", ["python"])).run()
blob = (Command("cat", ["big.txt"]) | Command("gzip")).output_bytes().stdout
```

*Deeper: [Pipelines](pipelines.md).*

---

Next: [Streaming & interactive I/O](streaming.md) ·
[Process groups](process-groups.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Supervision](supervision.md) · [Testing your code](testing.md) ·
[Cookbook](cookbook.md) · [Platform support](platforms.md)
