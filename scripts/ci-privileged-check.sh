#!/usr/bin/env bash
#
# Runs INSIDE the privileged Docker test harness (compose.yaml's `test` service)
# as root, with a delegated cgroup v2. Invoked by the `test-privileged` job in
# .github/workflows/ci.yml via:
#
#   docker compose run --build --rm -v "$PWD/artifacts:/app/artifacts" test \
#       bash scripts/ci-privileged-check.sh
#
# It exercises the Linux path no other CI lane can reach: cgroup v2 resource-
# limit enforcement. `ProcessGroup(max_memory=..., ...)` only resolves to the
# `cgroup_v2` mechanism -- with the limits actually enforced by the kernel --
# when this process runs at the REAL cgroup-v2 hierarchy root (cgroup v2's "no
# internal processes" rule exempts only that one cgroup; see
# docs/platforms.md). Every other runner (including this container by
# default) sits a level or more below it, so the crate raises ResourceLimit /
# falls back to process_group there instead.
#
# Step 0 below re-parents this process into the real root -- compose.yaml's
# `cgroup: host` makes `/sys/fs/cgroup` this container's REAL (not
# namespace-virtualized) view of the host hierarchy, so migrating our own pid
# there is an ordinary, permitted `cgroup.procs` write (needs the
# `privileged: true` also set in compose.yaml). Without both of those compose
# settings this step fails outright, which is intentional: better a hard
# failure here than a silent fall-through to a lane that no longer exercises
# real enforcement.
#
# The root-only privilege-drop test (test_privilege_drop_args_actually_drop_
# privilege) is deliberately EXCLUDED from the pytest run below and exercised
# instead in the `test-root` service (no delegated cgroup v2 there): under the
# cgroup_v2 mechanism this process now has, a privilege-dropped Command tries
# to join its own (root-owned, auto-created) cgroup *after* the OS has already
# dropped to the unprivileged uid, which fails with EACCES -- a documented
# upstream limitation ("Linux cgroup caveat" on processkit-rs's
# `Command::uid()` doc comment), not something this workflow can paper over.
#
# Usage: bash scripts/ci-privileged-check.sh   (run from the repo root, as root)

set -euo pipefail

mkdir -p artifacts

echo "==> Re-parenting this process into the real cgroup-v2 hierarchy root"
echo "    before: $(cat /proc/self/cgroup)"
echo $$ > /sys/fs/cgroup/cgroup.procs
echo "    after:  $(cat /proc/self/cgroup)"
if [ "$(cat /proc/self/cgroup)" != "0::/" ]; then
  echo "::error::failed to re-parent into the real cgroup-v2 root -- is compose.yaml still" \
       "set to 'privileged: true' + 'cgroup: host' on the 'test' service?" >&2
  exit 1
fi

# 1. Explicit, hard guard: the mechanism must resolve to cgroup_v2 in this
#    container, with the requested limits actually accepted (not merely that
#    building a plain, limit-less ProcessGroup happens to report cgroup_v2 --
#    that only needs a cgroup v2 mount, not real delegation). Checked directly
#    here, rather than only inferred from the pytest run below (whose own
#    resource-limit tests deliberately tolerate an Unsupported/ResourceLimit
#    skip on platforms that cannot enforce limits at all), so a silent
#    fallback fails loud, not quiet.
echo "==> Verifying the containment mechanism resolves to cgroup_v2 (not a process_group fallback)"
uv run python -c "
from processkit import ProcessGroup

with ProcessGroup(max_processes=64, max_memory=512 * 1024 * 1024) as group:
    mechanism = group.mechanism
    assert mechanism == 'cgroup_v2', (
        f'expected the cgroup_v2 mechanism in this privileged root container, got '
        f'{mechanism!r} instead -- delegated cgroup v2 is unavailable (host cgroup '
        f'version / container cgroup namespace?), so resource-limit enforcement is '
        f'silently untested here'
    )
print(f'    mechanism confirmed: {mechanism}')
"

# 2. Run the suite as root (minus the privilege-drop test -- see header), with
#    a JUnit report the caller (outside this container, after it exits) can
#    inspect to confirm the gated tests actually ran and PASSED -- not merely
#    that nothing failed (a silent skip exits 0 too).
echo "==> Running the suite as root, delegated cgroup v2 active (JUnit: artifacts/privileged-junit.xml)"
uv run pytest \
  --deselect tests/test_command.py::test_privilege_drop_args_actually_drop_privilege \
  --junitxml=artifacts/privileged-junit.xml
