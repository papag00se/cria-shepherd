import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "suite"))
import milestones  # noqa: E402
import usefulness  # noqa: E402


def _workspace(root: Path) -> Path:
    ws = root / "workspace"
    (ws / "node_modules" / "pkg").mkdir(parents=True)
    (ws / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1;\n")
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("[core]\n")
    (ws / "target" / "debug").mkdir(parents=True)
    (ws / "target" / "debug" / "program").write_bytes(b"binary")
    for n in range(405):
        (ws / f"file-{n:03d}.txt").write_text(str(n))
    return ws


def test_milestone_packet_lists_the_complete_frozen_tree(tmp_path, monkeypatch):
    live = _workspace(tmp_path / "live")
    task = tmp_path / "task"
    task.mkdir()
    (task / "prompt.txt").write_text("Build the requested program.\n")
    (task / "meta.toml").write_text("budget_intervals = 2\n")
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "checkpoints")

    checkpoint = milestones.create("run-1", 30, live, task)
    packet = (checkpoint / "packet.txt").read_text()

    assert "file-404.txt" in packet
    assert "node_modules/pkg/index.js" in packet
    assert ".git/config" in packet
    assert "target/debug/program" in packet
    assert "listing stopped" not in packet


def test_usefulness_packet_lists_the_same_complete_archived_tree(tmp_path):
    archive = tmp_path / "archive"
    _workspace(archive)
    row = {"run_id": "r", "task": "feed-pipeline-java", "archive": str(archive),
           "terminal": "exited", "calls": 1, "wall_seconds": 1}

    packet, _digest = usefulness.evidence(row, _saved=False)

    assert "file-404.txt" in packet
    assert "node_modules/pkg/index.js" in packet
    assert ".git/config" in packet
    assert "target/debug/program" in packet
    assert "listing stopped" not in packet
    assert "TASK METADATA" not in packet
