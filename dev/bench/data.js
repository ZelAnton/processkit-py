window.BENCHMARK_DATA = {
  "lastUpdate": 1786683709459,
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
      },
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
          "id": "8c00eeb330617711cfc87d446a23228444437121",
          "message": "Make Nightly orphan stress PID-reuse safe",
          "timestamp": "2026-08-08T08:47:02Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/8c00eeb330617711cfc87d446a23228444437121"
        },
        "date": 1786179939017,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.581748781118742,
            "unit": "iter/sec",
            "range": "stddev: 0.002580194345320039",
            "extra": "mean: 86.34274658333634 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.11216128319377,
            "unit": "iter/sec",
            "range": "stddev: 0.005293779547854988",
            "extra": "mean: 52.32270621739402 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.98024529380588,
            "unit": "iter/sec",
            "range": "stddev: 0.00019662215504214454",
            "extra": "mean: 14.710155805970832 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.93326357765737,
            "unit": "iter/sec",
            "range": "stddev: 0.0008021504715128131",
            "extra": "mean: 55.76229868421029 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4250889476590265,
            "unit": "iter/sec",
            "range": "stddev: 0.003009099555967562",
            "extra": "mean: 291.9632206000017 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 65.89666220177553,
            "unit": "iter/sec",
            "range": "stddev: 0.000363036541535239",
            "extra": "mean: 15.175275447760933 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.44265668898707,
            "unit": "iter/sec",
            "range": "stddev: 0.0015535915922293784",
            "extra": "mean: 57.330716176474375 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4073857293670122,
            "unit": "iter/sec",
            "range": "stddev: 0.0023569165593907582",
            "extra": "mean: 293.4801279999988 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 65.51186522545964,
            "unit": "iter/sec",
            "range": "stddev: 0.00047063249355631573",
            "extra": "mean: 15.264410447763797 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 44.72519631285731,
            "unit": "iter/sec",
            "range": "stddev: 0.000612220270406253",
            "extra": "mean: 22.358761558136 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 63.03692706043613,
            "unit": "iter/sec",
            "range": "stddev: 0.00045147068469813536",
            "extra": "mean: 15.86371745312487 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 65.91788312162215,
            "unit": "iter/sec",
            "range": "stddev: 0.0006737221983738449",
            "extra": "mean: 15.170390076922594 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 64.6275113536856,
            "unit": "iter/sec",
            "range": "stddev: 0.0004972604325338901",
            "extra": "mean: 15.47328651612966 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.4344451205947824,
            "unit": "iter/sec",
            "range": "stddev: 0.018585632288115782",
            "extra": "mean: 410.771223200004 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.049222498097654,
            "unit": "iter/sec",
            "range": "stddev: 0.0014159156642035273",
            "extra": "mean: 124.23560166666272 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "cdc7c3ab78b0346f3d447aa7ce0e1b0181221e28",
          "message": "Gate async completion-order test without timing",
          "timestamp": "2026-08-08T09:29:45Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/cdc7c3ab78b0346f3d447aa7ce0e1b0181221e28"
        },
        "date": 1786182140833,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.798078157564266,
            "unit": "iter/sec",
            "range": "stddev: 0.003164347203095612",
            "extra": "mean: 84.75956733333352 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.081460269808407,
            "unit": "iter/sec",
            "range": "stddev: 0.005836189817785043",
            "extra": "mean: 52.40689055555395 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.87217206240675,
            "unit": "iter/sec",
            "range": "stddev: 0.0013374015410615111",
            "extra": "mean: 14.733578867647335 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.87611701128186,
            "unit": "iter/sec",
            "range": "stddev: 0.00132119745839694",
            "extra": "mean: 55.94056021052483 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.43326063401659,
            "unit": "iter/sec",
            "range": "stddev: 0.0021822414161417024",
            "extra": "mean: 291.268303399994 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 66.4934721942865,
            "unit": "iter/sec",
            "range": "stddev: 0.0005195232635530514",
            "extra": "mean: 15.039070257575236 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.64814945731007,
            "unit": "iter/sec",
            "range": "stddev: 0.0010132609563626772",
            "extra": "mean: 56.66316473684375 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.356514363590057,
            "unit": "iter/sec",
            "range": "stddev: 0.0032913401465276145",
            "extra": "mean: 297.9281157999935 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 67.93899497243942,
            "unit": "iter/sec",
            "range": "stddev: 0.0002432781678739947",
            "extra": "mean: 14.719087328354895 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 46.35591055626247,
            "unit": "iter/sec",
            "range": "stddev: 0.0007671479654747123",
            "extra": "mean: 21.572222139532638 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 65.63187425516324,
            "unit": "iter/sec",
            "range": "stddev: 0.00030414227030697047",
            "extra": "mean: 15.236499206349123 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 69.55185476942313,
            "unit": "iter/sec",
            "range": "stddev: 0.0002358545869333848",
            "extra": "mean: 14.377761791043234 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.0841530578164,
            "unit": "iter/sec",
            "range": "stddev: 0.00020975010010706538",
            "extra": "mean: 14.687705656715886 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.5509138359288572,
            "unit": "iter/sec",
            "range": "stddev: 0.042315553140000975",
            "extra": "mean: 392.0163769999988 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.406026894881416,
            "unit": "iter/sec",
            "range": "stddev: 0.0012640904460530168",
            "extra": "mean: 118.96226511110955 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786250220124,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.064083525832476,
            "unit": "iter/sec",
            "range": "stddev: 0.004255186431074822",
            "extra": "mean: 90.38254254545305 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.210005688149042,
            "unit": "iter/sec",
            "range": "stddev: 0.005121821139491129",
            "extra": "mean: 52.05620530434908 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 68.91706868188807,
            "unit": "iter/sec",
            "range": "stddev: 0.000270021677023878",
            "extra": "mean: 14.510193470588044 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.885636845102013,
            "unit": "iter/sec",
            "range": "stddev: 0.0013859180825894484",
            "extra": "mean: 55.910785210527756 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4422411693686144,
            "unit": "iter/sec",
            "range": "stddev: 0.0014330512795218415",
            "extra": "mean: 290.50840740000297 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 67.78026704805423,
            "unit": "iter/sec",
            "range": "stddev: 0.0002787343578528365",
            "extra": "mean: 14.753556507693151 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.58926320564918,
            "unit": "iter/sec",
            "range": "stddev: 0.0013303631191216888",
            "extra": "mean: 56.85286463157979 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.425116321539938,
            "unit": "iter/sec",
            "range": "stddev: 0.001115685506791583",
            "extra": "mean: 291.9608871999998 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 67.73075973179888,
            "unit": "iter/sec",
            "range": "stddev: 0.00036184334207277385",
            "extra": "mean: 14.764340514705765 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 46.6880184739431,
            "unit": "iter/sec",
            "range": "stddev: 0.0007700406751079373",
            "extra": "mean: 21.418771511112784 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 68.46544548447442,
            "unit": "iter/sec",
            "range": "stddev: 0.00025276613173431586",
            "extra": "mean: 14.605908030303627 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.13414652060574,
            "unit": "iter/sec",
            "range": "stddev: 0.00017063601013154488",
            "extra": "mean: 14.258389808824369 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 67.76520673897475,
            "unit": "iter/sec",
            "range": "stddev: 0.0003254783276683865",
            "extra": "mean: 14.756835375001609 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.4315834578175823,
            "unit": "iter/sec",
            "range": "stddev: 0.028768087871787074",
            "extra": "mean: 411.25464839998926 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.578538717588964,
            "unit": "iter/sec",
            "range": "stddev: 0.0008953559314316895",
            "extra": "mean: 116.56996988888737 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786337640144,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 10.242367445392711,
            "unit": "iter/sec",
            "range": "stddev: 0.013965322335397457",
            "extra": "mean: 97.63367750000285 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.636724024644273,
            "unit": "iter/sec",
            "range": "stddev: 0.005799176693702032",
            "extra": "mean: 50.924991294117625 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.65257552578075,
            "unit": "iter/sec",
            "range": "stddev: 0.00024604656623753335",
            "extra": "mean: 14.781403253730145 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.620999231419113,
            "unit": "iter/sec",
            "range": "stddev: 0.001953876074718106",
            "extra": "mean: 56.75047066666631 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.404832115675359,
            "unit": "iter/sec",
            "range": "stddev: 0.0018924714905079684",
            "extra": "mean: 293.70023719999097 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 68.11176299492635,
            "unit": "iter/sec",
            "range": "stddev: 0.00029621086836233916",
            "extra": "mean: 14.681751815387456 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.730932479047837,
            "unit": "iter/sec",
            "range": "stddev: 0.0016505426623058383",
            "extra": "mean: 56.39861305555548 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.443391406609236,
            "unit": "iter/sec",
            "range": "stddev: 0.004980964554196591",
            "extra": "mean: 290.4113653999957 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 69.5636675434851,
            "unit": "iter/sec",
            "range": "stddev: 0.00020891061182432303",
            "extra": "mean: 14.375320268657308 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 48.57807002045807,
            "unit": "iter/sec",
            "range": "stddev: 0.0004941916655955105",
            "extra": "mean: 20.585420531916192 msec\nrounds: 47"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 69.66005750473605,
            "unit": "iter/sec",
            "range": "stddev: 0.0002913057275362694",
            "extra": "mean: 14.355428861539657 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 71.00893753992354,
            "unit": "iter/sec",
            "range": "stddev: 0.0001358878153577122",
            "extra": "mean: 14.082734295774632 msec\nrounds: 71"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.95024910829129,
            "unit": "iter/sec",
            "range": "stddev: 0.0002657213267535142",
            "extra": "mean: 14.503210835822053 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.514856447821782,
            "unit": "iter/sec",
            "range": "stddev: 0.039015645278276834",
            "extra": "mean: 397.6370106000047 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.783618123559021,
            "unit": "iter/sec",
            "range": "stddev: 0.0007305036016874084",
            "extra": "mean: 113.8483009999997 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786423215483,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.45311423070249,
            "unit": "iter/sec",
            "range": "stddev: 0.004720621457200148",
            "extra": "mean: 87.31249683333193 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.627816514521626,
            "unit": "iter/sec",
            "range": "stddev: 0.004752292154714444",
            "extra": "mean: 50.94810211111107 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 69.71573248094904,
            "unit": "iter/sec",
            "range": "stddev: 0.00024347592493356092",
            "extra": "mean: 14.343964617645899 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.18706855355774,
            "unit": "iter/sec",
            "range": "stddev: 0.0013481347747122583",
            "extra": "mean: 54.984122210524184 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.459898905670601,
            "unit": "iter/sec",
            "range": "stddev: 0.0036505802071407",
            "extra": "mean: 289.0257857999984 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 67.44031760269178,
            "unit": "iter/sec",
            "range": "stddev: 0.00028036440538478267",
            "extra": "mean: 14.827925424243354 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.323597902477754,
            "unit": "iter/sec",
            "range": "stddev: 0.004334090136908636",
            "extra": "mean: 57.724729333331645 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4450068689166087,
            "unit": "iter/sec",
            "range": "stddev: 0.003087926127302041",
            "extra": "mean: 290.27518319999217 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 68.8328337864718,
            "unit": "iter/sec",
            "range": "stddev: 0.00038753427854032506",
            "extra": "mean: 14.527950470586859 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 49.174213469166766,
            "unit": "iter/sec",
            "range": "stddev: 0.00040685459969471273",
            "extra": "mean: 20.33586161224562 msec\nrounds: 49"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 69.49855942108898,
            "unit": "iter/sec",
            "range": "stddev: 0.00032037805604312626",
            "extra": "mean: 14.388787455881497 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.61623479376067,
            "unit": "iter/sec",
            "range": "stddev: 0.0000891390222069434",
            "extra": "mean: 14.16104955072393 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.69573536339796,
            "unit": "iter/sec",
            "range": "stddev: 0.0003741238514875515",
            "extra": "mean: 14.556944397058073 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.3551747499461535,
            "unit": "iter/sec",
            "range": "stddev: 0.010991637579556983",
            "extra": "mean: 424.5969434000017 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.81584909589042,
            "unit": "iter/sec",
            "range": "stddev: 0.000534779100109711",
            "extra": "mean: 113.43206866666516 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786510938284,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.432126863576807,
            "unit": "iter/sec",
            "range": "stddev: 0.002025340050373926",
            "extra": "mean: 87.47278716666784 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 20.30293632299238,
            "unit": "iter/sec",
            "range": "stddev: 0.004114508466199003",
            "extra": "mean: 49.25395933333713 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 68.943505314214,
            "unit": "iter/sec",
            "range": "stddev: 0.00022663273434479422",
            "extra": "mean: 14.504629485292957 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.03862121969605,
            "unit": "iter/sec",
            "range": "stddev: 0.0015090856282889422",
            "extra": "mean: 55.436609473684044 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4148237936613963,
            "unit": "iter/sec",
            "range": "stddev: 0.00320836034183524",
            "extra": "mean: 292.8408786000034 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 65.78993267915992,
            "unit": "iter/sec",
            "range": "stddev: 0.000404038709141969",
            "extra": "mean: 15.199893954546742 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.516703909385555,
            "unit": "iter/sec",
            "range": "stddev: 0.001176234750050715",
            "extra": "mean: 57.08836577777592 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.3953472940791944,
            "unit": "iter/sec",
            "range": "stddev: 0.002961274601321124",
            "extra": "mean: 294.5206818000031 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 67.22089548091245,
            "unit": "iter/sec",
            "range": "stddev: 0.0003876914173183503",
            "extra": "mean: 14.876326666667996 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 46.86938533739119,
            "unit": "iter/sec",
            "range": "stddev: 0.00039936858203290824",
            "extra": "mean: 21.335888934780325 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 65.84231427495483,
            "unit": "iter/sec",
            "range": "stddev: 0.0003522790892889755",
            "extra": "mean: 15.187801507462822 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 67.84908317089746,
            "unit": "iter/sec",
            "range": "stddev: 0.00038002250197182775",
            "extra": "mean: 14.738592671638788 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 67.00552842513771,
            "unit": "iter/sec",
            "range": "stddev: 0.0002673266419658283",
            "extra": "mean: 14.924141686566287 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.6681108987317113,
            "unit": "iter/sec",
            "range": "stddev: 0.03575100313369297",
            "extra": "mean: 374.7970148000036 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.547463689303372,
            "unit": "iter/sec",
            "range": "stddev: 0.0012025799998039027",
            "extra": "mean: 116.99376988888982 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786597442273,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 10.834361913180304,
            "unit": "iter/sec",
            "range": "stddev: 0.00993367676629454",
            "extra": "mean: 92.29892890909173 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.121196991922936,
            "unit": "iter/sec",
            "range": "stddev: 0.005451879463319609",
            "extra": "mean: 52.29798115789582 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 65.51251651048774,
            "unit": "iter/sec",
            "range": "stddev: 0.00036670417856474256",
            "extra": "mean: 15.264258698410895 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.168343008475667,
            "unit": "iter/sec",
            "range": "stddev: 0.0014198295329219837",
            "extra": "mean: 58.24673933333694 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.333985158548945,
            "unit": "iter/sec",
            "range": "stddev: 0.0029426647597925013",
            "extra": "mean: 299.94134720000716 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 64.52645883768602,
            "unit": "iter/sec",
            "range": "stddev: 0.00040353391591495643",
            "extra": "mean: 15.49751866153796 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 16.956223456608996,
            "unit": "iter/sec",
            "range": "stddev: 0.0019636614369285036",
            "extra": "mean: 58.97539641176596 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.360862462481651,
            "unit": "iter/sec",
            "range": "stddev: 0.0017845945295176472",
            "extra": "mean: 297.5426728000059 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 65.12501886565886,
            "unit": "iter/sec",
            "range": "stddev: 0.0002946272157220183",
            "extra": "mean: 15.355081924242036 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 45.16949527883588,
            "unit": "iter/sec",
            "range": "stddev: 0.0005728264131333994",
            "extra": "mean: 22.138834933330525 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 64.48923441288021,
            "unit": "iter/sec",
            "range": "stddev: 0.00017695701075243122",
            "extra": "mean: 15.50646412698417 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 68.37816860688116,
            "unit": "iter/sec",
            "range": "stddev: 0.00018757286974854033",
            "extra": "mean: 14.62455079411656 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 65.89446579578426,
            "unit": "iter/sec",
            "range": "stddev: 0.00040443206062115787",
            "extra": "mean: 15.175781272726809 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.5321949084710953,
            "unit": "iter/sec",
            "range": "stddev: 0.03676876470088709",
            "extra": "mean: 394.9143080000056 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.295396128792985,
            "unit": "iter/sec",
            "range": "stddev: 0.0007466403591569216",
            "extra": "mean: 120.54879411111428 msec\nrounds: 9"
          }
        ]
      },
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
          "id": "35ef455d6db759efa65390ef4841aa7be43b425e",
          "message": "Release v1.5.0",
          "timestamp": "2026-08-08T18:35:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/35ef455d6db759efa65390ef4841aa7be43b425e"
        },
        "date": 1786683707711,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 14.306880761043724,
            "unit": "iter/sec",
            "range": "stddev: 0.0028179722301282647",
            "extra": "mean: 69.89643771428534 msec\nrounds: 14"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 29.01651485485676,
            "unit": "iter/sec",
            "range": "stddev: 0.002111894227169247",
            "extra": "mean: 34.463132633332805 msec\nrounds: 30"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 77.0063423636712,
            "unit": "iter/sec",
            "range": "stddev: 0.0004954708789663286",
            "extra": "mean: 12.985943356163919 msec\nrounds: 73"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 22.612455615388132,
            "unit": "iter/sec",
            "range": "stddev: 0.0016317860537492768",
            "extra": "mean: 44.22341460869399 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 4.254132466830751,
            "unit": "iter/sec",
            "range": "stddev: 0.0101040297396081",
            "extra": "mean: 235.06555280000043 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 80.94484064039527,
            "unit": "iter/sec",
            "range": "stddev: 0.0005871660338085684",
            "extra": "mean: 12.3540918987362 msec\nrounds: 79"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 21.923877207070298,
            "unit": "iter/sec",
            "range": "stddev: 0.0020599528524491853",
            "extra": "mean: 45.61237004545469 msec\nrounds: 22"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 4.289817959893193,
            "unit": "iter/sec",
            "range": "stddev: 0.0031218024955068425",
            "extra": "mean: 233.11012480000386 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 80.71672444647167,
            "unit": "iter/sec",
            "range": "stddev: 0.00047597716792787754",
            "extra": "mean: 12.389006204818964 msec\nrounds: 83"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 55.44305375905031,
            "unit": "iter/sec",
            "range": "stddev: 0.0008533135707612489",
            "extra": "mean: 18.03652454545334 msec\nrounds: 55"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 78.9096231381882,
            "unit": "iter/sec",
            "range": "stddev: 0.0005016712699428019",
            "extra": "mean: 12.672725584416732 msec\nrounds: 77"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 81.55442581557442,
            "unit": "iter/sec",
            "range": "stddev: 0.0007470094578408598",
            "extra": "mean: 12.261750236110794 msec\nrounds: 72"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 80.85818866146873,
            "unit": "iter/sec",
            "range": "stddev: 0.0003581504890555776",
            "extra": "mean: 12.367331207315667 msec\nrounds: 82"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 4.302422961636109,
            "unit": "iter/sec",
            "range": "stddev: 0.002880953653468645",
            "extra": "mean: 232.42717160000552 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 10.252178816575995,
            "unit": "iter/sec",
            "range": "stddev: 0.0018970244621053943",
            "extra": "mean: 97.54024172726811 msec\nrounds: 11"
          }
        ]
      }
    ]
  }
}