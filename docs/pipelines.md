# Pipelines

[‹ docs index](README.md)

`a | b | c` **without a shell**. Each stage's stdout feeds the next stage's
stdin through an in-process relay — there is no shell string anywhere, so no
quoting rules, no word splitting, no injection surface. Every stage spawns into
one shared kill-on-exit [process group](process-groups.md), so the chain lives
and dies as a unit.

```python
from processkit import Command

# git log --format=%an | sort | uniq -c
authors = (
    Command("git", ["log", "--format=%an"])
    | Command("sort")
    | Command("uniq", ["-c"])
).run()
print(authors)
```

## Building a pipeline

`Command.pipe(next)` starts a `Pipeline`; chain more stages with
`Pipeline.pipe`. The `|` operator is sugar for the same thing — `a | b | c` is
exactly `a.pipe(b).pipe(c)`:

```python
authors = (
    Command("git", ["log", "--format=%an"])
    .pipe(Command("sort"))
    .pipe(Command("uniq", ["-c"]))
    .run()
)
```

Python's `|` binds *looser* than a method call, so parenthesize the whole chain
before a terminal verb — `(a | b).run()`, never `a | b.run()` (which would call
`run()` on `b` alone). The `.pipe(...).pipe(...)` form chains cleanly without the
extra parentheses.

The verbs mirror a single `Command`'s, each folding the pipefail outcome
(below). Every verb has an `a`-prefixed asyncio twin:

| Sync | Async | Returns | A failing stage is… |
|---|---|---|---|
| `output()` | `aoutput()` | `ProcessResult` | …reported in the result (code/stderr/`program` of the first unclean stage) |
| `output_bytes()` | `aoutput_bytes()` | `BytesResult` | …same, with the last stage's stdout captured as raw `bytes` |
| `run()` | `arun()` | trimmed final stdout (`str`) | …raised as that stage's exception |
| `exit_code()` | `aexit_code()` | `int` | …its attributed code |
| `probe()` | `aprobe()` | `bool` | `0` → `True`, `1` → `False`, else raises |

`output()`/`output_bytes()` capture a non-zero exit, timeout, or signal as
**data** on the result; `run()`/`exit_code()`/`probe()` raise per the pipefail
attribution. An exception that isn't a clean process outcome — a stage that
couldn't be *spawned*, broken plumbing — surfaces as `ProcessError`, never as a
mere non-zero exit. See [Running commands](commands.md) for the full error model
and the structured exception fields.

## The pipefail outcome

The outcome is **pipefail**, like `set -o pipefail` in a shell:

- `stdout` is always the **last** stage's output — that's what the chain
  produced.
- `code`, `stderr`, and the reported `program` come from the **first** stage
  that didn't exit cleanly (non-zero, signal-killed, or timed out) — or from the
  last stage when every stage succeeded.

```python
result = (
    Command("cat", ["data.txt"])
    | Command("grep", ["ERROR"])      # suppose grep exits 2 (bad pattern)
    | Command("wc", ["-l"])
).output()

result.stdout        # whatever wc managed to print (the last stage)
result.code          # 2 — grep, the first unclean stage
result.program       # "grep"
result.is_success    # False
```

`run()` requires **every** stage to succeed and returns the trimmed final
stdout; if any stage exits uncleanly it raises that stage's exception
(`NonZeroExit`, `Timeout`, or `Signalled`) carrying that stage's code, stderr,
and `program`. So the chain above would raise `NonZeroExit(code=2, program="grep")`.

One honest edge: in the `producer | head` shape, a downstream that stops reading
early (`head` exits after one line and closes the pipe) leaves the producer to
die on a **broken pipe** at its next write. Under strict pipefail that counts as
the producer's failure — unless that stage was built with
`.unchecked_in_pipe()`, which exempts it from pipefail attribution (its
unclean exit, including a `SIGPIPE`, is skipped when the chain decides what to
report, and never shields a *checked* stage's own failure):

```python
top = (
    Command("producer").unchecked_in_pipe()   # SIGPIPE from `head` closing early is expected
    | Command("head", ["-1"])
).run()
```

Outside a `Pipeline`, `unchecked_in_pipe()` is a no-op — a single run's status
is already plain data on its own `ProcessResult`, and `ensure_success()` stays
opt-in.

## stdin and stdout at the ends; per-stage env/cwd

The ends of the chain behave like a single `Command`:

- The **first** stage's stdin source is honored — set `stdin_text(...)` /
  `stdin_bytes(...)` on it to feed the whole chain from a string or bytes.
- **Inner** stages read from the pipe, full stop; any stdin set on them is
  ignored. Only the last stage's stdout reaches you; inner stderr is captured
  per-stage for the pipefail diagnostics.

```python
# Feed the chain from a string; inner stages read the pipe.
unique = (
    Command("sort").stdin_text("b\na\nb\nc\n")
    | Command("uniq")
    | Command("wc", ["-l"])
).run()
print(unique)        # "3"
```

Per-stage `env` and `cwd` are plain `Command` builders — set them on each stage
**before** piping:

```python
counts = (
    Command("git", ["log", "--format=%an"]).cwd("/srv/repo")
    | Command("sort")
    | Command("uniq", ["-c"])
).run()
```

## Timeouts bound the chain

`Pipeline.timeout(seconds)` bounds the **whole** chain. At the deadline the
shared group is torn down and every stage is killed at once; the result reports
`timed_out` (and `run()` raises `Timeout`). Durations are floats of seconds:

```python
result = (
    Command("producer")
    | Command("consumer")
).timeout(30.0).output()

result.timed_out     # True if the 30s deadline fired
```

Unlike a single command's captured timeout, a timed-out pipeline yields **no
partial stdout** — the chain is run-to-completion or nothing. A per-stage
`Command.timeout(...)` set on an individual stage still kills just that stage and
surfaces under pipefail as that stage's `Timeout`. See
[Timeouts & cancellation](timeouts-and-cancellation.md); cancelling an awaited
`arun()`/`aoutput()` reaps the whole chain's tree the same way, and so does
firing a `CancellationToken` wired with `Pipeline.cancel_on(token)` — **gap-fill**
here, not override: a stage with its own explicit `Command.cancel_on(...)` keeps
it, only stages without one pick up the pipeline-level token.

## Binary tails

For a chain that ends in a binary producer (`... | gzip`), capture the last
stage's stdout raw with `output_bytes()` — its `stdout` is `bytes`, while stderr
stays decoded text:

```python
blob = (Command("cat", ["big.txt"]) | Command("gzip")).output_bytes().stdout
# blob is bytes — the gzip stream
```

The pipeline runs to completion and buffers the tail; this is a captured result,
not a streaming splice.

## Limitations

- **Run-to-completion only.** A `Pipeline` has no `astart()` and no
  line-streaming surface — it consumes its last stage in full to fold the
  pipefail outcome. Stream a *single* [Command](commands.md) when you need
  incremental output, or run the pipeline inside a [process group](process-groups.md)
  alongside other handles.
- **No `output_limit` of its own.** A pipeline can't cap retained output the way
  a single `Command` can. Bound a flooding chain with `.timeout(...)`; cap a
  single noisy stage by running it on its own with `output_limit(...)` first.

---

Next: [Running commands](commands.md) ·
[Process groups](process-groups.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Cookbook](cookbook.md) · [Platform support](platforms.md)
