"""cria refused the same pom.xml eight times at a line the coder could not see.

Cycle 4 cell 22, `feed-pipeline-java × nemotron-elastic`, strict 0/5, 5% useful. The model omitted
`</parameter>` and opened a second call in the same turn, so every `pom.xml` it sent ended:

    </project>
    </function>
    </tool_call>
    <tool_call>
    <function=write_file>
    <parameter=path>
    src/main/java/pipeline/Importer.java

cria's validate-before-write refused it — correctly, it is not well-formed XML — with

    write_file REFUSED (not written): this would replace a currently-valid pom.xml with content that
    does not parse — not well-formed (invalid token): line 34, column 1.

Line 34 was `</function>`. The coder cannot re-read its own rejected payload (cria elides it as
`[1107 characters — this edit was REJECTED, nothing was written to pom.xml]`), so a line number into
an invisible document points at nothing. Across eight refusals its reasoning never once mentions
line 34; at call 0016 it re-derived the identical file by hand and was refused again. It escaped only
by switching to `edit_file`, which put a `<dependency>` block outside `<dependencies>` and left the
project unreadable by Maven for the rest of the run.

TWO FIXES, and they are not alternatives:

- **Cut the junk.** `_protocol_debris` answers the all-or-nothing case — content that is NOTHING but
  protocol tags — and correctly declines when a genuine file merely has them appended. That is the
  expensive case, and cria already holds the knowledge: `massage._LEAK_DEBRIS` lists these sentinels
  as tokens that never appear in legitimate prose, and `massage._bounded_xml_params` cuts them out of
  arguments cria itself parses. The gap was a SERVER-parsed tool call, which `recover_leaked_tool_calls`
  skips by design (`if msg.get("tool_calls"): continue`).
- **Show the line.** When the validator does refuse, quote the line its coordinate names — the way the
  sibling EDIT path has quoted the file's real text around a divergence for months.

WHAT IS NOT CUT: only a trailing run, and the cut may only land ON a protocol tag. A bare single-token
line is scanned past but never becomes the cut — both ends of the debris need that, and for opposite
reasons: a bare token TRAILS the tags (the next call's `path` value, met first going backwards) and
also PRECEDES them in ordinary markup (`</project>`, `}`), where cutting at it would eat the file.
"""

import unittest

from cria import writeproxy

POM_REAL = ('<?xml version="1.0"?>\n'
            '<project>\n'
            '  <artifactId>feed</artifactId>\n'
            '</project>\n')
FUSED_TAIL = ('</function>\n'
              '</tool_call>\n'
              '<tool_call>\n'
              '<function=write_file>\n'
              '<parameter=path>\n'
              'src/main/java/pipeline/Importer.java')


class TheJunkIsCutTests(unittest.TestCase):
    def test_the_measured_pom(self):
        self.assertEqual(writeproxy.trim_fused_tail(POM_REAL.rstrip("\n") + "\n" + FUSED_TAIL),
                         POM_REAL)

    def test_what_is_left_actually_parses(self):
        """The point of the cut: the file cria was refusing was fine underneath."""
        from xml.etree import ElementTree
        ElementTree.fromstring(writeproxy.trim_fused_tail(
            POM_REAL.rstrip("\n") + "\n" + FUSED_TAIL))

    def test_a_tail_with_no_trailing_value(self):
        self.assertEqual(writeproxy.trim_fused_tail(POM_REAL + "</function>\n</tool_call>\n"),
                         POM_REAL)

    def test_the_cut_is_reported_and_the_clean_file_is_what_gets_written(self):
        """Both halves in one drive: the trim is not silent, and the bytes that reach the heredoc are
        the file without its junk."""
        import base64
        import json
        seen = []

        class _R:
            def emit(self, name, **k):
                seen.append((name, k))

        comp = {"choices": [{"message": {"tool_calls": [{
            "id": "1", "type": "function",
            "function": {"name": "write_file", "arguments": json.dumps(
                {"path": "pom.xml", "content": POM_REAL.rstrip("\n") + "\n" + FUSED_TAIL})}}]}}]}
        shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
        out = writeproxy.translate_outbound(comp, shell, _R(), injected={"write_file"})
        self.assertIn("writeproxy.write_fused_tail_trimmed", [n for n, _ in seen])
        cmd = json.loads(out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        cmd = cmd.get("cmd") or cmd.get("command")
        cmd = cmd[-1] if isinstance(cmd, list) else cmd
        blob = cmd.split("raw=base64.b64decode('")[1].split("')")[0]
        self.assertEqual(base64.b64decode(blob).decode(), POM_REAL)


class RealFilesAreUntouchedTests(unittest.TestCase):
    UNTOUCHED = {
        "a leak detector's own source": ('MARKS = ("</tool_call>", "<function=")\n'
                                         "def has_leak(text):\n"
                                         "    return any(m in text for m in MARKS)\n"),
        "plain prose": "hello world\n",
        "clean xml ending in a single-token close": '<?xml version="1.0"?>\n<project>\n</project>\n',
        "html": "<html>\n<body>\n<p>Hi there</p>\n</body>\n</html>\n",
        "go": "package main\n\nfunc main() {}\n",
        "python ending in a bare word": "def f():\n    return 1\n\nmain\n",
        "empty": "",
    }

    def test_none_of_them_are_cut(self):
        for name, text in self.UNTOUCHED.items():
            with self.subTest(file=name):
                self.assertEqual(writeproxy.trim_fused_tail(text), text)

    def test_content_that_is_ONLY_debris_is_left_to_the_refusal(self):
        """That case has its own message — it is not a file with junk on it, it is junk."""
        only = "</function>\n</tool_call>\n<tool_call>\ntests\n"
        self.assertTrue(writeproxy._protocol_debris(only))
        self.assertEqual(writeproxy.trim_fused_tail(only), only)


class TheRefusalShowsTheLineTests(unittest.TestCase):
    def _helpers(self):
        import textwrap
        src = __import__("pathlib").Path(writeproxy.__file__).read_text()
        i = src.index("def _v(path, raw):")
        ns: dict = {}
        exec(textwrap.dedent(src[i:src.index("'''", i)]), ns)
        return ns

    def test_it_quotes_the_line_the_coordinate_names(self):
        ns = self._helpers()
        bad = POM_REAL.rstrip("\n") + "\n</function>\n"
        msg = ns["_v"]("pom.xml", bad)
        self.assertIn("line 5", msg)
        self.assertIn("</function>", ns["_at"](bad, msg))

    def test_a_message_with_no_line_number_adds_nothing(self):
        ns = self._helpers()
        self.assertEqual(ns["_at"]("x = 1\n", "something went wrong"), "")

    def test_a_line_number_past_the_end_adds_nothing(self):
        """#5b: a message that cannot name a line must not print one."""
        ns = self._helpers()
        self.assertEqual(ns["_at"]("x = 1\n", "bad thing: line 99, column 1"), "")


if __name__ == "__main__":
    unittest.main()
