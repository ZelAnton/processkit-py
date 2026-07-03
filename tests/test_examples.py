"""Every script under examples/ must run to a clean exit.

These are the programs users copy first, so a broken one is a broken first
impression — and because they live outside the package, nothing else would catch
API drift in them. Each runs in a child interpreter (they spawn processes and
bind ports of their own), so this mirrors exactly what `python examples/<name>.py`
does for a user.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
_EXAMPLES = sorted(_EXAMPLES_DIR.glob("*.py"))


def test_examples_directory_is_populated() -> None:
    # Guard against a false green if the directory moves or the glob breaks:
    # an empty parametrization would otherwise report zero tests, silently.
    assert _EXAMPLES, f"no example scripts found under {_EXAMPLES_DIR}"


@pytest.mark.parametrize("script", _EXAMPLES, ids=lambda p: p.name)
def test_example_runs_cleanly(script: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"{script.name} exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    # A caught-and-handled error is fine (e.g. the sandbox example degrades on a
    # ResourceLimit); an *un*caught one surfaces as a traceback on stderr.
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"{script.name} raised an uncaught exception:\n{result.stderr}"
    )
