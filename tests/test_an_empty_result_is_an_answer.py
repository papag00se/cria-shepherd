"""cria told a model its read had FAILED twelve times. The file was empty.

`orders-api-py x nemotron-elastic` 1787270062. `orders/__init__.py` is 0 bytes. `read_file` returned
it correctly — an empty tool body — and `_repeat_failed` classified that as a failure, so the repeat
guard chose its failure wording:

    [you have now made this exact call 12 times and it failed the same way every time … Repeating it
    will fail the same way. It has not answered the question, so do not read its result as the
    answer: use a different tool, or fix what made it fail, before asking again.]

The model obeyed it literally: "Maybe the file exists but empty? Let's try to view it", and — pushed
by "use a different tool" — called `view_image` on a `.py` file. It escaped only by shelling out to
`cat`, which printed the same nothing, and only then believed the emptiness. Twelve of 146 turns,
spent because cria refused to let it read a true answer as an answer (#5b).

An empty file, a grep that matched nothing, a command that printed nothing: each is a fact the coder
asked for and got. Same class as `selfcompact`'s "an empty line in a program's output is a value"
(e6a3626), one module over.

The repeat guard still fires on the REPETITION — that part was never wrong. It just no longer calls
the answer a failure.
"""

import unittest

from cria import focustrim


def _call(cid, body, name="read_file", args='{"path":"orders/__init__.py"}'):
    return [{"role": "assistant", "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}]},
            {"role": "tool", "tool_call_id": cid, "content": body}]


class AnEmptyBodyIsAValueTests(unittest.TestCase):
    def test_the_measured_case_an_empty_file(self):
        self.assertFalse(focustrim._repeat_failed(_call("c1", ""), "c1"))

    def test_whitespace_only_output_is_also_a_value(self):
        """A grep that matched nothing, a command that printed a blank line."""
        for body in ("", "\n", "   ", "\n\n"):
            with self.subTest(body=repr(body)):
                self.assertFalse(focustrim._repeat_failed(_call("c1", body), "c1"))


class RealFailuresStillCountTests(unittest.TestCase):
    """The guard's job is unchanged for everything that genuinely failed."""

    def test_a_nonzero_exit_from_the_lowered_command(self):
        self.assertTrue(focustrim._repeat_failed(_call("c1", "boom\nEXIT:1"), "c1"))

    def test_a_zero_exit_is_not_a_failure(self):
        self.assertFalse(focustrim._repeat_failed(_call("c1", "ok\nEXIT:0"), "c1"))

    def test_a_refusal_cria_authored(self):
        from cria import denial
        self.assertTrue(focustrim._repeat_failed(
            _call("c1", denial.mark("that path is not there — nothing was read")), "c1"))


if __name__ == "__main__":
    unittest.main()
