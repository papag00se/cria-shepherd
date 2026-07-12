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
        c = Classifier(p, "m", bias="task").classify(_msgs("write a lambda handler"), _Rlog())
        self.assertEqual((c.engagement, c.task_type), ("task", "coding"))
        self.assertIn("handler", c.reason)

    def test_parses_fenced_classification(self):
        p = _Provider('```json\n{"engagement": "question", "task_type": "question"}\n```')
        c = Classifier(p, "m").classify(_msgs("what does this do?"), _Rlog())
        self.assertEqual(c.engagement, "question")

    def test_unparseable_falls_back_to_bias(self):
        p = _Provider("I think this is a coding task, definitely.")  # no JSON
        c = Classifier(p, "m", bias="task").classify(_msgs("hmm"), _Rlog())
        self.assertEqual(c.engagement, "task")  # bias, the safe (heavier) direction
        self.assertIn("fallback", c.reason)

    def test_bad_enum_values_are_normalized(self):
        p = _Provider('{"engagement": "WILD", "task_type": "nonsense"}')
        c = Classifier(p, "m", bias="simple").classify(_msgs("x"), _Rlog())
        self.assertEqual(c.engagement, "simple")  # invalid → bias
        self.assertEqual(c.task_type, "coding")  # invalid → derived default

    def test_result_is_cached_per_task(self):
        p = _Provider('{"engagement": "task", "task_type": "coding"}')
        clf = Classifier(p, "m")
        first = clf.classify(_msgs("same request"), _Rlog())
        second = clf.classify(_msgs("same request"), _Rlog())
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(p.calls, 1, "the classifier model is called once per task, not per turn")


if __name__ == "__main__":
    unittest.main()
