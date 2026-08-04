#!/usr/bin/env python3
"""Shared live-test fairness helpers for the handles verifiers (operator direction, 2026-08-04).

Grown one walked injustice at a time in the Python task's verifier, now shared with the
language battery (`_handles_verify.py`):

  * a dedicated live-test FILE counts whatever its extension — `*.py` (python3) or `*.sh`
    (bash), the two wrapper shapes any language's workspace can carry
    (walked: qwythos 1785884041's working live_test.sh scored zero for its extension);
  * a usage-failing live file is retried with the task's own handle as an argument
    (walked: nemotron lost the point twice to argument shape alone);
  * when every deterministic branch fails, ONE inference call may propose the command the
    README documents for the live test — the model only PROPOSES; execution judges.

The provably-live rule is unchanged everywhere: real markers (or a clean exit) WITH the
network, failure (or vanished markers) WITHOUT it. A mock passes both ways and scores nothing.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ADDR_RE = re.compile(r"addr1[0-9a-z]{20,}")
HOLDER_RE = re.compile(r"stake1[0-9a-z]{20,}")

DEAD_NET = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}

LLM_URL = "http://127.0.0.1:18084/v1/chat/completions"
PROBE_PROMPT = (
    "You are helping a test SCORER find the LIVE-test command for a small project. The "
    "README is your evidence; you may inspect files first. Reply with EXACTLY ONE JSON object "
    "and nothing else, in one of these forms:\n"
    '  {"read_file": "<relative path>"}   — see a file\'s contents\n'
    '  {"list_dir": "<relative path>"}    — list a directory\n'
    '  {"command": "<shell command>"}     — your FINAL answer: the one command the README '
    "documents (or the project layout implies) that runs the LIVE test against the real API. "
    "Use python3, never bare python. If no live-test command exists, reply "
    '{"command": ""}.'
)


def _run(argv, ws, timeout=180, blocked=False):
    env = {**os.environ, **DEAD_NET} if blocked else None
    try:
        p = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — a verifier reports, it does not crash
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


def _provably_live(argv, ws):
    """(ok, detail_suffix) — the shared judgment: run with the network, run without, compare."""
    code, out = _run(argv, ws)
    if code != 0:
        return False, f"exit={code}, real-data markers absent"
    markers = bool(ADDR_RE.search(out) and HOLDER_RE.search(out))
    b_code, b_out = _run(argv, ws, blocked=True)
    b_markers = bool(ADDR_RE.search(b_out) and HOLDER_RE.search(b_out))
    if markers:
        if b_code == 0 and b_markers:
            return False, "passes with the network BLOCKED — mocked, not live"
        return True, "real resolution (addr1+stake1 present)"
    if b_code != 0:
        return True, "provably live (passes with network, fails without)"
    return False, "exit=0 but no markers and no network dependence proof"


def live_file_check(ws: Path):
    """(ok, detail) from dedicated live-named files (*.py via python3, *.sh via bash), with the
    handle-argument retry. (False, reason) when none exists or none proves live."""
    files = sorted(p for ext in ("*.py", "*.sh") for p in ws.rglob(ext)
                   if "live" in p.name.lower() and "__pycache__" not in p.parts)
    if not files:
        return False, "no live-test file found"
    detail = "no live-test file proved live"
    for lf in files:
        runner = ["bash"] if lf.suffix == ".sh" else [sys.executable]
        for argv in (runner + [str(lf.relative_to(ws))],
                     runner + [str(lf.relative_to(ws)), "goose"]):
            ok, suffix = _provably_live(argv, ws)
            shown = f"{lf.name}{' goose' if argv[-1] == 'goose' else ''}"
            if ok:
                return True, f"{shown}: {suffix}"
            detail = f"{shown}: {suffix}"
    return False, detail


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


# A weak model often leaks its harness's tool-call syntax instead of JSON — the payload is
# recoverable deterministically (same lesson as cria's massage.leaked_* family).
_LEAK_CMD = re.compile(r'(?:command|cmd)\s*:\s*<\|"\|>(.*?)<\|"\|>', re.S)
_LEAK_PATH = re.compile(r'(?:path|file_path)\s*:\s*<\|"\|>(.*?)<\|"\|>', re.S)


def _reply_action(text):
    obj = _json_obj(text)
    if isinstance(obj, dict) and ({"command", "read_file", "list_dir"} & set(obj)):
        return obj
    m = _LEAK_CMD.search(text)
    if m:
        return {"command": m.group(1).strip()}
    m = _LEAK_PATH.search(text)
    if m and "read" in text.lower():
        return {"read_file": m.group(1).strip()}
    return None


def _safe_rel(ws: Path, rel: str):
    try:
        p = (ws / str(rel)).resolve()
        return p if str(p).startswith(str(ws.resolve()) + os.sep) or p == ws.resolve() else None
    except Exception:  # noqa: BLE001
        return None


def readme_live_probe(ws: Path):
    """(ok, detail) from the README-guided probe, or (False, reason). The model only PROPOSES a
    command; execution with the provably-live rule decides. Any failure — no server, no README,
    unparseable reply, refused paths — leaves the deterministic verdict standing."""
    rd = next((p for p in ws.iterdir() if p.is_file() and p.name.lower().startswith("readme")), None)
    if rd is None:
        return False, "no README for the live probe to read"
    skip = ("__pycache__", "venv", ".venv", "node_modules", "site-packages", ".git",
            "target", "vendor", "build", "dist")
    listing = "\n".join(sorted(str(p.relative_to(ws)) for ext in ("*.py", "*.sh", "*.go", "*.rs",
                                                                  "*.js", "*.rb", "*.php", "*.java")
                               for p in ws.rglob(ext)
                               if not any(x in p.parts for x in skip))[:60])
    messages = [
        {"role": "system", "content": PROBE_PROMPT},
        {"role": "user", "content": f"README:\n{rd.read_text(errors='replace')[:6000]}\n\n"
                                    f"SOURCE FILES IN THE WORKSPACE:\n{listing}"},
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
    except Exception as e:  # noqa: BLE001 — no model server → deterministic verdict stands
        return False, f"live probe unavailable: {e}"
    if not cmd:
        return False, "live probe: README documents no live-test command"
    if re.search(r"[;&|]|\brm\b|\bmv\b|>\s", cmd):
        return False, f"live probe: refused compound/mutating command ({cmd[:60]})"
    # This box has no bare `python`; READMEs say it anyway.
    cmd = re.sub(r"(?<![\w/-])python(?=\s)", "python3", cmd)
    ok, suffix = _provably_live(["bash", "-c", cmd], ws)
    if ok:
        return True, f"README-documented live command `{cmd}`: {suffix}"
    return False, f"live probe: `{cmd}` {suffix}"
