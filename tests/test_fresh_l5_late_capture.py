import json
import os
from pathlib import Path

from suite import fresh_l5_campaign as campaign, sampling


def _late_candidate(tmp_path):
    row = {
        "model": "gemma4-qat", "task": "feed-pipeline-java", "level": 5,
        "sampling": sampling.render("gemma4-qat"),
        "live_engagement_level": 5, "planner": "off", "planner_enabled": False,
        "planner_phase_count": 0, "revision": "fixed-sha", "note": "FRESH-L5 fixed-sha",
        "phases": {"coder": 1}, "calls": 1, "archive": str(tmp_path / "archive"),
        "workspace_lost": False, "terminal": "milestone-stalled-45min", "started": 50,
        "wall_seconds": 50,
    }
    archive = Path(row["archive"]) / "workspace"
    target = archive / "src/Importer.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unchanged before late response\n")
    calls = tmp_path / "calls"
    calls.mkdir(exist_ok=True)
    request = {
        "seq": 1, "phase": "coder-s1",
        "body": {"temperature": 1.0, "top_p": 0.95,
                 "messages": [{"role": "user", "content": "task"}]},
    }
    (calls / "0001-coder-s1.json").write_text(json.dumps(request))
    (calls / "0001-coder-s1.response.json").write_text(json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "done"}}]
    }))
    pending = {
        "seq": 2, "phase": "coder-s1",
        "body": {"temperature": 1.0, "top_p": 0.95,
                 "messages": [{"role": "user", "content": "task"}]},
    }
    (calls / "0002-coder-s1.json").write_text(json.dumps(pending))
    (calls / "0002-coder-s1.response.json").write_text(json.dumps({
        "choices": [{"message": {"role": "assistant", "tool_calls": [{
            "function": {"name": "edit_file", "arguments": json.dumps({
                "path": "src/Importer.java", "old_string": "old", "new_string": "new"
            })}
        }]}}]
    }))
    for path in [archive, target, calls / "0001-coder-s1.json",
                 calls / "0001-coder-s1.response.json", calls / "0002-coder-s1.json"]:
        os.utime(path, (100, 100))
    os.utime(calls / "0002-coder-s1.response.json", (200, 200))
    row["capture_dirs"] = [str(calls)]
    row["capture_dir"] = str(calls)
    return row


def test_late_response_is_preserved_but_not_credited_to_the_measured_row(tmp_path):
    row = _late_candidate(tmp_path)
    assert campaign._valid_capture_evidence(row)
    assert campaign._eligible(row, "fixed-sha")
    assert campaign._eligible(row, "fixed-sha")  # stable after the late response already exists
    remaining = campaign.worklist("fixed-sha", [row])
    assert len(remaining) == 53
    assert remaining[0]["task"] == "shipping-rates-rb"
    assert ("gemma4-qat", "feed-pipeline-java") not in {
        (cell["model"], cell["task"]) for cell in remaining
    }


def test_equal_response_count_cannot_replace_a_missing_on_time_response_with_late_one(tmp_path):
    row = _late_candidate(tmp_path)
    calls = Path(row["capture_dirs"][0])
    third_request = {
        "seq": 3, "phase": "coder-s1",
        "body": {"temperature": 1.0, "top_p": 0.95,
                 "messages": [{"role": "user", "content": "task"}]},
    }
    request = calls / "0003-coder-s1.json"
    response = calls / "0003-coder-s1.response.json"
    request.write_text(json.dumps(third_request))
    response.write_text(json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "on time"}}]
    }))
    os.utime(request, (100, 100))
    os.utime(response, (100, 100))
    # Two response files remain for a two-call row, but one is the late reply and
    # the other on-time reply was deleted. The pending 0002 response is not a call.
    (calls / "0001-coder-s1.response.json").unlink()
    row["calls"] = 2
    row["phases"] = {"coder": 2}
    assert len(list(calls.glob("*.response.json"))) == row["calls"]
    assert not campaign._valid_capture_evidence(row)


def test_late_response_does_not_weaken_planner_or_revision_guards(tmp_path):
    row = _late_candidate(tmp_path)
    request = Path(row["capture_dirs"][0]) / "0002-coder-s1.json"
    body = json.loads(request.read_text())
    body["phase"] = "planner-s1"
    request.write_text(json.dumps(body))
    assert not campaign._eligible(row, "fixed-sha")

    row = _late_candidate(tmp_path)
    assert not campaign._eligible(row, "different-sha")


def test_late_edit_touching_the_archived_target_is_not_eligible(tmp_path):
    row = _late_candidate(tmp_path)
    target = Path(row["archive"]) / "workspace/src/Importer.java"
    os.utime(target, (250, 250))
    assert not campaign._eligible(row, "fixed-sha")
