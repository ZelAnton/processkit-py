window.BENCHMARK_DATA = {
  "lastUpdate": 1787544301840,
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
      }
    ]
  }
}