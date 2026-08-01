#!/usr/bin/env python3
"""Verifier for bug-report-go (category 2: fix a bug from a user report).

The seed ships a WORKING build and a GREEN suite. There is no failing test to lean on — only a
symptom in the prompt, exactly as a customer would report it: totals are a cent low. The cause is
`float64(int(taxed*100))/100`, which truncates where the shop rounds. Every existing test was
chosen to pass under BOTH behaviours, so the model cannot find the bug by running the suite; it
has to reproduce the reported cart.

Four points:

  1. the existing suite still passes (no regression, and the tests are byte-identical)
  2. the exact cart the customer reported now totals 48.58
  3. HIDDEN cases round correctly too — four more carts where truncation and rounding differ, so
     special-casing the reported numbers scores nothing
  4. behaviour that was never in question is untouched (an unknown code still errors)

`go test -count=1` throughout: Go replays a cached pass without executing anything.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 300


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


PROBE = '''package main

import (
	"fmt"
	cartsvc "cartsvc"
)

func main() {
	c := &cartsvc.Cart{Items: []cartsvc.Item{{Name: "widget", Price: 19.99, Quantity: 3}}, Code: "SUMMER25"}
	t, err := c.Total()
	if err != nil {
		fmt.Println("ERR", err)
		return
	}
	fmt.Printf("%.2f\\n", t)
}
'''


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "bug-report-go", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    code, out = run(["go", "test", "-count=1", "./..."], ws)
    suite_ok = code == 0 and not re.search(r"^(FAIL|---\s+FAIL)", out, re.M)
    seed_test = HERE / "seed" / "cart_test.go"
    live_test = next((p for p in ws.rglob("cart_test.go") if ".git" not in p.parts), None)
    intact = live_test is not None and _sha(live_test) == _sha(seed_test)
    r["parts"]["suite_still_green"] = {
        "ok": suite_ok and intact,
        "detail": (out.strip().splitlines()[-1] if out.strip() else "no output")
                  + ("" if intact else "  [existing tests were MODIFIED]")}

    # The reported cart, computed by the model's own code.
    probe_dir = ws / "_verify_probe"
    reported_ok, reported_detail = False, "probe did not build"
    try:
        probe_dir.mkdir(exist_ok=True)
        (probe_dir / "main.go").write_text(PROBE)
        code, out = run(["go", "run", "./_verify_probe"], ws)
        val = out.strip().splitlines()[-1].strip() if out.strip() else ""
        reported_ok = code == 0 and val == "48.58"
        reported_detail = f"reported cart totals {val or out.strip()[-60:]} (want 48.58)"
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    r["parts"]["reported_cart_fixed"] = {"ok": reported_ok, "detail": reported_detail}

    # Hidden cases: truncation and rounding differ on every one.
    hidden = ws / "hidden_cart_test.go"
    hidden_ok, hidden_detail = False, "hidden tests not run"
    try:
        shutil.copy(HERE / "hidden" / "hidden_cart_test.go", hidden)
        code, out = run(["go", "test", "-count=1", "-run",
                         "TestRoundingAcrossManyCarts|TestReportedCartRoundsUp", "./..."], ws)
        hidden_ok = code == 0 and not re.search(r"^(FAIL|---\s+FAIL)", out, re.M)
        hidden_detail = out.strip().splitlines()[-1] if out.strip() else "no output"
        code2, out2 = run(["go", "test", "-count=1", "-run", "TestUnknownCodeStillErrors", "./..."], ws)
        untouched_ok = code2 == 0 and not re.search(r"^(FAIL|---\s+FAIL)", out2, re.M)
        untouched_detail = out2.strip().splitlines()[-1] if out2.strip() else "no output"
    finally:
        hidden.unlink(missing_ok=True)
    r["parts"]["hidden_cases_round"] = {"ok": hidden_ok, "detail": hidden_detail[:120]}
    r["parts"]["unrelated_behaviour_intact"] = {"ok": untouched_ok, "detail": untouched_detail[:120]}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
