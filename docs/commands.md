# Running commands

[‹ docs index](./)

`Command` is the entry point of the runner layer: a builder that describes *what*
to run and *how*, plus a family of verbs that decide *what you get back*. Every
one-shot verb spawns the child into a fresh, private, kill-on-exit process tree,
so an early return, an exception, or a cancelled task can never leak a child.

- [The two surfaces: sync and async](#the-two-surfaces-sync-and-async)
- [Picking a verb](#picking-a-verb)
- [Program, arguments, working directory](#program-arguments-working-directory)
- [Local program search](#local-program-search)
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
That handle's *consuming* verbs (`outcome`/`aoutcome`, `finish`/`afinish`,
`output`/`aoutput`, …) come in sync/async pairs too, like everywhere else in
this library — use whichever matches your code, regardless of whether the
handle came from `start()` or `astart()`.)

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

Read back what you built with the `program` / `arguments` properties (`arguments`,
not `args` — that name is already the builder method that *appends* args), or
render the whole thing as a single shell-quoted line with `command_line()` — for
display only (logs, error messages, a dry-run echo): it never invokes a shell,
and the escaping targets human legibility, not any shell's actual parsing rules.
Unlike the redacted `repr()`, `command_line()` **does** include argv, so render it
only into a sink you control.

```python
cmd = Command("login", ["--password", "hunter2"])
cmd.program              # "login"
cmd.arguments            # ["--password", "hunter2"]
cmd.command_line()       # "login --password hunter2" — includes the secret!
repr(cmd)                # redacted: shows arg COUNT, never values
```

## Local program search

Use `prefer_local(dir)` when a bare-name program should resolve from a project or
toolchain directory before falling back to the system `PATH`: for example
`node_modules/.bin`, `target/debug`, or a vendored tool directory. The directory
argument accepts `str` and `os.PathLike[str]`, like `cwd`.

```python
out = (
    Command("ruff")
    .prefer_local(Path(".venv/bin"))
    .prefer_local(Path("tools/bin"))
    .arg("--version")
    .run()
)
```

Repeated calls accumulate in priority order, so the first preferred directory is
searched first, then the next, then the normal `PATH`. The search reuses the same
platform behavior as `PATH` resolution, including `PATHEXT` on Windows.

`prefer_local` affects only bare-name programs such as `"ruff"` or `"cargo"`.
Path-form programs such as `"./ruff"`, `"tools/ruff"`, or an absolute path are
used as written. It also does not rewrite the child's own `PATH`; it only changes
how processkit finds the executable to spawn. If the program is not found, the
preferred directories are included in the failure diagnostics along with the
normal search locations.

Here is a self-contained example that creates two local tool directories and
prefers both before the system `PATH`:

```python
import os
import stat
import tempfile
from pathlib import Path

from processkit import Command

name = "demo-tool"


def write_tool(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True)
    if os.name == "nt":
        tool = directory / f"{name}.cmd"
        tool.write_text(f"@echo off\necho {text}\n", encoding="utf-8")
    else:
        tool = directory / name
        tool.write_text(f"#!/bin/sh\necho {text}\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


with tempfile.TemporaryDirectory() as tmp:
    project = Path(tmp)
    first = write_tool(project / "node_modules" / ".bin", "node tool")
    second = write_tool(project / "target" / "debug", "debug tool")

    # Search order for the bare name "demo-tool":
    #   1. ./node_modules/.bin
    #   2. ./target/debug
    #   3. the parent process PATH
    out = (
        Command(name)
        .cwd(project)
        .prefer_local(first.parent)
        .prefer_local(second.parent)
        .run()
    )
    assert out == "node tool"

    # The child still receives the inherited PATH unless you change it with
    # env(...). prefer_local only affects processkit's spawn-time lookup.
    assert str(first.parent) not in os.environ.get("PATH", "")

    # Path-form programs bypass prefer_local and are used exactly as written.
    assert Command(second).prefer_local(first.parent).run() == "debug tool"
    old_cwd = Path.cwd()
    os.chdir(project)
    try:
        assert (
            Command(f"target{os.sep}debug{os.sep}{second.name}")
            .prefer_local(first.parent)
            .run()
            == "debug tool"
        )
    finally:
        os.chdir(old_cwd)

    print(out)
```

## Preflight: is a program installed?

Sometimes you want to check that a tool is present *before* you run it — a
"doctor" subcommand, or a friendlier error than a spawn failure surfacing deep
in a workflow. `resolve_program()` locates the executable a run *would* spawn,
**without starting any process**:

```python
from processkit import Command, ProcessNotFound

try:
    path = Command("ruff").resolve_program()
    print(f"ruff is installed at {path}")
except ProcessNotFound as exc:
    print(f"ruff is not installed (searched: {exc.searched})")
```

The lookup reuses the **same** resolution the real launch performs — a bare name
against any `prefer_local()` directories first, then `PATH`, honoring `PATHEXT`
on Windows and the execute bit on Unix; a path-form program (`"./tool"`, an
absolute path) probed directly. So a hit is exactly what a spawn of the same
command would run, and a miss is exactly the `ProcessNotFound` it would raise —
`searched` diagnostic included. It also honors a relocated child `PATH`
(`env()` / `env_clear()` / `inherit_env()`), so the preflight never disagrees
with the actual spawn. It is synchronous and cheap (a few `stat`s); there is no
`a`-prefixed async twin, because no runtime is involved.

For a one-off check against the process `PATH`, the module-level `which()` is
shorthand for `Command(program).resolve_program()`:

```python
import processkit

interpreter = processkit.which("python3")   # absolute path, or raises ProcessNotFound
print(interpreter)
```

A `CliClient` offers the same preflight for the tool it wraps, with the client's
defaults (including a `default_env` that relocates `PATH`) applied:

```python
from processkit import CliClient, ProcessNotFound

client = CliClient("git")
try:
    client.resolve_program()   # is git installed, per this client's config?
except ProcessNotFound:
    raise SystemExit("git is required but was not found")
```

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

For a large input already sitting in a file — a database dump piped into `psql`,
an archive fed to `tar`, a multi-gigabyte log run through a filter — use
`stdin_file(path)` instead of reading the file into Python `bytes` yourself. The
file streams straight to the child's stdin in chunks, so it never has to fit in
Python memory:

```python
Command("psql", ["mydb"]).stdin_file("dump.sql").run()
Command("tar", ["-xf", "-"]).stdin_file("archive.tar").cwd("/tmp/extract").run()
```

`stdin_file()` doesn't touch the filesystem when you call it — the path is
opened lazily when the command actually spawns, so a not-yet-existing path is
not an error there. If the file turns out to be missing or unreadable once the
command runs, that surfaces as a generic `ProcessError` from the run/output
verb (not `FileNotFoundError`), since the child process has, by then, already
spawned successfully.

For a conversational, request/response exchange — write a line, read the answer,
repeat — call `keep_stdin_open()` and drive the process through the streaming API
instead. *Deeper: [Streaming & interactive I/O](streaming.md).*

To let the child read the parent's **own** stdin directly — the real terminal, a
file, or a pipe this process was launched with — call `inherit_stdin()`. It is
the stdin counterpart of `stdout("inherit")`: the child *shares* the parent's
stream instead of the crate mediating it. Use it when the child must reach the
real terminal — `git commit` opening `$EDITOR`, a tool prompting for a password
or a yes/no confirmation, or forwarding a shell pipeline's stdin straight
through:

```python
# The editor opens on the real terminal; the crate doesn't touch stdin.
Command("git", ["commit"]).inherit_stdin().run()
```

The crate neither feeds nor captures that input, so there is no writer to
`take_stdin()` — but stdout/stderr are untouched, so `run()` / `output()` still
return the child's captured stdout as usual. `inherit_stdin()` is **mutually
exclusive** with any *mediated* stdin: a `stdin_bytes()` / `stdin_text()` /
`stdin_file()` source, or `keep_stdin_open()`. A child either reads the parent's
stdin or has its stdin driven by the crate, not both. Building the conflicting
combination does not raise; the contradiction is rejected as a `ProcessError`
from the run/output verb when the command actually **launches**, not when you
build the `Command` (the same guard fires on the test doubles too — see
[Interactive stdin](streaming.md#interactive-stdin)).

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

### Redirecting a stream straight to a file

To send a stream *directly* to a file — the child writes to the file's own
descriptor, with no parent-side pump or capture in between — use `stdout_file()`
/ `stderr_file()`. This is the direct-redirect cousin of `stdout_tee()`: the tee
*also* captures and mirrors every decoded line, while these simply hand the child
the file (a `>` / `>>` shell redirect, minus the shell). `append=False` (the
default) creates or **truncates** the file on each spawn; `append=True` creates
or **appends** — the mode for a shared log across `Supervisor` incarnations or
`retry()` attempts, which write to one file with no separator.

```python
from processkit import Command, Supervisor

# Truncate a fresh file on each spawn (the default).
with Command("build", ["--all"]).stdout_file("build.log").start() as proc:
    proc.outcome()

# Append across restarts — one shared log for every Supervisor incarnation.
Supervisor(
    Command("worker").stdout_file("worker.log", append=True).stderr_file("worker.log", append=True)
).run()
```

Unlike `stdout_tee()`, the file is opened **at spawn time**, not when you build
the command — so a not-yet-existing path is not an error here, and each re-run or
retry reopens it. An unopenable path (a missing parent directory, a permission
denial) surfaces from the run verb when the command launches.

Because a file-redirected **stdout** has no pipe for the parent to read, the
verbs that actually read stdout back — `output()`, `run()`, `output_bytes()`
(and their `a`-twins), plus `start()` + `stdout_lines()` / `output_events()` —
**raise** the same "not piped" `ProcessError` as `stdout("null")`. `exit_code()`
and `probe()` are *not* capture verbs: they discard output entirely and never
touch the stdout pipe, so they work fine with a file-redirected stdout — they
(and their async twins `aexit_code()` / `aprobe()`) are the recommended way to
drive such a command to completion, alongside `start()` + `outcome()` /
`aoutcome()` (as the example above does). A file-redirected **stderr** leaves
stdout piped, so `output()` keeps working there; the child's stderr just lands
in the file and `result.stderr` comes back empty. A later `stdout(...)` /
`stderr(...)` call **clears** the redirect and restores the normal stdio mode,
so the builder chain stays composable.

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
does *not*, because one newline-free flood is a single, unbounded line. A
`max_lines` cap applies to line-captured output only — raw bytes have no line
count, so it never bounds the stdout of `output_bytes()`. A `max_bytes` cap
applies to *both* that line-captured output **and** the raw stdout of
`output_bytes()` / `aoutput_bytes()` (since processkit 2.1.0 — earlier the byte
ceiling bounded only the line-pumped stderr and raw stdout was always unbounded).
Over the byte cap an `output_bytes()` run either raises `OutputTooLarge` (with
`max_lines=None`) under `on_overflow="error"`, or keeps a bounded head/tail with
`BytesResult.truncated` set under a drop mode.

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
| usr2`, or a raw platform signal number (an `int`, POSIX only — Windows raises
`Unsupported` for anything but a hard kill, same as the named variants).
*Deeper: [Timeouts & cancellation](timeouts-and-cancellation.md).*

`no_timeout()` runs without a deadline, and — unlike simply never calling
`timeout()` — also opts out of a `CliClient`'s `default_timeout` gap-fill
(useful for the one deliberately unbounded call — a `tail -f`, a watch loop —
against a client that otherwise imposes a deadline on every call). Whichever
of `timeout()` / `no_timeout()` you call **last** wins.

## Retrying a run

```python
Command("flaky-fetch").retry(
    "transient_or_timeout",       # or "transient" — see below
    max_retries=3,                # up to 4 total attempts (default)
    initial_backoff=0.1,          # seconds before the first retry (default)
    multiplier=2.0,                # exponential growth per retry (default)
    max_backoff=30.0,             # cap on a single delay (default)
    jitter=True,                  # spread the wait over [0, delay] (default)
).run()
```

Honored only by the success-checking verbs (`run`/`exit_code`/`probe`) — the
non-erroring `output()`/`output_bytes()` never retry, since they never raise
in the first place. `retry_if` is a named preset over the error-classification
accessors, not an arbitrary predicate: `"transient"` covers a bare-retry-clears
spawn/IO condition (interrupted, would-block, a busy resource);
`"transient_or_timeout"` also retries a `.timeout()` expiry. Each attempt
**re-executes the whole command from scratch** — only retry operations safe to
repeat (a `git push` that already reached the server, then dropped the
connection, will be replayed if retried). A one-shot `stdin_bytes()`/
`stdin_text()` source can't survive a retry, so a command built with one is
never retried at all. Ignored by `Supervisor` (its own restart policy governs
keep-alive restarts — a different concern), `output_all`, and `Pipeline`.

`CliClient` has the same knobs, prefixed `default_` (`default_retry_if=`,
`default_max_retries=`, …) — `default_retry_if` is the required opt-in gate;
setting a tuning knob without it raises `ValueError`.

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

# Windows: give a console child a CTRL_BREAK to shut down cleanly before the hard kill.
Command("service").windows_graceful_ctrl_break().timeout(30.0).timeout_grace(5.0).run()

# Take the direct child down even if THIS process is killed before teardown runs.
Command("worker").kill_on_parent_death().start()

# Ask what scope that hardening actually reaches on THIS platform (build-time
# fixed; no prior kill_on_parent_death() needed).
scope = Command.kill_on_parent_death_scope()  # "whole_tree" | "direct_child_only" | "unsupported"
```

Platform honesty, not silent no-ops:

- `uid` / `gid` / `groups` / `setsid` are **POSIX-only**. On Windows the run
  raises `Unsupported` rather than silently skipping a privilege drop. A correct
  drop sets all three of `uid`/`gid`/`groups` — dropping the uid alone leaves the
  child holding the parent's (often root's) supplementary groups.
- `create_no_window` is a harmless no-op outside Windows.
- `windows_graceful_ctrl_break` is a **Windows-only opt-in**: at a graceful
  timeout (`timeout_grace`) or a group shutdown it sends the direct console
  child a `CTRL_BREAK` before the grace window, so a child that handles it can
  exit cleanly before the hard `TerminateJobObject` fallback (Windows otherwise
  has no soft-signal tier). Console-only — inert under `create_no_window` /
  detached, and it delivers `CTRL_BREAK`, not `CTRL_C`. A harmless no-op outside
  Windows (Unix's graceful tier already sends a real signal), like
  `create_no_window` — not one of the POSIX-only knobs that raise `Unsupported`.
- `kill_on_parent_death` is best-effort by design: kernel-guaranteed on Windows,
  `PR_SET_PDEATHSIG` on the direct child on Linux, a documented no-op on
  macOS/BSD. The graceful `with`-block teardown holds everywhere regardless.
  `Command.kill_on_parent_death_scope()` reports that reach programmatically —
  `"whole_tree"` on Windows, `"direct_child_only"` on Linux, `"unsupported"` on
  macOS/BSD — so you can read the *actual* abrupt-death scope instead of trusting
  the prose caveat. It is a static capability query fixed at build time: it needs
  no prior `kill_on_parent_death()` call (read it off the class or any instance)
  and describes only abrupt owner death — graceful teardown still kills the whole
  tree everywhere.

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
(stderr stays decoded `str`). On a `BytesResult`, `truncated` is set when an
`output_limit` cap dropped output — the line-captured stderr under any cap, and
(since processkit 2.1.0) the raw bytes stdout too when a `max_bytes` ceiling bounds
it to a head/tail. A `max_lines` cap never truncates raw stdout (bytes have no line
count); only a `max_bytes` cap does.

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
capturing verbs do not (call `ProcessResult.ensure_success()` /
`BytesResult.ensure_success()` on an already-captured result to raise the same
exception after the fact — it returns `self` unchanged on success, so it
composes: `cmd.output().ensure_success().stdout`). Each carries **structured
fields**, not just a message:

| Exception | Raised when | Fields |
|---|---|---|
| `NonZeroExit` | a checking verb saw a non-success exit code | `program`, `code`, `stdout`, `stderr`, `stdout_bytes` (`bytes \| None`), `diagnostic` |
| `Timeout` | the run's deadline killed it | `program`, `timeout_seconds`, `stdout`, `stderr`, `stdout_bytes` (`bytes \| None`), `diagnostic` |
| `Signalled` | the process was killed by a signal | `program`, `signal`, `stdout`, `stderr`, `stdout_bytes` (`bytes \| None`), `diagnostic` |
| `ProcessNotFound` | the program couldn't be located / spawned | `program` |
| `PermissionDenied` | the program couldn't be spawned for lack of permission (e.g. a non-executable file), or a permission-denied OS error surfaced from elsewhere in the run (e.g. a group signal the OS refused) | `program` (`str \| None` — `None` for the broader "refused OS operation" case, where no program is being named) |
| `OutputTooLarge` | an `on_overflow="error"` cap was crossed | `program`, `max_lines`, `max_bytes`, `total_lines`, `total_bytes` |
| `ResourceLimit` | a memory / process / CPU cap was invalid or couldn't be enforced | — (reason is `str(exc)`) |
| `Unsupported` | the platform can't perform the requested operation | `operation` |
| `Cancelled` | a wired `CancellationToken` fired | `program` |

`diagnostic` (on the three stream-bearing exceptions) is the best human-facing
message — captured stderr if it carries text, otherwise captured stdout,
`None` if both streams are blank — so a generic `except ProcessError` handler
can log something useful without knowing which of the three it caught.

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
`PermissionError`. Cancelling an *awaited* run via asyncio (`task.cancel()`,
`asyncio.wait_for`, `asyncio.timeout`) surfaces as `asyncio.CancelledError`
instead of raising `Cancelled` (that's for an explicit `CancellationToken` wired
with `.cancel_on()`) — either way the tree is reaped.
*Deeper: [Timeouts & cancellation](timeouts-and-cancellation.md).*

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
