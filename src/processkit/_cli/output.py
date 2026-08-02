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
    # `sys.stdout`/`sys.stderr` are block-buffered whenever redirected into a
    # pipe rather than a terminal (see `_flush_std_streams`'s own docstring),
    # so without this the streaming re-emitters (`run --idle-timeout` /
    # `--output-limit` / `--pty`, see `_drive_streaming`) only deliver lines to
    # a piped caller in ~8 KiB chunks or at final process exit, defeating the
    # documented "live" behavior. Flush per line instead, treating a flush
    # failure exactly like a write failure above — the destination went away
    # or refused output either way.
    try:
        stream.flush()
    except BrokenPipeError:
        setattr(sys, stream_name, None)
        return False
    except OSError as exc:
        setattr(sys, stream_name, None)
        if exc.errno == errno.EPIPE:
            return False
        raise OutputWriteError(f"could not flush {stream_name}: {exc!r}") from exc
    except ValueError as exc:
        setattr(sys, stream_name, None)
        raise OutputWriteError(f"could not flush {stream_name}: {exc!r}") from exc
    return True


def emit_stdout(text: str) -> bool:
    """Write one stdout line, returning false when its receiver disappeared."""
    return _emit("stdout", text)


def emit_stderr(text: str) -> bool:
    """Write one stderr line, returning false when its receiver disappeared."""
    return _emit("stderr", text)
