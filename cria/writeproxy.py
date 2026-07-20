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
from . import dirguard
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

# Tool-call-dialect special-token sentinels a weak model leaks into a shell command when it FUSES two
# calls into one turn (gemma live: `["bash","-lc","pytest"]}<tool_call|><|tool_call>call:write_file{…`).
# massage._recover_fused_call already RECOVERS the real first call for the ~83% that's cleanly parseable
# (a true massage — no wasted turn); this is the FLOOR beneath it: when even that can't reconstruct the
# command (mixed quoting / hallucinated paths), the debris survives into the lowered command and bash
# dies on the unbalanced quotes on a cryptic EOF. Rather than run garbage, REFUSE with guidance the model
# can act on — the "replace the bad call with a model-read refusal" pattern used for the dir guards.
# (Mirrors massage.py's dialect sentinels; kept local because massage imports writeproxy, not vice versa.)
_TC_DEBRIS = ("<|tool_call>", "<tool_call|>", '<|"|>', "<|tool_call_start|>", "<|tool_call_end|>")
_MALFORMED_TC_REFUSAL = (
    "Your last tool call was malformed: tool-call marker tokens leaked into the command text, so it is "
    "not a runnable command — this usually means two calls got fused into one turn (or broken quoting). "
    "Nothing was run. Send ONE clean tool call this turn: a single shell command as a plain JSON array of "
    "strings, and stop after it."
)


def _has_tc_debris(arguments) -> bool:
    """True when a tool call's raw arguments carry leaked tool-call special tokens — a fused/corrupt call
    whose command would reach bash as garbage. Cheap substring scan over the raw string."""
    s = arguments if isinstance(arguments, str) else ("" if arguments is None else str(arguments))
    return any(tok in s for tok in _TC_DEBRIS)


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
# Heredoc terminator — the payload rides on stdin, so there is NO arg-size limit (no chunking). Both
# the write and edit commands are python heredocs (they share the validate-before-lower syntax check).
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
# Ask Brave for its per-request maximum so a lower-ranked but authoritative page (9th, 12th…) is
# actually IN the response — then the parser shows ALL of them (no display slice) and discloses the
# total count, so the model is never silently capped at the top few and knows how many exist. 20 is
# Brave's hard per-request ceiling (query_url clamps to it); this requests it, it does not exceed it.
_SEARCH_MAX_RESULTS = 20


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


# VALIDATE-BEFORE-LOWER: a shared, in-process syntax check for the languages cria can parse with the
# stdlib (Python via compile, JSON via json, TOML via tomllib/tomli). Returns a parser message on a
# syntax error, else None. It runs INSIDE the lowered write/edit command, so a syntactically-broken
# file never reaches disk — the model gets the exact parser error immediately instead of the churn of
# writing garbage, hitting the completion gate two turns later, and re-breaking on the next edit.
# REGRESSION-ONLY (the write/edit callers gate on the BEFORE state): it refuses only when a write/edit
# would break a file that currently PARSES; it NEVER blocks a model from editing an already-broken file
# toward valid (broken→still-broken and broken→valid both write freely). Version-scoped to what the
# workspace python's own compile() accepts, which is the interpreter that will run the code anyway.
_VALIDATE_FN = r'''def _v(path, raw):
    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
    except Exception:
        return None
    low = path.lower()
    try:
        if low.endswith(('.py', '.pyi')):
            compile(text, path, 'exec')
        elif low.endswith('.json'):
            import json as _json; _json.loads(text)
        elif low.endswith('.toml'):
            try:
                import tomllib as _t
            except ImportError:
                try:
                    import tomli as _t
                except ImportError:
                    return None
            _t.loads(text)
    except Exception as _e:
        return str(_e)
    return None
'''

# Byte-exact atomic write (python heredoc — content rides in the source on stdin, no arg-size limit /
# no chunking), with validate-before-write: refuse only when this would replace a currently-VALID file
# with content that does not parse. A new file or an already-broken file writes freely.
_WRITE_PY = r'''import base64,sys,pathlib,os
p=pathlib.Path(base64.b64decode('{path}').decode())
raw=base64.b64decode('{content}')
_after=_v(str(p),raw)
if _after is not None and p.exists() and _v(str(p),p.read_bytes()) is None:
    sys.exit('write_file REFUSED (not written): this would replace a currently-valid '+p.name+
             ' with content that does not parse — '+_after+'. Fix the content so the file is valid, then write again.')
p.parent.mkdir(parents=True,exist_ok=True)
tmp=str(p)+'{suffix}'
pathlib.Path(tmp).write_bytes(raw)
os.replace(tmp,str(p))
print('{wrote}')
'''


def _write_command(path: str, content: str) -> str:
    """Byte-exact atomic write via a python heredoc: validate-before-write (a broken write over a valid
    file is refused), then write to a temp and os.replace over the target so a partial write never
    leaves a half-written file. No arg-size limit / no chunking — the content rides in the heredoc."""
    py = (_VALIDATE_FN + _WRITE_PY).format(path=_b64(path), content=_b64(content),
                                           suffix=_TMP_SUFFIX, wrote=_WROTE)
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


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
s=p.read_text()
if old==new:
    msg='edit_file: old_string and new_string are IDENTICAL — this edit changes nothing.'
    if len(s)<={small}:
        # The observed spiral: the model keeps submitting old==new (it can't pin down the exact current
        # text, esp. a whitespace/indent diff) and burns dozens of edit_file calls on a one-char fix.
        # For a SMALL file the reliable escape is to REWRITE it whole with write_file (it can produce the
        # full corrected content directly), overriding the general "don't rewrite" guidance for this case.
        msg+=(' You keep submitting an edit that changes nothing — you cannot pin down the exact current'
              ' text. STOP using edit_file on this file. It is small: REWRITE THE WHOLE FILE with'
              ' write_file, using its current contents below as your starting point:'+chr(10)+'---'+chr(10)+s+chr(10)+'---')
    else:
        msg+=' Put the text you actually want into new_string (or read the file to see what needs changing).'
    sys.exit(msg)
_before=_v(str(p),s)
def _w(res):
    if _before is None:                       # the file PARSES now — do not let this edit break it
        _e=_v(str(p),res)
        if _e is not None:
            sys.exit('edit_file REFUSED (not written): this edit would break '+p.name+', which currently'
                     ' parses cleanly — '+_e+'. Fix new_string so the file stays valid, then edit again.')
    p.write_text(res); print('{wrote}'); sys.exit()
n=s.count(old)
if n==1:
    _w(s.replace(old,new,1))
if n>1:
    sys.exit('edit_file: old_string occurs %d times — add surrounding lines to make it unique'%n)
toks=old.split()
if toks:
    ms=list(re.compile(r'\s+'.join(map(re.escape,toks))).finditer(s))
    if len(ms)==1:
        m=ms[0]; _w(s[:m.start()]+new+s[m.end():])
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
    # A small file whose anchor is gone (a prior edit removed it) and your old_string is stale — the
    # reliable escape is to rewrite it whole rather than keep guessing at old_string.
    msg+=(' The anchor line is gone (an earlier edit likely removed it). This file is small, and your'
          ' old_string is stale — the simplest fix is to REWRITE THE WHOLE FILE with write_file rather'
          ' than more edit_file guesses. Its current contents:'+chr(10)+'---'+chr(10)+s+chr(10)+'---')
else:
    msg+=' Read the file again to get its current contents, then edit — do not rewrite the whole file.'
sys.exit(msg)
'''


def _edit_command(path: str, old: str, new: str) -> str:
    py = (_VALIDATE_FN + _EDIT_PY).format(path=_b64(path), old=_b64(old), new=_b64(new),
                                          wrote=_WROTE, small=EDIT_SHOW_FULL_MAX)
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
    compact "title / url / description" lines the model can pair with web_fetch. Requests Brave's
    per-request maximum and prints EVERY returned result (no display slice) with a total-count header
    so the authoritative page — which may rank 9th+ — reaches the model and it knows how many exist."""
    url = brave.query_url(args.get("query") or "", count=_SEARCH_MAX_RESULTS)
    header_flags = " ".join(f"-H {_qbash(f'{k}: {v}')}" for k, v in brave.headers(brave_key).items())
    parse = (r"""python3 -c 'import sys,json"""
             r""";d=json.load(sys.stdin);r=(d.get("web") or {}).get("results") or []"""
             r""";body="\n".join("%s\n  %s\n  %s"%(x.get("title",""),x.get("url",""),x.get("description","")) for x in r)"""
             r""";print(("%d results:\n"%len(r))+body if r else "no results")'""")
    return f"curl -sL --max-time {_FETCH_TIMEOUT_S} {header_flags} {_qbash(url)} | {parse}"


def _external_refusal(name, args, fn, injected, level: str, workspace: str | None) -> str | None:
    """A refusal string when this tool call reaches outside the workspace beyond ``level``, else None.
    A synthetic file tool is checked by its explicit path + operation; a raw shell command by a
    heuristic scan. cria's OWN composed commands (the gate probe / a lowered synthetic, carrying a
    marker) are exempt — trusted and always workspace-scoped. See cria/dirguard.py."""
    if level == "write" or not workspace:  # unrestricted, or no known workspace to classify against
        return None
    if name in injected:  # a synthetic file tool cria advertised → explicit path + operation
        target = _guarded_path(name, args)
        if not target:
            return None
        return dirguard.path_refusal(target, name in _WRITE_NAMES or name in _EDIT_NAMES, level, workspace)
    if name in SHELL_TOOL_NAMES:  # the harness's raw shell → heuristic path/verb scan
        command = _command_of(fn.get("arguments"))
        if _SENTINEL in command or "___CRIA_GATE_" in command:  # cria's own composed command → trust
            return None
        return dirguard.command_refusal(command, level, workspace)
    return None


def translate_outbound(completion: dict, shell_tool: dict, rlog=None, injected: set[str] | None = None,
                       brave_key: str | None = None, native_search: str | None = None,
                       session: str | None = None, workspace_root: str | None = None,
                       external_dir_permission: str = "write") -> dict:
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
            # MALFORMED FUSED CALL: the model leaked tool-call marker tokens into the command (two calls
            # fused / broken quoting). It can't be reconstructed and would die in bash as a cryptic EOF —
            # refuse it with guidance to send ONE clean call, so the turn teaches instead of just failing.
            if name == "shell" and _has_tc_debris(fn.get("arguments")):
                cmd = f"printf %s {_qbash(_MALFORMED_TC_REFUSAL)}"
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_malformed_call", tool=name)
            # EXTERNAL-DIR GUARD (cria-side, independent of the harness sandbox): a fledgling model
            # gets bounded to the workspace even when the harness runs --yolo. Refuse a synthetic file
            # tool or raw shell command reaching outside the workspace beyond [safety] permission.
            elif (reason := _external_refusal(name, args, fn, injected, external_dir_permission, workspace_root)) is not None:
                cmd = f"printf %s {_qbash(reason)}"
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_external", tool=name, level=external_dir_permission)
            # cria's own dir is off-limits: refuse a synthetic read/write/edit/list whose path lands
            # in ~/.cria BEFORE lowering it, so cria never cats its secrets to the model or lets a
            # stray write corrupt its state. The refusal is a normal tool result the model reads.
            elif name in injected and (target := _guarded_path(name, args)) and _targets_cria_home(target):
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


# The Codex exec-output envelope wrapped around a lowered synthetic tool's result:
#   ``Chunk ID: <hex>`` / ``Wall time: <n> seconds`` / ``Process exited with code <n>`` /
#   ``Original token count: <n>`` / ``Output:`` / [``Warning: truncated output …``] /
#   [``Total output lines: <n>``] then the real stdout.
# web_fetch/web_search are SYNTHETIC tools cria lowers to a shell exec, so the harness wraps their
# result in this envelope. Re-presented as a web_fetch value it reads as a SHELL command that cached
# a "chunk" to disk: the model then greps a phantom cache path and re-fetches the whole page instead
# of paging with cursor/find (observed live — a 57K OpenAPI doc grepped at an imagined
# .cache/mcp-server/… file, then re-fetched 7×, its reasoning derailed across 10 turns by a "cache is
# gone" delusion). The tool's OWN "⚠ More remains … cursor=" footer is the real pagination signal;
# the envelope adds only a false disk-cache mental model (and a spurious "truncated output" warning —
# webfetch PAGINATES, it does not truncate). Strip it back to the payload. A no-op when absent.
_ENVELOPE_OUTPUT_LINE = re.compile(r"^Output:[ \t]*$", re.M)
_ENVELOPE_ADVISORY = re.compile(r"^(?:Warning: truncated output.*|Total output lines: \d+)[ \t]*$")


def _strip_exec_envelope(content: str) -> str:
    """The harness exec envelope around a re-presented synthetic-tool result → just the payload.
    Untouched when the envelope isn't present (a native path, an already-clean or non-exec result)."""
    if not content:
        return content
    m = _ENVELOPE_OUTPUT_LINE.search(content)
    if not m or "Process exited with code" not in content[:m.start()]:
        return content
    lines = content[m.end():].split("\n")
    while lines and (_ENVELOPE_ADVISORY.match(lines[0]) or not lines[0].strip()):
        lines.pop(0)  # drop the harness's leading truncation advisories + blank lines
    return "\n".join(lines).rstrip("\n")


def represent_inbound(messages: list[dict], rlog=None) -> list[dict]:
    """Swap cria's shell translations back to the tool the model actually called — read STATELESSLY
    from the sentinel in each stored command, so it survives a restart. Every SYNTHETIC tool is lowered
    to a shell exec, so its result comes back wrapped in the harness exec envelope (Chunk ID / Process
    exited / Output: / …). That envelope is stripped from read/nav results (read_file, list_dir,
    web_fetch, web_search) and from write/edit FAILURES so the tool reads as its own abstraction, not a
    disk-caching shell command. A write/edit SUCCESS is reframed as a clean confirmation (never over a
    real error). A harness ``local_web_search`` is re-presented as ``web_search``. The model's OWN
    exec_command calls keep their envelope — there the shell framing is the truth."""
    out: list[dict] = []
    swapped = 0
    write_paths: dict[str, str] = {}  # tool_call_id -> path, for the success reframe / failure strip
    strip_ids: set[str] = set()       # read/nav re-presented tool ids → strip the harness exec envelope
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
                        elif orig["name"] in (_READ_NAMES | _LIST_NAMES | _FETCH_NAMES | _SEARCH_NAMES):
                            strip_ids.add(tc.get("id"))
                elif name == "local_web_search":  # always present the Brave tool as web_search
                    tc = {**tc, "function": {**fn, "name": "web_search"}}
                    swapped += 1
                    strip_ids.add(tc.get("id"))
                new_calls.append(tc)
            out.append({**m, "tool_calls": new_calls})
        elif role == "tool":
            tid = m.get("tool_call_id")
            content = str(m.get("content") or "")
            if tid in strip_ids:                          # read/nav result → drop the shell envelope
                out.append({**m, "content": _strip_exec_envelope(content)})
            elif tid in write_paths and _WROTE in content:  # write/edit SUCCESS → clean confirmation
                out.append({**m, "content": prompts.render("write_confirm", path=write_paths[tid])})
            elif tid in write_paths:                      # write/edit FAILURE → strip envelope, keep the
                out.append({**m, "content": _strip_exec_envelope(content)})  # real error the model must see
            else:
                out.append(m)
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
