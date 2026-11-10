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
import zlib
import json
import os
import re
from dataclasses import dataclass, replace
from shlex import quote as _qbash  # one bash-quoting rule (was a hand-rolled _qbash)

from . import bodykeys, callauth, brave, denial, resultpacket, depsurface, dirguard, prompts, webfetch, wsview, toolstages
from .toolstages import (AnswerIntent, LoweringRequest, MutateIntent, OutboundCall, ReadIntent, SaveIntent, SearchIntent, ShellCommand,
                         ReturnedResult, ReturnedHistory)
from .returnedpolicies import (_rejected_payload_note, _collapse_rejected_payload,
                               _render_dependency_surface, _found_nothing, _blind_pipe_failure)
from .outboundpolicies import _external_refusal
from .shrinkprotection import ShrinkServices
from . import content_reduce as content_reduce_mod
from . import probeparse
from . import proberun
from .privatepaths import CRIA_HOME
from .shelltool import _CMD_FIELDS, is_shell_tool_name, shell_args
from .readops import LedgerRead
from .answerops import LedgerAnswer
from .toolargs import PATH_KEYS as _PATH_KEYS, parse_args as _parse, patch_paths, tool_path as _tool_path
from . import filecommands, harnessprims, ops
# Canonical pure helpers; transport/service composition remains in this facade.
from .callliterals import (
    _FUSED_TAIL_MAX_LINES, _PROTOCOL_TAG_LINE, _protocol_debris, trim_fused_tail,
    _TC_DEBRIS, _has_tc_debris, _ESCAPES, _repair_double_escaped, _decode_backslash_escapes)
from .filecommands import (
    _WRITE_NAMES, _EDIT_NAMES, _READ_NAMES, _LIST_NAMES, _SEARCH_FILE_NAMES, _FileMutation, _prepare_file_mutation,
    _targets_cria_home, _guarded_path, READ_INLINE_MAX)
from .toolwire import (
    REFUSED_EXIT_CODE, _oversize_command, _refusal_command, _SENTINEL, _SENTINEL_LINE,
    _sentinel, _shell_call, _b64,
    _command_of, is_crias_own, original_call, _read_sentinel, receipt_of, _declaration,
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
    lowered_id: str | None = None
    retained: bool = False


def _externalize_coder(source: OutboundCall) -> AnswerIntent | None:
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
    # THE SEARCH IS MADE HERE, ONCE, IN-PROCESS (as a fetch is), never by a harness-run curl: cria alone holds the process's wait
    # state, so a 429 is waited out or reported with the service's own stated wait, and the key never rides in a command.
    answer = brave.search(str(args.get('query') or ''), request.brave_key, _SEARCH_MAX_RESULTS) if search else None
    inline = (_search_answer(args, answer) if search else
              _fetch_answer(args, request.session, request.workspace_root))
    if definition is None or inline is None:
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
        offer = lambda spill: _search_answer(args, answer, search_offer=spill, operation=operation)
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
        offer = lambda spill: AnswerIntent('web_fetch', url, spill.pointer, denial.RAN, None, SaveIntent(spill.target, spill.content, operation))
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
        call = calls.get(offer.lowered_id or cid)
        if (offer.owner is owner and call is not None and offer.lowered_arguments is not None
                and call.get('type') == offer.lowered_type
                and (call.get('function') or {}).get('name') == offer.lowered_name
                and (call.get('function') or {}).get('arguments') == offer.lowered_arguments):
            offer.retained = True


def settle_externalizations(owner, saved) -> None:
    """Settle the externalization offers whose file the ledger says was saved, or was not: ``saved`` is ``(the model's call id, how the call ended, the
    offer's operation and the stored fact the ledger computed from the bytes it sent)`` for each finished answer that saved a file
    (:class:`cria.ops.Incoming`). The facts are the ledger's own; no result text and no record a harness program printed is read."""
    from . import externalization as e
    offers = getattr(owner, 'externalization_offers', None) or {}
    for call_id, outcome, ext in saved:
        offer = offers.get(call_id)
        if (not isinstance(offer, ExternalizationOffer) or offer.owner is not owner or not offer.retained
                or offer.operation != ext.get('operation')):
            continue
        stored, spill = ext.get('stored'), offer.delivery.result.spill
        if outcome != denial.RAN or not stored or stored['target'] != spill.target:
            offer.delivery.settle(e.Outcome.UNKNOWN if outcome == denial.UNKNOWN else e.Outcome.FAILED, stored=False)
            continue
        if isinstance(spill, e.Spill):
            raw = spill.content.encode('utf-8', 'surrogateescape')
            if stored['byte_count'] != len(raw) or stored['sha256'] != hashlib.sha256(raw).hexdigest():
                continue
            offer.delivery.settle(e.Outcome.RETAINED, stored=True)
        else:
            try:
                offer.delivery.settle(e.Outcome.RETAINED, stored=e.SearchStored(stored['target'], stored['byte_count'], stored['sha256']))
            except ValueError:
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
    elif error == "text":
        message = prompts.load("mutation_unwritable_text")
        if rlog is not None:
            rlog.emit("writeproxy.mutation_unwritable_text", tool=name)
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
        "grep": fn("grep", d["grep"], {"pattern": {"type": "string"}, "path": {"type": "string"}, "include": {"type": "string"}, "include_generated": {"type": "boolean"}}, ["pattern"]),
        "glob": fn("glob", d["glob"], {"pattern": {"type": "string"}, "path": {"type": "string"}, "include_generated": {"type": "boolean"}}, ["pattern"]),
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


def advertise(body: dict, rlog=None, brave_key: str | None = None, *, search_only: bool = False) -> set[str]:
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

    if search_only:
        for name in ('grep', 'glob'):
            if name not in present:
                add(name)
        return injected

    if not (present & _WRITE_NAMES):
        add("write_file")
    if not (present & _EDIT_NAMES):
        add("edit_file")  # the surgical-edit path; a whole-file rewrite botches a one-char fix
    if "read_file" not in present:
        add("read_file")
    if "list_dir" not in present:
        add("list_dir")
    for name in ("grep", "glob"):
        if name not in present:
            add(name)
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


def _sized_answer(tool: str, label: str, text: str, outcome: str, rep: dict | None = None) -> AnswerIntent:
    """``text`` as the model is told it: whole when the harness returns it whole, else saved whole at ``<spill dir>/stdout-<sha-256>.txt`` (the one thing
    cria writes in the workspace, so the model can search it) and the model is given the pointer. The measure is the bytes plus one per line feed, the way
    a pty returns them (:func:`externalization.stdout_size`)."""
    from . import externalization as e
    data = text.encode('utf-8', 'surrogateescape')
    if e.stdout_size(data) <= e.STDOUT_MAX_BYTES:
        return AnswerIntent(tool, label, text, outcome, rep)
    target = f"{webfetch.SPILL_DIR}/stdout-{hashlib.sha256(data).hexdigest()}.txt"
    return AnswerIntent(tool, label, webfetch.stdout_spill_pointer(target, len(text)), outcome, rep, SaveIntent(target, text))


def _fetch_answer(args: dict, session: str | None = None, workspace_root: str | None = None) -> AnswerIntent | None:
    """cria fetches + reduces the page IN-PROCESS (it runs as a stateful server with a per-URL
    doc cache) and answers with the ALREADY-REDUCED, bounded result — so the harness records navigable content that PERSISTS in the
    conversation, instead of running a raw ``curl`` whose single-line JSON/YAML it truncates mid-line (the Ada-handle openapi.json incident).
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
    with denial.unframed():       # the answer is cria's words as the model reads them: no record line leads a refusal the gate marked
        result, refused, status, facts = webfetch.fetch_nav_result(str(url), find=find, cursor=cursor, session=session, raw=raw,
                                                                   workspace_root=workspace_root)
    # A PLAIN fetch (no find/cursor) of an oversized doc is spilled by the externalization offer (`_externalize_coder`): the full doc is saved
    # under ./tmp and the model is handed a short pointer instead of a low-signal page-1. find=/cursor= navigation returns its slice as usual.
    # …but only the FIRST time. Once cria has written the doc to the workspace that file outlives the
    # conversation, so a later plain re-fetch is answered with the file's name (fetch_nav's refusal,
    # already in `result`) instead of copying the same document over itself. Measured (run
    # 0727-104845): a 154KB docs page re-fetched NINETEEN times after the harness compacted the first
    # result away — each one re-spilling and burning a turn.
    # A repeat-gate REFUSAL comes back from fetch_nav as ordinary text and is answered as a refusal ("a refused call must not report
    # success"). Which results are refusals is webfetch's own decision, never re-derived from wording: a real 404 page is a RESULT.
    if refused:                    # the repeat gate's own typed decision — a fetched page quoting the marker is a page
        with denial.unframed():
            return _sized_answer('web_fetch', str(url), denial.mark(result), denial.REFUSED)
    # THE FETCH'S OWN FACTS ride as a typed field of the answer (`rep.fx`: url, status, routes, shapes, catalog), computed
    # from the producer's parse of the document — never re-read from the rendered page, whose body may quote any marker.
    # This is also the visibility receipt's complete response contract: every HTTP response has fx,
    # even a 404/empty body. RAN without fx means the attempt returned no HTTP response (status=None),
    # not that it was refused or that a document has since been evicted from the cache.
    return _sized_answer('web_fetch', str(url), result, denial.RAN, {'fx': facts} if facts else None)


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


def _search_refusal(refused: int, wait_ms: int) -> str:
    """The result of a search the service refused: its own stated wait (`wait_ms`, from the shared reader), said once."""
    say = prompts.load_map("search_refused")
    return (prompts.fill(say["wait"], status=refused, seconds=-(-wait_ms // 1000)) if wait_ms > 0
            else prompts.fill(say["no_wait"], status=refused))


def _search_answer(args: dict, answer: "brave.Answer", *, search_offer=None, operation=None) -> AnswerIntent:
    """Brave web search answered from the answer cria itself fetched (`brave.search`: the shared endpoint, %-encoded query and headers, through the
    shared rate-limit opener), as compact "title / url / description" lines the model can pair with web_fetch. A refused search (429/503) is
    answered with a refusal naming the wait the service stated. Requests Brave's per-request maximum and shows EVERY returned result (no display
    slice) with a total-count header so the authoritative page — which may rank 9th+ — reaches the model and it knows how many exist."""
    query = str(args.get("query") or "")
    if answer.refused:
        with denial.unframed():
            return _sized_answer('web_search', query, denial.mark(_search_refusal(answer.refused, answer.wait_ms)), denial.REFUSED)
    # A body that is not the JSON object `brave.search` builds (a transport failure, HTML, an empty body) is answered with the "unreadable" line, never
    # with a traceback and never as "no results": the cause belongs to the search tool and says nothing about the site the model is working on.
    try:
        data = json.loads(answer.body)
        results = (data.get("web") or {}).get("results") or []
        error = data.get("error") or data.get("message")
        parts = [(x.get("title", ""), x.get("url", ""), x.get("description", "")) for x in results]
    except (ValueError, AttributeError, TypeError):
        return AnswerIntent('web_search', query, prompts.load("search_unparsable"), denial.RAN)
    # `error`: a Brave ERROR body (401 invalid key, 422, 429 rate-limited) is valid JSON with no `web`, and "no results" would tell the model the web
    # holds nothing for its query when the API had in fact refused the request, its own code/detail right there in the same body. Surface the API's
    # own error text; only a genuinely empty result set says "no results".
    nothing = ("search API error: " + json.dumps(error)) if error else "no results"
    # TITLES AND LINKS ARE THE ANSWER; DESCRIPTIONS ARE THE NOISE. Every search was spilled to disk whatever its size and the model got a pointer, and
    # the model did not open the file. Measured, nemotron-elastic/go: the coder said "Ok, I'm stuck. Let's search for a decimal library", the spill
    # file's fourth line read "decimal package - github.com/shopspring/decimal - Go Packages", and the go.mod it shipped required
    # `github.com/elliott/decimal v1.6.0`. A package that does not exist. Zero spill reads across 124 calls in that cell.
    #
    # So search obeys the size rule cria already owns for command output — inline when it fits, spill when it does not — instead of spilling always.
    # The full results with descriptions are written to the spill file either way, so the grep route and the ledger entry are unchanged.
    #
    # …EXCEPT A DESCRIPTION THAT CARRIES AN API NAME, which a title cannot. The poison the drop was written against was a wrong PACKAGE name — and a
    # title carries the package. A method name, a predicate or a constant only ever appears in the description. Walked on the sub-40 pass,
    # shipping-rates-rb x nemotron-elastic: the model's FIRST search returned the whole task as its first result's description
    # (`European Union Membership · c.in_eu? #=> false`); cria wrote that to disk, showed the model twenty titles, and closed with "you do not have
    # to open it". The model then spent fifteen minutes on nine more searches for a gem whose method name it had already been handed.
    stored = f"{len(results)} results:\n" + "\n".join("%s\n  %s\n  %s" % part for part in parts)
    if search_offer is None:
        return _sized_answer('web_search', query, (stored if results else nothing) + "\n", denial.RAN)
    # NAME THE FILE. The note ends "in the file named above" on the INLINE path, where nothing above names a file, so the target is named in the
    # sentence. THE POINTER MUST CARRY ITS QUERY: cria's read-judge finds the query for a saved result file by matching this sentence, and both
    # pointers say the same sentence, so one regex reads both (#23).
    target, pointer = webfetch.search_spill(query)
    note = prompts.fill(prompts.load("search_inline_note"), target=target, query=query)
    callable_ = re.compile(_API_NAME_SHAPE)
    brief = (f"{len(results)} results:\n" + "\n".join(
        "%s\n  %s%s" % (title, url, ("\n  " + (description or "")) if callable_.search(description or "") else "")
        for title, url, description in parts) + "\n" + note)
    shown = search_offer.program.show(brief, pointer) if results else nothing
    # The file is written whether or not there were results (the model is told where to look only when there is a file to look in): a no-result
    # search used to remember a spill path and write nothing, and the coder read a phantom three times (cart-billing-go).
    return AnswerIntent('web_search', query, shown + "\n", denial.RAN, None, SaveIntent(search_offer.target, stored, operation))




_REJECTIONS_SEEN: dict[str, set[tuple]] = {}


def _first_sight_of_rejection(sess_key: str, tc: dict) -> bool:
    """True the FIRST time this session meets a rejected call. The harness re-sends the whole history every request, so the
    same rejected call is re-collapsed on each one (the collapse itself is idempotent and stays); only its audit event must not
    repeat, or `writeproxy.rejected_payload_dropped` counted requests, not rejected calls. The key is the call's id AND its
    arguments, so a reused id with a different payload is a different rejection."""
    if len(_REJECTIONS_SEEN) > 512:
        _REJECTIONS_SEEN.clear()
    seen = _REJECTIONS_SEEN.setdefault(sess_key or "", set())
    key = (tc.get("id"), hashlib.sha256(str((tc.get("function") or {}).get("arguments")).encode()).hexdigest())
    if key in seen:
        return False
    seen.add(key)
    return True


def _lower_synthetic(source: OutboundCall) -> ShellCommand | AnswerIntent | SearchIntent | MutateIntent | ReadIntent | dict | None:
    """Required harness adapters, independent of optional steering selection.

    Validating mutation arguments and preserving execution/correlation are not
    advice. Disabling a protection never turns missing content into an empty write.
    """
    name, args, request = source.name, source.arguments, source.request
    if name in (_WRITE_NAMES | _EDIT_NAMES) and name in request.injected:
        mutation = _prepare_file_mutation(name, args)
        if mutation.error:
            return ShellCommand(_file_mutation_refusal(name, mutation, request.injected, source.log))
        plan = toolstages.current().mutation_plan(source)
        # Explicit, unbound library callback compatibility only. Production uses typed factual services; a bound selection never falls
        # back to a whole legacy policy callback, even when its selected source has no services.
        if (not toolstages.is_bound() and request.shrink_services is None
                and request.shrink_check is not None and name in _WRITE_NAMES):
            edits = request.injected & _EDIT_NAMES
            finding = request.shrink_check(str(mutation.path), _repair_double_escaped(mutation.content),
                                           sorted(edits)[0] if edits else '')
            if finding:
                plan = replace(plan, shrink=finding)
                if source.log is not None:
                    event = 'writeproxy.write_removal_facts' if finding.get('land') else 'writeproxy.write_shrink_held'
                    source.log.emit(event, tool=name, path=str(mutation.path))
        return MutateIntent(mutation, plan)
    if name in _READ_NAMES and name in request.injected:
        return ReadIntent()
    elif name in _LIST_NAMES and name in request.injected:
        if request.issue_list_dir is None:
            return None
        try:
            return request.issue_list_dir(source.call, args)
        except ops.OpsUnavailable as exc:
            if source.log is not None:
                source.log.emit('ops.unavailable', level='error', error=str(exc))
            return ShellCommand(_refusal_command(prompts.load('ops_unavailable')))
    elif name in _SEARCH_FILE_NAMES and name in request.injected:
        return SearchIntent() if request.issue_search is not None else None
    elif name in _FETCH_NAMES and name in request.injected:
        if request.issue_answer is None:
            return None
        return _externalize_coder(source)
    elif name == 'web_search':
        if name in request.injected and request.brave_key:
            return _externalize_coder(source) if request.issue_answer is not None else None
        elif request.native_search and request.native_search != name:
            return {**source.call, 'function': {**source.function, 'name': request.native_search}}
        else:
            return None
    else:
        return None


class WriteFact(NamedTuple):
    """A whole-file write cria carried out: its path and the content the coder sent (the pasted-file recovery settles on it)."""
    path: str
    content: str


def _carry_out(mutations: list, rebuilt: list, request: LoweringRequest, shell_tool: dict, rlog, notes: list, pack: bool) -> None:
    """Carry out a turn's cleared file mutations through the harness primitives (cria.writeops): the calls of one file are one operation.
    ``rebuilt[i]`` is replaced by the first primitive call of the model's i-th call; the model's calls and their results stay the
    ledger's, the harness is shown cria's own calls."""
    from .writeops import MutationRequest
    requests = []
    for _index, tc, args, effect in mutations:
        name = (tc.get('function') or {}).get('name')
        finding, terms = effect.plan.shrink, effect.plan.review
        requests.append(MutationRequest(
            tc, args, 'write' if name in _WRITE_NAMES else 'edit', str(effect.mutation.path),
            shrink=({'text': finding['text'], 'land': bool(finding.get('land')), 'sha': hashlib.sha256(finding['bytes']).hexdigest()}
                    if finding else None),
            review={'permission': terms.permission, 'ws': terms.workspace_root} if terms else None, echo=request.edit_echo))
    try:
        issued = request.issue_mutations(requests) if request.issue_mutations is not None else None
    except ops.OpsUnavailable as exc:
        if rlog is not None:
            rlog.emit('ops.unavailable', level='error', error=str(exc))
        issued = [_shell_call(tc.get('id'), shell_tool, _refusal_command(prompts.load('mutation_unavailable')), 0) for _i, tc, _a, _e in mutations]
    for (index, tc, args, effect), call in zip(mutations, issued or [None] * len(mutations)):
        rebuilt[index] = call or tc
        name = (tc.get('function') or {}).get('name')
        notes.append((index, tc, call or tc, WriteFact(str(effect.mutation.path), _repair_double_escaped(effect.mutation.content))
                      if call is not None and name in _WRITE_NAMES else None))
        if call is not None and rlog is not None:
            rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "", detail="")


def translate_outbound(completion: dict, shell_tool: dict, rlog=None, injected: set[str] | None = None,
                       brave_key: str | None = None, native_search: str | None = None,
                       session: str | None = None, workspace_root: str | None = None,
                       external_dir_permission: str = "write", unread_target=None,
                       shrink_check=None, pack: bool = False, edit_echo: bool = False,
                       declared_roots: tuple = (), *, shrink_services: ShrinkServices | None = None,
                       observe_lowering=None, externalization_owner=None,
                       observe_externalization=None, only_injected: bool = False, issue_list_dir=None,
                       issue_read=None, issue_mutations=None, issue_answer=None, issue_search=None,
                       safe_path: str = harnessprims.SAFE_PATH) -> dict:
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
        (assistruntime.current().document_guidance, webfetch.guidance_services()), issue_list_dir, safe_path, issue_read,
        issue_mutations, issue_answer, issue_search)

    for choice in completion.get("choices", []):
        tool_calls = (choice.get("message") or {}).get("tool_calls")
        if not tool_calls:
            continue
        rebuilt: list[dict] = []
        held_reads: set[str] = set()
        mutations: list = []        # (index in `rebuilt`, the model's call, its arguments, the MutateIntent): carried out together below
        notes: list = []            # (index in `rebuilt`, the model's call, what it became, the whole-file write proposed): reported to the observer in order
        for ti, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            name = fn.get("name")
            if callauth.verify(tc.get("id"), _command_of(fn.get("arguments"))) is not None:
                rebuilt.append(tc)        # a call cria issued itself (its id is the MAC of this very command): never re-guarded, never lowered
                continue
            if only_injected and name not in injected:
                rebuilt.append(tc)
                continue
            call_request = request
            from .readcontext import take
            if take(tc):
                # A read alias normalization renamed to `read_file` (the harness advertises no read tool of its own): cria runs it.
                call_request = replace(request, injected=request.injected | _READ_NAMES)
            args = _parse(fn.get("arguments"))
            # THE CORRELATION TOKEN FOR THIS CALL, derived once and held while its command is composed: every
            # program authored inside prints it in its typed result record, which is the first line of stdout; the
            # sentinel below declares it (and any survey record), and `represent_inbound` accepts a result as cria's
            # own only by POSITION (the leading record) plus a recomputed canonical correlation — never by finding
            # the marker or the token anywhere in the text.
            receipt = denial.receipt_for(tc.get("id"), name, fn.get("arguments"))
            with denial.receipt_scope(receipt):
                tc, args, effect = toolstages.current().outbound_call(
                    OutboundCall(tc, args, call_request, rlog))
                fn = tc.get("function") or {}
                name = fn.get("name")
                if effect is None:
                    effect = _lower_synthetic(OutboundCall(tc, args, call_request, rlog))
            if isinstance(effect, dict):
                rebuilt.append(effect)
                notes.append((len(rebuilt) - 1, tc, effect, None))
                continue
            if isinstance(effect, ReadIntent):
                # A read, or a held write answered with one: carried out through the harness's `read` primitive. A second held
                # write to one path in a batch is answered with the refusal alone (the first read answers for them all).
                instead, hold_key = None, None
                if effect.fact is not None:
                    path = ((paths[0] if len(paths := patch_paths(tc)) == 1 else None) if name == 'apply_patch'
                            else _tool_path(args))
                    if workspace_root and path:
                        hold_key = os.path.normpath(os.path.join(workspace_root, path))
                    instead = {'fact': effect.fact, 'again': hold_key in held_reads}
                try:
                    issued = issue_read(tc, args, instead) if issue_read is not None else None
                except ops.OpsUnavailable as exc:
                    if rlog is not None:
                        rlog.emit('ops.unavailable', level='error', error=str(exc))
                    issued = _shell_call(tc.get('id'), shell_tool, _refusal_command(prompts.load('read_unavailable')), 0)
                rebuilt.append(issued or tc)
                if issued is not None and hold_key is not None:
                    held_reads.add(hold_key)
                notes.append((len(rebuilt) - 1, tc, issued or tc, None))
                if issued is not None and rlog is not None:
                    rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "", detail="")
                continue
            if isinstance(effect, (AnswerIntent, SearchIntent)):
                # An answer cria composed (a fetch, a search) or a search it will walk and run: carried out through the harness primitives, in cria's words.
                try:
                    issued = (issue_answer(tc, args, effect) if isinstance(effect, AnswerIntent) else issue_search(tc, args))
                except ops.OpsUnavailable as exc:
                    if rlog is not None:
                        rlog.emit('ops.unavailable', level='error', error=str(exc))
                    issued = _shell_call(tc.get('id'), shell_tool, _refusal_command(prompts.load('ops_unavailable')), 0)
                    offers = getattr(externalization_owner, 'externalization_offers', None) or {}
                    if (stale := offers.pop(str(tc.get('id') or ''), None)) is not None:
                        stale.delivery.cancel()
                rebuilt.append(issued)
                pending = (getattr(externalization_owner, 'externalization_offers', None) or {}).get(str(tc.get('id') or ''))
                if pending is not None:
                    pending.lowered_arguments = issued['function']['arguments']
                    pending.lowered_name = issued['function']['name']
                    pending.lowered_type = issued.get('type')
                    pending.lowered_id = issued.get('id')
                    if observe_externalization is not None:
                        observe_externalization(tc, issued, pending)
                notes.append((len(rebuilt) - 1, tc, issued, None))
                if rlog is not None:
                    rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "", detail=str(args.get("query") or args.get("url") or args.get("pattern") or ""))
                continue
            if isinstance(effect, MutateIntent):
                # A file mutation cleared by every guard: carried out through the harness primitives, the calls of one file together.
                mutations.append((len(rebuilt), tc, args, effect))
                rebuilt.append(tc)
                continue
            cmd = effect.command if effect is not None else None
            if cmd is not None:
                header = _sentinel(name, fn.get('arguments'), receipt)
                rebuilt.append(_shell_call(tc.get("id"), shell_tool, f"{header}\n{cmd}", 0))
                pending = (getattr(externalization_owner, 'externalization_offers', None) or {}).get(str(tc.get('id') or ''))
                if pending is not None:
                    pending.lowered_arguments = rebuilt[-1]['function']['arguments']
                    pending.lowered_name = rebuilt[-1]['function']['name']
                    pending.lowered_type = rebuilt[-1].get('type')
                    if observe_externalization is not None:
                        observe_externalization(tc, rebuilt[-1], pending)
                notes.append((len(rebuilt) - 1, tc, rebuilt[-1], None))
                if rlog is not None:
                    # `target`/`detail` feed the LIVE status ticker — the harness renders the lowered
                    # call as an opaque sentinel blob (operator: "a file wrote to the project, but
                    # there was no indicator"), so the ACTION is narrated here in cria's own voice.
                    rlog.emit("writeproxy.lowered", tool=name, target=_tool_path(args) or "",
                              detail=str(args.get("query") or args.get("url") or ""))
            else:
                rebuilt.append(tc)
                notes.append((len(rebuilt) - 1, tc, tc, None))
        if mutations:
            _carry_out(mutations, rebuilt, request, shell_tool, rlog, notes, pack)
        for _position, original, lowered, written in sorted(notes, key=lambda note: note[0]):     # the observer hears of each call in the model's order
            if observe_lowering is not None:
                observe_lowering(original, lowered, written)
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
    rep: dict | None = None   # the first record's typed reports (`resultpacket.REPORT_KEYS`), or None
    observe: str = ""         # what the verified body is: `whole` (the file) or `range` (a numbered window of it)
    pre: str = ""             # exact producer-authored prelude, not inferred from file text


def _frame_proofs(messages: list[dict]) -> dict[str, _Proof]:
    """``tool_call_id -> _Proof`` for every call whose pairing is UNAMBIGUOUS (`denial.paired_results`: one call, one
    result after it) and whose STORED command declared a receipt in cria's sentinel.

    AUTHORITY IS POSITION AND DECLARATION (`resultpacket`): the first record is the program's own first line: at offset 0 of
    the stdout (after the harness's own envelope), or after whatever a chatty login shell printed first
    (`resultpacket.find_record`: the first occurrence of THIS call's receipt record, never past the harness's cut marker; that
    noise is dropped from the display); the second exists only if the sentinel declared a survey and is read only on the
    very next line. Nothing is searched for — a file, a page or a native command that quotes records, receipts, markers or
    a valid-looking survey is just the opaque tail and keeps every byte. A valid first record stands when the second is
    missing or cut. No record at offset 0 (a legacy command, a cut, an unlowered shape) means UNKNOWN: untouched."""
    paired = denial.paired_results(messages)
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
            content = str(paired_result.get("content") or "")
            off = _payload_offset(content)
            found = resultpacket.find_record(content, off, token)
            if found is None:
                # A shell that printed >5 KB before the program leaves the harness's tail holding the records (it keeps the first and
                # last halves). Record 1 is taken from there only on a proof the cut did not destroy: its DECLARED second record follows it
                # on the very next line (a quoted record in a command's tail is never followed by a valid survey of the same receipt), or
                # the call is one of cria's own write/edit programs (declared and recomputed from this call's id, name and arguments) and
                # nothing but whitespace follows the record: those programs print NO other output after a landed / unapplied record 1
                # (a survey rides only every SURVEY_EVERY-th call, so most results carry none), so the record that ENDS the result is
                # the program's own last word. Anything printed after it (a failure message, shell noise after the program) leaves the
                # result UNKNOWN, as before. A read never qualifies: its tail is the file.
                found = resultpacket.find_record(content, off, token, past_cut=True)
                if found is not None:
                    ends_the_result = declaration.get("name") in (_WRITE_NAMES | _EDIT_NAMES) and not content[found[1].end:].strip()
                    if not ends_the_result:
                        found = None
            if found is None:
                continue
            first = found[1]       # found[0] > off when the harness's shell printed noise before the program: dropped
            tail, rep = content[first.end:], first.rep
            if first.body is None:
                out[cid] = _Proof(first.kind, content[:off] + first.pre + tail, None, False, rep)
                continue
            try:
                text, exact = first.body.decode("utf-8"), True
            except UnicodeDecodeError:
                text, exact = first.body.decode("utf-8", "replace"), False
            out[cid] = _Proof(first.kind, first.pre + text + tail, text, exact and tail == "", rep, first.observe, first.pre)
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

    Measured since (decision-log, "Elision roots", 2026-11): 372 distinct cut results in 174 captured Codex sessions
    plus 243 in the outbound bodies; the policy is the model catalog's (40,000 bytes before 2026-10-07 19:33 PDT,
    10,000 after), so a remembered number is still a claim about one catalog.

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
                      sess_key: str = "", tools_present: bool = True, window: int | None = None,
                      ask=None, ledger_outcomes=None, ledger_reads=None, ledger_writes=None, ledger_surveys=None, ledger_answers=None) -> list[dict]:
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
    marks a harness compaction/summarize turn (empty tool menu) -- C40 skips those entirely.
    ``window`` is the coder's measured window (None = unknown): the dependency-note budgets are shares of it.
    ``ask`` is the one closed-question seat to the reasoner (None = no reasoner), for the history assists that judge.
    ``ledger_outcomes`` maps a tool call id to the typed outcome cria's own ledger recorded for an operation it carried out
    through the harness primitives (`cria.ops`): the outcome is a field of cria's record, never read out of result text.
    ``ledger_reads`` maps a tool call id to the ``readops.LedgerRead`` of a read cria carried out that way: the model's own call (a
    ``read_file``, or the held write it answered with a read), how it ended and the verified body. Such a call is treated as the
    lowered call it was; what it proved is the ledger's, not a record parsed out of its result.
    ``ledger_writes`` maps a tool call id to the ``writeops.LedgerWrite`` of a file mutation cria carried out that way: the model's own
    call, how it ended (landed, refused, did not apply, uncertain), the text the coder is shown and, for an edit that did not apply, the
    facts of the miss. The typed outcome is the ledger's; nothing is read out of result text.
    ``ledger_answers`` maps a tool call id to the ``answerops.LedgerAnswer`` of an answer cria composed and carried out (a fetch, a search, a grep, a
    glob): the model's own call, how it ended, the text it is told and the typed facts (a fetch's, a saved file's) its readers ask for.
    ``ledger_surveys`` maps the id of a tool result (None: the start of the history) to the ``wsview.Survey`` objects cria asked for on its
    own after it, in order: each is applied to the workspace view at that position, as the survey that rode with a result used to be."""
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
    ledger_reads, ledger_writes, ledger_answers = ledger_reads or {}, ledger_writes or {}, ledger_answers or {}
    proofs = {**_frame_proofs(messages),
              **{tid: _Proof(r.kind, r.pre + r.text, r.text, True, None, r.observe, r.pre)
                 for tid, r in ledger_reads.items() if r.text is not None},
              **{tid: _Proof(w.kind, w.text, None, False, w.rep or None) for tid, w in ledger_writes.items()},
              **{tid: _Proof(a.kind, a.text, None, False, a.rep) for tid, a in ledger_answers.items()}}
    outcomes = {tid: p.kind for tid, p in proofs.items() if p.kind in (denial.REFUSED, denial.UNAPPLIED)}
    outcomes |= {tid: kind for tid, kind in (ledger_outcomes or {}).items() if kind in (denial.REFUSED, denial.UNAPPLIED)}
    landed_ids = {tid for tid, p in proofs.items() if p.kind == denial.LANDED}   # cria's own program reported the mutation landed
    uncertain_ids = {tid for tid, p in proofs.items() if p.kind == denial.UNCERTAIN}
    called_ids = {tc.get("id") for m in messages if isinstance(m, dict) and m.get("role") == "assistant"
                  for tc in (m.get("tool_calls") or []) if isinstance(tc, dict) and tc.get("id")}
    ambiguous = called_ids - paired    # a call exists but the id does not name exactly one call and one result after it
    unread_hold_ids: set[str] = set()
    lowered_ids: set[str] = set()     # calls cria itself lowered (their result carries cria's frame, or is unknown)
    failed_ids = set(outcomes)          # proven: cria's own refusal ran, or its edit program reported 'not applied'
    write_paths: dict[str, str] = {}  # tool_call_id -> path, for the success reframe / failure strip
    strip_ids: set[str] = set()       # read/nav re-presented tool ids → strip the harness exec envelope
    content_search_ids: set[str] = set()  # authenticated search results contain literal file text
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
        if tc.get('id') in ledger_reads or tc.get('id') in ledger_answers:
            return False
        if tc.get('id') in ledger_writes:
            return tc.get("id") not in failed_ids
        fn = tc.get("function") or {}
        original = (_read_sentinel(_command_of(fn.get("arguments")), tc.get("id"))
                    if is_shell_tool_name(fn.get("name")) else None)
        if original is not None:
            return original["name"] in (_WRITE_NAMES | _EDIT_NAMES) and tc.get("id") not in failed_ids
        return _native_effect_unknown_or_mutating(fn, workspace_root)
    anchored = {anchor: list(found) for anchor, found in (ledger_surveys or {}).items()}

    def survey_after(anchor):
        """The surveys cria asked for on its own right after the tool result ``anchor`` (None: before everything), in order."""
        for found in anchored.pop(anchor, ()):
            view.observation_pending(bool(pending_mutations))
            observation = view.begin_observation(uncertain=bool(pending_mutations))
            if not wsview.from_observation(observation, wsview.apply_survey, view, found) and rlog is not None:
                # A rejected survey is the one failure `wsview` cannot show from the outside (#12).
                rlog.emit("wsview.survey_rejected", level="warn", **wsview.last_reject())
    survey_after(None)
    previous = None
    for m in messages:
        if previous is not None:
            survey_after(previous)
            previous = None
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
                led = ledger_reads.get(tc.get("id")) or ledger_writes.get(tc.get("id")) or ledger_answers.get(tc.get("id"))
                if led is not None or is_shell_tool_name(name):
                    orig = ({"name": led.name, "arguments": led.arguments} if led is not None
                            else _read_sentinel(_command_of(fn.get("arguments")), tc.get("id")))
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
                        if isinstance(led, LedgerRead) and led.hold:
                            unread_hold_ids.add(tc.get('id'))
                        lowered_ids.add(tc.get('id'))
                        tc = {**tc, "function": {"name": orig["name"], "arguments": orig["arguments"]}}
                        swapped += 1
                        if orig["name"] in (_WRITE_NAMES | _EDIT_NAMES | {'apply_patch'}):
                            p = _parse(orig["arguments"])
                            if orig['name'] == 'apply_patch':
                                from .toolargs import patch_paths
                                paths = patch_paths({'function': orig})
                                if len(paths) == 1:
                                    p = {**p, 'path': paths[0]}
                            if orig["name"] in _EDIT_NAMES and tc.get("id") in paired:
                                preimage = view.capture_edit_preimage(_tool_path(p))
                                if preimage is not None:
                                    edit_preimages[tc.get("id")] = preimage[0]
                            if tc.get("id") not in failed_ids and not isinstance(led, LedgerRead):
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
                            held = tc.get('id') in unread_hold_ids and tc.get('id') in paired
                            if tc.get("id") in failed_ids or held:
                                draft = toolstages.current().preserve_draft(
                                    tc, _tool_path(p) or "", rlog if _first_sight_of_rejection(sess_key, tc) else None,
                                    unread_hold=held)
                                if draft.note:
                                    rejected_notes_by_id[tc.get("id")] = draft.note
                                tc = draft.call
                        elif orig["name"] in (_READ_NAMES | _LIST_NAMES | _FETCH_NAMES | _SEARCH_NAMES | _SEARCH_FILE_NAMES):
                            if not isinstance(led, LedgerAnswer):       # cria's own words carry no harness envelope to strip
                                strip_ids.add(tc.get("id"))
                            if orig["name"] in _SEARCH_FILE_NAMES:
                                content_search_ids.add(tc.get("id"))
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
            previous = tid
            # THE PROVEN OUTCOME IS SET HERE, BEFORE any transform, preserve or recovery reads this message, and
            # whatever the client sent under that key is overwritten: a native client cannot nominate its own result.
            m = {k: v for k, v in m.items() if k not in (bodykeys.RESULT_OUTCOME, bodykeys.READ_OBSERVATION, bodykeys.RESULT_REPORT, bodykeys.UNREAD_HOLD)}
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
            # This marks the paired dispatch decision, not proof that the read or refusal ran.
            if tid in unread_hold_ids and tid in paired:
                m[bodykeys.UNREAD_HOLD] = True
            proof = proofs.get(tid)
            if proof is not None:
                m["content"] = proof.content       # exactly cria's own records removed; the payload keeps its bytes
                m[bodykeys.RESULT_OUTCOME] = proof.kind
                if proof.rep:
                    m[bodykeys.RESULT_REPORT] = proof.rep
            elif ledger_outcomes and tid in ledger_outcomes:
                m[bodykeys.RESULT_OUTCOME] = ledger_outcomes[tid]
            elif tid in lowered_ids:
                m[bodykeys.RESULT_OUTCOME] = denial.UNKNOWN   # cria lowered this call and cannot prove its branch
            if tid in ambiguous:
                # AMBIGUOUS: nothing call-attributed is cached, stripped or rendered, and no recovery or
                # advice is composed from it — it keeps its actual bytes (no frame is trusted, so no survey is
                # taken either).
                out.append({**m, "content": _debinarized(str(m.get("content") or ""))})
                continue
            # A verified UTF-8 read or authenticated search result contains user file text, not terminal log
            # decoration. Stripping ANSI or binary-looking controls would change the returned text.
            if (proof is not None and tid in content_search_ids and proof.kind == denial.RAN) or (proof is not None and proof.exact and proof.text is not None and proof.observe in (resultpacket.WHOLE, resultpacket.RANGE)):
                content = str(m.get('content') or '')
            else:
                content = _debinarized(str(m.get("content") or ""))
            if tid in own_cmds and (envelope := exec_envelope(content)) is not None and envelope.exit_code == 0:
                # A SUCCESSFUL RUN OF THE CODER'S OWN COMMAND is ground truth that its programs exist (`dirguard.programs_that_ran`).
                for program in dirguard.programs_that_ran(own_cmds[tid]):
                    view.note_program_ran(program)
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
                    from .readcontext import record_prefix
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
            elif tid in write_paths and tid in landed_ids:  # write/edit SUCCESS: the ledger's text (the confirmation, the window, the removal facts)
                out.append({**m, "content": proof.content})
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
    if previous is not None:
        survey_after(previous)
    if mutation_ids - paired:
        # Later surveys do not settle an unresolved/ambiguous native invocation.
        view.note_possible_effect()
    if swapped and rlog is not None:
        rlog.emit("writeproxy.represented", calls=swapped)
    toolstages.current().returned_history(
        ReturnedHistory(out, own_cmds, workspace_root, sess_key, tools_present, rlog, window, ask))
    return out


# The dependency-note budgets (one surface inline, and the sum of all notes per request) live in
# ``returnedpolicies._note_budgets`` / ``windowcaps`` — window-sized, one definition.
