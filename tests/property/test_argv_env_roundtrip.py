"""Property: arbitrary unicode argv/env round-trips through `Command` ->
`RecordingRunner` -> `Invocation` unmodified — no real process is ever
spawned (`RecordingRunner` only records what it was asked to run).

`Command`/`RecordingRunner`/`Invocation` are pure PyO3 <-> Rust conversions
(a `Vec<String>` / `HashMap<String, Option<String>>` under the hood) with no
OS boundary crossed here (unlike an actual spawn, where argv/env pass through
the platform's C-string/argv-encoding machinery) — so the round trip is
expected to be exact for *any* well-formed Python `str`, not just
shell/OS-safe ones. This is the "no real spawn" counterpart to
`test_runner_seam.py`'s example-based `Invocation` coverage.
"""

from __future__ import annotations

import sys

from hypothesis import assume, given
from hypothesis import strategies as st

from processkit import Command
from processkit.testing import RecordingRunner, Reply

# Any valid (surrogate-free, utf-8-safe — the `st.text()` default) unicode
# text is fair game for a program name / argv element / env value: nothing
# here touches an OS argv/env boundary, so there is no shell-quoting or
# C-string-NUL restriction to respect.
_text = st.text(max_size=40)
_program = st.text(min_size=1, max_size=20)
_args = st.lists(_text, max_size=8)
# Env var *names* exclude '=' (not a legal name on any platform) and are
# non-empty after stripping — an all-whitespace "name" is not a meaningful
# key to round-trip.
_env_key = st.text(
    # `codec="utf-8"` matches `st.text()`'s own default alphabet (surrogate-free,
    # utf-8-safe) — overriding `alphabet` without it would otherwise fall back to
    # `characters()`'s unrestricted default, which includes lone surrogates that
    # PyO3's str->Rust `String` conversion can't encode.
    alphabet=st.characters(codec="utf-8", exclude_characters="=\x00"),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")
_env = st.dictionaries(_env_key, _text, max_size=6)


@given(program=_program, args=_args, env=_env)
def test_argv_env_round_trip_through_invocation(
    program: str, args: list[str], env: dict[str, str]
) -> None:
    if sys.platform == "win32":
        # Windows env-var names fold case-insensitively (see
        # test_runner_seam.py::test_invocation_env_is_case_insensitive_on_windows) —
        # two generated keys differing only by case would collapse to one
        # `env()` override, breaking the 1:1 round-trip this property checks.
        assume(len({key.casefold() for key in env}) == len(env))

    command = Command(program, args)  # type: ignore[arg-type]  # list[str] vs invariant list[StrPath]
    for key, value in env.items():
        command = command.env(key, value)

    recorder = RecordingRunner.replying(Reply.ok(""))
    recorder.run(command)
    invocation = recorder.only_call()

    assert invocation.program == program
    assert invocation.args == args
    assert invocation.env == dict(env)
    for key, value in env.items():
        assert invocation.env_is(key, value)
        assert invocation.has_env(key)


@given(program=_program, key=_env_key, value=_text)
def test_env_remove_overrides_prior_env_call(program: str, key: str, value: str) -> None:
    # `env_remove` after `env(key, ...)` must win (last write wins) — the
    # removed key surfaces in `Invocation.env` as an explicit `None`, not a
    # leftover of the prior value and not simply absent.
    command = Command(program).env(key, value).env_remove(key)
    recorder = RecordingRunner.replying(Reply.ok(""))
    recorder.run(command)
    invocation = recorder.only_call()

    assert invocation.env == {key: None}
    # `has_env`/`env_is` answer "is there an override *value* set" — a removal
    # is present in `.env` (as `None`) but doesn't count as "having" one (see
    # test_runner_seam.py::test_invocation_env_is_and_has_env).
    assert not invocation.has_env(key)
    assert not invocation.env_is(key, value)


@given(program=_program, args=_args)
def test_command_program_and_arguments_accessors_match_the_build(
    program: str, args: list[str]
) -> None:
    # `Command.program` / `.arguments` are inspection accessors on the
    # builder itself, independent of any runner — pin them alongside the
    # `Invocation` round trip since both are meant to agree.
    command = Command(program, args)  # type: ignore[arg-type]  # list[str] vs invariant list[StrPath]
    assert command.program == program
    assert command.arguments == args
