import unittest

from cria.jsontext import extract_json_object, strip_think


class JsonTextTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(extract_json_object('{"a": 1}'), {"a": 1})

    def test_json_fences_stripped(self):
        raw = 'Here you go:\n```json\n{"engagement": "task"}\n```\n'
        self.assertEqual(extract_json_object(raw), {"engagement": "task"})

    def test_thinking_tag_variant_stripped(self):
        # M7: some models use <thinking>…</thinking> (not <think>). The strip regex required <think\b, so
        # a <thinking> block was NOT stripped and _scan_object returned the FIRST brace object — the
        # reasoning's, not the answer's — under-engaging a real coding task. Must strip both forms.
        raw = '<thinking>maybe {"engagement":"question"} but no</thinking>\n{"engagement":"task","task_type":"coding"}'
        self.assertEqual(extract_json_object(raw), {"engagement": "task", "task_type": "coding"})

    def test_think_preamble_stripped(self):
        raw = "<think>let me consider…</think>\n{\"task_type\": \"coding\"}"
        self.assertEqual(extract_json_object(raw), {"task_type": "coding"})

    def test_unclosed_think_dropped(self):
        # a dangling <think> with no close AND no real object after it: tail goes.
        self.assertIsNone(extract_json_object("<think>reasoning with { a brace"))

    def test_unclosed_think_preserves_following_object(self):
        # model forgot to close <think> before emitting the answer JSON: the real
        # object in the tail must survive (never blindly slice from <think to end).
        raw = '<think>deciding what to do…\n{"engagement": "task"}'
        self.assertEqual(extract_json_object(raw), {"engagement": "task"})
        # strip_think keeps the tail so the answer is still reachable.
        self.assertIn('{"engagement": "task"}', strip_think(raw))

    def test_unclosed_think_preserves_fenced_following_object(self):
        # same, but the answer arrives inside a ```json fence after the open tag.
        raw = '<think>hmm\n```json\n{"task_type": "coding"}\n```'
        self.assertEqual(extract_json_object(raw), {"task_type": "coding"})

    def test_trailing_prose_ignored(self):
        raw = '{"x": 1} and then some explanation about why.'
        self.assertEqual(extract_json_object(raw), {"x": 1})

    def test_braces_inside_strings(self):
        raw = '{"reason": "use the {handle} field"}'
        self.assertEqual(extract_json_object(raw), {"reason": "use the {handle} field"})

    def test_skips_non_object_first_brace(self):
        # a leading malformed brace span, then a real object.
        raw = "{ not json } trailing {\"ok\": true}"
        self.assertEqual(extract_json_object(raw), {"ok": True})

    def test_none_on_no_object(self):
        self.assertIsNone(extract_json_object("no json here"))
        self.assertIsNone(extract_json_object(""))

    def test_strip_think_leaves_answer(self):
        self.assertEqual(strip_think("<think>x</think>answer").strip(), "answer")


if __name__ == "__main__":
    unittest.main()


class DuplicateKeyTests(unittest.TestCase):
    """`json.loads` keeps the LAST value when a key repeats, which for model output is usually the
    wrong one: a small model emits its real answer first and a degenerate echo after. Measured (run
    0727-121457): a planner emitted `{"steps":[<five real steps>],"steps":[1,2,3,4,5]}` and stdlib
    semantics threw the plan away, handing the coder steps named "1", "2", "3". This lives in
    jsontext because EVERY model-produced payload is parsed here — verdicts, tool arguments, plans —
    so the quirk is handled once rather than wherever the symptom happens to surface."""

    def test_repeated_key_keeps_the_first_real_value(self):
        from cria.jsontext import loads
        self.assertEqual(loads('{"steps":["real","plan"],"steps":[1,2]}')["steps"], ["real", "plan"])

    def test_an_empty_first_value_does_not_shadow_a_real_one(self):
        from cria.jsontext import loads
        self.assertEqual(loads('{"missing":[],"missing":["the tests"]}')["missing"], ["the tests"])

    def test_verdict_readers_get_it_too(self):
        from cria.jsontext import extract_json_object
        self.assertEqual(extract_json_object('{"missing":[],"missing":["x"]}')["missing"], ["x"])

    def test_tool_arguments_get_it_too(self):
        from cria.toolargs import parse_args
        self.assertEqual(parse_args('{"path":"real.py","path":""}')["path"], "real.py")
