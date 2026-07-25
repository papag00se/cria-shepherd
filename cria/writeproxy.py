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
import hashlib
import json
import os
import re
from pathlib import Path
from shlex import quote as _qbash  # one bash-quoting rule (was a hand-rolled _qbash)

from . import brave, editrecovery, prompts, webfetch
from . import dirguard
from .config import CRIA_HOME
from .shelltool import _CMD_FIELDS, SHELL_TOOL_NAMES, shell_args
from .toolargs import PATH_KEYS as _PATH_KEYS, parse_args as _parse, tool_path as _tool_path

_WRITE_NAMES = {"write_file", "create_file"}
_EDIT_NAMES = {"edit_file", "str_replace"}
_READ_NAMES = {"read_file"}
_LIST_NAMES = {"list_dir"}

# cria's own private dir is off-limits to the driven model — no reading (it holds cria's .env
# credentials and config) and no writing (a stray file, or worse an overwrite of cria.toml /
# loopstate, corrupts cria). A confused small model has done both: it invented a `~/.cria/chat-<id>.txt`
# path and wrote a "message to the user" into it, having no other channel to speak. This is the dual of
# the no-workspace-pollution rule, enforced at the same chokepoint that lowers the synthetic tools.
# The cria-home refusal (prompts/cria_home_refusal.txt) and the malformed-fused-call refusal
# (prompts/malformed_call_refusal.txt) are loaded per call at their use sites in translate_outbound.

# Tool-call-dialect special-token sentinels a weak model leaks into a shell command when it FUSES two
# calls into one turn (gemma live: `["bash","-lc","pytest"]}<tool_call|><|tool_call>call:write_file{…`).
# massage._recover_fused_call already RECOVERS the real first call for the ~83% that's cleanly parseable
# (a true massage — no wasted turn); this is the FLOOR beneath it: when even that can't reconstruct the
# command (mixed quoting / hallucinated paths), the debris survives into the lowered command and bash
# dies on the unbalanced quotes on a cryptic EOF. Rather than run garbage, REFUSE with guidance the model
# can act on — the "replace the bad call with a model-read refusal" pattern used for the dir guards.
# (Mirrors massage.py's dialect sentinels; kept local because massage imports writeproxy, not vice versa.)
_TC_DEBRIS = ("<|tool_call>", "<tool_call|>", '<|"|>', "<|tool_call_start|>", "<|tool_call_end|>")


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
                        {"url": {"type": "string"}, "find": {"type": "string"}, "cursor": {"type": "string"},
                         "raw": {"type": "boolean"}}, ["url"]),
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
    sys.exit(base64.b64decode('{refused}').decode().replace('%%NAME%%',p.name).replace('%%AFTER%%',_after))
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
                                           suffix=_TMP_SUFFIX, wrote=_WROTE,
                                           refused=_b64(prompts.load("write_refused")))
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


# The edit executor (old/new/path base64'd — nothing to escape). Tries an EXACT single match first
# (precise); then a WHITESPACE-FLEXIBLE match — the non-whitespace tokens of old_string separated by
# any whitespace — which forgives the indentation / blank-line / trailing-space drift a 9B routinely
# produces (a byte-exact-only match failed ~1/3 of real edits). Still fail-CLOSED: 0 or ambiguous
# matches never write. On a genuine miss it hands the model the file's ACTUAL content near its target
# so its next attempt can copy the exact text, instead of a bare "found 0" it can only guess against.
# On a MISS the heredoc does NOT compose prose — it reports the FACTS (mode + the file's real current
# bytes + the near anchor) as a ``⟦ctx:editfail⟧`` marker; cria.editrecovery turns that into the one
# monotonic directive (surgical → committed whole-file rewrite), keyed on the file's failure history.
# This keeps the history-blind, whipsawing rewrite/don't-rewrite advice OUT of the per-call heredoc.
_EDIT_PY = r'''import base64,sys,re,pathlib,difflib,json
p=pathlib.Path(base64.b64decode('{path}').decode())
old=base64.b64decode('{old}').decode()
new=base64.b64decode('{new}').decode()
s=p.read_text()
def _fail(mode,**kw):
    kw['mode']=mode; kw['path']=p.name; kw.setdefault('current',s)
    sys.exit('{editfail}'+base64.b64encode(json.dumps(kw).encode()).decode())
if old==new:
    _fail('identical')
_before=_v(str(p),s)
def _w(res):
    if _before is None:                       # the file PARSES now — do not let this edit break it
        _e=_v(str(p),res)
        if _e is not None:
            _fail('would_break',err=_e)
    p.write_text(res); print('{wrote}'); sys.exit()
n=s.count(old)
if n==1:
    _w(s.replace(old,new,1))
if n>1:
    _fail('multi',n=n)
toks=old.split()
if toks:
    ms=list(re.compile(r'\s+'.join(map(re.escape,toks))).finditer(s))
    if len(ms)==1:
        m=ms[0]; _w(s[:m.start()]+new+s[m.end():])
    if len(ms)>1:
        _fail('multi_flex',n=len(ms))
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
if ctx:
    _fail('anchor',anchor=ctx)
elif close and new_first and new_first in close:
    _fail('phantom',anchor=close)   # already-correct line the model misremembers
elif close:
    _fail('close',anchor=close)     # near-miss: a mistyped token
else:
    _fail('no_anchor')
'''


def _edit_command(path: str, old: str, new: str) -> str:
    py = (_VALIDATE_FN + _EDIT_PY).format(path=_b64(path), old=_b64(old), new=_b64(new),
                                          wrote=_WROTE, editfail=editrecovery.EDITFAIL)
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


# A whole read bigger than this many bytes is steered to grep / a line range instead of cat'd — a raw
# cat of a big file is truncated HEAD+TAIL by the harness's exec-output cap (Codex kept only a few KB of
# a 96 KB spec, eating the middle where the endpoints were), a silent lie the model then acts on. Chosen
# below common harness caps; the whole size-check is lowered INSIDE the read_file call, so the sentinel
# swap re-presents it as a plain read_file — the model never sees the `wc`/`if` plumbing.
READ_INLINE_MAX = 12000


def _ranged_read(q: str, path: str, sed_end: str, start: int) -> str:
    """A ranged read (``sed -n 'start,END p'``) with the SAME two guards a whole read needs:
    * SIZE — if the range's bytes exceed READ_INLINE_MAX the HARNESS truncates the output (cria's
      'never hand back truncatable content' principle). Observed live: a big range was cut at ~20707
      tokens and the model then read line '20707' — the truncation count mistaken for a line number.
      Too big → steer to a narrower range / grep instead of returning a doomed-to-be-truncated blob.
    * PAST-EOF — a start beyond the file is a SILENT EMPTY the model crawls forever; say the length.
    An in-range, in-size read returns exactly its content."""
    steer = prompts.render("large_range_steer", path=str(path))
    return (
        # awk NR (not `wc -l`) so a final line with no trailing newline still counts — else a 1-line
        # file reads as 0 lines and a valid `start_line: 1` falsely trips the past-EOF branch.
        f'__n=$(awk \'END{{print NR}}\' {q} 2>/dev/null || echo 0); '
        f'if [ {start} -gt "$__n" ]; then '
        f'printf "(no lines in that range — %s has %s lines; line %s is past the end of the file)\\n" {q} "$__n" {start}; '
        f'else __s=$(sed -n \'{sed_end}p\' {q}); '
        f'if [ "$(printf %s "$__s" | wc -c)" -gt {READ_INLINE_MAX} ]; then printf %s {_qbash(steer)}; '
        f'else printf \'%s\\n\' "$__s"; fi; fi'
    )


def _read_command(args: dict) -> str | None:
    path = _tool_path(args)
    if not path:
        return None
    q = _qbash(path)
    start, end = args.get("start_line"), args.get("end_line")
    if isinstance(start, int) and start > 0 and isinstance(end, int) and end >= start:
        return _ranged_read(q, str(path), f"{start},{end}", start)
    if isinstance(start, int) and start > 0:          # start-only → from the line to EOF (was ignored)
        return _ranged_read(q, str(path), f"{start},$", start)
    # Whole read: size-check first; a big file would be truncated by the harness, so hand back a
    # grep/line-range pointer instead of a silently-cut cat. (Small files cat exactly as before.)
    steer = prompts.render("large_read_steer", path=str(path))
    return (f'if [ "$(wc -c < {q} 2>/dev/null || echo 0)" -gt {READ_INLINE_MAX} ]; '
            f"then printf %s {_qbash(steer)}; else cat {q}; fi")


def _list_command(args: dict) -> str:
    path = args.get("path") or args.get("dir") or args.get("directory") or "."
    q = _qbash(path)
    # Same principle as the read guard: a huge directory (node_modules, a data dir) would be SILENTLY
    # truncated by the harness's output cap. Cap the listing at READ_INLINE_MAX bytes and DISCLOSE the
    # total entry count so a cut isn't mistaken for the whole directory.
    return (f'__o=$(ls -la {q} 2>&1); '
            f'if [ "$(printf %s "$__o" | wc -c)" -gt {READ_INLINE_MAX} ]; then '
            f'printf %s "$__o" | head -c {READ_INLINE_MAX}; '
            f'printf "\\n...[listing capped — %s entries in this directory; narrow to a subpath, or grep for a name]...\\n" '
            f'"$(ls -1A {q} 2>/dev/null | wc -l | tr -cd 0-9)"; '
            f"else printf '%s\\n' \"$__o\"; fi")


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
    raw = bool(args.get("raw"))
    find = str(args["find"]) if args.get("find") else None
    cursor = str(cursor) if cursor not in (None, "") else None
    if raw:                       # raw source: the whole markup, not a filtered/paged reduced view
        find = cursor = None
    result = webfetch.fetch_nav(str(url), find=find, cursor=cursor, session=session, raw=raw)
    # A PLAIN fetch (no find/cursor) of an oversized doc: spill the full doc to ./tmp and hand back a
    # short pointer instead of a low-signal page-1. find=/cursor= navigation returns its slice as usual.
    if find is None and cursor is None:
        spill = webfetch.oversized_spill(str(url))
        if spill:
            _status, target, content, msg = spill
            return _spill_command(target, content, msg)
    return f"printf %s {_qbash(result)}"


_SPILL_STAGE = CRIA_HOME / "spill"  # cria's OWN dir — a large doc is staged here, then cp'd into the workspace


def _stage_spill(content: str, target: str) -> str | None:
    """Stage ``content`` in cria's OWN spill dir and return its absolute path, so the lowered command can
    ``cp`` it into the workspace instead of EMBEDDING the whole doc as a shell argument. A big doc's
    base64 in the argv overflows the harness's exec arg-length cap — Codex rejects it with "Argument
    list too long (os error 7)", so the spec never lands on disk and the coder thrashes on research. The
    cp command carries only paths. Returns None on any write failure -> caller falls back to the inline
    printf (fine for a small doc). Bounded scratch; the workspace copy is what the model actually reads."""
    try:
        _SPILL_STAGE.mkdir(parents=True, exist_ok=True)
        for old in sorted(_SPILL_STAGE.glob("*.dat"), key=lambda p: p.stat().st_mtime)[:-64]:
            old.unlink(missing_ok=True)  # keep the dir bounded; these are pure staging copies
        p = _SPILL_STAGE / (hashlib.sha1(target.encode("utf-8")).hexdigest()[:16] + ".dat")
        p.write_text(content, encoding="utf-8")
        return str(p)
    except OSError:
        return None


def _spill_command(target: str, content: str, msg: str) -> str:
    """Land ``content`` at ``target`` (in the workspace spill dir), then print the model-facing pointer
    message — the harness runs this and records the message as the tool result. cria STAGES the doc in
    its own dir and lowers a small ``cp`` (the doc is NOT in the argv, so a large spec can't overflow the
    harness exec arg cap); the sentinel re-presents the whole command as web_fetch, so the model never
    sees the cp or cria's path. Falls back to an inline base64 printf if staging fails. NOT ``chmod 444``:
    a read-only file can't be overwritten by a re-spill, and clearing it would need the ``rm -f`` the
    sandbox rejects — the spill dir is edit-protected by the dirguard, not the FS bit."""
    tdir = os.path.dirname(target) or "."
    staged = _stage_spill(content, target)
    if staged:
        return f"mkdir -p {_qbash(tdir)} && cp {_qbash(staged)} {_qbash(target)} && printf %s {_qbash(msg)}"
    return (f"mkdir -p {_qbash(tdir)} && printf %s {_qbash(_b64(content))} | base64 -d > {_qbash(target)} && "
            f"printf %s {_qbash(msg)}")


def _under_spill_dir(path: str) -> bool:
    """True when ``path`` lands in cria's read-only spill scratch (:data:`webfetch.SPILL_DIR`) — a
    reference doc cria saved, which the model must GREP, not read-whole or edit."""
    norm = os.path.normpath(path or "")
    tail = webfetch.SPILL_DIR.lstrip("./")   # "tmp/cria"
    return norm == tail or norm.startswith(tail + os.sep) or (os.sep + tail + os.sep) in (os.sep + norm)


def _spill_relpath(path: str) -> str | None:
    """The workspace-relative spill path when ``path`` names a SPILL_DIR file via a ROOT-ABSOLUTE
    ``/tmp/read-only/x`` form — the model dropped the leading ``./`` (wrote ``/tmp/read-only/x`` for
    ``./tmp/read-only/x``), which the dirguard then blocks as external, so the model can never re-read
    the doc cria saved (the live footgun: a fetched spec sitting unreadable on disk). Return
    ``./tmp/read-only/x``; ``None`` otherwise. Only the root-absolute spill form is redirected — a path
    that merely CONTAINS ``tmp/read-only`` deeper in some other tree is left alone."""
    if not path:
        return None
    p = os.path.normpath(os.path.expanduser(str(path)))
    if not os.path.isabs(p):
        return None                                   # already workspace-relative → nothing to fix
    tail = webfetch.SPILL_DIR.lstrip("./")            # "tmp/read-only"
    rel = p.lstrip(os.sep)
    return "./" + rel if (rel == tail or rel.startswith(tail + os.sep)) else None


def _search_command(args: dict, brave_key: str) -> str:
    """Brave web search lowered to a curl — endpoint, %-encoded query, and headers come from the
    shared `brave` module (same request the planner's in-process search builds), then parsed to
    compact "title / url / description" lines the model can pair with web_fetch. Requests Brave's
    per-request maximum and prints EVERY returned result (no display slice) with a total-count header
    so the authoritative page — which may rank 9th+ — reaches the model and it knows how many exist."""
    query = str(args.get("query") or "")
    url = brave.query_url(query, count=_SEARCH_MAX_RESULTS)
    header_flags = " ".join(f"-H {_qbash(f'{k}: {v}')}" for k, v in brave.headers(brave_key).items())
    parse = (r"""python3 -c 'import sys,json"""
             r""";d=json.load(sys.stdin);r=(d.get("web") or {}).get("results") or []"""
             r""";body="\n".join("%s\n  %s\n  %s"%(x.get("title",""),x.get("url",""),x.get("description","")) for x in r)"""
             r""";print(("%d results:\n"%len(r))+body if r else "no results")'""")
    # Save the (noisy) results to the read-only spill dir and hand back a grep/line-read pointer, instead
    # of inlining snippet poison. The lowered command carries the web_search sentinel (translate_outbound),
    # so re-presentation swaps it back to web_search — the model never sees this curl/tee plumbing.
    target, msg = webfetch.search_spill(query)
    tdir = os.path.dirname(target) or "."
    # NO `rm -f` and NO `chmod 444`: the harness sandbox (Codex) HARD-REJECTS `rm -f` ("rm -f style
    # commands are not permitted"), which broke EVERY web_search — the model read the refusal as "the
    # API has permission issues" and hallucinated an endpoint instead. The `rm -f` only existed to clear
    # a prior read-only spill file so the rewrite could land; `>` already truncates a WRITABLE file, so
    # dropping the 444 removes the need for it. The spill dir stays protected from edits by the dirguard
    # (_under_spill_dir / spill_edit_refusal), not the FS bit.
    # `|| printf <fallback>`: a rate-limited/HTML/empty body makes the parse (json.load) raise → the
    # pipeline exits non-zero → without this the harness would record the raw PYTHON TRACEBACK as the
    # model's web_search result (which it then reads as an API-permissions problem and hallucinates an
    # endpoint). The `||` hands it a clean, model-facing "unparseable/transient — retry" line instead.
    fallback = prompts.load("search_unparsable")
    return (f"mkdir -p {_qbash(tdir)} && "
            f"curl -sL --max-time {_FETCH_TIMEOUT_S} {header_flags} {_qbash(url)} | {parse} > {_qbash(target)} "
            f"&& printf %s {_qbash(msg)} "
            f"|| printf %s {_qbash(fallback)}")


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
            # DROPPED-'./' SPILL READ: the model wrote a root-absolute '/tmp/read-only/x' for the
            # workspace-relative './tmp/read-only/x' file cria saved; the dirguard would (correctly)
            # block that as external and the model could never re-read the doc. Rewrite it to the real
            # workspace path BEFORE the guard chain, so the read (or the grep steer) reaches the file.
            if name in injected and (_rp := _tool_path(args)) and (_rel := _spill_relpath(str(_rp))):
                for _k in _PATH_KEYS:
                    if args.get(_k):
                        args = {**args, _k: _rel}
                        break
                if rlog is not None:
                    rlog.emit("writeproxy.spill_path_redirect", tool=name, to=_rel)
            cmd = None
            # MALFORMED FUSED CALL: the model leaked tool-call marker tokens into the command (two calls
            # fused / broken quoting). It can't be reconstructed and would die in bash as a cryptic EOF —
            # refuse it with guidance to send ONE clean call, so the turn teaches instead of just failing.
            if name in SHELL_TOOL_NAMES and _has_tc_debris(fn.get("arguments")):
                cmd = f"printf %s {_qbash(prompts.load('malformed_call_refusal'))}"
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
                cmd = f"printf %s {_qbash(prompts.load('cria_home_refusal'))}"
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_cria_home", tool=name, path=target)
            # cria's read-only SPILL scratch (./tmp/cria): a big doc cria saved as REFERENCE. Refuse an
            # edit/write (observed: identical no-op edits on the spilled spec that poisoned the reasoner);
            # steer a WHOLE read to grep (a raw cat of a big file is truncated by the harness). A ranged
            # read is fine (falls through to the normal read handler).
            elif (name in (_WRITE_NAMES | _EDIT_NAMES | _READ_NAMES) and name in injected
                  and (sp := _tool_path(args)) and _under_spill_dir(str(sp))
                  and not (name in _READ_NAMES and (args.get("start_line") or args.get("end_line")))):
                key = "spill_read_steer" if name in _READ_NAMES else "spill_edit_refusal"
                cmd = f"printf %s {_qbash(prompts.render(key, path=str(sp)))}"
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_spill", tool=name, path=str(sp))
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


def _scrub(v, secrets: list[str]):
    """Replace every secret value in a string (or the strings inside a content-block list) with ***."""
    if isinstance(v, str):
        for s in secrets:
            if s in v:
                v = v.replace(s, "***")
        return v
    if isinstance(v, list):
        return [_scrub(x, secrets) if isinstance(x, str)
                else ({**x, "text": _scrub(x.get("text"), secrets)} if isinstance(x, dict) and isinstance(x.get("text"), str) else x)
                for x in v]
    return v


def redact_secrets(messages: list[dict], secrets: list[str]) -> list[dict]:
    """SECURITY backstop: strip cria's own credentials out of everything the model sees, on EVERY path.
    A lowered web_search curl carries the Brave API key (X-Subscription-Token); the harness echoes that
    command back into the tool RESULT, and on the passthrough path it reaches the model — which then
    reused the key as a fake api-key for the target API. Redaction is unconditional and last-resort: it
    doesn't matter HOW a secret leaks into the history (result echo, envelope, a stray write), it never
    goes out to the model. The real curl already ran with the real key; this only touches model-facing
    text, so search still works."""
    reds = [s for s in secrets if isinstance(s, str) and len(s) >= 8]
    if not reds:
        return messages
    out: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        m2 = dict(m)
        for key in ("content", "output"):
            if key in m2:
                m2[key] = _scrub(m2[key], reds)
        if m2.get("tool_calls"):
            m2["tool_calls"] = [
                {**tc, "function": {**(tc.get("function") or {}),
                                    "arguments": _scrub((tc.get("function") or {}).get("arguments"), reds)}}
                if tc.get("function") else tc
                for tc in m2["tool_calls"]]
        out.append(m2)
    return out


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
            elif tid in write_paths and any(ln.strip() == _WROTE for ln in content.splitlines()):  # write/edit SUCCESS
                out.append({**m, "content": prompts.render("write_confirm", path=write_paths[tid])})
            elif tid in write_paths:                      # write/edit FAILURE → strip the shell envelope,
                # then hand a structured edit-fail fact-report to the ONE edit-recovery owner, which
                # composes the single monotonic directive keyed on this file's failure history so far
                # (``out``). A non-edit-fail failure (write refusal, real error) passes through unchanged.
                out.append({**m, "content": editrecovery.recover(_strip_exec_envelope(content), out)})
            elif "externally-managed-environment" in content:
                # PEP 668: `pip install` fails by design on this box. A weak model retries it forever
                # (observed: Fabliq wedged a whole step re-running pip). Append the remedy (stdlib /
                # --break-system-packages / venv) ONCE — grounded in the real error, not invented.
                out.append({**m, "content": content + "\n\n" + prompts.load("pep668_remedy")})
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
