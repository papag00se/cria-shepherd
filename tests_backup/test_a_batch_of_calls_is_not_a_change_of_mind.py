"""Recovering a lost turn must recover the whole batch, not only its last call.

`recover_reasoning_tool_calls` forwards a tool call the model emitted in its reasoning channel. It
may only forward a TERMINAL one — a span with prose after it is a thought the model reasoned past,
and replaying it would repeat an action it abandoned. That rule was implemented as `spans[-1]`,
which is right for a change of mind and wrong for a batch: a model asking for three files at once
emits three spans back to back and had two of them dropped.

Walked twice in the L5 cells scoring under 60. orders-api-py x qwen35 emitted parallel batches on
five turns and lost 10 calls, each re-asked singly on a later turn. handles-cli-node x qwen35 asked
for lookup.js, package.json and README.md together at call 0003, got one, and spent calls 0004 and
0005 re-asking for the other two.

Adjacency is the test, and it is the model's own punctuation. Between two spans of a batch sits only
the dialect's wrapper; between two thoughts sit words.
"""
import json
import unittest

from cria import massage

TOOLS = [{"function": {"name": "read_file",
                       "parameters": {"properties": {"path": {"type": "string"}},
                                      "required": ["path"]}}}]


def _block(path):
    return ("<tool_call>\n<function=read_file>\n<parameter=path>\n"
            f"{path}\n</parameter>\n</function>\n</tool_call>")


def _paths(reasoning):
    comp = {"choices": [{"message": {"content": "", "reasoning_content": reasoning},
                         "finish_reason": "stop"}]}
    out = massage.recover_reasoning_tool_calls(comp, TOOLS, None)
    calls = out["choices"][0]["message"].get("tool_calls") or []
    return [json.loads(c["function"]["arguments"])["path"] for c in calls]


class ABatchOfCallsIsNotAChangeOfMind(unittest.TestCase):

    def test_a_back_to_back_batch_is_forwarded_whole(self):
        r = "I need three files.\n" + "\n".join(_block(p) for p in ("a.py", "b.py", "c.py"))
        self.assertEqual(["a.py", "b.py", "c.py"], _paths(r))

    def test_words_between_two_calls_still_mean_the_first_was_abandoned(self):
        r = ("Maybe read a.py.\n" + _block("a.py")
             + "\nActually no, that is the wrong file, I want c.py instead.\n" + _block("c.py"))
        self.assertEqual(["c.py"], _paths(r))

    def test_one_call_is_unchanged(self):
        self.assertEqual(["only.py"], _paths("Read it.\n" + _block("only.py")))

    def test_a_batch_after_an_abandoned_thought_takes_the_batch_only(self):
        r = ("First idea.\n" + _block("old.py") + "\nOn reflection I need both of these.\n"
             + _block("x.py") + "\n" + _block("y.py"))
        self.assertEqual(["x.py", "y.py"], _paths(r))


if __name__ == "__main__":
    unittest.main()
