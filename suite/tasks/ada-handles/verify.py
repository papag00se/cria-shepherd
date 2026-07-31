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
import os
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
    # RECURSIVE — the first version only looked at the workspace root, and a src-layout run
    # (gemma's habit) had its real tests/live.py scored "no live-test file found" (false FAIL).
    live_files = sorted(p for p in ws.rglob("*.py")
                        if "live" in p.name.lower() and "__pycache__" not in p.parts)
    live_ok, live_detail = False, "no live-test file found"
    for lf in live_files:
        code, out = run([sys.executable, str(lf.relative_to(ws))], ws)
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out):
            live_ok, live_detail = True, f"{lf.name}: real resolution (addr1+stake1 present)"
            break
        live_detail = f"{lf.name}: exit={code}, real-data markers {'partial' if ADDR_RE.search(out) or HOLDER_RE.search(out) else 'absent'}"
    if not live_ok:
        # Operator ruling (07-30): a live TEST inside the test file counts — it need not be a
        # separate file. It must still be provably LIVE (the m14 lesson: a mocked "live" test is
        # zero): with the network BLOCKED (dead proxy) the selected live tests must FAIL, and with
        # the network they must PASS. A mock passes both ways and scores nothing.
        dead = {**os.environ, "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}
        sel = [sys.executable, "-m", "pytest", "-q", "-k", "live", "--tb=no"]
        try:
            blocked = subprocess.run(sel, cwd=ws, capture_output=True, text=True,
                                     timeout=TIMEOUT, env=dead)
            normal = subprocess.run(sel, cwd=ws, capture_output=True, text=True, timeout=TIMEOUT)
            b_out, n_out = blocked.stdout + blocked.stderr, normal.stdout + normal.stderr
            n_pass = re.search(r"(\d+) passed", n_out)
            ran_some = bool(n_pass) and int(n_pass.group(1)) > 0
            needs_net = blocked.returncode != 0 or "failed" in b_out or "error" in b_out.lower()
            if ran_some and normal.returncode == 0 and needs_net:
                live_ok = True
                live_detail = f"in-file live test: {n_pass.group(1)} passed with network, fails without (provably live)"
            elif ran_some and normal.returncode == 0:
                live_detail = "in-file 'live' test passes even with the network blocked — mocked, not live"
        except subprocess.TimeoutExpired:
            live_detail = "in-file live check timed out"
    r["parts"]["live_test"] = {"ok": live_ok, "detail": live_detail}

    # 3) Resolver works as the README says — or, failing README instructions, the conventional
    #    `python3 <main>.py goose` shape. Demands all three facts: address, holder, a count.
    skip = ("__pycache__", "venv", ".venv", "testvenv", "site-packages", "node_modules")
    mains = [p for p in ws.rglob("*.py")
             if "test" not in p.name.lower() and "live" not in p.name.lower()
             and not any(x in p.parts for x in skip)]
    # Invocation forms, in the order a user would try them: what the README actually documents,
    # then `python file.py`, then `python -m pkg.module` (a package layout is a legitimate reading
    # of "write a script" — the earlier root-only-glob blindness, one level up).
    cmds = []
    readme_txt = ""
    rd = next((p for p in ws.iterdir() if p.name.lower().startswith("readme")), None)
    if rd:
        readme_txt = rd.read_text(errors="replace")
        for m in re.finditer(r"(?m)^\s*(?:\$\s*)?(python3?\s+(?:-m\s+)?[\w./-]+(?:\s+[\w-]+)*)\s*$", readme_txt):
            line = m.group(1)
            if "pip" in line or "venv" in line or "pytest" in line:
                continue
            parts = line.split()
            parts[0] = sys.executable
            cmds.append(parts if any(a in ("goose", "papagoose") for a in parts) else parts + ["goose"])
    for cand in sorted(mains, key=lambda p: -p.stat().st_size):
        rel = cand.relative_to(ws)
        cmds.append([sys.executable, str(rel), "goose"])
        if cand.name != "__init__.py":
            mod = ".".join(rel.with_suffix("").parts)
            cmds.append([sys.executable, "-m", mod, "goose"])
    cli_ok, cli_detail = False, "no candidate resolver script"
    for cmd in cmds:
        code, out = run(cmd, ws)
        shown = " ".join(cmd[1:])
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out) and re.search(r"\d+", out):
            cli_ok, cli_detail = True, f"{shown} → address+holder+count"
            break
        if code == 0 and ADDR_RE.search(out):   # it RAN and resolved, but is missing holder/count
            cli_detail = f"{shown}: ran, but holder/total missing (address only)"
        elif cli_detail.startswith("no candidate"):
            cli_detail = f"{shown}: exit={code}"
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
