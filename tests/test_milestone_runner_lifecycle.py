"""The runner monitor: checkpoints are asynchronous. Fake time/process and real packets and verdict files; no models.

Operator policy (2026-10-26): the coder is never paused for a judgment or a snapshot. Each interval copies the LIVE
workspace and the monitor keeps observing — natural exit, the next interval — while judgments are collected whenever the
campaign agent records them. Active time is therefore wall time. A genuine independent stop decision (minute >= 30) ends
the run even though files changed since its snapshot and even though a newer checkpoint is still unanswered: the operator
accepts approximate, mutable snapshots, and no file-state precondition may veto a recorded judgment. Only an
already-recorded judgment of a NEWER checkpoint supersedes an older one."""
import json
import os
import shutil
from types import SimpleNamespace

import pytest

from suite import milestones, run


def verdict_text(decision="continue", usefulness=20, reason="Inspected current and prior work."):
    return json.dumps(dict(usefulness_percent=usefulness, decision=decision, reason=reason,
                           evidence=["code.py"], material_changes="Inspected the changes.",
                           requirements=[dict(requirement="requirement", status="partial", evidence="code.py")],
                           pace_reason="Pace considered."))


class Rig:
    """Fake clock + fake process. `answers` = {minute: (clock_when_recorded, decision, usefulness)} are written as REAL
    verdict files, so parsing, validity and polling are the production ones."""

    def __init__(self, tmp_path, monkeypatch, *, exits_at=None, exit_code=0, answers=None):
        self.clock = SimpleNamespace(now=0.0)
        self.events, self.answers = [], dict(answers or {})
        monkeypatch.setattr(run.time, "time", lambda: self.clock.now)
        monkeypatch.setattr(run.time, "sleep", self.sleep)
        self.proc = SimpleNamespace(
            poll=lambda: exit_code if exits_at is not None and self.clock.now >= exits_at else None)
        self.ws = tmp_path / "live"
        self.ws.mkdir()
        (self.ws / "code.py").write_text("working = True\n")
        self.task = tmp_path / "task"
        self.task.mkdir()
        (self.task / "prompt.txt").write_text("Deliver useful code.")
        monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
        self.pacing = run.MilestonePacing(0, 15, 2)
        self.stop = lambda: self.events.append(("stop", self.clock.now))

    def sleep(self, seconds):
        self.clock.now += seconds
        for minute, (when, decision, usefulness) in list(self.answers.items()):
            checkpoint = milestones.ROOT / f"{self.run_id}.{minute:03d}min"
            if self.clock.now >= when and checkpoint.is_dir():
                milestones.verdict_path(checkpoint).write_text(verdict_text(decision, usefulness))
                del self.answers[minute]

    run_id = "async"

    def monitor(self):
        return run.monitor_milestones(self.proc, self.pacing, self.run_id, self.ws, self.task, stop=self.stop)


def test_full_monitor_never_pauses_collects_each_judgment_when_recorded_and_ends_on_a_genuine_stop(tmp_path, monkeypatch, capsys):
    rig = Rig(tmp_path, monkeypatch, answers={15: (1000, "continue", 20), 30: (2000, "continue", 20),
                                                45: (3000, "stalled", 20)})
    terminal, judgments = rig.monitor()
    assert terminal == "milestone-stalled-45min"
    # Snapshots are taken on the scheduled active clock: a judge that answers 100s late delays nothing.
    assert [(j["at_active_minutes"], j["actual_active_seconds"]) for j in judgments] == [(15, 900), (30, 1800), (45, 2700)]
    assert [j["status"] for j in judgments] == ["judged"] * 3
    assert [j["judged_at_active_seconds"] for j in judgments] == [1000, 2000, 3000]
    assert rig.events == [("stop", 3000)]          # the only control action: the terminal stop; no pause, no resume
    assert rig.pacing.active_elapsed(rig.clock.now) == 3000            # legacy 30-minute budget did not stop it; waits are active time
    log = capsys.readouterr().out
    assert log.count("usefulness=20%") == 3 and log.count("[material changes]") == 3
    assert log.count("coder keeps running") == 3
    # every packet compares with the snapshots already judged when it was cut
    second = (milestones.ROOT / "async.030min" / "packet.txt").read_text()
    assert str(milestones.ROOT / "async.015min" / "workspace") in second
    third = (milestones.ROOT / "async.045min" / "packet.txt").read_text()
    assert str(milestones.ROOT / "async.030min" / "workspace") in third and "NOT YET JUDGED" not in third


def test_an_unanswered_checkpoint_is_listed_as_pending_in_the_next_packet_and_never_blocks_it(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=2500, answers={15: (1900, "continue", 10)})   # judged AFTER minute 30 was cut
    terminal, judgments = rig.monitor()
    second = (milestones.ROOT / "async.030min" / "packet.txt").read_text()
    assert "Scheduled 15min checkpoint, NOT YET JUDGED" in second
    assert str(milestones.ROOT / "async.015min" / "workspace") in second
    assert terminal == "exited" and rig.events == []
    assert [j["status"] for j in judgments] == ["judged", "pending"]
    assert judgments[0]["judged_at_active_seconds"] == 1900 and judgments[0]["usefulness_percent"] == 10
    assert "usefulness_percent" not in judgments[1] and "decision" not in judgments[1]   # nothing invented for the pending one


@pytest.mark.parametrize("exit_code, expected", [(0, "exited"), (1, "harness-error")])
def test_natural_early_completion_needs_no_milestone_or_padding(tmp_path, monkeypatch, exit_code, expected):
    rig = Rig(tmp_path, monkeypatch, exits_at=20, exit_code=exit_code)
    monkeypatch.setattr(milestones, "create", lambda *a, **k: pytest.fail("no checkpoint before minute 15"))
    terminal, judgments = rig.monitor()
    assert terminal == expected
    assert judgments == [] and rig.events == []


def test_natural_exit_with_an_unrecorded_checkpoint_keeps_it_pending_and_invents_no_verdict(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=1000)
    terminal, judgments = rig.monitor()
    assert terminal == "exited" and rig.events == []
    assert len(judgments) == 1 and judgments[0]["status"] == "pending" and judgments[0]["at_active_minutes"] == 15
    assert not milestones.verdict_path(milestones.ROOT / "async.015min").exists()
    assert milestones.pending() == [milestones.ROOT / "async.015min"]          # still collectable by the campaign agent


def test_a_judgment_recorded_in_the_last_moments_before_exit_still_belongs_to_its_checkpoint(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=1000, answers={15: (998, "continue", 33)})
    terminal, judgments = rig.monitor()
    assert terminal == "exited"
    assert judgments[0]["status"] == "judged" and judgments[0]["usefulness_percent"] == 33


def test_a_fifteen_minute_stop_decision_cannot_end_the_protected_half_hour(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=1500, answers={15: (1000, "stalled", 0)})
    terminal, judgments = rig.monitor()
    assert terminal == "exited" and rig.events == []
    assert judgments[0]["decision"] == "stalled" and "terminal_not_applied" not in judgments[0]


def test_a_complete_decision_at_the_first_decision_point_ends_the_run(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, answers={15: (1000, "continue", 30), 30: (1850, "complete", 95)})
    result, judgments = rig.monitor()
    assert result == "milestone-complete-30min" and rig.events == [("stop", 1850)]
    assert "terminal_not_applied" not in judgments[1]


def touch_at(rig, monkeypatch, when, path):
    """Move a file's mtime (bytes unchanged) the instant the fake clock reaches `when`."""
    original = run.time.sleep
    def sleeping(seconds):
        original(seconds)
        if rig.clock.now == when:
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    monkeypatch.setattr(run.time, "sleep", sleeping)


@pytest.mark.parametrize("decision, terminal", [("stalled", "milestone-stalled-30min"), ("complete", "milestone-complete-30min")])
def test_a_genuine_stop_decision_ends_the_run_even_when_only_a_timestamp_changed(tmp_path, monkeypatch, decision, terminal):
    # independent repro 1 and 2: snapshot at 1800, mtime-only touch at 1850, valid judgment at 1900.
    rig = Rig(tmp_path, monkeypatch, exits_at=2000, answers={15: (1000, "continue", 30), 30: (1900, decision, 30)})
    touch_at(rig, monkeypatch, 1850, rig.ws / "code.py")
    result, judgments = rig.monitor()
    assert result == terminal and rig.events == [("stop", 1900)]
    assert "terminal_not_applied" not in judgments[1]


def test_repeated_touches_do_not_postpone_a_genuine_stop(tmp_path, monkeypatch):
    # independent repro 3: a touch before every answer used to silence all of them.
    rig = Rig(tmp_path, monkeypatch, exits_at=4000,
              answers={15: (1000, "continue", 30), 30: (1900, "continue", 30), 45: (2800, "stalled", 30), 60: (3700, "stalled", 30)})
    for when in (1850, 2750, 3650):
        touch_at(rig, monkeypatch, when, rig.ws / "code.py")
    result, judgments = rig.monitor()
    assert result == "milestone-stalled-45min" and rig.events == [("stop", 2800)]


def test_a_stop_decision_is_applied_although_the_coder_changed_files_since_the_snapshot(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=3000, answers={15: (1000, "continue", 20), 30: (2000, "stalled", 20)})
    original = run.time.sleep
    def coder_keeps_working(seconds):
        original(seconds)
        if rig.clock.now == 1900:                                  # real new work after the minute-30 snapshot
            (rig.ws / "code.py").write_text("working = 'more'\n")
            (rig.ws / "new.py").write_text("added = True\n")
    monkeypatch.setattr(run.time, "sleep", coder_keeps_working)
    result, judgments = rig.monitor()
    assert result == "milestone-stalled-30min" and rig.events == [("stop", 2000)]


def test_a_mixed_copy_the_operator_accepts_does_not_stop_a_real_judgment_from_ending_the_run(tmp_path, monkeypatch):
    # independent repro 4: a file mutated DURING copytree. No lock, retry or pause; the packet only discloses.
    real_copytree = shutil.copytree
    def changing(src, dst, *args, **kwargs):
        result = real_copytree(src, dst, *args, **kwargs)
        (rig.ws / "code.py").write_text("working = 'changed during the copy'\n")
        return result
    rig = Rig(tmp_path, monkeypatch, exits_at=2500, answers={15: (1000, "continue", 20), 30: (1900, "stalled", 20)})
    monkeypatch.setattr(milestones.shutil, "copytree", changing)
    result, judgments = rig.monitor()
    assert result == "milestone-stalled-30min" and rig.events == [("stop", 1900)]
    assert "approximate" in (milestones.ROOT / "async.030min" / "packet.txt").read_text()


def test_a_newer_unanswered_checkpoint_does_not_silence_an_older_genuine_stop(tmp_path, monkeypatch):
    # independent repro 5: reviewer latency longer than the cadence; the quiet workspace never changed.
    rig = Rig(tmp_path, monkeypatch, exits_at=4000, answers={15: (1000, "continue", 20), 30: (2800, "stalled", 20), 45: (3700, "stalled", 20)})
    result, judgments = rig.monitor()
    assert result == "milestone-stalled-30min" and rig.events == [("stop", 2800)]
    assert [j["status"] for j in judgments] == ["judged", "judged", "pending"]    # 45 was cut at 2700 and never answered in time


def test_an_older_stop_decision_recorded_after_a_newer_checkpoint_was_judged_continue_is_superseded(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=3000,
              answers={15: (1000, "continue", 20), 45: (2800, "continue", 20), 30: (2900, "stalled", 20)})
    result, judgments = rig.monitor()
    assert result == "exited" and rig.events == []
    assert "newer checkpoint was already judged" in judgments[1]["terminal_not_applied"]
    assert judgments[1]["decision"] == "stalled" and judgments[2]["decision"] == "continue"   # both real judgments retained


def test_when_an_older_and_a_newer_judgment_are_collected_together_the_newer_one_decides(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=3000,
              answers={15: (1000, "continue", 20), 30: (2800, "stalled", 20), 45: (2800, "continue", 20)})
    result, judgments = rig.monitor()
    assert result == "exited" and rig.events == []
    assert "newer checkpoint was already judged" in judgments[1]["terminal_not_applied"]


def test_invalid_or_partial_verdict_files_are_not_judgments_and_do_not_end_or_block_anything(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=2000)
    original = rig.sleep
    def garbage(seconds):
        original(seconds)
        checkpoint = milestones.ROOT / "async.015min"
        if checkpoint.is_dir():
            milestones.verdict_path(checkpoint).write_text('{"decision": "complete", "usefulness_perc')
    monkeypatch.setattr(run.time, "sleep", garbage)
    terminal, judgments = rig.monitor()
    assert terminal == "exited" and rig.events == []
    assert [j["status"] for j in judgments] == ["pending", "pending"]


def test_checkpoint_creation_is_not_a_pause_and_leaves_no_control_surface_for_one(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, exits_at=1000)
    signals = []
    monkeypatch.setattr(run.os, "killpg", lambda *a: signals.append(a))
    rig.monitor()
    assert signals == []                                                    # no SIGSTOP/SIGCONT/anything at a checkpoint
    for name in ("pause", "resume"):
        assert not hasattr(run.HarnessControl(SimpleNamespace(), None), name)
    assert not hasattr(rig.pacing, "record_pause") and not hasattr(rig.pacing, "paused_seconds")


def test_interrupted_checkpoint_creation_stops_the_owned_harness(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    def interrupted(*args, **kwargs):
        rig.clock.now += 30
        raise KeyboardInterrupt
    monkeypatch.setattr(milestones, "create", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rig.monitor()
    assert rig.events == [("stop", 930)]


def test_interrupted_judgment_collection_stops_the_owned_harness(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    def interrupted(_checkpoint):
        raise KeyboardInterrupt
    monkeypatch.setattr(milestones, "poll", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rig.monitor()
    assert rig.events == [("stop", 900)]


def test_a_real_process_keeps_running_through_the_checkpoint_and_the_late_judgment(tmp_path, monkeypatch):
    """Real subprocess, real monitor, real verdict file; only the 2s poll sleep is shortened. Before this policy the
    coder sat in SIGSTOP until a judgment was recorded."""
    import subprocess, sys, threading, time
    ticks = tmp_path / "ticks"
    proc = subprocess.Popen([sys.executable, "-c",
        "import sys,time\nf=open(sys.argv[1],'a',buffering=1)\nfor i in range(40):\n f.write('x\\n'); time.sleep(.05)\n", str(ticks)],
        start_new_session=True)
    ws, task = tmp_path / "live", tmp_path / "task"
    ws.mkdir(); task.mkdir(); (task / "prompt.txt").write_text("Deliver useful code.")
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
    real_sleep = time.sleep
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: real_sleep(.05))
    states, ticks_at_verdict, stop = [], [], threading.Event()
    def sample():
        while not stop.is_set():
            try:
                states.append(open(f"/proc/{proc.pid}/stat").read().rpartition(") ")[2].split()[0])
            except OSError:
                pass
            real_sleep(.005)
    def judge_late():
        checkpoint = milestones.ROOT / "real.015min"
        while not checkpoint.is_dir(): real_sleep(.01)
        real_sleep(.4)                                             # the agent takes its time
        milestones.verdict_path(checkpoint).write_text(verdict_text("continue", 40))
        ticks_at_verdict.append(len(ticks.read_text().splitlines()))
    sampler, judge = threading.Thread(target=sample), threading.Thread(target=judge_late)
    sampler.start(); judge.start()
    try:
        terminal, judgments = run.monitor_milestones(proc, run.MilestonePacing(time.time() - 900, 15, 2),
                                                     "real", ws, task, stop=lambda: pytest.fail("nothing ends this run"))
    finally:
        stop.set(); sampler.join(); judge.join()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    assert terminal == "exited" and judgments[0]["status"] == "judged" and judgments[0]["usefulness_percent"] == 40
    assert "T" not in states                                       # never stopped, at any moment of the checkpoint
    assert ticks_at_verdict and ticks_at_verdict[0] > 0 and len(ticks.read_text().splitlines()) == 40
