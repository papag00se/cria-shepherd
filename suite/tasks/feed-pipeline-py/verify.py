#!/usr/bin/env python3
"""Verifier for feed-pipeline-py — categories 17 (data transform), 10 (optimise), 13 (concurrency),
20 (code review).

The seed importer is slow by construction (an O(n^2) SKU scan), racy by construction (unsynchronised
`totals` and `row_count` across threads, which is why WORKERS_ENABLED is False), and crashes on the
messy feed. Four points:

  1. the messy feed is handled — no crash, sensible rows imported, and the summary SAYS how many
     rows were skipped
  2. substantially faster: timed against the SEED's own implementation in the same process on the
     same machine, so the bar cannot drift with hardware or load
  3. the race is fixed AND the workers are back on — checked by running the import many times and
     demanding identical totals, with the code showing parallelism enabled
  4. REVIEW.md names real, located issues

Correctness is checked before speed: an importer that is fast because it stopped counting is not an
optimisation.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 600
SPEEDUP_BAR = 4.0
BIG_ROWS, BIG_SKUS = 120_000, 25_000


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def make_big_feed(path):
    import csv
    import random
    random.seed(11)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "description", "quantity", "unit_price"])
        for i in range(BIG_ROWS):
            w.writerow([f"SKU-{i % BIG_SKUS:05d}", f"item {i}",
                        random.randint(1, 40), round(random.uniform(1, 90), 2)])


TIME_ONE = """
import sys, time, json
sys.path.insert(0, {root!r})
from pipeline.importer import summarize
t = time.perf_counter()
r = summarize({feed!r})
print("VERIFY_JSON=" + json.dumps({{"secs": time.perf_counter() - t,
                                   "rows": r.get("rows"), "skus": r.get("skus"),
                                   "total": round(sum(r.get("totals", {{}}).values()), 2)}}))
"""


def timed_run(root, feed, cwd):
    code, out = run([sys.executable, "-c", TIME_ONE.format(root=str(root), feed=str(feed))], cwd)
    m = re.search(r"VERIFY_JSON=(\{.*\})", out)
    return (json.loads(m.group(1)) if m else None), out


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "feed-pipeline-py", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    tmp = Path(tempfile.mkdtemp())

    # --- 1: the messy feed
    messy = ws / "data" / "feed_messy.csv"
    if not messy.exists():
        messy = HERE / "seed" / "data" / "feed_messy.csv"
    code, out = run([sys.executable, "-m", "pipeline.importer", str(messy)], ws)
    crashed = code != 0 or "Traceback" in out
    reports_skips = bool(re.search(r"skip|ignored|rejected|malformed|invalid", out, re.I))
    counts_something = bool(re.search(r"\b[1-9]\d*\b", out))
    r["parts"]["messy_feed_handled"] = {
        "ok": (not crashed) and reports_skips and counts_something,
        "detail": f"exit={code}, crashed={crashed}, reports skipped rows={reports_skips}"}

    # --- 2: speed, against the seed's own implementation on the same big feed
    big = tmp / "big.csv"
    make_big_feed(big)
    theirs, their_out = timed_run(ws, big, ws)
    seed_root = HERE / "seed"
    mine, _ = timed_run(seed_root, big, seed_root)
    speed_ok, speed_detail = False, "importer did not complete on the large feed"
    if theirs and mine:
        # Correct FIRST: same row count and same money, to 2dp. Fast-because-wrong scores nothing.
        same = (theirs.get("rows") == mine.get("rows")
                and abs((theirs.get("total") or 0) - (mine.get("total") or 0)) < 0.05)
        ratio = (mine["secs"] / theirs["secs"]) if theirs["secs"] > 0 else 0
        speed_ok = same and ratio >= SPEEDUP_BAR
        speed_detail = (f"seed {mine['secs']:.2f}s vs theirs {theirs['secs']:.2f}s "
                        f"({ratio:.1f}x, bar {SPEEDUP_BAR}x); same totals: {same}")
    elif theirs is None:
        speed_detail = f"their importer failed on the large feed: {their_out.strip()[-90:]}"
    r["parts"]["substantially_faster"] = {"ok": speed_ok, "detail": speed_detail}

    # --- 3: the race, and the workers actually on
    src = next((p for p in ws.rglob("importer.py") if ".git" not in p.parts), None)
    text = src.read_text(errors="replace") if src else ""
    workers_on = bool(re.search(r"WORKERS_ENABLED\s*=\s*True", text)) or (
        "Thread" in text and not re.search(r"WORKERS_ENABLED\s*=\s*False", text))
    stable, totals_seen = True, set()
    for _ in range(8):
        got, _ = timed_run(ws, ws / "data" / "feed.csv", ws)
        if not got:
            stable = False
            break
        totals_seen.add((got.get("rows"), got.get("total")))
    stable = stable and len(totals_seen) == 1
    r["parts"]["race_fixed_workers_on"] = {
        "ok": workers_on and stable,
        "detail": f"workers enabled: {workers_on}; 8 runs gave {len(totals_seen)} distinct result(s)"}

    # --- 4: the review
    rv = next((p for p in ws.rglob("REVIEW.md") if ".git" not in p.parts), None)
    rtext = rv.read_text(errors="replace") if rv else ""
    located = re.findall(r"[\w/]+\.py[:\s]+\d+|line\s+\d+", rtext, re.I)
    substantial = len(rtext.split()) >= 60
    r["parts"]["review_written"] = {
        "ok": bool(rv) and substantial and len(located) >= 2,
        "detail": (f"{len(rtext.split())} words, {len(located)} located finding(s)" if rv
                   else "no REVIEW.md")}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
