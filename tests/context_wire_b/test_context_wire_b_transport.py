"""Upstream transport promises: a real window or none, overflow refit exactly once, runaways and silence cut and labelled, native errors not hidden."""
import copy
import io
import json
import urllib.error
from unittest import mock

import pytest

from context_wire_b_helpers import Frames, Rlog, rows, sse
from cria import bodykeys, rumination, tokenratio
from cria.upstream import _FALLBACK_WINDOW, _MAX_PROPS_ATTEMPTS, _PROPS_RETRY_EVERY, Upstream, UpstreamError, _merge_consecutive_assistant

BODY = {"model": "m", "messages": [{"role": "user", "content": "go"}]}
DOWN = mock.patch("cria.upstream.urllib.request.urlopen", side_effect=urllib.error.URLError("down"))
CALL = {"id": "c", "type": "function", "function": {"name": "shell", "arguments": "{}"}}

props = lambda payload: mock.MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False, read=lambda: json.dumps(payload).encode())

def test_a_local_window_is_always_usable_only_ever_rises_on_evidence_and_a_guess_never_cuts():
    """One failed /props must not disable the floor (pre-fix it cached None) nor shrink a real 49,152 window to the 8,192 fallback (83% trimmed): probing backs off but never stops; accepted prompt+completion only raises a guess; a keyed cloud endpoint is never probed; a guessed window never aborts a long generation."""
    up, rlog = Upstream("http://x"), Rlog()
    with DOWN as probe:
        for _ in range(_MAX_PROPS_ATTEMPTS + 2):
            assert up._resolve_window(rlog) == _FALLBACK_WINDOW
        assert probe.call_count == _MAX_PROPS_ATTEMPTS
    assert up._window_guessed and not up._window_final
    with mock.patch("urllib.request.urlopen", return_value=Frames([sse({"content": f" w{i} "}) for i in range(9000)] + [sse({}, "stop")])):
        up.chat_watched(BODY, rlog)
    assert rlog.first("rumination.abort") is None
    up._calibrate("m", {"prompt_tokens": 5000}, 5000, rlog)
    assert up._window == _FALLBACK_WINDOW
    up._calibrate("m", {"prompt_tokens": 6000, "completion_tokens": 30000}, 5800, rlog)
    assert up._window == 36000 and not up._window_guessed and not up._window_final
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=props({"default_generation_settings": {"n_ctx": 49152}})):
        for _ in range(_PROPS_RETRY_EVERY):
            window = up._resolve_window(rlog)
    assert window == 49152 and up._window_final and not up._window_guessed
    up._window_at_least(99999, rlog)
    assert up._window == 49152
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("must not probe")):
        assert Upstream("http://x", api_key="sk-test")._resolve_window(rlog) is None

@rows([(5200, 5000, "tool_calls", True), (5200, 5000, "content", True), (5200, 400, "content", False), (49152, 5000, "tool_calls", False)])
def test_a_generation_that_used_the_whole_window_is_aborted_labelled_not_capped(window, frames, shape, aborts):
    """Measured 14 times: prompt + completion == n_ctx exactly, finish=length, nothing kept after 720 s (44k tokens into write_file args, which the rumination watcher skips on purpose). Near the end of the real room the stream is cut with a window_exhausted label; the same frames in a window that holds them pass untouched."""
    delta = lambda i: {"tool_calls": [{"index": 0, "function": {"arguments": f" w{i} "}}]} if shape == "tool_calls" else {"content": f" w{i} "}
    rlog = Rlog()
    with mock.patch("urllib.request.urlopen", return_value=Frames([sse(delta(i)) for i in range(frames)] + [sse({}, "stop")])):
        Upstream("http://x", context_window=window).chat_watched(BODY, rlog)
    abort = rlog.first("rumination.abort")
    assert (abort is not None) is aborts
    assert not aborts or (abort["window_exhausted"] and abort["room"] * rumination.WINDOW_EXHAUSTED_FRACTION <= abort["frames"] < frames)

def test_the_socket_deadline_is_owned_at_the_wire_and_a_silent_wire_is_a_repromptable_turn():
    """shipping-rates-rb x gemma4: a silent stream ran 743 s of a 949 s run. Streaming opens carry WIRE_SILENCE_SECONDS (above the worst measured prompt processing, 309 s, below the walked stalls, 525/743 s); a buffered post keeps the long timeout (its generation is ONE read). A silent wire ends as a dead_stream rumination (re-promptable), not an exception the harness blindly retries."""
    seen = []
    for stream in (True, False):
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: seen.append(timeout) or mock.MagicMock()):
            Upstream("http://x", context_window=49152)._open_with_refit(copy.deepcopy(BODY), stream, Rlog())
    assert seen[0] == rumination.WIRE_SILENCE_SECONDS and seen[1] > seen[0] and 309.4 < seen[0] < 525.0

    class Silent:
        def __iter__(self):
            raise TimeoutError("timed out")

        def close(self):
            pass

    rlog = Rlog()
    with mock.patch("urllib.request.urlopen", return_value=Silent()):
        out = Upstream("http://x", context_window=49152).chat_watched(BODY, rlog)
    assert rlog.first("rumination.abort")["dead_stream"] and rlog.first("rumination.abort")["wire"] and b"rumination" in out

def overflow(real, n_ctx):
    err = {"error": {"n_prompt_tokens": real, "n_ctx": n_ctx, "type": "exceed_context_size_error"}}
    return urllib.error.HTTPError("http://x/v1/chat/completions", 400, "Bad", {}, io.BytesIO(json.dumps(err).encode()))

def refit_body():
    task = "Complete the original task without dropping its restrictions."
    msgs = [{"role": "user", "content": "Keep the original local-only constraint."}, {"role": "user", "content": task}]
    for n in range(60):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"r{n}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": f"o{n}.txt"})}}]},
                 {"role": "tool", "tool_call_id": f"r{n}", "content": f"Observation {n}: " + "payload " * 80}]
    return {"model": "overflow-refit", "messages": msgs + [{"role": "user", "content": "A later amendment."}], bodykeys.PINNED_TASK: task}

GOOD = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"prompt_tokens": 4000}}).encode()

@rows([([overflow(9000, 8192), "GOOD"], 2, True), ([overflow(9000, 8192), overflow(9000, 8192)], 2, False), ([urllib.error.URLError("refused")], 1, False)])
def test_a_server_overflow_refits_exactly_once_and_only_reduces_history(outcomes, generations, survives):
    """A generation 400 carrying the server's own count triggers ONE changed re-prep (a lagging learned density); never a third request; non-overflow errors never refit; caller user turns and every call/result pair survive; the caller's body is untouched."""
    sent, queue = [], iter(outcomes)

    def opening(request, **kw):
        if request.full_url.endswith("/apply-template"):
            return props({"prompt": None})
        sent.append(json.loads(request.data))
        outcome = next(queue)
        if outcome == "GOOD":
            return mock.MagicMock(read=lambda: GOOD, close=lambda: None)
        raise outcome

    body, rlog = refit_body(), Rlog()
    original = copy.deepcopy(body)
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=opening):
        try:
            raw, err = Upstream("http://x", context_window=8192, capture_dir=None).chat(body, rlog), None
        except UpstreamError as caught:
            raw, err = None, caught
    assert (err is None) is survives and len(sent) == generations and body == original and (raw is None or raw == GOOD)
    assert (rlog.first("context.refit") or {}).get("real") == (9000 if generations == 2 else None)
    if generations == 2:
        assert sent[0] != sent[1] and len(sent[1]["messages"]) < len(sent[0]["messages"])
        assert [kw["refit"] for k, kw in rlog.events if k == "upstream.request"] == [False, True]
    for packet in sent:
        callers = [m for m in body["messages"] if m["role"] == "user"]
        assert [m for m in packet["messages"] if m in callers] == callers and bodykeys.PINNED_TASK not in packet
        assert {t["id"] for m in packet["messages"] for t in m.get("tool_calls") or []} == {m["tool_call_id"] for m in packet["messages"] if m["role"] == "tool"}

ERROR = {"code": 500, "type": "server_error", "message": "Invalid no-action protocol output; raw bytes (hex): " + b"<Thought>unfinished".hex()}

def rejection():
    return urllib.error.HTTPError("http://x/v1/chat/completions", 500, "ISE", {}, io.BytesIO(json.dumps({"error": ERROR}).encode()))

def test_protocol_errors_propagate_whole_and_a_half_written_call_is_never_assembled():
    """A typed 500 is not retried as a transient timeout. A streamed error frame after a half-written write_file (seen 280 times: llama.cpp 'Invalid diff') drops the fragment instead of shipping it as finish=tool_calls, reports the dropped bytes once, and falls to exactly one buffered re-ask (whose complete call, or typed error, is what the caller gets)."""
    make = lambda: Upstream("http://x", context_window=16384, capture_dir=None, capture_rendered=False)
    rlog = Rlog()
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=rejection()) as send, mock.patch("cria.upstream.time.sleep") as sleep:
        with pytest.raises(UpstreamError) as caught:
            make().chat(BODY, rlog)
    assert send.call_count == 1 and caught.value.code == 500 and not sleep.called and rlog.first("upstream.retry") is None
    partial = '{"path":"live.py","content":"x = [goose, '
    stream = lambda: Frames([sse({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "write_file"}}]}),
                             sse({"tool_calls": [{"index": 0, "function": {"arguments": partial}}]}), b"data: " + json.dumps({"error": ERROR}).encode() + b"\n"])
    first, rlog = stream(), Rlog()
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=[first, rejection()]) as send, mock.patch("cria.upstream.time.sleep"):
        with pytest.raises(UpstreamError):
            make().chat_watched(BODY, rlog)
    assert first.closed and json.loads(send.call_args_list[1].args[0].data)["stream"] is False and "stream_options" not in json.loads(send.call_args_list[1].args[0].data)
    assert [kw["dropped_tool_arg_chars"] for k, kw in rlog.events if k == "upstream.stream_error"] == [len(partial)]
    whole = json.dumps({"path": "live.py", "content": "x = ['goose']\n"})
    buffered = json.dumps({"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "write_file", "arguments": whole}}]}}]}).encode()
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=stream()), mock.patch.object(Upstream, "chat", return_value=buffered) as ask:
        raw = make().chat_watched(BODY, Rlog())
    assert ask.call_count == 1 and json.loads(json.loads(raw)["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == json.loads(whole)

def test_a_degenerate_tool_argument_run_is_aborted_but_varied_code_is_not():
    """Observed: 44,807 '0's in exec_command args. A stuck-token run aborts in flight (slot freed, re-promptable); a large legitimate write_file does not."""
    call = lambda a: sse({"tool_calls": [{"index": 0, "function": {"arguments": a}}]})
    stuck = Frames([sse({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "exec_command"}}]}), call('{"command":"'), call("0" * 3000), call("0" * 3000)])
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=stuck):
        done = json.loads(Upstream("http://x", context_window=49152).chat_watched(BODY, Rlog()))
    assert done["choices"][0]["finish_reason"] == "rumination" and done["cria_rumination"]["degenerate"] and stuck.closed
    fine = Frames([sse({"tool_calls": [{"index": 0, "id": "c", "function": {"name": "write_file"}}]}), call(json.dumps({"path": "h.py", "content": "def f():\n    return 42\n" * 80})), sse({}, "tool_calls")])
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=fine):
        assert json.loads(Upstream("http://x", context_window=49152).chat_watched(BODY, Rlog()))["choices"][0]["finish_reason"] == "tool_calls"

def test_a_malformed_native_tokenizer_or_template_reply_is_unknown_never_a_zero_count():
    """A count that is not a non-empty list of non-negative ints, or a template reply with no prompt, grants no capacity; a valid count is used."""
    up = Upstream("http://unused.invalid")
    for r in (None, [], {"tokens": []}, {"tokens": [True]}, {"tokens": [-1]}, {"tokens": ["12"]}, {"tokens": None}):
        up._ordinary_open = lambda *a, r=r, **k: io.BytesIO(json.dumps(r).encode())
        assert up._tokenize_prompt("real input", Rlog()) is None, r
    for r in (None, [], {"prompt": ""}, {"prompt": None}):
        up._ordinary_open = lambda *a, r=r, **k: io.BytesIO(json.dumps(r).encode())
        assert up._render_prompt({"messages": [{"role": "user", "content": "hello"}]}) is None, r
    up._ordinary_open = lambda *a, **k: io.BytesIO(b'{"tokens":[0,1,42]}')
    assert up._tokenize_prompt("real input", Rlog()) == 3

def test_density_is_learned_fast_up_slow_down_bounded_per_model_and_separately_for_summaries():
    """Real÷estimate: rises fast toward a denser turn, falls slowly, clamps, can learn below the 1.8 guess (gemma4 median 1.13), ignores missing counts; a summary's ~1.4 density never contaminates the coder's ~1.0."""
    tokenratio.reset()
    tokenratio.record("m", 30000, 10000)
    high = tokenratio.observed("m")
    tokenratio.record("m", 18000, 10000)
    assert 2.0 < high <= 3.0 and 2.2 < tokenratio.observed("m") < high and tokenratio.observed("other") == tokenratio.DEFAULT_RATIO
    for _ in range(20):
        tokenratio.record("low", 11300, 10000), tokenratio.record("floor", 5000, 10000), tokenratio.record("ceil", 100000, 10000)
    assert tokenratio.observed("low") < 1.3 and tokenratio.MIN_RATIO <= tokenratio.observed("floor") and tokenratio.observed("ceil") <= tokenratio.MAX_RATIO
    assert [tokenratio.record("z", *a) for a in ((None, 1), (0, 1), (5, 0))] == [None] * 3
    from cria.upstream import _density_key
    up, coder, summary = Upstream("http://x", context_window=8000), Rlog(), Rlog()
    for _ in range(8):
        up._calibrate("s", {"prompt_tokens": 1000}, 1000, coder)
    up._calibrate("s", {"prompt_tokens": 1400}, 1000, summary, {bodykeys.DENSITY_KIND: "summary"})
    assert tokenratio.observed(_density_key("s", coder)) < 1.2 < 1.3 < tokenratio.observed(_density_key("s", summary, {bodykeys.DENSITY_KIND: "summary"}))
    tokenratio.reset()

def test_adjacent_assistant_turns_merge_and_a_bare_assistant_is_never_sent():
    """The post-compaction 400: strict templates reject a bare {"role":"assistant"}. Adjacent assistants collapse, empties vanish, an empty assistant holding a tool_call stays."""
    roles = lambda m: [x["role"] for x in _merge_consecutive_assistant(m)]
    merged = _merge_consecutive_assistant([{"role": "user", "content": "go"}, {"role": "assistant", "content": "let me"}, {"role": "assistant", "content": None, "tool_calls": [CALL]}])
    assert [m["role"] for m in merged] == ["user", "assistant"] and merged[-1]["content"] == "let me" and merged[-1]["tool_calls"] == [CALL]
    assert roles([{"role": "assistant", "tool_calls": [CALL]}, {"role": "tool", "tool_call_id": "c", "content": "ok"}, {"role": "assistant"}, {"role": "user", "content": "n"}]) == ["assistant", "tool", "user"]
    assert roles([{"role": "user", "content": "go"}, {"role": "assistant", "content": ""}, {"role": "assistant", "content": None}]) == ["user"]
    assert roles([{"role": "assistant", "content": "", "tool_calls": [CALL]}]) == ["assistant"]
