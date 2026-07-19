"""``python -m processkit`` — run a shell command under processkit containment.

    python -m processkit run [OPTIONS] -- PROGRAM [ARG ...]

Everything after the literal ``--`` is the child's own argv, passed through
untouched (a second ``--`` in there is none of this wrapper's business — only
the *first* one is treated as the separator). The child is started inside a
`ProcessGroup` — a kill-on-exit container for the *whole* process tree, not
just the direct child — even for this single command, so a build tool's
grandchildren or a script's background jobs can never survive past this
process. Stdio is inherited straight through to the terminal
(`inherit_stdin()` / `stdout("inherit")` / `stderr("inherit")`): the child
reads from the same stdin and its output streams live, the same as running it
directly, never buffered up and dumped at the end.

Exit code contract:

- Normal completion: this process exits with the **exact same code** as the
  child (`Outcome.code`, unchanged).
- ``--timeout`` expired: exit **124** (matching GNU coreutils ``timeout``),
  with a one-line message on stderr — never a traceback.
- The child could not be found: exit **127** (``ProcessNotFound``).
- The child was found but could not be executed (e.g. not executable / no
  permission): exit **126** (``PermissionDenied``).
- The child was killed by a signal (POSIX only): exit **128 + signal number**
  (the same convention a POSIX shell uses).
- ``python -m processkit`` itself was interrupted with Ctrl+C: exit
  **128 + SIGINT**.
- Any other internal/containment failure (see below): exit **125**.

Resource-limit availability (``--max-memory`` / ``--max-processes`` /
``--cpu-quota``): these need a real container — a Windows Job Object or a
Linux **cgroup-v2 root** — the same prerequisite `ProcessGroup` itself
documents. When the kernel refuses a requested cap (`ResourceLimit` /
`Unsupported` — typical in containers, systemd user sessions, non-root
cgroups, and always on macOS), this CLI does **not** hard-fail: it prints a
warning to stderr and re-runs the child in a plain, uncapped `ProcessGroup`
— "contained, but uncapped" — by analogy with
``examples/04_sandbox_resource_limits.py``. The child still gets the
no-orphan containment guarantee either way; only the specific numeric caps
are dropped. If *no* resource limit was requested and containment itself is
unavailable (should not happen on any supported platform), that is instead
treated as the exit-125 internal failure above — and so is the (also
shouldn't-happen) case where the requested cap was rejected *and* the plain,
uncapped fallback still fails: containment is unavailable outright, not
merely the specific cap.

    python -m processkit doctor

A read-only preflight diagnosis of the containment environment, for CI gates
and wrapper scripts that want to know "will my caps actually hold here"
*before* running any untrusted workload, instead of parsing a `run` warning
on stderr after the fact. Nothing is spawned: it only constructs (and
immediately drops) throwaway `ProcessGroup` instances to see what the kernel
grants. Prints the active mechanism (`ProcessGroup().mechanism`) and whether
resource limits (`--max-memory` / `--max-processes` / `--cpu-quota`) are
actually enforceable — the same platform gap `run` degrades around above
(containers, systemd user sessions, non-root cgroups, and always on macOS
lack the Windows Job Object / Linux cgroup-v2 root those caps need).

`doctor` probes each of the three resource-limit controllers
(``--max-memory`` / ``--max-processes`` / ``--cpu-quota``) **independently** —
on Linux cgroup-v2 these are separate controllers (``memory.max``,
``pids.max``, ``cpu.max``) that can be unavailable one without the others —
so "resource limits are available" means *all three* probed successfully,
not just the first one tried.

`doctor`'s exit code is machine-readable and lives in its own reserved range,
deliberately disjoint from `run`'s codes above (124/125/126/127/128+signal)
*and* from argparse's own usage-error code (`2` — the same code `run` itself
uses for a bad invocation, e.g. a missing `--`-terminated command): `doctor`
never returns `2` as a diagnostic verdict, so a caller can always read `2` as
"you called this wrong", unambiguous from any of the codes below:

- **0** — resource limits are available (containment *and* all three caps
  hold).
- **1** — containment is enforced, but at least one resource limit is not
  (the "contained, but uncapped" gap).
- **3** — containment itself is unavailable (should not happen on any
  supported platform).
- **4** — a probe raised an unexpected operational error (e.g. `OSError` /
  `PermissionError` reading cgroup state) rather than a definitive
  `ResourceLimit`/`Unsupported` answer — the environment's actual
  availability could not be determined, so this is deliberately distinct
  from both `1` and `3` rather than guessing which one it is.

This package (``processkit._cli``) is the private implementation behind the
thin ``src/processkit/__main__.py`` entry point: `parser` builds the
argparse parsers and splits the ``--`` separator, `run` implements the
``run`` subcommand, `doctor` implements the ``doctor`` subcommand, and
`exit_codes` holds the shared exit-code constants both subcommands use.
Nothing here is part of the public ``processkit`` package surface.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from processkit._cli.doctor import _doctor
from processkit._cli.parser import _build_parser, _split_child_argv
from processkit._cli.run import _run

__all__: list[str] = []  # deliberately empty: this package is not public API


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    own_argv, child_argv = _split_child_argv(raw_argv)

    parser, run_parser, doctor_parser = _build_parser()
    args = parser.parse_args(own_argv)

    if args.subcommand == "doctor":
        if child_argv:
            doctor_parser.error("doctor: does not take a trailing command (no '--' needed)")
        return _doctor()

    # "run" is the only other subparser registered above, and `required=True`
    # means `parse_args` itself already rejected anything else — so `run` is
    # guaranteed parsed by now, and this late validation error reports
    # against the `run` usage line, not the top-level one.
    if not child_argv:
        run_parser.error("run: missing command to execute after '--'")
    return _run(run_parser, args, child_argv)
