"""Destructive/closing tools and evidence preservation: walk closure deletes only settled scratch, the usefulness
packet outlives its workspace, restored role config is restored byte-exact, sampling is injected non-lossily."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "suite"))   # usefulness imports siblings by bare name
import usefulness  # noqa: E402
from suite.sampling_adapter import RateLimitGate, inject_sampling  # noqa: E402
from suite import close_walk, restored_roles  # noqa: E402


@pytest.fixture
def area(tmp_path):
    scratch, repo = tmp_path / "scratch", tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    unit = scratch / "closed"
    unit.mkdir(parents=True)
    (unit / "output").write_bytes(b"old check output")
    record = dict(unit="walk-1", owner="o", closure="operator final fix dispositions", closed=True,
                  fixes=[dict(id="f1", disposition="ACCEPTED", changes=[])], scratch=[str(unit)],
                  protected_paths=[], call_logs=[])
    return scratch, unit, repo, record


def close(area):
    scratch, _, repo, record = area
    return close_walk.close(record, repo=repo, scratch_roots=[scratch])


def test_closure_removes_only_declared_scratch_and_keeps_secured_work_and_active_neighbours(area):
    """Settled (ACCEPTED/REJECTED) fixes remove their scratch; secured unique source survives in the repo,
    and an active neighbour (protected path) is untouched."""
    scratch, unit, repo, record = area
    (unit / "fix.py").write_bytes(b"def add(a, b): return a + b\n")
    (repo / "tests/fix.py").write_bytes((unit / "fix.py").read_bytes())
    record["fixes"][0]["changes"] = [dict(source=str(unit / "fix.py"), worktree=str(repo / "tests/fix.py"))]
    record["fixes"].append(dict(id="f2", disposition="REJECTED", changes=[]))
    active = scratch / "closed-pending"
    active.mkdir()
    (active / "call-log").write_bytes(b"keep active bytes")
    record["protected_paths"] = [str(active)]
    assert close(area) == [str(unit)] and not unit.exists()
    assert (repo / "tests/fix.py").is_file() and (active / "call-log").read_bytes() == b"keep active bytes"


@pytest.mark.parametrize("damage", [
    ("status", None), ("status", "PENDING"), ("status", True), ("fixes", []), ("scratch", ["/"]),
    ("scratch", ["relative"]), ("closed", "true"), ("record", None),
    ("unsecured", "missing"), ("unsecured", "different"), ("unsecured", "symlink"), ("unsecured", "outside-repo"), ("protected", "outside-roots"),
    ("protected", "call_log"), ("protected", "repo"), ("protected", "scratch-root"), ("protected", "duplicate"),
    ("protected", "absent"), ("alias", "symlink-into-calls")])
def test_closure_denies_before_any_delete_when_anything_is_unsettled_unsecured_or_protected(area, damage):
    """An unsettled/ambiguous fix, malformed declaration, unsecured unique change, protected/aliased/duplicate/absent
    path denies the WHOLE batch; the old scratch bytes are still there afterwards."""
    scratch, unit, repo, record = area
    kind, value = damage
    if kind == "status":
        record["fixes"].append(dict(id="x", disposition=value, changes=[]))
    elif kind in ("fixes", "scratch", "closed"):
        record[kind] = value
    elif kind == "record":
        record = value
    elif kind == "unsecured":
        src = unit / "regression.py"
        src.write_bytes(b"necessary regression")
        target = repo / "tests/regression.py"
        if value == "different":
            target.write_bytes(b"wrong revision")
        elif value == "symlink":
            target.symlink_to(src)
        elif value == "outside-repo":
            target = scratch.parent / "copy.py"
            target.write_bytes(src.read_bytes())
        record["fixes"][0]["changes"] = [dict(source=str(src), worktree=str(target))]
    elif kind == "protected":
        (unit / "keep").write_text("must survive")
        if value == "call_log":
            record["call_logs"] = [str(unit / "keep")]
        else:
            (scratch.parent / "unrelated").mkdir()
            record["scratch"].append({"repo": str(repo), "scratch-root": str(scratch), "duplicate": str(unit),
                                      "absent": str(scratch / "absent"),
                                      "outside-roots": str(scratch.parent / "unrelated")}[value])
    else:
        calls = scratch.parent / "actual-calls"
        calls.mkdir()
        (calls / "response.json").write_bytes(b"actual call bytes")
        (unit / "link").symlink_to(calls, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        close_walk.close(record, repo=repo, scratch_roots=[scratch])
    assert (unit / "output").read_bytes() == b"old check output"


def test_readonly_scratch_directories_remove_without_chmodding_a_hard_linked_original(area):
    """Go module caches are 0555 and hard-link outside files; removal must not chmod the linked original."""
    scratch, unit, repo, record = area
    original = repo / "frozen"
    original.write_bytes(b"outside bytes")
    original.chmod(0o444)
    package = unit / "gomodcache" / "module"
    package.mkdir(parents=True)
    os.link(original, package / "linked")
    for p in (package, package.parent, unit):
        p.chmod(0o555)
    close(area)
    assert not unit.exists() and original.read_bytes() == b"outside bytes" and original.stat().st_mode & 0o777 == 0o444


@pytest.fixture
def packets(tmp_path, monkeypatch):
    (tmp_path / "workspace/src").mkdir(parents=True)
    (tmp_path / "workspace/REVIEW.md").write_text("findings, Importer.java:31\n")
    monkeypatch.setattr(usefulness, "PACKETS", tmp_path / "_packets")
    monkeypatch.setattr(usefulness, "VERDICTS", tmp_path / "_verdicts")
    (tmp_path / "_verdicts").mkdir()
    return tmp_path


def test_usefulness_packet_is_frozen_before_the_workspace_is_reaped(packets):
    """After the archive is deleted the frozen packet (and digest) still serves; without one the evidence says
    'workspace unavailable'; a packet that cannot be written never fails a finished run."""
    row = {"run_id": "r1", "task": "feed-pipeline-java", "archive": str(packets), "terminal": "budget-killed",
           "calls": 44, "wall_seconds": 3685.2}
    live = usefulness.evidence(row)
    assert usefulness.save_packet(row) is not None
    shutil.rmtree(packets / "workspace")
    assert usefulness.evidence(row) == live and "TASK METADATA" not in live[0]
    assert "workspace unavailable" in usefulness.evidence({**row, "run_id": "r2"})[0]
    assert usefulness.save_packet({"run_id": "x", "task": "no-such-task"}) is None


def test_worklist_holds_only_judgeable_rows_and_a_rubric_change_reopens_verdicts(packets, monkeypatch):
    """No packet and no workspace = never judgeable; a verdict with a stale/missing digest (different rubric) is reopened."""
    usefulness.PACKETS.mkdir()
    (usefulness.PACKETS / "done.txt").write_text("frozen")
    done = {"run_id": "done", "archive": "/nowhere"}
    assert usefulness.pending([{"run_id": "lost", "archive": "/nowhere"}]) == []
    verdict = usefulness.VERDICTS / "done.json"
    verdict.write_text(json.dumps({"usefulness_percent": 50, "evidence_digest": usefulness.evidence(done)[1]}))
    assert usefulness.pending([done]) == []
    rubric = packets / "other-rubric.txt"
    rubric.write_text("a different rubric entirely\n")
    with monkeypatch.context() as m:
        m.setattr(usefulness, "SYSTEM", rubric)
        assert [r["run_id"] for r in usefulness.pending([done])] == ["done"]
    verdict.write_text(json.dumps({"usefulness_percent": 50}))
    assert [r["run_id"] for r in usefulness.pending([done])] == ["done"]


def test_scoped_role_config_restores_exact_bytes_even_when_the_cell_raises_and_keeps_operator_edits(tmp_path):
    """The temporary role sampling edit is reverted byte-for-byte (same inode) on failure; a newer operator edit
    made during the scope is never overwritten."""
    roles = {r: {"temperature": float(i)} for i, r in enumerate(("coder", "reasoner", "classifier", "compactor"))}
    path, original = tmp_path / "config.toml", Path("cria.example.toml").read_bytes()
    path.write_bytes(original)
    inode, restarts = path.stat().st_ino, []
    with pytest.raises(RuntimeError):
        with restored_roles.scoped(path, roles, tmp_path / "proof", restart_service=lambda: restarts.append(path.read_bytes())):
            assert path.read_bytes() != original
            raise RuntimeError("cell failed")
    assert path.read_bytes() == original and path.stat().st_ino == inode
    assert len(restarts) == 2 and restarts[-1] == original
    with pytest.raises(ValueError, match="newer edits"):
        with restored_roles.scoped(path, roles, tmp_path / "proof2", restart_service=lambda: None):
            path.write_text(path.read_text() + "\n# newer operator edit\n")
    assert path.read_text().endswith("# newer operator edit\n")


@pytest.mark.parametrize("knobs", [{"enable_thinking": True}, {"temperature": True}, {"top_k": "20"},
                                   {"temperature": float("nan")}, {"instructions": "do work"}])
def test_sampling_injection_keeps_the_whole_request_and_accepts_only_finite_numeric_knobs(knobs):
    """Full history and unknown fields survive; boolean/string/NaN/non-sampling knobs are refused."""
    body = {"model": "phi4", "input": [{"role": "user", "content": "α\n" * 20000}], "unknown": {"nested": ["keep"]}}
    assert json.loads(inject_sampling(json.dumps(body).encode(), {"temperature": 0.0})) == {**body, "temperature": 0.0}
    with pytest.raises(ValueError):
        inject_sampling(b"{}", knobs)


@pytest.mark.parametrize("headers,body,delay", [({"Retry-After": "13"}, b"", 13), ({"X-RateLimit-Reset": "1030"}, b"", 30),
                                                ({}, b'{"error":{"message":"Please retry in 2m3s."}}', 123)])
def test_rate_limit_gate_is_shared_across_instances_and_never_retries_early(tmp_path, headers, body, delay):
    """A 429 observed by one adapter makes every adapter on the same state dir wait the advertised delay."""
    clock = [1000.0]
    sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    RateLimitGate(tmp_path, now=lambda: clock[0], sleep=sleep).observe(headers, 429, body)
    RateLimitGate(tmp_path, now=lambda: clock[0], sleep=sleep).wait()
    assert clock[0] >= 1000 + delay
