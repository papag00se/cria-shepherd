"""Ending a battery cell must not signal other Codex sessions on the host."""
from __future__ import annotations

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
import run  # noqa: E402


class _Proc:
    def __init__(self, pid, states):
        self.pid, self._states = pid, iter(states)
        self.waited = False

    def poll(self):
        return next(self._states, None)

    def wait(self, timeout):
        self.waited = True


def test_stopping_a_cell_signals_only_its_own_process_group(monkeypatch):
    sent = []
    proc = _Proc(731, [None, None, None])
    monkeypatch.setattr(run.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    run.stop_process_group(proc, grace=0, sleeper=lambda _: None)
    assert sent == [(731, signal.SIGINT), (731, signal.SIGKILL)]
    assert proc.waited


def test_an_exited_leader_does_not_leave_its_owned_children_running(monkeypatch):
    sent = []
    proc = _Proc(731, [0])
    monkeypatch.setattr(run.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    run.stop_process_group(proc, grace=0, sleeper=lambda _: None)
    assert sent == [(731, signal.SIGINT), (731, signal.SIGKILL)]


def test_run_caller_includes_grace_period_session_and_response_in_post_stop_cutoff(monkeypatch, tmp_path):
    proc = _Proc(912, [0])  # leader exited; one owned child remains live during shutdown grace
    child_live = True
    events = []
    calls = tmp_path / "calls"
    calls.mkdir()
    before = set()

    def killpg(pgid, sig):
        nonlocal child_live
        events.append(("signal", pgid, sig))
        if sig == signal.SIGINT:
            # Model a child finishing a response and creating a fresh capture session during grace.
            session = calls / "20261001T010000-session"
            session.mkdir()
            request = session / "0001-coder-s1.json"
            request.write_text('{"seq":1,"phase":"coder-s1","body":{"messages":[]}}')
            response = session / "0001-coder-s1.response.json"
            response.write_text('{"choices":[{"message":{"content":"done"}}]}')
            events.extend([("request",), ("response",)])
        if sig == signal.SIGKILL:
            child_live = False

    monkeypatch.setattr(run.os, "killpg", killpg)
    started = run.time.time() - 10
    stopped_at, sessions, snapshot = run.shutdown_and_capture(
        proc, calls_dir=calls, before_sessions=before,
        resume=lambda: events.append(("resume",)),
        stopper=lambda p: run.stop_process_group(p, grace=0, sleeper=lambda _: None))
    wall_seconds = stopped_at - started
    response = sessions[0] / "0001-coder-s1.response.json"
    assert not child_live
    assert len(sessions) == 1 and sessions[0].name == "20261001T010000-session"
    assert snapshot["complete"] and len(snapshot["entries"]) == 1
    assert snapshot["entries"][0]["response"] == str(response)
    assert response.stat().st_mtime <= stopped_at
    assert started + wall_seconds == stopped_at
    assert events[0] == ("resume",)
    assert events.index(("response",)) < events.index(("signal", 912, signal.SIGKILL))
