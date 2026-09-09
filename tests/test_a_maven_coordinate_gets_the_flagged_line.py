"""Maven's bracket coordinate must reach the existing flagged-line grounder.

Captured in feed-pipeline-java x ornith15, call 0161: the completion gate reported
``Importer.java:[154,43]`` but did not quote line 154. The coder spent its next two
turns running an unrelated baseline command and reading the source range before it
could act. ``probeparse.split_diag`` already understands this coordinate shape; the
gate annotation had drifted onto its own narrower parser.
"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from cria import probediscovery, probegate


class MavenFlaggedLineGroundingTests(unittest.TestCase):
    def test_a_bracket_coordinate_quotes_the_current_line(self):
        with tempfile.TemporaryDirectory() as workspace:
            path = os.path.join(workspace, "src", "main", "java", "pipeline", "Importer.java")
            os.makedirs(os.path.dirname(path))
            lines = ["// filler"] * 153 + ["while ((cols = reader.readNext()) != null) {"]
            with open(path, "w") as fh:
                fh.write("\n".join(lines) + "\n")

            finding = (
                "[ERROR] " + path
                + ":[154,43] unreported exception "
                "com.opencsv.exceptions.CsvValidationException; must be caught or declared"
            )
            raw = (
                f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
                f"{finding}\nEXIT:1\n"
            )
            plan = probegate.GatePlan(
                workspace=workspace,
                candidates=[SimpleNamespace(kind=probediscovery.ProbeKind.BuildCheck)],
            )
            out = probegate.clean_gate_output(raw, plan)

        self.assertIn(finding, out)  # the checker's message stays byte-identical
        self.assertIn(
            "  the flagged line on disk — line 154: "
            "`while ((cols = reader.readNext()) != null) {`",
            out,
        )

    def test_a_test_failure_still_does_not_point_at_its_raise_site(self):
        with tempfile.TemporaryDirectory() as workspace:
            path = os.path.join(workspace, "Importer.java")
            with open(path, "w") as fh:
                fh.write("value.getName();\n")
            finding = f"{path}:1: java.lang.NullPointerException"
            raw = (
                f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
                f"{finding}\nEXIT:1\n"
            )
            plan = probegate.GatePlan(
                workspace=workspace,
                candidates=[SimpleNamespace(kind=probediscovery.ProbeKind.Test)],
            )
            out = probegate.clean_gate_output(raw, plan)

        self.assertIn(finding, out)
        self.assertNotIn("the flagged line on disk", out)
        self.assertNotIn("value.getName()", out)


if __name__ == "__main__":
    unittest.main()
