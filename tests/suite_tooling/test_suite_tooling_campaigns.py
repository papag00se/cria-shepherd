"""Restored L0/L5 and fresh-L5 campaign promises: planner stays off, a cell is never silently retried,
only fully evidenced and independently judged rows are credited, failed attempts are preserved unscored."""
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from suite import battery_run, fresh_l5_campaign as fresh, l0_campaign as campaign, restored_roles, sampling
from suite.run import capture_manifest

REV = "a" * 40


@pytest.mark.parametrize("name", ["", "../other", "x/y", "x y"])
def test_campaign_id_cannot_escape_the_state_directory(name):
    """campaign_dir refuses empty, traversal and separator-bearing ids."""
    with pytest.raises(ValueError):
        campaign.campaign_dir(name)


@pytest.mark.parametrize("level", [0, 5])
def test_manifest_is_48_fresh_pending_planner_off_cells_and_old_scores_earn_no_credit(level):
    """Historical rows (even 100%) never complete a fresh cell; the launch command has no --planner flag
    (launcher default is off) and carries the manifest level. 4a089fe7 had enabled planning at L5."""
    manifest = campaign.create_manifest("new", REV, {}, level=level)
    assert len(manifest["cells"]) == 48 and manifest["planner"] == "off" and manifest["level"] == level
    campaign.reconcile(manifest, [{"model": campaign.MODELS[0], "task": campaign.TASKS[0],
                                   "usefulness_percent": 100, "level": level}])
    assert all(c["state"] == "pending" for c in manifest["cells"])
    cmd = campaign.cell_command(manifest, manifest["cells"][0])
    assert cmd[cmd.index("--level") + 1] == str(level) and "--restored-fleet" in cmd
    assert "--planner" not in cmd and "--fresh-l5" not in cmd
    with pytest.raises(ValueError):
        campaign.create_manifest("x", REV, {}, level=3)


def test_interrupted_attempt_blocks_and_a_cell_awaits_judgment_before_the_next(monkeypatch):
    """A running cell with no result becomes blocked (never auto-retried); a valid row without a
    usefulness judgment stays awaiting, and only the judged one unlocks the next."""
    manifest = campaign.create_manifest("new", REV, {})
    manifest["cells"][1]["state"] = "running"
    campaign.reconcile(manifest, [])
    campaign.reconcile(manifest, [])
    assert manifest["cells"][1]["state"] == "blocked"          # and stays blocked on every later pass
    first = manifest["cells"][0]
    row = {"campaign_id": "new", "model": first["model"], "task": first["task"],
           "started": manifest["created"] + 1, "run_id": "one"}
    monkeypatch.setattr(campaign, "valid_row", lambda *_: True)
    monkeypatch.setattr(campaign, "judgment", lambda *_: None)
    campaign.reconcile(manifest, [row])
    assert first["state"] == "awaiting-usefulness"
    monkeypatch.setattr(campaign, "judgment", lambda *_: {"usefulness_percent": 0})
    campaign.reconcile(manifest, [row])
    assert first["state"] == "done"


def test_sampling_is_read_from_the_captured_upstream_wire(tmp_path):
    """A missing knob on the wire is invalid; at L5 judge calls (temp 0) are not mistaken for the coder."""
    knobs = {"temperature": 1.0, "top_k": 64}
    coder, judge = tmp_path / "coder.json", tmp_path / "judge.json"
    coder.write_text(json.dumps(dict(phase="coder-s1", body=dict(model="m", **knobs))))
    judge.write_text(json.dumps(dict(phase="classifier", body=dict(model="m", temperature=0.0))))
    snap = dict(entries=[dict(request=str(coder)), dict(request=str(judge))])
    with pytest.raises(ValueError):
        campaign.actual_sampling(snap, "m", knobs)
    assert campaign.actual_sampling(snap, "m", knobs, coder_only=True) == [dict(request=str(coder), fields=knobs)]
    coder.write_text(json.dumps(dict(phase="coder-s1", body=dict(model="m", temperature=1.0))))
    with pytest.raises(ValueError, match="sampling"):
        campaign.actual_sampling(snap, "m", knobs, coder_only=True)


def failed_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(fresh, "_valid_capture_evidence", lambda _, **kw: True)
    model, task, knobs = campaign.MODELS[1], campaign.TASKS[0], {"temperature": .6}
    snapshot = {"roles": {model: {"coder": knobs}}}
    manifest = campaign.create_manifest("current", REV, snapshot)
    cell = next(c for c in manifest["cells"] if (c["model"], c["task"]) == (model, task))
    cell.update(state="blocked", attempted_at=manifest["created"] + 1)
    (tmp_path / "workspace").mkdir()
    log = tmp_path / "harness.log"
    log.write_text("HTTP400")
    req = tmp_path / "request.json"
    req.write_text(json.dumps({"body": {"model": model, **knobs}}))
    capture = {"entries": [{"request": str(req)}]}
    row = {"campaign_id": "current", "run_id": "failed", "revision": REV, "code_revision": REV, "model": model,
           "task": task, "restored_fleet": True, "level": 0, "live_engagement_level": 0, "planner": "off",
           "planner_enabled": False, "planner_phase_count": 0, "pacing_policy": campaign.POLICY,
           "fleet_snapshot": snapshot, "capture_snapshot": capture, "archive": str(tmp_path),
           "harness_log": str(log), "source_coder_sampling": knobs,
           "actual_sent_sampling": campaign.actual_sampling(capture, model, knobs),
           "injected_sampling": [{"fields": knobs}], "started": manifest["created"] + 2,
           "terminal": "harness-error"}
    monkeypatch.setattr(campaign, "judgment", lambda _: pytest.fail("a failed cell must never be judged"))
    return manifest, cell, row, snapshot


def test_repair_preserves_the_failed_slot_unscored_unretried_and_detects_tampering(tmp_path, monkeypatch):
    """resume_after_repair consumes the infrastructure-failed slot: row untouched, never judged, never
    pending again; a later second repair keeps the first failure; tampering or a vanished row blocks it."""
    manifest, cell, row, snapshot = failed_fixture(tmp_path, monkeypatch)
    before = copy.deepcopy(row)
    campaign.resume_after_repair(manifest, REV, "b" * 40, snapshot, [row], failed_run_id="failed")
    assert row == before and cell["state"] == "infrastructure-failed" and "judgment" not in cell
    assert not campaign.valid_row(row, manifest)             # never scoreable
    campaign.reconcile(manifest, [row])
    assert cell["state"] == "infrastructure-failed"
    assert sum(c["state"] == "pending" for c in manifest["cells"]) == 47
    saved = copy.deepcopy(manifest["preserved_runs"]["failed"])
    campaign.resume_after_repair(manifest, "b" * 40, "c" * 40, snapshot, [row])
    assert manifest["preserved_runs"]["failed"] == saved
    tampered = copy.deepcopy(manifest)
    campaign.reconcile(manifest, [])                         # disappeared evidence blocks, never relaunches
    assert cell["state"] == "blocked"
    campaign.reconcile(tampered, [{**row, "note": "tampered"}])
    assert next(c for c in tampered["cells"] if c.get("run_id") == "failed")["state"] == "blocked"


@pytest.mark.parametrize("change", ["duplicate", "other_campaign", "predates_manifest", "natural_terminal",
                                    "wrong_revision", "wrong_run_id", "cell_not_blocked", "cell_other_run", "missing_archive"])
def test_repair_refuses_unproven_or_unrelated_failures_and_leaves_manifest_alone(tmp_path, monkeypatch, change):
    """Only an exact, fresh, blocked, harness-error attempt may be preserved; anything else raises unchanged."""
    manifest, cell, row, snapshot = failed_fixture(tmp_path, monkeypatch)
    rows = [row]
    if change == "duplicate":
        rows.append(copy.deepcopy(row))
    elif change == "other_campaign":
        row["campaign_id"] = "other"
    elif change == "predates_manifest":
        row["started"] = manifest["created"] - 1
    elif change == "natural_terminal":
        row["terminal"] = "model-done"
    elif change == "wrong_revision":
        row["revision"] = "c" * 40
    elif change == "wrong_run_id":
        row["run_id"] = "unrelated"
    elif change == "cell_not_blocked":
        cell["state"] = "running"
    elif change == "cell_other_run":
        cell["run_id"] = "someone-else"
    else:
        row["archive"] = str(tmp_path / "missing")
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError):
        campaign.resume_after_repair(manifest, REV, "b" * 40, snapshot, rows, failed_run_id="failed")
    assert manifest == before


def test_l5_row_is_valid_only_with_role_config_and_wire_bound_to_the_manifest(tmp_path, monkeypatch):
    """Active config must equal the roles render of the snapshot's config; a planner override added later invalidates."""
    model, task = campaign.MODELS[0], campaign.TASKS[0]
    roles = {r: {"temperature": float(i)} for i, r in enumerate(("coder", "reasoner", "classifier", "compactor"))}
    source = Path("cria.example.toml").read_bytes()
    before, active = tmp_path / "before.toml", tmp_path / "active.toml"
    before.write_bytes(source)
    active.write_text(restored_roles.render(source.decode(), roles))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    snapshot = dict(roles={model: roles}, live_config=dict(sha256=digest(before)))
    manifest = campaign.create_manifest("new", REV, snapshot, level=5)
    archive = tmp_path / "archive"
    (archive / "workspace").mkdir(parents=True)
    log = tmp_path / "run.log"
    log.write_text("terminal")
    request = tmp_path / "coder.json"
    request.write_text(json.dumps(dict(phase="coder-s1", body=dict(model=model, **roles["coder"]))))
    capture = dict(entries=[dict(request=str(request))])
    row = dict(campaign_id="new", revision=REV, code_revision=REV, model=model, task=task, restored_fleet=True,
               level=5, live_engagement_level=5, planner="off", planner_enabled=False, planner_phase_count=0,
               pacing_policy=campaign.POLICY, fleet_snapshot=snapshot, capture_snapshot=capture,
               archive=str(archive), harness_log=str(log), source_coder_sampling=roles["coder"],
               actual_sent_sampling=campaign.actual_sampling(capture, model, roles["coder"], coder_only=True),
               injected_sampling=[dict(fields=roles["coder"])], live_config_snapshot=dict(sha256=digest(active)),
               restored_role_config=dict(before=str(before), active=str(active), roles=roles,
                                         active_sha256=digest(active)))
    monkeypatch.setattr(fresh, "_valid_capture_evidence", lambda *a, **k: True)
    assert campaign.valid_row(row, manifest) and not campaign.valid_row({**row, "level": 0}, manifest)
    active.write_text(active.read_text() + "\n[planner_override]\nenabled=true\n")
    assert not campaign.valid_row(row, manifest)


def test_restored_battery_delegates_without_touching_the_live_arm_and_legacy_arms_keep_planner_off(monkeypatch, tmp_path):
    """--restored-fleet launches run.py through the campaign path (no set_level); legacy BASE/CRIA arms pass
    `--planner off` (4a089fe7: selecting full engagement must not opt into planning); cells have no timeout cap."""
    calls = []
    monkeypatch.setattr(battery_run.run_guard, "other_suite_runners", lambda: [])
    monkeypatch.setattr(battery_run, "sh", lambda *cmd, **kw: calls.append(cmd) or 0)
    monkeypatch.setattr(campaign, "fleet_snapshot", lambda **kw: {})
    monkeypatch.setattr(campaign, "validate_revision", lambda v: v)
    monkeypatch.setattr(battery_run, "set_level", lambda *_: pytest.fail("restored run must not edit the live arm"))
    monkeypatch.setattr(sys, "argv", ["battery_run.py", "--level", "5", "--model", "gemma4_12b", "--task",
                                      campaign.TASKS[0], "--restored-fleet", "--campaign-id", "today",
                                      "--campaign-revision", REV])
    assert battery_run.main() == 0
    assert "--restored-fleet" in calls[0] and calls[0][calls[0].index("--level") + 1] == "5"
    assert "--planner" not in calls[0] or calls[0][calls[0].index("--planner") + 1] == "off"
    assert battery_run.cell_timeout() is None
    monkeypatch.undo()
    for arm in ("BASE", "CRIA"):
        config = tmp_path / f"{arm}.toml"
        config.write_text("[engagement]\nlevel = 5\n")
        calls.clear()
        monkeypatch.setattr(battery_run.run_guard, "other_suite_runners", lambda: [])
        monkeypatch.setattr(battery_run, "TOML", config)
        monkeypatch.setattr(battery_run, "sh", lambda *cmd, **kw: calls.append(cmd) or 0)
        monkeypatch.setattr(sys, "argv", ["battery_run.py", "--arm", arm, "--model", "m", "--task", "t"])
        assert battery_run.main() == 0
        cmd = next(c for c in calls if str(battery_run.SUITE / "run.py") in c)
        assert cmd[cmd.index("--planner") + 1] == "off"
        monkeypatch.undo()


def candidate(tmp_path, **changes):
    archive = tmp_path / "archive"
    (archive / "workspace").mkdir(parents=True)
    calls = tmp_path / "calls"
    calls.mkdir()
    body = {"model": "cria", "temperature": 1.0, "top_p": 0.95, "messages": [{"role": "user", "content": "x"}]}
    (calls / "0001-coder-s1.json").write_text(json.dumps({"seq": 1, "phase": "coder-s1", "body": body}))
    (calls / "0001-coder-s1.response.json").write_text(json.dumps({"choices": [{"message": {"content": "ok"}}]}))
    row = {"model": fresh.MODELS[0], "task": fresh.TASKS[0], "level": 5, "sampling": sampling.render(fresh.MODELS[0]),
           "live_engagement_level": 5, "planner": "off", "planner_enabled": False, "planner_phase_count": 0,
           "revision": "rev-a", "note": "FRESH-L5 rev-a", "phases": {"coder": 1}, "calls": 1,
           "capture_dirs": [str(calls)], "archive": str(archive), "workspace_lost": False, "terminal": "exited",
           "started": time.time(), "wall_seconds": 1_000_000}
    row.update(changes)
    return row


def test_fresh_worklist_is_the_exact_pinned_grid_and_credits_only_observed_evidence(tmp_path):
    """54 pending cells at L5/planner off; a row is credited only when observed (not merely requested)."""
    assert len(fresh.worklist("abc", [])) == 54
    with pytest.raises(ValueError):
        fresh.worklist("")
    row = candidate(tmp_path)
    assert len(fresh.worklist("rev-a", [row])) == 53
    bad = [{"level": 0}, {"level": "5"}, {"live_engagement_level": 0}, {"terminal": "harness-error"},
           {"aborted": "throttled"}, {"workspace_lost": True}, {"calls": 0}, {"planner": "on"},
           {"planner_phase_count": 1}, {"revision": "rev-b"}, {"superseded": True}, {"note": "old historical row"},
           {"archive": str(tmp_path / "missing")}]
    for change in bad:
        assert len(fresh.worklist("rev-a", [{**row, **change}])) == 54, change
    request = tmp_path / "calls/0001-coder-s1.json"
    data = json.loads(request.read_text())
    request.write_text(json.dumps({**data, "phase": "proxy-s1"}))
    assert len(fresh.worklist("rev-a", [row])) == 54            # capture is not a coder call
    request.write_text(json.dumps(data))
    next((tmp_path / "calls").glob("*.response.json")).write_text("not json")
    assert len(fresh.worklist("rev-a", [row])) == 54


def test_capture_snapshot_must_be_complete_nonempty_and_hash_matched(tmp_path):
    """Empty/incomplete snapshots and a changed request hash fail evidence validation."""
    row = candidate(tmp_path)
    row["capture_snapshot"] = capture_manifest(row["capture_dirs"])
    assert fresh._valid_capture_evidence(row)
    row["capture_snapshot"]["entries"][0]["sha256"] = "0" * 64
    assert not fresh._valid_capture_evidence(row)
    row["capture_snapshot"] = {"complete": True, "entries": []}
    assert not fresh._valid_capture_evidence(row)
    row["capture_snapshot"] = {**capture_manifest(row["capture_dirs"]), "complete": False}
    assert not fresh._valid_capture_evidence(row)


def late(tmp_path):
    """A row stopped at t=100 whose second request got its response at t=200 (after the cutoff)."""
    row = candidate(tmp_path, revision="fixed-sha", note="FRESH-L5 fixed-sha", terminal="milestone-stalled-45min",
                    started=50, wall_seconds=50)
    calls, archive = Path(row["capture_dirs"][0]), Path(row["archive"]) / "workspace"
    target = archive / "src/Importer.java"
    target.parent.mkdir(parents=True)
    target.write_text("unchanged before late response\n")
    body = {"temperature": 1.0, "top_p": 0.95, "messages": [{"role": "user", "content": "task"}]}
    (calls / "0002-coder-s1.json").write_text(json.dumps({"seq": 2, "phase": "coder-s1", "body": body}))
    (calls / "0002-coder-s1.response.json").write_text(json.dumps({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "edit_file", "arguments": json.dumps({"path": "src/Importer.java"})}}]}}]}))
    for p in (archive, target, *calls.glob("000[12]-coder-s1.json"), calls / "0001-coder-s1.response.json"):
        os.utime(p, (100, 100))
    os.utime(calls / "0002-coder-s1.response.json", (200, 200))
    return row, calls, target


def test_a_response_after_the_stop_is_preserved_but_never_credited_and_cannot_hide_a_late_edit(tmp_path):
    """The measured row stays eligible with calls=1 (the late reply is evidence, not a call) — unless the
    late reply is a planner call, belongs to another revision, or its edit touched the archived workspace."""
    row, calls, target = late(tmp_path)
    assert fresh._eligible(row, "fixed-sha") and not fresh._eligible(row, "different-sha")
    remaining = fresh.worklist("fixed-sha", [row])
    assert len(remaining) == 53 and (row["model"], row["task"]) not in {(c["model"], c["task"]) for c in remaining}
    os.utime(target, (250, 250))
    assert not fresh._eligible(row, "fixed-sha")
    os.utime(target, (100, 100))
    request = calls / "0002-coder-s1.json"
    request.write_text(request.read_text().replace("coder-s1", "planner-s1"))
    assert not fresh._eligible(row, "fixed-sha")


