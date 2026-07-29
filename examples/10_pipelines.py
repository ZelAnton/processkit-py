"""Build a shell-free pipeline and inspect a checked-stage failure.

Run it:  python examples/10_pipelines.py
"""

from __future__ import annotations

import sys

from processkit import Command


def python_stage(code: str) -> Command:
    """Return a portable pipeline stage using the current interpreter."""
    return Command(sys.executable, ["-c", code])


def main() -> None:
    produce = python_stage("print('pear'); print('apple'); print('apricot')")
    select = python_stage(
        "import sys\n"
        "for line in sys.stdin:\n"
        "    if line.startswith('a'):\n"
        "        print(line.strip().upper())\n"
    )
    count = python_stage("import sys; print(sum(1 for _ in sys.stdin))")

    selected_count = (produce | select | count).timeout(10).run()
    assert selected_count == "2"
    print(f"selected lines: {selected_count}")

    fail = python_stage(
        "import sys; sys.stdin.read(); "
        "sys.stderr.write('intentional stage failure\\n'); sys.exit(7)"
    )
    drain = python_stage("import sys; sys.stdin.read(); print('downstream finished')")
    result = (produce | fail | drain).output()
    assert result.code == 7
    assert "intentional stage failure" in result.stderr
    print(f"pipefail attributed exit code: {result.code}")


if __name__ == "__main__":
    main()
