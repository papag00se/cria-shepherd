"""Source-owned output interventions; parsing and wire admission stay shared."""
from __future__ import annotations
import json
import re

from . import argumentconversion, bodykeys, generation, jsontext
from .assistcontract import Policy, Reference
from .toolcontracts import CompletionDefinition, CompletionTransform
from .callsyntax import (
    _GEMMA_STR, _HERMES, _XML_FN, _LFM2_TC_CLOSE, _LFM2_TC_OPEN,
    _FENCED_BLOCK, _WORDS_BETWEEN_CALLS, _LEAK_MARKERS,
    _alias, _call_syntax_calls, _envelope_calls, _extract_gemma, _fenced_envelope,
    _has_tool, _is_quoted, _is_terminal, _menu_admits, _menu_schemas,
    _reasoning_call_spans, _strip_channel, _strip_lfm2_sentinels, _tool_names,
    _toolcall, _xml_args, content_text, has_tool_call_leak, turn_text,
)
from .callformats import (
    _EXEC_NAMES, _READ_NAMES, _SHELL_CMD_ALIASES, _alias_command, _canon_key,
    _canonical_name_map, _command_string, _edit_to_patch, _normalize_patch_body,
    _pure_add_file, _read_command, _normalize_read_args,
)
from .callliterals import _FUSED_SENTINELS, _recover_write_args, recover_fused_call, trim_fused_tail
from .jsontext import extract_json_object
from .shelltool import find_shell_tool, shell_args
from .toolargs import PATH_KEYS, parse_args as _args, tool_path as _tool_path


LOST_CALL_KEY = bodykeys.LOST_CALL
_TEXT_FENCE_TAGS = ("", "plaintext", "text")
_ECHO_FLOOR = 80


def _log(rlog, kind: str, **fields) -> None:
    if rlog is not None:
        rlog.emit(kind, **fields)


def _convert_arguments(name: str, args: dict, schemas: dict, rlog=None) -> dict:
    """Execute only the exact selected converter at an already eligible position."""
    definition = argumentconversion.selected_definition()
    if definition is None:
        return args
    converted = definition.execute(name, args, schemas)
    if converted != args:
        _log(rlog, 'massage.arguments_converted', assist_id=definition.policy.id,
             family_id=definition.policy.family_id, tool=name)
    return converted


def _extract_leaked(content: str, schemas: dict | None = None, rlog=None) -> tuple[list[dict], str]:
    """Content dialect orchestration; raw XML parsing never owns conversion."""
    calls: list[dict] = []
    cleaned = content
    for m in _HERMES.finditer(content):
        obj = extract_json_object(m.group(1))
        if obj and obj.get('name'):
            calls.append(_toolcall(str(obj['name']), obj.get('arguments', {})))
            cleaned = cleaned.replace(m.group(0), '')
    for m in _XML_FN.finditer(content):
        name, body = m.group(1), m.group(2)
        args = _xml_args(body) or {}
        resolved = _alias(name)
        converted = _convert_arguments(resolved, args, schemas or {}, rlog)
        calls.append(_toolcall(resolved, converted))
        cleaned = cleaned.replace(m.group(0), '')
    gemma_calls, cleaned = _extract_gemma(cleaned)
    calls.extend(gemma_calls)
    return calls, cleaned.replace(_GEMMA_STR, '').strip()


def _echoes_a_draft(args: dict, drafts: list[str]) -> bool:
    if any(d.lstrip().startswith('{') for d in drafts):
        return False
    normed = {''.join(d.split()) for d in drafts}
    for v in args.values():
        if isinstance(v, str):
            n = ''.join(v.split())
            if len(n) >= _ECHO_FLOOR and n in normed:
                return True
    return False


def _fenced_envelope_call(content: str, tools) -> tuple[list[dict], str, dict, str | None]:
    """Apply the existing leader/menu/draft admission rules above raw readers."""
    schemas = _menu_schemas(tools)
    if not schemas:
        return [], content, {}, None
    blocks = list(_FENCED_BLOCK.finditer(content))
    first = None
    drafts: list[str] = []
    for fm in blocks:
        env = _fenced_envelope(fm.group(2))
        if env is not None:
            first = (fm, env)
            break
        if fm.group(1) not in _TEXT_FENCE_TAGS:
            drafts.append(fm.group(2))
    if first is None:
        return [], content, {}, None
    fm, (name, args) = first
    about = {'tool': name, 'path': next((v for k, v in args.items()
                                       if k in PATH_KEYS and isinstance(v, str)), '')}
    if drafts and not _echoes_a_draft(args, drafts):
        return [], content, about, 'prefix_fence'
    if _is_quoted(content, fm.start()):
        return [], content, about, 'nested'
    props = set((schemas.get(name) or {}).get('properties') or {})
    if name not in schemas:
        return [], content, about, 'off_menu'
    if not set(args) <= props or not _menu_admits(name, args, schemas):
        return [], content, about, 'inadmissible'
    later = sum(1 for b in blocks if b.start() > fm.start() and _fenced_envelope(b.group(2)) is not None)
    fields = {'later_envelopes': later, 'dropped_chars': len(content) - fm.start()}
    return [_toolcall(name, args)], content[:fm.start()].rstrip(), fields, None


def _to_shell(fn: dict, shell: dict, cmd, why: str, rlog) -> None:
    if not cmd:
        return
    fn['name'] = shell['name']
    fn['arguments'] = json.dumps(shell_args(shell, cmd))
    _log(rlog, 'massage.tool_normalized', why=why)


def _reshape_shell(fn: dict, shell: dict, rlog) -> None:
    args = _args(fn.get('arguments'))
    raw = args.get('command')
    if raw is None:
        raw = args.get('cmd')
    if raw is None:
        return
    cmd = _command_string(raw)
    if cmd is None:
        return
    fixed = {k: v for k, v in args.items() if k not in ('command', 'cmd')}
    fixed.update(shell_args(shell, cmd))
    if fixed != args:
        fn['arguments'] = json.dumps(fixed)
        _log(rlog, 'massage.shell_reshaped')


def promote_call(completion: dict, call: dict, keep: str, tools, rlog=None,
                 *, repair: CompletionTransform, **fields) -> dict:
    """Promote above parsers, then explicitly request upper selected repair."""
    if not generation.may_recover(completion):
        return completion
    choice = completion['choices'][0]
    msg = choice['message']
    msg['tool_calls'] = [call]
    msg['content'] = keep or None
    if choice.get('finish_reason') in (None, 'stop'):
        choice['finish_reason'] = 'tool_calls'
    _log(rlog, 'massage.text_write_recovered', reshape='massage',
         calls=[call['function']['name']], **fields)
    return repair(completion, tools, rlog)

def strip_debris_from_args(completion: dict, rlog=None) -> dict:
    """Cut a fused call's protocol debris off the END of every string tool ARGUMENT.

    `_bounded_xml_params` already does this for calls cria itself parses out of text. It cannot run
    on a call the SERVER parsed — `recover_leaked_tool_calls` skips those by design
    (``if msg.get("tool_calls"): continue``) — and that is the channel a weak model's fused call
    arrives on when the template parser accepts it.

    Walked on cycle 4 cell 22 (`feed-pipeline-java x nemotron-elastic`, 5% useful). The model omitted
    `</parameter>` and opened a second call in the same turn, so every argument it sent carried the
    tail `</function>` / `</tool_call>` / `<tool_call>` / `<function=write_file>` / `<parameter=path>`
    / the next call's path. cria refused the resulting `pom.xml` eight times as malformed XML at
    "line 34, column 1" — exactly where the junk began — and the coder, which cannot re-read its own
    rejected payload, re-derived the identical file by hand and was refused again.

    AT THE BOUNDARY, ONCE, FOR EVERY TOOL. The first cut of this lived in the writeproxy's
    `write_file` branch, which left `edit_file` — whose `old_string` AND `new_string` carried the same
    tail in that same run — still receiving the junk. An invariant about the arguments cria hands on
    belongs where the arguments are normalised, not in one consumer (#23, #24).

    These sentinels are `_LEAK_DEBRIS`, already documented there as tokens that NEVER appear in
    legitimate prose. Only a trailing run is cut and the cut may only land ON a tag, so a file whose
    real lines merely MENTION one is untouched — see writeproxy.trim_fused_tail."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                continue
            try:
                args = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(args, dict):
                continue
            cut = {k: trim_fused_tail(v) for k, v in args.items() if isinstance(v, str)}
            changed = {k: v for k, v in cut.items() if v != args[k]}
            if changed:
                fn["arguments"] = json.dumps({**args, **cut})
                if rlog is not None:
                    rlog.emit("massage.fused_tail_trimmed", level="warn",
                              tool=str(fn.get("name") or ""), args=",".join(sorted(changed)))
    return completion


def recover_reasoning_text(completion: dict, rlog=None) -> dict:
    """A turn that FINISHED with reasoning, no content and no tool call keeps its words.

    THE SIBLING OF :func:`recover_reasoning_tool_calls`, and its own docstring is the argument:
    "a lost turn forwards none … this function's only job is to stop losing the action". That one
    rescues an ACTION left in the reasoning channel. Nothing rescued a CONCLUSION left there, so a
    turn that reached one and emitted nothing was discarded whole — which is destroying model output
    (#5), by cria, at the wire.

    Measured across the three walked runs of 2026-08-27 (java/go/ruby x nemotron-elastic): every one
    of 249 coder turns produced reasoning and zero visible content, 1.54M characters of it, and every
    assistant turn in the model's own history is `content: ''` plus a tool call. 28 of those turns
    emitted no tool call either — 15 finished normally, 13 were cut by the rumination guard.

    Those 15 are the whole population this touches, and one of them decided a run: go call 0046
    reasoned *"we need to call loadDiscounts before using Discounts … inside Total, first call
    loadDiscounts(), then use Discounts"* — precisely the defect the shipped `cart.go` has — and the
    turn went back empty. The model re-derived the same conclusion at 0047, 0053, 0056, 0073, 0088
    and 0091, and never wrote the call, because nothing it concluded was ever in front of it again.

    ONLY ``finish_reason == "stop"``. A turn the rumination backstop cut is cut because the output
    degenerated, and carrying that forward is the thing the guard exists to prevent — the
    discriminator is the authoritative field on the choice, never a scan of the text (#12).

    It does not change routing. A turn with no tool call already reads as a completion claim one
    frame down (:func:`loop.unexecuted_write`), with or without content — and that detector reads
    the content it was never given, so on these turns it has been blind. Nothing here manufactures
    text: `turn_text` is the one owner for reading a model's words out of either channel
    (#19, #23), and it is asked only after the content is known to be empty."""
    if not generation.may_recover(completion):
        return completion
    for choice in completion.get("choices", []):
        if (choice.get("finish_reason") or "") != "stop":
            continue
        msg = choice.get("message")
        if not isinstance(msg, dict) or msg.get("tool_calls"):
            continue
        if content_text(msg.get("content")).strip():
            continue
        text = turn_text(msg)
        if not text:
            continue
        msg["content"] = text
        if rlog is not None:
            rlog.emit("massage.reasoning_text_recovered", level="info", chars=len(text))
    return completion


def recover_text_answer(completion: dict, tools=None, rlog=None) -> dict:
    """A TEXT answer was expected — the request offered no tools (a compaction/summary, a reasoner
    or critic call, a plain question) — but the model answered with a TOOL CALL instead: a native
    one, or a dialect leak already promoted to ``tool_calls`` by ``recover_leaked_tool_calls``.
    A tool call can't be the answer here, so recover the text: drop the spurious tool_calls and,
    if that leaves no content, promote the model's reasoning — where the answer was actually
    drafted (observed live: a gemma4 compaction reasoned out a full summary, then emitted a
    hallucinated ``<|tool_call>call:Gemma4__Try{…}`` as its 'answer', losing the summary). Dialect-
    agnostic and idempotent — it keys off 'has a tool call but no text', not any one syntax."""
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        # Dialect-debris content is NOT a text answer: a `<|tool_call>call:…` blob in content is a
        # mangled leaked call. It used to pass the has-text check untouched — a Codex LOCAL_COMPACT
        # summary came back as that blob (empty reasoning) and went to the harness verbatim, so the
        # post-compaction history carried tool-call junk instead of a continuation summary
        # (run 0729-gemma4 calls 0113/0167).
        has_text = isinstance(content, str) and content.strip() and not has_tool_call_leak(content)
        if has_text and not msg.get("tool_calls"):
            continue  # already a clean text answer
        if msg.get("tool_calls"):
            msg["tool_calls"] = None  # spurious: nothing was there to call
        if not has_text:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if isinstance(reasoning, str) and reasoning.strip():
                msg["content"] = reasoning.strip()
                _log(rlog, "massage.text_from_reasoning", reshape="massage", chars=len(reasoning.strip()))
            elif isinstance(content, str) and has_tool_call_leak(content):
                # No reasoning to promote — the model's real prose is INSIDE the fake call's string
                # payload (`content:<|"|># How to run …`). Salvage the longest delimited span: the
                # model's own words, never invented. Unparseable → leave as-is (the caller's retry
                # path owns it).
                spans = re.findall(re.escape(_GEMMA_STR) + r"(.*?)(?:" + re.escape(_GEMMA_STR) + r"|\Z)",
                                   content, re.DOTALL)
                best = max(spans, key=len).strip() if spans else ""
                if best:
                    msg["content"] = best
                    _log(rlog, "massage.text_from_dialect_payload", chars=len(best))
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"
    return completion


def lower_edit_file(completion: dict, tools=None, rlog=None) -> dict:
    """Rewrite an `edit_file`/`str_replace` find-replace as a native `apply_patch`
    Update hunk (old lines `-`, new lines `+`) — so an edit is escaping-proof too.
    Only when the harness doesn't run edit_file itself — AND only when it runs `apply_patch`.

    The guard asked one half of that. `apply_patch` is deliberately not in the advertised menu (a 9B
    cannot produce matching diff context), and on Codex the harness executes it anyway — a
    Codex-only guarantee that `toolmenu` states in the open. Every other harness gets a tool call by
    a name it never advertised and cannot run. Measured: `massage.edit_to_patch` fired **0 times in
    440,198 logged events**, because on Codex `advertise` always injects a synthetic `edit_file` and
    the branch is unreachable there. The path exists only where it is broken (#18)."""
    if _has_tool("edit_file", tools) or _has_tool("str_replace", tools):
        return completion
    if not _has_tool("apply_patch", tools):
        return completion
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") not in ("edit_file", "str_replace"):
                continue
            args = _args(fn.get("arguments"))
            path = _tool_path(args)
            old = args.get("old_string") or args.get("old_str") or args.get("old")
            if not path or old is None:
                continue
            new = args.get("new_string") or args.get("new_str") or args.get("new") or ""
            fn["name"] = "apply_patch"
            fn["arguments"] = json.dumps({"input": _edit_to_patch(str(path), str(old), str(new))})
            _log(rlog, "massage.edit_to_patch", path=path)
    return completion


def normalize_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Reshape the model's tool calls to the tools the harness actually advertised: a
    shell-ish NAME (`ls`/`cat`/`git`/…), a read tool, or an exec tool → the harness's
    `shell` with a proper command; a `shell` call with the wrong arg SHAPE (string vs
    argv, double-wrapped) fixed to its schema. No-op when the harness has no shell."""
    shell = find_shell_tool(tools)
    if shell is None:
        return completion
    names = _tool_names(tools)
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            if name == shell["name"]:
                _reshape_shell(fn, shell, rlog)
            elif name in names:
                continue  # the harness runs it natively
            elif name in _SHELL_CMD_ALIASES:
                _to_shell(fn, shell, _alias_command(name, _args(fn.get("arguments"))), "shell_name", rlog)
            elif name in _READ_NAMES and "read_file" not in names:
                a = _args(fn.get('arguments'))
                from .filecommands import canonical_read_args
                from .multipartcontext import record
                canonical = canonical_read_args(_normalize_read_args(a))
                if canonical is not None:
                    record(tc, json.dumps(canonical))
                _to_shell(fn, shell, _read_command(a), "read_lower", rlog)
            elif name in _EXEC_NAMES:
                a = _args(fn.get("arguments"))
                _to_shell(fn, shell, _command_string(a.get("cmd") if a.get("cmd") is not None else a.get("command")), "exec_command", rlog)
    return completion


def normalize_tool_names(completion: dict, tools=None, rlog=None) -> dict:
    """A ~12B model spells an advertised tool with the wrong CASE/separators (``EditFile`` / ``edit-file``
    for ``edit_file``). The exact-string dispatch downstream (normalize_tool_calls, writeproxy's
    ``name in _EDIT_NAMES``) then can't route it, so the call SILENTLY FAILS and the model believes it
    edited when it didn't — the exact churn seen live. Fold a mis-spelled name back to the one advertised
    tool with the same canonical key. Safety: matches ONLY tools actually advertised this request (can't
    invent a tool off the menu), only on an EXACT canonical-key hit, skips a name that is already valid
    (idempotent), and refuses when two advertised tools share a key. No-op when there are no tools."""
    cmap = _canonical_name_map(tools)
    if not cmap:
        return completion
    advertised = _tool_names(tools)
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name or name in advertised:      # empty, or already a real tool → leave it
                continue
            canon = cmap.get(_canon_key(name))
            if canon and canon != name:
                fn["name"] = canon
                _log(rlog, "massage.tool_renamed", reshape="massage", was=name, now=canon)
    return completion


def add_file_to_write_file(completion: dict, rlog=None) -> dict:
    """A pure file-creating apply_patch (`*** Add File:` + only `+` lines) → a robust
    write_file (which the writeproxy then lowers to a byte-exact shell write)."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "apply_patch":
                continue
            try:
                args = jsontext.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                continue
            body = args.get("input") or args.get("patch")
            if not isinstance(body, str):
                continue
            add = _pure_add_file(body)
            if add:
                path, content = add
                fn["name"] = "write_file"
                fn["arguments"] = json.dumps({"path": path, "content": content})
                _log(rlog, "massage.add_to_write", path=path)
    return completion


def recover_text_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Promote a tool call the model emitted as TEXT (Hermes `<tool_call>…`, XML
    `<function=…>`) into a real tool_calls entry, and strip it from the content.

    The ordered recovery stage follows this with reasoning-channel recovery.
    The public massage.recover_leaked_tool_calls entry also runs that stage, so
    the optional planner and the normal completion path share selection/order."""
    if not generation.may_recover(completion):
        return completion
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and "<|channel" in content:  # Gemma's thought channel
            content = _strip_channel(content)
            msg["content"] = content or None
        if isinstance(content, str) and (_LFM2_TC_OPEN in content or _LFM2_TC_CLOSE in content):
            content = _strip_lfm2_sentinels(content)  # llama.cpp recovered the call; strip its leaked text
            msg["content"] = content or None
        if msg.get("tool_calls"):
            continue  # already has real tool calls; don't double-recover
        if not isinstance(content, str) or not content.strip():
            continue
        calls: list[dict] = []
        cleaned = content
        fields: dict = {}   # extra event fields of the recovery that fired (the fenced envelope's drop count)
        if "<" not in content:
            # No angle-bracket dialect. The call may still be here as JSON DATA — the same leak,
            # a different envelope. Content is dropped whole (the call replaces it): a model that
            # emitted its actions as data has not also written an answer worth keeping.
            env = _envelope_calls(content, tools)
            if env:
                msg["tool_calls"] = env
                msg["content"] = None
                if choice.get("finish_reason") in (None, "stop"):
                    choice["finish_reason"] = "tool_calls"
                _log(rlog, "massage.envelope_recovered", reshape="massage",
                     calls=[c["function"]["name"] for c in env])
                continue
        else:
            calls, cleaned = _extract_leaked(content, _menu_schemas(tools), rlog)
        event = "massage.leaked_recovered"
        if not calls:
            # Neither dialect above. The call may still be here in CALL SYNTAX — `edit_file({…})` —
            # which is 46 of the 50 replies measured to hold an offered tool's own argument object
            # and no tool call at all. See the block comment on :func:`_call_syntax_calls`.
            #
            # A reply CUT AT THE OUTPUT CAP is refused outright, and this is the gate that earns its
            # keep: replaying the parser over the corpus, one truncated 123 KB reply
            # (20260728T000013 call 0514) parses into 252 `edit_file` calls — a generation that ran
            # away rather than a plan, and forwarding it would have been cria authoring a 252-action
            # turn out of a fragment. Gate 2's rule for one call ("a truncated call is not salvaged")
            # applied to the run: where the reply itself is truncated its LAST call is a guess, and
            # the run has no end the model wrote. The paths above are deliberately left alone — this
            # is regression-only, and it may not change what they already do.
            calls, cleaned = _call_syntax_calls(content, tools)
            if calls and choice.get("finish_reason") == "length":
                _log(rlog, "massage.call_syntax_truncated",
                     calls=[c["function"]["name"] for c in calls], chars=len(content))
                continue
            event = "massage.call_syntax_recovered"
        if not calls:
            # Third form, same chain: a call fenced as a JSON envelope. See the block comment on
            # :func:`_fenced_envelope_call`. The cap-cut refusal is the same gate as above.
            calls, cleaned, fields, why = _fenced_envelope_call(content, tools)
            if calls and choice.get("finish_reason") == "length":
                why, calls = "length", []
            if why:
                _log(rlog, "massage.fenced_call_refused", reason=why, chars=len(content))
                if why != "length" and fields.get("tool"):
                    # …and the coder hears of it (the loop pops this where it reads the turn).
                    completion[bodykeys.FENCED_REFUSED] = {"reason": why, "tool": fields["tool"],
                                                           "path": fields.get("path", "")}
                fields = {}
            if calls:
                event = "massage.fenced_call_recovered"
        if calls:
            msg["tool_calls"] = calls
            msg["content"] = cleaned or None
            if choice.get("finish_reason") in (None, "stop"):
                choice["finish_reason"] = "tool_calls"
            _log(rlog, event, reshape="massage", calls=[c["function"]["name"] for c in calls], **fields)
    return completion


def recover_reasoning_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Promote a complete tool call the model left in ``reasoning_content`` into a real ``tool_calls``
    entry — the one channel llama.cpp's own parser never reads. Full rationale, the refusal gates
    and the measured prevalence are in the block comment above.

    Additive and idempotent: it only ever ADDS ``tool_calls`` to a choice that had none, never edits
    the reasoning, and a second pass sees the calls it just added and does nothing.

    **Why the identical repeats are NOT deduplicated here.** 41 of the 68 recoveries in the corpus
    are byte-identical to one already recovered in the same session, 35 of them the same
    ``web_fetch('https://api.handle.me/swagger.yml', find='swagger')``, whose own reasoning says the
    previous attempt returned a 404. That looks like a reason to recover only the first of a kind.
    It is the opposite. The repeats are identical because the coder's PROMPT was identical — the
    same 33,168 bytes for thirty-five consecutive cycles — and the reason cria could never change
    that prompt is that :func:`loop.guard_track_refusals`, :func:`loop.guard_track_write_streak`,
    the search-loop matcher and the fetch ledger all iterate FORWARDED TOOL CALLS, and a lost turn
    forwards none. Recovering the call is what lets them see it: the third identical one trips
    ``redirect_due`` (``REPEAT_FINGERPRINT_N``), and a redirect changes the prompt. Suppressing the
    repeat here would starve the guard that ends the loop of the only evidence it runs on, and would
    re-create the deadlock one cycle later — a second, dumber repeat-detector in the massage layer,
    shadowing the real one (principle 4). The loop already owns "the same action, again"; this
    function's only job is to stop losing the action."""
    if not generation.may_recover(completion):
        return completion
    schemas = _menu_schemas(tools)
    if not schemas:
        return completion  # gate 4: no menu → nothing can be an action
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        # gate 1. Only a turn that is ALREADY lost. Note this also settles double-execution: if
        # llama.cpp surfaced the call itself, `tool_calls` is set and this returns untouched.
        if msg.get("tool_calls") or content_text(msg.get("content")).strip():
            continue
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not isinstance(reasoning, str) or not reasoning.strip():
            continue
        spans = _reasoning_call_spans(reasoning)
        if not spans:
            continue
        # THE TERMINAL RUN, NOT ONLY THE LAST SPAN. Gate 5 below requires the generation to have
        # STOPPED at the recovered call, which is why only the tail can be forwarded: a span with
        # prose after it is one the model reasoned past, and forwarding it would replay an action it
        # abandoned. But a model that wants several calls at once emits them BACK TO BACK, and
        # taking `spans[-1]` alone threw the rest away — a batch is not a supersession.
        #
        # Walked twice in the L5 cells: orders-api-py x qwen35 emitted parallel batches on five
        # turns and lost 10 calls, each re-asked singly afterwards; handles-cli-node x qwen35 asked
        # for lookup.js, package.json and README.md together at call 0003 and got one, spending
        # calls 0004 and 0005 re-asking for the other two.
        #
        # Adjacency is the whole test, and it is the model's own punctuation: spans separated by
        # nothing but whitespace are one batch; a span with words between it and the next is a
        # thought the model moved on from. Reading it needs no similarity judgement and no dialect
        # knowledge.
        run = [spans[-1]]
        while len(run) < len(spans):
            prev = spans[-(len(run) + 1)]
            if _WORDS_BETWEEN_CALLS.sub("", reasoning[prev[1]:run[0][0]]).strip():
                break                     # prose between them → the earlier one was abandoned
            run.insert(0, prev)
        start, end, dialect = run[0][0], run[-1][1], run[-1][2]
        parsed = [call for span in run for call in span[3]]
        # gate 5. TERMINAL — the generation stopped at this call — and not quoted inside a fence.
        if not _is_terminal(reasoning, end) or _is_quoted(reasoning, start):
            _log(rlog, "massage.reasoning_call_not_terminal", dialect=dialect,
                 calls=[n for n, _a in parsed], trailing=len(reasoning) - end,
                 quoted=_is_quoted(reasoning, start))
            continue
        # gate 4. Every call in the span must be admitted; one stranger refuses the lot, because a
        # partly-forwarded list is an action sequence the model never asked for.
        parsed = [(n, _convert_arguments(n, a, schemas, rlog))
                  for n, a in parsed]  # XML has no types; the schema does
        if not all(_menu_admits(n, a, schemas) for n, a in parsed):
            _log(rlog, "massage.reasoning_call_off_menu", dialect=dialect,
                 calls=[n for n, _a in parsed])
            # REFUSING TO FORWARD IS RIGHT; SAYING NOTHING IS NOT. The turn now leaves here exactly
            # as it arrived — empty content, no tool_calls — and the model reads that as its action
            # having produced no result. It repeats, or reasons on from memory, while downstream
            # cria reads the same empty turn as the coder FINISHING and runs the gate and the
            # satisfaction judge against a workspace where nothing happened.
            #
            # Measured across the six-language battery: nemotron-elastic's "quits after two calls"
            # signature is this. Run 1786436075 call 0006 is the FIRST action of the run — a
            # complete `str_replace_editor` view call in the reasoning channel — swallowed, and the
            # completion machinery engaged at calls 7-12 after two list_dirs. Calls 0167, 0178 and
            # 0180 are the same swallow again.
            #
            # cria owns the menu, so "that tool does not exist and here is what does" is a fact it
            # can state (#5b, the honest direction). It cannot be said here — this function only
            # reads the model's reply — so the fact rides out as a cria-internal hint and the loop
            # says it, the `cria_output_reserve` pattern (#24: carry the intent, consume it where it
            # belongs).
            completion[LOST_CALL_KEY] = {"tried": sorted({n for n, _a in parsed}),
                                         "menu": sorted(schemas)}
            continue
        msg["tool_calls"] = [_toolcall(n, a) for n, a in parsed]
        if choice.get("finish_reason") in (None, "stop"):
            choice["finish_reason"] = "tool_calls"
        _log(rlog, "massage.reasoning_call_recovered", dialect=dialect,
             calls=[n for n, _a in parsed], at=start, reasoning_chars=len(reasoning))
    return completion


def repair_tool_args(completion: dict, rlog=None) -> dict:
    """Ensure every tool call's ``arguments`` is a clean JSON string — unwrap ```` ``` ````
    fences, recover the object out of surrounding noise, else leave it be.

    A RECOVERY THAT LOSES THE CALL IS NOT A RECOVERY. `extract_json_object` returns the first
    brace-balanced span that parses to a dict, and on a CUT argument string the first such span is
    very often an empty brace pair belonging to the code the model was writing — `func main() {}`,
    `awk '{}'`, `${}`. The dict is `{}`, it is a dict, and the arguments were replaced with it.

    Reproduced, and found four times on this machine's captures: `write_file` calls of 6,026, 6,277,
    6,893 and 28,571 characters — one of them a whole test file — whose arguments became `{}`. All
    four sat on turns the rumination backstop had already aborted, so no damage is observed; the
    hazard is a turn the MODEL cut itself (`finish_reason="length"`), which this corpus also has.

    So an EMPTY recovered object never replaces a non-empty raw string. That is the whole rule: it
    needs no threshold and no schema, because `{}` carries nothing the model wrote and substituting
    it deletes the call outright. Every partial recovery still lands — a `write_file` rebuilt from
    raw newlines, a fenced object, an object with prose after it — because those carry the model's
    own values. When nothing is recovered the raw string is left exactly as written, which is what
    level 0 does, and what keeps the harness's parse error a true statement about the MODEL's output
    rather than about cria's repair (#5, #13)."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function")
            if not isinstance(fn, dict):
                continue
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                fn["arguments"] = json.dumps(raw if raw is not None else {})
                continue
            # A fused 2nd call trailing the real one comes FIRST — before the valid-JSON short-circuit —
            # because the leaked debris often parses as VALID-but-wrong JSON (it gets swallowed into a
            # string value), which `json.loads` would wave through unrecovered. Recover the real first
            # call (cut + unescape); if it can't be reconstructed, leave the debris for the writeproxy
            # refusal floor rather than mangling it further.
            if any(t in raw for t in _FUSED_SENTINELS):
                recovered = recover_fused_call(raw)
                if recovered.arguments is not None:
                    fn["arguments"] = json.dumps(recovered.arguments, ensure_ascii=False)
                    _log(rlog, "massage.fused_call_recovered", tool=fn.get("name"),
                         discarded_chars=recovered.discarded_chars)
                continue
            try:
                json.loads(raw)
                continue  # already valid
            except json.JSONDecodeError:
                obj = extract_json_object(raw)
                if obj is None:
                    obj = _recover_write_args(raw)  # raw newlines / unescaped quotes in content
                if obj == {} and raw.strip():
                    # AN EMPTY OBJECT IS NOT A RECOVERY. It carries nothing the model wrote, and
                    # substituting it deletes the call. See the docstring for the four real ones.
                    _log(rlog, "massage.args_recovery_refused", tool=fn.get("name"), raw_chars=len(raw))
                    obj = None
                if obj is not None:
                    fn["arguments"] = json.dumps(obj, ensure_ascii=False)
                    _log(rlog, "massage.args_repaired", reshape="massage", tool=fn.get("name"))
    return completion


def normalize_apply_patch(completion: dict, rlog=None) -> dict:
    """Repair an apply_patch body: decode a doubly-escaped `\\n` when there are no
    real newlines (the mixed-escape footgun), and ensure the Begin/End Patch
    envelope. Deeper normalization (unified-diff → native) is a later refinement."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "apply_patch":
                continue
            try:
                args = jsontext.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                continue
            key = "input" if "input" in args else ("patch" if "patch" in args else None)
            if key is None or not isinstance(args[key], str):
                continue
            fixed = _normalize_patch_body(args[key])
            if fixed != args[key]:
                args[key] = fixed
                fn["arguments"] = json.dumps(args, ensure_ascii=False)
                _log(rlog, "massage.patch_normalized")
    return completion


def stream_leak_position(content: str) -> int:
    found = [content.find(marker) for marker in _LEAK_MARKERS]
    found = [position for position in found if position >= 0]
    return min(found) if found else -1


def _definition(id, family, stage, execute, regression, needs_menu=True, stream_start=None, default_level=1):
    hook = {'output-recovery': 'recover_leaked_tool_calls',
            'output-repair': '_repair_calls', 'text-answer': 'coerce_text_answer'}[stage]
    hooks = (Reference('cria/massage.py', hook),)
    regressions = (regression,)
    if stream_start is not None:
        hooks += (Reference('cria/massage.py', 'massage_stream'),)
        regressions += (Reference('tests/test_output_selection_boundary.py',
                                  'test_bound_handler_selection_overrides_legacy_library_gate'),)
    return CompletionDefinition(Policy(id, stage, default_level, family_id=family, hooks=hooks,
        regressions=regressions, migrated=False), execute, needs_menu, stream_start)


RECOVERY = (
    _definition('text-call-recovery', 'F01', 'output-recovery', recover_text_calls,
                Reference('tests/test_tool_policy_stages.py', 'test_recovery_replacement_and_bypass_are_used_by_public_production_entry'),
                stream_start=stream_leak_position),
    _definition('reasoning-call-recovery', 'F01', 'output-recovery', recover_reasoning_tool_calls,
                Reference('tests/test_recovered_arg_types.py', 'BothRecoveryPathsUseItTests')),
)
REPAIR = (
    _definition('call-debris-repair', 'F01', 'output-repair', strip_debris_from_args,
                Reference('tests/test_a_fused_tail_is_cut_not_refused.py', 'TheJunkIsCutTests'), False),
    _definition('tool-name-normalization', 'F04', 'output-repair', normalize_tool_names,
                Reference('tests/test_massage.py', 'NormalizeToolNamesTests')),
    _definition('malformed-argument-repair', 'F06', 'output-repair', repair_tool_args,
                Reference('tests/test_massage.py', 'ArgRepairTests'), False),
    _definition('shell-tool-adaptation', 'F04', 'output-repair', normalize_tool_calls,
                Reference('tests/test_massage.py', 'NormalizeToolCallsTests')),
    _definition('edit-patch-adaptation', 'F05', 'output-repair', lower_edit_file,
                Reference('tests/test_massage.py', 'EditFileTests')),
    _definition('add-file-adaptation', 'F05', 'output-repair', add_file_to_write_file,
                Reference('tests/test_massage.py', 'AddFileTests'), False),
    _definition('patch-normalization', 'F05', 'output-repair', normalize_apply_patch,
                Reference('tests/test_massage.py', 'ApplyPatchTests'), False),
    _definition('reasoning-text-recovery', 'F08', 'output-repair', recover_reasoning_text,
                Reference('tests/test_a_finished_turn_keeps_its_words.py', 'AFinishedTurnKeepsItsWordsTests'), False),
)
# Unlike apply(), the existing server's tool-free answer path is not L1-gated.
# Preserve that applicability; changing L0 behavior is not part of this movement.
TEXT_ANSWER = (_definition('tool-free-text-recovery', 'F08', 'text-answer', recover_text_answer,
    Reference('tests/test_massage.py', 'CoerceTextAnswerTests'), default_level=0),)
