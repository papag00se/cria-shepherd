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


def test_run_caller_stops_live_children_before_capture_snapshot(monkeypatch, tmp_path):
    proc = _Proc(912, [0])  # leader has already exited; one owned child is still active
    child_live = True
    events = []

    def killpg(pgid, sig):
        nonlocal child_live
        events.append(("signal", pgid, sig))
        if sig == signal.SIGKILL:
            child_live = False

    monkeypatch.setattr(run.os, "killpg", killpg)

    def capture(dirs):
        events.append(("snapshot", tuple(dirs)))
        assert not child_live
        return {"complete": True, "entries": []}

    monkeypatch.setattr(run, "capture_manifest", capture)
    got = run.stopped_capture_manifest(
        proc, [tmp_path], resume=lambda: events.append(("resume",)),
        stopper=lambda p: run.stop_process_group(p, grace=0, sleeper=lambda _: None))
    assert got == {"complete": True, "entries": []}
    assert events == [("resume",), ("signal", 912, signal.SIGINT),
                      ("signal", 912, signal.SIGKILL), ("snapshot", (tmp_path,))]
