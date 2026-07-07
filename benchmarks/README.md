# Benchmarks

`pytest-benchmark` timings for the questions [ROADMAP.md](../ROADMAP.md)'s
Phase 5 asks — "does the bridge add silly overhead?" — with a real number
attached instead of only the loose pass/fail bound in
`tests/test_hardening.py::test_no_silly_per_call_overhead`:

- **`test_spawn_capture.py`** — spawn + capture a single short-lived command:
  `processkit`'s `Command(...).output()` against the two stdlib "naive"
  equivalents, `subprocess.run(..., capture_output=True)` and
  `asyncio.create_subprocess_exec(...)` + `communicate()`. Same payload on
  all three, so the comparison is per-call overhead, not a differing
  workload.
- **`test_process_group.py`** — `ProcessGroup` start/exit: creating the
  group's kernel container, entering it, starting one short-lived child,
  tearing the whole tree down.
- **`test_streaming_throughput.py`** — `RunningProcess.stdout_lines()` (see
  [`docs/streaming.md`](../docs/streaming.md)) draining a known number of
  lines end to end.
- **`test_output_all.py`** — `output_all()` / `aoutput_all()` at 1/10/50-way
  concurrency (see [`docs/cookbook.md`](../docs/cookbook.md)).

## Running locally

This suite is **not** part of the PR gate — it lives in its own
`bench` dependency-group and is excluded from `testpaths` (`tests/` only), so
an ordinary `pytest`/`uv run pytest` never collects it. Install the group and
run it explicitly:

```console
uv sync --group bench
uv run pytest benchmarks/ --benchmark-only -p no:xdist -o addopts=""
```

`-p no:xdist -o addopts=""` disables `-n auto` (the repo's default
`addopts`) — `pytest-benchmark` needs to run in the main process, in a single
worker, to produce meaningful timings; under `pytest-xdist` it silently skips
measuring instead.

Useful extras:

- `--benchmark-only` skips the normal (non-benchmark) test collection outside
  this directory should it ever leak in; harmless here since `benchmarks/`
  has none, but keeps the invocation copy-pasteable elsewhere.
- `--benchmark-compare` / `--benchmark-autosave` — compare a run against a
  previously saved one, to check a change before landing it.
- `--benchmark-json=out.json` — machine-readable results (what the nightly
  CI job uses to render the job-summary table; see below).

## CI

The `bench` job in
[`.github/workflows/nightly-hardening.yml`](../.github/workflows/nightly-hardening.yml)
runs this suite on the same `schedule`/`workflow_dispatch` triggers as the
`stress` job — never on `push`/`pull_request` — and publishes the results as
a table in the job summary, so a regression shows up as a trend across nights
rather than only when someone happens to run this locally.
