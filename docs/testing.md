# Testing your code

[‹ docs index](README.md)

Code that shells out is miserable to test — unless the subprocess sits behind a
seam. In **processkit-py** that seam is a plain object: a *runner*. Write your
code against a `runner` parameter, call its verbs, and never name a concrete
runner inside the logic. In production you pass `Runner()` — the real thing. In
tests you pass a double — a `ScriptedRunner` with canned replies, a replaying
`RecordReplayRunner`, a `RecordingRunner` spy, or a `DryRunRunner` that only
renders each command — and no subprocess is ever spawned. The objects that come
back are genuine `ProcessResult` / `RunningProcess` values, so the code under
test can't tell the difference.

> The doubles — `ScriptedRunner`, `RecordReplayRunner`, `RecordingRunner`,
> `DryRunRunner`, the `Reply` builder, and the `Invocation` record — live in the
> **`processkit.testing`** submodule (mirroring the crate's own
> `processkit::testing` split). `Runner` and the `ProcessRunner` protocol stay
> on the top-level `processkit` — they are production code, not test
> scaffolding.

- [The runner seam](#the-runner-seam)
- [The pytest plugin: ready-made fixtures](#the-pytest-plugin-ready-made-fixtures)
- [Scripting replies: ScriptedRunner](#scripting-replies-scriptedrunner)
- [Scripted streaming: a live handle, no child](#scripted-streaming-a-live-handle-no-child)
- [Record/replay cassettes: RecordReplayRunner](#recordreplay-cassettes-recordreplayrunner)
- [Asserting on calls: RecordingRunner](#asserting-on-calls-recordingrunner)
- [Rendering commands without running: DryRunRunner](#rendering-commands-without-running-dryrunrunner)
- [Wrapping a CLI tool: CliClient](#wrapping-a-cli-tool-cliclient)

## The runner seam

`Runner()` is the real implementation; every double exposes the **same verb
surface**, so swapping one in is the whole technique. Each verb takes a
`Command` and returns the same type the bare `Command` methods do:

| Sync | Async | Returns | Notes |
|---|---|---|---|
| `output(cmd)` | `aoutput(cmd)` | `ProcessResult` | full result; a non-zero exit is *data*, not a raise |
| `output_bytes(cmd)` | `aoutput_bytes(cmd)` | `BytesResult` | raw-bytes stdout |
| `run(cmd)` | `arun(cmd)` | `str` | trimmed stdout; raises on failure |
| `exit_code(cmd)` | `aexit_code(cmd)` | `int` | the raw exit code |
| `probe(cmd)` | `aprobe(cmd)` | `bool` | exit 0 as a boolean |
| `start(cmd)` | `astart(cmd)` | `RunningProcess` | a live handle for streaming / readiness probes |

Write production code against the seam; hand it the real runner there:

```python
from processkit import Command, ProcessRunner, Runner

def current_branch(runner: ProcessRunner) -> str:
    return runner.run(Command("git", ["branch", "--show-current"]))

# Production: the real runner, which actually spawns git.
branch = current_branch(Runner())
```

Annotate the injected runner as **`ProcessRunner`** — a `typing.Protocol` that
describes the verb surface. `Runner`, `ScriptedRunner`, `RecordReplayRunner`,
`RecordingRunner`, and `DryRunRunner` all satisfy it structurally, so the
annotation type-checks (strict `mypy`) against any of them. A custom double can implement the capture/check verbs directly; the
streaming `start`/`astart` verbs must return a `RunningProcess` (no public
constructor), so reach for `ScriptedRunner` when you need a streaming double rather
than building one from scratch. `CliClient` is also a `ProcessRunner`: its sync
and async capture/check verbs accept either per-call `Args` (combined with its
bound program) or a `Command` (whose explicit settings win over client
defaults). It is not a `StreamingRunner`, because it has no `start`/`astart`.

The sync and async surfaces are twins (`run` ↔ `arun`), so async code injects
the very same runner objects and awaits the `a`-prefixed verbs.

> These doubles are the *real* ones — they return genuine `ProcessResult` /
> `RunningProcess` objects, so the code under test behaves identically. (The Rust
> crate also ships a `mock` Cargo feature — a `mockall`-generated mock of its
> runner trait — but that is for *Rust* tests; it has no Python use, so the binding
> does not enable it. You get your doubles here, not from a mocking library.)

*Deeper: the verb vocabulary and what each return type carries — [Running commands](commands.md).*

## The pytest plugin: ready-made fixtures

Installing processkit registers a **pytest plugin** — a `pytest11` entry point,
autoloaded in every pytest session, with nothing to add to your `conftest.py`. It
turns the doubles above into fixtures, so wiring one into a test is a single
parameter rather than a line of construction. Each fixture yields one of the
doubles below, so it satisfies the same `ProcessRunner` seam and spawns no real
process:

| Fixture | Yields | Notes |
|---|---|---|
| `scripted_runner` | a fresh [`ScriptedRunner`](#scripting-replies-scriptedrunner) | teach it replies with `.on()` / `.when()` / `.fallback()` |
| `recording_runner` | a [`RecordingRunner`](#asserting-on-calls-recordingrunner) spy | replies `Reply.ok("")` (a clean exit 0, empty stdout — the neutral default) to every call and records each one |
| `record_replay_runner` | a [`RecordReplayRunner`](#recordreplay-cassettes-recordreplayrunner) cassette | replay by default, record on demand — see below |

```python
from processkit import Command
from processkit.testing import Reply

def latest_commit(runner):
    return runner.run(Command("git", ["rev-parse", "HEAD"]))

def test_latest_commit(scripted_runner):
    scripted_runner.on(["git", "rev-parse"], Reply.ok("deadbeef"))
    assert latest_commit(scripted_runner) == "deadbeef"     # no git spawned
```

### The cassette fixture: record ↔ replay

`record_replay_runner` binds a [cassette](#recordreplay-cassettes-recordreplayrunner)
to the test. Which way it runs is a **switch, off (replay) by default** so CI
never spawns by accident — chosen the way vcr-like tools do it, in precedence
order:

1. `pytest --processkit-record` (CLI flag) forces **record** mode; otherwise
2. the `PROCESSKIT_RECORD` environment variable, when set, decides by its
   truthiness (`1`/`true`/`yes`/`on` → record); otherwise
3. the `processkit_record` ini option (a bool) decides; defaulting to **replay**.

In record mode the cassette is captured against real processes and `save()`d on
teardown; in replay mode it is served offline, never spawning. The file lives
under the test's `tmp_path` by default — set the `processkit_cassette_dir` ini
option (a relative path resolves against the rootdir) to a committed fixtures
directory to **keep** cassettes across runs. Its name is derived deterministically
from the test's node id, so each test gets its own.

The workflow is the usual vcr one — *record once, replay forever*:

```ini
# pytest.ini (or [tool.pytest.ini_options] in pyproject.toml)
[pytest]
processkit_cassette_dir = tests/cassettes
```

```python
import sys
from processkit import Command

def test_offline(record_replay_runner):
    # `pytest --processkit-record` once: spawns for real and writes the cassette.
    # Every run after: served from tests/cassettes/…json, no process spawned.
    out = record_replay_runner.run(Command(sys.executable, ["--version"]))
    assert out.startswith("Python")
```

> Cassettes store `program`/`args`/`cwd`/`stdout`/`stderr` **verbatim** and can
> carry secrets — review one before committing it (see
> [Record/replay cassettes](#recordreplay-cassettes-recordreplayrunner) for the
> full semantics and the redaction boundary).

### The no-real-spawn guard

Mark a test `@pytest.mark.no_real_spawn` and any **real** process spawn through
`Command` / `Pipeline` / `Runner` / `ProcessGroup` inside it fails loudly (via
`pytest.fail`, which no `except` in the code under test can swallow) — so a
forgotten double can't quietly reach the OS:

```python
import pytest
from processkit import Command

@pytest.mark.no_real_spawn
def test_stays_hermetic(scripted_runner):
    scripted_runner.fallback(Reply.ok("ok"))
    assert my_code(scripted_runner) == "ok"   # injected double: fine
    # Command("git", ["status"]).run()        # would fail the test, loudly
```

The marker is registered by the plugin, so it passes `--strict-markers`. Injected
doubles keep working — only the real-spawn primitives are blocked. The interception
replaces those verbs on the compiled classes for the duration of the test (the
reliable seam, since PyO3 forbids subclassing or per-instance patching of them),
which catches a spawn even through a `Command` reference imported before the test
ran. The honest boundary: the injection-point APIs (`CliClient`, `output_all` and
friends, `Supervisor`) reach the OS entirely inside the Rust extension when given
the default real runner, with no Python seam to intercept — so pass them a
test-double `runner=` in a guarded test rather than relying on the guard to catch
their default path.

## Scripting replies: ScriptedRunner

`ScriptedRunner` is the work-horse double: it returns a canned `Reply` for each
command you teach it. Match rules with `.on(prefix, reply)`; add an optional
`.fallback(reply)` for everything else.

```python
from processkit import Command
from processkit.testing import Reply, ScriptedRunner

def current_branch(runner):
    return runner.run(Command("git", ["branch", "--show-current"]))

def test_detects_the_branch():
    runner = ScriptedRunner()
    # Match by program + argument PREFIX (element-wise; the program is the first
    # element). Rules are tried in registration order; first match wins.
    runner.on(["git", "branch", "--show-current"], Reply.ok("main\n"))
    runner.fallback(Reply.ok(""))            # optional catch-all
    assert current_branch(runner) == "main"
```

Build the canned outcomes with the `Reply` factories:

- **`Reply.ok(stdout)`** — exit 0 with this stdout.
- **`Reply.fail(code, stderr)`** — a non-zero exit; `run` / `exit_code` raise `NonZeroExit`, while `output` reports it as data.
- **`Reply.lines([...])`** — exit 0 with the lines joined (and streamed one-by-one on a scripted [`start`](#scripted-streaming-a-live-handle-no-child)).
- **`Reply.timeout()`** — a timed-out run; `run` and the checking verbs raise `Timeout`.
- **`Reply.signalled(signal=None)`** — a signal-killed run; `run` raises `Signalled`.
- **`Reply.pending()`** — parks the call like a hung child; pair it with `asyncio.wait_for` / a `Command.timeout()` to prove your orchestration actually cancels a blocked call.
- **`.with_stdout(text)`** — an instance method that attaches stdout to any reply (e.g. the `CONFLICT …` text git prints on a *failing* merge).
- **`.with_line_delay(seconds)`** — sleep `seconds` before each scripted stdout line on a `start()`/`astart()` run, so a hermetic streaming test can observe genuinely incremental delivery instead of every line arriving at once.

Prefix matching is element-wise over the program name then the arguments, so
`on(["git", "branch"])` matches `git branch --show-current` but not `git
branchx` (and not `hg branch`). An **unmatched command with no fallback raises
a plain `ProcessError`** (not `ProcessNotFound`/`FileNotFoundError` — a miss is
a scripting gap, not a missing *program*) — loud enough that an unexpected
invocation can't slip through a test silently, but distinguishable from a
genuinely missing binary.

Reply each of several successive calls in turn with **`.on_sequence(prefix,
replies)`** — the declarative form for "fail once, then succeed" retry
scenarios: the first matching call gets `replies[0]`, the second `replies[1]`,
and so on; once exhausted, the **last** reply repeats forever.

```python
runner = ScriptedRunner()
runner.on_sequence(["deploy"], [Reply.fail(1, "transient"), Reply.ok("deployed")])
```

For a match that isn't a plain argv prefix, **`.when(predicate, reply)`**
replies with `reply` when `predicate(command)` accepts it — inspecting
`command.cwd`/`command.arguments`/whatever `Command`'s own inspection
accessors expose:

```python
runner = ScriptedRunner()
runner.when(lambda cmd: "--dangerous" in cmd.arguments, Reply.fail(1, "blocked"))
runner.fallback(Reply.ok(""))
```

`predicate` is infallible from the crate's perspective, like
`Supervisor.stop_when`: a raising or non-`bool` predicate is treated as "does
not match" rather than propagating, with the error surfaced via
[`sys.unraisablehook`](https://docs.python.org/3/library/sys.html#sys.unraisablehook)
(visible on stderr) so a buggy predicate is noisy, not silently wrong.

*Deeper: outcome semantics and the exception hierarchy — [Running commands](commands.md).*

## Scripted streaming: a live handle, no child

`ScriptedRunner.start(cmd)` (and `astart`) returns a real `RunningProcess`
backed by the canned reply instead of an OS child. The scripted stdout flows
through the **same line pumps** a real child uses, so `stdout_lines()`,
readiness probing, and `finish()` all behave identically — letting you test a
readiness-gate orchestration hermetically:

```python
import asyncio
from processkit import Command
from processkit.testing import Reply, ScriptedRunner

async def becomes_ready(runner):
    proc = runner.start(Command("server", ["serve"]))
    async for line in proc.stdout_lines():
        if "listening" in line:
            break
    return (await proc.afinish()).exited_zero

def test_server_becomes_ready():
    runner = ScriptedRunner()
    runner.on(["server", "serve"], Reply.lines(["booting", "listening on 8080"]))
    assert asyncio.run(becomes_ready(runner))   # satisfied by the canned banner
```

`Reply.lines([...])` scripts the stdout lines and the scripted run "exits" after
the last one; `Reply.pending()` scripts a run that never ends on its own (bound
it with the command's own `timeout()`). The honest boundary: a scripted handle
has no OS identity — `pid` is `None` and `profile` reports empty samples — so it
tests orchestration logic, not real I/O timing.

*Deeper: the live streaming surface (`stdout_lines`, `output_events`, `take_stdin`) — [Streaming & interactive I/O](streaming.md).*

## Record/replay cassettes: RecordReplayRunner

`RecordReplayRunner` closes the loop: capture real runs to a JSON *cassette*
once, then replay them offline — fast, deterministic, no subprocess in CI. It
shares the `Runner` verb surface, so it drops into the same seam.

```python
from processkit import Command
from processkit.testing import RecordReplayRunner

CMD = Command("python", ["-c", "import random; print(random.random())"])

# Record once against the real tool (an opt-in test run, say):
rec = RecordReplayRunner.record("fixtures/random.json")   # records via the real Runner
recorded = rec.run(CMD)                                    # spawns python once, captures it
rec.save()                                                 # write the cassette to disk

# Replay everywhere else — NEVER spawns:
rep = RecordReplayRunner.replay("fixtures/random.json")
assert rep.run(CMD) == recorded
```

That last assertion is the **no-respawn proof**: the recorded command prints a
fresh random number every real run, so if replay equals the recorded value,
nothing was spawned. (This is exactly how our suite proves it.)

`start()` is covered too: the cassette records a streamed run (capture-whole — the
child runs to completion, then the handle replays its captured lines through a real
`RunningProcess`) and replays it offline, so a readiness-gated `start` flow tests
hermetically. Two limits: an *interactive* run fed stdin mid-stream can't be
cassette-recorded (bound it with `Command.timeout()`, or script it with
`ScriptedRunner`); and **`output_bytes` is not supported through a cassette** — it
stores lossy-UTF-8 *text*, so it can't reproduce exact bytes and raises
`Unsupported` (capture bytes from a real or scripted runner instead).

Semantics worth knowing before you commit a cassette:

| Aspect | Behavior |
|---|---|
| Match key | program + args + cwd + a stdin **source digest** |
| Environment | override **values never reach the file** — only sorted variable names; env is *not* matched, so env differences can't cause spurious misses |
| Duplicates of one key | replayed in capture order, then the **last entry repeats** — a changing sequence (`rev-parse HEAD` before/after a commit) replays faithfully, while a retry/probe loop keeps getting a stable final answer |
| Miss | an invocation **absent from the cassette is a strict error** — replay never spawns a surprise subprocess, so a stale cassette fails loudly |

Only env **values** are redacted. `program`, `args`, `cwd`, `stdout`, and
`stderr` are stored **verbatim** and can carry secrets — a `--password=…` flag,
a token echoed to output — so **review a fixture before committing it**, and
keep secret-bearing cassettes out of shared trees. (`save()` writes the file
owner-only — `0600` on Unix — and refuses to follow a symlink, so a fresh
cassette isn't world-readable; the review is still on you before *committing* it.)

Record from a single thread. The capture buffer is per-runner; recording the same
`RecordReplayRunner` from several threads at once (only possible on a free-threaded
build) can interleave entries non-deterministically. Replay is read-only and has no
such constraint.

*Deeper: how a `ProcessResult` is shaped before it's captured — [the Cookbook](cookbook.md).*

## Asserting on calls: RecordingRunner

`RecordingRunner` is the *spy*: it replies to every command with one canned
`Reply` and records each call, so a test can assert on **what** your code ran —
not just react to a reply. It shares the `Runner` verb surface.

```python
from processkit import Command
from processkit.testing import RecordingRunner, Reply


def deploy(runner) -> None:
    runner.run(Command("git", ["push", "--tags"]))


def test_deploy_pushes_tags() -> None:
    runner = RecordingRunner.replying(Reply.ok(""))
    deploy(runner)

    inv = runner.only_call()            # the one call (raises unless exactly one)
    assert inv.program == "git"
    assert inv.args == ["push", "--tags"]
    assert inv.has_flag("--tags")
```

- **`replying(reply)`** — every command gets `reply`, built with the same `Reply`
  factories as `ScriptedRunner`.
- **`new(inner)`** — wrap `inner` (any of `Runner`, `ScriptedRunner`,
  `RecordReplayRunner`, or another `RecordingRunner`), recording every call
  made through it. The general form behind `replying()`, for combining
  recording with a double you've already built (e.g. a `RecordReplayRunner`
  cassette, or a `ScriptedRunner` with several `.on()` rules already wired
  up) instead of a fresh runner that just replies with one canned `Reply`.
- **`calls()`** — every recorded `Invocation`, in call order.
- **`only_call()`** — the single invocation, or a `ProcessError` if there wasn't
  exactly one.

Each `Invocation` exposes `program`, `args`, `cwd`, `env` (a `dict[str, str |
None]`; a `None` value is an `env_remove`), `has_stdin`, and a `has_flag(flag)`
helper. The values are there for your assertions, but its `repr` is **redacted**
(program, arg count, cwd, env names, has_stdin — never argv or env values), like
`Command`'s — a failing assertion that prints the invocation won't leak a
secret-bearing flag.

Reach for `RecordingRunner` when the *call* is what matters (did my code push the
tags?); for canned per-command replies use
[`ScriptedRunner`](#scripting-replies-scriptedrunner), and to replay real output
offline use [`RecordReplayRunner`](#recordreplay-cassettes-recordreplayrunner).

## Rendering commands without running: DryRunRunner

`DryRunRunner` is the double behind a tool's own `--dry-run`/`--echo` mode: it
never spawns anything, renders each command to its display-quoted line, and
returns a synthetic success. There is nothing to script — a dry run has no real
output to fake, only a command line to show — so every call just succeeds
(empty stdout; an exit code drawn from the command's own `success_codes`, so
the checking verbs stay in agreement even for a command whose accepted set
excludes `0`). It shares the `Runner` verb surface, so it drops into the same
seam.

```python
from processkit import Command
from processkit.testing import DryRunRunner

def prune(runner) -> None:
    runner.run(Command("rm", ["-rf", "build"]))
    runner.run(Command("rm", ["-rf", "dist"]))

def test_prune_targets_the_right_dirs() -> None:
    runner = DryRunRunner()
    prune(runner)                                    # nothing spawned
    assert runner.commands() == ["rm -rf build", "rm -rf dist"]
```

- **`commands()`** — the rendered command line of every call so far, in order,
  each produced by [`Command.command_line()`](commands.md) (the same display
  quoting you'd reach for by hand).
- **`only_command()`** — the single rendered line, or a `ProcessError` if there
  wasn't exactly one call (like `RecordingRunner.only_call()`).
- **`on_invocation(callback)`** — call `callback(line)` with each rendered line
  *as the call happens* — e.g. to print the echo live for a real `--dry-run`
  flag — **in addition to** the collected `commands()` snapshot. The callback is
  a fire-and-forget side effect: a raising one is surfaced via
  [`sys.unraisablehook`](https://docs.python.org/3/library/sys.html#sys.unraisablehook)
  rather than derailing the run it was only observing.

```python
runner = DryRunRunner()
runner.on_invocation(print)          # echo each command as it's "run"
deploy_plan(runner)                  # prints: kubectl apply -f manifest.yaml, …
```

Reach for `DryRunRunner` when the rendered *command line* is what you want to
assert on (or echo), with no reply to script and no output to replay — the
`--dry-run` seam. When a call needs a specific canned outcome, use
[`ScriptedRunner`](#scripting-replies-scriptedrunner); when you also need the
structured call record (cwd/env/stdin), use
[`RecordingRunner`](#asserting-on-calls-recordingrunner).

## Wrapping a CLI tool: CliClient

`CliClient` binds a program to per-call defaults, so repeated calls usually
pass only their `Args`. Every sync and async capture/check verb (`run`,
`output`, `output_bytes`, `exit_code`, `probe`, plus the `a`-prefixed twins)
accepts `Args | Command`: args are combined with the bound program and client
defaults; a `Command` can carry per-call customization, whose explicit settings
win over client defaults. This broader input type makes `CliClient` a valid
`ProcessRunner` implementation. It is not a `StreamingRunner`, because it does
not provide `start`/`astart`:

```python
from processkit import CliClient

git = CliClient("git", default_timeout=30.0)
head = git.run(["rev-parse", "HEAD"])        # or: await git.arun([...])
clean = git.probe(["diff", "--quiet"])
git.run(["fetch", "--quiet"])                # raises on failure; ignore the stdout
```

`CliClient` accepts an optional `runner=` too, driving every verb through the
given runner instead of the real one — a `ScriptedRunner` (or `RecordingRunner`
/ `RecordReplayRunner`) makes a `CliClient`-based wrapper hermetically testable
without restructuring it around a `runner` parameter of its own:

```python
from processkit import CliClient
from processkit.testing import Reply, ScriptedRunner

scripted = ScriptedRunner()
scripted.on(["git", "rev-parse", "HEAD"], Reply.ok("deadbeef\n"))
git = CliClient("git", runner=scripted)
assert git.run(["rev-parse", "HEAD"]) == "deadbeef"   # no real git spawned
```

`output_all`/`aoutput_all` (and their `_bytes` twins) and `Supervisor` accept
the same `runner=` keyword, for the same reason — a batch or a supervised
command can be driven through a double in a test, with the real `Runner`
the default when `runner=` is omitted.

*Deeper: per-client defaults and the full verb set — [the Cookbook](cookbook.md) → "Wrap a CLI tool".*

---

Next: [Running commands](commands.md) ·
[Streaming & interactive I/O](streaming.md) ·
[Supervision](supervision.md) · [Cookbook](cookbook.md)
