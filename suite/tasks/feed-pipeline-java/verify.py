#!/usr/bin/env python3
"""Verifier for feed-pipeline-java — categories 17 (data transform), 10 (optimise),
13 (concurrency), 20 (code review). The Java member of the battery.

The seed importer is slow by construction (an O(n^2) SKU scan), racy by construction (an
unsynchronised HashMap and a non-atomic counter shared across threads, which is why
WORKERS_ENABLED is false), and throws on the messy feed. Four points:

  1. the messy feed is handled — no crash, sensible rows imported, and the summary SAYS how many
     rows were skipped
  2. substantially faster: timed against the SEED's own implementation on the same machine in the
     same conditions, so the bar cannot drift with hardware or load
  3. the race is fixed AND the workers are back on — checked by running the import many times and
     demanding identical totals, with the code showing parallelism enabled
  4. REVIEW.md names real, located issues

Correctness is checked before speed: an importer that is fast because it stopped counting is not an
optimisation. Both sides are measured through a generated harness that calls `summarize` directly,
so the timing excludes JVM start-up and the numbers compare like with like.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 600
SPEEDUP_BAR = 4.0
BIG_ROWS, BIG_SKUS = 120_000, 25_000
STABILITY_RUNS = 8

# Calls summarize() directly and reports wall time excluding JVM start-up, so the comparison is of
# the code and not of the runtime. Warms up once first for the same reason.
BENCH = """
import pipeline.Importer;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadMXBean;
import java.util.Map;

public class Bench {
    public static void main(String[] args) throws Exception {
        Importer.summarize(args[0]);                       // warm-up, not measured
        ThreadMXBean tmx = ManagementFactory.getThreadMXBean();
        tmx.resetPeakThreadCount();                        // peak := live count, right now
        int before = tmx.getThreadCount();
        long t0 = System.nanoTime();
        Importer.Summary s = Importer.summarize(args[0]);
        double secs = (System.nanoTime() - t0) / 1e9;
        int spawned = tmx.getPeakThreadCount() - before;   // threads the import actually started
        double total = 0;
        for (Map.Entry<String, Double> e : s.totals.entrySet()) total += e.getValue();
        System.out.println("VERIFY_JSON={\\"secs\\":" + secs + ",\\"rows\\":" + s.rows
                           + ",\\"skus\\":" + s.skus + ",\\"spawned\\":" + spawned
                           + ",\\"total\\":" + (Math.round(total * 100) / 100.0) + "}");
    }
}
"""


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier reports, it does not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def make_big_feed(path: Path):
    import csv
    import random
    random.seed(11)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "description", "quantity", "unit_price"])
        for i in range(BIG_ROWS):
            w.writerow([f"SKU-{i % BIG_SKUS:05d}", f"item {i}",
                        random.randint(1, 40), round(random.uniform(1, 90), 2)])


def build(root: Path, out: Path) -> tuple[bool, str]:
    """Compile every .java under root into out. Returns (ok, detail)."""
    sources = [str(p) for p in sorted(root.rglob("*.java"))
               if ".git" not in p.parts and p.name != "Bench.java"]
    if not sources:
        return False, "no .java sources found"
    out.mkdir(parents=True, exist_ok=True)
    code, log = run(["javac", "-nowarn", "-d", str(out), *sources], root, timeout=240)
    return code == 0, (log.strip()[-200:] if code else f"compiled {len(sources)} file(s)")


def timed_run(root: Path, classes: Path, feed: Path):
    """Compile the bench against `classes` and run it. Returns (parsed_json|None, output)."""
    bench_dir = Path(tempfile.mkdtemp())
    (bench_dir / "Bench.java").write_text(BENCH)
    code, log = run(["javac", "-nowarn", "-cp", str(classes), "-d", str(bench_dir),
                     str(bench_dir / "Bench.java")], root, timeout=240)
    if code != 0:
        return None, f"bench did not compile against their code: {log.strip()[-200:]}"
    code, out = run(["java", "-cp", f"{classes}:{bench_dir}", "Bench", str(feed)], root)
    m = re.search(r"VERIFY_JSON=(\{.*\})", out)
    return (json.loads(m.group(1)) if m else None), out


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "feed-pipeline-java", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    tmp = Path(tempfile.mkdtemp())

    their_classes = tmp / "theirs"
    built, build_detail = build(ws, their_classes)

    # --- 1: the messy feed
    messy = ws / "data" / "feed_messy.csv"
    if not messy.exists():
        messy = HERE / "seed" / "data" / "feed_messy.csv"
    if built:
        code, out = run(["java", "-cp", str(their_classes), "pipeline.Importer", str(messy)], ws)
        crashed = code != 0 or "Exception" in out
        reports_skips = bool(re.search(r"skip|ignored|rejected|malformed|invalid", out, re.I))
        counts_something = bool(re.search(r"\b[1-9]\d*\b", out))
        detail = f"exit={code}, crashed={crashed}, reports skipped rows={reports_skips}"
    else:
        crashed, reports_skips, counts_something = True, False, False
        detail = f"did not compile: {build_detail}"
    r["parts"]["messy_feed_handled"] = {
        "ok": built and (not crashed) and reports_skips and counts_something, "detail": detail}

    # --- 2: speed, against the seed's own implementation on the same big feed
    big = tmp / "big.csv"
    make_big_feed(big)
    seed_classes = tmp / "seed"
    seed_built, _ = build(HERE / "seed", seed_classes)
    theirs, their_out = (timed_run(ws, their_classes, big) if built else (None, build_detail))
    mine, _ = (timed_run(HERE / "seed", seed_classes, big) if seed_built else (None, ""))
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
        speed_detail = f"their importer failed on the large feed: {str(their_out).strip()[-90:]}"
    r["parts"]["substantially_faster"] = {"ok": speed_ok, "detail": speed_detail}

    # --- 3: the race, and the workers actually on.
    #
    # "Workers on" is MEASURED, not read off the source. Flipping WORKERS_ENABLED to true while
    # importing serially satisfies every static check and fixes nothing — there is no race in code
    # that never forks. The bench resets the JVM's peak-thread counter immediately before the timed
    # import, so `spawned` is the number of threads that import actually started.
    stable, seen, spawned = built, set(), 0
    if built:
        feed = ws / "data" / "feed.csv"
        if not feed.exists():
            feed = HERE / "seed" / "data" / "feed.csv"
        for _ in range(STABILITY_RUNS):
            got, _ = timed_run(ws, their_classes, feed)
            if not got:
                stable = False
                break
            seen.add((got.get("rows"), got.get("total")))
            spawned = max(spawned, int(got.get("spawned") or 0))
        stable = stable and len(seen) == 1
    workers_on = spawned >= 2
    r["parts"]["race_fixed_workers_on"] = {
        "ok": workers_on and stable,
        "detail": f"import spawned {spawned} thread(s) (need >=2); "
                  f"{STABILITY_RUNS} runs gave {len(seen)} distinct result(s)"}

    # --- 4: the review
    rv = next((p for p in ws.rglob("REVIEW.md") if ".git" not in p.parts), None)
    rtext = rv.read_text(errors="replace") if rv else ""
    located = re.findall(r"[\w/]+\.java[:\s]+\d+|line\s+\d+", rtext, re.I)
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
