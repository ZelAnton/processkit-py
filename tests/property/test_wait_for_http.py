"""Property: `wait_for_http`'s status-acceptance dispatch (`_status_predicate`
in `_aio.py`), its ``Host``-header formatting (`_format_host_header`), and its
``path`` validation (`_check_http_path`). A container is normalized to a
membership test; a callable is used as the predicate as-is; an IPv6 literal
host is bracketed per RFC 9112/3986; a ``path`` with whitespace/control
characters or a non-latin-1 character is rejected.

No sockets here — the deadline/same-tick-race/cancellation machinery is covered
by `tests/test_readiness.py`; this pins only the pure-function contracts (the
`expected_status` dispatch, the `Host` header, and the `path` guard) across
arbitrary inputs, the pieces a dispatch/formatting/validation bug would
silently break.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from processkit._aio import (
    _build_http_request,
    _check_http_path,
    _format_host_header,
    _status_predicate,
)

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


@given(address=st.ip_addresses(v=6), port=st.integers(min_value=0, max_value=65535))
def test_format_host_header_brackets_ipv6_literals(address: object, port: int) -> None:
    # Any IPv6 literal -- across the whole address space, not just "::1" --
    # must come back bracketed with the port appended outside the brackets,
    # per RFC 9112/3986 (`Host: [<addr>]:<port>`, never the ambiguous
    # `Host: <addr>:<port>` a bare colon-separated literal would otherwise
    # produce).
    host = str(address)
    assert _format_host_header(host, port) == f"[{host}]:{port}"


@given(address=st.ip_addresses(v=4), port=st.integers(min_value=0, max_value=65535))
def test_format_host_header_leaves_ipv4_literals_unbracketed(address: object, port: int) -> None:
    host = str(address)
    assert _format_host_header(host, port) == f"{host}:{port}"


@given(
    name=st.sampled_from(["localhost", "example.com", "api.example.org", "my-host-01"]),
    port=st.integers(min_value=0, max_value=65535),
)
def test_format_host_header_leaves_dns_names_unbracketed(name: str, port: int) -> None:
    assert _format_host_header(name, port) == f"{name}:{port}"


@given(
    prefix=st.text(
        alphabet=st.characters(exclude_categories=("Cc", "Cs"), min_codepoint=33), max_size=8
    ),
    bad_char=st.sampled_from(["\r", "\n", " ", "\t", "\x00", "\x1f", "\x7f"]),
    suffix=st.text(
        alphabet=st.characters(exclude_categories=("Cc", "Cs"), min_codepoint=33), max_size=8
    ),
)
def test_check_http_path_rejects_whitespace_and_control_chars(
    prefix: str, bad_char: str, suffix: str
) -> None:
    path = f"/{prefix}{bad_char}{suffix}"
    with pytest.raises(ValueError, match="whitespace or control characters"):
        _check_http_path(path)


@given(
    path=st.text(
        alphabet=st.characters(exclude_categories=("Cc", "Cs"), min_codepoint=33, max_codepoint=126)
    )
)
def test_check_http_path_accepts_printable_ascii(path: str) -> None:
    # Never raises for a path built purely from printable, non-control ASCII
    # (the class of values `wait_for_http`'s existing tests already rely on).
    _check_http_path(path)


@given(
    char=st.characters(
        min_codepoint=0x100, max_codepoint=0x10FFFF, exclude_categories=("Cs", "Cn")
    ),
    in_path=st.booleans(),
)
def test_build_http_request_rejects_non_latin1_characters(char: str, in_path: bool) -> None:
    # A `host`/`path` character outside latin-1 (U+0100 and beyond) must raise
    # `ValueError` -- the encode-time guard around `.encode("latin-1")` -- never
    # a raw `UnicodeEncodeError` escaping to the caller.
    host = f"example{char}.test" if not in_path else "example.test"
    path = f"/{char}" if in_path else "/"
    with pytest.raises(ValueError, match="latin-1"):
        _build_http_request(host, 8080, path)
