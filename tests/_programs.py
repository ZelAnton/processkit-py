"""Shared test fixtures: reusable child-program snippets and a free-port helper.
Centralized so a tweak lands in one place rather than in every test module that
spawns a grandchild or needs an ephemeral port.
"""

from __future__ import annotations

import contextlib
import socket
from collections.abc import Iterator

# A child that spawns a *grandchild* (a detached sleeper), records the
# grandchild's pid to argv[1], then sleeps. Used to prove whole-tree teardown:
# killing the child must also reap the grandchild.
SPAWN_GRANDCHILD = (
    "import subprocess, sys, time;"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
    "open(sys.argv[1], 'w').write(str(gc.pid));"
    "time.sleep(60)"
)


def free_port() -> int:
    """Bind an ephemeral port, then release it, returning the number — for a
    test that will bind its own listener on it shortly after (a small,
    accepted TOCTOU window). For a test that needs a *guaranteed* refused
    connection instead, use `refused_port()`."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@contextlib.contextmanager
def refused_port() -> Iterator[int]:
    """Bind an ephemeral port and hold it open (never `listen()`) for the
    block's duration, yielding the port number — for tests that need a
    deterministically *refused* connection (readiness-probe timeout/retry
    paths). Unlike `free_port()`'s bind-then-release, holding the socket open
    closes the TOCTOU window where another process could grab the port before
    the test connects; a bound-but-not-listening socket still refuses incoming
    connections (ECONNREFUSED), so "nothing is listening" behavior is
    unchanged.
    """
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        yield int(sock.getsockname()[1])
    finally:
        sock.close()
