"""Exact Feed capture replay for the plan-on delivery boundary.

The archived Feed attempts all preserved the full request but delivered a system directive saying
``Do ONLY this step … then stop``.  That boundary made tests and REVIEW.md structurally unreachable
while a dependency, a read, or Importer.java remained the current step.
"""

import json
import re
import unittest
from pathlib import Path

from cria import loop


CAPTURES = (
    ("20260921T110810-01a0c527-6c46-74b3-bf8d-91cb6d18d707", "0057-coder-s3.json"),
    ("20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016", "0058-coder-s3.json"),
    ("20260921T135359-01a0c5bf-3d05-7fd0-a573-6c95720f4526", "0080-coder-s3.json"),
)
_STEP = re.compile(r"Do ONLY this step \((\d+) of (\d+)\), then stop:\n\n(.+)", re.S)


class FeedDeliveryBoundaryReplayTests(unittest.TestCase):
    def test_exact_feed_bodies_make_the_step_a_priority_not_a_delivery_ceiling(self):
        """The three comparable attempts all retain the full ask and must not hide behind a stop."""
        for capture, call in CAPTURES:
            with self.subTest(capture=capture, call=call):
                path = Path.home() / ".cria" / "calls" / capture / call
                self.assertTrue(path.is_file(), path)
                captured = json.loads(path.read_text())
                system = captured["body"]["messages"][0]["content"]
                match = _STEP.search(system)
                self.assertIsNotNone(match)
                idx, total, step = match.groups()
                framed = loop._frame_for_item(
                    captured["body"]["messages"], step, "", int(idx), int(total),
                    tools=captured["body"].get("tools"),
                )
                active = framed[0]["content"]
                history = "\n".join(str(message.get("content") or "") for message in framed[1:])
                self.assertIn("REVIEW.md", history)
                self.assertIn("tests", history)
                self.assertIn("Prioritize this step", active)
                self.assertIn("required tests, documentation, and verification", active)
                self.assertNotIn("Do ONLY this step", active)
                self.assertNotIn("then stop", active)


if __name__ == "__main__":
    unittest.main()
