"""Claude-CLI provider — the Anthropic escalation path, ported from codex-local.

codex-local's ``provider = "anthropic"`` does NOT call the Anthropic API; it shells
out to the ``claude`` CLI (Claude Code) in print mode and returns its final result
as the model's completion. This is the faithful port: same invocation, same
``--resume`` session continuity, adapted to cria's provider interface so the router
treats it like any other cloud provider.

    claude -p "<prompt>" --model <model> --output-format json [--resume <sid>]

Run in the workspace cwd, stdin null, JSON parsed from stdout. Claude runs its own
agentic loop (its own tools, editing files in the cwd) — so unlike the HTTP
providers this one is NOT "owns no executors"; it hands the task to a more capable
agent and returns what it did. That's the whole point of the escalation.

Streaming: ``claude -p`` returns a single final result, so a streaming request is
fake-streamed (one content delta + done) from that result.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Iterator

from .classify import latest_user_text
from .upstream import UpstreamError


@dataclass
class ClaudeResult:
    content: str
    model: str
    session_id: str | None
    input_tokens: int
    output_tokens: int


class ClaudeCliProvider:
    def __init__(
        self,
        binary: str = "claude",
        cwd: str | None = None,
        timeout_seconds: int = 1800,
    ) -> None:
        self._binary = binary
        self._cwd = cwd  # workspace to run in; None → cria's own cwd
        self._timeout = timeout_seconds
        self._sessions: dict[str, str] = {}  # cria session -> claude session_id (for --resume)

    def chat(self, body: dict, rlog) -> bytes:
        model = str(body.get("model", ""))
        result = self._invoke(body, model, rlog)
        return _openai_completion(result)

    def stream_chat(self, body: dict, rlog) -> Iterator[bytes]:
        # claude -p is not a token stream; run it, then emit the final result as
        # a single SSE completion so streaming clients still work.
        model = str(body.get("model", ""))
        result = self._invoke(body, model, rlog)
        yield from _sse_from_result(result)

    def _invoke(self, body: dict, model: str, rlog) -> ClaudeResult:
        prompt = latest_user_text(body.get("messages", []))
        session_key = getattr(rlog, "session", None) or "main"
        resume = self._sessions.get(session_key)

        args = [self._binary, "-p", prompt, "--model", model, "--output-format", "json"]
        if resume:
            args += ["--resume", resume]

        rlog.emit("claude.invoke", model=model, resume=bool(resume), cwd=self._cwd)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=self._cwd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as e:
            rlog.emit("claude.error", level="error", error=f"binary not found: {self._binary}")
            raise UpstreamError(f"claude CLI not found: {self._binary}") from e
        except subprocess.TimeoutExpired as e:
            rlog.emit("claude.error", level="error", error="timeout")
            raise UpstreamError(f"claude CLI timed out after {self._timeout}s") from e

        if proc.returncode != 0:
            rlog.emit("claude.error", level="error", code=proc.returncode, stderr=(proc.stderr or "")[:300])
            raise UpstreamError(f"claude CLI exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")

        result = _parse_claude_json(proc.stdout, fallback_model=model)
        if result.session_id:
            self._sessions[session_key] = result.session_id
        rlog.emit(
            "claude.done",
            model=result.model,
            output_tokens=result.output_tokens,
            ms=round((time.monotonic() - t0) * 1000, 1),
            resumed=bool(resume),
            session=bool(result.session_id),
        )
        return result


def _parse_claude_json(stdout: str, fallback_model: str) -> ClaudeResult:
    """Parse ``claude -p --output-format json``. Field names mirror codex-local:
    ``result`` (with ``content`` as an alt), ``session_id``, ``usage.{input,output}
    _tokens``, ``model``. On unparseable output, treat stdout as the content."""
    try:
        obj = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return ClaudeResult(content=stdout.strip(), model=fallback_model, session_id=None, input_tokens=0, output_tokens=0)
    if not isinstance(obj, dict):
        return ClaudeResult(content=stdout.strip(), model=fallback_model, session_id=None, input_tokens=0, output_tokens=0)
    content = obj.get("result")
    if not isinstance(content, str):
        content = obj.get("content") if isinstance(obj.get("content"), str) else ""
    usage = obj.get("usage") or {}
    return ClaudeResult(
        content=content or "",
        model=str(obj.get("model") or fallback_model),
        session_id=(str(obj["session_id"]) if obj.get("session_id") else None),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
    )


def _openai_completion(r: ClaudeResult) -> bytes:
    """Format a ClaudeResult as a non-streaming OpenAI chat.completion."""
    body = {
        "object": "chat.completion",
        "model": r.model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": r.content}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": r.input_tokens,
            "completion_tokens": r.output_tokens,
            "total_tokens": r.input_tokens + r.output_tokens,
        },
    }
    return json.dumps(body).encode("utf-8")


def _sse_from_result(r: ClaudeResult) -> Iterator[bytes]:
    """Fake-stream a ClaudeResult: a role delta, the content, a stop, then [DONE]."""
    def chunk(delta: dict, finish=None) -> bytes:
        payload = {
            "object": "chat.completion.chunk",
            "model": r.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"

    yield chunk({"role": "assistant"})
    if r.content:
        yield chunk({"content": r.content})
    yield chunk({}, finish="stop")
    yield b"data: [DONE]\n\n"
