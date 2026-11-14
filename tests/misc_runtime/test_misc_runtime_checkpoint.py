"""A suite checkpoint never freezes or signals the client; cancel is the terminal path and unblocks quiescence."""
import http.client
import os
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from suite import milestones, run
from suite.sampling_adapter import RateLimitGate, SamplingAdapter


def test_a_checkpoint_never_signals_the_harness(tmp_path, monkeypatch):
    """Run1792338837 paused the client before its native call arrived; checkpoints now copy the workspace, signalling nothing."""
    killpg = Mock()
    monkeypatch.setattr(run.os, "killpg", killpg)
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "checkpoints")
    monkeypatch.setattr(run.time, "sleep", lambda _s: None)
    ws, task = tmp_path / "ws", tmp_path / "task"
    ws.mkdir(); task.mkdir(); (task / "prompt.txt").write_text("Implement.")
    polls = []
    proc = Mock(); proc.poll.side_effect = lambda: (polls.append(1), None if len(polls) < 3 else 0)[1]
    terminal, judgments = run.monitor_milestones(proc, run.MilestonePacing(time.time() - 900, 15, 2), "nosig", ws, task, stop=Mock())
    assert terminal == "exited" and [j["status"] for j in judgments] == ["pending"]
    killpg.assert_not_called()


def test_interrupt_during_monitor_is_reported_and_returns_to_shutdown(monkeypatch):
    monkeypatch.setattr(run, "monitor_milestones", Mock(side_effect=KeyboardInterrupt))
    terminal, judgments = run.monitor_interruptible(Mock(), Mock(), "run", None, None, stop=Mock())
    assert terminal == "operator-interrupted" and judgments == []


def test_wrapper_interrupt_reaches_runner_and_owned_harness_is_reaped(tmp_path):
    ready, finished = tmp_path / "ready", tmp_path / "finished"
    script = tmp_path / "runner.py"
    script.write_text('''import os, subprocess, sys, time\nfrom pathlib import Path\nfrom suite import run\np = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)\nPath(sys.argv[1]).write_text(str(p.pid))\nterminal, _ = run.monitor_interruptible(p, run.MilestonePacing(time.time(), 15, 2), "cell", None, None, stop=lambda: run.stop_process_group(p, grace=0.01))\nrun.shutdown_and_capture(calls_dir=Path(sys.argv[1]).parent, before_sessions=set(), stop=lambda: run.stop_process_group(p, grace=0.01))\nPath(sys.argv[2]).write_text(terminal + ":" + str(p.poll()))\n''')
    env = dict(os.environ, PYTHONPATH=str(run.SUITE.parent))
    wrapper = subprocess.Popen([sys.executable, "-c", "from suite.battery_run import sh; import sys; sys.exit(sh(*sys.argv[1:], timeout=None))", sys.executable, str(script), str(ready), str(finished)], env=env)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        pid = int(ready.read_text())
        wrapper.send_signal(signal.SIGINT)
        assert wrapper.wait(timeout=10) == 130
        assert finished.read_text().startswith("operator-interrupted:")
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()


def test_cancel_unblocks_quiescence_and_admission_stays_closed(tmp_path):
    """Cancel wakes a waiting quiesce (False, not a hang); a later request gets 503, never forwarded (the target port is closed)."""
    with SamplingAdapter(None, RateLimitGate(tmp_path / "rate"), target=("127.0.0.1", 1)) as adapter:
        outcome = []
        waiting = threading.Thread(target=lambda: outcome.append(adapter.quiesce(lambda: True)))
        waiting.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda: adapter._paused, timeout=3)
        adapter.cancel()
        waiting.join(3)
        assert not waiting.is_alive() and outcome == [False]
        conn = http.client.HTTPConnection(*adapter.server.server_address, timeout=5)
        conn.request("POST", "/v1/responses", b'{"input":"x"}', {"Content-Type": "application/json"})
        assert conn.getresponse().status == 503
