#!/usr/bin/env python3
"""Verifier for shipping-rates-py — a FOUR-skill task, weighted like ada-handles rather than a
single-bug exercise: debug an existing failure, implement a new zone from a spec in prose, cover it
with tests, and update documentation that already exists.

The seed ships working code, a green-but-for-one suite, and ONE real bug: an order EXACTLY at the
free-shipping threshold is charged, because the check is `>` where the contract is `>=`.

Four points, and the cheats are all worthless:

  1. the whole suite passes AND the seeded tests are byte-identical — deleting or loosening the
     failing assertion is the obvious way to go green, and the prompt forbids it
  2. HIDDEN tests pass: the same contract at inputs the model never saw, plus the new zone, so
     special-casing the visible numbers (`if order_total == 75.00: return 0.0`) scores nothing
  3. the express zone is implemented AND the model wrote its own tests for it (a zone that only
     the hidden tests exercise is untested work)
  4. the README carries a rate table naming every zone with its numbers

Hidden tests are copied in at scoring time and removed after, so nothing in the workspace hints at
them during the run.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 180
# The seed's test files, by sha256 — the model must fix the CODE, not the promise.
SEED_TESTS = HERE / "seed" / "tests"


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier reports, it does not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "shipping-rates-py", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) the suite passes
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    m = re.search(r"(\d+) passed", out)
    n_pass = int(m.group(1)) if m else 0
    suite_ok = code == 0 and n_pass >= 7
    suite_detail = out.strip().splitlines()[-1] if out.strip() else "no output"

    # ...and the seeded tests were not edited. ONE point with the suite result, deliberately:
    # a green suite bought by deleting the failing assertion is not a pass, so scoring them
    # separately would hand half a mark to the cheat the prompt explicitly forbids.
    intact, detail = True, "tests byte-identical to the seed"
    for seed_file in sorted(SEED_TESTS.glob("*.py")):
        live = next((p for p in ws.rglob(seed_file.name) if ".git" not in p.parts), None)
        if live is None:
            intact, detail = False, f"{seed_file.name} was deleted"
            break
        if _sha(live) != _sha(seed_file):
            intact, detail = False, f"{seed_file.name} was modified — the contract was changed, not the code"
            break
    r["parts"]["suite_green_tests_intact"] = {
        "ok": suite_ok and intact, "passed": n_pass,
        "detail": suite_detail + ("" if intact else f"  [{detail}]")}

    # 3) hidden tests: the same contract, inputs the model never saw
    hidden_src = HERE / "hidden" / "test_hidden_rates.py"
    hidden_dst = ws / "test_hidden_rates.py"
    hidden_ok, hidden_detail = False, "hidden tests not run"
    try:
        shutil.copy(hidden_src, hidden_dst)
        code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=line",
                         str(hidden_dst.name)], ws)
        hm = re.search(r"(\d+) passed", out)
        hidden_ok = code == 0 and bool(hm) and int(hm.group(1)) > 0
        hidden_detail = out.strip().splitlines()[-1] if out.strip() else "no output"
    finally:
        hidden_dst.unlink(missing_ok=True)
        shutil.rmtree(ws / ".pytest_cache", ignore_errors=True)
    r["parts"]["hidden_contract"] = {"ok": hidden_ok, "detail": hidden_detail}

    # 3) the express zone exists, prices correctly, AND the model tested it itself
    probe = ("import sys; sys.path.insert(0, '.');"
             "from shipping.rates import shipping_cost;"
             "print(shipping_cost('express', 0.0, 10.0), shipping_cost('express', 4.0, 10.0))")
    code, out = run([sys.executable, "-c", probe], ws)
    priced = code == 0 and out.strip().splitlines()[-1].strip().startswith("14.99 24.99")
    own_tests = any("express" in p.read_text(errors="replace").lower()
                    for p in ws.rglob("test_*.py") if ".git" not in p.parts)
    r["parts"]["express_zone"] = {
        "ok": priced and own_tests,
        "detail": f"prices {out.strip()[-24:]} (want 14.99 24.99); model wrote its own tests: {own_tests}"}

    # 4) the README gained a rate table covering every zone with its numbers
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    txt = rd.read_text(errors="replace").lower() if rd else ""
    zones_named = [z for z in ("domestic", "eu", "international", "express") if z in txt]
    rates_named = [v for v in ("4.99", "9.99", "19.99", "14.99", "0.75", "1.50", "3.25", "2.50")
                   if v in txt]
    r["parts"]["readme_rate_table"] = {
        "ok": len(zones_named) == 4 and len(rates_named) >= 6,
        "detail": f"zones named {zones_named}, {len(rates_named)}/8 rate values present"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
