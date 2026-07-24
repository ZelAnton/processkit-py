"""Hold a conversation with a live REPL-style child, one exchange at a time.

The conversational stdin pattern for the agent / LLM-tool niche: an agent that
drives a REPL-like helper (a calculator, a database shell, a language server)
needs to send one request, read exactly its response, then send the next —
not dump everything upfront and hope the output lines back up in order.
``keep_stdin_open()`` on the ``Command`` keeps the pipe open across writes,
``take_stdin()`` hands back the writer, and ``stdout_lines()`` streams the
child's answers as they arrive.

Run it:  python examples/05_interactive_stdin.py
"""

from __future__ import annotations

import asyncio
import sys

from processkit import Command

# A tiny calculator REPL: read one arithmetic expression per line, print its
# value, repeat until stdin closes (EOF). Kept inline and dependency-free (no
# external binary, no third-party package) so the example runs unmodified on
# Windows, Linux, and macOS. Stands in for any conversational child — a `bc`,
# a database shell, a language server driven over stdin/stdout.
_CALCULATOR = """
import sys
for line in sys.stdin:
    expr = line.strip()
    if not expr:
        continue
    try:
        value = eval(expr, {"__builtins__": {}}, {})
    except Exception as exc:
        print(f"error: {exc}", flush=True)
    else:
        print(value, flush=True)
"""


async def main() -> None:
    proc = await Command(sys.executable, ["-c", _CALCULATOR]).keep_stdin_open().astart()
    async with proc:
        stdin = proc.take_stdin()  # ProcessStdin (raises if stdin wasn't kept open)
        answers = proc.stdout_lines()

        # Several exchanges in a row — write one request, read exactly its
        # answer, then move to the next. This is what tells the conversational
        # pattern apart from a single upfront write/read.
        for question in ("2 + 2", "6 * 7", "100 / 4"):
            print(f"> {question}")
            await stdin.write_line(question)
            answer = await anext(answers)
            print(f"= {answer.rstrip()}")

        await stdin.close()  # send EOF — the calculator exits on its own
        finished = await proc.afinish()

    print(f"exit code : {finished.code}")
    print("done" if finished.exited_zero else "calculator failed")


if __name__ == "__main__":
    asyncio.run(main())
