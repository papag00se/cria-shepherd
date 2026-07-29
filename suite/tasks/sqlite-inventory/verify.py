#!/usr/bin/env python3
"""Deterministic verifier for sqlite-inventory. The prompt PINS the CLI interface, so
verification exercises exactly that contract — no shape-guessing. Fully offline."""

import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def main(ws: Path) -> dict:
    r = {"task": "sqlite-inventory", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    py = sys.executable

    # 1) The pinned CLI contract end-to-end: add, restock accumulation, list, value.
    (ws / "inventory.db").unlink(missing_ok=True)   # fresh db for the contract check
    cli_ok, detail = False, ""
    c1, o1 = run([py, "inventory.py", "add", "widget", "3", "2.50"], ws)
    c2, o2 = run([py, "inventory.py", "add", "widget", "2", "2.50"], ws)   # restock → qty 5
    c3, o3 = run([py, "inventory.py", "add", "gadget", "1", "10.00"], ws)
    cl, ol = run([py, "inventory.py", "list"], ws)
    cv, ov = run([py, "inventory.py", "value"], ws)
    if 0 in (c1, c2, c3) and cl == 0 and cv == 0:
        nums = re.findall(r"\d+(?:\.\d+)?", ov)
        # 3*2.5 + 2*2.5 + 1*10 = 22.5
        cli_ok = any(abs(float(n) - 22.5) < 0.01 for n in nums)
        detail = f"value output: {ov.strip()[:80]!r} (expect 22.5)"
    else:
        detail = f"exits add={c1},{c2},{c3} list={cl} value={cv}: {(o1+o2+o3+ol+ov)[-120:]!r}"
    r["parts"]["cli_contract"] = {"ok": cli_ok, "detail": detail}

    # 2) list actually shows both items with quantities.
    list_ok = cl == 0 and "widget" in ol and "gadget" in ol and "5" in ol
    r["parts"]["list_output"] = {"ok": list_ok, "detail": ol.strip()[:120]}

    # 3) Unit tests pass under pytest (unittest-style files are pytest-discoverable too).
    (ws / "inventory.db").unlink(missing_ok=True)
    code, out = run([py, "-m", "pytest", "-q", "--tb=no"], ws, timeout=120)
    m = re.search(r"(\d+) passed", out)
    unit_ok = code == 0 and bool(m) and int(m.group(1)) > 0
    r["parts"]["unit_tests"] = {"ok": unit_ok, "passed": int(m.group(1)) if m else 0,
                                "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # 4) README covers commands + tests.
    readme = next((p for p in ws.iterdir() if p.name.lower().startswith("readme")), None)
    if readme:
        text = readme.read_text(errors="replace").lower()
        readme_ok = "add" in text and "value" in text and "test" in text
        r["parts"]["readme"] = {"ok": readme_ok, "detail": f"{readme.name} covers add/value/tests: {readme_ok}"}
    else:
        r["parts"]["readme"] = {"ok": False, "detail": "no README"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    return r


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=1))
