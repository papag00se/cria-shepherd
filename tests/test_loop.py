import json
import unittest

from cria.loop import (Loop, LoopContext, LoopStore, PlanSession, TASK_COMPLETE_TOOL, _add_completion_tool,
                       _frame_for_item, _has_tool_calls, _completion_text, _normalize_completion,
                       completion_to_sse, guard_rumination, guard_truncation, session_key)
from cria.plan import Plan, PlanItem
from cria.shelltool import find_shell_tool, shell_args


class _NullRlog:
    def emit(self, *a, **k):
        pass


class CompletionToolTests(unittest.TestCase):
    """The task_complete tool is an EXPLICIT 'done' the driver folds into the normal flow — a lone
    call becomes a plain-text done (running the SAME gate a bare done does); alongside real work it's
    dropped. It is advertised on coder turns but never lowered/forwarded."""

    def _comp(self, tcs, content=None):
        return {"choices": [{"message": {"content": content, "tool_calls": tcs}}]}

    def _tc(self, name, args):
        return {"id": "x", "type": "function", "function": {"name": name, "arguments": args}}

    def test_lone_task_complete_becomes_plain_done_with_summary(self):
        c = _normalize_completion(self._comp([self._tc(TASK_COMPLETE_TOOL, '{"summary": "made hello.py"}')]), _NullRlog())
        self.assertFalse(_has_tool_calls(c))                 # no longer an acting turn → routes to the gate
        self.assertEqual(_completion_text(c), "made hello.py")  # the summary is the completion text (pending_done)

    def test_task_complete_alongside_real_work_is_dropped(self):
        c = _normalize_completion(
            self._comp([self._tc(TASK_COMPLETE_TOOL, '{"summary": "x"}'), self._tc("write_file", '{"path": "a"}')]),
            _NullRlog())
        names = [t["function"]["name"] for t in c["choices"][0]["message"]["tool_calls"]]
        self.assertEqual(names, ["write_file"])              # still working → the premature done is ignored

    def test_real_tools_and_bare_done_pass_through(self):
        real = _normalize_completion(self._comp([self._tc("write_file", "{}")]), _NullRlog())
        self.assertTrue(_has_tool_calls(real))
        bare = _normalize_completion(self._comp(None, content="all done"), _NullRlog())
        self.assertFalse(_has_tool_calls(bare))
        self.assertEqual(_completion_text(bare), "all done")

    def test_advertised_once_on_a_coder_turn(self):
        framed = {"tools": [{"type": "function", "function": {"name": "shell"}}]}
        _add_completion_tool(framed)
        _add_completion_tool(framed)  # idempotent — no duplicate
        names = [t["function"]["name"] for t in framed["tools"]]
        self.assertEqual(names.count(TASK_COMPLETE_TOOL), 1)
        self.assertIn("shell", names)


class SyntheticFramingTests(unittest.TestCase):
    """Single-item plan-off mode frames the RAW task (no 'step k/n') — byte-equivalent to the
    former server._direct_coder_body, so 'planner off' stays a fair 'coder without a planner'."""

    def _body(self):
        return {
            "model": "m",
            "tools": [{"type": "function", "function": {"name": "shell", "description": "run", "parameters": {}}}],
            "messages": [
                {"role": "system", "content": "You are Codex, an autonomous agent."},
                {"role": "user", "content": "<env>cwd=/repo</env>"},
                {"role": "user", "content": "Add a --verbose flag to the CLI."},
                {"role": "assistant", "content": "⟦cria⟧ coder · gemma"},
                {"role": "tool", "content": "ok"},
            ],
        }

    def test_synthetic_drops_harness_system_and_banner_leads_with_coder_prompt(self):
        # The former server._direct_coder_body framing, now produced by _frame_for_item(synthetic=True):
        # cria's coder_system (+ menu hint) leads, the harness system + cria's own ⟦cria⟧ banner are
        # dropped, the env-preamble + raw task + work history are kept.
        from cria import prompts
        from cria.toolmenu import cheatsheet
        body = self._body()
        out = _frame_for_item(body["messages"], "", "", 1, 1, prior_work="", tools=body.get("tools"), synthetic=True)
        hint = cheatsheet(body.get("tools"))
        expected_system = prompts.load("coder_system") + (f"\n\n{hint}" if hint else "")
        self.assertEqual(out[0], {"role": "system", "content": expected_system})     # cria's coder prompt leads
        self.assertEqual([m["role"] for m in out], ["system", "user", "user", "tool"])  # harness sys + banner dropped
        joined = " ".join(m.get("content") or "" for m in out)
        self.assertIn("--verbose flag", joined)                                       # raw task kept
        self.assertNotIn("You are Codex", joined)                                     # harness system gone
        self.assertNotIn("⟦cria⟧", joined)                                            # cria's banner scrubbed

    def test_synthetic_keeps_raw_task_and_no_step_prompt(self):
        body = self._body()
        out = _frame_for_item(body["messages"], "IGNORED-STEP", "IGNORED-SUMMARY", 1, 1, tools=body.get("tools"), synthetic=True)
        self.assertEqual(out[0]["role"], "system")
        self.assertNotIn("step 1", " ".join(m.get("content", "") for m in out).lower())  # no "step 1/1"
        self.assertTrue(any("--verbose flag" in m.get("content", "") for m in out))       # raw task kept

    def test_multi_item_still_step_frames(self):
        # A genuine plan step (synthetic=False) keeps the step framing — the flag, not len==1, is the key.
        body = self._body()
        out = _frame_for_item(body["messages"], "Write the flag parser", "", 2, 3, tools=body.get("tools"))
        joined = " ".join(m.get("content", "") for m in out)
        self.assertIn("Write the flag parser", joined)   # the STEP is the ask, not the raw task


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


def _replan(steps):
    return {"choices": [{"message": {"content": json.dumps({"steps": steps})}}]}


def _text(s):
    # a bare content answer — e.g. the reasoner's NOISE-step judgment ("1, 2" / "NONE")
    return {"choices": [{"message": {"content": s}}]}


def _sat(satisfied, reason="r"):
    return {"choices": [{"message": {"content": json.dumps({"satisfied": satisfied, "reason": reason})}}]}


class CompletionCriticTests(unittest.TestCase):
    """A plan-ON completion (all steps verified INDIVIDUALLY) runs the WHOLE-TASK satisfaction critic
    before declaring done — the green-but-wrong backstop the plan-off path already had. On not-satisfied
    it re-opens with ONE corrective step; bounded so an unfinishable task still exits."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def _loop(self, reasoner):
        ctx = _ctx(_Scripted([_toolcall()]), reasoner)
        ctx.reasoner_role = self._role()
        return Loop(ctx)

    def _done_sess(self):
        plan = Plan(id="x", task="build a resolver", created="c",
                    items=[PlanItem("step 1", done=True, note="verified"),
                           PlanItem("step 2", done=True, note="verified")])
        return PlanSession(plan=plan)

    def test_reopens_with_a_corrective_step_when_not_satisfied(self):
        from cria.loop import _COMPLETION_FIX_PREFIX
        loop = self._loop(_Scripted([_sat(False, "the resolver 404s on the wrong endpoint")]))
        sess = self._done_sess()
        reason = loop._reopen_if_unsatisfied(sess, _body(), _Rlog())
        self.assertIsNotNone(reason)                          # not None → caller re-drives, doesn't complete
        self.assertIn("404", reason)
        self.assertEqual(sess.plan.status, "in_progress")
        self.assertTrue(sess.plan.items[-1].text.startswith(_COMPLETION_FIX_PREFIX))
        self.assertIsNotNone(sess.plan.current())             # a step to drive again
        self.assertEqual(sess.completion_checks, 1)

    def test_completes_when_satisfied(self):
        loop = self._loop(_Scripted([_sat(True)]))
        sess = self._done_sess()
        self.assertIsNone(loop._reopen_if_unsatisfied(sess, _body(), _Rlog()))   # None → complete
        self.assertIsNone(sess.plan.current())                # plan stays complete

    def test_bound_lets_an_unfinishable_task_exit(self):
        from cria.loop import MAX_COMPLETION_CHECKS
        loop = self._loop(_Scripted([_sat(False, "still broken")]))
        sess = self._done_sess()
        sess.completion_checks = MAX_COMPLETION_CHECKS
        self.assertIsNone(loop._reopen_if_unsatisfied(sess, _body(), _Rlog()))   # capped → exit, not forever
        self.assertEqual(reasoner_calls := loop._ctx.reasoner_chat.calls, 0, "capped before calling the critic")

    def test_corrective_step_is_reused_not_grown(self):
        from cria.loop import _COMPLETION_FIX_PREFIX
        loop = self._loop(_Scripted([_sat(False, "broken A"), _sat(False, "broken B")]))
        sess = self._done_sess()
        loop._reopen_if_unsatisfied(sess, _body(), _Rlog())   # adds one corrective step
        sess.plan.items[-1].done = True                       # simulate it got verified, then re-check
        loop._reopen_if_unsatisfied(sess, _body(), _Rlog())   # reuses the SAME corrective step
        fixes = [it for it in sess.plan.items if it.text.startswith(_COMPLETION_FIX_PREFIX)]
        self.assertEqual(len(fixes), 1)                       # exactly one, reused — no plan bloat

    def test_no_reasoner_completes_without_a_check(self):
        loop = Loop(_ctx(_Scripted([_toolcall()]), _Scripted([_sat(False)])))  # reasoner_role stays None
        sess = self._done_sess()
        self.assertIsNone(loop._reopen_if_unsatisfied(sess, _body(), _Rlog()))

    def test_critic_judges_the_PLAN_task_not_the_compaction_summary(self):
        # M1: after a harness compaction, _history_root(messages)[0] is the SUMMARY (which may have
        # dropped a requirement); the critic must judge the AUTHORITATIVE sess.plan.task, else a
        # green-but-incomplete finish passes. Fails before the swap (task was the history root).
        seen = {}

        def reasoner(bd, rl):
            seen["prompt"] = bd["messages"][-1]["content"]   # the satisfaction_user prompt carries the task
            return json.dumps(_sat(True)).encode()
        ctx = _ctx(_Scripted([_toolcall()]), reasoner)
        ctx.reasoner_role = self._role()
        plan = Plan(id="x", task="build a resolver AND ship a README", created="c",
                    items=[PlanItem("step 1", done=True, note="verified")])
        sess = PlanSession(plan=plan)
        body = {"messages": [{"role": "user", "content": "compacted note omitting the readme requirement"}]}
        Loop(ctx)._reopen_if_unsatisfied(sess, body, _Rlog())
        # the plan task is NOT in the body messages, so it can only appear if plan.task was used (M1)
        self.assertIn("build a resolver AND ship a README", seen["prompt"])


class LivingPlanTests(unittest.TestCase):
    """At each verified advance a dedicated reasoner re-derives the NOT-done steps from the real work
    done (the living plan) — pruning a step the coder already satisfied before it makes them redo it."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def _sess(self):
        plan = Plan(id="x", task="build it", created="c",
                    items=[PlanItem("step 1", done=True, note="verified"),
                           PlanItem("step 2"), PlanItem("step 3")])
        return PlanSession(plan=plan)

    def _loop(self, reasoner):
        ctx = _ctx(_Scripted([_toolcall()]), reasoner)
        ctx.reasoner_role = self._role()
        return Loop(ctx)

    def test_refines_not_done_tail_and_keeps_completed(self):
        loop = self._loop(_Scripted([_replan(["step 3"]), _text("NONE")]))  # re-derive drops step 2; noise: NONE
        sess = self._sess()
        loop._replan_tail(sess, _body(), 1, _Rlog())
        self.assertEqual([(it.text, it.done) for it in sess.plan.items],
                         [("step 1", True), ("step 3", False)])   # step 1 kept verified; step 2 pruned

    def test_unparseable_leaves_plan_untouched(self):
        loop = self._loop(_Scripted([_unparseable()]))
        sess = self._sess()
        loop._replan_tail(sess, _body(), 1, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items], ["step 1", "step 2", "step 3"])  # fail-safe

    def test_empty_tail_declined_when_task_not_satisfied(self):
        # reasoner says nothing remains, but the task critic disagrees → keep the remaining steps
        loop = self._loop(_Scripted([_replan([]), _sat(False)]))
        sess = self._sess()
        loop._replan_tail(sess, _body(), 1, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items], ["step 1", "step 2", "step 3"])

    def test_empty_tail_allowed_when_task_satisfied(self):
        loop = self._loop(_Scripted([_replan([]), _sat(True)]))
        sess = self._sess()
        loop._replan_tail(sess, _body(), 1, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items], ["step 1"])   # tail emptied → plan complete
        self.assertIsNone(sess.plan.current())

    def test_skipped_for_synthetic_plan(self):
        reasoner = _Scripted([_replan(["x"])])
        loop = self._loop(reasoner)
        sess = PlanSession(plan=_plan(1), synthetic=True)
        loop._replan_tail(sess, _body(), 1, _Rlog())
        self.assertEqual(reasoner.calls, 0)                        # no tail on a 1-item synthetic plan

    def test_reasoning_of_falls_back_to_content_for_a_non_splitting_model(self):
        # The quiet-flail detector was inert for any model that inlines its thinking in `content`
        # (no reasoning_content channel); mirror the rumination watcher's reasoning-or-content fallback.
        from cria.loop import _reasoning_of
        self.assertEqual(_reasoning_of({"choices": [{"message": {"content": "hmm, wait, let me reconsider"}}]}),
                         "hmm, wait, let me reconsider")
        # a splitting model still uses its dedicated reasoning channel (content is the answer, not thinking)
        self.assertEqual(_reasoning_of({"choices": [{"message": {"reasoning_content": "R", "content": "C"}}]}), "R")

    def test_reassess_remaining_returns_none_on_no_reasoner(self):
        from cria.loop import reassess_remaining
        self.assertIsNone(reassess_remaining(_Scripted([_replan(["a"])]), None,
                                             "t", "(none)", "- s", "ev", _Rlog()))

    def test_reassess_remaining_drops_a_speculative_endpoint_step(self):
        # PARITY with the initial plan (the shared reasoned_noise_indices): a re-derivation grounded in the
        # coder's FAILED work would otherwise CODIFY its guessed endpoint into an authoritative step
        # (observed live: a research step re-derived into "call requests.get('<root>')" — the guessed root
        # — which the coder then shipped as a 404/403). The reasoner JUDGES the /resolve guess speculative
        # (script "1") and drops it; the real work survives. 2 reasoner calls: re-derive, then noise-judge.
        from cria.loop import reassess_remaining
        steps = reassess_remaining(
            _Scripted([_replan(["Call /resolve/{handle} and return the address", "Write unit tests"]),
                       _text("1")]),
            self._role(), "resolve an Ada Handle via api.handle.me", "- researched", "- old", "ev", _Rlog())
        self.assertFalse(any("/resolve/{handle}" in s for s in steps))  # speculative step dropped, not hardened
        self.assertTrue(any("unit tests" in s for s in steps))          # real steps survive

    def test_reassess_reprepends_research_when_api_code_remains_unresearched(self):
        # DURABILITY (shared enforce_research_first): the living plan must NOT silently DROP "read the real
        # source" while a re-derived step still targets the API un-researched — this run guessed
        # /resolve?handle= after re-derivation dropped the research step. Calls: re-derive, noise,
        # api-host, research-satisfied(NO) → re-prepend.
        from cria.loop import reassess_remaining
        steps = reassess_remaining(
            _Scripted([_replan(["Call the api.handle.me endpoint and return the resolved address",
                                "Add unit tests"]),
                       _text("NONE"),           # noise? none
                       _text("api.handle.me"),  # which API host?
                       _text("NO")]),           # research satisfied? NO → re-prepend
            self._role(), "resolve an Ada Handle via api.handle.me", "- some coder work", "- old", "ev", _Rlog())
        self.assertIn("api.handle.me/openapi.json", steps[0])           # research step re-prepended FIRST
        self.assertTrue(any("unit tests" in s for s in steps))         # real steps survive after it

    def test_reassess_does_not_reprepend_once_research_is_satisfied(self):
        # The EVIDENCE shows the coder already read the spec (research SATISFIED → YES), so the living plan
        # must NOT re-prepend a research step on every advance — no churn.
        from cria.loop import reassess_remaining
        steps = reassess_remaining(
            _Scripted([_replan(["Add unit tests", "Write the README"]),
                       _text("NONE"),           # noise? none
                       _text("api.handle.me"),  # which API host?
                       _text("YES")]),          # research satisfied → NO re-prepend
            self._role(), "resolve via api.handle.me", "- fetched the openapi spec", "- old", "ev", _Rlog())
        self.assertNotIn("openapi.json", steps[0])   # no research step re-prepended
        self.assertEqual(len(steps), 2)

    def test_reassess_remaining_drops_a_shell_command_step(self):
        # observed live: the re-derivation codified the coder's grep as step 1 — "grep -n 'resolve'
        # ./tmp/.../openapi.json" — which the coder could not "complete", trapping the plan. The reasoner
        # judges it a bare command (script "1") and drops it.
        from cria.loop import reassess_remaining
        steps = reassess_remaining(
            _Scripted([_replan(["grep -n 'resolve' ./tmp/read-only/api.handle.me_openapi.json",
                                "Write the resolver using the endpoint the spec names"]),
                       _text("1")]),
            self._role(), "resolve via api.handle.me", "- researched", "- old", "ev", _Rlog())
        self.assertFalse(any(s.startswith("grep") for s in steps))
        self.assertTrue(any("resolver" in s for s in steps))

    def test_reassess_remaining_all_noise_keeps_prior_plan(self):
        from cria.loop import reassess_remaining
        # a re-derivation the reasoner judges ENTIRELY noise (script "1, 2") → None (keep the plan we had),
        # never an empty plan
        out = reassess_remaining(
            _Scripted([_replan(["grep -n x f.json", "cat ./f.py"]), _text("1, 2")]),
            self._role(), "task", "- done", "- old", "ev", _Rlog())
        self.assertIsNone(out)

    def test_reassess_remaining_coerces_dict_wrapped_steps(self):
        # a small model wraps each step in {"step": "..."} instead of a bare string — the step text must
        # be the field, NOT the dict repr "{'step': ...}" (the observed JSON-in-the-plan leak). The noise
        # judge (script "NONE") drops nothing.
        from cria.loop import reassess_remaining
        steps = reassess_remaining(
            _Scripted([_replan([{"step": "Design the CLI skeleton"}, {"step": "Write unit tests"}]),
                       _text("NONE")]),
            self._role(), "build it", "- step 1", "- step 2\n- step 3", "evidence", _Rlog())
        self.assertEqual(steps, ["Design the CLI skeleton", "Write unit tests"])
        for s in steps:
            self.assertNotIn("{", s)     # no dict repr leaked into the step text


class GroundedEvidenceTests(unittest.TestCase):
    """The step critic (and the re-derivation) must judge on the DURABLE fetched-page facts, not just the
    recent compaction-shrunk work log — else a research step ("examine the spec") is judged NOT-done
    because the spec fetch scrolled off (observed live: the critic saw a 3-action window, concluded "no
    OpenAPI spec reference", and kept the coder re-researching a spec it had fetched openapi.json 45×)."""

    def _loop(self):
        return Loop(_ctx(_Scripted([_toolcall()]), None))

    def test_durable_fetch_facts_are_folded_into_evidence(self):
        loop = self._loop()
        sess = PlanSession(plan=_plan(2))
        sess.fetched_pages = {"https://api.handle.me/openapi.json": (200, "/handles/{handle}, /holders/{address}")}
        ev = loop._grounded_evidence(sess, {"messages": []})   # empty window — the fetch was compacted away
        self.assertIn("openapi.json", ev)
        self.assertIn("/handles/{handle}", ev)                 # the critic now SEES the coder read the spec
        self.assertIn("THE CODER ALREADY FETCHED", ev)         # verifier-framed, not the coder-facing "YOU HAVE"

    def test_no_durable_facts_leaves_evidence_as_the_work_log(self):
        loop = self._loop()
        sess = PlanSession(plan=_plan(2))                      # fetched_pages is None → no facts appended
        ev = loop._grounded_evidence(sess, {"messages": []})
        self.assertNotIn("ALREADY FETCHED", ev)


class StuckStepReplanTests(unittest.TestCase):
    """A step advances ONLY on a genuine pass — no advance-on-unverified cap — so a MISCONCEIVED step (a
    confused/category-error step the planner wrote whose checks pass but whose intent the critic keeps
    judging unmet) re-nudges FOREVER (observed live: a step looped 16 min). After STUCK_STEP_REPLAN critic
    fails, _renudge_or_replan hands the living-plan reasoner the real work done to RE-DERIVE the stuck tail.
    Before the fix (plain _renudge), a stuck step's plan NEVER changed; after, it can."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def _sess(self):
        plan = Plan(id="x", task="build it", created="c",
                    items=[PlanItem("step 1", done=True, note="verified"),
                           PlanItem("confused step 2"), PlanItem("step 3")])
        return PlanSession(plan=plan)

    def _loop(self, reasoner):
        ctx = _ctx(_Scripted([_toolcall()]), reasoner)  # coder acts → _work forwards it, no verify churn
        ctx.reasoner_role = self._role()
        return Loop(ctx)

    def test_below_threshold_does_not_replan(self):
        from cria.loop import STUCK_STEP_REPLAN
        loop = self._loop(_Scripted([_replan(["rewritten step 2", "step 3"])]))
        sess = self._sess(); sess.verify_fails = STUCK_STEP_REPLAN - 1
        loop._renudge_or_replan(sess, "k", _body(), "still not done", 2, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items],
                         ["step 1", "confused step 2", "step 3"])   # untouched — just a re-nudge

    def test_at_threshold_rederives_the_stuck_tail_and_resets(self):
        from cria.loop import STUCK_STEP_REPLAN
        loop = self._loop(_Scripted([_replan(["rewritten step 2", "step 3"]), _text("NONE")]))
        sess = self._sess(); sess.verify_fails = STUCK_STEP_REPLAN
        loop._renudge_or_replan(sess, "k", _body(), "still not done", 2, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items],
                         ["step 1", "rewritten step 2", "step 3"])  # stuck step re-derived from ground truth
        self.assertEqual(sess.verify_fails, 0)                       # clean restart on the new step

    def test_at_threshold_unchanged_plan_falls_through_to_renudge(self):
        from cria.loop import STUCK_STEP_REPLAN
        # reasoner re-derives the SAME remaining tail → no change → normal re-nudge (streak NOT reset)
        loop = self._loop(_Scripted([_replan(["confused step 2", "step 3"]), _text("NONE")]))
        sess = self._sess(); sess.verify_fails = STUCK_STEP_REPLAN
        loop._renudge_or_replan(sess, "k", _body(), "still not done", 2, _Rlog())
        self.assertEqual([it.text for it in sess.plan.items], ["step 1", "confused step 2", "step 3"])
        self.assertEqual(sess.verify_fails, STUCK_STEP_REPLAN)       # not reset — the plan didn't move

    def test_gate_real_error_fails_never_replan(self):
        # the gate-fail path (real syntax/lint/test errors) uses plain _renudge, NOT _renudge_or_replan —
        # a real failing check must be FIXED, never re-derived away. Prove the plain path leaves the plan.
        loop = self._loop(_Scripted([_replan(["rewritten step 2", "step 3"])]))
        sess = self._sess(); sess.verify_fails = 9
        loop._renudge(sess, "k", _body(), "SyntaxError line 5", _Rlog())
        self.assertEqual([it.text for it in sess.plan.items],
                         ["step 1", "confused step 2", "step 3"])   # gate errors never trigger a re-derive

    def test_tool_call_thrash_rederives_the_step(self):
        from cria.loop import STEP_THRASH_REPLAN
        # a coder looping on tool calls (never signalling completion) accrues NO verify-fails, so the
        # verify escape can't fire — the acting-turn count is the signal instead.
        loop = self._loop(_Scripted([_replan(["write a flat resolver.py", "step 3"]), _text("NONE")]))
        sess = self._sess(); sess.step_tool_calls = STEP_THRASH_REPLAN
        out = loop._replan_if_thrashing(sess, "k", _body(), 2, _Rlog())
        self.assertIsNotNone(out)                                   # re-derived → fresh drive, not None
        self.assertEqual([it.text for it in sess.plan.items],
                         ["step 1", "write a flat resolver.py", "step 3"])   # over-engineered step simplified

    def test_thrash_below_threshold_forwards_normally(self):
        from cria.loop import STEP_THRASH_REPLAN
        loop = self._loop(_Scripted([_replan(["rewritten", "step 3"])]))
        sess = self._sess(); sess.step_tool_calls = STEP_THRASH_REPLAN - 1
        self.assertIsNone(loop._replan_if_thrashing(sess, "k", _body(), 2, _Rlog()))  # forward the tool call
        self.assertEqual([it.text for it in sess.plan.items], ["step 1", "confused step 2", "step 3"])

    def test_thrash_replan_fires_at_most_once_per_step_no_churn(self):
        # ANTI-CHURN: re-deriving repeatedly on one step position churned the plan (a weak reasoner
        # returns a different tail each call: 11→5→6→9). The one-shot flag stops it after ONE attempt.
        from cria.loop import STEP_THRASH_REPLAN
        loop = self._loop(_Scripted([_replan(["A", "B"])]))
        sess = self._sess()
        sess.thrash_replanned = True                      # already spent this step
        sess.step_tool_calls = STEP_THRASH_REPLAN * 3     # well past the threshold
        self.assertIsNone(loop._replan_if_thrashing(sess, "k", _body(), 2, _Rlog()))  # no second re-derive
        self.assertEqual([it.text for it in sess.plan.items], ["step 1", "confused step 2", "step 3"])


def _done(text="looks done"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def _verdict(done=True, reason="ok", fix=None):
    v = {"done": done, "reason": reason}
    if fix is not None:
        v["proposed_fix"] = fix
    return {"choices": [{"message": {"content": json.dumps(v)}}]}


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

    # The coder-turn guards are module functions (run by the shared _coder_turn); test them with the
    # loop's watched coder_chat — exactly what _coder_turn passes them.
    def _trunc(self, rec, coder, idx, rlog):
        return guard_truncation(coder, _framed(), self._loop(rec)._ctx.coder_chat, rlog, step=idx, phase=f"coder-s{idx}")

    def _rum(self, rec, coder, idx, rlog):
        return guard_rumination(coder, _framed(), self._loop(rec)._ctx.coder_chat, rlog, step=idx, phase=f"coder-s{idx}")

    # -------- truncation guard --------
    def test_truncation_steers_incremental_and_recovers(self):
        rec = _Recorder([_toolcall()])  # the retry succeeds with a clean tool call
        rlog = _Rlog()
        out = self._trunc(rec, _trunc_write(), 4, rlog)
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))       # recovered (retry's call)
        self.assertIn("loop.truncated", rlog.kinds())
        ev = dict(rlog.events)["loop.truncated"]
        self.assertEqual(ev["path"], "h.py")                                  # path parsed from cut-off JSON
        self.assertEqual(ev["output_tokens"], 30675)
        self.assertIn("SMALL pieces", rec.last_user())                        # the incremental-write steer

    def test_truncation_exhausted_refuses_partial_write(self):
        rec = _Recorder([_trunc_write()])  # ALWAYS truncates
        rlog = _Rlog()
        out = self._trunc(rec, _trunc_write(), 4, rlog)
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
        out = self._trunc(rec, trunc_noargs, 2, rlog)
        self.assertEqual(rec.calls, 0)                                        # no write path → no retry
        self.assertIn("loop.truncated_dropped", rlog.kinds())

    # -------- rumination guard --------
    def test_rumination_refocuses_and_recovers(self):
        rec = _Recorder([_toolcall()])
        rlog = _Rlog()
        out = self._rum(rec, _ruminating(), 4, rlog)
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
        self.assertIn("loop.rumination", rlog.kinds())
        self.assertIn("RUMINATION GUARD", rec.last_user())
        self.assertNotIn("cria_rumination", out)                             # internal marker stripped

    def test_rumination_exhausted_normalizes_and_stops(self):
        rec = _Recorder([_ruminating()])  # never focuses
        rlog = _Rlog()
        out = self._rum(rec, _ruminating(), 4, rlog)
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

    def test_work_log_keeps_full_args_and_output_no_clip(self):
        # The completion summary reads the work log; a 200-char clip of args/output would drop the
        # real work before the reasoner ever sees it. Full content flows; the floor bounds the window.
        from cria.loop import _work_log
        body = "z" * 4000                                          # far past the old 200-char clip
        msgs = [
            {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "write_file", "arguments": '{"path":"h.py","content":"' + body + '"}'}}]},
            {"role": "tool", "tool_call_id": "a", "content": "OUTPUT " + body},
        ]
        log = _work_log(msgs)
        self.assertEqual(log.count(body), 2)   # both the args body AND the tool output survive in full
        self.assertNotIn("…", log)

    def test_satisfaction_evidence_includes_summary_after_a_compaction(self):
        # THE false 'no work done': a harness compaction replaces the structured tool history with a
        # ⟦ctx:...⟧ prose summary. _work_log alone is then EMPTY, so the judge hallucinated an empty
        # workspace. _satisfaction_evidence must surface the summary as the record of the built work.
        from cria.loop import _satisfaction_evidence, _work_log
        compacted = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "⟦ctx:continuation⟧ Earlier you built resolve_handle.py, a test "
                                        "suite, and a README; the live check still needs a real run."},
            {"role": "assistant", "content": ""},   # no tool_calls survived the compaction
        ]
        self.assertFalse(_work_log(compacted).strip())            # old evidence: EMPTY → false 'no work'
        ev = _satisfaction_evidence(compacted)
        self.assertIn("resolve_handle.py", ev)                    # the real work is now visible
        self.assertIn("README", ev)
        self.assertIn("SUMMARY OF EARLIER WORK", ev)

    def test_satisfaction_evidence_is_just_the_log_when_uncompacted(self):
        # No summary markers → identical to _work_log (no spurious header).
        from cria.loop import _satisfaction_evidence, _work_log
        msgs = [{"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "write_file", "arguments": '{"path":"h.py"}'}}]},
                {"role": "tool", "tool_call_id": "a", "content": "wrote h.py"}]
        self.assertEqual(_satisfaction_evidence(msgs), _work_log(msgs))
        self.assertNotIn("SUMMARY OF EARLIER WORK", _satisfaction_evidence(msgs))


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

    def test_plan_on_red_gate_records_last_gate_red(self):
        # H2: a RED step-gate on the MULTI-STEP (plan-ON) path must record sess.last_gate_red — the field
        # the anti-laundering rollup override + vacuous-green evidence read. It was permanently False on
        # plan-ON (set only by the plan-off readers), leaving those ground-truth guards dead.
        ws = self._ws()
        coder = _Recorder([_toolcall(), _done(), _toolcall()])
        loop = Loop(_ctx(coder, _Scripted([_verdict(True)]), _plan(2), workspace_root=ws))  # 2 items → plan-ON
        rlog = _Rlog()
        loop.drive(_body(), "k", _Classification(), rlog)                     # act on step 1
        c2 = loop.drive(_body(), "k", _Classification(), rlog)                # claim done → step gate probe
        loop.drive(_body_with_probe(_tc_id(c2), self._gate_result(floor_exit=1)),
                   "k", _Classification(), rlog)                             # RED (SyntaxError)
        self.assertTrue(loop._store.get("k").last_gate_red)                   # recorded (was permanently False)

    def test_plan_on_periodic_gate_fires_in_a_long_step(self):
        # M2: a plan-ON step where the coder keeps ACTING with DISTINCT edits (never repeating, never
        # claiming done) must get a periodic check-in after GATE_EVERY_CODER_TURNS acting turns — this
        # was plan-off-only, so a long step editing many different things got no proactive ground truth.
        # (Distinct actions on purpose: identical ones would trip the repetition guard instead.)
        from cria.loop import GATE_EVERY_CODER_TURNS

        def _distinct(i):  # a unique shell action each turn → no repetition/wheel-spin, just steady work
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": f"c{i}", "type": "function", "function": {"name": "shell",
                 "arguments": json.dumps({"command": ["sh", "-c", f"echo edit-{i} >> note{i}.txt"]})}}]}}]}
        ws = self._ws()
        coder = _Recorder([_distinct(i) for i in range(GATE_EVERY_CODER_TURNS + 2)])
        loop = Loop(_ctx(coder, _Scripted([_verdict(True)]), _plan(2), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(GATE_EVERY_CODER_TURNS + 1):
            loop.drive(_body(), "k", _Classification(), rlog)
        self.assertIn("loop.periodic_gate", rlog.kinds())

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
        self.assertTrue(any("⟦ctx:rollup⟧" in str(m.get("content")) for m in out))

    def test_rollup_is_grounded_by_the_real_gate_state(self):
        # a summary that LAUNDERS an unverified "tests pass" claim is overridden by cria's real last
        # check state, appended to the rolling briefing so the coder can't trust the false claim.
        from cria.loop import Loop, PlanSession
        from dataclasses import replace

        def reasoner(body, rlog):
            return json.dumps({"choices": [{"message": {"content": "all 7 tests now pass"}}]}).encode()

        ctx = replace(_ctx(coder=None, reasoner=reasoner), trigger_compaction=100)
        sess = PlanSession(plan=_plan(1))
        sess.last_gate_red = True
        sess.last_gate_flag = "⟦ctx:checks⟧ test_x.py:1: AssertionError: 400 != 200"
        big = [{"role": "system", "content": "sys"}] + [{"role": "assistant", "content": "y" * 1000} for _ in range(50)]
        rollup = next(m["content"] for m in Loop(ctx)._self_compact(big, sess, 1, _Rlog())
                      if "⟦ctx:rollup⟧" in str(m.get("content")))
        self.assertIn("all 7 tests now pass", rollup)    # the laundered claim is still there...
        self.assertIn("currently FAIL", rollup)          # ...but so is the real gate state, which wins
        self.assertIn("400 != 200", rollup)


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
        self.assertTrue(gs.last_gate_red)                      # RED → the satisfaction judge is gated off

    def _armed(self, ws):
        from cria.loop import GuardState, guard_periodic_gate
        gs = GuardState(coder_turns=15)
        guard_periodic_gate(gs, self._SHELL, _Rlog(), workspace_root=ws)
        return gs

    def test_clean_result_clears_last_gate_red(self):
        import tempfile, os
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        from cria.loop import guard_periodic_result
        ws = tempfile.mkdtemp(); open(os.path.join(ws, "x.py"), "w").write("print(1)\n")
        gs = self._armed(ws); gs.last_gate_red = True          # a prior red
        result = f'{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n'     # ran, no findings → GREEN
        body = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id, "content": result}]}
        self.assertIsNone(guard_periodic_result(gs, body, _Rlog()))   # stays silent on a pass
        self.assertFalse(gs.last_gate_red)                     # GREEN → judge may run again

    def test_couldnt_run_leaves_last_gate_red_unchanged(self):
        from cria.loop import GuardState, guard_periodic_result
        gs = GuardState(periodic_probe=True, probe_call_id="p1", last_gate_red=True)  # gate_plan None → couldn't run
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "meh"}]}
        self.assertIsNone(guard_periodic_result(gs, body, _Rlog()))
        self.assertTrue(gs.last_gate_red)                      # neutral non-signal must NOT flip the gate


class GateProgressTrackingTests(unittest.TestCase):
    """Plan-off gate-progress tracking — the same-finding stall that drives the reasoned thrash-assist.
    There is NO stall terminator: cria never ends a non-converging session by handing back to a human;
    a persistent RED keeps driving the unstick steers (mission: the model succeeds on its own)."""

    def test_stall_grows_on_the_same_finding_resets_on_change_or_green(self):
        from cria.loop import GuardState, track_gate_progress
        gs = GuardState()
        track_gate_progress(gs, "err A"); self.assertEqual(gs.gate_stall, 1)
        track_gate_progress(gs, "err A"); self.assertEqual(gs.gate_stall, 2)   # same finding → stall grows
        track_gate_progress(gs, "err B"); self.assertEqual(gs.gate_stall, 1)   # changed → stall resets
        track_gate_progress(gs, "")                                            # GREEN → reset
        self.assertEqual((gs.gate_stall, gs.gate_sig), (0, ""))

    def test_couldnt_run_gate_does_not_advance_the_stall(self):
        from cria.loop import GuardState, guard_periodic_result
        gs = GuardState(periodic_probe=True, probe_call_id="p1", gate_stall=2)  # gate_plan None → couldn't run
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "x"}]}
        guard_periodic_result(gs, body, _Rlog())
        self.assertEqual(gs.gate_stall, 2)      # neutral non-signal → stall unchanged


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
        with open(os.path.join(t, "handler.py"), "w") as f:
            f.write("def handle():\n    return 1\n")   # the file _VaryingWriter churns — real on disk for the steer
        return t

    def test_five_rewrites_trigger_a_spin_probe_and_reasoner_authors_the_steer(self):
        from cria.loop import WHEEL_SPIN_WRITES
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        captured = {}

        class _Reasoner:                           # the wheel-spin is now REASONED, not canned
            def __call__(self, body, rlog):
                captured["user"] = body["messages"][-1]["content"]
                return json.dumps({"choices": [{"message": {"content":
                    "Read handler.py as it stands on disk and run the failing check to see the real error."}}]}).encode()

        coder = _VaryingWriter()                   # rewrites handler.py forever (content varies)
        loop = Loop(_ctx(coder, _Reasoner(), _plan(1), workspace_root=ws))
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
        # gate result: failing checks → REASONER authors the grounded steer → inserted into the coder's next turn
        result = (f"{P}probe-0{S}\n  File \"x.py\", line 3\nSyntaxError: bad\nEXIT:1\n"
                  f"{P}git{S}\nabc\n")
        nxt = loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        self.assertIn("Read handler.py", coder.last_user())   # the reasoner's grounded words, not a canned template
        # ...and the reasoner SAW the wheel-spin trigger, the churned file, and the ground truth
        self.assertIn("handler.py", captured["user"])
        self.assertIn("SyntaxError", captured["user"])
        self.assertNotIn("loop.step_done", rlog.kinds())   # inserted, never judged
        self.assertIn("loop.spin_probe_result", rlog.kinds())

    def test_probe_steer_labels_which_guard_fired(self):
        # The ⟦cria⟧ note must say WHICH guard steered the coder, not just "a guard" — so a
        # wheel-spin steer and a repetition redirect are distinguishable in the scrollback.
        from cria.loop import GuardState, guard_probe_steer, CANNED
        rlog = _Rlog()
        # wheel-spin probe resolving → labels "wheel-spin guard"
        gs = GuardState(spin_probe=True, probe_call_id="p1", spin_path="x.py")
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "EXIT:0"}]}
        self.assertIsNotNone(guard_probe_steer(gs, body, rlog, author=CANNED))
        self.assertEqual(gs.steer_source, "wheel-spin guard")
        # repetition redirect resolving (canned, no author) → labels "repetition guard"
        gs2 = GuardState(redirect_probe=True, probe_call_id="p2", repeat_action="write_file(h.py)")
        body2 = {"messages": [{"role": "tool", "tool_call_id": "p2", "content": "EXIT:0"}]}
        steer = guard_probe_steer(gs2, body2, rlog, author=CANNED)
        self.assertIn("[REDIRECT]", steer)
        self.assertEqual(gs2.steer_source, "repetition guard")

    def test_clean_gate_lets_the_reasoner_judge_without_canned_editorializing(self):
        # Round-6 lives on: a content-blind streak can't tell a spiral from honest edits (applying review
        # findings one by one). So there's no canned "the problem is elsewhere" steer — the reasoner is
        # handed the CLEAN ground truth + the real session and DECIDES. Here it judges the coder fine
        # (ON_TRACK); we fall back to inserting the clean FACT, never an "elsewhere" editorialization.
        from cria.loop import WHEEL_SPIN_WRITES
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        ws = self._ws()
        captured = {}

        class _Reasoner:
            def __call__(self, body, rlog):
                captured["user"] = body["messages"][-1]["content"]
                return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

        coder = _VaryingWriter()
        loop = Loop(_ctx(coder, _Reasoner(), _plan(1), workspace_root=ws))
        rlog = _Rlog()
        for _ in range(WHEEL_SPIN_WRITES):
            loop.drive(_body(), "k", _Classification(), rlog)
        gate = loop.drive(_body(), "k", _Classification(), rlog)
        result = f"{P}probe-0{S}\nEXIT:0\n{P}git{S}\nabc\n"
        loop.drive(_body_with_probe(_tc_id(gate), result), "k", _Classification(), rlog)
        # the reasoner SAW the clean ground truth, free of any "elsewhere" premise it could parrot
        self.assertIn("no error-class", captured["user"].lower())
        self.assertNotIn("elsewhere", captured["user"].lower())
        # ON_TRACK → the canned FACT is inserted (states the clean result), never an editorializing steer
        msg = coder.last_user()
        self.assertNotIn("all pass", msg.lower())         # no overclaimed verified/done state
        self.assertNotIn("elsewhere", msg.lower())        # no false "look elsewhere" steer
        self.assertIn("loop.spin_probe_result", rlog.kinds())

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


class SteerVerdictTests(unittest.TestCase):
    """The "fine, no help" verdict is the POSITIVE sentinel ON_TRACK (the old NOT_STUCK was a negation
    trap a weak reasoner emitted for the WRONG reason — "the coder is NOT progressing → NOT_STUCK" —
    vetoing its own rescue while looping). A verbose reasoner (Fabliq) also HEDGES: it writes the verdict
    token and then a real grounded directive; the old prefix check discarded the whole reply, silently
    dropping good steers (observed: 7 redirects delivered NOTHING). _steer_or_none must strip the verdict
    token + scaffolding and deliver the directive, treating the verdict as final only when essentially
    nothing else follows."""

    def test_on_track_veto_is_recognized(self):
        # the new positive sentinel must be honored as a veto — before the consumer knew ON_TRACK it
        # would have been delivered as an 8-char "directive", steering the coder with the veto word.
        from cria.loop import _steer_or_none
        self.assertIsNone(_steer_or_none("ON_TRACK"))
        self.assertIsNone(_steer_or_none("ON_TRACK </think> ON_TRACK"))

    def test_hedged_directive_is_delivered_not_discarded(self):
        from cria.loop import _steer_or_none
        t = "ON_TRACK You are stuck fetching the spec; the endpoint is GET /handles/{handle} — stop fetching, write the resolver now."
        out = _steer_or_none(t)
        self.assertIsNotNone(out)
        self.assertIn("/handles/{handle}", out)
        self.assertNotIn("ON_TRACK", out)

    def test_legacy_not_stuck_verdict_still_vetoes(self):
        from cria.loop import _steer_or_none
        self.assertIsNone(_steer_or_none("NOT_STUCK"))            # back-compat
        self.assertIsNone(_steer_or_none("NOT_STUCK </think> NOT_STUCK"))
        self.assertIsNone(_steer_or_none(""))

    def test_clean_directive_without_prefix_still_delivers(self):
        from cria.loop import _steer_or_none
        self.assertIn("write", _steer_or_none("You keep repeating; read the file then write the fix.") or "")


class CoderToolsSummaryTests(unittest.TestCase):
    """The steer reasoner is blind to the coder's tools, so it can't say 'run grep via exec_command' —
    the coder wavered on whether it could grep with exec_command right there. Give the reasoner the list."""

    def test_lists_tools_and_flags_the_shell(self):
        from cria.loop import _coder_tools_summary
        tools = [{"function": {"name": "read_file", "parameters": {"properties": {"path": {}, "start_line": {}}}}},
                 {"function": {"name": "exec_command", "parameters": {"properties": {"cmd": {}}}}}]
        out = _coder_tools_summary(tools)
        self.assertIn("read_file(path, start_line)", out)
        self.assertIn("exec_command(cmd)", out)
        self.assertIn("grep", out.lower())              # the shell tool is flagged as running grep/…
        self.assertIn("none advertised", _coder_tools_summary([]))

    def test_verdict_nudge_appends_proposed_fix_only_when_not_done(self):
        """A NOT-done verdict hands the coder the concrete proposed_fix (an action), not just a
        diagnosis; a DONE verdict drops it (nothing to fix). Empty fields degrade cleanly."""
        from cria.loop import _verdict_nudge
        not_done = {"done": False, "reason": "never grepped the spec", "proposed_fix": 'grep -n "/holders" spec.json'}
        out = _verdict_nudge(not_done, False)
        self.assertIn("never grepped the spec", out)
        self.assertIn('Proposed fix: grep -n "/holders" spec.json', out)
        # DONE → the fix is meaningless, dropped
        self.assertEqual(_verdict_nudge({"done": True, "reason": "ok", "proposed_fix": "x"}, True), "ok")
        # missing/empty proposed_fix → just the reason, no dangling label
        self.assertEqual(_verdict_nudge({"reason": "r"}, False), "r")
        self.assertEqual(_verdict_nudge({"reason": "r", "proposed_fix": ""}, False), "r")
        # only a fix, no reason → still surfaced
        self.assertEqual(_verdict_nudge({"proposed_fix": "do X"}, False), "Proposed fix: do X")

    def test_critic_prompts_declare_reason_and_proposed_fix(self):
        # BOTH the step critic (verify) and the task critic (satisfaction) must define "reason"
        # (anti-parrot) and ask for "proposed_fix" in the reply schema.
        from cria import prompts
        for name in ("verify", "satisfaction"):
            p = prompts.load(name)
            self.assertIn('"reason" is your SPECIFIC finding', p, name)   # reason DEFINED
            self.assertIn('"proposed_fix"', p, name)                      # field asked for
            self.assertIn("proposed_fix", p.splitlines()[-1], name)       # in the reply schema line

    def test_summarize_prepends_coder_tools_when_given(self):
        """Every reasoner that reasons about the coder's session opts in via summarize(coder_tools=…);
        the fragment must land IN the user message the reasoner sees (not silently dropped)."""
        import json
        from cria.loop import summarize
        seen = {}

        def fake_chat(call, rlog):
            seen["user"] = call["messages"][1]["content"]
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

        summarize(fake_chat, None, "sys", "THE-TASK", _Rlog(), retry_off=False,
                  coder_tools="  - exec_command(cmd) — runs ANY shell command")
        self.assertIn("TOOLS THE CODER HAS", seen["user"])
        self.assertIn("exec_command(cmd)", seen["user"])
        self.assertIn("THE-TASK", seen["user"])          # the real prompt still follows
        # ...and omitted by default (compaction/summarization callers must not get it)
        summarize(fake_chat, None, "sys", "THE-TASK", _Rlog(), retry_off=False)
        self.assertNotIn("TOOLS THE CODER HAS", seen["user"])


class FetchGroundTruthTests(unittest.TestCase):
    """runG: the coder fetched api.handle.me/openapi.json (HTTP 200, 33 endpoints) but hallucinated a
    400 and searched 40x; the steer PARROTED the 400. _fetch_ground_truth extracts the real outcomes so
    the steer author can't miss that the fetch succeeded — separating result from narration."""

    def _fgt(self, messages):
        from cria.loop import _fetch_ground_truth
        return _fetch_ground_truth(messages)

    def test_extracts_status_and_endpoints_from_the_real_result(self):
        result = ("HTTP 200 OK · https://api.handle.me/openapi.json\nContent-Type: application/json\n"
                  "[structured doc] [API endpoints (3): /handles/{handle}, /holders/{address}, /stats]\n...")
        out = self._fgt([{"role": "user", "content": "resolve a handle"},
                         {"role": "tool", "content": result}])
        self.assertIn("https://api.handle.me/openapi.json", out)
        self.assertIn("HTTP 200", out)
        self.assertIn("/handles/{handle}", out)
        self.assertIn("trust these", out.lower())

    def test_ignores_a_hallucinated_status_in_prose(self):
        # The coder's narration ("returned HTTP 400 Bad Request") has no ` · <url>` → not a real result.
        out = self._fgt([{"role": "assistant",
                          "content": "The fetch returned an HTTP 400 Bad Request, so I could not read it."}])
        self.assertEqual(out, "")

    def test_last_status_per_url_wins(self):
        msgs = [{"role": "tool", "content": "HTTP 500 err · https://x.test/openapi.json"},
                {"role": "tool", "content": "HTTP 200 OK · https://x.test/openapi.json [API endpoints (1): /a]"}]
        out = self._fgt(msgs)
        self.assertIn("HTTP 200", out)
        self.assertNotIn("HTTP 500", out)

    def test_no_fetches_yields_empty(self):
        self.assertEqual(self._fgt([{"role": "user", "content": "just do the task"}]), "")

    def test_durable_facts_survive_after_the_result_is_floored_out(self):
        # runJ: the openapi.json result scrolls out of the window before the late spiral-steer fires.
        # _track_fetched_pages persists it on the session so _fetch_ground_truth still cites it.
        from cria.loop import _fetch_ground_truth, _track_fetched_pages, GuardState
        gs = GuardState()
        early = [{"role": "tool", "content": "HTTP 200 OK · https://api.handle.me/openapi.json "
                                             "[API endpoints (2): /handles/{handle}, /holders/{address}]"}]
        _track_fetched_pages(gs, early)
        # a LATER body no longer contains that result (floored out) — only a Windows-handle search
        later = [{"role": "assistant", "content": "searching GetHandleInformation hObject flags"}]
        out = _fetch_ground_truth(later, gs)
        self.assertIn("api.handle.me/openapi.json", out)   # still cited from the durable store
        self.assertIn("/handles/{handle}", out)

    def test_in_window_status_wins_over_stale_durable(self):
        from cria.loop import _fetch_ground_truth, _track_fetched_pages, GuardState
        gs = GuardState()
        _track_fetched_pages(gs, [{"role": "tool", "content": "HTTP 500 err · https://x.test/openapi.json"}])
        fresh = [{"role": "tool", "content": "HTTP 200 OK · https://x.test/openapi.json [API endpoints (1): /a]"}]
        out = _fetch_ground_truth(fresh, gs)
        self.assertIn("HTTP 200", out)
        self.assertNotIn("HTTP 500", out)

    def test_a_later_find_fetch_does_not_clobber_the_endpoint_list(self):
        # runK: the outline (endpoints) is captured once; a later web_fetch(find="paths") returns a
        # sub-section with NO outline. The endpoints must survive (they name /handles/{handle}).
        from cria.loop import _fetch_ground_truth, _track_fetched_pages, GuardState
        gs = GuardState()
        _track_fetched_pages(gs, [{"role": "tool", "content":
            "HTTP 200 OK · https://api.handle.me/openapi.json [API endpoints (2): /handles/{handle}, /holders/{address}]"}])
        # a subsequent find-fetch of the same URL, no outline this time
        _track_fetched_pages(gs, [{"role": "tool", "content": "HTTP 200 OK · https://api.handle.me/openapi.json (paths section)"}])
        out = _fetch_ground_truth([], gs)
        self.assertIn("/handles/{handle}", out)   # endpoints preserved, not clobbered
        self.assertIn("/holders/{address}", out)


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
        # ...and the reasoner SAW the evidence: the trigger, the repeated action, the session, ground truth
        self.assertIn("WHAT TRIPPED THE DETECTOR", captured["user"])
        self.assertIn("THE CODING SESSION SO FAR", captured["user"])
        self.assertIn("write_file", captured["user"])
        self.assertIn("SyntaxError", captured["user"])

    def test_redirect_prompt_does_not_order_a_look_elsewhere_steer(self):
        # Round-7: de-editorializing the code-side fact was nullified because the reasoner's SYSTEM
        # prompt still ordered "say the problem is NOT in the file". The unified steer prompt must not
        # instruct any where-the-problem-is claim on a clean gate.
        from cria import prompts
        txt = prompts.load("steer_diagnose").lower()
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

    def test_careful_reasoning_verdict_completes_the_step(self):
        # The reasoning-ON pass lands a clean verdict → the step advances normally (the trusted path).
        coder = _Scripted([_done()])
        reasoner = _Scripted([_verdict(True)])
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "sid:v", _Classification(), rlog)                           # work → done → PROBE
        c2 = loop.drive(_body_with_probe(_tc_id(c1), "PROBE_EXIT=0"), "sid:v", _Classification(), rlog)  # probe clean → verify → done
        self.assertIn("plan complete", c2["choices"][0]["message"]["content"])  # 1-step plan → completes this turn
        self.assertIn("loop.step_done", rlog.kinds())

    def test_reasoning_off_retry_cannot_advance_the_step(self):
        # THE both-paths mirror of the satisfaction fail-close: careful pass unparseable, reasoning-off
        # retry says done=true → FAIL CLOSED (a rubber-stamp can't approve). The step does NOT complete;
        # the loop re-nudges instead.
        coder = _Scripted([_done()])
        reasoner = _Scripted([_unparseable(), _verdict(True)])   # unparseable careful pass, then a reasoning-off "done"
        loop = Loop(_ctx(coder, reasoner, _plan(1)))
        rlog = _Rlog()
        c1 = loop.drive(_body(), "sid:v", _Classification(), rlog)                           # work → done → PROBE
        c2 = loop.drive(_body_with_probe(_tc_id(c1), "PROBE_EXIT=0"), "sid:v", _Classification(), rlog)  # probe clean → verify → FAIL CLOSED
        self.assertNotIn("plan complete", c2["choices"][0]["message"].get("content") or "")  # did NOT complete
        self.assertIn("loop.verify_failclosed", rlog.kinds())
        self.assertNotIn("loop.step_done", rlog.kinds())

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

    def test_closing_never_hands_back_untrusted_work(self):
        # The accept-unverified / "N steps did NOT pass — needs review" HANDBACK was removed: a step
        # advances ONLY on a genuine pass (the loop re-nudges indefinitely otherwise), so _closing is
        # always a clean completion — cria never ends a plan by surfacing untrusted work to a human.
        plan = Plan(id="x", task="t", created="c", items=[
            PlanItem("Create handler.py", done=True, note="verified"),
            PlanItem("Run pytest", done=True, note="verified"),
        ])
        msg = self._loop()._closing(PlanSession(plan=plan))
        self.assertIn("plan complete", msg)
        self.assertNotIn("did NOT pass", msg)
        self.assertNotIn("needs review", msg)


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
    def test_keeps_task_as_history_step_is_active_directive(self):
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
        self.assertIn("Do ONLY this step", blob)            # step framing = the ACTIVE directive
        self.assertIn("Create handler.py", blob)
        # the WHOLE task is kept as HISTORY (background context — every requirement), NOT replaced
        self.assertIn("unit tests", blob)
        self.assertIn("README", blob)
        # …and acknowledged as decomposed, so it reads as the goal, not a fresh do-it-all ask
        from cria import prompts
        self.assertIn(prompts.load("plan_ack")[:30], blob)
        # the ACTIVE ask (last user turn) is the step, not the whole task
        self.assertEqual(framed[-1]["role"], "user")
        self.assertIn("Create handler.py", framed[-1]["content"])
        self.assertNotIn("README", framed[-1]["content"])

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
        self.assertIn("Build the whole feature", blob)      # the raw task is KEPT as history (the overall goal)
        self.assertEqual(sum(1 for m in framed if m["role"] == "system"), 1)  # exactly one system msg


class VerifyEvidenceTests(unittest.TestCase):
    """The per-step critic (_verify) now judges on the ACTION LOG (_work_log) — the coder's tool CALLS
    AND their results, not results alone — so it can see 'searched but never fetched the real docs' and
    refuse a research step done from a guess, not just check that a file exists."""

    def test_action_log_shows_the_calls_not_just_results(self):
        # THE point of the change: a research step that only SEARCHED (never web_fetch-ed) is visible.
        from cria.loop import _work_log
        msgs = [
            {"role": "assistant", "tool_calls": [{"function": {"name": "web_search", "arguments": '{"query":"ADA Handle API"}'}}]},
            {"role": "tool", "content": "19 results: generic snippets, no endpoint"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "write_file", "arguments": '{"path":"r.py"}'}}]},
            {"role": "tool", "content": "wrote r.py"},
        ]
        log = _work_log(msgs)
        self.assertIn("$ web_search", log)          # the CALL is in the evidence now
        self.assertIn("$ write_file", log)
        self.assertNotIn("web_fetch", log)          # …and its ABSENCE is visible → research not obtained

    def test_excludes_probe_and_empty_keeps_coder_runs(self):
        from cria.loop import _work_log
        msgs = [
            {"role": "tool", "content": "--- cria probe ---\nPROBE_EXIT=0"},   # cria's probe output
            {"role": "tool", "content": ""},                                    # empty
            {"role": "tool", "content": "3 passed, 0 failed in 0.12s"},         # coder's own test run
        ]
        ev = _work_log(msgs)
        self.assertIn("3 passed", ev)          # the coder's real run is the evidence
        self.assertNotIn("PROBE_EXIT", ev)     # cria's probe excluded

    def test_keeps_all_runs_in_full_no_clip_no_last_n_drop(self):
        # The critic must see the FULL ground truth: every coder run (not just the last 3) and each
        # in full (no clip). A per-site slice here would be a lie the critic can't detect.
        from cria.loop import _work_log
        big = "FAILED test_x " + ("y" * 5000)
        msgs = [{"role": "tool", "content": f"run {i} {big}"} for i in range(8)]
        ev = _work_log(msgs)
        for i in range(8):
            self.assertIn(f"run {i}", ev)
        self.assertIn("y" * 5000, ev)
        self.assertNotIn("…", ev)


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

    def test_guard_truncation_refuses_self_truncated_write(self):
        # The model cut its OWN write_file off mid-content: finish_reason is "tool_calls" (NOT
        # "length", so is_truncated never sees it), and the `content` string is unclosed with an
        # invalid `\'` escape — exactly the api.handle.me run that wrote a broken resolver.py.
        # cria must NOT lower the partial to disk; it drops the call so the turn gates on truth.
        from cria.loop import guard_truncation
        raw = r'{"path":"/x/resolver.py","content":"print(f\"hi\")\n    print(f\"a: {r[\'k'  # cut off mid-f-string
        trunc = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "w1", "function": {"name": "write_file", "arguments": raw}}]}, "finish_reason": "tool_calls"}]}
        calls = []

        def coder_chat(body, rlog):  # must NOT be called — this isn't a length-cap retry
            calls.append(1)
            return b"{}"

        rlog = _Rlog()
        out = guard_truncation(dict(trunc), {"messages": [], "tools": None}, coder_chat, rlog)
        self.assertEqual(calls, [])                                             # no incremental-write retry
        self.assertFalse(out["choices"][0]["message"].get("tool_calls"))       # partial write refused
        self.assertIn("loop.incomplete_tool_call_dropped", rlog.kinds())

    def test_guard_truncation_refuses_a_self_truncated_exec_command(self):
        # NOT write-only: a self-truncated exec_command (inline python leaked the model's
        # <|tool_call_end|> dialect token mid-string → unparseable args) must be refused too, else it
        # reaches the harness as "failed to parse function arguments" every turn (observed: 564×).
        from cria.loop import guard_truncation
        raw = '{"cmd": "python3 -c \\"import json; data=json.load(open(\'<|tool_call_end|>'
        trunc = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "e1", "function": {"name": "exec_command", "arguments": raw}}]}, "finish_reason": "tool_calls"}]}
        out = guard_truncation(dict(trunc), {"messages": [], "tools": None}, lambda b, r: None, _Rlog())
        self.assertFalse(out["choices"][0]["message"].get("tool_calls"))       # partial exec refused


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

    def test_track_repetition_matches_through_pipe_and_redirect_jitter(self):
        # The api.handle.me incident: the SAME failing command re-run with output-plumbing jitter
        # (`2>&1`, `| head -n 5`) must still trip at the 3rd call, not scatter into separate
        # signatures and fire ~16 calls late. Plumbing (cd/head/redirects) is boilerplate now.
        from cria.loop import GuardState, guard_track_repetition
        gs = GuardState()
        D = "/home/jesse/src/codex.test.site"
        variants = [
            f"cd {D} && git log --oneline -5",
            f"cd {D} && git log --oneline -5 2>&1",
            f"cd {D} && git log --oneline -5 2>&1 | head -n 5",
        ]
        for cmd in variants:
            guard_track_repetition(gs, self._tc("exec_command", json.dumps({"cmd": cmd})), _Rlog())
        self.assertTrue(gs.redirect_due)  # tripped by the 3rd variant, despite the pipe/redirect jitter

    def test_track_repetition_does_not_merge_distinct_shell_commands(self):
        # Stripping plumbing must not over-merge genuinely different commands into one hunt.
        from cria.loop import GuardState, guard_track_repetition
        gs = GuardState()
        D = "/home/jesse/src/codex.test.site"
        for cmd in [f"cd {D} && git log --oneline -5", f"cd {D} && ls -la", f"cd {D} && git rev-parse --show-toplevel"]:
            guard_track_repetition(gs, self._tc("exec_command", json.dumps({"cmd": cmd})), _Rlog())
        self.assertFalse(gs.redirect_due)  # three DIFFERENT commands → not a spin

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
        from cria.loop import GuardState, guard_probe_steer, CANNED
        gs = GuardState(); gs.spin_probe = True; gs.spin_path = "h.py"; gs.probe_call_id = "p1"
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "PROBE_EXIT=0"}]}
        steer = guard_probe_steer(gs, body, _Rlog(), author=CANNED)  # explicit CANNED (no reasoner)
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

    def test_gate_verdict_sets_last_gate_red_from_the_result(self):
        import tempfile, os
        from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
        from cria.loop import GuardState, guard_gate_op, guard_gate_verdict
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "h.py"), "w").write("def f():\n    return 1\n")
            body = {"tools": [{"type": "function", "function": {"name": "shell",
                     "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}],
                    "messages": [{"role": "user", "content": f"<environment_context><cwd>{tmp}</cwd></environment_context>"}]}
            gs = GuardState(); guard_gate_op(gs, body, _Rlog())
            red = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id,
                                 "content": f'{P}probe-0{S}\n  File "h.py", line 1\nSyntaxError: bad\nEXIT:1\n{P}git{S}\nz\n'}]}
            self.assertIsNotNone(guard_gate_verdict(gs, red, _Rlog()))
            self.assertTrue(gs.last_gate_red)               # a failing done-gate → RED
            clean = {"messages": [{"role": "tool", "tool_call_id": gs.probe_call_id,   # reuse the same plan
                                   "content": f'{P}probe-0{S}\nEXIT:0\n{P}git{S}\nz\n'}]}
            self.assertIsNone(guard_gate_verdict(gs, clean, _Rlog()))
            self.assertFalse(gs.last_gate_red)              # ran and clean → GREEN

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
        self.assertNotIn("all pass", truth.lower())            # not a false "pass"/"done" verdict
        # and NO "but correctness/behaviour might still be wrong / doesn't mean done" doubt-hedge
        self.assertNotIn("not a verdict", truth.lower())
        self.assertNotIn("mean the task is done", truth.lower())
        self.assertNotIn("still wrong", truth.lower())

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
        from cria.loop import GuardState, guard_probe_steer, CANNED
        gs = GuardState(); gs.spin_probe = True; gs.spin_path = "handle_api.py"; gs.probe_call_id = "p1"
        gs.gate_plan = None  # → outcome.ran False → guard_ground_truth "" → spin_no_truth path
        body = {"messages": [{"role": "tool", "tool_call_id": "p1", "content": "x"}]}
        steer = guard_probe_steer(gs, body, _Rlog(), author=CANNED)
        self.assertIsNotNone(steer)
        self.assertIn("handle_api.py", steer)
        self.assertIn("different next action", steer.lower())
        self.assertNotIn("pass", steer.lower())


class UnifiedSteerAuthorTests(unittest.TestCase):
    """ONE reasoned author (author_steer) behind EVERY detector: repetition / wheel-spin / thrash /
    flail all route through it, grounded in the real session + churned files + checks. It may reply
    ON_TRACK (a false-positive trigger) → the caller injects nothing."""

    def _gs(self):
        from cria.loop import GuardState
        gs = GuardState(probe_call_id="p1", spin_path="x.py", repeat_action="write_file x.py", gate_stall=3)
        gs.recent_writes = []
        return gs

    def _chat(self, content):
        return lambda b, r: json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def test_every_condition_yields_the_reasoners_directive_when_stuck(self):
        import tempfile
        from cria.loop import author_steer
        from cria.probegate import GateOutcome
        gs, ws = self._gs(), tempfile.mkdtemp()
        for cond in ("repetition", "wheel_spin", "thrash", "flail"):
            out = author_steer(self._chat("read the real file and run the failing test"), None, ws, gs,
                               {"messages": []}, _Rlog(), condition=cond, outcome=GateOutcome(ran=False),
                               reasoning_window=["keep guessing at the attr"])
            self.assertIn("read the real file", out, cond)

    def test_on_track_reply_suppresses_the_steer(self):
        import tempfile
        from cria.loop import author_steer
        gs, ws = self._gs(), tempfile.mkdtemp()
        self.assertIsNone(author_steer(self._chat("ON_TRACK"), None, ws, gs,
                                       {"messages": []}, _Rlog(), condition="wheel_spin"))
        self.assertIsNone(author_steer(self._chat("NOT_STUCK"), None, ws, gs,  # legacy still vetoes
                                       {"messages": []}, _Rlog(), condition="wheel_spin"))

    def test_empty_reasoner_reply_is_none(self):
        import tempfile
        from cria.loop import author_steer
        gs, ws = self._gs(), tempfile.mkdtemp()
        self.assertIsNone(author_steer(self._chat(""), None, ws, gs,
                                       {"messages": []}, _Rlog(), condition="thrash"))

    def test_trigger_slots_the_grounded_per_condition_signal(self):
        import tempfile
        from cria.loop import author_steer
        gs, ws = self._gs(), tempfile.mkdtemp()
        seen = {}

        def cap(b, r):
            seen["u"] = b["messages"][-1]["content"]
            return json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()

        author_steer(cap, None, ws, gs, {"messages": []}, _Rlog(), condition="wheel_spin")
        self.assertIn("x.py", seen["u"])          # spin_path names the churned file
        author_steer(cap, None, ws, gs, {"messages": []}, _Rlog(), condition="thrash")
        self.assertIn("3 rounds", seen["u"])       # gate_stall count is in the trigger

    def test_session_drops_harness_frame_but_keeps_the_real_turns(self):
        # The serialized session handed to the reasoner must NOT carry the harness's own agent prompt
        # (Codex ships ~7.8K tokens of update_plan/apply_patch/planning boilerplate — a full quarter of
        # the steer prompt, and pure noise to a reasoner with its own supervisor prompt). It's the same
        # drop _frame_for_item does for the coder. Every real user/assistant/tool turn stays verbatim.
        import tempfile
        from cria.loop import author_steer
        gs, ws = self._gs(), tempfile.mkdtemp()
        body = {"messages": [
            {"role": "system", "content": "You are a coding agent running in the Codex CLI. Use update_plan and apply_patch."},
            {"role": "developer", "content": "High-quality plans Example 1: Add CLI entry"},
            {"role": "user", "content": "# AGENTS.md instructions\n<INSTRUCTIONS> my project rules </INSTRUCTIONS>\n<environment_context><cwd>/repo</cwd></environment_context>"},
            {"role": "user", "content": "Resolve an Ada Handle to a Cardano address."},
            {"role": "assistant", "content": "web_fetch swagger.json"},
            {"role": "tool", "content": "HTTP 200 OK swagger schema Handle"},
        ]}
        seen = {}

        def cap(b, r):
            seen["u"] = b["messages"][-1]["content"]
            return json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()

        author_steer(cap, None, ws, gs, body, _Rlog(), condition="wheel_spin")
        u = seen["u"]
        self.assertNotIn("Codex CLI", u)            # harness agent prompt GONE
        self.assertNotIn("update_plan", u)          # its tool boilerplate GONE
        self.assertNotIn("High-quality plans", u)   # developer boilerplate GONE
        self.assertNotIn("<INSTRUCTIONS>", u)       # env-context user block REFRAMED, not raw XML
        self.assertNotIn("<environment_context>", u)
        self.assertIn("my project rules", u)        # the user's real instructions KEPT (clean voice)
        self.assertIn("Ada Handle", u)              # the real task KEPT
        self.assertIn("swagger.json", u)            # the real tool call KEPT
        self.assertIn("HTTP 200", u)                # the real tool result KEPT

    def test_drop_harness_frame_keeps_non_frame_roles(self):
        from cria.loop import _drop_harness_frame
        msgs = [
            {"role": "system", "content": "harness agent prompt"},
            {"role": "developer", "content": "more harness"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "did a thing"},
            {"role": "tool", "content": "result"},
        ]
        out = _drop_harness_frame(msgs)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "tool"])


class SearchEscalationTests(unittest.TestCase):
    """A weak model can web_search the same thing over and over without ever web_fetch-ing (fabliq: 9
    near-identical searches, 0 fetches, then a hallucinated endpoint). At the streak cap cria stops
    asking and FETCHES for it — the reasoner picks the url from the full context, cria substitutes a
    web_fetch for the search. Any other action resets the streak."""

    def _reasoner(self, content):
        return lambda b, r: json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def test_verbose_recommendation_is_not_misread_as_a_NONE_decline(self):
        # L7: the decline was `"NONE" in text[:12]` — a real url recommendation that merely STARTS with
        # "Nonetheless, …" was discarded, leaving the coder in its search loop. Must be WORD-anchored
        # (and "Nonetheless" is NOT the decline token "NONE").
        from cria.loop import author_search_fetch
        body = {"messages": [{"role": "user", "content": "use api.handle.me"}]}
        r = self._reasoner("Nonetheless, fetch https://api.handle.me/openapi.json to get the schema.")
        self.assertEqual(author_search_fetch(r, self._role(), body, _Rlog()),
                         "https://api.handle.me/openapi.json")
        self.assertEqual(author_search_fetch(self._reasoner("NONE"), self._role(), body, _Rlog()), "")

    def _search(self, q):
        return {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": q})}}]}}]}

    def _fn(self, coder):
        return coder["choices"][0]["message"]["tool_calls"][0]["function"]

    def _run(self, gs, coder, reasoner, task="use api.handle.me"):
        from cria.loop import guard_search_escalation
        return guard_search_escalation(gs, coder, {"messages": [{"role": "user", "content": task}]},
                                       reasoner, self._role(), _Rlog())

    def _escalate(self, gs, reasoner, task="use api.handle.me"):
        from cria.loop import SEARCH_STREAK_ESCALATE
        out = None
        for _ in range(SEARCH_STREAK_ESCALATE):
            out = self._run(gs, self._search("ADA Handle API resolve handle to address"), reasoner, task)
        return out

    def test_named_domain_escalates_to_the_openapi_convention(self):
        # The task named api.handle.me → the FIRST escape is the deterministic OpenAPI standard path,
        # NOT the reasoner's guess (runE: the reasoner kept picking /swagger and / and never openapi.json).
        from cria.loop import GuardState
        gs = GuardState()
        out = self._escalate(gs, self._reasoner("Fetch https://api.handle.me/swagger.json"))
        self.assertEqual(self._fn(out)["name"], "web_fetch")
        self.assertIn("api.handle.me/openapi.json", self._fn(out)["arguments"])
        self.assertNotIn("swagger.json", self._fn(out)["arguments"])   # reasoner NOT consulted first
        self.assertTrue(gs.tried_spec_convention)
        self.assertEqual(gs.search_streak, 0)

    def test_second_escalation_falls_to_the_reasoner(self):
        # The convention is spent once; a recurring streak then defers to the reasoner (which may know a
        # non-standard path), so an API without /openapi.json can't trap the escape on the convention.
        from cria.loop import GuardState
        gs = GuardState()
        self._escalate(gs, self._reasoner("Fetch https://api.handle.me/swagger.json"))   # convention
        out = self._escalate(gs, self._reasoner("Fetch https://api.handle.me/swagger.json"))  # reasoner
        self.assertIn("api.handle.me/swagger.json", self._fn(out)["arguments"])

    def test_no_named_domain_uses_the_reasoner(self):
        from cria.loop import GuardState
        gs = GuardState()
        out = self._escalate(gs, self._reasoner("Fetch https://example.org/openapi.json"),
                             task="build a thing, good luck")   # no domain in the task
        self.assertFalse(gs.tried_spec_convention)
        self.assertIn("example.org/openapi.json", self._fn(out)["arguments"])

    def test_reasoner_declines_with_no_named_domain_leaves_the_search(self):
        from cria.loop import GuardState
        gs = GuardState(); gs.tried_spec_convention = True   # convention already spent → reasoner path
        out = self._escalate(gs, self._reasoner("NONE"), task="find the ADA Handle docs")  # no domain named
        self.assertEqual(self._fn(out)["name"], "web_search")       # nothing to fall back to → not substituted

    def test_reasoner_none_falls_to_the_named_domain_root(self):
        # Reasoner-punt floor: convention spent + reasoner says NONE, but the task NAMED a domain (observed
        # live: fabliq replied NONE on 5 of 6 escapes, stranding the coder in a 900+ steer search loop).
        # cria fetches the domain ROOT — the docs page the user pointed to — not another dead search.
        from cria.loop import GuardState
        gs = GuardState(); gs.tried_spec_convention = True
        out = self._escalate(gs, self._reasoner("NONE"))            # default task names api.handle.me
        self.assertEqual(self._fn(out)["name"], "web_fetch")
        self.assertIn('"https://api.handle.me/"', self._fn(out)["arguments"])
        self.assertNotIn("openapi", self._fn(out)["arguments"])     # the ROOT, not the (spent) spec path
        self.assertTrue(gs.tried_domain_root)

    def test_domain_root_floor_is_spent_once(self):
        # spent once → a later NONE can't re-loop on the root; the search is then left for the gate to refuse
        from cria.loop import GuardState
        gs = GuardState(); gs.tried_spec_convention = True; gs.tried_domain_root = True
        out = self._escalate(gs, self._reasoner("NONE"))
        self.assertEqual(self._fn(out)["name"], "web_search")

    def test_task_api_domain_extraction(self):
        from cria.loop import _task_api_domain
        msg = lambda t: [{"role": "user", "content": t}]
        # the real task: one host named, filenames ignored
        self.assertEqual(_task_api_domain(msg(
            "resolve via the Ada Handles API (api.handle.me); write resolve_handle.py and a README.md")),
            "api.handle.me")
        self.assertEqual(_task_api_domain(msg("no domain here, just write config.json")), "")   # only a filename
        self.assertEqual(_task_api_domain(msg("compare api.foo.com and api.bar.com")), "")       # ambiguous → none

    def test_a_write_resets_the_streak(self):
        from cria.loop import GuardState
        gs = GuardState(); gs.search_streak = 4; gs.search_words = ["ada", "handle"]
        write = {"choices": [{"message": {"tool_calls": [
            {"id": "w", "type": "function", "function": {"name": "write_file", "arguments": "{}"}}]}}]}
        self._run(gs, write, self._reasoner("NONE"))
        self.assertEqual(gs.search_streak, 0)

    def test_a_new_direction_search_resets_the_streak(self):
        from cria.loop import GuardState
        gs = GuardState()
        r = self._reasoner("NONE")
        self._run(gs, self._search("ADA Handle API resolve handle to address"), r)
        self._run(gs, self._search("ADA Handle API resolve handle to address"), r)
        self.assertEqual(gs.search_streak, 2)
        self._run(gs, self._search("cardano staking rewards calculator python"), r)  # unrelated
        self.assertEqual(gs.search_streak, 1)


class SearchJudgeTests(unittest.TestCase):
    """Per-search reasoned assist: judge the OUTGOING query (off-target → fetch a URL / re-query), and
    judge the model's READ of a spilled search file (off-target → strip it + steer). Fails OPEN."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def _reasoner(self, verdict):
        return lambda b, r: json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    def _search(self, q):
        return {"choices": [{"message": {"tool_calls": [{"id": "s", "type": "function", "function":
                {"name": "web_search", "arguments": json.dumps({"query": q})}}]}}]}

    def _fn(self, out):
        return out["choices"][0]["message"]["tool_calls"][0]["function"]

    def _body(self):
        return {"messages": [{"role": "user", "content": "resolve an Ada Handle via the API (api.handle.me)"}]}

    def test_off_target_query_with_url_rec_becomes_a_fetch(self):
        from cria.loop import guard_search_query, GuardState
        out = guard_search_query(GuardState(), self._search("Cardano Wallet Backend API"), self._body(),
                                 self._reasoner({"on_target": False, "recommendation": "https://api.handle.me/openapi.json"}),
                                 self._role(), _Rlog())
        self.assertEqual(self._fn(out)["name"], "web_fetch")
        self.assertIn("api.handle.me/openapi.json", self._fn(out)["arguments"])

    def test_off_target_query_with_terms_rec_is_requeried(self):
        from cria.loop import guard_search_query, GuardState
        out = guard_search_query(GuardState(), self._search("random cardano stuff"), self._body(),
                                 self._reasoner({"on_target": False, "recommendation": "api.handle.me handles endpoint"}),
                                 self._role(), _Rlog())
        self.assertEqual(self._fn(out)["name"], "web_search")
        self.assertEqual(json.loads(self._fn(out)["arguments"])["query"], "api.handle.me handles endpoint")

    def test_on_target_query_untouched_and_verdict_cached(self):
        from cria.loop import guard_search_query, GuardState
        gs = GuardState()
        calls = {"n": 0}
        def reasoner(b, r):
            calls["n"] += 1
            return json.dumps({"choices": [{"message": {"content": json.dumps({"on_target": True})}}]}).encode()
        for _ in range(3):  # same query 3x → judged once (cached)
            out = guard_search_query(gs, self._search("api.handle.me openapi.json"), self._body(), reasoner, self._role(), _Rlog())
        self.assertEqual(self._fn(out)["name"], "web_search")   # unchanged
        self.assertEqual(calls["n"], 1)                          # cached after the first

    def test_judge_query_fails_open(self):
        from cria.loop import judge_query
        ok, rec = judge_query(lambda b, r: json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode(),
                              self._role(), "task", "query", _Rlog())
        self.assertTrue(ok)          # parse miss → on-target (never derail)
        self.assertEqual(rec, "")

    def test_looks_like_url(self):
        from cria.loop import _looks_like_url
        self.assertTrue(_looks_like_url("https://api.handle.me/openapi.json"))
        self.assertTrue(_looks_like_url("api.handle.me/openapi.json"))
        self.assertFalse(_looks_like_url("api.handle.me handles endpoint"))   # a search phrase, not a URL


class ReasonedRedirectTests(unittest.TestCase):
    """The SHARED author_redirect (both loop + plan-off run the identical reasoning). The reasoner
    authors the steer from ground truth; an empty reasoner reply falls back to canned — a stuck coder
    is never left without a steer."""

    def test_uses_reasoner_reply_then_falls_back_to_canned(self):
        import json, tempfile
        from cria.loop import GuardState, author_redirect
        from cria.probegate import GateOutcome
        gs = GuardState(probe_call_id="p1", spin_path="x.py", repeat_action="edit_file x.py")
        gs.recent_writes = []
        ws, outcome, body = tempfile.mkdtemp(), GateOutcome(ran=False), {"messages": []}
        reply = lambda b, r: json.dumps({"choices": [{"message": {"content": "do X instead of Y"}}]}).encode()
        self.assertIn("do X instead",
                      author_redirect(reply, None, ws, "the task", gs, outcome, body, _Rlog()))
        empty = lambda b, r: json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
        self.assertTrue(author_redirect(empty, None, ws, "the task", gs, outcome, body, _Rlog()))  # canned fallback

    def test_thrash_steer_diagnoses_else_raw_truth(self):
        import json, tempfile
        from cria.loop import GuardState, author_thrash_steer
        gs = GuardState(probe_call_id="p1", gate_stall=2)
        gs.recent_writes = []
        ws, truth, body = tempfile.mkdtemp(), "x.py:1: SyntaxError: bad", {"messages": []}
        reply = lambda b, r: json.dumps({"choices": [{"message": {"content": "you keep re-adding a colon on line 1; delete it"}}]}).encode()
        self.assertIn("delete it", author_thrash_steer(reply, None, ws, gs, truth, body, _Rlog()))
        empty = lambda b, r: json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
        self.assertEqual(author_thrash_steer(empty, None, ws, gs, truth, body, _Rlog()), truth)  # fall back to ground truth

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

    def test_reasoning_off_retry_cannot_APPROVE_completion(self):
        # THE false-complete: the reasoning-ON pass leaked a tool call (non-JSON), so the reasoning-OFF
        # retry ran and said satisfied=true — but a reasoning-off judge is a rubber stamp that can't do
        # the verification which catches a placeholder solution (hardcoded handles passing mocked
        # tests). A "satisfied" that exists ONLY because the careful pass failed must FAIL CLOSED.
        from cria.loop import judge_satisfaction
        calls = []

        def fake(body, rlog):
            calls.append(body)
            content = ("Re-install with the fixed pyproject and run both tests." if len(calls) == 1
                       else '{"satisfied": true, "reason": "all three tests pass"}')
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()

        sat, reason = judge_satisfaction("t", "e", fake, None, _Rlog())
        self.assertFalse(sat)                 # reasoning-off "satisfied" is FAILED CLOSED
        self.assertEqual(len(calls), 2)       # both passes ran (on, then off)
        self.assertIn("keep working", reason)

    def test_reasoning_off_retry_CAN_confirm_not_satisfied(self):
        # Rejecting is safe — a reasoning-off NOT-satisfied is trustworthy and respected with its reason.
        from cria.loop import judge_satisfaction
        calls = []

        def fake(body, rlog):
            calls.append(body)
            content = ("some leaked prose, not JSON" if len(calls) == 1
                       else '{"satisfied": false, "reason": "the live test was never run against the API"}')
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()

        sat, reason = judge_satisfaction("t", "e", fake, None, _Rlog())
        self.assertFalse(sat)
        self.assertIn("never run", reason)

    def test_careful_reasoning_on_pass_CAN_approve(self):
        # The reasoning-ON pass cleanly saying satisfied=true IS trusted — the only approval path — and
        # no reasoning-off retry is needed.
        from cria.loop import judge_satisfaction
        calls = []

        def fake(body, rlog):
            calls.append(body)
            return json.dumps({"choices": [{"message": {"role": "assistant",
                "content": '{"satisfied": true, "reason": "resolver + tests + README all present"}'}}]}).encode()

        sat, reason = judge_satisfaction("t", "e", fake, None, _Rlog())
        self.assertTrue(sat)
        self.assertEqual(len(calls), 1)       # careful pass parsed → no retry
        self.assertIn("resolver", reason)

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


def _single_loop(coder_chat, *, reasoner_chat=None, reasoner_role=None, compactor_chat=None,
                 compactor_role=None, coder_role=None, workspace_root=None, store=None,
                 satisfaction_check_start=100, satisfaction_check_every=25):
    """A Loop wired for the single-item (plan-off) path: planner_enabled=False, a dormant planner."""
    ctx = LoopContext(
        planner=_Planner(_plan()), coder_chat=coder_chat,
        reasoner_chat=reasoner_chat or coder_chat, reasoner_role=reasoner_role,
        compactor_chat=compactor_chat, compactor_role=compactor_role, coder_role=coder_role,
        planner_enabled=False, runs_dir="", workspace_root=workspace_root,
        satisfaction_check_start=satisfaction_check_start, satisfaction_check_every=satisfaction_check_every)
    return Loop(ctx, store or LoopStore())


def _synth(n=1):
    return PlanSession(plan=_plan(n), synthetic=True)


class SingleItemMethodTests(unittest.TestCase):
    """The SHARED _coder_turn (one guarded coder call behind BOTH driver halves — _work and the plan-off
    _drive_single_item — so a coder-turn guard can never land in one and miss the other)."""

    def _reasoner_chat(self, reply):
        return lambda b, r: json.dumps({"choices": [{"message": {"content": reply}}]}).encode()

    # ---- _coder_turn (the shared coder call) --------------------------------------------------
    def test_coder_turn_forwards_toolcall_and_tracks(self):
        loop = _single_loop(_Scripted([_toolcall()]))
        sess = _synth()
        comp = loop._coder_turn(sess, {"messages": [], "tools": [_SHELL]}, {"messages": []}, step=1, rlog=_Rlog())
        self.assertTrue(comp["choices"][0]["message"]["tool_calls"])   # acting turn forwarded
        self.assertIsNotNone(sess.recent_actions)                      # repetition tracking ran

    def test_coder_turn_empty_on_decode_fail(self):
        loop = _single_loop(lambda b, r: b"not json")
        comp = loop._coder_turn(_synth(), {"messages": [], "tools": []}, {"messages": []}, step=1, rlog=_Rlog())
        self.assertFalse(_has_tool_calls(comp))                        # decode fail → empty 'done', gate handles it

    def test_both_driver_halves_route_through_the_shared_coder_turn(self):
        # THE "both paths" INVARIANT (this is the regression guard for the search-escape divergence): a
        # coder-turn guard added to _coder_turn reaches BOTH halves. If a future edit re-inlines a coder
        # call in one half, a new guard could silently miss it again — this catches that.
        import inspect
        # _work delegates the actual coder work to _work_item (the completion path splits off first to run
        # the whole-task satisfaction critic); the coder call lives in _work_item.
        for method in ("_work_item", "_drive_single_item", "_gate_single_done"):
            src = inspect.getsource(getattr(Loop, method))
            self.assertIn("_coder_turn", src, f"{method} must route its coder call through _coder_turn")

    # ---- _reasoned_reanchor ------------------------------------------------------------------
    def test_reasoned_reanchor_authors_else_canned(self):
        from cria import prompts
        from cria.config import Role
        body = {"messages": [{"role": "user", "content": "SUMMARY: resolver built, tests remain"}]}
        role = Role(name="reasoner", backend="local")
        self.assertIn("X is done", _single_loop(_Scripted([_done()]),
            reasoner_chat=self._reasoner_chat("X is done; finish Y"), reasoner_role=role)._reasoned_reanchor(body, _Rlog()))
        self.assertEqual(_single_loop(_Scripted([_done()]), reasoner_chat=self._reasoner_chat("x"),
            reasoner_role=None)._reasoned_reanchor(body, _Rlog()), prompts.load("reanchor"))   # no reasoner → canned
        self.assertEqual(_single_loop(_Scripted([_done()]), reasoner_chat=self._reasoner_chat(""),
            reasoner_role=role)._reasoned_reanchor(body, _Rlog()), prompts.load("reanchor"))   # empty → canned
        self.assertEqual(_single_loop(_Scripted([_done()]), reasoner_chat=self._reasoner_chat("x"),
            reasoner_role=role)._reasoned_reanchor({"messages": []}, _Rlog()), prompts.load("reanchor"))  # no summary → canned

    # ---- _done_critic_reason (NO once-bound: re-runs on every green 'done' until satisfied) -------
    def test_done_critic_returns_concrete_reason_and_re_runs(self):
        import cria.loop as loopmod
        from cria.config import Role
        body = {"messages": [{"role": "user", "content": "build X with tests"}]}
        loop = _single_loop(_Scripted([_done()]), reasoner_chat=self._reasoner_chat("x"),
                            reasoner_role=Role(name="reasoner", backend="local"))
        orig = loopmod.judge_satisfaction
        try:
            loopmod.judge_satisfaction = lambda *a, **k: (False, "total_handles is missing")
            sess = _synth()
            # NOT satisfied → returns the critic's CONCRETE reason (to steer the coder back with)...
            self.assertEqual(loop._done_critic_reason(sess, body, _Rlog()), "total_handles is missing")
            # ...and it is NOT bounded — a second still-incomplete 'done' is critiqued again, not waved through
            self.assertEqual(loop._done_critic_reason(sess, body, _Rlog()), "total_handles is missing")
            loopmod.judge_satisfaction = lambda *a, **k: (True, "all present")
            self.assertEqual(loop._done_critic_reason(_synth(), body, _Rlog()), "")  # satisfied → "" → done
        finally:
            loopmod.judge_satisfaction = orig

    # ---- _gate_single_done -------------------------------------------------------------------
    def test_gate_single_done_no_shell_no_reasoner_forwards_the_done(self):
        loop = _single_loop(_Scripted([_done()]))  # no reasoner_role → nothing can verify
        sess = _synth(); sess.action_seq = 1  # already acted → skip LEG0
        framed = {"messages": [{"role": "user", "content": "x"}]}
        body = {"messages": [{"role": "user", "content": "x"}], "tools": []}  # no shell → can't gate
        out = loop._gate_single_done(sess, _done("all done"), framed, body, "k", _Rlog())
        self.assertEqual(out["choices"][0]["message"]["content"], "all done")  # can't verify at all → forward

    def test_gate_single_done_no_shell_but_reasoner_critiques_before_ending(self):
        # No shell tool → the objective gate can't run, but a reasoner CAN judge: a NOT-satisfied critic
        # re-nudges the coder instead of forwarding an unverified 'done' (no blind exit when we can judge).
        import cria.loop as loopmod
        from cria.config import Role
        loop = _single_loop(_Scripted([_toolcall()]), reasoner_chat=self._reasoner_chat("x"),
                            reasoner_role=Role(name="reasoner", backend="local"))
        sess = _synth(); sess.action_seq = 1
        body = {"messages": [{"role": "user", "content": "build X"}], "tools": []}  # no shell
        orig = loopmod.judge_satisfaction
        try:
            loopmod.judge_satisfaction = lambda *a, **k: (False, "total_handles is missing")
            out = loop._gate_single_done(sess, _done("all done"), {"messages": []}, body, "k", _Rlog())
            self.assertNotEqual(out["choices"][0]["message"].get("content"), "all done")  # NOT forwarded
        finally:
            loopmod.judge_satisfaction = orig

    def test_gate_single_done_emits_probe_with_shell(self):
        import os
        import tempfile
        loop = _single_loop(_Scripted([_done()]))
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "h.py"), "w") as f:
                f.write("def f():\n    return 1\n")
            body = {"tools": [_SHELL],
                    "messages": [{"role": "user", "content": f"<environment_context><cwd>{tmp}</cwd></environment_context>"}]}
            sess = _synth(); sess.action_seq = 1
            out = loop._gate_single_done(sess, _done("done"), {"messages": []}, body, "k", _Rlog())
            self.assertTrue(sess.done_probe)                              # a gate probe is now in flight
            self.assertTrue(out["choices"][0]["message"]["tool_calls"])   # emitted as a shell tool call

    # ---- _drive_single_item ------------------------------------------------------------------
    def test_drive_single_item_forwards_coder_action(self):
        loop = _single_loop(_Scripted([_toolcall()]))
        sess = _synth()
        comp = loop._drive_single_item(sess, _body(), "sid:x", _Rlog())
        self.assertTrue(comp["choices"][0]["message"]["tool_calls"])  # coder acting → forwarded
        self.assertEqual(sess.drive_count, 1)
        self.assertEqual(sess.coder_turns, 1)

    def test_drive_single_item_never_gives_up_on_persistent_red(self):
        # No stall terminator: a session past the old floor with a persistent RED keeps DRIVING the
        # coder (forwards its action / steers) — it never ends the session back to the human.
        loop = _single_loop(_Scripted([_toolcall()]))
        sess = _synth()
        sess.drive_count = 200
        sess.gate_stall = 10
        sess.gate_sig = "SyntaxError"
        out = loop._drive_single_item(sess, _body(), "sid:x", _Rlog())
        self.assertIsNotNone(out["choices"][0]["message"].get("tool_calls"))  # still driving, not a give-up


class _Class:
    """A minimal classification stub for the loop's drive gates (task_type + engagement only)."""

    def __init__(self, task_type="coding", engagement="task"):
        self.task_type = task_type
        self.engagement = engagement


class SingleItemModeTests(unittest.TestCase):
    """Phase 3+: the synthetic 1-item plan reached via Loop.drive (planner_enabled=False). Creation +
    persistence (Invariant 3: stable sid: persists+resumes, unstable task: is ephemeral) + the
    shell-tool-decline TRAP (plan-off runs the guarded coder even with NO shell tool)."""

    def test_unstable_task_key_is_ephemeral_never_persisted(self):
        store = LoopStore()
        loop = _single_loop(_Scripted([_toolcall()]), store=store)
        out = loop.drive(_body(), "task:xyz", _Class(), _Rlog())
        self.assertTrue(out["choices"][0]["message"]["tool_calls"])  # driven (coder acted)
        self.assertEqual(store._sessions, {})                        # NEVER persisted — re-synthesized each turn
        self.assertNotIn("task:xyz", store._shapes)                  # and no shape recorded for an unstable key

    def test_stable_sid_key_persists_and_resumes_synthetic(self):
        store = LoopStore()
        loop = _single_loop(_Scripted([_toolcall()]), store=store)
        loop.drive(_body(), "sid:abc", _Class(), _Rlog())
        sess = store.get("sid:abc")
        self.assertIsNotNone(sess)
        self.assertTrue(sess.synthetic)                              # a synthetic 1-item plan, persisted
        self.assertEqual(len(sess.plan.items), 1)
        loop.drive(_body(), "sid:abc", _Class(engagement="chat"), _Rlog())  # a non-task turn mid-session
        self.assertIs(store.get("sid:abc"), sess)                    # RESUMED, not re-planned or dropped

    def test_noncoding_turn_declines_to_proxy(self):
        loop = _single_loop(_Scripted([_toolcall()]))
        self.assertIsNone(loop.drive(_body(), "sid:q", _Class(task_type="chat", engagement="chat"), _Rlog()))

    def test_no_shell_tool_still_drives_when_planner_off(self):
        # THE TRAP: plan-off runs the guarded coder even with NO shell tool (the gate fails open),
        # so a native-write_file harness keeps every rumination/truncation/repetition guard.
        loop = _single_loop(_Scripted([_toolcall()]))
        body = {"stream": True, "messages": [{"role": "user", "content": "build it"}],
                "tools": [{"type": "function", "function": {"name": "write_file", "parameters": {}}}]}
        out = loop.drive(body, "sid:ns", _Class(), _Rlog())
        self.assertIsNotNone(out)                                    # NOT declined to proxy

    def test_synthetic_survives_dict_roundtrip(self):
        from cria.loop import _session_to_dict, _session_from_dict
        d = _session_to_dict(_synth())
        self.assertTrue(d["synthetic"])
        self.assertTrue(_session_from_dict(d).synthetic)             # a resumed session stays single-item


if __name__ == "__main__":
    unittest.main()
