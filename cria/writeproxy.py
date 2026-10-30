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
from typing import NamedTuple
import hashlib
import uuid
import json
import os
import re
from dataclasses import dataclass, replace
from shlex import quote as _qbash  # one bash-quoting rule (was a hand-rolled _qbash)

from . import bodykeys, brave, denial, resultpacket, depsurface, dirguard, editrecovery, editsequence, ownedfiles, prompts, webfetch, wsview, toolstages
from .editsequence import EDIT_SEQ_DIR, EDIT_SEQ_WAIT_SECONDS, _HD_PY, _seq_release
from .toolstages import EditSequence, LoweringRequest, OutboundCall, ShellCommand, ReturnedResult, ReturnedHistory
from .returnedpolicies import (_rejected_payload_note, _collapse_rejected_payload,
                               _render_dependency_surface, _found_nothing, _blind_pipe_failure)
from .outboundpolicies import _external_refusal, _spill_read_command
from .shrinkprotection import ShrinkServices, wrap_finding
from . import content_reduce as content_reduce_mod
from . import probeparse
from . import proberun
from .privatepaths import CRIA_HOME
from .shelltool import _CMD_FIELDS, is_shell_tool_name, shell_args
from .toolargs import PATH_KEYS as _PATH_KEYS, parse_args as _parse, tool_path as _tool_path
from . import filecommands
# Canonical pure helpers; transport/service composition remains in this facade.
from .callliterals import (
    _FUSED_TAIL_MAX_LINES, _PROTOCOL_TAG_LINE, _protocol_debris, trim_fused_tail,
    _TC_DEBRIS, _has_tc_debris, _ESCAPES, _repair_double_escaped, _decode_backslash_escapes)
from .filecommands import (
    _WRITE_NAMES, _EDIT_NAMES, _READ_NAMES, _LIST_NAMES, _FileMutation, _prepare_file_mutation,
    _targets_cria_home, _guarded_path, READ_INLINE_MAX, _ranged_read, _read_failure_branches,
    _read_command, _read_in_place_of_write)
from .toolwire import (
    REFUSED_EXIT_CODE, _oversize_command, _refusal_command, _SENTINEL, _SENTINEL_LINE,
    _sentinel, _shell_call, _b64, _RIDE_ALONG_HOST_RESERVE,
    _RIDE_ALONG_COMMAND_RESERVE, _command_of, is_crias_own, original_call, _read_sentinel, receipt_of, survey_declared, _declaration,
    GATE_SENTINEL)

from .resultnotes import (
    exec_envelope, _strip_exec_envelope, _noted, _digest, append_note, payload_of, _workspace_ecosystem,
    probegate_marker_in)


@dataclass
class ExternalizationOffer:
    """Invocation authority plus required transport correlation, never a storage claim."""
    owner: object
    source: object
    delivery: object
    call_id: str
    original_arguments: str
    operation: str
    original_name: str
    lowered_arguments: str | None = None
    lowered_name: str | None = None
    lowered_type: str | None = None
    retained: bool = False


def _externalize_coder(source: OutboundCall) -> str:
    from . import externalization as e
    request, args = source.request, source.arguments
    definition, owner = request.externalization_definition, request.externalization_owner
    search = source.name == 'web_search'
    cid = str(source.call.get('id') or '')
    arguments = source.function.get('arguments')
    prior = (getattr(owner, 'externalization_offers', None) or {}).get(cid) if owner is not None else None
    if (prior is not None and prior.original_arguments == arguments
            and prior.original_name == source.name and prior.delivery.owner is definition):
        return prior.delivery.result.payload
    if prior is not None:
        prior.delivery.cancel()
        owner.externalization_offers.pop(cid, None)
    inline = (_search_command(args, request.brave_key) if search else
              _fetch_command(args, request.session, request.workspace_root))
    if definition is None:
        return inline
    state = getattr(owner, 'externalization_state', None) if owner is not None else None
    if state is None:
        state = e.State()
        if owner is not None:
            owner.externalization_state = state
    operation = uuid.uuid4().hex
    if search:
        target = webfetch.search_spill_name(str(args.get('query') or ''))
        program = definition.search_program(content_reduce_mod.INLINE_RESULT_MAX_BYTES)
        detect = lambda: e.SearchOffer(target, program)
        offer = lambda spill: _search_command(args, request.brave_key, search_offer=spill, operation=operation)
        record = lambda spill: webfetch.note_search_spill(request.session, str(args.get('query') or ''), spill.target)
    else:
        url = str(args.get('url') or '')
        def cached(value):
            found = webfetch._DOC_CACHE.get(value)
            if found is None:
                return None
            def render():
                _status, target, content, pointer = webfetch.render_cached_spill(
                    value, found, _guidance=request.document_guidance)
                return e.Spill(target, content, pointer)
            return e.FetchFacts(len(found[2]), render)
        services = e.FetchServices(webfetch.OVERSIZE_CHARS, cached,
            lambda: webfetch.already_spilled(request.session, url, request.workspace_root))
        cursor = None if args.get('raw') else args.get('cursor')
        detect = lambda: e.coder_fetch(url, find=args.get('find') or None,
                                      cursor=cursor or None, services=services)
        offer = lambda spill: _spill_command(spill.target, spill.content, spill.pointer,
                                             operation=operation)
        def record(spill):
            webfetch.note_fetch_spill(request.session, url, spill.target,
                                     workspace_root=request.workspace_root)
    value = e.Input(operation, inline, e.Services(detect, offer, record))
    delivery = e.selected_externalization(definition, value, state)
    if owner is not None and delivery.result.spill is not None:
        pending = ExternalizationOffer(owner, value, delivery, cid, arguments, operation, source.name)
        if owner.externalization_offers is None:
            owner.externalization_offers = {}
        owner.externalization_offers[cid] = pending
    return delivery.result.payload


def retain_externalizations(owner, completion) -> None:
    """Only final retained exact lowered calls earn offer retention, never storage."""
    calls = {str(tc.get('id') or ''): tc for choice in completion.get('choices', [])
             for tc in (choice.get('message') or {}).get('tool_calls') or []}
    for cid, offer in (getattr(owner, 'externalization_offers', None) or {}).items():
        if not isinstance(offer, ExternalizationOffer):
            continue
        call = calls.get(cid)
        if (offer.owner is owner and call is not None and offer.lowered_arguments is not None
                and call.get('type') == offer.lowered_type
                and (call.get('function') or {}).get('name') == offer.lowered_name
                and (call.get('function') or {}).get('arguments') == offer.lowered_arguments):
            offer.retained = True


def observe_externalization_results(owner, messages) -> None:
    """Read checked producer facts from raw exact paired transport, before representation."""
    from . import externalization as e
    calls = {}
    offers = getattr(owner, 'externalization_offers', None) or {}
    proofs = _frame_proofs(messages)       # the typed first records of the paired lowered calls: the stored fact is a field
    for message in messages:
        if message.get('role') == 'assistant':
            calls.update({str(call.get('id') or ''): call for call in message.get('tool_calls') or []})
        if message.get('role') != 'tool':
            continue
        cid = str(message.get('tool_call_id') or '')
        offer, call = offers.get(cid), calls.get(cid)
        if (not isinstance(offer, ExternalizationOffer) or offer.owner is not owner or not offer.retained or call is None
                or call.get('type') != offer.lowered_type
                or (call.get('function') or {}).get('name') != offer.lowered_name
                or (call.get('function') or {}).get('arguments') != offer.lowered_arguments):
            continue
        content = message.get('content')
        if not isinstance(content, str):
            continue
        envelope = exec_envelope(content)
        if envelope is not None and envelope.exit_code not in (None, 0):
            offer.delivery.settle(e.Outcome.FAILED, stored=False)
            continue
        proof = proofs.get(cid)
        for fact in ([proof.rep["st"]] if proof is not None and proof.rep and "st" in proof.rep else []):
            try:
                if fact.get('operation') != offer.operation:
                    continue
                stored = e.SearchStored(fact['target'], fact['byte_count'], fact['sha256'])
                spill = offer.delivery.result.spill
                if isinstance(spill, e.Spill):
                    body, _note = _spill_body(spill.content)
                    raw = body.encode('utf-8')
                    if (stored.target != spill.target or stored.byte_count != len(raw)
                            or stored.sha256 != hashlib.sha256(raw).hexdigest()):
                        continue
                    stored = True
                offer.delivery.settle(e.Outcome.RETAINED, stored=stored)
            except (ValueError, TypeError, KeyError):
                continue


def _file_mutation_refusal(name: str, mutation: _FileMutation, injected: set, rlog) -> str:
    """One truthful refusal path; retain tool-specific prompts and event identity."""
    error = mutation.error
    if error == "empty_old_string":
        whole = sorted(injected & _WRITE_NAMES)
        message = prompts.load("edit_empty_old_string") + (
            " " + prompts.fill(prompts.load("edit_empty_old_string_write"), tool=f"`{whole[0]}`")
            if whole else "")
        if rlog is not None:
            rlog.emit("writeproxy.edit_empty_old_string", tool=name, path=mutation.path)
    else:
        write = name in _WRITE_NAMES
        prompt = (("write_missing_path" if error == "path" else "write_missing_content") if write
                  else ("edit_missing_new_string" if error == "new_string" else "edit_missing_path"))
        message = prompts.load(prompt)
        if rlog is not None:
            rlog.emit("writeproxy.write_missing_arg" if write else "writeproxy.edit_missing_arg",
                      tool=name, arg=error)
    return _refusal_command(message)
_FETCH_NAMES = {"web_fetch"}
_SEARCH_NAMES = {"web_search", "local_web_search"}
# Heredoc terminator — the payload rides on stdin, so there is NO arg-size limit (no chunking). Both
# the write and edit commands are python heredocs (they share the validate-before-lower syntax check).
# A per-write temp suffix keeps the write atomic (write temp, then mv over the target). The temp is
# removed on ANY failure: `os.replace` onto a directory raises, and the file used to survive — measured
# (run 0727-161325), 1,089 bytes of the model's code were left at
# `/home/jesse/src/<workspace>.cria-tmp`, a SIBLING of the workspace, because `Path("<ws>/.")`
# normalizes to `<ws>` and `str(p) + suffix` then lands one level UP. The dirguard had checked the
# MODEL's path (`<ws>/.`, legitimately inside); the temp path cria derived from it was never
# re-checked. A directory target is now refused before any temp exists, which removes the escape at
# its source; the cleanup covers every other way a write can fail.
# A result line saying the edit ran BEFORE one or more edits the coder sent ahead of it in the same turn had
# finished (see `_EDIT_SEQ_BLOCK`). Rendered into prose by `render_edit_echo` / `editrecovery.recover`.
EDIT_ORDER_LATE = editrecovery.ORDER_LATE
_TMP_SUFFIX = ownedfiles.TEMP_SUFFIX   # shared atomic resource contract; no PID-derived allocations
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
%%RECORD%%
p=pathlib.Path(base64.b64decode('{path}').decode())
raw=base64.b64decode('{content}')
_late=False
#%%SEQ%%
_after=_v(str(p),raw)
if _after is not None and p.exists() and _v(str(p),p.read_bytes()) is None:
    sys.exit(base64.b64decode('{refused}').decode().replace('%%NAME%%',p.name).replace('%%AFTER%%',_after)+_at(raw,_after))
if p.is_dir():
    sys.exit(base64.b64decode('{isdir}').decode().replace('%%NAME%%',str(p)))
_bp=next((a for a in p.parents if a.exists()), None)
if _bp is not None and not _bp.is_dir():
    sys.exit(base64.b64decode('{parentfile}').decode().replace('%%NAME%%',str(p)).replace('%%BLOCK%%',str(_bp)))
p.parent.mkdir(parents=True,exist_ok=True)
# The SAME directory lock the edit executor takes, so a write and an edit sent in one batch cannot interleave;
# the atomic helper exclusively allocates its own temporary inode.
import fcntl
try:
    _lk=os.open(os.path.realpath(str(p.parent)),os.O_RDONLY); fcntl.flock(_lk,fcntl.LOCK_EX)
except OSError:
    pass
try:
    _atomic_replace(p,raw)
except _TargetMutationUncertain as _e:
    sys.stdout.write(_rec('uncertain', **({{'late':True}} if _late else {{}}))); sys.stdout.flush()
    sys.exit(base64.b64decode('{uncertain}').decode().replace('%%NAME%%',p.name).replace('%%ERR%%',_e.strerror or str(_e)))
# THE LANDED FACT, and the removal facts the shrink protection measured (handed in by its wrapper), are TYPED fields of the
# record — never lines a reader has to find.
sys.stdout.write(_rec('landed', **({{'rm':os.environ['CRIA_RM']}} if os.environ.get('CRIA_RM') else {{}}), **({{'late':True}} if _late else {{}})))
'''


class WriteCommand(str):
    """The actual whole-write producer's admission facts; shell bytes are unchanged."""
    def __new__(cls, command, path, content):
        result = super().__new__(cls, command)
        object.__setattr__(result, 'path', path)
        object.__setattr__(result, 'content', content)
        return result

    def __setattr__(self, name, value):
        raise AttributeError('Write producer facts are immutable')


def _write_command(path: str, content: str, seq: "EditSequence | None" = None) -> str:
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
                                           suffix=_TMP_SUFFIX,
                                           uncertain=_b64(prompts.load('edit_mutation_unknown')),
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
    py = ownedfiles.ATOMIC_REPLACE_PROGRAM + py.replace("%%RECORD%%", resultpacket.RECORD_PY.replace("%%RCPT%%", denial.active_receipt()))
    py = _queued(py, seq)
    return WriteCommand(f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}", path, content)


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
%%RECORD%%
import fcntl,os
p=pathlib.Path(base64.b64decode('{path}').decode())
rp=pathlib.Path(os.path.realpath(str(p)))   # the file itself: a symlink is read and written THROUGH, never replaced
old=base64.b64decode('{old}').decode()
new=base64.b64decode('{new}').decode()
# ONE EDIT AT A TIME PER DIRECTORY. A coder that sends a batch of edits gets them run CONCURRENTLY by its
# harness, each in its own process, and read-modify-write on one file loses updates — and a write that
# truncates in place lets a sibling's read land on an EMPTY file and be told the text it anchored on is
# "not in the file". Walked on phi4 / Java A11 call 0016 (thirty-odd edits in one turn, twenty-odd refused
# with an empty `current`). So: take the lock, and swap the new bytes in atomically (below). The lock is on
# the directory, so it leaves nothing in the user's tree; it is released when this process exits.
_late=False
#%%SEQ%%
try:
    _lk=os.open(str(rp.parent),os.O_RDONLY); fcntl.flock(_lk,fcntl.LOCK_EX)
except OSError:
    pass
s=rp.read_text()
def _fail(mode,**kw):
    kw['mode']=mode; kw['path']=p.name; kw.setdefault('current',s)
    _b=lambda d: base64.b64encode(json.dumps(d).encode()).decode()
    _r=_b(kw)
    if len('{editfail}')+len(_r)>{cap}:
        kw.pop('current',None); _r=_b(kw)
{packblock}    # THE FACT REPORT IS A TYPED FIELD of the record (`ef`), and the batch-order note a flag (`late`): nothing for a reader to find.
    sys.stdout.write(_rec('unapplied', ef=_r, **({{'late':True}} if _late else {{}}))); sys.stdout.flush()
    sys.exit(1)
if old==new:
    _fail('identical')
_before=_v(str(p),s)
{echodef}def _w(res):
    if _before is None:                       # the file PARSES now — do not let this edit break it
        _e=_v(str(p),res)
        if _e is not None:
            _fail('would_break',err=_e)
    _inplace_started=False
    try:
        if os.stat(str(rp)).st_nlink>1:          # replacing would split the hard-linked names
            with rp.open('r+') as _stream:       # open without truncating: pre-open refusal is still nonmutating
                _inplace_started=True
                _stream.truncate(0)             # a failure from here onward has uncertain mutation
                _stream.write(res)
        else:
            _atomic_replace(rp,res.encode(),preserve=True)
    except OSError as _e:
        _template='%%UNCERTAIN%%' if _inplace_started or isinstance(_e,_TargetMutationUncertain) else '%%UNWRITABLE%%'
        if _template=='%%UNCERTAIN%%': sys.stdout.write(_rec('uncertain')); sys.stdout.flush()
        sys.exit(base64.b64decode(_template).decode().replace('%%NAME%%',p.name).replace('%%ERR%%',_e.strerror or str(_e)))
    _ev={echocall}
    sys.stdout.write(_rec('landed', **({{'ev':_ev}} if _ev else {{}}), **({{'late':True}} if _late else {{}})))
    sys.exit()
n=s.count(old)
if n==1:
    {posx}_w(s.replace(old,new,1))
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
        {posf}_w(s[:a]+new+s[m.end():])
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
elif close and new_first and len([l for l in new.split(chr(10)) if l.strip()]) == 1 and ' '.join(new_first.split()) == ' '.join(close.split()):
    # "Already done" is a fact only when the complete proposed replacement equals the complete
    # current line. Substring containment made `require x` equal `require x "v1.5.0"` and falsely
    # ordered the coder not to remove the rejected version.
    _fail('phantom',anchor=close)   # already-correct line the model misremembers
elif close:
    _fail('close',anchor=close)     # near-miss: a mistyped token
else:
    _fail('no_anchor')
'''.replace('%%LATE%%', EDIT_ORDER_LATE).replace('%%SUFFIX%%', _TMP_SUFFIX)


# THE EDIT'S RESULT, AS THE FILE NOW READS. The executor already holds the post-edit bytes, so for an
# engaged coder (`translate_outbound(edit_echo=)`) it reports the window it just wrote — the replaced span
# plus ECHO_CONTEXT lines either side, with the file's line count — as a second marker line that
# `represent_inbound` renders. It is a window, never a claim about the whole file, and it is read off the
# bytes on disk, not authored. A span too large to repeat (the coder's own new_string, already in its
# history) is shown as the two context windows around it, each lossless for the lines it names.
# Absent the flag none of this is spliced in and the command is byte-for-byte what it always was.
ECHO_CONTEXT = 3
# ONE byte bound on the whole echo: the lines shown (span + context), and — separately — the report that
# carries them (the `_fail` bound). Over it the window is dropped to the two context windows around the
# span, and over it again to the header alone, which says so. A window is never cut mid-way.
ECHO_MAX_BYTES = 3000
ECHO_WIRE_MAX_BYTES = content_reduce_mod.INLINE_RESULT_MAX_BYTES


_ECHO_DEF = r'''def _echo(res):
    a0,a1,flex=_pos
    L=res.split(chr(10))
    if res.endswith(chr(10)) or not res: L.pop()
    total=len(L)
    nl=lambda i: res.count(chr(10),0,i)+1
    first=nl(a0); last=nl(max(a0,a1-1)) if a1>a0 else first
    first=min(max(first,1),max(total,1)); last=min(max(last,first),max(total,1))
    lo=max(1,first-{ctx}); hi=min(total,last+{ctx})
    J=chr(10).join
    cands=[[[lo,J(L[lo-1:hi])]]]
    if a1>a0:
        cands.append([x for x in ([[lo,J(L[lo-1:first-1])]] if first>lo else [])+([[last+1,J(L[last:hi])]] if hi>last else [])])
    cands.append([])
    if total==0: cands=[[]]
    # THE LINES THAT NOW FOLLOW THE REPLACEMENT, MEASURED AGAINST IT. An old_string that anchors only the
    # head of a member (its signature line) while new_string carries the WHOLE member replaces that head
    # and nothing else: the old body is still in the file, directly under the new one. Counted, not
    # judged: the first lines after the span (blank ones skipped) that read the same, whitespace
    # collapsed, as one unbroken stretch of the replacement. Only a replacement longer than what it
    # replaced can leave such a remainder, and a stretch of one line (or one repeated line) is no signal.
    dup=None
    NL=new.split(chr(10))
    if NL and NL[-1]=='': NL.pop()
    OL=old.split(chr(10))
    if OL and OL[-1]=='': OL.pop()
    if len(NL)>len(OL) and a1>a0:
        _n=lambda l: ' '.join(l.split())
        N=[(first+j,_n(l)) for j,l in enumerate(NL) if l.strip()]
        F=[(last+1+k,_n(l)) for k,l in enumerate(L[last:last+len(NL)]) if l.strip()]
        best=0; bj=0
        for j in range(len(N)):
            m=0
            while m<len(F) and j+m<len(N) and N[j+m][1]==F[m][1]: m+=1
            if m>best: best=m; bj=j
        if best>=2 and len(set(t for _,t in F[:best]))>=2 and any(c.isalnum() for _,t in F[:best] for c in t):
            dup=[F[0][0],F[best-1][0],N[bj][0],N[bj+best-1][0],len(OL),len(NL)]
    def _rep(segs,omitted):
        kw=dict(first=first,last=last,total=total,flex=flex,empty=a1<=a0,segs=segs,omitted=omitted)
        if dup: kw['dup']=dup
        _b=lambda d: base64.b64encode(json.dumps(d).encode()).decode()
        _r=_b(kw)
        try:
            import zlib
            _z='{zprefix}'+base64.b64encode(zlib.compress(json.dumps(kw).encode(),9)).decode()
            if len(_z)<len(_r): _r=_z
        except Exception:
            pass
        return _r
    for i,segs in enumerate(cands):
        omitted=(not segs) and (lo<first or hi>last)
        if sum(len(t.encode()) for _,t in segs)>{maxb} and i<len(cands)-1: continue
        r=_rep(segs,omitted)
        if len(r)>{wire} and i<len(cands)-1: continue
        return r
'''


# Spliced into `_fail` only for a coder at the gate's rung (`translate_outbound(pack=)`); below it the edit
# command is byte-for-byte what it always was.
_EDIT_PACK_BLOCK = r'''    # The report is plumbing the harness keeps and counts; the coder reads cria's decoding of it. Packed
    # only when that is smaller; the drop-`current` decision above is made on the UNPACKED size, so what
    # the coder is shown never depends on whether zlib was there.
    try:
        import zlib
        _z='{zprefix}'+base64.b64encode(zlib.compress(json.dumps(kw).encode(),9)).decode()
        if len(_z)<len(_r):
            _r=_z
    except Exception:
        pass
'''


# THE COMMAND CARRIES ITS PLACE IN THE TURN. A batch of edits the harness runs concurrently must still apply in
# the order the coder sent them — a later edit is anchored on text an earlier one produces. Each edit in a
# batch that touches the same file names its predecessors (call indexes in this turn); it waits, OUTSIDE the
# directory lock, until each has left a done-mark (written at process exit, whether it applied, was refused or
# failed). A predecessor that never arrives inside the bound is not waited for further: the edit applies and
# its result says it ran early. A turn with a single edit per file carries none of this.
_EDIT_SEQ_BLOCK = r'''import time,atexit
_seq_deadline=time.monotonic()+%(wait)r
try:
    _sequence=_seq_open(%(turn)r,%(dir)r,%(participants)r,_seq_deadline)
    atexit.register(_seq_done,_sequence,%(idx)r)
    _miss=lambda: _seq_missing(_sequence,%(preds)r)
    while _miss() and time.monotonic()<_seq_deadline: time.sleep(0.05)
    _late=bool(_miss())
except (OSError,ValueError):
    _late=bool(%(preds)r)
'''


def _queued(py: str, seq: "EditSequence | None") -> str:
    """``py`` with its place in the turn's per-file queue (the ``#%%SEQ%%`` slot of an edit or whole-write program) filled in.
    A call that has no predecessors carries none of it: the slot is a comment and the program is byte-for-byte what it was."""
    if seq is None:
        return py
    turn, idx, preds, participants = seq
    return editsequence.PROGRAM + py.replace("#%%SEQ%%\n", _EDIT_SEQ_BLOCK % dict(
        dir=EDIT_SEQ_DIR, turn=turn, idx=idx, preds=list(preds),
        participants=list(participants), wait=EDIT_SEQ_WAIT_SECONDS))


def render_edit_echo(path: str, rep: "dict | None" = None) -> str:
    """The landed write's confirmation, plus the window of the file the executor reported (when it did).

    ``rep`` is the record's TYPED reports (`ev` the window report token, `late` the batch-order flag): this reads those
    fields and nothing else — no tail is searched. Everything after the confirmation is facts read off the post-edit
    bytes; a missing or unreadable report leaves the plain confirmation — saying less is allowed."""
    rep = rep or {}
    confirm = prompts.render("write_confirm", path=path)
    if rep.get("late"):
        return render_edit_echo(path, {k: v for k, v in rep.items() if k != "late"}) + "\n" + prompts.load("edit_order_late")
    for token in ([rep["ev"]] if "ev" in rep else []):
        try:
            d = editrecovery.decode_report(token)
            first, last, total = int(d["first"]), int(d["last"]), int(d["total"])
            segs = [(int(n), str(t)) for n, t in d["segs"]]
        except (ValueError, KeyError, TypeError):
            return confirm
        if d.get("empty"):
            head = prompts.render("edit_echo_removed", path=path, total=total, a=first)
        elif segs and (len(segs) == 1 and segs[0][0] <= first and segs[0][0] + segs[0][1].count("\n") >= last):
            head = prompts.render("edit_echo", path=path, total=total, a=first, b=last)
        else:
            head = prompts.render("edit_echo_span_omitted", path=path, total=total, a=first, b=last)
        parts = [confirm, head]
        dup = d.get("dup")
        if dup:
            try:
                a, b, x, y, nold, nnew = (int(v) for v in dup)
                parts.append(prompts.render("edit_echo_repeat", a=a, b=b, x=x, y=y, old=nold, new=nnew))
            except (ValueError, TypeError):
                pass
        if d.get("flex"):
            parts.append(prompts.load("edit_echo_flexible"))
        if d.get("omitted"):
            parts.append(prompts.load("edit_echo_omitted"))
        for n, t in segs:
            rows = t.split("\n")
            parts.append(prompts.render("edit_echo_window", first=n, last=n + len(rows) - 1))
            parts.append("\n".join(f"{n + i}: {r}" for i, r in enumerate(rows)))
        return "\n".join(parts)
    return confirm


def _edit_command(path: str, old: str, new: str, pack: bool = False, echo: bool = False,
                  seq: EditSequence | None = None) -> str:
    py = (_VALIDATE_FN + _EDIT_PY).format(
        echodef=(_ECHO_DEF.format(ctx=ECHO_CONTEXT, maxb=ECHO_MAX_BYTES, wire=ECHO_WIRE_MAX_BYTES,
                                     zprefix=editrecovery.PACKED_PREFIX) if echo else ""),
        echocall="_echo(res)" if echo else "None",
        posx="_pos=(s.find(old),s.find(old)+len(new),False)\n    " if echo else "",
        posf="_pos=(a,a+len(new),True)\n        " if echo else "",path=_b64(path), old=_b64(old), new=_b64(new),
                                          editfail=editrecovery.EDITFAIL,
                                          packblock=(_EDIT_PACK_BLOCK.format(zprefix=editrecovery.PACKED_PREFIX)
                                                     if pack else ''),
                                          cap=content_reduce_mod.INLINE_RESULT_MAX_BYTES)
    py = py.replace("%%RECORD%%", resultpacket.RECORD_PY.replace("%%RCPT%%", denial.active_receipt()))
    py = py.replace('%%UNWRITABLE%%', _b64(denial.mark(prompts.load("edit_unwritable"))))
    py = py.replace('%%UNCERTAIN%%', _b64(prompts.load("edit_mutation_unknown")))
    py = ownedfiles.ATOMIC_REPLACE_PROGRAM + py
    py = _queued(py, seq)
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}"


_STDOUT_SPILL_PY = r'''
def bounded_stdout(raw, receipt, directory, template, placeholder, limit):
    import hashlib, json, os, tempfile
    if stdout_size(raw) <= limit:
        return raw
    target = directory + '/stdout-' + hashlib.sha256(raw).hexdigest() + '.txt'
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stored:
            temporary = stored.name
            stored.write(raw)
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    first, separator, tail = raw.partition(b'\n')
    prefix = b''
    if receipt and separator:
        try:
            record = json.loads(first)
            if type(record.get('v')) is int and record['v'] == 1 and record.get('r') == receipt:
                prefix = first + separator
        except (ValueError, AttributeError):
            pass
    pointer = template.replace(placeholder, target).replace('{{STDOUT_CHARS}}', format(len(raw.decode('utf-8', 'replace')), ',')).encode()
    if stdout_size(prefix + pointer) > limit or receipt and not prefix:
        # An untransportable record remains intact in the saved transcript.
        # The inline refusal grants none of its unavailable reports.
        prefix = (json.dumps({'v':1, 'r':receipt, 'k':'refused'}, separators=(',', ':')) + '\n').encode() if receipt else b''
    assert stdout_size(prefix + pointer) <= limit
    return prefix + pointer
'''


def _stdout_transport(*, listing: bool = False):
    """One complete-result measurement and lossless spill program for producers."""
    from . import externalization as e
    target = webfetch.SPILL_DIR + '/stdout-' + '0' * 64 + '.txt'
    arguments = (denial.active_receipt() or '', webfetch.SPILL_DIR,
                 webfetch.stdout_spill_pointer(target, listing=listing), target, e.STDOUT_MAX_BYTES)
    return e.STDOUT_SIZE_PY + _STDOUT_SPILL_PY, arguments


def _bounded_tool_stdout(command: str, expected: str | None = None, *, listing: bool = False) -> str:
    """Bound complete owned stdout, including records and possible PTY CRs.

    The harness runs this adapter; it never reruns the producer. Static results
    that already fit keep their original command. Oversize output is saved in
    full, without the argv content cap of a cached-document upload.
    """
    from . import externalization as e
    if expected is not None and e.stdout_size(expected.encode()) <= e.STDOUT_MAX_BYTES:
        return command
    program, arguments = _stdout_transport(listing=listing)
    program += ("\nimport subprocess, sys\n"
                "process = subprocess.run(['bash', '-c', sys.argv[1]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)\n"
                "sys.stdout.buffer.write(bounded_stdout(process.stdout, *" + repr(arguments) + "))\n"
                "sys.exit(process.returncode)\n")
    return 'python3 -c ' + _qbash(program) + ' ' + _qbash(command)


def _list_command(args: dict) -> str:
    path = args.get("path") or args.get("dir") or args.get("directory") or "."
    q = _qbash(path)
    # Gather once; the complete listing and its record share the exact transport
    # limit. Large listings are saved intact rather than refused at a raw 9 KB.
    command = (f'__o=$(ls -la {q} 2>&1); __ec=$?; '
               f'if [ "$__ec" -eq 0 ]; then {denial.ran_command()}:; '
               f'else printf %s {_qbash(denial.frame(denial.REFUSED))}; fi; '
               'printf \'%s\\n\' "$__o"; exit "$__ec"')
    return _bounded_tool_stdout(command, listing=True)


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
    result, refused, status, facts = webfetch.fetch_nav_result(str(url), find=find, cursor=cursor, session=session, raw=raw,
                                                               workspace_root=workspace_root)
    # A PLAIN fetch (no find/cursor) of an oversized doc: spill the full doc to ./tmp and hand back a
    # short pointer instead of a low-signal page-1. find=/cursor= navigation returns its slice as usual.
    # …but only the FIRST time. Once cria has written the doc to the workspace that file outlives the
    # conversation, so a later plain re-fetch is answered with the file's name (fetch_nav's refusal,
    # already in `result`) instead of copying the same document over itself. Measured (run
    # 0727-104845): a 154KB docs page re-fetched NINETEEN times after the harness compacted the first
    # result away — each one re-spilling and burning a turn.
    # A repeat-gate REFUSAL comes back from fetch_nav as ordinary text, and this printf gave it
    # printf's exit 0 — the "a refused call must not report success" contradiction the module header
    # documents, at the one site that still had it. Which results are refusals is webfetch's own
    # decision, recorded on the text at the key it rendered (denial), never re-derived from wording:
    # a real 404 page is a RESULT and still exits 0 here.
    if refused:                    # the repeat gate's own typed decision — a fetched page quoting the marker is a page
        return _bounded_tool_stdout(_refusal_command(result), denial.mark(result))
    # THE FETCH'S OWN FACTS ride as a typed field of the `ran` record (`rep.fx`: url, status, routes, shapes, catalog), computed
    # from the producer's parse of the document — never re-read from the rendered page, whose body may quote any marker.
    # This is also the visibility receipt's complete response contract: every HTTP response has fx,
    # even a 404/empty body. RAN without fx means the attempt returned no HTTP response (status=None),
    # not that it was refused or that a document has since been evicted from the cache.
    output = denial.frame(denial.RAN, rep={'fx': facts} if facts else None) + result
    return _bounded_tool_stdout(f"printf %s {_qbash(output)}", output)



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
def _survey_after_first_record(cmd: str, ride: str) -> str:
    """``cmd`` and its survey, composed so the survey's record is the VERY NEXT record after the command's own first record.

    A write or edit prints its first record (`landed` / `unapplied` / ...) and then its own lines; the survey must run AFTER
    the command (it reports the post-write tree). The command's combined output is therefore held in a shell variable, its
    first line (record 1) is printed, the survey prints its record, and the rest of the command's own output follows — so a
    reader never has to look past record 1 for the survey, and never searches for it. The exit status is the command's own,
    saved before and restored last (the survey wrapper preserves it too). Only cria's OWN lowered commands are composed this
    way; a native command is never wrapped."""
    return ("__cria_o=$( { " + cmd + "\n} 2>&1 )\n"
            "__cria_ec=$?\n"
            "printf '%s\\n' \"${__cria_o%%$'\\n'*}\"\n"
            "( exit $__cria_ec )\n"
            + ride + "\n"
            "case \"$__cria_o\" in *$'\\n'*) printf '%s\\n' \"${__cria_o#*$'\\n'}\" ;; esac\n"
            "exit $__cria_ec")


SPILL_CONTENT_MAX = content_reduce_mod.SPILL_CONTENT_MAX


def _spill_command(target: str, content: str, msg: str, *, operation=None) -> str:
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
    body, note = _spill_body(content)
    # THE STORED FACT IS A TYPED FIELD of the `ran` record printed once the file has landed (the `then` branch): the producer
    # declares it, so no reader looks for a marker line in a tail a page could end with.
    stored = None
    if operation is not None:
        raw = body.encode('utf-8')
        stored = dict(operation=operation, target=target, byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    command = (f"if mkdir -p {_qbash(tdir)} && base64 -d > {_qbash(target)} <<'__CRIA_SPILL__'\n"
               f"{_b64_wrapped(body)}\n__CRIA_SPILL__\n"
               f"then printf %s {_qbash(denial.frame(denial.RAN, rep={'st': stored} if stored else None) + msg + (chr(10) + note if note else ''))}")
    output = denial.frame(denial.RAN, rep={'st': stored} if stored else None) + msg + (chr(10) + note if note else '')
    return _bounded_tool_stdout(command + '; else exit 1; fi', output)


def _spill_body(content: str) -> tuple[str, str]:
    """Existing labelled command-budget extent, shared by producer and observation."""
    body, note = content, ''
    if len(content.encode('utf-8', 'replace')) > SPILL_CONTENT_MAX:
        body = content.encode('utf-8', 'replace')[:SPILL_CONTENT_MAX].decode('utf-8', 'ignore')
        note = prompts.fill(prompts.load('spill_cut'), kept=f'{len(body):,}', total=f'{len(content):,}')
        body += '\n\n' + note
    return body, note


def _b64_wrapped(s: str, width: int = 76) -> str:
    """base64 of ``s``, line-wrapped. `base64 -d` accepts one long line on GNU coreutils and rejects
    it on some BSD builds; wrapping is what every base64 encoder emits by default and works on
    both."""
    raw = _b64(s)
    return "\n".join(raw[i:i + width] for i in range(0, len(raw), width))


def _under_spill_dir(path: str) -> bool:
    """True when ``path`` lands in cria's read-only spill scratch (:data:`webfetch.SPILL_DIR`) — a
    reference doc cria saved, which the model must GREP, not read-whole or edit."""
    return filecommands._under_spill_dir(path, webfetch.SPILL_DIR)


def _spill_relpath(path: str) -> str | None:
    """The workspace-relative spill path when ``path`` names a SPILL_DIR file via a ROOT-ABSOLUTE
    ``/tmp/read-only/x`` form — the model dropped the leading ``./`` (wrote ``/tmp/read-only/x`` for
    ``./tmp/read-only/x``), which the dirguard then blocks as external, so the model can never re-read
    the doc cria saved (the live footgun: a fetched spec sitting unreadable on disk). Return
    ``./tmp/read-only/x``; ``None`` otherwise. Only the root-absolute spill form is redirected — a path
    that merely CONTAINS ``tmp/read-only`` deeper in some other tree is left alone."""
    return filecommands._spill_relpath(path, webfetch.SPILL_DIR)


def _respill_command(command: str) -> str:
    """Root-absolute spill references inside a RAW command string, rewritten to the real
    workspace-relative form — the command-string twin of :func:`_spill_relpath`. ``read_file`` on
    ``/tmp/read-only/x`` was silently redirected while the SAME string in a grep/cp was dirguard-
    refused; shown both, the model learned "the sandbox blocks this file" and burned ~130 calls on
    it (run 0729-gemma4 pon2; ~25 more in poff-C1). cria controls the spill dir name, so the
    rewrite is exact — only a token that STARTS at the filesystem root is touched."""
    return filecommands._respill_command(command, webfetch.SPILL_DIR)


# WHAT A TITLE CANNOT CARRY. A description earns its place inline when it names something callable:
# a backticked span, a namespaced name (`ISO3166::Country`), a leading-hash method (`#in_eu?`), a
# receiver call (`c.in_eu?`, `decimal.NewFromFloat(`), or a bare empty call (`in_eu?()`). Package
# names are deliberately NOT in this set — those are the snippet poison the drop was written for,
# and the title already carries them.
#
# A SHAPE, not a language list (#20): every one of these forms is punctuation between word
# characters, and Ruby, Go, Java, Rust and Python all write callables that way.
_API_NAME_SHAPE = r"`[^`]+`|\w+::\w+|(?<![\w#])#\w+|\w+\.\w+[?!(]|\w+[?!]\(|\w+\(\)"


def _pyq(s: str) -> str:
    """A Python string literal safe to embed inside the single-quoted `python3 -c '...'` body.

    json.dumps handles the Python side — backslashes, newlines, double quotes. It does NOT escape an
    APOSTROPHE, and an apostrophe is the one character that ends the shell's quoting: a note reading
    "each page\u0027s description" closed the `-c '` early and bash died on the rest of the line. So
    every `\u0027` is re-encoded as a unicode escape, which Python decodes back to an apostrophe and
    the shell never sees at all."""
    import json as _json
    return _json.dumps(s).replace("'", "\\u0027")


def _search_command(args: dict, brave_key: str, *, search_offer=None, operation=None) -> str:
    """Brave web search lowered to a curl — endpoint, %-encoded query, and headers come from the
    shared `brave` module (same request the planner's in-process search builds), then parsed to
    compact "title / url / description" lines the model can pair with web_fetch. Requests Brave's
    per-request maximum and prints EVERY returned result (no display slice) with a total-count header
    so the authoritative page — which may rank 9th+ — reaches the model and it knows how many exist."""
    query = str(args.get("query") or "")
    # Composed before the parse below, which needs both: the spill path to write, and the pointer to
    # print when the brief listing does not fit inline.
    if search_offer is not None:
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
    inline_note = (prompts.fill(prompts.load("search_inline_note"), target=target, query=query)
                   if search_offer is not None else '')
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
    #
    # …EXCEPT A DESCRIPTION THAT CARRIES AN API NAME, which a title cannot. The poison the drop was
    # written against was a wrong PACKAGE name — and a title carries the package. A method name, a
    # predicate or a constant only ever appears in the description.
    #
    # Walked on the sub-40 pass, shipping-rates-rb x nemotron-elastic. The model's FIRST search,
    # ninety seconds into the run, returned the whole task as its first result's description:
    # `European Union Membership · c.in_eu? #=> false`. cria wrote that to disk, showed the model
    # twenty titles, and closed with "you do not have to open it". The model then spent fifteen
    # minutes on nine more searches for a gem whose method name it had already been handed, and
    # never opened the file — zero tool calls in 89 touched the spill directory, and four of the
    # nine saved files contain `in_eu?`. Measured over those nine files, the rule below keeps 9 of
    # 20 descriptions on the search that mattered (3,054 characters) and 250-1,750 on the rest.
    script = (resultpacket.RECORD_PY.replace("%%RCPT%%", denial.active_receipt()) +
              'import sys,json,os,re,hashlib\n'
              'd=json.load(sys.stdin)\nr=(d.get("web") or {}).get("results") or []\n'
              'e=d.get("error") or d.get("message")\n'
              'full="\\n".join("%s\\n  %s\\n  %s"%(x.get("title",""),x.get("url",""),x.get("description","")) for x in r)\n'
              'stored=("%d results:\\n"%len(r))+full\n')
    if search_offer is None:
        script += 'print(stored if r else "search API error: "+json.dumps(e) if e else "no results")\n'
    else:
        script += ('T=' + repr(search_offer.target) + '\n'
                   'K=re.compile(' + repr(_API_NAME_SHAPE) + ')\n'
                   'api=lambda x:("\\n  "+(x.get("description") or "")) if K.search(x.get("description") or "") else str()\n'
                   'brief=("%d results:\\n"%len(r))+"\\n".join("%s\\n  %s%s"%(x.get("title",""),x.get("url",""),api(x)) for x in r)+"\\n"+' + repr(inline_note) + '\n'
                   'pointer=' + repr(msg) + '\n'
                   'os.makedirs(os.path.dirname(T) or ".",exist_ok=True)\n'
                   'with open(T,"w",encoding="utf-8") as f:\n    f.write(stored)\n'
                   'raw=stored.encode("utf-8")\n'
                   # the stored fact is a TYPED field of the program's own first record, printed before the results
                   'sys.stdout.write(_rec("ran", st={"operation":' + repr(operation) + ',"target":T,"byte_count":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}))\n'
                   'print(' + search_offer.program.expression + ') if r else print("search API error: "+json.dumps(e) if e else "no results")\n')
    # Keep the parser as the actual pipeline consumer. Its complete first
    # record and answer share the same transport check as the other producers.
    import textwrap
    transport, transport_arguments = _stdout_transport()
    if search_offer is None:
        # This branch's first record remains shell-owned. Charge it to the
        # same complete-result limit without making the parser emit it twice.
        from . import externalization as e
        transport_arguments = ('', *transport_arguments[1:-1],
                               e.STDOUT_MAX_BYTES - e.stdout_size(denial.frame(denial.RAN).encode()))
    script = (transport + '\nimport io, sys\ndef _produce():\n' + textwrap.indent(script, '    ')
              + "\nbuffer = io.StringIO()\noriginal_stdout = sys.stdout\n"
              + "try:\n    sys.stdout = buffer\n    _produce()\nfinally:\n    sys.stdout = original_stdout\n"
              + "sys.stdout.write(bounded_stdout(buffer.getvalue().encode(), *" + repr(transport_arguments) + ").decode())\n")
    parse = 'python3 -c ' + _qbash(script)
    # Save the (noisy) results to the read-only spill dir and hand back a grep/line-read pointer, instead
    # of inlining snippet poison. The lowered command carries the web_search sentinel (translate_outbound),
    # so re-presentation swaps it back to web_search — the model never sees this curl/tee plumbing.
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
    # With a search offer the PROGRAM prints the first record (it carries the stored fact); otherwise the shell does.
    lead = "" if search_offer is not None else denial.ran_command()
    command = (f"{lead}curl -sL --max-time {_FETCH_TIMEOUT_S} {header_flags} {_qbash(url)} | {parse} "
               f"|| printf %s {_qbash(denial.frame(denial.RAN) + fallback if search_offer is not None else fallback)}")
    return command




# Lowered tools whose own result is ONE bounded line, so appending the workspace survey to them
# cannot push the model's own content past the harness's output cap. Reads, fetches and searches
# are deliberately absent — see the ride-along note in translate_outbound.
#
# AND SO IS `list_dir`, WHICH WAS HERE AND IS NOT ONE LINE. Its lowering caps the listing at
# READ_INLINE_MAX (9,000 bytes) and the survey it carried measured 6.6-10 KB, so a single result
# could reach ~19 KB — well past the ~10 KB a harness keeps. The harness then cut the middle, which
# is exactly where the survey's head sits; `apply_survey` refused the remains (entry count no longer
# matches the records that survived) and the workspace view went stale for the rest of the session.
# Measured across the 144-cell engagement ladder: 449 refused surveys in 11 cells, and the refusals
# track the harness's own cut markers almost one for one — 94/94, 46/47, 29/29, 17/17. Eight of the
# eleven are L5 runs, where the gate and the assists are the readers that lose the view.
#
# Each half was bounded and their SUM was not, which is the whole bug. Writes and edits really do
# answer in one line, so they keep carrying it; a `list_dir` changes nothing on disk, so a view that
# waits for the next write is not stale about anything that happened in between.
_SURVEYABLE = _WRITE_NAMES | _EDIT_NAMES

# How many surveyable calls pass between surveys once the view is populated. The tree is re-walked
# on the harness's side each time, so this is a cost on the CODER's box, not cria's; four is often
# enough to see the file the coder wrote two turns ago without re-listing the repo every turn.
SURVEY_EVERY = 4
_SURVEY_SEQ: dict[str, int] = {}


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


def _edit_sequence(tool_calls: list, injected: set) -> dict:
    """``{call index: (group token, index, predecessor indexes, all participant indexes)}`` for the file-mutating calls (edits AND
    whole-file writes) of ONE turn that share a file with an earlier such call of the same turn. Everything else is absent: a lone
    mutation per file runs unqueued.

    A WRITE QUEUES TOO. The harness runs a batch concurrently, and a whole-file write is the one call that REPLACES what its
    predecessors produced: `write f; edit f` run edit-first anchors on the old file, and `write f=A; write f=B` run B-first leaves
    A on disk while the coder, the ledger and every later fact say B. Each program leaves its own authenticated done-mark at exit
    (the producer-issued, invocation-bound completion fact), so ordering is enforced where the writer runs, not inferred from where
    the replies land."""
    by_path: dict[str, list[int]] = {}
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function") or {}
        if fn.get("name") not in (_EDIT_NAMES | _WRITE_NAMES) or fn.get("name") not in injected:
            continue
        args = _parse(fn.get("arguments"))
        path = _tool_path(args)
        if not path:
            continue
        queued = ((isinstance(args.get("old_string"), str) and args["old_string"] and "new_string" in args)
                  if fn.get("name") in _EDIT_NAMES else not _prepare_file_mutation(fn.get("name"), args).error)
        if queued:
            by_path.setdefault(os.path.normpath(str(path)), []).append(i)
    group = [ix for ix in by_path.values() if len(ix) > 1]
    if not group:
        return {}
    nonce = uuid.uuid4().hex     # per translation: a resent identical batch can never see an earlier batch's marks
    out: dict = {}
    for ix in group:
        token = hashlib.sha1((nonce + str(ix)).encode()).hexdigest()[:16]
        for n, i in enumerate(ix):
            out[i] = (token, i, ix[:n], ix)
    return out


def _lower_synthetic(source: OutboundCall) -> ShellCommand | dict | None:
    """Required harness adapters, independent of optional steering selection.

    Validating mutation arguments and preserving execution/correlation are not
    advice. Disabling a protection never turns missing content into an empty write.
    """
    name, args, request = source.name, source.arguments, source.request
    if name in (_WRITE_NAMES | _EDIT_NAMES) and name in request.injected:
        mutation = _prepare_file_mutation(name, args)
        if mutation.error:
            return ShellCommand(_file_mutation_refusal(name, mutation, request.injected, source.log))
        if name in _WRITE_NAMES:
            command = _write_command(str(mutation.path), _repair_double_escaped(mutation.content), seq=source.sequence)
        else:
            command = _edit_command(str(mutation.path), mutation.old, mutation.new,
                pack=request.pack, echo=request.edit_echo, seq=source.sequence)
        command = toolstages.current().mutation_command(source, command)
        # Explicit, unbound library callback compatibility only. Production uses
        # typed factual services; a bound selection never falls back to a whole
        # legacy policy callback, even when its selected source has no services.
        if (not toolstages.is_bound() and request.shrink_services is None
                and request.shrink_check is not None and name in _WRITE_NAMES):
            edits = request.injected & _EDIT_NAMES
            finding = request.shrink_check(str(mutation.path), _repair_double_escaped(mutation.content),
                                           sorted(edits)[0] if edits else '')
            if finding:
                command = wrap_finding(str(mutation.path), finding, command,
                                       _seq_release(source.sequence) if source.sequence is not None else "")
                if source.log is not None:
                    event = 'writeproxy.write_removal_facts' if finding.get('land') else 'writeproxy.write_shrink_held'
                    source.log.emit(event, tool=name, path=str(mutation.path))
        return ShellCommand(command)
    if name in _READ_NAMES and name in request.injected:
        command = _read_command(args)
        return ShellCommand(command, multipart_kind='read') if command is not None else None
    elif name in _LIST_NAMES and name in request.injected:
        command = _list_command(args)
    elif name in _FETCH_NAMES and name in request.injected:
        command = _externalize_coder(source)
    elif name == 'web_search':
        if name in request.injected and request.brave_key:
            command = _externalize_coder(source)
        elif request.native_search and request.native_search != name:
            return {**source.call, 'function': {**source.function, 'name': request.native_search}}
        else:
            return None
    else:
        return None
    return ShellCommand(command) if command is not None else None


def translate_outbound(completion: dict, shell_tool: dict, rlog=None, injected: set[str] | None = None,
                       brave_key: str | None = None, native_search: str | None = None,
                       session: str | None = None, workspace_root: str | None = None,
                       external_dir_permission: str = "write", unread_target=None,
                       shrink_check=None, pack: bool = False, edit_echo: bool = False,
                       declared_roots: tuple = (), *, shrink_services: ShrinkServices | None = None,
                       observe_lowering=None, externalization_owner=None,
                       observe_externalization=None, multipart_command=None, multipart_new_id=None,
                       observe_multipart_fallback=None) -> dict:
    """Lower cria's synthetic tool calls to shell commands the harness runs, each stamped with the
    stateless re-presentation sentinel. Only lowers a tool cria INJECTED (a harness-native tool of
    the same name is the harness's to run). ``web_search`` routes to ``native_search`` when the
    harness has one, else to a Brave curl (when injected).

    ``shrink_services`` supplies factual services to the selected F15 source.
    ``shrink_check`` is retained only for explicit unbound library callers; a
    bound request never consults that legacy whole-policy callback.

    """
    injected = injected or set()
    from . import assistruntime
    request = LoweringRequest(frozenset(injected), brave_key, native_search, session, workspace_root,
        external_dir_permission, unread_target, shrink_check, pack, edit_echo, declared_roots, shrink_services,
        externalization_owner, assistruntime.current().externalization, observe_externalization,
        (assistruntime.current().document_guidance, webfetch.guidance_services()))

    for choice in completion.get("choices", []):
        tool_calls = (choice.get("message") or {}).get("tool_calls")
        if not tool_calls:
            continue
        rebuilt: list[dict] = []
        edit_seq = _edit_sequence(tool_calls, injected)
        for ti, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            name = fn.get("name")
            direct_synthetic_read = name in _READ_NAMES or name in _WRITE_NAMES
            call_request = request
            from .multipartcontext import take
            alias = take(tc)
            if alias is not None and is_shell_tool_name(name):
                # A privately held identity from the normalization producer,
                # not a declaration guessed out of model-supplied shell text.
                tc = {**tc, 'function': {'name':'read_file', 'arguments':alias}}
                fn = tc['function']
                name = 'read_file'
                call_request = replace(request, injected=request.injected | _READ_NAMES)
                direct_synthetic_read = True
            # Early normalization may already have lowered a read alias to shell.
            # Recompile its declared original read with this call's receipt, without
            # treating ordinary native shell calls as synthetic reads.
            if is_shell_tool_name(name):
                original = original_call(_command_of(fn.get("arguments") or ""))
                if original is not None and original.get("name") in _READ_NAMES:
                    fn = original
                    tc = {**tc, "function": fn}
                    name = fn.get("name")
                    call_request = replace(request, injected=request.injected | _READ_NAMES)
            args = _parse(fn.get("arguments"))
            # THE CORRELATION TOKEN FOR THIS CALL, derived once and held while its command is composed: every
            # program authored inside prints it in its typed result record, which is the first line of stdout; the
            # sentinel below declares it (and any survey record), and `represent_inbound` accepts a result as cria's
            # own only by POSITION (the leading record) plus a recomputed canonical correlation — never by finding
            # the marker or the token anywhere in the text.
            receipt = denial.receipt_for(tc.get("id"), name, fn.get("arguments"))
            declaration = denial.Declaration()      # what this call's compiler declares for its sentinel (a survey record)
            with denial.receipt_scope(receipt, declaration):
                tc, args, effect = toolstages.current().outbound_call(
                    OutboundCall(tc, args, call_request, edit_seq.get(ti), rlog))
                fn = tc.get("function") or {}
                name = fn.get("name")
                if effect is None:
                    effect = _lower_synthetic(OutboundCall(tc, args, call_request, edit_seq.get(ti), rlog))
            if isinstance(effect, dict):
                rebuilt.append(effect)
                if observe_lowering is not None:
                    observe_lowering(tc, effect, None)
                continue
            cmd = effect.command if effect is not None else None
            proposed_write = cmd if isinstance(cmd, WriteCommand) else None
            read_in_place = effect.read_in_place if effect is not None else False
            if cmd is not None:
                if (multipart_command is not None and direct_synthetic_read
                        and effect.multipart_kind and receipt == denial.receipt_for(tc.get('id'), name, fn.get('arguments'))):
                    from .multipart import BridgeError
                    from .filecommands import MultipartCommandTooLarge
                    original_tc, original_receipt, original_cmd = tc, receipt, cmd
                    if multipart_new_id is not None:
                        tc = {**tc, 'id': multipart_new_id()}
                        receipt = denial.receipt_for(tc.get('id'), name, fn.get('arguments'))
                    try:
                        replacement = multipart_command(tc, effect, receipt)
                    except (BridgeError, MultipartCommandTooLarge) as exc:
                        tc, receipt = original_tc, original_receipt
                        replacement = None
                        if rlog is not None:
                            rlog.emit('multipart.register_failed', level='warn', error=str(exc))
                    if replacement is not None:
                        cmd = replacement
                        if observe_multipart_fallback is not None:
                            fallback = original_cmd
                            if ti in edit_seq and EDIT_SEQ_DIR not in fallback:
                                fallback = _seq_release(edit_seq[ti]) + fallback
                            fallback_call = _shell_call(original_tc.get('id'), shell_tool,
                                f"{_sentinel(name, fn.get('arguments'), original_receipt, declaration.survey)}\n{fallback}", 0)
                            observe_multipart_fallback(tc.get('id'), fallback_call)
                # RIDE ALONG. cria has no synchronous channel to the harness — it can ask the
                # workspace a question only by putting a command in the reply it is already
                # sending. This is that reply. The survey is appended to write/edit/list
                # translations, whose own output is one bounded line, and NEVER to a read or a
                # fetch: those results are already large, and pushing one past the harness's own
                # output cap would cut the CODER's content to pay for cria's instrumentation.
                # `represent_inbound` strips it back out, so the model sees its own call's result
                # and nothing else.
                # A read answering a write carries no survey: its result is the whole file, and
                # instrumentation must not add to the coder's output.
                if name in _SURVEYABLE and not read_in_place and _survey_due(session, name):
                    # BUDGETED for this one-result ride-along. The completion gate no longer shares
                    # this arithmetic: it carries the survey and probe evidence in checked pages.
                    # Riding along without one is how cria's instrumentation came to push a result
                    # past what a harness keeps — and the half the harness then cut was the MODEL'S
                    # content, on a result cria itself composed. cria does not truncate; asking for
                    # more than a result's worth let something else do it on cria's behalf, which
                    # the never-truncate rule covers just the same.
                    # The survey leaves as a typed record whose body costs up to 4/3 of its text on the wire (the codec
                    # picks the shortest of text / zlib / base64): budget the ENCODED record, not the raw tree.
                    room = resultpacket.max_text_for_wire(content_reduce_mod.INLINE_RESULT_MAX_BYTES
                                                          - _RIDE_ALONG_HOST_RESERVE - _RIDE_ALONG_COMMAND_RESERVE)
                    if room >= wsview.TREE_MIN_BYTES:
                        with denial.receipt_scope(receipt, declaration):      # the survey record follows THIS call's first record
                            ride = wsview.survey_command(session or '', cd=workspace_root or '', budget=room, pack=pack)
                        cmd = _survey_after_first_record(cmd, ride)
                    elif rlog is not None:
                        rlog.emit("wsview.survey_not_carried", level="info", left=room,
                                  need=wsview.TREE_MIN_BYTES)
                if ti in edit_seq and EDIT_SEQ_DIR not in cmd:   # answered without running the edit: release the queue
                    cmd = _seq_release(edit_seq[ti]) + cmd
                rebuilt.append(_shell_call(tc.get("id"), shell_tool,
                                           f"{_sentinel(name, fn.get('arguments'), receipt, declaration.survey)}\n{cmd}",
                                           0))
                pending = (getattr(externalization_owner, 'externalization_offers', None) or {}).get(str(tc.get('id') or ''))
                if pending is not None:
                    pending.lowered_arguments = rebuilt[-1]['function']['arguments']
                    pending.lowered_name = rebuilt[-1]['function']['name']
                    pending.lowered_type = rebuilt[-1].get('type')
                    if observe_externalization is not None:
                        observe_externalization(tc, rebuilt[-1], pending)
                if observe_lowering is not None:
                    observe_lowering(tc, rebuilt[-1], proposed_write)
                if rlog is not None:
                    # `target`/`detail` feed the LIVE status ticker — the harness renders the lowered
                    # call as an opaque sentinel blob (operator: "a file wrote to the project, but
                    # there was no indicator"), so the ACTION is narrated here in cria's own voice.
                    rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "",
                              detail=str(args.get("query") or args.get("url") or ""))
            else:
                rebuilt.append(tc)
                if observe_lowering is not None:
                    observe_lowering(tc, tc, None)
        choice["message"]["tool_calls"] = rebuilt
    return completion


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
    envelope = exec_envelope(content)
    if envelope is not None:
        head, payload = content[:envelope.payload_start], content[envelope.payload_start:]
        if not content_reduce_mod.looks_binary(payload):
            return content
        return head + _binary_fact(payload)
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


def _redact_carrying_boundary(m: dict, key: str, reds: list[str]):
    """Scrub ``m[key]``; when cria stamped a payload boundary on it, scrub payload and annotation SEPARATELY and
    re-stamp over the redacted payload, so provenance survives the rewrite (a rewrite that changes the content
    must carry the boundary forward). An unverifiable boundary is left as it is — the reader abstains."""
    v = m[key]
    if key == "content" and isinstance(v, str) and bodykeys.PAYLOAD_BOUNDARY in m:
        pay = payload_of(m, v)
        if pay is not None:
            head = _scrub(pay, reds)
            m[bodykeys.PAYLOAD_BOUNDARY] = (len(head), _digest(head))
            return head + _scrub(v[len(pay):], reds)
    return _scrub(v, reds)


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
                m2[key] = _redact_carrying_boundary(m2, key, reds)
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


def _payload_offset(content: str) -> int:
    """The protocol owner's positional record boundary, or stdout offset zero when unframed."""
    envelope = exec_envelope(content)
    return envelope.record_start if envelope is not None else 0


class _Proof(NamedTuple):
    """What cria's own records PROVED about one paired lowered result (see :func:`_frame_proofs`)."""
    kind: str | None          # the first record's branch kind, or None (no record: unknown)
    content: str              # the result with cria's records removed. A body-bearing record's result is
                              # `pre + body + tail` with the harness envelope dropped; anything else keeps the envelope
    text: str | None          # the body's decoded text when the first record carried a verified body, else None
    exact: bool               # `text` is the body's EXACT bytes (valid UTF-8, and nothing follows it): cacheable
    survey: str               # the survey text the declared second record carried, "" when none
    rep: dict | None = None   # the first record's typed reports (`resultpacket.REPORT_KEYS`), or None
    observe: str = ""         # what the verified body is: `whole` (the file) or `range` (a numbered window of it)
    pre: str = ""             # exact producer-authored prelude, not inferred from file text


def _frame_proofs(messages: list[dict]) -> dict[str, _Proof]:
    """``tool_call_id -> _Proof`` for every call whose pairing is UNAMBIGUOUS (`denial.paired_results`: one call, one
    result after it) and whose STORED command declared a receipt in cria's sentinel.

    AUTHORITY IS POSITION AND DECLARATION (`resultpacket`): the first record is the line at offset 0 of the stdout
    (after the harness's own envelope); the second exists only if the sentinel declared a survey and is read only on the
    very next line. Nothing is searched for — a file, a page or a native command that quotes records, receipts, markers or
    a valid-looking survey is just the opaque tail and keeps every byte. A valid first record stands when the second is
    missing or cut. No record at offset 0 (a legacy command, a cut, an unlowered shape) means UNKNOWN: untouched."""
    paired = denial.paired_results(messages)
    from .multipart import UnverifiedCarrier
    out: dict[str, _Proof] = {}
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            cid, fn = tc.get("id"), tc.get("function") or {}
            if cid not in paired or not is_shell_tool_name(fn.get("name")):
                continue
            command = _command_of(fn.get("arguments"))
            declaration = _declaration(command, cid)
            if declaration is None or not declaration.get("rcpt"):
                continue
            token = str(declaration["rcpt"])
            paired_result = paired[cid]
            if isinstance(paired_result.get(bodykeys.MULTIPART_UNVERIFIED), UnverifiedCarrier):
                continue
            content = str(paired_result.get("content") or "")
            off = _payload_offset(content)
            first = resultpacket.read_record(content, off, token)
            if first is None:
                continue
            at, survey = first.end, ""
            if declaration.get("sv") == 1 and (second := resultpacket.read_record(content, at, token, survey=True)) is not None:
                at = second.end
                if second.body is not None:
                    try:
                        survey = second.body.decode("utf-8")
                    except UnicodeDecodeError:
                        survey = ""
            tail = content[at:]
            if first.body is None:
                if first.kind == denial.UNAPPLIED and first.rep and "ef" in first.rep:
                    # the edit program's fact report is a TYPED field; the directive input is composed from it here, by cria,
                    # so no payload byte can stand in for it
                    tail = ((EDIT_ORDER_LATE + "\n" if first.rep.get("late") else "")
                            + editrecovery.EDITFAIL + first.rep["ef"] + "\n" + tail)
                out[cid] = _Proof(first.kind, content[:off] + first.pre + tail, None, False, survey, first.rep)
                continue
            try:
                text, exact = first.body.decode("utf-8"), True
            except UnicodeDecodeError:
                text, exact = first.body.decode("utf-8", "replace"), False
            out[cid] = _Proof(first.kind, first.pre + text + tail, text, exact and tail == "", survey, first.rep, first.observe, first.pre)
    return out






# THE HARNESS'S OWN TRUNCATION MARKER, in either unit. Codex writes `…N chars truncated…` /
# `…N tokens truncated…` into a tool result it decided was too big to keep whole. Other harnesses
# will spell it differently; this matches the shape, and anything it misses stays silent (#3).
_HARNESS_CUT = re.compile(r"…\s*([\d,]+)\s+(chars|tokens)\s+truncated\s*…")
# THE OTHER SHAPE THE SAME HARNESS EMITS. Codex writes an inline `…N tokens truncated…` into a
# result it cut in the MIDDLE, and a leading `Warning: truncated output (original token count: N)`
# on one it cut at the END. Only the first was counted, so every end-cut result was a cut cria never
# observed at all — and the strip used to remove the warning, so nothing downstream could see it
# either. The count it carries is the ORIGINAL size, not the amount removed; that difference is
# recorded in the event rather than papered over.
_HARNESS_CUT_HEAD = re.compile(r"^Warning: truncated output(?:\s*\(original token count:\s*([\d,]+)\))?",
                               re.M)


def note_harness_cuts(messages: list, rlog=None) -> int:
    """Count tool results the HARNESS truncated before cria ever saw them, and say so in the log.

    Nothing is altered and no new text reaches the model. The returned fact also prevents a
    known-cut whole read from being cached as a complete file by represent_inbound.

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
        body = str(m.get("content") or "")
        for hit in _HARNESS_CUT.finditer(body):
            n += 1
            if rlog is not None:
                rlog.emit("harness.truncated_a_result", level="warn",
                          amount=hit.group(1), unit=hit.group(2))
        for hit in _HARNESS_CUT_HEAD.finditer(body):
            n += 1
            if rlog is not None:
                rlog.emit("harness.truncated_a_result", level="warn", where="tail",
                          original=hit.group(1) or "unstated", unit="tokens")
    return n


def _native_effect_unknown_or_mutating(function, workspace_root):
    """No successful execution is inferred. Only supported read contracts exempt facts.

    Names merely resembling readers have no read-only contract here. Shell
    commands use the existing no-writes proof, rather than a mutation-keyword scan.
    """
    name = function.get('name')
    if is_shell_tool_name(name):
        return not dirguard.command_only_reads(_command_of(function.get('arguments')), workspace_root, no_writes=True)
    if name in (_READ_NAMES | _LIST_NAMES):
        return False
    return True



def represent_inbound(messages: list[dict], rlog=None, workspace_root: str | None = None,
                      sess_key: str = "", tools_present: bool = True) -> list[dict]:
    """Swap cria's shell translations back to the tool the model actually called — read STATELESSLY
    from the sentinel in each stored command, so it survives a restart. Every SYNTHETIC tool is lowered
    to a shell exec, so its result comes back wrapped in the harness exec envelope (Chunk ID / Process
    exited / Output: / …). That envelope is stripped from read/nav results (read_file, list_dir,
    web_fetch, web_search) and from write/edit FAILURES so the tool reads as its own abstraction, not a
    disk-caching shell command. A write/edit SUCCESS is reframed as a clean confirmation (never over a
    real error). A harness ``local_web_search`` is re-presented as ``web_search``. The model's OWN
    exec_command calls keep their envelope — there the shell framing is the truth.

    ``sess_key`` is the session identity Candidate C40's delivered-state remembers against; without
    it that mechanism never fires (no identity to remember delivery against). ``tools_present=False``
    marks a harness compaction/summarize turn (empty tool menu) -- C40 skips those entirely."""
    # Retired client-supplied hint spellings are never provenance, regardless
    # of message role. Only the typed current owner marker can withhold proof.
    messages = [{k: v for k, v in m.items() if k not in bodykeys.LEGACY_MESSAGE_KEYS}
                if isinstance(m, dict) else m for m in messages]
    note_harness_cuts(messages, rlog)   # observe only: did the harness cut anything before cria saw it?
    out: list[dict] = []
    rejected_notes_by_id: dict[str, str] = {}
    swapped = 0
    # WHICH CALLS FAILED, known before the assistant turn is emitted. A rejected edit_file keeps its
    # arguments in the replayed history, and `old_string` is the model's own idea of the file —
    # formatted exactly like a file listing, sitting closer to the generation point than the real
    # content. Measured on the six-language battery: at nemotron cart-billing-go 0021 the coder read
    # its own rejected old_string back as authority — "the earlier snippet we saw in the instruction
    # shows the Item struct with ID, Name, PricePerUnit … Perhaps the original code is missing; we
    # need to restore that structure" — and rebuilt a file that never existed. The asymmetry is the
    # bug: fabrications persisted verbatim while verified content was dropped by compaction.
    # PAIRING GOVERNS EVERY RESULT-SPECIFIC FACT, not only the outcome: a result is attributed to a call (its path,
    # its payload, its envelope handling, the file fact it would cache) only when the id names exactly one call and
    # one result after it (`denial.paired_results`). An ambiguous result keeps its actual bytes and teaches nothing.
    paired = set(denial.paired_results(messages))
    from .multipart import UnverifiedCarrier
    proofs = _frame_proofs(messages)
    outcomes = {tid: p.kind for tid, p in proofs.items() if p.kind in (denial.REFUSED, denial.UNAPPLIED)}
    landed_ids = {tid for tid, p in proofs.items() if p.kind == denial.LANDED}   # cria's own program reported the mutation landed
    uncertain_ids = {tid for tid, p in proofs.items() if p.kind == denial.UNCERTAIN}
    called_ids = {tc.get("id") for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
                  for tc in (m.get("tool_calls") or []) if isinstance(tc, dict) and tc.get("id")}
    ambiguous = called_ids - paired    # a call exists but the id does not name exactly one call and one result after it
    lowered_ids: set[str] = set()     # calls cria itself lowered (their result carries cria's frame, or is unknown)
    failed_ids = set(outcomes)          # proven: cria's own refusal ran, or its edit program reported 'not applied'
    write_paths: dict[str, str] = {}  # tool_call_id -> path, for the success reframe / failure strip
    strip_ids: set[str] = set()       # read/nav re-presented tool ids → strip the harness exec envelope
    own_cmds: dict[str, str] = {}     # tool_call_id -> the model's OWN raw command, for the blind-pipe note
    # WHAT THIS PASS TEACHES THE WORKSPACE VIEW. cria lowered every one of these calls, so it knows
    # the path and (for a whole write) the exact bytes — the workspace's own contents, proved by the
    # harness's own confirmation rather than inferred from the model's account of what it did. An
    # EDIT proves the opposite direction and is just as useful: the file changed, and cria no longer
    # knows what it holds (see View.note_changed).
    view = wsview.current()
    mutation_ids = set()
    written: dict[str, str] = {}      # tool_call_id -> whole content the write carried
    edited: set[str] = set()          # tool_call_id of an edit (content becomes unknown on success)
    edit_pairs: dict[str, tuple[str, str]] = {}  # tool_call_id -> the exact (old_string, new_string)
    edit_preimages: dict[str, bytes] = {}       # current bytes captured before this invocation
    observation_revisions: dict[str, int] = {}  # identity/order, never receipt or execution credit
    observations = {}                          # invocation bounds, not result-arrival order
    pending_mutations = set()
    read_whole: dict[str, str] = {}   # tool_call_id -> path of an UNRANGED read (result is the file)
    def may_mutate(tc):
        fn = tc.get("function") or {}
        original = (_read_sentinel(_command_of(fn.get("arguments")), tc.get("id"))
                    if is_shell_tool_name(fn.get("name")) else None)
        if original is not None:
            return original["name"] in (_WRITE_NAMES | _EDIT_NAMES) and tc.get("id") not in failed_ids
        return _native_effect_unknown_or_mutating(fn, workspace_root)
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            # All calls in a batch may overlap; a pending writer is not closed
            # merely because another result arrived first. Ambiguous IDs never close.
            pending_mutations.update(tc.get("id") if tc.get("id") in paired else object()
                                     for tc in m["tool_calls"] if may_mutate(tc))
            new_calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                name = fn.get("name")
                if is_shell_tool_name(name):
                    orig = _read_sentinel(_command_of(fn.get("arguments")), tc.get("id"))
                    if orig is None:
                        own = _command_of(fn.get("arguments"))
                        own_cmds[tc.get("id")] = own
                        # THE DISK MOVED AND THE SURVEY DID NOT. A survey rides along on a
                        # cria-composed write/edit/list, so a run of the coder's own shell commands
                        # changes the workspace while the view stands still. Recording that here is
                        # what lets a caller tell "cria saw no vendor/" from "there is no vendor/".
                        if _native_effect_unknown_or_mutating(fn, workspace_root):
                            mutation_ids.add(tc.get("id"))
                            view.note_possible_effect()
                    if orig is not None:
                        lowered_ids.add(tc.get('id'))
                        tc = {**tc, "function": {"name": orig["name"], "arguments": orig["arguments"]}}
                        swapped += 1
                        if orig["name"] in (_WRITE_NAMES | _EDIT_NAMES):
                            p = _parse(orig["arguments"])
                            if orig["name"] in _EDIT_NAMES and tc.get("id") in paired:
                                preimage = view.capture_edit_preimage(_tool_path(p))
                                if preimage is not None:
                                    edit_preimages[tc.get("id")] = preimage[0]
                            if tc.get("id") not in failed_ids:
                                mutation_ids.add(tc.get("id"))
                                view.note_a_mutator_ran()
                            write_paths[tc.get("id")] = _tool_path(p) or ""
                            if orig["name"] in _EDIT_NAMES:
                                edited.add(tc.get("id"))
                                if isinstance(p.get("old_string"), str) and isinstance(p.get("new_string"), str):
                                    edit_pairs[tc.get("id")] = (p["old_string"], p["new_string"])
                            else:
                                body_arg = next((p[k] for k in ("content", "file_text", "text", "body")
                                                 if isinstance(p.get(k), str)), None)
                                if body_arg is not None:
                                    written[tc.get("id")] = body_arg
                            if tc.get("id") in failed_ids:
                                draft = toolstages.current().preserve_draft(tc, _tool_path(p) or "", rlog)
                                if draft.note:
                                    rejected_notes_by_id[tc.get("id")] = draft.note
                                tc = draft.call
                        elif orig["name"] in (_READ_NAMES | _LIST_NAMES | _FETCH_NAMES | _SEARCH_NAMES):
                            strip_ids.add(tc.get("id"))
                            if orig["name"] in _READ_NAMES:
                                rp = _parse(orig["arguments"])
                                # A RANGED read is not the file. Only a whole read proves content;
                                # recording a `sed -n 20,40p` slice as the file's bytes would be a
                                # false fact of exactly the shape this module exists to stop (#5b).
                                if not rp.get("start_line") and not rp.get("end_line") and _tool_path(rp):
                                    read_whole[tc.get("id")] = str(_tool_path(rp))
                else:
                    if _native_effect_unknown_or_mutating(fn, workspace_root):
                        # Unsupported native effects are uncertainty, never proof
                        # of execution. A namespace spelling grants no exemption.
                        mutation_ids.add(tc.get("id"))
                        view.note_possible_effect()
                    if name == "local_web_search":
                        tc = {**tc, "function": {**fn, "name": "web_search"}}
                        swapped += 1
                        strip_ids.add(tc.get("id"))
                if tc.get("id") in lowered_ids:
                    observation_revisions[tc.get("id")] = view.body_revision
                new_calls.append(tc)
            view.observation_pending(bool(pending_mutations))
            for tc in new_calls:
                if tc.get("id") in lowered_ids:
                    observations[tc.get("id")] = view.begin_observation(
                        uncertain=bool(pending_mutations - {tc.get("id")}))
            out.append({**m, "tool_calls": new_calls})
        elif role == "tool":
            tid = m.get("tool_call_id")
            # THE PROVEN OUTCOME IS SET HERE, BEFORE any transform, preserve or recovery reads this message, and
            # whatever the client sent under that key is overwritten: a native client cannot nominate its own result.
            m = {k: v for k, v in m.items() if k not in (bodykeys.RESULT_OUTCOME, bodykeys.READ_OBSERVATION, bodykeys.RESULT_REPORT)}
            survey_text = ""
            pending_mutations.discard(tid)
            view.observation_pending(bool(pending_mutations))
            observation = observations.get(tid)
            interval_current = bool(observation is not None and not pending_mutations
                                    and view.observation_current(observation))
            observed_path = write_paths.get(tid) or read_whole.get(tid)
            uninterrupted = bool(interval_current and observed_path
                                 and view.body_unchanged_since(observed_path, observation_revisions.get(tid)))
            observation_options = {} if interval_current else {"current": False}
            if tid in mutation_ids:
                view.note_possible_effect()
            proof = proofs.get(tid)
            if proof is not None:
                m["content"] = proof.content       # exactly cria's own records removed; the payload keeps its bytes
                m[bodykeys.RESULT_OUTCOME] = proof.kind
                if proof.rep:
                    m[bodykeys.RESULT_REPORT] = proof.rep
                survey_text = proof.survey         # only what a DECLARED second record carried is instrumentation
            elif tid in lowered_ids:
                m[bodykeys.RESULT_OUTCOME] = denial.UNKNOWN   # cria lowered this call and cannot prove its branch
            unverified = isinstance(m.pop(bodykeys.MULTIPART_UNVERIFIED, None), UnverifiedCarrier)
            if tid in ambiguous and not unverified:
                # AMBIGUOUS: nothing call-attributed is cached, stripped or rendered, and no recovery or
                # advice is composed from it — it keeps its actual bytes (no frame is trusted, so no survey is
                # taken either).
                out.append({**m, "content": _debinarized(str(m.get("content") or ""))})
                continue
            # A verified UTF-8 read is user file content, not terminal log
            # decoration. Stripping ANSI or binary-looking controls would change
            # its bytes even though the record proved them exactly.
            if unverified:
                # Keep the complete original carrier, including non-text
                # content, without attributing any source or write fact.
                out.append(m)
                continue
            if proof is not None and proof.exact and proof.text is not None and proof.observe in (resultpacket.WHOLE, resultpacket.RANGE):
                content = str(m.get('content') or '')
            else:
                content = _debinarized(str(m.get("content") or ""))
            # THE SURVEY IS WHAT A DECLARED SECOND RECORD CARRIED, NOTHING ELSE: the sentinel said one follows the first
            # record, it was read on the very next line and removed there. A file, a native command or a read-instead
            # answer that quotes a perfectly valid-looking survey block keeps it — and teaches the view nothing.
            _, survey = wsview.strip_survey(survey_text)    # decodes a packed block; the text is cria's own bytes
            if tid in write_paths and tid in uncertain_ids:
                # The in-place hardlink writer may have changed every alias. Their
                # identities are not surveyed, so invalidate all held candidates
                # BEFORE this result's fresh survey can attest current bodies.
                view.note_unknown_mutation()
            if observation is not None:
                observation = view.settle_observation(observation, current=interval_current)
            # A LANDED EDIT CRIA KNOWS EXACTLY KEEPS THE HELD BODY CURRENT. Applied BEFORE this
            # result's own survey: that survey reports the post-edit size, which would otherwise drop
            # the pre-edit body as stale before the edit could be applied to it — and the survey is
            # then the ground-truth check on the reconstruction (a size that disagrees drops it).
            edit_applied = (uninterrupted and tid in edit_pairs and bool(write_paths.get(tid)) and tid in landed_ids
                            and wsview.from_observation(observation, view.note_edited, write_paths[tid],
                                                       *edit_pairs[tid], previous=edit_preimages.get(tid)))
            if survey:
                # Same as the gate's copy: a rejected survey is the one failure `wsview` cannot show
                # from the outside, and both readers used to drop the answer on the floor (#12).
                if not wsview.from_observation(observation, wsview.apply_survey, view, survey) and rlog is not None:
                    rlog.emit("wsview.survey_rejected", level="warn", bytes=len(survey),
                              closed=wsview.SURVEY_CLOSE in survey, **wsview.last_reject())
            # A WHOLE READ BECOMES THE FILE'S BYTES ONLY ON A VERIFIED BODY: the producer's own read-once program put the
            # bytes in the first record with their length and sha-256, and `_frame_proofs` verified both. There is no
            # other source: the absence of a refusal proves nothing (a legacy own refusal, a lost record, a cut result),
            # an envelope-stripped display is not the file (a pty rewrites its newlines), and unknown is not positive.
            if proof is not None and proof.text is not None:
                exact = proof.exact and content == proof.content       # `_debinarized` left the display alone
                if exact:
                    m[bodykeys.READ_OBSERVATION] = (len(proof.text), denial.text_digest(proof.text))
                    if tid in write_paths and proof.kind == denial.REFUSED:
                        wsview.from_observation(observation, view.note_read, write_paths[tid], proof.text, **observation_options)
                    elif tid in read_whole and proof.kind == denial.RAN and proof.observe == resultpacket.WHOLE:
                        wsview.from_observation(observation, view.note_read, read_whole[tid], proof.text, **observation_options)
                shown = content
                final_prefix = proof.pre
                if tid in write_paths and proof.kind == denial.REFUSED:
                    # THE REJECTED CANDIDATE STAYS. This answer is denied, so `_collapse_rejected_payload` took the
                    # coder's own large payload out of its call; the lossless copy rides here, in the authored prefix
                    # before the file's bytes, so what follows is still only the file's bytes. Placed by the record's
                    # own prefix/body split, never by searching for a marker.
                    note = rejected_notes_by_id.get(tid, "")
                    marker = denial.READ_INSTEAD_MARKER + "\n"
                    head = shown.removesuffix(proof.text)          # the authored prefix: the body is the tail by construction
                    if note and head.endswith(marker):
                        final_prefix = f"{head.removesuffix(marker)}{note}\n\n{marker}"
                        shown = final_prefix + proof.text
                if exact and proof.observe in (resultpacket.WHOLE, resultpacket.RANGE):
                    from .multipartcontext import record_prefix
                    record_prefix(tid, proof.text, final_prefix)
                out.append({**m, "content": shown})
                continue
            if tid in write_paths and write_paths[tid] and tid in landed_ids:
                if tid in written:
                    wsview.from_observation(observation, view.note_written, write_paths[tid], written[tid], **observation_options)
                elif tid in edited and not edit_applied:
                    wsview.from_observation(observation, view.note_changed, write_paths[tid])
            if tid in strip_ids:                          # read/nav result → drop only proven framing, never EOF
                out.append({**m, "content": _strip_exec_envelope(content)})
            elif tid in write_paths and tid in landed_ids:  # write/edit SUCCESS
                rendered = render_edit_echo(write_paths[tid], proof.rep if proof is not None else None)
                facts = ((proof.rep or {}).get("rm") or "").strip() if proof is not None else ""
                out.append({**m, "content": f"{rendered}\n{facts}" if facts else rendered})
            elif tid in write_paths:                      # write/edit FAILURE → strip the shell envelope,
                # then hand a structured edit-fail fact-report to the ONE edit-recovery owner, which
                # composes the single monotonic directive keyed on this file's failure history so far
                # (``out``). A non-edit-fail failure (write refusal, real error) passes through unchanged.
                stripped = _strip_exec_envelope(content)
                result = toolstages.current().returned_result(
                    ReturnedResult(m, stripped, own_cmds.get(tid, ""), out, rlog, mutation_failure=True))
                recovered = (result or {**m, "content": stripped})["content"]
                note = rejected_notes_by_id.get(tid, "")
                if note:
                    recovered = recovered.rstrip() + "\n\n" + note
                out.append({**m, "content": recovered})
            elif (result := toolstages.current().returned_result(
                    ReturnedResult(m, content, own_cmds.get(tid, ""), out, rlog))) is not None:
                out.append(result)
            elif content != str(m.get("content") or ""):
                out.append({**m, "content": content})   # the binary-soup cleanse changed it
            else:
                out.append(m)
        else:
            out.append(m)
    if mutation_ids - paired:
        # Later surveys do not settle an unresolved/ambiguous native invocation.
        view.note_possible_effect()
    if swapped and rlog is not None:
        rlog.emit("writeproxy.represented", calls=swapped)
    toolstages.current().returned_history(
        ReturnedHistory(out, own_cmds, workspace_root, sess_key, tools_present, rlog))
    return out


# Bytes of REAL selected lines allowed inline before this switches to the partial/overflow wording
# (#5: never truncate silently -- the switch STATES the real total and the real read_hint, it never
# drops lines without saying so). Deliberately small: a handful of real signatures is the common
# case, and a large budget would let one bloated package push everything else in the same tool
# result out of the window it rides in.
# Independent review round 4 (usefulness finding): measured against the REAL shopspring/decimal
# cache, the declaration-only (no doc-prose) surface is 4,645 real bytes -- comfortably real-world
# sized once prose is gone, but still bigger than the old 2,400-byte budget, which truncated the
# alphabetically-sorted member list before reaching `Round`/`RoundCeil`/`RoundBank` -- the exact real
# members that contradict the invented `Quantize`/`RoundingModeCeiling` this candidate exists to catch.
# Measured: decimal 4,645B, toml 0.8.23 3,152B, a robfig/cron-shaped fixture 150B all now fit whole;
# commons-csv (8 real classes' worth of javap output, 7,007B) does not and stays partial-with-pointer,
# which is the explicitly allowed outcome for a genuinely large single dependency.
_SURFACE_INLINE_BUDGET = 6000
# How many NEW coordinates one request will ever gather() for the first time (independent review B2):
# even restricted to direct dependencies, a manifest can name several in one project, and each
# first-time gather() may be a real disk walk or (JVM) up to MAX_FILES real `javap` subprocesses.
# Re-RENDERING an already-anchored coordinate (replaying cached text) does not count against this --
# it costs one dict lookup, never a disk read -- but is separately bounded by
# `_MAX_ANCHOR_RENDERS_PER_REQUEST` so a project with many direct dependencies cannot still turn one
# request into an unbounded wall of text.
_MAX_NOTES_PER_REQUEST = 3
_MAX_ANCHOR_RENDERS_PER_REQUEST = 12
# A hard ceiling on the TOTAL bytes this candidate appends in one request, across every coordinate
# combined (independent review round 3, R3). `_SURFACE_INLINE_BUDGET` already bounds one note; this
# bounds the SUM, because a session that has anchored several real direct dependencies would otherwise
# re-render all of them, every request, forever -- individually bounded, collectively not. A
# coordinate skipped for THIS reason is not withdrawn (its anchor state is untouched) and is retried
# on the next request; if anything was withheld this pass, ONE labelled sentence says so -- never a
# silent cut (#5).
_MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 24_000
