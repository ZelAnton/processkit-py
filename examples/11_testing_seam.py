"""Test through a runner seam, then record and replay a scrubbed cassette.

Run it:  python examples/11_testing_seam.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

from processkit import Command, ProcessRunner
from processkit.testing import RecordingRunner, RecordReplayRunner, Reply, ScriptedRunner


def deployment_status(runner: ProcessRunner, token: str) -> str:
    """Application code depends on the runner protocol, not a concrete runner."""
    return runner.run(Command("deploy-tool", ["status", "--token", token]))


def main() -> None:
    scripted = ScriptedRunner()
    scripted.on(["deploy-tool", "status"], Reply.ok("ready"))
    spy = RecordingRunner.new(scripted)
    assert deployment_status(spy, "test-token") == "ready"
    assert spy.only_call().has_flag("--token")
    print("scripted status: ready (no process spawned)")

    secret = "record-only-secret"

    def scrub(field: str, text: str) -> str:
        if field in {"argument", "stdout", "stderr"}:
            return text.replace(secret, "<token>")
        return text

    code = "import sys; print('token=' + sys.argv[1])"
    command = Command(sys.executable, ["-c", code, secret])
    with tempfile.TemporaryDirectory() as directory:
        cassette = pathlib.Path(directory) / "tool.json"
        recorder = RecordReplayRunner.record(str(cassette), scrub=scrub)
        recorded = recorder.run(command)
        recorder.save()

        assert recorded == f"token={secret}"
        assert secret not in cassette.read_text(encoding="utf-8")

        replay = RecordReplayRunner.replay(str(cassette), scrub=scrub)
        assert replay.run(command) == "token=<token>"
        print("cassette replay: token=<token> (offline and scrubbed)")


if __name__ == "__main__":
    main()
