# API reference

The complete, per-symbol reference for the public `processkit` surface —
every class, function, protocol, type alias, and exception exported by the
package, plus the `processkit.testing` submodule.

It is generated from the type stub (`processkit/_processkit.pyi`) and the
docstrings, the same source your IDE and `mypy` read, so it cannot drift from
the real API. The narrative [guides](README.md) explain how the pieces compose;
this page is the exhaustive index. Both surfaces are covered together: the
synchronous verbs and their `a`-prefixed asyncio twins.


## Building & running commands

Construct a command and run it — capturing everything, or checking for success — synchronously or with the `a`-prefixed asyncio twins. `CliClient` binds a program to reusable defaults; `Pipeline` chains commands shell-free; `RunningProcess` is the live handle a started child hands back.

### `Command`

```python
Command(program: StrPath, args: Args | None = ...)
```

A command builder. Builder methods return a new `Command`.

#### `arg`

```python
def arg(arg: StrPath) -> Command
```

#### `args`

```python
def args(args: Args) -> Command
```

#### `cwd`

```python
def cwd(path: StrPath) -> Command
```

#### `prefer_local`

```python
def prefer_local(dir: StrPath) -> Command
```

Search this directory before ``PATH`` when resolving a bare-name
program. Repeated calls accumulate in priority order, path-form
programs are unchanged, and the child's own ``PATH`` is not rewritten.

#### `env`

```python
def env(key: str, value: str) -> Command
```

#### `envs`

```python
def envs(vars: Mapping[str, str]) -> Command
```

#### `env_remove`

```python
def env_remove(key: str) -> Command
```

#### `env_clear`

```python
def env_clear() -> Command
```

#### `inherit_env`

```python
def inherit_env(names: Sequence[str]) -> Command
```

#### `stdin_bytes`

```python
def stdin_bytes(data: ReadableBuffer) -> Command
```

#### `stdin_text`

```python
def stdin_text(text: str) -> Command
```

#### `stdin_file`

```python
def stdin_file(path: StrPath) -> Command
```

#### `keep_stdin_open`

```python
def keep_stdin_open() -> Command
```

#### `timeout`

```python
def timeout(seconds: float) -> Command
```

#### `timeout_grace`

```python
def timeout_grace(seconds: float) -> Command
```

#### `timeout_signal`

```python
def timeout_signal(name: SignalName | int) -> Command
```

The signal sent first on a graceful timeout (default ``"term"``): a
name (``term``/``kill``/``int``/``hup``/``quit``/``usr1``/``usr2``) or a
raw platform signal number (Unix only). A raw number is validated as a
real, deliverable signal — on Unix ``1..=SIGRTMAX`` (``0``, the existence
probe that delivers nothing, negatives, and out-of-range raise
``ValueError``); on Windows a raw number raises ``Unsupported`` (only
``"kill"`` is deliverable there). A ``bool`` raises ``TypeError`` — it is
an ``int`` subtype that would otherwise silently become raw signal
``1``/``0``.

#### `no_timeout`

```python
def no_timeout() -> Command
```

#### `timeout_opt`

```python
def timeout_opt(seconds: float | None) -> Command
```

#### `cancel_on`

```python
def cancel_on(token: CancellationToken) -> Command
```

#### `success_codes`

```python
def success_codes(codes: Sequence[int]) -> Command
```

#### `retry`

```python
def retry(
    retry_if: RetryIf,
    *,
    max_retries: int | None = ...,
    initial_backoff: float | None = ...,
    multiplier: float | None = ...,
    max_backoff: float | None = ...,
    jitter: bool | None = ...,
) -> Command
```

#### `retry_never`

```python
def retry_never() -> Command
```

#### `stdout`

```python
def stdout(mode: Literal['pipe', 'inherit', 'null']) -> Command
```

#### `stderr`

```python
def stderr(mode: Literal['pipe', 'inherit', 'null']) -> Command
```

#### `encoding`

```python
def encoding(label: str) -> Command
```

#### `stdout_encoding`

```python
def stdout_encoding(label: str) -> Command
```

#### `stderr_encoding`

```python
def stderr_encoding(label: str) -> Command
```

#### `line_terminator`

```python
def line_terminator(mode: LineTerminatorName) -> Command
```

Choose where the line pump splits **both** streams into lines.
``"newline"`` (the default) splits on ``\n`` only; ``"carriage_return"``
also splits on a bare ``\r`` (one not immediately followed by ``\n``),
delivered live — for ``curl``/``pip``/``apt``-style ``\r``-redrawn
progress output that would otherwise pile up into a single line until
EOF. A ``\r\n`` pair still counts as one terminator. Shared by
``stdout_lines()``/``output_events()``, the per-line handlers
(``on_stdout_line``/``on_stderr_line``), ``stdout_tee``/``stderr_tee``,
and ``output_string`` alike; set both streams here or independently
with ``stdout_line_terminator``/``stderr_line_terminator``. Unknown
preset raises ``ValueError``.

#### `stdout_line_terminator`

```python
def stdout_line_terminator(mode: LineTerminatorName) -> Command
```

Choose where the line pump splits **stdout** into lines (see
``line_terminator``); stderr framing is left untouched.

#### `stderr_line_terminator`

```python
def stderr_line_terminator(mode: LineTerminatorName) -> Command
```

Choose where the line pump splits **stderr** into lines (see
``line_terminator``); stdout framing is left untouched. Handy when
progress output lands on stderr while stdout stays newline-structured.

#### `stdout_tee`

```python
def stdout_tee(sink: StrPath | SupportsWrite, *, append: bool = ...) -> Command
```

Tee every decoded stdout line (line + ``\n``) to ``sink`` as it is
produced, while the run *also* keeps capturing the full output (the sink
does not steal from ``ProcessResult.stdout``).

``sink`` is either a **file path** (``str`` / ``os.PathLike[str]``) or a
**Python writer** — any object with a callable ``write()`` (an
``io.StringIO``, ``sys.stderr``, a text-mode file, a logger wrapper),
picked apart by whether it exposes ``write`` (neither ``str`` nor
``pathlib.Path`` does).

- *File path:* teed as raw UTF-8 bytes, opened **at build time** (not at
  run) — created if absent and truncated, or append mode when
  ``append=True``; an unopenable path raises the matching ``OSError``
  subclass right here.
- *Writer:* each decoded line (then ``"\n"``) is passed to ``write()``
  as a ``str`` (a text sink — a binary writer whose ``write(str)`` raises
  ``TypeError`` is the wrong object here). Every write is dispatched to a
  blocking thread and awaited on the pump, so a slow ``write()`` applies
  backpressure without blocking the event loop; the object is **not**
  closed for you. ``append`` is meaningless for a writer — passing
  ``append=True`` with one raises ``ValueError``.

A write error disables the tee for the rest of the run (a ``tracing``
warning under ``enable_logging()``) while the run and its captured result
continue unaffected; a writer's ``write()`` exception is additionally
reported via ``sys.unraisablehook``. Inert unless stdout is piped through
the line pump — a no-op under ``stdout("inherit")`` / ``stdout("null")``
and under ``output_bytes()`` (raw capture).

#### `stderr_tee`

```python
def stderr_tee(sink: StrPath | SupportsWrite, *, append: bool = ...) -> Command
```

Tee every decoded stderr line to ``sink``. Same contract as
``stdout_tee`` — a file path (opened at build time, truncate by default
or ``append``) or a Python writer object with a callable ``write()`` (fed
each decoded line as a ``str`` via the same blocking-pool async-write
bridge, never closed for you), coexisting with capture, inert unless
stderr is piped through the line pump.

#### `on_stdout_line`

```python
def on_stdout_line(callback: Callable[[str], None]) -> Command
```

Call ``callback`` with every decoded stdout line as it is produced —
the way to give the **synchronous** surface (``.output()``/``.run()``)
live progress observation during an otherwise-blocking call, without
losing the full capture: ``callback`` observes the same decoded lines
that land in ``ProcessResult.stdout``, it does not replace them. Also
fires on the async verbs and on a streamed run (``start()``/
``astart()`` + ``stdout_lines()``/``output_events()``) — one callback,
every path.

``callback`` is infallible: an exception raised inside it is reported
via ``sys.unraisablehook`` rather than propagated — it never derails
the run or alters the captured result. At most one handler per stream
— a repeat call replaces the previous one (builder semantics, like
``timeout()``); compose inside one callable to fan out.

Inert under ``stdout("inherit")``/``stdout("null")`` (no pump runs)
and under ``output_bytes()`` (stdout is captured raw there, bypassing
the line pump).

#### `on_stderr_line`

```python
def on_stderr_line(callback: Callable[[str], None]) -> Command
```

Call ``callback`` with every decoded stderr line as it is produced.
Same contract as ``on_stdout_line`` — full capture unaffected, fires on
sync/async/streamed paths alike, infallible (a raising callback goes to
``sys.unraisablehook``, never propagates), at most one handler per
stream.

Inert under ``stderr("inherit")``/``stderr("null")``. Unlike
``on_stdout_line``, **not** silenced by ``output_bytes()``: that verb
only bypasses the *stdout* line pump for its raw-bytes capture —
stderr still decodes through the line pump exactly as under
``output()``, so this callback still fires.

#### `kill_on_parent_death`

```python
def kill_on_parent_death() -> Command
```

#### `create_no_window`

```python
def create_no_window() -> Command
```

#### `uid`

```python
def uid(uid: int) -> Command
```

#### `gid`

```python
def gid(gid: int) -> Command
```

#### `groups`

```python
def groups(gids: Sequence[int]) -> Command
```

#### `setsid`

```python
def setsid() -> Command
```

#### `umask`

```python
def umask(mask: int) -> Command
```

#### `priority`

```python
def priority(level: Priority) -> Command
```

#### `output_limit`

```python
def output_limit(
    *,
    max_bytes: int | None = ...,
    max_lines: int | None = ...,
    on_overflow: Literal['drop_oldest', 'drop_newest', 'error'] = ...,
) -> Command
```

#### `output`

```python
def output() -> ProcessResult
```

#### `output_bytes`

```python
def output_bytes() -> BytesResult
```

#### `run`

```python
def run() -> str
```

#### `exit_code`

```python
def exit_code() -> int
```

#### `probe`

```python
def probe() -> bool
```

#### `aoutput`

```python
async def aoutput() -> ProcessResult
```

#### `aoutput_bytes`

```python
async def aoutput_bytes() -> BytesResult
```

#### `arun`

```python
async def arun() -> str
```

#### `aexit_code`

```python
async def aexit_code() -> int
```

#### `aprobe`

```python
async def aprobe() -> bool
```

#### `start`

```python
def start() -> RunningProcess
```

#### `astart`

```python
async def astart() -> RunningProcess
```

#### `unchecked_in_pipe`

```python
def unchecked_in_pipe() -> Command
```

#### `program`

```python
program: str
```

#### `arguments`

```python
arguments: list[str]
```

#### `command_line`

```python
def command_line() -> str
```

#### `pipe`

```python
def pipe(other: Command) -> Pipeline
```

### `CliClient`

```python
CliClient(
    program: StrPath,
    *,
    default_timeout: float | None = ...,
    default_env: Mapping[str, str] | None = ...,
    default_env_remove: Sequence[str] | None = ...,
    default_env_fn: Mapping[str, Callable[[], str]] | None = ...,
    default_retry_if: RetryIf | None = ...,
    default_max_retries: int | None = ...,
    default_initial_backoff: float | None = ...,
    default_multiplier: float | None = ...,
    default_max_backoff: float | None = ...,
    default_jitter: bool | None = ...,
    default_cancel_on: CancellationToken | None = ...,
    runner: RunnerLike | None = ...,
)
```

A program bound to default timeout/env/retry, run with the real
`Runner` by default or an injected `runner=` (a `ScriptedRunner` and
friends, for testable code with no real spawns). The verbs take just the
per-call arguments.

#### `command`

```python
def command(args: Args) -> Command
```

A `Command` for `program <args>`, the client's defaults pre-applied
— chain more builders, then pass it to a verb below instead of a plain
arg list. An explicit setting on it always wins over the default.

#### `run`

```python
def run(call: Args | Command) -> str
```

#### `output`

```python
def output(call: Args | Command) -> ProcessResult
```

#### `output_bytes`

```python
def output_bytes(call: Args | Command) -> BytesResult
```

#### `exit_code`

```python
def exit_code(call: Args | Command) -> int
```

#### `probe`

```python
def probe(call: Args | Command) -> bool
```

#### `arun`

```python
async def arun(call: Args | Command) -> str
```

#### `aoutput`

```python
async def aoutput(call: Args | Command) -> ProcessResult
```

#### `aoutput_bytes`

```python
async def aoutput_bytes(call: Args | Command) -> BytesResult
```

#### `aexit_code`

```python
async def aexit_code(call: Args | Command) -> int
```

#### `aprobe`

```python
async def aprobe(call: Args | Command) -> bool
```

### `Pipeline`

```python
class Pipeline
```

A shell-free pipeline `a | b | c`.

By design, no `start`/`astart` — see `Command.pipe()`'s stub/binding
comment: a pipeline is a whole-chain verb, with no natural "handle to a
live chain" to hand back. Stream an individual stage by `start()`ing that
one `Command` directly instead.

#### `pipe`

```python
def pipe(other: Command) -> Pipeline
```

#### `timeout`

```python
def timeout(seconds: float) -> Pipeline
```

#### `cancel_on`

```python
def cancel_on(token: CancellationToken) -> Pipeline
```

#### `output`

```python
def output() -> ProcessResult
```

#### `output_bytes`

```python
def output_bytes() -> BytesResult
```

#### `run`

```python
def run() -> str
```

#### `exit_code`

```python
def exit_code() -> int
```

#### `probe`

```python
def probe() -> bool
```

#### `aoutput`

```python
async def aoutput() -> ProcessResult
```

#### `aoutput_bytes`

```python
async def aoutput_bytes() -> BytesResult
```

#### `arun`

```python
async def arun() -> str
```

#### `aexit_code`

```python
async def aexit_code() -> int
```

#### `aprobe`

```python
async def aprobe() -> bool
```

### `RunningProcess`

```python
class RunningProcess
```

A handle to a started process: stream output, write stdin, wait for exit.

Usable as a (async) context manager — exiting the block tears the process
down (a hard kill of the whole private tree for a standalone
``start()``/``astart()`` handle). ``stdout_lines()`` / ``output_events()`` /
``take_stdin()`` / ``kill()`` are *synchronous* setup calls; the
iterator / handle they return is what you await.

Every consuming verb — ``outcome``/``finish``/``output``/``output_bytes``/
``profile``/``shutdown`` — comes in a sync/async pair, like everywhere else
in this library: the bare name blocks the calling thread (via the same
interruptible driver as ``Command.output()``), the ``a``-prefixed twin is a
coroutine (``outcome``/``aoutcome`` rather than the unusable ``wait``/
``await``, since ``await`` is a reserved word). Either member of a pair
**consumes** the handle — afterwards it is spent (``pid`` and the other
getters return ``None``, and every consuming verb raises). Use whichever
matches your calling code, regardless of whether the handle came from
``start()`` or ``astart()``.

#### `pid`

```python
pid: int | None
```

#### `elapsed_seconds`

```python
elapsed_seconds: float | None
```

#### `cpu_time_seconds`

```python
cpu_time_seconds: float | None
```

#### `peak_memory_bytes`

```python
peak_memory_bytes: int | None
```

#### `stdout_line_count`

```python
stdout_line_count: int | None
```

#### `stderr_line_count`

```python
stderr_line_count: int | None
```

#### `owns_group`

```python
owns_group: bool | None
```

#### `stdout_lines`

```python
def stdout_lines() -> StdoutLines
```

#### `output_events`

```python
def output_events() -> OutputEvents
```

#### `take_stdin`

```python
def take_stdin() -> ProcessStdin
```

The writable stdin handle. Raises `ProcessError` if stdin was not kept
open (build the `Command` with ``keep_stdin_open()``) or was already
taken — so a missing setup fails here, not with a later `AttributeError`.

#### `kill`

```python
def kill() -> None
```

Begin tearing the tree down without waiting (like
``subprocess.Popen.kill()``: fire-and-forget).

#### `outcome`

```python
def outcome() -> Outcome
```

#### `aoutcome`

```python
async def aoutcome() -> Outcome
```

#### `finish`

```python
def finish() -> Finished
```

#### `afinish`

```python
async def afinish() -> Finished
```

#### `output`

```python
def output() -> ProcessResult
```

#### `aoutput`

```python
async def aoutput() -> ProcessResult
```

#### `output_bytes`

```python
def output_bytes() -> BytesResult
```

#### `aoutput_bytes`

```python
async def aoutput_bytes() -> BytesResult
```

#### `profile`

```python
def profile(every_seconds: float) -> RunProfile
```

#### `aprofile`

```python
async def aprofile(every_seconds: float) -> RunProfile
```

#### `shutdown`

```python
def shutdown(grace_seconds: float) -> Outcome
```

Graceful teardown (signal -> wait ``grace_seconds`` -> hard kill),
returning the `Outcome`; consumes the handle. Only for a standalone
``start()``/``astart()`` handle — a handle from ``ProcessGroup.start()``
raises `Unsupported`; tear such a child down via the group (or `kill()`).
Named to match ``ProcessGroup.shutdown()``/``ashutdown()``.

#### `ashutdown`

```python
async def ashutdown(grace_seconds: float) -> Outcome
```

Async counterpart of `shutdown`.

## Results & outcomes

What a finished (or streamed) run reports back. A non-zero exit, a timeout, and a signal-kill are all *data* on these types — never raised by the capturing verbs.

### `ProcessResult`

```python
class ProcessResult
```

The captured result of a finished run. A non-zero exit, a timeout, and a
signal-kill are all reported as data here — never raised by `output()`.

Value semantics: `==`/`hash()` compare every field (program/stdout/stderr/
outcome/success codes — not the incidental `duration_seconds`/`truncated`).
**Not** picklable: equality also spans the configured `timeout` and accepted
`success_codes`, which processkit exposes no accessor to read back, so a
pickled result could not reconstruct them and would compare unequal to its
original for any command that set `.timeout(...)`/`.success_codes(...)`;
pickling raises `TypeError`. Pickle `result.outcome` (an `Outcome`, which
round-trips exactly — e.g. to return it from a
`concurrent.futures.ProcessPoolExecutor` worker), or persist
`result.stdout`/`.stderr`/`.code` yourself, to cross a process boundary.

#### `stdout`

```python
stdout: str
```

#### `stderr`

```python
stderr: str
```

#### `code`

```python
code: int | None
```

#### `is_success`

```python
is_success: bool
```

#### `timed_out`

```python
timed_out: bool
```

#### `signal`

```python
signal: int | None
```

#### `program`

```python
program: str
```

#### `duration_seconds`

```python
duration_seconds: float
```

#### `truncated`

```python
truncated: bool
```

#### `combined`

```python
combined: str
```

#### `diagnostic`

```python
diagnostic: str | None
```

The best human-facing message: stderr if it carries text, otherwise
stdout, otherwise ``None`` if both are blank — the same preference
order as ``NonZeroExit``/``Timeout``/``Signalled.diagnostic``.

#### `outcome`

```python
outcome: Outcome
```

The full run outcome (``code`` / ``signal`` / ``timed_out``), the
same value ``RunProfile.outcome`` and the checking-verb exceptions
expose.

#### `ensure_success`

```python
def ensure_success() -> ProcessResult
```

Raise the same exception a checking verb would if this result's
exit isn't in ``success_codes``; returns ``self`` unchanged otherwise,
so it composes: ``cmd.output().ensure_success().stdout``.

### `BytesResult`

```python
class BytesResult
```

The captured result of a run with raw-bytes stdout (`Command.output_bytes()`);
stderr stays decoded text. A non-zero exit, a timeout, and a signal-kill are
all data here, never raised.

Value semantics: `==`/`hash()` compare every field, same as `ProcessResult`.
**Not** picklable — raw stdout may not be valid UTF-8 and processkit has no
way to reconstruct one from arbitrary bytes outside a real run; pickling
raises `TypeError`. Pickle a `ProcessResult` (`Command.output()`) instead,
or persist the fields you need yourself.

#### `stdout`

```python
stdout: bytes
```

#### `stderr`

```python
stderr: str
```

#### `code`

```python
code: int | None
```

#### `is_success`

```python
is_success: bool
```

#### `timed_out`

```python
timed_out: bool
```

#### `signal`

```python
signal: int | None
```

#### `program`

```python
program: str
```

#### `duration_seconds`

```python
duration_seconds: float
```

#### `truncated`

```python
truncated: bool
```

Whether captured output was truncated by an ``output_limit(...)`` cap
— the line-captured stderr under any cap, and (since processkit 2.1.0)
the raw stdout too when an ``output_limit(max_bytes=...)`` byte ceiling
bounds it to a head/tail. A ``max_lines`` cap never truncates raw stdout
(bytes have no line count); only a ``max_bytes`` cap does.

#### `diagnostic`

```python
diagnostic: str | None
```

See ``ProcessResult.diagnostic``. Raw stdout is lossily decoded to
text for this message when stderr is blank.

#### `outcome`

```python
outcome: Outcome
```

See ``ProcessResult.outcome``.

#### `ensure_success`

```python
def ensure_success() -> BytesResult
```

See ``ProcessResult.ensure_success()``.

### `Outcome`

```python
class Outcome
```

How a process ended.

There is no `is_success` here on purpose: an `Outcome` carries no
`success_codes` context, so it cannot give the command's own success verdict
the way `ProcessResult.is_success` does. Use `exited_zero` for the literal
"exit code 0" test, or compare `code` against your accepted set.

Value semantics: `==`/`hash()` compare `code`/`signal`/`timed_out`
(equivalently, which variant this is and its payload); picklable.

#### `code`

```python
code: int | None
```

#### `signal`

```python
signal: int | None
```

#### `timed_out`

```python
timed_out: bool
```

#### `exited_zero`

```python
exited_zero: bool
```

### `Finished`

```python
class Finished
```

A process's outcome plus captured stderr (stdout was streamed).

Mirrors `Outcome`'s `code`, `exited_zero`, `timed_out`, and `signal`
directly (in addition to the nested `outcome`), so callers don't need to
reach through `.outcome` for fields they already use on `Outcome`. Like
`Outcome`, it exposes `exited_zero` (literal "exit code 0"), not an
`is_success` that would falsely imply `success_codes` were considered.

Value semantics: `==`/`hash()` compare `outcome`/`stderr`; picklable.

#### `outcome`

```python
outcome: Outcome
```

#### `stderr`

```python
stderr: str
```

#### `code`

```python
code: int | None
```

#### `exited_zero`

```python
exited_zero: bool
```

#### `timed_out`

```python
timed_out: bool
```

#### `signal`

```python
signal: int | None
```

### `RunProfile`

```python
class RunProfile
```

A resource-usage profile sampled across a run (`RunningProcess.profile`),
plus the run's `outcome` — `profile()` is a superset of `outcome()`.

Value semantics: `==`/`hash()` compare every field (`outcome`/
`duration_seconds`/`cpu_time_seconds`/`peak_memory_bytes`/`samples`; all
exact underneath, though two are exposed here as `float`). **Not**
picklable — it reports live OS resource-sampling telemetry that processkit
has no way to reconstruct outside an actual monitored run; pickling raises
`TypeError`.

#### `code`

```python
code: int | None
```

#### `signal`

```python
signal: int | None
```

#### `timed_out`

```python
timed_out: bool
```

#### `outcome`

```python
outcome: Outcome
```

#### `duration_seconds`

```python
duration_seconds: float
```

#### `cpu_time_seconds`

```python
cpu_time_seconds: float | None
```

#### `peak_memory_bytes`

```python
peak_memory_bytes: int | None
```

#### `samples`

```python
samples: int
```

#### `avg_cpu_cores`

```python
avg_cpu_cores: float | None
```

## Streaming & interactive I/O

The live handles a started `RunningProcess` hands out: async iterators over its output (line by line, or as interleaved stdout/stderr events) and a writable stdin.

### `StdoutLines`

```python
class StdoutLines
```

Async iterator over a process's stdout, line by line.

### `OutputEvents`

```python
class OutputEvents
```

Async iterator over stdout + stderr as interleaved `OutputEvent`s.

### `OutputEvent`

```python
class OutputEvent
```

One captured line and the stream it came from.

#### `stream`

```python
stream: Literal['stdout', 'stderr']
```

#### `is_stderr`

```python
is_stderr: bool
```

#### `text`

```python
text: str
```

### `ProcessStdin`

```python
class ProcessStdin
```

A writable handle to a running process's stdin (all methods awaitable).

#### `write`

```python
async def write(data: ReadableBuffer) -> None
```

#### `write_line`

```python
async def write_line(line: str) -> None
```

#### `send_control`

```python
async def send_control(control: str) -> None
```

Write one mapped control byte, e.g. ``"c"`` -> Ctrl-C (``\x03``).

This writes a byte to the child's stdin pipe, not a terminal signal;
real SIGINT/SIGTSTP delivery requires a pseudoterminal.

#### `flush`

```python
async def flush() -> None
```

#### `close`

```python
async def close() -> None
```

## Process groups

Kill-on-drop containment for a whole process tree — start children into it, signal or suspend the group, and reap the entire tree (grandchildren included) on exit.

### `ProcessGroup`

```python
ProcessGroup(
    *,
    max_memory: int | None = ...,
    max_processes: int | None = ...,
    cpu_quota: float | None = ...,
    shutdown_grace: float | None = ...,
    escalate_to_kill: bool | None = ...,
)
```

A kill-on-drop container for a process tree; use as a (async) context
manager. Also a `ProcessRunner` in its own right (see `_RunnerVerbs`):
its run verbs run `command` as a *shared* member of this group (not a
standalone tree) — the same verb surface `Runner`/`ScriptedRunner`/…
expose (not an `extract_runner` target, though — see `runner.rs`).

#### `mechanism`

```python
mechanism: Literal['job_object', 'cgroup_v2', 'process_group', 'unknown']
```

#### `members`

```python
def members() -> list[int]
```

#### `signal`

```python
def signal(name: SignalName | int) -> None
```

Send a signal to every process in the tree: a name
(``term``/``kill``/``int``/``hup``/``quit``/``usr1``/``usr2``) or a raw
platform signal number (Unix only). On Windows a Job Object has no POSIX
signals, so only ``"kill"`` is deliverable and any other name/number
raises ``Unsupported``. A raw number is validated as a real, deliverable
signal (``1..=SIGRTMAX`` on Unix); ``0`` (the existence probe), negatives,
and out-of-range values raise ``ValueError`` instead of a silent no-op,
and a ``bool`` raises ``TypeError``.

#### `suspend`

```python
def suspend() -> None
```

#### `resume`

```python
def resume() -> None
```

#### `kill_all`

```python
def kill_all() -> None
```

#### `stats`

```python
def stats() -> ProcessGroupStats
```

#### `shutdown`

```python
def shutdown() -> None
```

#### `ashutdown`

```python
async def ashutdown() -> None
```

### `ProcessGroupStats`

```python
class ProcessGroupStats
```

A snapshot of a `ProcessGroup`'s resource usage.

#### `active_process_count`

```python
active_process_count: int
```

#### `peak_memory_bytes`

```python
peak_memory_bytes: int | None
```

#### `total_cpu_time_seconds`

```python
total_cpu_time_seconds: float | None
```

## Supervision

Keep a command alive: restart it per a policy, with backoff and jitter, until a stop condition is met.

### `Supervisor`

```python
Supervisor(
    command: Command,
    *,
    restart: Literal['always', 'on_crash', 'never'] | None = ...,
    max_restarts: int | None = ...,
    backoff_initial: float | None = ...,
    backoff_factor: float | None = ...,
    max_backoff: float | None = ...,
    jitter: bool | None = ...,
    stop_when: Callable[[ProcessResult], bool] | None = ...,
    give_up_when: Callable[[ProcessResult | ProcessError], bool] | None = ...,
    storm_pause: float | None = ...,
    failure_threshold: float | None = ...,
    failure_decay: float | None = ...,
    capture_max_bytes: int | None = ...,
    capture_max_lines: int | None = ...,
    capture_on_overflow: Literal['drop_oldest', 'drop_newest', 'error'] | None = ...,
    runner: RunnerLike | None = ...,
)
```

Keep a command alive: restart per policy with backoff until a stop condition.

#### `run`

```python
def run() -> SupervisionOutcome
```

#### `arun`

```python
async def arun() -> SupervisionOutcome
```

### `SupervisionOutcome`

```python
class SupervisionOutcome
```

The result of a `Supervisor.run()`.

Value semantics: `==`/`hash()` compare every field (`final_result` via
`ProcessResult`'s own comparison, plus `restarts`/`stopped`/`storm_pauses`).
**Not** picklable: its identity includes `final_result` (a `ProcessResult`),
which cannot be faithfully reconstructed from a pickle (its `timeout`/
`success_codes` have no accessor to read back), so pickling raises
`TypeError`. Read the fields you need, or pickle `final_result.outcome` (an
`Outcome`, which round-trips exactly), to cross a process boundary.

#### `final_result`

```python
final_result: ProcessResult
```

#### `restarts`

```python
restarts: int
```

#### `stopped`

```python
stopped: Literal['policy_satisfied', 'predicate', 'restarts_exhausted', 'gave_up', 'unknown']
```

#### `storm_pauses`

```python
storm_pauses: int
```

## Cancellation

A portable cancel switch, wired into a run via `Command.cancel_on()`, `Pipeline.cancel_on()`, or `CliClient`'s `default_cancel_on=`.

### `CancellationToken`

```python
class CancellationToken
```

A cancel switch: fire it to tear down every run wired to it via
`Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
`Pipeline.cancel_on()` — surfacing `Cancelled`. Cheap to clone/share:
every clone refers to the same underlying state, so cancelling any clone
cancels every run wired to it. A cancelled token stays cancelled forever.

`child_token()` derives a separate, scoped token: it is cancelled
automatically when this one is, but cancelling it back does NOT
propagate to this token or to its other children — cancellation only
flows parent-to-child, never child-to-parent or between siblings.

#### `cancel`

```python
def cancel() -> None
```

#### `is_cancelled`

```python
def is_cancelled() -> bool
```

#### `child_token`

```python
def child_token() -> CancellationToken
```

A new token that is cancelled automatically when this one is, but
can also be cancelled independently — cancelling the child does not
affect this token or its other children.

## Batch execution

Run many commands with bounded concurrency, returning each result — or a `ProcessError` for a spawn/I/O failure — in input order.

### `output_all`

```python
def output_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[ProcessResult | ProcessError]
```

### `output_all_bytes`

```python
def output_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[BytesResult | ProcessError]
```

### `aoutput_all`

```python
async def aoutput_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[ProcessResult | ProcessError]
```

### `aoutput_all_bytes`

```python
async def aoutput_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[BytesResult | ProcessError]
```

## Readiness helpers

Asyncio helpers that wait for a condition — a matching output line, an open TCP port, a filesystem path, or any polled predicate — bounded by a deadline.

### `wait_until`

```python
async def wait_until(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float,
    interval: float = 0.05,
) -> None
```

Poll ``predicate`` until it returns true, or ``timeout`` seconds elapse.

(Named ``wait_until``, not ``wait_for`` — the latter would collide with
``asyncio.wait_for``, whose semantics differ: it bounds one *awaitable*,
not a *polled predicate*.)

``predicate`` may be synchronous or return an awaitable. Polls every
``interval`` seconds; raises `WaitTimeout` (also a `TimeoutError`) if the
deadline passes first. A synchronous ``predicate`` runs on the event loop,
so keep it non-blocking — use an async ``predicate`` for anything that does
I/O. If ``predicate``'s awaitable is already a `asyncio.Future`/`asyncio.Task`
you own, note it is never cancelled by this helper on timeout — only
abandoned, so cancel or await it yourself afterwards if that matters.

``timeout<=0`` contract (shared with `wait_for_port` / `wait_for_line`):
at ``timeout=0``, ``predicate`` is still evaluated (at least once) before
any deadline check, so an already-true predicate succeeds instead of
failing before it was ever checked. A **negative** ``timeout`` is rejected
outright — raises `ValueError`, same as NaN — rather than being treated as
"expired" or silently accepted.

### `wait_for_line`

```python
async def wait_for_line(
    lines: AsyncIterator[Any],
    predicate: str | Callable[[Any], bool],
    *,
    timeout: float,
) -> Any
```

Consume from an async iterator until ``predicate`` matches an item.

``predicate`` is either a callable (``predicate(item) -> bool``) or, for a
`str`-yielding iterator only, a plain `str` — a shorthand for "the item
contains this substring" (``predicate in item``). Not just for
`StdoutLines`: any async iterator works (e.g. `OutputEvents`, with a
callable predicate over its `OutputEvent` items).

Returns the matching item. Raises `WaitTimeout` (also a `TimeoutError`,
carrying ``timeout_seconds``) if nothing matches within ``timeout``
seconds, or propagates whatever ``predicate`` or the iterator itself
raised (a `ProcessError` if the stream ends first) untouched — never
masked behind the timeout. Items read before the match are consumed;
iteration may continue afterward **only when a match was found** — on a
`WaitTimeout`, exactly how far the iterator advanced past the last
inspected item is unspecified (cancellation of the internal scan races the
iterator's own advancement), so don't rely on its position after a
timeout.

``timeout<=0`` contract (shared with `wait_until` / `wait_for_port`): at
``timeout=0``, the iterator is still scanned (at least one tick), so an
item that already matches (already sitting in the iterator) succeeds
instead of failing before it was ever inspected. A **negative** ``timeout``
is rejected outright — raises `ValueError`, same as NaN — rather than being
treated as "expired" or silently accepted.

### `wait_for_port`

```python
async def wait_for_port(
    host: str,
    port: int,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None
```

Wait until a TCP connection to ``(host, port)`` succeeds.

Polls every ``interval`` seconds until the port accepts a connection or
``timeout`` seconds elapse, in which case `WaitTimeout` (also a
`TimeoutError`) is raised — carrying ``host``/``port`` — chained from the
last connection attempt's exception (e.g. a DNS failure survives as the
cause instead of being silently dropped).

``timeout<=0`` contract (shared with `wait_until` / `wait_for_line`): at
``timeout=0``, a connection attempt is still made (at least one), so an
already-ready port succeeds instead of failing before a connection was
ever tried — this first attempt is not cut short by the already-expired
deadline. It IS bounded, though: to a short, fixed event-loop tick (or a
smaller caller-supplied ``interval``), not left uncapped — an
unresolvable/blackhole address would
otherwise be free to block on the OS's own (much longer, or absent)
connect/DNS timeout well past the caller's requested deadline. A
**negative** ``timeout`` is rejected outright — raises `ValueError`, same
as NaN — rather than being treated as "expired" or silently accepted.

### `wait_for_path`

```python
async def wait_for_path(
    path: StrPath,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None
```

Wait until ``path`` exists on the filesystem.

Polls every ``interval`` seconds until ``path.exists()`` returns true or
``timeout`` seconds elapse, in which case `WaitTimeout` (also a
`TimeoutError`) is raised, carrying ``path``. A unix-socket, a pid file, or
any other marker file a daemon creates once ready are all typical uses —
for a TCP port or an arbitrary predicate, see `wait_for_port` /
`wait_until` instead (`wait_until(lambda: path.exists(), ...)` is exactly
what this helper does, named for readability and given the same
`WaitTimeout` discipline as its siblings).

``timeout<=0`` contract (shared with `wait_until` / `wait_for_port` /
`wait_for_line`): at ``timeout=0``, ``path`` is still checked (at least
once) before any deadline check, so an already-existing path succeeds
instead of failing before it was ever checked. A **negative** ``timeout``
is rejected outright — raises `ValueError`, same as NaN — rather than
being treated as "expired" or silently accepted.

### `WaitTimeout`

```python
WaitTimeout(
    message: str,
    *,
    timeout_seconds: float,
    host: str | None = None,
    port: int | None = None,
    path: StrPath | None = None,
)
```

A readiness helper (`wait_until` / `wait_for_line` / `wait_for_port` /
`wait_for_path`) didn't succeed within its deadline.

Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
the same convention a run's own `.timeout()` uses (see `Timeout`). Always
carries `timeout_seconds`; `wait_for_port` additionally sets `host` /
`port`, and `wait_for_path` sets `path` (all `None` for `wait_until` /
`wait_for_line`, which have none of these) and chains the last connection
attempt's exception as `__cause__` (`wait_for_port` only).

#### `timeout_seconds`

```python
timeout_seconds = timeout_seconds
```

#### `host`

```python
host = host
```

#### `port`

```python
port = port
```

#### `path`

```python
path = path
```

## Observability

Opt-in bridging of the core's per-run `tracing` events to Python `logging`.

### `enable_logging`

```python
def enable_logging() -> bool
```

## The runner seam

The dependency-injection seam: annotate your code against a protocol, inject the real `Runner` in production and a test double (see the Testing section) in tests. `ProcessRunner` is the capture/check verbs; `StreamingRunner` adds `start`/`astart`.

### `ProcessRunner`

```python
class ProcessRunner
```

The capture/check run verbs as a structural type: `output`/`output_bytes`/
`run`/`exit_code`/`probe` and their `a`-prefixed async twins — no streaming.

Every built-in runner satisfies this (and the wider `StreamingRunner`).
Prefer this narrower protocol when your own code only calls these verbs —
a hand-rolled double then only needs to implement five verbs (times two
for the async twins), not the full runner surface.
`CliClient` also satisfies `ProcessRunner`: each capture/check verb accepts
either per-call `Args` (which it combines with its bound program) or a
`Command` (whose explicit settings win over client defaults). It is not a
`StreamingRunner`, because it has no `start`/`astart` verbs.

#### `output`

```python
def output(command: Command) -> ProcessResult
```

#### `output_bytes`

```python
def output_bytes(command: Command) -> BytesResult
```

#### `run`

```python
def run(command: Command) -> str
```

#### `exit_code`

```python
def exit_code(command: Command) -> int
```

#### `probe`

```python
def probe(command: Command) -> bool
```

#### `aoutput`

```python
async def aoutput(command: Command) -> ProcessResult
```

#### `aoutput_bytes`

```python
async def aoutput_bytes(command: Command) -> BytesResult
```

#### `arun`

```python
async def arun(command: Command) -> str
```

#### `aexit_code`

```python
async def aexit_code(command: Command) -> int
```

#### `aprobe`

```python
async def aprobe(command: Command) -> bool
```

### `StreamingRunner`

```python
class StreamingRunner
```

`ProcessRunner` plus `start`/`astart` — the full runner verb surface,
for code that also needs a live `RunningProcess` handle to stream.

`Runner`, `ScriptedRunner`, `RecordReplayRunner`, and `RecordingRunner` all
satisfy it. A hand-rolled double can implement the capture/check verbs
easily, but `start`/`astart` must return a `RunningProcess`, which has no
public constructor — and the built-in runners are `@final`, so a
fully-conforming custom runner in practice means *wrapping* one
(delegating `start`/`astart` to it; use `ScriptedRunner` for streaming
doubles).

#### `start`

```python
def start(command: Command) -> RunningProcess
```

#### `astart`

```python
async def astart(command: Command) -> RunningProcess
```

### `Runner`

```python
class Runner
```

The real process runner — inject it for testable code.

## Exceptions

Every error raised by the package descends from `ProcessError`, so a single `except ProcessError` catches them all. `Timeout`, `ProcessNotFound`, and `PermissionDenied` also subclass a builtin (`TimeoutError` / `FileNotFoundError` / `PermissionError`, each itself an `OSError`), so the stdlib `except` clauses catch them too.

### `ProcessError`

```python
class ProcessError
```

Base class for every error raised by this package.

### `NonZeroExit`

```python
class NonZeroExit
```

`run()` / `exit_code()` got a non-zero exit.

#### `program`

```python
program: str
```

#### `code`

```python
code: int
```

#### `stdout`

```python
stdout: str
```

#### `stderr`

```python
stderr: str
```

#### `stdout_bytes`

```python
stdout_bytes: bytes | None
```

#### `diagnostic`

```python
diagnostic: str | None
```

### `Timeout`

```python
class Timeout
```

A run exceeded its configured timeout.

Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
and since `TimeoutError` is itself an `OSError` subclass (as of Python
3.3), `except OSError` catches it as well (the same is true of
`ProcessNotFound`/`FileNotFoundError` and
`PermissionDenied`/`PermissionError` below — all three dual-base
exceptions are transitively `OSError`).

#### `program`

```python
program: str
```

#### `timeout_seconds`

```python
timeout_seconds: float | None
```

#### `stdout`

```python
stdout: str
```

#### `stderr`

```python
stderr: str
```

#### `stdout_bytes`

```python
stdout_bytes: bytes | None
```

#### `diagnostic`

```python
diagnostic: str | None
```

### `Signalled`

```python
class Signalled
```

A run was killed by a signal.

#### `program`

```python
program: str
```

#### `signal`

```python
signal: int | None
```

#### `stdout`

```python
stdout: str
```

#### `stderr`

```python
stderr: str
```

#### `stdout_bytes`

```python
stdout_bytes: bytes | None
```

#### `diagnostic`

```python
diagnostic: str | None
```

### `ProcessNotFound`

```python
class ProcessNotFound
```

The program could not be found / spawned.

Also a builtin `FileNotFoundError` (what `subprocess` raises), so
`except FileNotFoundError` catches it too.

#### `program`

```python
program: str
```

#### `searched`

```python
searched: str | None
```

### `PermissionDenied`

```python
class PermissionDenied
```

The program could not be spawned because of insufficient permissions
(e.g. a non-executable file), or a permission-denied OS error surfaced
from elsewhere in the run (e.g. a group signal the OS refused).

Also a builtin `PermissionError`, so `except PermissionError` catches it too.

#### `program`

```python
program: str | None
```

### `ResourceLimit`

```python
class ResourceLimit
```

A resource limit (memory / processes / CPU) was invalid or could not be
enforced by the active containment mechanism. The reason is the exception
message (``str(exc)``); it carries no extra structured field.

### `Unsupported`

```python
class Unsupported
```

The operation is not supported on this platform.

#### `operation`

```python
operation: str
```

### `OutputTooLarge`

```python
class OutputTooLarge
```

Captured output hit an `output_limit(..., on_overflow="error")` ceiling.

#### `program`

```python
program: str
```

#### `max_lines`

```python
max_lines: int | None
```

#### `max_bytes`

```python
max_bytes: int | None
```

#### `total_lines`

```python
total_lines: int
```

#### `total_bytes`

```python
total_bytes: int
```

### `Cancelled`

```python
class Cancelled
```

The run was deliberately cancelled via a `CancellationToken` wired
with `Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
`Pipeline.cancel_on()`. Terminal — never retried by `Command.retry()` or
restarted by `Supervisor` (the token stays cancelled forever, so another
attempt could only fail the same way).

#### `program`

```python
program: str
```

## Type aliases

Exported so your own wrappers can annotate against the same types the API accepts.

### `Args`

```python
Args = list[str] | list[Path] | list[os.PathLike[str]] | tuple[StrPath, ...]
```

### `LineTerminatorName`

```python
LineTerminatorName = Literal['newline', 'carriage_return']
```

### `Priority`

```python
Priority = Literal['idle', 'below_normal', 'normal', 'above_normal', 'high']
```

### `ReadableBuffer`

```python
ReadableBuffer = bytes | bytearray | memoryview
```

### `RetryIf`

```python
RetryIf = Literal['transient', 'transient_or_timeout']
```

### `SignalName`

```python
SignalName = Literal['term', 'kill', 'int', 'hup', 'quit', 'usr1', 'usr2']
```

### `StrPath`

```python
StrPath = str | os.PathLike[str]
```

## Testing

Runner test doubles, in the `processkit.testing` submodule. Inject one in tests — all satisfy the `ProcessRunner` protocol — so the code under test spawns no real processes.

### `ScriptedRunner`

```python
class ScriptedRunner
```

A scripted test double for `Runner`.

#### `on`

```python
def on(prefix: Args, reply: Reply) -> None
```

#### `on_sequence`

```python
def on_sequence(prefix: Args, replies: Sequence[Reply]) -> None
```

#### `when`

```python
def when(predicate: Callable[[Command], bool], reply: Reply) -> None
```

#### `fallback`

```python
def fallback(reply: Reply) -> None
```

### `RecordReplayRunner`

```python
class RecordReplayRunner
```

Records real runs to a cassette file (`record`) and replays them without
spawning (`replay`); shares the `Runner` run-verb surface.

#### `record`

```python
def record(path: StrPath) -> RecordReplayRunner
```

#### `replay`

```python
def replay(path: StrPath) -> RecordReplayRunner
```

#### `save`

```python
def save() -> None
```

### `RecordingRunner`

```python
class RecordingRunner
```

A recording test double: replies to every command with a canned `Reply`
and records each call, so a test can assert on what its code ran. Shares the
`Runner` run-verb surface; inspect calls with `calls()` / `only_call()`.

#### `replying`

```python
def replying(reply: Reply) -> RecordingRunner
```

#### `new`

```python
def new(inner: RunnerLike) -> RecordingRunner
```

#### `calls`

```python
def calls() -> list[Invocation]
```

#### `only_call`

```python
def only_call() -> Invocation
```

### `DryRunRunner`

```python
class DryRunRunner
```

A dry-run test double: never spawns a process. Every verb renders the
command to its display-quoted line (like `Command.command_line()`) and
returns a synthetic successful result — the seam behind a tool's own
`--dry-run`/`--echo` mode. Shares the `Runner` run-verb surface; inspect the
rendered lines with `commands()` / `only_command()`, or stream them live
with `on_invocation()`.

#### `on_invocation`

```python
def on_invocation(callback: Callable[[str], None]) -> None
```

#### `commands`

```python
def commands() -> list[str]
```

#### `only_command`

```python
def only_command() -> str
```

### `Reply`

```python
class Reply
```

A canned reply for a `ScriptedRunner` rule.

#### `ok`

```python
def ok(stdout: str) -> Reply
```

#### `fail`

```python
def fail(code: int, stderr: str) -> Reply
```

#### `timeout`

```python
def timeout() -> Reply
```

#### `signalled`

```python
def signalled(signal: int | None = ...) -> Reply
```

#### `pending`

```python
def pending() -> Reply
```

#### `lines`

```python
def lines(lines: Sequence[str]) -> Reply
```

#### `with_stdout`

```python
def with_stdout(stdout: str) -> Reply
```

#### `with_stderr`

```python
def with_stderr(stderr: str) -> Reply
```

#### `with_line_delay`

```python
def with_line_delay(seconds: float) -> Reply
```

### `Invocation`

```python
class Invocation
```

One call captured by a `RecordingRunner`: the program, args, cwd, env
overrides, and whether stdin was supplied. Values are inspectable for
assertions; the `repr` stays redacted (program, arg count, cwd, env names,
has_stdin — never argv or env values).

#### `program`

```python
program: str
```

#### `args`

```python
args: list[str]
```

#### `cwd`

```python
cwd: str | None
```

#### `env`

```python
env: dict[str, str | None]
```

#### `env_is`

```python
def env_is(name: str, value: str) -> bool
```

#### `has_env`

```python
def has_env(name: str) -> bool
```

#### `has_stdin`

```python
has_stdin: bool
```

#### `has_flag`

```python
def has_flag(flag: str) -> bool
```
