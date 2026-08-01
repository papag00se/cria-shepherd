#!/usr/bin/env python3
"""Verifier for failing-tests-py (category 3: investigate and resolve failing tests).

The seed ships working code, a working suite, and ONE real bug: an order EXACTLY at the
free-shipping threshold is charged, because the check is `>` where the contract is `>=`. Six tests
pass, one fails, and the failing test states the promise in its own name.

Four points, and three of them exist to make the easy cheats worthless:

  1. the whole suite passes
  2. the TESTS ARE BYTE-IDENTICAL to the seed — deleting or loosening the failing assertion is the
     obvious way to make a suite green, and the prompt explicitly forbids it
  3. HIDDEN tests pass — the same contract at inputs the model never saw, so special-casing the
     visible numbers (`if order_total == 75.00: return 0.0`) scores nothing
  4. the previously-failing behaviour is actually fixed

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
    r = {"task": "failing-tests-py", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) the suite passes
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    m = re.search(r"(\d+) passed", out)
    n_pass = int(m.group(1)) if m else 0
    suite_ok = code == 0 and n_pass >= 7
    r["parts"]["suite_passes"] = {
        "ok": suite_ok, "passed": n_pass,
        "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # 2) the tests were not edited
    intact, detail = True, "tests byte-identical to the seed"
    for seed_file in sorted(SEED_TESTS.glob("*.py")):
        live = next((p for p in ws.rglob(seed_file.name) if ".git" not in p.parts), None)
        if live is None:
            intact, detail = False, f"{seed_file.name} was deleted"
            break
        if _sha(live) != _sha(seed_file):
            intact, detail = False, f"{seed_file.name} was modified — the contract was changed, not the code"
            break
    r["parts"]["tests_intact"] = {"ok": intact, "detail": detail}

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

    # 4) the specific reported behaviour
    probe = ("import sys; sys.path.insert(0, '.');"
             "from shipping.rates import shipping_cost;"
             "print(shipping_cost('domestic', 3.0, 75.00))")
    code, out = run([sys.executable, "-c", probe], ws)
    fixed = code == 0 and out.strip().splitlines()[-1].strip() in ("0.0", "0", "0.00")
    r["parts"]["threshold_fixed"] = {
        "ok": fixed, "detail": f"shipping_cost('domestic', 3.0, 75.00) -> {out.strip()[-40:]}"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
