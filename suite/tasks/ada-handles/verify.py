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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _liveprobe  # noqa: E402 — shared live-test fairness helpers

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


def positive_count(out: str) -> bool:
    """Is there a real handle COUNT in the output — not a digit borrowed from an address?

    The check here was `re.search(r"\\d+", out)`, which can never fail: a Cardano address
    (`addr1qxsfzsmy6y2seduagp6...`) and a stake address are both full of digits, so any run that
    printed an address scored the count for free.

    Caught on run 1785685170, which scored 4/4 while printing

        {"resolved_address": "addr1qxsf...", "holder_address": "stake1u85...", "total_handles": 0}

    The real value is 15 — the script read `total_handles` from the /handles/{handle} response, which
    does not carry it, and never called /holders/{address} at all. A third of the deliverable was
    wrong and the verifier said PASS.

    Strips the address-shaped tokens first, then requires a POSITIVE integer in what remains. Not the
    exact value: a holder can buy or sell handles, and pinning 15 would make this fail for a reason
    that has nothing to do with the code."""
    stripped = re.sub(r"\b(?:addr|stake|addr_test|stake_test)1[0-9a-z]+", " ", out)
    return any(int(n) > 0 for n in re.findall(r"\b\d+\b", stripped))


def main(ws: Path, capture=None) -> dict:
    r = {"task": "ada-handles", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) Unit tests: pytest discovers and passes ≥1 real test.
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    m = re.search(r"(\d+) passed", out)
    unit_ok = code == 0 and bool(m) and int(m.group(1)) > 0
    r["parts"]["unit_tests"] = {"ok": unit_ok, "passed": int(m.group(1)) if m else 0,
                                "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # 2) Live test — the walked fairness rules live in _liveprobe (shared with the language
    #    battery): dedicated live-named files (*.py/*.sh, recursive, handle-argument retry,
    #    provably-live judgment), then the in-file pytest branch below, then the README probe.
    live_ok, live_detail = _liveprobe.live_file_check(ws)
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
    if not live_ok:
        # Last resort: ask what the README says to run (see _liveprobe.readme_live_probe — the
        # model only proposes; execution with the provably-live rule decides).
        probe_ok, probe_detail = _liveprobe.readme_live_probe(ws)
        if probe_ok:
            live_ok, live_detail = True, probe_detail
        else:
            live_detail = f"{live_detail}; {probe_detail}"
    if not live_ok and capture is not None:
        # Operator ruling 2026-08-05: evidence that the coder's own executed code resolved a
        # task handle live, captured in the session, counts — "the spirit is there and the
        # interpretation is fair." Evidence rules live in _liveprobe.session_live_evidence.
        ev_ok, ev_detail = _liveprobe.session_live_evidence(capture)
        if ev_ok:
            live_ok, live_detail = True, ev_detail
        else:
            live_detail = f"{live_detail}; {ev_detail}"
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
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out) and positive_count(out):
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
    print(json.dumps(main(Path(sys.argv[1]).resolve(),
                      capture=sys.argv[2] if len(sys.argv) > 2 else None), indent=1))
