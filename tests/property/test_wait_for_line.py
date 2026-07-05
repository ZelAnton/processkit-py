"""Property: `wait_for_line` (pure-Python readiness helper, `_aio.py`) over a
plain async iterator — no real process involved (any async iterator works,
per its own docstring; a hand-rolled async generator exercises exactly the
same code path a `StdoutLines`/`OutputEvents` iterator would).

Covers both predicate forms: a `str` (substring match, `str`-yielding
iterators only) and an arbitrary callable predicate — and the "nothing
matched before the iterator ended" case, which surfaces as a plain
`ProcessError` (the stream-ended message), not `WaitTimeout` (that is
reserved for the wall-clock deadline elapsing while the scan is still
running — see `_aio.py`'s `wait_for_line` docstring).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from hypothesis import assume, given
from hypothesis import strategies as st

from processkit import ProcessError, wait_for_line

_LINE = st.text(max_size=15)
_LINES = st.lists(_LINE, max_size=12)


async def _aiter(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


@given(items=_LINES, data=st.data())
def test_callable_predicate_returns_the_first_match(items: list[str], data: st.DataObject) -> None:
    assume(items)
    target_index = data.draw(st.integers(min_value=0, max_value=len(items) - 1))
    target = items[target_index]
    first_index = items.index(target)  # the first occurrence, which may precede target_index

    async def scenario() -> str:
        return await wait_for_line(_aiter(items), lambda line: line == target, timeout=5.0)

    assert asyncio.run(scenario()) == items[first_index]


@given(items=_LINES, needle=st.text(max_size=5))
def test_str_predicate_matches_by_substring(items: list[str], needle: str) -> None:
    matches = [item for item in items if needle in item]

    async def scenario() -> str:
        return await wait_for_line(_aiter(items), needle, timeout=5.0)

    if matches:
        assert asyncio.run(scenario()) == matches[0]
    else:
        try:
            asyncio.run(scenario())
        except ProcessError as exc:
            assert not isinstance(exc, TimeoutError)
        else:
            raise AssertionError("wait_for_line should have raised when nothing matched")


@given(items=_LINES)
def test_predicate_matching_nothing_raises_process_error_not_timeout(items: list[str]) -> None:
    # A predicate that can never match exhausts the (finite) iterator well
    # before the deadline — the stream-ended `ProcessError`, not `WaitTimeout`.
    async def scenario() -> None:
        await wait_for_line(_aiter(items), lambda _line: False, timeout=5.0)

    try:
        asyncio.run(scenario())
    except ProcessError as exc:
        assert not isinstance(exc, TimeoutError)
    else:
        raise AssertionError("wait_for_line should have raised when nothing matched")
