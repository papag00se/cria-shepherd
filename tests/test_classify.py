import json
import unittest

from cria.classify import Classifier, completion_text, latest_user_text


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def decide(self, name, choice, reason, **kw):
        self.events.append(("decision", {"decision": name, "choice": choice, "reason": reason, **kw}))


class _Provider:
    """Returns a canned OpenAI response; counts calls to prove caching."""

    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    def chat(self, body, rlog):
        self.calls += 1
        return json.dumps({"choices": [{"message": {"content": self._content}}]}).encode()


def _msgs(text: str):
    return [{"role": "user", "content": text}]


class ClassifyHelperTests(unittest.TestCase):
    def test_latest_user_text_takes_last_user(self):
        msgs = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "x"}, {"role": "user", "content": "second"}]
        self.assertEqual(latest_user_text(msgs), "second")

    def test_latest_user_text_skips_cria_injected_scaffolding(self):
        # THE reasoner-misroute footgun: after a harness compaction the latest user turns are cria's
        # own continuation reframe + squash note, which classify as reasoning and route a CODING
        # session onto the reasoner. latest_user_text must skip cria scaffolding and return the task.
        msgs = [
            {"role": "user", "content": "<environment_context><cwd>/x</cwd></environment_context>"},
            {"role": "user", "content": "Write a Python script that resolves an Ada Handle to an address"},
            {"role": "assistant", "content": "working"},
            {"role": "user", "content": "⟦ctx:continuation⟧ Earlier in THIS session you worked on this task and produced the summary below"},
            {"role": "user", "content": "[removed 13 earlier failed attempts to keep you focused]"},
            {"role": "user", "content": "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems"},
        ]
        self.assertIn("Ada Handle", latest_user_text(msgs))     # the REAL task, not cria's briefing
        self.assertNotIn("cria", latest_user_text(msgs))

    def test_latest_user_text_returns_genuine_followup_over_older_task(self):
        # a genuine NEW user turn is NOT cria scaffolding → it's still returned (follow-up detection kept)
        msgs = [{"role": "user", "content": "old task"},
                {"role": "user", "content": "⟦ctx:rollup⟧ prior work summary"},
                {"role": "user", "content": "now also add a CLI flag"}]
        self.assertEqual(latest_user_text(msgs), "now also add a CLI flag")

    def test_completion_text_handles_list_content(self):
        raw = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "hello"}]}}]}).encode()
        self.assertEqual(completion_text(raw), "hello")


class ClassifierTests(unittest.TestCase):
    def test_parses_clean_classification(self):
        p = _Provider('{"engagement": "task", "task_type": "coding", "reason": "write handler + tests"}')
        c = Classifier(p, bias="task").classify(_msgs("write a lambda handler"), _Rlog())
        self.assertEqual((c.engagement, c.task_type), ("task", "coding"))
        self.assertIn("handler", c.reason)

    def test_parses_fenced_classification(self):
        p = _Provider('```json\n{"engagement": "question", "task_type": "question"}\n```')
        c = Classifier(p).classify(_msgs("what does this do?"), _Rlog())
        self.assertEqual(c.engagement, "question")

    def test_unparseable_falls_back_to_bias(self):
        p = _Provider("I think this is a coding task, definitely.")  # no JSON
        c = Classifier(p, bias="task").classify(_msgs("hmm"), _Rlog())
        self.assertEqual(c.engagement, "task")  # bias, the safe (heavier) direction
        self.assertIn("fallback", c.reason)

    def test_persistent_failure_escalates_to_error(self):
        p = _Provider("no json here")  # every classify fails → fallback
        clf = Classifier(p, bias="task")
        rlog = _Rlog()
        for i in range(3):
            clf.classify(_msgs(f"distinct task {i}"), rlog)  # distinct → not cached, each re-fails
        kinds = [k for k, _ in rlog.events]
        self.assertIn("route.classify_degraded", kinds)   # a broken classifier is no longer silent
        deg = [kw for k, kw in rlog.events if k == "route.classify_degraded"][0]
        self.assertEqual(deg["level"], "error")

    def test_a_clean_classify_resets_the_failure_streak(self):
        # two fails then a success then a fail → no escalation (streak was reset)
        clf = Classifier(_Provider("junk"), bias="task")
        rlog = _Rlog()
        clf.classify(_msgs("a"), rlog)
        clf.classify(_msgs("b"), rlog)
        clf._provider = _Provider('{"engagement":"task","task_type":"coding"}')
        clf.classify(_msgs("c"), rlog)   # clean → resets
        clf._provider = _Provider("junk")
        clf.classify(_msgs("d"), rlog)   # 1 fail, below threshold
        self.assertNotIn("route.classify_degraded", [k for k, _ in rlog.events])

    def test_bad_enum_values_are_normalized(self):
        p = _Provider('{"engagement": "WILD", "task_type": "nonsense"}')
        c = Classifier(p, bias="simple").classify(_msgs("x"), _Rlog())
        self.assertEqual(c.engagement, "simple")  # invalid → bias
        self.assertEqual(c.task_type, "coding")  # invalid → derived default

    def test_result_is_cached_per_task(self):
        p = _Provider('{"engagement": "task", "task_type": "coding"}')
        clf = Classifier(p)
        first = clf.classify(_msgs("same request"), _Rlog())
        second = clf.classify(_msgs("same request"), _Rlog())
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(p.calls, 1, "the classifier model is called once per task, not per turn")


if __name__ == "__main__":
    unittest.main()


class TitleAuxTests(unittest.TestCase):
    def test_title_request_is_detected(self):
        from cria.classify import is_title_request
        title = ("You are a helpful assistant. You will be presented with a user prompt, and your "
                 "job is to provide a short title for a task that will be created from that prompt. "
                 "Generate a concise UI title (up to 36 characters). Fill the structured title field.")
        self.assertTrue(is_title_request(title))
        self.assertFalse(is_title_request("write a Python Lambda handler that resolves an Ada handle"))

    def test_title_request_routes_to_question_not_task(self):
        # even though the title prompt EMBEDS a coding task, it must not be planned
        import json
        title = ("provide a short title for a task. the task: build a Python Lambda with tests and a README")
        class _P:
            def chat(self, body, rlog):
                raise AssertionError("classifier LLM must NOT be called for a title aux request")
        class _R:
            def __init__(self): self.events=[]
            def emit(self,k,**kw): self.events.append((k,kw))
            def decide(self,*a,**k): pass
        c = Classifier(_P())
        got = c.classify([{"role":"user","content":title}], _R())
        self.assertEqual(got.engagement, "question")   # -> proxy, never the plan loop



class JudgeBudgetTests(unittest.TestCase):
    """The cap is the ONLY bound on an internal judge call: `guard_rumination` is wired to the coder
    path alone, and these calls are non-streamed, so nothing else can stop a runaway. It therefore
    stays finite — but it must sit well above where real judgements land, because a judge that hits it
    produces NOTHING (a reasoning model spends the budget thinking before it writes a character), and
    a lost verdict costs more than a long one: measured, two of them spent a one-shot rescue.

    MEASURED over 493 judge calls (runs 0727-13xx..16xx): 486 answered — median 981 tokens, p90 2,468,
    p99 8,192 — and 7 answered NOTHING, all at exactly 8,192. So the cap bound only the top 1.4%, and
    every time it bound, the judgement was lost. 16,384 leaves the p90 case 6.6x headroom while
    keeping the bound finite; judge INPUTS run ~6k tokens against a 49,152 window, so the reserve
    fits comfortably."""

    def test_the_judge_budget_clears_the_measured_tail(self):
        from cria.classify import JUDGE_MAX_TOKENS
        self.assertGreater(JUDGE_MAX_TOKENS, 8192, "8192 was measured to lose 1.4% of judgements whole")
        self.assertLessEqual(JUDGE_MAX_TOKENS, 20000, "it is still a BOUND — a runaway has nothing else")

    def test_the_planner_ask_shares_it(self):
        from cria.classify import JUDGE_MAX_TOKENS
        from cria.planner import ASK_MAX_TOKENS
        self.assertEqual(ASK_MAX_TOKENS, JUDGE_MAX_TOKENS)
