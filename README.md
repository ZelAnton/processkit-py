# processkit

Python bindings to the [`processkit`](https://crates.io/crates/processkit) Rust crate —
asyncio-native, kernel-backed, no-orphan process containment.

> **Status: Phase 1 — minimal viable sync core.** Not yet published to PyPI. See
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

> **Coming next:** the asyncio-native surface (`await Command(...).output()`,
> `async with ProcessGroup()`, line streaming, readiness probes) — see
> [ROADMAP.md](ROADMAP.md) Phase 2+.

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
