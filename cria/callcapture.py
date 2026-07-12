"""Full-fidelity capture of EXACTLY what the model sees on every call.

cria transforms every request before it reaches the model — it frames the current step,
applies the context floor (tool-schema bounding + trimming), injects the tool cheatsheet,
and sets sampling/reasoning. To know what the model ACTUALLY receives — not what the harness
sent, not what cria intended — this writes the exact final request body (messages, tools,
sampling params, ``chat_template_kwargs``) to one file per call, captured at the single
outbound chokepoint (:meth:`cria.upstream.Upstream._prep`). Deterministic, stdlib-only.

One file per call at ``<dir>/<session>/NNNN-<phase>.json`` (NNNN = per-session call order);
a pointer ``upstream.dump`` event lands in the JSONL so each capture correlates to the loop
events (``route.classify``, ``loop.item`` step=N, ``loop.probe`` …) sharing its session/turn.
The ``phase`` (coder / critic / classifier / planner / proxy) is read from ``rlog.phase`` —
whatever the calling subsystem set before the model call — so you can see, per turn, exactly
what each role was handed.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .content_reduce import est_tokens

_lock = threading.Lock()
_seq: dict[str, int] = {}


def _next_seq(session: str) -> int:
    with _lock:
        n = _seq.get(session, 0) + 1
        _seq[session] = n
        return n


def _safe(s) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)) if s else "nosession"


def _stats(body: dict) -> dict:
    msgs = body.get("messages") or []
    tools = body.get("tools") or []
    msg_tokens = est_tokens(json.dumps(msgs, ensure_ascii=False, default=str))
    tool_tokens = est_tokens(json.dumps(tools, ensure_ascii=False, default=str)) if tools else 0
    return {
        "n_messages": len(msgs),
        "n_tools": len(tools),
        "msg_tokens": msg_tokens,
        "tool_tokens": tool_tokens,
        "est_total": msg_tokens + tool_tokens,
    }


def capture(body: dict, rlog, *, calls_dir, phase: str | None = None, url: str = "",
            rendered: str | None = None) -> str | None:
    """Write the EXACT outbound ``body`` to a per-call file and emit ``upstream.dump``. When
    ``rendered`` (the flat prompt the model tokenizes, chat template applied) is given, also write
    it as a readable sibling ``.prompt.txt`` — the literal 'what the model sees'. Returns the JSON
    file path, or ``None`` on failure. Best-effort — never breaks the request."""
    try:
        session = getattr(rlog, "session", None)
        turn = getattr(rlog, "_turn", None) or getattr(rlog, "turn", None)
        sess = _safe(session)
        seq = _next_seq(sess)
        d = Path(calls_dir).expanduser() / sess
        d.mkdir(parents=True, exist_ok=True)
        now = time.time()
        stats = _stats(body)
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", phase) if phase else "call"
        record = {
            "seq": seq,
            "iso": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
            "session": session,
            "turn": turn,
            "phase": phase,
            "url": url,
            "stats": stats,
            "body": body,  # EXACTLY what cria serializes and POSTs to the server
        }
        if rendered is not None:
            # the flat string the model ACTUALLY tokenizes (chat template applied) — the ground truth
            prompt_name = f"{seq:04d}-{label}.prompt.txt"
            (d / prompt_name).write_text(rendered, encoding="utf-8")
            record["rendered_prompt_file"] = prompt_name
            stats["rendered_chars"] = len(rendered)
            stats["rendered_tokens_est"] = est_tokens(rendered)
        path = d / f"{seq:04d}-{label}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        rlog.emit("upstream.dump", path=str(path), seq=seq, phase=phase,
                  rendered=rendered is not None, **stats)
        return str(path)
    except (OSError, TypeError, ValueError):
        return None
