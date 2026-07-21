"""Property: `wait_for_http`'s status-acceptance dispatch (`_status_predicate`
in `_aio.py`). A container is normalized to a membership test; a callable is
used as the predicate as-is.

No sockets here — the deadline/same-tick-race/cancellation machinery is covered
by `tests/test_readiness.py`; this pins only the *configurable status* contract
(the `expected_status` parameter) across arbitrary code sets, the piece a
container-vs-callable dispatch bug would silently break.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from processkit._aio import _status_predicate

_STATUS = st.integers(min_value=100, max_value=599)


@given(accepted=st.sets(_STATUS), code=_STATUS)
def test_container_predicate_matches_membership(accepted: set[int], code: int) -> None:
    predicate = _status_predicate(accepted)
    assert predicate(code) is (code in accepted)


@given(code=_STATUS)
def test_default_range_container_matches_2xx(code: int) -> None:
    # The default `expected_status=range(200, 300)` must accept exactly the 2xx
    # codes — a range is a container, so it flows through the same membership path.
    predicate = _status_predicate(range(200, 300))
    assert predicate(code) is (200 <= code < 300)


@given(code=_STATUS)
def test_callable_predicate_is_used_as_is(code: int) -> None:
    even = _status_predicate(lambda c: c % 2 == 0)
    assert even(code) is (code % 2 == 0)
