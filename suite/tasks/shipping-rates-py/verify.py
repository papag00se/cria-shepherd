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
import ast
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


def _test_funcs(src: str) -> dict[str, str]:
    """{name: normalized source} for each top-level test function. Blank lines and trailing
    whitespace are ignored so a reformat is not read as a contract change; anything that alters an
    assertion changes the text and is caught."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            seg = ast.get_source_segment(src, node) or ""
            out[node.name] = "\n".join(l.rstrip() for l in seg.splitlines() if l.strip())
    return out


def _seeded_tests_unchanged(ws: Path) -> tuple[bool, str]:
    """Every seeded test still present, with its body byte-for-byte intact. ADDING tests is fine.

    This used to demand the seed file be byte-identical, which failed the task's own instructions:
    the prompt says "don't change what the tests ASSERT" and, two paragraphs later, "Add it, with
    tests". A model that appends its express tests to the existing file — the obvious place — was
    scored as having broken the contract. Measured on the first battery baseline run: gemma4
    appended three correct express tests, deleted nothing, left the suite green at 10 passed, and
    lost the point.

    The anti-cheat this protects is unchanged and is the whole reason the check exists: a green
    suite bought by deleting or weakening a failing assertion is not a pass. That is still caught —
    a removed test is missing, and an edited one has different source."""
    seed_funcs: dict[str, tuple[str, str]] = {}
    for seed_file in sorted(SEED_TESTS.glob("*.py")):
        for name, body in _test_funcs(seed_file.read_text(errors="replace")).items():
            seed_funcs[name] = (seed_file.name, body)
    if not seed_funcs:
        return True, "no seeded tests to protect"
    live_funcs: dict[str, str] = {}
    for p in ws.rglob("test_*.py"):
        if ".git" in p.parts:
            continue
        live_funcs.update(_test_funcs(p.read_text(errors="replace")))
    for name, (fname, body) in sorted(seed_funcs.items()):
        if name not in live_funcs:
            return False, f"seeded test {name}() from {fname} was deleted"
        if live_funcs[name] != body:
            return False, f"seeded test {name}() was modified — the contract was changed, not the code"
    added = len(live_funcs) - len(seed_funcs)
    return True, f"all {len(seed_funcs)} seeded tests intact" + (f", {added} added" if added > 0 else "")


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
    intact, detail = _seeded_tests_unchanged(ws)
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
                    for p in list(ws.rglob("test_*.py")) + list(ws.rglob("*_test.py"))
                    if ".git" not in p.parts)   # both pytest conventions, not just one
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
