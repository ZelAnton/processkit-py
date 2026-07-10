"""Property: `parse_signal` (Rust `convert.rs`) over int/str inputs, exercised
through `Command.timeout_signal()` — the cheapest pure-builder call that routes
through it (no real spawn: `timeout_signal()` only configures the builder).

`parse_signal` picks a branch on the Python type and *validates* the result:

- A `bool` is rejected with `TypeError` **before** the number path — it is a
  Python `int` subtype, so `True`/`False` would otherwise slip through as raw
  signals `1`/`0`, and raw `0` is the POSIX existence probe that delivers nothing
  (a boolean-config typo must not become a silent no-op send).
- A non-`bool` `int` is a raw platform signal number. On POSIX it must be a real,
  deliverable signal (`1..=SIGRTMAX`): `0`, negatives, and out-of-range values
  raise `ValueError`. On Windows a raw number is never deliverable and raises
  `Unsupported` (only the named `"kill"` works there). An `int` wider than `i32`
  falls through to the `str` branch and fails there too, surfacing as `TypeError`.
- Anything else is a name string — one of `term`/`kill`/`int`/`hup`/`quit`/
  `usr1`/`usr2`, matched case-insensitively with an optional `sig` prefix, or
  `ValueError`.
"""

from __future__ import annotations

import sys

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from processkit import Command, Unsupported

_KNOWN_NAMES = ("term", "kill", "int", "hup", "quit", "usr1", "usr2")

# Signals 1..15 (SIGHUP..SIGTERM) exist and are deliverable on every POSIX
# platform (well inside SIGRTMAX, which is >= 31 everywhere) — a raw number this
# small is accepted on POSIX and rejected (Unsupported) on Windows.
_valid_posix_raw = st.integers(min_value=1, max_value=15)
# `0` (the existence probe) and negatives are real-but-not-deliverable numbers,
# rejected with ValueError on POSIX. Kept inside i32 so they reach the number
# branch rather than falling through to the str branch.
_zero_or_negative = st.integers(min_value=-(2**31), max_value=0)
# Comfortably above any real SIGRTMAX (64 on Linux, 31 on macOS) yet inside i32:
# out-of-range, rejected with ValueError on POSIX.
_out_of_range = st.integers(min_value=1000, max_value=2**31 - 1)
# Wider than i32 — the int branch declines it and the str branch can't take an
# int, so it surfaces as TypeError on every platform.
_outside_i32_range = st.one_of(
    st.integers(min_value=2**31, max_value=2**63),
    st.integers(min_value=-(2**63), max_value=-(2**31) - 1),
)


@given(raw=st.booleans())
def test_timeout_signal_rejects_bool(raw: bool) -> None:
    # `bool` is a Python `int` subtype, but is rejected before the number path on
    # every platform — a `False`/`True` typo must not silently mean raw signal
    # 0/1 (raw 0 delivers nothing).
    try:
        Command("x").timeout_signal(raw)
    except TypeError:
        pass
    else:
        raise AssertionError(f"timeout_signal({raw!r}) should have raised TypeError")


@pytest.mark.skipif(sys.platform == "win32", reason="raw signal numbers are POSIX-only")
@given(raw=_valid_posix_raw)
def test_timeout_signal_accepts_valid_raw_number_on_posix(raw: int) -> None:
    Command("x").timeout_signal(raw)


@pytest.mark.skipif(sys.platform == "win32", reason="raw signal numbers are POSIX-only")
@example(0)  # the POSIX existence probe — the headline silent-no-op case
@given(raw=_zero_or_negative)
def test_timeout_signal_rejects_zero_or_negative_on_posix(raw: int) -> None:
    try:
        Command("x").timeout_signal(raw)
    except ValueError:
        pass
    else:
        raise AssertionError(f"timeout_signal({raw}) should have raised ValueError")


@pytest.mark.skipif(sys.platform == "win32", reason="raw signal numbers are POSIX-only")
@given(raw=_out_of_range)
def test_timeout_signal_rejects_out_of_range_on_posix(raw: int) -> None:
    try:
        Command("x").timeout_signal(raw)
    except ValueError:
        pass
    else:
        raise AssertionError(f"timeout_signal({raw}) should have raised ValueError")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows has no POSIX signals")
@example(9)  # even a real POSIX signal number is undeliverable on Windows
@given(raw=st.integers(min_value=-(2**31), max_value=2**31 - 1))
def test_timeout_signal_rejects_raw_number_on_windows(raw: int) -> None:
    # A Job Object has no POSIX signals — any raw number is Unsupported, raised
    # from the builder call, not deferred to when the timeout fires. (`bool`
    # would be a TypeError instead, but `st.integers` never yields a bool.)
    try:
        Command("x").timeout_signal(raw)
    except Unsupported:
        pass
    else:
        raise AssertionError(f"timeout_signal({raw}) should have raised Unsupported")


@given(raw=_outside_i32_range)
def test_timeout_signal_rejects_int_outside_i32_range(raw: int) -> None:
    # Wider than i32: the int branch declines it and the str branch can't take an
    # int, so it surfaces as TypeError, not ValueError/Unsupported — on every
    # platform.
    try:
        Command("x").timeout_signal(raw)
    except TypeError:
        pass
    else:
        raise AssertionError(f"timeout_signal({raw}) should have raised TypeError")


@given(name=st.sampled_from(_KNOWN_NAMES), upper=st.booleans(), sig_prefix=st.booleans())
def test_timeout_signal_accepts_known_names_case_and_prefix_insensitively(
    name: str, upper: bool, sig_prefix: bool
) -> None:
    spelled = name.upper() if upper else name
    if sig_prefix:
        spelled = "SIG" + spelled if upper else "sig" + spelled
    Command("x").timeout_signal(spelled)  # type: ignore[arg-type]


@example("")
@example("sig")
@given(name=st.text(max_size=15))
def test_timeout_signal_rejects_unknown_name(name: str) -> None:
    # Strip a "sig" prefix (case-insensitively) the same way `parse_signal`
    # does, so a generated string that only *happens* to spell a known name
    # (e.g. "sigterm" itself, or oddities like "SigTerm") isn't mistaken for
    # an invalid one.
    key = name.lower()
    if key.startswith("sig"):
        key = key[3:]
    assume(key not in _KNOWN_NAMES)
    try:
        Command("x").timeout_signal(name)  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError(f"timeout_signal({name!r}) should have raised ValueError")
