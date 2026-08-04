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


# ---- README-guided live probe (operator directive 2026-08-04) --------------------------------
# When every deterministic live-test branch fails, ONE inference call may propose the command the
# README documents for the live test. The model only PROPOSES; ground truth judges: the command
# must run inside the workspace, print real resolution markers WITH the network, and lose them
# (or fail) with the network dead — the provably-live rule unchanged. Evidence = the README, plus
# two READ-ONLY tools (list_dir / read_file, workspace-bounded). Any failure — no server, no
# README, unparseable reply, refused paths — falls back to the deterministic verdict already in
# hand; the probe can only ever ADD a point that real execution then proves.
LLM_URL = "http://127.0.0.1:18084/v1/chat/completions"
LLM_PROBE_PROMPT = (
    "You are helping a test SCORER find the LIVE-test command for a small Python project. The "
    "README is your evidence; you may inspect files first. Reply with EXACTLY ONE JSON object "
    "and nothing else, in one of these forms:\n"
    '  {"read_file": "<relative path>"}   — see a file\'s contents\n'
    '  {"list_dir": "<relative path>"}    — list a directory\n'
    '  {"command": "<shell command>"}     — your FINAL answer: the one command the README '
    "documents (or the project layout implies) that runs the LIVE test against the real API. "
    "Use python3, never bare python. If no live-test command exists, reply "
    '{"command": ""}.'
)


def _llm(messages):
    import urllib.request
    body = json.dumps({"model": "scorer", "messages": messages,
                       "temperature": 0, "max_tokens": 700}).encode()
    req = urllib.request.Request(LLM_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        d = json.loads(resp.read())
    text = d["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _json_obj(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


# A weak model often leaks its harness's tool-call syntax instead of JSON
# (`<|tool_call>call:Bash{command:<|"|>python tests/generate_live.py<|"|>,…}`). The payload is
# recoverable deterministically — same lesson as cria's massage.leaked_* family.
_LEAK_CMD = re.compile(r'(?:command|cmd)\s*:\s*<\|"\|>(.*?)<\|"\|>', re.S)
_LEAK_PATH = re.compile(r'(?:path|file_path)\s*:\s*<\|"\|>(.*?)<\|"\|>', re.S)


def _reply_action(text):
    """The probe reply as an action dict — JSON first, leaked tool-call syntax second."""
    obj = _json_obj(text)
    if isinstance(obj, dict) and ({"command", "read_file", "list_dir"} & set(obj)):
        return obj
    m = _LEAK_CMD.search(text)
    if m:
        return {"command": m.group(1).strip()}
    m = _LEAK_PATH.search(text)
    if m and ("read" in text.lower() or "Read" in text):
        return {"read_file": m.group(1).strip()}
    return None


def _safe_rel(ws: Path, rel: str) -> Path | None:
    try:
        p = (ws / str(rel)).resolve()
        return p if str(p).startswith(str(ws.resolve()) + os.sep) or p == ws.resolve() else None
    except Exception:  # noqa: BLE001
        return None


def readme_live_probe(ws: Path):
    """(ok, detail) from the README-guided probe, or (False, reason). Judgment is EXECUTION."""
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    if rd is None:
        return False, "no README for the live probe to read"
    skip = ("__pycache__", "venv", ".venv", "node_modules", "site-packages", ".git")
    listing = "\n".join(sorted(str(p.relative_to(ws)) for p in ws.rglob("*.py")
                               if not any(x in p.parts for x in skip))[:60])
    messages = [
        {"role": "system", "content": LLM_PROBE_PROMPT},
        {"role": "user", "content": f"README:\n{rd.read_text(errors='replace')[:6000]}\n\n"
                                    f"PYTHON FILES IN THE WORKSPACE:\n{listing}"},
    ]
    cmd = None
    try:
        for _ in range(5):
            reply = _llm(messages)
            obj = _reply_action(reply) or {}
            if "command" in obj:
                cmd = str(obj.get("command") or "").strip()
                break
            if "read_file" in obj:
                p = _safe_rel(ws, obj["read_file"])
                result = p.read_text(errors="replace")[:8000] if p and p.is_file() else "NOT FOUND"
            elif "list_dir" in obj:
                p = _safe_rel(ws, obj["list_dir"])
                result = "\n".join(sorted(x.name for x in p.iterdir())) if p and p.is_dir() else "NOT FOUND"
            else:
                return False, "live probe: unparseable reply"
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": result}]
    except Exception as e:  # noqa: BLE001 — no server / timeout → deterministic verdict stands
        return False, f"live probe unavailable: {e}"
    if not cmd:
        return False, "live probe: README documents no live-test command"
    if re.search(r"[;&|]|\brm\b|\bmv\b|>\s", cmd):
        return False, f"live probe: refused compound/mutating command ({cmd[:60]})"
    # This box has no bare `python`; READMEs say it anyway. Same substitution a human would make.
    cmd = re.sub(r"(?<![\w/-])python(?=\s)", "python3", cmd)
    argv = ["bash", "-c", cmd]
    code, out = run(argv, ws, timeout=180)
    if code != 0:
        return False, f"live probe: `{cmd}` exit={code}, real-data markers absent"
    markers = bool(ADDR_RE.search(out) and HOLDER_RE.search(out))
    # Provably-live rule, either proof: real markers that vanish when the network dies, or a
    # clean exit that turns into a failure when the network dies (a unittest suite prints dots,
    # not addresses — exit-code proof is the same standard the in-file pytest branch uses).
    dead = {**os.environ, "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}
    try:
        blocked = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=180, env=dead)
        b_out = (blocked.stdout or "") + (blocked.stderr or "")
        b_rc, b_markers = blocked.returncode, bool(ADDR_RE.search(b_out) and HOLDER_RE.search(b_out))
    except subprocess.TimeoutExpired:
        b_rc, b_markers = -1, False  # hanging without a network is failing without a network
    if markers:
        if b_rc == 0 and b_markers:
            return False, f"live probe: `{cmd}` passes with the network BLOCKED — mocked, not live"
        return True, f"README-documented live command `{cmd}`: provably live (markers with network only)"
    if b_rc != 0:
        return True, f"README-documented live command `{cmd}`: provably live (passes with network, fails without)"
    return False, f"live probe: `{cmd}` exit=0 but no markers and no network dependence proof"


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


def main(ws: Path) -> dict:
    r = {"task": "ada-handles", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}

    # 1) Unit tests: pytest discovers and passes ≥1 real test.
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=no"], ws)
    m = re.search(r"(\d+) passed", out)
    unit_ok = code == 0 and bool(m) and int(m.group(1)) > 0
    r["parts"]["unit_tests"] = {"ok": unit_ok, "passed": int(m.group(1)) if m else 0,
                                "detail": out.strip().splitlines()[-1] if out.strip() else "no output"}

    # 2) Live test: find it, RUN it, and demand evidence of a real resolution (addr1 + stake1
    #    in output). Shape-agnostic: any file whose name mentions "live".
    # RECURSIVE — the first version only looked at the workspace root, and a src-layout run
    # (gemma's habit) had its real tests/live.py scored "no live-test file found" (false FAIL).
    # *.sh included (walked on ada-handles_qwythos_codex_poff_1785884041: a real, working
    # live_test.sh — resolved both handles live in-session — scored zero because this glob only
    # knew Python; a shell runner is a legitimate reading of "create a live test").
    live_files = sorted(p for ext in ("*.py", "*.sh") for p in ws.rglob(ext)
                        if "live" in p.name.lower() and "__pycache__" not in p.parts)
    live_ok, live_detail = False, "no live-test file found"
    for lf in live_files:
        runner = ["bash"] if lf.suffix == ".sh" else [sys.executable]
        # Bare first; a usage-error retry gets the task's own handle as an argument (operator
        # ruling 2026-08-04: nemotron lost this point twice for a live test that WORKS but wants
        # the handle on the command line — the CLI check already honours exactly that shape).
        for argv in (runner + [str(lf.relative_to(ws))],
                     runner + [str(lf.relative_to(ws)), "goose"]):
            code, out = run(argv, ws)
            if code == 0 and ADDR_RE.search(out) and HOLDER_RE.search(out):
                shown = " goose" if argv[-1] == "goose" else ""
                live_ok, live_detail = True, f"{lf.name}{shown}: real resolution (addr1+stake1 present)"
                break
            live_detail = f"{lf.name}: exit={code}, real-data markers {'partial' if ADDR_RE.search(out) or HOLDER_RE.search(out) else 'absent'}"
        if live_ok:
            break
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
        # Last resort: ask what the README says to run (see readme_live_probe — the model only
        # proposes; execution with the provably-live rule decides).
        probe_ok, probe_detail = readme_live_probe(ws)
        if probe_ok:
            live_ok, live_detail = True, probe_detail
        else:
            live_detail = f"{live_detail}; {probe_detail}"
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
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=1))
