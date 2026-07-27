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

# Reasoner calls one draft costs when the model never calls a tool: the RESEARCH turn, the one
# research nudge ("look before planning"), then the DRAFT turn. Planning is two phases — research
# with the gather tools, then drafting with submit_plan — so a model that plans blind is asked once
# to look first. Tests assert in multiples of this rather than hard-coding a total.
_CALLS_PER_BLIND_DRAFT = 3


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
        self.assertEqual(p.calls, 2 * _CALLS_PER_BLIND_DRAFT,
                         "re-planned fresh, not served from a positive cache")
        self.assertIsNot(plan2, plan1, "a distinct plan object")
        self.assertTrue(all(not it.done for it in plan2.items), "fresh plan is all not-done")

    def test_unplannable_task_is_negatively_cached(self):
        # An UNplannable task re-drafts PLAN_RETRIES times (a weak model is non-deterministic), then is
        # negatively cached so it doesn't re-hit the reasoner every turn of the session.
        from cria.planner import PLAN_RETRIES
        p = _Provider("write some code, good luck")  # no parseable plan
        planner = Planner(p, clock=lambda: _FIXED)
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        drafts = (1 + PLAN_RETRIES) * _CALLS_PER_BLIND_DRAFT
        self.assertEqual(p.calls, drafts, "first plan_for retries the unparseable draft")
        self.assertIsNone(planner.plan_for(_msgs("bad task"), _Rlog()))
        self.assertEqual(p.calls, drafts, "then negatively cached — no further reasoner calls")

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
        # PHASE A round 1: the reasoner calls a tool (investigate). Round 2: no tool call → done
        # looking. PHASE B: the drafting call returns the plan.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo 'the docs say GET /handles/{handle}'"}),
            _content_resp("1. Fetch api.handle.me\n2. Write handler.py\n3. Run tests"),
        ])
        plan = Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(
            _msgs("build an ada handle resolver"), _Rlog())
        self.assertEqual(len(plan.items), 3)
        self.assertEqual(prov.calls, 3)  # research round + end-of-research turn + the drafting call
        # the tool round-trip was fed back as PROTOCOL on the 2nd call (assistant tool_calls + tool result)
        second = prov.bodies[1]["messages"]
        self.assertTrue(any(m.get("role") == "assistant" and m.get("tool_calls") for m in second))
        self.assertTrue(any(m.get("role") == "tool" for m in second))

    def test_research_phase_is_not_offered_the_submit_tool(self):
        # THE ENFORCEMENT (measured: 3 of 4 runs drafted a plan having read no real source, and two of
        # those shipped an invented endpoint). "Research first" was prose in plan.txt and was ignored,
        # so it is now structural: while researching, submit_plan is not on the menu — the planner
        # CANNOT draft before it has looked. Only the drafting call may submit.
        prov = _ScriptedProvider([
            _tool_resp("web_search", {"query": "docs"}),
            _content_resp("1. a\n2. b"),
        ])
        Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("build it"), _Rlog())
        research_tools = [f["function"]["name"] for f in prov.bodies[0]["tools"]]
        self.assertNotIn("submit_plan", research_tools)
        self.assertIn("web_fetch", research_tools)          # ...but the read-only tools ARE there
        draft_tools = [f["function"]["name"] for f in prov.bodies[-1]["tools"]]
        self.assertEqual(draft_tools, ["submit_plan"])      # the drafting call: submit, nothing else

    def test_calls_that_return_nothing_do_not_count_as_research(self):
        # MEASURED (run 0727-090143): in an EMPTY workspace the planner ran `ls -la` then `find` —
        # both returned nothing — and cria counted that as having researched. It then drafted from
        # memory and invented `/resolve?handle={handle}`, which the coder duly built and 404'd.
        # Two calls that returned no bytes are not research: the nudge to look must still fire.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "true"}),   # runs fine, returns nothing at all
            _content_resp("1. write it\n2. test it"),
        ])
        rlog = _Rlog()
        Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("do a thing"), rlog)
        self.assertEqual(len([k for k, _ in rlog.events if k == "plan.research_nudge"]), 1)

    def test_a_call_that_returns_real_content_is_research(self):
        # The other half: once something actually came back, the planner has looked and is left alone.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo 'GET /handles/{handle} resolves a handle'"}),
            _content_resp("1. write it\n2. test it"),
        ])
        rlog = _Rlog()
        Planner(prov, search_key="", clock=lambda: _FIXED).plan_for(_msgs("do a thing"), rlog)
        self.assertNotIn("plan.research_nudge", [k for k, _ in rlog.events])

    def test_planner_that_opens_nothing_is_asked_once_to_look_first(self):
        # A planner that calls NO tool at all has planned blind (measured: one run's planner made zero
        # tool calls and drafted "perform a web search…" as step 1). It gets ONE nudge to look, and
        # only one — a task with nothing to read must not be badgered, and the nudge must not eat a
        # gather round.
        prov = _ScriptedProvider([_content_resp("1. write it\n2. test it")])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("do a chore"), rlog)
        nudges = [k for k, _ in rlog.events if k == "plan.research_nudge"]
        self.assertEqual(len(nudges), 1)                       # exactly one, never a loop
        self.assertEqual(len(plan.items), 2)                   # and it still gets its plan
        self.assertTrue(any("LOOK" in str(m.get("content")) for b in prov.bodies
                            for m in b["messages"] if m.get("role") == "user"))

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

    # The research these three do is a local `echo` of a spec fragment, not a live fetch: it grounds
    # the evidence exactly the same way (it is a real tool result the gather read) without making the
    # suite depend on a network round-trip to a third-party host.
    _SPEC_ECHO = {"cmd": "echo 'https://api.handle.me/openapi.json paths: /handles/{handle}: get: a handle'"}

    def test_plan_naming_a_route_the_research_never_saw_is_handed_back_once(self):
        # MEASURED: after 17 real fetch rounds the planner submitted "send a POST request to the
        # resolve endpoint at https://api.handle.me/resolve" — a host it had only seen in search
        # results and a route it had seen NOWHERE. The coder follows the plan verbatim, built to it,
        # got a 404, and thrashed. Hand it back ONCE and let it draft again.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", self._SPEC_ECHO),                      # PHASE A: research
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve with the handle",
                                                 "2. write tests"]}),
            _tool_resp("submit_plan", {"steps": ["1. GET https://api.handle.me/handles/{handle}",
                                                 "2. write tests"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("resolve an ada handle"), rlog)
        self.assertIn("plan.submit_ungrounded", [k for k, _ in rlog.events])
        self.assertIn("/resolve", str([kw for k, kw in rlog.events if k == "plan.submit_ungrounded"]))
        # it re-drafted a grounded plan, and THAT is what was accepted
        self.assertIn("/handles/", plan.items[0].text)
        self.assertNotIn("/resolve", plan.items[0].text)
        # the challenge reached the model, naming what was unverified — and saying plainly that this
        # is NOT evidence the route is wrong (the planner read the earlier phrasing as proof the
        # endpoint did not exist, and planned a reachability probe instead of the work).
        challenge = next(str(m.get("content")) for b in prov.bodies for m in b["messages"]
                         if "UNVERIFIED" in str(m.get("content")))
        self.assertIn("NOT evidence they are wrong", challenge)

    def test_ungrounded_plan_is_challenged_only_once_never_wedges(self):
        # A planner that insists gets its plan anyway — cria never wedges the session on this, and
        # never rewrites the step itself (authoring a plan is not cria's job).
        prov = _ScriptedProvider([
            _tool_resp("exec_command", self._SPEC_ECHO),
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve"]}),
            _tool_resp("submit_plan", {"steps": ["1. POST to https://api.handle.me/resolve"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("t"), rlog)
        self.assertEqual(len([k for k, _ in rlog.events if k == "plan.submit_ungrounded"]), 1)
        self.assertIn("/resolve", plan.items[0].text)   # accepted as drafted, not deleted or edited

    def test_route_the_research_really_read_is_accepted_untouched(self):
        # The other half: a plan whose route the research actually saw sails through. This guard tests
        # for INVENTION, not novelty — a grounded plan must never pay for it.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", self._SPEC_ECHO),
            _tool_resp("submit_plan", {"steps": ["1. GET https://api.handle.me/handles/{handle}",
                                                 "2. write the script"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("t"), rlog)
        self.assertNotIn("plan.submit_ungrounded", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 2)

    def test_research_findings_travel_with_the_plan(self):
        # THE MEASURED LOSS (run 0726-221401): at gather call 4 the planner held the REAL spec —
        # `/handles/{handle}` and `/holders/{address}`, the two endpoints that task needs — and the
        # findings died with the gather transcript. The plan named no endpoint, the coder was never
        # shown the routes, invented `/handle/{handle}`, and 404'd. cria had the ground truth in hand.
        # A fetch's routes/fields must now ride out on the plan.
        import cria.planner_tools as pt
        facts = {}
        spec = _json.dumps({"paths": {"/handles/{handle}": {"get": {}},
                                      "/holders/{address}": {"get": {}}}})
        pt._record_fetch(facts, "https://api.handle.me/openapi.json", 200, spec, "application/json")
        self.assertIn("https://api.handle.me/openapi.json", facts)
        status, routes, _fields = facts["https://api.handle.me/openapi.json"]
        self.assertEqual(status, "HTTP 200")
        self.assertIn("/handles/{handle}", routes)      # the exact route the coder kept inventing
        self.assertIn("/holders/{address}", routes)     # ...and the second call it never knew it needed

    def test_a_failed_fetch_records_nothing(self):
        # A fetch that failed proved NOTHING. Restating a 404 as a fact is how a hallucinated endpoint
        # became "ground truth" once already — only a 2xx may enter the record.
        import cria.planner_tools as pt
        facts = {}
        pt._record_fetch(facts, "https://api.handle.me/resolve", 404, "not found", "text/plain")
        pt._record_fetch(facts, "https://api.handle.me/ok", 200, "{}", "application/json")
        self.assertNotIn("https://api.handle.me/resolve", facts)
        self.assertIn("https://api.handle.me/ok", facts)

    def test_drafting_call_restates_the_findings_in_the_last_turn(self):
        # The raw transcript is not enough on its own: it is tens of KB of fetched bodies in which the
        # one line that matters appears once, and the context floor drops the OLDEST turns first — in
        # the measured run the successful-fetch header was floored out before drafting. The digest
        # rides in the LAST turn, which the floor drops LAST. It is an ADDITION: the transcript stays.
        from cria.planner import _facts_digest
        digest = _facts_digest({"https://api.handle.me/openapi.json":
                                ("HTTP 200", "/handles/{handle}, /holders/{address}", "GET → holder")})
        self.assertIn("https://api.handle.me/openapi.json", digest)
        self.assertIn("/handles/{handle}", digest)
        self.assertIn("GET → holder", digest)

class UnreadHostTests(unittest.TestCase):
    """A plan can be built against a host nobody ever READ. Code gathers the discrepancy — hosts the
    plan names, minus hosts a 2xx fetch actually returned — and ONE reasoner call decides whether the
    work really depends on reading them. Measured (run 0727-090143): the planner listed an empty git
    repo, that counted as research, and it drafted against `api.handle.me` having never fetched it,
    inventing `/resolve?handle=` which the coder then built and 404'd."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def test_unread_hosts_are_the_named_ones_minus_the_fetched_ones(self):
        from cria.planner import _unread_hosts
        task = "resolve a handle with api.handle.me and link docs.example.com in the README"
        facts = {"https://api.handle.me/openapi.json": ("HTTP 200", "/handles/{handle}", "")}
        steps = ["Call api.handle.me to resolve the handle", "Link to docs.example.com in the README"]
        self.assertEqual(_unread_hosts(steps, facts, task), ["docs.example.com"])  # the fetched one is gone

    def test_a_host_the_request_named_but_nobody_read_is_a_candidate(self):
        # THE SEMANTIC POINT: a host counts as grounded only when something came BACK from it. Being
        # named — by the user's own request — is what creates the dependency, not what satisfies it.
        from cria.planner import _unread_hosts
        self.assertEqual(_unread_hosts(["resolve it using api.handle.me"], {},
                                       "resolve a handle using api.handle.me"), ["api.handle.me"])

    def test_filenames_in_a_plan_do_not_spend_a_reasoner_call(self):
        # The host pattern is over-inclusive by design (`fib.py`, `README.md` match it), and plans name
        # files constantly — so the candidate must ALSO be named in the REQUEST. Otherwise nearly every
        # plan would buy a reasoner call to be told NONE.
        from cria.planner import _unread_hosts
        steps = ["Write fib.py", "Add test_fib.py", "Add README.md with usage"]
        self.assertEqual(_unread_hosts(steps, {}, "write a fibonacci module with tests"), [])

    def test_reasoner_says_it_must_be_read_so_the_plan_is_handed_back_once(self):
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked at the workspace"}),   # PHASE A
            _tool_resp("submit_plan", {"steps": ["Write a script that calls api.handle.me to resolve a handle"]}),
            _content_resp("api.handle.me"),          # the host judge: yes, this must be read
            _tool_resp("submit_plan", {"steps": ["Fetch the spec from api.handle.me, then write the script"]}),
            _content_resp("NONE"),                   # the noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            _msgs("resolve an ada handle using the Ada Handles API (api.handle.me)"), rlog)
        self.assertIn("plan.host_unread", [k for k, _ in rlog.events])
        self.assertIn("Fetch the spec", plan.items[0].text)          # the re-draft is what landed
        self.assertTrue(any("has read" in str(m.get("content"))
                            for b in prov.bodies for m in b["messages"]))

    def test_reasoner_says_no_so_nothing_fires(self):
        # A README link, a package registry, a git remote — named but not depended on. No challenge,
        # and no lexical exception list needed to know that.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": ["Add a README linking to docs.example.com"]}),
            _content_resp("NONE"),                   # the host judge: nothing needs reading
            _content_resp("NONE"),                   # the noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            _msgs("write docs, link docs.example.com"), rlog)
        self.assertNotIn("plan.host_unread", [k for k, _ in rlog.events])
        self.assertIn("docs.example.com", plan.items[0].text)        # accepted untouched

    def test_a_host_that_was_fetched_costs_no_reasoner_call_at_all(self):
        # Zero cost when there is no discrepancy: the deterministic half found nothing to ask about.
        from cria.planner import _unread_hosts
        facts = {"https://api.handle.me/openapi.json": ("HTTP 200", "/handles/{handle}", "")}
        self.assertEqual(_unread_hosts(["call api.handle.me for the handle"], facts,
                                       "resolve with api.handle.me"), [])

    def test_prose_answer_takes_the_safe_null(self):
        # Strict parse, same posture as the noise judge: anything that is not a clean list of the
        # candidates drops to "challenge nothing". cria never hands a plan back on a guess.
        from cria.planner import _parse_unread_verdict
        cands = ["api.handle.me", "docs.example.com"]
        self.assertEqual(_parse_unread_verdict("api.handle.me", cands), ["api.handle.me"])
        self.assertEqual(_parse_unread_verdict("NONE", cands), [])
        self.assertEqual(_parse_unread_verdict("I think api.handle.me is needed here", cands), [])
        self.assertEqual(_parse_unread_verdict("some.other.host", cands), [])
        self.assertEqual(_parse_unread_verdict("", cands), [])

    def test_no_reasoner_means_no_judgment(self):
        from cria.planner import _unread_hosts
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": ["Call api.handle.me"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("t"), rlog)                        # no role → no reasoner → no challenge
        self.assertNotIn("plan.host_unread", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 1)


class PlanCoverageTests(unittest.TestCase):
    """Nothing checked that a fresh plan covers what the request asked for. replan.txt carries the
    rule for the RE-derivation ("every deliverable the user asked for ... must still be covered by a
    step"); plan.txt never had it and nothing enforced it. Measured (run 0727-090143): a ONE-step plan
    — "Explore the workspace to locate any existing source code" — was accepted for a request wanting
    a script, unit tests, a live test and a README. Only the end-of-task satisfaction critic caught it,
    after coder calls had already been spent."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def test_a_plan_missing_deliverables_is_handed_back_once(self):
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),                       # PHASE A
            _tool_resp("submit_plan", {"steps": ["Explore the workspace"]}),          # covers nothing
            _content_resp('{"missing": ["the unit tests", "the README"]}'),           # coverage judge
            _tool_resp("submit_plan", {"steps": ["Write the script", "Add unit tests", "Add a README"]}),
            _content_resp("NONE"),                                                    # noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            _msgs("write a script, with unit tests, and a README"), rlog)
        self.assertIn("plan.missing_deliverables", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 3)                       # the re-draft is what landed
        self.assertTrue(any("README" in str(m.get("content"))
                            for b in prov.bodies for m in b["messages"]))

    def test_a_second_distinct_problem_still_gets_its_own_hand_back(self):
        # MEASURED (live run 0727-110625): the URL challenge fired, consumed a SHARED one-hand-back
        # budget, and every later check was then skipped — so the re-draft was never examined at all.
        # It came back as a single step that was a raw shell command, producing none of the four
        # deliverables, and was accepted. Replayed against the live model, the coverage check flags
        # that plan 4 times out of 4. The budget must bound how many times cria HANDS BACK, not how
        # many times it LOOKS: the re-draft is the most likely thing to be degraded.
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo https://api.handle.me/openapi.json paths: /handles/{handle}"}),
            _tool_resp("submit_plan", {"steps": ["Call https://api.handle.me/resolve to resolve it"]}),
            _tool_resp("submit_plan", {"steps": ["python3 -c 'print(1)'"]}),   # re-draft: covers nothing
            _content_resp('{"missing": ["the unit tests", "the README"]}'),    # coverage: caught
            _tool_resp("submit_plan", {"steps": ["Write the script", "Add tests", "Add a README"]}),
            _content_resp('{"missing": []}'),                       # coverage on the good draft
            _content_resp("NONE"),                                  # noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(
            _msgs("resolve a handle with api.handle.me, with unit tests and a README"), rlog)
        kinds = [k for k, _ in rlog.events]
        self.assertIn("plan.submit_ungrounded", kinds)      # first problem handed back
        self.assertIn("plan.missing_deliverables", kinds)   # ...and the SECOND, distinct one too
        self.assertEqual(len(plan.items), 3)                # the good draft is what landed

    def test_hand_backs_are_capped_so_a_stubborn_planner_still_gets_its_plan(self):
        # Bounded: at most MAX_PLAN_HANDBACKS, so this can never ping-pong or wedge a session.
        from cria.planner import MAX_PLAN_HANDBACKS
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo https://api.handle.me/openapi.json paths: /handles/{handle}"}),
            _tool_resp("submit_plan", {"steps": ["Call https://api.handle.me/resolve"]}),   # url challenge
            _tool_resp("submit_plan", {"steps": ["Call https://api.handle.me/resolve"]}),   # insists
            _content_resp('{"missing": ["the tests"]}'),            # coverage challenge (2nd, the cap)
            _tool_resp("submit_plan", {"steps": ["Call https://api.handle.me/resolve"]}),   # still insists
            _content_resp("NONE"),                                  # noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("resolve with api.handle.me"), rlog)
        handbacks = sum(1 for k, _ in rlog.events
                        if k in ("plan.submit_ungrounded", "plan.missing_deliverables", "plan.host_unread"))
        self.assertLessEqual(handbacks, MAX_PLAN_HANDBACKS)
        self.assertIsNotNone(plan)                          # it still gets a plan

    def test_a_covering_plan_sails_through(self):
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": ["Write the script", "Add unit tests", "Add a README"]}),
            _content_resp('{"missing": []}'),      # covers everything
            _content_resp("NONE"),                 # noise judge
        ])
        rlog = _Rlog()
        plan = Planner(prov, role=self._role(), search_key="", max_gather_rounds=1,
                       clock=lambda: _FIXED).plan_for(_msgs("script, tests, README"), rlog)
        self.assertNotIn("plan.missing_deliverables", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 3)

    def test_an_unclear_verdict_challenges_nothing(self):
        # Safe null, same posture as every other judge here: a plan is never handed back on a guess.
        # This one matters more than most — an open "what's missing?" question is exactly where a weak
        # reasoner starts inventing requirements (the unfalsifiable-step bug), so anything that is not
        # a clean list is treated as "nothing missing".
        from cria.planner import _parse_missing_verdict
        self.assertEqual(_parse_missing_verdict('{"missing": ["tests"]}'), ["tests"])
        self.assertEqual(_parse_missing_verdict('{"missing": []}'), [])
        self.assertEqual(_parse_missing_verdict("NONE"), [])
        self.assertEqual(_parse_missing_verdict("I think the tests are missing"), [])
        self.assertEqual(_parse_missing_verdict(""), [])
        self.assertEqual(_parse_missing_verdict('{"missing": "tests"}'), [])   # not a list → null

    def test_no_reasoner_means_no_coverage_judgment(self):
        prov = _ScriptedProvider([
            _tool_resp("exec_command", {"cmd": "echo looked"}),
            _tool_resp("submit_plan", {"steps": ["Explore the workspace"]}),
        ])
        rlog = _Rlog()
        plan = Planner(prov, search_key="", max_gather_rounds=1, clock=lambda: _FIXED).plan_for(
            _msgs("script, tests, README"), rlog)
        self.assertNotIn("plan.missing_deliverables", [k for k, _ in rlog.events])
        self.assertEqual(len(plan.items), 1)


class GatherEvidenceTests(unittest.TestCase):
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

    def test_a_duplicate_steps_key_does_not_replace_the_plan_with_ordinals(self):
        # MEASURED (run 0727-121457): the model emitted `{"steps":[<five real steps>],"steps":[1,2,3,4,5]}`
        # — json.loads keeps the LAST duplicate key, so the real plan was silently discarded and the
        # ordinals became the plan. The coder was handed steps literally named "1", "2", "3".
        from cria.planner import _steps_from_submit
        raw = ('{"steps":["1. Research the API spec", "2. Write the resolver", "3. Add tests"],'
               '"steps":[1, 2, 3]}')
        out = _steps_from_submit({"tool_calls": [{"function": {"name": "submit_plan", "arguments": raw}}]})
        self.assertEqual(out, ["Research the API spec", "Write the resolver", "Add tests"])

    def test_a_bare_ordinal_is_not_a_step(self):
        # Whatever the route in, an integer or a lone "3." is not an action the coder can perform.
        from cria.planner import _clean_step
        for junk in (1, "1", "2.", " 3 ", "4)", ""):
            self.assertEqual(_clean_step(junk), "", repr(junk))
        self.assertEqual(_clean_step("1. Write the resolver"), "Write the resolver")

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

    def test_clean_step_keeps_a_closing_brace_the_step_itself_opened(self):
        # The blanket trailing-junk strip ate the brace off a step ending in a path template, so
        # `GET /handles/{handle}` reached the coder as `GET /handles/{handle` — and the coder follows
        # the plan verbatim, so it builds that URL wrong. A closer is junk only when UNBALANCED.
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("1. GET https://api.handle.me/handles/{handle}"),
                         "GET https://api.handle.me/handles/{handle}")
        self.assertEqual(_clean_step("Call the endpoint /v1/users/{id}"), "Call the endpoint /v1/users/{id}")
        self.assertEqual(_clean_step("Read config[0]"), "Read config[0]")
        # …while genuinely unbalanced JSON bleed is still stripped
        self.assertEqual(_clean_step('Write the script",]}'), "Write the script")

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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp('1. Set up the development environment and install dependencies.\n'
                          '2. Write the fibonacci module fib.py.\n3. Add unit tests in test_fib.py.'),  # plan
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp("1. grep -n 'resolve' ./tmp/read-only/openapi.json\n"
                          "2. Write resolver.py that calls the endpoint the spec names\n3. Add unit tests"),
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp("1. Create tests/test_x.py with content 'import sys, json, mock, requests; def test(): ...'\n"
                          "2. Write resolver.py"),
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp('1. Set up the development environment.\n2. Install the dependencies.'),
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp('1. Write fib.py.\n2. Add tests.'),
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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
            _tool_resp("web_search", {"query": "background"}),  # PHASE A: research round
            _content_resp('1. Fetch the OpenAPI specification from the API and read the real endpoint.\n'
                          '2. Write resolver.py.\n'
                          '3. Add README.md with installation instructions (pip install requests).'),  # plan
            _content_resp('{"missing": []}'),   # COVERAGE? nothing missing
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

    def test_a_judge_question_gets_room_to_answer_after_reasoning(self):
        # MEASURED (run 0727-114502, call 0028): finish_reason=length, completion_tokens=2000 — the
        # cap exactly — 8,865 chars of reasoning and ZERO content. A reasoning model spends the budget
        # THINKING before it writes anything, so a small cap does not buy a short answer, it buys NO
        # answer: the judge had already reached "steps to remove: 1 (installation)" and was cut off
        # before it could say so, and a plan opening with `pip install` and `venv` was accepted whole.
        from cria.planner import ASK_MAX_TOKENS
        from cria.loop import summarize   # the sibling primitive this must not undercut
        import inspect
        sibling = inspect.signature(summarize).parameters["max_tokens"].default
        self.assertGreaterEqual(ASK_MAX_TOKENS, sibling)

    def test_an_unanswered_judge_question_is_recorded_not_silent(self):
        # An empty answer is indistinguishable from "nothing to report" — every caller safe-nulls on
        # it — so a judgement that never happened must leave a trace instead of looking like a clean
        # verdict. That silence is why the cap went unnoticed.
        prov = _ScriptedProvider([_content_resp("")])
        rlog = _Rlog()
        Planner(prov, role=self._role(), clock=lambda: _FIXED)._ask("sys", "usr", rlog)
        self.assertIn("plan.ask_no_answer", [k for k, _ in rlog.events])

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


class StepObjectFieldChoiceTests(unittest.TestCase):
    """A model that wraps each step in an object gets its text pulled out by `_clean_step`. The field
    was chosen from a fixed key list, so an UNKNOWN intent key was invisible while a known mechanical
    key won.

    MEASURED (run 0727-135408): the living-plan rescue — the LAST resort for a step the coder cannot
    finish, and one-shot by design — spent 2,884 tokens returning five properly re-derived steps as
    `{"outcome": "Read Ada Handle API documentation file", "description": "read_file(path='…')"}`.
    `outcome` was not in the key list, so cria took `description`: the bare command. The noise judge
    then correctly dropped every one of them for "codifying a bare command", the re-derivation came
    back empty, and the rescue was recorded as DECLINED with its one shot gone — on a step that went
    on to burn 67 calls. cria chose the worse half of the model's answer and then rejected it.

    The rule: what the step IS beats how it is carried out, and a key nobody listed is still readable
    — the model's own field order says which it considers primary."""

    def test_the_outcome_wins_over_the_mechanism(self):
        from cria.planner import _clean_step
        step = {"outcome": "Read the Ada Handle API documentation",
                "description": "read_file(path='./tmp/read-only/search.txt')"}
        self.assertEqual(_clean_step(step), "Read the Ada Handle API documentation")

    def test_an_unknown_key_is_still_read(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step({"objective": "Write the resolver"}), "Write the resolver")

    def test_the_models_own_field_order_decides_when_no_key_is_known(self):
        """With nothing recognizable to go on, the model's OWN field order is the only signal — it
        puts what it considers primary first. Better than dropping the step for an unguessed name."""
        from cria.planner import _clean_step
        self.assertEqual(_clean_step({"aim": "Write the resolver", "how": "python resolve.py"}),
                         "Write the resolver")

    def test_the_known_keys_still_work(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step({"step": "Write the README"}), "Write the README")
        self.assertEqual(_clean_step({"description": "Write the README"}), "Write the README")

    def test_a_non_text_field_is_never_mistaken_for_the_step(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step({"id": 3, "status": "pending", "step": "Ship it"}), "Ship it")


class StepTrailingQuoteTests(unittest.TestCase):
    """`ed1ae9f` taught `_strip_trailing_junk` that a closing BRACE is junk only when unbalanced —
    `GET /handles/{handle}` had been reaching the coder as `GET /handles/{handle`. The line right
    below that rule still stripped quotes unconditionally.

    MEASURED (run 0727-135951): the planner's live-test step, whose raw arguments read
    `"5. Run live tests to resolve handles like 'goose' and 'papagoose'"`, reached the plan as
    `…and 'papagoose` — cria ate the closing quote off the two handle names the task is ABOUT. The
    coder follows a plan verbatim, and an unterminated quote in the one step that names the test
    fixtures is cria corrupting its own instruction.

    A single quote is never JSON-envelope junk (the envelope is double-quoted); a double quote is
    junk only when it has no partner."""

    def test_a_step_ending_in_a_single_quoted_name_keeps_its_quote(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("5. Run live tests to resolve handles like 'goose' and 'papagoose'"),
                         "Run live tests to resolve handles like 'goose' and 'papagoose'")

    def test_a_step_ending_in_a_double_quoted_name_keeps_its_quote(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step('6. Create a live test that resolves "goose" and "papagoose"'),
                         'Create a live test that resolves "goose" and "papagoose"')

    def test_an_apostrophe_in_prose_is_untouched(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Parse the API's response"), "Parse the API's response")

    def test_a_lone_trailing_quote_is_still_envelope_junk(self):
        """A model that quotes its array elements Python-style leaves one behind; parity catches it
        without touching a matched pair."""
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Implement tests against the real API\n'"),
                         "Implement tests against the real API")

    def test_the_json_envelope_junk_is_still_stripped(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step('Write the resolver",]}'), "Write the resolver")

    def test_the_brace_rule_from_ed1ae9f_still_holds(self):
        from cria.planner import _clean_step
        self.assertEqual(_clean_step("Call GET /handles/{handle}"), "Call GET /handles/{handle}")
