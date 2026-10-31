"""Streamed generations (Upstream.chat_watched): every thought is kept on disk - finished or not - and a server
that streams nothing readable is stopped on the clock, while real work is never stopped for being slow."""
import json
import pathlib

import pytest

from cria import rumination
from cria.upstream import Upstream


class Rlog:
    phase, live_t0, live_chars = "coder-s1", None, 0

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def first(self, kind):
        return next((f for k, f in self.events if k == kind), None)


def sse(delta=None, usage=None, finish=None):
    payload = {"choices": [{"delta": delta or {}, "finish_reason": finish}]}
    if usage:
        payload["usage"] = usage
    return b"data: " + json.dumps(payload).encode() + b"\n"


class Stream:
    """A streamed HTTP response: yields frames, runs `at_end` (an inspection or a death) after the last one."""
    status, headers = 200, {}

    def __init__(self, frames, at_end=None, per_frame=None):
        self.frames, self.at_end, self.per_frame = frames, at_end, per_frame

    def __iter__(self):
        for frame in self.frames:
            if self.per_frame:
                self.per_frame()
            yield frame
        if self.at_end:
            self.at_end()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def read(self, *a):
        return b""


MESSAGES = {"model": "m", "messages": [{"role": "user", "content": "go"}]}


def captured(tmp_path, frames, at_end=None):
    up = Upstream("http://fixture.invalid", context_window=8192, capture_dir=str(tmp_path), capture_rendered=False,
                  open_request=lambda req, timeout=None, receipt=None: Stream(frames, at_end))
    rlog = Rlog()
    try:
        up.chat_watched(dict(MESSAGES), rlog)
    except KeyboardInterrupt:
        pass
    return rlog


def reasoning_files(tmp_path, suffix):
    return sorted(pathlib.Path(tmp_path).rglob(f"*.reasoning{suffix}.txt"))


def test_streamed_reasoning_reaches_the_disk_whether_or_not_the_stream_finishes(tmp_path):
    """Operator: 'I want all streamed reasoning logged. Whether it finishes or not.' rust-toml-cli / bonsai call 0043:
    a run killed mid-call left no reasoning - the one that said what the model was about to do. The thought is
    appended to a .partial file AS IT STREAMS (a SIGKILL runs no finally), the partial is gone after a clean
    finish, and an interrupted turn's file says it is incomplete."""
    thought = "".join(f"Step {i}: handle {i} totals are merged per SKU, not under one TOTAL key. " for i in range(60))
    on_disk_at_death = []

    def die():
        on_disk_at_death.extend(p.read_text() for p in reasoning_files(tmp_path / "killed", ".partial"))
        raise KeyboardInterrupt

    rlog = captured(tmp_path / "killed", [sse({"reasoning_content": thought})], at_end=die)
    assert on_disk_at_death == [thought]                              # on disk BEFORE the stream ended
    (final,) = reasoning_files(tmp_path / "killed", "")
    text = final.read_text()
    assert text.startswith("⟦INCOMPLETE REASONING⟧") and "merged per SKU" in text and thought in text
    assert "coder.reasoning" in [k for k, _ in rlog.events] and rlog.first("upstream.first_token") is not None   # a reasoning delta IS a first token

    done = [sse({"reasoning_content": "a complete thought"}), sse({"content": "answer"}, {"completion_tokens": 4}, "stop"),
            b"data: [DONE]\n"]
    captured(tmp_path / "clean", done)
    assert reasoning_files(tmp_path / "clean", ".partial") == []
    assert [p.read_text() for p in reasoning_files(tmp_path / "clean", "")] == ["a complete thought"]

    captured(tmp_path / "silent", [sse({"content": "hi"}, {"completion_tokens": 1}, "stop"), b"data: [DONE]\n"])
    assert reasoning_files(tmp_path / "silent", "") == [] and reasoning_files(tmp_path / "silent", ".partial") == []


class Clock:
    def __init__(self, seconds_per_frame):
        self.t, self.step = 1000.0, seconds_per_frame

    def __call__(self):
        return self.t

    def tick(self):
        self.t += self.step


def watched(monkeypatch, *, frames, readable, seconds):
    """Run chat_watched over `frames` SSE frames, advancing a fake clock evenly to `seconds` in total."""
    clock = Clock(seconds / frames)
    body = [sse({"content": f" w{i} "} if readable else {}, finish="stop" if i == frames - 1 else None) for i in range(frames)]
    body += [b'data: {"usage": {"completion_tokens": 43442}}\n', b"data: [DONE]\n"]
    monkeypatch.setattr("time.monotonic", clock)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: Stream(body, per_frame=clock.tick))
    rlog = Rlog()
    Upstream("http://x", context_window=49152).chat_watched(dict(MESSAGES), rlog)
    return rlog


@pytest.mark.parametrize("frames,readable,seconds,stopped", [
    (300, False, 755.0, True),                                          # shipping-rates-rb / gemma4 call 0070
    (2000, True, 1200.0, False),                                        # twenty minutes of real output is work
    (50, False, rumination.DEAD_STREAM_SECONDS - 30, False),            # a slow prompt-processing head is honest
])
def test_a_server_streaming_nothing_readable_is_stopped_on_the_clock_but_real_work_never_is(monkeypatch, frames, readable, seconds, stopped):
    """12.5 minutes, 43,442 tokens, an empty message and no guard fired: under 400 frames the counting guard is
    below threshold however long the call runs, so the clock is the one signal a quiet server cannot suppress.
    The condition is 'nothing readable', not 'slow'."""
    rlog = watched(monkeypatch, frames=frames, readable=readable, seconds=seconds)
    abort = rlog.first("rumination.abort")
    if stopped:
        assert abort["dead_stream"] and rumination.DEAD_STREAM_SECONDS <= abort["seconds"] < 300
        assert 0 < abort["chunks"] < frames                             # cut part way: the minutes go back to the model
    else:
        assert abort is None
        assert rlog.first("upstream.done")["frames"] > 0
