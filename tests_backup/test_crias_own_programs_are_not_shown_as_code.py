"""cria handed a Rust project a Python library name, and the run scored 0/4.

`rust-toml-cli x nemotron-elastic` 1787160046, walked call by call. The first appearance of the
string `tomli` anywhere in that session is not the model's — it is cria's own TOML manifest check,
composed as a `python3 -c` program and carried into the coder's context at call 0012 inside the gate
command:

    python3 -c 'import sys
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
    …'

`tomli` is a PYTHON package. The model was writing a RUST TOML reader. It read that as the library
it should use and put `tomli = "^0.9"` into Cargo.toml; every subsequent build died on `failed to
select a version for the requirement`, and two of cria's own steers then contradicted each other
about whether to delete it. The project never compiled and the run scored 0/4.

The earlier report of this run blamed the model for "reaching out of its ecosystem". It did not
reach anywhere — it was handed the wrong ecosystem and believed cria (#5b, and #17: the model must
never read cria's own plumbing as if it were the work).

The same leak feeds Java `from xml.etree import ElementTree as ET` from the pom check and Node
`json.load(fh)` from the package.json check.

THE RULE NEEDS NO PER-LANGUAGE KNOWLEDGE, AND IT IS NO LONGER A RULE ABOUT TEXT. `plan_gate` knows
which of its candidates is argv the coder could retype and which is a program cria composed, and it
says so in the plan (`GATE_SENTINEL`). These tests run the real composition on real project trees:
what the model may see is whatever survives that, in every language.
"""

import pathlib
import tempfile
import unittest

from cria import probegate


def _tree(**files) -> str:
    ws = tempfile.mkdtemp()
    for rel, body in files.items():
        p = pathlib.Path(ws, rel.replace("__", "/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return ws


def _shown(ws: str) -> str:
    """Exactly what the model reads back of the gate cria ran in `ws`."""
    return probegate._strip_gate_plumbing(probegate.plan_gate(ws).script)


RUST = dict(**{"Cargo.toml": "[package]\nname = \"toml-cli\"\nversion = \"0.1.0\"\n",
               "src__main.rs": "fn main() {}\n"})
JAVA = dict(**{"pom.xml": "<project><artifactId>x</artifactId></project>",
               "src__main__java__App.java": "class App {}\n"})
NODE = dict(**{"package.json": "{\"name\":\"x\",\"scripts\":{\"test\":\"jest\"}}",
               "index.js": "module.exports = {};\n"})


class CriasOwnProgramIsNotTests(unittest.TestCase):
    def test_the_toml_check_that_cost_the_run_is_gone(self):
        out = _shown(_tree(**RUST))
        self.assertNotIn("tomli", out)
        self.assertNotIn("tomllib", out)

    def test_the_java_and_node_manifest_checks_too(self):
        for lang, files in (("java", JAVA), ("node", NODE)):
            with self.subTest(lang=lang):
                out = _shown(_tree(**files))
                self.assertNotIn("import", out)
                self.assertNotIn("ElementTree", out)
                self.assertNotIn("json.load", out)

    def test_no_program_cria_composed_reaches_the_model_in_any_language(self):
        """The general form: a line the model sees is one command, never a program."""
        for lang, files in (("rust", RUST), ("java", JAVA), ("node", NODE)):
            with self.subTest(lang=lang):
                for line in _shown(_tree(**files)).splitlines():
                    self.assertNotIn("python3 -c", line)
                    self.assertNotIn("<<", line)


class ARealCommandIsShownTests(unittest.TestCase):
    """Dropping the program must not drop the probe beside it — the gate is still worth seeing."""

    def test_the_rust_probes_the_coder_could_retype_survive(self):
        shown = _shown(_tree(**RUST))
        self.assertTrue(shown.strip(), "a Rust gate that shows the coder nothing is not a gate")
        for line in shown.splitlines():
            self.assertTrue(line.startswith("cargo "), line)

    def test_every_line_shown_is_a_command_and_nothing_else(self):
        for lang, files in (("rust", RUST), ("java", JAVA), ("node", NODE)):
            for line in _shown(_tree(**files)).splitlines():
                with self.subTest(lang=lang, line=line):
                    self.assertNotIn("cria", line.lower())
                    self.assertNotIn("$", line)
                    self.assertNotIn(";", line)


if __name__ == "__main__":
    unittest.main()
