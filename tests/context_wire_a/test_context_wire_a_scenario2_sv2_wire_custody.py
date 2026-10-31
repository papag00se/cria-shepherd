"""Wire custody owners on the real Upstream: the coder observer (told of the exact bytes POSTed and of the terminal outcome, buffered and streamed, and refused when its
role settings drift) and protected-read validation (every malformed read is ReadFitUnknown with its reason before anything is sent)."""
import hashlib
import json

import pytest

from cria import bodykeys
from cria.upstream import (CoderObserverBinding, ProtectedRead, ReadFitUnknown, Upstream, UpstreamError, bind_coder_observer, bind_protected_reads, coder_role_signature,
                           protected_reads)
from test_context_wire_a_stream import MESSAGES, Rlog, Stream, sse
from test_context_wire_a_scenario2_sv2_upstream_errors import Buffered, upstream


def observed(body, log):
    binding = CoderObserverBinding(object(), coder_role_signature(body), lambda receipt: log.append(("start", receipt)),
                                   lambda receipt, completion, terminal: log.append(("done", receipt, completion, terminal)))
    return bind_coder_observer(body, binding)


def test_the_observer_sees_the_exact_posted_bytes_and_a_terminal_buffered_outcome():
    """started() gets the final wire bytes of the single POST; completed() gets the parsed completion, terminal only when every choice carries a finish_reason."""
    log = []
    up, opened = upstream([Buffered("fine")])
    body = observed({**MESSAGES, "temperature": 0.2}, log)
    up.chat(body, Rlog())
    start, done = log
    assert start[0] == "start" and json.loads(start[1].final_wire) == opened[0] and start[1].model == MESSAGES["model"]
    assert start[1].role_signature == coder_role_signature({**MESSAGES, "temperature": 0.2})
    assert done[0] == "done" and done[1] is start[1] and done[2]["choices"][0]["message"]["content"] == "fine" and done[3] is False   # no finish_reason: not terminal
    stopped = Buffered("fine")
    stopped.payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": "fine"}, "finish_reason": "stop"}]}).encode()
    log.clear()
    upstream([stopped])[0].chat(observed(dict(MESSAGES), log), Rlog())
    assert log[1][3] is True


def test_a_streamed_coder_call_reports_terminal_only_when_the_stream_finished_cleanly():
    """Watched streams assemble the pieces (content, reasoning, tool deltas, usage) for the observer; one that ends without a finish, or errors mid-stream, is reported non-terminal."""
    log = []
    frames = [sse({"reasoning_content": "hm"}), sse({"content": "ans"}), sse({}, finish="stop"), b'data: {"usage": {"completion_tokens": 3}}\n']
    up, _ = upstream([Stream(frames)])
    out = json.loads(up.chat_watched(observed(dict(MESSAGES), log), Rlog()))
    assert out["choices"][0]["message"]["content"] == "ans"
    assert [e[0] for e in log] == ["start", "done"] and log[1][3] is True


def test_the_proxy_stream_notifies_start_and_a_completion_assembled_from_its_frames():
    """stream_chat with an observer: tool-call deltas, content and finish are assembled; a terminal stop yields terminal=True; an early close (consumer stops) completes non-terminal."""
    call = lambda args, **kw: sse({"tool_calls": [{"index": 0, **kw, "function": {"arguments": args, **({"name": "shell"} if kw else {})}}]})
    log = []
    up, _ = upstream([Stream([call('{"cmd":', id="c1"), call('"ls"}'), sse({}, finish="tool_calls"), b"data: [DONE]\n"])])
    assert len(list(up.stream_chat(observed(dict(MESSAGES), log), Rlog()))) == 4
    kinds = [e[0] for e in log]
    assert kinds == ["start", "done"] and log[1][2]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"cmd":"ls"}' and log[1][3] is True
    log.clear()
    up, _ = upstream([Stream([sse({"content": "a"}), sse({"content": "b"}), sse({}, finish="stop")])])
    gen = up.stream_chat(observed(dict(MESSAGES), log), Rlog())
    next(gen)
    gen.close()
    assert [e[0] for e in log] == ["start", "done"] and log[1][3] is False


def test_an_observer_whose_role_settings_changed_before_dispatch_is_refused_and_a_foreign_binding_is_not_accepted():
    """Binding checks the signature against the body it is attached to; a body edited afterwards (temperature changed) fails at dispatch and nothing is sent."""
    log = []
    with pytest.raises(UpstreamError, match="does not match actual applied role settings"):
        bind_coder_observer(dict(MESSAGES), CoderObserverBinding(object(), "0" * 64, lambda r: None, lambda r, c, t: None))
    with pytest.raises(UpstreamError):
        bind_coder_observer(dict(MESSAGES), "not-a-binding")
    body = observed({**MESSAGES, "temperature": 0.2}, log)
    body["temperature"] = 0.9
    up, opened = upstream([Buffered()])
    with pytest.raises(UpstreamError, match="Coder role settings changed before actual dispatch"):
        up.chat(body, Rlog())
    assert opened == [] and log == []


def test_the_role_signature_ignores_tool_shape_and_dialect_and_follows_real_role_controls():
    """Tools/messages/stream do not change a role's identity; reasoning_effort and enable_thinking spell the same intent; sampling does change it."""
    base = {**MESSAGES, "temperature": 0.2}
    assert coder_role_signature({**base, "tools": [{"x": 1}], "stream": True, "tool_choice": "auto"}) == coder_role_signature(base)
    assert coder_role_signature({**base, "reasoning_effort": "high"}) == coder_role_signature({**base, "chat_template_kwargs": {"enable_thinking": True}})
    assert coder_role_signature({**base, "reasoning_effort": "none"}) == coder_role_signature({**base, "chat_template_kwargs": {"enable_thinking": False}})
    assert coder_role_signature({**base, "reasoning_effort": "none"}) != coder_role_signature({**base, "reasoning_effort": "high"})
    assert coder_role_signature({**base, "temperature": 0.3}) != coder_role_signature(base)
    assert coder_role_signature({**base, "chat_template_kwargs": {"enable_thinking": True, "x": 1}}) != coder_role_signature({**base, "chat_template_kwargs": {"enable_thinking": True}})


def read(**kw):
    exact = kw.pop("exact_body", b"hello\n")
    raw = exact if isinstance(exact, bytes) else b""
    fields = dict(call_id="c1", source=(0, hashlib.sha256(raw).hexdigest()), model_content=raw.decode("utf-8", "replace"), exact_body=exact)
    return ProtectedRead(**{**fields, **kw})


BODY = {**MESSAGES, "messages": [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
                                 {"role": "tool", "tool_call_id": "c1", "content": "hello\n"}]}


@pytest.mark.parametrize("make, reason", [
    (lambda: read(call_id=""), "invalid_protected_read_source"),
    (lambda: read(source=(-1, "0" * 64)), "invalid_protected_read_source"),
    (lambda: read(source=(0, "xyz")), "invalid_protected_read_source"),
    (lambda: read(source=(0, "G" * 64)), "invalid_protected_read_source"),
    (lambda: read(exact_body="text"), "invalid_protected_read_source"),
    (lambda: read(exact_body=b"\xff\xfe"), "non_text_protected_read"),
    (lambda: read(model_content="different"), "read_representation_changed"),
    (lambda: read(read_instead=True, pre=None), "read_instead_representation_changed"),
    (lambda: read(read_instead=True, pre="note\n"), "read_instead_representation_changed"),
])
def test_a_malformed_protected_read_is_unknown_with_its_reason_before_anything_is_sent(make, reason):
    """Each way a protected read can disagree with its own bytes/source/representation names the reason and stops the request."""
    with pytest.raises(ReadFitUnknown) as err:
        protected_reads({bodykeys.PROTECTED_READS: (make(),)})
    assert err.value.reason == reason


def test_protected_read_binding_accepts_a_consistent_set_and_rejects_untyped_duplicate_or_misplaced_ones():
    """A paired call/result with matching bytes binds; untyped tuples, duplicate ids, a result that moved, and callbacks of the wrong type are refused; an absent key means no reads."""
    good = read()
    bound = bind_protected_reads(BODY, [good])
    assert protected_reads(bound) == (good,) and protected_reads({}) == ()
    instead = read(read_instead=True, pre="note\n", model_content="note\nhello\n")
    assert protected_reads({bodykeys.PROTECTED_READS: (instead,)}) == (instead,)
    for bad, reason in (({bodykeys.PROTECTED_READS: ["x"]}, "untyped_protected_reads"), ({bodykeys.PROTECTED_READS: ("x",)}, "untyped_protected_reads"),
                        ({bodykeys.PROTECTED_READS: (good, good)}, "ambiguous_protected_reads")):
        with pytest.raises(ReadFitUnknown) as err:
            protected_reads(bad)
        assert err.value.reason == reason
    moved = {**BODY, "messages": BODY["messages"][::-1]}
    with pytest.raises(ReadFitUnknown, match="protected_read_changed_or_missing"):
        bind_protected_reads(moved, [good])
    with pytest.raises(ReadFitUnknown, match="untyped_read_fit_callbacks"):
        bind_protected_reads(BODY, [good], callbacks=object())
