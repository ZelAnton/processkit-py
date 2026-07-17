"""Type stubs for the compiled `_processkit` extension module.

mypy cannot see into the PyO3 cdylib, so the public surface is declared here.
Keep this in sync with `src/lib.rs`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from types import TracebackType
from typing import Literal, final

# `StrPath` (program/path arg: `str` or `os.PathLike[str]`), `Args` (an argv-like
# list/tuple of them — deliberately not `Sequence[StrPath]`, see `_types.py`),
# `SignalName`, `RetryIf`, `LineTerminatorName`, `Priority`, `ReadableBuffer`,
# and `RunnerLike` are the single source in `_types`, re-exported from the
# package so callers can annotate with them; imported here for the signatures
# below. `RunnerLike` in particular must live in `_types.py` rather than be
# defined directly in this stub: a name that exists only in a compiled
# extension's `.pyi` (with no backing Python source) is never present at
# runtime, which `mypy.stubtest` flags as an error.
from ._types import (
    Args,
    LineTerminatorName,
    Priority,
    ReadableBuffer,
    RetryIf,
    RunnerLike,
    SignalName,
    StrPath,
    SupportsWrite,
)

@final
class ProcessResult:
    """The captured result of a finished run. A non-zero exit, a timeout, and a
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
    `result.stdout`/`.stderr`/`.code` yourself, to cross a process boundary."""

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
    @property
    def diagnostic(self) -> str | None:
        """The best human-facing message: stderr if it carries text, otherwise
        stdout, otherwise ``None`` if both are blank — the same preference
        order as ``NonZeroExit``/``Timeout``/``Signalled.diagnostic``."""

    @property
    def outcome(self) -> Outcome:
        """The full run outcome (``code`` / ``signal`` / ``timed_out``), the
        same value ``RunProfile.outcome`` and the checking-verb exceptions
        expose."""

    def ensure_success(self) -> ProcessResult:
        """Raise the same exception a checking verb would if this result's
        exit isn't in ``success_codes``; returns ``self`` unchanged otherwise,
        so it composes: ``cmd.output().ensure_success().stdout``."""

    def __repr__(self) -> str: ...
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...

@final
class BytesResult:
    """The captured result of a run with raw-bytes stdout (`Command.output_bytes()`);
    stderr stays decoded text. A non-zero exit, a timeout, and a signal-kill are
    all data here, never raised.

    Value semantics: `==`/`hash()` compare every field, same as `ProcessResult`.
    **Not** picklable — raw stdout may not be valid UTF-8 and processkit has no
    way to reconstruct one from arbitrary bytes outside a real run; pickling
    raises `TypeError`. Pickle a `ProcessResult` (`Command.output()`) instead,
    or persist the fields you need yourself."""

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
        """Whether captured output was truncated by an ``output_limit(...)`` cap
        — the line-captured stderr under any cap, and (since processkit 2.1.0)
        the raw stdout too when an ``output_limit(max_bytes=...)`` byte ceiling
        bounds it to a head/tail. A ``max_lines`` cap never truncates raw stdout
        (bytes have no line count); only a ``max_bytes`` cap does."""

    @property
    def diagnostic(self) -> str | None:
        """See ``ProcessResult.diagnostic``. Raw stdout is lossily decoded to
        text for this message when stderr is blank."""

    @property
    def outcome(self) -> Outcome:
        """See ``ProcessResult.outcome``."""

    def ensure_success(self) -> BytesResult:
        """See ``ProcessResult.ensure_success()``."""

    def __repr__(self) -> str: ...
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...

@final
class Command:
    """A command builder. Builder methods return a new `Command`.

    Its `a`-verbs return custom awaitables, rather than coroutine objects:
    await them directly, or pass one to ``asyncio.ensure_future(...)`` when a
    Task/Future is required.
    """

    def __init__(self, program: StrPath, args: Args | None = ...) -> None: ...
    def arg(self, arg: StrPath) -> Command: ...
    def args(self, args: Args) -> Command: ...
    def cwd(self, path: StrPath) -> Command: ...
    def prefer_local(self, dir: StrPath) -> Command:
        """Search this directory before ``PATH`` when resolving a bare-name
        program. Repeated calls accumulate in priority order, path-form
        programs are unchanged, and the child's own ``PATH`` is not rewritten."""

    def env(self, key: str, value: str) -> Command: ...
    def envs(self, vars: Mapping[str, str]) -> Command: ...
    def env_remove(self, key: str) -> Command: ...
    def env_clear(self) -> Command: ...
    def inherit_env(self, names: Sequence[str]) -> Command: ...
    def stdin_bytes(self, data: ReadableBuffer) -> Command: ...
    def stdin_text(self, text: str) -> Command: ...
    def stdin_file(self, path: StrPath) -> Command: ...
    def keep_stdin_open(self) -> Command: ...
    def timeout(self, seconds: float) -> Command: ...
    def timeout_grace(self, seconds: float) -> Command: ...
    def timeout_signal(self, name: SignalName | int) -> Command:
        """The signal sent first on a graceful timeout (default ``"term"``): a
        name (``term``/``kill``/``int``/``hup``/``quit``/``usr1``/``usr2``) or a
        raw platform signal number (Unix only). A raw number is validated as a
        real, deliverable signal — on Unix ``1..=SIGRTMAX`` (``0``, the existence
        probe that delivers nothing, negatives, and out-of-range raise
        ``ValueError``); on Windows a raw number raises ``Unsupported`` (only
        ``"kill"`` is deliverable there). A ``bool`` raises ``TypeError`` — it is
        an ``int`` subtype that would otherwise silently become raw signal
        ``1``/``0``."""
    def no_timeout(self) -> Command: ...
    def timeout_opt(self, seconds: float | None) -> Command: ...
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
    def retry_never(self) -> Command: ...
    def stdout(self, mode: Literal["pipe", "inherit", "null"]) -> Command: ...
    def stderr(self, mode: Literal["pipe", "inherit", "null"]) -> Command: ...
    def encoding(self, label: str) -> Command: ...
    def stdout_encoding(self, label: str) -> Command: ...
    def stderr_encoding(self, label: str) -> Command: ...
    def line_terminator(self, mode: LineTerminatorName) -> Command:
        """Choose where the line pump splits **both** streams into lines.
        ``"newline"`` (the default) splits on ``\\n`` only; ``"carriage_return"``
        also splits on a bare ``\\r`` (one not immediately followed by ``\\n``),
        delivered live — for ``curl``/``pip``/``apt``-style ``\\r``-redrawn
        progress output that would otherwise pile up into a single line until
        EOF. A ``\\r\\n`` pair still counts as one terminator. Shared by
        ``stdout_lines()``/``output_events()``, the per-line handlers
        (``on_stdout_line``/``on_stderr_line``), ``stdout_tee``/``stderr_tee``,
        and ``output_string`` alike; set both streams here or independently
        with ``stdout_line_terminator``/``stderr_line_terminator``. Unknown
        preset raises ``ValueError``."""

    def stdout_line_terminator(self, mode: LineTerminatorName) -> Command:
        """Choose where the line pump splits **stdout** into lines (see
        ``line_terminator``); stderr framing is left untouched."""

    def stderr_line_terminator(self, mode: LineTerminatorName) -> Command:
        """Choose where the line pump splits **stderr** into lines (see
        ``line_terminator``); stdout framing is left untouched. Handy when
        progress output lands on stderr while stdout stays newline-structured."""

    def stdout_tee(self, sink: StrPath | SupportsWrite, *, append: bool = ...) -> Command:
        """Tee every decoded stdout line (line + ``\\n``) to ``sink`` as it is
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
        - *Writer:* each decoded line (then ``"\\n"``) is passed to ``write()``
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
        and under ``output_bytes()`` (raw capture)."""

    def stderr_tee(self, sink: StrPath | SupportsWrite, *, append: bool = ...) -> Command:
        """Tee every decoded stderr line to ``sink``. Same contract as
        ``stdout_tee`` — a file path (opened at build time, truncate by default
        or ``append``) or a Python writer object with a callable ``write()`` (fed
        each decoded line as a ``str`` via the same blocking-pool async-write
        bridge, never closed for you), coexisting with capture, inert unless
        stderr is piped through the line pump."""

    def on_stdout_line(self, callback: Callable[[str], None]) -> Command:
        """Call ``callback`` with every decoded stdout line as it is produced —
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
        the line pump)."""

    def on_stderr_line(self, callback: Callable[[str], None]) -> Command:
        """Call ``callback`` with every decoded stderr line as it is produced.
        Same contract as ``on_stdout_line`` — full capture unaffected, fires on
        sync/async/streamed paths alike, infallible (a raising callback goes to
        ``sys.unraisablehook``, never propagates), at most one handler per
        stream.

        Inert under ``stderr("inherit")``/``stderr("null")``. Unlike
        ``on_stdout_line``, **not** silenced by ``output_bytes()``: that verb
        only bypasses the *stdout* line pump for its raw-bytes capture —
        stderr still decodes through the line pump exactly as under
        ``output()``, so this callback still fires."""

    def kill_on_parent_death(self) -> Command: ...
    def create_no_window(self) -> Command: ...
    def uid(self, uid: int) -> Command: ...
    def gid(self, gid: int) -> Command: ...
    def groups(self, gids: Sequence[int]) -> Command: ...
    def setsid(self) -> Command: ...
    def umask(self, mask: int) -> Command: ...
    def priority(self, level: Priority) -> Command: ...
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
    def resolve_program(self) -> str:
        """Resolve this command's ``program`` to a concrete executable path
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
        runtime."""

    def aoutput(self) -> Awaitable[ProcessResult]: ...
    def aoutput_bytes(self) -> Awaitable[BytesResult]: ...
    def arun(self) -> Awaitable[str]: ...
    def aexit_code(self) -> Awaitable[int]: ...
    def aprobe(self) -> Awaitable[bool]: ...
    def start(self) -> RunningProcess: ...
    def astart(self) -> Awaitable[RunningProcess]: ...
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
    def aoutput(self) -> Awaitable[ProcessResult]: ...
    def aoutput_bytes(self) -> Awaitable[BytesResult]: ...
    def arun(self) -> Awaitable[str]: ...
    def aexit_code(self) -> Awaitable[int]: ...
    def aprobe(self) -> Awaitable[bool]: ...
    def __repr__(self) -> str: ...

@final
class CancellationToken:
    """A cancel switch: fire it to tear down every run wired to it via
    `Command.cancel_on()` / `CliClient`'s `default_cancel_on=` /
    `Pipeline.cancel_on()` — surfacing `Cancelled`. Cheap to clone/share:
    every clone refers to the same underlying state, so cancelling any clone
    cancels every run wired to it. A cancelled token stays cancelled forever.

    `child_token()` derives a separate, scoped token: it is cancelled
    automatically when this one is, but cancelling it back does NOT
    propagate to this token or to its other children — cancellation only
    flows parent-to-child, never child-to-parent or between siblings."""

    def __init__(self) -> None: ...
    def cancel(self) -> None: ...
    def is_cancelled(self) -> bool: ...
    def child_token(self) -> CancellationToken:
        """A new token that is cancelled automatically when this one is, but
        can also be cancelled independently — cancelling the child does not
        affect this token or its other children."""
    def __repr__(self) -> str: ...

@final
class Outcome:
    """How a process ended.

    There is no `is_success` here on purpose: an `Outcome` carries no
    `success_codes` context, so it cannot give the command's own success verdict
    the way `ProcessResult.is_success` does. Use `exited_zero` for the literal
    "exit code 0" test, or compare `code` against your accepted set.

    Value semantics: `==`/`hash()` compare `code`/`signal`/`timed_out`
    (equivalently, which variant this is and its payload); picklable.
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
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...
    # `__reduce__`'s factory (see the class docstring on pickling); private,
    # not for direct use — declared only so stubtest sees the real member.
    @staticmethod
    def _unpickle(code: int | None, signal: int | None, timed_out: bool) -> Outcome: ...

@final
class Finished:
    """A process's outcome plus captured stderr (stdout was streamed).

    Mirrors `Outcome`'s `code`, `exited_zero`, `timed_out`, and `signal`
    directly (in addition to the nested `outcome`), so callers don't need to
    reach through `.outcome` for fields they already use on `Outcome`. Like
    `Outcome`, it exposes `exited_zero` (literal "exit code 0"), not an
    `is_success` that would falsely imply `success_codes` were considered.

    Value semantics: `==`/`hash()` compare `outcome`/`stderr`; picklable.
    """

    @property
    def outcome(self) -> Outcome: ...
    @property
    def stderr(self) -> str: ...
    @property
    def code(self) -> int | None: ...
    @property
    def exited_zero(self) -> bool: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def signal(self) -> int | None: ...
    def __repr__(self) -> str: ...
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...
    # `__reduce__`'s factory (see the class docstring on pickling); private,
    # not for direct use — declared only so stubtest sees the real member.
    @staticmethod
    def _unpickle(
        stderr: str, code: int | None, signal: int | None, timed_out: bool
    ) -> Finished: ...

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
    async def send_control(self, control: str) -> None:
        """Write one mapped control byte, e.g. ``"c"`` -> Ctrl-C (``\\x03``).

        This writes a byte to the child's stdin pipe, not a terminal signal;
        real SIGINT/SIGTSTP delivery requires a pseudoterminal.
        """

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
    def aoutcome(self) -> Awaitable[Outcome]: ...
    def finish(self) -> Finished: ...
    def afinish(self) -> Awaitable[Finished]: ...
    def output(self) -> ProcessResult: ...
    def aoutput(self) -> Awaitable[ProcessResult]: ...
    def output_bytes(self) -> BytesResult: ...
    def aoutput_bytes(self) -> Awaitable[BytesResult]: ...
    def profile(self, every_seconds: float) -> RunProfile: ...
    def aprofile(self, every_seconds: float) -> Awaitable[RunProfile]: ...
    def shutdown(self, grace_seconds: float) -> Outcome:
        """Graceful teardown (signal -> wait ``grace_seconds`` -> hard kill),
        returning the `Outcome`; consumes the handle. Only for a standalone
        ``start()``/``astart()`` handle — a handle from ``ProcessGroup.start()``
        raises `Unsupported`; tear such a child down via the group (or `kill()`).
        Named to match ``ProcessGroup.shutdown()``/``ashutdown()``."""

    def ashutdown(self, grace_seconds: float) -> Awaitable[Outcome]:
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
    `RecordingRunner`, `DryRunRunner`) — de-duplicating what would otherwise be
    six identical copies of the same 12 method declarations. Its `a`-verbs
    return awaitables, not coroutines; use ``asyncio.ensure_future(...)`` to
    schedule one as a Task. Not a real runtime
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
    def aoutput(self, command: Command) -> Awaitable[ProcessResult]: ...
    def aoutput_bytes(self, command: Command) -> Awaitable[BytesResult]: ...
    def arun(self, command: Command) -> Awaitable[str]: ...
    def aexit_code(self, command: Command) -> Awaitable[int]: ...
    def aprobe(self, command: Command) -> Awaitable[bool]: ...
    def astart(self, command: Command) -> Awaitable[RunningProcess]: ...

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
    def signal(self, name: SignalName | int) -> None:
        """Send a signal to every process in the tree: a name
        (``term``/``kill``/``int``/``hup``/``quit``/``usr1``/``usr2``) or a raw
        platform signal number (Unix only). On Windows a Job Object has no POSIX
        signals, so only ``"kill"`` is deliverable and any other name/number
        raises ``Unsupported``. A raw number is validated as a real, deliverable
        signal (``1..=SIGRTMAX`` on Unix); ``0`` (the existence probe), negatives,
        and out-of-range values raise ``ValueError`` instead of a silent no-op,
        and a ``bool`` raises ``TypeError``."""
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def kill_all(self) -> None: ...
    def stats(self) -> ProcessGroupStats: ...
    def shutdown(self) -> None: ...
    def ashutdown(self) -> Awaitable[None]: ...
    def __repr__(self) -> str: ...

@final
class SupervisionOutcome:
    """The result of a `Supervisor.run()`.

    Value semantics: `==`/`hash()` compare every field (`final_result` via
    `ProcessResult`'s own comparison, plus `restarts`/`stopped`/`storm_pauses`).
    **Not** picklable: its identity includes `final_result` (a `ProcessResult`),
    which cannot be faithfully reconstructed from a pickle (its `timeout`/
    `success_codes` have no accessor to read back), so pickling raises
    `TypeError`. Read the fields you need, or pickle `final_result.outcome` (an
    `Outcome`, which round-trips exactly), to cross a process boundary."""

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
    ) -> Literal["policy_satisfied", "predicate", "restarts_exhausted", "gave_up", "unknown"]: ...
    @property
    def storm_pauses(self) -> int: ...
    def __repr__(self) -> str: ...
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...

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
        # A `stop_when` that raises or returns a non-bool aborts supervision with
        # that error — it is NOT swallowed into "do not stop" — so a broken
        # predicate surfaces to the caller (from `run()`/`arun()`) instead of
        # looping to `max_restarts`. No further restart runs after it.
        stop_when: Callable[[ProcessResult], bool] | None = ...,
        # Classify a permanent failure so supervision gives up instead of
        # restarting a crash forever. Consulted only for a crash the policy would
        # otherwise restart, ahead of `max_restarts` and the storm guard. The
        # callback receives one argument mirroring the crate's `GiveUpAttempt`
        # sum type, dispatched with `isinstance`: a `ProcessResult` for a crashed
        # run that produced a result (classify by e.g. `attempt.code`), or a
        # `ProcessError` subclass for a launch that never produced one (classify
        # by e.g. `isinstance(attempt, ProcessNotFound)` for a missing binary).
        # A crash verdict stops with `SupervisionOutcome.stopped == "gave_up"`; a
        # launch-failure verdict has no result to report and surfaces the
        # classified error directly from `run()`/`arun()`. A classifier that
        # raises or returns a non-bool likewise aborts supervision with that error
        # rather than being read as "keep restarting".
        give_up_when: Callable[[ProcessResult | ProcessError], bool] | None = ...,
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
        # `Runner` — any `RunnerLike` for hermetic supervision tests. Not a
        # `ProcessGroup` — deliberately not an `extract_runner` target; see
        # `runner.rs::extract_runner`'s doc comment.
        runner: RunnerLike | None = ...,
    ) -> None: ...
    # Run supervision to completion and return the `SupervisionOutcome`. Consumes
    # the supervisor: `run`/`arun` may be called ONCE — a second call (on any
    # thread, including one re-entered from a `stop_when`/`give_up_when` callback)
    # raises `ProcessError` ("already been run"), never returns the prior outcome
    # and never a raw `RuntimeError`.
    def run(self) -> SupervisionOutcome: ...
    # Async counterpart of `run()`; likewise one-shot — the supervisor is spent
    # once awaited, and a second `run`/`arun` raises `ProcessError`.
    def arun(self) -> Awaitable[SupervisionOutcome]: ...

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
    def with_stderr(self, stderr: str) -> Reply: ...
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
    # A `predicate` that raises or returns a non-bool aborts the run verb with
    # that error — it does NOT fall through to the next rule or the fallback — so
    # a broken match predicate surfaces instead of silently masking a test defect
    # behind a fallback reply (see `runner.rs`). This holds however the runner is
    # driven: its own verbs, an injected runner under a `CliClient` or a
    # `Supervisor`, and every command of a batch (`output_all`/`output_all_bytes`
    # and their async twins) — for a batch, the error surfaces in that command's
    # own result slot. Concurrent verbs against one shared runner never cross
    # predicate errors.
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
    # Wrap `inner` — any `RunnerLike` (including another `RecordingRunner`, or a
    # `DryRunRunner`) — recording every call made through it.
    @staticmethod
    def new(inner: RunnerLike) -> RecordingRunner: ...
    def calls(self) -> list[Invocation]: ...
    def only_call(self) -> Invocation: ...
    def __repr__(self) -> str: ...

@final
class DryRunRunner(_RunnerVerbs):
    """A dry-run test double: never spawns a process. Every verb renders the
    command to its display-quoted line (like `Command.command_line()`) and
    returns a synthetic successful result — the seam behind a tool's own
    `--dry-run`/`--echo` mode. Shares the `Runner` run-verb surface; inspect the
    rendered lines with `commands()` / `only_command()`, or stream them live
    with `on_invocation()`."""

    def __init__(self) -> None: ...
    # Call `callback` with each rendered line as its call is dry-run "executed",
    # in addition to the collected `commands()` snapshot. `callback` is
    # infallible from the crate's perspective: a raising one is surfaced via the
    # unraisable hook (see `runner.rs`), not propagated.
    def on_invocation(self, callback: Callable[[str], None]) -> None: ...
    def commands(self) -> list[str]: ...
    def only_command(self) -> str: ...
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
    plus the run's `outcome` — `profile()` is a superset of `outcome()`.

    Value semantics: `==`/`hash()` compare every field (`outcome`/
    `duration_seconds`/`cpu_time_seconds`/`peak_memory_bytes`/`samples`; all
    exact underneath, though two are exposed here as `float`). **Not**
    picklable — it reports live OS resource-sampling telemetry that processkit
    has no way to reconstruct outside an actual monitored run; pickling raises
    `TypeError`."""

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
    def __eq__(self, value: object, /) -> bool: ...
    def __hash__(self) -> int: ...

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
        # retry attempt), synchronously. It is expected to return a `str`; a
        # resolver that raises or returns a non-`str` is fail-closed — the
        # exception propagates out of the verb (or `command()`) that triggered
        # the build, before the runner is reached, so no process is spawned with
        # a missing/blank credential. (A resolver whose key is already set by an
        # explicit per-command `env()` or a static `default_env` never runs, so
        # it cannot abort a call whose value it does not supply.)
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
        # any `RunnerLike` for testable client code with no real spawns.
        runner: RunnerLike | None = ...,
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
    def resolve_program(self) -> str:
        """Resolve this client's ``program`` to a concrete executable path
        **without spawning it** — the client-level preflight ("is this tool
        installed?"), with no side effects. Applies the client's defaults (so a
        ``default_env``/``default_env_fn`` that relocates ``PATH`` is honored
        as at launch), then resolves via the same PATH/PATHEXT/execute-bit logic
        a real run uses. Returns the resolved **absolute** path; a
        ``default_env_fn`` that raises or returns a non-``str`` aborts it
        fail-closed (like the run verbs), and a miss raises ``ProcessNotFound``
        (also a ``FileNotFoundError``, with a ``searched`` diagnostic). No
        ``a``-prefixed async twin — the probe is synchronous."""

    def arun(self, call: Args | Command) -> Awaitable[str]: ...
    def aoutput(self, call: Args | Command) -> Awaitable[ProcessResult]: ...
    def aoutput_bytes(self, call: Args | Command) -> Awaitable[BytesResult]: ...
    def aexit_code(self, call: Args | Command) -> Awaitable[int]: ...
    def aprobe(self, call: Args | Command) -> Awaitable[bool]: ...
    def __repr__(self) -> str: ...

class ProcessError(Exception):
    """Base class for every error raised by this package."""

class NonZeroExit(ProcessError):
    """`run()` / `exit_code()` got a non-zero exit."""

    program: str
    code: int
    stdout: str
    stderr: str
    # The exact raw stdout bytes when this error came from a checking verb over
    # `output_bytes()` (e.g. `BytesResult.ensure_success()`); `None` on the text
    # path (`run()` / `output()`), where `stdout` above is already the complete
    # decoded text. When present, these are the exact pre-decode bytes `stdout`
    # is a lossy UTF-8 view of (they differ only for non-UTF-8 output).
    stdout_bytes: bytes | None
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
    # See `NonZeroExit.stdout_bytes` — the exact partial raw stdout bytes captured
    # before the kill when the timeout came from a checking verb over
    # `output_bytes()`; `None` on the text path.
    stdout_bytes: bytes | None
    # See `NonZeroExit.diagnostic` — the partial output of a hung-then-killed run.
    diagnostic: str | None

class Signalled(ProcessError):
    """A run was killed by a signal."""

    program: str
    signal: int | None
    stdout: str
    stderr: str
    # See `NonZeroExit.stdout_bytes` — the exact raw stdout bytes captured before
    # the signal-kill when the error came from a checking verb over
    # `output_bytes()`; `None` on the text path.
    stdout_bytes: bytes | None
    # See `NonZeroExit.diagnostic` — the output captured before the signal-kill.
    diagnostic: str | None

class ProcessNotFound(ProcessError, FileNotFoundError):
    """The program could not be found / spawned.

    Also a builtin `FileNotFoundError` (what `subprocess` raises), so
    `except FileNotFoundError` catches it too.
    """

    program: str
    # The searched directories joined by the platform path separator, or `None`
    # when no PATH-like search was used.
    searched: str | None

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

# Program resolution: resolve a program to its concrete executable path *without*
# launching it — a spawn-free, side-effect-free preflight ("is this tool
# installed?"). Reuses the same PATH/PATHEXT/execute-bit lookup a real run
# performs, so a hit is exactly what a spawn would find and a miss is exactly the
# `ProcessNotFound` (also a `FileNotFoundError`, with a `searched` diagnostic) a
# run would raise. This module function searches only the process `PATH`; for a
# `prefer_local` directory or a relocated child `PATH`, use `Command.resolve_program`
# / `CliClient.resolve_program`. Synchronous — no async runtime is required.
def which(program: StrPath) -> str: ...

# Batch execution: run many commands with bounded concurrency, in input order.
# A command that failed (a spawn or I/O error) appears as a `ProcessError` in its
# result slot (a non-zero exit is data on the `ProcessResult`). `runner=` drives
# every command through the given runner (any `RunnerLike`) instead of the real
# `Runner`, for a hermetic batch test with no real spawns.
def output_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[ProcessResult | ProcessError]: ...
def aoutput_all(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> Awaitable[list[ProcessResult | ProcessError]]: ...
def output_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> list[BytesResult | ProcessError]: ...
def aoutput_all_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = ...,
    runner: RunnerLike | None = ...,
) -> Awaitable[list[BytesResult | ProcessError]]: ...

# Opt-in observability: install a process-global subscriber that forwards the
# core's per-run `tracing` events to Python `logging` (a `processkit` logger).
# Idempotent; returns False if another library already owns the global subscriber.
def enable_logging() -> bool: ...
