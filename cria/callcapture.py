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

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .content_reduce import est_tokens

_lock = threading.Lock()
_seq: dict[str, int] = {}


_SEQ_NAME = re.compile(r"^(\d{4})-")


def _resume_seq(d: Path) -> int:
    """The highest ``NNNN`` already written in this session's folder, or 0.

    THE FOLDER IS RESTART-STABLE AND THE COUNTER WAS NOT. `session_dirname` is deliberately
    deterministic — "identical for every call of a session and across restarts, with no stored
    state" — while this counter lived only in memory, so a restart mid-session began writing
    `0001-*` over the first call's capture. cria restarts about 53 times a day (the
    restart-after-every-change rule), and 21 of 293 sessions in the log window span one.

    Counted exactly from `upstream.dump`, which carries its own path: **25,823 distinct capture
    paths written, 189 written more than once, 274 captures destroyed** across 22 session folders,
    one path written eleven times. One folder holds three interleaved runs of a single session id
    whose first calls are simply gone. This is the evidence store the project diagnoses from, and it
    was being corrupted silently."""
    try:
        return max((int(m.group(1)) for f in d.iterdir()
                    if (m := _SEQ_NAME.match(f.name))), default=0)
    except OSError:
        return 0


def _next_seq(session: str, d: Path) -> int:
    with _lock:
        n = _seq.get(session)
        if n is None:
            n = _resume_seq(d)
        n += 1
        _seq[session] = n
        return n


def _safe(s) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)) if s else "nosession"


_UUID7_RE = re.compile(r"([0-9a-f]{8})-([0-9a-f]{4})-(7[0-9a-f]{3})-", re.I)


def uuid7_epoch(session) -> float | None:
    """The creation time a UUIDv7 embeds, as unix SECONDS — the durable 'when did this session
    start' anchor (identical across cria restarts, no stored state). None for a non-v7 id."""
    m = _UUID7_RE.match(str(session or ""))
    if not m:
        return None
    try:
        return int(m.group(1) + m.group(2), 16) / 1000.0
    except (ValueError, OverflowError):
        return None


def _uuid7_stamp(session) -> str | None:
    """The creation time a UUIDv7 embeds in its first 48 bits → local ``YYYYMMDDTHHMMSS``.
    Codex's ``prompt_cache_key`` (the cria session id) is a v7 UUID, so this is deterministic —
    identical for every call of a session and across restarts, with no stored state. ``None``
    when the id isn't a v7 UUID."""
    m = _UUID7_RE.match(str(session or ""))
    if not m:
        return None
    try:
        ms = int(m.group(1) + m.group(2), 16)  # unix milliseconds
        return datetime.fromtimestamp(ms / 1000).strftime("%Y%m%dT%H%M%S")  # local wall-clock
    except (ValueError, OverflowError, OSError):
        return None


def session_dirname(session) -> str:
    """The per-run folder name: ``<YYYYMMDDTHHMMSS>-<session>`` so the newest run sorts last and
    the time is legible at a glance. The timestamp is decoded from the (UUIDv7) session id; for a
    non-v7 id the bare safe id is used — degrading to the old naming rather than inventing an
    unstable ``now()`` prefix that would fork the folder per call."""
    safe = _safe(session)
    ts = _uuid7_stamp(session)
    return f"{ts}-{safe}" if ts else safe


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


def capture_inbound(raw: bytes, rlog, *, calls_dir, api: str) -> str | None:
    """Retain an exact valid harness request before an API adapter transforms it.

    Inbound receipts deliberately have no ``NNNN`` identity: they correlate by the
    bound request turn and must never advance the model-call sequence.
    """
    try:
        session = getattr(rlog, "session", None)
        turn = getattr(rlog, "_turn", None) or getattr(rlog, "turn", None)
        d = Path(calls_dir).expanduser() / session_dirname(session)
        d.mkdir(parents=True, exist_ok=True)
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", str(turn or "noturn"))
        api_label = re.sub(r"[^A-Za-z0-9._-]+", "-", api)
        path = d / f"inbound-{label}-{api_label}.json"
        path.write_bytes(raw)
        rlog.emit("inbound.dump", api=api, path=str(path), bytes=len(raw),
                  sha256=hashlib.sha256(raw).hexdigest())
        return str(path)
    except (OSError, TypeError, ValueError):
        return None


def capture(body: dict, rlog, *, calls_dir, phase: str | None = None, url: str = "",
            rendered: str | None = None, coder_preframe: dict | None = None) -> str | None:
    """Write the EXACT outbound ``body`` to a per-call file and emit ``upstream.dump``. When
    ``rendered`` (the flat prompt the model tokenizes, chat template applied) is given, also write
    it as a readable sibling ``.prompt.txt`` — the literal 'what the model sees'. ``coder_preframe``
    is an out-of-band live-state receipt supplied by the final wire owner. Returns the JSON
    file path, or ``None`` on failure. Best-effort — never breaks the request."""
    try:
        session = getattr(rlog, "session", None)
        turn = getattr(rlog, "_turn", None) or getattr(rlog, "turn", None)
        sess = session_dirname(session)  # <timestamp>-<session>, sortable; stable per session
        d = Path(calls_dir).expanduser() / sess
        d.mkdir(parents=True, exist_ok=True)
        seq = _next_seq(sess, d)  # seeded from what is already there, so a restart cannot overwrite
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
        if coder_preframe is not None:
            # A separate observation receipt: never a request-body field and therefore incapable
            # of changing what the model sees.  The wire owner supplies its final byte identity.
            record["coder_preframe"] = coder_preframe
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


def capture_response(request_path: str | None, response, rlog=None) -> str | None:
    """Write the model's RESPONSE next to its request capture, at ``NNNN-<phase>.response.json``.
    The request capture records what cria SENT; this records what the model ANSWERED — the raw
    tool-call dialect leak, the plan, the reasoning — so a forced-plan leak or a repeat-force is
    reconstructable from disk instead of only from a replay. ``request_path`` is what ``capture``
    returned (None → no-op); ``response`` is the raw bytes or a parsed dict. Best-effort."""
    if not request_path:
        return None
    try:
        base = Path(request_path)
        rp = base.with_name(base.stem + ".response.json")
        obj = response
        if isinstance(response, (bytes, bytearray)):
            try:
                obj = json.loads(response)
            except (json.JSONDecodeError, ValueError):
                obj = {"raw": bytes(response).decode("utf-8", "replace")}
        rp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if rlog is not None:
            rlog.emit("upstream.response_dump", path=str(rp))
        return str(rp)
    except (OSError, TypeError, ValueError):
        return None
