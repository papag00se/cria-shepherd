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
