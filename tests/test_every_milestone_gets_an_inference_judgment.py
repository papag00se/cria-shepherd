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
    (task / "meta.toml").write_text('budget_intervals = 2\nprivate_hint = "not a requirement"\n')
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "checkpoints")

    checkpoint = milestones.create("run-1", 30, workspace, task)
    (workspace / "answer.txt").write_text("after the tick\n")

    assert (checkpoint / "workspace" / "answer.txt").read_text() == "at the tick\n"
    packet = (checkpoint / "packet.txt").read_text()
    assert "run-1 at 30 active minutes" in packet
    assert str(checkpoint / "workspace") in packet
    assert "Deliver the answer." in packet
    assert "TASK SLOTS: 2" in packet
    assert "TASK METADATA" not in packet
    assert "private_hint" not in packet


def _judgment(*states):
    return {
        "reason": "The frozen workspace establishes these task states.",
        "tasks": [
            {"name": f"task {i}", "state": state, "evidence": f"evidence {i}"}
            for i, state in enumerate(states, 1)
        ],
    }


def test_only_typed_task_inference_is_accepted():
    raw = _judgment("complete", "partial", "missing")
    assert milestones.parse(json.dumps(raw), expected_tasks=3) == raw
    assert milestones.parse(json.dumps(raw), expected_tasks=4) is None
    assert milestones.parse(json.dumps({"reason": "x", "tasks": []}), expected_tasks=3) is None
    bad = _judgment("delivered", "partial", "missing")
    assert milestones.parse(json.dumps(bad), expected_tasks=3) is None


def test_first_gate_is_30_minutes_and_two_complete_tasks_earn_more_time():
    pacing = suite_run.MilestonePacing(started_at=0.0, task_minutes=15, task_count=5)
    assert pacing.next_milestone == 30 * 60
    assert pacing.maximum_active_seconds == 75 * 60
    assert suite_run.milestone_terminal(_judgment("complete", "complete", "partial", "missing", "missing"),
                                        30, False) is None
    assert suite_run.milestone_terminal(_judgment("complete", "partial", "partial", "missing", "missing"),
                                        30, False) == "milestone-quota-miss-30min"


def test_each_later_gate_requires_one_more_complete_task_in_any_order():
    assert suite_run.milestone_terminal(
        _judgment("partial", "complete", "complete", "complete", "missing"), 45, False) is None
    assert suite_run.milestone_terminal(
        _judgment("complete", "complete", "partial", "complete", "missing"), 60, False
    ) == "milestone-quota-miss-60min"
    assert suite_run.milestone_terminal(
        _judgment("complete", "complete", "complete", "complete", "complete"), 75, True
    ) == "milestone-complete-75min"


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


def test_maximum_active_budget_is_15_minutes_per_task(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "meta.toml").write_text('budget_intervals = 3\n')
    assert suite_run.budget_intervals(task) == 3
    pacing = suite_run.MilestonePacing(started_at=0.0, task_minutes=15,
                                       task_count=suite_run.budget_intervals(task))
    assert pacing.maximum_active_seconds == 45 * 60


def test_waiting_for_the_judge_does_not_consume_active_time():
    pacing = suite_run.MilestonePacing(started_at=100.0, task_minutes=15, task_count=4)
    assert not pacing.due(1899.9)
    assert pacing.due(1900.0)
    pacing.record_pause(40.0)
    assert not pacing.due(1939.9)
    assert pacing.due(1940.0)
    assert not pacing.at_limit
    pacing.advance()
    assert pacing.next_milestone == 45 * 60
    pacing.advance()
    assert pacing.at_limit
