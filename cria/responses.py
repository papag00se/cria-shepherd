"""OpenAI **Responses API** ↔ **Chat Completions** translation.

Codex 0.142.5 dropped the chat-completions wire API — it only speaks the Responses
API (`POST /v1/responses` + a specific SSE event protocol) to a provider. cria's
entire pipeline (classify → plan loop → route → massage) works on chat-completions
dicts, so this module adapts at the HTTP edge:

* inbound  — a Responses request  → a chat-completions body (fed to the normal pipeline)
* outbound — a chat completion    → the Responses SSE event stream Codex expects

The event shapes here were validated end-to-end against Codex 0.142.5 (it rendered
the token from exactly this sequence). Output is fake-streamed: cria produces a
buffered completion, then this emits it as a single delta per item — Codex accepts
that, and it sidesteps incremental chat-SSE↔Responses-SSE delta translation.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

from .indicators import MARKER, THINK_FENCE


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


# ------------------------------------------------------------------ inbound

def to_chat_body(r: dict) -> dict:
    """Responses request → chat-completions body."""
    sys_parts: list[str] = []
    if isinstance(r.get("instructions"), str) and r["instructions"].strip():
        sys_parts.append(r["instructions"])

    rest: list[dict] = []
    for item in r.get("input") or []:
        if not isinstance(item, dict):
            continue
        t = item.get("type", "message")
        if t == "message":
            role = item.get("role")
            text = _content_text(item.get("content"))
            # `developer`/`system` items are instructions → fold into the single
            # leading system message (a 2nd leading system message breaks strict
            # chat templates — see toolmenu.add_cheatsheet).
            if role in ("system", "developer"):
                if text:
                    sys_parts.append(text)
            else:
                rest.append({"role": "assistant" if role == "assistant" else "user", "content": text})
        elif t == "function_call":
            rest.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": item.get("call_id") or item.get("id") or _new_id("call"),
                    "type": "function",
                    "function": {"name": item.get("name", ""), "arguments": _as_args_str(item.get("arguments"))},
                }],
            })
        elif t == "function_call_output":
            call_id = item.get("call_id") or item.get("id")
            if call_id is None:
                continue  # no id to pair on — a role:tool with null tool_call_id orphans and
                #           strict chat templates reject it; drop rather than fabricate an id
            rest.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": _output_text(item.get("output")),
            })
        # other item types (reasoning, etc.) are dropped — cria works from messages

    messages: list[dict] = []
    if sys_parts:
        messages.append({"role": "system", "content": "\n\n".join(p for p in sys_parts if p)})
    messages.extend(rest)

    body: dict = {"model": r.get("model"), "messages": messages, "stream": bool(r.get("stream"))}
    tools = _to_chat_tools(r.get("tools"))
    if tools:
        body["tools"] = tools
    choice = _to_chat_tool_choice(r.get("tool_choice"))
    if choice is not None:
        body["tool_choice"] = choice
    if r.get("parallel_tool_calls") is not None:
        body["parallel_tool_calls"] = r["parallel_tool_calls"]
    return body


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("input_text", "output_text", "text", "summary_text"):
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _output_text(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):  # some clients wrap output in content parts
        return _content_text(output)
    if isinstance(output, dict):
        return output.get("output") or output.get("text") or json.dumps(output)
    return "" if output is None else str(output)


def _as_args_str(args) -> str:
    """Return tool-call arguments as a VALID-JSON string. A model/harness sometimes
    emits arguments with raw newlines (or tabs) inside string values — invalid JSON.
    Left as-is, the upstream model server's chat-template tool parser 500s on it AND
    poisons every later turn (the whole history is re-parsed). Re-parse leniently
    (`strict=False` tolerates control chars) and re-serialize with proper escaping."""
    if isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    if not isinstance(args, str):
        return json.dumps(args or {})
    try:
        return json.dumps(json.loads(args, strict=False), ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return args  # unrecoverable — leave it (better than dropping the call)


def _to_chat_tool_choice(tc):
    """Translate a Responses `tool_choice` to the chat-completions form. Strings
    (`auto`/`none`/`required`) pass through. Responses' FLAT object form
    `{"type":"function","name":"foo"}` is NESTED to `{"type":"function","function":{"name":"foo"}}`
    (chat completions rejects the flat form). Any other object type (allowed_tools/mcp/…) is
    dropped — sending it verbatim is garbage the server can't honor. None → omit."""
    if tc is None or isinstance(tc, str):
        return tc
    if isinstance(tc, dict):
        if tc.get("type") == "function" and tc.get("name"):
            return {"type": "function", "function": {"name": tc["name"]}}
        if tc.get("type") == "function" and isinstance(tc.get("function"), dict):
            return tc  # already nested
    return None  # unrecognized object form → omit (fall back to the server's default)


def _to_chat_tools(tools) -> list[dict]:
    """Responses tools are FLAT (`{type:function, name, description, parameters}`);
    chat completions nests them under `function`. Non-function tools are skipped."""
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        fn = {"name": t.get("name", "")}
        if t.get("description") is not None:
            fn["description"] = t["description"]
        # A strict llama.cpp tool template can require the `parameters` key — default an
        # absent schema to the empty-object form rather than emit a param-less tool.
        fn["parameters"] = t["parameters"] if t.get("parameters") is not None else {"type": "object", "properties": {}}
        if t.get("strict") is not None:
            fn["strict"] = t["strict"]  # carry structured-output enforcement across the boundary
        out.append({"type": "function", "function": fn})
    return out


# ------------------------------------------------------------------ outbound

def _event(kind: str, obj: dict) -> bytes:
    obj.setdefault("type", kind)
    return f"event: {kind}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def created_event(resp_id: str, model: str) -> bytes:
    """The first event — emit it BEFORE the (slow) model work so the SSE stream
    opens immediately and the client doesn't sit on a silent socket."""
    return _event("response.created", {
        "response": {"id": resp_id, "object": "response", "status": "in_progress", "model": model, "output": []}
    })


def in_progress_event(resp_id: str) -> bytes:
    """A keepalive the Responses PROTOCOL recognizes. SSE comments are spec-ignorable — and the
    Codex extension's client ignores them for its idle timer too, so a long internal model call
    (a 27B compactor at ~7 tok/s) tripped "idle timeout waiting for SSE" with comments flowing.
    response.in_progress is a legal, contentless status event every Responses client must parse."""
    return _event("response.in_progress", {
        "response": {"id": resp_id, "object": "response", "status": "in_progress"}
    })


def failed_event(resp_id: str, message: str) -> bytes:
    """A TERMINAL `response.failed` SSE event. The error is generic (no `code`), which Codex maps to
    a RETRYABLE failure (ApiError::Retryable) — so on a mid-stream shutdown the client cleanly
    RE-SENDS the turn instead of seeing a bare EOF, which it can only escape via a manual interrupt
    that then gets mislabeled as a deliberate user abort."""
    return _event("response.failed",
                  {"response": {"id": resp_id, "status": "failed", "error": {"message": message}}})


# The model's reasoning can be a very long chain-of-thought; forward a generous but bounded slice
# as the "thinking" preamble (Codex renders the reasoning summary), not the entire transcript.
_REASONING_CAP = 8000


def _reasoning_item(text: str, idx: int) -> tuple[list[bytes], dict]:
    """A Responses REASONING item — the model's 'thinking'. Emitted on BOTH reasoning channels:

    * the SUMMARY channel (`response.reasoning_summary_text.delta`) — Codex renders this as the
      live, TRANSIENT 'thinking' status header (extracted bold chunk), which is replaced each turn
      and is NOT kept in the transcript; and
    * the raw CONTENT channel (`response.reasoning_text.delta` + the item's `content` field) — the
      channel gated by Codex's `show_raw_agent_reasoning` config, which is the one rendered into the
      PERSISTENT transcript. Without this channel the reasoning only ever flashed in the transient
      header and vanished on the next call.

    The item is opened first so the deltas have an active item to attach to. Shape mirrors the
    ResponseItem::Reasoning the client parses: ``{type: reasoning, summary: [{type: summary_text,
    text}], content: [{type: reasoning_text, text}]}`` (id/encrypted_content optional)."""
    item_id = _new_id("rs")
    done = {"id": item_id, "type": "reasoning",
            "summary": [{"type": "summary_text", "text": text}],
            "content": [{"type": "reasoning_text", "text": text}]}
    evs = [
        _event("response.output_item.added", {"output_index": idx,
            "item": {"id": item_id, "type": "reasoning", "summary": [], "content": []}}),
        _event("response.reasoning_summary_part.added", {"item_id": item_id, "output_index": idx,
            "summary_index": 0, "part": {"type": "summary_text", "text": ""}}),
        _event("response.reasoning_summary_text.delta", {"item_id": item_id, "output_index": idx,
            "summary_index": 0, "delta": text}),
        _event("response.reasoning_summary_text.done", {"item_id": item_id, "output_index": idx,
            "summary_index": 0, "text": text}),
        _event("response.reasoning_summary_part.done", {"item_id": item_id, "output_index": idx,
            "summary_index": 0, "part": {"type": "summary_text", "text": text}}),
        # Raw reasoning content — the persistent-transcript channel (needs show_raw_agent_reasoning).
        _event("response.reasoning_text.delta", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "delta": text}),
        _event("response.reasoning_text.done", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "text": text}),
        _event("response.output_item.done", {"output_index": idx, "item": done}),
    ]
    return evs, done


def status_item_open(idx: int = 0) -> tuple[bytes, bytes, str]:
    """Open the LIVE STATUS message item early — before any model work — so status lines can stream
    as output_text deltas while the pipeline grinds. Returns (item.added, part.added, item_id)."""
    item_id = _new_id("msg")
    return (
        _event("response.output_item.added", {"output_index": idx,
            "item": {"id": item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}}),
        _event("response.content_part.added", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "part": {"type": "output_text", "text": ""}}),
        item_id,
    )


def status_delta(item_id: str, text: str, idx: int = 0) -> bytes:
    return _event("response.output_text.delta",
                  {"item_id": item_id, "output_index": idx, "content_index": 0, "delta": text})


def status_item_close(item_id: str, text: str, idx: int = 0) -> tuple[list[bytes], dict]:
    """Close the status item; the DONE dict joins the completed response's output list (the harness
    stores it as assistant content — ⟦cria⟧-marked, stripped inbound like the banner)."""
    done = {"id": item_id, "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}
    return [
        _event("response.output_text.done", {"item_id": item_id, "output_index": idx, "content_index": 0, "text": text}),
        _event("response.content_part.done", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "part": {"type": "output_text", "text": text}}),
        _event("response.output_item.done", {"output_index": idx, "item": done}),
    ], done


def _message_item(text: str, idx: int) -> tuple[list[bytes], dict]:
    item_id = _new_id("msg")
    done = {"id": item_id, "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}
    evs = [
        _event("response.output_item.added", {"output_index": idx,
            "item": {"id": item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []}}),
        _event("response.content_part.added", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "part": {"type": "output_text", "text": ""}}),
        _event("response.output_text.delta", {"item_id": item_id, "output_index": idx, "content_index": 0, "delta": text}),
        _event("response.output_text.done", {"item_id": item_id, "output_index": idx, "content_index": 0, "text": text}),
        _event("response.content_part.done", {"item_id": item_id, "output_index": idx,
            "content_index": 0, "part": {"type": "output_text", "text": text}}),
        _event("response.output_item.done", {"output_index": idx, "item": done}),
    ]
    return evs, done


def _function_item(tc: dict, idx: int) -> tuple[list[bytes], dict]:
    fn = tc.get("function") or {}
    item_id = _new_id("fc")
    call_id = tc.get("id") or _new_id("call")
    args = _as_args_str(fn.get("arguments"))
    done = {"id": item_id, "type": "function_call", "status": "completed",
            "name": fn.get("name", ""), "call_id": call_id, "arguments": args}
    evs = [
        _event("response.output_item.added", {"output_index": idx,
            "item": {"id": item_id, "type": "function_call", "status": "in_progress",
                     "name": fn.get("name", ""), "call_id": call_id, "arguments": ""}}),
        _event("response.function_call_arguments.delta", {"item_id": item_id, "output_index": idx, "delta": args}),
        _event("response.function_call_arguments.done", {"item_id": item_id, "output_index": idx, "arguments": args}),
        _event("response.output_item.done", {"output_index": idx, "item": done}),
    ]
    return evs, done


def _reasoning_transcript_block(reasoning: str) -> str:
    """The model's reasoning, folded into the persistent message content so it rides in the SCROLLBACK
    — the only reliable persistence, since Codex renders the native reasoning channel only transiently
    (even with show_raw_agent_reasoning). BRACKETED by a ``⟦cria⟧ 💭`` fence so the body renders CLEAN
    (no per-line marker walling every code line a model like fabliq drafts in its reasoning);
    strip_history drops the whole fenced block from inbound history so the model never re-ingests it."""
    return f"{THINK_FENCE}\n{reasoning.strip(chr(10))}\n{THINK_FENCE}"


def body_events(completion: dict, resp_id: str, model: str, banner: str | None = None,
                show_reasoning: bool = False, reasoning_transcript: bool = False,
                start_index: int = 0, extra_items: list | None = None) -> Iterator[bytes]:
    """Everything after `response.created`: the model's reasoning (its 'thinking', when present and
    enabled), an optional cria banner line, one message item (if any text), one function_call item
    per tool call, then `response.completed`."""
    choice = (completion.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    out_items: list[dict] = list(extra_items or [])   # e.g. the closed live-status item at index 0
    idx = start_index

    reasoning = msg.get("reasoning_content")
    reasoning = reasoning.strip()[:_REASONING_CAP] if isinstance(reasoning, str) and reasoning.strip() else ""

    # The model's REASONING first, on the NATIVE reasoning channel — Codex renders it as the live
    # 'thinking' preamble (transient). cria captures it (upstream assembles message.reasoning_content)
    # and forwards it (dropped INBOUND by to_chat_body, so it never re-feeds the model).
    if show_reasoning and reasoning:
        evs, done = _reasoning_item(reasoning, idx)
        out_items.append(done); idx += 1
        yield from evs

    # The "⟦cria⟧ …" lead — the optional reasoning-transcript block (persistent 'thinking') then the
    # banner — rides in a message item. When the turn has text, it's PREPENDED into that content.
    # When the turn is tool-calls-only (the common case in a coding run), it becomes its own message
    # item AHEAD of the function calls — safe there because the tool call keeps the agent loop alive
    # (a lead is only a "the agent answered" signal on an otherwise EMPTY turn, which we still drop).
    # Either way it's stripped inbound (strip_history) so the model never re-ingests it and it can't
    # seed a compaction summary — the two hazards that once justified dropping it on tool-only turns.
    content = msg.get("content")
    text = content if (isinstance(content, str) and content) else None
    has_tool_calls = bool(msg.get("tool_calls"))
    lead_parts = []
    if reasoning_transcript and reasoning:
        lead_parts.append(_reasoning_transcript_block(reasoning))
    if banner:
        lead_parts.append(banner)
    lead = "\n".join(lead_parts)
    if lead and text:
        text = f"{lead}\n{text}"
    elif lead and has_tool_calls:
        text = lead  # tool-call-only turn — show the lead alongside the call, not dropped
    if text:
        evs, done = _message_item(text, idx); out_items.append(done); idx += 1
        yield from evs
    for tc in msg.get("tool_calls") or []:
        evs, done = _function_item(tc, idx); out_items.append(done); idx += 1
        yield from evs

    resp = {"id": resp_id, "object": "response", "status": "completed", "model": model,
            "output": out_items, "usage": _map_usage(completion.get("usage"))}
    yield _event("response.completed", {"response": resp})


def to_responses_sse(completion: dict, model: str, resp_id: str | None = None, banner: str | None = None) -> Iterator[bytes]:
    """Full SSE stream (created + body) — for when there's no early-created split."""
    rid = resp_id or _new_id("resp")
    yield created_event(rid, model)
    yield from body_events(completion, rid, model, banner)


def to_responses_json(completion: dict, model: str, show_reasoning: bool = False,
                      reasoning_transcript: bool = False, banner: str | None = None) -> dict:
    """Non-streaming Responses object (stream:false). Mirrors ``body_events`` — including the
    ⟦cria⟧ lead (reasoning transcript + banner) — so the buffered and streaming paths agree."""
    choice = (completion.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    out: list[dict] = []
    reasoning = msg.get("reasoning_content")
    reasoning = reasoning.strip()[:_REASONING_CAP] if isinstance(reasoning, str) and reasoning.strip() else ""
    if show_reasoning and reasoning:
        out.append({"id": _new_id("rs"), "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": reasoning}],
                    "content": [{"type": "reasoning_text", "text": reasoning}]})
    content = msg.get("content")
    text = content if (isinstance(content, str) and content) else None
    has_tool_calls = bool(msg.get("tool_calls"))
    lead_parts = []
    if reasoning_transcript and reasoning:
        lead_parts.append(_reasoning_transcript_block(reasoning))
    if banner:
        lead_parts.append(banner)
    lead = "\n".join(lead_parts)
    if lead and text:
        text = f"{lead}\n{text}"
    elif lead and has_tool_calls:
        text = lead  # tool-call-only turn — show the lead alongside the call, not dropped
    if text:
        out.append({"id": _new_id("msg"), "type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": text}]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        out.append({"id": _new_id("fc"), "type": "function_call", "status": "completed",
                    "name": fn.get("name", ""), "call_id": tc.get("id") or _new_id("call"),
                    "arguments": _as_args_str(fn.get("arguments"))})
    return {"id": _new_id("resp"), "object": "response", "status": "completed", "model": model,
            "output": out, "usage": _map_usage(completion.get("usage"))}


def _map_usage(u) -> dict:
    u = u or {}
    inp = u.get("prompt_tokens", 0)
    out = u.get("completion_tokens", 0)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": u.get("total_tokens", inp + out)}


def session_key_of(r: dict) -> str | None:
    """Codex sends a stable `prompt_cache_key` per conversation — use it to correlate
    cria's plan-loop turns (store:false means each request carries the full input)."""
    k = r.get("prompt_cache_key")
    return str(k) if k else None
