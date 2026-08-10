#!/usr/bin/env python3
"""Verifier for cart-billing-go (category 2: fix a bug from a user report).

The seed ships a WORKING build and a GREEN suite. There is no failing test to lean on — only a
symptom in the prompt, exactly as a customer would report it: totals are a cent low. The cause is
`float64(int(taxed*100))/100`, which truncates where the shop rounds. Every existing test was
chosen to pass under BOTH behaviours, so the model cannot find the bug by running the suite; it
has to reproduce the reported cart.

Four points:

  1. the existing suite still passes, every seeded test survives with its body intact, AND the
     model added a regression test of its own (additions are free — see _seedtests.py)
  2. the reported cart AND four hidden carts round correctly — special-casing the ticket's numbers
     scores nothing
  3. discount codes load from discounts.json, and a MISSING file still falls back rather than
     failing (the prompt asks for that explicitly)
  4. the README covers running it, running the tests, and how ops edit the discount file

`go test -count=1` throughout: Go replays a cached pass without executing anything.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _seedtests  # noqa: E402

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


# Runs two real carts and captures whatever the code logs. A discount cart and a bare one, so a
# logger that only fires on the discount path is visible as such.
LOG_PROBE = '''package main

import (
	cartsvc "cartsvc"
)

func main() {
	c := &cartsvc.Cart{Items: []cartsvc.Item{{Name: "widget", Price: 19.99, Quantity: 3}}, Code: "SUMMER25"}
	_, _ = c.Total()
	b := &cartsvc.Cart{Items: []cartsvc.Item{{Name: "pen", Price: 2.50, Quantity: 2}}}
	_, _ = b.Total()
}
'''

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
	// A MARKER, not the last line: the task asks for logging, so stderr now carries lines of its
	// own and "the last line of the output" stopped being the answer the moment that landed.
	fmt.Printf("VERIFY_TOTAL=%.2f\\n", t)
}
'''


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "cart-billing-go", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    code, out = run(["go", "test", "-count=1", "./..."], ws)
    suite_ok = code == 0 and not re.search(r"^(FAIL|---\s+FAIL)", out, re.M)

    # Per-test-function integrity, NOT a file hash. The two checks below used to be unsatisfiable
    # together for the obvious solution: `intact` demanded cart_test.go be byte-identical, while
    # `own_test` demanded some *_test.go differ from the seed — so appending the regression test to
    # the file that already has tests failed the first, and satisfying the first meant the new test
    # had to live in a file the prompt never asked for. Measured: gemma4 inserted exactly the
    # regression test the ticket describes, an 18-line pure insertion leaving all three seeded tests
    # untouched, and scored 3/4 for it. True score 4/4. Shared with every other seeded task in the
    # battery — see suite/tasks/_seedtests.py for the full account.
    intact, intact_detail = _seedtests.unchanged(HERE / "seed", ws, "go")
    seeded_names = set(_seedtests.go_tests((HERE / "seed" / "cart_test.go").read_text()))
    live_names: set[str] = set()
    for p in ws.rglob("*_test.go"):
        if ".git" not in p.parts:
            live_names |= set(_seedtests.go_tests(p.read_text(errors="replace")))
    own_test = bool(live_names - seeded_names)
    r["parts"]["suite_green_plus_regression_test"] = {
        "ok": suite_ok and intact and own_test,
        "detail": (out.strip().splitlines()[-1] if out.strip() else "no output")
                  + ("" if intact else f"  [{intact_detail}]")
                  + ("" if own_test else "  [no regression test of its own]")}

    # The reported cart, computed by the model's own code.
    probe_dir = ws / "_verify_probe"
    reported_ok, reported_detail = False, "probe did not build"
    try:
        probe_dir.mkdir(exist_ok=True)
        (probe_dir / "main.go").write_text(PROBE)
        code, out = run(["go", "run", "./_verify_probe"], ws)
        m = re.search(r"VERIFY_TOTAL=([0-9.]+)", out)
        val = m.group(1) if m else ""
        reported_ok = code == 0 and val == "48.58"
        reported_detail = f"reported cart totals {val or out.strip()[-60:]} (want 48.58)"
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)

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
    # The reported case and the hidden ones are ONE point: fixing only the cart in the ticket is
    # the special-case cheat, and scoring them apart would pay half a mark for it.
    r["parts"]["rounding_fixed_everywhere"] = {
        "ok": reported_ok and hidden_ok,
        "detail": f"{reported_detail}; hidden cases: {hidden_detail[:60]}"}

    # Discount codes come from a file, and a MISSING file still works — the prompt asks for the
    # fallback explicitly, and "works only when the file exists" is the usual half-done shape.
    cfg = next((p for p in ws.rglob("discounts.json") if ".git" not in p.parts), None)
    cfg_ok, cfg_detail = False, "no discounts.json"
    if cfg is not None:
        try:
            codes = json.loads(cfg.read_text())
            has_codes = all(k in json.dumps(codes) for k in ("WELCOME10", "SUMMER25", "VIP50"))
        except ValueError:
            has_codes = False
        moved = cfg.read_text().strip() != ""
        stash = cfg.with_suffix(".json.hidden")
        try:
            cfg.rename(stash)
            code_nf, out_nf = run(["go", "test", "-count=1", "./..."], ws)
            fallback_ok = code_nf == 0 and not re.search(r"^(FAIL|---\s+FAIL)", out_nf, re.M)
        finally:
            stash.rename(cfg)
        cfg_ok = has_codes and moved and fallback_ok
        cfg_detail = (f"discounts.json present, all three codes: {has_codes}, "
                      f"still builds+passes without the file: {fallback_ok}")
    r["parts"]["discounts_from_file"] = {"ok": cfg_ok, "detail": cfg_detail}

    # Logging: ONE line per total, on stderr, carrying the three facts support needs to grep.
    # Checked by running real carts and reading what actually came out — not by grepping the source
    # for the word "log", which a single unused import would satisfy.
    log_ok, log_detail = False, "no log line observed on stderr"
    probe_dir = ws / "_verify_logprobe"
    try:
        probe_dir.mkdir(exist_ok=True)
        (probe_dir / "main.go").write_text(LOG_PROBE)
        code, out = run(["go", "run", "./_verify_logprobe"], ws)
        err_lines = [l for l in out.splitlines() if "48.58" in l or "SUMMER25" in l]
        has_sub = any("44.98" in l or "59.97" in l or "44.97" in l for l in out.splitlines())
        has_code = any("SUMMER25" in l for l in out.splitlines())
        has_total = any("48.58" in l for l in out.splitlines())
        log_ok = code == 0 and has_code and has_total and has_sub
        log_detail = (f"stderr carried subtotal:{has_sub} code:{has_code} total:{has_total}"
                      + (f" | {err_lines[0][:60]}" if err_lines else ""))
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    r["parts"]["logging"] = {"ok": log_ok, "detail": log_detail}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
