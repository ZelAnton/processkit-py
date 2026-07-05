"""Property: `Command.output_limit()`'s boundary arithmetic.

Two layers:

- Pure builder validation (no real spawn — `output_limit()` only configures
  the `Command`): at least one of `max_bytes`/`max_lines` is required,
  `on_overflow` must be one of the three known labels, and a negative cap
  size is rejected by the `usize` conversion itself.
- The actual overflow arithmetic against a real child that prints a known
  number of lines (`python -c` echo, as the task explicitly allows for this
  surface) — `drop_oldest` keeps the tail, `drop_newest` keeps the head, and
  `error` raises `OutputTooLarge` carrying the exact counts. These spawn a
  real process per example, so they run under an explicit, small
  `max_examples` regardless of the active Hypothesis profile.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from processkit import Command, OutputTooLarge

from ..conftest import PY

_VALID_OVERFLOW = ("drop_oldest", "drop_newest", "error")
_CAP_SIZE = st.integers(min_value=0, max_value=10_000)


# --- pure builder validation (no spawn) --------------------------------------


def test_output_limit_requires_at_least_one_cap() -> None:
    for on_overflow in (*_VALID_OVERFLOW, "bogus"):
        try:
            Command("x").output_limit(on_overflow=on_overflow)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"output_limit(on_overflow={on_overflow!r}) needed a cap size")


@given(
    max_bytes=st.one_of(st.none(), _CAP_SIZE),
    max_lines=st.one_of(st.none(), _CAP_SIZE),
    on_overflow=st.sampled_from(_VALID_OVERFLOW),
)
def test_output_limit_accepts_any_cap_combination_with_a_known_overflow_label(
    max_bytes: int | None, max_lines: int | None, on_overflow: str
) -> None:
    if max_bytes is None and max_lines is None:
        try:
            Command("x").output_limit(
                max_bytes=max_bytes,
                max_lines=max_lines,
                on_overflow=on_overflow,  # type: ignore[arg-type]
            )
        except ValueError:
            pass
        else:
            raise AssertionError("output_limit() with no cap size should have raised ValueError")
    else:
        Command("x").output_limit(
            max_bytes=max_bytes,
            max_lines=max_lines,
            on_overflow=on_overflow,  # type: ignore[arg-type]
        )


@given(
    max_bytes=_CAP_SIZE,
    on_overflow=st.text(max_size=15).filter(lambda s: s not in _VALID_OVERFLOW),
)
def test_output_limit_rejects_unknown_overflow_label(max_bytes: int, on_overflow: str) -> None:
    try:
        Command("x").output_limit(max_bytes=max_bytes, on_overflow=on_overflow)  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        msg = f"output_limit(on_overflow={on_overflow!r}) should have raised ValueError"
        raise AssertionError(msg)


@given(negative=st.integers(min_value=-(2**63), max_value=-1))
def test_output_limit_rejects_negative_cap_sizes(negative: int) -> None:
    try:
        Command("x").output_limit(max_bytes=negative)
    except OverflowError:
        pass
    else:
        raise AssertionError(f"output_limit(max_bytes={negative}) should have raised OverflowError")
    try:
        Command("x").output_limit(max_lines=negative)
    except OverflowError:
        pass
    else:
        raise AssertionError(f"output_limit(max_lines={negative}) should have raised OverflowError")


# --- real-spawn overflow arithmetic -------------------------------------------

_ECHO_LINES = "import sys\nfor i in range({total}):\n    print(i)"


def _echo_command(total: int) -> Command:
    return Command(PY, ["-c", _ECHO_LINES.format(total=total)])


@settings(max_examples=8, deadline=None)
@given(total=st.integers(min_value=1, max_value=25), data=st.data())
def test_drop_oldest_keeps_the_most_recent_lines(total: int, data: st.DataObject) -> None:
    cap = data.draw(st.integers(min_value=1, max_value=total))
    result = _echo_command(total).output_limit(max_lines=cap).output()
    assert result.is_success
    expected = [str(i) for i in range(max(0, total - cap), total)]
    assert result.stdout.split("\n") == expected
    assert result.truncated == (cap < total)


@settings(max_examples=8, deadline=None)
@given(total=st.integers(min_value=1, max_value=25), data=st.data())
def test_drop_newest_keeps_the_earliest_lines(total: int, data: st.DataObject) -> None:
    cap = data.draw(st.integers(min_value=1, max_value=total))
    result = _echo_command(total).output_limit(max_lines=cap, on_overflow="drop_newest").output()
    assert result.is_success
    expected = [str(i) for i in range(min(cap, total))]
    assert result.stdout.split("\n") == expected
    assert result.truncated == (cap < total)


@settings(max_examples=8, deadline=None)
@given(total=st.integers(min_value=2, max_value=25), data=st.data())
def test_on_overflow_error_reports_exact_counts(total: int, data: st.DataObject) -> None:
    cap = data.draw(st.integers(min_value=1, max_value=total - 1))  # force an overflow
    try:
        _echo_command(total).output_limit(max_lines=cap, on_overflow="error").run()
    except OutputTooLarge as exc:
        assert exc.max_lines == cap
        assert exc.total_lines == total
    else:
        raise AssertionError("an overflowing cap with on_overflow='error' should have raised")


@settings(max_examples=8, deadline=None)
@given(total=st.integers(min_value=1, max_value=25))
def test_a_cap_at_or_above_the_total_never_truncates(total: int) -> None:
    result = _echo_command(total).output_limit(max_lines=total + 5).output()
    assert result.is_success
    assert not result.truncated
    assert result.stdout.split("\n") == [str(i) for i in range(total)]
