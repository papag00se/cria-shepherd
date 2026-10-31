"""Portable regression for the old plan-on delivery ceiling.

These controlled frames retain the literal historical stop instruction; they are not
reconstructions of request captures that no longer exist.
"""
import re
import unittest

from cria import loop
from tests.completion_fixtures import feed_body

_STEP = re.compile(r"Do ONLY this step \((\d+) of (\d+)\), then stop:\n\n(.+)", re.S)


class FeedDeliveryBoundaryReplayTests(unittest.TestCase):
    def test_read_dependency_and_implementation_cursors_do_not_cap_delivery(self):
        for step in ("Read data/feed_messy.csv in full.",
                     "Add the third-party CSV library to pom.xml.",
                     "Fix the threading bug in Importer.java."):
            with self.subTest(step=step):
                body = feed_body(3, 6, step=step, legacy=True)
                # The harness can add testing obligations beyond the task's prompt.txt.
                body["messages"][1]["content"] += "\nRun the requested regression tests."
                match = _STEP.search(body["messages"][0]["content"])
                self.assertIsNotNone(match)
                idx, total, active_step = match.groups()
                framed = loop._frame_for_item(body["messages"], active_step, "", int(idx), int(total),
                                              tools=body["tools"])
                active = framed[0]["content"]
                self.assertEqual(framed[1], body["messages"][1])
                history = "\n".join(str(message.get("content") or "") for message in framed[1:])
                self.assertIn("REVIEW.md", history)
                self.assertIn("tests", history)
                self.assertIn("Prioritize this step", active)
                self.assertIn("required tests, documentation, and verification", active)
                self.assertNotIn("Do ONLY this step", active)
                self.assertNotIn("then stop", active)


if __name__ == "__main__":
    unittest.main()
