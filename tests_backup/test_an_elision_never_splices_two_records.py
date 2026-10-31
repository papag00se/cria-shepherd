"""Probe composition preserves records because it no longer elides any output.

The old byte head/middle/tail splice could join fragments from different failures into a record the
checker never printed. The harness now spools the complete stream; this layer contributes only the
timeout, merged stderr, and exit sentinel.
"""

import pathlib
import subprocess
import tempfile
import unittest

from cria import probediscovery, proberun


def run_probe(body: str) -> str:
    with tempfile.TemporaryDirectory() as dirname:
        path = pathlib.Path(dirname, "emit.sh")
        path.write_text("cat <<'XEOFX'\n" + body + "XEOFX\n")
        candidate = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test,
            command=["sh", "emit.sh"],
            working_dir=pathlib.Path(dirname),
            confidence=1,
            expected_value=1,
            cost=probediscovery.ProbeCost.Cheap,
            mutates_code=False,
            may_hang=False,
            may_need_services=False,
            reason="test",
        )
        return subprocess.run(
            ["bash", "-c", proberun.compose_probe_command(candidate, 60)],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout


class EveryRecordSurvivesWholeTests(unittest.TestCase):
    def test_front_middle_and_tail_all_arrive(self):
        body = "FIRST_FAILURE\n" + "".join(f"row-{i:04d} {'x' * 80}\n" for i in range(400))
        body += "MIDDLE_FAILURE\n" + "".join(f"tail-{i:04d} {'y' * 80}\n" for i in range(400))
        body += "LAST_FAILURE\n"
        out = run_probe(body)
        self.assertIn("FIRST_FAILURE", out)
        self.assertIn("MIDDLE_FAILURE", out)
        self.assertIn("LAST_FAILURE", out)
        self.assertNotIn("elided", out)

    def test_every_emitted_line_is_preserved(self):
        lines = [f'row{i:04d} "region"=>"Americas", "pad"=>"{"x" * 60}"' for i in range(800)]
        out = run_probe("\n".join(lines) + "\n")
        for line in lines:
            self.assertIn(line, out)


if __name__ == "__main__":
    unittest.main()
