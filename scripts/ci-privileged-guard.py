#!/usr/bin/env python3
"""Fail loud if any required test did not actually PASS in a JUnit report.

Guards the `test-privileged` CI job (see .github/workflows/ci.yml) against a
falsely-green run: a gated test that silently SKIPPED (its own
``skipif``/``pytest.skip()`` guard firing for an unexpected reason — wrong
euid, cgroup delegation unexpectedly unavailable, ...) still exits pytest with
status 0. This script inspects the JUnit XML pytest produced and requires each
listed test id to be present and PASSED (no <skipped>/<failure>/<error> child
element) -- run once per JUnit report, with the test ids that report is
expected to actually exercise.

Usage:
    python3 scripts/ci-privileged-guard.py <junit-xml-path> <test-id> [<test-id> ...]

Each <test-id> is an ordinary pytest node id, e.g.
``tests/test_command.py::test_privilege_drop_args_actually_drop_privilege``.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def node_id_to_classname_name(node_id: str) -> tuple[str, str]:
    """Convert a pytest node id to the (classname, name) junitxml uses.

    ``tests/test_command.py::test_foo`` -> ``("tests.test_command", "test_foo")``.
    """
    path, _, name = node_id.partition("::")
    if not name:
        raise ValueError(f"not a module-qualified test id (missing '::'): {node_id!r}")
    classname = path.removesuffix(".py").replace("/", ".").replace("\\", ".")
    return classname, name


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: ci-privileged-guard.py <junit-xml-path> <test-id> [<test-id> ...]",
            file=sys.stderr,
        )
        return 2

    junit_path, node_ids = argv[1], argv[2:]
    required = [node_id_to_classname_name(node_id) for node_id in node_ids]

    tree = ET.parse(junit_path)
    testcases = {
        (tc.get("classname"), tc.get("name")): tc for tc in tree.getroot().iter("testcase")
    }

    problems: list[str] = []
    for node_id, (classname, name) in zip(node_ids, required, strict=True):
        testcase = testcases.get((classname, name))
        if testcase is None:
            problems.append(f"{node_id} did not run at all (not collected?)")
            continue
        # A passing <testcase> has no child elements at all; <skipped>,
        # <failure>, and <error> are all outcomes we must reject here.
        outcome_tags = [child.tag for child in testcase]
        if outcome_tags:
            problems.append(
                f"{node_id} did not PASS (found {outcome_tags!r} -- likely skipped or "
                "failed instead of actually exercising the root/cgroup-v2-gated path)"
            )

    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1

    print(f"all {len(required)} required test(s) actually PASSED (not skipped) in {junit_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
