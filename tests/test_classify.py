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

