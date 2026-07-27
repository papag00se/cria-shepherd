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

    def test_plan_key_and_embedded_ordinals_parse(self):
        # Fabliq emits {"plan":[...]} about as often as {"steps":[...]}, with the ordinal embedded in
        # each string. Accepting only "steps" dropped it to plan.unparsed → plan-OFF fallback (no
        # step-gating → the coder hallucinated). Must parse, and strip the leading "1. ".
        content = '{"plan": ["1. Fetch the OpenAPI spec via web_fetch.", "2. Write the resolver.", "3. Add tests."]}'
        plan = _planner(content).plan_for(_msgs("build a resolver"), _Rlog())
        self.assertEqual([i.text for i in plan.items],
                         ["Fetch the OpenAPI spec via web_fetch.", "Write the resolver.", "Add tests."])

    def test_numbered_plan_folds_sub_bullets_into_their_step(self):
        # Sub-bullets under a numbered step must NOT become extra steps — that exploded a 7-step plan
        # into 11 and ground the loop through phantom README "steps". But they must not be DELETED
        # either: they ARE the step's requirements. Step COUNT is unchanged (3); the detail rides with
        # the step that owns it.
        content = ("1. Fetch the spec.\n2. Write the resolver.\n3. Add a README containing:\n"
                   "   - install instructions\n   - how to run the CLI\n   - how to run tests")
        plan = _planner(content).plan_for(_msgs("build it"), _Rlog())
        texts = [i.text for i in plan.items]
        self.assertEqual(len(texts), 3)                       # still 3 steps, no phantom README steps
        self.assertEqual(texts[:2], ["Fetch the spec.", "Write the resolver."])
        self.assertTrue(texts[2].startswith("Add a README containing:"))
        for detail in ("install instructions", "how to run the CLI", "how to run tests"):
            self.assertIn(detail, texts[2])                   # every requirement survived, on its step

    def test_lettered_sub_items_survive_and_the_step_does_not_trail_off(self):
        # THE FOOTGUN (live run 0726-132914): the planner wrote "3. Write a Python script (e.g.,
        # `resolve_handle.py`) that:" with four indented lettered requirements under it, and cria handed
        # the coder the header ALONE — a sentence trailing off at a colon with every requirement
        # deleted. cria must never destroy content the model relies on.
        content = ("1. Research the API.\n"
                   "2. Write a Python script (e.g., `resolve_handle.py`) that:\n"
                   "   a. Accepts an Ada handle as a command-line argument.\n"
                   "   b. Sends a GET request to the identified endpoint.\n"
                   "   c. Parses the JSON response, extracting the address and total handles.\n"
                   "3. Add tests.")
        plan = _planner(content).plan_for(_msgs("build it"), _Rlog())
        texts = [i.text for i in plan.items]
        self.assertEqual(len(texts), 3)                       # a., b., c. are DETAILS, not steps
        self.assertFalse(texts[1].endswith("that:"))          # no dangling colon handed to the coder
        for detail in ("Accepts an Ada handle", "Sends a GET request", "extracting the address"):
            self.assertIn(detail, texts[1])

    def test_unindented_prose_after_the_list_is_not_folded_into_a_step(self):
        # Only indented lines and bullet/lettered items are a step's detail. The model's commentary
        # around the list is not a requirement and must not be glued onto the last step.
        content = ("1. Fetch the spec.\n2. Write the resolver.\n"
                   "This plan covers the whole task and should be followed in order.")
        plan = _planner(content).plan_for(_msgs("build it"), _Rlog())
        texts = [i.text for i in plan.items]
        self.assertEqual(texts, ["Fetch the spec.", "Write the resolver."])

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
        # An UNplannable task re-drafts PLAN_RETRIES times (a weak model is non-deterministic), then is
        # negatively cached so it doesn't re-hit the reasoner every turn of the session.
        from cria.planner import PLAN_RETRIES
        p = _Provider("write some code, good luck")  # no parseable plan
        planner = Planner(p, clock=lambda: _FIXED)
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        self.assertEqual(p.calls, 1 + PLAN_RETRIES, "first plan_for retries the unparseable draft")
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        self.assertEqual(p.calls, 1 + PLAN_RETRIES, "then negatively cached — no further reasoner calls")

    def test_empty_draft_is_retried_then_lands(self):
        # A weak model draws an empty/unparseable plan non-deterministically; re-draft within PLAN_RETRIES
        # rather than dropping the coding session to the unguarded proxy (the silent-stop root).
        from cria.planner import PLAN_RETRIES

        class _Retry:  # empty for the first `fail_n` calls, then a valid plan
            def __init__(self, fail_n):
                self.fail_n, self.calls = fail_n, 0

            def chat(self, body, rlog):
                self.calls += 1
                c = "" if self.calls <= self.fail_n else '{"plan":["a","b"]}'
                return json.dumps({"choices": [{"message": {"content": c}}]}).encode()

        p = _Retry(fail_n=PLAN_RETRIES)     # fails exactly PLAN_RETRIES times, lands on the last retry
        plan = Planner(p, clock=lambda: _FIXED).plan_for(_msgs("do a coding task"), _Rlog())
        self.assertIsNotNone(plan)
        self.assertEqual([i.text for i in plan.items], ["a", "b"])
        self.assertEqual(p.calls, 1 + PLAN_RETRIES)

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

    def test_plan_naming_a_route_the_gather_never_saw_is_handed_back_once(self):
        # MEASURED: after 17 real fetch rounds the planner submitted "send a POST request to the
        # resolve endpoint at https://api.handle.me/resolve" — a host it had only seen in search
        # results and a route it had seen NOWHERE. The coder follows the plan verbatim, built to it,
        # got a 404, and thrashed. Hand it back ONCE as a proper tool result and keep gathering.
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "https://api.handle.me/swagger/swagger.yml"}),
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve with the handle",
                                                 "2. write tests"]}),
            _tool_resp("submit_plan", {"steps": ["1. GET https://api.handle.me/handles/{handle}",
                                                 "2. write tests"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(
            _msgs("resolve an ada handle"), rlog)
        self.assertIn("plan.submit_ungrounded", [k for k, _ in rlog.events])
        self.assertIn("/resolve", str([kw for k, kw in rlog.events if k == "plan.submit_ungrounded"]))
        # it re-submitted a grounded plan, and THAT is what was accepted
        self.assertIn("/handles/", plan.items[0].text)
        self.assertNotIn("/resolve", plan.items[0].text)
        # the challenge reached the model as a well-formed tool result
        challenged = next(b for b in prov.bodies
                          if any("nothing you fetched" in str(m.get("content")) for m in b["messages"]))
        self.assertTrue(any(m.get("role") == "tool" and "nothing you fetched" in str(m.get("content"))
                            for m in challenged["messages"]))

    def test_ungrounded_plan_is_challenged_only_once_never_wedges(self):
        # A planner that insists gets its plan anyway — cria never wedges the session on this, and
        # never rewrites the step itself (authoring a plan is not cria's job).
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "https://api.handle.me/swagger/swagger.yml"}),
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve"]}),
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("t"), rlog)
        self.assertEqual(len([k for k, _ in rlog.events if k == "plan.submit_ungrounded"]), 1)
        self.assertIn("/resolve", plan.items[0].text)   # accepted as drafted, not deleted or edited

    def test_route_the_gather_really_read_is_accepted_untouched(self):
        # The other half: a plan whose route the gather actually saw sails through. This guard tests
        # for INVENTION, not novelty — a grounded plan must never pay for it.
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "https://api.handle.me/swagger/swagger.yml"}),
            _tool_resp("submit_plan", {"steps": ["1. GET https://api.handle.me/swagger/swagger.yml first",
                                                 "2. write the script"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("t"), rlog)
        self.assertNotIn("plan.submit_ungrounded", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 2)

    def test_gather_evidence_excludes_the_models_own_turns(self):
        # The honesty of the whole check: a route the planner merely GUESSED at in its own
        # web_fetch(url=…) call must not appear in the "evidence" and ground itself.
        from cria.planner import _gather_evidence
        msgs = [
            {"role": "user", "content": "the task"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"function": {"name": "web_fetch",
                                          "arguments": '{"url":"https://x.dev/guessed"}'}}]},
            {"role": "tool", "content": "[web_fetch error: HTTP Error 404: Not Found]"},
        ]
        ev = _gather_evidence(msgs)
        self.assertNotIn("guessed", ev)     # its own guess is not evidence
        self.assertIn("404", ev)            # what it actually got back is

    def test_extract_cwd_from_environment_context(self):
        from cria.planner import _extract_cwd
        msgs = [{"role": "user", "content": "<environment_context>\n<cwd>/home/jesse/src/codex.test.site</cwd>\n</environment_context>"},
                {"role": "user", "content": "the task"}]
        self.assertEqual(_extract_cwd(msgs), "/home/jesse/src/codex.test.site")
        # no <cwd> advertised → None (UNKNOWN), never "." (cria's own dir) — callers must not target cria's tree
        self.assertIsNone(_extract_cwd([{"role": "user", "content": "no cwd here"}]))


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

    def test_live_model_lfm2_tool_call_tokens_are_cut_from_a_step(self):
        # The live model (LFM2/fabliq) leaks <|tool_call_start|>/<|tool_call_end|> — the _start/_end
        # suffix used to defeat _DIALECT_MARKER, so its debris survived into the step (writeproxy._TC_DEBRIS
        # lists these; the two cleaners must agree).
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Write the resolver module <|tool_call_start|>[read_file(x)]"),
                         "Write the resolver module")
        self.assertEqual(_clean_step("Add tests <|tool_call_end|> stray"), "Add tests")

    def test_clean_step_leaves_normal_text_alone(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Write the README with usage."), "Write the README with usage.")

    def test_clean_step_keeps_bare_xml_tag_mentions(self):
        # M13: the dialect marker required NO delimiter, so a bare <message>/<think>/<channel> mention —
        # a legit plan step about XML/streaming — was truncated ("Handle the <message> element" ->
        # "Handle the"). A real leaked control token ALWAYS carries a pipe/slash delimiter; bare tags stay.
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Handle the <message> XML element in the parser"),
                         "Handle the <message> XML element in the parser")
        self.assertEqual(_clean_step("Render <think> blocks as collapsible"), "Render <think> blocks as collapsible")
        # a genuine leaked native call is STILL cut
        self.assertEqual(_clean_step("Write the resolver <|tool_call|> leak"), "Write the resolver")


class AllStepsExecutedTests(unittest.TestCase):
    """EVERY emitted step becomes a PlanItem — no 12-step cap. A longer decomposition previously
    had its tail (steps 13+) silently dropped, so the loop ran a plan that structurally omitted
    work and could declare done with work missing."""

    def test_long_numbered_plan_keeps_every_step(self):
        content = "\n".join(f"{i}. step number {i}" for i in range(1, 16))  # 15 steps
        plan = _planner(content).plan_for(_msgs("a big task"), _Rlog())
        self.assertEqual(len(plan.items), 15)
        self.assertEqual(plan.items[-1].text, "step number 15")

    def test_long_json_plan_keeps_every_step(self):
        content = _json.dumps({"steps": [f"do thing {i}" for i in range(20)]})
        plan = _planner(content).plan_for(_msgs("json task"), _Rlog())
        self.assertEqual(len(plan.items), 20)

    def test_long_submit_plan_keeps_every_step(self):
        # the forced-plan / submit_plan path also keeps all steps (was sliced to 12 too)
        prov = _ScriptedProvider([
            _tool_resp("web_fetch", {"url": "x"}),
            _tool_resp("submit_plan", {"steps": [f"do {i}" for i in range(15)]}),
        ])
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(_msgs("t"), _Rlog())
        self.assertEqual(len(plan.items), 15)


class SalvageMalformedPlanTests(unittest.TestCase):
    """runH: fabliq emitted a clean 6-step {"plan":[...]} but one item — `like `"goose"`` — had
    unescaped inner quotes, so json.loads rejected the WHOLE object → plan.unparsed → the task fell to
    the UNGUARDED proxy path and freewheeled 60 turns. parse_steps must recover the array items."""

    def test_unescaped_inner_quotes_are_salvaged(self):
        from cria.planner import parse_steps
        text = ('{\n  "plan": [\n'
                '    "Fetch the spec with web_fetch.",\n'
                '    "Write tests for handles like `"goose"` and `"papagoose`.",\n'
                '    "Add a README."\n  ]\n}')
        steps = parse_steps(text)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0], "Fetch the spec with web_fetch.")
        self.assertIn("goose", steps[1])          # the whole item survived despite the inner quotes
        self.assertEqual(steps[2], "Add a README.")

    def test_salvage_does_not_fire_without_an_array_key(self):
        # A bare quoted sentence must NOT be mined as a step (only a steps/plan/items array is salvaged).
        from cria.planner import parse_steps
        self.assertIsNone(parse_steps('I think the answer is "probably yes" but I am not sure.'))

    def test_valid_json_still_takes_the_fast_path(self):
        from cria.planner import parse_steps
        self.assertEqual(parse_steps('{"plan": ["a", "b"]}'), ["a", "b"])

    def test_stringified_numbered_plan_is_split(self):
        # runI: {"plan": "1. Search... 2. Fetch... 3. Write..."} — plan is a STRING, steps inline.
        from cria.planner import parse_steps
        text = '{"plan": "1. Search the web. 2. Fetch the spec. 3. Write the script.", "output": ""}'
        steps = parse_steps(text)
        self.assertEqual(steps, ["Search the web.", "Fetch the spec.", "Write the script."])

    def test_single_ordinal_string_is_not_a_plan(self):
        # One "1." sentence must not be mistaken for a plan (needs >=2 ordinals).
        from cria.planner import parse_steps
        self.assertIsNone(parse_steps('{"plan": "1. just do the whole thing in one go"}'))


class NoiseStepDropTests(unittest.TestCase):
    """ONE reasoner judgment (plan_noise_steps.txt) replaces the old pile of keyword/shape regexes
    (_is_plumbing_step, _is_shell_command_step, _strip_baked_content, _scrub_invented_paths). It drops a
    step that is pure env-plumbing, a bare shell command, dictated literal code, or a fabricated/
    speculative guess. Reasoner-only — no keyword fallback: without a reasoner, or on an answer with no
    step numbers, NOTHING is dropped (cria never deletes a step on a guess). Call order in plan_for after
    the draft: NOISE judge, then the api-domain question, then (if a domain) the has-research question."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def test_reasoner_drops_a_plumbing_step_and_keeps_real_work(self):
        prov = _ScriptedProvider([
            _content_resp('1. Set up the development environment and install dependencies.\n'
                          '2. Write the fibonacci module fib.py.\n3. Add unit tests in test_fib.py.'),  # plan
            _content_resp('1'),        # NOISE? drop step 1 (pure plumbing)
            _content_resp('NONE'),     # which API? none → no research question
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("write a fibonacci module with unit tests"), rlog)
        texts = [it.text for it in plan.items]
        self.assertFalse(any("development environment" in t for t in texts))  # plumbing gone
        self.assertTrue(any("fib.py" in t for t in texts))                    # real work kept
        self.assertEqual(len(texts), 2)
        self.assertTrue(any(k == "plan.noise_dropped" for k, _ in rlog.events))

    def test_reasoner_drops_a_bare_shell_command_step(self):
        prov = _ScriptedProvider([
            _content_resp("1. grep -n 'resolve' ./tmp/read-only/openapi.json\n"
                          "2. Write resolver.py that calls the endpoint the spec names\n3. Add unit tests"),
            _content_resp('1'),        # NOISE? drop the bare grep command
            _content_resp('NONE'),     # which API? none
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("build a resolver"), rlog)
        texts = [it.text for it in plan.items]
        self.assertFalse(any(t.startswith("grep") for t in texts))   # the command-step is gone
        self.assertTrue(any("resolver.py" in t for t in texts))      # real outcomes kept

    def test_reasoner_drops_a_baked_code_step(self):
        prov = _ScriptedProvider([
            _content_resp("1. Create tests/test_x.py with content 'import sys, json, mock, requests; def test(): ...'\n"
                          "2. Write resolver.py"),
            _content_resp('1'),        # NOISE? drop the step that dictates literal code
            _content_resp('NONE'),
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("build a resolver with tests"), rlog)
        texts = [it.text for it in plan.items]
        self.assertFalse(any("import sys" in t for t in texts))      # baked code gone
        self.assertTrue(any("resolver.py" in t for t in texts))

    def test_all_noise_plan_is_never_emptied(self):
        prov = _ScriptedProvider([
            _content_resp('1. Set up the development environment.\n2. Install the dependencies.'),
            _content_resp('1, 2'),     # NOISE? both — but cria never empties the plan
            _content_resp('NONE'),
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("do a thing"), rlog)
        self.assertEqual(len(plan.items), 2)  # kept as-is — never leave an empty plan
        self.assertTrue(any(k == "plan.noise_all_kept" for k, _ in rlog.events))

    def test_prose_answer_never_over_deletes(self):
        # H1: a weak model that wraps its verdict in prose ("steps 1 and 2 look fine; step 3 is
        # plumbing") must NOT have every number it MENTIONS scraped as a deletion — that dropped the
        # endorsed steps 1 and 2. Strict parse → a non-numeric answer drops NOTHING (safe null).
        from cria.planner import reasoned_noise_indices
        steps = ["Fetch the spec", "Write resolver", "Set up the venv", "Add tests"]
        self.assertEqual(reasoned_noise_indices(
            lambda s, u: "Steps 1 and 2 look fine; step 3 is plumbing.", "t", steps), set())  # prose → nothing
        self.assertEqual(reasoned_noise_indices(lambda s, u: "The steps to remove are 3.", "t", steps), set())
        # a CLEAN number list still acts, and NONE still drops nothing
        self.assertEqual(reasoned_noise_indices(lambda s, u: "3", "t", steps), {2})
        self.assertEqual(reasoned_noise_indices(lambda s, u: "1, 3", "t", steps), {0, 2})
        self.assertEqual(reasoned_noise_indices(lambda s, u: "NONE", "t", steps), set())

    def test_NONE_answer_drops_nothing(self):
        prov = _ScriptedProvider([
            _content_resp('1. Write fib.py.\n2. Add tests.'),
            _content_resp('NONE'),     # NOISE? none
            _content_resp('NONE'),     # which API? none
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("write a fibonacci module"), rlog)
        self.assertEqual(len(plan.items), 2)
        self.assertFalse(any(k == "plan.noise_dropped" for k, _ in rlog.events))

    def test_no_second_task_less_setup_pass_can_delete_a_research_or_docs_step(self):
        # THE FOOTGUN THAT REPLACED IT: a second, TASK-LESS "which steps are pure env setup?" pass was
        # unioned into the drop set to catch a venv step the task-aware judge waves through. Measured over
        # the captures it was wrong 4 of 6 times, and what it deleted was a step the prompt EXCLUDES:
        # "Fetch the OpenAPI specification…" (research — deleting it is how the coder ends up guessing an
        # endpoint) and a README whose CONTENT mentions `pip install` (docs). Blinded to the task it can't
        # tell a step whose OUTPUT is documentation from a step whose ACTION is installing. So there is
        # exactly ONE noise judgment now, WITH the task: when it says NONE, nothing is dropped — even a
        # step that lexically smells like setup. (A real PEP-668 wall is handled at the real error by
        # writeproxy's pep668_remedy.) The script gives only ONE noise answer; a second scripted answer
        # would be consumed by a re-introduced pass and the research step would vanish again.
        prov = _ScriptedProvider([
            _content_resp('1. Fetch the OpenAPI specification from the API and read the real endpoint.\n'
                          '2. Write resolver.py.\n'
                          '3. Add README.md with installation instructions (pip install requests).'),  # plan
            _content_resp('NONE'),     # the ONE task-aware NOISE judgment: drop nothing
            _content_resp('1, 3'),     # would-be blinded SETUP verdict — must never be asked for/consumed
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("build a resolver"), rlog)
        texts = [it.text for it in plan.items]
        self.assertEqual(len(texts), 3)                                  # nothing deleted
        self.assertTrue(any("OpenAPI specification" in t for t in texts))  # the RESEARCH step survives
        self.assertTrue(any("README.md" in t for t in texts))              # the DOCS step survives
        self.assertFalse(any(k == "plan.noise_dropped" for k, _ in rlog.events))

    def test_no_reasoner_drops_nothing(self):
        # reasoner-only: without a role cria does NOT classify steps — the plan is used exactly as drafted
        # (no keyword-regex fallback). The basic no-role plan_for path is covered here.
        prov = _ScriptedProvider([_content_resp(
            '1. Set up the development environment.\n2. Write fib.py.\n3. Add tests.')])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("write a fibonacci module"), rlog)
        self.assertEqual(len(plan.items), 3)  # nothing dropped without a reasoner
        self.assertFalse(any(k == "plan.noise_dropped" for k, _ in rlog.events))
