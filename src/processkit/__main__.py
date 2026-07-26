"""``python -m processkit`` — the CLI entry point.

A thin wrapper delegating to `processkit._cli.main_and_exit`; see that
package's module docstring for the full CLI contract (subcommands, flags, and
the exit-code contract for both ``run`` and ``doctor``).

The exit itself goes through `processkit._cli.main_and_exit` so Ctrl+C,
unexpected exceptions, final output flushing, and exit-code normalization all
share one path before ordinary interpreter finalization runs.
"""

from __future__ import annotations

from processkit._cli import main_and_exit

if __name__ == "__main__":
    main_and_exit()
