window.BENCHMARK_DATA = {
  "lastUpdate": 1786178231309,
  "repoUrl": "https://github.com/ZelAnton/processkit-py",
  "entries": {
    "processkit benchmarks": [
      {
        "commit": {
          "author": {
            "name": "Anton Zhelezniakou",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "committer": {
            "name": "Anton Zhelezniakou",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "91b315ed479e88bfa4ffe1ee85a8632c8ff3f1d0",
          "message": "Fix Nightly benchmark branch bootstrap cleanup",
          "timestamp": "2026-08-08T07:51:34Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/91b315ed479e88bfa4ffe1ee85a8632c8ff3f1d0"
        },
        "date": 1786178230150,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 10.905059753714808,
            "unit": "iter/sec",
            "range": "stddev: 0.004663055844123874",
            "extra": "mean: 91.70055209090901 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.73105689193531,
            "unit": "iter/sec",
            "range": "stddev: 0.004685053243842897",
            "extra": "mean: 53.38727044444309 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 63.463674171090474,
            "unit": "iter/sec",
            "range": "stddev: 0.0002981747802406985",
            "extra": "mean: 15.757045476190358 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 16.845224727585663,
            "unit": "iter/sec",
            "range": "stddev: 0.002018102342729392",
            "extra": "mean: 59.36400470587992 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.3014632760719405,
            "unit": "iter/sec",
            "range": "stddev: 0.00236893100079932",
            "extra": "mean: 302.8959937999957 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 60.755174173983484,
            "unit": "iter/sec",
            "range": "stddev: 0.0009855563662859012",
            "extra": "mean: 16.459503467742817 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 16.705504573622274,
            "unit": "iter/sec",
            "range": "stddev: 0.0008701237562001735",
            "extra": "mean: 59.86050858822811 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.312473376740546,
            "unit": "iter/sec",
            "range": "stddev: 0.0014320171834306928",
            "extra": "mean: 301.8892187999995 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 64.40694580239065,
            "unit": "iter/sec",
            "range": "stddev: 0.0003161214137762711",
            "extra": "mean: 15.526275738460527 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 45.18524963001243,
            "unit": "iter/sec",
            "range": "stddev: 0.00038277816307506415",
            "extra": "mean: 22.131115976745463 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 63.38329633157181,
            "unit": "iter/sec",
            "range": "stddev: 0.0003445315625555599",
            "extra": "mean: 15.777027353843867 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 64.81839878837809,
            "unit": "iter/sec",
            "range": "stddev: 0.0003510006998991245",
            "extra": "mean: 15.427718343750563 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 63.22094192314808,
            "unit": "iter/sec",
            "range": "stddev: 0.0003105340721139191",
            "extra": "mean: 15.817543516128067 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.6526447159609465,
            "unit": "iter/sec",
            "range": "stddev: 0.04675388977741441",
            "extra": "mean: 376.9822599999941 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.115209643076396,
            "unit": "iter/sec",
            "range": "stddev: 0.0007591328889209631",
            "extra": "mean: 123.22540562499995 msec\nrounds: 8"
          }
        ]
      }
    ]
  }
}