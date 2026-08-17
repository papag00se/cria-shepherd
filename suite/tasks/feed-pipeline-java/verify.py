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
import shutil
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


# Maven puts the USEFUL error first and its own boilerplate last, so a tail slice of the log is the
# one part guaranteed to say nothing. Taking `log[-200:]` gave every failed Java cell the identical
# detail — "[ERROR] For more information about the errors and possible solutions, please read the
# following articles: [ERROR] [Help 1] http://cwiki.apache.org/..." — while the real cause sat a
# hundred lines above. Cost twice in one cycle: cell 4 and cell 16 both reported that URL, and both
# times the actual reason (a fabricated API, then a missing opencsv package) had to be re-derived by
# re-running the build by hand. A detail line exists to say why a check failed.
_JAVAC_LINE = re.compile(r"^.*?\.java:\[\d+,\d+\].*$|^\s+symbol:\s+.*$|^\s+location:\s+.*$", re.M)


def _javac_errors(log: str, limit: int = 6) -> str:
    """The compiler's own located errors, or a tail slice when it produced none (a plugin failure,
    a missing dependency resolution) — never Maven's "for more information" trailer alone."""
    hits = [re.sub(r"\x1b\[[0-9;]*m", "", m.group(0)).strip() for m in _JAVAC_LINE.finditer(log)]
    hits = [h for h in hits if h and "For more information" not in h and "[Help" not in h]
    if hits:
        more = f" (+{len(hits) - limit} more)" if len(hits) > limit else ""
        return " | ".join(hits[:limit]) + more
    return log.strip()[-200:]


def build(root: Path) -> tuple[str | None, str]:
    """Build with Maven and return the FULL runtime classpath — the project's own classes plus
    every resolved dependency.

    Maven, not bare javac: the task now asks the model to pull in a CSV parser, and a build that
    cannot resolve a dependency cannot verify one. `dependency:build-classpath` is how the jars get
    onto the classpath the bench and the CLI probe run against; without it the model's own code
    would compile and then fail at runtime with NoClassDefFoundError, which would read as a model
    failure and is not one."""
    if not (root / "pom.xml").exists():
        return None, "no pom.xml"
    code, log = run(["mvn", "-B", "-q", "compile"], root, timeout=420)
    if code != 0:
        return None, f"mvn compile failed: {_javac_errors(log)}"
    cp_file = root / "target" / "_verify_cp.txt"
    code, log = run(["mvn", "-B", "-q", "dependency:build-classpath",
                     f"-Dmdep.outputFile={cp_file}"], root, timeout=420)
    deps = cp_file.read_text().strip() if cp_file.exists() else ""
    classes = root / "target" / "classes"
    if not classes.is_dir():
        return None, "mvn compile produced no target/classes"
    return (f"{classes}:{deps}" if deps else str(classes)), "built"


def timed_run(root: Path, classpath: str, feed: Path):
    """Compile the bench against `classpath` and run it. Returns (parsed_json|None, output)."""
    bench_dir = Path(tempfile.mkdtemp())
    (bench_dir / "Bench.java").write_text(BENCH)
    code, log = run(["javac", "-nowarn", "-cp", classpath, "-d", str(bench_dir),
                     str(bench_dir / "Bench.java")], root, timeout=240)
    if code != 0:
        return None, f"bench did not compile against their code: {log.strip()[-200:]}"
    code, out = run(["java", "-cp", f"{classpath}:{bench_dir}", "Bench", str(feed)], root)
    m = re.search(r"VERIFY_JSON=(\{.*\})", out)
    return (json.loads(m.group(1)) if m else None), out


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "feed-pipeline-java", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    tmp = Path(tempfile.mkdtemp())

    their_cp, build_detail = build(ws)
    built = their_cp is not None

    # --- 1: the messy feed
    messy = ws / "data" / "feed_messy.csv"
    if not messy.exists():
        messy = HERE / "seed" / "data" / "feed_messy.csv"
    if built:
        code, out = run(["java", "-cp", their_cp, "pipeline.Importer", str(messy)], ws)
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
    # BUILD THE BASELINE IN A COPY, NOT IN THE REPO. `build()` runs `mvn compile` and
    # `dependency:build-classpath`, both of which WRITE — so pointing it at HERE/"seed" compiled the
    # reference implementation inside the git working tree on every scoring run. That is how five
    # build artefacts came to be tracked (target/classes/*.class, maven-status/*.lst,
    # _verify_cp.txt): they appeared under the author's feet during 0c16f52, whose long commit
    # message never mentions them, and they have been committed ever since.
    #
    # The baseline must be built on THIS machine — that is the whole point of timing it here — but
    # nothing required it to be built in the tracked tree, and this function already makes temp dirs
    # two lines above. Scoring a run must not dirty the repo.
    seed_copy = tmp / "seed-baseline"
    shutil.copytree(HERE / "seed", seed_copy)
    seed_cp, _ = build(seed_copy)
    theirs, their_out = (timed_run(ws, their_cp, big) if built else (None, build_detail))
    mine, _ = (timed_run(seed_copy, seed_cp, big) if seed_cp else (None, ""))
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
            got, _ = timed_run(ws, their_cp, feed)
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
    # CASE IS NOT THE PROPERTY THE TASK ASKS FOR. `rglob("REVIEW.md")` is case-sensitive, so a
    # review written to `review.md` scored zero for its capitalisation. The task asks for a
    # document describing remaining problems with file names and line numbers; it never says how
    # to case the filename. A check may only fail a run over the property the task names.
    rv = next((p for p in sorted(ws.rglob("*"))
               if p.is_file() and p.name.lower() == "review.md" and ".git" not in p.parts), None)
    rtext = rv.read_text(errors="replace") if rv else ""
    # A LOCATED FINDING IS A FILE AND A NUMBER NEAR EACH OTHER. The task asks for a review whose
    # findings say WHERE; it never says how to write a location down. This matched
    # `Importer.java:31` and the bare words "line 31", and missed "Lines 31-33 of Importer.java" —
    # a correctly located finding scored as unlocated because of how the reviewer punctuated it.
    # Same class as b623d90: assert the property the task names, nothing adjacent.
    #
    # THE WINDOW WAS FOUR AND A MARKDOWN TABLE NEEDS FIVE. Cycle 2, feed-pipeline-java x
    # ternary-bonsai wrote 729 words of findings in a `| File | Line(s) | Before | After |` table:
    #     | `src/main/java/pipeline/Importer.java` | ~45–50 | `knownSkus()` used ArrayList.contains |
    # Between `.java` and the number sit a backtick, a space, a pipe, a space and a tilde — five
    # non-word characters against a window of four. It scored 0 located findings and lost the check;
    # at five it finds 13. A table is the most natural way to write "the file and the line", and
    # nothing in the task forbids it. Widened to 24, which spans a table cell without reaching the
    # next row: a cell's own text sits between the two, so a wider window cannot pair a filename
    # with some other row's number. Checked against every REVIEW.md on disk — exactly one row moves
    # (this one, 0 -> 13); nemotron's 419-word review has no located findings under either window
    # and stays correctly at 0.
    located = re.findall(
        r"[\w/]+\.java\W{0,24}\d+"         # Importer.java:31 · `Importer.java` (31) · | ~45–50 |
        r"|[\w/]+\.java\W{0,12}?lines?\W{0,4}\d+"   # Importer.java, on line 31
        r"|lines?\W{0,4}\d+(?:\s*[-–]\s*\d+)?",     # line 31 · Lines 31-33
        rtext, re.I)
    substantial = len(rtext.split()) >= 60
    r["parts"]["review_written"] = {
        "ok": bool(rv) and substantial and len(located) >= 2,
        "detail": (f"{len(rtext.split())} words, {len(located)} located finding(s)" if rv
                   else "no REVIEW.md")}

    # --- 5: a real CSV parser, proven by BEHAVIOUR first.
    #
    # The messy feed carries `SKU-0007,"widget, blue",2,12.50` — a comma inside a quoted field.
    # Splitting on commas shifts every later column on that row, so the quantity becomes ` blue"`
    # and the row is dropped or mangled. A parser that understands quoting imports it at 25.00.
    # That is the check that matters, and it is behavioural: no grep for a package name, which
    # would be exactly the task-specific overfit the doctrine forbids.
    #
    # The declared-dependency half is secondary and exists because the prompt asks for a library
    # rather than a hand-rolled parser. Behaviour alone cannot buy the point, and neither can a
    # dependency added and ignored.
    quoted_ok, csv_detail = False, "did not build"
    if built:
        code, out = run(["java", "-cp", their_cp, "pipeline.Importer", str(messy)], ws)
        quoted_ok = bool(re.search(r"SKU-0007\D+25\.00", out))
        csv_detail = ("quoted-comma row imported at 25.00" if quoted_ok
                      else "quoted-comma row (SKU-0007) missing or mis-parsed")
    pom = ws / "pom.xml"
    declared = re.findall(r"<artifactId>\s*([\w.-]+)\s*</artifactId>",
                          pom.read_text(errors="replace")) if pom.exists() else []
    # The project's own artifactId and the build plugins are not dependencies it went and found.
    declared = [d for d in declared
                if d != "feed-importer" and not d.startswith("maven-")]
    r["parts"]["csv_library"] = {
        "ok": quoted_ok and bool(declared),
        "detail": f"{csv_detail}; declared deps: {declared or 'none'}"}

    # max_score follows the checks — the battery scores by percentage, so a task carries as many
    # checks as its work needs and a constant here would silently misreport every run.
    r["max_score"] = float(len(r["parts"]))
    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
