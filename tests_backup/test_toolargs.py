import unittest

from cria.toolargs import PATH_KEYS, parse_args, tool_path


class ParseArgsTests(unittest.TestCase):
    def test_dict_passthrough(self):
        d = {"a": 1}
        self.assertIs(parse_args(d), d)

    def test_json_string_parsed(self):
        self.assertEqual(parse_args('{"path":"x.py"}'), {"path": "x.py"})

    def test_lenient_control_chars(self):
        # a raw newline inside a string value (a small model's leak) is invalid strict JSON but
        # parse_args tolerates it (strict=False)
        self.assertEqual(parse_args('{"content":"a\nb"}'), {"content": "a\nb"})

    def test_junk_and_non_dict_to_empty(self):
        self.assertEqual(parse_args("not json"), {})
        self.assertEqual(parse_args("[1,2,3]"), {})   # valid JSON but not an object
        self.assertEqual(parse_args(None), {})
        self.assertEqual(parse_args(12), {})


class ToolPathTests(unittest.TestCase):
    def test_alias_order(self):
        self.assertEqual(tool_path({"path": "a"}), "a")
        self.assertEqual(tool_path({"file_path": "b"}), "b")
        self.assertEqual(tool_path({"file": "c"}), "c")
        self.assertEqual(tool_path({"filename": "d"}), "d")

    def test_parses_string_args(self):
        self.assertEqual(tool_path('{"file_path":"y.py"}'), "y.py")

    def test_none_when_absent(self):
        self.assertIsNone(tool_path({"query": "x"}))
        self.assertIsNone(tool_path("junk"))

    def test_keys_are_the_shared_set(self):
        self.assertEqual(PATH_KEYS, ("path", "file_path", "file", "filename"))


if __name__ == "__main__":
    unittest.main()
