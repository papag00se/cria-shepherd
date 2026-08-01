#!/usr/bin/env python3
"""Verifier for missing-tests-py (category 4: write missing unit tests).

Counting tests is worthless — `assert True` counts. This scores the tests by MUTATION: seed a
deliberate bug into the module and check the model's suite goes red. A suite that stays green
against a broken ledger has tested nothing, however many cases it contains.

Four points:

  1. the suite runs and passes against the CORRECT module
  2. it is a real suite, not a token one (>= 5 tests, and they touch the module under test)
  3. MUTATION SCORE >= 60% — of the seeded bugs below, this fraction is caught
  4. every mutant class is caught at least once (arithmetic, comparison, guard removal), so a
     suite that only ever checks happy-path arithmetic cannot score full marks

Each mutant is a one-line edit that a competent suite would notice. They are applied to a COPY of
the workspace, so nothing the model wrote is disturbed.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 180
MODULE = Path("ledger") / "accounts.py"

# (class, description, find, replace). "class" groups them so a suite cannot ace one kind and
# ignore the others.
MUTANTS = [
    ("guard", "deposit accepts zero and negatives",
     'if amount <= 0:\n            raise ValueError("deposit must be positive")',
     'if amount < -1e9:\n            raise ValueError("deposit must be positive")'),
    ("guard", "withdrawal past the balance is allowed",
     "if self._balances[self._known(name)] < amount:",
     "if self._balances[self._known(name)] < -1e9:"),
    ("guard", "duplicate account names are allowed",
     'if name in self._balances:\n            raise ValueError(f"account already exists: {name}")',
     'if False:\n            raise ValueError(f"account already exists: {name}")'),
    ("arithmetic", "deposit subtracts instead of adding",
     "self._balances[self._known(name)] += float(amount)",
     "self._balances[self._known(name)] -= float(amount)"),
    ("arithmetic", "transfer credits the source, not the destination",
     "self.withdraw(src, amount)\n        self.deposit(dst, amount)",
     "self.withdraw(src, amount)\n        self.deposit(src, amount)"),
    ("comparison", "negative opening balances are accepted",
     "if opening_balance < 0:",
     "if opening_balance < -1e9:"),
    ("comparison", "total() drops the last account",
     "return round(sum(self._balances.values()), 2)",
     "return round(sum(list(self._balances.values())[:-1]), 2)"),
]
PASS_BAR = 0.60


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def pytest_counts(out):
    p = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) (?:failed|error)", out)
    return (int(p.group(1)) if p else 0), (int(f.group(1)) if f else 0)


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "missing-tests-py", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    n_pass, n_fail = pytest_counts(out)
    green = code == 0 and n_pass > 0 and n_fail == 0
    r["parts"]["suite_passes"] = {"ok": green, "passed": n_pass,
                                  "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # A real suite, not a token one — and it must actually import the module under test.
    test_files = [p for p in ws.rglob("test_*.py") if ".git" not in p.parts] + \
                 [p for p in ws.rglob("*_test.py") if ".git" not in p.parts]
    touches = any("ledger" in p.read_text(errors="replace") for p in test_files)
    real = green and n_pass >= 5 and touches
    r["parts"]["real_suite"] = {
        "ok": real,
        "detail": f"{len(test_files)} test file(s), {n_pass} tests, imports ledger: {touches}"}

    # MUTATION: each seeded bug must turn the suite red.
    caught, results = [], []
    if green:
        src = (ws / MODULE)
        original = src.read_text() if src.exists() else ""
        for cls, desc, find, repl in MUTANTS:
            if not original or find not in original:
                results.append((cls, desc, "unapplied"))
                continue
            with tempfile.TemporaryDirectory() as tmp:
                clone = Path(tmp) / "ws"
                shutil.copytree(ws, clone, ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", ".pytest_cache"))
                (clone / MODULE).write_text(original.replace(find, repl, 1))
                m_code, m_out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], clone)
                _, mf = pytest_counts(m_out)
                hit = m_code != 0 or mf > 0
                results.append((cls, desc, "caught" if hit else "MISSED"))
                if hit:
                    caught.append(cls)
    applied = [x for x in results if x[2] != "unapplied"]
    score_frac = (len(caught) / len(applied)) if applied else 0.0
    r["parts"]["mutation_score"] = {
        "ok": bool(applied) and score_frac >= PASS_BAR,
        "detail": f"{len(caught)}/{len(applied)} seeded bugs caught ({score_frac:.0%}); "
                  + ", ".join(f"{d}: {s}" for _c, d, s in results if s == "MISSED")[:160]}

    classes = {m[0] for m in MUTANTS}
    covered = set(caught)
    r["parts"]["every_bug_class"] = {
        "ok": covered >= classes,
        "detail": f"caught classes {sorted(covered) or '[]'} of {sorted(classes)}"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
