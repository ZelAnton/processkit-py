# processkit

Python bindings to the [`processkit`](https://crates.io/crates/processkit) Rust crate —
asyncio-native, kernel-backed, no-orphan process containment.

> **Status: Phase 2 — async & streaming.** Not yet published to PyPI. See
> [ROADMAP.md](ROADMAP.md) for the plan.

## What it does

Thin PyO3 bindings to the `processkit` Rust crate. The Rust crate handles all the hard
platform code — Windows Job Object containment, Linux cgroup v2, race-free subprocess spawn.
The Python layer exposes a typed surface with context-manager teardown.

The synchronous surface is available today:

```python
from processkit import Command, ProcessGroup

# Run and capture. A non-zero exit is data, not an exception.
result = Command("git", ["rev-parse", "HEAD"]).output()
print(result.stdout.strip(), result.code)

# Kill-on-exit container for a whole tree.
with ProcessGroup() as group:
    group.start(Command("my-server"))
    # ... use the server ...
# group exit reaps the whole tree, grandchildren included
```

`output()` captures a non-zero exit, a timeout, and a signal-kill as data
(`result.code`, `result.timed_out`, `result.signal`); `run()` returns trimmed
stdout and raises on failure. The raised exceptions carry structured fields
(`NonZeroExit.code` / `.stdout` / `.stderr`, `Timeout.timeout_seconds`, …), and
a blocked sync call honours `Ctrl+C` — it raises `KeyboardInterrupt` and reaps
the process tree rather than hanging.

### Async & streaming

The asyncio-native surface mirrors the sync one with an `a`-prefix, and adds
line streaming and interactive stdin:

```python
import asyncio
from processkit import Command, ProcessGroup


async def main():
    # Run-and-capture; cancelling the awaiting task reaps the whole tree.
    result = await Command("git", ["rev-parse", "HEAD"]).aoutput()
    print(result.stdout.strip(), result.code)

    # Stream a child's stdout line by line.
    proc = await Command("ping", ["-c", "3", "127.0.0.1"]).astart()
    async for line in proc.stdout_lines():
        print(line)
    await proc.wait()

    # Kill-on-exit container for a whole tree.
    async with ProcessGroup() as group:
        await group.astart(Command("my-server"))
        # ... use the server ...
    # async-with exit reaps the whole tree, grandchildren included


asyncio.run(main())
```

Write to a child interactively with `keep_stdin_open()` + `take_stdin()`, or feed
input upfront with `stdin_text()` / `stdin_bytes()`.

## Requirements

- Python 3.10 or later (abi3 wheel; [Rust toolchain](https://rustup.rs/) required to build from source)

## Installation

Not yet on PyPI. To build from source:

```sh
git clone https://github.com/ZelAnton/processkit-py
cd processkit-py
uv run maturin develop
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for build/test instructions and conventions.
To report a security issue, follow [SECURITY.md](SECURITY.md).

## License

This project is licensed under the [MIT License](LICENSE).
