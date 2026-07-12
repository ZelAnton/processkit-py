"""Property: numeric kwarg validation across the surfaces that share the
`convert.rs` helpers (`positive_duration` / `nonnegative_duration`) or a
hand-rolled finite-range check — `Command.timeout()`/`.timeout_grace()`/
`.retry()`, `Supervisor`'s backoff/storm knobs, `Command.success_codes()`, and
`output_all`'s `concurrency=`.

None of these constructions spawn a real process: a `Command`/`Supervisor` is
only a builder until `.run()`/`.output()`/... is called, and `output_all([])`
with an empty command list has nothing to run.
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from processkit import Command, Supervisor, output_all, output_all_bytes

# --- shared strategies -------------------------------------------------------

# Safely within `Duration`'s range (~5.8e11 years in seconds) — never trips the
# "value too big to convert to Duration" branch, only the sign/finiteness check.
_finite_positive = st.floats(min_value=1e-9, max_value=1e12, allow_nan=False, allow_infinity=False)
_nonpositive_finite = st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)
_nonfinite = st.sampled_from([math.nan, math.inf, -math.inf])
_invalid_shape = st.one_of(_nonpositive_finite, _nonfinite)
# Comfortably past `Duration::MAX.as_secs_f64()` but still a finite `f64`.
_overflowing = st.floats(min_value=1e250, max_value=1.5e308, allow_nan=False, allow_infinity=False)

_u32_valid = st.integers(min_value=0, max_value=2**32 - 1)
_u32_negative = st.integers(min_value=-(2**63), max_value=-1)
_u32_too_big = st.integers(min_value=2**32, max_value=2**64)

_i32_valid = st.integers(min_value=-(2**31), max_value=2**31 - 1)
_i32_too_big = st.integers(min_value=2**31, max_value=2**63)


# --- Command.timeout() / Command.timeout_grace() ----------------------------


@given(seconds=_finite_positive)
def test_timeout_accepts_finite_positive(seconds: float) -> None:
    Command("x").timeout(seconds)


@given(seconds=st.one_of(_invalid_shape, _overflowing))
def test_timeout_rejects_nonpositive_nonfinite_or_overflowing(seconds: float) -> None:
    try:
        Command("x").timeout(seconds)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Command.timeout({seconds!r}) should have raised ValueError")


@given(seconds=st.one_of(st.just(0.0), _finite_positive))
def test_timeout_grace_accepts_nonnegative(seconds: float) -> None:
    # Unlike `timeout()`, zero is a valid grace window ("kill immediately").
    Command("x").timeout_grace(seconds)


@given(seconds=st.one_of(_nonpositive_finite.filter(lambda s: s != 0.0), _nonfinite, _overflowing))
def test_timeout_grace_rejects_negative_nonfinite_or_overflowing(seconds: float) -> None:
    try:
        Command("x").timeout_grace(seconds)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Command.timeout_grace({seconds!r}) should have raised ValueError")


# --- Command.retry()'s backoff knobs -----------------------------------------


@given(
    initial_backoff=st.one_of(st.just(0.0), _finite_positive),
    max_backoff=st.one_of(st.just(0.0), _finite_positive),
)
def test_retry_backoff_knobs_accept_nonnegative(initial_backoff: float, max_backoff: float) -> None:
    Command("x").retry("transient", initial_backoff=initial_backoff, max_backoff=max_backoff)


@given(seconds=st.one_of(_nonpositive_finite.filter(lambda s: s != 0.0), _nonfinite, _overflowing))
def test_retry_initial_backoff_rejects_negative_nonfinite_or_overflowing(seconds: float) -> None:
    try:
        Command("x").retry("transient", initial_backoff=seconds)
    except ValueError:
        pass
    else:
        raise AssertionError(f"retry(initial_backoff={seconds!r}) should have raised ValueError")


@given(name=st.text(max_size=15).filter(lambda s: s.lower() not in ("transient", "transient_or_timeout")))
def test_retry_rejects_unknown_retry_if_preset(name: str) -> None:
    try:
        Command("x").retry(name)  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError(f"retry({name!r}) should have raised ValueError")


# --- Command.success_codes() -------------------------------------------------


@given(codes=st.lists(_i32_valid, min_size=1, max_size=10))
def test_success_codes_accepts_any_nonempty_i32_list(codes: list[int]) -> None:
    Command("x").success_codes(codes)


def test_success_codes_rejects_empty_list() -> None:
    try:
        Command("x").success_codes([])
    except ValueError:
        pass
    else:
        raise AssertionError("success_codes([]) should have raised ValueError")


@given(code=_i32_too_big)
def test_success_codes_rejects_i32_overflow(code: int) -> None:
    try:
        Command("x").success_codes([code])
    except OverflowError:
        pass
    else:
        raise AssertionError(f"success_codes([{code}]) should have raised OverflowError")


# --- Supervisor's backoff / storm-guard knobs --------------------------------


@given(seconds=_finite_positive)
def test_supervisor_backoff_initial_accepts_positive(seconds: float) -> None:
    Supervisor(Command("x"), backoff_initial=seconds)


@given(seconds=st.one_of(_invalid_shape, _overflowing))
def test_supervisor_backoff_initial_rejects_nonpositive_or_overflowing(seconds: float) -> None:
    try:
        Supervisor(Command("x"), backoff_initial=seconds)
    except ValueError:
        pass
    else:
        msg = f"Supervisor(backoff_initial={seconds!r}) should have raised ValueError"
        raise AssertionError(msg)


@given(factor=st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_supervisor_backoff_factor_accepts_at_least_one(factor: float) -> None:
    Supervisor(Command("x"), backoff_factor=factor)


@given(
    factor=st.one_of(
        st.floats(max_value=1.0, exclude_max=True, allow_nan=False, allow_infinity=False),
        _nonfinite,
    )
)
def test_supervisor_backoff_factor_rejects_below_one_or_nonfinite(factor: float) -> None:
    try:
        Supervisor(Command("x"), backoff_factor=factor)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Supervisor(backoff_factor={factor!r}) should have raised ValueError")


@given(threshold=_finite_positive)
def test_supervisor_failure_threshold_accepts_positive(threshold: float) -> None:
    Supervisor(Command("x"), storm_pause=0.01, failure_threshold=threshold)


@given(threshold=st.one_of(_nonpositive_finite, _nonfinite))
def test_supervisor_failure_threshold_rejects_nonpositive_or_nonfinite(threshold: float) -> None:
    try:
        Supervisor(Command("x"), storm_pause=0.01, failure_threshold=threshold)
    except ValueError:
        pass
    else:
        raise AssertionError(
            f"Supervisor(failure_threshold={threshold!r}) should have raised ValueError"
        )


@given(seconds=st.one_of(st.just(0.0), _finite_positive))
def test_supervisor_failure_decay_accepts_nonnegative(seconds: float) -> None:
    # A zero half-life is a valid config (see test_supervisor.py's
    # `test_supervisor_zero_failure_decay_is_accepted`).
    Supervisor(Command("x"), failure_decay=seconds)


@given(seconds=st.one_of(_nonpositive_finite.filter(lambda s: s != 0.0), _nonfinite))
def test_supervisor_failure_decay_rejects_negative_or_nonfinite(seconds: float) -> None:
    try:
        Supervisor(Command("x"), failure_decay=seconds)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Supervisor(failure_decay={seconds!r}) should have raised ValueError")


@given(n=_u32_valid)
def test_supervisor_max_restarts_accepts_u32_range(n: int) -> None:
    Supervisor(Command("x"), max_restarts=n)


@given(n=st.one_of(_u32_negative, _u32_too_big))
def test_supervisor_max_restarts_rejects_outside_u32_range(n: int) -> None:
    try:
        Supervisor(Command("x"), max_restarts=n)
    except OverflowError:
        pass
    else:
        raise AssertionError(f"Supervisor(max_restarts={n}) should have raised OverflowError")


# --- output_all / output_all_bytes concurrency -------------------------------


@given(n=st.integers(min_value=1, max_value=2**32 - 1))
def test_output_all_accepts_positive_concurrency(n: int) -> None:
    # An empty command list spawns nothing — only `resolve_concurrency`'s
    # validation is under test.
    assert output_all([], concurrency=n) == []
    assert output_all_bytes([], concurrency=n) == []


def test_output_all_rejects_zero_concurrency() -> None:
    try:
        output_all([], concurrency=0)
    except ValueError:
        pass
    else:
        raise AssertionError("output_all(concurrency=0) should have raised ValueError")


@given(n=st.integers(min_value=-(2**63), max_value=-1))
def test_output_all_rejects_negative_concurrency(n: int) -> None:
    try:
        output_all([], concurrency=n)
    except OverflowError:
        pass
    else:
        raise AssertionError(f"output_all(concurrency={n}) should have raised OverflowError")
