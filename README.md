# processkit

Python bindings to the [`processkit`](https://crates.io/crates/processkit) Rust crate —
asyncio-native, kernel-backed, no-orphan process containment.

> **Status: Phase 0 — de-risk spikes.** Not yet published to PyPI. See
> [ROADMAP.md](ROADMAP.md) for the plan.

## What it does

Thin PyO3 bindings to the `processkit` Rust crate. The Rust crate handles all the hard
platform code — Windows Job Object containment, Linux cgroup v2, race-free subprocess spawn.
The Python layer exposes an asyncio-native surface with context-manager teardown.

```python
import asyncio
from processkit import Command, ProcessGroup

async def main():
    result = await Command("git", ["rev-parse", "HEAD"]).output()
    print(result.stdout.strip(), result.exit_code)

    async with ProcessGroup() as group:
        server = await group.start(Command("my-server"))
        await server.wait_for_port(("127.0.0.1", 8080), timeout=10)
        # whole process tree is reaped on exit, grandchildren included

asyncio.run(main())
```

> **Note (Phase 0):** `Command` and `ProcessGroup` are not yet implemented.
> The API above is the planned target surface — see [ROADMAP.md](ROADMAP.md).

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
