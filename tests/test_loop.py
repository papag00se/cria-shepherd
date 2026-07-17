import json
import unittest

from cria.loop import Loop, LoopContext, LoopStore, PlanSession, completion_to_sse, session_key
from cria.plan import Plan, PlanItem
from cria.shelltool import find_shell_tool, shell_args


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _Scripted:
    """Returns canned completions in order; repeats the last when exhausted."""

    def __init__(self, responses):
        self._r = list(responses)
        self.calls = 0

    def __call__(self, body, rlog):
        self.calls += 1
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()


class _Planner:
    def __init__(self, plan):
        self._plan = plan
        self.prior_work_seen = None
        self.rewrite_summary_seen = None

    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        self.prior_work_seen = prior_work
        self.rewrite_summary_seen = rewrite_summary
        return self._plan


def _plan(n=2):
    return Plan(id="20260707T0000-abcd1234", task="build it", created="2026-07-07T00:00:00+00:00",
                items=[PlanItem(f"step {i+1}") for i in range(n)])


def _toolcall():
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}


def _done(text="looks done"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _verdict(done=True, reason="ok"):
    return {"choices": [{"message": {"content": json.dumps({"done": done, "reason": reason})}}]}


def _unparseable():
    # A reasoning model that burned its token budget thinking and never emitted the JSON verdict.
    return {"choices": [{"message": {"content": "Okay, let me consider whether this step's goal is met"}}]}


_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}


def _ctx(coder, reasoner, plan=None, workspace_root=None):
    return LoopContext(planner=_Planner(plan or _plan()), coder_chat=coder,
                       reasoner_chat=reasoner, runs_dir="",  # "" = no run-artifact writes in tests
                       workspace_root=workspace_root)


def _body(tools=True):
    return {"messages": [{"role": "user", "content": "build an ada handle resolver"}], "tools": [_SHELL] if tools else [], "stream": True}


def _body_with_probe(call_id, output):
    """Simulate the harness having run cria's ground-truth probe: its result is now in the stream."""
    b = _body()
    b["messages"] = b["messages"] + [{"role": "tool", "tool_call_id": call_id, "content": output}]
    return b


def _tc_id(completion):
    return completion["choices"][0]["message"]["tool_calls"][0]["id"]


class _Recorder:
    """A coder stub that records the bodies it's handed and returns scripted completions."""

    def __init__(self, responses):
        self._r = list(responses)
        self.bodies = []
        self.calls = 0

    def __call__(self, body, rlog):
        self.bodies.append(body)
        self.calls += 1
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()

    def last_user(self):
        return self.bodies[-1]["messages"][-1]["content"]


def _trunc_write(path="h.py"):
    # A write_file cut off at the token cap: finish_reason=length + args that are truncated JSON.
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "write_file",
         "arguments": '{"path":"' + path + '","content":"partial and cut off'}}]},
        "finish_reason": "length"}], "usage": {"completion_tokens": 30675}}


def _ruminating():
    return {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "rumination"}],
            "cria_rumination": {"hits": 7, "reasoning_tokens": 5000}}


def _framed():
    return {"messages": [{"role": "system", "content": "do the step"},
                         {"role": "user", "content": "write h.py"}], "tools": [_SHELL]}


class GuardTests(unittest.TestCase):
    def _loop(self, coder):
        from cria.loop import Loop
        return Loop(_ctx(coder, _Scripted([_verdict()])))

    # -------- truncation guard --------
    def test_truncation_steers_incremental_and_recovers(self):
        rec = _Recorder([_toolcall()])  # the retry succeeds with a clean tool call
        rlog = _Rlog()
        out = self._loop(rec)._guard_truncation(_trunc_write(), _framed(), idx=4, rlog=rlog)
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))       # recovered (retry's call)
        self.assertIn("loop.truncated", rlog.kinds())
        ev = dict(rlog.events)["loop.truncated"]
        self.assertEqual(ev["path"], "h.py")                                  # path parsed from cut-off JSON
        self.assertEqual(ev["output_tokens"], 30675)
        self.assertIn("SMALL pieces", rec.last_user())                        # the incremental-write steer

    def test_truncation_exhausted_refuses_partial_write(self):
        rec = _Recorder([_trunc_write()])  # ALWAYS truncates
        rlog = _Rlog()
        out = self._loop(rec)._guard_truncation(_trunc_write(), _framed(), idx=4, rlog=rlog)
        self.assertEqual(rec.calls, 3)                                        # capped at MAX_TRUNCATION_RETRIES
        self.assertIn("loop.truncated_dropped", rlog.kinds())
        self.assertFalse(out["choices"][0]["message"].get("tool_calls"))      # partial write NOT forwarded
        self.assertNotEqual(out["choices"][0]["finish_reason"], "length")     # sentinel normalized

    def test_non_write_truncation_not_retried_as_write(self):
        # A truncation with no write path (e.g. cut-off reasoning) → don't apply the write steer,
        # don't ship a partial; just refuse. Only the initial detection, no incremental retries.
        trunc_noargs = {"choices": [{"message": {"role": "assistant", "content": "x"}, "finish_reason": "length"}]}
        rec = _Recorder([_toolcall()])
        rlog = _Rlog()
        out = self._loop(rec)._guard_truncation(trunc_noargs, _framed(), idx=2, rlog=rlog)
        self.assertEqual(rec.calls, 0)                                        # no write path → no retry
        self.assertIn("loop.truncated_dropped", rlog.kinds())

    # -------- rumination guard --------
    def test_rumination_refocuses_and_recovers(self):
        rec = _Recorder([_toolcall()])
        rlog = _Rlog()
        out = self._loop(rec)._guard_rumination(_ruminating(), _framed(), idx=4, rlog=rlog)
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
        self.assertIn("loop.rumination", rlog.kinds())
        self.assertIn("RUMINATION GUARD", rec.last_user())
        self.assertNotIn("cria_rumination", out)                             # internal marker stripped

    def test_rumination_exhausted_normalizes_and_stops(self):
        rec = _Recorder([_ruminating()])  # never focuses
        rlog = _Rlog()
        out = self._loop(rec)._guard_rumination(_ruminating(), _framed(), idx=4, rlog=rlog)
        self.assertEqual(rec.calls, 3)
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")         # sentinel normalized on exit
        self.assertNotIn("cria_rumination", out)


def _summary(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class _Question:
    engagement = "question"
    task_type = "question"
    cached = True


class SessionGateTests(unittest.TestCase):
    def test_has_session_reflects_store(self):
        from cria.loop import Loop, LoopStore, PlanSession
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict()])), store)
        self.assertFalse(loop.has_session("k"))
        store.put("k", PlanSession(plan=_plan(1)))
        self.assertTrue(loop.has_session("k"))
        store.drop("k")
        self.assertFalse(loop.has_session("k"))

    def test_live_session_continues_regardless_of_classification(self):
        # The bug: a returning tool result classifies as 'question' and the loop got abandoned. drive()
        # consults classification ONLY when there's no live session; an in-flight plan must continue.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_toolcall(), _toolcall()]), _Scripted([_verdict()]), _plan(1)), store)
        loop.drive(_body(), "k", _Classification(), _Rlog())     # start the plan (task) → plan-file op
        self.assertTrue(loop.has_session("k"))
        out = loop.drive(_body(), "k", _Question(), _Rlog())     # next turn reads as a QUESTION
        self.assertIsNotNone(out)                                # …but the live plan still drives
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))

    def test_no_session_and_question_falls_through_to_proxy(self):
        # With no live plan, a non-task turn must NOT be hijacked by the loop (returns None → proxy).
        from cria.loop import Loop, LoopStore
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1)), LoopStore())
        self.assertIsNone(loop.drive(_body(), "k", _Question(), _Rlog()))


class CompactionTests(unittest.TestCase):
    def test_done_marker_lives_in_the_shape_not_a_briefing_store(self):
        # No server-side briefing store exists — only a one-bit `done` marker on the shape.
        from cria.loop import LoopStore
        s = LoopStore()
        s.observe_shape("sid:k", "fp1", 3)
        self.assertFalse(s.shape_done("sid:k"))
        s.mark_done("sid:k")
        self.assertTrue(s.shape_done("sid:k"))
        s.mark_done("sid:unknown")                       # no shape → no-op, no crash
        self.assertFalse(s.shape_done("sid:unknown"))
        s.observe_shape("sid:k", "fp1", 9)               # re-observing preserves the done bit
        self.assertTrue(s.shape_done("sid:k"))

    def test_compact_done_summarizes_via_reasoner(self):
        from cria.loop import Loop, PlanSession
        reasoner = _Scripted([_summary("Built resolve_handle.py (handler) + test_resolve_handle.py; run: pytest -q.")])
        loop = Loop(_ctx(_Scripted([_done()]), reasoner))
        sess = PlanSession(plan=_plan(1))
        sess.plan.items[0].done = True
        rlog = _Rlog()
        out = loop._compact_done(sess, _body(), rlog)
        self.assertIn("resolve_handle.py", out)
        self.assertIn("loop.compacted", rlog.kinds())

    def test_compact_done_falls_back_to_running_summary(self):
        from cria.loop import Loop, PlanSession
        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_summary("")])))  # model returns nothing
        sess = PlanSession(plan=_plan(1), summary="step 1 done: built X")
        out = loop._compact_done(sess, _body(), _Rlog())
        self.assertEqual(out, "step 1 done: built X")  # never break completion — fall back

    def test_follow_up_plan_is_grounded_from_history_briefing(self):
        # The briefing rides IN the conversation (the closing message); a follow-up re-reads it
        # from history — nothing is stored server-side.
        from cria.loop import BRIEFING_CLOSE, BRIEFING_OPEN, Loop, LoopStore
        store = LoopStore()
        ctx = _ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1))
        loop = Loop(ctx, store)
        body = _body()
        body["messages"] = body["messages"] + [
            {"role": "assistant", "content": f"⟦cria⟧ plan complete — all 1 steps verified.\n\n"
             f"{BRIEFING_OPEN}\nDONE: built the handler + unit tests + README\n{BRIEFING_CLOSE}"},
            {"role": "user", "content": "now add a README badge"},
        ]
        loop.drive(body, "sid:k", _Classification(), _Rlog())
        self.assertEqual(ctx.planner.prior_work_seen, "DONE: built the handler + unit tests + README")
        self.assertEqual(store.get("sid:k").prior_work, "DONE: built the handler + unit tests + README")

    def test_loop_done_stores_compaction_end_to_end(self):
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        coder = _Scripted([_toolcall(), _done()])
        reasoner = _Scripted([_verdict(True), _summary("BUILT the handler; run pytest -q")])
        loop = Loop(_ctx(coder, reasoner, _plan(1)), store)
        C = _Classification()
        c1 = loop.drive(_body(), "sid:k", C, _Rlog())                              # work → coder tool call
        c2 = loop.drive(_body(), "sid:k", C, _Rlog())                              # coder done → probe
        final = loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "sid:k", C, _Rlog())  # verify → all done → loop.done
        closing = final["choices"][0]["message"]["content"]
        self.assertIn("plan complete", closing)
        from cria.loop import BRIEFING_OPEN
        self.assertIn(BRIEFING_OPEN, closing)                                      # briefing embedded in the message
        self.assertIn("BUILT the handler", closing)                                # …content included
        self.assertTrue(store.shape_done("sid:k"))                                 # only the one-bit marker server-side

    def test_drive_stamps_wire_envelope_on_completions(self):
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        coder = _Scripted([_toolcall(), _done()])
        reasoner = _Scripted([_verdict(True), _summary("done")])
        loop = Loop(_ctx(coder, reasoner, _plan(1)), store)
        c1 = loop.drive(_body(), "sid:k", _Classification(), _Rlog())
        self.assertIsNotNone(c1)
        self.assertTrue(c1["id"].startswith("chatcmpl-"))  # non-Codex chat clients need a full envelope
        self.assertIsInstance(c1["created"], int)
        self.assertIn("model", c1)
        chunks = b"".join(completion_to_sse(c1))
        self.assertIn(c1["id"].encode(), chunks)           # id propagates into the SSE chunks

    def test_work_log_strips_cria_ops_keeps_real_actions(self):
        from cria.loop import _work_log
        msgs = [
            {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "write_file", "arguments": '{"path":"h.py","content":"x"}'}}]},
            {"role": "tool", "tool_call_id": "a", "content": "wrote 12 bytes to h.py"},
            {"role": "assistant", "tool_calls": [{"id": "b", "function": {"name": "shell", "arguments": '{"command":["bash","-lc","mkdir -p .cria && printf %s Zm9v | base64 -d > .cria/p.md"]}'}}]},
            {"role": "tool", "tool_call_id": "b", "content": "(cria plan file written)"},
        ]
        log = _work_log(msgs)
        self.assertIn("write_file", log)
        self.assertIn("h.py", log)
        self.assertNotIn(".cria", log)  # cria's own plan-file op stripped, not counted as work


def _body_rewritten(summary="Summary: built handler.py + tests; current goal: finish the live test."):
    """A post-compaction request: same session key, but the conversation ROOT was replaced
    by the harness's summary (structurally, a different first user message)."""
    return {"messages": [{"role": "user", "content": summary}], "tools": [_SHELL], "stream": True}


class HistoryRewriteTests(unittest.TestCase):
    """Structural harness-compaction detection: a changed conversation root under a stable
    session key = the history was rewritten. No phrase-matching anywhere."""

    def test_observe_shape_flags_only_root_changes(self):
        from cria.loop import LoopStore
        s = LoopStore()
        self.assertFalse(s.observe_shape("k", "fp1", 3))   # first sight — not a rewrite
        self.assertFalse(s.observe_shape("k", "fp1", 9))   # appended turns, same root — no flag
        self.assertTrue(s.observe_shape("k", "fp2", 2))    # root REPLACED → rewrite
        self.assertTrue(s.observe_shape("k", "fp2", 5))    # STICKY: pending until acted on...
        s.clear_rewrite("k")                                # ...the loop clears it when it acts
        self.assertFalse(s.observe_shape("k", "fp2", 7))   # cleared + stable → no re-flag
        self.assertFalse(s.observe_shape("k2", "", 1))     # no root at all → never flags

    def test_rewrite_after_done_plans_continuation_not_fresh_task(self):
        # The lame-plan bug: plan finished (briefing stored), Codex compacted, next request's root
        # is the summary. Must plan via the rewrite frame — bypassing the classifier's opinion of
        # the summary text — and must NOT stack cria's briefing on top of the harness summary.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        ctx = _ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1))
        loop = Loop(ctx, store)
        loop.drive(_body(), "sid:abc", _Classification(), _Rlog())      # original task seen (shape recorded)
        store.drop("sid:abc")                                            # plan finished → session dropped
        store.mark_done("sid:abc")                                       # the one-bit completion marker
        rlog = _Rlog()
        out = loop.drive(_body_rewritten(), "sid:abc", _Question(), rlog)  # summary classifies as 'question'
        self.assertIsNotNone(out)                                        # continuation still planned
        self.assertIn("Summary: built handler.py", ctx.planner.rewrite_summary_seen)  # rewrite frame
        self.assertEqual(ctx.planner.prior_work_seen, "")                # NO summary stacking
        self.assertIn("Summary: built handler.py",                       # coder grounded by the harness summary
                      store.get("sid:abc").prior_work)                   # (the briefing was folded into it)
        self.assertIn("loop.history_rewritten", rlog.kinds())
        starts = [kw for k, kw in rlog.events if k == "loop.start"]
        self.assertTrue(starts and starts[0].get("rewritten"))

    def test_rewrite_without_briefing_needs_task_classification(self):
        # No completed briefing (e.g. compaction mid-question-chat): don't hijack a non-task turn.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        ctx = _ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1))
        loop = Loop(ctx, store)
        store.observe_shape("sid:q", "originalroot", 3)                  # session known by shape only
        self.assertIsNone(loop.drive(_body_rewritten(), "sid:q", _Question(), _Rlog()))
        # ...but a task-classified rewrite DOES plan, with the rewrite frame (no briefing to prefer)
        out = loop.drive(_body_rewritten("S2: different summary"), "sid:q", _Classification(), _Rlog())
        self.assertIsNotNone(out)
        self.assertIn("S2: different summary", ctx.planner.rewrite_summary_seen)
        self.assertIn("S2: different summary", store.get("sid:q").prior_work)  # clipped summary as prior

    def test_normal_followup_still_uses_briefing_not_rewrite_frame(self):
        # A same-root follow-up (no compaction) keeps the existing plan_continuation behavior.
        from cria.loop import Loop, LoopStore
        from cria.loop import BRIEFING_CLOSE, BRIEFING_OPEN
        store = LoopStore()
        ctx = _ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1))
        loop = Loop(ctx, store)
        body = _body()
        body["messages"] = body["messages"] + [
            {"role": "assistant", "content": f"{BRIEFING_OPEN}\nthe briefing\n{BRIEFING_CLOSE}"},
            {"role": "user", "content": "now do a follow-up thing"},
        ]
        loop.drive(body, "sid:f", _Classification(), _Rlog())
        self.assertEqual(ctx.planner.prior_work_seen, "the briefing")    # re-read from history
        self.assertEqual(ctx.planner.rewrite_summary_seen, "")

    def test_probe_result_lost_to_rewrite_reissues_probe(self):
        # Mid-plan compaction erases the probe's tool result. Fail-open would pass the step with
        # zero ground truth; instead the probe is re-issued.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_done(), _done()]), _Scripted([_verdict()]), _plan(1)), store)
        loop.drive(_body(), "sid:m", _Classification(), _Rlog())         # work → coder done → PROBE emitted
        rlog = _Rlog()
        out = loop.drive(_body_rewritten(), "sid:m", _Classification(), rlog)  # rewritten; probe result GONE
        self.assertIn("loop.probe_reissued", rlog.kinds())
        from cria.probegate import SECTION_PREFIX
        args = json.loads(out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertIn(SECTION_PREFIX, " ".join(args["command"]))        # a fresh ground-truth gate
        self.assertNotIn("loop.step_done", rlog.kinds())                # nothing passed silently

    def test_probe_absent_without_rewrite_keeps_fail_open(self):
        # The existing don't-wedge behavior is preserved when there was NO rewrite: an absent
        # probe result still fails open to the critic path.
        from cria.loop import Loop, LoopStore
        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict(True), _summary("s")]), _plan(1)), LoopStore())
        loop.drive(_body(), "sid:n", _Classification(), _Rlog())         # coder done → probe emitted
        rlog = _Rlog()
        out = loop.drive(_body(), "sid:n", _Classification(), rlog)      # same root; result just absent
        self.assertNotIn("loop.probe_reissued", rlog.kinds())
        self.assertIn("loop.probe", rlog.kinds())                        # judged (fail-open) as before

    def test_knows_session_via_live_completed_or_shape(self):
        from cria.loop import Loop, LoopStore, PlanSession
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict()])), store)
        self.assertFalse(loop.knows_session("k"))
        store.observe_shape("k", "fp", 2)
        self.assertTrue(loop.knows_session("k"))                         # shape
        store.put("k3", PlanSession(plan=_plan(1)))
        self.assertTrue(loop.knows_session("k3"))                        # live

    def test_state_persists_across_restart(self):
        # Briefings + shapes survive a new LoopStore instance (a cria restart); live plans don't.
        import tempfile, os
        from cria.loop import LoopStore, PlanSession
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "loopstate.json")
            s1 = LoopStore(state_path=p)
            s1.observe_shape("sid:x", "rootfp", 4)
            s1.mark_done("sid:x")
            plan = _plan(2)
            plan.items[0].done = True                                    # step 1 finished mid-plan
            s1.put("sid:x", PlanSession(plan=plan, summary="1. did the thing"))
            s2 = LoopStore(state_path=p)                                 # "restart"
            self.assertTrue(s2.shape_done("sid:x"))                      # done bit survived
            self.assertTrue(s2.observe_shape("sid:x", "NEWROOT", 2))     # rewrite still detected post-restart
            resumed = s2.get("sid:x")                                    # live plans RESUME (restart-amnesia fix)
            self.assertIsNotNone(resumed)
            self.assertTrue(resumed.plan.items[0].done)                  # finished steps stay finished
            self.assertEqual(resumed.plan.current().text, "step 2")      # picks up where it left off
            self.assertEqual(resumed.summary, "1. did the thing")
            self.assertFalse(resumed.awaiting_probe)                     # transient turn state reset


class _FlakyPlanner:
    """Returns None for the first N calls (unplannable), then the plan — for sticky-rewrite tests."""

    def __init__(self, plan, fail_first=1):
        self._plan = plan
        self._fails = fail_first
        self.rewrite_summaries = []

    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        self.rewrite_summaries.append(rewrite_summary)
        if self._fails > 0:
            self._fails -= 1
            return None
        return self._plan


class ReviewFixTests(unittest.TestCase):
    """Regression tests for the adversarially-confirmed findings on the rewrite feature."""

    def test_session_key_skips_env_preamble(self):
        # Keying on a stable harness preamble collided every conversation in a repo onto ONE
        # task: key (false rewrites + briefing leakage). The fallback must key on the same
        # message _history_root fingerprints — the first REAL user message.
        env = {"role": "user", "content": "<environment_context><cwd>/repo</cwd></environment_context>"}
        a = session_key(None, [env, {"role": "user", "content": "task A"}])
        b = session_key(None, [env, {"role": "user", "content": "task B"}])
        self.assertNotEqual(a, b)                                        # different tasks → different keys
        self.assertEqual(a, session_key(None, [env, {"role": "user", "content": "task A"},
                                                {"role": "assistant", "content": "ok"}]))  # stable per convo

    def test_task_keyed_sessions_never_rewrite_or_store_briefings(self):
        # task: keys derive from the root — rewrite detection is meaningless and a briefing under
        # a task-text hash would resurrect for unrelated same-prompt conversations. Both gated.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        coder = _Scripted([_toolcall(), _done()])
        reasoner = _Scripted([_verdict(True), _summary("BRIEFING")])
        loop = Loop(_ctx(coder, reasoner, _plan(1)), store)
        C = _Classification()
        c1 = loop.drive(_body(), "task:abc123", C, _Rlog())
        c2 = loop.drive(_body(), "task:abc123", C, _Rlog())
        final = loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "task:abc123", C, _Rlog())  # → loop.done
        from cria.loop import BRIEFING_OPEN
        self.assertIn(BRIEFING_OPEN, final["choices"][0]["message"]["content"])  # briefing still rides the convo
        self.assertFalse(store.shape_done("task:abc123"))               # …but NO server-side marker/shape
        rlog = _Rlog()
        loop.drive(_body_rewritten(), "task:abc123", C, rlog)           # root changed under the key
        self.assertNotIn("loop.history_rewritten", rlog.kinds())        # detection gated off

    def test_question_with_distinct_new_ask_is_not_hijacked(self):
        # Briefing + rewrite, but the user typed a NEW question after the compaction (latest text
        # != compacted root). The classifier judged real user text — respect it: proxy, don't plan.
        from cria.loop import Loop, LoopStore
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_verdict()]), _plan(1)), store)
        loop.drive(_body(), "sid:h", _Classification(), _Rlog())        # original task (shape recorded)
        store.drop("sid:h")
        store.mark_done("sid:h")
        body = {"messages": [{"role": "user", "content": "SUMMARY OF PRIOR WORK"},
                             {"role": "user", "content": "what does handler.py do?"}],
                "tools": [_SHELL], "stream": True}
        self.assertIsNone(loop.drive(body, "sid:h", _Question(), _Rlog()))  # proxied, not hijacked
        self.assertIsNone(store.get("sid:h"))                           # no phantom plan started

    def test_rewrite_signal_sticky_across_a_failed_plan_attempt(self):
        # The planner failing on the rewrite turn must not consume the one-shot signal — the next
        # turn still plans the continuation.
        from cria.loop import Loop, LoopContext, LoopStore
        store = LoopStore()
        planner = _FlakyPlanner(_plan(1), fail_first=1)
        ctx = LoopContext(planner=planner, coder_chat=_Scripted([_toolcall()]),
                          reasoner_chat=_Scripted([_verdict()]), runs_dir="")
        loop = Loop(ctx, store)
        store.observe_shape("sid:s", "originalroot", 3)                  # session known at the original root
        store.mark_done("sid:s")
        self.assertIsNone(loop.drive(_body_rewritten(), "sid:s", _Question(), _Rlog()))  # attempt 1: planner fails
        out = loop.drive(_body_rewritten(), "sid:s", _Question(), _Rlog())               # attempt 2: still rewritten
        self.assertIsNotNone(out)                                        # sticky signal → continuation planned
        self.assertTrue(planner.rewrite_summaries[-1])                   # via the rewrite frame

    def test_probe_reissue_is_capped(self):
        # A harness compacting EVERY turn can't wedge the loop in endless probe re-issues.
        from cria.loop import Loop, LoopStore, MAX_PROBE_REISSUES
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict(True), _summary("s")]), _plan(1)), store)
        loop.drive(_body(), "sid:p", _Classification(), _Rlog())         # coder done → probe emitted
        reissues = 0
        for i in range(MAX_PROBE_REISSUES + 2):                          # every turn arrives root-rewritten, result-less
            rlog = _Rlog()
            loop.drive(_body_rewritten(f"summary v{i}"), "sid:p", _Classification(), rlog)
            if "loop.probe_reissued" in rlog.kinds():
                reissues += 1
            else:
                break
        self.assertEqual(reissues, MAX_PROBE_REISSUES)                   # capped, then falls back to judgment

    def test_shape_eviction_refreshes_on_reobserve(self):
        from cria.loop import LoopStore, _MAX_SHAPES
        s = LoopStore()
        s.observe_shape("sid:active", "fp", 2)
        s.mark_done("sid:active")
        for i in range(_MAX_SHAPES - 1):
            s.observe_shape(f"sid:e{i}", "x", 1)
        s.observe_shape("sid:active", "fp", 9)                           # re-observe refreshes recency
        s.observe_shape("sid:new", "y", 1)                               # evicts the OLDEST, not the active one
        self.assertTrue(s.shape_done("sid:active"))

    def test_load_tolerates_garbage_state_files(self):
        import tempfile, os
        from cria.loop import LoopStore
        for garbage in ("null", "[]", '"a string"', '{"completed": [1,2], "shapes": "nope"}',
                        '{"completed": {"k": 5}, "shapes": {"k": {"fp": 7}}}'):
            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "loopstate.json")
                with open(p, "w") as f:
                    f.write(garbage)
                s = LoopStore(state_path=p)                              # must not raise
                self.assertFalse(s.shape_done("k"))
                self.assertFalse(s.knows("k"))


class GateFlowTests(unittest.TestCase):
    """The ported completion gate driven THROUGH the loop: floor/probe failures block with
    exact errors (critic never consulted); a clean gate hands the critic the digest."""

    def _ws(self):
        import tempfile, os
        t = tempfile.mkdtemp()
        with open(os.path.join(t, "x.py"), "w") as f:
            f.write("print(1)\n")
        with open(os.path.join(t, "pyproject.toml"), "w") as f:
            f.write("[tool.pytest.ini_options]\n")
        return t

    def _gate_result(self, floor_exit=0, probe_body=None):
        # Unified design: sections are probe-<i> in candidate order. The _ws fixture has both a .py
        # and a pyproject.toml, so the order is [compileall(SyntaxCheck), TOML(SyntaxCheck),
        # pyflakes(Lint), pytest(Test)].
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        parts = [f"{P}probe-0{S}",
                 "EXIT:0" if floor_exit == 0 else '  File "x.py", line 3\nSyntaxError: bad\nEXIT:1',
                 f"{P}probe-1{S}", "EXIT:0",   # TOML floor (pyproject.toml present)
                 f"{P}probe-2{S}", "EXIT:0"]   # pyflakes
        if probe_body is not None:
            parts += [f"{P}probe-3{S}", probe_body]   # pytest
        parts += [f"{P}git{S}", "abc"]
        return "\n".join(parts)

    def test_floor_failure_blocks_without_critic(self):
        ws = self._ws()
        coder = _Recorder([_toolcall(), _done(), _toolcall()])
        reasoner = _Scripted([_verdict(True)])   # would pass — must NOT be reached
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)          # act
        c2 = loop.drive(_body(), "k", _Classification(), rlog)     # done → GATE
        c3 = loop.drive(_body_with_probe(_tc_id(c2), self._gate_result(floor_exit=1)),
                        "k", _Classification(), rlog)
        self.assertTrue(c3["choices"][0]["message"].get("tool_calls"))   # coder re-driven
        self.assertIn("loop.gate", rlog.kinds())                          # truth capture
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertEqual(reasoner.calls, 0, "a failing floor short-circuits — no critic")
        # the coder's nudge carries the EXACT error
        self.assertIn("SyntaxError", coder.last_user())

    def test_failing_test_probe_blocks_without_critic(self):
        ws = self._ws()
        coder = _Recorder([_toolcall(), _done(), _toolcall()])
        reasoner = _Scripted([_verdict(True)])
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)
        c2 = loop.drive(_body(), "k", _Classification(), rlog)
        c3 = loop.drive(_body_with_probe(_tc_id(c2), self._gate_result(
            probe_body="FAILED tests/test_x.py::t - AssertionError: boom\n1 failed\nEXIT:1")),
            "k", _Classification(), rlog)
        self.assertTrue(c3["choices"][0]["message"].get("tool_calls"))
        self.assertEqual(reasoner.calls, 0, "failing tests short-circuit — no critic")
        self.assertIn("tests/test_x.py", coder.last_user())

    def test_clean_gate_hands_critic_the_digest(self):
        ws = self._ws()
        captured = {}

        class _R:
            calls = 0
            def __call__(self, body, rlog):
                _R.calls += 1
                captured.setdefault("user", body["messages"][-1]["content"])
                return json.dumps(_verdict(True)).encode()

        coder = _Scripted([_toolcall(), _done()])
        loop = Loop(_ctx(coder, _R(), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)
        c2 = loop.drive(_body(), "k", _Classification(), rlog)
        final = loop.drive(_body_with_probe(_tc_id(c2), self._gate_result(
            probe_body="3 passed\nEXIT:0")), "k", _Classification(), rlog)
        self.assertIn("plan complete", final["choices"][0]["message"]["content"])
        self.assertIn("exit 0 (ran clean)", captured["user"])   # digest reached the critic
        gate_events = [kw for k, kw in rlog.events if k == "loop.gate"]
        self.assertTrue(gate_events and gate_events[0]["floor_clean"] and not gate_events[0]["blocked"])

    def test_stalled_gate_is_logged_not_accepted(self):
        ws = self._ws()
        coder = _Scripted([_toolcall(), _done()])   # keeps claiming done, never fixes
        reasoner = _Scripted([_verdict(True)])
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)
        c = loop.drive(_body(), "k", _Classification(), rlog)
        same = self._gate_result(floor_exit=1)
        c = loop.drive(_body_with_probe(_tc_id(c), same), "k", _Classification(), rlog)
        c = loop.drive(_body_with_probe(_tc_id(c), same), "k", _Classification(), rlog)
        self.assertIn("loop.gate_stalled", rlog.kinds())        # stall is LOUD...
        self.assertNotIn("loop.step_done", rlog.kinds())        # ...but never auto-accepted (no-cap)


def _write(path="handler.py", content="x = 1"):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "w", "type": "function", "function": {"name": "write_file",
         "arguments": json.dumps({"path": path, "content": content})}}]}}]}


def _shell_cmd(cmd):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "t", "type": "function", "function": {"name": "shell",
         "arguments": json.dumps({"command": ["bash", "-lc", cmd]})}}]}}]}


def _edit(path, old, new):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "e", "type": "function", "function": {"name": "edit_file",
         "arguments": json.dumps({"path": path, "old_string": old, "new_string": new})}}]}}]}


class _VaryingWriter:
    """Rewrites the same file with DIFFERENT content each turn — trips the wheel-spin
    same-file streak without tripping the repetition guard (new content = progress)."""

    def __init__(self, path="handler.py"):
        self._path = path
        self._n = 0
        self.bodies = []

    def __call__(self, body, rlog):
        self.bodies.append(body)
        self._n += 1
        return json.dumps(_write(self._path, f"x = {self._n}")).encode()

    def last_user(self):
        return self.bodies[-1]["messages"][-1]["content"]


class ProbeReissueTests(unittest.TestCase):
    _SHELL = {"tools": [{"type": "function", "function": {"name": "shell",
              "parameters": {"properties": {"command": {"type": "array"}}}}}], "messages": []}

    def test_reissues_when_result_lost_to_compaction(self):
        from cria.loop import GuardState, guard_probe_reissue
        gs = GuardState(awaiting_probe=True, probe_call_id="p1")   # result missing
        out = guard_probe_reissue(gs, self._SHELL, _Rlog(), rewritten=True)
        self.assertIsNotNone(out)                                 # re-issued, not failed-open
        self.assertEqual(gs.probe_reissues, 1)

    def test_no_reissue_when_result_present_streak_reset(self):
        from cria.loop import GuardState, guard_probe_reissue
        body = {"tools": self._SHELL["tools"], "messages": [{"role": "tool", "tool_call_id": "p1", "content": "EXIT:0"}]}
        gs = GuardState(awaiting_probe=True, probe_call_id="p1", probe_reissues=1)
        self.assertIsNone(guard_probe_reissue(gs, body, _Rlog(), rewritten=True))
        self.assertEqual(gs.probe_reissues, 0)

    def test_no_reissue_without_compaction_or_when_nothing_pending(self):
        from cria.loop import GuardState, guard_probe_reissue
        self.assertIsNone(guard_probe_reissue(GuardState(awaiting_probe=True, probe_call_id="p1"), self._SHELL, _Rlog(), rewritten=False))
        self.assertIsNone(guard_probe_reissue(GuardState(), self._SHELL, _Rlog(), rewritten=True))  # nothing pending


class SharedSummarizeTests(unittest.TestCase):
    def test_two_pass_retry_reasoning_off_when_first_is_empty(self):
        from cria.loop import summarize
        calls = []

        def chat(body, rlog):
            calls.append(body)
            # first pass (reasoning as configured) → empty; second (forced off) → text
            off = (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False
            content = "THE SUMMARY" if off else ""
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

        out = summarize(chat, None, "sys", "user", _Rlog(), phase="t")
        self.assertEqual(out, "THE SUMMARY")
        self.assertEqual(len(calls), 2)                       # retried with reasoning off

    def test_single_pass_when_retry_off_false(self):
        from cria.loop import summarize
        calls = []
        chat = lambda b, r: (calls.append(1), b"".join([b'{"choices":[{"message":{"content":""}}]}']))[1]
        self.assertEqual(summarize(chat, None, "s", "u", _Rlog(), retry_off=False), "")
        self.assertEqual(len(calls), 1)

    def test_leaked_tool_call_first_pass_is_discarded_and_retried(self):
        # A non-empty but MANGLED tool-call leak (`<|tool_call>call:Gemma4__…`) must NOT become the
        # summary — it's failed like an empty pass so the reasoning-off retry produces real prose.
        from cria.loop import summarize
        calls = []

        def chat(body, rlog):
            calls.append(body)
            off = (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False
            content = "A real briefing." if off else "<|tool_call>call:Gemma4__1025 abcd0000 hex"
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

        out = summarize(chat, None, "sys", "user", _Rlog(), phase="t")
        self.assertEqual(out, "A real briefing.")
        self.assertEqual(len(calls), 2)                       # garbage first pass triggered the retry

    def test_leak_on_both_passes_returns_empty(self):
        # If both passes leak, summarize returns "" — the caller's own fallback briefing applies,
        # never a wall of tool-call sentinels.
        from cria.loop import summarize
        chat = lambda b, r: json.dumps(
            {"choices": [{"message": {"content": "<|tool_call>call:X{<|\"|>y<|\"|>}"}}]}).encode()
        self.assertEqual(summarize(chat, None, "s", "u", _Rlog(), phase="t"), "")

    def test_tool_call_answer_recovers_plan_is_discarded_and_retried(self):
        # THE 6/6 compactor failure: the model answers a SUMMARIZE call with a leaked tool call, whose
        # recovered reasoning is a forward PLAN, not a retrospective. has_tool_call_leak passes (clean
        # plan-prose), so the answered-with-a-tool-call check must catch it and force the reasoning-off
        # retry, which produces a real summary in content.
        from cria.loop import summarize
        calls = []

        def chat(body, rlog):
            calls.append(body)
            off = (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False
            if off:
                return json.dumps({"choices": [{"message": {
                    "content": "Built the resolver; the live test fails on a 404."}}]}).encode()
            # reasoning-on pass: a leaked tool call whose reasoning is forward planning
            return json.dumps({"choices": [{"message": {
                "content": "<|tool_call>call:Read{file_path:<|\"|>spec.json<|\"|>}<tool_call|>",
                "reasoning_content": "Plan: 1. Read the OpenAPI spec. 2. Write resolve_handle."}}]}).encode()

        out = summarize(chat, None, "summarize past work", "transcript", _Rlog(), phase="t")
        self.assertEqual(out, "Built the resolver; the live test fails on a 404.")
        self.assertEqual(len(calls), 2)   # the plan-recovered pass was discarded and retried off


class LoopSelfCompactTests(unittest.TestCase):
    def test_loop_rolls_up_a_big_coder_view(self):
        from cria.loop import Loop, PlanSession
        from dataclasses import replace
        reasoner_calls = []

        def reasoner(body, rlog):
            reasoner_calls.append(body)
            return json.dumps({"choices": [{"message": {"content": "ROLLUP"}}]}).encode()

        ctx = replace(_ctx(coder=None, reasoner=reasoner), trigger_compaction=100)  # low trigger
        loop = Loop(ctx)
        sess = PlanSession(plan=_plan(1))
        # total must exceed the 6000-token default tail so there's a middle to roll up (~50 * 250 tok)
        big = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(50)]
        out = loop._self_compact(big, sess, 1, _Rlog())
        self.assertLess(len(out), len(big))                                   # compacted
        self.assertEqual(len(reasoner_calls), 1)                              # via the shared summarizer
        self.assertTrue(any("⟦cria:rollup⟧" in str(m.get("content")) for m in out))


class PeriodicGateTests(unittest.TestCase):
    _SHELL = {"tools": [{"type": "function", "function": {"name": "shell",
              "parameters": {"properties": {"command": {"type": "array"}}}}}], "messages": []}

    def test_fires_only_at_the_cadence_and_resets(self):
        from cria.loop import GuardState, guard_periodic_gate, GATE_EVERY_CODER_TURNS
        self.assertIsNone(guard_periodic_gate(GuardState(coder_turns=GATE_EVERY_CODER_TURNS - 1), self._SHELL, _Rlog()))
        gs = GuardState(coder_turns=GATE_EVERY_CODER_TURNS)
        self.assertIsNotNone(guard_periodic_gate(gs, self._SHELL, _Rlog()))  # a probe is emitted
        self.assertTrue(gs.periodic_probe)
        self.assertEqual(gs.coder_turns, 0)                                  # counter reset

    def test_result_inserts_the_ground_truth_findings(self):
        import tempfile, os
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        from cria.loop import GuardState, guard_periodic_gate, guard_periodic_result
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "x.py"), "w") as f:
            f.write("print(1)\n")                              # a .py → probe-0 is the compile floor
        gs = GuardState(coder_turns=15)
        guard_periodic_gate(gs, self._SHELL, _Rlog(), workspace_root=ws)   # arms a real gate
        result = f'{P}probe-0{S}\n  File "x.py", line 1\nSyntaxError: bad\nEXIT:1\n{P}git{S}\nabc\n'
        body = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id, "content": result}]}
        truth = guard_periodic_result(gs, body, _Rlog())
        self.assertIsNotNone(truth)
        self.assertIn("SyntaxError", truth)                    # the failing check reaches the model
        self.assertFalse(gs.periodic_probe)                    # consumed


class ShellWritePathTests(unittest.TestCase):
    def test_shell_native_write_yields_a_path(self):
        from cria.loop import _write_path
        self.assertEqual(_write_path({"name": "shell", "arguments": '{"command":["bash","-lc","echo x > handler.py"]}'}), "handler.py")
        self.assertEqual(_write_path({"name": "exec_command", "arguments": '{"cmd":"cat > a/b.py <<EOF\\nx\\nEOF"}'}), "a/b.py")
        self.assertEqual(_write_path({"name": "shell", "arguments": '{"command":["bash","-lc","pytest -q | tee out.log"]}'}), "out.log")

    def test_shell_reads_and_redirect_to_devnull_are_not_writes(self):
        from cria.loop import _write_path
        self.assertIsNone(_write_path({"name": "shell", "arguments": '{"command":["bash","-lc","cat handler.py"]}'}))
        self.assertIsNone(_write_path({"name": "shell", "arguments": '{"command":["bash","-lc","pytest -q 2>/dev/null"]}'}))
        self.assertIsNone(_write_path({"name": "shell", "arguments": '{"command":["bash","-lc","echo \\"a > b\\""]}'}))  # `>` inside a quote

    def test_write_class_predicate_is_unified(self):
        # write_stdin is NOT a file write (the old loose regex mis-classed it); named write tools are.
        from cria.loop import _is_write_tool
        self.assertFalse(_is_write_tool("write_stdin"))
        self.assertTrue(_is_write_tool("write_file"))
        self.assertTrue(_is_write_tool("edit_file"))


class WheelSpinTests(unittest.TestCase):
    """Trigger 2: the same file written WHEEL_SPIN_WRITES times — any content — within the
    last REPEAT_WINDOW forwarded calls → cria runs the gate mid-work and INSERTS the results
    into the coder's next turn. No judging. (Byte-identical rewrites trip the stricter 3×
    repetition redirect first; this is the varying-content tier.)"""

    def _ws(self):
        import tempfile, os
        t = tempfile.mkdtemp()
        with open(os.path.join(t, "x.py"), "w") as f:
            f.write("print(1)\n")
        return t

    def test_five_rewrites_trigger_a_spin_probe_and_insert_results(self):
        from cria.loop import WHEEL_SPIN_WRITES
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        coder = _VaryingWriter()                   # rewrites handler.py forever (content varies)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        c = None
        for _ in range(WHEEL_SPIN_WRITES):         # five forwarded writes, one per turn
            c = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())
        # the write itself was still forwarded (never blocked)
        self.assertEqual(c["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "write_file")
        # NEXT turn: the gate fires instead of the coder
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        args = json.loads(gate["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertIn(P.rstrip("_"), " ".join(args["command"]))
        self.assertIn("loop.spin_probe", rlog.kinds())
        # gate result: failing checks → findings INSERTED into the coder's next turn
        result = (f"{P}probe-0{S}\n  File \"x.py\", line 3\nSyntaxError: bad\nEXIT:1\n"
                  f"{P}git{S}\nabc\n")
        nxt = loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertIn("rewritten `handler.py`", coder.last_user())
        self.assertIn("SyntaxError", coder.last_user())
        self.assertNotIn("loop.step_done", rlog.kinds())   # inserted, never judged
        self.assertIn("loop.spin_probe_result", rlog.kinds())

    def test_probe_steer_labels_which_guard_fired(self):
        # The ⟦cria⟧ note must say WHICH guard steered the coder, not just "a guard" — so a
        # wheel-spin steer and a repetition redirect are distinguishable in the scrollback.
        from cria.loop import GuardState, guard_probe_steer
        rlog = _Rlog()
        # wheel-spin probe resolving → labels "wheel-spin guard"
        gs = GuardState(spin_probe=True, probe_call_id="p1", spin_path="x.py")
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "EXIT:0"}]}
        self.assertIsNotNone(guard_probe_steer(gs, body, rlog))
        self.assertEqual(gs.steer_source, "wheel-spin guard")
        # repetition redirect resolving (canned, no author) → labels "repetition guard"
        gs2 = GuardState(redirect_probe=True, probe_call_id="p2", repeat_action="write_file(h.py)")
        body2 = {"messages": [{"role": "tool", "tool_call_id": "p2", "content": "EXIT:0"}]}
        steer = guard_probe_steer(gs2, body2, rlog)
        self.assertIn("[REDIRECT]", steer)
        self.assertEqual(gs2.steer_source, "repetition guard")

    def test_clean_checks_report_the_pass_without_editorializing(self):
        # Round-6: the clean-gate message must NOT claim "the problem is elsewhere" — a
        # content-blind streak can't distinguish a spiral from an honest sequence of edits to
        # one file (applying review findings one by one). It states the checks pass, no more.
        from cria.loop import WHEEL_SPIN_WRITES
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        coder = _VaryingWriter()
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(WHEEL_SPIN_WRITES):
            loop.drive(_body(), "k", _Classification(), rlog)
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        msg = coder.last_user()
        self.assertIn("no error-class", msg.lower())      # states the clean fact...
        self.assertNotIn("all pass", msg.lower())         # ...without overclaiming a verified/done state
        self.assertNotIn("NOT in the file", msg)          # no false "look elsewhere" steer
        self.assertNotIn("elsewhere", msg)

    def test_other_file_writes_do_not_shield_the_count(self):
        # WINDOWED (operator, 2026-07-12), not consecutive: the tiny-edit spiral interleaves
        # other work — 5 writes to a.py within the window fire even with b.py written between.
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        writes = ([_write("a.py", f"v = {i}") for i in range(WHEEL_SPIN_WRITES - 1)]
                  + [_write("b.py")] + [_write("a.py", "back")])
        coder = _Recorder(writes)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(writes)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())     # 4×a, b, a → 5×a within 6 calls

    def test_edit_file_spiral_counts_toward_wheel_spin(self):
        # The tiny-edit route: the writeproxy lowers edit_file → apply_patch BEFORE tracking,
        # so the patch target must count as a write to that file. (The old greedy patch-tail
        # regex made every edit look like a different garbage path — the trigger's own target
        # pathology, tiny varying edits, was invisible on this route.)
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        edits = [_edit("h.py", f"x = {i}", f"x = {i + 1}") for i in range(WHEEL_SPIN_WRITES)]
        coder = _Recorder(edits)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(WHEEL_SPIN_WRITES):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())
        self.assertNotIn("loop.repetition", rlog.kinds())  # contents vary — the identical tier stays silent

    def test_canonical_tiny_edit_spiral_fires(self):
        # Round-5 verify: THE incident shape — edit → cat → pytest, repeated. Five edits at
        # 3-call interleave span 13 calls; the old 12-call window missed it by exactly one,
        # permanently. WRITE_WINDOW (five full cycles) must catch it.
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        seq = []
        for i in range(WHEEL_SPIN_WRITES):
            seq.append(_edit("handler.py", f"x = {i}", f"x = {i + 1}"))  # lowered to apply_patch
            seq.append(_shell_cmd("cat handler.py"))
            seq.append(_shell_cmd("pytest -q"))
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq) - 2):                       # through the 5th edit
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())
        self.assertNotIn("loop.repetition", rlog.kinds())   # varying edits purge the act hunt

    def test_create_file_spiral_counts_toward_wheel_spin(self):
        # Round-5 verify: create_file is a write for the writeproxy — it must be one for the
        # spin tracker too (a varying-content create_file spiral was invisible to BOTH tiers).
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        def _create(i):
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "create_file",
                 "arguments": json.dumps({"path": "handler.py", "content": f"v = {i}"})}}]}}]}
        coder = _Recorder([_create(i) for i in range(WHEEL_SPIN_WRITES)])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(WHEEL_SPIN_WRITES):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())

    def test_writes_spread_past_the_window_do_not_fire(self):
        # The window is the last REPEAT_WINDOW forwarded CALLS: a file revisited occasionally
        # across a long stretch of real work never accrues 5 in-window writes.
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        seq = []
        for i in range(WHEEL_SPIN_WRITES):
            seq.append(_write("a.py", f"v = {i}"))
            seq.extend(_shell_cmd(f"cat part_{i}_{j}.py") for j in range(3))  # distinct actions
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.wheel_spinning", rlog.kinds())  # ≤3 a.py writes in any 12-call span
        # ...and the distinct cat reads never false-fire repetition (which would consume drives
        # on gate turns and desync this fixture — the vacuous-pass the verify pass caught)
        self.assertNotIn("loop.repetition", rlog.kinds())

    def test_interleaved_non_write_calls_do_not_break_the_streak(self):
        from cria.loop import WHEEL_SPIN_WRITES
        ws = self._ws()
        seq = []
        for i in range(WHEEL_SPIN_WRITES):
            seq.append(_write("h.py", f"v = {i}"))   # varying content — streak, not repetition
            # IDENTICAL test commands between real edits: each new-content write is progress
            # and resets the repetition hunt, so the healthy cycle only trips the (weaker,
            # same-file) wheel-spin streak — never the repetition redirect.
            seq.append(_shell_cmd("pytest -q"))
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq) - 1):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.wheel_spinning", rlog.kinds())
        self.assertNotIn("loop.repetition", rlog.kinds())


class RunFolderTests(unittest.TestCase):
    def test_plan_and_verify_land_in_the_capture_session_folder(self):
        # ONE folder per run: <runs_dir>/<session>/ holds plan-<id>.md + verify-*.md — the
        # same folder (same session id) the call captures use.
        import tempfile, os
        tmp = tempfile.mkdtemp()

        class _SessRlog(_Rlog):
            session = "019fabcd-1234"

        ctx = LoopContext(planner=_Planner(_plan(1)), coder_chat=_Scripted([_toolcall(), _done()]),
                          reasoner_chat=_Scripted([_verdict(True), _summary("s")]),
                          runs_dir=tmp)
        loop = Loop(ctx)
        rlog = _SessRlog()
        loop.drive(_body(), "k", _Classification(), rlog)                      # plan persisted
        c2 = loop.drive(_body(), "k", _Classification(), rlog)                 # done → gate
        loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "k", _Classification(), rlog)  # critic ran
        run = os.path.join(tmp, "019fabcd-1234")
        names = sorted(os.listdir(run))
        self.assertTrue(any(n.startswith("plan-") and n.endswith(".md") for n in names), names)
        self.assertTrue(any(n.startswith("verify-step-") for n in names), names)


class ResumeTests(unittest.TestCase):
    def test_restart_mid_plan_resumes_instead_of_replanning(self):
        # The restart-amnesia bug: cria restarted mid-plan → fresh blind plan → new filenames →
        # duplicate files. Now: a new Loop over the SAME state file resumes the plan at the
        # current step; the planner is never consulted.
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "loopstate.json")
            store1 = LoopStore(state_path=state)
            loop1 = Loop(_ctx(_Scripted([_toolcall(), _done()]), _Scripted([_verdict(True)]), _plan(2)), store1)
            C = _Classification()
            loop1.drive(_body(), "sid:r", C, _Rlog())                    # step 1: coder acts
            c2 = loop1.drive(_body(), "sid:r", C, _Rlog())               # done → gate
            loop1.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "sid:r", C, _Rlog())  # step 1 done → step 2

            # "restart": fresh store from the same file, fresh Loop with a planner that MUST not run
            class _NoPlanner:
                def plan_for(self, *a, **k):
                    raise AssertionError("re-planned after restart — resume failed")
            store2 = LoopStore(state_path=state)
            ctx2 = LoopContext(planner=_NoPlanner(), coder_chat=_Recorder([_toolcall()]),
                               reasoner_chat=_Scripted([_verdict(True)]), runs_dir="")
            loop2 = Loop(ctx2, store2)
            rlog = _Rlog()
            out = loop2.drive(_body(), "sid:r", C, rlog)                 # resumes: drives step 2
            self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
            items = [kw for k, kw in rlog.events if k == "loop.item"]
            self.assertEqual(items[0]["step"], 2)                        # picked up at step 2, not step 1


class RepetitionRedirectTests(unittest.TestCase):
    """Trigger 3: the SAME tool call (name+args) 3x within the window → gate for ground truth →
    the REASONER authors the redirect → delivered as the coder's next nudge."""

    def _ws(self):
        import tempfile, os
        t = tempfile.mkdtemp()
        with open(os.path.join(t, "x.py"), "w") as f:
            f.write("print(1)\n")
        return t

    def test_identical_calls_trip_redirect_and_reasoner_authors_it(self):
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        captured = {}

        class _Reasoner:
            calls = 0
            def __call__(self, body, rlog):
                _Reasoner.calls += 1
                captured.setdefault("user", body["messages"][-1]["content"])
                return json.dumps({"choices": [{"message": {"role": "assistant", "content":
                    "Stop rewriting test_handle.py — the mock target is wrong. Patch handler.requests instead."}}]}).encode()

        coder = _Recorder([_write("h.py", "same bytes")])   # IDENTICAL write forever
        loop = Loop(_ctx(coder, _Reasoner(), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        c = None
        for _ in range(3):                                  # 3 identical forwarded writes
            c = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())
        # next turn: the gate fires for ground truth
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.redirect_probe", rlog.kinds())
        args = json.loads(gate["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertIn(P.rstrip("_"), " ".join(args["command"]))
        # gate result (failing floor) → reasoner authors the redirect → coder is re-driven with it
        result = f'{P}probe-0{S}\n  File "x.py", line 3\nSyntaxError: bad\nEXIT:1\n{P}git{S}\nabc\n'
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertIn("loop.redirect", rlog.kinds())
        self.assertIn("[REDIRECT]", coder.last_user())
        self.assertIn("Patch handler.requests", coder.last_user())   # the reasoner's words
        # ...and the reasoner SAW the evidence: step, repeated action, ground truth
        self.assertIn("THE ACTION IT KEEPS REPEATING", captured["user"])
        self.assertIn("write_file", captured["user"])
        self.assertIn("SyntaxError", captured["user"])

    def test_redirect_prompt_does_not_order_a_look_elsewhere_steer(self):
        # Round-7: de-editorializing the code-side fact was nullified because redirect.txt
        # (the reasoner's SYSTEM prompt) still ordered "say the problem is NOT in the file".
        # The prompt must not instruct any where-the-problem-is claim on a clean gate.
        from cria import prompts
        txt = prompts.load("redirect").lower()
        self.assertNotIn("not in the file", txt)
        self.assertNotIn("look elsewhere", txt)

    def test_reasoner_sees_neutral_system_and_fact_on_clean_gate(self):
        # The reasoner's inputs on a clean gate carry no "problem is elsewhere" premise, in
        # EITHER the system prompt or the ground-truth fact.
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        seen = {}

        class _Recorder2:
            def __call__(self, body, rlog):
                msgs = body["messages"]
                seen["system"] = next(m["content"] for m in msgs if m["role"] == "system")
                seen["user"] = msgs[-1]["content"]
                return json.dumps({"choices": [{"message": {"role": "assistant",
                        "content": "Different next step."}}]}).encode()

        coder = _Recorder([_write("h.py", "same bytes")])
        loop = Loop(_ctx(coder, _Recorder2(), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        for blob in (seen["system"].lower(), seen["user"].lower()):
            self.assertNotIn("not in the file", blob)
            self.assertNotIn("look elsewhere", blob)
        self.assertIn("no error-class", seen["user"].lower())   # the neutral clean fact

    def test_reasoner_failure_falls_back_to_canned_redirect(self):
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        coder = _Recorder([_write("h.py", "same bytes")])
        reasoner = _Scripted([{"choices": [{"message": {"role": "assistant", "content": ""}}]}])  # empty forever
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertIn("[REDIRECT]", coder.last_user())
        self.assertIn("very similar actions", coder.last_user())  # canned fallback
        self.assertIn("no error-class", coder.last_user().lower())    # clean-checks truth included

    def test_canned_redirect_foregrounds_the_failing_check(self):
        # #2: when the gate FAILS, the concrete error must LEAD the redirect (a small model reads
        # past a trailing ground-truth block and rewrites the whole file again).
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        coder = _Recorder([_write("h.py", "same bytes")])
        reasoner = _Scripted([{"choices": [{"message": {"role": "assistant", "content": ""}}]}])  # empty → canned
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f'{P}probe-0{S}\n  File "h.py", line 1\nSyntaxError: bad\nEXIT:1\n{P}git{S}\nabc\n'
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        nudge = coder.last_user()
        self.assertIn("GROUND TRUTH", nudge)                              # the failing check is present
        self.assertIn("very similar actions", nudge)                 # and so is the repetition framing
        # the ground truth LEADS — it comes before the 'you repeated' text, not buried after it
        self.assertLess(nudge.index("GROUND TRUTH"), nudge.index("very similar actions"))

    def test_varying_args_do_not_trip(self):
        ws = self._ws()
        coder = _VaryingWriter("h.py")                      # same file, different bytes each time
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())

    def test_flag_jitter_still_trips_by_nature(self):
        # The codex-local lesson: the model jitters one flag/word without changing what it's
        # doing. Exact fingerprints missed this; nature-matching (normalized word-sets) must not.
        ws = self._ws()
        coder = _Recorder([_shell_cmd("pytest -q"),
                           _shell_cmd("pytest -q --tb=short"),   # same hunt, jittered flag
                           _shell_cmd("pytest -q")])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())

    def test_reads_of_different_files_do_not_trip(self):
        # Wrapper boilerplate (bash -lc) must not count as shared intent: three reads of three
        # DIFFERENT files share only {cat} once it's stripped — that's exploration, not a loop.
        ws = self._ws()
        coder = _Recorder([_shell_cmd("cat a.py"), _shell_cmd("cat b.py"), _shell_cmd("cat c.py")])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())

    def test_identical_reads_still_trip(self):
        # The live incident: "stuck on reading package.json" — the SAME read over and over.
        ws = self._ws()
        coder = _Recorder([_shell_cmd("cat package.json")])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())

    def test_symbol_only_args_match_exact_bytes_only(self):
        # Args that normalize to an EMPTY word-set (symbol-only/non-ASCII commands) must not
        # wildcard-match each other — exact bytes only.
        ws = self._ws()
        coder = _Recorder([_shell_cmd("→"), _shell_cmd("←"), _shell_cmd("↔")])  # three DIFFERENT
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())
        coder2 = _Recorder([_shell_cmd("→")])                     # the SAME one, three times
        loop2 = Loop(_ctx(coder2, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog2 = _Rlog()
        for _ in range(3):
            loop2.drive(_body(), "k", _Classification(), rlog2)
        self.assertIn("loop.repetition", rlog2.kinds())

    def test_parallel_identical_writes_fire_one_redirect_no_spin(self):
        # One completion carrying 5 IDENTICAL write_file calls (parallel tool calls are real):
        # exactly one intervention — the redirect fires and consumes BOTH windows; the spin
        # probe stays silent. Previously both fired, two gates ran back-to-back, and the spin
        # renudge overwrote the reasoner-authored redirect.
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        tc = {"type": "function", "function": {"name": "write_file",
              "arguments": json.dumps({"path": "h.py", "content": "same"})}}
        five = {"choices": [{"message": {"role": "assistant",
                "tool_calls": [dict(tc, id=f"w{i}") for i in range(5)]}}]}
        coder = _Recorder([five])
        reasoner = _Scripted([{"choices": [{"message": {"role": "assistant",
                                            "content": "Try a different approach now."}}]}])
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())
        self.assertNotIn("loop.wheel_spinning", rlog.kinds())
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.redirect_probe", rlog.kinds())
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertNotIn("loop.spin_probe", rlog.kinds())         # no second gate hijack
        self.assertIn("[REDIRECT]", coder.last_user())
        self.assertIn("Try a different approach now.", coder.last_user())

    def test_compliance_write_after_redirect_does_not_trip_spin(self):
        # Round-2 verify: _track_write_streak runs AFTER _track_repetition on the SAME
        # completion — without the in-flight freeze it repopulated the flushed window with the
        # very writes that fired the redirect, and the coder's single compliance write re-tripped
        # a spin probe steering it away from the file it had just fixed.
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        tc = {"type": "function", "function": {"name": "write_file",
              "arguments": json.dumps({"path": "h.py", "content": "same"})}}
        five = {"choices": [{"message": {"role": "assistant",
                "tool_calls": [dict(tc, id=f"w{i}") for i in range(5)]}}]}
        fix = _write("h.py", "the compliant fix")           # ONE new-content write
        coder = _Recorder([five, five, fix])                # five... gate... [gate result → fix]
        reasoner = _Scripted([{"choices": [{"message": {"role": "assistant",
                                            "content": "Fix the mock target instead."}}]}])
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)   # 5 identical writes → repetition
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        loop.drive(_body(), "k", _Classification(), rlog)   # the compliance write is forwarded
        self.assertNotIn("loop.wheel_spinning", rlog.kinds())
        self.assertNotIn("loop.spin_probe", rlog.kinds())

    def test_comparison_operators_are_not_progress(self):
        # `awk '$3 > 100'` / `grep 'n > 0'` are READS: quoted comparisons must not reset the
        # hunt, or a real read-loop interleaved with >-laden diagnostics never trips.
        ws = self._ws()
        seq = []
        for i in range(3):
            seq.append(_shell_cmd("cat src/parser.py"))                    # the stuck read
            seq.append(_shell_cmd(f"awk '$3 > {100 + i}' data_{i}.txt"))   # distinct diagnostics
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(5):                                  # the 3rd identical read is call 5
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())

    def test_dev_null_redirect_is_not_progress(self):
        from cria.loop import _action_signature, _is_progress
        args = json.dumps({"command": ["bash", "-lc", "pytest -q > /dev/null 2>&1"]})
        self.assertFalse(_is_progress(_action_signature("shell", args), args))
        args2 = json.dumps({"command": ["bash", "-lc", "echo done > out.txt"]})
        self.assertTrue(_is_progress(_action_signature("shell", args2), args2))

    def test_prose_sidecar_fields_do_not_corrupt_progress_detection(self):
        # Round-3 verify: one apostrophe in a justification field unbalanced the quote masking.
        # Only COMMAND fields are scanned — prose never hides a real write or fakes one.
        from cria.loop import _action_signature, _is_progress
        read = json.dumps({"command": ["bash", "-lc", "cat a.py"],
                           "justification": "we can't miss Bob's edge > case"})
        self.assertFalse(_is_progress(_action_signature("shell", read), read))
        write = json.dumps({"command": ["bash", "-lc", "echo hi > f.txt"],
                            "justification": "don't skip"})
        self.assertTrue(_is_progress(_action_signature("shell", write), write))

    def test_unparseable_args_still_detect_shell_writes(self):
        # Round-3 verify: a truncated arg blob (invalid JSON, still escape-encoded) must use
        # the raw-tolerant pattern — quote-masking raw JSON would mask the whole command away.
        from cria.loop import _action_signature, _is_progress
        raw = '{"command": ["bash", "-lc", "echo x > f.py"]'   # cut off — invalid JSON
        self.assertTrue(_is_progress(_action_signature("shell", raw), raw))

    def test_decodable_non_dict_args_are_quote_masked(self):
        # Round-4 verify: bare shell text and JSON argv arrays (the shapes leaked-tool-call
        # recovery mints) have REAL balanced quotes — they take the masked path, so quoted
        # comparisons are reads, while their real redirects still count as writes.
        from cria.loop import _action_signature, _is_progress
        for read in ("grep 'count > 1' src/module.py",              # bare shell text
                     '["bash", "-lc", "awk \'$3 > 100\' data.txt"]'):  # JSON argv array
            self.assertFalse(_is_progress(_action_signature("shell", read), read), read)
        for write in ("echo x > f.py",
                      '["bash", "-lc", "echo done > out.txt"]'):
            self.assertTrue(_is_progress(_action_signature("shell", write), write), write)

    def test_shell_command_field_counts_as_command(self):
        # Round-4 verify: _COMMAND_KEYS is derived from shelltool._CMD_FIELDS — a harness
        # whose shell tool uses `shell_command` gets the same progress detection.
        from cria.loop import _action_signature, _is_progress
        args = json.dumps({"shell_command": "echo done > result.txt"})
        self.assertTrue(_is_progress(_action_signature("shell", args), args))

    def test_prose_mutator_words_are_not_progress(self):
        # Round-4 verify: "don't touch the config" in a justification is not a `touch` —
        # mutator words come from the COMMAND text only.
        from cria.loop import _action_signature, _is_progress
        args = json.dumps({"command": "grep -n handler src/module.py",
                           "justification": "checking we don't touch the config"})
        self.assertFalse(_is_progress(_action_signature("shell", args), args))

    def test_script_outranks_input(self):
        # Round-5 verify: script=program, input=stdin — the derivation must not demote script
        # below input (stdin data with a '>' read as a phantom write; a real script write missed).
        from cria.loop import _action_signature, _is_progress
        stdin_read = json.dumps({"script": "sort", "input": "line a\nc > d\nline b"})
        self.assertFalse(_is_progress(_action_signature("run", stdin_read), stdin_read))
        script_write = json.dumps({"script": "generate.sh > reports/out.txt", "input": "dataset-a"})
        self.assertTrue(_is_progress(_action_signature("run", script_write), script_write))

    def test_bracket_leading_shell_text_is_not_a_json_fragment(self):
        # Round-5 verify: `[ -f x ] && …` test-brackets and `{ cmd; }` brace groups are bare
        # shell text (quote-masked path) — only `{"…` / `["…` shapes are cut-off JSON.
        from cria.loop import _action_signature, _is_progress
        for read in ("[ -f x ] && grep 'count > 1' src/module.py",
                     "{ grep 'n > 0' f.py; } | wc -l"):
            self.assertFalse(_is_progress(_action_signature("shell", read), read), read)

    def test_jittered_parameter_sweep_fires(self):
        # Round-6: a version-pin retry loop is "the same nature, one thing jittered" — exactly
        # what the redesign exists to catch. The round-5 file-target veto SILENCED this (it read
        # 1.0.1/1.0.2/1.0.3 as disjoint "files"); removing the veto restores the catch.
        ws = self._ws()
        coder = _Recorder([_shell_cmd("pip install cryptg==1.0.1"),
                           _shell_cmd("pip install cryptg==1.0.2"),
                           _shell_cmd("pip install cryptg==1.0.3")])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())

    def test_survey_with_shared_flag_fires_and_is_reasoner_mediated(self):
        # Round-6 tradeoff (documented): `head -50 a.py/b.py/c.py` share verb+flag and DO fire —
        # the veto that spared this couldn't be made sound without silencing real loops. A
        # survey false-positive is cheap: the gate confirms clean and the reasoner sees the 3
        # distinct files in the evidence. The redirect is delivered, not suppressed.
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        coder = _Recorder([_shell_cmd("head -50 src/a.py"), _shell_cmd("head -50 src/b.py"),
                           _shell_cmd("head -50 src/c.py")])
        reasoner = _Scripted([{"choices": [{"message": {"role": "assistant",
                              "content": "You're surveying different files — nothing is broken, proceed."}}]}])
        loop = Loop(_ctx(coder, reasoner, _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertIn("proceed", coder.last_user())        # the reasoner's benign steer, not a canned scold

    def test_identical_writes_far_apart_age_out(self):
        # Round-3 verify: preserved write signatures must not be immortal — identical writes
        # ~15 calls apart are NOT "3× within the last 12 calls".
        ws = self._ws()
        seq = []
        for burst in range(3):
            seq.append(_write("a.py", "same bytes"))           # the recurring identical write
            for j in range(13):                                # 13 distinct reads age it out
                seq.append(_shell_cmd(f"cat part_{burst}_{j}.py"))
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())

    def test_identical_writes_survive_interleaved_progress(self):
        # The operator's per-file rule: a.py written 3× with the SAME content fires even with
        # productive other-file writes in between (progress resets the ACTION hunt, not the
        # write signatures).
        ws = self._ws()
        seq = [_write("a.py", "same"), _write("b.py", "real work 1"),
               _write("a.py", "same"), _write("c.py", "real work 2"),
               _write("a.py", "same")]
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())

    def test_no_gate_still_delivers_a_canned_steer(self):
        # The gate can't compose (unreadable workspace → _gate_op returns None). The tripped
        # intervention must NEVER be swallowed: the coder's next turn carries the canned
        # redirect as a nudge.
        from unittest import mock
        ws = self._ws()
        coder = _Recorder([_write("h.py", "same bytes")])
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(3):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.repetition", rlog.kinds())
        with mock.patch("cria.loop.probegate.plan_gate", side_effect=OSError("unreadable")):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.redirect", rlog.kinds())        # canned, not silent
        self.assertIn("very similar actions", coder.last_user())

    def test_shell_native_writes_are_progress(self):
        # The coder writes via heredoc/redirect instead of write_file: still progress, so the
        # identical pytest runs between genuinely different shell writes never accrue.
        ws = self._ws()
        bodies = ["import json\ndef parse():\n    return 1",
                  "class Handler:\n    def run(self):\n        pass",
                  "from x import y\nVALUE = 42"]
        seq = []
        for i, b in enumerate(bodies):
            seq.append(_shell_cmd(f"cat > mod_{i}.py <<'EOF'\n{b}\nEOF"))
            seq.append(_shell_cmd("pytest -q"))
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())

    def test_healthy_edit_test_cycle_never_trips(self):
        # write(NEW content) → pytest -q → write(NEW) → pytest -q …: each real edit is progress
        # and resets the hunt, so the identical test runs never accrue. THE false positive the
        # nature redesign exists to prevent.
        ws = self._ws()
        seq = []
        for i in range(4):                                  # 4 writes — under the wheel-spin 5
            seq.append(_write("h.py", f"attempt = {i}"))
            seq.append(_shell_cmd("pytest -q"))
        coder = _Recorder(seq)
        loop = Loop(_ctx(coder, _Scripted([_verdict()]), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(len(seq)):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertNotIn("loop.repetition", rlog.kinds())
        self.assertNotIn("loop.wheel_spinning", rlog.kinds())  # 4 writes — under the threshold


class WritePathTests(unittest.TestCase):
    """_path_of_args: what file does a write-class call target? Bounded extraction — the old
    greedy patch regex swallowed the whole escaped patch body, and rstrip('\\n\"') was a
    CHARACTER-SET strip that mangled real paths (config.json → config.jso)."""

    def test_json_suffix_path_not_mangled(self):
        from cria.loop import _write_path
        fn = {"name": "write_file", "arguments": json.dumps({"path": "config.json", "content": "{}"})}
        self.assertEqual(_write_path(fn), "config.json")

    def test_alias_keys(self):
        from cria.loop import _write_path
        for k in ("path", "file_path", "file", "filename"):
            fn = {"name": "write_file", "arguments": json.dumps({k: "a.py", "content": "x"})}
            self.assertEqual(_write_path(fn), "a.py", k)

    def test_lowered_patch_target(self):
        # the writeproxy's edit_file → apply_patch route: {"input": "*** Begin Patch\n..."}
        from cria.loop import _write_path
        patch = "*** Begin Patch\n*** Update File: handler.py\n-a\n+b\n*** End Patch"
        fn = {"name": "apply_patch", "arguments": json.dumps({"input": patch})}
        self.assertEqual(_write_path(fn), "handler.py")

    def test_raw_escaped_patch_stops_at_newline(self):
        # malformed/truncated JSON: the raw blob has ESCAPED \n — the path must not swallow
        # the patch tail
        from cria.loop import _write_path
        raw = '{"input": "*** Begin Patch\\n*** Update File: handler.py\\n-a\\n+b'
        fn = {"name": "apply_patch", "arguments": raw}
        self.assertEqual(_write_path(fn), "handler.py")

    def test_non_write_tools_return_none(self):
        from cria.loop import _write_path
        self.assertIsNone(_write_path({"name": "shell",
                                       "arguments": json.dumps({"command": ["cat", "a.py"]})}))

    def test_truncated_write_uses_alias_keys(self):
        # a cut-off write with a file_path alias still gets the incremental-write steer
        from cria.loop import _truncated_write_path
        comp = {"choices": [{"message": {"tool_calls": [{"function": {
            "name": "write_file", "arguments": '{"file_path": "big.py", "content": "xxx'}}]}}]}
        self.assertEqual(_truncated_write_path(comp), "big.py")

    def test_patch_header_in_write_file_content_is_not_a_path(self):
        # Round-2 verify: a truncated write_file whose CONTENT contains patch-example text
        # must not yield that example's file — the steer would name a file the model never
        # touched. The patch fallback applies to apply_patch calls only — at BOTH callsites
        # (round 3 caught _truncated_write_path, the truncation steer itself, ungated).
        from cria.loop import _truncated_write_path, _write_path
        raw = '{"content": "How to patch:\\n*** Update File: src/parser.py\\n+fixed line\\nthen run te'
        self.assertIsNone(_write_path({"name": "write_file", "arguments": raw}))
        comp = {"choices": [{"message": {"tool_calls": [{"function": {
            "name": "write_file", "arguments": raw}}]}}]}
        self.assertIsNone(_truncated_write_path(comp))


class _Classification:
    engagement = "task"
    task_type = "coding"
    cached = False


class LoopDriveTests(unittest.TestCase):
    def test_happy_path_two_items(self):
        from cria.probegate import SECTION_PREFIX
        coder = _Scripted([_toolcall(), _done(), _done()])  # work(item0), done(item0), done(item1 twice via leg0)
        reasoner = _Scripted([_verdict(True), _verdict(True)])
        loop = Loop(_ctx(coder, reasoner, _plan(2)))
        rlog = _Rlog()

        # 1: fresh → straight into item 0 (no workspace plan file); coder acts → forward its tool call
        c1 = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertTrue(c1["choices"][0]["message"].get("tool_calls"))
        self.assertIn("loop.start", rlog.kinds())

        # 2: coder claims done → cria emits the GROUND-TRUTH gate (a shell tool call)
        c2 = loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn(SECTION_PREFIX, json.loads(c2["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1])

        # 3: no-marker result → fail-open → critic verifies item 0 → advance → item 1: coder proses,
        #    the no-tools leg nudges once, coder proses again → item 1's gate is emitted
        c3 = loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "k", _Classification(), rlog)
        self.assertIn("loop.step_done", rlog.kinds())
        self.assertIn("loop.probe", rlog.kinds())
        self.assertIn(SECTION_PREFIX, json.loads(c3["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1])

        # 4: gate result → critic verifies item 1 → all steps done → a final answer ends the harness turn
        c4 = loop.drive(_body_with_probe(_tc_id(c3), "PROBE_EXIT=0"), "k", _Classification(), rlog)
        self.assertEqual(c4["choices"][0]["finish_reason"], "stop")
        self.assertIn("plan complete", c4["choices"][0]["message"]["content"])
        self.assertIn("loop.done", rlog.kinds())

    def test_failing_probe_nudges_coder_with_the_error(self):
        # coder claims done → probe FAILS (syntax error) → cria hands the coder the real
        # error and re-drives it — the reasoner critic is never even consulted.
        coder = _Scripted([_done(), _toolcall()])  # done, then a fix action after the nudge
        reasoner = _Scripted([_verdict(True)])       # would say "done" — must NOT be reached
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "k", _Classification(), rlog)  # work → done → PROBE
        c2 = loop.drive(_body_with_probe(_tc_id(c1), "*** Error compiling './h.py'\nSyntaxError: bad\nPROBE_EXIT=1"),
                        "k", _Classification(), rlog)  # probe failed → nudge coder
        self.assertTrue(c2["choices"][0]["message"].get("tool_calls"))  # coder's fix action
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertEqual(reasoner.calls, 0, "a failing probe short-circuits — the critic isn't consulted")

    def test_failing_unit_tests_nudge_coder_and_skip_critic(self):
        # Syntax is fine (PROBE_EXIT=0) but the unit suite is RED (PROBE_TESTS=1) — the
        # qwopus run-7 hole. Ground truth says not-done: hand the coder the pytest output
        # and re-drive it; the critic must NOT be able to mark it done on "files exist".
        coder = _Scripted([_done(), _toolcall()])   # claims done, then fixes after the nudge
        reasoner = _Scripted([_verdict(True)])        # would falsely pass — must NOT be reached
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "k", _Classification(), rlog)                                # work → done → PROBE
        probe_out = ("--- cria unit tests (pytest) ---\n"
                     "FAILED test_handler.py::test_resolve_handle_success - TypeError: not MagicMock\n"
                     "8 failed, 20 passed in 0.3s\nPROBE_EXIT=0 PROBE_TESTS=1")
        c2 = loop.drive(_body_with_probe(_tc_id(c1), probe_out), "k", _Classification(), rlog)  # tests red → nudge
        self.assertTrue(c2["choices"][0]["message"].get("tool_calls"))  # coder re-driven to fix
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertNotIn("loop.step_done", rlog.kinds())
        self.assertEqual(reasoner.calls, 0, "failing tests short-circuit — the critic isn't consulted")

    def test_probe_passes_but_critic_rejects_does_not_advance(self):
        # The syntax probe passes, but THIS step's own goal is failing (e.g. it's the test
        # step and its tests fail) → the critic returns not-done → cria nudges the coder to
        # fix it rather than marking the step done. (Regression: a test step was being
        # marked done while its tests were red.)
        coder = _Scripted([_toolcall(), _done(), _toolcall()])   # acts, claims done, then fixes after the nudge
        reasoner = _Scripted([_verdict(False, "2 tests fail")])
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)                                   # 1: work (tool call forwarded)
        c2 = loop.drive(_body(), "k", _Classification(), rlog)                               # 2: done → GATE
        c3 = loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "k", _Classification(), rlog)  # 3: gate absent → critic rejects
        self.assertTrue(c3["choices"][0]["message"].get("tool_calls"))  # coder re-driven to fix
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertNotIn("loop.step_done", rlog.kinds())   # NOT marked done
        self.assertEqual(reasoner.calls, 1, "the critic WAS consulted — the gate did not block")

    def test_nudge_with_no_tool_call_emits_probe_not_a_dead_end(self):
        # After a critic rejection cria re-drives the coder; if the coder answers with PROSE
        # (no tool call) — which weak models do constantly — cria must NOT forward that bare
        # completion. A text-only turn tells the harness the agent is DONE and stops the
        # session (the step-6 stop). cria emits a fresh ground-truth probe instead.
        coder = _Scripted([_done(), _done()])   # claims done, then STILL no tool call after the nudge
        reasoner = _Scripted([_verdict(False, "not yet")])
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        from cria.probegate import SECTION_PREFIX
        c1 = loop.drive(_body(), "k", _Classification(), rlog)                               # prose → leg0 → prose → GATE
        c2 = loop.drive(_body_with_probe(_tc_id(c1), "PROBE_EXIT=0"), "k", _Classification(), rlog)  # gate absent → critic rejects → re-drive → prose → GATE again
        # c2 MUST carry a tool call (a fresh gate), never a bare/prose completion
        self.assertTrue(c2["choices"][0]["message"].get("tool_calls"))
        self.assertIn(SECTION_PREFIX, json.loads(c2["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1])
        self.assertIn("loop.step_incomplete", rlog.kinds())

    def test_unparseable_verdict_fails_closed_not_open(self):
        # Regression: when the critic returns NO parseable verdict (a reasoning model that ran
        # out of budget before emitting JSON), the step must NOT be silently marked done. It
        # fails CLOSED — the coder is re-driven — and the critic was retried (reasoning-off).
        coder = _Scripted([_toolcall(), _done(), _toolcall()])   # acts, claims done, then a fix action
        reasoner = _Scripted([_unparseable()])              # never yields JSON, on either attempt
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)                                   # 1: work (tool call forwarded)
        c2 = loop.drive(_body(), "k", _Classification(), rlog)                               # 2: done → GATE
        c3 = loop.drive(_body_with_probe(_tc_id(c2), "PROBE_EXIT=0"), "k", _Classification(), rlog)  # 3: gate absent → critic unparseable
        self.assertTrue(c3["choices"][0]["message"].get("tool_calls"))  # coder re-driven, NOT advanced
        self.assertIn("loop.step_incomplete", rlog.kinds())
        self.assertNotIn("loop.step_done", rlog.kinds())    # never marked done on a silent verifier
        self.assertIn("loop.verify_retry", rlog.kinds())    # the reasoning-off retry fired
        self.assertEqual(reasoner.calls, 2, "first pass + reasoning-off retry")

    def test_unparseable_verdict_recovers_on_reasoning_off_retry(self):
        # First pass yields no JSON (budget exhausted); the reasoning-off retry lands a clean
        # verdict → the step advances normally. The retry is the fix for the common case.
        coder = _Scripted([_done()])
        reasoner = _Scripted([_unparseable(), _verdict(True)])   # unparseable, then a real verdict
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "sid:v", _Classification(), rlog)                           # work → done → PROBE
        c2 = loop.drive(_body_with_probe(_tc_id(c1), "PROBE_EXIT=0"), "sid:v", _Classification(), rlog)  # probe clean → retry → done
        self.assertIn("plan complete", c2["choices"][0]["message"]["content"])  # 1-step plan → completes this turn
        self.assertIn("loop.step_done", rlog.kinds())
        # first verdict pass + reasoning-off retry, then the completion compaction on loop.done
        # (the completion compaction runs for every key — the briefing rides the closing message)
        self.assertEqual(reasoner.calls, 3)

    def test_no_shell_tool_declines_to_proxy(self):
        # Without a shell tool the loop can't run: no plan file, no ground-truth probe, and the
        # writeproxy can't lower write_file → a shell command, so the coder can't even write files.
        # Codex also sends genuinely tool-less turns (title/summarize) that classify as 'task'.
        # Decline → proxy, and start NO plan on a request the loop can't execute.
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_verdict(True)]), _plan(1)))
        rlog = _Rlog()
        out = loop.drive({"messages": [{"role": "user", "content": "go"}], "tools": []}, "k", _Classification(), rlog)
        self.assertIsNone(out)                     # proxied, not driven
        self.assertIn("loop.no_shell_tool", rlog.kinds())
        self.assertFalse(loop.has_session("k"))    # no plan started

    def test_live_plan_survives_a_tool_less_turn(self):
        # A tool-less turn arriving mid-plan is declined (proxied) but must NOT drop the live plan —
        # the next tool-bearing turn resumes it.
        store = LoopStore()
        loop = Loop(_ctx(_Scripted([_toolcall(), _toolcall()]), _Scripted([_verdict(True)]), _plan(1)), store)
        loop.drive(_body(), "k", _Classification(), _Rlog())            # start (has shell) → live
        self.assertTrue(loop.has_session("k"))
        out = loop.drive({"messages": [{"role": "user", "content": "?"}], "tools": []}, "k", _Classification(), _Rlog())
        self.assertIsNone(out)                                          # tool-less turn declined
        self.assertTrue(loop.has_session("k"))                          # …but the plan is still live

    def test_non_task_falls_through(self):
        class Q:
            engagement = "question"
            task_type = "question"
            cached = False

        loop = Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict()])))
        self.assertIsNone(loop.drive(_body(), "k", Q(), _Rlog()))


class ClosingTests(unittest.TestCase):
    def _loop(self):
        return Loop(_ctx(_Scripted([_done()]), _Scripted([_verdict()])))

    def test_clean_when_all_verified(self):
        plan = Plan(id="x", task="t", created="c", items=[
            PlanItem("a", done=True, note="verified"),
            PlanItem("b", done=True, note="verified"),
        ])
        msg = self._loop()._closing(PlanSession(plan=plan))
        self.assertIn("plan complete — all 2 steps verified", msg)

    def test_flags_unverified_steps_with_reason(self):
        # A step advanced "accepted unverified" (its checks never passed) must be named in
        # the final message with WHY — not hidden behind a clean "plan complete".
        plan = Plan(id="x", task="t", created="c", items=[
            PlanItem("Create handler.py", done=True, note="verified"),
            PlanItem("Run pytest", done=True, note="accepted unverified", fail_reason="tests failed: 0 collected"),
        ])
        msg = self._loop()._closing(PlanSession(plan=plan))
        self.assertNotIn("plan complete", msg)
        self.assertIn("did NOT pass verification", msg)
        self.assertIn("step 2: Run pytest", msg)
        self.assertIn("tests failed: 0 collected", msg)  # the reason is surfaced


class HelperTests(unittest.TestCase):
    def test_session_key_prefers_header(self):
        self.assertEqual(session_key({"X-Cria-Session-Id": "s9"}, []), "sid:s9")

    def test_session_key_falls_back_to_task_hash(self):
        k1 = session_key(None, [{"role": "user", "content": "same task"}])
        k2 = session_key(None, [{"role": "user", "content": "same task"}, {"role": "assistant", "content": "x"}])
        self.assertTrue(k1.startswith("task:"))
        self.assertEqual(k1, k2, "keyed on the ORIGINAL user message → stable across the task's turns")

    def test_shell_args_by_schema(self):
        arr = find_shell_tool([_SHELL])
        self.assertEqual(shell_args(arr, "ls")["command"], ["bash", "-lc", "ls"])
        string_tool = {"name": "bash", "schema": {"properties": {"command": {"type": "string"}}}}
        self.assertEqual(shell_args(string_tool, "ls")["command"], "ls")

    def test_shell_args_exec_command_uses_cmd_field(self):
        # Codex's exec_command carries the command in `cmd` (required), not `command`.
        # Producing `command` here is what stalled the plan loop ("missing cmd field").
        exec_cmd = {"name": "exec_command", "schema": {
            "properties": {"cmd": {"type": "string"}, "justification": {"type": "string"}},
            "required": ["cmd"]}}
        args = shell_args(exec_cmd, "mkdir -p .cria")
        self.assertEqual(args, {"cmd": "mkdir -p .cria"})
        self.assertNotIn("command", args)

    def test_completion_to_sse_carries_toolcalls(self):
        comp = _toolcall()
        blob = b"".join(completion_to_sse(comp))
        self.assertIn(b"tool_calls", blob)
        self.assertTrue(blob.endswith(b"data: [DONE]\n\n"))


if __name__ == "__main__":
    unittest.main()


class StripCriaFileOpsTests(unittest.TestCase):
    def test_cria_plan_write_hidden_from_coder(self):
        from cria.loop import _frame_for_item
        msgs = [
            {"role": "user", "content": "build the thing"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                "function": {"name": "exec_command",
                    "arguments": '{"cmd": "mkdir -p .cria && printf %s YWJj | base64 -d > .cria/x.md"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": ""},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c2", "type": "function",
                "function": {"name": "exec_command", "arguments": '{"cmd": "cat handler.py"}'}}]},
        ]
        framed = _frame_for_item(msgs, "step 1", "", 1, 3)
        blob = __import__("json").dumps(framed)
        self.assertNotIn(".cria", blob)          # cria's file-op + result gone
        self.assertIn("cat handler.py", blob)    # the coder's real call kept


class BannerStripTests(unittest.TestCase):
    def test_strip_cria_banners_drops_marker_lines(self):
        from cria.loop import _strip_cria_banners
        text = "⟦cria⟧ coder · qwopus · 74 tok/s\n⟦cria⟧ planned 5 steps\nI'll inspect the API."
        self.assertEqual(_strip_cria_banners(text), "I'll inspect the API.")
        self.assertEqual(_strip_cria_banners("just working"), "just working")  # no banners → unchanged

    def test_frame_strips_parroted_banners_from_coder_context(self):
        from cria.loop import _frame_for_item
        msgs = [
            {"role": "user", "content": "build it"},
            {"role": "assistant", "content": "⟦cria⟧ planned 5 steps\n⟦cria⟧ update_plan: [...]"},  # banner-only → dropped
            {"role": "assistant", "content": "⟦cria⟧ coder · m\nActually reading handler.py now."},   # banner scrubbed, real text kept
        ]
        blob = json.dumps(_frame_for_item(msgs, "step 1", "", 1, 3))
        self.assertNotIn("⟦cria⟧", blob)                 # no banners reach the coder
        self.assertIn("Actually reading handler.py", blob)  # the coder's real line survives

    def test_pending_coder_text_is_banner_free_for_critic(self):
        # the coder parrots cria's banners; they must NOT reach the critic as its "summary"
        parroted = _done("⟦cria⟧ coder · m\n⟦cria⟧ planned 5 steps\nI'll inspect the docs.")
        coder = _Scripted([parroted])   # coder is 'done' with parroted banners in its content
        captured = {}

        class _R:
            def __call__(self, body, rlog):
                captured.setdefault("user", body["messages"][-1]["content"])  # the CRITIC's user msg (first call)
                return json.dumps(_verdict(True)).encode()

        loop = Loop(_ctx(coder, _R(), _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "k", _Classification(), rlog)                                # work → done → PROBE
        loop.drive(_body_with_probe(_tc_id(c1), "PROBE_EXIT=0"), "k", _Classification(), rlog)  # probe → critic
        self.assertNotIn("⟦cria⟧", captured.get("user", ""))  # banners scrubbed from the critic's context
        self.assertIn("inspect the docs", captured.get("user", ""))  # the coder's real claim survives


class FrameForItemTests(unittest.TestCase):
    def test_replaces_task_not_env_context(self):
        from cria.loop import _frame_for_item
        msgs = [
            {"role": "system", "content": "generic coding-agent prompt"},
            {"role": "user", "content": "<environment_context>\n<cwd>/repo</cwd>\n</environment_context>"},
            {"role": "user", "content": "Write a handler, unit tests, a live test, and a README."},
        ]
        framed = _frame_for_item(msgs, "Create handler.py with resolve_handle()", "", 1, 7)
        blob = json.dumps(framed)
        self.assertIn("cwd: /repo", blob)                   # env context KEPT — reframed to cria's clean voice
        self.assertNotIn("<environment_context>", blob)     # …no longer the raw harness tags
        self.assertIn("Do ONLY this step", blob)            # step framing present
        self.assertIn("Create handler.py", blob)            # the step is the task
        self.assertNotIn("README", blob)                    # full task (later steps) GONE
        self.assertNotIn("unit tests", blob)

    def test_drops_harness_system_prompt_and_leads_with_crias(self):
        # cria owns the system slot when orchestrating: the harness's agent prompt is dropped
        # entirely and cria's own coder system prompt leads — the user's instructions survive.
        from cria.loop import _frame_for_item
        # Codex sends the user's AGENTS.md folded into the same block as <environment_context>,
        # so _is_env_context recognizes and preserves it (real capture confirmed this shape).
        msgs = [
            {"role": "system", "content": "You are a coding agent running in the Codex CLI. Plan, apply_patch, finish the whole task."},
            {"role": "developer", "content": "extra harness boilerplate (apps/skills/plugins)"},
            {"role": "user", "content": "# AGENTS.md instructions\n<INSTRUCTIONS> my project rules </INSTRUCTIONS>\n<environment_context><cwd>/repo</cwd></environment_context>"},
            {"role": "user", "content": "Build the whole feature."},
        ]
        from cria import prompts
        framed = _frame_for_item(msgs, "Create handler.py", "", 1, 5)
        self.assertEqual(framed[0]["role"], "system")
        self.assertTrue(framed[0]["content"].startswith(prompts.load("coder_system")))  # cria's coder prompt leads
        self.assertIn("Create handler.py", framed[0]["content"])  # + the current step, in the PROTECTED system msg
        blob = json.dumps(framed)
        self.assertNotIn("Codex CLI", blob)                 # harness agent prompt GONE
        self.assertNotIn("harness boilerplate", blob)       # developer boilerplate GONE
        self.assertNotIn("<INSTRUCTIONS>", blob)            # the raw harness tags GONE (reframed)
        self.assertIn("Project instructions", blob)         # the USER's own instructions KEPT — cria's voice
        self.assertIn("my project rules", blob)             # (kept in full)
        self.assertIn("Create handler.py", blob)            # the step
        self.assertNotIn("Build the whole feature", blob)   # the raw task was replaced by the step
        self.assertEqual(sum(1 for m in framed if m["role"] == "system"), 1)  # exactly one system msg


class CoderEvidenceTests(unittest.TestCase):
    def test_excludes_probe_and_empty_keeps_coder_runs(self):
        from cria.loop import _coder_evidence
        msgs = [
            {"role": "tool", "tool_call_id": "probe1", "content": "--- cria probe ---\nPROBE_EXIT=0"},  # cria's probe
            {"role": "tool", "tool_call_id": "fileop", "content": ""},                                   # cria's .cria write
            {"role": "tool", "tool_call_id": "c1", "content": "3 passed, 0 failed in 0.12s"},            # coder's own test run
        ]
        ev = _coder_evidence(msgs, "probe1")
        self.assertIn("3 passed", ev)          # the coder's real run is the evidence
        self.assertNotIn("PROBE_EXIT", ev)     # cria's probe excluded


class SharedGuardTests(unittest.TestCase):
    """The guards are shared module functions (not gated behind the planner), so the plan-off
    proxy path runs the IDENTICAL protection the loop does."""

    def _trunc_write(self):
        return {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": {"name": "write_file",
                                      "arguments": '{"path": "h.py", "content": "def f(): pass"}'}}]},
            "finish_reason": "length"}]}

    def test_guard_truncation_refuses_partial_write_when_exhausted(self):
        from cria.loop import guard_truncation
        calls = []

        def coder_chat(body, rlog):  # always still truncated → never recovers
            calls.append(1)
            return json.dumps(self._trunc_write()).encode()

        out = guard_truncation(self._trunc_write(), {"messages": [{"role": "user", "content": "go"}],
                                                     "tools": None}, coder_chat, _Rlog(), phase="direct-coder")
        self.assertTrue(calls)  # it retried (a mid-write truncation → incremental steer)
        # exhausted → the partial write is REFUSED (tool calls dropped), never shipped to disk
        self.assertFalse((out["choices"][0]["message"].get("tool_calls")))

    def test_guard_truncation_passes_clean_completion_untouched(self):
        from cria.loop import guard_truncation
        clean = {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]}
        calls = []

        def coder_chat(body, rlog):
            calls.append(1)
            return b"{}"

        out = guard_truncation(clean, {"messages": [], "tools": None}, coder_chat, _Rlog())
        self.assertEqual(calls, [])  # not truncated → no retry, no coder call
        self.assertEqual(out["choices"][0]["message"]["content"], "done")


class ReframePreambleTests(unittest.TestCase):
    """The harness env-context/instructions preamble is re-presented in cria's own clean voice
    (ports codex-local extract_project_instructions), not forwarded as a raw foreign-tag collage."""

    _BLOB = ("# AGENTS.md instructions\n\n<INSTRUCTIONS>\n# AGENTS\nNo band-aids.\r\n</INSTRUCTIONS>"
             "<environment_context>\n  <cwd>/w/site</cwd>\n  <shell>bash</shell>\n"
             "  <current_date>2026-07-13</current_date>\n"
             "  <permission_profile type=\"disabled\"/>\n</environment_context>")

    def test_unwraps_instructions_and_env_dropping_noise(self):
        from cria.loop import reframe_preamble
        out = reframe_preamble({"role": "user", "content": self._BLOB})["content"]
        self.assertIn("No band-aids.", out)          # the real instructions survive
        self.assertIn("cwd: /w/site", out)           # the useful env fields survive
        self.assertNotIn("<INSTRUCTIONS>", out)      # foreign tags gone
        self.assertNotIn("permission_profile", out)  # sandbox/permission noise dropped
        self.assertNotIn("\r", out)                  # CRLF normalized

    def test_leaves_the_task_message_untouched(self):
        from cria.loop import reframe_preamble
        task = {"role": "user", "content": "port the lambda handler"}
        self.assertEqual(reframe_preamble(task), task)  # not a preamble → unchanged

    def test_keeps_raw_when_nothing_extractable(self):
        from cria.loop import reframe_preamble
        # matches the env-context signal but has no extractable tag bodies → don't lose it
        m = {"role": "user", "content": "<environment_context></environment_context>"}
        self.assertEqual(reframe_preamble(m), m)


class SharedRepetitionGuardTests(unittest.TestCase):
    """The repetition/wheel-spin guard is now shared module functions (GuardState-driven), so the
    plan-off path runs the IDENTICAL detection→probe→steer the loop does."""

    def _tc(self, name, args):
        return {"choices": [{"message": {"tool_calls": [
            {"id": "x", "function": {"name": name, "arguments": args}}]}}]}

    def test_track_repetition_trips_redirect(self):
        from cria.loop import GuardState, guard_track_repetition, REPEAT_FINGERPRINT_N
        gs = GuardState()
        for _ in range(REPEAT_FINGERPRINT_N):
            guard_track_repetition(gs, self._tc("exec_command", '{"cmd":"pytest -q"}'), _Rlog())
        self.assertTrue(gs.redirect_due)
        self.assertIn("exec_command", gs.repeat_action)

    def test_track_write_streak_trips_spin(self):
        from cria.loop import GuardState, guard_track_write_streak, WHEEL_SPIN_WRITES
        gs = GuardState()
        for _ in range(WHEEL_SPIN_WRITES):
            guard_track_write_streak(gs, self._tc("write_file", '{"path":"h.py","content":"x"}'), _Rlog())
        self.assertTrue(gs.spin_probe_due)
        self.assertEqual(gs.spin_path, "h.py")

    def test_intervene_parks_canned_steer_without_shell(self):
        from cria.loop import GuardState, guard_intervene
        gs = GuardState(); gs.spin_probe_due = True; gs.spin_path = "h.py"
        out = guard_intervene(gs, {"tools": [], "messages": []}, _Rlog())  # no shell → no probe
        self.assertIsNone(out)
        self.assertIn("rewritten `h.py`", gs.nudge_reason)  # never silent — canned steer parked
        self.assertFalse(gs.spin_probe_due)

    def test_probe_steer_returns_spin_ground_truth(self):
        from cria.loop import GuardState, guard_probe_steer
        gs = GuardState(); gs.spin_probe = True; gs.spin_path = "h.py"; gs.probe_call_id = "p1"
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "PROBE_EXIT=0"}]}
        steer = guard_probe_steer(gs, body, _Rlog())  # author=None → canned (plan-off)
        self.assertIn("rewritten `h.py`", steer)
        self.assertFalse(gs.spin_probe)  # consumed


class GuardNoteTests(unittest.TestCase):
    """No hidden guards: rumination + truncation surface an out-of-band cria_notes entry when they
    fire, which the server renders as a ⟦cria⟧ line under [indicators] assists."""

    def test_rumination_surfaces_a_note(self):
        from cria.loop import guard_rumination
        ruminating = {"choices": [{"message": {"role": "assistant", "content": "…"}, "finish_reason": "rumination"}],
                      "cria_rumination": {"hits": 7, "reasoning_tokens": 5000}}
        acted = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c", "function": {"name": "write_file", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}
        out = guard_rumination(ruminating, {"messages": [], "tools": None},
                               lambda b, r: json.dumps(acted).encode(), _Rlog())
        self.assertIn("reasoning loop detected", " ".join(out.get("cria_notes", [])))

    def test_truncation_refusal_surfaces_a_note(self):
        from cria.loop import guard_truncation
        trunc = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c", "function": {"name": "write_file", "arguments": '{"path":"h.py","content":"x"}'}}]},
            "finish_reason": "length"}]}
        out = guard_truncation(dict(trunc), {"messages": [], "tools": None},
                               lambda b, r: json.dumps(trunc).encode(), _Rlog())  # never recovers → refuse
        self.assertIn("partial write refused", " ".join(out.get("cria_notes", [])))


class DirectCompletionGateTests(unittest.TestCase):
    """The objective completion gate cria now runs on a plan-off 'done' (verify the repo's checks
    before letting the turn end) — the pieces the plan-off path drives."""

    def test_gate_verdict_fail_open_without_a_plan(self):
        from cria.loop import GuardState, guard_gate_verdict
        gs = GuardState(); gs.probe_call_id = "p1"  # gate_plan None → couldn't run → accept the 'done'
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "x"}]}
        self.assertIsNone(guard_gate_verdict(gs, body, _Rlog()))

    def test_gate_op_emits_a_shell_probe_and_stashes_the_plan(self):
        from cria.loop import GuardState, guard_gate_op
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "h.py"), "w") as f:
                f.write("def f():\n    return 1\n")
            body = {"tools": [{"type": "function", "function": {"name": "shell",
                     "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}],
                    "messages": [{"role": "user", "content": f"<environment_context><cwd>{tmp}</cwd></environment_context>"}]}
            gs = GuardState()
            probe = guard_gate_op(gs, body, _Rlog())
            self.assertIsNotNone(probe)                 # a shell probe to run the repo's checks
            self.assertEqual(probe["function"]["name"], "shell")
            self.assertIsNotNone(gs.gate_plan)          # stashed so the verdict can interpret it


class CompactionReframeTests(unittest.TestCase):
    """Codex's VS Code compaction APPENDS an 'Another language model started to solve this problem…'
    turn that misattributes the model's own summary — cria reattributes it (the root doesn't change,
    so the structural rewrite detector never fires; this is the fix for that blind spot)."""

    _MARKER = ("Another language model started to solve this problem and produced a summary of its "
               "thinking process. You also have access to the state of the tools that were used by "
               "that language model. Use this to build on the work that has already been done and "
               "avoid duplicating work. Here is the summary produced by the other language model, "
               "use the information in this summary to assist with your own analysis:\n"
               "Built handler.py + tests; live test still failing.")

    def test_reattributes_and_keeps_the_summary(self):
        from cria.loop import reframe_compaction
        msgs = [{"role": "user", "content": "task: build the lambda"},
                {"role": "user", "content": self._MARKER}]
        out, hit = reframe_compaction(msgs)
        self.assertTrue(hit)
        new = out[1]["content"]
        self.assertNotIn("Another language model", new)          # misattribution gone
        self.assertIn("YOUR OWN prior work", new)                # reattributed to the model
        self.assertIn("Built handler.py + tests", new)           # the real summary survives
        self.assertIs(out[0], msgs[0])                           # unrelated messages untouched

    def test_noop_and_idempotent(self):
        from cria.loop import reframe_compaction
        plain = [{"role": "user", "content": "just a normal task"}]
        same, hit = reframe_compaction(plain)
        self.assertFalse(hit)
        self.assertIs(same, plain)                               # same list, no copy
        once, _ = reframe_compaction([{"role": "user", "content": self._MARKER}])
        twice, hit2 = reframe_compaction(once)                   # already reframed → no re-touch
        self.assertFalse(hit2)

    def test_reframes_list_shaped_content(self):
        # A2/A1: content as structured parts (a chat client) must still be matched (was isinstance str)
        from cria.loop import reframe_compaction
        msgs = [{"role": "user", "content": [{"type": "text", "text": self._MARKER}]}]
        out, hit = reframe_compaction(msgs)
        self.assertTrue(hit)
        self.assertNotIn("Another language model", out[0]["content"])
        self.assertIn("Built handler.py + tests", out[0]["content"])

    def test_drifted_boundary_does_not_wrap_the_foreign_preamble(self):
        # A3: boundary text absent → strip up to the marker's line-end, never wrap "another language
        # model…" inside "this is YOUR OWN work".
        from cria.loop import reframe_compaction
        drifted = ("Another language model started to solve this problem and did a bunch.\n"
                   "Built handler.py; tests failing.")
        out, hit = reframe_compaction([{"role": "user", "content": drifted}])
        self.assertTrue(hit)
        self.assertNotIn("Another language model", out[0]["content"])   # preamble stripped
        self.assertIn("Built handler.py", out[0]["content"])            # real content kept

    def test_empty_workspace_inverts_the_reframe(self):
        # THE DRIFT ROOT: over an EMPTY advertised cwd the "read the files that already exist, do NOT
        # recreate" claim is false — invert it to "start fresh here, don't look elsewhere".
        import tempfile
        from cria.loop import reframe_compaction
        with tempfile.TemporaryDirectory() as empty:   # exists but has no entries
            msgs = [{"role": "user", "content": f"<environment_context><cwd>{empty}</cwd></environment_context>"},
                    {"role": "user", "content": self._MARKER}]
            out, hit = reframe_compaction(msgs)
        self.assertTrue(hit)
        new = out[1]["content"]
        self.assertIn("EMPTY", new)                              # the workspace-empty framing
        self.assertIn("Start the work FRESH", new)
        self.assertIn(empty, new)                                # names the cwd to recreate in
        self.assertNotIn("YOUR OWN prior work", new)             # NOT the "build on existing files" claim
        self.assertNotIn("do NOT recreate", new.lower())         # the harmful instruction is gone
        self.assertIn("Built handler.py + tests", new)           # the real summary still survives

    def test_populated_workspace_keeps_the_normal_reframe(self):
        # A non-empty workspace (real prior work) keeps the standard "build on it" reframe.
        import os
        import tempfile
        from cria.loop import reframe_compaction
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "handler.py"), "w") as f:
                f.write("x = 1\n")
            msgs = [{"role": "user", "content": f"<environment_context><cwd>{ws}</cwd></environment_context>"},
                    {"role": "user", "content": self._MARKER}]
            out, hit = reframe_compaction(msgs)
        self.assertTrue(hit)
        self.assertIn("YOUR OWN prior work", out[1]["content"])  # normal reframe


class GuardStoreIsolationTests(unittest.TestCase):
    def test_unstable_keys_isolated_stable_persist_and_bounded(self):
        from cria.loop import GuardStore, _MAX_GUARD_STATES
        st = GuardStore()
        self.assertIs(st.get("sid:abc"), st.get("sid:abc"))        # stable key → persists (same object)
        self.assertIsNot(st.get("task:h"), st.get("task:h"))       # unstable → fresh each turn, no sharing
        for i in range(_MAX_GUARD_STATES + 5):                     # never grows unboundedly
            st.get(f"sid:{i}")
        self.assertLessEqual(len(st._m), _MAX_GUARD_STATES + 1)


class FreshDiskFactsTests(unittest.TestCase):
    """The reasoned redirect now grounds on the files as they ARE on disk (groundtruth port),
    not the transcript's stale view."""

    def test_reads_current_bytes_and_reports_missing(self):
        import os
        import tempfile

        from cria.loop import _fresh_disk_facts
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "h.py"), "w") as f:
            f.write("def f():\n    return 42\n")
        out = _fresh_disk_facts(d, ["h.py", None, "h.py"], "")   # dedups, skips None
        self.assertIn("h.py", out)
        self.assertIn("return 42", out)                          # the ACTUAL current disk bytes
        self.assertIn("on disk NOW", out)
        self.assertIn("does NOT exist", _fresh_disk_facts(d, ["nope.py"], ""))  # missing = a fact
        self.assertEqual(_fresh_disk_facts(None, ["h.py"], ""), "")  # no root → empty (prior behavior)
        self.assertEqual(_fresh_disk_facts(d, [], ""), "")          # no paths → empty


class GroundTruthSilenceTests(unittest.TestCase):
    """guard_ground_truth (shared by BOTH the spin nudge and the canned redirect, in the loop and
    plan-off) speaks to the model ONLY from positive signal. A gate whose test probe failed to launch
    is cria's OWN setup gap — it stays SILENT (empty), never 'all checks pass' (the false green light
    that talked the coder out of a still-needed KeyError fix, session 20260716T093350) and never a
    confession the model can't act on."""

    def _gate_outcome(self, results):
        from cria.probegate import GateOutcome
        from cria.proberun import ProbeReport
        return GateOutcome(ran=True, report=ProbeReport([], [], results))

    def test_launch_failed_probe_is_silence_not_pass(self):
        from cria.loop import guard_ground_truth
        from cria.probeparse import ProbeResult
        truth = guard_ground_truth(self._gate_outcome([
            ProbeResult("python -m pytest -q", None, "failed to launch — python not found", []),
            ProbeResult("python3 -m compileall -q .", 0, "clean", []),
        ]))
        self.assertEqual(truth, "")   # no positive signal → say nothing (not "pass", not a confession)

    def test_all_ran_clean_is_no_error_class_not_a_pass_verdict(self):
        from cria.loop import guard_ground_truth
        from cria.probeparse import ProbeResult
        truth = guard_ground_truth(self._gate_outcome([ProbeResult("python3 -m pytest -q", 0, "3 passed", [])]))
        self.assertIn("no error-class", truth.lower())
        self.assertIn("not a verdict", truth.lower())
        self.assertNotIn("all pass", truth.lower())

    def test_error_findings_are_surfaced(self):
        from cria.loop import guard_ground_truth
        from cria.probeparse import Finding, ProbeResult
        truth = guard_ground_truth(self._gate_outcome([ProbeResult(
            "python3 -m pytest -q", 1, "1 failed",
            [Finding(file="x.py", line=5, message="undefined name 'foo'")])]))
        self.assertIn("undefined name 'foo'", truth)

    def test_gate_never_ran_is_silence(self):
        from cria.loop import guard_ground_truth
        from cria.probegate import GateOutcome
        self.assertEqual(guard_ground_truth(GateOutcome(ran=False)), "")

    def test_spin_steer_falls_back_to_behavioral_nudge_when_silent(self):
        # the wheel-spin steer must still fire (with a DIFFERENT-action nudge) even when the checks
        # gave no signal — it just carries no checks claim.
        from cria.loop import GuardState, guard_probe_steer
        gs = GuardState(); gs.spin_probe = True; gs.spin_path = "handle_api.py"; gs.probe_call_id = "p1"
        gs.gate_plan = None  # → outcome.ran False → guard_ground_truth "" → spin_no_truth path
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "x"}]}
        steer = guard_probe_steer(gs, body, _Rlog())
        self.assertIsNotNone(steer)
        self.assertIn("handle_api.py", steer)
        self.assertIn("different next action", steer.lower())
        self.assertNotIn("pass", steer.lower())

    def _test_cand(self, cmd, kind):
        from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind  # noqa: F401
        return ProbeCandidate(kind=kind, command=cmd, working_dir="/tmp", confidence=90,
                              expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
                              may_hang=False, may_need_services=False, reason="t")

    def test_failed_unparsed_check_is_surfaced_not_clean(self):
        # a hard-failure probe (test) that ran, exited non-zero, but produced no parseable finding must
        # surface as FAILED — not fall through to the clean "no error-class findings" message.
        from cria.loop import guard_ground_truth
        from cria.probediscovery import ProbeKind
        from cria.probegate import GateOutcome
        from cria.probeparse import ProbeResult
        from cria.proberun import ProbeReport
        cand = self._test_cand(["pytest", "-q"], ProbeKind.Test)
        out = GateOutcome(ran=True, report=ProbeReport([], [cand], [ProbeResult("pytest -q", 1, "boom", [])]))
        truth = guard_ground_truth(out)
        self.assertIn("failed", truth.lower())
        self.assertNotIn("no error-class", truth.lower())

    def test_gate_verdict_blocks_a_failed_unparsed_done(self):
        # the plan-off DONE gate must NOT accept a 'done' when a hard-failure check ran and failed —
        # even with no parseable location (the guard_gate_verdict straggler the sweep found).
        from cria.loop import GuardState, guard_gate_verdict
        from cria.probediscovery import ProbeKind
        from cria.probegate import GatePlan, SECTION_PREFIX as P, SECTION_SUFFIX as S
        gs = GuardState(); gs.probe_call_id = "p1"
        gs.gate_plan = GatePlan(workspace="/tmp", candidates=[self._test_cand(["python3", "-m", "pytest", "-q"], ProbeKind.Test)])
        probe = f"{P}probe-0{S}\ninternal error, aborting collection\nEXIT:1\n{P}git{S}\nabc\n"
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": probe}]}
        self.assertIsNotNone(guard_gate_verdict(gs, body, _Rlog()))   # 'done' NOT accepted


class NavRepeatSignatureTests(unittest.TestCase):
    """Progressive navigation (paging a doc, drilling by key, listing a NEW dir) is progress, not a
    spiral — a changed url/cursor/path must not trip the repetition redirect. Three progressive
    web_fetches falsely matched (host tokens dominated the word-bag), aborting a legitimate paginated
    read (calls 25-28); three list_dir of DIFFERENT paths falsely fired at call 12."""

    def test_progressive_web_fetch_pages_do_not_match(self):
        from cria.loop import _action_signature, _actions_match
        a = _action_signature("web_fetch", '{"url":"https://api.handle.me/openapi.json"}')
        b = _action_signature("web_fetch", '{"url":"https://api.handle.me/openapi.json","cursor":"c16000"}')
        self.assertFalse(_actions_match(a, b))          # different cursor = progress, not a repeat

    def test_identical_web_fetch_still_matches(self):
        from cria.loop import _action_signature, _actions_match
        s = '{"url":"https://api.handle.me/openapi.json","cursor":"c16000"}'
        self.assertTrue(_actions_match(_action_signature("web_fetch", s), _action_signature("web_fetch", s)))

    def test_list_dir_of_different_paths_do_not_match(self):
        from cria.loop import _action_signature, _actions_match
        a = _action_signature("list_dir", '{"path":"/w"}')
        b = _action_signature("list_dir", '{"path":"/w/docs"}')
        self.assertFalse(_actions_match(a, b))          # the bogus call-12 "3 times (list_dir docs)"

    def test_list_dir_same_path_matches(self):
        from cria.loop import _action_signature, _actions_match
        s = '{"path":"/w"}'
        self.assertTrue(_actions_match(_action_signature("list_dir", s), _action_signature("list_dir", s)))

    def test_read_file_progressive_start_lines_do_not_match(self):
        from cria.loop import _action_signature, _actions_match
        a = _action_signature("read_file", '{"path":"big.py"}')
        b = _action_signature("read_file", '{"path":"big.py","start_line":200}')
        self.assertFalse(_actions_match(a, b))


class SatisfactionCheckTests(unittest.TestCase):
    """The periodic 'is the user's task satisfied?' off-ramp for a plan-off session that finished the
    work but can't STOP. Cadence: drive 100, then every 25. Fails CLOSED on an unparseable verdict."""

    def test_cadence_starts_at_100_every_25(self):
        from cria.loop import satisfaction_check_due
        self.assertFalse(satisfaction_check_due(99, 100, 25))
        self.assertTrue(satisfaction_check_due(100, 100, 25))
        self.assertFalse(satisfaction_check_due(101, 100, 25))
        self.assertFalse(satisfaction_check_due(124, 100, 25))
        self.assertTrue(satisfaction_check_due(125, 100, 25))
        self.assertTrue(satisfaction_check_due(150, 100, 25))
        # tunable + disable: a tighter cadence, and 0 turns it off
        self.assertTrue(satisfaction_check_due(60, 50, 10))
        self.assertFalse(satisfaction_check_due(1000, 0, 25))    # start=0 disables
        self.assertFalse(satisfaction_check_due(1000, 100, 0))   # every=0 disables

    def _chat(self, content):
        def fake(body, rlog):
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        return fake

    def test_satisfied_verdict_parsed(self):
        from cria.loop import judge_satisfaction
        sat, reason = judge_satisfaction("build a resolver", "wrote resolver.py; pytest: 3 passed",
                                         self._chat('{"satisfied": true, "reason": "tests pass, live check works"}'),
                                         None, _Rlog())
        self.assertTrue(sat)
        self.assertIn("tests pass", reason)

    def test_not_satisfied_verdict(self):
        from cria.loop import judge_satisfaction
        sat, _ = judge_satisfaction("t", "e",
                                    self._chat('{"satisfied": false, "reason": "tests failing"}'), None, _Rlog())
        self.assertFalse(sat)

    def test_fails_closed_on_unparseable_verdict(self):
        from cria.loop import judge_satisfaction
        sat, reason = judge_satisfaction("t", "e", self._chat("maybe it is done, hard to say"), None, _Rlog())
        self.assertFalse(sat)                 # no JSON → NOT satisfied; never end a session on silence
        self.assertIn("unverified", reason)

    def test_reasoning_off_retry_recovers_a_leaked_verdict(self):
        # THE live bug: the reasoning-ON pass role-plays the coder (non-empty, non-JSON — a leaked
        # tool call), so the old summarize-on-empty retry never fired and it failed closed forever.
        # Now it retries reasoning-OFF on a parse miss and recovers the real verdict.
        from cria.loop import judge_satisfaction
        calls = []

        def fake(body, rlog):
            calls.append(body)
            content = ("Re-install with the fixed pyproject and run both tests." if len(calls) == 1
                       else '{"satisfied": true, "reason": "all three tests pass"}')
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()

        sat, reason = judge_satisfaction("t", "e", fake, None, _Rlog())
        self.assertTrue(sat)                  # recovered on the reasoning-off retry
        self.assertEqual(len(calls), 2)       # both passes ran (on, then off)
        self.assertIn("tests pass", reason)

    def test_empty_task_is_not_satisfied(self):
        from cria.loop import judge_satisfaction
        sat, _ = judge_satisfaction("   ", "e", self._chat('{"satisfied": true}'), None, _Rlog())
        self.assertFalse(sat)                 # nothing to judge → fail closed


class PeriodicGateSilentOnCleanTests(unittest.TestCase):
    """The periodic check-in must be SILENT on a clean result — only surface real problems. Prodding a
    passing check-in with "checks pass but that's not correctness, keep fixing" made the model distrust
    a genuine pass and keep working (feeding the can't-stop spiral)."""

    def _oc(self, results):
        from cria.probegate import GateOutcome
        from cria.proberun import ProbeReport
        return GateOutcome(ran=True, report=ProbeReport([], [], results))

    def test_gate_error_text_empty_on_clean(self):
        from cria.loop import gate_error_text
        from cria.probeparse import ProbeResult
        self.assertEqual(gate_error_text(self._oc([ProbeResult("pytest -q", 0, "3 passed", [])])), "")

    def test_gate_error_text_surfaces_findings(self):
        from cria.loop import gate_error_text
        from cria.probeparse import Finding, ProbeResult
        err = gate_error_text(self._oc([ProbeResult(
            "pytest -q", 1, "1 failed", [Finding(file="x.py", line=5, message="undefined name 'foo'")])]))
        self.assertIn("undefined name 'foo'", err)

    def test_periodic_result_silent_on_clean(self):
        from cria.loop import GuardState, guard_periodic_result
        from cria.probegate import GatePlan, SECTION_PREFIX as P, SECTION_SUFFIX as S
        from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
        cand = ProbeCandidate(kind=ProbeKind.Test, command=["python3", "-m", "pytest", "-q"],
                              working_dir="/tmp", confidence=90, expected_value=80, cost=ProbeCost.Cheap,
                              mutates_code=False, may_hang=False, may_need_services=False, reason="t")
        gs = GuardState(); gs.periodic_probe = True; gs.probe_call_id = "p1"
        gs.gate_plan = GatePlan(workspace="/tmp", candidates=[cand])
        clean = f"{P}probe-0{S}\n3 passed in 0.1s\nEXIT:0\n{P}git{S}\nabc\n"
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": clean}]}
        self.assertIsNone(guard_periodic_result(gs, body, _Rlog()))   # clean → no injection


if __name__ == "__main__":
    unittest.main()
