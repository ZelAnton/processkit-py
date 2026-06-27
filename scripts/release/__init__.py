"""Helper scripts for `.github/workflows/release.yml`.

Split out of the workflow's inline Python heredocs so the CHANGELOG.md and
Cargo.lock manipulation logic is unit-tested by the normal pytest suite
instead of only ever exercised by an actual release run. Each module is both
importable (for tests) and runnable as a CLI (invoked from the workflow).
"""
