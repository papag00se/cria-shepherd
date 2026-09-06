import json
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "suite"))
import milestones  # noqa: E402
import run as suite_run  # noqa: E402


def _judgment(decision="continue", usefulness_percent=50):
    return {
        "usefulness_percent": usefulness_percent,
        "decision": decision,
        "reason": "The frozen workspace supports this holistic usefulness judgment.",
        "evidence": ["The implementation changed and the current checks are visible."],
    }


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
    assert "TASK METADATA" not in packet
    assert "private_hint" not in packet
    assert "TASK SLOTS" not in packet


def test_only_holistic_inference_decisions_are_accepted():
    raw = _judgment()
    assert milestones.parse(json.dumps(raw)) == raw
    assert milestones.parse('{"usefulness_percent":50,"decision":"yes","reason":"x","evidence":["x"]}') is None
    assert milestones.parse('{"decision":"continue","reason":"x","evidence":["x"]}') is None
    assert milestones.parse('{"usefulness_percent":101,"decision":"continue","reason":"x","evidence":["x"]}') is None
    assert milestones.parse('{"usefulness_percent":50,"decision":"continue","reason":"x","tasks":[]}') is None


def test_first_gate_is_30_minutes_and_has_no_numeric_completion_threshold():
    pacing = suite_run.MilestonePacing(started_at=0.0, interval_minutes=15, budget_intervals=5)
    assert pacing.next_milestone == 30 * 60
    assert pacing.maximum_active_seconds == 75 * 60
    assert suite_run.milestone_terminal(_judgment("continue"), 30, False) is None
    assert suite_run.milestone_terminal(_judgment("stalled"), 30, False) == \
        "milestone-stalled-30min"
    assert suite_run.milestone_terminal(_judgment("complete"), 30, False) == \
        "milestone-complete-30min"


def test_usefulness_means_model_written_work_the_user_does_not_have_to_write():
    milestone_prompt = (ROOT / "suite" / "prompts" / "milestone_judge.txt").read_text()
    final_prompt = (ROOT / "suite" / "prompts" / "usefulness_judge.txt").read_text()
    for prompt in (milestone_prompt, final_prompt):
        assert "so the user does not have to write it" in prompt
        assert "Correct, reusable model-authored code retains value" in prompt
        assert "pre-existing code is not work delivered by the model" in prompt
        assert "not a count of task items, lines, passed checks" in prompt
    assert "Do not continue merely because budget remains" in milestone_prompt
    assert "no substantial requested code is ordinarily stalled" in milestone_prompt
    assert "substantial correct partial work with a credible path forward" in milestone_prompt


def test_every_checkpoint_progress_report_states_the_usefulness_percentage():
    report = suite_run.milestone_progress(_judgment("continue", 37), 45)
    assert "45min" in report
    assert "usefulness=37%" in report
    assert "decision=continue" in report


def test_the_inferred_percentage_is_reported_but_never_mechanically_controls_the_run():
    assert suite_run.milestone_terminal(_judgment("continue", 1), 45, False) is None
    assert suite_run.milestone_terminal(_judgment("stalled", 99), 45, False) == \
        "milestone-stalled-45min"
    assert suite_run.milestone_terminal(_judgment("continue", 50), 60, False) is None
    assert suite_run.milestone_terminal(_judgment("continue", 50), 75, True) == "budget-killed"


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


def test_maximum_active_budget_is_fifteen_minutes_per_interval(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "meta.toml").write_text('budget_intervals = 3\n')
    assert suite_run.budget_intervals(task) == 3
    pacing = suite_run.MilestonePacing(started_at=0.0, interval_minutes=15,
                                       budget_intervals=suite_run.budget_intervals(task))
    assert pacing.maximum_active_seconds == 45 * 60


def test_waiting_for_the_judge_does_not_consume_active_time():
    pacing = suite_run.MilestonePacing(started_at=100.0, interval_minutes=15, budget_intervals=4)
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
