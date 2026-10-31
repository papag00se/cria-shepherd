"""Late wide repetition through real feed/collector; synthetic bytes, no upstream IO."""
import hashlib
import json
from unittest.mock import patch

import pytest

from cria import assistruntime, bodykeys, generation, generationguards as guards, upstream


class Log:
    phase = "coder"
    live_chars = 0

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def varied(label, size):
    return "".join(hashlib.sha256(f"{label}:{i}".encode()).hexdigest()
                   for i in range((size + 63) // 64))[:size]


PREFIX = varied("prefix", guards.WIDE_RUN_CHARS + 8192)
UNIT = varied("period", 4096)


def frame(text="", channel="content", finish=None):
    delta = ({"tool_calls": [{"index": 0, "id": "w", "type": "function",
                              "function": {"name": "write_file", "arguments": text}}]}
             if channel == "arguments" else {channel: text}) if text else {}
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def frames(text, channel, split):
    for start in range(0, len(text), split):
        yield frame(text[start:start + split], channel)
        yield frame()  # Empty/usage-only frames must not become generated characters.
        yield {"choices": [], "usage": {"completion_tokens": 1}}


def feed_all(state, items, log):
    for item in items:
        out = state.feed(item, lambda: 0, lambda: "", lambda: "", log)
        # This fixture cannot be rescued by the independent short-tail detector.
        assert not guards.degenerate_tail(state.tail)
        assert len(state.wide_tail) <= guards.WIDE_RUN_CHARS
        if out.status is guards.StreamStatus.ABORT:
            return out
    return out


@pytest.mark.parametrize("channel", ["content", "reasoning_content", "reasoning", "arguments"])
@pytest.mark.parametrize("split", [257, 2048, 8192])
def test_saturated_varied_prefix_then_late_wide_repetition(channel, split):
    state = guards.StreamGuard(guards.StreamInput(None, 0, False))
    log = Log()
    assert feed_all(state, frames(PREFIX, channel, split), log).status is guards.StreamStatus.CONTINUE
    assert state.chars == len(PREFIX)
    assert len(state.wide_tail) == guards.WIDE_RUN_CHARS
    assert not log.events

    out = feed_all(state, frames(UNIT * 5, channel, split), log)
    assert out.status is guards.StreamStatus.ABORT
    assert out.verdict == {"degenerate": True, "chars": guards.WIDE_RUN_CHARS}
    assert log.events == [("rumination.abort", {
        "assist_id": guards.RUNAWAY.policy.id, "family_id": "F48", "steer": "rumination",
        "level": "warn", "degenerate": True, "chars": guards.WIDE_RUN_CHARS, "wide": True})]
    # An abort stays latched without recounting/logging even if new bytes arrive.
    count = state.chars
    assert state.feed(frame("later"), lambda: 0, lambda: "", lambda: "", log) == out
    assert state.chars == count and len(log.events) == 1

    fresh = guards.StreamGuard(guards.StreamInput(None, 0, False))
    fresh_log = Log()
    assert feed_all(fresh, frames(UNIT * 2, channel, split), fresh_log).status is guards.StreamStatus.CONTINUE
    assert fresh.chars == len(UNIT) * 2 and not fresh_log.events


@pytest.mark.parametrize("suffix", [varied("continued legitimate output", 65536), UNIT * 2])
def test_saturated_varied_output_and_two_copies_are_not_runaways(suffix):
    state = guards.StreamGuard(guards.StreamInput(None, 0, False))
    log = Log()
    assert feed_all(state, frames(PREFIX + suffix, "content", 257), log).status is guards.StreamStatus.CONTINUE
    assert state.chars == len(PREFIX + suffix)
    assert not log.events


class Response:
    def __init__(self, items):
        self.items = items
        self.read = 0
        self.closed = False

    def __iter__(self):
        for item in self.items:
            self.read += 1
            yield b"data: " + json.dumps(item).encode() + b"\n\n"

    def close(self):
        self.closed = True


@pytest.mark.parametrize("window,guessed", [(None, False), (20, True), (1000000, False)])
@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("channel", ["content", "reasoning_content", "reasoning", "arguments"])
def test_real_collector_late_wide_guard_selection_and_window_authority(window, guessed, disabled, channel):
    items = list(frames(PREFIX + UNIT * 5, channel, 257)) + [frame(finish="stop")]
    response, log = Response(items), Log()
    up = upstream.Upstream("http://not-used", context_window=window)
    up._window_guessed = guessed
    runtime = assistruntime.AssistRuntime.select(
        level=4, disabled=(guards.RUNAWAY.policy.id,) if disabled else ())
    with assistruntime.bound(runtime), \
         patch.object(up, "_open_with_refit", return_value=(response, 10, None)), \
         patch.object(up, "_resolve_window", return_value=window):
        result = json.loads(up.chat_watched({"messages": [], "model": "fake"}, log, watch=None))
    aborts = [fields for event, fields in log.events if event == "rumination.abort"]
    assert response.closed
    if disabled:
        assert bodykeys.RUMINATION not in result
        assert not aborts and response.read == len(items)
        message = result["choices"][0]["message"]
        if channel == "arguments":
            assert message["tool_calls"][0]["function"]["arguments"] == PREFIX + UNIT * 5
        else:
            key = "content" if channel == "content" else "reasoning_content"
            assert message[key] == PREFIX + UNIT * 5
    else:
        assert result.get(bodykeys.RUMINATION) == {"degenerate": True, "chars": guards.WIDE_RUN_CHARS}
        assert response.read < len(items)
        assert len(aborts) == 1 and aborts[0]["wide"] is True
        assert not result["choices"][0]["message"].get("tool_calls")
        assert result.get(generation.EVIDENCE), "aborted bytes remain quarantined evidence"
        done = [fields for event, fields in log.events if event == "upstream.done"]
        assert len(done) == 1 and done[0]["aborted"] is True
        assert done[0]["read_chars"] > guards.WIDE_RUN_CHARS
