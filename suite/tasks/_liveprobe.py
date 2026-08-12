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
    "Name the interpreter or runner exactly as this project invokes it. If no live-test command "
    "exists, reply "
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


# The NAME is the signal; the extension picks the RUNNER. Collecting only *.py and *.sh made the
# docstring's own claim false — it said these were "the two wrapper shapes any language's workspace
# can carry", while `live_test.rb` and `live_test.js` were invisible and scored zero. One map, every
# language the battery runs.
_LIVE_RUNNERS = {".py": None, ".sh": ["bash"], ".rb": ["ruby"], ".js": ["node"], ".mjs": ["node"],
                 ".php": ["php"], ".go": ["go", "run"], ".rs": ["cargo", "run", "--quiet", "--bin"]}


def live_file_check(ws: Path):
    """(ok, detail) from dedicated live-named files, run by whatever their extension implies, with
    the handle-argument retry. (False, reason) when none exists or none proves live."""
    files = sorted(p for ext in _LIVE_RUNNERS for p in ws.rglob(f"*{ext}")
                   if "live" in p.name.lower() and "__pycache__" not in p.parts
                   and "node_modules" not in p.parts and "target" not in p.parts)
    if not files:
        return False, "no live-test file found"
    detail = "no live-test file proved live"
    for lf in files:
        runner = _LIVE_RUNNERS.get(lf.suffix) or [sys.executable]
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


# Placeholder values cria's own spec outline carries — evidence must never match the EXAMPLES.
_PLACEHOLDER_RE = re.compile(r"addr1e0{6,}|stake1[a-z]?x{4,}|stake1d4fg5dghr")
_FETCH_HEADER_RE = re.compile(r"\AHTTP \d{3}|Content-Type:", re.M)


_TEST_SUITE_RUN = re.compile(
    r"(?:\./)?\b(?:pytest|unittest|rake\s+test|bundle\s+exec\s+(?:rspec|rake)|rspec|minitest"
    r"|go\s+test|cargo\s+test|mvn\s+(?:test|verify)|gradlew?\s+test"
    r"|npm\s+(?:test|run\s+test)|yarn\s+test|pnpm\s+test|node\s+--test|jest|vitest|mocha"
    r"|phpunit|dotnet\s+test|mix\s+test)\b", re.I)


def session_live_evidence(capture_dir, names=("goose", "papagoose")):
    """Operator ruling 2026-08-05: the live-test deliverable ALSO counts when the session holds
    evidence that the coder RAN a test of a live handle and got successful results — "the spirit
    is there and the interpretation is fair." The rule follows the ruling's words exactly, and
    the first draft's false positives (a reasoner's file-read echoing hardcoded values; a 23K
    curl dump of the whole /handles list that merely CONTAINS 'goose') define the fences:
      - the RESULT must pair with the EXEC call that produced it (call_id / positional pairing),
        never a read_file/web_fetch — file contents and research fetches are not runs;
      - the producing COMMAND must itself name a task handle (it was run ON the handle) or be a
        pytest invocation, and must not be a bare curl/wget/httpie fetch of the API — executing
        the coder's own code is the ruling's subject;
      - the OUTPUT must carry a real addr1… AND a real stake1… (cria's outline placeholders
        excluded).
    Returns (ok, detail-naming-the-call)."""
    import json as _json
    from pathlib import Path as _P
    d = _P(capture_dir)
    if not d.is_dir():
        return False, "no capture dir"
    name_re = re.compile("|".join(re.escape(n) for n in names), re.I)
    # ALLOWLIST of program runners — the ruling's subject is the coder's OWN code running.
    # A blocklist kept leaking: `curl` was research, then `cd ws && grep goose goose.json`
    # re-emitted a saved file's contents. Only an invocation of a program counts, after
    # stripping any `cd <dir> &&` prefix; grep/cat/curl/wget never appear on this list.
    runner_re = re.compile(
        r"^\s*(?:python3?(?:\s+-m)?|pytest|node|ruby|php|java|go\s+run|cargo\s+run|bash|sh|\./)")
    # "is this the coder running its own test suite?" — the sibling allowlist one block up is already
    # shape-generalised across seven runtimes, and this test was `"pytest" not in cmd`, which is one
    # tool's name standing in for the question. A Go, Rust, Ruby, Java or Node suite run by the coder
    # could never earn the operator's 2026-08-05 in-session credit.
    exec_names = {"exec_command", "shell", "bash", "run", "execute_command"}
    for f in sorted(d.glob("[0-9]*.json")):
        if f.name.endswith(".response.json"):
            continue
        try:
            body = _json.loads(f.read_text(errors="replace")).get("body", {})
        except (ValueError, OSError):
            continue
        msgs = body.get("messages", [])
        calls = {}          # call_id -> (tool name, arguments str)
        last_call = None
        for m in msgs:
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {})
                calls[tc.get("id") or ""] = (fn.get("name", ""), fn.get("arguments", ""))
                last_call = (fn.get("name", ""), fn.get("arguments", ""))
            if m.get("role") not in ("tool", "function_call_output") and m.get("type") != "function_call_output":
                continue
            producer = calls.get(m.get("tool_call_id") or "") or last_call
            if not producer or producer[0] not in exec_names:
                continue
            cmd = producer[1]
            if not name_re.search(cmd) and not _TEST_SUITE_RUN.search(cmd):
                continue          # the run was not ON a task handle and was not the test suite
            shell_text = cmd.split('"cmd"')[-1].lstrip(':{ "[')
            shell_text = re.sub(r"^(?:cd\s+\S+\s*&&\s*)+", "", shell_text)
            if not runner_re.match(shell_text):
                continue          # not a program invocation (curl/grep/cat are not runs of their code)
            c = m.get("content")
            if c is None:
                c = m.get("output") or ""
            if isinstance(c, list):
                c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
            if not isinstance(c, str) or len(c) > 20000:
                continue
            if not name_re.search(c):
                continue
            addrs = [a for a in ADDR_RE.findall(c) if not _PLACEHOLDER_RE.search(a)]
            holders = [h for h in HOLDER_RE.findall(c) if not _PLACEHOLDER_RE.search(h)]
            if addrs and holders:
                return True, (f"in-session live resolution evidence (call {f.name.split('.')[0]}): "
                              f"executed `{'pytest' if 'pytest' in cmd else 'handle-named command'}` "
                              f"output shows {addrs[0][:24]}… + holder — counted per operator "
                              f"ruling 2026-08-05")
    return False, "no in-session live execution evidence"
