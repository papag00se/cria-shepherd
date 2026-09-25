"""writeproxy._note_dependency_surface — Candidate C40's delivery half.

Covers the 2026-09-25b independent-review fixes:
  B1 — real session-scoped delivered-state (requires `sess_key`; a genuine second REQUEST replaying
       the harness's OWN unmodified turn-1 history, not a self-serving re-feed of cria's own output).
  B2 — direct dependencies only + a bounded note count per request + delivered-state checked before
       any disk read.
  B3 — completeness wording only when the read is provably complete.
  B4 — path escape / option injection (covered directly in tests/test_depsurface.py; this file only
       checks the end-to-end behaviour stays refused through the full represent_inbound path).

Hermetic: the module cache and the workspace are both throwaway temp dirs; wsview reads the workspace
body through the autouse DirectView (tests/conftest.py).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import depsurface, writeproxy


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
        depsurface._DELIVERED.clear()
        self.addCleanup(depsurface._DELIVERED.clear)
        self.sess = "test-session-1"

    def represent(self, messages, workspace_root=None, sess_key=None, tools_present=True):
        return writeproxy.represent_inbound(
            messages, workspace_root=(self.ws if workspace_root is None else workspace_root),
            sess_key=(self.sess if sess_key is None else sess_key), tools_present=tools_present)

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
    def test_manifest_present_but_no_local_cache_yields_no_note(self):
        self._write_go_mod()
        out = self.represent([tool("some build output")])
        self.assertEqual(out[0]["content"], "some build output")
        self.assertNotIn("THE PACKAGE MANAGER JUST RESOLVED", out[0]["content"])

    def test_no_manifest_at_all_yields_no_note_even_with_a_populated_cache(self):
        self._write_module_cache()
        out = self.represent([tool("some build output")])
        self.assertEqual(out[0]["content"], "some build output")

    def test_no_sess_key_never_fires(self):
        self._write_go_mod()
        self._write_module_cache()
        out = self.represent([tool("build output")], sess_key="")
        self.assertEqual(out[0]["content"], "build output")


class PassesAfterTests(_WorkspaceCase):
    def test_manifest_plus_cache_triggers_the_real_surface_note(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("go build ./... succeeded")])
        content = out[0]["content"]
        self.assertIn("go build ./... succeeded", content)
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED example.invalid/nonexistent v1.4.0", content)
        self.assertIn("func NewFromString(value string) (Decimal, error) {", content)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", content)

    def test_no_paraphrase_every_added_line_is_a_real_source_line(self):
        body = ("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                "\treturn Decimal{}, nil\n}\n")
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent", body=body)
        out = self.represent([tool("build output")])
        added = out[0]["content"][len("build output"):]
        for line in body.splitlines():
            stripped = line.rstrip()
            if stripped.startswith("func "):
                self.assertIn(stripped, added)
        self.assertNotIn("Quantize", added)
        self.assertNotIn("RoundingModeCeiling", added)

    def test_exact_declared_version_only(self):
        self._write_go_mod(module="example.invalid/nonexistent", version="v1.3.0")
        self._write_module_cache(module="example.invalid/nonexistent", version="v1.4.0")
        out = self.represent([tool("build output")])
        self.assertEqual(out[0]["content"], "build output")

    def test_jvm_now_covered_via_pom_plus_m2_jar(self):
        with open(os.path.join(self.ws, "pom.xml"), "w") as fh:
            fh.write("<project><dependencies><dependency>\n"
                     "<groupId>org.apache.commons</groupId>\n"
                     "<artifactId>commons-csv</artifactId>\n"
                     "<version>1.10.0</version>\n"
                     "</dependency></dependencies></project>")
        out = self.represent([tool("mvn output")])
        # No real .m2 jar in this fixture (the javap fixture lives in test_depsurface.py::JvmTests) --
        # proves the ABSTAIN half: a declared pom.xml coordinate with no matching local jar injects
        # nothing, same as any other ecosystem's cache-miss path.
        self.assertEqual(out[0]["content"], "mvn output")


class AbstainTests(_WorkspaceCase):
    def test_no_workspace_root_never_fires(self):
        out = self.represent([tool("go build ./... succeeded")], workspace_root=None)
        self.assertEqual(out[0]["content"], "go build ./... succeeded")

    def test_cache_absent_never_blocks_or_alters_the_real_result(self):
        self._write_go_mod()
        out = self.represent([tool("go build ./... succeeded")])
        self.assertEqual(out[0]["content"], "go build ./... succeeded")

    def test_unsupported_ecosystem_manifest_never_fires(self):
        with open(os.path.join(self.ws, "package.json"), "w") as fh:
            fh.write('{"dependencies": {"left-pad": "1.0.0"}}')
        out = self.represent([tool("npm output")])
        self.assertEqual(out[0]["content"], "npm output")

    def test_compaction_turn_no_tools_menu_is_skipped(self):
        # B1/cheap item: a compaction/summarize turn (empty tool menu) must never spend a real
        # disk/subprocess probe -- even with a fully satisfiable manifest+cache, tools_present=False
        # short-circuits before depsurface is ever consulted.
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")], tools_present=False)
        self.assertEqual(out[0]["content"], "build output")


class IdempotencyTests(_WorkspaceCase):
    def test_a_genuine_second_request_with_the_harnesss_own_unmodified_history_does_not_re_fire(self):
        """B1's actual bug: the harness replays ITS OWN unmodified history, never cria's rewrite.
        Turn 2 here is exactly that -- the SAME raw turn-1 message (never touched by
        represent_inbound's output) plus one new, unrelated tool result. A self-serving test that
        fed cria's own annotated text back in would prove nothing about production; this does not."""
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        # `represent_inbound` may alias/mutate a passthrough message dict in place (writeproxy.py's
        # own documented behaviour for a message it does not otherwise need to copy) -- a REAL harness
        # never sees that mutation, it keeps its OWN independently-held copy. Turn 1's message is
        # therefore rebuilt fresh for turn 2 rather than reusing the (possibly now-mutated) object, so
        # this test cannot accidentally pass by aliasing instead of by real session-state recall.
        first = self.represent([tool("build output", call_id="c1")])
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED", first[0]["content"])

        # Turn 2: the harness's OWN record of turn 1 (raw, unmodified -- it never saw cria's rewrite)
        # plus a new tool result for whatever the coder did next.
        second = self.represent([tool("build output", call_id="c1"),
                                 tool("go vet ./... clean", call_id="c2")])
        self.assertEqual(second[0]["content"], "build output")   # NOT re-annotated: already delivered
        self.assertEqual(second[1]["content"], "go vet ./... clean")   # note does NOT move here either
        combined_text = second[0]["content"] + second[1]["content"]
        self.assertEqual(combined_text.count("THE PACKAGE MANAGER JUST RESOLVED"), 0)

    def test_state_persists_even_though_history_never_shows_the_note(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        self.represent([tool("build output", call_id="c1")])
        self.assertTrue(depsurface.already_delivered(
            self.sess, ("go", "example.invalid/nonexistent", "v1.4.0")))

    def test_a_different_session_is_delivered_independently(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        self.represent([tool("build output")], sess_key="session-A")
        out = self.represent([tool("build output")], sess_key="session-B")
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED", out[0]["content"])


class BoundedNotesTests(_WorkspaceCase):
    def test_more_direct_dependencies_than_the_cap_only_render_the_cap(self):
        lines = ["module example.com/many\n\ngo 1.21\n"]
        for i in range(6):
            module = f"example.invalid/pkg{i}"
            lines.append(f"require {module} v1.0.0\n")
            d = os.path.join(self.home, "go", "pkg", "mod", f"{module}@v1.0.0")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "x.go"), "w") as fh:
                fh.write(f"package pkg{i}\nfunc Foo() int {{ return {i} }}\n")
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("".join(lines))
        out = self.represent([tool("build output")])
        rendered = out[0]["content"].count("THE PACKAGE MANAGER JUST RESOLVED")
        self.assertGreater(rendered, 0)
        self.assertLessEqual(rendered, writeproxy._MAX_NOTES_PER_REQUEST)

    def test_delivered_state_is_checked_before_gather_no_repeated_disk_cost(self):
        """B2: once delivered, a later request for the SAME coordinate must not re-run gather() at
        all -- proven by making gather() itself raise if called a second time for the delivered
        coordinate, then confirming a second (fresh, unmodified-history) request does not error and
        does not re-render."""
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        first = self.represent([tool("build output", call_id="c1")])
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED", first[0]["content"])

        real_gather = depsurface.gather

        def _boom(*a, **kw):
            raise AssertionError("gather() must not run for an already-delivered coordinate")

        depsurface.gather = _boom
        try:
            second = self.represent([tool("build output", call_id="c1"),
                                     tool("go vet ./... clean", call_id="c2")])
        finally:
            depsurface.gather = real_gather
        self.assertEqual(second[1]["content"], "go vet ./... clean")


class CompletenessTests(_WorkspaceCase):
    """B3: the inline template's totality claim ("a member you don't see here does not exist") may
    only be used when the surface is provably complete."""

    def test_fallback_scan_never_uses_the_complete_template(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")])
        content = out[0]["content"]
        self.assertNotIn("does not exist in this exact resolved version", content)
        self.assertIn("PARTIAL", content)

    def test_jvm_never_uses_the_complete_template(self):
        # No real .m2 jar in this fixture -- assembled directly against depsurface to check the
        # wording contract without needing a real jar/javap here (covered live in
        # tests/test_depsurface.py::JvmTests).
        surface = depsurface.DependencySurface(
            "jvm", "org.apache.commons:commons-csv:1.10.0", "/fake.jar", ("A",),
            ("public final class A {", "  public A();", "}"), read_hint="javap ...", complete=False)
        note = writeproxy._render_dependency_surface(surface)
        self.assertNotIn("does not exist in this exact resolved version", note)
        self.assertIn("PARTIAL", note)

    def test_a_complete_surface_that_fits_uses_the_complete_template(self):
        surface = depsurface.DependencySurface(
            "go", "example.com/x v1.0.0", "/fake", ("go doc -all example.com/x@v1.0.0",),
            ("func Foo() int",), read_hint="run go doc yourself", complete=True)
        note = writeproxy._render_dependency_surface(surface)
        self.assertIn("COMPLETE", note)
        self.assertIn("does not exist in this exact resolved version", note)

    def test_a_complete_surface_that_overflows_the_budget_still_uses_partial_wording(self):
        many_lines = tuple(f"func Member{i}() int" for i in range(2000))
        surface = depsurface.DependencySurface(
            "go", "example.com/big v1.0.0", "/fake", ("go doc -all example.com/big@v1.0.0",),
            many_lines, read_hint="run go doc yourself", complete=True)
        note = writeproxy._render_dependency_surface(surface)
        # Even a COMPLETE read that does not fit the inline budget must not claim "you've seen it
        # all" for the truncated INLINE text -- completeness is a property of what was GATHERED, not
        # of what fits on screen.
        self.assertNotIn("does not exist in this exact resolved version", note)
        self.assertIn("PARTIAL", note)


class OverflowTests(_WorkspaceCase):
    def test_a_surface_too_large_to_inline_spills_with_a_real_ecosystem_correct_read_hint(self):
        lines = "\n\n".join(
            f"func Member{i}(x int) int {{\n\treturn x\n}}" for i in range(400))
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent",
                                 body="package decimal\n\n" + lines + "\n")
        out = self.represent([tool("build output")])
        content = out[0]["content"]
        self.assertIn("read_file or grep", content)
        self.assertIn(os.path.join(self.home, "go", "pkg", "mod", "example.invalid",
                                   "nonexistent@v1.4.0"), content)


if __name__ == "__main__":
    unittest.main()
