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
- **`test_pty.py`** — PTY/ConPTY merged-output relay with a bounded stream of
  fixed-width lines. It runs on POSIX and Windows hosts that provide ConPTY;
  other platforms skip it rather than producing incomparable numbers.
- **`test_lifecycle_events.py`** — the full `lifecycle_events()` stream over a
  mixed stdout/stderr workload, including the started and exited events.
- **`test_aoutput_as_completed.py`** — `aoutput_as_completed()` draining a
  bounded batch at fixed concurrency, measuring completion-order delivery and
  per-slot result handling.
- **`test_supervisor.py`** — a live `Supervisor`/`SupervisionSession` that
  restarts a bounded crash workload and waits for the restart policy to end.

The PTY benchmark uses the native pty implementation on POSIX.
Windows requires ConPTY (Windows 10 1809 or newer).
The weekly job runs on Ubuntu.
Do not compare its POSIX measurements directly with Windows ConPTY measurements.

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
- `--benchmark-json=out.json` provides machine-readable results for the weekly job's summary table.

## CI

The `bench` job in [`.github/workflows/nightly-hardening.yml`](../.github/workflows/nightly-hardening.yml) runs each Saturday at 03:17 UTC.
It shares the `schedule` and `workflow_dispatch` triggers with the `stress` job.
It does not run on pushes or pull requests.
Each run publishes a table in the job summary to show performance changes between runs.

### History and regression alerts

Each run's summary shows current measurements only.
A persistent history also reveals gradual regressions, such as a 20% increase across several changes.
The `bench` job passes each run's `benchmark.json` to [`benchmark-action/github-action-benchmark`][gh-action-benchmark].
The action adds a point to `dev/bench/data.js` on the orphan `gh-pages` branch.
The chart is in `dev/bench/index.html` on that branch.

The `gh-pages` branch stores benchmark data and does not serve a live site.
The repository's GitHub Pages site publishes the mdBook documentation through `.github/workflows/docs.yml`.
A repository permits only one Pages source at a time.
To examine the trend:

- `git fetch origin gh-pages && git show gh-pages:dev/bench/data.js` for the
  raw JSON history, or
- `git worktree add ../bench-history gh-pages` and open
  `dev/bench/index.html` in a browser locally for the chart view.

**Regression alert.** Each run compares the mean time with the previous run.
At 130% or more, `github-action-benchmark` adds a comment to the tested commit.
This threshold represents an increase of at least 30%.
The alert does not fail the job (`fail-on-alert: false`) or block pull requests.

The threshold exceeds normal noise from shared GitHub runners.
Smaller regressions across several runs can remain below this threshold.
Review the chart periodically to find those gradual changes.

**When an alert appears:** read the commit comment.
It identifies the affected benchmarks and compares their results.
Use the chart to distinguish a regression from a single noisy run.
If the regression appears real, open a task to investigate.
The alert provides information and does not block checks.

[gh-action-benchmark]: https://github.com/benchmark-action/github-action-benchmark
