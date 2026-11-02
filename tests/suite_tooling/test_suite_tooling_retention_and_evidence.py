"""The usefulness worklist, role config restored byte-exact after a cell, and non-lossy sampling injection."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "suite"))   # usefulness imports siblings by bare name
import usefulness  # noqa: E402
from suite.sampling_adapter import RateLimitGate, inject_sampling  # noqa: E402
from suite import restored_roles  # noqa: E402


@pytest.fixture
def packets(tmp_path, monkeypatch):
    (tmp_path / "workspace/src").mkdir(parents=True)
    (tmp_path / "workspace/REVIEW.md").write_text("findings, Importer.java:31\n")
    monkeypatch.setattr(usefulness, "VERDICTS", tmp_path / "_verdicts")
    (tmp_path / "_verdicts").mkdir()
    return tmp_path


def test_worklist_holds_only_rows_with_a_workspace_and_no_verdict(packets):
    """A row is judgeable while its archived workspace exists; a recorded verdict or a missing workspace removes it."""
    row = {"run_id": "done", "task": "feed-pipeline-java", "archive": str(packets)}
    assert usefulness.pending([{"run_id": "lost", "archive": "/nowhere"}]) == []
    assert [r["run_id"] for r in usefulness.pending([row])] == ["done"]
    assert "REVIEW.md" in usefulness.evidence(row) and "workspace unavailable" in usefulness.evidence({**row, "archive": "/nowhere"})
    (usefulness.VERDICTS / "done.json").write_text(json.dumps({"usefulness_percent": 50}))
    assert usefulness.pending([row]) == []


def test_scoped_role_config_restores_exact_bytes_even_when_the_cell_raises_and_keeps_operator_edits(tmp_path):
    """The temporary role sampling edit is reverted byte-for-byte (same inode) on failure; a newer operator edit
    made during the scope is never overwritten."""
    roles = {r: {"temperature": float(i)} for i, r in enumerate(("coder", "reasoner", "classifier", "compactor"))}
    path, original = tmp_path / "config.toml", Path("cria.example.toml").read_bytes()
    path.write_bytes(original)
    inode, restarts = path.stat().st_ino, []
    with pytest.raises(RuntimeError):
        with restored_roles.scoped(path, roles, restart_service=lambda: restarts.append(path.read_bytes())):
            assert path.read_bytes() != original
            raise RuntimeError("cell failed")
    assert path.read_bytes() == original and path.stat().st_ino == inode
    assert len(restarts) == 2 and restarts[-1] == original
    with pytest.raises(ValueError, match="newer edits"):
        with restored_roles.scoped(path, roles, restart_service=lambda: None):
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
