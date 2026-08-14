"""The research read-ledger counts reading, not writing.

See ReadingBackYourOwnWritingIsNotResearchTests below for the incident.
"""

import unittest




class ReadingBackYourOwnWritingIsNotResearchTests(unittest.TestCase):
    """The research step closed on a file the coder had just created.

    nemotron-elastic/rust 0033. The block headed "WHAT HAS REALLY BEEN READ THIS SESSION" listed
    `tests/test_nested_lookup.rs`, written by the coder four calls earlier, and the judge closed the
    documentation step with "So we have DONE." No page defining the toml crate API was read at any
    point in the run — a fifth of the run's budget spent before any code changed.

    A file that existed BEFORE the session — a seed, a schema, a data set — still counts. That is
    real reading, and covering files rather than fetches alone is a deliberate decision recorded in
    research.py: research is reading, whatever the source. Only the coder's own output is excluded.
    """

    def call(self, name, path, tid):
        return {"role": "assistant", "content": None,
                "tool_calls": [{"id": tid, "type": "function",
                                "function": {"name": name,
                                             "arguments": '{"path": "%s"}' % path}}]}

    def result(self, tid, body):
        return {"role": "tool", "tool_call_id": tid, "content": body}

    def test_a_file_the_coder_wrote_does_not_count(self):
        from cria.research import files_read
        msgs = [self.call("write_file", "tests/mine.rs", "w1"), self.result("w1", "Wrote it"),
                self.call("read_file", "tests/mine.rs", "r1"), self.result("r1", "fn t() {}")]
        self.assertEqual(files_read(msgs), [])

    def test_a_file_that_was_already_there_still_counts(self):
        from cria.research import files_read
        msgs = [self.call("read_file", "Cargo.toml", "r1"),
                self.result("r1", '[package]\nname = "x"')]
        self.assertEqual([p for p, _ in files_read(msgs)], ["Cargo.toml"])

    def test_both_at_once(self):
        from cria.research import files_read
        msgs = [self.call("write_file", "tests/mine.rs", "w1"), self.result("w1", "Wrote it"),
                self.call("read_file", "tests/mine.rs", "r1"), self.result("r1", "fn t() {}"),
                self.call("read_file", "Cargo.toml", "r2"), self.result("r2", "[package]")]
        self.assertEqual([p for p, _ in files_read(msgs)], ["Cargo.toml"])

    def test_an_edit_counts_as_writing_it(self):
        from cria.research import files_read
        msgs = [self.call("edit_file", "src/main.rs", "e1"), self.result("e1", "Edited"),
                self.call("read_file", "src/main.rs", "r1"), self.result("r1", "fn main() {}")]
        self.assertEqual(files_read(msgs), [])

    def test_a_refusal_is_still_not_a_read(self):
        """The existing rule, unchanged: an attempted read is not a read."""
        from cria.research import files_read
        from cria import denial
        msgs = [self.call("read_file", "big.json", "r1"),
                self.result("r1", denial.mark("too large to return"))]
        self.assertEqual(files_read(msgs), [])
