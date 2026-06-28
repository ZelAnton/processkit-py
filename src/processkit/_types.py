"""Public type aliases, exported so callers can annotate their own wrappers.

`StrPath` is what every program/path argument accepts; `SignalName` is the set of
portable signal names accepted by `Command.timeout_signal()` / `ProcessGroup.signal()`.
Kept here as the single runtime+stub source (the compiled module's `.pyi` imports
them), so a caller can `from processkit import SignalName, StrPath`.
"""

from __future__ import annotations

import os
from typing import Literal

StrPath = str | os.PathLike[str]
SignalName = Literal["term", "kill", "int", "hup", "quit", "usr1", "usr2"]

__all__ = ["SignalName", "StrPath"]
