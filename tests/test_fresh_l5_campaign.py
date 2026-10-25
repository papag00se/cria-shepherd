import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from suite import fresh_l5_campaign as campaign, sampling
from suite.run import capture_manifest, collect_capture, validate_fresh_l5_live_level
from cria.receivecapture import Receipt, metadata_path
from cria import callcapture


def candidate(tmp_path, **changes):
    archive = tmp_path / "archive"
    (archive / "workspace").mkdir(parents=True)
    capture = tmp_path / "calls"
    capture.mkdir()
    (capture / "0001-coder-s1.json").write_text(json.dumps({
        "seq": 1, "iso": "2026-08-20T02:08:16.280+00:00", "session": "session-id",
        "turn": "turn-id", "phase": "coder-s1", "url": "http://127.0.0.1:18084/v1/chat/completions",
        "stats": {"n_messages": 1, "n_tools": 1},
        "body": {"model": "cria", "temperature": 1.0, "top_p": 0.95,
                 "messages": [{"role": "user", "content": "x"}]},
        "rendered_prompt_file": "0001-coder-s1.prompt.txt",
    }))
    (capture / "0001-coder-s1.response.json").write_text(json.dumps({
        "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "ok"}}]
    }))
    row = {
        "model": campaign.MODELS[0], "task": campaign.TASKS[0], "level": 5,
        "sampling": sampling.render(campaign.MODELS[0]),
        "live_engagement_level": 5, "planner": "off", "planner_enabled": False,
        "planner_phase_count": 0, "revision": "rev-a", "note": "FRESH-L5 rev-a",
        "phases": {"coder": 1}, "calls": 1, "capture_dirs": [str(capture)],
        "archive": str(archive), "workspace_lost": False, "terminal": "exited",
        "started": time.time(), "wall_seconds": 1_000_000,
    }
    row.update(changes)
    return row


def test_worklist_is_exact_fresh_54_cell_grid_and_revision_pinned():
    cells = campaign.worklist("abc123", [])
    assert len(cells) == 54
    assert all(c["level"] == 5 and c["planner"] == "off" and c["revision"] == "abc123"
               for c in cells)
    assert {(c["model"], c["task"]) for c in cells} == {
        (model, task) for model in campaign.MODELS for task in campaign.TASKS
    }


def test_snapshot_must_be_nonempty_and_complete(tmp_path):
    row = candidate(tmp_path)
    row["capture_snapshot"] = {"complete": True, "entries": []}
    row["calls"] = 0
    row["phases"] = {}
    assert not campaign._valid_capture_evidence(row)

    row["calls"] = 1
    row["phases"] = {"coder": 1}
    row["capture_snapshot"] = capture_manifest(row["capture_dirs"])
    row["capture_snapshot"]["complete"] = False
    assert not campaign._valid_capture_evidence(row)


def test_snapshot_hashes_and_phase_inventory_must_match_captures(tmp_path):
    row = candidate(tmp_path)
    row["capture_snapshot"] = capture_manifest(row["capture_dirs"])
    assert campaign._valid_capture_evidence(row)

    row["capture_snapshot"]["entries"][0]["sha256"] = "0" * 64
    assert not campaign._valid_capture_evidence(row)


def test_worklist_credits_real_envelope_capture_and_matching_phase(tmp_path):
    row = candidate(tmp_path)
    assert campaign._valid_capture_evidence(row)
    cells = campaign.worklist("rev-a", [row])
    assert len(cells) == 53
    assert (row["model"], row["task"]) not in {(c["model"], c["task"]) for c in cells}


def test_worklist_rejects_requested_but_unobserved_or_invalid_candidates(tmp_path):
    row = candidate(tmp_path)
    rejected = (
        {**row, "level": 0}, {**row, "level": None}, {**row, "level": "5"},
        {**row, "live_engagement_level": 0}, {**row, "live_engagement_level": None},
        {**row, "terminal": "crashed-early"}, {**row, "terminal": "harness-error"},
        {**row, "terminal": None},
        {**row, "aborted": "throttled"}, {**row, "archive": str(tmp_path / "missing")},
        {**row, "workspace_lost": True}, {**row, "capture_dirs": []},
        {**row, "calls": 0}, {**row, "phases": {}},
        {**row, "planner": "on"}, {**row, "planner_enabled": True},
        {**row, "planner_phase_count": 1}, {**row, "revision": "rev-b"},
        {**row, "superseded": True}, {**row, "note": "old historical row"},
    )
    for invalid in rejected:
        assert len(campaign.worklist("rev-a", [invalid])) == 54

    request = tmp_path / "calls" / "0001-coder-s1.json"
    request_data = json.loads(request.read_text())
    request_data["phase"] = "proxy-s1"
    request.write_text(json.dumps(request_data))
    assert len(campaign.worklist("rev-a", [row])) == 54
    request_data["phase"] = "coder-s1"
    request.write_text(json.dumps(request_data))

    response = next((tmp_path / "calls").glob("*.response.json"))
    response.write_text("not json")
    assert len(campaign.worklist("rev-a", [row])) == 54


def test_requested_level_five_cannot_override_observed_live_level():
    with pytest.raises(RuntimeError, match="live cria engagement level 5, got 0"):
        validate_fresh_l5_live_level(True, 0)
    validate_fresh_l5_live_level(True, 5)
    validate_fresh_l5_live_level(False, 0)


def test_worklist_rejects_unpinned_revision():
    with pytest.raises(ValueError):
        campaign.worklist("")


def received_candidate(tmp_path, *, legacy=False):
    row = candidate(tmp_path)
    request = tmp_path / 'calls' / '0001-coder-s1.json'
    receipt = Receipt(request, request_sha256='a' * 64)
    receipt.finish()
    row['capture_snapshot'] = capture_manifest(row['capture_dirs'])
    if legacy:
        # Exact shape the old collector emitted for the transport's companion JSON.
        path = metadata_path(request)
        entry = {'request': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'phase': None, 'seq': 1, 'pending': True}
        row['capture_snapshot']['entries'] = [
            entry if e['request'] == str(path) else e
            for e in row['capture_snapshot']['entries']]
        if not any(e['request'] == str(path) for e in row['capture_snapshot']['entries']):
            row['capture_snapshot']['entries'].append(entry)
    return row, metadata_path(request)


def test_real_http_receipt_is_not_a_second_upstream_request(tmp_path):
    row, receipt = received_candidate(tmp_path)
    entries = row['capture_snapshot']['entries']
    assert [Path(e['request']).name for e in entries] == ['0001-coder-s1.json']
    assert collect_capture(row['capture_dirs'], row['capture_snapshot'])['calls'] == 1
    assert campaign._valid_capture_evidence(row)
    assert receipt.is_file()  # Never delete the actual transport evidence to fix the census.


def test_legacy_receipt_entry_is_verified_without_mutating_frozen_snapshot(tmp_path):
    row, _ = received_candidate(tmp_path, legacy=True)
    frozen = json.dumps(row)
    assert campaign._valid_capture_evidence(row)
    assert json.dumps(row) == frozen
    assert row['calls'] == 1
    assert row['phases'] == {'coder': 1}


def test_legacy_receipt_hash_tampering_still_fails_closed(tmp_path):
    row, receipt = received_candidate(tmp_path, legacy=True)
    receipt.write_bytes(receipt.read_bytes() + b' ')
    assert not campaign._valid_capture_evidence(row)


def test_upstream_request_cannot_hide_as_a_legacy_receipt(tmp_path):
    row, receipt = received_candidate(tmp_path, legacy=True)
    receipt.write_text(json.dumps({'phase': 'coder-s1', 'body': {'messages': []}}))
    row['capture_snapshot']['entries'][-1]['sha256'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert not campaign._valid_capture_evidence(row)


def test_legacy_receipt_without_its_primary_request_is_not_evidence(tmp_path):
    row, receipt = received_candidate(tmp_path, legacy=True)
    row['capture_snapshot']['entries'] = [e for e in row['capture_snapshot']['entries']
                                          if e['request'] == str(receipt)]
    row.update(calls=0, phases={})
    assert not campaign._valid_capture_evidence(row)


def test_pending_real_dotted_phase_and_its_receipt_are_not_hidden(tmp_path):
    from suite.walk import list_calls
    rlog = SimpleNamespace(session=str(tmp_path), emit=lambda *args, **kwargs: None)
    path = Path(callcapture.capture({'messages': []}, rlog, calls_dir=tmp_path,
                                    phase='custom.json.receive'))
    Receipt(path, request_sha256='a' * 64).finish()
    snapshot = capture_manifest([path.parent])
    assert [e['phase'] for e in snapshot['entries']] == ['custom.json.receive']
    assert snapshot['entries'][0]['pending'] is True
    row = {'capture_snapshot': snapshot, 'capture_dirs': [str(path.parent)], 'calls': 0, 'phases': {}}
    assert campaign._valid_capture_evidence(row)
    assert [(phase, stem) for _, phase, stem in list_calls(path.parent)] == [
        ('custom.json.receive', path.with_suffix(''))]


def test_all_role_sampling_reads_real_requests_not_legacy_receipts(tmp_path):
    from suite.l0_campaign import actual_sampling
    row, _ = received_candidate(tmp_path, legacy=True)
    knobs = {'temperature': 1.0, 'top_p': 0.95}
    assert actual_sampling(row['capture_snapshot'], 'cria', knobs) == [
        {'request': str(tmp_path / 'calls' / '0001-coder-s1.json'), 'fields': knobs}]
