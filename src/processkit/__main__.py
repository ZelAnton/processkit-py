"""``python -m processkit`` — the CLI entry point.

A thin wrapper delegating to `processkit._cli.main_and_exit`; see that
package's module docstring for the full CLI contract (subcommands, flags, and
the exit-code contract for both ``run`` and ``doctor``).

The exit itself goes through `processkit._cli.main_and_exit` rather than
``sys.exit(main())``: this process must not run interpreter finalization while
the binding's async bridge may still have a tokio worker thread inside the
interpreter. See that function's docstring for the race it closes.
"""

from __future__ import annotations

from processkit._cli import main_and_exit

if __name__ == "__main__":
    main_and_exit()
