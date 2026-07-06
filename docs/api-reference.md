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

::: processkit.Command

::: processkit.CliClient

::: processkit.Pipeline

::: processkit.RunningProcess

## Results & outcomes

What a finished (or streamed) run reports back. A non-zero exit, a timeout, and a signal-kill are all *data* on these types — never raised by the capturing verbs.

::: processkit.ProcessResult

::: processkit.BytesResult

::: processkit.Outcome

::: processkit.Finished

::: processkit.RunProfile

## Streaming & interactive I/O

The live handles a started `RunningProcess` hands out: async iterators over its output (line by line, or as interleaved stdout/stderr events) and a writable stdin.

::: processkit.StdoutLines

::: processkit.OutputEvents

::: processkit.OutputEvent

::: processkit.ProcessStdin

## Process groups

Kill-on-drop containment for a whole process tree — start children into it, signal or suspend the group, and reap the entire tree (grandchildren included) on exit.

::: processkit.ProcessGroup

::: processkit.ProcessGroupStats

## Supervision

Keep a command alive: restart it per a policy, with backoff and jitter, until a stop condition is met.

::: processkit.Supervisor

::: processkit.SupervisionOutcome

## Cancellation

A portable cancel switch, wired into a run via `Command.cancel_on()`, `Pipeline.cancel_on()`, or `CliClient`'s `default_cancel_on=`.

::: processkit.CancellationToken

## Batch execution

Run many commands with bounded concurrency, returning each result — or a `ProcessError` for a spawn/I/O failure — in input order.

::: processkit.output_all

::: processkit.output_all_bytes

::: processkit.aoutput_all

::: processkit.aoutput_all_bytes

## Readiness helpers

Asyncio helpers that wait for a condition — a matching output line, an open TCP port, or any polled predicate — bounded by a deadline.

::: processkit.wait_until

::: processkit.wait_for_line

::: processkit.wait_for_port

::: processkit.WaitTimeout

## Observability

Opt-in bridging of the core's per-run `tracing` events to Python `logging`.

::: processkit.enable_logging

## The runner seam

The dependency-injection seam: annotate your code against a protocol, inject the real `Runner` in production and a test double (see the Testing section) in tests. `ProcessRunner` is the capture/check verbs; `StreamingRunner` adds `start`/`astart`.

::: processkit.ProcessRunner

::: processkit.StreamingRunner

::: processkit.Runner

## Exceptions

Every error raised by the package descends from `ProcessError`, so a single `except ProcessError` catches them all. `Timeout`, `ProcessNotFound`, and `PermissionDenied` also subclass a builtin (`TimeoutError` / `FileNotFoundError` / `PermissionError`, each itself an `OSError`), so the stdlib `except` clauses catch them too.

::: processkit.ProcessError

::: processkit.NonZeroExit

::: processkit.Timeout

::: processkit.Signalled

::: processkit.ProcessNotFound

::: processkit.PermissionDenied

::: processkit.ResourceLimit

::: processkit.Unsupported

::: processkit.OutputTooLarge

::: processkit.Cancelled

## Type aliases

Exported so your own wrappers can annotate against the same types the API accepts.

::: processkit.Args

::: processkit.LineTerminatorName

::: processkit.Priority

::: processkit.ReadableBuffer

::: processkit.RetryIf

::: processkit.SignalName

::: processkit.StrPath

## Testing

Runner test doubles, in the `processkit.testing` submodule. Inject one in tests — all satisfy the `ProcessRunner` protocol — so the code under test spawns no real processes.

::: processkit.testing.ScriptedRunner

::: processkit.testing.RecordReplayRunner

::: processkit.testing.RecordingRunner

::: processkit.testing.DryRunRunner

::: processkit.testing.Reply

::: processkit.testing.Invocation
