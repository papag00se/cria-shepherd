"""Massages — silent repairs of the local model's OUTPUT so the harness accepts it.

A small model constantly mis-formats its tool calls: it leaks them as text in a
Hermes/XML dialect instead of the tool_calls field, wraps JSON args in ```` ```json ````
fences or breaks the escaping, and emits malformed apply_patch bodies. These
functions repair a completion dict in place-ish (returns a new dict) before cria
hands it back — the model never knows, the harness just sees valid tool calls.

Applied to BUFFERED completions (the loop's coder turns, the buffered proxy),
where the whole completion is in hand. Streaming-path recovery is a refinement.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
import json

from . import bodykeys, generation
# Library callers retain the real implementation's identity (no forwarding shim).
from .argumentconversion import coerce_args
from .jsontext import extract_json_object
from . import callliterals
from .shelltool import find_shell_tool, shell_args
from .toolargs import PATH_KEYS, WHOLE_FILE_WRITES
from .toolargs import parse_args as _parse_tool_args, parse_args as _args, tool_path as _tool_path
from .filecommands import _read_command as _wp_read_command
# Canonical pure helpers; selected recovery orchestration remains above these libraries.
from .callsyntax import (
    _SHELL_ALIASES, _HERMES, _XML_FN, _GEMMA_TC_OPEN, _GEMMA_TC_CLOSE, _GEMMA_STR,
    _LFM2_TC_OPEN, _LFM2_TC_CLOSE, _LEAK_DEBRIS, has_tool_call_leak, _has_tool, _tool_names,
    is_truncated, is_ruminating, _menu_schemas, _sole_required, _envelope_calls,
    _CALL_SYNTAX_OPEN, _CALL_SYNTAX_TERM, _skip_between_calls, _call_syntax_calls,
    _FENCED_BLOCK, _envelope_pair, _fenced_envelope, fenced_file_blocks, _PATH_TOKEN, _URL,
    binding_paths, has_call_envelope, whole_file_write_call, content_text, turn_text,
    _TAG_TOKEN, _FENCE, _is_terminal, _is_quoted, _literal_kwargs, _lfm2_native_calls,
    _WORDS_BETWEEN_CALLS, _reasoning_call_spans, _PARAM_OPEN, _PARAM_CLOSE,
    _PARAM_HARD_BOUNDARIES, _bounded_xml_params, _xml_args, _outermost, _menu_admits,
    _CHANNEL, _CHANNEL_FABLE, _strip_channel, _strip_delimited, _strip_lfm2_sentinels,
    _extract_gemma, _parse_gemma_call, _gemma_object, _gemma_array, _gemma_value,
    _gemma_scalar, _alias, _LEAK_MARKERS, _toolcall)
from .callformats import (
    _edit_to_patch, _SHELL_CMD_ALIASES, _READ_NAMES, _EXEC_NAMES, _BASH_HEADS, _canon_key,
    _canonical_name_map, _command_string, _alias_command, _read_command, _pure_add_file,
    _HUNK, _normalize_patch_body, _collapse_wrappers, _strip_ab, _unified_to_native,
    _repair_hunk_headers, _fix_hunk_lines)
from .callliterals import (
    _FUSED_SENTINELS, _PATH_RE, _CONTENT_RE, _json_structurally_complete,
    _recover_write_args, _content_value_end, _unescape_once, _MUTATION_TOOLS,
    _content_truncated, has_incomplete_tool_args, _decode_backslash_escapes, trim_fused_tail)



from . import toolstages
from .outputpolicies import (strip_debris_from_args, recover_reasoning_text,
    lower_edit_file, normalize_tool_calls, normalize_tool_names, add_file_to_write_file,
    recover_reasoning_tool_calls, repair_tool_args, normalize_apply_patch,
    _extract_leaked, _fenced_envelope_call, _echoes_a_draft, _to_shell, _reshape_shell, _log,
    _TEXT_FENCE_TAGS, _ECHO_FLOOR, promote_call as _promote_call)


def recover_leaked_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Public recovery stage, also used directly by the optional planner."""
    return toolstages.current().completions('recovery', completion, tools, rlog)


def coerce_text_answer(completion: dict, rlog=None) -> dict:
    return toolstages.current().completions('text_answer', completion, None, rlog)


def _recover_fused_call(raw: str) -> dict | None:
    """Recover the real first call from a fused/leaked ``arguments`` string: cut at the first tool-call/
    channel sentinel, then parse the head — first as-is, then undoing the over-escaped quotes (``\\"``→
    ``"``, ``\\'``→``'``) the model routinely emits inside the array. Returns the parsed args dict, or
    None when the head is still not valid JSON (genuinely mangled → the writeproxy refusal is the floor)."""
    return callliterals.recover_fused_call(raw).arguments




# Legacy library applicability is context-local. Request/task selection is the
# authority whenever explicitly bound, including an empty selection. The old
# attribute remains a compatibility snapshot for callers saving/restoring it;
# execution never reads that process-wide snapshot.
_TOOL_CALL_FIXES = True
_UNBOUND_TOOL_CALL_FIXES = ContextVar('unbound_tool_call_fixes', default=True)


def set_tool_call_fixes(enabled: bool) -> None:
    """Set the unbound library default; never override selected task stages.

    Servers must bind their authoritative runtime rather than use this setter.
    Existing direct library callers retain their opt-out in their own context.
    """
    global _TOOL_CALL_FIXES
    _TOOL_CALL_FIXES = bool(enabled)
    _UNBOUND_TOOL_CALL_FIXES.set(bool(enabled))


def _tool_call_fixes_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    if toolstages.is_bound():
        return True  # the selected tuples, not this legacy gate, decide what runs
    return _UNBOUND_TOOL_CALL_FIXES.get()


def apply(completion: dict, tools=None, rlog=None, *, tool_call_fixes: bool | None = None) -> dict:
    """Run all output massages, in order.

    LEVEL 1 — TOOL_CALL_FIXES. Every pass in this chain exists to make the many ways a model emits a
    tool call homogeneous: a dialect leaked into text or the reasoning channel, a fused tail, a
    misspelled tool name, fenced JSON arguments. None of it changes the TOOLSET and none of it is an
    assist, but all of it is a change to what the model said, so at the pure proxy it must not run.
    `tool_call_fixes=False` returns the completion untouched.

    Measured on the ladder, 2026-08-25: qwen35's first level-0 cell logged 66
    `massage.reasoning_call_recovered` — level 1's headline mechanism, running in the arm that is
    supposed to be without it. gemma4 never exposed it because it emits 6 of these in a whole
    campaign; qwen35 emits hundreds, which is exactly why the ladder runs more than one model."""
    completion = generation.safe_completion(completion)
    if not generation.may_recover(completion) and not any(
            (ch.get("message") or {}).get("tool_calls") for ch in completion.get("choices", [])):
        return completion
    if not _tool_call_fixes_enabled(tool_call_fixes):
        return completion
    completion = recover_leaked_tool_calls(completion, tools, rlog)  # text → real tool_calls
    return _repair_calls(completion, tools, rlog)


def _repair_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Every pass of :func:`apply` AFTER the recovery of a call out of text — shared with
    :func:`promote_call`, so a call recovered later (by the loop, which holds the judge and the
    workspace view the recovery needs) meets exactly the passes a native one does."""
    return toolstages.current().completions('repair', completion, tools, rlog)


def promote_call(completion: dict, call: dict, keep: str, tools, rlog=None, **fields) -> dict:
    """Make ``call`` THE tool call of the first choice, with ``keep`` as its content, then run the
    repairs a native call of the same name would have met in :func:`apply` — a recovered call is
    held to the same lowering and normalisation as a native one, never exempt from it."""
    return _promote_call(completion, call, keep, tools, rlog, repair=_repair_calls, **fields)
_HOLDBACK = 32  # keep this many trailing chars unemitted, so a leak marker start isn't leaked


@dataclass
class _StreamChoice:
    content: str = ''
    emitted: int = 0
    captured: bool = False
    native_calls: dict[int, dict] = field(default_factory=dict)
    finish: str = 'stop'
    evidence: dict = field(default_factory=dict)


def massage_stream(chunks, model: str, tools=None, rlog=None, post=None, *, tool_call_fixes: bool | None = None):
    """Massage a streaming completion. Content streams live, lagging by a few chars,
    until a leaked-call marker appears — then cria captures the rest, recovers the
    call, and emits it as real tool_call deltas. No leak → a normal live stream.

    ``post`` transforms admitted actions before emission, whether they arrived as
    structured fragments or were recovered from text. Ordinary prose remains live."""
    chunks = generation.quarantine_stream(chunks)
    global_evidence = {}
    states: dict[int, _StreamChoice] = {}

    for raw in chunks:
        if raw.strip() == b"data: [DONE]":
            continue  # skip, don't break — let the upstream generator run to its finally
        if raw.startswith(b"data:") and raw[5:].strip() != b"[DONE]":
            try:
                obj = json.loads(raw[5:])
            except (ValueError, UnicodeDecodeError):
                obj = {}
            if isinstance(obj, dict):
                if not obj.get('choices'):
                    global_evidence.update(obj.get(generation.EVIDENCE) or {})
                if obj.get("error"):
                    for index, state in states.items():
                        if len(state.content) > state.emitted:
                            yield _sse({'content': state.content[state.emitted:]}, model, index=index)
                    yield raw
                    return
        choice = _choice(raw)
        if choice is None:
            if not any(state.captured for state in states.values()):
                yield raw  # blank line / comment / heartbeat
            continue
        index = choice.get('index', 0)
        state = states.setdefault(index, _StreamChoice())
        state.evidence.update(obj.get(generation.EVIDENCE) or {})
        if choice.get("finish_reason"):
            state.finish = choice["finish_reason"]
            continue  # re-emitted for this choice at the end
        delta = choice.get("delta") or {}
        if delta.get("tool_calls"):
            # quarantine_stream has admitted these fragments at an explicit successful
            # terminal status. Assemble before repair/lowering; a fragment is not a call.
            for fragment in delta["tool_calls"]:
                call = state.native_calls.setdefault(fragment.get("index", 0), {
                    "type": "function", "function": {"name": "", "arguments": ""}})
                if fragment.get("id"):
                    call["id"] = fragment["id"]
                for key in ("name", "arguments"):
                    value = (fragment.get("function") or {}).get(key)
                    if value is not None:
                        call["function"][key] += value
            continue
        dc = delta.get("content")
        if dc is None:
            if not state.captured:
                yield raw  # role delta
            continue

        state.content += dc
        if state.captured:
            continue
        pos = toolstages.current().stream_start(state.content, rlog) if _tool_call_fixes_enabled(tool_call_fixes) else -1
        if pos >= 0:
            if pos > state.emitted:
                yield _sse({'content': state.content[state.emitted:pos]}, model, index=index)
                state.emitted = pos
            state.captured = True
        else:
            safe = len(state.content) - _HOLDBACK
            if safe > state.emitted:
                yield _sse({'content': state.content[state.emitted:safe]}, model, index=index)
                state.emitted = safe

    for index, state in (states or {0: _StreamChoice()}).items():
        evidence = {**global_evidence, **state.evidence}
        finish = state.finish
        if state.captured or state.native_calls:
            message = {'role': 'assistant', 'content': state.content}
            original_indices = {}
            if state.native_calls:
                message['tool_calls'] = [state.native_calls[i] for i in sorted(state.native_calls)]
                original_indices = {tc.get('id'): i for i, tc in state.native_calls.items()}
            completion = apply({generation.EVIDENCE: evidence, 'choices': [
                {'index': index, 'finish_reason': finish, 'message': message}]},
                tools, rlog, tool_call_fixes=tool_call_fixes)
            if post is not None:
                completion = post(completion)
            msg = completion['choices'][0]['message']
            cleaned = msg.get('content') or ''
            if len(cleaned) > state.emitted:
                yield _sse({'content': cleaned[state.emitted:]}, model, index=index)
            for i, tc in enumerate(msg.get('tool_calls') or []):
                call_index = original_indices.get(tc.get('id'), i)
                yield _sse({'tool_calls': [{'index': call_index, 'id': tc.get('id'),
                    'type': 'function', 'function': tc['function']}]}, model, index=index)
            if generation.incomplete(completion):
                finish = 'length'
            elif not state.native_calls:
                finish = 'tool_calls' if msg.get('tool_calls') else 'stop'
        elif len(state.content) > state.emitted:
            yield _sse({'content': state.content[state.emitted:]}, model, index=index)

        terminal = _sse({}, model, finish=('length' if evidence.get('incomplete') else finish), index=index)
        if evidence:
            obj = json.loads(terminal[5:]); obj[generation.EVIDENCE] = evidence
            terminal = b'data: ' + json.dumps(obj, ensure_ascii=False).encode() + b'\n\n'
        yield terminal
    yield b"data: [DONE]\n\n"


def _sse(delta: dict, model: str, finish=None, *, index: int = 0) -> bytes:
    payload = {"object": "chat.completion.chunk", "model": model, "choices": [{"index": index, "delta": delta, "finish_reason": finish}]}
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def _choice(raw: bytes):
    if not raw.startswith(b"data:"):
        return None
    payload = raw[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    choices = obj.get("choices") if isinstance(obj, dict) else None
    return choices[0] if choices else None


# ------------------------------------------------------------------ arg repair




def repair_history_tool_args(messages: list, rlog=None, *, recover: bool = True) -> list:
    """Compatibility for the existing non-private, directly imported library API.

    The source owns all recovery/enveloping decisions. Explicit root bindings,
    including empty ones, never inherit the unbound library default. The direct
    ``recover=False`` opt-out still retains mandatory lossless wire enveloping.
    """
    from . import assistbinding, historyarguments
    binding = assistbinding.current()
    definition = (historyarguments.DEFINITION if binding is assistbinding.UNBOUND else
                  historyarguments.selected_definition(binding.definitions))
    return historyarguments.prepare_history(messages, rlog, definition=definition, recover=recover)


# --- strict-template turn alternation (a WIRE normalization) -----------------------------------
#
# The template groups `tool` WITH `user`: a tool result is rendered as a user turn wrapping
# <TOOL_RESPONSE>[…]. So the two sides that must alternate are {user, tool} and {assistant}.
_USER_SIDE = ("user", "tool")

# The cria-internal body hint that turns this on, set by `Role.apply` from the role's
# `merge_consecutive_turns` and consumed + stripped by `Upstream._prep`. Same contract as
# `cria_output_reserve`: a hint cria carries on the body, never a wire field.
MERGE_TURNS_KEY = bodykeys.MERGE_TURNS
# A turn whose only action named a tool that does not exist. cria-internal, consumed and stripped by
# the loop, never on the wire. See the refusal site in recover_reasoning_tool_calls.
LOST_CALL_KEY = bodykeys.LOST_CALL


def merge_for_alternation(messages: list) -> list:
    """Collapse each run of consecutive same-side messages into one, so roles strictly alternate.

    For a Llama-lineage template the sides are {user, tool} and {assistant} — a tool result IS a
    user turn to that template, which is why merging by ROLE alone is not enough: cria commonly
    emits `tool` then a ⟦ctx:…⟧ `user` anchor, and that pair is already a violation.

    Nothing is dropped and nothing is reordered. cria's anchors are self-delimiting blocks — each
    opens with its own ⟦ctx:…⟧ marker — so concatenating them reads exactly as it did when they were
    separate turns. A merged run keeps the role of its FIRST message, which preserves the
    <TOOL_RESPONSE> framing when a tool result leads.

    The system message is left where it is: the template consumes messages[0] as the system prompt
    before the alternation loop ever runs, so it is outside the rule.

    THIS RUNS AT THE WIRE, and that placement is the whole fix. It lived in `Role.apply`, which runs
    mid-pipeline — so every later append defeated it. nemotron-nano run 1786243834 died on exactly
    that: `focustrim` appends its repeat-note as a `user` turn AFTER the role was applied, the body
    went out as `…, tool, user`, and the template answered `Conversation roles must alternate` six
    times until the harness gave up (calls 0075-0081, workspace empty). Four call sites append
    user-side turns after `Role.apply` — the plan-off driver, `guard_rumination`, `guard_truncation`,
    and the streaming proxy, which skips the trim entirely — so ordering them one by one is a
    band-aid per site (#4). At the wire there is no "later": this is the last transform before the
    body is serialized, alongside its assistant-side twin `_merge_consecutive_assistant` and the
    unconditional orphan-`tool` repair, both of which live here for the identical reason."""
    if not isinstance(messages, list) or len(messages) < 2:
        return messages

    def side(m):
        r = m.get("role") if isinstance(m, dict) else None
        return "u" if r in _USER_SIDE else ("a" if r == "assistant" else None)

    head = list(messages[:1]) if isinstance(messages[0], dict) and messages[0].get("role") == "system" else []
    out: list = []
    for m in messages[len(head):]:
        sd = side(m)
        prev = out[-1] if out else None
        # An assistant turn carrying tool_calls is a structured emission — never fold another
        # message into it, and never fold it into one. Only its TEXT siblings merge.
        mergeable = (sd is not None and prev is not None and side(prev) == sd
                     and not (prev.get("tool_calls") or m.get("tool_calls"))
                     and isinstance(prev.get("content"), str) and isinstance(m.get("content"), str))
        if mergeable:
            merged = dict(prev)
            merged["content"] = f"{prev['content']}\n\n{m['content']}".strip()
            out[-1] = merged
        else:
            out.append(dict(m) if isinstance(m, dict) else m)
    return head + out
