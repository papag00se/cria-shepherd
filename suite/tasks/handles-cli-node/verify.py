#!/usr/bin/env python3
"""Verifier for handles-cli-node — categories 18 (external service), 16 (CLI tooling),
7 (dependency migration), 15 (containerise).

The seed is a working script on the deprecated `request` package that prints only the address.
Four points:

  1. a real CLI: takes the handle as an argument, --json emits parseable JSON, --help explains
     itself, an unresolvable handle exits NON-ZERO (the seed exits 0 on every failure), AND it
     reports the holder address and the holder's total handles, which the seed never did
  2. `request` is GONE — not merely unused: absent from package.json, absent from the source, and
     the tool still runs with no node_modules at all
  3. tests exist and at least one really hits the API — PASSES with the network, FAILS without it
     (`unshare -rn`), so a mocked "live" test scores nothing

Real Cardano artifacts in the output are the evidence the resolution actually happened.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT = 300
ADDR_RE = re.compile(r"addr1[0-9a-z]{20,}")
HOLDER_RE = re.compile(r"stake1[0-9a-z]{20,}")


def run(cmd, cwd, timeout=TIMEOUT, blocked=False):
    argv = (["unshare", "-rn"] + list(cmd)) if blocked else list(cmd)
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -3, f"VERIFIER: {argv[0]} not installed"
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def entrypoints(ws):
    """However the model spelled it: the documented command, then the usual candidates."""
    cmds = []
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    if rd:
        for m in re.finditer(r"(?m)^\s*(?:\$\s*)?((?:node|npm)\s+[^\n`]+)$", rd.read_text(errors="replace")):
            line = m.group(1).strip()
            if "install" in line or "test" in line:
                continue
            cmds.append(line.split())
    for name in ("cli.js", "index.js", "lookup.js", "main.js", "bin/cli.js"):
        if (ws / name).exists():
            cmds.append(["node", name])
    return cmds


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "handles-cli-node", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    base = entrypoints(ws)
    # --- 1: CLI behaviour
    cli_ok, cli_detail = False, "no runnable entry point"
    for cmd in base:
        code, out = run([*[a for a in cmd if a != "goose"], "goose"], ws)
        if code != 0 or not ADDR_RE.search(out):
            cli_detail = f"{' '.join(cmd)} goose: exit={code}"
            continue
        jcode, jout = run([*cmd, "goose", "--json"], ws)
        # PARSE THE WHOLE OUTPUT FIRST. This only ever tried each LINE on its own, so a tool that
        # pretty-printed its JSON across several lines scored zero — `{` is not valid JSON and
        # neither is `"handle_name": "goose",`. Nothing in the task asks for one line, and
        # `json.dumps(x, indent=2)` is the obvious way to write it. gemma4 emitted correct,
        # indented JSON and lost the check for formatting it the normal way.
        # The per-line pass is kept underneath for a tool that emits one object per line (JSONL),
        # which is also a legitimate reading of "--json".
        parsed = False
        try:
            json.loads(jout)
            parsed = True
        except ValueError:
            for line in jout.splitlines():
                try:
                    json.loads(line)
                    parsed = True
                except ValueError:
                    continue
        hcode, hout = run([*cmd, "--help"], ws)
        helped = hcode == 0 and len(hout.strip()) > 20
        bcode, _ = run([*cmd, "definitely-not-a-real-handle-zzz"], ws)
        fails_loudly = bcode != 0
        cli_ok = parsed and helped and fails_loudly
        cli_detail = (f"{' '.join(cmd)}: --json parses: {parsed}, --help: {helped}, "
                      f"bad handle exits non-zero: {fails_loudly}")
        if cli_ok:
            break
    cli_flags_ok, cli_flags_detail = cli_ok, cli_detail

    # --- 2: holder + total handles
    facts_ok, facts_detail = False, "no output with holder + count"
    for cmd in base:
        code, out = run([*cmd, "goose"], ws)
        if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out) and re.search(r"\d+", out):
            facts_ok, facts_detail = True, f"{' '.join(cmd)} goose -> address+holder+count"
            break
        if code == 0 and ADDR_RE.search(out):
            facts_detail = f"{' '.join(cmd)}: address only, holder/count missing"
    # ONE point with the flags: "a shippable CLI" means it takes the argument, honours the flags,
    # exits correctly AND reports the three facts asked for. Scoring them apart pays half a mark
    # for a tool that runs beautifully and answers the wrong question.
    r["parts"]["cli_behaviour"] = {
        "ok": cli_flags_ok and facts_ok,
        "detail": f"{cli_flags_detail} | {facts_detail}"}

    # --- 3: `request` really gone
    pkg = ws / "package.json"
    dep_listed = "request" in json.loads(pkg.read_text()).get("dependencies", {}) if pkg.exists() else False
    src_uses = any("require('request')" in p.read_text(errors="replace")
                   or 'require("request")' in p.read_text(errors="replace")
                   for p in ws.rglob("*.js") if "node_modules" not in p.parts)
    nm = ws / "node_modules"
    stash = ws / "_node_modules_hidden"
    ran_clean = False
    try:
        if nm.exists():
            nm.rename(stash)
        for cmd in base:
            code, out = run([*cmd, "goose"], ws)
            if code == 0 and ADDR_RE.search(out):
                ran_clean = True
                break
    finally:
        if stash.exists():
            stash.rename(nm)
    r["parts"]["request_removed"] = {
        "ok": (not dep_listed) and (not src_uses) and ran_clean,
        "detail": f"listed in package.json: {dep_listed}, required in source: {src_uses}, "
                  f"runs with no node_modules: {ran_clean}"}

    # --- 4: tests, one of which is provably live
    test_cmds = [["npm", "test", "--silent"], ["node", "--test"]]
    live_ok, live_detail = False, "no passing test run"
    for cmd in test_cmds:
        code, out = run(cmd, ws)
        if code == -3 or code != 0:
            continue
        b_code, _ = run(cmd, ws, blocked=True)
        if b_code != 0:
            live_ok, live_detail = True, f"{' '.join(cmd)}: passes with network, fails without"
            break
        live_detail = f"{' '.join(cmd)}: passes with the network BLOCKED — mocked, not live"
    r["parts"]["tests_incl_live"] = {"ok": live_ok, "detail": live_detail}

    # --- Dockerfile rides with the CLI point: a container that cannot be built is not a delivery.
    dockerfile = next((p for p in ws.rglob("Dockerfile") if ".git" not in p.parts), None)
    dtext = dockerfile.read_text(errors="replace").lower() if dockerfile else ""
    docker_sane = bool(dockerfile) and "from" in dtext and ("node" in dtext) and \
        any(k in dtext for k in ("cmd", "entrypoint"))
    r["parts"]["dockerfile"] = {
        "ok": docker_sane,
        "detail": (f"{dockerfile.name}: FROM node + CMD/ENTRYPOINT" if docker_sane
                   else ("no Dockerfile" if not dockerfile else "Dockerfile missing FROM node or CMD"))}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
