"""Shared fakes for the loop_guards shard: a recording log, an SSE response and scripted chat replies.

Only the model server boundary is faked; every guard under test is the real owner.
"""
import json
import random
from unittest.mock import patch

from cria import assistruntime, upstream


class Log:
    phase = "coder"
    live_chars = 0

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def names(self):
        return [name for name, _ in self.events]

    def first(self, name):
        return next((fields for kind, fields in self.events if kind == name), None)


def frame(delta=None, finish=None, index=0):
    return {"choices": [{"index": index, "delta": delta or {}, "finish_reason": finish}]}


def call_delta(args, name="write_file", cid="c1"):
    return {"tool_calls": [{"index": 0, "id": cid, "type": "function",
                            "function": {"name": name, "arguments": args}}]}


class Response:
    """A urllib response double: iterates SSE lines, records whether the reader closed it early."""

    def __init__(self, frames):
        self.lines = [b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames] + [b"data: [DONE]\n\n"]
        self.read = 0
        self.closed = False

    def __iter__(self):
        for line in self.lines:
            self.read += 1
            yield line

    def close(self):
        self.closed = True


def watched(frames, *, window=1_000_000, prompt=10, guessed=False, watch=None, level=5):
    """Drive the REAL streaming reader over ``frames``; returns (completion dict, response, log)."""
    up = upstream.Upstream("http://unused.invalid", context_window=window)
    up._window_guessed = guessed
    response, log = Response(frames), Log()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=level)), \
         patch.object(up, "_open_with_refit", return_value=(response, prompt, None)), \
         patch.object(up, "_resolve_window", return_value=window):
        out = up.chat_watched({"model": "fake", "messages": []}, log, watch=watch)
    return json.loads(out), response, log


def reply(content="ok", finish="stop", **message):
    return {"choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content, **message}}]}


class Chat:
    """A scripted coder provider: records every body it was sent, replays ``replies`` (last repeats)."""

    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, body, rlog):
        self.bodies.append(json.loads(json.dumps(body)))
        item = self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]
        if isinstance(item, Exception):
            raise item
        return json.dumps(item).encode()


def nonrepeating(n, seed=11):
    """``n`` characters of word salad that is never periodic."""
    r = random.Random(seed)
    vocab = ["".join(r.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(r.randint(3, 10))) for _ in range(4000)]
    return " ".join(r.choice(vocab) for _ in range(n // 4))[:n]
