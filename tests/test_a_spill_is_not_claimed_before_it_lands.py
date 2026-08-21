"""cria told a model a file was on disk for twenty-six turns after failing to write it.

`handles-cli-node x nemotron-elastic` 1787273429, scored 1/4 and ended early. The model fetched
`https://api.handle.me/handles` (111,330 chars). cria composed a spill command of ~122 KB, the
harness REFUSED the exec, and nothing was written. cria had already recorded the spill as done —
`note_fetch_spill` is called one line before the command is returned, at compose time — so from then
on every prompt carried:

    - https://api.handle.me/handles → HTTP 200 … Its full text is on disk at
      ./tmp/reference/api.handle.me_handles.txt — grep it or read a line range

and the re-fetch gate went further: "It was too large to inline, so it was saved IN FULL to … and
**that file is still there**." In the same prompt, twice, cria's read guard answered "is not there —
nothing was read". Two owners of one question, opposite answers, for twenty-six turns. The model
re-fetched the same document seven times.

Each refusal echoed the whole command back as the tool result, so ~10 KB of raw base64 landed in the
context per attempt. By the final compaction that base64 was 68% of a 92,261-character prompt; the
floor had nothing legal to drop, and the model server answered HTTP 400.

Two faults, one incident:

* **The record is not evidence.** It says cria INTENDED to write the file. Only the filesystem can
  say the file is there, and it must say yes — failing to say no is not enough (#5b).
* **The budget was derived from the kernel cap, not from the harness.** `MAX_ARG_STRLEN` is 128 KiB,
  but the harness wraps the command in `/bin/bash -lc "…"`, so its real limit is lower. Seven spill
  execs were refused across the captured rollouts, the smallest at 123,848 bytes.
"""

import json
import unittest

from cria import webfetch, writeproxy, wsview


class TheBudgetIsSizedToTheHarnessNotTheKernelTests(unittest.TestCase):
    def test_a_max_size_spill_composes_far_below_every_observed_refusal(self):
        cmd = writeproxy._spill_command("./tmp/reference/doc.txt",
                                        "x" * writeproxy.SPILL_CONTENT_MAX, "saved it")
        self.assertLessEqual(len(cmd), writeproxy.COMMAND_ARG_BUDGET)
        self.assertLess(len(cmd), 123_848, "smallest refusal observed in the captured rollouts")

    def test_the_encoded_bytes_are_what_is_budgeted(self):
        """base64 is 4-for-3 and `_b64_wrapped` adds a newline every 76 chars; budgeting the RAW
        document is how a command that looked like 89 KB reached 122 KB on the wire."""
        doc = "x" * writeproxy.SPILL_CONTENT_MAX
        self.assertGreater(len(writeproxy._b64_wrapped(doc)), len(doc))
        self.assertLessEqual(len(writeproxy._spill_command("./t.txt", doc, "m")),
                             writeproxy.COMMAND_ARG_BUDGET)

    def test_an_oversized_document_is_cut_and_says_so(self):
        big = "y" * (writeproxy.SPILL_CONTENT_MAX * 3)
        cmd = writeproxy._spill_command("./tmp/reference/doc.txt", big, "saved it")
        self.assertLessEqual(len(cmd), writeproxy.COMMAND_ARG_BUDGET)
        self.assertIn("could not be delivered", cmd)


class TheFilesystemMustSayYesTests(unittest.TestCase):
    URL = "https://api.handle.me/handles"

    def setUp(self):
        webfetch.note_fetch_spill("s", self.URL, "/ws/tmp/reference/api.handle.me_handles.txt")
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/ws", "s")))

    def test_an_unanswered_workspace_does_not_sustain_the_claim(self):
        """The turn after the exec, nobody has looked. cria must not swear the file is there."""
        self.assertIsNone(wsview.current().isfile("/ws/tmp/reference/api.handle.me_handles.txt"))
        self.assertFalse(webfetch.already_spilled("s", self.URL, "/ws"))

    def test_a_listing_that_does_not_name_it_withdraws_the_claim(self):
        from wsfixture import survey
        wsview.apply_survey(wsview.current(), survey("D\ttmp\nD\ttmp/reference\n"
                                                     "F\t0\t9\ttmp/reference/other.txt"))
        self.assertFalse(webfetch.already_spilled("s", self.URL, "/ws"))

    def test_a_listing_that_names_it_keeps_the_claim(self):
        from wsfixture import survey
        wsview.apply_survey(wsview.current(), survey(
            "D\ttmp\nD\ttmp/reference\nF\t0\t400\ttmp/reference/api.handle.me_handles.txt"))
        self.assertTrue(webfetch.already_spilled("s", self.URL, "/ws"))

    def test_a_spill_in_another_workspace_is_never_claimed(self):
        self.assertFalse(webfetch.already_spilled("s", self.URL, "/other-workspace"))


if __name__ == "__main__":
    unittest.main()
