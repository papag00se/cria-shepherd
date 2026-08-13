#!/usr/bin/env python3
"""Verifier for shipping-rates-rb — the Ruby member of the battery, and the same FOUR-skill shape
as its Python sibling: debug an existing failure, implement a new zone from a spec in prose, cover
it with tests, and update documentation that already exists.

The seed ships working code, a green-but-for-one suite, and ONE real bug: an order EXACTLY at the
free-shipping threshold is charged, because the check is `>` where the contract is `>=`.

Four points, and the cheats are all worthless:

  1. the whole suite passes AND every seeded test method is still present with its body intact —
     deleting or loosening the failing assertion is the obvious way to go green, and the prompt
     forbids it. Adding tests is free, because the prompt asks for tests.
  2. HIDDEN tests pass: the same contract at inputs the model never saw, plus the new zone, so
     special-casing the visible numbers scores nothing
  3. the express zone is implemented AND the model wrote its own tests for it (a zone that only
     the hidden tests exercise is untested work)
  4. the README carries a rate table naming every zone with its numbers

The suite is run by loading the test files directly rather than through `rake`, so the task does
not silently grade the model on keeping a Rakefile it was never asked to keep.

Hidden tests are copied in at scoring time and removed after, so nothing in the workspace hints at
them during the run.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 180
SEED_TESTS = HERE / "seed" / "test"

# Load every test file in one process; minitest/autorun runs them all at exit.
RUN_SUITE = (
    'files = Dir["test/**/test_*.rb"] + Dir["spec/**/*_spec.rb"] + Dir["test_*.rb"];'
    'files.uniq.each { |f| require File.expand_path(f) }'
)
SUMMARY = re.compile(r"(\d+) runs?, \d+ assertions?, (\d+) failures?, (\d+) errors?")


def _is_test_file(p) -> bool:
    """Any ruby file this task's own suite runner would load — see RUN_SUITE. Name conventions only;
    a file is a test file if minitest or rspec would pick it up, whichever layout the model chose."""
    name, parts = p.name, p.parts
    return (name.startswith("test_") or name.endswith("_test.rb")
            or name.endswith("_spec.rb") or "spec" in parts or "test" in parts)


# `def test_x` … `end` at the SAME indent. Ruby has no stdlib AST, and this is the shape minitest
# mandates, so a regex anchored on indentation is exact for any conventionally formatted file.
TEST_DEF = re.compile(r"^([ \t]*)def\s+(test_\w+)", re.M)


def run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier reports, it does not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def _test_methods(src: str) -> dict[str, str]:
    """{name: normalized body} for each `def test_*`. Blank lines and trailing whitespace are
    ignored so a reformat is not read as a contract change; anything that alters an assertion
    changes the text and is caught."""
    out: dict[str, str] = {}
    lines = src.splitlines()
    for m in TEST_DEF.finditer(src):
        indent, name = m.group(1), m.group(2)
        start = src[: m.start()].count("\n")
        body = [lines[start]]
        for line in lines[start + 1:]:
            body.append(line)
            if line.rstrip() == f"{indent}end":
                break
        out[name] = "\n".join(l.rstrip() for l in body if l.strip())
    return out


def _seeded_tests_unchanged(ws: Path) -> tuple[bool, str]:
    """Every seeded test still present, with its body intact. ADDING tests is fine — the prompt
    asks for them, and the obvious place to put them is the file that already has tests.

    The anti-cheat this protects is the whole reason the check exists: a green suite bought by
    deleting or weakening the failing assertion is not a pass. A removed test is missing, and an
    edited one has different source."""
    seed_methods: dict[str, tuple[str, str]] = {}
    for seed_file in sorted(SEED_TESTS.glob("*.rb")):
        for name, body in _test_methods(seed_file.read_text(errors="replace")).items():
            seed_methods[name] = (seed_file.name, body)
    if not seed_methods:
        return True, "no seeded tests to protect"
    live: dict[str, str] = {}
    for p in ws.rglob("*.rb"):
        if ".git" in p.parts or "vendor" in p.parts:
            continue
        live.update(_test_methods(p.read_text(errors="replace")))
    for name, (fname, body) in sorted(seed_methods.items()):
        if name not in live:
            return False, f"seeded test {name} from {fname} was deleted"
        if live[name] != body:
            return False, f"seeded test {name} was modified — the contract was changed, not the code"
        added = len(live) - len(seed_methods)
    return True, f"all {len(seed_methods)} seeded tests intact" + (f", {added} added" if added > 0 else "")


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "shipping-rates-rb", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) the suite passes, and the seeded tests were not edited. ONE point deliberately: a green
    # suite bought by deleting the failing assertion is not a pass, so scoring them separately
    # would hand half a mark to the cheat the prompt explicitly forbids.
    code, out = run(["ruby", "-Ilib", "-Itest", "-e", RUN_SUITE], ws)
    m = SUMMARY.search(out)
    runs, fails, errs = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 1, 1)
    suite_ok = code == 0 and runs >= 7 and fails == 0 and errs == 0
    intact, detail = _seeded_tests_unchanged(ws)
    r["parts"]["suite_green_tests_intact"] = {
        "ok": suite_ok and intact, "passed": runs,
        "detail": (m.group(0) if m else out.strip()[-120:]) + ("" if intact else f"  [{detail}]")}

    # 2) hidden tests: the same contract at inputs the model never saw, plus the new zone
    hidden_dst = ws / "test_hidden_rates.rb"
    hidden_ok, hidden_detail = False, "hidden tests not run"
    try:
        shutil.copy(HERE / "hidden" / "test_hidden_rates.rb", hidden_dst)
        code, out = run(["ruby", "-Ilib", "-I.", hidden_dst.name], ws)
        hm = SUMMARY.search(out)
        hidden_ok = code == 0 and bool(hm) and int(hm.group(2)) == 0 and int(hm.group(3)) == 0
        hidden_detail = hm.group(0) if hm else out.strip()[-120:]
    finally:
        hidden_dst.unlink(missing_ok=True)
    r["parts"]["hidden_contract"] = {"ok": hidden_ok, "detail": hidden_detail}

    # 3) the express zone exists, prices correctly, AND the model tested it itself
    probe = ('require "shipping/rates";'
             'print Shipping.shipping_cost("express", 0.0, 10.0), " ",'
             '      Shipping.shipping_cost("express", 4.0, 10.0)')
    code, out = run(["ruby", "-Ilib", "-e", probe], ws)
    priced = code == 0 and out.strip().splitlines()[-1].strip().startswith("14.99 24.99")
    # THE TASK ASKS FOR TESTS, NOT FOR A FILENAME. This looked only at files named `test_*`, while
    # RUN_SUITE eight lines up loads `test/**/test_*.rb`, `spec/**/*_spec.rb` AND `test_*.rb` — so a
    # model writing `spec/rates_spec.rb` had its tests RUN and got no credit for writing them.
    # `rates_test.rb` is a common ruby convention too and was equally invisible. Any file this
    # task's own runner would execute counts (operator ruling: a check may only fail a run over the
    # property the task actually asks for).
    own_tests = any("express" in p.read_text(errors="replace").lower()
                    for p in ws.rglob("*.rb")
                    if ".git" not in p.parts and _is_test_file(p))
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

    # 5) country code -> zone, backed by a maintained source rather than a hand-typed EU list.
    # The cases are chosen so a hand-rolled list fails: Croatia joined the EU in 2013 and is
    # routinely missing from one; Switzerland and Norway are in Europe and NOT in the EU, which is
    # the mistake the other direction. The library is checked structurally and WITHOUT naming a
    # gem — pinning one would be the task-specific overfit the doctrine forbids — so what is
    # verified is that some third-party gem is required by the source AND the tricky cases are
    # right. A gem required and ignored cannot buy the point, because the answers still have to be.
    probe = ('require "shipping/rates";'
             'print [%w[GB DE HR CH US NO].map { |c| Shipping.zone_for(c) }.join(","),'
             '       Shipping.shipping_cost("DE", 4.0, 50.00)].join("|")')
    code, out = run(["ruby", "-Ilib", "-e", probe], ws)
    last = out.strip().splitlines()[-1].strip() if out.strip() else ""
    zones_ok = last.startswith("domestic,eu,eu,international,international,international")
    by_code_ok = "|15.99" in last
    # A require is THIRD-PARTY only if its top-level segment is not stdlib AND it does not resolve
    # to a file in this workspace. Matching the full string missed `minitest/autorun` — stdlib
    # reached through a sub-path — which would have let a hand-rolled EU list satisfy the library
    # half of this check on the strength of the test framework it was already using.
    stdlib = {"json", "set", "date", "time", "csv", "bigdecimal", "minitest", "rake", "English",
              "fileutils", "optparse", "logger", "yaml", "uri", "net", "digest", "securerandom",
              "pp", "stringio", "tempfile", "benchmark", "ostruct", "forwardable", "singleton"}
    own = {q.relative_to(d).with_suffix("").as_posix()
           for d in (ws / "lib", ws / "test", ws) if d.is_dir()
           for q in d.rglob("*.rb")}
    gems = set()
    for p_ in ws.rglob("*.rb"):
        if ".git" in p_.parts or "vendor" in p_.parts:
            continue
        for m in re.finditer(r'^\s*require\s+["\']([\w/.-]+)["\']', p_.read_text(errors="replace"), re.M):
            name = m.group(1)
            if name.startswith(".") or name in own or name.split("/")[0] in stdlib:
                continue
            gems.add(name)
    r["parts"]["country_zone_mapping"] = {
        "ok": zones_ok and by_code_ok and bool(gems),
        "detail": (f"zones {last or out.strip()[-60:]}; "
                   f"third-party requires: {sorted(gems) or 'none'}")}
    # The detail is NOT clipped. It was cut at 70 characters, which lands mid-number on the
    # cost that follows the zone list — "…|15.99" displayed as "…|15" and read as a wrong
    # answer when the answer was right. A detail line exists to say why a check failed; a
    # clipped one says something else.

    # max_score follows the checks — the battery scores by percentage, so a task carries as many
    # checks as its work needs and a constant here would silently misreport every run.
    r["max_score"] = float(len(r["parts"]))
    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
