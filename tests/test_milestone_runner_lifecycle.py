"""Exercise the actual runner monitor with fake time/process and real frozen packets; no models."""
import json
from types import SimpleNamespace
import pytest
from suite import run, milestones


def rig(tmp_path, monkeypatch, *, exits_at=None, exit_code=0):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(run.time, "time", lambda: clock.now)
    def sleep(seconds):
        clock.now += seconds
    monkeypatch.setattr(run.time, "sleep", sleep)
    proc = SimpleNamespace(poll=lambda: exit_code if exits_at is not None and clock.now >= exits_at else None)
    ws = tmp_path / "live"
    ws.mkdir()
    (ws / "code.py").write_text("working = True\n")
    task = tmp_path / "task"
    task.mkdir()
    (task / "prompt.txt").write_text("Deliver useful code.")
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
    pacing = run.MilestonePacing(0, 15, 2)
    events = []
    callbacks = dict(pause=lambda: events.append(("pause", clock.now)) or True,
                     resume=lambda: events.append(("resume", clock.now)),
                     stop=lambda: events.append(("stop", clock.now)))
    return clock, proc, ws, task, pacing, events, callbacks


def test_full_monitor_protects_fifteen_reports_once_and_compares_every_snapshot(tmp_path, monkeypatch, capsys):
    clock, proc, ws, task, pacing, events, callbacks = rig(tmp_path, monkeypatch)
    seen = []
    def judge(checkpoint):
        minute = pacing.next_milestone // 60
        packet = (checkpoint / "packet.txt").read_text()
        if seen:
            assert str(seen[-1] / "workspace") in packet
        seen.append(checkpoint)
        clock.now += 120  # judge wait must not spend coder time
        return milestones.parse(json.dumps(dict(usefulness_percent=20, decision=(
            "stalled" if minute in (15, 45) else "continue"), reason="Inspected current and prior work.",
            evidence=["code.py"], material_changes=f"Inspected changes at {minute} minutes.")))
    monkeypatch.setattr(milestones, "wait", judge)
    terminal, judgments = run.monitor_milestones(proc, pacing, "one", ws, task, **callbacks)
    assert terminal == "milestone-stalled-45min"
    assert [j["at_active_minutes"] for j in judgments] == [15, 30, 45]
    assert pacing.active_elapsed(clock.now) == 45 * 60  # legacy 30-minute budget did not stop it
    assert events == [("pause", 900), ("resume", 1020), ("pause", 1920),
                      ("resume", 2040), ("pause", 2940), ("stop", 3060)]
    log = capsys.readouterr().out
    assert log.count("usefulness=20%") == 3
    assert log.count("[material changes]") == 3


@pytest.mark.parametrize("exit_code, expected", [(0, "exited"), (1, "harness-error")])
def test_natural_early_completion_needs_no_milestone_or_padding(tmp_path, monkeypatch, exit_code, expected):
    _, proc, ws, task, pacing, events, callbacks = rig(tmp_path, monkeypatch, exits_at=20, exit_code=exit_code)
    monkeypatch.setattr(milestones, "wait", lambda _: pytest.fail("no checkpoint before minute 15"))
    terminal, judgments = run.monitor_milestones(proc, pacing, "early", ws, task, **callbacks)
    assert terminal == expected
    assert judgments == [] and events == []


def test_interrupted_judgment_stops_the_owned_harness_not_leaves_it_paused(tmp_path, monkeypatch):
    _, proc, ws, task, pacing, events, callbacks = rig(tmp_path, monkeypatch)
    def interrupted(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(milestones, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run.monitor_milestones(proc, pacing, "interrupt", ws, task, **callbacks)
    assert events == [("pause", 900), ("stop", 900)]
