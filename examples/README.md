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
| [`04_sandbox_resource_limits.py`](04_sandbox_resource_limits.py) | Memory / process / CPU caps on a locked-down untrusted child | Sandboxing untrusted tools |

For task-sized snippets rather than whole programs, see the
[cookbook](../docs/cookbook.md); for the full treatment of any area, the
[guide set](../docs/README.md).
