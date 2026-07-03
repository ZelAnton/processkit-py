"""Start a server, wait until it is ready, use it, then reap the whole tree.

The "start a service, then talk to it" pattern - everywhere in CI orchestration
and integration tests, and a constant Python pain point (racy ``sleep()`` calls,
leaked server processes). Here the server runs inside a ``ProcessGroup``, so no
matter how the block exits - success, exception, or timeout - the server and
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

# A tiny stand-in HTTP server: bind a port (reusably, so a just-freed port rebinds
# cleanly on macOS/BSD), then answer every connection with a canned 200. Your real
# service - uvicorn, a Node process, a database - goes here instead. Kept inline and
# dependency-free so it starts in milliseconds and the example runs anywhere.
_SERVER = r"""
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((host, port))
srv.listen()
body = b"hello from the processkit example server\n"
response = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
    b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
) + body
while True:
    conn, _ = srv.accept()
    try:
        conn.recv(65536)      # read and ignore the request
        conn.sendall(response)
    except OSError:
        pass                  # a readiness probe that connected and left
    finally:
        conn.close()
"""


def _free_port() -> int:
    """Grab a port the OS is not using, so the example never collides with
    something already listening."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _http_status(url: str) -> int:
    """A blocking HTTP GET returning the status code - run off the event loop."""
    with urllib.request.urlopen(url, timeout=5) as response:
        return int(response.status)


async def main() -> None:
    port = _free_port()
    async with ProcessGroup() as group:
        await group.astart(Command(sys.executable, ["-c", _SERVER, HOST, str(port)]))

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
