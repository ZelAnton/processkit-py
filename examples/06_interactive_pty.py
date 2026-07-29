"""Drive a terminal-oriented child through a managed pseudo-terminal.

Run it:  python examples/06_interactive_pty.py
"""

from __future__ import annotations

import asyncio
import sys

from processkit import Command

_CHILD = "import time; print('ready', flush=True); time.sleep(30)"


async def main() -> None:
    proc = await (
        Command(sys.executable, ["-c", _CHILD]).pty(cols=100, rows=30).keep_stdin_open().astart()
    )
    async with proc:
        output = proc.stdout_lines()
        first_line = await anext(output)
        print(first_line.rstrip())

        proc.resize_pty(120, 40)
        terminal_input = proc.take_stdin()
        await terminal_input.send_control("c")
        outcome = await proc.aoutcome()

    print(f"terminal child stopped: {not outcome.exited_zero}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=20))
