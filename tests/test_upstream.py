import json
import unittest
import urllib.error
from unittest import mock

from cria import rumination
from cria.upstream import (
    _PROPS_RETRY_EVERY,
    _FALLBACK_WINDOW,
    _MAX_PROPS_ATTEMPTS,
    Upstream,
    _accumulate_tool_deltas,
    _assemble_completion,
)


class _PropsResp:
    """A urlopen context-manager result for a /props GET."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))
        return self


class _FakeResp:
    """A urlopen result: iterable over SSE byte lines, with a close() that records early aborts."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for ln in self._lines:
            self.consumed += 1
            yield ln

    def close(self):
        self.closed = True


def _sse(obj):
    return b"data: " + json.dumps(obj).encode() + b"\n"


def _delta(**d):
    return {"choices": [{"delta": d, "finish_reason": d.pop("_finish", None)}]}


class ToolAssemblyTests(unittest.TestCase):
    def test_accumulate_tool_deltas_by_index(self):
        acc = {}
        _accumulate_tool_deltas(acc, [{"index": 0, "id": "c1", "function": {"name": "write_file"}}])
        _accumulate_tool_deltas(acc, [{"index": 0, "function": {"arguments": '{"path":"a.py",'}}])
        _accumulate_tool_deltas(acc, [{"index": 0, "function": {"arguments": '"content":"x"}'}}])
        self.assertEqual(acc[0]["id"], "c1")
        self.assertEqual(acc[0]["name"], "write_file")
        self.assertEqual("".join(acc[0]["args"]), '{"path":"a.py","content":"x"}')

    def test_assemble_maps_finish_reason(self):
        acc = {0: {"id": "c1", "name": "write_file", "args": ['{"path":"a.py"}']}}
        c = _assemble_completion("m", [], [], acc, "stop", None, None)
        # a tool call present with a natural stop → normalized to tool_calls
        self.assertEqual(c["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(c["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "write_file")

    def test_assemble_rumination_sets_sentinel(self):
        c = _assemble_completion("m", ["thinking..."], ["reasoning"], {}, None, None, {"hits": 7, "reasoning_tokens": 5000})
        self.assertEqual(c["choices"][0]["finish_reason"], "rumination")
        self.assertEqual(c["cria_rumination"], {"hits": 7, "reasoning_tokens": 5000})


class WindowResolutionTests(unittest.TestCase):
    """Invariant: a LOCAL upstream ALWAYS ends up with a usable window — the floor is never
    silently disabled by a transient /props miss (pre-fix, one failure cached None forever)."""

    def test_transient_props_failure_keeps_floor_alive_then_heals(self):
        up = Upstream("http://x")  # local, no context_window → must discover
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=urllib.error.URLError("busy")):
            w = up._resolve_window(rlog)
        self.assertEqual(w, _FALLBACK_WINDOW)   # floor stays alive on the fallback…
        self.assertIsNotNone(w)                 # …never None (the pre-fix regression)
        self.assertFalse(up._window_final)      # still provisional → will retry
        # a later call, /props back up → real window replaces the fallback
        with mock.patch("cria.upstream.urllib.request.urlopen",
                        return_value=_PropsResp({"default_generation_settings": {"n_ctx": 16384}})):
            w2 = up._resolve_window(rlog)
        self.assertEqual(w2, 16384)
        self.assertTrue(up._window_final)

    def test_persistent_props_failure_keeps_the_floor_and_backs_OFF_rather_than_giving_up(self):
        """The attempt budget exists so a dead /props doesn't cost a probe on every single call. It
        must not become a permanent verdict: committing 8192 for the life of the process against a
        49,152-token model trims ~83% of the real window away, silently and forever, and the trigger
        is as ordinary as cria being restarted while llama.cpp is still loading. Probing BACKS OFF;
        it never stops."""
        up = Upstream("http://x")
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")) as probe:
            for _ in range(_MAX_PROPS_ATTEMPTS + 2):
                w = up._resolve_window(rlog)
                self.assertEqual(w, _FALLBACK_WINDOW)   # the floor stays alive on the fallback
                self.assertIsNotNone(w)
            self.assertEqual(probe.call_count, _MAX_PROPS_ATTEMPTS)   # …and stopped hammering it
        self.assertFalse(up._window_final)   # NOT a permanent verdict

    def test_a_window_that_was_missed_is_still_discovered_much_later(self):
        up = Upstream("http://x")
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=urllib.error.URLError("loading")):
            for _ in range(_MAX_PROPS_ATTEMPTS + 1):
                up._resolve_window(rlog)
        # llama.cpp finished loading long after the budget was spent — the real window must win
        with mock.patch("cria.upstream.urllib.request.urlopen",
                        return_value=_PropsResp({"default_generation_settings": {"n_ctx": 49152}})):
            for _ in range(_PROPS_RETRY_EVERY):
                w = up._resolve_window(rlog)
        self.assertEqual(w, 49152)
        self.assertTrue(up._window_final)

    def test_cloud_endpoint_never_probes_and_skips_floor(self):
        up = Upstream("http://x", api_key="sk-test")  # cloud → no floor, no /props
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("must not probe")):
            self.assertIsNone(up._resolve_window(rlog))


class ChatWatchedTests(unittest.TestCase):
    def _upstream(self):
        # context_window set → _resolve_window returns it without an HTTP /props call.
        return Upstream("http://x", context_window=8192, capture_dir=None)

    def test_assembles_tool_call_from_stream(self):
        lines = [
            _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "write_file"}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": '{"path":"h.py","content":"print(1)"}'}}])),
            _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
            b"data: [DONE]\n",
        ]
        resp = _FakeResp(lines)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        c = json.loads(raw)
        tc = c["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "write_file")
        self.assertEqual(json.loads(tc["function"]["arguments"])["path"], "h.py")
        self.assertEqual(c["choices"][0]["finish_reason"], "tool_calls")

    def test_streamed_completion_carries_measured_timings(self):
        """Streamed answers have no server "timings" block, so every streamed (coder) call was
        invisible to timing readers of the capture — the suite's tok/s silently averaged crew calls
        only. The assembled completion must stamp cria-measured timings whenever usage arrived."""
        lines = [
            _sse(_delta(content="hi")),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 7}}),
            b"data: [DONE]\n",
        ]
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        c = json.loads(raw)
        self.assertEqual(c["timings"]["predicted_n"], 7)
        self.assertGreater(c["timings"]["predicted_ms"], 0)
        self.assertEqual(c["timings"]["source"], "cria-measured")

    def test_no_usage_means_no_timings_block(self):
        # No token count → no rate to state. A fabricated or zero-token timings block would be
        # cria asserting a measurement it never made.
        lines = [
            _sse(_delta(content="hi")),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n",
        ]
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        self.assertNotIn("timings", json.loads(raw))

    def test_degenerate_tool_arg_runaway_is_aborted(self):
        # THE runaway: a model emits a stuck single-token stream inside tool-call ARGUMENTS (observed:
        # 44,807 '0's in exec_command args), which the rumination watcher deliberately skips. The
        # degenerate-run backstop must abort it — even with no rumination watch — so it doesn't burn
        # the window to a dead turn.
        run = "0" * 3000  # > DEGENERATE_RUN_CHARS (2048)
        lines = [
            _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "exec_command"}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": '{"command":"'}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": run}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": run}}])),  # never reached — aborted
            b"data: [DONE]\n",
        ]
        resp = _FakeResp(lines)
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        c = json.loads(raw)
        self.assertEqual(c["choices"][0]["finish_reason"], "rumination")   # reuses the re-prompt path
        self.assertTrue(c["cria_rumination"].get("degenerate"))
        self.assertTrue(resp.closed)                                       # aborted in-flight, slot freed

    def test_normal_tool_args_are_not_aborted(self):
        # A legit write_file with varied content must NOT trip the degenerate backstop.
        content = json.dumps({"path": "h.py", "content": "def f():\n    return 42\n" * 80})
        lines = [
            _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "write_file"}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": content}}])),
            _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
            b"data: [DONE]\n",
        ]
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
            raw = self._upstream().chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog())
        self.assertEqual(json.loads(raw)["choices"][0]["finish_reason"], "tool_calls")

    def test_mid_stream_error_frame_reissues_buffered_instead_of_assembling_a_fragment(self):
        # THE bug this pins (observed live, 280 times across runs): llama.cpp's streaming tool-call
        # differ raises "Invalid diff" when a partial-JSON heal lands mid-escape, and ends the stream
        # with an SSE *error* frame ~75% through a write_file. Assembling the accumulated fragment
        # would hand the caller a truncated tool call wearing finish_reason="tool_calls" — cria
        # asserting the model wrote something it never wrote. The same request buffered returns the
        # complete call, so cria must re-ask rather than assemble.
        partial = '{"path":"live.py","content":"handles = [\'goose\', \'papagoose\\'
        lines = [
            _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "write_file"}}])),
            _sse(_delta(tool_calls=[{"index": 0, "function": {"arguments": partial}}])),
            _sse({"error": {"code": 500, "message": "Invalid diff: '...' not found at start of '...'"}}),
        ]
        whole = json.dumps({"path": "live.py", "content": "handles = ['goose', 'papagoose']\n"})
        buffered = json.dumps({"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "write_file", "arguments": whole}}]}}]}).encode()
        up = self._upstream()
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)), \
             mock.patch.object(Upstream, "chat", return_value=buffered) as buffered_call:
            raw = up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog)
        self.assertEqual(buffered_call.call_count, 1)                      # re-asked, once
        tc = json.loads(raw)["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tc["function"]["arguments"])                     # parses — the FULL call
        self.assertEqual(args["content"], "handles = ['goose', 'papagoose']\n")
        self.assertNotIn("stream_options", buffered_call.call_args[0][0])  # buffered body is clean

    def test_saves_full_reasoning_untruncated_to_capture_sibling(self):
        import tempfile
        from pathlib import Path
        det = rumination.Detector(budget=10_000_000, threshold=999)  # never fires — capture a normal turn
        # ~23k chars; must NOT be clipped. VARIED, not one sentence x500: the degeneration guard now
        # catches any repeating period, and a fixture that repeats one sentence is itself the shape it
        # exists to stop. The point of this test is length, not repetition.
        big = "".join(f"Step {i}: resolve handle {i} then check the mock result for it. " for i in range(500))
        lines = [
            _sse(_delta(reasoning_content=big)),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
            rlog = _Rlog()
            with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog, watch=det.check)
            files = list(Path(tmp).rglob("*.reasoning.txt"))
            self.assertEqual(len(files), 1)                       # one reasoning file per coder call
            self.assertEqual(files[0].read_text(), big)          # the WHOLE block, byte-for-byte, untruncated
            self.assertIn("coder.reasoning", [k for k, _ in rlog.events])

    def test_ruminating_reasoning_file_is_marked(self):
        import tempfile
        from pathlib import Path
        det = rumination.Detector(budget=1000, threshold=3)  # fires
        chunk = "actually wait hmm let me reconsider on second thought " * 10
        lines = [_sse(_delta(reasoning_content=chunk)) for _ in range(20)] + [b"data: [DONE]\n"]
        with tempfile.TemporaryDirectory() as tmp:
            up = Upstream("http://x", context_window=8192, capture_dir=tmp, capture_rendered=False)
            with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_FakeResp(lines)):
                up.chat_watched({"model": "m", "messages": [{"role": "user", "content": "go"}]}, _Rlog(), watch=det.check)
            saved = list(Path(tmp).rglob("*.reasoning.txt"))[0].read_text()
            self.assertIn("RUMINATION GUARD FIRED", saved)          # marked at the top
            self.assertIn("ABORTED HERE by the rumination guard", saved)  # and where it was cut
            self.assertIn("let me reconsider", saved)               # the full reasoning is still there

    def test_rumination_abort_cuts_stream_early(self):
        det = rumination.Detector(budget=1000, threshold=3)  # gate 500 tok; fires fast
        chunk = "actually wait hmm let me reconsider on second thought " * 10  # ~530 chars, many markers
        lines = [_sse(_delta(reasoning_content=chunk)) for _ in range(20)] + [b"data: [DONE]\n"]
        resp = _FakeResp(lines)
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            raw = self._upstream().chat_watched(
                {"model": "m", "messages": [{"role": "user", "content": "go"}]}, rlog, watch=det.check)
        c = json.loads(raw)
        self.assertEqual(c["choices"][0]["finish_reason"], "rumination")
        self.assertIn("cria_rumination", c)
        self.assertTrue(resp.closed)
        self.assertLess(resp.consumed, len(lines))  # aborted BEFORE draining the whole stream
        self.assertIn("rumination.abort", [k for k, _ in rlog.events])


class MergeAssistantTests(unittest.TestCase):
    def test_adjacent_assistants_merged(self):
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "let me do that"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]},
        ]
        out = _merge_consecutive_assistant(msgs)
        self.assertEqual([m["role"] for m in out], ["user", "assistant"])   # collapsed to one
        self.assertEqual(out[-1]["content"], "let me do that")
        self.assertEqual(len(out[-1]["tool_calls"]), 1)

    def test_non_adjacent_assistants_untouched(self):
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "s", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        self.assertEqual([m["role"] for m in _merge_consecutive_assistant(msgs)], ["assistant", "tool", "assistant"])

    def test_bare_assistant_dropped_not_sent(self):
        # The real post-compaction 400: a bare {"role": "assistant"} (no content, no tool_calls) —
        # the strict gemma template rejects it ("must contain either 'content' or 'tool_calls'").
        # It must be dropped, not merged into a same-role neighbor and shipped.
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "s", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "assistant"},                       # the offender — bare
            {"role": "user", "content": "next"},
        ]
        out = _merge_consecutive_assistant(msgs)
        self.assertEqual([m["role"] for m in out], ["assistant", "tool", "user"])
        self.assertFalse(any(m.get("role") == "assistant" and not m.get("content") and not m.get("tool_calls") for m in out))

    def test_merge_of_two_empty_assistants_yields_no_bare_message(self):
        # The synthesis path: two adjacent EMPTY assistants merge to a bare {"role": "assistant"} —
        # which must then be dropped, not emitted.
        from cria.upstream import _merge_consecutive_assistant
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": None},
        ]
        out = _merge_consecutive_assistant(msgs)
        self.assertEqual([m["role"] for m in out], ["user"])   # both empties gone, nothing bare left

    def test_empty_assistant_with_tool_calls_is_kept(self):
        # An assistant with EMPTY content but a real tool_call is a valid turn — never dropped.
        from cria.upstream import _merge_consecutive_assistant
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "s", "arguments": "{}"}}]}]
        self.assertEqual(len(_merge_consecutive_assistant(msgs)), 1)


class LoadedModelTests(unittest.TestCase):
    """cria asks the server what's ACTUALLY loaded (/v1/models → the --alias), so the banner shows
    the truth instead of a config label — no silent model mismatch."""

    def test_reads_and_caches_the_loaded_alias(self):
        up = Upstream("http://x")
        resp = _PropsResp({"data": [{"id": "gemma_4_12b_fable_v2_q4"}]})
        with mock.patch("cria.upstream.urllib.request.urlopen", return_value=resp):
            self.assertEqual(up.loaded_model(_Rlog()), "gemma_4_12b_fable_v2_q4")
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("cached — no refetch")):
            self.assertEqual(up.loaded_model(_Rlog()), "gemma_4_12b_fable_v2_q4")

    def test_none_for_cloud_endpoint(self):
        up = Upstream("http://x", api_key="sk-test")
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("must not probe")):
            self.assertIsNone(up.loaded_model(_Rlog()))

    def test_prep_fills_missing_model_from_loaded(self):
        # A role that omits its alias sends a body with no `model`; _prep fills it (in place) from
        # the server's loaded model so the wire + density key + echoed completion all agree.
        up = Upstream("http://x", context_window=8192)
        up._loaded_model = "gemma_4_12b_fable_v2_q4"  # pre-seed the cache (skip the /v1/models call)
        body = {"messages": [{"role": "user", "content": "hi"}]}  # NO model key
        up._prep(body, False, _Rlog())
        self.assertEqual(body["model"], "gemma_4_12b_fable_v2_q4")

    def test_prep_leaves_an_explicit_model_untouched(self):
        up = Upstream("http://x", context_window=8192)
        up._loaded_model = "server-loaded"
        body = {"model": "explicit-alias", "messages": [{"role": "user", "content": "hi"}]}
        up._prep(body, False, _Rlog())
        self.assertEqual(body["model"], "explicit-alias")  # a set alias wins; no override


class _BufResp:
    """A urlopen result for a buffered (non-stream) call: read() once, then close()."""

    def __init__(self, raw):
        self._raw = raw
        self.closed = False

    def read(self):
        return self._raw

    def close(self):
        self.closed = True


def _overflow_error(n_prompt_tokens, n_ctx):
    import io
    body = json.dumps({"error": {
        "n_prompt_tokens": n_prompt_tokens, "n_ctx": n_ctx, "type": "exceed_context_size_error"}}).encode()
    return urllib.error.HTTPError("http://x/v1/chat/completions", 400, "Bad Request", {}, io.BytesIO(body))


class OverflowRefitTests(unittest.TestCase):
    """cria's floor budgets against a LEARNED per-model density that lags a single hot (base64/blob)
    turn. When the server still 400s 'exceeds context', cria re-fits to the REAL token count it
    reports and retries ITSELF — so the harness never sees the 400 (its blind same-body retries
    can't converge fast enough)."""

    def _big_body(self):
        # Enough messages that a tighter density visibly trims MORE of them on the refit.
        msgs = [{"role": "user", "content": "payload " * 80} for _ in range(200)]
        return {"model": "m", "messages": msgs}

    def test_overflow_triggers_a_single_refit_retry_that_succeeds(self):
        up = Upstream("http://x", context_window=8192, capture_dir=None)
        good = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                           "usage": {"prompt_tokens": 4000, "completion_tokens": 1}}).encode()
        calls = [_overflow_error(9000, 8192), _BufResp(good)]
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=calls) as m:
            raw = up.chat(self._big_body(), rlog)
        self.assertEqual(m.call_count, 2)                       # 400 → re-fit → retry, then 200
        self.assertEqual(json.loads(raw)["choices"][0]["message"]["content"], "ok")
        refits = [kw for k, kw in rlog.events if k == "context.refit"]
        self.assertEqual(len(refits), 1)
        self.assertEqual(refits[0]["real"], 9000)              # learned the server's real count
        reqs = [kw for k, kw in rlog.events if k == "upstream.request"]
        self.assertEqual([r["refit"] for r in reqs], [False, True])
        # the retry was prepped TIGHTER against the real count → the wire body kept fewer messages
        sent = [len(json.loads(c.args[0].data)["messages"]) for c in m.call_args_list]
        self.assertLess(sent[1], sent[0])

    def test_non_overflow_error_is_not_retried(self):
        up = Upstream("http://x", context_window=8192, capture_dir=None)
        rlog = _Rlog()
        with mock.patch("cria.upstream.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("connection refused")) as m:
            with self.assertRaises(Exception):
                up.chat(self._big_body(), rlog)
        self.assertEqual(m.call_count, 1)                       # not a refittable overflow → no retry
        self.assertFalse([k for k, _ in rlog.events if k == "context.refit"])

    def test_second_overflow_is_not_retried_again(self):
        # If the re-fit STILL overflows (should not happen, but be safe), give up — one retry only,
        # then surface the error rather than looping.
        up = Upstream("http://x", context_window=8192, capture_dir=None)
        rlog = _Rlog()
        errs = [_overflow_error(9000, 8192), _overflow_error(9000, 8192)]
        with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=errs) as m:
            with self.assertRaises(Exception):
                up.chat(self._big_body(), rlog)
        self.assertEqual(m.call_count, 2)                       # one refit attempt, no infinite loop


class ChatTimingTests(unittest.TestCase):
    """Non-streaming chat must time the FULL generation, not just the buffered-body read. A blocking
    urlopen returns only AFTER the server finished generating; timing from after the open reported
    millions of tok/s (the reasoner-banner bug: gemma_4_12b at 3.3M tok/s)."""

    def test_tok_per_s_measures_generation_not_body_read(self):
        import time as _time
        up = Upstream("http://x", context_window=8192, capture_dir=None)
        raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hi"}}],
                          "usage": {"completion_tokens": 50, "prompt_tokens": 10}}).encode()

        class _Resp:
            def read(self_):
                return raw          # instant — the body is already generated server-side

            def close(self_):
                pass

        def fake_open(b, stream, rlog):
            _time.sleep(0.1)        # the server generating; a non-stream urlopen blocks HERE
            return _Resp(), 10, None

        rlog = _Rlog()
        with mock.patch.object(up, "_open_with_refit", side_effect=fake_open), \
             mock.patch("cria.upstream.callcapture.capture_response"):
            up.chat({"model": "m", "messages": []}, rlog)
        done = [kw for k, kw in rlog.events if k == "upstream.done"][0]
        tps = done["tok_per_s"]
        self.assertIsNotNone(tps)
        self.assertLess(tps, 5000)      # ~500 tok/s (50 tok / 0.1s) — NOT the millions the old timing gave
        self.assertGreater(tps, 50)     # the 0.1s generation IS in the interval (not a near-zero read window)
