"""Property: `parse_signal` (Rust `convert.rs`) over int/str inputs, exercised
through `Command.timeout_signal()` — the cheapest pure-builder call that routes
through it (no real spawn: `timeout_signal()` only configures the builder).

`parse_signal` takes either branch based on the Python type: an `int` (Python
`bool` included, since `bool` is an `int` subtype) is a raw platform signal
number, in `i32` range; anything else is extracted as a `str` name — one of
`term`/`kill`/`int`/`hup`/`quit`/`usr1`/`usr2`, matched case-insensitively and
with an optional `sig` prefix stripped, or `ValueError`.
"""

from __future__ import annotations

from hypothesis import assume, example, given
from hypothesis import strategies as st

from processkit import Command

_KNOWN_NAMES = ("term", "kill", "int", "hup", "quit", "usr1", "usr2")

# The `int` branch is tried first and only succeeds within `i32` range —
# anything wider falls through to the `str` branch and fails there too
# (`int` is not a `str`), surfacing as `TypeError`, not `ValueError`.
_i32_range = st.integers(min_value=-(2**31), max_value=2**31 - 1)
_outside_i32_range = st.one_of(
    st.integers(min_value=2**31, max_value=2**63),
    st.integers(min_value=-(2**63), max_value=-(2**31) - 1),
)


@given(raw=_i32_range)
def test_timeout_signal_accepts_any_i32_raw_number(raw: int) -> None:
    Command("x").timeout_signal(raw)


@given(raw=st.booleans())
def test_timeout_signal_accepts_bool_as_a_raw_int(raw: bool) -> None:
    # `bool` is a Python `int` subtype — `True`/`False` take the int branch
    # (raw signal 1 / 0), not the str branch.
    Command("x").timeout_signal(raw)


@given(raw=_outside_i32_range)
def test_timeout_signal_rejects_int_outside_i32_range(raw: int) -> None:
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
