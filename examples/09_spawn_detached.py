"""Launch a trusted short-lived helper that intentionally outlives its owner.

Run it:  python examples/09_spawn_detached.py
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
import time
from pathlib import Path

from processkit import Command


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "helper-finished"
        helper = (
            "import pathlib, time; "
            "time.sleep(0.2); "
            f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')"
        )
        child = Command(sys.executable, ["-c", helper]).spawn_detached()
        print(f"detached pid={child.pid}")

        # DetachedChild is deliberately pid-only: processkit cannot wait for,
        # kill, time out, or contain it. The helper must own its own lifetime.
        deadline = time.monotonic() + 5
        contents = ""
        while time.monotonic() < deadline:
            with contextlib.suppress(FileNotFoundError):
                contents = marker.read_text(encoding="utf-8")
            if contents == "done":
                break
            time.sleep(0.05)
        if contents != "done":
            raise RuntimeError("detached helper did not finish")
        print(contents)


if __name__ == "__main__":
    main()
