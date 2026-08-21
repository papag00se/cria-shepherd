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

THE RULE NEEDS NO PER-LANGUAGE KNOWLEDGE. A probe the coder could retype is one line — `cargo test`,
`go vet ./...`, `bundle exec rubocop`. A program cria wrote is several. Only the first is worth
showing.
"""

import unittest

from cria import probegate, proberun


def _wrapped(inner: str) -> str:
    """A probe command shaped exactly as `proberun.compose_probe_command` builds it."""
    return (f"cd /ws && __cria_out=$(timeout -k 5 240 {inner} </dev/null 2>&1); __cria_ec=$?; "
            f"__cria_n=$(printf '%s' \"$__cria_out\" | wc -c); "
            f"if [ \"$__cria_n\" -le 1850 ]; then printf '%s\\n' \"$__cria_out\"; fi; "
            f"printf '{proberun.PROBE_EXIT_SENTINEL}%d\\n' \"$__cria_ec\"")


class ARealCommandIsShownTests(unittest.TestCase):
    def test_the_commands_the_coder_could_retype_survive(self):
        for cmd in ("cargo test --no-fail-fast", "go vet ./...", "bundle exec rubocop",
                    "mvn -q compile", "python3 -m pytest -q"):
            with self.subTest(cmd=cmd):
                self.assertEqual(probegate._strip_gate_plumbing(_wrapped(cmd)), cmd)

    def test_several_probes_in_one_script_all_survive(self):
        script = "\n".join(_wrapped(c) for c in ("cargo check", "cargo test --no-fail-fast"))
        self.assertEqual(probegate._strip_gate_plumbing(script).splitlines(),
                         ["cargo check", "cargo test --no-fail-fast"])


class CriasOwnProgramIsNotTests(unittest.TestCase):
    TOML_CHECK = ("python3 -c 'import sys\n"
                  "try:\n"
                  "    import tomllib\n"
                  "except ModuleNotFoundError:\n"
                  "    try:\n"
                  "        import tomli as tomllib\n"
                  "    except ModuleNotFoundError:\n"
                  "        sys.exit(0)\n"
                  "' /ws/Cargo.toml")

    def test_the_toml_check_that_cost_the_run_is_gone(self):
        out = probegate._strip_gate_plumbing(_wrapped(self.TOML_CHECK))
        self.assertNotIn("tomli", out)
        self.assertNotIn("tomllib", out)
        self.assertEqual(out, "")

    def test_the_java_and_node_manifest_checks_too(self):
        for prog in ("python3 -c 'from xml.etree import ElementTree as ET\nET.parse(f)\n' pom.xml",
                     "python3 -c 'import json\nwith open(f) as fh:\n    json.load(fh)\n' package.json"):
            with self.subTest(prog=prog.split("\n")[0]):
                out = probegate._strip_gate_plumbing(_wrapped(prog))
                self.assertNotIn("import", out)
                self.assertEqual(out, "")

    def test_a_real_command_beside_an_inline_program_still_survives(self):
        """Dropping the program must not drop the probe next to it."""
        script = "\n".join([_wrapped(self.TOML_CHECK), _wrapped("cargo check")])
        self.assertEqual(probegate._strip_gate_plumbing(script), "cargo check")


if __name__ == "__main__":
    unittest.main()
