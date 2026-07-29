#!/usr/bin/env python3
"""Deterministic verifier for the ada-handles task — the m15 walk, mechanized.

Success is NEVER the model's claim, a critic verdict, or a green gate (m13 looked done and
wasn't): this runs the deliverables itself, outside the session, and scores what actually works.
Four deliverables, one point each; hard success requires all four AND the live test proving a
REAL resolution (a mocked "live" test scores zero — the m14 lesson).

Usage: verify.py <workspace>  → prints one JSON object on stdout, exit 0 always (the score is
the result; only a verifier bug exits nonzero).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

TIMEOUT = 120
# Real Cardano artifacts in output = the resolution actually happened against the real API.
ADDR_RE = re.compile(r"addr1[0-9a-z]{20,}")
HOLDER_RE = re.compile(r"stake1[0-9a-z]{20,}")


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier must report, not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def main(ws: Path) -> dict:
    r = {"task": "ada-handles", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) Unit tests: pytest discovers and passes ≥1 real test.
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    m = re.search(r"(\d+) passed", out)
    unit_ok = code == 0 and bool(m) and int(m.group(1)) > 0
    r["parts"]["unit_tests"] = {"ok": unit_ok, "passed": int(m.group(1)) if m else 0,
                                "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # 2) Live test: find it, RUN it, and demand evidence of a real resolution (addr1 + stake1
    #    in output). Shape-agnostic: any file whose name mentions "live".
    live_files = sorted(p for p in ws.glob("*.py") if "live" in p.name.lower())
    live_ok, live_detail = False, "no live-test file found"
    for lf in live_files:
        code, out = run([sys.executable, lf.name], ws)
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out):
            live_ok, live_detail = True, f"{lf.name}: real resolution (addr1+stake1 present)"
            break
        live_detail = f"{lf.name}: exit={code}, real-data markers {'partial' if ADDR_RE.search(out) or HOLDER_RE.search(out) else 'absent'}"
    r["parts"]["live_test"] = {"ok": live_ok, "detail": live_detail}

    # 3) Resolver works as the README says — or, failing README instructions, the conventional
    #    `python3 <main>.py goose` shape. Demands all three facts: address, holder, a count.
    mains = [p for p in ws.glob("*.py")
             if "test" not in p.name.lower() and "live" not in p.name.lower()]
    cli_ok, cli_detail = False, "no candidate resolver script"
    for cand in sorted(mains, key=lambda p: -p.stat().st_size):
        code, out = run([sys.executable, cand.name, "goose"], ws)
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out) and re.search(r"\d+", out):
            cli_ok, cli_detail = True, f"{cand.name} goose → address+holder+count"
            break
        cli_detail = f"{cand.name}: exit={code}"
    r["parts"]["resolver_cli"] = {"ok": cli_ok, "detail": cli_detail}

    # 4) README exists and covers install + how to run script AND tests.
    readme = next((p for p in ws.iterdir() if p.name.lower().startswith("readme")), None)
    if readme:
        text = readme.read_text(errors="replace").lower()
        readme_ok = ("install" in text or "pip" in text) and ("test" in text) and ("run" in text or "usage" in text)
        r["parts"]["readme"] = {"ok": readme_ok, "detail": f"{readme.name} covers install/run/tests: {readme_ok}"}
    else:
        r["parts"]["readme"] = {"ok": False, "detail": "no README"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    return r


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=1))
