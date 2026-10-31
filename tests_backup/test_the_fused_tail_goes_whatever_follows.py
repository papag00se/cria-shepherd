"""A fused second call is trimmed whatever kind of call it is.

`trim_fused_tail` scans backwards for the protocol tags that open a second call the model fused into
its write payload. It scanned PAST a bare single token — which fitted the walked case, where the
second call was a `write_file` whose `path` is one word — and broke on anything longer.

So when the fused call was an `exec_command`, the scan met `mvn -q compile` first, broke before it
ever saw a tag, and returned the payload untouched. Verified against the four captured payloads of
feed-pipeline-java x nemotron-elastic 1787436645: all four came back unchanged, cria then refused its
own write four times as malformed XML pointing at `line 34: </function>`, and the model — whose
rejected payload cria had elided from the transcript — could not see what it had sent."""
import unittest

from cria import writeproxy

REAL = "<project>\n  <build>\n  </build>\n</project>\n"
FUSE = "</function>\n</tool_call>\n<tool_call>\n"


class WhateverTheSecondCallIsTests(unittest.TestCase):
    def test_a_fused_exec_command_is_trimmed(self):
        payload = REAL + FUSE + "<function=exec_command>\n<parameter=cmd>\nmvn -q compile\n"
        self.assertEqual(writeproxy.trim_fused_tail(payload), REAL)

    def test_a_fused_write_file_still_is(self):
        payload = REAL + FUSE + "<function=write_file>\n<parameter=path>\nsrc/Foo.java\n"
        self.assertEqual(writeproxy.trim_fused_tail(payload), REAL)

    def test_a_fused_call_with_a_multi_line_body(self):
        payload = REAL + FUSE + ("<function=exec_command>\n<parameter=cmd>\n"
                                 "cd /w && mvn -q compile\nmvn test\necho done\n")
        self.assertEqual(writeproxy.trim_fused_tail(payload), REAL)

    def test_an_ordinary_file_is_untouched(self):
        self.assertEqual(writeproxy.trim_fused_tail(REAL), REAL)

    def test_prose_that_merely_mentions_a_tag_is_untouched(self):
        prose = "line one of a real file\nline two mentions </function> in prose\nline three\n"
        self.assertEqual(writeproxy.trim_fused_tail(prose), prose)

    def test_a_long_file_with_no_fused_call_is_untouched(self):
        big = "".join(f"def function_number_{i}(a, b):\n    return a + b\n" for i in range(200))
        self.assertEqual(writeproxy.trim_fused_tail(big), big)


if __name__ == "__main__":
    unittest.main()
