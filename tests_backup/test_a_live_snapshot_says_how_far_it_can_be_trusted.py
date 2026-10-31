"""A checkpoint copies the LIVE workspace (nothing is paused), so the copy says plainly that it is approximate. The
operator accepts mutable, approximate snapshots: nothing is fingerprinted, locked or retried, and no file state can veto a
recorded judgment (see test_milestone_runner_lifecycle). CPU/filesystem only."""
import json
import os
import shutil

import pytest

from suite import milestones


@pytest.fixture
def world(tmp_path, monkeypatch):
    ws, task = tmp_path / "live", tmp_path / "task"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.py").write_text("a = 1\n")
    (ws / "b.txt").write_text("b\n")
    task.mkdir()
    (task / "prompt.txt").write_text("Deliver.")
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "milestones")
    return ws, task


def valid(decision="continue"):
    return json.dumps(dict(usefulness_percent=10, decision=decision, reason="r", evidence=["e"],
                           material_changes="m", requirements=[dict(requirement="q", status="partial", evidence="e")],
                           pace_reason="p"))


def test_a_quiet_copy_says_it_is_approximate_and_records_only_mode_and_copy_errors(world):
    ws, task = world
    checkpoint = milestones.create("r", 15, ws, task, actual_active_seconds=900.0)
    policy = json.loads((checkpoint / "policy.json").read_text())
    assert policy["pacing_policy"] == milestones.JUDGMENT_POLICY == "requirement-pace-15m-protected-30m-v3-async-live-snapshot"
    assert policy["snapshot"] == {"mode": "live-unpaused", "errors": []}      # no fingerprint, no stability claim
    assert (checkpoint / "workspace" / "src" / "a.py").read_text() == "a = 1\n"
    packet = (checkpoint / "packet.txt").read_text()
    assert "SNAPSHOT CONDITIONS: Copied from the LIVE workspace while the coder kept running" in packet
    assert "approximate" in packet and "may have changed during or after the copy" in packet


def test_the_packet_never_asserts_the_tree_was_unchanged_when_metadata_cannot_know(world, monkeypatch):
    # Reviewer finding: bytes changed under a restored mtime; any 'did not change' claim would be a made-up world fact.
    ws, task = world
    real_copytree = shutil.copytree
    def mutate_after_copy(src, dst, *args, **kwargs):
        result = real_copytree(src, dst, *args, **kwargs)
        info = (ws / "src" / "a.py").stat()
        (ws / "src" / "a.py").write_text("a = 2\n")
        os.utime(ws / "src" / "a.py", ns=(info.st_atime_ns, info.st_mtime_ns))
        return result
    monkeypatch.setattr(milestones.shutil, "copytree", mutate_after_copy)
    checkpoint = milestones.create("r", 15, ws, task)
    monkeypatch.undo()
    assert (checkpoint / "workspace" / "src" / "a.py").read_text() == "a = 1\n" != (ws / "src" / "a.py").read_text()
    packet = (checkpoint / "packet.txt").read_text()
    assert "did not change" not in packet and "unchanged" not in packet


def test_a_file_that_vanishes_mid_copy_is_reported_not_hidden_and_the_rest_is_still_copied(world, monkeypatch):
    ws, task = world
    real_scandir, real_copytree, armed = os.scandir, shutil.copytree, []
    class Listed(list):
        def __enter__(self): return self
        def __exit__(self, *exc): return False
    def arm(*args, **kwargs):
        armed.append(True)
        return real_copytree(*args, **kwargs)
    def vanishing(path):
        with real_scandir(path) as scan:
            listing = Listed(scan)
        if armed and os.fspath(path) == str(ws / "src"):
            (ws / "src" / "a.py").unlink()                            # listed, then gone before it is copied
        return listing
    monkeypatch.setattr(milestones.shutil, "copytree", arm)
    monkeypatch.setattr(os, "scandir", vanishing)
    checkpoint = milestones.create("r", 15, ws, task, actual_active_seconds=900.0)
    monkeypatch.undo()
    policy = json.loads((checkpoint / "policy.json").read_text())
    assert policy["snapshot"]["errors"] and "a.py" in policy["snapshot"]["errors"][0]
    assert (checkpoint / "workspace" / "b.txt").read_text() == "b\n"
    packet = (checkpoint / "packet.txt").read_text()
    assert "could not be fully copied" in packet and "copy error(s)" in packet


def test_there_is_no_fingerprint_warehouse_or_terminal_gate_left():
    assert not hasattr(milestones, "state_digest") and not hasattr(milestones, "is_current")


def test_polling_never_blocks_and_only_a_valid_recorded_judgment_counts(world):
    ws, task = world
    checkpoint = milestones.create("r", 15, ws, task)
    assert milestones.poll(checkpoint) is None                         # nothing recorded: no wait, no invention
    milestones.verdict_path(checkpoint).write_text('{"decision": "continue"')
    assert milestones.poll(checkpoint) is None                         # partial write
    milestones.verdict_path(checkpoint).write_text(json.dumps(dict(usefulness_percent=5, decision="continue", reason="r",
                                                                   evidence=["e"], material_changes="m")))
    assert milestones.poll(checkpoint) is None                         # new checkpoints need requirements + pace_reason
    milestones.verdict_path(checkpoint).write_text(valid("stalled"))
    assert milestones.poll(checkpoint)["decision"] == "stalled"
    assert not hasattr(milestones, "wait")                             # the blocking API is gone, not merely unused


def test_a_legacy_checkpoint_without_policy_metadata_stays_readable(world):
    ws, task = world
    checkpoint = milestones.create("r", 15, ws, task)
    (checkpoint / "policy.json").unlink()
    milestones.verdict_path(checkpoint).write_text(json.dumps(dict(usefulness_percent=5, decision="continue", reason="r",
                                                                   evidence=["e"], material_changes="m")))
    assert milestones.poll(checkpoint)["usefulness_percent"] == 5
