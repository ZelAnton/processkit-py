"""Pure-Python asyncio readiness helpers.

These compose on top of the compiled async surface (a `StdoutLines` iterator, a
plain TCP connect) rather than bridging the Rust crate's borrowing probe methods
— simpler, fully composable, and they work against any server, not only one this
package started.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

from ._processkit import ProcessError

__all__ = ["wait_for_line", "wait_for_port"]


async def wait_for_port(
    host: str,
    port: int,
    timeout: float,
    *,
    interval: float = 0.05,
) -> None:
    """Wait until a TCP connection to ``(host, port)`` succeeds.

    Polls every ``interval`` seconds until the port accepts a connection or
    ``timeout`` seconds elapse, in which case `TimeoutError` is raised.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"port {host}:{port} not ready within {timeout}s")
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=remaining
            )
        except (OSError, asyncio.TimeoutError):
            if loop.time() >= deadline:
                raise TimeoutError(f"port {host}:{port} not ready within {timeout}s") from None
            await asyncio.sleep(interval)
            continue
        writer.close()
        # The probe connection closing is best-effort.
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return


async def wait_for_line(
    lines: AsyncIterator[str],
    predicate: Callable[[str], bool],
    timeout: float,
) -> str:
    """Consume from an stdout line iterator until ``predicate(line)`` is true.

    Returns the matching line. Raises `TimeoutError` if no line matches within
    ``timeout`` seconds, or `ProcessError` if the stream ends first. Lines read
    before the match are consumed; iteration may continue afterwards.
    """

    async def scan() -> str:
        async for line in lines:
            if predicate(line):
                return line
        raise ProcessError("the output stream ended before a matching line")

    try:
        return await asyncio.wait_for(scan(), timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"no matching line within {timeout}s") from None
