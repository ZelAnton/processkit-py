"""Handle a bounded batch in completion order instead of input order.

Run it:  python examples/08_batch_as_completed.py
"""

from __future__ import annotations

import asyncio
import sys

from processkit import Command, ProcessError, aoutput_as_completed


async def main() -> None:
    commands = [
        Command(sys.executable, ["-c", f"import time; time.sleep({delay}); print({index})"])
        for index, delay in enumerate((0.25, 0.05, 0.15))
    ]

    async for index, result in aoutput_as_completed(commands, concurrency=2):
        if isinstance(result, ProcessError):
            print(f"slot {index} failed to run: {result}")
        else:
            print(f"slot {index} finished: {result.stdout.strip()}")


if __name__ == "__main__":
    asyncio.run(main())
