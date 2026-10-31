"""Milestone runner promises: the coder is never paused or waited on, every checkpoint copy is honestly
approximate, only valid recorded judgments count, a genuine stop (>=30min) ends the run, and an
unattended run stops its own harness if the monitor is interrupted."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from suite import milestones, run

ROOT = Path(__file__).resolve().parents[2]


def verdict_text(decision="continue", usefulness=20, **drop):
    value = dict(usefulness_percent=usefulness, decision=decision, reason="Inspected current work.",
                 evidence=["code.py"], material_changes="Inspected the changes.",
                 requirements=[dict(requirement="q", status="partial", evidence="code.py")], pace_reason="Pace.")
    for key in drop:
        value[key] = drop[key]
    return json.dumps({k: v for k, v in value.items() if v is not None})


class Rig:
    """Fake clock/process; `answers` {minute: (when_recorded, decision, pct)} become REAL verdict files."""

    def __init__(self, tmp_path, monkeypatch, *, exits_at=None, exit_code=0, answers=None):
        self.clock, self.events, self.answers = SimpleNamespace(now=0.0), [], dict(answers or {})
        monkeypatch.setattr(run.time, "time", lambda: self.clock.now)
        monkeypatch.setattr(run.time, "sleep", self.sleep)
        self.proc = SimpleNamespace(poll=lambda: exit_code if exits_at is not None and self.clock.now >= exits_at else None)
        self.ws, self.task = tmp_path / "live", tmp_path / "task"
        self.ws.mkdir(), self.task.mkdir()
        (self.ws / "code.py").write_text("working = True\n")
        (self.task / "prompt.txt").write_text("Deliver useful code.")
        monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
        self.pacing = run.MilestonePacing(0, 15, 2)

    def sleep(self, seconds):
        self.clock.now += seconds
        for minute, (when, decision, pct) in list(self.answers.items()):
            checkpoint = milestones.ROOT / f"async.{minute:03d}min"
            if self.clock.now >= when and checkpoint.is_dir():
                milestones.verdict_path(checkpoint).write_text(verdict_text(decision, pct))
                del self.answers[minute]

    def monitor(self):
        return run.monitor_milestones(self.proc, self.pacing, "async", self.ws, self.task,
                                      stop=lambda: self.events.append(("stop", self.clock.now)))


def test_pacing_is_one_fifteen_minute_wall_clock_with_a_budget_cap():
    """Reviews fall due exactly at 15/30/45/60 (never twice at one instant); active time is wall time."""
    clock = run.MilestonePacing(started_at=100, interval_minutes=15, budget_intervals=4)
    seen = []
    for minute in (15, 30, 45, 60):
        t = 100 + minute * 60
        assert not clock.due(t - 1) and clock.due(t) and clock.active_elapsed(t) == minute * 60
        seen.append(clock.next_milestone // 60)
        clock.advance()
        assert not clock.due(t)
    assert seen == [15, 30, 45, 60] and clock.maximum_active_seconds == 3600
    for bad in (dict(interval_minutes=10, budget_intervals=4), dict(interval_minutes=15, budget_intervals=1)):
        with pytest.raises(ValueError):
            run.MilestonePacing(started_at=0, **bad)


@pytest.mark.parametrize("decision,pct,minute,expected", [
    ("stalled", 0, 15, None), ("complete", 99, 15, None),            # protected first half hour
    ("stalled", 99, 30, "milestone-stalled-30min"), ("complete", 5, 30, "milestone-complete-30min"),
    ("continue", 0, 75, None), ("stalled", 99, 45, "milestone-stalled-45min")])
def test_the_judge_decides_the_stop_never_the_percentage(decision, pct, minute, expected):
    """Only a recorded complete/stalled decision from minute 30 ends a run; a low score alone never does."""
    assert run.milestone_terminal({"decision": decision, "usefulness_percent": pct}, minute, True) == expected


def test_progress_line_always_states_the_inferred_percentage_and_changes():
    """Each checkpoint report carries usefulness=NN% and the material changes; <30min says protected."""
    v = dict(json.loads(verdict_text("continue", 37)))
    assert "usefulness=37%" in run.milestone_progress(v, 45) and "decision=continue" in run.milestone_progress(v, 45)
    early = run.milestone_progress(v, 15)
    assert "protected" in early and v["material_changes"] in early


@pytest.mark.parametrize("raw", [verdict_text(decision="yes"), verdict_text(usefulness=101),
                                 verdict_text(usefulness=True), verdict_text(material_changes=None),
                                 verdict_text(material_changes=" "), verdict_text(evidence=[]),
                                 '{"decision": "complete", "usefulness_perc'])
def test_only_complete_holistic_verdicts_are_judgments(raw):
    """Unknown decision, out-of-range/bool percentage, missing material changes/evidence, partial JSON: no judgment."""
    assert milestones.parse(raw) is None
    assert milestones.parse(verdict_text())["decision"] == "continue"


@pytest.fixture
def world(tmp_path, monkeypatch):
    ws, task = tmp_path / "live", tmp_path / "task"
    (ws / "src").mkdir(parents=True)
    (ws / "src/a.py").write_text("a = 1\n")
    (ws / "b.txt").write_text("b\n")
    (task / "seed").mkdir(parents=True)
    (task / "seed/base.txt").write_text("baseline")
    (task / "prompt.txt").write_text("Deliver the answer.")
    (task / "meta.toml").write_text('budget_intervals = 2\nprivate_hint = "not a requirement"\n')
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
    return ws, task


def test_checkpoint_copy_is_frozen_honest_about_being_approximate_and_carries_context(world, monkeypatch):
    """The copy keeps tick-time bytes; the packet never claims the tree was unchanged (an mtime-restored edit
    can't be known), includes the baseline and prior judgments, and hides task metadata hints."""
    ws, task = world
    real = shutil.copytree

    def mutate_after_copy(src, dst, *a, **k):
        out = real(src, dst, *a, **k)
        info = (ws / "src/a.py").stat()
        (ws / "src/a.py").write_text("a = 2\n")
        os.utime(ws / "src/a.py", ns=(info.st_atime_ns, info.st_mtime_ns))
        return out

    prior = [{"at_active_minutes": 15, "checkpoint": "/prior/milestone", "usefulness_percent": 25,
              "decision": "continue", "reason": "substantial partial", "evidence": ["code.py"]}]
    monkeypatch.setattr(milestones.shutil, "copytree", mutate_after_copy)
    cp = milestones.create("r", 30, ws, task, prior, actual_active_seconds=1800.0)
    monkeypatch.undo()
    assert (cp / "workspace/src/a.py").read_text() == "a = 1\n"
    packet = (cp / "packet.txt").read_text()
    assert "LIVE workspace" in packet and "approximate" in packet and "unchanged" not in packet
    assert 'F "base.txt"' in packet and "25%" in packet and "/prior/milestone/workspace" in packet
    assert "Deliver the answer." in packet and "private_hint" not in packet
    assert json.loads((cp / "policy.json").read_text())["snapshot"] == {"mode": "live-unpaused", "errors": []}


def test_monitor_never_pauses_collects_each_late_judgment_and_ends_on_a_genuine_stop(tmp_path, monkeypatch):
    """Snapshots follow the schedule even when judges answer late; judgments are collected when recorded; the
    only control action is the terminal stop; each packet lists the previously judged snapshots."""
    rig = Rig(tmp_path, monkeypatch, answers={15: (1000, "continue", 20), 30: (2000, "continue", 20),
                                              45: (3000, "stalled", 20)})
    terminal, judgments = rig.monitor()
    assert terminal == "milestone-stalled-45min" and rig.events == [("stop", 3000)]
    assert [(j["at_active_minutes"], j["actual_active_seconds"], j["judged_at_active_seconds"]) for j in judgments] == \
        [(15, 900, 1000), (30, 1800, 2000), (45, 2700, 3000)]
    third = (milestones.ROOT / "async.045min/packet.txt").read_text()
    assert str(milestones.ROOT / "async.030min/workspace") in third and "NOT YET JUDGED" not in third


def test_unanswered_checkpoints_stay_pending_and_never_gain_an_invented_verdict(tmp_path, monkeypatch):
    """A checkpoint unanswered at natural exit stays pending (collectable later); a verdict recorded just before
    exit still counts; a pending one is listed in the next packet and never blocks it."""
    rig = Rig(tmp_path, monkeypatch, exits_at=2500, answers={15: (1900, "continue", 10)})
    terminal, judgments = rig.monitor()
    assert "Scheduled 15min checkpoint, NOT YET JUDGED" in (milestones.ROOT / "async.030min/packet.txt").read_text()
    assert terminal == "exited" and rig.events == []
    assert [j["status"] for j in judgments] == ["judged", "pending"] and "decision" not in judgments[1]
    assert milestones.pending() == [milestones.ROOT / "async.030min"]
    (tmp_path / "b").mkdir()
    late = Rig(tmp_path / "b", monkeypatch, exits_at=1000, answers={15: (999, "continue", 33)})
    assert late.monitor()[1][0]["usefulness_percent"] == 33


@pytest.mark.parametrize("code,expected", [(0, "exited"), (1, "harness-error")])
def test_a_natural_exit_before_the_first_checkpoint_needs_no_judgment(tmp_path, monkeypatch, code, expected):
    """The exit code alone classifies a short run; no checkpoint is cut before minute 15."""
    rig = Rig(tmp_path, monkeypatch, exits_at=20, exit_code=code)
    monkeypatch.setattr(milestones, "create", lambda *a, **k: pytest.fail("no checkpoint before minute 15"))
    assert rig.monitor() == (expected, [])


@pytest.mark.parametrize("scenario", ["files-changed", "mtime-only-touch", "newer-unanswered", "mid-copy-mutation"])
def test_no_file_state_or_newer_unanswered_checkpoint_vetoes_a_recorded_stop(tmp_path, monkeypatch, scenario):
    """Reviewer repros 1-5: the operator accepts mutable snapshots, so a stop judgment ends the run even when
    files changed after the snapshot, mtimes were touched, a newer checkpoint is unanswered, or a file mutated mid-copy."""
    answers = {15: (1000, "continue", 20), 30: (1900, "stalled", 20)}
    rig = Rig(tmp_path, monkeypatch, exits_at=4000, answers=answers)
    original = run.time.sleep

    def sleeping(seconds):
        original(seconds)
        if scenario == "files-changed" and rig.clock.now == 1850:
            (rig.ws / "code.py").write_text("working = 'more'\n")
            (rig.ws / "new.py").write_text("added = True\n")
        if scenario == "mtime-only-touch" and rig.clock.now == 1850:
            info = (rig.ws / "code.py").stat()
            os.utime(rig.ws / "code.py", ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))

    monkeypatch.setattr(run.time, "sleep", sleeping)
    if scenario == "newer-unanswered":
        rig.answers[30] = (2800, "stalled", 20)            # minute-45 checkpoint (cut at 2700) stays unanswered
    if scenario == "mid-copy-mutation":
        real = shutil.copytree
        monkeypatch.setattr(milestones.shutil, "copytree", lambda s, d, *a, **k: (
            real(s, d, *a, **k), (rig.ws / "code.py").write_text("changed during copy\n"))[0])
    terminal, judgments = rig.monitor()
    assert terminal == "milestone-stalled-30min" and len(rig.events) == 1 and "terminal_not_applied" not in judgments[1]


def test_the_newest_judged_checkpoint_decides_an_older_stop_is_superseded(tmp_path, monkeypatch):
    """A stale 30min stop recorded after 45min was judged continue is retained but not applied."""
    rig = Rig(tmp_path, monkeypatch, exits_at=3000,
              answers={15: (1000, "continue", 20), 45: (2800, "continue", 20), 30: (2900, "stalled", 20)})
    terminal, judgments = rig.monitor()
    assert terminal == "exited" and rig.events == []
    assert "newer checkpoint was already judged" in judgments[1]["terminal_not_applied"]
    assert judgments[1]["decision"] == "stalled" and judgments[2]["decision"] == "continue"


@pytest.mark.parametrize("failing", ["create", "poll"])
def test_an_interrupted_monitor_stops_the_owned_harness_and_never_signals_a_pause(tmp_path, monkeypatch, failing):
    """Ctrl-C while cutting a checkpoint or collecting a judgment stops the harness group (unattended runs must
    not leak a coder), and no SIGSTOP/SIGCONT is ever sent at a checkpoint."""
    rig = Rig(tmp_path, monkeypatch)
    signals = []
    monkeypatch.setattr(run.os, "killpg", lambda *a: signals.append(a))
    if failing == "create":
        monkeypatch.setattr(milestones, "create", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    else:
        monkeypatch.setattr(milestones, "poll", lambda _c: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        rig.monitor()
    assert len(rig.events) == 1 and signals == []
