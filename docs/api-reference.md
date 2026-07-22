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

```text
Command(program: StrPath, args: Args | None = ...)
```

A command builder. Builder methods return a new `Command`.

Its `a`-verbs return custom awaitables, rather than coroutine objects:
await them directly, or pass one to ``asyncio.ensure_future(...)`` when a
Task/Future is required.

#### `arg`

```text
def arg(arg: StrPath) -> Command
```

#### `args`

```text
def args(args: Args) -> Command
```

#### `cwd`

```text
def cwd(path: StrPath) -> Command
```

#### `prefer_local`

```text
def prefer_local(dir: StrPath) -> Command
```

Search this directory before ``PATH`` when resolving a bare-name
program. Repeated calls accumulate in priority order, path-form
programs are unchanged, and the child's own ``PATH`` is not rewritten.

#### `env`

```text
def env(key: str, value: str) -> Command
```

#### `envs`

```text
def envs(vars: Mapping[str, str]) -> Command
```

#### `env_remove`

```text
def env_remove(key: str) -> Command
```

#### `env_clear`

```text
def env_clear() -> Command
```

#### `inherit_env`

```text
def inherit_env(names: Sequence[str]) -> Command
```

#### `stdin_bytes`

```text
def stdin_bytes(data: ReadableBuffer) -> Command
```

#### `stdin_text`

```text
def stdin_text(text: str) -> Command
```

#### `stdin_file`

```text
def stdin_file(path: StrPath) -> Command
```

#### `keep_stdin_open`

```text
def keep_stdin_open() -> Command
```

#### `inherit_stdin`

```text
def inherit_stdin() -> Command
```

Give the child this process's **own** stdin — it reads directly from
whatever the parent's stdin is connected to (a terminal, a file, a pipe)
instead of a crate-managed pipe. The stdin counterpart of
``stdout("inherit")``: the child *shares* the parent's stream. Reach for
it when a child must talk to the real terminal — ``git commit`` opening
``$EDITOR``, a tool prompting for a password/confirmation, or forwarding
the parent's piped stdin straight through. There is no writer to
``RunningProcess.take_stdin()`` (it raises, as for a non-kept-open run);
stdout/stderr are unaffected, so ``run()``/``output()`` still return the
child's stdout. Mutually exclusive with a *mediated* stdin — a configured
``stdin_bytes()``/``stdin_text()``/``stdin_file()`` source or
``keep_stdin_open()``: the conflict is rejected as a ``ProcessError`` at
**launch** (from the run/output verb), not when you build the ``Command``;
the live ``Runner`` and the test doubles reject it identically. Drop the
other stdin knob to resolve it.

#### `timeout`

```text
def timeout(seconds: float) -> Command
```

#### `timeout_grace`

```text
def timeout_grace(seconds: float) -> Command
```

#### `timeout_signal`

```text
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

```text
def no_timeout() -> Command
```

#### `timeout_opt`

```text
def timeout_opt(seconds: float | None) -> Command
```

#### `cancel_on`

```text
def cancel_on(token: CancellationToken) -> Command
```

#### `success_codes`

```text
def success_codes(codes: Sequence[int]) -> Command
```

#### `retry`

```text
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

```text
def retry_never() -> Command
```

#### `stdout`

```text
def stdout(mode: Literal['pipe', 'inherit', 'null']) -> Command
```

#### `stderr`

```text
def stderr(mode: Literal['pipe', 'inherit', 'null']) -> Command
```

#### `encoding`

```text
def encoding(label: str) -> Command
```

#### `stdout_encoding`

```text
def stdout_encoding(label: str) -> Command
```

#### `stderr_encoding`

```text
def stderr_encoding(label: str) -> Command
```

#### `line_terminator`

```text
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

```text
def stdout_line_terminator(mode: LineTerminatorName) -> Command
```

Choose where the line pump splits **stdout** into lines (see
``line_terminator``); stderr framing is left untouched.

#### `stderr_line_terminator`

```text
def stderr_line_terminator(mode: LineTerminatorName) -> Command
```

Choose where the line pump splits **stderr** into lines (see
``line_terminator``); stdout framing is left untouched. Handy when
progress output lands on stderr while stdout stays newline-structured.

#### `stdout_tee`

```text
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

```text
def stderr_tee(sink: StrPath | SupportsWrite, *, append: bool = ...) -> Command
```

Tee every decoded stderr line to ``sink``. Same contract as
``stdout_tee`` — a file path (opened at build time, truncate by default
or ``append``) or a Python writer object with a callable ``write()`` (fed
each decoded line as a ``str`` via the same blocking-pool async-write
bridge, never closed for you), coexisting with capture, inert unless
stderr is piped through the line pump.

#### `stdout_file`

```text
def stdout_file(path: StrPath, *, append: bool = ...) -> Command
```

Redirect the child's stdout **straight to a file**, opened at spawn
time — the child writes to the file's own descriptor, with no
parent-side pump, tee, or capture buffer. The direct-redirect cousin of
``stdout_tee`` (which instead *also* captures and mirrors each line): a
``>`` / ``>>`` shell redirect, minus the shell.

The binding folds the crate's three spellings (``stdout_file`` /
``stdout_file_append`` / ``stdout_file_truncate``) into one ``append=``
kwarg, mirroring the sibling ``stdout_tee(sink, *, append=False)`` rather
than a 1:1 copy of the core's convenience aliases. ``append=False`` (the
default) **creates or truncates** the file on every spawn; ``append=True``
**creates or appends** — the mode for a shared log across ``Supervisor``
incarnations / ``retry()`` attempts (each re-run appends to the one file
with no separator).

**Opened at spawn, not now (unlike ``stdout_tee``).** Only the path is
stored; the file is opened when the command launches, so a not-yet-
existing path is not a build-time error and each re-run / retry reopens
it. An unopenable path (a missing parent directory, a permission denial)
surfaces from the run verb at launch, not from this call.

**No capture — use a non-capturing verb.** With stdout on the file there
is no pipe to read, so the capture/streaming verbs (``output()`` /
``run()`` / ``output_bytes()`` / their ``a``-twins, and ``start()`` +
``stdout_lines()`` / ``output_events()``) raise ``ProcessError`` ("stdout
is not piped … so the capture verbs have nothing to read") instead of
returning empty output — drive it with ``exit_code()`` / ``probe()``. A
later ``stdout("pipe"/"inherit"/"null")`` **clears** the redirect and
restores the ordinary stdio mode.

#### `stderr_file`

```text
def stderr_file(path: StrPath, *, append: bool = ...) -> Command
```

Redirect the child's stderr **straight to a file**, opened at spawn
time. Same contract as ``stdout_file`` — a child-owned descriptor with no
parent-side pump/tee/buffer, the path opened lazily at launch (a missing
path is not a build-time error), ``append=False`` truncating on every
spawn while ``append=True`` appends (the shared-``Supervisor``-log mode),
and a later ``stderr("pipe"/"inherit"/"null")`` clearing the redirect.

Unlike ``stdout_file``, this does **not** disable the capture verbs: only
a non-piped *stdout* gates them, so ``output()`` / ``run()`` keep working
and return the child's stdout while stderr is diverted to the file and
``result.stderr`` comes back empty.

#### `on_stdout_line`

```text
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

```text
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

```text
def kill_on_parent_death() -> Command
```

#### `kill_on_parent_death_scope`

```text
def kill_on_parent_death_scope() -> str
```

The scope of parent-death cleanup this platform actually achieves
when the owner dies **abruptly** (a ``SIGKILL`` or crash, where graceful
``Drop`` teardown never runs), as a stable string:

- ``"whole_tree"`` — Windows: the kernel closes the Job Object handle on
  owner death and kill-on-close reaps the direct child and every
  descendant.
- ``"direct_child_only"`` — Linux: ``PR_SET_PDEATHSIG`` reaches only the
  direct child; grandchildren survive the owner's abrupt death.
- ``"unsupported"`` — macOS/BSD: no ``pdeathsig`` equivalent, so an
  abrupt owner death triggers no cleanup at all.

An honest capability report, not a request — read it to state the real
reach of ``kill_on_parent_death()`` (best-effort on Unix) instead of
overpromising a whole-tree guarantee the OS cannot keep. It covers only
the abrupt-death path: ordinary graceful teardown still kills the whole
tree on every platform regardless.

A ``staticmethod`` — the scope is fixed per target at build time and does
not depend on instance state or on whether ``kill_on_parent_death()`` was
called, so call it on the class (``Command.kill_on_parent_death_scope()``)
or on any instance for the same answer.

#### `create_no_window`

```text
def create_no_window() -> Command
```

#### `windows_graceful_ctrl_break`

```text
def windows_graceful_ctrl_break() -> Command
```

Windows: opt in to a **graceful teardown** — at a graceful timeout
(``timeout_grace``) or a ``ProcessGroup`` shutdown, send the direct
child a console ``CTRL_BREAK`` before the grace window, so a console
child (a CLI, Node, Python, or Go service that installs a ``CTRL_BREAK``
handler) can flush and exit cleanly ahead of the hard
``TerminateJobObject`` fallback. Without it Windows has no soft-signal
tier and a graceful timeout collapses straight to an atomic Job Object
kill; any survivor past the grace is still hard-killed.

**Boundaries.** *Console-only* — a child spawned ``create_no_window()``
(or otherwise detached) shares no console, never receives the event, and
rides the grace to the hard kill; a GUI/service parent with no console
of its own can't deliver it either. It is ``CTRL_BREAK``, **not**
``CTRL_C``, and ``timeout_signal`` does not apply. Only the **direct
child** is addressed — its own descendants get it via the shared
console/group, but an ``adopt``ed process does not. A harmless **no-op
outside Windows** (Unix's graceful tier already sends a real signal) —
unlike the POSIX-only ``uid``/``gid``/``groups``/``setsid``/``umask``,
which raise ``Unsupported`` off-platform rather than silently
no-op'ing.

#### `uid`

```text
def uid(uid: int) -> Command
```

#### `gid`

```text
def gid(gid: int) -> Command
```

#### `groups`

```text
def groups(gids: Sequence[int]) -> Command
```

#### `setsid`

```text
def setsid() -> Command
```

#### `umask`

```text
def umask(mask: int) -> Command
```

#### `priority`

```text
def priority(level: Priority) -> Command
```

#### `output_limit`

```text
def output_limit(
    *,
    max_bytes: int | None = ...,
    max_lines: int | None = ...,
    on_overflow: Literal['drop_oldest', 'drop_newest', 'error'] = ...,
) -> Command
```

#### `output`

```text
def output() -> ProcessResult
```

#### `output_bytes`

```text
def output_bytes() -> BytesResult
```

#### `run`

```text
def run() -> str
```

#### `exit_code`

```text
def exit_code() -> int
```

#### `probe`

```text
def probe() -> bool
```

#### `resolve_program`

```text
def resolve_program() -> str
```

Resolve this command's ``program`` to a concrete executable path
**without launching it** — a spawn-free, side-effect-free preflight
("is this tool installed?"). Reuses the same PATH/PATHEXT/execute-bit
lookup a real run performs — a bare name against this command's
``prefer_local()`` directories (priority order) then the effective
``PATH``, a path-form program directly — honoring a relocated child
``PATH`` (``env()``/``env_remove()``/``env_clear()``/``inherit_env()``),
so the result is exactly what a spawn of this same command would find.
Returns the resolved **absolute** path; raises ``ProcessNotFound`` (also
a ``FileNotFoundError``, with a ``searched`` diagnostic) on a miss. No
``a``-prefixed async twin — the probe is synchronous and needs no
runtime.

#### `aoutput`

```text
def aoutput() -> Awaitable[ProcessResult]
```

#### `aoutput_bytes`

```text
def aoutput_bytes() -> Awaitable[BytesResult]
```

#### `arun`

```text
def arun() -> Awaitable[str]
```

#### `aexit_code`

```text
def aexit_code() -> Awaitable[int]
```

#### `aprobe`

```text
def aprobe() -> Awaitable[bool]
```

#### `start`

```text
def start() -> RunningProcess
```

#### `astart`

```text
def astart() -> Awaitable[RunningProcess]
```

#### `unchecked_in_pipe`

```text
def unchecked_in_pipe() -> Command
```

#### `program`

```text
program: str
```

#### `arguments`

```text
arguments: list[str]
```

#### `command_line`

```text
def command_line() -> str
```

#### `pipe`

```text
def pipe(other: Command) -> Pipeline
```

### `CliClient`

```text
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

```text
def command(args: Args) -> Command
```

A `Command` for `program <args>`, the client's defaults pre-applied
— chain more builders, then pass it to a verb below instead of a plain
arg list. An explicit setting on it always wins over the default.

#### `run`

```text
def run(call: Args | Command) -> str
```

#### `output`

```text
def output(call: Args | Command) -> ProcessResult
```

#### `output_bytes`

```text
def output_bytes(call: Args | Command) -> BytesResult
```

#### `exit_code`

```text
def exit_code(call: Args | Command) -> int
```

#### `probe`

```text
def probe(call: Args | Command) -> bool
```

#### `resolve_program`

```text
def resolve_program() -> str
```

Resolve this client's ``program`` to a concrete executable path
**without spawning it** — the client-level preflight ("is this tool
installed?"), with no side effects. Applies the client's defaults (so a
``default_env``/``default_env_fn`` that relocates ``PATH`` is honored
as at launch), then resolves via the same PATH/PATHEXT/execute-bit logic
a real run uses. Returns the resolved **absolute** path; a
``default_env_fn`` that raises or returns a non-``str`` aborts it
fail-closed (like the run verbs), and a miss raises ``ProcessNotFound``
(also a ``FileNotFoundError``, with a ``searched`` diagnostic). No
``a``-prefixed async twin — the probe is synchronous.

#### `arun`

```text
def arun(call: Args | Command) -> Awaitable[str]
```

#### `aoutput`

```text
def aoutput(call: Args | Command) -> Awaitable[ProcessResult]
```

#### `aoutput_bytes`

```text
def aoutput_bytes(call: Args | Command) -> Awaitable[BytesResult]
```

#### `aexit_code`

```text
def aexit_code(call: Args | Command) -> Awaitable[int]
```

#### `aprobe`

```text
def aprobe(call: Args | Command) -> Awaitable[bool]
```

### `Pipeline`

```text
class Pipeline
```

A shell-free pipeline `a | b | c`.

By design, no `start`/`astart` — see `Command.pipe()`'s stub/binding
comment: a pipeline is a whole-chain verb, with no natural "handle to a
live chain" to hand back. Stream an individual stage by `start()`ing that
one `Command` directly instead.

#### `pipe`

```text
def pipe(other: Command) -> Pipeline
```

#### `timeout`

```text
def timeout(seconds: float) -> Pipeline
```

#### `cancel_on`

```text
def cancel_on(token: CancellationToken) -> Pipeline
```

#### `output`

```text
def output() -> ProcessResult
```

#### `output_bytes`

```text
def output_bytes() -> BytesResult
```

#### `run`

```text
def run() -> str
```

#### `exit_code`

```text
def exit_code() -> int
```

#### `probe`

```text
def probe() -> bool
```

#### `aoutput`

```text
def aoutput() -> Awaitable[ProcessResult]
```

#### `aoutput_bytes`

```text
def aoutput_bytes() -> Awaitable[BytesResult]
```

#### `arun`

```text
def arun() -> Awaitable[str]
```

#### `aexit_code`

```text
def aexit_code() -> Awaitable[int]
```

#### `aprobe`

```text
def aprobe() -> Awaitable[bool]
```

### `RunningProcess`

```text
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

```text
pid: int | None
```

#### `elapsed_seconds`

```text
elapsed_seconds: float | None
```

#### `cpu_time_seconds`

```text
cpu_time_seconds: float | None
```

#### `peak_memory_bytes`

```text
peak_memory_bytes: int | None
```

#### `stdout_line_count`

```text
stdout_line_count: int | None
```

#### `stderr_line_count`

```text
stderr_line_count: int | None
```

#### `owns_group`

```text
owns_group: bool | None
```

#### `stdout_lines`

```text
def stdout_lines() -> StdoutLines
```

#### `output_events`

```text
def output_events() -> OutputEvents
```

#### `take_stdin`

```text
def take_stdin() -> ProcessStdin
```

The writable stdin handle. Raises `ProcessError` if stdin was not kept
open (build the `Command` with ``keep_stdin_open()``) or was already
taken — so a missing setup fails here, not with a later `AttributeError`.

#### `kill`

```text
def kill() -> None
```

Begin tearing the tree down without waiting (like
``subprocess.Popen.kill()``: fire-and-forget).

#### `outcome`

```text
def outcome() -> Outcome
```

#### `aoutcome`

```text
def aoutcome() -> Awaitable[Outcome]
```

#### `finish`

```text
def finish() -> Finished
```

#### `afinish`

```text
def afinish() -> Awaitable[Finished]
```

#### `output`

```text
def output() -> ProcessResult
```

#### `aoutput`

```text
def aoutput() -> Awaitable[ProcessResult]
```

#### `output_bytes`

```text
def output_bytes() -> BytesResult
```

#### `aoutput_bytes`

```text
def aoutput_bytes() -> Awaitable[BytesResult]
```

#### `profile`

```text
def profile(every_seconds: float) -> RunProfile
```

#### `aprofile`

```text
def aprofile(every_seconds: float) -> Awaitable[RunProfile]
```

#### `shutdown`

```text
def shutdown(grace_seconds: float) -> Outcome
```

Graceful teardown (signal -> wait ``grace_seconds`` -> hard kill),
returning the `Outcome`; consumes the handle. Only for a standalone
``start()``/``astart()`` handle — a handle from ``ProcessGroup.start()``
raises `Unsupported`; tear such a child down via the group (or `kill()`).
Named to match ``ProcessGroup.shutdown()``/``ashutdown()``.

#### `ashutdown`

```text
def ashutdown(grace_seconds: float) -> Awaitable[Outcome]
```

Async counterpart of `shutdown`.

## Program resolution

Resolve a program to its concrete executable path *without* launching it — a spawn-free preflight ("is this tool installed?") that reuses the same PATH/PATHEXT/execute-bit lookup a real run performs, so it never disagrees with what a spawn would find. The module-level `which` searches the process `PATH`; `Command.resolve_program()` and `CliClient.resolve_program()` additionally honor a `prefer_local` directory and a relocated child `PATH`. A miss raises `ProcessNotFound`.

### `which`

```text
def which(program: StrPath) -> str
```

## Results & outcomes

What a finished (or streamed) run reports back. A non-zero exit, a timeout, and a signal-kill are all *data* on these types — never raised by the capturing verbs.

### `ProcessResult`

```text
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

```text
stdout: str
```

#### `stderr`

```text
stderr: str
```

#### `code`

```text
code: int | None
```

#### `is_success`

```text
is_success: bool
```

#### `timed_out`

```text
timed_out: bool
```

#### `signal`

```text
signal: int | None
```

#### `program`

```text
program: str
```

#### `duration_seconds`

```text
duration_seconds: float
```

#### `truncated`

```text
truncated: bool
```

#### `combined`

```text
combined: str
```

#### `diagnostic`

```text
diagnostic: str | None
```

The best human-facing message: stderr if it carries text, otherwise
stdout, otherwise ``None`` if both are blank — the same preference
order as ``NonZeroExit``/``Timeout``/``Signalled.diagnostic``.

#### `outcome`

```text
outcome: Outcome
```

The full run outcome (``code`` / ``signal`` / ``timed_out``), the
same value ``RunProfile.outcome`` and the checking-verb exceptions
expose.

#### `ensure_success`

```text
def ensure_success() -> ProcessResult
```

Raise the same exception a checking verb would if this result's
exit isn't in ``success_codes``; returns ``self`` unchanged otherwise,
so it composes: ``cmd.output().ensure_success().stdout``.

### `BytesResult`

```text
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

```text
stdout: bytes
```

#### `stderr`

```text
stderr: str
```

#### `code`

```text
code: int | None
```

#### `is_success`

```text
is_success: bool
```

#### `timed_out`

```text
timed_out: bool
```

#### `signal`

```text
signal: int | None
```

#### `program`

```text
program: str
```

#### `duration_seconds`

```text
duration_seconds: float
```

#### `truncated`

```text
truncated: bool
```

Whether captured output was truncated by an ``output_limit(...)`` cap
— the line-captured stderr under any cap, and (since processkit 2.1.0)
the raw stdout too when an ``output_limit(max_bytes=...)`` byte ceiling
bounds it to a head/tail. A ``max_lines`` cap never truncates raw stdout
(bytes have no line count); only a ``max_bytes`` cap does.

#### `diagnostic`

```text
diagnostic: str | None
```

See ``ProcessResult.diagnostic``. Raw stdout is lossily decoded to
text for this message when stderr is blank.

#### `outcome`

```text
outcome: Outcome
```

See ``ProcessResult.outcome``.

#### `ensure_success`

```text
def ensure_success() -> BytesResult
```

See ``ProcessResult.ensure_success()``.

### `Outcome`

```text
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

```text
code: int | None
```

#### `signal`

```text
signal: int | None
```

#### `timed_out`

```text
timed_out: bool
```

#### `exited_zero`

```text
exited_zero: bool
```

### `Finished`

```text
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

```text
outcome: Outcome
```

#### `stderr`

```text
stderr: str
```

#### `code`

```text
code: int | None
```

#### `exited_zero`

```text
exited_zero: bool
```

#### `timed_out`

```text
timed_out: bool
```

#### `signal`

```text
signal: int | None
```

### `RunProfile`

```text
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

```text
code: int | None
```

#### `signal`

```text
signal: int | None
```

#### `timed_out`

```text
timed_out: bool
```

#### `outcome`

```text
outcome: Outcome
```

#### `duration_seconds`

```text
duration_seconds: float
```

#### `cpu_time_seconds`

```text
cpu_time_seconds: float | None
```

#### `peak_memory_bytes`

```text
peak_memory_bytes: int | None
```

#### `samples`

```text
samples: int
```

#### `avg_cpu_cores`

```text
avg_cpu_cores: float | None
```

## Streaming & interactive I/O

The live handles a started `RunningProcess` hands out: async iterators over its output (line by line, or as interleaved stdout/stderr events) and a writable stdin.

### `StdoutLines`

```text
class StdoutLines
```

Async iterator over a process's stdout, line by line.

### `OutputEvents`

```text
class OutputEvents
```

Async iterator over stdout + stderr as interleaved `OutputEvent`s.

### `OutputEvent`

```text
class OutputEvent
```

One captured line and the stream it came from.

#### `stream`

```text
stream: Literal['stdout', 'stderr']
```

#### `is_stderr`

```text
is_stderr: bool
```

#### `text`

```text
text: str
```

### `ProcessStdin`

```text
class ProcessStdin
```

A writable handle to a running process's stdin (all methods awaitable).

#### `write`

```text
def write(data: ReadableBuffer) -> Awaitable[None]
```

#### `write_line`

```text
def write_line(line: str) -> Awaitable[None]
```

#### `send_control`

```text
def send_control(control: str) -> Awaitable[None]
```

Write one mapped control byte, e.g. ``"c"`` -> Ctrl-C (``\x03``).

This writes a byte to the child's stdin pipe, not a terminal signal;
real SIGINT/SIGTSTP delivery requires a pseudoterminal.

#### `flush`

```text
def flush() -> Awaitable[None]
```

#### `close`

```text
def close() -> Awaitable[None]
```

## Process groups

Kill-on-drop containment for a whole process tree — start children into it, signal or suspend the group, and reap the entire tree (grandchildren included) on exit. `MemberInfo` is the enriched per-member snapshot `members_info()` returns; `sample_stats` turns a one-shot `stats()` snapshot into a periodic async series for live monitoring.

### `ProcessGroup`

```text
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

```text
mechanism: Literal['job_object', 'cgroup_v2', 'process_group', 'unknown']
```

#### `members`

```text
def members() -> list[int]
```

#### `members_info`

```text
def members_info() -> list[MemberInfo]
```

An enriched, point-in-time snapshot of the group's members — the same
set as ``members()``, but each pid carried in a `MemberInfo` alongside
best-effort ``ppid``/``exe_name``/``start_time``. Synchronous only (the
crate offers no async twin). See `MemberInfo` for the per-field platform
matrix and the ``start_time`` opacity/pid-reuse note.

#### `signal`

```text
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

```text
def suspend() -> None
```

#### `resume`

```text
def resume() -> None
```

#### `kill_all`

```text
def kill_all() -> None
```

#### `stats`

```text
def stats() -> ProcessGroupStats
```

#### `shutdown`

```text
def shutdown() -> None
```

#### `ashutdown`

```text
def ashutdown() -> Awaitable[None]
```

### `ProcessGroupStats`

```text
class ProcessGroupStats
```

A snapshot of a `ProcessGroup`'s resource usage.

#### `active_process_count`

```text
active_process_count: int
```

#### `peak_memory_bytes`

```text
peak_memory_bytes: int | None
```

#### `total_cpu_time_seconds`

```text
total_cpu_time_seconds: float | None
```

### `MemberInfo`

```text
class MemberInfo
```

An enriched, point-in-time snapshot of one member of a `ProcessGroup`'s
tree — its pid plus best-effort metadata.

The metadata-carrying companion to a bare pid from `ProcessGroup.members()`.
*Which* members appear follows the same platform matrix as ``members()`` (the
whole tree on Windows and the Linux cgroup backend; the tracked group leaders
on the POSIX process-group fallback). Every field beyond ``pid`` is
independently ``None`` wherever the platform can't report it — never a
fabricated value — and a member that exits mid-snapshot is silently omitted,
not invented.

The raw command line / environment is **deliberately never** carried, on any
platform: an argv routinely holds secrets, and redaction is the consumer's
policy to own.

Field availability (``None`` where the platform can't report it): ``ppid``,
``exe_name``, and ``start_time`` are populated on Windows, Linux, and macOS,
and are always ``None`` on the BSDs (no wired-up per-process reader).

#### `pid`

```text
pid: int
```

The member's process id — always present. Point-in-time, like a pid
from ``members()``: pair it with ``start_time`` to tell a recycled number
apart from the original process.

#### `ppid`

```text
ppid: int | None
```

The member's parent process id, or ``None`` where unreadable (always
``None`` on the BSDs).

#### `exe_name`

```text
exe_name: str | None
```

The member's short image **base name** — never a full path, and never a
command line (the crate never exposes argv/env). ``None`` where unreadable
(always ``None`` on the BSDs).

#### `start_time`

```text
start_time: int | None
```

An **opaque per-process identity token**, or ``None`` where unreadable —
**not** a wall-clock timestamp. Its unit and epoch are platform-specific
(Windows creation ``FILETIME``, 100ns intervals since 1601; Linux
``/proc/<pid>/stat`` field 22, clock ticks since boot; macOS microseconds
since the Unix epoch; always ``None`` on the BSDs), so do not interpret it
or compare it across platforms. Its sole use is pairing with ``pid``: two
snapshots whose ``pid`` **and** ``start_time`` both match name the same
process instance, telling a recycled pid apart from the original.

### `sample_stats`

```text
async def sample_stats(
    group: ProcessGroup,
    every: float,
) -> AsyncIterator[ProcessGroupStats]
```

Sample ``group.stats()`` on an interval, forever, as an async series of
`ProcessGroupStats` snapshots — a pure-Python analogue of the crate's
`ProcessGroup::sample_stats` (its `StatsSampler` borrows the group by
lifetime and has no FFI-safe equivalent here; this is plain Python built
directly on the already-public `group.stats()`, living alongside the
readiness helpers above for the same reason).

``async for snapshot in sample_stats(group, every): ...`` — the first
snapshot is taken immediately (no initial sleep), then one every ``every``
seconds, for as long as you keep consuming. There is no overall deadline;
stop by ``break``ing out of the loop or otherwise abandoning/closing the
generator yourself.

**Fused, and louder than the crate's stream.** The crate's `StatsSampler`
swallows the error on the first failed sample and just ends the series
silently — a caller has to separately call `stats()` to learn why. This
generator instead lets `group.stats()`'s own exception (a `ProcessError` —
e.g. "ProcessGroup is already closed" once the group has torn down, or an
`Unsupported`/OS-error-derived failure from the platform's resource query)
propagate out of the ``async for`` untouched — the underlying cause is
never hidden behind a quiet end-of-series. That still fuses the series:
once this generator function raises, it is exhausted by Python's own
async-generator protocol, so a further ``__anext__`` (another loop
iteration, a second ``async for`` over the same object) raises
`StopAsyncIteration` rather than calling `group.stats()` again or
replaying the same error. If the group is already closed/invalid *before
the first snapshot* (e.g. iteration starts only after `group.shutdown()`
already ran), that same exception surfaces on the very first ``async
for`` step, not silently as an empty series.

``every`` is validated up front: NaN and negative values raise
`ValueError` (the shared convention with the readiness helpers'
``timeout``/``interval``). Unlike the crate — which clamps a zero period
to 1 ms because `tokio` panics on a zero-duration interval — ``every=0``
is accepted here as-is: `asyncio.sleep(0)` has no such restriction, so it
means "sample as fast as the event loop allows," with no artificial floor.

## Supervision

Keep a command alive: restart it per a policy, with backoff and jitter, until a stop condition is met.

### `Supervisor`

```text
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
    health_check: Callable[[], bool] | None = ...,
    health_check_interval: float | None = ...,
    health_check_failures: int | None = ...,
    runner: RunnerLike | None = ...,
)
```

Keep a command alive: restart per policy with backoff until a stop condition.

#### `run`

```text
def run() -> SupervisionOutcome
```

#### `arun`

```text
def arun() -> Awaitable[SupervisionOutcome]
```

### `SupervisionOutcome`

```text
class SupervisionOutcome
```

The result of a `Supervisor.run()`.

Value semantics: `==`/`hash()` compare every field (`final_result` via
`ProcessResult`'s own comparison, plus
`restarts`/`stopped`/`storm_pauses`/`liveness_kills`).
**Not** picklable: its identity includes `final_result` (a `ProcessResult`),
which cannot be faithfully reconstructed from a pickle (its `timeout`/
`success_codes` have no accessor to read back), so pickling raises
`TypeError`. Read the fields you need, or pickle `final_result.outcome` (an
`Outcome`, which round-trips exactly), to cross a process boundary.

#### `final_result`

```text
final_result: ProcessResult
```

#### `restarts`

```text
restarts: int
```

#### `stopped`

```text
stopped: Literal['policy_satisfied', 'predicate', 'restarts_exhausted', 'gave_up', 'unhealthy', 'unknown']
```

#### `storm_pauses`

```text
storm_pauses: int
```

#### `liveness_kills`

```text
liveness_kills: int
```

## Cancellation

A portable cancel switch, wired into a run via `Command.cancel_on()`, `Pipeline.cancel_on()`, or `CliClient`'s `default_cancel_on=`.

### `CancellationToken`

```text
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

```text
def cancel() -> None
```

#### `is_cancelled`

```text
def is_cancelled() -> bool
```

#### `child_token`

```text
def child_token() -> CancellationToken
```

A new token that is cancelled automatically when this one is, but
can also be cancelled independently — cancelling the child does not
affect this token or its other children.

## Batch execution

Run many commands with bounded concurrency, each result — or a `ProcessError` for a spawn/I/O failure — in its own slot. The `output_all` family is *collect-all* (every result in input order once the whole batch finishes); `aoutput_as_completed` and its `_bytes` twin instead stream each `(index, result)` pair *as it finishes*, for progress and early reaction on a large fan-out.

### `output_all`

```text
def output_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[ProcessResult | ProcessError]
```

### `output_all_bytes`

```text
def output_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[BytesResult | ProcessError]
```

### `aoutput_all`

```text
def aoutput_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> Awaitable[list[ProcessResult | ProcessError]]
```

### `aoutput_all_bytes`

```text
def aoutput_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> Awaitable[list[BytesResult | ProcessError]]
```

### `aoutput_as_completed`

```text
def aoutput_as_completed(
    commands: Sequence[Command],
    *,
    concurrency: int | None = None,
) -> AsyncIterator[tuple[int, ProcessResult | ProcessError]]
```

Run ``commands`` with bounded concurrency, yielding each ``(original
index, ProcessResult | ProcessError)`` pair **as that command finishes** —
the streaming, pure-Python counterpart to the compiled `aoutput_all`.

Where `aoutput_all` is *collect-all* (nothing is visible until the whole
batch is done), this is an async iterator — ``async for index, result in
aoutput_as_completed(commands, concurrency=8): ...`` — that hands each
result back the moment its command completes, so a large fan-out reports
progress and lets you react to early finishers instead of blocking on the
slowest command in the batch.

**Completion order, not input order.** Pairs arrive in the order their
commands *finish*, which is generally not the input order; the ``index`` (a
command's position in ``commands``) is what re-associates a result with the
command that produced it. Every command is yielded exactly once, and the
iterator is exhausted once all of them have been.

**Errors are per-slot data, not a series-ending raise** (aligned with
`output_all`): a command that fails to *spawn* — or hits an I/O error, or is
cancelled through its own `CancellationToken` — yields its `ProcessError` in
its own pair, and never short-circuits the others. A non-zero exit, a
timeout, and a signal-kill are, as everywhere in this library, *data* on a
`ProcessResult`, not errors at all.

**Hard concurrency cap.** At most ``concurrency`` commands are ever live at
once (an `asyncio.Semaphore` gates each `Command.aoutput()`), so fanning out
hundreds of commands can't exhaust file descriptors or the process table —
the same bound `aoutput_all` gives, held *while* streaming. ``concurrency``
defaults to the CPU count (`os.cpu_count()`), matching the batch family; a
non-positive value raises `ValueError` rather than being silently clamped.

**No orphans on cancellation or early exit.** Cancelling the task consuming
this iterator — or simply ``break``ing out of the ``async for`` early — tears
down every command still in flight: each `Command.aoutput()` reaps its whole
process subtree (grandchildren included) on cancellation, and this iterator
drives that teardown for *all* live slots before it finishes unwinding. No
started child is left orphaned, whether the batch ran to completion, was
abandoned partway, or was cancelled outright.

Built directly on `Command.aoutput()`; unlike the compiled `aoutput_all`
family it takes no ``runner=`` double — the streaming layer is deliberately
kept minimal, so for a hermetic batch that doesn't need streaming reach for
`aoutput_all(..., runner=...)` instead. For raw ``bytes`` output (no UTF-8
decode) use the twin `aoutput_as_completed_bytes`.

### `aoutput_as_completed_bytes`

```text
def aoutput_as_completed_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = None,
) -> AsyncIterator[tuple[int, BytesResult | ProcessError]]
```

The raw-``bytes`` twin of `aoutput_as_completed`: the identical streaming,
concurrency-cap, per-slot-error, and no-orphan-on-cancellation contract, but
each finished command yields a `BytesResult` — its stdout/stderr as undecoded
``bytes``, for non-UTF-8 or binary output — in place of a text
`ProcessResult`, mirroring how `aoutput_all_bytes` relates to `aoutput_all`.
See `aoutput_as_completed` for the full contract.

## Readiness helpers

Asyncio helpers that wait for a condition — a matching output line, an open TCP port, an HTTP endpoint answering with an expected status, a filesystem path, or any polled predicate — bounded by a deadline.

### `wait_until`

```text
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

```text
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

```text
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

### `wait_for_http`

```text
async def wait_for_http(
    host: str,
    port: int,
    path: str = '/',
    *,
    timeout: float,
    interval: float = 0.05,
    expected_status: Container[int] | Callable[[int], bool] | None = None,
) -> None
```

Wait until an HTTP ``GET`` of ``http://host:port/path`` answers with an
acceptable status code.

A stronger readiness signal than `wait_for_port`: a server often *accepts*
TCP connections while still warming up and answering ``503``, so a bare port
probe reports ready too early. This one performs a minimal HTTP/1.1 ``GET``
(hand-rolled over `asyncio.open_connection` — no `http.client` / `urllib` /
third-party dependency) every ``interval`` seconds and succeeds only once the
response's status code is accepted.

``expected_status`` decides what "accepted" means: either a container tested
with ``in`` or a predicate ``Callable[[int], bool]`` for arbitrary logic
(e.g. ``lambda c: c == 204``). The default (``None``) accepts any 2xx code —
equivalent to passing ``range(200, 300)``. The whole request/response is
bounded by the deadline, so a server that accepts the connection but never
answers can't outlive ``timeout``.

On failure the deadline raises `WaitTimeout` (also a `TimeoutError`),
carrying ``host`` / ``port`` / ``path`` and chained (as ``__cause__``) from
the last attempt's failure — a connection error (e.g. a refused connect or a
DNS failure) or a `ProcessError` recording the last unexpected status code —
so the evidence for *why* it never became ready survives.

``timeout<=0`` contract (shared with `wait_until` / `wait_for_port` /
`wait_for_line` / `wait_for_path`): at ``timeout=0`` one request attempt is
still made (at least one), so an already-ready endpoint succeeds instead of
failing before it was ever probed; that first attempt is bounded to a short,
fixed event-loop tick (or a smaller caller-supplied ``interval``), never left
uncapped. A **negative** ``timeout`` is rejected outright — raises
`ValueError`, same as NaN — as is a non-positive ``interval``.

### `wait_for_path`

```text
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

```text
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
`wait_for_http` / `wait_for_path`) didn't succeed within its deadline.

Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
the same convention a run's own `.timeout()` uses (see `Timeout`). Always
carries `timeout_seconds`; `wait_for_port` and `wait_for_http` additionally
set `host` / `port` (and `wait_for_http` also `path`), and `wait_for_path`
sets `path` (all `None` for `wait_until` / `wait_for_line`, which have none
of these). `wait_for_port` / `wait_for_http` also chain the last attempt's
failure as `__cause__` (a connection error, or — for `wait_for_http` — the
last unexpected status code).

#### `timeout_seconds`

```text
timeout_seconds = timeout_seconds
```

#### `host`

```text
host = host
```

#### `port`

```text
port = port
```

#### `path`

```text
path = path
```

## Observability

Opt-in bridging of the core's per-run `tracing` events to Python `logging`.

### `enable_logging`

```text
def enable_logging() -> bool
```

## The runner seam

The dependency-injection seam: annotate your code against a protocol, inject the real `Runner` in production and a test double (see the Testing section) in tests. `ProcessRunner` is the capture/check verbs; `StreamingRunner` adds `start`/`astart`.

### `ProcessRunner`

```text
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

```text
def output(command: Command, /) -> ProcessResult
```

#### `output_bytes`

```text
def output_bytes(command: Command, /) -> BytesResult
```

#### `run`

```text
def run(command: Command, /) -> str
```

#### `exit_code`

```text
def exit_code(command: Command, /) -> int
```

#### `probe`

```text
def probe(command: Command, /) -> bool
```

#### `aoutput`

```text
def aoutput(command: Command, /) -> Awaitable[ProcessResult]
```

#### `aoutput_bytes`

```text
def aoutput_bytes(command: Command, /) -> Awaitable[BytesResult]
```

#### `arun`

```text
def arun(command: Command, /) -> Awaitable[str]
```

#### `aexit_code`

```text
def aexit_code(command: Command, /) -> Awaitable[int]
```

#### `aprobe`

```text
def aprobe(command: Command, /) -> Awaitable[bool]
```

### `StreamingRunner`

```text
class StreamingRunner
```

`ProcessRunner` plus `start`/`astart` — the full runner verb surface,
for code that also needs a live `RunningProcess` handle to stream.

`Runner`, `ScriptedRunner`, `RecordReplayRunner`, `RecordingRunner`, and
`DryRunRunner` all satisfy it. A hand-rolled double can implement the
capture/check verbs easily, but `start`/`astart` must return a
`RunningProcess`, which has no public constructor — and the built-in
runners are `@final`, so a fully-conforming custom runner in practice means
*wrapping* one (delegating `start`/`astart` to it; use `ScriptedRunner`
for streaming doubles).

#### `start`

```text
def start(command: Command, /) -> RunningProcess
```

#### `astart`

```text
def astart(command: Command, /) -> Awaitable[RunningProcess]
```

### `Runner`

```text
class Runner
```

The real process runner — inject it for testable code.

## Exceptions

Every error raised by the package descends from `ProcessError`, so a single `except ProcessError` catches them all. `Timeout`, `ProcessNotFound`, and `PermissionDenied` also subclass a builtin (`TimeoutError` / `FileNotFoundError` / `PermissionError`, each itself an `OSError`), so the stdlib `except` clauses catch them too.

### `ProcessError`

```text
class ProcessError
```

Base class for every error raised by this package.

### `NonZeroExit`

```text
class NonZeroExit
```

`run()` / `exit_code()` got a non-zero exit.

#### `program`

```text
program: str
```

#### `code`

```text
code: int
```

#### `stdout`

```text
stdout: str
```

#### `stderr`

```text
stderr: str
```

#### `stdout_bytes`

```text
stdout_bytes: bytes | None
```

#### `diagnostic`

```text
diagnostic: str | None
```

### `Timeout`

```text
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

```text
program: str
```

#### `timeout_seconds`

```text
timeout_seconds: float | None
```

#### `stdout`

```text
stdout: str
```

#### `stderr`

```text
stderr: str
```

#### `stdout_bytes`

```text
stdout_bytes: bytes | None
```

#### `diagnostic`

```text
diagnostic: str | None
```

### `Signalled`

```text
class Signalled
```

A run was killed by a signal.

#### `program`

```text
program: str
```

#### `signal`

```text
signal: int | None
```

#### `stdout`

```text
stdout: str
```

#### `stderr`

```text
stderr: str
```

#### `stdout_bytes`

```text
stdout_bytes: bytes | None
```

#### `diagnostic`

```text
diagnostic: str | None
```

### `ProcessNotFound`

```text
class ProcessNotFound
```

The program could not be found / spawned.

Also a builtin `FileNotFoundError` (what `subprocess` raises), so
`except FileNotFoundError` catches it too.

#### `program`

```text
program: str
```

#### `searched`

```text
searched: str | None
```

### `PermissionDenied`

```text
class PermissionDenied
```

The program could not be spawned because of insufficient permissions
(e.g. a non-executable file), or a permission-denied OS error surfaced
from elsewhere in the run (e.g. a group signal the OS refused).

Also a builtin `PermissionError`, so `except PermissionError` catches it too.

#### `program`

```text
program: str | None
```

### `ResourceLimit`

```text
class ResourceLimit
```

A resource limit (memory / processes / CPU) was invalid or could not be
enforced by the active containment mechanism. The reason is the exception
message (``str(exc)``); it carries no extra structured field.

### `Unsupported`

```text
class Unsupported
```

The operation is not supported on this platform.

#### `operation`

```text
operation: str
```

### `OutputTooLarge`

```text
class OutputTooLarge
```

Captured output hit an `output_limit(..., on_overflow="error")` ceiling.

#### `program`

```text
program: str
```

#### `max_lines`

```text
max_lines: int | None
```

#### `max_bytes`

```text
max_bytes: int | None
```

#### `total_lines`

```text
total_lines: int
```

#### `total_bytes`

```text
total_bytes: int
```

### `Cancelled`

```text
class Cancelled
```

The run was deliberately cancelled via a `CancellationToken` wired
with `Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
`Pipeline.cancel_on()`. Terminal — never retried by `Command.retry()` or
restarted by `Supervisor` (the token stays cancelled forever, so another
attempt could only fail the same way).

#### `program`

```text
program: str
```

## Type aliases

Exported so your own wrappers can annotate against the same types the API accepts.

### `Args`

```text
Args = list[str] | list[Path] | list[os.PathLike[str]] | tuple[StrPath, ...]
```

### `LineTerminatorName`

```text
LineTerminatorName = Literal['newline', 'carriage_return']
```

### `Priority`

```text
Priority = Literal['idle', 'below_normal', 'normal', 'above_normal', 'high']
```

### `ReadableBuffer`

```text
ReadableBuffer = bytes | bytearray | memoryview
```

### `RetryIf`

```text
RetryIf = Literal['transient', 'transient_or_timeout']
```

### `SignalName`

```text
SignalName = Literal['term', 'kill', 'int', 'hup', 'quit', 'usr1', 'usr2']
```

### `StrPath`

```text
StrPath = str | os.PathLike[str]
```

## Testing

Runner test doubles, in the `processkit.testing` submodule. Inject one in tests — all satisfy the `ProcessRunner` protocol — so the code under test spawns no real processes.

### `ScriptedRunner`

```text
class ScriptedRunner
```

A scripted test double for `Runner`.

#### `on`

```text
def on(prefix: Args, reply: Reply) -> None
```

#### `on_sequence`

```text
def on_sequence(prefix: Args, replies: Sequence[Reply]) -> None
```

#### `when`

```text
def when(predicate: Callable[[Command], bool], reply: Reply) -> None
```

#### `fallback`

```text
def fallback(reply: Reply) -> None
```

### `RecordReplayRunner`

```text
class RecordReplayRunner
```

Records real runs to a cassette file (`record`) and replays them without
spawning (`replay`); shares the `Runner` run-verb surface.

#### `record`

```text
def record(path: StrPath) -> RecordReplayRunner
```

#### `replay`

```text
def replay(path: StrPath) -> RecordReplayRunner
```

#### `save`

```text
def save() -> None
```

### `RecordingRunner`

```text
class RecordingRunner
```

A recording test double: replies to every command with a canned `Reply`
and records each call, so a test can assert on what its code ran. Shares the
`Runner` run-verb surface; inspect calls with `calls()` / `only_call()`.

#### `replying`

```text
def replying(reply: Reply) -> RecordingRunner
```

#### `new`

```text
def new(inner: RunnerLike) -> RecordingRunner
```

#### `calls`

```text
def calls() -> list[Invocation]
```

#### `only_call`

```text
def only_call() -> Invocation
```

### `DryRunRunner`

```text
class DryRunRunner
```

A dry-run test double: never spawns a process. Every verb renders the
command to its display-quoted line (like `Command.command_line()`) and
returns a synthetic successful result — the seam behind a tool's own
`--dry-run`/`--echo` mode. Shares the `Runner` run-verb surface; inspect the
rendered lines with `commands()` / `only_command()`, or stream them live
with `on_invocation()`.

#### `on_invocation`

```text
def on_invocation(callback: Callable[[str], None]) -> None
```

#### `commands`

```text
def commands() -> list[str]
```

#### `only_command`

```text
def only_command() -> str
```

### `Reply`

```text
class Reply
```

A canned reply for a `ScriptedRunner` rule.

#### `ok`

```text
def ok(stdout: str) -> Reply
```

#### `fail`

```text
def fail(code: int, stderr: str) -> Reply
```

#### `timeout`

```text
def timeout() -> Reply
```

#### `signalled`

```text
def signalled(signal: int | None = ...) -> Reply
```

#### `pending`

```text
def pending() -> Reply
```

#### `lines`

```text
def lines(lines: Sequence[str]) -> Reply
```

#### `with_stdout`

```text
def with_stdout(stdout: str) -> Reply
```

#### `with_stderr`

```text
def with_stderr(stderr: str) -> Reply
```

#### `with_line_delay`

```text
def with_line_delay(seconds: float) -> Reply
```

### `Invocation`

```text
class Invocation
```

One call captured by a `RecordingRunner`: the program, args, cwd, env
overrides, and whether stdin was supplied. Values are inspectable for
assertions; the `repr` stays redacted (program, arg count, cwd, env names,
has_stdin — never argv or env values).

#### `program`

```text
program: str
```

#### `args`

```text
args: list[str]
```

#### `cwd`

```text
cwd: str | None
```

#### `env`

```text
env: dict[str, str | None]
```

#### `env_is`

```text
def env_is(name: str, value: str) -> bool
```

#### `has_env`

```text
def has_env(name: str) -> bool
```

#### `has_stdin`

```text
has_stdin: bool
```

#### `has_flag`

```text
def has_flag(flag: str) -> bool
```
