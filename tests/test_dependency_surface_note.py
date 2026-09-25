"""writeproxy._note_dependency_surface — Candidate C40's delivery half, redesigned 2026-09-25 on
supervisor follow-up (manifest/lockfile + local cache, replacing the textual ledger-success trigger
measured to cover ~0 of the real p27 row: see
~/.cria/walk-findings/2026-09-24/c40-replay/coverage_ledger_events.txt).

Fails-before/passes-after plan: a workspace whose go.mod declares the real coordinate but whose local
module cache does not (yet) hold it is the exact fails-before precondition; once the cache holds it,
the SAME manifest yields the real note. Hermetic: the module cache and the workspace are both a
throwaway temp dir; wsview reads the workspace body through the autouse DirectView
(tests/conftest.py), exactly like every other wsview-backed test in this repo.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import writeproxy


def tool(content, call_id="c1"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


class _WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._home_tmp = tempfile.TemporaryDirectory()
        self._ws_tmp = tempfile.TemporaryDirectory()
        self.home = self._home_tmp.name
        self.ws = self._ws_tmp.name
        self._real_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: (self.home if p == "~" else
                                        os.path.join(self.home, p[2:]) if p.startswith("~/") else
                                        self._real_expanduser(p))
        self.addCleanup(self._home_tmp.cleanup)
        self.addCleanup(self._ws_tmp.cleanup)
        self.addCleanup(setattr, os.path, "expanduser", self._real_expanduser)

    def _write_go_mod(self, module="github.com/shopspring/decimal", version="v1.4.0"):
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write(f"module example.com/cart\n\ngo 1.21\n\nrequire {module} {version}\n")

    def _write_module_cache(self, module="github.com/shopspring/decimal", version="v1.4.0", body=None):
        d = os.path.join(self.home, "go", "pkg", "mod", module + "@" + version)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "decimal.go"), "w") as fh:
            fh.write(body or (
                "package decimal\n\n"
                "func NewFromString(value string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n\n"
                "func (d Decimal) Round(places int32) Decimal {\n\treturn d\n}\n\n"
                "func (d Decimal) RoundCeil(places int32) Decimal {\n\treturn d\n}\n"))


class FailsBeforeTests(_WorkspaceCase):
    """The precondition this candidate closes: today, nothing follows a manifest-declared dependency
    with the real exported surface, even when the manifest is on disk."""

    def test_manifest_present_but_no_local_cache_yields_no_note(self):
        self._write_go_mod()
        # No module cache written — cache-presence check fails, so C40 must abstain.
        out = writeproxy.represent_inbound([tool("some build output")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "some build output")
        self.assertNotIn("THE PACKAGE MANAGER JUST RESOLVED", out[0]["content"])

    def test_no_manifest_at_all_yields_no_note_even_with_a_populated_cache(self):
        self._write_module_cache()
        out = writeproxy.represent_inbound([tool("some build output")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "some build output")


class PassesAfterTests(_WorkspaceCase):
    def test_manifest_plus_cache_triggers_the_real_surface_note(self):
        self._write_go_mod()
        self._write_module_cache()
        out = writeproxy.represent_inbound([tool("go build ./... succeeded")], workspace_root=self.ws)
        content = out[0]["content"]
        self.assertIn("go build ./... succeeded", content)   # the coder's own tool output is untouched
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED github.com/shopspring/decimal v1.4.0", content)
        self.assertIn("func NewFromString(value string) (Decimal, error) {", content)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", content)

    def test_no_paraphrase_every_added_line_is_a_real_source_line(self):
        body = ("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                "\treturn Decimal{}, nil\n}\n")
        self._write_go_mod()
        self._write_module_cache(body=body)
        out = writeproxy.represent_inbound([tool("build output")], workspace_root=self.ws)
        added = out[0]["content"][len("build output"):]
        for line in body.splitlines():
            stripped = line.rstrip()
            if stripped.startswith("func "):
                self.assertIn(stripped, added)
        self.assertNotIn("Quantize", added)
        self.assertNotIn("RoundingModeCeiling", added)

    def test_exact_declared_version_only(self):
        self._write_go_mod(version="v1.3.0")
        self._write_module_cache(version="v1.4.0")   # cache holds a DIFFERENT version than declared
        out = writeproxy.represent_inbound([tool("build output")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "build output")   # v1.3.0 not cached -> abstain

    def test_jvm_now_covered_via_pom_plus_m2_jar(self):
        pom = os.path.join(self.ws, "pom.xml")
        with open(pom, "w") as fh:
            fh.write("<project><dependencies><dependency>\n"
                     "<groupId>org.apache.commons</groupId>\n"
                     "<artifactId>commons-csv</artifactId>\n"
                     "<version>1.10.0</version>\n"
                     "</dependency></dependencies></project>")
        # No real .m2 jar written in this test (javap/.class fixture is exercised in
        # tests/test_depsurface.py::JvmTests) -- this asserts the ABSTAIN half of JVM coverage: a
        # declared pom.xml coordinate with no matching local jar injects nothing, same as every
        # other ecosystem's cache-miss path, proving JVM is no longer silently excluded by the
        # dispatch table itself (the first landing's `_PROBES` had no "jvm" key at all).
        out = writeproxy.represent_inbound([tool("mvn output")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "mvn output")


class AbstainTests(_WorkspaceCase):
    def test_no_workspace_root_never_fires(self):
        out = writeproxy.represent_inbound([tool("go build ./... succeeded")], workspace_root=None)
        self.assertEqual(out[0]["content"], "go build ./... succeeded")

    def test_cache_absent_never_blocks_or_alters_the_real_result(self):
        self._write_go_mod()
        out = writeproxy.represent_inbound([tool("go build ./... succeeded")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "go build ./... succeeded")

    def test_unsupported_ecosystem_manifest_never_fires(self):
        with open(os.path.join(self.ws, "package.json"), "w") as fh:
            fh.write('{"dependencies": {"left-pad": "1.0.0"}}')
        out = writeproxy.represent_inbound([tool("npm output")], workspace_root=self.ws)
        self.assertEqual(out[0]["content"], "npm output")


class IdempotencyTests(_WorkspaceCase):
    def test_a_second_request_replaying_the_same_annotated_history_does_not_double_append(self):
        self._write_go_mod()
        self._write_module_cache()
        first = writeproxy.represent_inbound([tool("build output")], workspace_root=self.ws)
        annotated = first[0]["content"]
        # The harness echoes cria's own annotated content back on the next request, verbatim.
        second = writeproxy.represent_inbound([tool(annotated)], workspace_root=self.ws)
        self.assertEqual(second[0]["content"], annotated)
        self.assertEqual(second[0]["content"].count("THE PACKAGE MANAGER JUST RESOLVED"), 1)

    def test_a_later_unrelated_tool_result_in_the_same_history_does_not_re_fire(self):
        self._write_go_mod()
        self._write_module_cache()
        first = writeproxy.represent_inbound([tool("build output", call_id="c1")],
                                             workspace_root=self.ws)
        annotated = first[0]["content"]
        combined = writeproxy.represent_inbound([
            tool(annotated, call_id="c1"),
            tool("go vet ./... clean", call_id="c2"),
        ], workspace_root=self.ws)
        # The note stays exactly where it was delivered; the LATER unrelated result is untouched.
        self.assertEqual(combined[1]["content"], "go vet ./... clean")
        self.assertEqual(combined[0]["content"].count("THE PACKAGE MANAGER JUST RESOLVED"), 1)


class OverflowTests(_WorkspaceCase):
    def test_a_surface_too_large_to_inline_spills_with_a_real_ecosystem_correct_read_hint(self):
        lines = "\n\n".join(
            f"func Member{i}(x int) int {{\n\treturn x\n}}" for i in range(400))
        self._write_go_mod()
        self._write_module_cache(body="package decimal\n\n" + lines + "\n")
        out = writeproxy.represent_inbound([tool("build output")], workspace_root=self.ws)
        content = out[0]["content"]
        self.assertIn("is larger than fits here", content)
        self.assertIn("members found", content)
        # Ecosystem-correct real instruction for reading the rest -- go's cache is real text.
        self.assertIn("read_file or grep", content)
        self.assertIn(os.path.join(self.home, "go", "pkg", "mod", "github.com", "shopspring",
                                   "decimal@v1.4.0"), content)


if __name__ == "__main__":
    unittest.main()
