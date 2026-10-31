"""The capacity refit of the REAL Upstream._prep (the last point before serialization) in front of a fake llama.cpp (/props, /apply-template, /tokenize at 1 token per
3 characters): a protected read is delivered byte-exact with what the floor dropped LABELLED, or the measured overflow is reported with its numbers, or the reason the
fit is unknown is named - never a silent drop, never a guess. The compaction route is the loop-owned callback; its every answer is classified."""
import hashlib
import json
from contextlib import contextmanager

import pytest

from cria import bodykeys, tokenratio
from cria.upstream import MeasuredReadOverflow, ProtectedRead, ReadFitCallbacks, ReadFitOverflow, ReadFitUnknown, Upstream
from test_context_wire_a_scenario2_sv2_upstream_errors import Buffered
from test_context_wire_a_stream import Rlog

READ = "R" * 3000


@pytest.fixture(autouse=True)
def fresh_density():
    """The learned tokens-per-estimate ratio is process-wide; every measurement here teaches it and must not steer the next row."""
    tokenratio.reset()
    yield
    tokenratio.reset()


class Answer:
    def __init__(self, obj):
        self.raw = json.dumps(obj).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *a):
        return self.raw


class Llama:
    """Fake llama.cpp transport: `ordinary` answers the measurement endpoints, calling it answers the chat."""

    def __init__(self, window=4096, props=True, tokenizer=True):
        self.window, self.props, self.tokenizer, self.paths = window, props, tokenizer, []

    def ordinary(self, req, timeout=None):
        path = req.full_url.rsplit("/", 1)[1]
        self.paths.append(path)
        if path == "props" and self.props:
            return Answer({"default_generation_settings": {"n_ctx": self.window}})
        if path == "apply-template":
            return Answer({"prompt": json.dumps(json.loads(req.data)["messages"])})
        if path == "tokenize" and self.tokenizer:
            return Answer({"tokens": [1] * (len(json.loads(req.data)["content"]) // 3)})
        raise OSError(path + " unavailable")

    def __call__(self, req, timeout=None, receipt=None):
        self.paths.append("chat")
        return Buffered("ok")


def tokens_of(wire):
    """What the fake tokenizer says about a final wire: the rendered prompt is the messages' JSON, 3 characters a token."""
    return len(json.dumps(json.loads(wire)["messages"])) // 3


def read_of(text, call_id="r1"):
    raw = text.encode()
    return ProtectedRead(call_id=call_id, source=(0, hashlib.sha256(raw).hexdigest()), model_content=text, exact_body=raw)


def call(call_id, cmd):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "shell", "arguments": json.dumps({"cmd": cmd})}}]}


def history(old=4, size=800, text=READ):
    """The task, `old` earlier file reads (droppable), then the protected read."""
    msgs = [{"role": "user", "content": "fix the bug"}]
    for i in range(old):
        msgs += [call(f"o{i}", f"cat f{i}"), {"role": "tool", "tool_call_id": f"o{i}", "content": f"old{i} " + "x" * size}]
    return msgs + [call("r1", "cat big"), {"role": "tool", "tool_call_id": "r1", "content": text}]


def request(messages=None, **extra):
    return {"model": "m", "max_tokens": 300, "messages": messages or history(), bodykeys.PROTECTED_READS: (read_of(READ),), **extra}


def prep(llama, body, level=5, rlog=None):
    return Upstream("http://llama.invalid", open_request=llama, engagement_level=level)._prep(body, False, rlog or Rlog())[0]


def results(wire):
    return {m["tool_call_id"]: m["content"] for m in json.loads(wire)["messages"] if m["role"] == "tool"}


@pytest.mark.parametrize("level,window,dropped", [(5, 6000, ()), (3, 3200, ()), (5, 2800, ("o0",)), (3, 2800, ("o0",))])
def test_the_read_arrives_exact_and_only_the_oldest_turns_are_compacted_with_a_label(level, window, dropped):
    """5 reads of ~800 chars before a 3,000-char protected read: a roomy window ships all of it; a tight one compacts the OLDEST turn into a labelled stand-in that
    names the command it summarized, and never touches the read or the task. The measurement is logged."""
    rlog = Rlog()
    wire = prep(Llama(window), request(), level, rlog)
    messages = json.loads(wire)["messages"]
    assert results(wire)["r1"] == READ and messages[0]["content"] == "fix the bug"
    assert {f"o{i}" for i in range(4)} - set(results(wire)) == set(dropped)
    notes = [m["content"] for m in messages if m["role"] == "user" and m["content"].startswith("⟦ctx:compacted⟧")]
    assert (len(notes) == 1 and "2 earlier turn(s) were compacted" in notes[0] and "cat f0" in notes[0]) == bool(dropped) and (not notes) == (not dropped)
    assert rlog.first("context.measured")["n_ctx"] == window and (rlog.first("context.floor") is not None) == bool(dropped)


@pytest.mark.parametrize("level,window", [(5, 2300), (3, 2300), (2, 2600)])
def test_a_read_that_cannot_fit_raises_the_measured_overflow_with_the_servers_numbers(level, window):
    """Too big even for the floor (or, below level 3, with NO floor at all): ReadFitOverflow carries the window, the server's own token count and the reply reserve (the floor
    yields reserve to the live input, never the reverse); below level 3 nothing was dropped to try."""
    with pytest.raises(ReadFitOverflow) as err:
        prep(Llama(window), request(), level)
    measured = err.value.measurement
    assert isinstance(measured, MeasuredReadOverflow) and measured.window == window and (measured.reserve == 300 if level == 2 else 0 < measured.reserve <= 300)
    assert measured.tokens == tokens_of(measured.final_wire) and measured.tokens + measured.reserve > window and measured.reads[0].model_content == READ
    if level == 2:
        assert {f"o{i}" for i in range(4)} <= set(results(measured.final_wire))


def fold(body, reads):
    """The loop's compaction: the old reads folded into one note, the task and the read kept."""
    keep = [m for m in body["messages"] if m.get("tool_call_id") == "r1" or m is body["messages"][0] or m.get("tool_calls", [{}])[0].get("id") == "r1"]
    return {**body, "messages": [keep[0], {"role": "user", "content": "earlier reads: f0 f1 f2 f3 (folded)"}, *keep[1:]]}


COMPACTIONS = [  # (what the loop's compact callback answers, how the refit ends)
    ("folded", "ok"),
    ("none", ReadFitUnknown("compaction_unavailable")),
    ("not_a_request", ReadFitUnknown("compaction_unavailable")),
    ("lost_the_task", ReadFitUnknown("compaction_changed_user_packet")),
    ("lost_the_binding", ReadFitUnknown("compaction_changed_read_binding")),
    ("unchanged", "overflow"),
]


@pytest.mark.parametrize("answer,end", COMPACTIONS)
def test_compaction_is_offered_once_and_its_answer_is_verified_before_anything_ships(answer, end):
    """Measured overflow -> the loop's compact(body, reads) is asked exactly once. A fold that keeps the task and the binding is re-measured and shipped; None/non-dict,
    a dropped user packet, a changed read binding are each a NAMED unknown; a fold that did not help ends as the measured overflow WITH the owner's guidance."""
    asked, guided = [], []
    body = request()
    replies = {"folded": fold(body, None), "none": None, "not_a_request": "text", "unchanged": body,
               "lost_the_task": {**body, "messages": body["messages"][1:]}, "lost_the_binding": {k: v for k, v in body.items() if k != bodykeys.PROTECTED_READS}}

    def compact(sent, reads):
        asked.append((sent is body, reads[0].call_id))
        return replies[answer]

    def guidance(measured):
        guided.append(measured)
        return "read it in two ranges"
    body[bodykeys.READ_FIT_CALLBACKS] = ReadFitCallbacks(compact, guidance)
    llama = Llama(2300)
    if end == "ok":
        wire = prep(llama, body)
        assert results(wire) == {"r1": READ} and "folded" in json.dumps(json.loads(wire)["messages"]) and llama.paths.count("tokenize") >= 2
    elif end == "overflow":
        with pytest.raises(ReadFitOverflow) as err:
            prep(llama, body)
        assert err.value.guidance == "read it in two ranges" and guided == [err.value.measurement]
    else:
        with pytest.raises(ReadFitUnknown) as err:
            prep(llama, body)
        assert err.value.reason == end.reason
    assert asked == [(True, "r1")] and "chat" not in llama.paths


@pytest.mark.parametrize("callbacks", [None, ReadFitCallbacks(None), "not callbacks"])
def test_an_overflow_with_no_usable_compaction_route_is_still_reported_as_the_measured_overflow(callbacks):
    """A plain proxied turn has no compaction: the overflow was MEASURED, so it is reported as one (not as 'unknown') and with no guidance invented."""
    extra = {} if callbacks is None else {bodykeys.READ_FIT_CALLBACKS: callbacks}
    with pytest.raises(ReadFitOverflow) as err:
        prep(Llama(2300), request(**extra))
    assert err.value.guidance is None and err.value.measurement.window == 2300


@pytest.mark.parametrize("level", [2, 5])
@pytest.mark.parametrize("llama,reason", [(dict(tokenizer=False), "native_measurement_unavailable"), (dict(props=False), "authoritative_context_window_unavailable")])
def test_an_unmeasurable_read_fit_is_unknown_with_its_reason_and_nothing_is_sent(level, llama, reason):
    """No tokenizer, or no authoritative window (a guessed 8,192 is never one): the fit is UNKNOWN, named, and the request is not sent or trimmed on a guess."""
    server = Llama(**llama)
    with pytest.raises(ReadFitUnknown) as err:
        prep(server, request(), level)
    assert err.value.reason == reason and "chat" not in server.paths


def test_a_read_in_a_request_with_an_image_is_unknown_because_vision_cost_is_not_a_text_token_count():
    """The text tokenizer cannot size an image: protected reads in such a request are refused with a named reason and the structured event, not estimated."""
    messages = history(old=0) + [{"role": "user", "content": [{"type": "text", "text": "and this?"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    rlog = Rlog()
    with pytest.raises(ReadFitUnknown) as err:
        prep(Llama(8192), request(messages), 5, rlog)
    assert err.value.reason == "visual_capacity_unavailable" and rlog.first("context.image_fit_unknown")
