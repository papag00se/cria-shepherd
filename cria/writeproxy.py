"""Synthetic lean tools ↔ shell — the "cria owns no executors" pattern.

A small local model handles purpose-built tools (write_file, edit_file, read_file,
list_dir, web_fetch, web_search) far better than driving a raw shell for every op. But
the only harness-agnostic executor is `shell`. So when the harness offers `shell` but not
these tools, cria:

* **advertises** the synthetic tools to the MODEL (so it reaches for them),
* translates each call **outbound** to a shell command the harness runs — byte-exact
  (base64 for writes/edits; heredoc-fed so there is no arg-size limit and no chunking),
* stamps a **stateless sentinel** (`# ⟦ctx:tool⟧<b64>`) into the command carrying the
  ORIGINAL tool name + args, so the **inbound** pass re-presents the recorded shell call
  as the tool the model actually called — from the sentinel in the conversation itself,
  with NO in-process store (survives a restart mid-session; the old store did not).

Writes are one atomic command (temp file + `mv`); an empty success is reframed as a
confirmation. Reads/lists/fetches are re-presented too, so the model never sees the raw
shell it didn't call. `web_search` routes to the harness's own search tool when it has one
(presented as `web_search`), else to a Brave `curl` when a key is available.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from shlex import quote as _qbash  # one bash-quoting rule (was a hand-rolled _qbash)

from . import brave, prompts, webfetch
from .config import CRIA_HOME
from .shelltool import _CMD_FIELDS, SHELL_TOOL_NAMES, shell_args
from .toolargs import parse_args as _parse, tool_path as _tool_path

_WRITE_NAMES = {"write_file", "create_file"}
_EDIT_NAMES = {"edit_file", "str_replace"}
_READ_NAMES = {"read_file"}
_LIST_NAMES = {"list_dir"}

# cria's own private dir is off-limits to the driven model — no reading (it holds cria's .env
# credentials and config) and no writing (a stray file, or worse an overwrite of cria.toml /
# loopstate, corrupts cria). A confused small model has done both: it invented a `~/.cria/chat-<id>.txt`
# path and wrote a "message to the user" into it, having no other channel to speak. This is the dual of
# the no-workspace-pollution rule, enforced at the same chokepoint that lowers the synthetic tools.
_CRIA_HOME_REFUSAL = (
    "that path is inside a protected internal directory and is off-limits — config, credentials, and "
    "state live there. Use the project workspace for any file you read or write. If you meant to tell "
    "the user something, just say it in your reply — do not write a file."
)


def _targets_cria_home(path: str) -> bool:
    """True when a synthetic tool's path resolves INTO cria's own home (~/.cria). Only absolute / ~
    paths can — a relative path resolves against the harness workspace, never cria's home. Lexical
    (normpath, not resolve) so `..` can't escape the check and the path need not exist yet."""
    try:
        t = Path(path).expanduser()
        if not t.is_absolute():
            return False
        t = Path(os.path.normpath(str(t)))
        return t == CRIA_HOME or CRIA_HOME in t.parents
    except (ValueError, OSError):
        return False


def _guarded_path(name: str, args: dict) -> str | None:
    """The local filesystem path a synthetic tool would touch — for the cria-home guard. None for the
    non-path tools (web_fetch/web_search take a URL/query, not a local path)."""
    if name in _WRITE_NAMES or name in _EDIT_NAMES or name in _READ_NAMES:
        p = _tool_path(args)
    elif name in _LIST_NAMES:
        p = args.get("path") or args.get("dir") or args.get("directory")
    else:
        return None
    return str(p) if p else None
_FETCH_NAMES = {"web_fetch"}
_SEARCH_NAMES = {"web_search", "local_web_search"}

# The stateless re-presentation sentinel: a leading shell COMMENT line carrying the original
# tool call, base64-encoded, so inbound can rebuild it from the command in history (no store).
_SENTINEL = "⟦ctx:tool⟧"
_SENTINEL_LINE = re.compile(r"#\s*" + re.escape(_SENTINEL) + r"([A-Za-z0-9+/=]+)")
# Heredoc terminators — the payload rides on stdin, so there is NO arg-size limit (no chunking).
_HD_B64 = "__CRIA_B64_EOF__"
_HD_PY = "__CRIA_PY_EOF__"
# A per-write temp suffix keeps the write atomic (write temp, then mv over the target).
_TMP_SUFFIX = ".cria-tmp"
# A POSITIVE success token a write/edit prints ONLY on success. The empty-result reframe keys on
# this, not on blank output — otherwise a FAILED write/edit (silent success and stderr-only failure
# both look blank) would be reported to the model as "Wrote {path}" (false success).
_WROTE = "⟦ctx:wrote⟧"
# When an edit_file misses AND its anchor line is gone (a prior edit deleted it), the near-context
# fallback finds nothing and the model, handed a bare "read the file again", re-guesses the same stale
# old_string and fails identically. If the file is at most this many chars, inline its FULL current
# contents in the failure so the model has exact text to copy. Bounded so a large file never dumps.
EDIT_SHOW_FULL_MAX = 2000
_FETCH_TIMEOUT_S = 20


# --------------------------------------------------------------------- synthetic schemas


def _synthetic_tools() -> dict[str, dict]:
    """The synthetic tool SCHEMAS cria advertises and lowers. Model-facing DESCRIPTIONS live in
    prompts/tool_descs.txt (tunable without a restart, like every other model-facing string)."""
    d = prompts.load_map("tool_descs")

    def fn(name, description, props, required):
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    return {
        "write_file": fn("write_file", d["write_file"],
                         {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        "edit_file": fn("edit_file", d["edit_file"],
                        {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
                        ["path", "old_string", "new_string"]),
        "read_file": fn("read_file", d["read_file"],
                        {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
        "list_dir": fn("list_dir", d["list_dir"], {"path": {"type": "string"}}, []),
        "web_fetch": fn("web_fetch", d["web_fetch"],
                        {"url": {"type": "string"}, "find": {"type": "string"}, "cursor": {"type": "string"}}, ["url"]),
        "web_search": fn("web_search", d["web_search"], {"query": {"type": "string"}}, ["query"]),
    }


def needs_translation(tools) -> dict | None:
    """The harness's shell tool when it offers `shell` but NOT `write_file` (so cria should
    translate); ``None`` when the harness runs write_file itself (passthrough)."""
    shell = None
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        name = fn.get("name")
        if name in _WRITE_NAMES:
            return None
        if name in SHELL_TOOL_NAMES and shell is None:
            shell = {"name": name, "schema": fn.get("parameters") or {}}
    return shell


def _names_of(tools) -> set[str]:
    return {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools or []}


def native_search_name(tools) -> str | None:
    """The harness's own search tool to route `web_search` calls to, or None. A native `web_search`
    passes straight through; a Brave `local_web_search` is what we present AS `web_search`."""
    names = _names_of(tools)
    if "web_search" in names:
        return "web_search"
    if "local_web_search" in names:
        return "local_web_search"
    return None


def advertise(body: dict, rlog=None, brave_key: str | None = None) -> set[str]:
    """Add cria's synthetic tools to what the MODEL sees (only those the harness lacks), and present
    a Brave ``local_web_search`` to the model AS ``web_search``. Returns the set of names cria will
    LOWER on the way out (so a harness-native tool of the same name is left for the harness)."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        tools = []
        body["tools"] = tools
    present = _names_of(tools)
    injected: set[str] = set()
    synth = _synthetic_tools()

    def add(name):
        tools.append(synth[name])
        injected.add(name)

    if not (present & _WRITE_NAMES):
        add("write_file")
    if not (present & _EDIT_NAMES):
        add("edit_file")  # the surgical-edit path; a whole-file rewrite botches a one-char fix
    if "read_file" not in present:
        add("read_file")
    if "list_dir" not in present:
        add("list_dir")
    if "web_fetch" not in present:
        add("web_fetch")
    if "web_search" not in present:
        if "local_web_search" in present:
            for t in tools:  # present the harness's Brave search to the model as web_search
                if (((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) == "local_web_search":
                    (t.get("function") or t)["name"] = "web_search"
        elif brave_key:
            add("web_search")  # no harness search tool → synthesize one lowered to a Brave curl

    if injected and rlog is not None:
        rlog.emit("writeproxy.advertised", tools=sorted(injected))
    return injected


# --------------------------------------------------------------------- outbound lowering


def _sentinel(name: str, arguments) -> str:
    """The leading comment line that lets inbound rebuild the original tool call, statelessly."""
    args_str = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    payload = base64.b64encode(json.dumps({"name": name, "arguments": args_str}).encode("utf-8")).decode("ascii")
    return f"# {_SENTINEL}{payload}"


def _shell_call(orig_id: str, shell_tool: dict, command: str) -> dict:
    return {"id": orig_id, "type": "function",
            "function": {"name": shell_tool["name"], "arguments": json.dumps(shell_args(shell_tool, command))}}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _write_command(path: str, content: str) -> str:
    """Byte-exact atomic write: base64 (on stdin via heredoc — no arg-size limit) decoded to a temp
    file, then moved over the target so a partial decode never leaves a half-written file."""
    q, tmp = _qbash(path), _qbash(path + _TMP_SUFFIX)
    # &&-chain so a failure at ANY step (mkdir/decode/mv) short-circuits BEFORE the success token —
    # blank/absent token ⇒ the write did not land, and the model sees the real stderr.
    return (f'mkdir -p "$(dirname {q})" && base64 -d > {tmp} <<\'{_HD_B64}\'\n'
            f'{_b64(content)}\n{_HD_B64}\nmv {tmp} {q} && printf %s {_qbash(_WROTE)}')


# The edit executor (old/new/path base64'd — nothing to escape). Tries an EXACT single match first
# (precise); then a WHITESPACE-FLEXIBLE match — the non-whitespace tokens of old_string separated by
# any whitespace — which forgives the indentation / blank-line / trailing-space drift a 9B routinely
# produces (a byte-exact-only match failed ~1/3 of real edits). Still fail-CLOSED: 0 or ambiguous
# matches never write. On a genuine miss it hands the model the file's ACTUAL content near its target
# so its next attempt can copy the exact text, instead of a bare "found 0" it can only guess against.
_EDIT_PY = r'''import base64,sys,re,pathlib,difflib
p=pathlib.Path(base64.b64decode('{path}').decode())
old=base64.b64decode('{old}').decode()
new=base64.b64decode('{new}').decode()
if old==new:
    sys.exit('edit_file: old_string and new_string are IDENTICAL — this edit changes nothing. Put the text you actually want into new_string (or read the file to see what needs changing).')
s=p.read_text()
n=s.count(old)
if n==1:
    p.write_text(s.replace(old,new,1)); print('{wrote}'); sys.exit()
if n>1:
    sys.exit('edit_file: old_string occurs %d times — add surrounding lines to make it unique'%n)
toks=old.split()
if toks:
    ms=list(re.compile(r'\s+'.join(map(re.escape,toks))).finditer(s))
    if len(ms)==1:
        m=ms[0]; p.write_text(s[:m.start()]+new+s[m.end():]); print('{wrote}'); sys.exit()
    if len(ms)>1:
        sys.exit('edit_file: old_string matches %d places (ignoring whitespace) — add more surrounding context'%len(ms))
key=next((l.strip() for l in old.split(chr(10)) if l.strip()),'')
new_first=next((l.strip() for l in new.split(chr(10)) if l.strip()),'')
lines=s.split(chr(10)); ctx=''; close=''
if key:
    for i,l in enumerate(lines):
        if key[:40] in l:
            ctx=chr(10).join(lines[max(0,i-2):i+4]); break
    if not ctx:  # no substring anchor — find the file line the old_string is CLOSEST to (a near-miss)
        cm=difflib.get_close_matches(key, [l.strip() for l in lines if l.strip()], n=1, cutoff=0.75)
        if cm:
            close=cm[0]
msg=('edit_file: old_string is NOT in '+p.name+' — and this is not a spacing problem '
     '(indentation/whitespace is already tolerated), so your text genuinely differs from the file '
     '(likely a stale copy from before your last edit).')
if ctx:
    msg+=' The file ACTUALLY reads near there:'+chr(10)+'---'+chr(10)+ctx+chr(10)+'---'+chr(10)+'Copy THAT exact text into old_string and edit again — do not rewrite the whole file.'
elif close and new_first and new_first in close:
    # THE PHANTOM BUG: old_string is a near-miss of a real line, and that line ALREADY reads the way
    # new_string wants — the model is re-fixing an already-correct line it misremembers (e.g. it thinks
    # the file says `base_user` and keeps "fixing" it to `base_url`, which is already there).
    msg+=(' In fact that file already reads: '+chr(10)+'---'+chr(10)+close+chr(10)+'--- '
          +chr(10)+'which is ALREADY what your new_string makes it. This change is DONE — do NOT edit '
          'this line again. Your old_string just misremembers the current text. Move on to the real '
          'remaining problem (run the tests and read the actual failure).')
elif close:
    msg+=(' Your old_string is very CLOSE to this line but not identical — you likely mistyped a token '
          '(e.g. a variable name):'+chr(10)+'---'+chr(10)+close+chr(10)+'---'+chr(10)+'Copy that line '
          'VERBATIM into old_string. Do not rewrite the whole file.')
elif len(s)<={small}:
    msg+=' The anchor line is gone (an earlier edit likely removed it), so there is nothing near it to show. The file CURRENTLY reads IN FULL — copy the exact text you want to change into old_string:'+chr(10)+'---'+chr(10)+s+chr(10)+'---'
else:
    msg+=' Read the file again to get its current contents, then edit — do not rewrite the whole file.'
sys.exit(msg)
'''


def _edit_command(path: str, old: str, new: str) -> str:
    py = _EDIT_PY.format(path=_b64(path), old=_b64(old), new=_b64(new), wrote=_WROTE, small=EDIT_SHOW_FULL_MAX)
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


def _read_command(args: dict) -> str | None:
    path = _tool_path(args)
    if not path:
        return None
    q = _qbash(path)
    start, end = args.get("start_line"), args.get("end_line")
    if isinstance(start, int) and start > 0 and isinstance(end, int) and end >= start:
        return f"sed -n '{start},{end}p' {q}"
    if isinstance(start, int) and start > 0:          # start-only → from the line to EOF (was ignored)
        return f"sed -n '{start},$p' {q}"
    return f"cat {q}"


def _list_command(args: dict) -> str:
    path = args.get("path") or args.get("dir") or args.get("directory") or "."
    return f"ls -la {_qbash(path)}"


def _fetch_command(args: dict, session: str | None = None) -> str | None:
    """cria fetches + reduces the page IN-PROCESS (it runs as a stateful server with a per-URL
    doc cache) and lowers to a ``printf`` of the ALREADY-REDUCED, bounded result — so the harness
    records navigable content that PERSISTS in the conversation, instead of running a raw ``curl``
    whose single-line JSON/YAML it truncates mid-line (the Ada-handle openapi.json incident).
    Structural JSON/YAML reduce + ``find``/``cursor`` navigation live in :mod:`cria.webfetch`.
    ``session`` (when known) enables the exact-repeat + stop-guessing gates in webfetch."""
    url = args.get("url")
    if not url:
        return None
    cursor = args.get("cursor")
    result = webfetch.fetch_nav(
        str(url),
        find=(str(args["find"]) if args.get("find") else None),
        cursor=(str(cursor) if cursor not in (None, "") else None),
        session=session,
    )
    return f"printf %s {_qbash(result)}"


def _search_command(args: dict, brave_key: str) -> str:
    """Brave web search lowered to a curl — endpoint, %-encoded query, and headers come from the
    shared `brave` module (same request the planner's in-process search builds), then parsed to
    compact "title / url / description" lines the model can pair with web_fetch."""
    url = brave.query_url(args.get("query") or "")
    header_flags = " ".join(f"-H {_qbash(f'{k}: {v}')}" for k, v in brave.headers(brave_key).items())
    parse = (r"""python3 -c 'import sys,json"""
             r""";d=json.load(sys.stdin);r=(d.get("web") or {}).get("results") or []"""
             r""";print("\n".join("%s\n  %s\n  %s"%(x.get("title",""),x.get("url",""),x.get("description","")) for x in r[:8]) or "no results")'""")
    return f"curl -sL --max-time {_FETCH_TIMEOUT_S} {header_flags} {_qbash(url)} | {parse}"


def translate_outbound(completion: dict, shell_tool: dict, rlog=None, injected: set[str] | None = None,
                       brave_key: str | None = None, native_search: str | None = None,
                       session: str | None = None) -> dict:
    """Lower cria's synthetic tool calls to shell commands the harness runs, each stamped with the
    stateless re-presentation sentinel. Only lowers a tool cria INJECTED (a harness-native tool of
    the same name is the harness's to run). ``web_search`` routes to ``native_search`` when the
    harness has one, else to a Brave curl (when injected)."""
    injected = injected or set()
    for choice in completion.get("choices", []):
        tool_calls = (choice.get("message") or {}).get("tool_calls")
        if not tool_calls:
            continue
        rebuilt: list[dict] = []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name")
            args = _parse(fn.get("arguments"))
            cmd = None
            # cria's own dir is off-limits: refuse a synthetic read/write/edit/list whose path lands
            # in ~/.cria BEFORE lowering it, so cria never cats its secrets to the model or lets a
            # stray write corrupt its state. The refusal is a normal tool result the model reads.
            if name in injected and (target := _guarded_path(name, args)) and _targets_cria_home(target):
                cmd = f"printf %s {_qbash(_CRIA_HOME_REFUSAL)}"
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_cria_home", tool=name, path=target)
            elif name in _WRITE_NAMES and name in injected:
                path = _tool_path(args)
                if path:
                    cmd = _write_command(str(path), _repair_double_escaped(str(args.get("content") or args.get("contents") or "")))
            elif name in _EDIT_NAMES and name in injected:
                path = _tool_path(args)
                if path and args.get("old_string") is not None:
                    cmd = _edit_command(str(path), str(args.get("old_string") or ""), str(args.get("new_string") or ""))
            elif name in _READ_NAMES and name in injected:
                cmd = _read_command(args)
            elif name in _LIST_NAMES and name in injected:
                cmd = _list_command(args)
            elif name in _FETCH_NAMES and name in injected:
                cmd = _fetch_command(args, session)
            elif name == "web_search":
                refusal = webfetch.gate_search(session, str(args.get("query") or ""))
                if refusal is not None:  # exact-repeat search this session → refuse, don't burn a call
                    cmd = f"printf %s {_qbash(refusal)}"
                elif "web_search" in injected and brave_key:  # synthetic → Brave curl
                    cmd = _search_command(args, brave_key)
                elif native_search and native_search != "web_search":  # route to the harness's search tool
                    rebuilt.append({**tc, "function": {**fn, "name": native_search}})
                    continue
            if cmd is not None:
                rebuilt.append(_shell_call(tc.get("id"), shell_tool, f"{_sentinel(name, fn.get('arguments'))}\n{cmd}"))
                if rlog is not None:
                    rlog.emit("writeproxy.lowered", tool=name)
            else:
                rebuilt.append(tc)
        choice["message"]["tool_calls"] = rebuilt
    return completion


# --------------------------------------------------------------------- inbound re-presentation


def _command_of(args) -> str:
    """The command string out of a shell-tool call's arguments (reverse of shell_args)."""
    d = _parse(args)
    v = next((d[f] for f in (*_CMD_FIELDS, "script") if d.get(f)), None)
    if isinstance(v, list):
        return v[-1] if v else ""
    return str(v or "")


def _read_sentinel(command: str) -> dict | None:
    """The original tool call encoded in a lowered command's sentinel, or None."""
    m = _SENTINEL_LINE.search(command or "")
    if not m:
        return None
    try:
        d = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
        return {"name": d["name"], "arguments": d.get("arguments") or "{}"}
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        return None


def represent_inbound(messages: list[dict], rlog=None) -> list[dict]:
    """Swap cria's shell translations back to the tool the model actually called — read STATELESSLY
    from the sentinel in each stored command, so it survives a restart. A write/edit's empty success
    is reframed as a confirmation (never overriding a real error). A harness ``local_web_search`` in
    history is re-presented as ``web_search`` to match what the model was shown."""
    out: list[dict] = []
    swapped = 0
    write_paths: dict[str, str] = {}  # tool_call_id -> path, for the empty-success reframe
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            new_calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                name = fn.get("name")
                if name in SHELL_TOOL_NAMES:
                    orig = _read_sentinel(_command_of(fn.get("arguments")))
                    if orig is not None:
                        tc = {**tc, "function": {"name": orig["name"], "arguments": orig["arguments"]}}
                        swapped += 1
                        if orig["name"] in (_WRITE_NAMES | _EDIT_NAMES):
                            p = _parse(orig["arguments"])
                            write_paths[tc.get("id")] = _tool_path(p) or ""
                elif name == "local_web_search":  # always present the Brave tool as web_search
                    tc = {**tc, "function": {**fn, "name": "web_search"}}
                    swapped += 1
                new_calls.append(tc)
            out.append({**m, "tool_calls": new_calls})
        elif role == "tool" and _WROTE in str(m.get("content") or "") and m.get("tool_call_id") in write_paths:
            # POSITIVE success signal only — a blank or error result (no token) is left untouched so
            # the model sees the real failure instead of a fabricated "Wrote {path}".
            out.append({**m, "content": prompts.render("write_confirm", path=write_paths[m["tool_call_id"]])})
        else:
            out.append(m)
    if swapped and rlog is not None:
        rlog.emit("writeproxy.represented", calls=swapped)
    return out


# --------------------------------------------------------------------- content repair

# Ported from codex-local tool_aliases.rs: a weak model sometimes emits a file's whole content with
# literal `\n` for every newline and NO real newlines — which lands the file as one physical line.
# If the content has no real newline but has a literal `\n`, decode its backslash escapes.
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "0": "\0"}


def _repair_double_escaped(content: str) -> str:
    if "\n" in content or "\\n" not in content:
        return content
    return _decode_backslash_escapes(content)


def _decode_backslash_escapes(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            out.append("\\")
            i += 1
            continue
        nxt = s[i + 1]
        out.append(_ESCAPES[nxt] if nxt in _ESCAPES else "\\" + nxt)
        i += 2
    return "".join(out)
