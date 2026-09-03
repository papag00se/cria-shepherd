"""cria asked a model to describe a workspace it had never been shown.

Both compaction paths — cria's own rolling fold and the harness's `<<<LOCAL_COMPACT>>>` handshake —
sent the transcript and nothing else. A transcript records what the coder TRIED; it does not record
what survived. So the writer filled the gap:

    qwen35/rust 0032 briefed "**Test file created** — `tests/nested_key_lookup.rs` exists".
    The next prompt's own ground-truth block listed six files, none of them under tests/.
    That path never existed at any point in the run.

cria then shipped the invention as ⟦ctx:rollup⟧ and the coder planned against it. 16 occurrences,
six languages, three models — a Rust cell struck two of four deliverables off its own to-do list.

WHY NOT ANOTHER CORRECTOR. `loop._briefing_disk_truth` already repairs the OPPOSITE direction: a
briefing that DENIES a file cria can see. It is untouched here, including its hard-won rule that it
APPENDS and never deletes (a regex cannot tell "resolver.py does not exist" from "resolver.py's
main() is not written", and deleting the second hides real remaining work). Adding a second
post-hoc corrector for invention would be a new assist over a fact cria was simply failing to pass
along. The listing was already being gathered one line away — it just went to the corrector instead
of the writer.
"""

import types
import unittest

from cria import groundtruth, prompts, selfcompact, server


def transcript():
    return [
        {"role": "user", "content": "build a nested key lookup for the toml cli"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "write_file",
                                      "arguments": '{"path": "tests/nested_key_lookup.rs"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "Process exited with code 1\nOutput:\nerror"},
    ]


class TheListingReachesTheWriterTests(unittest.TestCase):
    def test_the_self_compaction_ask_carries_it(self):
        out = selfcompact.compaction_request(transcript(), "FILES ON DISK RIGHT NOW:\n  src/main.rs (12 B)")
        self.assertIn("src/main.rs", out)

    def test_it_sits_before_the_ask(self):
        """cria's ask stays LAST — a model obeys the last instruction it reads."""
        out = selfcompact.compaction_request(transcript(), "FILES ON DISK RIGHT NOW:\n  src/main.rs (12 B)")
        self.assertLess(out.index("src/main.rs"), out.index("Write the briefing now"))

    def test_no_workspace_means_no_section(self):
        """Silence over an empty or guessed listing (#3, #5b)."""
        out = selfcompact.compaction_request(transcript(), "")
        self.assertNotIn("FILES ON DISK", out)
        self.assertTrue(out.endswith(prompts.load("compact_closing_ask")))

    def test_the_harness_path_carries_it_too(self, ):
        body = server._compaction_body({"messages": transcript()}, workspace_root=None)
        self.assertGreater(len(body["messages"]), 2)  # evidence is independently reducible
        self.assertNotIn("FILES ON DISK RIGHT NOW:", str(body["messages"]))

    def test_the_harness_path_renders_a_real_root(self):
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "main.rs").write_text("fn main() {}\n")
            body = server._compaction_body({"messages": transcript()}, workspace_root=ws)
        evidence = "\n".join(m["content"] for m in body["messages"][1:-1])
        self.assertIn("main.rs", evidence)
        self.assertNotIn("nested_key_lookup.rs (", evidence)


class TheListingIsDecisiveTests(unittest.TestCase):
    def test_the_briefing_flavor_keeps_the_completeness_clause(self):
        """"Not listed = does not exist" is the clause that makes the section settle anything."""
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "a.rs").write_text("x")
            out = groundtruth.workspace_inventory(ws, flavor="briefing")
        self.assertIn("a.rs", out)
        self.assertIn("a file not listed here does not exist", out.lower())

    def test_it_says_the_transcript_may_be_stale(self):
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "a.rs").write_text("x")
            out = groundtruth.workspace_inventory(ws, flavor="briefing")
        self.assertIn("stale", out)

    def test_an_empty_workspace_still_answers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            self.assertIn("none", groundtruth.workspace_inventory(ws, flavor="briefing"))

    def test_the_other_flavors_are_unchanged(self):
        import tempfile
        import pathlib
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "a.rs").write_text("x")
            self.assertIn("at judging time", groundtruth.workspace_inventory(ws))
            self.assertIn("before any work has started",
                          groundtruth.workspace_inventory(ws, flavor="planner"))
            self.assertIn("⟦ctx:files⟧", groundtruth.workspace_inventory(ws, flavor="coder"))


class ThePromptTellsItWhatTheListMeansTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("selfcompact_summary")

    def test_it_may_not_claim_a_file_that_is_not_listed(self):
        self.assertIn("Never state that a file was created unless it is on that list", self.body)

    def test_the_list_settles_existence_only(self):
        """It carries names and sizes. It cannot say whether a test passed."""
        self.assertIn("settles whether a file exists and nothing else", self.body)

    def test_the_evidence_rule_still_stands(self):
        self.assertIn("Only state that tests PASS or the build WORKS if the transcript shows the "
                      "check ACTUALLY RAN", self.body)


class TheDenialRepairIsUntouchedTests(unittest.TestCase):
    """The opposite direction keeps its own owner, and keeps appending rather than deleting."""

    def test_it_still_appends_when_the_briefing_denies_a_real_file(self):
        from cria import loop
        files = "WORKSPACE FILES in /w:\n  resolver.py (100 B)\nThis list is complete"
        claim = "resolver.py has not been written yet."
        out = loop._briefing_disk_truth(claim, files)
        self.assertIn(claim, out)                       # never deletes the briefing's own words
        self.assertGreater(len(out), len(claim))        # states cria's fact alongside it


if __name__ == "__main__":
    unittest.main()
