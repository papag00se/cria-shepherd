import inspect
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "suite"))
import milestones  # noqa: E402
import run as suite_run  # noqa: E402


def test_checkpoint_freezes_the_workspace_for_read_only_inspection(tmp_path, monkeypatch):
    workspace = tmp_path / "live"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("at the tick\n")
    task = tmp_path / "task"
    task.mkdir()
    (task / "prompt.txt").write_text("Deliver the answer.")
    (task / "meta.toml").write_text('deliverables = ["answer"]\n')
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "checkpoints")

    checkpoint = milestones.create("run-1", 30, workspace, task)
    (workspace / "answer.txt").write_text("after the tick\n")

    assert (checkpoint / "workspace" / "answer.txt").read_text() == "at the tick\n"
    packet = (checkpoint / "packet.txt").read_text()
    assert "run-1 at 30 active minutes" in packet
    assert str(checkpoint / "workspace") in packet


def test_only_inference_decisions_are_accepted():
    assert milestones.parse(json.dumps({
        "decision": "continue", "reason": "Real implementation exists. More work remains.",
        "deliverables": []})) == {
            "decision": "continue", "reason": "Real implementation exists. More work remains.",
            "deliverables": []}
    assert milestones.parse('{"decision":"yes","reason":"x","deliverables":[]}') is None
    assert milestones.parse('{"decision":"continue","deliverables":[]}') is None


def test_runner_pauses_and_waits_at_every_interval():
    src = inspect.getsource(suite_run.main)
    assert "next_milestone = milestone_s" in src
    assert "pause_run()" in src
    assert "milestones.create(" in src
    assert "milestones.wait(" in src
    assert "next_milestone += milestone_s" in src


def test_inference_controls_whether_another_interval_is_earned():
    assert suite_run.milestone_terminal("complete", 30, False) == "milestone-complete-30min"
    assert suite_run.milestone_terminal("stalled", 30, False) == "milestone-stalled-30min"
    assert suite_run.milestone_terminal("continue", 30, False) is None
    assert suite_run.milestone_terminal("continue", 150, True) == "budget-killed"


def test_waiting_for_the_judge_does_not_consume_active_time():
    src = inspect.getsource(suite_run.main)
    assert "time.time() - t0 - paused_seconds" in src
    assert "paused_seconds += time.time() - pause_started" in src


def test_maximum_active_budget_tracks_declared_deliverables():
    src = inspect.getsource(suite_run.main)
    assert "wall = milestone_s * deliverable_count(task_dir)" in src
