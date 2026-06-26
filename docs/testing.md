# Testing your code

[‹ docs index](README.md)

Code that shells out is miserable to test — unless the subprocess sits behind a
seam. In **processkit-py** that seam is a plain object: a *runner*. Write your
code against a `runner` parameter, call its verbs, and never name a concrete
runner inside the logic. In production you pass `Runner()` — the real thing. In
tests you pass a double — a `ScriptedRunner` with canned replies, or a replaying
`RecordReplayRunner` — and no subprocess is ever spawned. The objects that come
back are genuine `ProcessResult` / `RunningProcess` values, so the code under
test can't tell the difference.

- [The runner seam](#the-runner-seam)
- [Scripting replies: ScriptedRunner](#scripting-replies-scriptedrunner)
- [Scripted streaming: a live handle, no child](#scripted-streaming-a-live-handle-no-child)
- [Record/replay cassettes: RecordReplayRunner](#recordreplay-cassettes-recordreplayrunner)
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
describes the verb surface. `Runner`, `ScriptedRunner`, and `RecordReplayRunner`
all satisfy it structurally, so the annotation type-checks (strict `mypy`) against
any of them, and against a custom double you write yourself. (`CliClient` is *not*
a `ProcessRunner` — its verbs take per-call args, not a `Command`.)

The sync and async surfaces are twins (`run` ↔ `arun`), so async code injects
the very same runner objects and awaits the `a`-prefixed verbs.

*Deeper: the verb vocabulary and what each return type carries — [Running commands](commands.md).*

## Scripting replies: ScriptedRunner

`ScriptedRunner` is the work-horse double: it returns a canned `Reply` for each
command you teach it. Match rules with `.on(prefix, reply)`; add an optional
`.fallback(reply)` for everything else.

```python
from processkit import Command, Reply, ScriptedRunner

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

Prefix matching is element-wise over the program name then the arguments, so
`on(["git", "branch"])` matches `git branch --show-current` but not `git
branchx` (and not `hg branch`). An **unmatched command with no fallback raises
`ProcessNotFound`** — the same loud error as a missing binary, so an unexpected
invocation can't slip through a test silently.

*Deeper: outcome semantics and the exception hierarchy — [Running commands](commands.md).*

## Scripted streaming: a live handle, no child

`ScriptedRunner.start(cmd)` (and `astart`) returns a real `RunningProcess`
backed by the canned reply instead of an OS child. The scripted stdout flows
through the **same line pumps** a real child uses, so `stdout_lines()`,
readiness probing, and `finish()` all behave identically — letting you test a
readiness-gate orchestration hermetically:

```python
import asyncio
from processkit import Command, Reply, ScriptedRunner

async def becomes_ready(runner):
    proc = runner.start(Command("server", ["serve"]))
    async for line in proc.stdout_lines():
        if "listening" in line:
            break
    return (await proc.finish()).is_success

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
from processkit import Command, RecordReplayRunner

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
keep secret-bearing cassettes out of shared, world-readable trees.

Record from a single thread. The capture buffer is per-runner; recording the same
`RecordReplayRunner` from several threads at once (only possible on a free-threaded
build) can interleave entries non-deterministically. Replay is read-only and has no
such constraint.

*Deeper: how a `ProcessResult` is shaped before it's captured — [the Cookbook](cookbook.md).*

## Wrapping a CLI tool: CliClient

`CliClient` binds a program to per-call defaults, so repeated calls pass only
their args. Its verbs (`run`, `output`, `output_bytes`, `exit_code`, `probe`,
`run_unit`, plus the `a`-prefixed twins) each take just the per-call arguments:

```python
from processkit import CliClient

git = CliClient("git", default_timeout=30.0)
head = git.run(["rev-parse", "HEAD"])        # or: await git.arun([...])
clean = git.probe(["diff", "--quiet"])
git.run_unit(["fetch", "--quiet"])           # success-only; returns None
```

One important limit: **`CliClient` always uses the real `Runner` — it is not
injectable.** It is convenience, not a seam. For hermetic tests, don't try to
double a `CliClient`; instead structure the code under test around a `runner`
parameter (as in [The runner seam](#the-runner-seam)) and inject a `Runner` /
`ScriptedRunner` at the `Command` level. Reach for `CliClient` in glue code
where you're content to call the real tool.

*Deeper: per-client defaults and the full verb set — [the Cookbook](cookbook.md) → "Wrap a CLI tool".*

---

Next: [Running commands](commands.md) ·
[Streaming & interactive I/O](streaming.md) ·
[Supervision](supervision.md) · [Cookbook](cookbook.md)
