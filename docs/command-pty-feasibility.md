# PTY launch mode (`Command.pty()`) — feasibility & design

**Status: implemented.** This remains the historical decision record that led
to the shipping PTY surface. The current user contract is documented in
[Running commands](commands.md#pseudo-terminal-mode) and
[Streaming & interactive I/O](streaming.md#interactive-pty-sessions):
`Command.pty(*, cols=None, rows=None)`, merged terminal output through stdout,
interactive input through `take_stdin()`, and live
`RunningProcess.resize_pty(cols, rows)`.

The design sketches and upstream constraints below are retained to explain the
decision. Where a sketch differs from the final API, the shipping surface above
wins: there is no `echo=` option, resize is named `resize_pty`, and conflicting
stdio builder calls are rejected during command construction.

## Why a PTY mode at all

processkit-py's target niche — agent/LLM frameworks and CI tooling that shell
out to third-party CLIs — repeatedly hits the "no tty" wall. Many programs
change behaviour when their stdio is a pipe rather than a terminal:

- output switches from line-buffered to block-buffered, so a live
  `stdout_lines()` stream stalls until the child flushes or exits;
- interactive prompts, progress bars, and pagers turn themselves off (or, worse,
  a tool *insists* on a tty and refuses to run);
- terminal control sequences (colour, cursor moves) and real terminal signals
  (Ctrl-C → `SIGINT`, Ctrl-Z → `SIGTSTP`) are unavailable.

At the time of this decision, the streaming/interactive surface
(`keep_stdin_open()` / `take_stdin()` / `stdout_lines()` / `send_control()`)
drove such tools over ordinary **pipes**. The gap described here has since been
closed by the implemented PTY surface linked above.

## Decision summary (the answer up front)

- **(a) A binding-only PTY mode is not feasible against the pinned crate.** The
  binding cannot inject a PTY into a launch without upstream support, for two
  independent reasons (no stdio-injection seam, and race-free-spawn-into-
  containment being crate-owned). See [Feasibility](#a-feasibility-binding-only-vs-upstream).
- **(b) Upstream support is therefore required.** A concrete, ready-to-file API
  request to the `processkit` crate is drafted in
  [Upstream request](#b-upstream-request-to-the-processkit-crate).
- **(c) The proposed Python surface is `Command.pty(...)`**, streaming one
  merged terminal stream through `RunningProcess` while preserving kill-on-exit
  containment unchanged. See [Python API sketch](#c-python-api-sketch-commandpty).
- **(d) Implementation landed in the upstream crate and this binding**, including
  public-surface, test, and documentation follow-ups.

## Background: how a launch works today

processkit-py is a **thin PyO3 binding** to the upstream `processkit` Rust crate
(pinned to the `2.3` compatible range; `Cargo.lock` resolves it to `2.3.2`,
built with `default-features = false`). The layering, spelled out in the
*Architecture* page (`docs/internals.md`), matters directly here:

- the binding crate (`src/*.rs` → the `_processkit` cdylib) is glue: it exposes
  the crate's types as pyclasses, drives its futures, and maps its errors — it
  does **not** reimplement any OS mechanism;
- the `processkit` crate owns *all* platform logic: Windows Job Objects, Linux
  cgroup v2, POSIX process groups, and the **race-free spawn** that enrols a
  child into its containment primitive atomically with creating it.

Two facts about the current stdio surface are load-bearing for the feasibility
question:

1. **The child's stdio is a closed three-variant choice.** `Command.stdout(...)`
   / `Command.stderr(...)` accept only `"pipe"` / `"inherit"` / `"null"`, which
   the binding maps (in `src/convert.rs`) onto the crate's `StdioMode` enum —
   `Piped`, `Inherit`, `Null`. There is no public crate API that hands the child
   a **caller-provided OS handle/fd** for a std stream.
2. **Spawn and containment are one atomic, crate-owned step.** `Command.start()`
   (`src/command.rs`, `src/running.rs`) calls straight into the crate; the child
   is created and enrolled in its Job Object / cgroup / process group in the same
   race-free sequence. The binding has no seam between "process created" and
   "process contained".

## (a) Feasibility: binding-only vs. upstream

**Conclusion: a PTY mode cannot be implemented in the binding layer
(`src/command.rs`, `src/runner.rs`, `src/running.rs`) alone against the pinned
crate. Upstream support is required.** This rests on two *independent* blockers —
either one is sufficient on its own.

### Blocker 1 — no stdio-injection seam

Allocating the PTY itself from the binding is entirely feasible in principle: a
Rust helper crate such as `portable-pty` (or direct platform calls) can create a
ConPTY on Windows or an `openpty()` master/slave pair on POSIX. The problem is
the *next* step. The crate's `Command` builder only exposes `StdioMode`
(`Piped`/`Inherit`/`Null`); it accepts no raw handle or file descriptor for the
child's stdin/stdout/stderr. So even with a freshly allocated PTY slave in hand,
the binding has nowhere to hand it to the crate's spawn. A binding-only PTY would
have to bypass the crate's launch entirely — which runs straight into Blocker 2.

### Blocker 2 — race-free spawn into containment is crate-owned and atomic

Attaching a PTY slave is not a post-spawn operation on any platform — it has to
happen *as part of* process creation:

- **Windows (ConPTY):** the pseudo-console handle is passed via
  `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` in the `STARTUPINFOEX` given to
  `CreateProcess`. It cannot be attached after the child exists.
- **POSIX (`openpty`):** the slave fd must become the child's controlling
  terminal in the pre-exec window (`setsid()` then `TIOCSCTTY`, with the slave
  dup'd onto fds 0/1/2). This runs in the forked child before `execvp`.

Both of these live squarely inside the crate's race-free spawn sequence — the
very code the crate exists to own. For the binding to inject a PTY it would have
to spawn the child *itself* (with the slave attached) and only then ask the crate
to contain it. But there is no crate API to enrol an **already-spawned,
binding-created** process into a fresh Job Object / cgroup as part of a race-free
sequence. The nearest concept the crate documents is *adopting* a foreign
process into a group — exposed by the published binding as
`ProcessGroup.adopt_external(pid)` — but adoption is explicitly best-effort: it
opens exactly the spawn/enrol race that the crate's own launch eliminates (in the
window between creation and enrolment, the child can fork descendants that escape
containment). Trading the project's core no-orphan / kill-on-exit guarantee for a
PTY is not an acceptable design, so this path is rejected even where it is
technically reachable.

### Consequence

Because both the stdio seam and the atomic spawn belong to the pinned crate, the
PTY capability has to originate **upstream**. The crate's own release cadence
makes this practical rather than blocking: each recent `processkit` patch release
has in fact shipped new public API (file-redirect stdio sinks,
`kill_on_parent_death_scope`, and more), and this binding adopts each as it
lands. A PTY builder can follow the same path once requested.

### Open questions to settle with upstream

- Whether the crate prefers a new **`StdioMode::Pty`** variant, a dedicated
  **`Command::pty(PtyOptions)`** builder, or both (a builder reads better for the
  extra knobs — size, echo — that a bare enum variant can't carry).
- Whether the crate takes an internal `portable-pty` dependency or calls the
  platform APIs directly (affects its dependency surface and MSRV).
- Whether stdout and stderr are **necessarily merged** on the master (they are on
  a real terminal) or whether the crate can optionally keep a separate stderr
  pipe alongside the PTY (some tools split diagnostics onto stderr even under a
  tty).
- How PTY interacts with the crate's existing `inherit_stdin` / file-redirect
  stdio and with `ProcessGroup` membership.

## (b) Upstream request to the `processkit` crate

The following is drafted to be filed as-is against the upstream crate.

```text
Title: opt-in PTY (pseudo-terminal) launch mode for Command

Motivation
  Downstream (processkit-py, and any consumer driving interactive/tty-demanding
  CLIs) needs to launch a child attached to a pseudo-terminal instead of pipes,
  so that block-buffered tools stream live, prompts/progress/pagers stay on, and
  real terminal signals (Ctrl-C -> SIGINT) reach the child. This must NOT weaken
  the crate's race-free-spawn-into-containment guarantee.

Requested API (illustrative shape)
  Command::pty(PtyOptions) -> Command            // opt-in builder
    PtyOptions { cols: u16, rows: u16, echo: bool }

  Within the EXISTING race-free spawn, the crate would:
    - allocate the pty (ConPTY via CreatePseudoConsole on Windows;
      openpty + controlling-tty setup in the pre-exec window on POSIX),
    - attach the slave to the child's std handles (stdout+stderr merged, as on a
      real terminal, unless a split-stderr option is offered),
    - enrol the child in the Job Object / cgroup / process group EXACTLY as today
      (containment and kill-on-exit unchanged),
    - keep the master and surface it on RunningProcess for read + write,
    - support an initial window size and a runtime resize
      (ResizePseudoConsole on Windows; TIOCSWINSZ on POSIX).

  RunningProcess additions:
    - a read handle for the merged terminal stream (reuse StdoutLines /
      OutputEvents, or a dedicated terminal reader),
    - the existing stdin writer (ProcessStdin) drives the master so send_control
      delivers a REAL terminal control (SIGINT) via the line discipline,
    - resize(cols, rows).

Constraints / non-negotiables
  - No new spawn/enrol race: pty attach happens inside the crate's own launch.
  - PTY is mutually exclusive with inherit_stdin and the file-redirect stdio
    sinks; document the precedence/rejection.
  - Off-platform behaviour stated explicitly (both families support a pty, so
    this is a supported-everywhere feature, not a platform no-op).

Questions
  - New StdioMode::Pty variant, a Command::pty(...) builder, or both?
  - portable-pty dependency vs. direct platform calls?
  - Mandatory stdout/stderr merge, or an optional separate stderr pipe?
```

## (c) Implemented Python API (`Command.pty()`)

The final binding surfaces the opt-in builder using the existing builder
conventions (`src/command.rs`). The historical sketch below is followed by the
final differences.

```python
proc = await Command("claude", ["--interactive"]).pty(cols=120, rows=40).keep_stdin_open().astart()

# One MERGED terminal stream: the existing stdout iterator carries stdout and
# stderr together.
lines = proc.stdout_lines()
stdin = proc.take_stdin()
await stdin.write_line("do the thing")
proc.resize_pty(160, 50)
await stdin.send_control("c")
outcome = await proc.aoutcome()
```

### Semantics that the design pins down

- **Merged terminal stream.** A real terminal has one stream, so under `pty()`
  the child's stdout and stderr are combined on the master. The existing
  `RunningProcess.stdout_lines()` / `output_events()` carry that merged output,
  with the separate-stderr view empty. The chosen line framing
  (`line_terminator(...)`) still applies to the merged stream — important for
  carriage-return progress output, which is exactly the tty case.
- **Interactive stdin over the master.** `keep_stdin_open()` + `take_stdin()`
  return a `ProcessStdin` that writes to the master. The key behavioural upgrade:
  `send_control("c")` becomes a **real** terminal control (the line discipline
  turns it into `SIGINT`), rather than the plain `\x03` byte pipe mode sends to a
  cooperating child (see `docs/streaming.md`). `inherit_stdin()` stays
  mutually exclusive with `pty()` — a pty *is* a crate-managed terminal, so
  handing the child the parent's real terminal at the same time is a
  contradiction and is rejected during command construction, mirroring the existing
  `inherit_stdin` / `keep_stdin_open` exclusion.
- **Kill-on-exit containment is unchanged.** Because the child is still spawned
  race-free into the crate's Job Object / cgroup / process group, the no-orphan
  guarantee is identical to a pipe launch: dropping the `RunningProcess`, exiting
  its `with` / `async with` block, or a timeout still hard-kills the whole
  private tree. The PTY master is just another captured stream — closing it never
  affects containment. This equivalence is the whole point of routing PTY through
  the crate rather than spawning in the binding (see
  [Blocker 2](#blocker-2--race-free-spawn-into-containment-is-crate-owned-and-atomic)).
- **Window size.** An initial `cols`/`rows` at build time and a runtime
  `RunningProcess.resize_pty(cols, rows)`; both optional, with a sensible default
  size when unset.
- **Mutual exclusivity & platform reach.** `pty()` is incompatible with the
  file-redirect stdio sinks (`stdout_file` / `stderr_file`) and with
  `inherit_stdin`; conflicts are rejected while constructing the command, not
  silently ignored. Both
  platform families support a pseudo-terminal, so — unlike the POSIX-only
  privilege knobs — this is a supported-everywhere feature rather than an
  off-platform no-op.

### Pipe-mode alternatives

Even though PTY mode now ships, non-interactive operation or direct terminal
inheritance can still be the simpler choice:

```python
from processkit import Command

# Prefer non-interactive modes so a pipe launch behaves deterministically.
Command("ssh", ["-o", "BatchMode=yes", "deploy@host", "systemctl status app"]).run()
Command("git", ["fetch"]).env("GIT_TERMINAL_PROMPT", "0").run()

# Or give the child the *real* terminal (no crate-mediated capture) when it must
# talk to a tty — e.g. an editor or a password prompt.
Command("gpg", ["--decrypt", "secret.asc"]).inherit_stdin().stdout("inherit").run()
```

## (d) Completed follow-up work

The upstream, binding, public-surface, test, and documentation follow-ups have
all landed. The original checklist is retained as implementation history:

1. **Upstream request.** File the PTY API request from
   [section (b)](#b-upstream-request-to-the-processkit-crate) against the
   `processkit` crate; track its landing.
2. **Adopt the upstream PTY API in the binding.** Once released, bump the pinned
   crate version and wire a `Command.pty(...)` builder in `src/command.rs` (plus
   any `src/convert.rs` mapping), following the existing builder/`StdioMode`
   conventions.
3. **Stream + control the terminal on `RunningProcess`.** Expose the merged
   terminal stream and `resize(...)` in `src/running.rs`, and make
   `send_control` deliver real terminal controls under a pty.
4. **Stub, surface, and reference sync.** Update `src/processkit/_processkit.pyi`,
   the `__init__` / `processkit.testing` re-exports, and regenerate
   `docs/api-reference.md`, keeping the stub/runtime/surface drift guards green.
5. **User docs + tests.** Add a PTY section to the *Streaming & interactive I/O*
   and *Running commands* guides (and drop the "not provided yet" caveats),
   and add platform-gated PTY tests plus doc snippets.
