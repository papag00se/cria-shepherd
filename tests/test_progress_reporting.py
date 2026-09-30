from suite import milestones, progress_reports
from suite.run import MilestonePacing


def test_ten_minute_reports_are_independent_of_milestone_clock_and_never_control_run():
    clock = MilestonePacing(started_at=0, interval_minutes=15, budget_intervals=4)
    observed = []
    for now in (600, 1200, 1800, 2400):
        assert clock.progress_due(now)
        observed.append(clock.next_progress_report // 60)
        clock.advance_progress()
    assert observed == [10, 20, 30, 40]
    assert clock.next_milestone == 1800
    assert clock.due(1800)  # at 30 both independent judgments are due
    clock.advance()
    assert clock.next_milestone == 2700  # milestone schedule remains 30,45,...
    assert clock.progress_due(2400) is False


def test_every_judge_wait_is_excluded_from_active_time():
    clock = MilestonePacing(started_at=100, interval_minutes=15, budget_intervals=4)
    clock.record_pause(900)
    assert clock.active_elapsed(1000) == 0
    assert not clock.progress_due(699)
    assert clock.progress_due(1600)
    assert not clock.due(1900)
    assert clock.due(2800)


def test_progress_packet_freezes_workspace_and_compares_baseline_and_prior_report(tmp_path, monkeypatch):
    task = tmp_path / "task"
    (task / "seed").mkdir(parents=True)
    (task / "seed" / "base.txt").write_text("baseline\n")
    (task / "prompt.txt").write_text("implement a feature\n")
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "feature.py").write_text("v1\n")
    monkeypatch.setattr(progress_reports, "ROOT", tmp_path / "reports")
    path = progress_reports.create("run", 10, workspace, task,
                                   [{"minute": 10, "checkpoint": "/prior/checkpoint", "verdict": {"usefulness_percent": 8,
                                    "reason": "initial change", "evidence": ["feature.py"]}}])
    (workspace / "feature.py").write_text("v2\n")
    packet = (path / "packet.txt").read_text()
    assert 'F "base.txt"' in packet and "initial change" in packet
    assert f"BASELINE DIRECTORY (inspect read-only): {task / 'seed'}" in packet
    assert "/prior/checkpoint/workspace" in packet
    assert (path / "workspace" / "feature.py").read_text() == "v1\n"
    assert progress_reports.pending() == [path]
    assert progress_reports.parse('{"usefulness_percent": 12, "reason": "material change", "evidence": ["feature.py"]}')


def test_milestone_packet_has_baseline_and_prior_checkpoint_judgment(tmp_path, monkeypatch):
    task = tmp_path / "task"
    (task / "seed").mkdir(parents=True)
    (task / "seed" / "base.txt").write_text("starting point")
    (task / "prompt.txt").write_text("finish task")
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "code.py").write_text("actual work")
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
    path = milestones.create("run", 30, workspace, task,
        [{"at_active_minutes": 15, "checkpoint": "/prior/milestone", "usefulness_percent": 25, "decision": "continue",
          "reason": "substantial partial", "evidence": ["code.py"]}])
    packet = (path / "packet.txt").read_text()
    assert "BASELINE SEED TREE" in packet and 'F "base.txt"' in packet
    assert "25%" in packet and "substantial partial" in packet
    assert "/prior/milestone/workspace" in packet
