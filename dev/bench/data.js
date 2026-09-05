window.BENCHMARK_DATA = {
  "lastUpdate": 1788594016186,
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1786766055037,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 13.798199429195714,
            "unit": "iter/sec",
            "range": "stddev: 0.0030022171623124184",
            "extra": "mean: 72.47322414286117 msec\nrounds: 14"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 25.66515400070293,
            "unit": "iter/sec",
            "range": "stddev: 0.002774608982386989",
            "extra": "mean: 38.96333526666591 msec\nrounds: 30"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 76.29758601660205,
            "unit": "iter/sec",
            "range": "stddev: 0.0009866194169448456",
            "extra": "mean: 13.106574561643457 msec\nrounds: 73"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 21.002160976399733,
            "unit": "iter/sec",
            "range": "stddev: 0.0014615039477501542",
            "extra": "mean: 47.614147949999364 msec\nrounds: 20"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 4.153503314736504,
            "unit": "iter/sec",
            "range": "stddev: 0.008066728698921872",
            "extra": "mean: 240.76061200000254 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 77.6938904286254,
            "unit": "iter/sec",
            "range": "stddev: 0.0007546766133745768",
            "extra": "mean: 12.871024922077552 msec\nrounds: 77"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 20.189318321358915,
            "unit": "iter/sec",
            "range": "stddev: 0.0017077329160398206",
            "extra": "mean: 49.53114236363634 msec\nrounds: 22"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.9653209713914945,
            "unit": "iter/sec",
            "range": "stddev: 0.009268661194830628",
            "extra": "mean: 252.18639479998618 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 81.35350901731356,
            "unit": "iter/sec",
            "range": "stddev: 0.0005461182693556913",
            "extra": "mean: 12.292032784808104 msec\nrounds: 79"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 58.20674324875733,
            "unit": "iter/sec",
            "range": "stddev: 0.0008616907877295395",
            "extra": "mean: 17.180140035086904 msec\nrounds: 57"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 77.87878751126352,
            "unit": "iter/sec",
            "range": "stddev: 0.00046136347419931963",
            "extra": "mean: 12.84046698666657 msec\nrounds: 75"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 81.67066577725544,
            "unit": "iter/sec",
            "range": "stddev: 0.0005847113404681317",
            "extra": "mean: 12.244298371796685 msec\nrounds: 78"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 80.07806787345343,
            "unit": "iter/sec",
            "range": "stddev: 0.000550069856236382",
            "extra": "mean: 12.487813786669903 msec\nrounds: 75"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.618035604732395,
            "unit": "iter/sec",
            "range": "stddev: 0.010212336615599275",
            "extra": "mean: 276.3930787999982 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 9.496179972157357,
            "unit": "iter/sec",
            "range": "stddev: 0.0015044019663693529",
            "extra": "mean: 105.30550210000058 msec\nrounds: 10"
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1786852775038,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.187631819436307,
            "unit": "iter/sec",
            "range": "stddev: 0.0032468433970847892",
            "extra": "mean: 89.38442166667453 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 23.043077139343424,
            "unit": "iter/sec",
            "range": "stddev: 0.00128124171674976",
            "extra": "mean: 43.3969818333253 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 62.108793959251976,
            "unit": "iter/sec",
            "range": "stddev: 0.00036436431293765945",
            "extra": "mean: 16.100779555566238 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.861366893218705,
            "unit": "iter/sec",
            "range": "stddev: 0.0013096033381814341",
            "extra": "mean: 55.98675655555022 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.411200320943405,
            "unit": "iter/sec",
            "range": "stddev: 0.0012832374859814857",
            "extra": "mean: 293.15194239998164 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 61.19206138138047,
            "unit": "iter/sec",
            "range": "stddev: 0.0004377067505147769",
            "extra": "mean: 16.341989098348634 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.11121066906735,
            "unit": "iter/sec",
            "range": "stddev: 0.0021199556848293466",
            "extra": "mean: 58.44121841172476 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.3610695108173805,
            "unit": "iter/sec",
            "range": "stddev: 0.0028591761810251035",
            "extra": "mean: 297.52434360002553 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 62.66110094453041,
            "unit": "iter/sec",
            "range": "stddev: 0.00034389232711008413",
            "extra": "mean: 15.958864190484485 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 44.037838105119754,
            "unit": "iter/sec",
            "range": "stddev: 0.0003214660693103773",
            "extra": "mean: 22.707745044453986 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 61.98053769177021,
            "unit": "iter/sec",
            "range": "stddev: 0.00034583445671379064",
            "extra": "mean: 16.134096883331495 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 64.03299630466864,
            "unit": "iter/sec",
            "range": "stddev: 0.0002624674169541212",
            "extra": "mean: 15.61694841269032 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 61.65737248656394,
            "unit": "iter/sec",
            "range": "stddev: 0.00047688896686246104",
            "extra": "mean: 16.21866063491296 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.295971018869416,
            "unit": "iter/sec",
            "range": "stddev: 0.021147587376482858",
            "extra": "mean: 303.40072600001804 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.13660138110829,
            "unit": "iter/sec",
            "range": "stddev: 0.0025592929008856",
            "extra": "mean: 122.90143674997012 msec\nrounds: 8"
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1786939334294,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.648750994416908,
            "unit": "iter/sec",
            "range": "stddev: 0.0027002826281624973",
            "extra": "mean: 85.84611350000415 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.673704367554397,
            "unit": "iter/sec",
            "range": "stddev: 0.005847908919682296",
            "extra": "mean: 53.55123869999261 msec\nrounds: 20"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.32018949705005,
            "unit": "iter/sec",
            "range": "stddev: 0.00027900377203747464",
            "extra": "mean: 14.85438480596998 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.925646783327807,
            "unit": "iter/sec",
            "range": "stddev: 0.001304494578965226",
            "extra": "mean: 55.78599266666768 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.418664636213193,
            "unit": "iter/sec",
            "range": "stddev: 0.0014331528747639037",
            "extra": "mean: 292.5118742000052 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 63.678914626327014,
            "unit": "iter/sec",
            "range": "stddev: 0.0005425769105888095",
            "extra": "mean: 15.703785246153776 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.207562280431038,
            "unit": "iter/sec",
            "range": "stddev: 0.0009062860014450871",
            "extra": "mean: 58.113984055558554 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.3482016522320683,
            "unit": "iter/sec",
            "range": "stddev: 0.0013130190541285852",
            "extra": "mean: 298.66779359999214 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 66.87043191798415,
            "unit": "iter/sec",
            "range": "stddev: 0.0004189483380827785",
            "extra": "mean: 14.954292522388505 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 47.1209432496618,
            "unit": "iter/sec",
            "range": "stddev: 0.0005727330831033448",
            "extra": "mean: 21.22198604348136 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 65.82068385529934,
            "unit": "iter/sec",
            "range": "stddev: 0.00026900706120056467",
            "extra": "mean: 15.192792621213224 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 67.92387180746985,
            "unit": "iter/sec",
            "range": "stddev: 0.00037194683742808733",
            "extra": "mean: 14.722364514709925 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 64.04971316696762,
            "unit": "iter/sec",
            "range": "stddev: 0.0006656481619527752",
            "extra": "mean: 15.612872416667281 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.54776816909661,
            "unit": "iter/sec",
            "range": "stddev: 0.03481969294643354",
            "extra": "mean: 392.5003899999979 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.368133323763578,
            "unit": "iter/sec",
            "range": "stddev: 0.001712102683318659",
            "extra": "mean: 119.50096411110343 msec\nrounds: 9"
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1787025477961,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.762756343874434,
            "unit": "iter/sec",
            "range": "stddev: 0.003409185086744259",
            "extra": "mean: 85.01408774999912 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 23.63155047673991,
            "unit": "iter/sec",
            "range": "stddev: 0.001028727175101285",
            "extra": "mean: 42.316309333333045 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 66.85850485518354,
            "unit": "iter/sec",
            "range": "stddev: 0.0001055441277636301",
            "extra": "mean: 14.956960257577013 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.280179665263955,
            "unit": "iter/sec",
            "range": "stddev: 0.002992087618284424",
            "extra": "mean: 54.704057526316475 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.5137145845960736,
            "unit": "iter/sec",
            "range": "stddev: 0.0015942652534326567",
            "extra": "mean: 284.5990975999996 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 65.52256768266966,
            "unit": "iter/sec",
            "range": "stddev: 0.00012987410512648291",
            "extra": "mean: 15.261917158727194 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 18.465279033666583,
            "unit": "iter/sec",
            "range": "stddev: 0.0010008154602035094",
            "extra": "mean: 54.15569394736807 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.489135520743763,
            "unit": "iter/sec",
            "range": "stddev: 0.0019184564621616475",
            "extra": "mean: 286.6039435999994 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 66.57379587467695,
            "unit": "iter/sec",
            "range": "stddev: 0.00013168533941611236",
            "extra": "mean: 15.020925078126357 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 47.300865757001965,
            "unit": "iter/sec",
            "range": "stddev: 0.0003363030217246344",
            "extra": "mean: 21.141262088886176 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 66.54612488162162,
            "unit": "iter/sec",
            "range": "stddev: 0.0001195951600821186",
            "extra": "mean: 15.027171030302549 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 67.36191594141894,
            "unit": "iter/sec",
            "range": "stddev: 0.00011620686040129937",
            "extra": "mean: 14.845183454544946 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 66.1696981150749,
            "unit": "iter/sec",
            "range": "stddev: 0.00013554549150291152",
            "extra": "mean: 15.112657734374313 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.3865191402119907,
            "unit": "iter/sec",
            "range": "stddev: 0.001356862501321739",
            "extra": "mean: 295.2884535999999 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.464008144091371,
            "unit": "iter/sec",
            "range": "stddev: 0.00022679271025398832",
            "extra": "mean: 118.14733433333105 msec\nrounds: 9"
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1787111949374,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.632545484997982,
            "unit": "iter/sec",
            "range": "stddev: 0.001297699549347016",
            "extra": "mean: 85.9657072727254 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.825895184491955,
            "unit": "iter/sec",
            "range": "stddev: 0.006040959651364672",
            "extra": "mean: 53.1183240000062 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 61.64539632368784,
            "unit": "iter/sec",
            "range": "stddev: 0.0014574815576828338",
            "extra": "mean: 16.22181151613004 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.585498785112996,
            "unit": "iter/sec",
            "range": "stddev: 0.0011874809961133419",
            "extra": "mean: 56.86503477777668 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.368795591211985,
            "unit": "iter/sec",
            "range": "stddev: 0.002486438318144304",
            "extra": "mean: 296.8419937999954 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 65.24311961217155,
            "unit": "iter/sec",
            "range": "stddev: 0.0006153789738164454",
            "extra": "mean: 15.327286707692059 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.34946011530875,
            "unit": "iter/sec",
            "range": "stddev: 0.00104418006649125",
            "extra": "mean: 57.638681166661996 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.201196764080972,
            "unit": "iter/sec",
            "range": "stddev: 0.011057601710480354",
            "extra": "mean: 312.3831722000034 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 61.53748037068407,
            "unit": "iter/sec",
            "range": "stddev: 0.0008931459117800168",
            "extra": "mean: 16.25025909374722 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 42.659816714417346,
            "unit": "iter/sec",
            "range": "stddev: 0.0010616947113242011",
            "extra": "mean: 23.441263395349733 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 64.02436859664468,
            "unit": "iter/sec",
            "range": "stddev: 0.0004797691413940199",
            "extra": "mean: 15.619052899998564 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 66.47530550607716,
            "unit": "iter/sec",
            "range": "stddev: 0.00046648412244682885",
            "extra": "mean: 15.04318020634866 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 66.65584546046291,
            "unit": "iter/sec",
            "range": "stddev: 0.00030585981707586087",
            "extra": "mean: 15.002435166667455 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.3126567131639524,
            "unit": "iter/sec",
            "range": "stddev: 0.012107239620299949",
            "extra": "mean: 432.4031293999951 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.461435932077316,
            "unit": "iter/sec",
            "range": "stddev: 0.0020621572102244154",
            "extra": "mean: 118.18325022222274 msec\nrounds: 9"
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
          "id": "7ff1bbc1d997c87a319d48005979b7cfa28f21e2",
          "message": "Fix CI after dependency updates",
          "timestamp": "2026-08-14T09:49:30Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/7ff1bbc1d997c87a319d48005979b7cfa28f21e2"
        },
        "date": 1787198309523,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 12.084194644377149,
            "unit": "iter/sec",
            "range": "stddev: 0.0022576433810302453",
            "extra": "mean: 82.75272199999743 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.097556186315195,
            "unit": "iter/sec",
            "range": "stddev: 0.004713703717869596",
            "extra": "mean: 52.36272066666695 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 70.90474033222232,
            "unit": "iter/sec",
            "range": "stddev: 0.0001343000531045209",
            "extra": "mean: 14.103429408450353 msec\nrounds: 71"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.589830926861527,
            "unit": "iter/sec",
            "range": "stddev: 0.0008516265289199364",
            "extra": "mean: 53.79285072222157 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4430010040699752,
            "unit": "iter/sec",
            "range": "stddev: 0.0019833611034038062",
            "extra": "mean: 290.4442952000011 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 69.3991886638164,
            "unit": "iter/sec",
            "range": "stddev: 0.00015493995598605775",
            "extra": "mean: 14.409390358210105 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 18.08264201957419,
            "unit": "iter/sec",
            "range": "stddev: 0.0015244613182609588",
            "extra": "mean: 55.301653315788414 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4669012991505483,
            "unit": "iter/sec",
            "range": "stddev: 0.0027677076795160553",
            "extra": "mean: 288.44201599999906 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 70.92183824671014,
            "unit": "iter/sec",
            "range": "stddev: 0.00017165666236605573",
            "extra": "mean: 14.100029338232604 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 50.3639618329113,
            "unit": "iter/sec",
            "range": "stddev: 0.00040799570708528857",
            "extra": "mean: 19.85546735416932 msec\nrounds: 48"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 70.58183505606678,
            "unit": "iter/sec",
            "range": "stddev: 0.0001112650234483274",
            "extra": "mean: 14.167951275362116 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.97767007011366,
            "unit": "iter/sec",
            "range": "stddev: 0.00015131064973589135",
            "extra": "mean: 14.088938098590345 msec\nrounds: 71"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 70.05285269454417,
            "unit": "iter/sec",
            "range": "stddev: 0.00009695484117495808",
            "extra": "mean: 14.274936159421836 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.733902092392653,
            "unit": "iter/sec",
            "range": "stddev: 0.03328278342197614",
            "extra": "mean: 365.77754660000323 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.92190425238335,
            "unit": "iter/sec",
            "range": "stddev: 0.000761754874706948",
            "extra": "mean: 112.08369555556095 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "committer": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "id": "6039e76e2a543334827bf51ea32ecd3db1298e97",
          "message": "Reject malformed HTTP status codes in wait_for_http",
          "timestamp": "2026-08-20T17:50:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/6039e76e2a543334827bf51ea32ecd3db1298e97"
        },
        "date": 1787285183344,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.650601547014276,
            "unit": "iter/sec",
            "range": "stddev: 0.0028447282770225715",
            "extra": "mean: 85.83247791666793 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.155255570537857,
            "unit": "iter/sec",
            "range": "stddev: 0.005887652109587229",
            "extra": "mean: 52.20499388888714 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 69.31592526151188,
            "unit": "iter/sec",
            "range": "stddev: 0.00016857397808424938",
            "extra": "mean: 14.426699149253894 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.9598088384031,
            "unit": "iter/sec",
            "range": "stddev: 0.0011677378481321585",
            "extra": "mean: 55.67987994737005 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.412043860123294,
            "unit": "iter/sec",
            "range": "stddev: 0.001725117133535039",
            "extra": "mean: 293.079468199997 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 67.59181433183278,
            "unit": "iter/sec",
            "range": "stddev: 0.00024886283704655124",
            "extra": "mean: 14.794690893939265 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.89228765892352,
            "unit": "iter/sec",
            "range": "stddev: 0.0011416951892133642",
            "extra": "mean: 55.8900023888932 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.3952397284485722,
            "unit": "iter/sec",
            "range": "stddev: 0.003281405103987999",
            "extra": "mean: 294.53001260000633 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 68.9201753849358,
            "unit": "iter/sec",
            "range": "stddev: 0.00019177614394829513",
            "extra": "mean: 14.509539397059841 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 48.48449014677372,
            "unit": "iter/sec",
            "range": "stddev: 0.00042763370030201626",
            "extra": "mean: 20.625152434784184 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 68.42874819417631,
            "unit": "iter/sec",
            "range": "stddev: 0.00026480452879846134",
            "extra": "mean: 14.61374095522481 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 69.7162034116116,
            "unit": "iter/sec",
            "range": "stddev: 0.00020317864928097337",
            "extra": "mean: 14.343867724636373 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.74180390039238,
            "unit": "iter/sec",
            "range": "stddev: 0.00017961588645259863",
            "extra": "mean: 14.547188803031862 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.4302949486149745,
            "unit": "iter/sec",
            "range": "stddev: 0.025791978812662843",
            "extra": "mean: 411.4726899999937 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.771024066723323,
            "unit": "iter/sec",
            "range": "stddev: 0.0012077588111898377",
            "extra": "mean: 114.01177244444385 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "committer": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "id": "6039e76e2a543334827bf51ea32ecd3db1298e97",
          "message": "Reject malformed HTTP status codes in wait_for_http",
          "timestamp": "2026-08-20T17:50:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/6039e76e2a543334827bf51ea32ecd3db1298e97"
        },
        "date": 1787370979572,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 18.7022353641089,
            "unit": "iter/sec",
            "range": "stddev: 0.002003014722236917",
            "extra": "mean: 53.46954417647212 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 38.49067272332371,
            "unit": "iter/sec",
            "range": "stddev: 0.004003345888701805",
            "extra": "mean: 25.980320146341388 msec\nrounds: 41"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 105.31747039421992,
            "unit": "iter/sec",
            "range": "stddev: 0.00022842797365822296",
            "extra": "mean: 9.495100824742961 msec\nrounds: 97"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 28.419880102115123,
            "unit": "iter/sec",
            "range": "stddev: 0.0012793498760690857",
            "extra": "mean: 35.186636833333296 msec\nrounds: 30"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 5.205108231103797,
            "unit": "iter/sec",
            "range": "stddev: 0.003747761167107392",
            "extra": "mean: 192.11896383333027 msec\nrounds: 6"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 102.33974573821851,
            "unit": "iter/sec",
            "range": "stddev: 0.0003251186308848455",
            "extra": "mean: 9.77137467741971 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 28.07858581927462,
            "unit": "iter/sec",
            "range": "stddev: 0.0012447447156082295",
            "extra": "mean: 35.61432924138036 msec\nrounds: 29"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 5.222802995690893,
            "unit": "iter/sec",
            "range": "stddev: 0.0037569397517794286",
            "extra": "mean: 191.46806816666384 msec\nrounds: 6"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 105.47523155859817,
            "unit": "iter/sec",
            "range": "stddev: 0.0002036629811731285",
            "extra": "mean: 9.480898834950048 msec\nrounds: 103"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 73.29289305924149,
            "unit": "iter/sec",
            "range": "stddev: 0.0002614696965474958",
            "extra": "mean: 13.643887671233223 msec\nrounds: 73"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 105.50457018458063,
            "unit": "iter/sec",
            "range": "stddev: 0.00019537103260291167",
            "extra": "mean: 9.47826239423085 msec\nrounds: 104"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 107.33303617296397,
            "unit": "iter/sec",
            "range": "stddev: 0.0002401446626290695",
            "extra": "mean: 9.316795980582622 msec\nrounds: 103"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 106.37302794155958,
            "unit": "iter/sec",
            "range": "stddev: 0.00021352147996685816",
            "extra": "mean: 9.400879333334306 msec\nrounds: 102"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 6.172688939375051,
            "unit": "iter/sec",
            "range": "stddev: 0.0021806343651572134",
            "extra": "mean: 162.0039515714272 msec\nrounds: 7"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 12.847771597945757,
            "unit": "iter/sec",
            "range": "stddev: 0.0013868457643612003",
            "extra": "mean: 77.83450946153891 msec\nrounds: 13"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "committer": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "id": "6039e76e2a543334827bf51ea32ecd3db1298e97",
          "message": "Reject malformed HTTP status codes in wait_for_http",
          "timestamp": "2026-08-20T17:50:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/6039e76e2a543334827bf51ea32ecd3db1298e97"
        },
        "date": 1787457637103,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.715562314480364,
            "unit": "iter/sec",
            "range": "stddev: 0.003620667729712438",
            "extra": "mean: 85.356551666667 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 23.529420738181635,
            "unit": "iter/sec",
            "range": "stddev: 0.0011080383071709217",
            "extra": "mean: 42.499983791665606 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 65.21242588073997,
            "unit": "iter/sec",
            "range": "stddev: 0.0004205783104698357",
            "extra": "mean: 15.334500848485424 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.232862064965396,
            "unit": "iter/sec",
            "range": "stddev: 0.0016571906454234148",
            "extra": "mean: 54.84602452631443 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.467212504661079,
            "unit": "iter/sec",
            "range": "stddev: 0.001470468253464599",
            "extra": "mean: 288.4161264000028 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 65.25873275588462,
            "unit": "iter/sec",
            "range": "stddev: 0.00025929801003680855",
            "extra": "mean: 15.323619656249399 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.811801894255126,
            "unit": "iter/sec",
            "range": "stddev: 0.002163161879243628",
            "extra": "mean: 56.142551210528104 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4626423484563698,
            "unit": "iter/sec",
            "range": "stddev: 0.0013432437463529125",
            "extra": "mean: 288.79679140001144 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 66.01257136807834,
            "unit": "iter/sec",
            "range": "stddev: 0.0004281877076173082",
            "extra": "mean: 15.14862971212131 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 45.58067408590555,
            "unit": "iter/sec",
            "range": "stddev: 0.0006307497634276162",
            "extra": "mean: 21.939122666665867 msec\nrounds: 48"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 62.46913564996385,
            "unit": "iter/sec",
            "range": "stddev: 0.0005168925605344675",
            "extra": "mean: 16.007905177419865 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 67.1238813233207,
            "unit": "iter/sec",
            "range": "stddev: 0.0001917434857732831",
            "extra": "mean: 14.897827424240026 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 66.45370317631722,
            "unit": "iter/sec",
            "range": "stddev: 0.00023223601759066932",
            "extra": "mean: 15.04807034375144 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.4014003868798386,
            "unit": "iter/sec",
            "range": "stddev: 0.001806182449659003",
            "extra": "mean: 293.9965561999941 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.326904508156735,
            "unit": "iter/sec",
            "range": "stddev: 0.0023997805051892258",
            "extra": "mean: 120.09264655556409 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "committer": {
            "name": "Test",
            "username": "TESTPERSONAL",
            "email": "test@test.com"
          },
          "id": "6039e76e2a543334827bf51ea32ecd3db1298e97",
          "message": "Reject malformed HTTP status codes in wait_for_http",
          "timestamp": "2026-08-20T17:50:47Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/6039e76e2a543334827bf51ea32ecd3db1298e97"
        },
        "date": 1787544300436,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 10.957466064296385,
            "unit": "iter/sec",
            "range": "stddev: 0.0020898551043006244",
            "extra": "mean: 91.26197554545777 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 17.65235372949248,
            "unit": "iter/sec",
            "range": "stddev: 0.003565175270172579",
            "extra": "mean: 56.64966923528508 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 62.265781648210066,
            "unit": "iter/sec",
            "range": "stddev: 0.00018451026825130188",
            "extra": "mean: 16.060185442620984 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 16.659958599671143,
            "unit": "iter/sec",
            "range": "stddev: 0.0024436131320574495",
            "extra": "mean: 60.024158764700616 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.2484796998056606,
            "unit": "iter/sec",
            "range": "stddev: 0.0009314757130459044",
            "extra": "mean: 307.83630880002875 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 60.24202044966528,
            "unit": "iter/sec",
            "range": "stddev: 0.00021540013545848078",
            "extra": "mean: 16.599708849996848 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 16.51847940412745,
            "unit": "iter/sec",
            "range": "stddev: 0.0011289710199772337",
            "extra": "mean: 60.538259941174196 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.2651890191771464,
            "unit": "iter/sec",
            "range": "stddev: 0.0006371988254827253",
            "extra": "mean: 306.26098339997725 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 61.731679796769875,
            "unit": "iter/sec",
            "range": "stddev: 0.0003279286031936348",
            "extra": "mean: 16.199138000005068 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 43.59299716425999,
            "unit": "iter/sec",
            "range": "stddev: 0.0004429138493939255",
            "extra": "mean: 22.93946425000244 msec\nrounds: 44"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 61.58856860819074,
            "unit": "iter/sec",
            "range": "stddev: 0.00026777486089254055",
            "extra": "mean: 16.23677936666657 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 62.87524558567253,
            "unit": "iter/sec",
            "range": "stddev: 0.00013811258757262865",
            "extra": "mean: 15.90451044262595 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 61.26262108909549,
            "unit": "iter/sec",
            "range": "stddev: 0.00019308460547347637",
            "extra": "mean: 16.32316708332932 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.550082426696738,
            "unit": "iter/sec",
            "range": "stddev: 0.02225289208339708",
            "extra": "mean: 392.14418700000806 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 7.912655025985491,
            "unit": "iter/sec",
            "range": "stddev: 0.0005520260738160375",
            "extra": "mean: 126.37983037500788 msec\nrounds: 8"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "e553183f19a1b4364aa9a763871fd4fa260edd67",
          "message": "Merge canary contract refresh",
          "timestamp": "2026-08-24T15:31:04Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/e553183f19a1b4364aa9a763871fd4fa260edd67"
        },
        "date": 1787630373711,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 14.557367992927968,
            "unit": "iter/sec",
            "range": "stddev: 0.0014413025310293943",
            "extra": "mean: 68.69373642857722 msec\nrounds: 14"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 28.342878256680596,
            "unit": "iter/sec",
            "range": "stddev: 0.0020876653588552813",
            "extra": "mean: 35.28223178125156 msec\nrounds: 32"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 85.42000979230649,
            "unit": "iter/sec",
            "range": "stddev: 0.0002753262442553314",
            "extra": "mean: 11.70685887804788 msec\nrounds: 82"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 22.372657530767434,
            "unit": "iter/sec",
            "range": "stddev: 0.0008563614121162628",
            "extra": "mean: 44.697416863632554 msec\nrounds: 22"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 4.503943357795744,
            "unit": "iter/sec",
            "range": "stddev: 0.0014792500969188316",
            "extra": "mean: 222.0276590000026 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 81.57639851630019,
            "unit": "iter/sec",
            "range": "stddev: 0.00032676064739507195",
            "extra": "mean: 12.258447518986573 msec\nrounds: 79"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 22.316371907075084,
            "unit": "iter/sec",
            "range": "stddev: 0.0012275010515054219",
            "extra": "mean: 44.81015122726846 msec\nrounds: 22"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 4.4785557685205015,
            "unit": "iter/sec",
            "range": "stddev: 0.0018711241881381793",
            "extra": "mean: 223.2862672000067 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 86.42304489750886,
            "unit": "iter/sec",
            "range": "stddev: 0.00015054838997284505",
            "extra": "mean: 11.570987821430311 msec\nrounds: 84"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 61.262126186310816,
            "unit": "iter/sec",
            "range": "stddev: 0.0005515514209523235",
            "extra": "mean: 16.32329894915486 msec\nrounds: 59"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 85.09571720178722,
            "unit": "iter/sec",
            "range": "stddev: 0.0003176434014647351",
            "extra": "mean: 11.751472728394814 msec\nrounds: 81"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 86.91147488019169,
            "unit": "iter/sec",
            "range": "stddev: 0.00017446185702035995",
            "extra": "mean: 11.505960534883451 msec\nrounds: 86"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 85.38917038907111,
            "unit": "iter/sec",
            "range": "stddev: 0.00019504876231670964",
            "extra": "mean: 11.711086961538033 msec\nrounds: 78"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.9085175050557988,
            "unit": "iter/sec",
            "range": "stddev: 0.008687576350558484",
            "extra": "mean: 255.85148300000355 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 10.423554622631144,
            "unit": "iter/sec",
            "range": "stddev: 0.0014597029974134168",
            "extra": "mean: 95.93656254545314 msec\nrounds: 11"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "ac0465bec89341b9015be5f7d4b3b2274d1eb1e8",
          "message": "Close the partial PyPI retry race",
          "timestamp": "2026-08-25T00:13:25Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/ac0465bec89341b9015be5f7d4b3b2274d1eb1e8"
        },
        "date": 1787716996488,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.452580392028402,
            "unit": "iter/sec",
            "range": "stddev: 0.0027094239684783924",
            "extra": "mean: 87.31656672727244 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.87556553134376,
            "unit": "iter/sec",
            "range": "stddev: 0.005438375798619404",
            "extra": "mean: 52.978545111109554 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.64351881572352,
            "unit": "iter/sec",
            "range": "stddev: 0.0003332841251197361",
            "extra": "mean: 14.783382318182316 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.455484433327335,
            "unit": "iter/sec",
            "range": "stddev: 0.004066025498461288",
            "extra": "mean: 57.288584789473056 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4014590338111286,
            "unit": "iter/sec",
            "range": "stddev: 0.0033689393291021787",
            "extra": "mean: 293.99148719999744 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 62.28390824066028,
            "unit": "iter/sec",
            "range": "stddev: 0.0004106499135261482",
            "extra": "mean: 16.05551141935532 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.268568009043427,
            "unit": "iter/sec",
            "range": "stddev: 0.0017686004445921356",
            "extra": "mean: 57.90868122222451 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.395145852145288,
            "unit": "iter/sec",
            "range": "stddev: 0.0009615379599368451",
            "extra": "mean: 294.53815640000585 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 64.72073944284725,
            "unit": "iter/sec",
            "range": "stddev: 0.0002791929758160205",
            "extra": "mean: 15.450997757574559 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 45.83118884957123,
            "unit": "iter/sec",
            "range": "stddev: 0.0005106633780770041",
            "extra": "mean: 21.819202711110897 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 65.91362066151433,
            "unit": "iter/sec",
            "range": "stddev: 0.00024630125410341917",
            "extra": "mean: 15.17137110606155 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 68.39383922472132,
            "unit": "iter/sec",
            "range": "stddev: 0.000211124355264692",
            "extra": "mean: 14.621199969697631 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 66.1241401382029,
            "unit": "iter/sec",
            "range": "stddev: 0.0003002860946687642",
            "extra": "mean: 15.123070000002237 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.6989615408101746,
            "unit": "iter/sec",
            "range": "stddev: 0.023679108869433255",
            "extra": "mean: 370.51287499999717 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 7.985451465683871,
            "unit": "iter/sec",
            "range": "stddev: 0.0010680653627934318",
            "extra": "mean: 125.22773499999731 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1787839850332,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 9.990750853500144,
            "unit": "iter/sec",
            "range": "stddev: 0.013506288154276508",
            "extra": "mean: 100.0925770909062 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 22.88331936599805,
            "unit": "iter/sec",
            "range": "stddev: 0.0015757325701747779",
            "extra": "mean: 43.69995383999594 msec\nrounds: 25"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 60.07491243097471,
            "unit": "iter/sec",
            "range": "stddev: 0.0007831018418182901",
            "extra": "mean: 16.64588360655518 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 16.74768545041448,
            "unit": "iter/sec",
            "range": "stddev: 0.001944965260834164",
            "extra": "mean: 59.70974335293905 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.2900983223643796,
            "unit": "iter/sec",
            "range": "stddev: 0.0033960246631062237",
            "extra": "mean: 303.9422843999887 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 60.53046442925466,
            "unit": "iter/sec",
            "range": "stddev: 0.0004890190025570088",
            "extra": "mean: 16.520606762711292 msec\nrounds: 59"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 16.779000365137225,
            "unit": "iter/sec",
            "range": "stddev: 0.00170627899032993",
            "extra": "mean: 59.59830611111746 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.2748858667069625,
            "unit": "iter/sec",
            "range": "stddev: 0.0029483733822444494",
            "extra": "mean: 305.3541530000075 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 61.543097031716314,
            "unit": "iter/sec",
            "range": "stddev: 0.0006746613051968927",
            "extra": "mean: 16.24877603225994 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 43.84854480533474,
            "unit": "iter/sec",
            "range": "stddev: 0.0014747714454026164",
            "extra": "mean: 22.805773930229424 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 60.6272704906643,
            "unit": "iter/sec",
            "range": "stddev: 0.0006195559919491229",
            "extra": "mean: 16.494227629033457 msec\nrounds: 62"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 60.642046855903686,
            "unit": "iter/sec",
            "range": "stddev: 0.0007273227254604317",
            "extra": "mean: 16.490208557375684 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 60.35214395271062,
            "unit": "iter/sec",
            "range": "stddev: 0.0006132564431565004",
            "extra": "mean: 16.569419651165294 msec\nrounds: 43"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.375728367744476,
            "unit": "iter/sec",
            "range": "stddev: 0.0026214718323064163",
            "extra": "mean: 296.23236560000805 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 7.946945942531562,
            "unit": "iter/sec",
            "range": "stddev: 0.002065573630645516",
            "extra": "mean: 125.83450387501216 msec\nrounds: 8"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1787930473827,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.37361585382668,
            "unit": "iter/sec",
            "range": "stddev: 0.0038546316948355566",
            "extra": "mean: 87.92278663636662 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 22.968673714980216,
            "unit": "iter/sec",
            "range": "stddev: 0.0013958133668395044",
            "extra": "mean: 43.53755956521765 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 64.41264881330368,
            "unit": "iter/sec",
            "range": "stddev: 0.0004004548130384847",
            "extra": "mean: 15.524901062498486 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.736160737485438,
            "unit": "iter/sec",
            "range": "stddev: 0.0016709920186527827",
            "extra": "mean: 56.381987894736234 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.368150459252719,
            "unit": "iter/sec",
            "range": "stddev: 0.0016513735979206828",
            "extra": "mean: 296.89885060000165 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 59.3731784126301,
            "unit": "iter/sec",
            "range": "stddev: 0.0006664124959385488",
            "extra": "mean: 16.84262198412602 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.127278509992955,
            "unit": "iter/sec",
            "range": "stddev: 0.0019050832770253936",
            "extra": "mean: 58.3863921764656 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.359174271859021,
            "unit": "iter/sec",
            "range": "stddev: 0.003301130101883746",
            "extra": "mean: 297.69220620000283 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 64.09584650175086,
            "unit": "iter/sec",
            "range": "stddev: 0.0004095934592899527",
            "extra": "mean: 15.601634966669547 msec\nrounds: 60"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 45.4385241032028,
            "unit": "iter/sec",
            "range": "stddev: 0.0005354833434640335",
            "extra": "mean: 22.00775706818157 msec\nrounds: 44"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 64.1082048659169,
            "unit": "iter/sec",
            "range": "stddev: 0.00033089382309944154",
            "extra": "mean: 15.598627384614998 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 64.92806183188401,
            "unit": "iter/sec",
            "range": "stddev: 0.0003442078939457617",
            "extra": "mean: 15.40166103508935 msec\nrounds: 57"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 64.36541396063343,
            "unit": "iter/sec",
            "range": "stddev: 0.00022718913078457936",
            "extra": "mean: 15.53629408196785 msec\nrounds: 61"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.333355171254209,
            "unit": "iter/sec",
            "range": "stddev: 0.0026599710650176433",
            "extra": "mean: 299.99803459999725 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.05799299687286,
            "unit": "iter/sec",
            "range": "stddev: 0.0018408550927630559",
            "extra": "mean: 124.10038087499942 msec\nrounds: 8"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1787997772915,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.697089511578916,
            "unit": "iter/sec",
            "range": "stddev: 0.002237598504042789",
            "extra": "mean: 85.49135227272586 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 20.059882279142148,
            "unit": "iter/sec",
            "range": "stddev: 0.004436550219347619",
            "extra": "mean: 49.850741200000925 msec\nrounds: 20"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 69.23446616843935,
            "unit": "iter/sec",
            "range": "stddev: 0.00022572290065447969",
            "extra": "mean: 14.443673149253682 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.080257499864366,
            "unit": "iter/sec",
            "range": "stddev: 0.0013966109906865308",
            "extra": "mean: 55.308946789474746 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.500496441805567,
            "unit": "iter/sec",
            "range": "stddev: 0.003181603413123343",
            "extra": "mean: 285.6737656000007 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 68.02619418663352,
            "unit": "iter/sec",
            "range": "stddev: 0.0003691413642763309",
            "extra": "mean: 14.700219701493902 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.88997132442858,
            "unit": "iter/sec",
            "range": "stddev: 0.0016482461206374659",
            "extra": "mean: 55.897238842105345 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4784025706118147,
            "unit": "iter/sec",
            "range": "stddev: 0.0029304239841131435",
            "extra": "mean: 287.48828800000297 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 69.02927719038715,
            "unit": "iter/sec",
            "range": "stddev: 0.00031297666105114825",
            "extra": "mean: 14.486606852943517 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 48.137068762916144,
            "unit": "iter/sec",
            "range": "stddev: 0.0006643631838244759",
            "extra": "mean: 20.77401108333336 msec\nrounds: 48"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 68.85233043449277,
            "unit": "iter/sec",
            "range": "stddev: 0.00021755935881046754",
            "extra": "mean: 14.523836647060428 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.06392454129929,
            "unit": "iter/sec",
            "range": "stddev: 0.00021022447513620342",
            "extra": "mean: 14.27268036363776 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.50443079558751,
            "unit": "iter/sec",
            "range": "stddev: 0.00023826801288211581",
            "extra": "mean: 14.597595927538338 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.731380965599763,
            "unit": "iter/sec",
            "range": "stddev: 0.041455831507351285",
            "extra": "mean: 366.11516759999745 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.765216292527088,
            "unit": "iter/sec",
            "range": "stddev: 0.0011149261844392447",
            "extra": "mean: 114.08731588889192 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1788081202284,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.343620650466212,
            "unit": "iter/sec",
            "range": "stddev: 0.002329577278725431",
            "extra": "mean: 88.1552751818178 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 23.620781587465544,
            "unit": "iter/sec",
            "range": "stddev: 0.0009240869120243317",
            "extra": "mean: 42.33560165217622 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 62.78847360655036,
            "unit": "iter/sec",
            "range": "stddev: 0.0004243969672070771",
            "extra": "mean: 15.926490047620392 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.951259995449348,
            "unit": "iter/sec",
            "range": "stddev: 0.0012838919964757623",
            "extra": "mean: 55.70639611110866 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.371914093261731,
            "unit": "iter/sec",
            "range": "stddev: 0.002790778211924951",
            "extra": "mean: 296.567460600005 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 62.75350129748254,
            "unit": "iter/sec",
            "range": "stddev: 0.0004711114961097999",
            "extra": "mean: 15.93536582539844 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.187160568497106,
            "unit": "iter/sec",
            "range": "stddev: 0.00142429862659508",
            "extra": "mean: 58.18296722222587 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.3408897912721076,
            "unit": "iter/sec",
            "range": "stddev: 0.0037961691485872114",
            "extra": "mean: 299.32145700000206 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 63.33282444235846,
            "unit": "iter/sec",
            "range": "stddev: 0.00026517596502193577",
            "extra": "mean: 15.789600555556099 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 46.137703399537564,
            "unit": "iter/sec",
            "range": "stddev: 0.0005103286503358012",
            "extra": "mean: 21.674247444445253 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 63.97518890258324,
            "unit": "iter/sec",
            "range": "stddev: 0.00024811374050515335",
            "extra": "mean: 15.631059746032593 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 65.83086700732201,
            "unit": "iter/sec",
            "range": "stddev: 0.0007576015453952172",
            "extra": "mean: 15.190442500001943 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 64.94604566665328,
            "unit": "iter/sec",
            "range": "stddev: 0.0002685361829009659",
            "extra": "mean: 15.39739624999914 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 3.4110956813458007,
            "unit": "iter/sec",
            "range": "stddev: 0.0036380964503890446",
            "extra": "mean: 293.16093519999527 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.306591676627594,
            "unit": "iter/sec",
            "range": "stddev: 0.0006682128111703255",
            "extra": "mean: 120.38631955555464 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1788169393051,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.46878508806401,
            "unit": "iter/sec",
            "range": "stddev: 0.0020791572425009",
            "extra": "mean: 87.19319372727082 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.39047916298456,
            "unit": "iter/sec",
            "range": "stddev: 0.004741022732740781",
            "extra": "mean: 54.375962210530666 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 67.02622950320882,
            "unit": "iter/sec",
            "range": "stddev: 0.00037272894829791286",
            "extra": "mean: 14.91953235937471 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 17.67193624922711,
            "unit": "iter/sec",
            "range": "stddev: 0.002102256432201331",
            "extra": "mean: 56.586894944448176 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.419683721386328,
            "unit": "iter/sec",
            "range": "stddev: 0.0015750948205105017",
            "extra": "mean: 292.4247039999955 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 64.45819514182338,
            "unit": "iter/sec",
            "range": "stddev: 0.00028915038185445003",
            "extra": "mean: 15.513931126984891 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.129674031525465,
            "unit": "iter/sec",
            "range": "stddev: 0.0015611944344562014",
            "extra": "mean: 58.3782270555528 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.394749982217639,
            "unit": "iter/sec",
            "range": "stddev: 0.0008720239252958023",
            "extra": "mean: 294.57250319999844 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 66.7242378892886,
            "unit": "iter/sec",
            "range": "stddev: 0.0002548203301494289",
            "extra": "mean: 14.987057651512455 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 46.459639851840784,
            "unit": "iter/sec",
            "range": "stddev: 0.0004231567768083794",
            "extra": "mean: 21.524058369565232 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 66.56838769353465,
            "unit": "iter/sec",
            "range": "stddev: 0.00031406952871797076",
            "extra": "mean: 15.02214541538496 msec\nrounds: 65"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 68.77537467448454,
            "unit": "iter/sec",
            "range": "stddev: 0.00025484445473339883",
            "extra": "mean: 14.540088000000342 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 66.7458726453447,
            "unit": "iter/sec",
            "range": "stddev: 0.000338608504635654",
            "extra": "mean: 14.982199803027768 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.4161259560402577,
            "unit": "iter/sec",
            "range": "stddev: 0.022483766827839133",
            "extra": "mean: 413.88570720000075 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.446541325649457,
            "unit": "iter/sec",
            "range": "stddev: 0.0035662980024576594",
            "extra": "mean: 118.39165422222209 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1788251896384,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 14.737080333011205,
            "unit": "iter/sec",
            "range": "stddev: 0.0020541643269148292",
            "extra": "mean: 67.85604593333119 msec\nrounds: 15"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 28.070880101695604,
            "unit": "iter/sec",
            "range": "stddev: 0.0023190597824397775",
            "extra": "mean: 35.624105705884 msec\nrounds: 34"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 86.94779527677623,
            "unit": "iter/sec",
            "range": "stddev: 0.0002347276210061603",
            "extra": "mean: 11.50115419047434 msec\nrounds: 84"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 23.00728204730359,
            "unit": "iter/sec",
            "range": "stddev: 0.0011909636343634682",
            "extra": "mean: 43.46449954166568 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 4.670740383672952,
            "unit": "iter/sec",
            "range": "stddev: 0.0013886301608450047",
            "extra": "mean: 214.098819000003 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 84.53315862440267,
            "unit": "iter/sec",
            "range": "stddev: 0.00020182508284333992",
            "extra": "mean: 11.829677445784265 msec\nrounds: 83"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 22.882942012654883,
            "unit": "iter/sec",
            "range": "stddev: 0.001039066560127717",
            "extra": "mean: 43.70067447826302 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 4.643111518706507,
            "unit": "iter/sec",
            "range": "stddev: 0.0024247872274381164",
            "extra": "mean: 215.37281540000208 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 87.19907828608348,
            "unit": "iter/sec",
            "range": "stddev: 0.00019456653602328494",
            "extra": "mean: 11.468011126438649 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 65.06403632181633,
            "unit": "iter/sec",
            "range": "stddev: 0.00047798330844890966",
            "extra": "mean: 15.36947377586371 msec\nrounds: 58"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 88.41440547290621,
            "unit": "iter/sec",
            "range": "stddev: 0.00010798004958754764",
            "extra": "mean: 11.310374080459557 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 89.00039302573776,
            "unit": "iter/sec",
            "range": "stddev: 0.00014024999649315576",
            "extra": "mean: 11.235905438201973 msec\nrounds: 89"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 85.30412892290768,
            "unit": "iter/sec",
            "range": "stddev: 0.000940154905328692",
            "extra": "mean: 11.722761988505093 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 4.05821278328394,
            "unit": "iter/sec",
            "range": "stddev: 0.009164459638144256",
            "extra": "mean: 246.41389039999808 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 10.686932043300539,
            "unit": "iter/sec",
            "range": "stddev: 0.001262288688038289",
            "extra": "mean: 93.57222409090582 msec\nrounds: 11"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1788335682833,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.629717782811586,
            "unit": "iter/sec",
            "range": "stddev: 0.0029743570168280255",
            "extra": "mean: 85.98660936364024 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.796069047760607,
            "unit": "iter/sec",
            "range": "stddev: 0.0035863241200238156",
            "extra": "mean: 53.20261366666673 msec\nrounds: 21"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 68.61574419465612,
            "unit": "iter/sec",
            "range": "stddev: 0.0003546676248732708",
            "extra": "mean: 14.573914656716369 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.08110496605676,
            "unit": "iter/sec",
            "range": "stddev: 0.001388011366348153",
            "extra": "mean: 55.30635444444777 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.502196863652169,
            "unit": "iter/sec",
            "range": "stddev: 0.001057761045127565",
            "extra": "mean: 285.5350623999982 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 67.15185296975004,
            "unit": "iter/sec",
            "range": "stddev: 0.000346603336254494",
            "extra": "mean: 14.891621835818453 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.888828675644184,
            "unit": "iter/sec",
            "range": "stddev: 0.0016207961334418096",
            "extra": "mean: 55.90080927777623 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.475267722409743,
            "unit": "iter/sec",
            "range": "stddev: 0.003974631740657453",
            "extra": "mean: 287.74761540000213 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 69.42222744518227,
            "unit": "iter/sec",
            "range": "stddev: 0.0002156786436846475",
            "extra": "mean: 14.40460839130562 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 48.883871523691994,
            "unit": "iter/sec",
            "range": "stddev: 0.0005648089911706322",
            "extra": "mean: 20.456644877551103 msec\nrounds: 49"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 68.46943065572624,
            "unit": "iter/sec",
            "range": "stddev: 0.00033229280358942263",
            "extra": "mean: 14.605057913043531 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.19467328987861,
            "unit": "iter/sec",
            "range": "stddev: 0.00020959965631873808",
            "extra": "mean: 14.246095225350816 msec\nrounds: 71"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.09467785218807,
            "unit": "iter/sec",
            "range": "stddev: 0.0003827606216716603",
            "extra": "mean: 14.685435507466275 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.7920216063920202,
            "unit": "iter/sec",
            "range": "stddev: 0.03205322759470164",
            "extra": "mean: 358.1634173999987 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.839471077204953,
            "unit": "iter/sec",
            "range": "stddev: 0.0013191233862572295",
            "extra": "mean: 113.12894077777793 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "c46f37c0bd3a57014a84e26f7a9671b8a9c448d5",
          "message": "Update: Bump the python-dependencies group with 3 updates\n\nBumps the python-dependencies group with 3 updates: [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and griffelib.\n\n\nUpdates `ruff` from 0.16.3 to 0.16.4\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.3...0.16.4)\n\nUpdates `hypothesis` from 6.165.9 to 6.165.10\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.9...v6.165.10)\n\nUpdates `griffelib` from 2.1.0 to 2.2.0\n\n---\nupdated-dependencies:\n- dependency-name: ruff\n  dependency-version: 0.16.4\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.165.10\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: griffelib\n  dependency-version: 2.2.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-08-26T05:35:33Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/c46f37c0bd3a57014a84e26f7a9671b8a9c448d5"
        },
        "date": 1788422561501,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.247773854658117,
            "unit": "iter/sec",
            "range": "stddev: 0.003329829249454909",
            "extra": "mean: 88.90648166666892 msec\nrounds: 12"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 18.675102238013118,
            "unit": "iter/sec",
            "range": "stddev: 0.0046873527682066585",
            "extra": "mean: 53.547230277781445 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 69.45202671625064,
            "unit": "iter/sec",
            "range": "stddev: 0.0002523779284108681",
            "extra": "mean: 14.398427911766271 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.15908320079905,
            "unit": "iter/sec",
            "range": "stddev: 0.001062388312931959",
            "extra": "mean: 55.06885942105256 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.4676534419188214,
            "unit": "iter/sec",
            "range": "stddev: 0.0012186645110954235",
            "extra": "mean: 288.37945220000165 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 66.56484685808348,
            "unit": "iter/sec",
            "range": "stddev: 0.0005517291271205726",
            "extra": "mean: 15.022944500000188 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 16.9817872539336,
            "unit": "iter/sec",
            "range": "stddev: 0.0023268207737779296",
            "extra": "mean: 58.886616882352214 msec\nrounds: 17"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.4444710067505455,
            "unit": "iter/sec",
            "range": "stddev: 0.0034628519986239516",
            "extra": "mean: 290.32034179999755 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 68.36432999031793,
            "unit": "iter/sec",
            "range": "stddev: 0.0005346149559046188",
            "extra": "mean: 14.627511161765566 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 44.70037681613149,
            "unit": "iter/sec",
            "range": "stddev: 0.0008622582375140665",
            "extra": "mean: 22.37117606666617 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 64.92861351050499,
            "unit": "iter/sec",
            "range": "stddev: 0.0004154346035416566",
            "extra": "mean: 15.401530171874178 msec\nrounds: 64"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 68.95157559642783,
            "unit": "iter/sec",
            "range": "stddev: 0.0004049487719562038",
            "extra": "mean: 14.502931823530469 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 69.00688315645941,
            "unit": "iter/sec",
            "range": "stddev: 0.00016363404911198974",
            "extra": "mean: 14.491308029848247 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.508732393205542,
            "unit": "iter/sec",
            "range": "stddev: 0.01709584887509985",
            "extra": "mean: 398.60768039999925 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.626302560544698,
            "unit": "iter/sec",
            "range": "stddev: 0.00062154086488677",
            "extra": "mean: 115.924521888884 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "e56827e7c1d0bcfb445cda9595a4cc2f42a7f5a5",
          "message": "Update: Bump the python-dependencies group with 4 updates\n\nBumps the python-dependencies group with 4 updates: [maturin](https://github.com/pyo3/maturin), [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and [pytest-benchmark](https://github.com/ionelmc/pytest-benchmark).\n\n\nUpdates `maturin` from 1.14.1 to 1.15.0\n- [Release notes](https://github.com/pyo3/maturin/releases)\n- [Changelog](https://github.com/PyO3/maturin/blob/main/Changelog.md)\n- [Commits](https://github.com/pyo3/maturin/compare/v1.14.1...v1.15.0)\n\nUpdates `ruff` from 0.16.4 to 0.16.5\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.4...0.16.5)\n\nUpdates `hypothesis` from 6.165.10 to 6.167.0\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.10...v6.167.0)\n\nUpdates `pytest-benchmark` from 5.2.3 to 5.3.0\n- [Release notes](https://github.com/ionelmc/pytest-benchmark/releases)\n- [Changelog](https://github.com/ionelmc/pytest-benchmark/blob/master/CHANGELOG.rst)\n- [Commits](https://github.com/ionelmc/pytest-benchmark/compare/v5.2.3...v5.3.0)\n\n---\nupdated-dependencies:\n- dependency-name: maturin\n  dependency-version: 1.15.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n- dependency-name: ruff\n  dependency-version: 0.16.5\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.167.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n- dependency-name: pytest-benchmark\n  dependency-version: 5.3.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-09-02T05:35:51Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/e56827e7c1d0bcfb445cda9595a4cc2f42a7f5a5"
        },
        "date": 1788508733211,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 11.256227095765176,
            "unit": "iter/sec",
            "range": "stddev: 0.005154452875264123",
            "extra": "mean: 88.83971436363615 msec\nrounds: 11"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 19.261707446470236,
            "unit": "iter/sec",
            "range": "stddev: 0.005112672496127006",
            "extra": "mean: 51.916477434779694 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 69.01893783125622,
            "unit": "iter/sec",
            "range": "stddev: 0.00016986152054066043",
            "extra": "mean: 14.488777014286873 msec\nrounds: 70"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 18.20603012866627,
            "unit": "iter/sec",
            "range": "stddev: 0.0013284221064309384",
            "extra": "mean: 54.92685626315931 msec\nrounds: 19"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 3.454302538444485,
            "unit": "iter/sec",
            "range": "stddev: 0.0007057444466105596",
            "extra": "mean: 289.4940408000025 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 67.99013341605304,
            "unit": "iter/sec",
            "range": "stddev: 0.00019708257231817894",
            "extra": "mean: 14.708016439395479 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 17.752760937736085,
            "unit": "iter/sec",
            "range": "stddev: 0.0012600582621808078",
            "extra": "mean: 56.32926638888907 msec\nrounds: 18"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 3.441086999411501,
            "unit": "iter/sec",
            "range": "stddev: 0.0016547802618210497",
            "extra": "mean: 290.60584639999547 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 69.46404235628468,
            "unit": "iter/sec",
            "range": "stddev: 0.00027338386160279896",
            "extra": "mean: 14.395937323528456 msec\nrounds: 68"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 48.84858362401626,
            "unit": "iter/sec",
            "range": "stddev: 0.0004333558586796931",
            "extra": "mean: 20.471422625002234 msec\nrounds: 48"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 69.3291079794131,
            "unit": "iter/sec",
            "range": "stddev: 0.00019952390546999315",
            "extra": "mean: 14.423955956521821 msec\nrounds: 69"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 70.09513596418005,
            "unit": "iter/sec",
            "range": "stddev: 0.00012993680346511606",
            "extra": "mean: 14.266325134329138 msec\nrounds: 67"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 68.4810760271222,
            "unit": "iter/sec",
            "range": "stddev: 0.0002475552346855422",
            "extra": "mean: 14.602574287879854 msec\nrounds: 66"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 2.5015828828230537,
            "unit": "iter/sec",
            "range": "stddev: 0.05547901944516218",
            "extra": "mean: 399.7468990000016 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 8.64766943122887,
            "unit": "iter/sec",
            "range": "stddev: 0.00168308195334093",
            "extra": "mean: 115.63809277777813 msec\nrounds: 9"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "dependabot[bot]",
            "username": "dependabot[bot]",
            "email": "49699333+dependabot[bot]@users.noreply.github.com"
          },
          "committer": {
            "name": "Zhelezniakou Anton",
            "username": "ZelAnton",
            "email": "github@zelanton.net"
          },
          "id": "e56827e7c1d0bcfb445cda9595a4cc2f42a7f5a5",
          "message": "Update: Bump the python-dependencies group with 4 updates\n\nBumps the python-dependencies group with 4 updates: [maturin](https://github.com/pyo3/maturin), [ruff](https://github.com/astral-sh/ruff), [hypothesis](https://github.com/HypothesisWorks/hypothesis) and [pytest-benchmark](https://github.com/ionelmc/pytest-benchmark).\n\n\nUpdates `maturin` from 1.14.1 to 1.15.0\n- [Release notes](https://github.com/pyo3/maturin/releases)\n- [Changelog](https://github.com/PyO3/maturin/blob/main/Changelog.md)\n- [Commits](https://github.com/pyo3/maturin/compare/v1.14.1...v1.15.0)\n\nUpdates `ruff` from 0.16.4 to 0.16.5\n- [Release notes](https://github.com/astral-sh/ruff/releases)\n- [Changelog](https://github.com/astral-sh/ruff/blob/main/CHANGELOG.md)\n- [Commits](https://github.com/astral-sh/ruff/compare/0.16.4...0.16.5)\n\nUpdates `hypothesis` from 6.165.10 to 6.167.0\n- [Release notes](https://github.com/HypothesisWorks/hypothesis/releases)\n- [Commits](https://github.com/HypothesisWorks/hypothesis/compare/v6.165.10...v6.167.0)\n\nUpdates `pytest-benchmark` from 5.2.3 to 5.3.0\n- [Release notes](https://github.com/ionelmc/pytest-benchmark/releases)\n- [Changelog](https://github.com/ionelmc/pytest-benchmark/blob/master/CHANGELOG.rst)\n- [Commits](https://github.com/ionelmc/pytest-benchmark/compare/v5.2.3...v5.3.0)\n\n---\nupdated-dependencies:\n- dependency-name: maturin\n  dependency-version: 1.15.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n- dependency-name: ruff\n  dependency-version: 0.16.5\n  dependency-type: direct:development\n  update-type: version-update:semver-patch\n  dependency-group: python-dependencies\n- dependency-name: hypothesis\n  dependency-version: 6.167.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n- dependency-name: pytest-benchmark\n  dependency-version: 5.3.0\n  dependency-type: direct:development\n  update-type: version-update:semver-minor\n  dependency-group: python-dependencies\n...\n\nSigned-off-by: dependabot[bot] <support@github.com>",
          "timestamp": "2026-09-02T05:35:51Z",
          "url": "https://github.com/ZelAnton/processkit-py/commit/e56827e7c1d0bcfb445cda9595a4cc2f42a7f5a5"
        },
        "date": 1788594015464,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_aoutput_as_completed.py::test_aoutput_as_completed_throughput",
            "value": 15.156526185245696,
            "unit": "iter/sec",
            "range": "stddev: 0.003131771323173989",
            "extra": "mean: 65.97817915383949 msec\nrounds: 13"
          },
          {
            "name": "benchmarks/test_lifecycle_events.py::test_lifecycle_events_throughput",
            "value": 28.344379846767513,
            "unit": "iter/sec",
            "range": "stddev: 0.0022414064024999084",
            "extra": "mean: 35.28036264706082 msec\nrounds: 34"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[1]",
            "value": 87.45987906664246,
            "unit": "iter/sec",
            "range": "stddev: 0.000263077302226143",
            "extra": "mean: 11.433814117648419 msec\nrounds: 85"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[10]",
            "value": 23.11921790767942,
            "unit": "iter/sec",
            "range": "stddev: 0.0010466530379164844",
            "extra": "mean: 43.25405833334154 msec\nrounds: 24"
          },
          {
            "name": "benchmarks/test_output_all.py::test_output_all_concurrency[50]",
            "value": 4.670275356053564,
            "unit": "iter/sec",
            "range": "stddev: 0.0024751385509294566",
            "extra": "mean: 214.12013720000687 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[1]",
            "value": 86.17477881424504,
            "unit": "iter/sec",
            "range": "stddev: 0.0002973844846504606",
            "extra": "mean: 11.604323373496097 msec\nrounds: 83"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[10]",
            "value": 23.07669826820143,
            "unit": "iter/sec",
            "range": "stddev: 0.0012760669902341802",
            "extra": "mean: 43.33375547826751 msec\nrounds: 23"
          },
          {
            "name": "benchmarks/test_output_all.py::test_aoutput_all_concurrency[50]",
            "value": 4.667753589187093,
            "unit": "iter/sec",
            "range": "stddev: 0.002351568174028428",
            "extra": "mean: 214.23581620000505 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_process_group.py::test_process_group_start_exit",
            "value": 88.43062708750773,
            "unit": "iter/sec",
            "range": "stddev: 0.0002936514608612117",
            "extra": "mean: 11.308299318181204 msec\nrounds: 88"
          },
          {
            "name": "benchmarks/test_pty.py::test_pty_output_relay",
            "value": 63.590296705741935,
            "unit": "iter/sec",
            "range": "stddev: 0.000604104911542732",
            "extra": "mean: 15.725669666669509 msec\nrounds: 63"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_processkit",
            "value": 87.68579811022241,
            "unit": "iter/sec",
            "range": "stddev: 0.00017402620455410402",
            "extra": "mean: 11.404355340906912 msec\nrounds: 88"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_subprocess",
            "value": 89.59611547965552,
            "unit": "iter/sec",
            "range": "stddev: 0.00018600937602134004",
            "extra": "mean: 11.161198168541901 msec\nrounds: 89"
          },
          {
            "name": "benchmarks/test_spawn_capture.py::test_spawn_capture_asyncio_subprocess",
            "value": 88.45992850648614,
            "unit": "iter/sec",
            "range": "stddev: 0.00021899841160353596",
            "extra": "mean: 11.304553563217917 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_streaming_throughput.py::test_stdout_lines_throughput",
            "value": 4.061035709816043,
            "unit": "iter/sec",
            "range": "stddev: 0.005021831541558225",
            "extra": "mean: 246.24260199999526 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/test_supervisor.py::test_live_supervisor_session_restarts",
            "value": 10.658728138970032,
            "unit": "iter/sec",
            "range": "stddev: 0.0004858139965382157",
            "extra": "mean: 93.81982418182133 msec\nrounds: 11"
          }
        ]
      }
    ]
  }
}