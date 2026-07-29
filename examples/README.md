# processkit examples

Runnable, self-contained programs — each maps to one of the niches processkit is
built for. They use only the standard library plus `processkit`, spawn their own
child processes (via the running Python), and run to a clean exit on Windows,
Linux, and macOS (the sandbox example degrades gracefully where the kernel forbids
resource limits). Every one is exercised in CI, so they stay current with the API.

Run any of them from the repository root:

```bash
python examples/01_no_orphan_guarantee.py
```

| Example | Shows | Niche |
|---|---|---|
| [`01_no_orphan_guarantee.py`](01_no_orphan_guarantee.py) | A `ProcessGroup` reaps a whole child→grandchild tree on block exit | The core guarantee |
| [`02_wait_for_server.py`](02_wait_for_server.py) | Start a server, `await wait_for_port(...)`, make a request, tear the tree down (async) | CI orchestration / integration tests |
| [`03_supervise_until_healthy.py`](03_supervise_until_healthy.py) | `Supervisor` with restart + backoff + a `stop_when` predicate | Agents / long-lived services |
| [`04_sandbox_resource_limits.py`](04_sandbox_resource_limits.py) | Memory / process / CPU caps, per-call output limits, timeouts, and teardown across a locked-down agent's tool calls | Sandboxing untrusted tools |
| [`05_interactive_stdin.py`](05_interactive_stdin.py) | `keep_stdin_open()` + `take_stdin()` + `stdout_lines()` for a request/response conversation with a live REPL-style child | Agent/LLM tools driving a conversational subprocess |
| [`06_interactive_pty.py`](06_interactive_pty.py) | A managed PTY session with initial sizing, live resize, and terminal Ctrl-C | Terminal-oriented tools in automation |
| [`07_lifecycle_events.py`](07_lifecycle_events.py) | One ordered `started` → output → `exited` event stream | Progress and structured run telemetry |
| [`08_batch_as_completed.py`](08_batch_as_completed.py) | Bounded-concurrency results emitted as each command finishes | Large fan-out with immediate progress |
| [`09_spawn_detached.py`](09_spawn_detached.py) | A trusted, self-terminating detached helper and the explicit loss of containment | The rare intentional ownership opt-out |

For task-sized snippets rather than whole programs, see the
[cookbook](../docs/cookbook.md); for the full treatment of any area, the
[guide set](../docs/README.md). The [Sandboxing untrusted tools](../docs/sandboxing.md)
guide walks through the recipe behind `04_sandbox_resource_limits.py` in full,
plus a checklist and an honest threat model.
