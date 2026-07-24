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

### History and regression alerts

A single night's numbers only catch a large jump, not a slow creep (e.g. the
bridge getting +20% pricier over a series of small edits) — the raw
per-run summary table above has no memory of previous nights. To fix that,
the `bench` job also feeds each run's `benchmark.json` into
[`benchmark-action/github-action-benchmark`][gh-action-benchmark], which
appends it as a new point in a persistent time series stored on this repo's
orphan `gh-pages` branch (`dev/bench/data.js`, plus a chart `index.html`
alongside it). That branch is a plain data store here, not a live site: it is
**not** wired up to GitHub Pages, since this repo's Pages site already
publishes the mdBook docs via `.github/workflows/docs.yml`'s Actions-based
deployment, and a repo can only have one Pages source at a time. To look at
the trend:

- `git fetch origin gh-pages && git show gh-pages:dev/bench/data.js` for the
  raw JSON history, or
- `git worktree add ../bench-history gh-pages` and open
  `dev/bench/index.html` in a browser locally for the chart view.

**Regression alert.** Each run is compared against the immediately preceding
one; if the mean time is 130% or more of the previous run's (i.e. at least
30% slower), `github-action-benchmark` leaves an informative-only commit
comment on the commit the nightly run checked out — it never fails the job
(`fail-on-alert: false`) and, like the rest of this workflow, never gates a
PR. The threshold is set above ordinary shared-GitHub-runner noise so a
single-night 130% alert is worth a look, while a smaller multi-night creep
(the "+20% over a series of edits" case above) stays below it by design and
is instead something to notice by periodically eyeballing the chart, not
something this per-run threshold catches automatically.

**What to do when it fires:** read the commit comment (it links the specific
benchmark(s) involved and their before/after numbers), then use the chart
above to tell a genuine regression from a one-off noisy run. If it looks
real, open a follow-up task to investigate — the alert itself is only a
pointer, never a blocking check.

[gh-action-benchmark]: https://github.com/benchmark-action/github-action-benchmark
