"""The gate's advisory filter may only delete a line the CHECKER wrote about code, and it says how many.

Two faults. The phrase test ran over every raw line of a check's output — including the source echo
inside a traceback and the body of a failure report — so a line of the coder's own code containing
"unused variable" was deleted from the middle of a block cria ships as "each is the checker's OWN
message". And the drop was silent, so a check whose whole output was advisory was indistinguishable
from a check that printed nothing."""
import unittest

from cria import probegate


def _raw(body):
    return (probegate.SECTION_PREFIX + "0" + probegate.SECTION_SUFFIX + "\n"
            + body + "\nEXIT:1\n")


class OnlyTheCheckersOwnLinesTests(unittest.TestCase):
    def test_a_source_echo_line_is_not_filtered_on_its_words(self):
        # pytest prints the failing function's body. This line is CODE, not a diagnostic about code.
        out = probegate.clean_gate_output(_raw(
            "t.py:9: in test_totals\n"
            "    unused_variable = compute()  # unused variable\n"
            "E   AssertionError: 3 != 4"))
        self.assertIn("unused_variable = compute()", out)

    def test_a_real_advisory_diagnostic_is_still_filtered(self):
        out = probegate.clean_gate_output(_raw("x.py:1:1 'os' imported but unused"))
        self.assertNotIn("imported but unused", out)
        self.assertIn("no error-class", out.lower())

    def test_the_drop_is_counted(self):
        out = probegate.clean_gate_output(_raw(
            "x.py:1:1 'os' imported but unused\nx.py:2:1 'sys' imported but unused"))
        self.assertIn("2 advisory line(s)", out)

    def test_nothing_dropped_says_nothing(self):
        out = probegate.clean_gate_output(_raw("x.py:5:4 undefined name 'foo'"))
        self.assertNotIn("advisory line(s)", out)

    def test_the_count_rides_alongside_a_red_gate_too(self):
        out = probegate.clean_gate_output(_raw(
            "x.py:1:1 'os' imported but unused\nx.py:5:4 undefined name 'foo'"))
        self.assertIn("undefined name 'foo'", out)
        self.assertIn("1 advisory line(s)", out)


class APayloadIsNotAVerdictTests(unittest.TestCase):
    """`{"error":"route_not_found","docs":"…"}` is a live service ANSWERING. It was read as a dead
    end on the phrase "not found" and squashed into a "tried this" note, which steers the model away
    from the one route that would have told it the real path."""

    def test_a_json_body_is_data_not_a_failure(self):
        from cria import focustrim
        self.assertFalse(focustrim._is_failure(
            '{"error": "route_not_found", "docs": "https://api.example.com/routes"}'))

    def test_a_shell_dead_end_is_still_a_failure(self):
        from cria import focustrim
        self.assertTrue(focustrim._is_failure("bash: frobnicate: command not found"))

    def test_something_that_only_looks_like_json_is_not_a_payload(self):
        from cria import focustrim
        self.assertTrue(focustrim._is_failure('{"error": "no such file or directory"'))


if __name__ == "__main__":
    unittest.main()
