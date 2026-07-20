"""``python -m processkit`` — the CLI entry point.

A thin wrapper delegating to `processkit._cli.main`; see that package's
module docstring for the full CLI contract (subcommands, flags, and the
exit-code contract for both ``run`` and ``doctor``).
"""

from __future__ import annotations

import sys

from processkit._cli import main

if __name__ == "__main__":
    sys.exit(main())
