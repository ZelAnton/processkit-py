"""Failure-aware writes for output produced by the CLI wrapper itself."""

from __future__ import annotations

import errno
import sys
from typing import Literal


class OutputWriteError(Exception):
    """The wrapper could not deliver its own output to a live destination."""


def _emit(stream_name: Literal["stdout", "stderr"], text: str) -> bool:
    stream = getattr(sys, stream_name)
    if stream is None:
        return False
    try:
        stream.write(text + "\n")
    except BrokenPipeError:
        setattr(sys, stream_name, None)
        return False
    except OSError as exc:
        setattr(sys, stream_name, None)
        if exc.errno == errno.EPIPE:
            return False
        raise OutputWriteError(f"could not write {stream_name}: {exc!r}") from exc
    except ValueError as exc:
        setattr(sys, stream_name, None)
        raise OutputWriteError(f"could not write {stream_name}: {exc!r}") from exc
    return True


def emit_stdout(text: str) -> bool:
    """Write one stdout line, returning false when its receiver disappeared."""
    return _emit("stdout", text)


def emit_stderr(text: str) -> bool:
    """Write one stderr line, returning false when its receiver disappeared."""
    return _emit("stderr", text)
