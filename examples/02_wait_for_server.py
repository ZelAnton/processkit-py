"""Start a server, wait until it is ready, use it, then reap the whole tree.

The "start a service, then talk to it" pattern — everywhere in CI orchestration
and integration tests, and a constant Python pain point (racy ``sleep()`` calls,
leaked server processes). Here the server runs inside a ``ProcessGroup``, so no
matter how the block exits — success, exception, or timeout — the server and
anything it spawned are gone.

``wait_for_port`` replaces the usual ``time.sleep(2)  # hope it's up`` guess with
an actual readiness check.

Run it:  python examples/02_wait_for_server.py
"""

from __future__ import annotations

import asyncio
import socket
import sys
import urllib.request

from processkit import Command, ProcessGroup, wait_for_port

HOST = "127.0.0.1"


def _free_port() -> int:
    """Grab a port the OS is not using, so the example never collides with
    something already listening."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _http_status(url: str) -> int:
    """A blocking HTTP GET returning the status code — run off the event loop."""
    with urllib.request.urlopen(url, timeout=5) as response:
        return int(response.status)


async def main() -> None:
    port = _free_port()
    async with ProcessGroup() as group:
        # Python's stdlib HTTP server stands in for your real service. Send its
        # logs to null: it communicates over the socket, so we don't need them —
        # and an undrained stdio pipe would otherwise stall a background server.
        server = (
            Command(sys.executable, ["-m", "http.server", str(port), "--bind", HOST])
            .stdout("null")
            .stderr("null")
        )
        await group.astart(server)

        print(f"waiting for the server on {HOST}:{port} ...")
        await wait_for_port(HOST, port, timeout=10)
        print("server is accepting connections")

        # urllib is blocking, so run it in a worker thread rather than stalling
        # the event loop.
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, _http_status, f"http://{HOST}:{port}/")
        print(f"GET / -> HTTP {status}")
        print("leaving the block - the server tree is about to be reaped...")

    print("done - the server has been torn down.")


if __name__ == "__main__":
    asyncio.run(main())
