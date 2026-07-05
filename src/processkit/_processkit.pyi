"""Type stubs for the compiled `_processkit` extension module.

mypy cannot see into the PyO3 cdylib, so the public surface is declared here.
Keep this in sync with `src/lib.rs`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from types import TracebackType
from typing import Literal, final

# `StrPath` (program/path arg: `str` or `os.PathLike[str]`), `Args` (an argv-like
# list/tuple of them — deliberately not `Sequence[StrPath]`, see `_types.py`),
# `SignalName`, `RetryIf`, and `ReadableBuffer` are the single source in
# `_types`, re-exported from the package so callers can annotate with them;
# imported here for the signatures below.
from ._types import Args, ReadableBuffer, RetryIf, SignalName, StrPath

@final
class ProcessResult:
    """The captured result of a finished run. A non-zero exit, a timeout, and a
    signal-kill are all reported as data here — never raised by `output()`."""

    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def code(self) -> int | None: ...
    @property
    def is_success(self) -> bool: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def signal(self) -> int | None: ...
    @property
    def program(self) -> str: ...
    @property
    def duration_seconds(self) -> float: ...
    @property
    def truncated(self) -> bool: ...
    @property
    def combined(self) -> str: ...
    def ensure_success(self) -> ProcessResult:
        """Raise the same exception a checking verb would if this result's
        exit isn't in ``success_codes``; returns ``self`` unchanged otherwise,
        so it composes: ``cmd.output().ensure_success().stdout``."""

    def __repr__(self) -> str: ...

@final
class BytesResult:
    """The captured result of a run with raw-bytes stdout (`Command.output_bytes()`);
    stderr stays decoded text. A non-zero exit, a timeout, and a signal-kill are
    all data here, never raised."""

    @property
    def stdout(self) -> bytes: ...
    @property
    def stderr(self) -> str: ...
    @property
    def code(self) -> int | None: ...
    @property
    def is_success(self) -> bool: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def signal(self) -> int | None: ...
    @property
    def program(self) -> str: ...
    @property
    def duration_seconds(self) -> float: ...
    @property
    def truncated(self) -> bool:
        """Whether captured *stderr* was truncated by an ``output_limit`` cap;
        raw bytes stdout is never line-capped."""

    def ensure_success(self) -> BytesResult:
        """See ``ProcessResult.ensure_success()``."""

    def __repr__(self) -> str: ...

@final
class Command:
    """A command builder. Builder methods return a new `Command`."""

    def __init__(self, program: StrPath, args: Args | None = ...) -> None: ...
    def arg(self, arg: StrPath) -> Command: ...
    def args(self, args: Args) -> Command: ...
    def cwd(self, path: StrPath) -> Command: ...
    def env(self, key: str, value: str) -> Command: ...
    def envs(self, vars: Mapping[str, str]) -> Command: ...
    def env_remove(self, key: str) -> Command: ...
    def env_clear(self) -> Command: ...
    def inherit_env(self, names: Sequence[str]) -> Command: ...
    def stdin_bytes(self, data: ReadableBuffer) -> Command: ...
    def stdin_text(self, text: str) -> Command: ...
    def keep_stdin_open(self) -> Command: ...
    def timeout(self, seconds: float) -> Command: ...
    def timeout_grace(self, seconds: float) -> Command: ...
    def timeout_signal(self, name: SignalName | int) -> Command: ...
    def no_timeout(self) -> Command: ...
    def cancel_on(self, token: CancellationToken) -> Command: ...
    def success_codes(self, codes: Sequence[int]) -> Command: ...
    def retry(
        self,
        retry_if: RetryIf,
        *,
        max_retries: int | None = ...,
        initial_backoff: float | None = ...,
        multiplier: float | None = ...,
        max_backoff: float | None = ...,
        jitter: bool | None = ...,
    ) -> Command: ...
    def stdout(self, mode: Literal["pipe", "inherit", "null"]) -> Command: ...
    def stderr(self, mode: Literal["pipe", "inherit", "null"]) -> Command: ...
    def encoding(self, label: str) -> Command: ...
    def stdout_encoding(self, label: str) -> Command: ...
    def stderr_encoding(self, label: str) -> Command: ...
    def stdout_tee(self, path: StrPath, *, append: bool = ...) -> Command:
        """Tee every decoded stdout line (line + ``\\n``) to the file at ``path``
        as it is produced, while the run *also* keeps capturing the full output
        (the sink does not steal from ``ProcessResult.stdout``).

        The sink is a **file path only** (``str`` / ``os.PathLike[str]``) — an
        arbitrary Python writer is deliberately not supported here (a separate,
        deferred feature). The file is opened **at build time** (not at run):
        created if absent and truncated, or opened in append mode when
        ``append=True``; an unopenable path raises the matching ``OSError``
        subclass right here. Inert unless stdout is piped through the line pump
        — a no-op under ``stdout("inherit")`` / ``stdout("null")`` and under
        ``output_bytes()`` (raw capture)."""

    def stderr_tee(self, path: StrPath, *, append: bool = ...) -> Command:
        """Tee every decoded stderr line to the file at ``path``. Same contract
        as ``stdout_tee`` — a file-path sink, opened at build time (truncate by
        default or ``append``), coexisting with capture, inert unless stderr is
        piped through the line pump."""

    def kill_on_parent_death(self) -> Command: ...
    def create_no_window(self) -> Command: ...
    def uid(self, uid: int) -> Command: ...
    def gid(self, gid: int) -> Command: ...
    def groups(self, gids: Sequence[int]) -> Command: ...
    def setsid(self) -> Command: ...
    def output_limit(
        self,
        *,
        max_bytes: int | None = ...,
        max_lines: int | None = ...,
        on_overflow: Literal["drop_oldest", "drop_newest", "error"] = ...,
    ) -> Command: ...
    def output(self) -> ProcessResult: ...
    def output_bytes(self) -> BytesResult: ...
    def run(self) -> str: ...
    def exit_code(self) -> int: ...
    def probe(self) -> bool: ...
    async def aoutput(self) -> ProcessResult: ...
    async def aoutput_bytes(self) -> BytesResult: ...
    async def arun(self) -> str: ...
    async def aexit_code(self) -> int: ...
    async def aprobe(self) -> bool: ...
    def start(self) -> RunningProcess: ...
    async def astart(self) -> RunningProcess: ...
    def unchecked_in_pipe(self) -> Command: ...
    @property
    def program(self) -> str: ...
    @property
    def arguments(self) -> list[str]: ...
    def command_line(self) -> str: ...
    def pipe(self, other: Command) -> Pipeline: ...
    def __or__(self, other: Command, /) -> Pipeline: ...
    def __repr__(self) -> str: ...

@final
class Pipeline:
    """A shell-free pipeline `a | b | c`.

    By design, no `start`/`astart` — see `Command.pipe()`'s stub/binding
    comment: a pipeline is a whole-chain verb, with no natural "handle to a
    live chain" to hand back. Stream an individual stage by `start()`ing that
    one `Command` directly instead."""

    def pipe(self, other: Command) -> Pipeline: ...
    def __or__(self, other: Command, /) -> Pipeline: ...
    def timeout(self, seconds: float) -> Pipeline: ...
    # Gap-fill (not override, unlike Command.cancel_on): a stage with its own
    # explicit token keeps it; this only fills stages that don't have one.
    def cancel_on(self, token: CancellationToken) -> Pipeline: ...
    def output(self) -> ProcessResult: ...
    def output_bytes(self) -> BytesResult: ...
    def run(self) -> str: ...
    def exit_code(self) -> int: ...
    def probe(self) -> bool: ...
    async def aoutput(self) -> ProcessResult: ...
    async def aoutput_bytes(self) -> BytesResult: ...
    async def arun(self) -> str: ...
    async def aexit_code(self) -> int: ...
    async def aprobe(self) -> bool: ...
    def __repr__(self) -> str: ...

@final
class CancellationToken:
    """A cancel switch: fire it to tear down every run wired to it via
    `Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
    `Pipeline.cancel_on()` — surfacing `Cancelled`. Cheap to clone/share:
    every clone and every `child_token()` refers to the same underlying
    cancellation state. A cancelled token stays cancelled forever."""

    def __init__(self) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    def child_token(self) -> CancellationToken: ...
    def __repr__(self) -> str: ...

@final
class Outcome:
    """How a process ended.

    There is no `is_success` here on purpose: an `Outcome` carries no
    `success_codes` context, so it cannot give the command's own success verdict
    the way `ProcessResult.is_success` does. Use `exited_zero` for the literal
    "exit code 0" test, or compare `code` against your accepted set.
    """

    @property
    def code(self) -> int | None: ...
    @property
    def signal(self) -> int | None: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def exited_zero(self) -> bool: ...
    def __repr__(self) -> str: ...

@final
class Finished:
    """A process's outcome plus captured stderr (stdout was streamed).

    Like `Outcome`, it exposes `exited_zero` (literal "exit code 0"), not an
    `is_success` that would falsely imply `success_codes` were considered.
    """

    @property
    def outcome(self) -> Outcome: ...
    @property
    def stderr(self) -> str: ...
    @property
    def code(self) -> int | None: ...
    @property
    def exited_zero(self) -> bool: ...
    def __repr__(self) -> str: ...

@final
class OutputEvent:
    """One captured line and the stream it came from."""

    @property
    def stream(self) -> Literal["stdout", "stderr"]: ...
    @property
    def is_stderr(self) -> bool: ...
    @property
    def text(self) -> str: ...
    def __repr__(self) -> str: ...

@final
class StdoutLines:
    """Async iterator over a process's stdout, line by line."""

    def __aiter__(self) -> AsyncIterator[str]: ...
    async def __anext__(self) -> str: ...

@final
class OutputEvents:
    """Async iterator over stdout + stderr as interleaved `OutputEvent`s."""

    def __aiter__(self) -> AsyncIterator[OutputEvent]: ...
    async def __anext__(self) -> OutputEvent: ...

@final
class ProcessStdin:
    """A writable handle to a running process's stdin (all methods awaitable)."""

    async def write(self, data: ReadableBuffer) -> None: ...
    async def write_line(self, line: str) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...

@final
class RunningProcess:
    """A handle to a started process: stream output, write stdin, wait for exit.

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
    ``start()`` or ``astart()``."""

    @property
    def pid(self) -> int | None: ...
    @property
    def elapsed_seconds(self) -> float | None: ...
    @property
    def cpu_time_seconds(self) -> float | None: ...
    @property
    def peak_memory_bytes(self) -> int | None: ...
    @property
    def stdout_line_count(self) -> int | None: ...
    @property
    def stderr_line_count(self) -> int | None: ...
    @property
    def owns_group(self) -> bool | None: ...
    def __enter__(self) -> RunningProcess: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None = ...,
        exc_value: BaseException | None = ...,
        traceback: TracebackType | None = ...,
    ) -> Literal[False]: ...
    async def __aenter__(self) -> RunningProcess: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = ...,
        exc_value: BaseException | None = ...,
        traceback: TracebackType | None = ...,
    ) -> Literal[False]: ...
    def stdout_lines(self) -> StdoutLines: ...
    def output_events(self) -> OutputEvents: ...
    def take_stdin(self) -> ProcessStdin:
        """The writable stdin handle. Raises `ProcessError` if stdin was not kept
        open (build the `Command` with ``keep_stdin_open()``) or was already
        taken — so a missing setup fails here, not with a later `AttributeError`."""

    def kill(self) -> None:
        """Begin tearing the tree down without waiting (like
        ``subprocess.Popen.kill()``: fire-and-forget)."""

    def outcome(self) -> Outcome: ...
    async def aoutcome(self) -> Outcome: ...
    def finish(self) -> Finished: ...
    async def afinish(self) -> Finished: ...
    def output(self) -> ProcessResult: ...
    async def aoutput(self) -> ProcessResult: ...
    def output_bytes(self) -> BytesResult: ...
    async def aoutput_bytes(self) -> BytesResult: ...
    def profile(self, every_seconds: float) -> RunProfile: ...
    async def aprofile(self, every_seconds: float) -> RunProfile: ...
    def shutdown(self, grace_seconds: float) -> Outcome:
        """Graceful teardown (signal -> wait ``grace_seconds`` -> hard kill),
        returning the `Outcome`; consumes the handle. Only for a standalone
        ``start()``/``astart()`` handle — a handle from ``ProcessGroup.start()``
        raises `Unsupported`; tear such a child down via the group (or `kill()`).
        Named to match ``ProcessGroup.shutdown()``/``ashutdown()``."""

    async def ashutdown(self, grace_seconds: float) -> Outcome:
        """Async counterpart of `shutdown`."""

    def __repr__(self) -> str: ...

@final
class ProcessGroupStats:
    """A snapshot of a `ProcessGroup`'s resource usage."""

    @property
    def active_process_count(self) -> int: ...
    @property
    def peak_memory_bytes(self) -> int | None: ...
    @property
    def total_cpu_time_seconds(self) -> float | None: ...
    def __repr__(self) -> str: ...

class _RunnerVerbs:
    """Private, stub-only base: the run-verb surface every runner shares
    (`ProcessGroup`, `Runner`, `ScriptedRunner`, `RecordReplayRunner`,
    `RecordingRunner`) — de-duplicating what would otherwise be five
    identical copies of the same 12 method declarations. Not a real runtime
    base class (there is no such Python object at runtime — each concrete
    class implements this surface independently in Rust); purely a
    typing-time convenience, safe alongside `mypy.stubtest
    --ignore-disjoint-bases` (which this project's gate already passes)."""

    def output(self, command: Command) -> ProcessResult: ...
    def output_bytes(self, command: Command) -> BytesResult: ...
    def run(self, command: Command) -> str: ...
    def exit_code(self, command: Command) -> int: ...
    def probe(self, command: Command) -> bool: ...
    def start(self, command: Command) -> RunningProcess: ...
    async def aoutput(self, command: Command) -> ProcessResult: ...
    async def aoutput_bytes(self, command: Command) -> BytesResult: ...
    async def arun(self, command: Command) -> str: ...
    async def aexit_code(self, command: Command) -> int: ...
    async def aprobe(self, command: Command) -> bool: ...
    async def astart(self, command: Command) -> RunningProcess: ...

@final
class ProcessGroup(_RunnerVerbs):
    """A kill-on-drop container for a process tree; use as a (async) context
    manager. Also a `ProcessRunner` in its own right (see `_RunnerVerbs`):
    its run verbs run `command` as a *shared* member of this group (not a
    standalone tree) — the same verb surface `Runner`/`ScriptedRunner`/…
    expose (not an `extract_runner` target, though — see `runner.rs`)."""

    def __init__(
        self,
        *,
        max_memory: int | None = ...,
        max_processes: int | None = ...,
        cpu_quota: float | None = ...,
        shutdown_grace: float | None = ...,
        escalate_to_kill: bool | None = ...,
    ) -> None:
        """Resource limits need a Windows Job Object or a Linux cgroup-v2 root:
        ``max_memory`` is **bytes** (whole tree), ``max_processes`` a count, and
        ``cpu_quota`` a fraction of a **single** core (``0.5`` = half a core,
        ``2.0`` = two cores) — not a share of all cores. ``shutdown_grace`` is the
        seconds to wait after signalling before escalating to a hard kill;
        ``escalate_to_kill`` (default on) is whether that hard kill follows once
        the grace elapses — set ``False`` to leave any survivors instead of
        force-killing them."""

    def __enter__(self) -> ProcessGroup: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None = ...,
        exc_value: BaseException | None = ...,
        traceback: TracebackType | None = ...,
    ) -> Literal[False]: ...
    async def __aenter__(self) -> ProcessGroup: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = ...,
        exc_value: BaseException | None = ...,
        traceback: TracebackType | None = ...,
    ) -> Literal[False]: ...
    # "unknown" is a forward-compat fallback the pinned crate version does not emit.
    @property
    def mechanism(self) -> Literal["job_object", "cgroup_v2", "process_group", "unknown"]: ...
    def members(self) -> list[int]: ...
    def signal(self, name: SignalName | int) -> None: ...
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def kill_all(self) -> None: ...
    def stats(self) -> ProcessGroupStats: ...
    def shutdown(self) -> None: ...
    async def ashutdown(self) -> None: ...
    def __repr__(self) -> str: ...

@final
class SupervisionOutcome:
    """The result of a `Supervisor.run()`."""

    @property
    def final_result(self) -> ProcessResult: ...
    @property
    def restarts(self) -> int: ...
    # Why the run ended. "unknown" is a forward-compat fallback the pinned crate
    # version does not emit. (Inline like the other read-only Literals —
    # `OutputEvent.stream`, `ProcessGroup.mechanism` — rather than a named export.)
    @property
    def stopped(
        self,
    ) -> Literal["policy_satisfied", "predicate", "restarts_exhausted", "unknown"]: ...
    @property
    def storm_pauses(self) -> int: ...
    def __repr__(self) -> str: ...

@final
class Supervisor:
    """Keep a command alive: restart per policy with backoff until a stop condition."""

    def __init__(
        self,
        command: Command,
        *,
        restart: Literal["always", "on_crash", "never"] | None = ...,
        max_restarts: int | None = ...,
        backoff_initial: float | None = ...,
        backoff_factor: float | None = ...,
        max_backoff: float | None = ...,
        jitter: bool | None = ...,
        stop_when: Callable[[ProcessResult], bool] | None = ...,
        storm_pause: float | None = ...,
        failure_threshold: float | None = ...,
        failure_decay: float | None = ...,
        # Bound (or widen) the output captured from each incarnation — opt-in;
        # the default is already a sensible bounded tail. Setting any of these
        # three requires at least one of the two cap sizes (mirrors
        # `Command.output_limit`'s own validation), applied here as
        # `Supervisor.__new__` constructor kwargs instead of a builder method.
        capture_max_bytes: int | None = ...,
        capture_max_lines: int | None = ...,
        capture_on_overflow: Literal["drop_oldest", "drop_newest", "error"] | None = ...,
        # Drives every incarnation through this runner instead of the real
        # `Runner` — a `ScriptedRunner`/`RecordingRunner`/`RecordReplayRunner`
        # for hermetic supervision tests. (Inline union, not a named alias:
        # only three call sites in the whole surface use this shape.) Not a
        # `ProcessGroup` — deliberately not an `extract_runner` target; see
        # `runner.rs::extract_runner`'s doc comment.
        runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
    ) -> None: ...
    def run(self) -> SupervisionOutcome: ...
    async def arun(self) -> SupervisionOutcome: ...

@final
class Reply:
    """A canned reply for a `ScriptedRunner` rule."""

    @staticmethod
    def ok(stdout: str) -> Reply: ...
    @staticmethod
    def fail(code: int, stderr: str) -> Reply: ...
    @staticmethod
    def timeout() -> Reply: ...
    @staticmethod
    def signalled(signal: int | None = ...) -> Reply: ...
    @staticmethod
    def pending() -> Reply: ...
    @staticmethod
    def lines(lines: Sequence[str]) -> Reply: ...
    def with_stdout(self, stdout: str) -> Reply: ...
    def with_line_delay(self, seconds: float) -> Reply: ...
    def __repr__(self) -> str: ...

@final
class Runner(_RunnerVerbs):
    """The real process runner — inject it for testable code."""

    def __init__(self) -> None: ...
    def __repr__(self) -> str: ...

@final
class ScriptedRunner(_RunnerVerbs):
    """A scripted test double for `Runner`."""

    def __init__(self) -> None: ...
    def on(self, prefix: Args, reply: Reply) -> None: ...
    # Reply with each of `replies` in turn on successive matching calls; the
    # last one repeats once exhausted. Raises `ValueError` for an empty
    # `replies` sequence.
    def on_sequence(self, prefix: Args, replies: Sequence[Reply]) -> None: ...
    # `predicate` is infallible from the crate's perspective: a raising or
    # non-bool predicate reads as "does not match" (see `runner.rs`).
    def when(self, predicate: Callable[[Command], bool], reply: Reply) -> None: ...
    def fallback(self, reply: Reply) -> None: ...
    def __repr__(self) -> str: ...

@final
class RecordReplayRunner(_RunnerVerbs):
    """Records real runs to a cassette file (`record`) and replays them without
    spawning (`replay`); shares the `Runner` run-verb surface."""

    @staticmethod
    def record(path: StrPath) -> RecordReplayRunner: ...
    @staticmethod
    def replay(path: StrPath) -> RecordReplayRunner: ...
    def save(self) -> None: ...
    def __repr__(self) -> str: ...

@final
class RecordingRunner(_RunnerVerbs):
    """A recording test double: replies to every command with a canned `Reply`
    and records each call, so a test can assert on what its code ran. Shares the
    `Runner` run-verb surface; inspect calls with `calls()` / `only_call()`."""

    @staticmethod
    def replying(reply: Reply) -> RecordingRunner: ...
    # Wrap `inner` — any of `Runner`, `ScriptedRunner`, `RecordReplayRunner`,
    # or another `RecordingRunner` — recording every call made through it.
    @staticmethod
    def new(
        inner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner,
    ) -> RecordingRunner: ...
    def calls(self) -> list[Invocation]: ...
    def only_call(self) -> Invocation: ...
    def __repr__(self) -> str: ...

@final
class Invocation:
    """One call captured by a `RecordingRunner`: the program, args, cwd, env
    overrides, and whether stdin was supplied. Values are inspectable for
    assertions; the `repr` stays redacted (program, arg count, cwd, env names,
    has_stdin — never argv or env values)."""

    @property
    def program(self) -> str: ...
    @property
    def args(self) -> list[str]: ...
    @property
    def cwd(self) -> str | None: ...
    @property
    def env(self) -> dict[str, str | None]: ...
    def env_is(self, name: str, value: str) -> bool: ...
    def has_env(self, name: str) -> bool: ...
    @property
    def has_stdin(self) -> bool: ...
    def has_flag(self, flag: str) -> bool: ...
    def __repr__(self) -> str: ...

@final
class RunProfile:
    """A resource-usage profile sampled across a run (`RunningProcess.profile`),
    plus the run's `outcome` — `profile()` is a superset of `wait()`."""

    @property
    def code(self) -> int | None: ...
    @property
    def signal(self) -> int | None: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def outcome(self) -> Outcome: ...
    @property
    def duration_seconds(self) -> float: ...
    @property
    def cpu_time_seconds(self) -> float | None: ...
    @property
    def peak_memory_bytes(self) -> int | None: ...
    @property
    def samples(self) -> int: ...
    @property
    def avg_cpu_cores(self) -> float | None: ...
    def __repr__(self) -> str: ...

@final
class CliClient:
    """A program bound to default timeout/env/retry, run with the real
    `Runner` by default or an injected `runner=` (a `ScriptedRunner` and
    friends, for testable code with no real spawns). The verbs take just the
    per-call arguments."""

    def __init__(
        self,
        program: StrPath,
        *,
        default_timeout: float | None = ...,
        default_env: Mapping[str, str] | None = ...,
        default_env_remove: Sequence[str] | None = ...,
        # A resolver is called fresh each time a command is *built* (not each
        # retry attempt), synchronously, and is expected to be infallible —
        # a raising/non-str-returning callback is surfaced via the
        # unraisable hook and falls back to an empty string.
        default_env_fn: Mapping[str, Callable[[], str]] | None = ...,
        # `default_retry_if` is the opt-in gate for the client-wide retry
        # policy (mirrors `Command.retry()`'s required `retry_if`) — the
        # tuning knobs below only apply when it's set; passing one of them
        # without it raises `ValueError`.
        default_retry_if: RetryIf | None = ...,
        default_max_retries: int | None = ...,
        default_initial_backoff: float | None = ...,
        default_multiplier: float | None = ...,
        default_max_backoff: float | None = ...,
        default_jitter: bool | None = ...,
        # Gap-fill (not override): each built command gets `cancel_on(token)`
        # unless it already has its own explicit token.
        default_cancel_on: CancellationToken | None = ...,
        # Drives every verb through this runner instead of the real `Runner` —
        # a `ScriptedRunner`/`RecordingRunner`/`RecordReplayRunner` for testable
        # client code with no real spawns.
        runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
    ) -> None: ...
    def command(self, args: Args) -> Command:
        """A `Command` for `program <args>`, the client's defaults pre-applied
        — chain more builders, then pass it to a verb below instead of a plain
        arg list. An explicit setting on it always wins over the default."""

    def run(self, call: Args | Command) -> str: ...
    def output(self, call: Args | Command) -> ProcessResult: ...
    def output_bytes(self, call: Args | Command) -> BytesResult: ...
    def exit_code(self, call: Args | Command) -> int: ...
    def probe(self, call: Args | Command) -> bool: ...
    async def arun(self, call: Args | Command) -> str: ...
    async def aoutput(self, call: Args | Command) -> ProcessResult: ...
    async def aoutput_bytes(self, call: Args | Command) -> BytesResult: ...
    async def aexit_code(self, call: Args | Command) -> int: ...
    async def aprobe(self, call: Args | Command) -> bool: ...
    def __repr__(self) -> str: ...

class ProcessError(Exception):
    """Base class for every error raised by this package."""

class NonZeroExit(ProcessError):
    """`run()` / `exit_code()` got a non-zero exit."""

    program: str
    code: int
    stdout: str
    stderr: str
    # The best human-facing message: captured stderr if it carries text,
    # otherwise captured stdout; `None` if both streams are blank.
    diagnostic: str | None

class Timeout(ProcessError, TimeoutError):
    """A run exceeded its configured timeout.

    Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
    and since `TimeoutError` is itself an `OSError` subclass (as of Python
    3.3), `except OSError` catches it as well (the same is true of
    `ProcessNotFound`/`FileNotFoundError` and
    `PermissionDenied`/`PermissionError` below — all three dual-base
    exceptions are transitively `OSError`).
    """

    program: str
    # `None` when the deadline wasn't known to the checking verb (a
    # scripted/cassette-replayed timeout with no `timeout()` configured).
    timeout_seconds: float | None
    stdout: str
    stderr: str
    # See `NonZeroExit.diagnostic` — the partial output of a hung-then-killed run.
    diagnostic: str | None

class Signalled(ProcessError):
    """A run was killed by a signal."""

    program: str
    signal: int | None
    stdout: str
    stderr: str
    # See `NonZeroExit.diagnostic` — the output captured before the signal-kill.
    diagnostic: str | None

class ProcessNotFound(ProcessError, FileNotFoundError):
    """The program could not be found / spawned.

    Also a builtin `FileNotFoundError` (what `subprocess` raises), so
    `except FileNotFoundError` catches it too.
    """

    program: str

class PermissionDenied(ProcessError, PermissionError):
    """The program could not be spawned because of insufficient permissions
    (e.g. a non-executable file), or a permission-denied OS error surfaced
    from elsewhere in the run (e.g. a group signal the OS refused).

    Also a builtin `PermissionError`, so `except PermissionError` catches it too.
    """

    # `None` for the broader "refused OS operation" case (no program is being
    # named there) — `str` for a genuine spawn-time permission denial. Unlike
    # every other program-naming exception in this module, this one is not
    # guaranteed to carry a program, since `is_permission_denied()` covers both
    # a program-naming `Spawn` failure and a program-less `Io` failure.
    program: str | None

class ResourceLimit(ProcessError):
    """A resource limit (memory / processes / CPU) was invalid or could not be
    enforced by the active containment mechanism. The reason is the exception
    message (``str(exc)``); it carries no extra structured field."""

class Unsupported(ProcessError):
    """The operation is not supported on this platform."""

    operation: str

class OutputTooLarge(ProcessError):
    """Captured output hit an `output_limit(..., on_overflow="error")` ceiling."""

    program: str
    max_lines: int | None
    max_bytes: int | None
    total_lines: int
    total_bytes: int

class Cancelled(ProcessError):
    """The run was deliberately cancelled via a `CancellationToken` wired
    with `Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
    `Pipeline.cancel_on()`. Terminal — never retried by `Command.retry()` or
    restarted by `Supervisor` (the token stays cancelled forever, so another
    attempt could only fail the same way)."""

    program: str

# Batch execution: run many commands with bounded concurrency, in input order.
# A command that failed (a spawn or I/O error) appears as a `ProcessError` in its
# result slot (a non-zero exit is data on the `ProcessResult`). `runner=` drives
# every command through the given runner instead of the real `Runner` — a
# `ScriptedRunner`/`RecordingRunner`/`RecordReplayRunner` for a hermetic batch
# test with no real spawns.
def output_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
) -> list[ProcessResult | ProcessError]: ...
async def aoutput_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
) -> list[ProcessResult | ProcessError]: ...
def output_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
) -> list[BytesResult | ProcessError]: ...
async def aoutput_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | None = ...,
) -> list[BytesResult | ProcessError]: ...

# Opt-in observability: install a process-global subscriber that forwards the
# core's per-run `tracing` events to Python `logging` (a `processkit` logger).
# Idempotent; returns False if another library already owns the global subscriber.
def enable_logging() -> bool: ...
