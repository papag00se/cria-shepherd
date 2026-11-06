"""The System 1 ``progress`` dataset: verdict-status -> label mapping, the seed diff that is the input, and the
provenance/abort filtering of checkpoints. Offline: fake milestone tree, no model, no GPU."""
import json

import pytest

from suite import progress_dataset as pd
from suite.progress_loto import f1_report, group_weights, majority_baseline


@pytest.mark.parametrize("status,label", [("completed", "DONE"), ("partial", "PARTIAL"), ("not_started", "NOT_STARTED")])
def test_status_maps_to_label(status, label):
    assert pd.label_rows({"requirements": [{"requirement": "r", "status": status}]}) == [(0, "r", label)]


def test_unknown_status_and_blank_requirement_are_dropped_and_indices_kept():
    verdict = {"requirements": [{"requirement": "a", "status": "completed"},
                                {"requirement": "b", "status": "blocked"},
                                {"requirement": "  ", "status": "partial"},
                                {"requirement": "d", "status": "not_started"}]}
    assert pd.label_rows(verdict) == [(0, "a", "DONE"), (3, "d", "NOT_STARTED")]
    assert pd.label_rows({}) == []


def tree(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
    return root


def test_seed_diff_shows_only_what_the_coder_changed(tmp_path):
    seed = tree(tmp_path / "seed", {"a.py": "x = 1\ny = 2\n", "keep.py": "same\n", "gone.py": "bye\n"})
    ws = tree(tmp_path / "ws", {
        "a.py": "x = 1\ny = 3\n", "keep.py": "same\n", "new.py": "print('hi')\n",
        # tooling / harness state / dependencies are never evidence
        ".git/config": "c", ".codex/x": "c", "target/debug/out": "c", "vendor/dep.go": "c", "tmp/scratch": "c",
        ".writetest": "", "node_modules/m/index.js": "c",
        # unreadable or generated files are named, not dumped
        "blob.bin": b"\0\1\2", "go.sum": "h1:abc\n"})
    diff = pd.seed_diff(seed, ws)
    assert "-y = 2" in diff and "+y = 3" in diff and "+print('hi')" in diff
    assert "deleted file: gone.py" in diff
    assert "keep.py" not in diff
    for hidden in (".git", ".codex", "target", "vendor", "scratch", ".writetest", "node_modules"):
        assert hidden not in diff
    assert "binary file added (not shown): blob.bin (3 bytes)" in diff
    assert "generated file added (not shown): go.sum" in diff


def test_untouched_workspace_has_empty_diff_and_missing_seed_means_everything_is_new(tmp_path):
    seed = tree(tmp_path / "seed", {"a.py": "1\n"})
    assert pd.seed_diff(seed, tree(tmp_path / "same", {"a.py": "1\n", ".git/HEAD": "x"})) == ""
    out = pd.seed_diff(tmp_path / "no-seed", tree(tmp_path / "w", {"main.rs": "fn main() {}\n"}))
    assert "--- /dev/null" in out and "+fn main() {}" in out


def test_dependency_dumps_are_named_not_inlined(tmp_path):
    seed = tree(tmp_path / "seed", {"a.py": "1\n"})
    ws = tree(tmp_path / "ws", {"a.py": "1\n", **{f"countries_tmp/f{i}.json": "{}" for i in range(pd.MAX_NEW_DIR_FILES + 1)},
                                "big.txt": "x" * (pd.MAX_ADDED_FILE_BYTES + 1), "small/one.txt": "tiny"})
    diff = pd.seed_diff(seed, ws)
    assert f"new directory (not shown): countries_tmp/ ({pd.MAX_NEW_DIR_FILES + 1} files)" in diff
    assert "f0.json" not in diff
    assert "large text file added (not shown): big.txt" in diff
    assert "+tiny" in diff


def packet(seed_lines):
    return "BASELINE SEED TREE (before coder started):\n" + "\n".join(seed_lines) + "\n\nPRIOR MILESTONE JUDGMENTS"


def test_packet_seed_tree_parse_and_seed_drift_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "TASKS", tmp_path)
    tree(tmp_path / "t" / "seed", {"a.py": "12345"})
    tree(tmp_path / "e", {})
    assert pd.packet_seed_tree(packet(['  F "a.py" (5 B)', '  D "lib"'])) == {"a.py": 5, "lib": None}
    assert pd.packet_seed_tree(packet(["(empty baseline)"])) == {}
    assert pd.seed_unchanged("t", packet(['  F "a.py" (5 B)']))
    assert not pd.seed_unchanged("t", packet(['  F "a.py" (6 B)']))     # seed edited since the checkpoint
    assert pd.seed_unchanged("empty-task", packet(["(empty baseline)"]))  # an empty seed is not a drift


def milestone(root, name, requirements, files, seed_line='  F "a.py" (4 B)'):
    d = root / name
    tree(d / "workspace", files)
    (d / "verdict.json").write_text(json.dumps({"reason": "JUDGE PROSE", "requirements": requirements}))
    (d / "packet.txt").write_text(packet([seed_line]))


def test_build_labels_diffs_and_skips_aborted_unrecorded_and_drifted(tmp_path, monkeypatch):
    tasks, ms, out = tmp_path / "tasks", tmp_path / "ms", tmp_path / "out"
    tree(tasks / "t" / "seed", {"a.py": "old\n"})
    results = tmp_path / "results.jsonl"
    rec = lambda run, **kw: {"run_id": run, "model": "m", "level": 5, "campaign_id": "c", "harness": "codex", **kw}
    results.write_text("\n".join(json.dumps(r) for r in [
        rec("t_m_ok_1"), rec("t_m_aborted_2", aborted="rerun: bad"), rec("t_m_drift_4")]) + "\n")
    reqs = [{"requirement": "do A", "status": "completed", "evidence": "JUDGE EVIDENCE"},
            {"requirement": "do B", "status": "not_started", "evidence": "JUDGE EVIDENCE"}]
    work = {"a.py": "new\n"}
    milestone(ms, "t_m_ok_1.030min", reqs, work)
    milestone(ms, "t_m_aborted_2.015min", reqs, work)
    milestone(ms, "t_m_unrecorded_3.015min", reqs, work)           # no results row: abort status unknowable
    milestone(ms, "t_m_drift_4.015min", reqs, work, seed_line='  F "a.py" (99 B)')
    monkeypatch.setattr(pd, "TASKS", tasks)
    monkeypatch.setattr(pd, "RESULTS", results)
    manifest = pd.build(out, ms)
    rows = [json.loads(line) for line in (out / "dataset.jsonl").read_text().splitlines()]
    assert [(r["id"], r["label"], r["minute"]) for r in rows] == [("t_m_ok_1.030min#0", "DONE", 30),
                                                                  ("t_m_ok_1.030min#1", "NOT_STARTED", 30)]
    assert all("-old" in r["evidence"] and "+new" in r["evidence"] for r in rows)
    assert {r["model"] for r in rows} == {"m"} and {r["campaign"] for r in rows} == {"c"}
    assert "JUDGE" not in json.dumps(rows)                           # the judge's prose is never evidence
    assert manifest["counts_by_task_label"] == {"t": {"DONE": 1, "NOT_STARTED": 1}}
    assert sum(manifest["skipped_checkpoints"].values()) == 3


def test_metrics_and_group_balancing():
    labels = pd.LABELS
    report = f1_report(["DONE", "DONE", "PARTIAL", "NOT_STARTED"], ["DONE", "PARTIAL", "PARTIAL", "NOT_STARTED"], labels)
    assert report["accuracy"] == 0.75 and report["confusion"] == [[1, 1, 0], [0, 1, 0], [0, 0, 1]]
    assert report["per_label_f1"]["DONE"] == pytest.approx(2 / 3)
    base = majority_baseline(["DONE", "PARTIAL", "PARTIAL"], ["PARTIAL", "DONE"])
    assert base["label"] == "PARTIAL" and base["accuracy"] == 0.5
    rows = [{"id": str(i), "task": "t", "family": "progress", "label": "DONE" if i < 3 else "PARTIAL"} for i in range(4)]
    w = group_weights(rows)
    assert sum(w.values()) == pytest.approx(len(rows))
    assert sum(w[str(i)] for i in range(3)) == pytest.approx(w["3"])  # each group carries the same total weight

    # Incident: better aggregate accuracy/NOT_STARTED separation bought eight
    # additional false approvals of PARTIAL. That must not win D/P selection.
    from suite.progress_correctness.benchmark_repair import select_done_partial
    candidates = {
        "source_recorded": {"confusion": [[99, 51, 50], [82, 66, 52], [0, 1, 199]],
                            "done_precision": 99/181, "macro_f1": 0.5764},
        "aggregate-winner": {"confusion": [[100, 82, 18], [90, 92, 18], [0, 3, 197]],
                             "done_precision": 100/190, "macro_f1": 0.6369},
        "precision-only": {"confusion": [[99, 51, 50], [80, 67, 53], [0, 1, 199]],
                           "done_precision": 99/179, "macro_f1": 0.5784},
    }
    assert select_done_partial(candidates) == "precision-only"
    candidates["done-improvement"] = {"confusion": [[110, 40, 50], [80, 68, 52], [0, 1, 199]],
                                      "done_precision": 110/190, "macro_f1": 0.60}
    assert select_done_partial(candidates) == "done-improvement"


@pytest.mark.parametrize("descending", [False, True])
def test_monotone_gather_backward_matches_stock_gather(descending):
    """The scatter-free backward used to train on DeBERTa's relative-position gather is the same gradient."""
    torch = pytest.importorskip("torch")
    from suite.progress_loto import monotone_gather_class
    n, length, slots = 3, 40, 16
    delta = torch.arange(length)[:, None] - torch.arange(length)[None, :]            # i - j
    row = torch.clamp(delta // 3 + slots // 2, 0, slots - 1)                           # clamped bucketed i - j
    row = row if not descending else slots - 1 - row
    index = row.unsqueeze(0).expand(n, length, length)
    weight = torch.randn(n, length, length)
    stock = torch.randn(n, length, slots, requires_grad=True)
    fast = stock.detach().clone().requires_grad_(True)
    (torch.gather(stock, -1, index) * weight).sum().backward()
    (monotone_gather_class(torch)(fast, -1, index) * weight).sum().backward()
    assert torch.allclose(stock.grad, fast.grad, atol=1e-5)
