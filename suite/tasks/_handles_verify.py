#!/usr/bin/env python3
"""Shared deterministic verifier for the handles-<language> battery.

One task per language, same problem, so the matrix isolates ONE variable: the language. The
Python original (ada-handles) keeps its own verifier — this is the port of its rules to a
per-language table.

Four deliverables, one point each; hard success needs all four:

  1. unit tests      the language's own runner discovers and passes >= 1 real test
  2. live test       a test/script that provably hits the REAL API — see `live` below
  3. CLI             running it as documented prints address + holder + a count
  4. README          install, run and test instructions

Scoring NEVER trusts the model's claim, a critic verdict, or a green gate. It runs the
deliverables itself, outside the session.

PROVABLY LIVE is the rule the Python task learned the hard way (a mocked "live" test scored a
point it had not earned): the live test must PASS with the network and FAIL without it. The block
is `unshare -rn` — an unprivileged network namespace with no interfaces — because it is the one
method that works for every language's HTTP client. Proxy environment variables do not: Go and
Ruby honour them, PHP's curl often does not, and Java ignores them entirely in favour of
-Dhttp.proxyHost. A language-specific block would have quietly awarded the point to the languages
whose clients ignore it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _liveprobe  # noqa: E402 — shared live-test fairness helpers (see its docstring)

TIMEOUT = 300           # a cold cargo/maven build is slow; a hang is caught by the wall, not here
LIVE_TIMEOUT = 180

# Real Cardano artifacts in the output = the resolution actually happened against the real API.
# The address and holder prefixes are self-identifying: nothing else in a program's output looks
# like `addr1…` or `stake1…`, so their presence IS the evidence.
ADDR_RE = re.compile(r"addr1[0-9a-z]{20,}")
HOLDER_RE = re.compile(r"stake1[0-9a-z]{20,}")

# THE COUNT IS NOT SELF-IDENTIFYING, and `\d+` was scoring it. Any digit anywhere passed — a slot
# number, a byte length, a timestamp. Walked on maple-preview 1786228135: the delivered program
# printed the address and the holder and NEVER the count (neither file it shipped ever calls
# /holders/{address}, the only endpoint that has one), and the run scored 4/4 because its JSON dump
# contained `"created_slot_number": 145829`. A run that did not deliver a third of the task looked
# identical to one that did — qwen35 1786230527 printed `Total Handles: 15` and scored the same.
#
# So the count must be LABELLED. A bare number proves nothing; a number the program itself calls a
# handle count is the deliverable. Kept language-neutral: any of the words a program would use,
# any separator, the number on either side of it (`Total Handles: 15`, `total_handles=15`,
# `"total_handles": 15`, `15 handles held`).
_COUNT_WORD = r"(?:total[_\s-]*handles?|handles?[_\s-]*(?:count|total|held)|handle[_\s-]*count)"
COUNT_RE = re.compile(rf"{_COUNT_WORD}\W{{0,4}}(\d+)|(\d+)\s+{_COUNT_WORD}", re.I)


def positive_count(out: str) -> bool:
    """A LABELLED, positive handle count in the program's output. THE one owner of this question.

    ada-handles/verify.py had its own copy that stripped address-shaped tokens and then accepted any
    positive integer left over. That fixed the run it was written for (`total_handles: 0`) and left
    the general hole open: maple-preview 1786228135 printed the address and the holder, never the
    count — neither file it shipped calls /holders/{address}, the only endpoint that has one — and
    scored 4/4 on `"created_slot_number": 145829`. Two verifiers, one question, and the weaker
    answer was the one scoring the ladder's main task."""
    return any(int(n) > 0 for m in COUNT_RE.finditer(out or "") for n in m.groups() if n)

SKIP_DIRS = ("__pycache__", ".git", "node_modules", "target", "vendor", ".venv", "venv",
             "build", "dist", ".gradle", ".m2")

# Per language: how its ecosystem runs tests, how a CLI is invoked, and what "tests passed" looks
# like in that runner's own words. Each pattern was taken from a REAL failing/passing run of that
# tool on this box, never from memory of its output format.
LANGS = {
    # `-count=1` is REQUIRED, not tidiness: `go test` caches a passing result and replays it
    # without running anything, so the network-blocked half of the liveness check returned a cached
    # "ok (cached)" and a genuinely live test was scored as mocked. Caught by running the verifier
    # against a known-good solution instead of trusting it.
    "go": {
        "test": [["go", "test", "-count=1", "./..."]],
        "pass": re.compile(r"^ok\s|\bPASS\b", re.M),
        "fail": re.compile(r"^(FAIL|---\s+FAIL)", re.M),
        "run": [["go", "run", ".", "goose"], ["go", "run", "./...", "goose"]],
        "tool": "go",
    },
    "rust": {
        "test": [["cargo", "test", "--quiet"]],
        "pass": re.compile(r"test result: ok\. (\d+) passed"),
        "fail": re.compile(r"test result: FAILED|error\[E\d+\]", re.M),
        "run": [["cargo", "run", "--quiet", "--", "goose"]],
        "tool": "cargo",
    },
    "node": {
        "test": [["npm", "test", "--silent"], ["node", "--test"]],
        "pass": re.compile(r"# pass (\d+)|(\d+) passing|Tests:\s+(\d+) passed"),
        "fail": re.compile(r"# fail [1-9]|(\d+) failing|Tests:.*\d+ failed", re.M),
        "run": [["node", "index.js", "goose"], ["node", "main.js", "goose"],
                ["npm", "start", "--silent", "goose"]],
        "tool": "node",
    },
    "ruby": {
        "test": [["rspec"], ["ruby", "-Ilib", "-e", "Dir['**/*_spec.rb'].each { |f| require File.expand_path(f) }"]],
        "pass": re.compile(r"(\d+) examples?, 0 failures"),
        "fail": re.compile(r"(\d+) examples?, [1-9]\d* failures?|Failure/Error"),
        "run": [["ruby", "main.rb", "goose"], ["ruby", "resolve.rb", "goose"]],
        "tool": "ruby",
    },
    "php": {
        "test": [["phpunit", "--no-configuration", "tests"], ["phpunit"]],
        "pass": re.compile(r"OK \((\d+) test"),
        "fail": re.compile(r"FAILURES!|ERRORS!"),
        "run": [["php", "main.php", "goose"], ["php", "resolve.php", "goose"]],
        "tool": "php",
    },
    "java": {
        "test": [["mvn", "-q", "-B", "test"]],
        "pass": re.compile(r"Tests run: (\d+), Failures: 0, Errors: 0"),
        "fail": re.compile(r"Tests run: \d+, Failures: [1-9]|BUILD FAILURE"),
        "run": [["mvn", "-q", "-B", "exec:java", "-Dexec.args=goose"]],
        "tool": "mvn",
    },
}


def run(cmd, cwd, timeout=TIMEOUT, blocked=False):
    """Run `cmd` in `cwd`. ``blocked=True`` runs it with NO network (unprivileged netns)."""
    argv = (["unshare", "-rn"] + list(cmd)) if blocked else list(cmd)
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -3, f"VERIFIER: {argv[0]} not installed"
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier reports, it does not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def _passed(spec, out):
    if spec["fail"].search(out):
        return 0
    m = spec["pass"].search(out)
    if not m:
        return 0
    nums = [g for g in (m.groups() or ()) if g and g.isdigit()]
    return int(nums[0]) if nums else 1


def unit_tests(ws, spec):
    for cmd in spec["test"]:
        code, out = run(cmd, ws)
        if code == -3:
            continue
        n = _passed(spec, out)
        if code == 0 and n:
            return True, n, f"{' '.join(cmd)}: {n} passed"
    return False, 0, f"no passing test run ({spec['tool']})"


def live_test(ws, spec, capture=None):
    """PASSES with the network and FAILS without it. A mock passes both ways and scores nothing.

    Three branches, most-specific first (the Python task's walked fairness rules, shared via
    _liveprobe): a dedicated live-named file (*.py/*.sh wrapper — legitimate in ANY language's
    workspace), then the language's own test suite, then the README-guided probe."""
    f_ok, f_detail = _liveprobe.live_file_check(ws)
    if f_ok:
        return True, f_detail
    for cmd in spec["test"]:
        code, out = run(cmd, ws, timeout=LIVE_TIMEOUT)
        if code == -3:
            continue
        if code != 0 or not _passed(spec, out):
            continue
        b_code, b_out = run(cmd, ws, timeout=LIVE_TIMEOUT, blocked=True)
        if b_code != 0 or spec["fail"].search(b_out):
            return True, f"{' '.join(cmd)}: passes with network, fails without (provably live)"
        return False, f"{' '.join(cmd)}: passes with the network BLOCKED — mocked, not live"
    p_ok, p_detail = _liveprobe.readme_live_probe(ws)
    if p_ok:
        return True, p_detail
    if capture is not None:
        # Operator ruling 2026-08-05 (ported from the Python task, fixes-in-both-paths): captured
        # evidence of the coder's own executed code resolving a task handle live counts.
        ev_ok, ev_detail = _liveprobe.session_live_evidence(capture)
        if ev_ok:
            return True, ev_detail
        p_detail = f"{p_detail}; {ev_detail}"
    return False, f"no runnable test suite to check for liveness; {p_detail}"


def _readme_commands(ws, spec):
    """Commands the README itself documents — tried before any convention."""
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    if not rd:
        return [], ""
    txt = rd.read_text(errors="replace")
    out = []
    for m in re.finditer(r"(?m)^\s*(?:\$\s*)?((?:go|cargo|node|npm|ruby|php|mvn|java)\s+[^\n`]+)$", txt):
        line = m.group(1).strip()
        if any(w in line for w in ("install", "add ", "init", "build", "test")):
            continue
        parts = line.split()
        out.append(parts if "goose" in parts else parts + ["goose"])
    return out, txt


def cli(ws, spec):
    cmds, _ = _readme_commands(ws, spec)
    cmds += spec["run"]
    detail = "no runnable CLI found"
    for cmd in cmds:
        code, out = run(cmd, ws)
        if code == -3:
            continue
        shown = " ".join(cmd)
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out) and positive_count(out):
            return True, f"{shown} → address+holder+count"
        if code == 0 and ADDR_RE.search(out):
            detail = f"{shown}: ran, but holder/total missing (address only)"
        elif detail.startswith("no runnable"):
            detail = f"{shown}: exit={code}"
    return False, detail


def readme(ws):
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    if not rd:
        return False, "no README"
    t = rd.read_text(errors="replace").lower()
    ok = ("install" in t or "depend" in t) and ("run" in t) and ("test" in t)
    return ok, f"{rd.name} covers install/run/tests: {ok}"


def verify(task: str, language: str, ws: Path, capture=None) -> dict:
    spec = LANGS[language]
    r = {"task": task, "language": language, "score": 0.0, "max_score": 4.0,
         "success": False, "parts": {}}
    if not shutil.which(spec["tool"]):
        r["parts"]["toolchain"] = {"ok": False, "detail": f"{spec['tool']} not installed on this box"}
        print(json.dumps(r))
        return r

    ok, n, detail = unit_tests(ws, spec)
    r["parts"]["unit_tests"] = {"ok": ok, "passed": n, "detail": detail}

    lok, ldetail = live_test(ws, spec, capture)
    r["parts"]["live_test"] = {"ok": lok, "detail": ldetail}

    cok, cdetail = cli(ws, spec)
    r["parts"]["resolver_cli"] = {"ok": cok, "detail": cdetail}

    rok, rdetail = readme(ws)
    r["parts"]["readme"] = {"ok": rok, "detail": rdetail}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    return r


def main(task: str, language: str) -> None:
    ws = Path(sys.argv[1]).resolve()
    capture = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(verify(task, language, ws, capture)))
