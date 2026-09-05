import json
import sys
import tomllib
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
    (task / "meta.toml").write_text('budget_intervals = 1\nprivate_hint = "not a requirement"\n')
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "checkpoints")

    checkpoint = milestones.create("run-1", 30, workspace, task)
    (workspace / "answer.txt").write_text("after the tick\n")

    assert (checkpoint / "workspace" / "answer.txt").read_text() == "at the tick\n"
    packet = (checkpoint / "packet.txt").read_text()
    assert "run-1 at 30 active minutes" in packet
    assert str(checkpoint / "workspace") in packet
    assert "Deliver the answer." in packet
    assert "TASK METADATA" not in packet
    assert "private_hint" not in packet


def test_only_inference_decisions_are_accepted():
    assert milestones.parse(json.dumps({
        "decision": "continue", "reason": "Real implementation exists. More work remains.",
        "deliverables": []})) == {
            "decision": "continue", "reason": "Real implementation exists. More work remains.",
            "deliverables": []}
    assert milestones.parse('{"decision":"yes","reason":"x","deliverables":[]}') is None
    assert milestones.parse('{"decision":"continue","deliverables":[]}') is None


def test_inference_controls_whether_another_interval_is_earned():
    assert suite_run.milestone_terminal("complete", 30, False) == "milestone-complete-30min"
    assert suite_run.milestone_terminal("stalled", 30, False) == "milestone-stalled-30min"
    assert suite_run.milestone_terminal("continue", 30, False) is None
    assert suite_run.milestone_terminal("continue", 150, True) == "budget-killed"


def test_every_task_declares_an_integer_budget_not_a_second_judgment_contract():
    for prompt_path in sorted((ROOT / "suite" / "tasks").glob("*/prompt.txt")):
        task_dir = prompt_path.parent
        meta_path = task_dir / "meta.toml"
        assert meta_path.is_file(), f"{task_dir.name} has no pacing metadata"
        meta = tomllib.loads(meta_path.read_text())
        with_budget = meta.get("budget_intervals")
        assert isinstance(with_budget, int) and not isinstance(with_budget, bool)
        assert with_budget > 0
        assert "deliverables" not in meta


def test_maximum_active_budget_tracks_only_the_declared_budget(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "meta.toml").write_text('budget_intervals = 3\n')
    assert suite_run.budget_intervals(task) == 3
    pacing = suite_run.MilestonePacing(started_at=0.0, interval_seconds=7 * 60,
                                       budget_intervals=suite_run.budget_intervals(task))
    assert pacing.maximum_active_seconds == 21 * 60


def test_waiting_for_the_judge_does_not_consume_active_time():
    pacing = suite_run.MilestonePacing(started_at=100.0, interval_seconds=60,
                                       budget_intervals=3)
    assert not pacing.due(159.9)
    assert pacing.due(160.0)
    pacing.record_pause(40.0)
    assert not pacing.due(199.9)
    assert pacing.due(200.0)
    assert not pacing.at_limit
    pacing.advance()
    assert pacing.next_milestone == 120
    pacing.advance()
    assert pacing.at_limit
