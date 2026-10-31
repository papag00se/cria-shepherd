"""The streaming guard through the real reader (Upstream.chat_watched): what it aborts, what it must never touch."""
import pytest

from cria import bodykeys, generationguards as g
from loop_guards_helpers import Log, call_delta, frame, nonrepeating, watched

DENSE = "actually wait hmm reconsider " * 20


@pytest.mark.parametrize("kind", ["dead_stream", "degenerate", "window_exhausted", "second_guessing", "length"])
def test_runaway_stream_is_closed_early_and_labelled_with_the_arm_that_fired(kind):
    """Each runaway ends the read early with finish_reason=rumination and a verdict naming ITS trigger.

    cycle 3 cell 1 (shipping-rates-rb x gemma4): 42,744 tokens of nothing readable ran 11.7 minutes
    until the window ended it; nothing read bytes, so only a frame-count rule could see it."""
    kw, watch = {}, None
    if kind == "dead_stream":
        frames = [frame()] * (g.DEAD_STREAM_CHUNKS + 5)
    elif kind == "degenerate":
        frames = [frame(call_delta("0" * g.DEGENERATE_RUN_CHARS))] * 2     # even inside a write_file argument
    elif kind == "window_exhausted":
        frames, kw = [frame({"unknown_parser_shape": 1})] * 15, dict(window=110, prompt=100)
    else:
        watch = g.Detector(200).check
        key = {"second_guessing": DENSE, "length": "".join(f"analysis{i} " for i in range(120))}[kind]
        frames = [frame({"reasoning_content": key})] * 2
    out, response, log = watched(frames, watch=watch, **kw)
    verdict = out[bodykeys.RUMINATION]
    assert (verdict["arm"] == kind) if kind in ("second_guessing", "length") else verdict[kind] is True
    assert out["choices"][0]["finish_reason"] == "rumination"
    assert not out["choices"][0]["message"].get("tool_calls")
    assert response.closed and response.read < len(frames) + 1
    assert log.first("rumination.abort")["steer"] == "rumination"


def test_a_large_native_write_streams_to_completion_untouched():
    """A legitimate 40k-token write_file accumulates as tool arguments from its first delta: it never
    trips the dead-stream rule, a guessed small window, or the reasoning scanner (principle 6, no caps)."""
    lines = [f"line{i} = compute_value({i})\n" for i in range(g.DEAD_STREAM_CHUNKS * 3)]
    frames = [frame(call_delta(piece)) for piece in lines]
    frames[-1]["choices"][0]["finish_reason"] = "tool_calls"
    scanned = []
    out, response, log = watched(frames, window=20, prompt=10, guessed=True,
                                 watch=lambda text, tokens: scanned.append(text))
    assert bodykeys.RUMINATION not in out and not scanned and "rumination.abort" not in log.names()
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == "".join(lines)
    assert response.read == len(frames) + 1


def _dense_finish(args, finish="tool_calls", extra=()):
    reasoning = {"reasoning_content": "Actually wait. " * 160}
    return [*extra, frame({**reasoning, **call_delta(args)}, finish)]


@pytest.mark.parametrize("name,frames,survives", [
    ("finished", _dense_finish('{"path":"r.txt","content":"complete"}'), True),
    # the same threshold frame with a half-written call, or a frame that did not settle on tool_calls,
    # is unfinished work and is still caught
    ("cut arguments", _dense_finish("{"), False),
    ("finish=length", _dense_finish('{"path":"r.txt"}', finish="length"), False),
    ("another choice still open", [frame({"content": "x"}, index=1)] + _dense_finish('{"path":"r.txt"}'), False),
])
def test_a_finished_native_tool_call_is_never_deleted_by_the_reasoning_guard(name, frames, survives):
    """The completed call on the very frame where reasoning crosses the watch threshold must ship."""
    out, _, _ = watched(frames, watch=g.Detector(1000).check)
    calls = out["choices"][0]["message"].get("tool_calls")
    assert (bodykeys.RUMINATION not in out) is survives
    assert bool(calls) is survives
    if survives:
        assert calls[0]["function"]["arguments"] == '{"path":"r.txt","content":"complete"}'


def test_a_clock_or_wire_silence_is_labelled_dead_stream_with_its_own_facts():
    guard = g.RUNAWAY.stream(g.StreamInput(1_000_000, 10, False))
    log = Log()
    out = guard.feed(frame(), lambda: 181.25, lambda: "", lambda: "", log)
    assert out.status is g.StreamStatus.ABORT
    assert out.verdict == {"dead_stream": True, "chunks": 1, "seconds": 181.2}
    fresh = g.RUNAWAY.stream(g.StreamInput(None, 0, True))
    assert fresh.wire_timeout(420.55, "read deadline", log).verdict == {
        "dead_stream": True, "chunks": 0, "seconds": 420.6, "wire": True}
    assert log.events[-1][1]["error"] == "read deadline"


def test_the_wide_repeat_check_runs_on_a_stride_not_per_frame(monkeypatch):
    """KMP over 32 KB on every one of 40,000 frames is unaffordable; the stream must still arrive whole."""
    text = nonrepeating(60_000)
    frames = [frame({"content": text[i:i + 12]}) for i in range(0, len(text), 12)]
    frames[-1]["choices"][0]["finish_reason"] = "stop"
    calls = []
    real = g.degenerate_wide
    monkeypatch.setattr(g, "degenerate_wide", lambda s: calls.append(len(s)) or real(s))
    out, _, _ = watched(frames)
    assert out["choices"][0]["message"]["content"] == text
    assert 0 < len(calls) * 20 < len(frames)

