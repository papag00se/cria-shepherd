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

from . import brave, denial, editrecovery, prompts, webfetch, wsview
from . import content_reduce as content_reduce_mod
from . import probeparse
from . import proberun
from . import dirguard
from .config import CRIA_HOME
from .shelltool import _CMD_FIELDS, is_shell_tool_name, shell_args
from .toolargs import PATH_KEYS as _PATH_KEYS, parse_args as _parse, tool_path as _tool_path

# A tool-protocol tag line, any dialect seen in captures: XML-ish (</tool_call>, <function=...>,
# <parameter=...>), gemma pipes (<|tool_call>, <tool_call|>, <|channel>thought), bare <think> forms.
# How far back a fused call's ARGUMENT may run before the protocol tags that opened it. A second call
# carries a path, a command, or a short body; a whole file does not.
_FUSED_TAIL_MAX_LINES = 40

_PROTOCOL_TAG_LINE = re.compile(
    r"^\s*(?:</?(?:tool_call|function|parameter|think|channel)\b[^\n]*?>?"
    r"|<\|[^|>\n]+\|?>|<[a-z_]+\|>)\s*$")


def _protocol_debris(content: str) -> bool:
    """True when write content is a fused call's DEBRIS: at least one protocol-tag line, and every
    other non-empty line a bare single token (the path the next call carried). Real file content —
    even code that mentions these tags inside string literals with normal multi-word lines — never
    classifies: one real line of prose or code defeats it."""
    lines = [ln for ln in (content or "").splitlines() if ln.strip()]
    if not lines:
        return False
    tags = [ln for ln in lines if _PROTOCOL_TAG_LINE.match(ln)]
    if not tags:
        return False
    return all(len(ln.split()) == 1 for ln in lines if ln not in tags)


def trim_fused_tail(content: str) -> str:
    """Real file content with a fused call's debris stuck to its END, cut back to the real content.

    `_protocol_debris` answers the all-or-nothing case — content that is NOTHING but protocol tags —
    and correctly says no when a genuine file has the tags appended to it. That is the expensive
    case. Walked on cycle 4 cell 22 (`feed-pipeline-java x nemotron-elastic`, 5% useful): the model
    omitted `</parameter>` and opened a second call in the same turn, so every `pom.xml` it sent
    ended

        </project>
        </function>
        </tool_call>
        <tool_call>
        <function=write_file>
        <parameter=path>
        src/main/java/pipeline/Importer.java

    cria refused it eight times as malformed XML at "line 34, column 1" — which is exactly where the
    junk began — and the model, unable to re-read its own rejected payload, re-derived the identical
    file by hand and was refused again. It escaped only by switching to `edit_file`, which then put a
    `<dependency>` block outside `<dependencies>` and left the project unreadable by Maven.

    cria already knows these sentinels: `massage._LEAK_DEBRIS` lists them as tokens that NEVER appear
    in legitimate prose, and `massage._bounded_xml_params` cuts them out of arguments cria itself
    parses. This is the same knowledge applied where a SERVER-parsed tool call delivered them instead.

    ONLY A TAIL, and only one made entirely of tags and bare tokens: a file whose real lines merely
    MENTION a tag (a leak-detector's own source, say) has multi-word lines all the way down and is
    returned untouched, which is the same distinction `_protocol_debris` already draws."""
    lines = (content or "").splitlines()
    cut = len(lines)
    saw_tag = False
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i]
        if not ln.strip():
            continue
        if _PROTOCOL_TAG_LINE.match(ln):
            saw_tag, cut = True, i     # the cut may only ever land ON a tag
            continue
        # A VALUE LINE IS SCANNED PAST but never becomes the cut. Both ends of the debris need this
        # and for opposite reasons: it trails the tags (the next call's argument, met first going
        # backwards), and it also precedes them in ordinary markup (`</project>`, `}`), where cutting
        # at it would eat the file. Only a tag marks where the junk starts.
        #
        # ANY value, not just a bare token. The single-token rule fitted the walked case, where the
        # fused second call was a `write_file` and its `path` is one word — and missed the same
        # failure when the second call is an `exec_command`, because `mvn -q compile` is three words
        # and the scan broke on it before it ever met a tag. Verified against the four captured
        # payloads from feed-pipeline-java x nemotron-elastic 1787436645: all four returned unchanged,
        # cria refused its own write four times as malformed XML pointing at `line 34: </function>`,
        # and the model could not see the payload it had sent.
        #
        # This is safe because `_PROTOCOL_TAG_LINE` matches only tokens that never appear in real
        # content — `</function>`, `<tool_call>`, `<parameter=…>` — so a file with no fused call has
        # no tag to find and comes back untouched however far the scan walks. The bound keeps it to
        # an argument's worth of lines rather than the whole file.
        if not saw_tag and (len(lines) - i) > _FUSED_TAIL_MAX_LINES:
            break
        continue
    if not saw_tag or cut == 0:
        return content          # nothing to cut, or the whole thing is debris (that is _protocol_debris)
    return "\n".join(lines[:cut]).rstrip("\n") + "\n"


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

# A REFUSED call did not run, so it must not report success. Every refusal cria lowers is a
# `printf`, and printf exits 0 — so the harness stamped `Process exited with code 0` directly above
# text saying "Nothing was run". Measured: 331 captured prompts carry that pair for the malformed-call
# refusal alone, and the same shape reaches the external-dir guard, the cria-home guard, the read-only
# spill guard and the repeat-search gate. A guard that reports success is the worst failure shape
# there is, and the contradiction sat inside a single tool result.
REFUSED_EXIT_CODE = 1


def _oversize_command(text: str) -> str:
    """A refusal for SIZE, which exits 0 — the target is fine, cria simply will not hand it over.

    Operator ruling, 2026-08-12: *"You must still use an exit code of 0 or the weak model will
    assume something like the file doesn't exist."* A non-zero exit on `ls` or `cat` means one thing
    to a small model — the path is not there — and it then goes looking for a directory it is
    standing in. That is a worse lie than the success-stamp the sibling owner exists to prevent,
    because it is about the WORLD rather than about the call.

    The distinction between the two owners is what was refused. :func:`_refusal_command` answers a
    call that was BLOCKED or malformed — it did not run and must not report success. This one
    answers a call that ran fine and produced more than fits: nothing failed, so nothing claims to
    have. The denied mark is carried either way, so cria's own readers still know no content came
    back."""
    return f"printf %s {_qbash(denial.mark(text))}"


def _refusal_command(text: str) -> str:
    """The one way cria lowers a refusal: MARK it as a call that did not run, print it, then exit
    non-zero. ONE owner — the five call sites each hand-rolled `printf %s …` and all five inherited
    printf's exit 0.

    The mark (:mod:`cria.denial`) is applied HERE, at the site that decides to refuse, because the
    exit code does not survive to the reader that needs it: a refusal comes back as a tool result
    whose text is the only thing a judge's action log carries, and ``represent_inbound`` strips the
    harness's ``Process exited with code`` envelope off read/nav results outright. Marking the text
    is what lets ``loop._work_log`` say the call never ran without matching a single word of it."""
    return f"printf %s {_qbash(denial.mark(text))}; exit {REFUSED_EXIT_CODE}"


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
# A per-write temp suffix keeps the write atomic (write temp, then mv over the target). The temp is
# removed on ANY failure: `os.replace` onto a directory raises, and the file used to survive — measured
# (run 0727-161325), 1,089 bytes of the model's code were left at
# `/home/jesse/src/<workspace>.cria-tmp`, a SIBLING of the workspace, because `Path("<ws>/.")`
# normalizes to `<ws>` and `str(p) + suffix` then lands one level UP. The dirguard had checked the
# MODEL's path (`<ws>/.`, legitimately inside); the temp path cria derived from it was never
# re-checked. A directory target is now refused before any temp exists, which removes the escape at
# its source; the cleanup covers every other way a write can fail.
_TMP_SUFFIX = ".tmp-partial"   # never carries the marker: a leftover is a filename the model can ls
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
    # {{SPILL_DIR}} is filled from the ONE owner of the name (webfetch.SPILL_DIR) rather than
    # spelled in the prompt: a model-facing path that drifts from the real one sends the coder
    # to a file that is not there.
    d = {k: prompts.fill(v, spill_dir=webfetch.SPILL_DIR) for k, v in prompts.load_map("tool_descs").items()}

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
        if is_shell_tool_name(name) and shell is None:
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
# ONE ext -> validator table, and it runs INSIDE the lowered heredoc, so it may use Python's own
# parsers in-process and must shell out for the rest.
#
# THE HOLE THIS CLOSES. It used to dispatch on .py/.pyi, .json and .toml and fall off the end for
# everything else, returning None — "no opinion". Both callers read None as "nothing to refuse", so
# for a .rb, .go, .java, .rs or .js file the validate-before-lower refusal branch was UNREACHABLE:
# cria would happily replace a parsing Ruby file with one that does not parse, and the edit path's
# would_break check was likewise always False. Measured across the six-language battery, where
# cria's own write path corrupted a pom.xml with nothing detecting it.
#
# cria already owns a per-extension syntax-command table 600 lines away in probediscovery
# (node --check, php -l, ruby -c). This is the same knowledge, needed in a place that cannot import
# it. Per-language entries are correct here — every language gets its equivalent check; the defect
# was the missing rows, not the table.
#
# UNKNOWN STAYS SAFE. A tool that is not installed, a timeout, or an extension with no parser all
# return None, which means "cria cannot judge this" and never refuses. The guard stays
# regression-only (#2): it may only refuse replacing a file that currently parses.
_VALIDATE_FN = r'''import shutil as _sh, subprocess as _sp, tempfile as _tf, os as _os
# NO literal braces anywhere in this source: it is prepended to the heredoc templates below, which
# are .format()ed, and a dict literal's braces read as format placeholders.
_EXT_CMD = dict([('.rb', ['ruby', '-c']), ('.js', ['node', '--check']),
                 ('.mjs', ['node', '--check']), ('.cjs', ['node', '--check']),
                 ('.php', ['php', '-l']), ('.go', ['gofmt', '-e'])])


def _v(path, raw):
    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
    except Exception:
        return None
    low = path.lower()
    _dot = low.rfind('.')
    ext = low[_dot:] if _dot >= 0 else ''
    try:
        if ext in ('.py', '.pyi'):
            compile(text, path, 'exec')
        elif ext == '.json':
            import json as _json; _json.loads(text)
        elif ext == '.xml':
            from xml.etree import ElementTree as _ET; _ET.fromstring(text)
        elif ext == '.toml':
            try:
                import tomllib as _t
            except ImportError:
                try:
                    import tomli as _t
                except ImportError:
                    return None
            _t.loads(text)
        elif ext in _EXT_CMD:
            _argv = _EXT_CMD[ext]
            if _sh.which(_argv[0]) is None:
                return None
            _fd, _tmp = _tf.mkstemp(suffix=ext)
            try:
                with _os.fdopen(_fd, 'w') as _fh:
                    _fh.write(text)
                _r = _sp.run(_argv + [_tmp], capture_output=True, text=True, timeout=20)
                if _r.returncode != 0:
                    _msg = ((_r.stderr or '') + (_r.stdout or '')).strip()
                    # THE TEMP PATH GOES, IT IS NOT REPLACED. This used to substitute the real
                    # absolute workspace path back in and THEN cut to `splitlines()[0][:200]`.
                    # `ruby -c` prints the path TWICE on line one, and a suite workspace path is 96
                    # characters, so 198 of the 200 were path: the coder was refused with the
                    # message `:36: s` and, unable to see what was wrong, discarded a complete
                    # five-change implementation it had just written. Measured and reproduced
                    # byte-exact. The cap was never the size the message needed; the substitution
                    # inflated the string four and a half times and the cap then cut the half that
                    # carried the diagnosis.
                    #
                    # The coder already knows which file it just tried to write, so the path is the
                    # one part of this that carries no information. Stripping it leaves the
                    # coordinate and the text — and the checker's own caret line, which is two
                    # thirds of what makes a syntax error actionable and which `splitlines()[0]`
                    # threw away before the cap even ran (#5: per-line caps and character budgets
                    # are truncation; this is tool output cria itself ran).
                    _base = _os.path.basename(path)
                    _msg = _msg.replace(_tmp + ':', _base + ':').replace(_tmp, _base)
                    _msg = _msg.replace(_base + ': ' + _base + ':', _base + ':')
                    return _msg if _msg else 'does not parse'
            except Exception:
                return None
            finally:
                try:
                    _os.unlink(_tmp)
                except OSError:
                    pass
    except Exception as _e:
        return str(_e)
    return None


def _at(raw, msg):
    # SHOW THE LINE THE COORDINATE POINTS AT. The refusal used to carry only the parser's message —
    # "not well-formed (invalid token): line 34, column 1" — into content the coder cannot re-read
    # (cria elides a rejected payload). A line number into an invisible document points at nothing.
    #
    # Walked on cycle 4 cell 22 (`feed-pipeline-java x nemotron-elastic`, 5% useful): eight refusals
    # of pom.xml, every one at line 34, and line 34 of the content the model sent was `</function>`
    # — a tool-call terminator that had been swallowed into the file body. Across all eight the
    # model's reasoning never once mentions line 34; at call 0016 it re-derived the identical pom by
    # hand and was refused again. The sibling EDIT path has done this right for months: it quotes the
    # file's real text around the divergence.
    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
        import re as _re
        # BOTH SHAPES A CHECKER EMITS. This matched `line\s+(\d+)` only — Python's compile() and an
        # XML parser say "line 34, column 1", which is the run this helper was written for. Ruby
        # says `rates.rb:36:`, and so do `node --check`, `php -l` and `gofmt -e`. So the assist
        # abstained SILENTLY on four of the six languages the validator beside it covers, which is
        # worse than absent: it looks present. A matcher keyed to one tool's phrasing is inert on
        # every other tool (#20).
        # `node --check` prints `f.js:3` with NO trailing colon, `gofmt -e` prints `f.go:3:5`, ruby
        # and php print `f.rb:36:`. Requiring a filename-shaped token before the number keeps a port
        # or a timestamp in the message from being read as a line.
        m = (_re.search(r'line\s+(\d+)', msg or '')
             or _re.search(r'[\w./\-]+\.\w+:(\d+)\b', msg or ''))
        if not m:
            return ''
        n = int(m.group(1))
        lines = text.splitlines()
        if not (1 <= n <= len(lines)):
            return ''
        # The line goes whole — a cap here cuts exactly the long line most likely to be the fault.
        return ' Line %d of the content you sent is: %s' % (n, lines[n - 1].strip())
    except Exception:
        return ''
'''

# Byte-exact atomic write (python heredoc — content rides in the source on stdin, no arg-size limit /
# no chunking), with validate-before-write: refuse only when this would replace a currently-VALID file
# with content that does not parse. A new file or an already-broken file writes freely.
_WRITE_PY = r'''import base64,sys,pathlib,os
p=pathlib.Path(base64.b64decode('{path}').decode())
raw=base64.b64decode('{content}')
_after=_v(str(p),raw)
if _after is not None and p.exists() and _v(str(p),p.read_bytes()) is None:
    sys.exit(base64.b64decode('{refused}').decode().replace('%%NAME%%',p.name).replace('%%AFTER%%',_after)+_at(raw,_after))
if p.is_dir():
    sys.exit(base64.b64decode('{isdir}').decode().replace('%%NAME%%',str(p)))
_bp=next((a for a in p.parents if a.exists()), None)
if _bp is not None and not _bp.is_dir():
    sys.exit(base64.b64decode('{parentfile}').decode().replace('%%NAME%%',str(p)).replace('%%BLOCK%%',str(_bp)))
p.parent.mkdir(parents=True,exist_ok=True)
tmp=str(p)+'{suffix}'
try:
    pathlib.Path(tmp).write_bytes(raw)
    os.replace(tmp,str(p))
except BaseException:
    try: os.unlink(tmp)
    except OSError: pass
    raise
print('{wrote}')
'''


def _write_command(path: str, content: str) -> str:
    """Byte-exact atomic write via a python heredoc: validate-before-write (a broken write over a valid
    file is refused), then write to a temp and os.replace over the target so a partial write never
    leaves a half-written file. The content rides in the heredoc, so there is nothing to escape and
    no chunking.

    THERE IS STILL A CEILING, and it is not the heredoc's. The harness runs `bash -lc "<command>"`,
    so the whole command is ONE argv string and Linux caps a single argument at MAX_ARG_STRLEN =
    128 KiB. A heredoc does not get around that — its bytes are in the same string. A write past
    :data:`COMMAND_ARG_BUDGET` therefore dies in the harness with "Argument list too long (os error
    7)" before any of this runs. Not observed from a model yet (see docs/open-threads.md); the
    fetch-spill path, where it WAS observed, states its own bound and cuts with disclosure."""
    py = (_VALIDATE_FN + _WRITE_PY).format(path=_b64(path), content=_b64(content),
                                           suffix=_TMP_SUFFIX, wrote=_WROTE,
                                           # Both are REFUSALS decided inside the lowered heredoc —
                                           # validate-before-lower rejected the content, or the path
                                           # is a directory. Nothing was written either way, so both
                                           # carry the did-not-run mark from the site that authors them.
                                           refused=_b64(denial.mark(prompts.load("write_refused"))),
                                           isdir=_b64(denial.mark(prompts.load("write_isdir"))),
                                           # Walked on nemotron poff 1785946072: a mis-split fused
                                           # call planted a junk FILE named `tests`; every later
                                           # write below it died in this heredoc's mkdir with a raw
                                           # FileExistsError traceback — cause invisible, three
                                           # identical retries, tests never landed. Name the block.
                                           parentfile=_b64(denial.mark(prompts.load("write_parent_is_file"))))
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
    _b=lambda d: base64.b64encode(json.dumps(d).encode()).decode()
    _r=_b(kw)
    if len('{editfail}')+len(_r)>{cap}:
        kw.pop('current',None); _r=_b(kw)
    sys.exit('{editfail}'+_r)
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
        # The token match starts at the first NON-WHITESPACE character, so the file's leading indent
        # sits in the prefix. When old_string starts flush (coder gave bare statements), that is the
        # point: the file's indent survives and a bare new_string lands after it. But when old_string
        # CARRIES its own leading indent, new_string carries the same indent — and splicing after the
        # file's indent doubles it. Walked on mellum2 1786196176 call 0190: a correct side_effect fix
        # (12-space old, 12-space new, off-disk only by a blank line the flexible match forgives)
        # became a 24-space line, the syntax guard caught cria's own wreckage, and the report told
        # the coder to "Fix new_string" — for an edit that was right. The same fix, resubmitted with
        # a one-line old_string, applied verbatim at 0215, 120 calls later. So: old_string indented →
        # consume the file's indent back to line start and let new_string supply its own.
        # ...and only when new_string carries indentation of its OWN to replace it with. Gating on
        # old_string alone regressed the sloppy case the flexible matcher exists for: indented old +
        # FLUSH new used to land after the file's indent (valid) and would now land at column 0
        # (broken, then refused as would_break). Both sides indented is the 0190 shape and the only
        # one where the file's indent is redundant.
        m=ms[0]; a=m.start()
        if old[:1] in ' \t' and new[:1] in ' \t':
            ls=s.rfind(chr(10),0,a)+1
            if not s[ls:a].strip():
                a=ls
        _w(s[:a]+new+s[m.end():])
    if len(ms)>1:
        _fail('multi_flex',n=len(ms))
oldl=old.split(chr(10))
o0=next((j for j,l in enumerate(oldl) if l.strip()),0)
key=oldl[o0].strip() if oldl else ''
new_first=next((l.strip() for l in new.split(chr(10)) if l.strip()),'')
lines=s.split(chr(10)); ctx=''; close=''; dline=0
if key:
    for i,l in enumerate(lines):
        if key[:40] in l:
            # Window the DIVERGENCE, not the head. Anchoring on the first line of old_string put the
            # 6-line window over the text that already MATCHED — so a 10-line old_string that differs
            # at line 7 got back six lines it had verbatim, under "The file actually reads", and the
            # coder resubmitted the same wrong old_string. Walk forward to the first line that
            # actually differs and centre there.
            d=i
            for k in range(o0,len(oldl)):
                fi=i+k-o0
                if fi>=len(lines) or lines[fi]!=oldl[k]:
                    d=min(fi,len(lines)-1); break
            ctx=chr(10).join(lines[max(0,d-2):d+4]); dline=d+1; break
    if not ctx:  # no substring anchor — find the file line the old_string is CLOSEST to (a near-miss)
        cm=difflib.get_close_matches(key, [l.strip() for l in lines if l.strip()], n=1, cutoff=0.75)
        if cm:
            close=cm[0]
if ctx:
    _fail('anchor',anchor=ctx,line=dline)
elif close and new_first and new_first in close:
    _fail('phantom',anchor=close)   # already-correct line the model misremembers
elif close:
    _fail('close',anchor=close)     # near-miss: a mistyped token
else:
    _fail('no_anchor')
'''


def _edit_command(path: str, old: str, new: str) -> str:
    py = (_VALIDATE_FN + _EDIT_PY).format(path=_b64(path), old=_b64(old), new=_b64(new),
                                          wrote=_WROTE, editfail=editrecovery.EDITFAIL,
                                          cap=content_reduce_mod.INLINE_RESULT_MAX_BYTES)
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


# A whole read bigger than this is steered to grep / a line range instead of cat'd — a raw cat of a
# big file is middle-cut by the harness (Codex kept only a few KB of a 96 KB spec, eating the middle
# where the endpoints were), a silent lie the model then acts on. THE bound is the shared inline-result
# bound (content_reduce.INLINE_RESULT_MAX_BYTES): the old local 12,000 sat exactly ON codex-local's
# 10,000-byte×1.2 history budget, so borderline reads (~12–13 KB observed kept-sizes in the capture
# corpus) still got holed in later prompts. The size-check is lowered INSIDE the read_file call, so
# the sentinel swap re-presents it as a plain read_file — the model never sees the `wc`/`if` plumbing.
READ_INLINE_MAX = content_reduce_mod.INLINE_RESULT_MAX_BYTES


def _ranged_read(q: str, path: str, sed_end: str, start: int) -> str:
    """A ranged read (``sed -n 'start,END p'``) with the SAME two guards a whole read needs:
    * SIZE — a range over READ_INLINE_MAX is not handed back; the coder is told how to ask a
      smaller question instead. Observed live: a big range was cut at ~20707 tokens and the model
      then read line '20707' — the truncation count mistaken for a line number.

      WHAT THE REFUSAL SAYS ABOUT ITSELF. It used to say "the HARNESS would truncate it mid-way".
      READ_INLINE_MAX is 9,000 bytes and the observed cut was ~20,707 tokens — roughly nine times
      higher — so at the threshold where this actually fires, nothing would have been truncated by
      anyone. That is an internal limit stated as a fact about the world, which rule 5b names in
      those words, and it is the same defect `_spill_read_command` was fixed for one function over:
      "cria says it about its OWN read guard, which is a claim about cria dressed as a claim about
      the world". The refusal stands — cria genuinely will not return that much in one piece — so it
      now says THAT, and the routes it offers are unchanged and still true.
    * PAST-EOF — a start beyond the file is a SILENT EMPTY the model crawls forever; say the length.
    An in-range, in-size read returns exactly its content."""
    # Through an owner, not a hand-rolled printf — and specifically the SIZE owner, which exits 0.
    # These two guards were once switched to REFUSED_EXIT_CODE alongside the blocked-call refusals,
    # and that was wrong for them: a non-zero exit on a read means one thing to a small model, that
    # the path is not there, and it goes hunting for a file it is holding. The call did not fail —
    # cria declined to hand over the bytes — so nothing claims it failed. The denied mark still
    # rides, so cria's own readers know no content came back (operator ruling, 2026-08-12).
    steer = _oversize_command(prompts.render("large_range_steer", path=str(path)))
    return (
        # awk NR (not `wc -l`) so a final line with no trailing newline still counts — else a 1-line
        # file reads as 0 lines and a valid `start_line: 1` falsely trips the past-EOF branch.
        # A MISSING FILE IS NOT AN EMPTY ONE. `awk` on a nonexistent path prints nothing, `|| echo 0`
        # makes that a zero, and the past-EOF branch then reports a file that does not exist as one
        # with no lines in it. Walked on ada-handles_fabliq_codex_pon_1785721353 (calls 0093-0096,
        # 0085-0088, 0263, 0268): the coder guessed a path, cria answered "has 0 lines; line 1 is past
        # the end of the file", and its reasoning recorded the damage — "the file was empty or
        # couldn't be found". The UNRANGED read of that same path says the file is not there, so cria
        # held the true answer and served the false one. Ask the filesystem first.
        #
        # Through the SAME owner as the unranged read (_read_failure_branches), not a hand-rolled
        # printf of bash's wording. Unmarked error text is indistinguishable from the file's contents
        # to everything downstream: the read ledger counted exactly this shape as "261 chars read
        # from disk" for a file nobody opened. One owner, one answer, whichever read was asked for.
        f"{_read_failure_branches(q, path)}"
        f'__n=$(awk \'END{{print NR}}\' {q} 2>/dev/null || echo 0); '
        f'if [ {start} -gt "$__n" ]; then '
        f'printf "(no lines in that range — %s has %s lines; line %s is past the end of the file)\\n" {q} "$__n" {start}; '
        # NUMBER THE LINES. The crew's read_file has always numbered them (verifytools: `f"{i}: {line}"`)
        # and the coder's never did — the same tool name, two different views, and only the model that
        # has to EDIT by line number got the one without them. Walked on
        # ada-handles_mellum2_codex_poff_1785693138: the coder asked for lines 55-68 to see the line a
        # check flagged at 63, got the text naked, counted from the top of the block, and burned 8,234
        # reasoning tokens insisting a valid f-string was valid — then took three more calls to find
        # one line. Numbering is why the crew never has that problem.
        f'else __s=$(sed -n \'{sed_end}p\' {q} | awk -v s={start} \'{{printf "%d: %s\\n", s+NR-1, $0}}\'); '
        f'if [ "$(printf %s "$__s" | wc -c)" -gt {READ_INLINE_MAX} ]; then {steer}; '
        f'else printf \'%s\\n\' "$__s"; fi; fi'
    )


def _spill_read_command(path: str) -> str:
    """A WHOLE read of a file in the read-only spill scratch: hand back the file when it fits, and
    refuse only when it genuinely does not.

    This branch used to refuse EVERY whole read of a spilled file, at any size, with a message that
    says "reading it whole gets truncated, so you would miss the middle". For a file under
    :data:`READ_INLINE_MAX` that sentence is false — nothing would have been truncated — and cria
    says it about its OWN read guard, which is a claim about cria dressed as a claim about the world
    (rule 5b). Measured over the 96 captured runs (``suite/replay_logic.py --check spill-read-small``):
    FIVE distinct spilled files were refused a whole read while being 6630–8408 bytes, across 5 runs,
    every one of them saved SEARCH RESULTS. Search results are the worst case: a shell pipeline writes
    them, so cria never holds them parsed and there is no outline to carry — "grep it for what you
    need" was the entire answer, about a file the coder had no way to see the shape of.

    The size test lives in the LOWERED COMMAND, not in an in-process ``stat``, for the same reason
    :func:`_read_command` puts it there: the file is on the harness's filesystem at the moment of the
    read, and a size cria measured a turn earlier is a remembered flag, not the world.

    A MISSING FILE IS NOT AN EMPTY ONE — the same guard :func:`_ranged_read` carries, for the same
    reason. ``wc -c`` on a path that is not there yields 0, which is not over the limit, so the read
    fell through to ``cat``, whose error goes to STDERR: the coder saw an empty result with no
    explanation and crawled the path forever. Ask the filesystem first and answer on stdout.

    DIRECTION OF FAILURE: strictly toward the coder having MORE real content. It changes no verdict
    path, advances no step, and the oversized case is byte-identical to before (same steer, same
    outline, same refusal exit code)."""
    q = _qbash(path)
    # The outline carries the doc's own routes/keys — the SIBLING of the web_fetch spill refusal, and
    # the same trap: cria refuses the whole read of a doc it is itself holding parsed, and answers
    # with "grep it for what you need", which cannot be acted on before you know what the doc
    # contains. Measured across the 123 captured sessions: 1,931 coder calls carried this steer and
    # 500 of them (26%) had no outline anywhere in the prompt. "" when the doc is not cached
    # (rule 5b — no outline is invented); the steer's own instructions stand without it. The EDIT
    # refusal names no content, so it takes no outline — which is why it renders without one above.
    fmt = webfetch.format_for_spill_path(path)
    # …AND HOW BIG IT IS. "grep it, or read a line range" is unactionable without the document's
    # extent: measured twice on `shipping-rates-rb x ternary-bonsai`, the coder asked once, was
    # refused, and never opened the file again — the file that defines the method it then guessed
    # wrong. See webfetch.spill_reading_hint; "" when cria holds no such doc.
    extent = webfetch.spill_reading_hint(path, READ_INLINE_MAX)
    fmt_clause = f" It is {fmt}." if fmt else ""
    if webfetch.page_not_file_for_spill_path(path):
        fmt_clause += " " + prompts.load_map("webfetch_guards")["spill_is_the_page_not_the_file"]
    steer = prompts.render("spill_read_steer", path=path,
                           format=fmt_clause,
                           extent=(f" {extent}\n" if extent else ""),
                           outline=webfetch.outline_for_spill_path(path))
    # The refuse branch goes through the ONE refusal owner, so it keeps this guard's non-zero exit.
    # So does the not-there branch now: it used to printf bash's own phrasing, which exits non-zero
    # but carries NO denied mark — so the ledger counted the error text as the file's contents. Same
    # owner, same mark, one statement of what happened (see _read_failure_branches).
    return (f"{_read_failure_branches(q, path)}"
            f'if [ "$(wc -c < {q} 2>/dev/null || echo 0)" -gt {READ_INLINE_MAX} ]; '
            f'then {_oversize_command(steer)}; else cat {q}; fi')


def _read_failure_branches(q: str, path: str) -> str:
    """The guards that must run before any `cat`: a read that CANNOT return bytes says so in cria's
    own voice, through the one refusal owner, so it carries the denied mark and a non-zero exit.

    A bare `cat <missing>` hands the model bash's own error as the tool RESULT — text that is
    non-empty and unmarked, so everything downstream reads it as content. `research.files_read`
    accepts a read when the body is non-empty and not a denial, and its docstring already states the
    intended rule: *an attempted read is not a read*. It was right; the input was lying to it. The
    ledger recorded "Importer.java — 261 chars read from disk" for a 6,783-byte file at a path that
    holds only directories, and a judge ruled the reading step DONE on a file nobody opened.

    Fixed HERE, where cria composes the command, and not in the ledger: one statement of what
    happened, in cria's own voice (#5b), and every reader downstream inherits it. The ledger needs
    no change at all — the denied mark is already what it tests."""
    msg = prompts.load_map("read_failed")
    return (f'if [ -d {q} ]; then {_refusal_command(prompts.fill(msg["is_directory"], path=path))}; fi; '
            f'if [ ! -e {q} ]; then {_refusal_command(prompts.fill(msg["missing"], path=path))}; fi; '
            f'if [ ! -r {q} ]; then {_refusal_command(prompts.fill(msg["unreadable"], path=path))}; fi; ')


def _read_command(args: dict) -> str | None:
    path = _tool_path(args)
    if not path:
        return None
    q = _qbash(path)
    start, end = args.get("start_line"), args.get("end_line")
    # An INVERTED range is its own defect and gets its own answer. The old flow dropped the
    # end_line silently (the `end >= start` guard below fails, so the start-only branch read
    # start→EOF) and then refused THAT as "too large — narrow your window" — about a request the
    # coder believed was already narrow. Walked on run 1785893473 call 0018 (start 1041, end 358);
    # 100 inverted ranges across 3 captured sessions. Name the real cause instead.
    if isinstance(start, int) and start > 0 and isinstance(end, int) and 0 < end < start:
        return _refusal_command(prompts.render("inverted_range", path=str(path),
                                               start=start, end=end))
    if isinstance(start, int) and start > 0 and isinstance(end, int) and end >= start:
        return _ranged_read(q, str(path), f"{start},{end}", start)
    if isinstance(start, int) and start > 0:          # start-only → from the line to EOF (was ignored)
        return _ranged_read(q, str(path), f"{start},$", start)
    # Whole read: size-check first; a file over the limit is not handed back, so the coder gets a
    # grep/line-range pointer instead of a silently-cut cat. (Small files cat exactly as before.)
    # The pointer states the refusal, not a prediction about what some other layer would have done
    # with the bytes — see the SIZE note in `_ranged_read`.
    # Through the ONE refusal owner (see _ranged_read): the `cat` never runs, so this must not
    # report success.
    steer = _oversize_command(prompts.render("large_read_steer", path=str(path)))
    return (f"{_read_failure_branches(q, str(path))}"
            f'if [ "$(wc -c < {q} 2>/dev/null || echo 0)" -gt {READ_INLINE_MAX} ]; '
            f"then {steer}; else cat {q}; fi")


def _list_command(args: dict) -> str:
    path = args.get("path") or args.get("dir") or args.get("directory") or "."
    q = _qbash(path)
    # Same principle as the read guard: a huge directory (node_modules, a data dir) would be SILENTLY
    # truncated by the harness's output cap. Cap the listing at READ_INLINE_MAX bytes and DISCLOSE the
    # total entry count so a cut isn't mistaken for the whole directory.
    # NO CAP-AND-DISCLOSE. A clipped listing is still a partial view the model reasons over as if it
    # were the directory (operator ruling: never elide, never truncate — refuse and make it narrow).
    # The refusal is composed per call because it names the entry count, which only the shell knows.
    refusal = denial.mark(
        prompts.load_map("oversize_refusal")["list"].replace("{{PATH}}", str(path)))
    head, _, tail = refusal.partition("{{ENTRIES}}")
    return (f'__o=$(ls -la {q} 2>&1); '
            f'if [ "$(printf %s "$__o" | wc -c)" -gt {READ_INLINE_MAX} ]; then '
            f'printf "%s%s%s\\n" {_qbash(head)} "$(ls -1A {q} 2>/dev/null | wc -l | tr -cd 0-9)" {_qbash(tail)}; '
            f"else printf '%s\\n' \"$__o\"; fi")


def _fetch_command(args: dict, session: str | None = None, workspace_root: str | None = None) -> str | None:
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
    if raw:                       # raw source: the whole markup, not a PAGED view — `find` is honored
        # `find` used to be nulled here too, which made webfetch's own raw-honors-find fix unreachable:
        # this is the only caller of fetch_nav from the model path, so the model's narrowing request
        # died here before fetch_nav could act on it — and a nulled find also forces the oversized-spill
        # branch below, reproducing the "saved N chars, go grep it" reply that fix set out to kill.
        cursor = None
    result = webfetch.fetch_nav(str(url), find=find, cursor=cursor, session=session, raw=raw,
                                workspace_root=workspace_root)
    # A PLAIN fetch (no find/cursor) of an oversized doc: spill the full doc to ./tmp and hand back a
    # short pointer instead of a low-signal page-1. find=/cursor= navigation returns its slice as usual.
    # …but only the FIRST time. Once cria has written the doc to the workspace that file outlives the
    # conversation, so a later plain re-fetch is answered with the file's name (fetch_nav's refusal,
    # already in `result`) instead of copying the same document over itself. Measured (run
    # 0727-104845): a 154KB docs page re-fetched NINETEEN times after the harness compacted the first
    # result away — each one re-spilling and burning a turn.
    if find is None and cursor is None and not webfetch.already_spilled(session, str(url), workspace_root):
        spill = webfetch.oversized_spill(str(url))
        if spill:
            _status, target, content, msg = spill
            # Record WHERE it landed: the refusal built on this ledger names that path to the model,
            # and the same session key can be reused by a later run in a DIFFERENT workspace.
            written = os.path.join(workspace_root, target.lstrip("./")) if workspace_root else ""
            webfetch.note_fetch_spill(session, str(url), written)
            return _spill_command(target, content, msg)
    # A repeat-gate REFUSAL comes back from fetch_nav as ordinary text, and this printf gave it
    # printf's exit 0 — the "a refused call must not report success" contradiction the module header
    # documents, at the one site that still had it. Which results are refusals is webfetch's own
    # decision, recorded on the text at the key it rendered (denial), never re-derived from wording:
    # a real 404 page is a RESULT and still exits 0 here.
    if denial.is_denied(result):
        return _refusal_command(result)
    return f"printf %s {_qbash(result)}"



# What one composed command can carry. The harness runs `bash -lc "<command>"`, so the whole command
# is ONE argv string, and Linux caps a single argument at MAX_ARG_STRLEN = 32 pages = 128 KiB. Nothing
# inside the command can get around that — a heredoc, chunked printfs, base64: they are all still
# bytes in that one string. Codex reports the overrun as "Argument list too long (os error 7)" and
# the whole exec fails, so the doc never lands at all.
# MEASURED, NOT DERIVED FROM THE KERNEL CAP. `MAX_ARG_STRLEN` is 128 KiB, and 120 KiB left headroom
# on paper — but the harness wraps what cria composes in `/bin/bash -lc "<command>"`, so the shell
# quoting, the ⟦ctx:tool⟧ sentinel and the harness's own framing all ride on top, and its effective
# limit is lower than the kernel's. Across the captured rollouts: seven spill execs were REFUSED, the
# smallest at 123,848 bytes on the wire.
#
# THE COST IS ASYMMETRIC, so the budget is. Overshooting does not merely fail: the harness echoes the
# WHOLE refused command back as the tool result, so ~10 KB of raw base64 lands in the model's context
# per attempt. Walked on handles-cli-node x nemotron-elastic 1787273429 — the spill was refused, cria
# recorded it as written anyway, the model re-fetched seven times chasing the phantom file, and by the
# final compaction that base64 was 68% of a 92,261-character prompt. The context floor could drop
# nothing (two composed messages), the model server answered HTTP 400, and the run ended early.
#
# Undershooting costs a disclosed cut (see SPILL_CONTENT_MAX and prompts/spill_cut.txt). Half the
# kernel cap sits far below every observed refusal and still carries a substantial spec.
COMMAND_ARG_BUDGET = content_reduce_mod.COMMAND_ARG_BUDGET
# base64 is 4 bytes per 3, and the rest of the command (paths, the pointer message, the markers)
# needs room too.
SPILL_CONTENT_MAX = content_reduce_mod.SPILL_CONTENT_MAX


def _spill_command(target: str, content: str, msg: str) -> str:
    """Land ``content`` at ``target`` (in the workspace spill dir), then print the model-facing pointer
    message — the harness runs this and records the message as the tool result. The sentinel
    re-presents the whole command as web_fetch, so the model never sees the plumbing.

    THE DOC TRAVELS IN THE COMMAND. It used to be staged in cria's OWN directory and lowered as a
    small ``cp``, to keep a large spec out of the argv. That works only while cria and the harness
    share a filesystem: off a shared box the ``cp`` copies a file that is not there, the exec
    "succeeds", and the spill silently produces an empty doc — then cria tells the model to go read
    it. An empty doc under a pointer is worse than no doc at all.

    A doc past what one command can carry is CUT, and the cut is stated — in the file and in the
    pointer message. cria does not truncate what the model reads without saying so (#5b), and it has
    no way to deliver more than this in one turn: it cannot write to the harness's disk except
    through a command, and a command is one argv string."""
    tdir = os.path.dirname(target) or "."
    body, note = content, ""
    if len(content.encode("utf-8", "replace")) > SPILL_CONTENT_MAX:
        body = content.encode("utf-8", "replace")[:SPILL_CONTENT_MAX].decode("utf-8", "ignore")
        note = prompts.fill(prompts.load("spill_cut"),
                            kept=f"{len(body):,}", total=f"{len(content):,}")
        body += "\n\n" + note
    return (f"mkdir -p {_qbash(tdir)} && base64 -d > {_qbash(target)} <<'__CRIA_SPILL__'\n"
            f"{_b64_wrapped(body)}\n__CRIA_SPILL__\n"
            f"printf %s {_qbash(msg + (chr(10) + note if note else ''))}")


def _b64_wrapped(s: str, width: int = 76) -> str:
    """base64 of ``s``, line-wrapped. `base64 -d` accepts one long line on GNU coreutils and rejects
    it on some BSD builds; wrapping is what every base64 encoder emits by default and works on
    both."""
    raw = _b64(s)
    return "\n".join(raw[i:i + width] for i in range(0, len(raw), width))


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


def _respill_command(command: str) -> str:
    """Root-absolute spill references inside a RAW command string, rewritten to the real
    workspace-relative form — the command-string twin of :func:`_spill_relpath`. ``read_file`` on
    ``/tmp/read-only/x`` was silently redirected while the SAME string in a grep/cp was dirguard-
    refused; shown both, the model learned "the sandbox blocks this file" and burned ~130 calls on
    it (run 0729-gemma4 pon2; ~25 more in poff-C1). cria controls the spill dir name, so the
    rewrite is exact — only a token that STARTS at the filesystem root is touched."""
    tail = webfetch.SPILL_DIR.lstrip("./")
    return re.sub(r"(?<![\w.])/" + re.escape(tail) + r"(?=[/\s\"']|$)", "./" + tail, command)


def _pyq(s: str) -> str:
    """A Python string literal safe to embed inside the single-quoted `python3 -c '...'` body.

    json.dumps handles the Python side — backslashes, newlines, double quotes. It does NOT escape an
    APOSTROPHE, and an apostrophe is the one character that ends the shell's quoting: a note reading
    "each page\u0027s description" closed the `-c '` early and bash died on the rest of the line. So
    every `\u0027` is re-encoded as a unicode escape, which Python decodes back to an apostrophe and
    the shell never sees at all."""
    import json as _json
    return _json.dumps(s).replace("'", "\\u0027")


def _search_command(args: dict, brave_key: str) -> str:
    """Brave web search lowered to a curl — endpoint, %-encoded query, and headers come from the
    shared `brave` module (same request the planner's in-process search builds), then parsed to
    compact "title / url / description" lines the model can pair with web_fetch. Requests Brave's
    per-request maximum and prints EVERY returned result (no display slice) with a total-count header
    so the authoritative page — which may rank 9th+ — reaches the model and it knows how many exist."""
    query = str(args.get("query") or "")
    # Composed before the parse below, which needs both: the spill path to write, and the pointer to
    # print when the brief listing does not fit inline.
    target, msg = webfetch.search_spill(query)
    # NAME THE FILE. The note used to end "in the file named above" on the INLINE path, where
    # nothing above names a file — the filename only appears in the spill branch, which is the
    # branch not taken. A pointer to a file cria never named is a false fact in cria's own voice
    # (#5b); seen in three cells of cycle 1. The target is known here, so it goes in the sentence.
    # THE POINTER MUST CARRY ITS QUERY. cria's read-judge finds the query for a saved result file by
    # matching this sentence, and the inline branch's version did not contain one — so the judge was
    # asked to rule on a search whose query it was told was "(none)", and ruled it off-target. Walked
    # on shipping-rates-rb x nemotron-elastic 1787294328: the deleted file held
    # `ISO3166::Country#in_eu?`, the exact predicate that task needed, and the run scored 0/5. Both
    # pointers now say the same sentence, so one regex reads both (#23).
    inline_note = prompts.fill(prompts.load("search_inline_note"), target=target, query=query)
    url = brave.query_url(query, count=_SEARCH_MAX_RESULTS)
    header_flags = " ".join(f"-H {_qbash(f'{k}: {v}')}" for k, v in brave.headers(brave_key).items())
    # `e`: a Brave ERROR body (401 invalid key, 422, 429 rate-limited) is valid JSON, so json.load
    # succeeds, `.get("web")` is None, and this used to print the literal "no results" — telling the
    # model the web holds nothing for its query when the API had in fact refused the request, and its
    # own code/detail was right there in the same body. The model then concludes the source doesn't
    # exist and starts guessing. Surface the API's own error text instead; only a genuinely empty
    # result set says "no results".
    # TITLES AND LINKS ARE THE ANSWER; DESCRIPTIONS ARE THE NOISE. Every search was spilled to disk
    # whatever its size and the model got a pointer, and the model did not open the file. Measured,
    # nemotron-elastic/go: the coder said "Ok, I'm stuck. Let's search for a decimal library", the
    # spill file's fourth line read "decimal package - github.com/shopspring/decimal - Go Packages",
    # and the go.mod it shipped required `github.com/elliott/decimal v1.6.0`. A package that does not
    # exist. Zero spill reads across 124 calls in that cell.
    #
    # This function's own comment named the DESCRIPTIONS as the snippet poison, which is true and is
    # the whole special case: titles and links are short, and they are exactly the fact a model needs
    # when it is choosing a dependency. So search now obeys the size rule cria already owns for
    # command output — inline when it fits, spill when it does not — instead of spilling always.
    # The full results with descriptions are written to the spill file either way, so the grep route
    # and the ledger entry are unchanged.
    parse = (r"""python3 -c 'import sys,json,os"""
             r""";d=json.load(sys.stdin);r=(d.get("web") or {}).get("results") or []"""
             r""";e=d.get("error") or d.get("message")"""
             r""";T=""" + _pyq(target) +
             r""";full="\n".join("%s\n  %s\n  %s"%(x.get("title",""),x.get("url",""),x.get("description","")) for x in r)"""
             r""";os.makedirs(os.path.dirname(T) or ".",exist_ok=True)"""
             r""";r and open(T,"w").write(("%d results:\n"%len(r))+full)"""
             r""";brief=("%d results:\n"%len(r))+"\n".join("%s\n  %s"%(x.get("title",""),x.get("url","")) for x in r)+"\n"+""" + _pyq(inline_note) +
             r""";print(brief if len(brief.encode())<=""" + str(content_reduce_mod.INLINE_RESULT_MAX_BYTES) +
             r""" else """ + _pyq(msg) + r""") if r else print("search API error: "+json.dumps(e) if e else "no results")'""")
    # Save the (noisy) results to the read-only spill dir and hand back a grep/line-read pointer, instead
    # of inlining snippet poison. The lowered command carries the web_search sentinel (translate_outbound),
    # so re-presentation swaps it back to web_search — the model never sees this curl/tee plumbing.
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
    # The parse writes the spill file itself now (it decides what to print based on size), so this is
    # a plain pipeline rather than a redirect-then-announce.
    return (f"mkdir -p {_qbash(tdir)} && "
            f"curl -sL --max-time {_FETCH_TIMEOUT_S} {header_flags} {_qbash(url)} | {parse} "
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
    if is_shell_tool_name(name):  # the harness's raw shell → heuristic path/verb scan
        command = _command_of(fn.get("arguments"))
        # cria's own composed command → trust. ANCHORED, not a substring scan anywhere in the text: a
        # model-authored command that merely mentions either literal used to inherit cria's trust and
        # skip the guard entirely. cria always writes the sentinel as the FIRST line (`# ⟦ctx:tool⟧<b64>`)
        # and always opens the gate script with `cd <workspace> || exit 97` followed by the section
        # echo — so requiring the marker in the first two lines authenticates the shape cria emits
        # rather than any text containing the token.
        head = "\n".join(command.lstrip().splitlines()[:2])
        if head.startswith("# " + _SENTINEL) or (head.startswith("cd ") and "___CRIA_GATE_" in head):
            return None
        return dirguard.command_refusal(command, level, workspace)
    return None


# Lowered tools whose own result is ONE bounded line, so appending the workspace survey to them
# cannot push the model's own content past the harness's output cap. Reads, fetches and searches
# are deliberately absent — see the ride-along note in translate_outbound.
_SURVEYABLE = _WRITE_NAMES | _EDIT_NAMES | _LIST_NAMES

# How many surveyable calls pass between surveys once the view is populated. The tree is re-walked
# on the harness's side each time, so this is a cost on the CODER's box, not cria's; four is often
# enough to see the file the coder wrote two turns ago without re-listing the repo every turn.
SURVEY_EVERY = 4
_SURVEY_SEQ: dict[str, int] = {}


def _litter_leg(workspace_root: str | None) -> str:
    """The queued gate-litter removal, or "". One line, so the gate keeps owning WHAT is litter and
    this only asks whether anything is waiting to go out."""
    if not workspace_root:
        return ""
    from .probegate import litter_removal_command
    return litter_removal_command(workspace_root)


def _survey_due(session: str | None, name: str) -> bool:
    """Whether this lowered call should carry the workspace survey.

    ALWAYS when cria still knows nothing about the workspace, or when a reader asked a question
    the view could not answer (a file body, a program on the coder's PATH) — those are real
    demand, and leaving them unanswered is what makes a mechanism silently stop reaching what it
    judges (#11b). Otherwise every SURVEY_EVERY-th call, which keeps the listing current without
    paying for a tree walk on every write."""
    sess = session or ""
    view = wsview.current()
    bodies, progs, outside = wsview.pending(sess)
    if not view.surveyed or bodies or progs or outside:
        return True
    if len(_SURVEY_SEQ) > 512:
        _SURVEY_SEQ.clear()
    n = _SURVEY_SEQ.get(sess, 0) + 1
    _SURVEY_SEQ[sess] = n
    return n % SURVEY_EVERY == 0


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
            # The same rescue for RAW commands (grep/cp/sed on the spill file), which previously got
            # only the dirguard refusal — the file-tool half succeeding while the command half was
            # blocked on the same path string taught the model a false sandbox rule.
            if is_shell_tool_name(name) and (_c0 := _command_of(fn.get("arguments"))) \
                    and _respill_command(_c0) != _c0:
                _d = _parse(fn.get("arguments"))
                for _f in (*_CMD_FIELDS, "script"):
                    _v = _d.get(_f)
                    if isinstance(_v, list) and _v and isinstance(_v[-1], str):
                        _d = {**_d, _f: [*_v[:-1], _respill_command(_v[-1])]}
                    elif isinstance(_v, str) and _v:
                        _d = {**_d, _f: _respill_command(_v)}
                fn = {**fn, "arguments": json.dumps(_d, ensure_ascii=False)}
                tc = {**tc, "function": fn}
                args = _d
                if rlog is not None:
                    rlog.emit("writeproxy.spill_command_redirect", tool=name)
            cmd = None
            # MALFORMED FUSED CALL: the model leaked tool-call marker tokens into the command (two calls
            # fused / broken quoting). It can't be reconstructed and would die in bash as a cryptic EOF —
            # refuse it with guidance to send ONE clean call, so the turn teaches instead of just failing.
            if is_shell_tool_name(name) and _has_tc_debris(fn.get("arguments")):
                cmd = _refusal_command(prompts.load('malformed_call_refusal'))
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_malformed_call", tool=name)
            # EXTERNAL-DIR GUARD (cria-side, independent of the harness sandbox): a fledgling model
            # gets bounded to the workspace even when the harness runs --yolo. Refuse a synthetic file
            # tool or raw shell command reaching outside the workspace beyond [safety] permission.
            elif (reason := _external_refusal(name, args, fn, injected, external_dir_permission, workspace_root)) is not None:
                cmd = _refusal_command(reason)
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_external", tool=name, permission=external_dir_permission)
            # cria's own dir is off-limits: refuse a synthetic read/write/edit/list whose path lands
            # in ~/.cria BEFORE lowering it, so cria never cats its secrets to the model or lets a
            # stray write corrupt its state. The refusal is a normal tool result the model reads.
            elif name in injected and (target := _guarded_path(name, args)) and _targets_cria_home(target):
                cmd = _refusal_command(prompts.load('cria_home_refusal'))
                if rlog is not None:
                    rlog.emit("writeproxy.blocked_cria_home", tool=name, path=target)
            # cria's read-only SPILL scratch (./tmp/cria): a big doc cria saved as REFERENCE. Refuse an
            # edit/write (observed: identical no-op edits on the spilled spec that poisoned the reasoner);
            # steer a WHOLE read to grep (a raw cat of a big file is truncated by the harness). A ranged
            # read is fine (falls through to the normal read handler).
            elif (name in (_WRITE_NAMES | _EDIT_NAMES | _READ_NAMES) and name in injected
                  and (sp := _tool_path(args)) and _under_spill_dir(str(sp))
                  and not (name in _READ_NAMES and (args.get("start_line") or args.get("end_line")))):
                # A READ is SIZE-GATED, not refused outright (see _spill_read_command): a spilled
                # file under READ_INLINE_MAX is handed over, because "reading it whole gets
                # truncated" is not true of it. An edit/write is refused whatever the size — the doc
                # is reference material, and that has nothing to do with how big it is.
                cmd = (_spill_read_command(str(sp)) if name in _READ_NAMES
                       else _refusal_command(prompts.render("spill_edit_refusal", path=str(sp))))
                if rlog is not None:
                    # A read is no longer necessarily BLOCKED — the size test runs on the harness's
                    # filesystem, so cria does not know here which way it went. Naming this event
                    # "blocked" for a read that then succeeds would put a false fact in cria's own
                    # log, which is the same defect one level down (rule 12: the event is the truth).
                    rlog.emit("writeproxy.spill_read_gated" if name in _READ_NAMES
                              else "writeproxy.blocked_spill", tool=name, path=str(sp))
            elif name in _WRITE_NAMES and name in injected:
                path = _tool_path(args)
                if not path:
                    # No usable path — the arguments arrived malformed (gemma4 re-measure run
                    # 1785893473 call 0007: path fused into another key). Before this branch the
                    # un-lowerable call fell through RAW to the harness, whose reply —
                    # "unsupported call: write_file" — the coder read as "writes are unsupported".
                    # cria advertised this tool; cria owns the refusal that explains it.
                    cmd = _refusal_command(prompts.load("write_missing_path"))
                    if rlog is not None:
                        rlog.emit("writeproxy.write_missing_arg", tool=name, arg="path")
                if path:
                    # The `new_string` lesson below, for the tool that carries whole files. `content`
                    # is declared required, and `args.get("content") or ""` turned its ABSENCE — and
                    # its explicit `null` — into an empty string, which the byte-exact write then put
                    # on disk: a working file truncated to zero bytes, reported to the coder as a
                    # successful write. Validate-before-lower does not catch it either, because an
                    # empty file parses. Only a MISSING/NULL value is refused; an intentional empty
                    # string still writes, and a falsy-but-real value (0) is no longer discarded.
                    body = args.get("content")
                    if body is None:
                        body = args.get("contents")
                    if body is None:
                        cmd = _refusal_command(prompts.load("write_missing_content"))
                        if rlog is not None:
                            rlog.emit("writeproxy.write_missing_arg", tool=name, arg="content")
                    elif _protocol_debris(str(body)):
                        # Content that is NOTHING BUT tool-protocol tags (plus at most a bare
                        # path token) is the mis-split half of a FUSED call, not a file. Walked
                        # on nemotron poff 1785946072: cria wrote that soup as a file named
                        # `tests` ("Wrote tests"), which then blocked the real tests/ directory
                        # for the rest of the run. A file whose real lines merely MENTION a tag
                        # never trips this — every line must be a tag or a bare token.
                        cmd = _refusal_command(prompts.load("write_fused_content"))
                        if rlog is not None:
                            rlog.emit("writeproxy.write_fused_content", tool=name,
                                      path=str(path))
                    else:
                        # NO SECOND TRIM HERE. The fused-call tail is cut once, for every tool's
                        # every string argument, at `massage.strip_debris_from_args` — which runs on
                        # this completion before it ever reaches translation. A copy of the rule in
                        # this one branch is what left `edit_file` still receiving the junk (#23).
                        cmd = _write_command(str(path), _repair_double_escaped(str(body)))
            elif name in _EDIT_NAMES and name in injected:
                path = _tool_path(args)
                if not path or args.get("old_string") is None:
                    # Same malformed-arguments hole as the write branch (run 1785893473 calls
                    # 0059/0184: path+old_string fused into new_string). Un-lowered, the raw call
                    # drew the harness's opaque "unsupported call: edit_file", which the coder
                    # misread as edits being unsupported and rerouted through whole-file rewrites.
                    cmd = _refusal_command(prompts.load("edit_missing_path"))
                    if rlog is not None:
                        rlog.emit("writeproxy.edit_missing_arg", tool=name,
                                  arg="path" if not path else "old_string")
                if path and args.get("old_string") is not None:
                    # A MISSING required argument is not an empty one. `new_string` is declared
                    # required, and `args.get(...) or ""` turned its ABSENCE — the shape a truncated
                    # tool call has — into "delete this text". cria then applied that deletion, saw
                    # the wreckage, and reported it to the coder as a fact about ITS file:
                    #   "your edit would break handle_resolver.py — unmatched ')' (line 15)"
                    # Walked on ada-handles_fabliq_codex_pon_1785721353 call 0165-0166: that file
                    # compiles cleanly. The syntax error was cria's own artifact, handed over with a
                    # file:line citation — and it named the exact phantom (a missing closing paren)
                    # the run had already been chasing for a hundred calls. An intentional empty
                    # new_string is still fine; only an ABSENT key is refused.
                    if "new_string" not in args:
                        cmd = _refusal_command(prompts.load("edit_missing_new_string"))
                        if rlog is not None:
                            rlog.emit("writeproxy.edit_missing_arg", tool=name, arg="new_string")
                    else:
                        cmd = _edit_command(str(path), str(args.get("old_string") or ""),
                                            str(args.get("new_string") or ""))
            elif name in _READ_NAMES and name in injected:
                cmd = _read_command(args)
            elif name in _LIST_NAMES and name in injected:
                cmd = _list_command(args)
            elif name in _FETCH_NAMES and name in injected:
                cmd = _fetch_command(args, session, workspace_root)
            elif name == "web_search":
                refusal = webfetch.gate_search(session, str(args.get("query") or ""))
                if refusal is not None:  # exact-repeat search this session → refuse, don't burn a call
                    cmd = _refusal_command(refusal)
                elif "web_search" in injected and brave_key:  # synthetic → Brave curl
                    q = str(args.get("query") or "")
                    cmd = _search_command(args, brave_key)
                    # ONLY this path writes the spill file, so only this path earns the later
                    # "go read that file" refusal — and it records the path the composed curl
                    # actually writes, so that refusal names a file that exists rather than
                    # deriving the name a second time from a differently-spelled copy of the query.
                    webfetch.note_search_spill(session, q, webfetch.search_spill_name(q))
                elif native_search and native_search != "web_search":  # route to the harness's search tool
                    rebuilt.append({**tc, "function": {**fn, "name": native_search}})
                    continue
            if cmd is not None:
                # RIDE ALONG. cria has no synchronous channel to the harness — it can ask the
                # workspace a question only by putting a command in the reply it is already
                # sending. This is that reply. The survey is appended to write/edit/list
                # translations, whose own output is one bounded line, and NEVER to a read or a
                # fetch: those results are already large, and pushing one past the harness's own
                # output cap would cut the CODER's content to pay for cria's instrumentation.
                # `represent_inbound` strips it back out, so the model sees its own call's result
                # and nothing else.
                if name in _SURVEYABLE and _survey_due(session, name):
                    cmd = f"{cmd}\n{wsview.survey_command(session or '', cd=workspace_root or '')}"
                # AND TAKE CRIA'S OWN LITTER OUT WITH IT. The gate's probes create untracked files in
                # the coder's workspace; cria cannot unlink them itself (that filesystem is the
                # harness's), so the removal rides on a command cria composes. The next GATE carries
                # it too — this is the leg that matters when there is no next gate, which is the case
                # where the litter would otherwise sit in the user's repo for good (#7).
                if (rm := _litter_leg(workspace_root)):
                    cmd = f"{rm}\n{cmd}"
                rebuilt.append(_shell_call(tc.get("id"), shell_tool, f"{_sentinel(name, fn.get('arguments'))}\n{cmd}"))
                if rlog is not None:
                    # `target`/`detail` feed the LIVE status ticker — the harness renders the lowered
                    # call as an opaque sentinel blob (operator: "a file wrote to the project, but
                    # there was no indicator"), so the ACTION is narrated here in cria's own voice.
                    rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "",
                              detail=str(args.get("query") or args.get("url") or ""))
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


def is_crias_own(command: str) -> bool:
    """Did cria compose this command, whatever it composed it FOR?

    ONE QUESTION, ONE OWNER (#23). `original_call` answers a narrower one — "which coder tool did
    this lowering come from" — and returns None for a cria composition that is nobody's tool call:
    the gate script, which carries its own sentinel. Every caller that used `original_call` as a
    stand-in for this question therefore fell through to scanning cria's own bytes on the gate leg.
    That is how `FILE FOLD_AT — does NOT exist on disk` kept reaching the steer author: the workspace
    survey program contains `if len(files) > FOLD_AT:`, and the redirect matcher read the `>` as a
    write to a file named after one of cria's own constants. Fixed once for the writeproxy sentinel
    and still live on the gate leg at ef8ee77 — hence one owner rather than one sentinel's reader."""
    text = command or ""
    if not text:
        return False
    from . import probegate
    return _SENTINEL in text or probegate.GATE_SENTINEL in text


def original_call(command: str) -> dict | None:
    """The tool call a lowered command was made FROM — ``{"name":…, "arguments":…}`` — or None when
    this is not one of cria's.

    Public so a reader that wants to know what the CODER did stops reading what CRIA WROTE. The
    lowered form is cria's text: a `python3` heredoc, a curl, and — appended to writes, edits and
    lists — the workspace survey program. Anything that scans it is scanning cria's own bytes.

    Walked on feed-pipeline-java x nemotron-elastic 1787346816. `loop._shell_write_target` looks for
    a redirect target after a `>`; the survey program contains the ordinary Python comparison
    `if len(files) > FOLD_AT:`, so cria read one of its OWN CONSTANTS as a file the coder had
    written, and then told the model, in its own voice, `FILE FOLD_AT — does NOT exist on disk`.
    Same family as the gate matchers retired on 2026-08-21: cria's own text re-entering as the
    model's work (#12, #17)."""
    return _read_sentinel(command)


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


# A pipe into a line-filter: the class of self-blinding observed live (`| grep -E 'passed|failed'`,
# `| grep -v Error`, `| tail`). Only these — a pipe into tee/xargs/python is not a filter.
_FILTER_PIPE = re.compile(r"\|\s*(?:grep|egrep|fgrep|rg|head|tail|sed|awk)\b")
_EXIT_CODE = re.compile(r"Process exited with code (\d+)")


def _debinarized(content: str) -> str:
    """Terminal colour stripped, then binary SOUP replaced by a fact line (operator ruling: blobs have
    no place in any model-facing prompt). The harness exec envelope — the true record of the run — is
    preserved; only the payload is stood in for. A hexdump/od/strings output the model asked for is
    TEXT and passes untouched (the detector keys on replacement/control chars, which those never
    contain).

    The colour strip comes FIRST and is unconditional. Build tools colour their output, the escape
    byte is a control character, and a coloured compiler log therefore read as binary and was thrown
    away whole — every Maven error in the six-language battery. Stripping also spares the model bytes
    it can do nothing with."""
    content = content_reduce_mod.strip_ansi(content)
    if not content or not content_reduce_mod.looks_binary(content):
        return content
    m = _ENVELOPE_OUTPUT_LINE.search(content)
    if m and "Process exited with code" in content[:m.start()]:
        head, payload = content[:m.end()], content[m.end():]
        if not content_reduce_mod.looks_binary(payload):
            return content
        return head + "\n" + _binary_fact(payload)
    return _binary_fact(content)


def _binary_fact(blob: str) -> str:
    """The stand-in line for output cria will not pass through as text — NAMING the format.

    Both call sites passed `kind=None`, so the note read "[binary content: 4,096 bytes — not shown]"
    and the model could not tell a PNG from a ZIP from a corrupt log. `binary_kind` existed for
    exactly this and was reached from nowhere. It reads magic bytes, so re-encode the head — as
    latin-1, the only codec where one character is the one byte it came from. Encoding the head as
    UTF-8 turns 0x89 into 0xc2 0x89 and no signature ever matches, which is how a kind of None became
    the only outcome. When the head will not round-trip, the format is genuinely unrecoverable and
    the note says only what it knows (#5b)."""
    try:
        head = blob[:16].encode("latin-1")
    except UnicodeEncodeError:
        head = b""
    return content_reduce_mod.binary_note(len(blob.encode("utf-8", "replace")),
                                          content_reduce_mod.binary_kind(head))


# A SEARCH COMMAND, by shape. These read a file or a tree and answer with the lines that matched;
# every one of them exits 1 and prints nothing when the answer is "none", which is a FACT and not a
# failure. Deliberately excludes the pipe case — `_blind_pipe_failure` owns that one, where the
# model's own filter ate someone else's error.
_SEARCH_CMD = re.compile(r"(?:^|[;&|(]\s*)\s*(?:grep|egrep|fgrep|rg|ag|ack)\b")


def _found_nothing(command: str, content: str) -> bool:
    """The model ran a search, it matched nothing, and the envelope shows that as a blank."""
    cmd = command or ""
    if not cmd or not _SEARCH_CMD.search(cmd) or _FILTER_PIPE.search(cmd):
        return False
    m = _EXIT_CODE.search(content or "")
    if not m or m.group(1) != "1":       # 1 is "no match"; 2+ is a real error, with its own message
        return False
    return not _strip_exec_envelope(content or "").strip()


def _blind_pipe_failure(command: str, content: str) -> bool:
    """True when the model's own command failed (nonzero exit), printed NOTHING, and contains a
    line-filter pipe — the three computable facts behind 'your filter ate the error'. Anything less
    than all three → stay silent (a bare `grep pat file` exiting 1 with no output is a real answer)."""
    if not command or not _FILTER_PIPE.search(command):
        return False
    m = _EXIT_CODE.search(content)
    if not m or m.group(1) == "0":
        return False
    return _strip_exec_envelope(content).strip() == ""


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


# A payload smaller than this is a targeted snippet — genuinely useful context for the model's next
# attempt, and too short to be mistaken for the file. Above it, a rejected old_string reads as a
# listing of the whole file.
_REJECTED_PAYLOAD_CHARS = 400


def _failed_edit_ids(messages: list[dict]) -> set[str]:
    """tool_call_ids whose write/edit result came back as a failure — the payload never hit disk.

    Keyed on cria's OWN marker. Every edit-failure directive is composed by `editrecovery.compose`
    and every one of them is prefixed with `EDIT_MARK` (see `_tag`), so the marker is the
    authoritative record of "cria refused this edit" — #12, from the event rather than from prose.

    It used to ask `hasattr(editrecovery, "is_edit_failure")` and fall back to a substring scan for
    `old_string` when the attribute was missing. It has always been missing: no such function has
    ever existed in that module, so the fallback WAS the rule, and a `hasattr` guarding a name that
    never existed is a mitigation for a problem that isn't there (#4). The scan is also wrong in
    principle — `old_string` is an ordinary token that appears in any source file that documents the
    edit tool, so reading such a file would collapse the coder's own successful payloads. It happens
    not to have cost anything yet: over every captured session the two rules agree on all 9,248
    matches, zero disagreements. Ground truth is available, so use it rather than the coincidence."""
    ids: set[str] = set()
    for m in messages:
        if m.get("role") != "tool":
            continue
        body = _debinarized(str(m.get("content") or ""))
        if any(ln.strip() == _WROTE for ln in body.splitlines()):
            continue                                   # a success — its content IS on disk
        # …or the HARNESS refused the call outright, which is a failure cria did not author.
        if editrecovery.EDIT_MARK in body or denial.is_denied(body):
            if m.get("tool_call_id"):
                ids.add(m["tool_call_id"])
    return ids


def _collapse_rejected_payload(tc: dict, path: str, rlog=None) -> dict:
    """Take a REJECTED edit's verbatim payload OUT of the call, rather than replacing it with prose.

    The model no longer sees its own invented file text rendered as though it were the file. What it
    still sees is the call it made, the path it aimed at, and — in the tool RESULT, which is cria's
    own marked refusal — that nothing was written. None of that lives in an argument slot.

    NO SENTENCE GOES IN THE CONTENT SLOT. This used to write
    `[985 characters — this edit was REJECTED, nothing was written to <path>]` into `content`, which
    is the exact position a file body occupies, and the model read it as one. In the captures:
    `20260819T063347` calls 0046 and 0047 emitted `write_file {"content": "[2254 characters — this
    edit was REJECTED…]"}` twice in a row — cria's sentence WAS the file it wrote;
    `20260817T020431/0012` reasoned *"The current pom.xml is: ```[1107 characters — this edit was
    REJECTED…]```"*; `20260822T001226/0078` attributed the same sentence to a read_file result. The
    stub's em dash is the documented cause of `Importer.java:[1,20] illegal character: '\u2014'`.
    It shipped in 858 prompt files, 1,770 times, including 85 coder prompts on 2026-08-22/23.

    `focustrim` reached the same place from the other side and the operator ruled on it,
    2026-08-19: *"There is not supposed to be any elision. It's all or nothing."* There the whole
    call could go, because a superseded write loses nothing. Here the failure is information the
    coder needs, so the CALL stays and only the payload leaves — which is the same rule applied to
    the only part of it that can be misread."""
    fn = tc.get("function") or {}
    args = _parse(fn.get("arguments"))
    if not isinstance(args, dict):
        return tc
    dropped = []
    for key in ("old_string", "new_string", "content"):
        val = args.get(key)
        if isinstance(val, str) and len(val) > _REJECTED_PAYLOAD_CHARS:
            del args[key]
            dropped.append((key, len(val)))
    if not dropped:
        return tc
    if rlog is not None:
        rlog.emit("writeproxy.rejected_payload_dropped", level="info", path=path,
                  keys=[k for k, _ in dropped], chars=sum(n for _, n in dropped))
    return {**tc, "function": {**fn, "arguments": json.dumps(args)}}


# THE HARNESS'S OWN TRUNCATION MARKER, in either unit. Codex writes `…N chars truncated…` /
# `…N tokens truncated…` into a tool result it decided was too big to keep whole. Other harnesses
# will spell it differently; this matches the shape, and anything it misses stays silent (#3).
_HARNESS_CUT = re.compile(r"…\s*([\d,]+)\s+(chars|tokens)\s+truncated\s*…")


def note_harness_cuts(messages: list, rlog=None) -> int:
    """Count tool results the HARNESS truncated before cria ever saw them, and say so in the log.

    OBSERVE, NEVER ACT. Nothing is altered and nothing reaches the model: this is cria learning a
    fact about the harness it is fronting, on the only channel where that fact is visible.

    Why it exists. `content_reduce.INLINE_RESULT_MAX_BYTES = 9000` is a hardcoded copy of a constant
    from ONE harness's source — Codex's `TruncationPolicyConfig::bytes(10_000)` — in a project whose
    rule 18 says cria never depends on one harness's config and the retired fork is "a read-only
    spec, never a fix target". The number was measured once, in August, against 166 observed cuts.
    Asked for a current example, there was none: zero markers across all 50 captured sessions, and
    the largest result cria had actually sent upstream was 160,447 bytes, intact.

    So the belief outlived its evidence, grew a second life on the inbound path, and cost 24% of
    every command result in a 24-cell campaign before anyone re-checked it. A remembered number is a
    claim about cria; the marker on the wire is a claim about the world (#5b). This asks the world.

    It is harness-AGNOSTIC by construction: Claude Code, Aider and whatever connects next get counted
    the same way, with no survey of anyone's source and nothing to go stale."""
    n = 0
    for m in messages or []:
        if (m or {}).get("role") != "tool":
            continue
        for hit in _HARNESS_CUT.finditer(str(m.get("content") or "")):
            n += 1
            if rlog is not None:
                rlog.emit("harness.truncated_a_result", level="warn",
                          amount=hit.group(1), unit=hit.group(2))
    return n


def represent_inbound(messages: list[dict], rlog=None, workspace_root: str | None = None) -> list[dict]:
    """Swap cria's shell translations back to the tool the model actually called — read STATELESSLY
    from the sentinel in each stored command, so it survives a restart. Every SYNTHETIC tool is lowered
    to a shell exec, so its result comes back wrapped in the harness exec envelope (Chunk ID / Process
    exited / Output: / …). That envelope is stripped from read/nav results (read_file, list_dir,
    web_fetch, web_search) and from write/edit FAILURES so the tool reads as its own abstraction, not a
    disk-caching shell command. A write/edit SUCCESS is reframed as a clean confirmation (never over a
    real error). A harness ``local_web_search`` is re-presented as ``web_search``. The model's OWN
    exec_command calls keep their envelope — there the shell framing is the truth."""
    note_harness_cuts(messages, rlog)   # observe only: did the harness cut anything before cria saw it?
    out: list[dict] = []
    swapped = 0
    # WHICH CALLS FAILED, known before the assistant turn is emitted. A rejected edit_file keeps its
    # arguments in the replayed history, and `old_string` is the model's own idea of the file —
    # formatted exactly like a file listing, sitting closer to the generation point than the real
    # content. Measured on the six-language battery: at nemotron cart-billing-go 0021 the coder read
    # its own rejected old_string back as authority — "the earlier snippet we saw in the instruction
    # shows the Item struct with ID, Name, PricePerUnit … Perhaps the original code is missing; we
    # need to restore that structure" — and rebuilt a file that never existed. The asymmetry is the
    # bug: fabrications persisted verbatim while verified content was dropped by compaction.
    failed_ids = _failed_edit_ids(messages)
    write_paths: dict[str, str] = {}  # tool_call_id -> path, for the success reframe / failure strip
    strip_ids: set[str] = set()       # read/nav re-presented tool ids → strip the harness exec envelope
    own_cmds: dict[str, str] = {}     # tool_call_id -> the model's OWN raw command, for the blind-pipe note
    # WHAT THIS PASS TEACHES THE WORKSPACE VIEW. cria lowered every one of these calls, so it knows
    # the path and (for a whole write) the exact bytes — the workspace's own contents, proved by the
    # harness's own confirmation rather than inferred from the model's account of what it did. An
    # EDIT proves the opposite direction and is just as useful: the file changed, and cria no longer
    # knows what it holds (see View.note_changed).
    view = wsview.current()
    written: dict[str, str] = {}      # tool_call_id -> whole content the write carried
    edited: set[str] = set()          # tool_call_id of an edit (content becomes unknown on success)
    read_whole: dict[str, str] = {}   # tool_call_id -> path of an UNRANGED read (result is the file)
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            new_calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                name = fn.get("name")
                if is_shell_tool_name(name):
                    orig = _read_sentinel(_command_of(fn.get("arguments")))
                    if orig is None:
                        own = _command_of(fn.get("arguments"))
                        own_cmds[tc.get("id")] = own
                        # THE DISK MOVED AND THE SURVEY DID NOT. A survey rides along on a
                        # cria-composed write/edit/list, so a run of the coder's own shell commands
                        # changes the workspace while the view stands still. Recording that here is
                        # what lets a caller tell "cria saw no vendor/" from "there is no vendor/".
                        from . import shelltool as _shelltool
                        if _shelltool.writes_something(name, own):
                            view.note_a_mutator_ran()
                    if orig is not None:
                        tc = {**tc, "function": {"name": orig["name"], "arguments": orig["arguments"]}}
                        swapped += 1
                        if orig["name"] in (_WRITE_NAMES | _EDIT_NAMES):
                            p = _parse(orig["arguments"])
                            write_paths[tc.get("id")] = _tool_path(p) or ""
                            if orig["name"] in _EDIT_NAMES:
                                edited.add(tc.get("id"))
                            else:
                                body_arg = next((p[k] for k in ("content", "file_text", "text", "body")
                                                 if isinstance(p.get(k), str)), None)
                                if body_arg is not None:
                                    written[tc.get("id")] = body_arg
                            if tc.get("id") in failed_ids:
                                tc = _collapse_rejected_payload(tc, _tool_path(p) or "", rlog)
                        elif orig["name"] in (_READ_NAMES | _LIST_NAMES | _FETCH_NAMES | _SEARCH_NAMES):
                            strip_ids.add(tc.get("id"))
                            if orig["name"] in _READ_NAMES:
                                rp = _parse(orig["arguments"])
                                # A RANGED read is not the file. Only a whole read proves content;
                                # recording a `sed -n 20,40p` slice as the file's bytes would be a
                                # false fact of exactly the shape this module exists to stop (#5b).
                                if not rp.get("start_line") and not rp.get("end_line") and _tool_path(rp):
                                    read_whole[tc.get("id")] = str(_tool_path(rp))
                elif name == "local_web_search":  # always present the Brave tool as web_search
                    tc = {**tc, "function": {**fn, "name": "web_search"}}
                    swapped += 1
                    strip_ids.add(tc.get("id"))
                new_calls.append(tc)
            out.append({**m, "tool_calls": new_calls})
        elif role == "tool":
            tid = m.get("tool_call_id")
            content = _debinarized(str(m.get("content") or ""))
            # cria's own instrumentation rode along on this command — take it back off before
            # anything else looks at the result, so no downstream check ever sees a byte the model
            # did not ask for, and fold what it says into the view.
            content, survey = wsview.strip_survey(content)
            if survey:
                # Same as the gate's copy: a rejected survey is the one failure `wsview` cannot show
                # from the outside, and both readers used to drop the answer on the floor (#12).
                if not wsview.apply_survey(view, survey) and rlog is not None:
                    rlog.emit("wsview.survey_rejected", level="warn", bytes=len(survey),
                              closed=wsview.SURVEY_CLOSE in survey)
            if tid in write_paths and write_paths[tid] and tid not in failed_ids \
                    and any(ln.strip() == _WROTE for ln in content.splitlines()):
                if tid in written:
                    view.note_written(write_paths[tid], written[tid])
                elif tid in edited:
                    view.note_changed(write_paths[tid])
            elif tid in read_whole and not denial.is_denied(content):
                # A REFUSAL IS NOT THE FILE. The write path two lines up requires proof the call
                # landed (`_WROTE`); this one had no equivalent, so every whole read cria itself
                # refused — oversize, spilled, missing, unreadable, a directory — was recorded as
                # that file's BYTES. Found in the captures: 20260822T174652 call 0112, the
                # satisfaction judge, under a header saying "read from disk just now … what is
                # actually there, not a claim by anyone":
                #
                #     ----- src/main/java/pipeline/Importer.java -----
                #     ⟦ctx:denied⟧ src/main/java/pipeline/Importer.java is larger than can be
                #     returned in one read, so nothing is shown.
                #
                # It is worse than a bad body: `note_read` delegates to `note_written`, so a refused
                # read of a file that does not exist ADDS it to the view — `isfile` then answers
                # True and `_veto_refuted_by_disk` prints "EXISTS on disk — 52 bytes" as a verified
                # fact. It also re-opens the incident `loop.search_file_text` records as fixed
                # (searching cria's own pointer instead of the file). The mark is on the text
                # already, applied at the site that decided to refuse — this just reads it.
                view.note_read(read_whole[tid], _strip_exec_envelope(content))
            if tid in strip_ids:                          # read/nav result → drop the shell envelope
                out.append({**m, "content": _strip_exec_envelope(content)})
            elif tid in write_paths and any(ln.strip() == _WROTE for ln in content.splitlines()):  # write/edit SUCCESS
                out.append({**m, "content": prompts.render("write_confirm", path=write_paths[tid])})
            elif tid in write_paths:                      # write/edit FAILURE → strip the shell envelope,
                # then hand a structured edit-fail fact-report to the ONE edit-recovery owner, which
                # composes the single monotonic directive keyed on this file's failure history so far
                # (``out``). A non-edit-fail failure (write refusal, real error) passes through unchanged.
                out.append({**m, "content": editrecovery.recover(_strip_exec_envelope(content), out, rlog)})
            elif "externally-managed-environment" in content:
                # PEP 668: `pip install` fails by design on this box. A weak model retries it forever
                # (observed: Fabliq wedged a whole step re-running pip). Append the remedy (stdlib /
                # --break-system-packages / venv) ONCE — grounded in the real error, not invented.
                out.append({**m, "content": content + "\n\n" + prompts.load("pep668_remedy")})
            elif _found_nothing(own_cmds.get(tid, ""), content):
                # AN EMPTY RESULT FROM A SEARCH IS AN ANSWER. `grep` exits 1 and prints nothing when
                # the string is not there, and the harness envelope renders that as `Process exited
                # with code 1 / Output:` with a blank beneath it — indistinguishable, to a reader,
                # from a command that failed to run. Walked on cart-billing-go x nemotron-elastic
                # 1787434778: the coder grepped the library for `Quantize` six times, got the blank
                # each time, and read it as "the command did not work" rather than "the method does
                # not exist" — which was the whole question of the run. Its own words at 0072: "in our
                # fetch we didn't see that snippet; maybe it's later in the file."
                out.append({**m, "content": content + "\n\n" + prompts.load("search_found_nothing")})
            elif _blind_pipe_failure(own_cmds.get(tid, ""), content):
                # The model's OWN filter pipe ate the error: `pytest … | grep -E 'passed|failed'` on a
                # collection error prints NOTHING (grep exits 1 on no match), and a weak model re-ran
                # that blind for ELEVEN turns while the real traceback existed (run 0729-gemma4 B3).
                # The note states only computable facts: nonzero exit, empty output, a filter present.
                out.append({**m, "content": content + "\n\n" + prompts.load("filtered_failure_note")})
            elif content != str(m.get("content") or ""):
                out.append({**m, "content": content})   # the binary-soup cleanse changed it
            else:
                out.append(m)
        else:
            out.append(m)
    if swapped and rlog is not None:
        rlog.emit("writeproxy.represented", calls=swapped)
    _note_missing_dependency(out, workspace_root, rlog)
    _note_dependency_search(out, own_cmds, workspace_root, rlog)
    return out


def _note_missing_dependency(messages: list[dict], workspace_root, rlog) -> None:
    """Label the MOST RECENT command result whose own output says a dependency will not load.

    The note existed already and fired only on cria's gate probes — so it never saw the model's own
    `ruby -Ilib …`, which is where this actually happens. Measured on the p3 arm: nemotron-elastic's
    ruby run carried `cannot load such file` 39 times and the note appeared zero times, and all five
    of that cell's checks died on that one unloadable gem. Same mistake as the read guard: the door
    cria watches was not the door the failure comes through.

    ONLY THE LAST ONE. Annotating all 39 would put the same paragraph in the window 39 times, which
    is noise on a signal the model has already seen (#3). The most recent occurrence is the turn it
    can act on.

    Silent when the name resolves to the project's own file — telling a coder its own module is a
    missing dependency sends it after a package that should not exist (#8: ask the disk)."""
    last = None
    for m in messages:
        if m.get("role") != "tool":
            continue
        c = m.get("content")
        if not isinstance(c, str) or probegate_marker_in(c):
            continue          # a gate result already carries the note from proberun
        if probeparse.dependency_missing(c):
            last = m
    if last is None:
        return
    eco, name = probeparse.dependency_missing(last["content"])
    if workspace_root and probeparse.names_a_workspace_file(name, workspace_root):
        return
    note = prompts.fill(proberun.dependency_line(eco, workspace_root or ""), name=name)
    if note in last["content"]:
        return
    last["content"] = last["content"] + "\n\n" + note
    if rlog is not None:
        rlog.emit("writeproxy.dependency_note", level="info", ecosystem=eco, name=name)


def _note_dependency_search(messages: list[dict], own_cmds: dict[str, str],
                            workspace_root, rlog) -> None:
    """Answer a search for dependency SOURCE that came back empty, by naming where it really lives.

    `probeparse.searched_for_dependency_source` and `probeparse.dependency_source_root` were written
    for this on 2026-08-19 and NOTHING EVER CALLED THEM. The prompt file existed, the table of
    per-ecosystem roots existed, the tests passed against the functions directly — and the whole
    thing sat outside the loop for a day (#11b, again: a mechanism that reaches nothing). Its sibling
    from the same walk, the 4xx note in `webfetch.render_page`, did land, so half that fix has been
    live and half has been dead.

    The incident it was built for, walked on `rust-toml-cli x ternary-bonsai` 2026-08-19: the coder
    ran `find <WORKSPACE>/.cargo/registry/src/... -name value.rs` twice, got nothing both times, and
    concluded the source was unavailable. It was on the box the whole run under `~/.cargo/registry/src`
    — one directory root away — and the model spent the next twenty calls guessing TOML syntax from
    memory instead.

    THE TRIGGER IS THE SEARCH, NOT THE FAILURE THAT PROMPTED IT, and that bounds what this can do:
    a model that never goes looking is never answered. `feed-pipeline-java x nemotron-elastic`
    1787247514 died believing `com.opencsv.CSVRecord` exists, with the jar sitting in `~/.m2` that
    would have disproved it in one command — and searched no package directory in 74 calls, so this
    note could not have fired. Pointing a model at the source it did not ask for is a different
    mechanism and a much higher bar (#1); this one only answers a question already asked.

    ONLY THE LAST ONE, like its sibling above: repeating the same paragraph for every empty search is
    noise on a signal the model has already read (#3). Silent when the search found something, when
    the path searched is already the home root (`searched_for_dependency_source` handles that), and
    when no root for this ecosystem is on disk in the `found` wording — that case gets the `absent`
    wording instead, which tells the model to stop searching the same way rather than sending it to a
    directory cria cannot see."""
    if not messages:
        return
    last, searched = None, ""
    for m in messages:
        if m.get("role") != "tool":
            continue
        c = m.get("content")
        if not isinstance(c, str) or probegate_marker_in(c):
            continue
        tok = probeparse.searched_for_dependency_source(own_cmds.get(m.get("tool_call_id"), ""))
        if not tok:
            continue
        if _strip_exec_envelope(c).strip():
            continue                     # it FOUND something — nothing to answer (#3)
        last, searched = m, tok
    if last is None:
        return
    eco = _workspace_ecosystem(workspace_root)
    root = probeparse.dependency_source_root(eco, workspace_root or "") if eco else ""
    words = prompts.load_map("dependency_source_root")
    # …AND NOT A PARENT OF WHERE IT JUST LOOKED. The `found` wording says "you looked in the wrong
    # root; the real one is <root>" — false when the token is already inside that root, and its
    # remedy names a directory the search was already under. Walked on shipping-rates-rb x
    # nemotron-elastic 1787432916: cria answered a search of the installed gem's own lib/ with "this
    # project keeps no vendored copy there … Search there instead", naming the parent (#5b).
    if root and probeparse.searched_under(searched, root):
        return
    note = (prompts.fill(words["found"], searched=searched, root=root) if root
            else prompts.fill(words["absent"], searched=searched))
    if note in last["content"]:
        return
    last["content"] = last["content"] + "\n\n" + note
    if rlog is not None:
        rlog.emit("writeproxy.dependency_source_note", level="info",
                  ecosystem=eco or "", root=root, searched=searched)


def _workspace_ecosystem(workspace_root) -> str:
    """The first ecosystem this workspace declares, by its own manifests — "" when none or unreadable.

    Reuses `probediscovery.detect_ecosystems`, whose enum values are already the keys of
    `_DEPENDENCY_SOURCE_ROOTS` ("jvm", "rust", …), so there is no second table to drift (#23)."""
    if not workspace_root:
        return ""
    try:
        from pathlib import Path
        from .probediscovery import ProjectDir, detect_ecosystems
        entries = wsview.current(workspace_root).scandir(workspace_root)
        if entries is None:
            return ""
        names = {e.name for e in entries if e.is_file()}
        found = detect_ecosystems(ProjectDir(Path(workspace_root), names))
        return found[0].value if found else ""
    except Exception:                     # noqa: BLE001 — a note must never break the reply
        return ""


def probegate_marker_in(text: str) -> bool:
    """A gate result — proberun.dependency_note already speaks for those."""
    from .probegate import SECTION_PREFIX
    return SECTION_PREFIX in text


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
