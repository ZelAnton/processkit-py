"""Observe one ordered stream from process start through process exit.

Run it:  python examples/07_lifecycle_events.py
"""

from __future__ import annotations

import asyncio
import sys

from processkit import Command

_CHILD = "import sys; print('building'); print('warning', file=sys.stderr)"


async def main() -> None:
    proc = await Command(sys.executable, ["-c", _CHILD]).astart()
    async with proc:
        async for event in proc.lifecycle_events():
            if event.kind == "started":
                print(f"started pid={event.pid}")
            elif event.kind in {"stdout", "stderr"}:
                assert event.text is not None
                print(f"{event.stream}: {event.text.rstrip()}")
            elif event.kind == "exited":
                assert event.outcome is not None
                print(f"exited code={event.outcome.code}")

        finished = await proc.afinish()
        assert finished.exited_zero


if __name__ == "__main__":
    asyncio.run(main())
