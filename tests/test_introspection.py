"""Spawn-free pid and containment capability introspection."""

from __future__ import annotations

import os

from processkit import (
    Command,
    HostContainment,
    MemberInfo,
    ProcessGroup,
    host_containment,
    process_info,
    process_is_alive,
)

from ._liveness import wait_until
from .conftest import PY


def test_process_lookup_tracks_a_live_then_finished_child() -> None:
    proc = Command(PY, ["-c", "import time; time.sleep(1)"]).start()
    pid = proc.pid
    assert pid is not None
    info = process_info(pid)
    assert isinstance(info, MemberInfo)
    assert info.pid == pid
    assert process_is_alive(pid)
    assert process_is_alive(pid, info.start_time)
    if info.start_time is not None:
        assert not process_is_alive(pid, info.start_time + 1)
    proc.outcome()
    # A cancel-safe Windows wait can retain a cloned process handle briefly after
    # reporting the outcome. Release the owner and wait for that handle to close.
    del proc
    assert wait_until(lambda: process_info(pid) is None, timeout=5.0)
    assert not process_is_alive(pid, info.start_time)


def test_process_lookup_reports_a_nonexistent_pid() -> None:
    assert process_info(0xFFFFFFFF) is None
    assert not process_is_alive(0xFFFFFFFF)


def test_process_info_agrees_with_group_membership() -> None:
    with ProcessGroup() as group:
        proc = group.start(Command(PY, ["-c", "import time; time.sleep(1)"]))
        pid = proc.pid
        assert pid is not None
        members = group.members()
        assert pid in members
        info = process_info(pid)
        assert info is not None
        assert info.pid in members
        assert any(member.pid == info.pid for member in group.members_info())


def test_host_containment_matches_a_real_group() -> None:
    report = host_containment()
    assert isinstance(report, HostContainment)
    assert report.mechanism in {"job_object", "cgroup_v2", "process_group"}
    assert report.soft_stop_scope in {"whole_tree", "opt_in_members", "none"}
    assert report.parent_death_cleanup in {"whole_tree", "direct_child_only", "none"}
    assert report.crate_version == "3.3.0"
    assert "HostContainment(" in repr(report)

    with ProcessGroup() as group:
        assert group.mechanism == report.mechanism
        assert group.soft_stop_scope in {"whole_tree", "opt_in_members", "none"}
        if os.name != "nt":
            assert group.soft_stop_scope == report.soft_stop_scope == "whole_tree"

    parent_scope = Command.kill_on_parent_death_scope()
    assert report.parent_death_cleanup == (
        "none" if parent_scope == "unsupported" else parent_scope
    )
