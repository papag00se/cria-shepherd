"""A suite checkpoint never freezes or signals the client; cancel is the terminal path and unblocks quiescence."""
import http.client
import threading
import time
from unittest.mock import Mock

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
