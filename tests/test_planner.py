import json
import json as _json
import unittest
from datetime import datetime, timezone

from cria.planner import Planner


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class _Provider:
    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def chat(self, body, rlog):
        self.calls += 1
        return json.dumps({"choices": [{"message": {"content": self._content}}]}).encode()


class _ScriptedProvider:
    """Returns canned completions in order (repeating the last); records the bodies it
    was called with so a test can inspect what was fed back to the reasoner."""

    def __init__(self, responses):
        self._r = list(responses)
        self.calls = 0
        self.bodies = []

    def chat(self, body, rlog):
        self.calls += 1
        self.bodies.append(body)
        r = self._r.pop(0) if len(self._r) > 1 else self._r[0]
        return json.dumps(r).encode()


def _tool_resp(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _content_resp(text):
    return {"choices": [{"message": {"content": text}}]}


_FIXED = datetime(2026, 7, 7, 0, 45, 12, tzinfo=timezone.utc)


def _planner(content: str) -> Planner:
    return Planner(_Provider(content), clock=lambda: _FIXED)


def _msgs(text):
    return [{"role": "user", "content": text}]


class PlannerTests(unittest.TestCase):
    def test_drafts_plan_in_memory(self):
        plan = _planner('{"steps": ["Fetch the API contract", "Write the handler", "Write tests"]}').plan_for(
            _msgs("write an ada handle resolver"), _Rlog()
        )
        self.assertEqual([i.text for i in plan.items], ["Fetch the API contract", "Write the handler", "Write tests"])
        self.assertTrue(plan.id.startswith("20260707T004512-"))
        self.assertTrue(all(not i.done for i in plan.items))

    def test_fenced_steps_parse(self):
        plan = _planner('```json\n{"steps": ["a", "b"]}\n```').plan_for(_msgs("task"), _Rlog())
        self.assertEqual([i.text for i in plan.items], ["a", "b"])

    def test_numbered_list_parses(self):
        # The prompt asks for a numbered list; small models (e.g. Gemma) emit that
        # rather than JSON. Must parse into steps just the same.
        content = (
            "1. Create handler.py with resolve_handle and lambda_handler.\n"
            "2. Create tests/test_handler.py with mocked API tests.\n"
            "3. Create tests/live_test.py with a real request for 'goose'.\n"
            "4. Create README.md with setup and usage."
        )
        plan = _planner(content).plan_for(_msgs("build a resolver"), _Rlog())
        self.assertEqual(len(plan.items), 4)
        self.assertEqual(plan.items[0].text, "Create handler.py with resolve_handle and lambda_handler.")

    def test_think_wrapped_list_parses(self):
        content = "<think>let me plan this</think>\n1. First step here\n2. Second step here\n3. Third step"
        plan = _planner(content).plan_for(_msgs("x"), _Rlog())
        self.assertEqual([i.text for i in plan.items], ["First step here", "Second step here", "Third step"])

    def test_replans_each_call_no_positive_cache(self):
        # A plannable task is re-planned on each plan_for call (the loop's session store, not the
        # planner, prevents re-planning WITHIN a session). So a re-run of the same task in a new
        # session drafts fresh and does the work — it never inherits a prior run's plan.
        p = _Provider('{"steps": ["a", "b", "c"]}')
        planner = Planner(p, clock=lambda: _FIXED)
        plan1 = planner.plan_for(_msgs("same task"), _Rlog())
        for it in plan1.items:          # simulate the loop completing the whole plan
            it.done = True
        plan2 = planner.plan_for(_msgs("same task"), _Rlog())
        self.assertEqual(p.calls, 2, "re-planned fresh, not served from a positive cache")
        self.assertIsNot(plan2, plan1, "a distinct plan object")
        self.assertTrue(all(not it.done for it in plan2.items), "fresh plan is all not-done")

    def test_unplannable_task_is_negatively_cached(self):
        # An UNplannable task must not re-hit the reasoner every turn of a session.
        p = _Provider("write some code, good luck")  # no parseable plan
        planner = Planner(p, clock=lambda: _FIXED)
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        self.assertEqual(p.calls, 1, "negative cache prevents re-calling the reasoner")

    def test_unparseable_returns_none(self):
        self.assertIsNone(_planner("write some code, good luck").plan_for(_msgs("x"), _Rlog()))

    def test_no_task_text_returns_none(self):
        self.assertIsNone(_planner('{"steps": ["a"]}').plan_for([{"role": "assistant", "content": "hi"}], _Rlog()))


class RewriteSeedTests(unittest.TestCase):
    def test_rewrite_summary_seeds_the_rewritten_frame(self):
        # A post-harness-compaction plan is seeded with plan_rewritten (summary + current ask),
        # never the raw summary as the task, and never the plan_continuation prior-work frame.
        prov = _ScriptedProvider([_content_resp("1. finish the live test\n2. run it")])
        p = Planner(prov, clock=lambda: _FIXED)
        summary = "Built handler.py and unit tests; live test remains."
        plan = p.plan_for(_msgs(summary), _Rlog(), rewrite_summary=summary)
        self.assertIsNotNone(plan)
        seed = prov.bodies[0]["messages"][-1]["content"]
        self.assertIn("condensed by the harness", seed)                     # the rewrite frame
        self.assertIn(summary, seed)                                        # carries the summary
        self.assertIn("Continue and finish the remaining work", seed)       # root==latest → continue ask
        self.assertNotIn("This session already completed earlier work", seed)  # NOT the continuation frame

    def test_rewrite_with_distinct_new_ask_carries_both(self):
        prov = _ScriptedProvider([_content_resp("1. write the script")])
        p = Planner(prov, clock=lambda: _FIXED)
        msgs = [{"role": "user", "content": "SUMMARY: handler built."},
                {"role": "user", "content": "now write the live-test script"}]
        plan = p.plan_for(msgs, _Rlog(), rewrite_summary="SUMMARY: handler built.")
        self.assertIsNotNone(plan)
        seed = prov.bodies[0]["messages"][-1]["content"]
        self.assertIn("SUMMARY: handler built.", seed)
        self.assertIn("now write the live-test script", seed)               # the real current ask


class GatherLoopTests(unittest.TestCase):
    def test_investigates_with_a_tool_then_plans(self):
        # round 1: the reasoner calls a tool (investigate). round 2: no tool call → the plan.
        prov = _ScriptedProvider([
            _tool_resp("web_search", {"query": "api.handle.me docs"}),   # search_key="" → graceful result
            _content_resp("1. Fetch api.handle.me\n2. Write handler.py\n3. Run tests"),
        ])
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(
            _msgs("build an ada handle resolver"), _Rlog())
        self.assertEqual(len(plan.items), 3)
        self.assertEqual(prov.calls, 2)  # one gather round + one plan
        # the tool round-trip was fed back as PROTOCOL on the 2nd call (assistant tool_calls + tool result)
        second = prov.bodies[1]["messages"]
        self.assertTrue(any(m.get("role") == "assistant" and m.get("tool_calls") for m in second))
        self.assertTrue(any(m.get("role") == "tool" for m in second))

    def test_tools_offered_on_gather_but_off_when_forced(self):
        prov = _ScriptedProvider([_content_resp("1. a\n2. b")])  # plans immediately, no tool call
        Planner(prov, clock=lambda: _FIXED).plan_for(_msgs("do a task"), _Rlog())
        self.assertIn("tools", prov.bodies[0])  # the gather call offers the read-only tools

    def test_repeated_gather_signature_nudges_not_forces(self):
        # the reasoner re-runs the SAME tool call → cria NUDGES it (don't force the plan, a
        # sledgehammer that cut off a still-productive gather) and keeps gathering; the plan
        # comes when the model stops calling tools.
        prov = _ScriptedProvider([
            _tool_resp("web_search", {"query": "same thing"}),
            _tool_resp("web_search", {"query": "same thing"}),   # repeat → NUDGE, keep gathering
            _content_resp("1. step one\n2. step two"),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("a task"), rlog)
        self.assertEqual(len(plan.items), 2)
        # the repeat was nudged, not forced
        self.assertIn("plan.repeat_nudge", [k for k, _ in rlog.events])
        # and the gather kept its tools on the round AFTER the repeat (no forced-plan-off)
        nudged_round = next(b for b in prov.bodies if any(
            "you already ran" in str(m.get("content")) for m in b["messages"]))
        self.assertIn("tools", nudged_round)

    def test_forced_plan_reads_submit_plan_tool(self):
        # gemma-fable won't emit a plain-text plan, so at the force cria offers submit_plan and
        # reads the steps from the call it makes.
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "x"}),                     # round 1 gather
            _tool_resp("submit_plan", {"steps": ["do a", "do b", "do c"]}),  # forced → submit_plan
        ])
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(_msgs("t"), _Rlog())
        self.assertEqual([i.text for i in plan.items], ["do a", "do b", "do c"])
        self.assertEqual(prov.bodies[-1]["tools"][0]["function"]["name"], "submit_plan")  # offered submit_plan

    def test_forced_plan_leak_is_logged_and_retried(self):
        # the model calls something OTHER than submit_plan (a hallucinated tool) → logged with the
        # name, retried in place; still nothing after retries → retriable (not poison-cached).
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "x"}),
            _tool_resp("CreateNewProject", {"goal": "build"}),   # leak, every forced attempt
        ])
        rlog = _Rlog()
        self.assertIsNone(Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(_msgs("t"), rlog))
        retries = [kw for k, kw in rlog.events if k == "plan.final_retry"]
        self.assertTrue(retries)
        self.assertIn("CreateNewProject", str(retries[0].get("called")))  # the leak is in the record
        self.assertIn("plan.retriable", [k for k, _ in rlog.events])       # retriable, not cached

    def test_extract_cwd_from_environment_context(self):
        from cria.planner import _extract_cwd
        msgs = [{"role": "user", "content": "<environment_context>\n<cwd>/home/jesse/src/codex.test.site</cwd>\n</environment_context>"},
                {"role": "user", "content": "the task"}]
        self.assertEqual(_extract_cwd(msgs), "/home/jesse/src/codex.test.site")
        self.assertEqual(_extract_cwd([{"role": "user", "content": "no cwd here"}]), ".")


if __name__ == "__main__":
    unittest.main()


class GemmaLeakRecoveryTests(unittest.TestCase):
    """The planner recovers leaked tool-call dialects (codex-local: 'quirky reasoners gather
    too') and never poison-caches a gather overrun (observed live: gemma4's forced-plan leaked
    `call:web_search{…}` → plan.unparsed → the whole session fell to the proxy path)."""

    def test_gemma_dialect_gather_call_is_recovered_and_executed(self):
        # Round 1: the model LEAKS its gather call in the gemma dialect (llama.cpp can't parse
        # it). The planner must recover it, run the tool, and continue to the plan.
        leak = _content_resp('<|tool_call>call:read_file{path:<|"|>x.py<|"|>}<tool_call|>')
        prov = _ScriptedProvider([leak, _content_resp("1. do the thing\n2. verify")])
        p = Planner(prov, clock=lambda: _FIXED)
        plan = p.plan_for(_msgs("build it"), _Rlog())
        self.assertIsNotNone(plan)                       # gather continued → plan landed
        self.assertEqual(len(plan.items), 2)
        # the recovered call's RESULT was fed back as protocol (a role:tool message)
        roles = [m["role"] for m in prov.bodies[-1]["messages"]]
        self.assertIn("tool", roles)

    def test_forced_plan_tool_call_is_retriable_not_poisoned(self):
        # The model answers the forced "output the plan" with ANOTHER tool call, every time.
        leak = _content_resp('<|tool_call>call:web_search{query:<|"|>docs<|"|>}<tool_call|>')
        prov = _ScriptedProvider([leak])                 # repeats forever → gather cap → forced plan → leak again
        p = Planner(prov, max_gather_rounds=2, clock=lambda: _FIXED)
        rlog = _Rlog()
        self.assertIsNone(p.plan_for(_msgs("task x"), rlog))
        self.assertIn("plan.retriable", [k for k, _ in rlog.events])
        calls_before = prov.calls
        # NOT negative-cached: the next turn tries planning again (reasoner re-consulted)
        self.assertIsNone(p.plan_for(_msgs("task x"), _Rlog()))
        self.assertGreater(prov.calls, calls_before)

    def test_unparsed_prose_is_still_negative_cached(self):
        prov = _ScriptedProvider([_content_resp("I think this task is about lambdas and such.")])
        p = Planner(prov, clock=lambda: _FIXED)
        self.assertIsNone(p.plan_for(_msgs("task y"), _Rlog()))
        calls_before = prov.calls
        self.assertIsNone(p.plan_for(_msgs("task y"), _Rlog()))
        self.assertEqual(prov.calls, calls_before)       # cached — no re-call


class StepCleaningTests(unittest.TestCase):
    """A step must be one clean action — leaked dialect the model emitted by running PAST the
    plan (a <|channel>thought, another call:web_search) must not bleed into it (observed live:
    a dirty submit_plan step dirtied the whole plan mirror)."""

    def test_dialect_and_json_junk_stripped_from_step(self):
        from cria.planner import _clean_step
        dirty = ("Implement tests against the real API\n',]}<tool_call|><|channel>thought\n"
                 "I'm planning...<channel|><|tool_call>call:web_search{query:")
        self.assertEqual(_clean_step(dirty), "Implement tests against the real API")

    def test_submit_plan_steps_are_cleaned(self):
        from cria.planner import _steps_from_submit
        msg = {"tool_calls": [{"function": {"name": "submit_plan", "arguments":
            _json.dumps({"steps": ["Do a clean thing",
                                   "Do another\n']}<tool_call|><|channel>thought\nnoise"]})}}]}
        self.assertEqual(_steps_from_submit(msg), ["Do a clean thing", "Do another"])

    def test_clean_step_leaves_normal_text_alone(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Write the README with usage."), "Write the README with usage.")

