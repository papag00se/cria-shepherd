"""Dataset for the System 1 ``progress`` family: one row per (checkpoint, requirement).

Source: the battery's milestone checkpoints, ``~/.cria/suite/_milestones/<checkpoint>/{verdict.json, workspace/,
packet.txt}``. Per requirement the row's INPUT is the requirement text plus compact evidence — the unified diff of
the snapshot's task files against the task seed — and its LABEL is the Sonnet verdict's status for that requirement
(``completed`` -> DONE, ``partial`` -> PARTIAL, ``not_started`` -> NOT_STARTED; anything else is dropped).

What is deliberately NOT in the input: the judge's own prose (verdict ``evidence``/``reason``/``pace_reason``, the
packet's prior-milestone judgments, the checkpoint minute). The labels are model verdicts, not human gold.
``packet.txt`` holds no coder-side facts beyond the task prompt and a path inventory of the snapshot, and the
inventory is subsumed by the diff, so the packet contributes only its BASELINE SEED TREE, used to detect a task seed
that has changed since the checkpoint was taken (such checkpoints are skipped, not diffed against the wrong seed).

Everything is written under ``~/.cria/training/progress-v1`` (never the repo):

    python -m suite.progress_dataset [--out DIR]
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MILESTONES = Path.home() / ".cria" / "suite" / "_milestones"
RESULTS = REPO / "suite" / "results" / "results.jsonl"
TASKS = REPO / "suite" / "tasks"
OUT = Path.home() / ".cria" / "training" / "progress-v1"

LABELS = ("DONE", "PARTIAL", "NOT_STARTED")
STATUS_TO_LABEL = {"completed": "DONE", "partial": "PARTIAL", "not_started": "NOT_STARTED"}

#: directories that are tooling, caches, dependencies, build output or harness state — never task files.
IGNORED_DIRS = {
    ".git", ".codex", ".agents", ".aws", "target", "vendor", "node_modules", "tmp", "_tmp", ".m2", ".bundle", "build",
    "oldbuild", "oldslow_build", ".pytest_cache", "__pycache__", "venv", ".venv", ".cargo", ".gradle", ".modcache",
    "_cacache", "_logs", ".tmp",
}
#: GEM_HOME-style directories that Ruby installs dump at the workspace top level.
IGNORED_TOP_LEVEL = {"build_info", "cache", "doc", "extensions", "gems", "plugins", "specifications", "bin_gems"}
IGNORED_FILES = {".writetest"}
#: machine-generated files: shown as a path + size line, never as a diff.
GENERATED_FILES = {"go.sum", "Cargo.lock", "package-lock.json", "Gemfile.lock", "yarn.lock", "poetry.lock"}
MAX_TEXT_FILE_BYTES = 200_000
#: a file the coder ADDED (absent from the seed) beyond this is a data dump / log / vendored source, not readable evidence.
MAX_ADDED_FILE_BYTES = 12_000
#: a NEW top-level directory holding more files than this is a cloned/unpacked dependency, not authored code.
MAX_NEW_DIR_FILES = 12


def _ignored_dir(name: str, depth: int) -> bool:
    if name in IGNORED_DIRS or (name.startswith(".") and depth == 0):
        return True
    return depth == 0 and name in IGNORED_TOP_LEVEL


def _files(root: Path) -> dict[str, Path]:
    """Every regular, non-symlink task-relevant file below ``root``, keyed by posix-relative path."""
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for base, dirs, names in os.walk(root, followlinks=False):
        depth = len(Path(base).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if not _ignored_dir(d, depth) and not (Path(base) / d).is_symlink())
        for name in sorted(names):
            path = Path(base) / name
            if name in IGNORED_FILES or path.is_symlink() or not path.is_file():
                continue
            found[path.relative_to(root).as_posix()] = path
    return found


def _read_text(path: Path) -> str | None:
    """The file's text, or None when it is binary / not UTF-8."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def seed_diff(seed: Path, workspace: Path) -> str:
    """Unified diff of the workspace's task files against the seed, as one string ('' when nothing changed).

    Added, modified and deleted files each get a ``--- / +++`` block; a binary, generated, or oversize file gets one
    labelled line (path, size); a new directory of many files, likewise, instead of content, because its bytes are not readable evidence."""
    old, new = _files(seed), _files(workspace)
    blocks: list[str] = []
    seed_tops = {rel.split("/")[0] for rel in old}
    new_dir_files = Counter(rel.split("/")[0] for rel in new if "/" in rel and rel.split("/")[0] not in seed_tops)
    bulk_dirs = {d for d, n in new_dir_files.items() if n > MAX_NEW_DIR_FILES}
    for d in sorted(bulk_dirs):
        blocks.append(f"new directory (not shown): {d}/ ({new_dir_files[d]} files)")
    for rel in sorted(set(old) | set(new)):
        a, b = old.get(rel), new.get(rel)
        if b is not None and rel.split("/")[0] in bulk_dirs and "/" in rel:
            continue
        if a is not None and b is not None and a.read_bytes() == b.read_bytes():
            continue
        if b is None:
            blocks.append(f"deleted file: {rel}")
            continue
        size = b.stat().st_size
        if Path(rel).name in GENERATED_FILES:
            blocks.append(f"generated file {'added' if a is None else 'changed'} (not shown): {rel} ({size} bytes)")
            continue
        new_text = _read_text(b)
        if new_text is None:
            blocks.append(f"binary file {'added' if a is None else 'changed'} (not shown): {rel} ({size} bytes)")
            continue
        if size > MAX_TEXT_FILE_BYTES or (a is None and size > MAX_ADDED_FILE_BYTES):
            blocks.append(f"large text file {'added' if a is None else 'changed'} (not shown): {rel} ({size} bytes)")
            continue
        old_text = _read_text(a) if a is not None else ""
        if old_text is None:
            blocks.append(f"binary file changed (not shown): {rel} ({size} bytes)")
            continue
        lines = list(difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(),
            fromfile=f"a/{rel}" if a is not None else "/dev/null", tofile=f"b/{rel}", lineterm="", n=2))
        blocks.append("\n".join(lines) if lines else f"empty file added: {rel}")
    return "\n".join(blocks)


def label_rows(verdict: dict) -> list[tuple[int, str, str]]:
    """(index, requirement text, label) for every requirement whose status maps to a label; the rest are dropped."""
    out = []
    for i, req in enumerate(verdict.get("requirements") or []):
        label = STATUS_TO_LABEL.get(req.get("status"))
        text = (req.get("requirement") or "").strip()
        if label and text:
            out.append((i, text, label))
    return out


_TREE_LINE = re.compile(r'^\s+([FD]) "((?:[^"\\]|\\.)*)"(?: \((\d+) B\))?$')


def packet_seed_tree(packet: str) -> dict[str, int | None] | None:
    """The packet's BASELINE SEED TREE as {path: size or None for dirs}; None when it has no such section."""
    lines = packet.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("BASELINE SEED TREE"))
    except StopIteration:
        return None
    tree: dict[str, int | None] = {}
    for line in lines[start + 1:]:
        if not line.strip():
            break
        m = _TREE_LINE.match(line)
        if m:
            tree[json.loads(f'"{m.group(2)}"')] = int(m.group(3)) if m.group(3) is not None else None
    return tree


def seed_tree(seed: Path) -> dict[str, int | None]:
    tree: dict[str, int | None] = {}
    for base, dirs, names in os.walk(seed):
        for d in dirs:
            tree[(Path(base) / d).relative_to(seed).as_posix()] = None
        for n in names:
            p = Path(base) / n
            tree[p.relative_to(seed).as_posix()] = p.stat().st_size
    return tree


def seed_unchanged(task: str, packet: str) -> bool:
    """True when the task's current seed is the one the checkpoint's packet recorded."""
    recorded = packet_seed_tree(packet)
    seed = TASKS / task / "seed"
    current = seed_tree(seed) if seed.is_dir() else {}
    return recorded is not None and (recorded or {}) == current


def render_state(requirement: str, diff: str) -> dict:
    return {"requirement": requirement, "workspace_changes": diff or "(no task file differs from the seed)"}


def _run_index() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            by[row["run_id"]].append(row)
    return by


def _checkpoint(name: str) -> tuple[str, int]:
    run_id, _, minute = name.rpartition(".")
    return run_id, int(minute.removesuffix("min"))


def build(out: Path = OUT, milestones: Path = MILESTONES) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    runs = _run_index()
    skipped: Counter = Counter()
    rows: list[dict] = []
    diffs: dict[str, str] = {}
    for ckpt in sorted(p.name for p in milestones.iterdir() if p.is_dir()):
        run_id, minute = _checkpoint(ckpt)
        task = run_id.split("_")[0]
        d = milestones / ckpt
        recs = runs.get(run_id)
        if not recs:
            skipped["no results row (run never recorded: abort status unknown)"] += 1
            continue
        if any(r.get("aborted") for r in recs):
            skipped["aborted run"] += 1
            continue
        try:
            verdict = json.loads((d / "verdict.json").read_text())
        except (OSError, ValueError):
            skipped["no readable verdict"] += 1
            continue
        reqs = label_rows(verdict)
        if not reqs:
            skipped["no labelled requirements"] += 1
            continue
        if not (d / "workspace").is_dir():
            skipped["no workspace"] += 1
            continue
        if not seed_unchanged(task, (d / "packet.txt").read_text(errors="replace")):
            skipped["seed differs from the one recorded in the packet"] += 1
            continue
        diff = seed_diff(TASKS / task / "seed", d / "workspace")
        digest = hashlib.sha256(diff.encode()).hexdigest()
        diffs[digest] = diff
        rec = recs[-1]
        for index, text, label in reqs:
            rows.append({
                "id": f"{ckpt}#{index}", "checkpoint": ckpt, "run_id": run_id, "task": task,
                "model": rec.get("model"), "level": rec.get("level"), "campaign": rec.get("campaign_id"),
                "harness": rec.get("harness"), "minute": minute, "terminal": rec.get("terminal"),
                "requirement": text, "label": label, "label_source": "sonnet-milestone-verdict",
                "diff_sha256": digest,
            })
    with (out / "dataset.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps({**r, "evidence": diffs[r["diff_sha256"]]}, ensure_ascii=False) + "\n")
    counts: dict = defaultdict(lambda: Counter())
    for r in rows:
        counts[r["task"]][r["label"]] += 1
    manifest = {
        "rows": len(rows), "checkpoints": len({r["checkpoint"] for r in rows}), "runs": len({r["run_id"] for r in rows}),
        "labels": list(LABELS), "counts_by_task_label": {t: dict(c) for t, c in sorted(counts.items())},
        "counts_by_label": dict(Counter(r["label"] for r in rows)),
        "counts_by_model": dict(Counter(r["model"] for r in rows)),
        "counts_by_level": dict(Counter(str(r["level"]) for r in rows)),
        "skipped_checkpoints": dict(skipped),
        "input": "state {requirement, workspace_changes}: seed->snapshot unified diff of task files; judge prose excluded",
        "labels_are": "Sonnet milestone verdicts, not human gold",
        "dataset_sha256": hashlib.sha256((out / "dataset.jsonl").read_bytes()).hexdigest(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(build(args.out), indent=2))


if __name__ == "__main__":
    main()
