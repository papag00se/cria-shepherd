"""An unclosed `<parameter=…>` swallowed the next tool call, and the write was refused twelve times.

`feed-pipeline-java x nemotron-elastic`, cycle 1 of the 100% campaign. The model emitted a
`write_file` and a `task_complete` in one turn, XML dialect, and forgot the `</parameter>` on the
write's `content`. `_XML_PARAM` is non-greedy — which sounds safe and is not, because with no closing
tag of its own the match simply runs on to the NEXT one, in the other call. The recorded value ends:

    …</project>
    </function>
    </tool_call>
    <tool_call>
    <function=task_complete>

`validate-before-lower` then refused the `pom.xml` as malformed XML, at "line 34, column 1" — exactly
where cria's junk began — TWELVE times. Fourteen calls lost; the model escaped only by switching to
`edit_file`. The trailing call is always `task_complete`, a recent addition to the menu, so a feature
added to make completion cleaner was corrupting the write in front of it.

This was already NAMED in the file, on gate 3 of `recover_leaked_tool_calls`: "nine
`<parameter=steps>` openers closed by ONE `</parameter>` collapse into a single string carrying the
other eight tags verbatim… a PRE-EXISTING property of the content path". Named, and never fixed.

THE REAL CLOSING TAG STILL WINS. A `write_file` whose content is a document ABOUT tool calls really
does contain `<parameter=` and `</function>` text — `_outermost` exists because that happens — so the
boundary only applies when there is no `</parameter>` to find before it.
"""

import json
import unittest

from cria import massage

TOOLS = [
    {"type": "function", "function": {"name": "write_file", "parameters": {
        "type": "object", "properties": {"path": {}, "content": {}},
        "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "task_complete", "parameters": {
        "type": "object", "properties": {"summary": {}}, "required": ["summary"]}}},
]


def calls(raw: str):
    out = massage.apply({"choices": [{"message": {"role": "assistant", "content": raw}}]}, tools=TOOLS)
    return {tc["function"]["name"]: json.loads(tc["function"]["arguments"])
            for tc in (out["choices"][0]["message"].get("tool_calls") or [])}


class TheMeasuredCorruptionTests(unittest.TestCase):
    RAW = ("<tool_call>\n<function=write_file>\n<parameter=path>pom.xml</parameter>\n"
           "<parameter=content><project>\n  <artifactId>x</artifactId>\n</project>\n"
           "</function>\n</tool_call>\n<tool_call>\n<function=task_complete>\n"
           "<parameter=summary>all done</parameter>\n</function>\n</tool_call>")

    def test_the_write_does_not_swallow_the_next_call(self):
        content = calls(self.RAW)["write_file"]["content"]
        self.assertNotIn("task_complete", content)
        self.assertNotIn("</tool_call>", content)
        self.assertNotIn("</function>", content)

    def test_the_write_keeps_its_own_payload(self):
        content = calls(self.RAW)["write_file"]["content"]
        self.assertIn("<project>", content)
        self.assertIn("</project>", content)

    def test_the_second_call_still_arrives(self):
        self.assertEqual(calls(self.RAW)["task_complete"]["summary"], "all done")


class SiblingOpenersDoNotCollapseTests(unittest.TestCase):
    """The shape gate 3's note describes: several openers, one closing tag between them."""

    RAW = ("<tool_call>\n<function=write_file>\n"
           "<parameter=path>a.txt\n<parameter=content>hello</parameter>\n"
           "</function>\n</tool_call>")

    def test_each_parameter_keeps_its_own_value(self):
        a = calls(self.RAW)["write_file"]
        self.assertEqual(a["path"], "a.txt")
        self.assertEqual(a["content"], "hello")


class ANestedPayloadIsSTILLCutOneLevelUpTests(unittest.TestCase):
    """HONEST LIMIT, not a claim of a fix. A file ABOUT tool calls contains the tags, and that case
    is truncated — but by `_XML_FN`, whose own non-greedy match ends the function BODY at the first
    nested `</function>`, before the parameter reader ever sees it.

    Checked against the code as it stood before this change, which produced
    `Call it like this:\n<function=web_fetch>\n<parameter=url>http://x` — also cut, and further into
    the payload. So this is pre-existing and one layer above, and it is recorded rather than fixed:
    zero occurrences in the cycle-1 corpus, and #15 says measure prevalence before building.

    What this test pins is that the behaviour did not get WORSE, and that the boundary logic below is
    not what causes it."""

    RAW = ("<tool_call>\n<function=write_file>\n<parameter=path>README.md</parameter>\n"
           "<parameter=content>Call it like this:\n"
           "<function=web_fetch>\n<parameter=url>http://x</parameter>\n</function>\n"
           "That is the whole syntax.</parameter>\n</function>\n</tool_call>")

    def test_the_call_is_still_recovered_and_the_head_of_the_payload_kept(self):
        content = calls(self.RAW)["write_file"]["content"]
        self.assertEqual(calls(self.RAW)["write_file"]["path"], "README.md")
        self.assertIn("Call it like this:", content)

    def test_the_cut_is_the_function_regex_not_the_parameter_boundary(self):
        """`_XML_FN` ends the body at the nested `</function>`; the tail is gone before we look."""
        body = massage._XML_FN.search(self.RAW).group(2)
        self.assertNotIn("That is the whole syntax.", body)


class TheWellFormedCaseIsUnchangedTests(unittest.TestCase):
    RAW = ("<tool_call>\n<function=write_file>\n<parameter=path>a.txt</parameter>\n"
           "<parameter=content>hello</parameter>\n</function>\n</tool_call>")

    def test_nothing_moved(self):
        self.assertEqual(calls(self.RAW)["write_file"], {"path": "a.txt", "content": "hello"})


if __name__ == "__main__":
    unittest.main()
