"""Java was the one build-system ecosystem with nothing below the test phase.

Three holes, all found by the six-language battery and all of them completeness in tables that
already have the right shape:

  * `syntax_floor_candidates` was enumerated by LANGUAGES-WITH-A-PARSE-FLAG — python3 -m compileall,
    node --check, php -l, ruby -c — which silently excludes every format whose parser is a library.
    A build file is exactly that. cria's own write path corrupted a pom.xml during the campaign and
    nothing in the gate could read XML, so the damage surfaced much later as `mvn` failing, with no
    finding naming the file.
  * `build_jvm`'s pom branch had no compile probe. Gradle gets `gradle check`, cargo gets `cargo
    check`, go gets `go build ./...`, dotnet gets `dotnet build` — Maven had only `mvn test`
    (Expensive, tier 4). Java has no interpreter parse flag, so the compiler IS its syntax floor:
    every Java run in the battery reported "SYNTAX FLOOR: did not run".
  * `mvn checkstyle:check` ran on poms that never declare checkstyle, making Maven download the
    plugin and apply its default sun_checks ruleset — which cria then injected as "the repo's own
    checks report these error-class problems". 43 style violations (80-column limits, missing
    `final`) were presented to gemma4 as the project's own standard and it rewrote Importer.java
    four times to satisfy a rule the project does not have.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery as pd
from cria import proberun

BARE_POM = '<project><modelVersion>4.0.0</modelVersion><artifactId>x</artifactId></project>'
CHECKSTYLE_POM = ('<project><build><plugins><plugin>'
                  '<artifactId>maven-checkstyle-plugin</artifactId>'
                  '</plugin></plugins></build></project>')


def _maven_tree(pom=BARE_POM):
    ws = Path(tempfile.mkdtemp())
    (ws / "src" / "main" / "java" / "pipeline").mkdir(parents=True)
    (ws / "pom.xml").write_text(pom)
    (ws / "src" / "main" / "java" / "pipeline" / "Importer.java").write_text(
        "package pipeline;\npublic class Importer {}\n")
    return ws


def _cmds(ws):
    return [" ".join(c.command) for c in proberun.select_completion_probes(ws)]


class MavenFillsTheCompileSlotTests(unittest.TestCase):
    def test_a_maven_project_gets_a_compile_check(self):
        self.assertTrue(any(c.startswith("mvn -q compile") for c in _cmds(_maven_tree())),
                        "Java's only parse check is the compiler and none was offered")

    def test_it_is_cheaper_than_the_test_phase(self):
        probes = {c.kind.value: c for c in proberun.select_completion_probes(_maven_tree())}
        self.assertIn("build_check", probes)
        self.assertLess(probes["build_check"].cost.value, probes["test"].cost.value)

    def test_the_test_phase_survives(self):
        self.assertTrue(any(c == "mvn test" for c in _cmds(_maven_tree())))


class CheckstyleMustBeDeclaredTests(unittest.TestCase):
    def test_a_pom_that_never_mentions_checkstyle_gets_no_checkstyle_probe(self):
        self.assertFalse([c for c in _cmds(_maven_tree()) if "checkstyle" in c],
                         "cria conjured a check the project never asked for")

    def test_a_pom_that_declares_it_still_gets_it(self):
        self.assertTrue([c for c in _cmds(_maven_tree(CHECKSTYLE_POM)) if "checkstyle" in c])


class TheFloorReadsBuildXmlTests(unittest.TestCase):
    def test_a_corrupt_pom_is_caught_by_the_floor(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "pom.xml").write_text("<project><unclosed>")
        probe = next(c for c in pd.syntax_floor_candidates(ws) if "ElementTree" in " ".join(c.command))
        done = subprocess.run(probe.command, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("pom.xml", done.stdout)

    def test_a_valid_pom_passes_the_floor(self):
        ws = _maven_tree()
        probe = next(c for c in pd.syntax_floor_candidates(ws) if "ElementTree" in " ".join(c.command))
        self.assertEqual(subprocess.run(probe.command, capture_output=True).returncode, 0)

    def test_an_arbitrary_data_xml_is_not_dragged_in(self):
        """The floor covers build files a coder breaks, not every .xml in a tree."""
        ws = Path(tempfile.mkdtemp())
        (ws / "fixture.xml").write_text("<not-well-formed>")
        self.assertFalse([c for c in pd.syntax_floor_candidates(ws) if "ElementTree" in " ".join(c.command)])


if __name__ == "__main__":
    unittest.main()
