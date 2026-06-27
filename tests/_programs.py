"""Shared test fixtures: reusable child-program snippets and a free-port helper.
Centralized so a tweak lands in one place rather than in every test module that
spawns a grandchild or needs an ephemeral port.
"""

from __future__ import annotations

import socket

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
    """Bind an ephemeral port, then release it, returning the number — for tests
    that need a port nothing is listening on (readiness-probe timeouts)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port
