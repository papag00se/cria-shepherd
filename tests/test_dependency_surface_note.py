"""writeproxy._note_dependency_surface — Candidate C40's delivery half.

2026-09-25c (independent review round 2): the 2026-09-25b one-shot delivered-state fix was itself
wrong — it made a real fact visible for exactly ONE request, then silently absent for the rest of a
30+ minute session. This file now covers the DURABLE, RE-RENDERED ANCHOR design: the SAME text
re-attached to the SAME message on every later request while that message survives, re-anchored once
(same text) if a compaction folds the original anchor out of history, and TIMELESS wording ("the
version declared in <manifest>", never "JUST RESOLVED").

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

ANCHOR_TEXT = "THE VERSION OF"   # the timeless template's own opening words


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
        depsurface._ANCHOR.clear()
        depsurface._WITHHELD.clear()
        depsurface._ABSTAINED.clear()
        self.addCleanup(depsurface._ANCHOR.clear)
        self.addCleanup(depsurface._WITHHELD.clear)
        self.addCleanup(depsurface._ABSTAINED.clear)
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
        self.assertNotIn(ANCHOR_TEXT, out[0]["content"])

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
        self.assertIn("THE VERSION OF example.invalid/nonexistent v1.4.0 DECLARED IN go.mod", content)
        self.assertIn("func NewFromString(value string) (Decimal, error) {", content)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", content)

    def test_wording_is_timeless_never_says_just_resolved(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")])
        self.assertNotIn("JUST RESOLVED", out[0]["content"])
        self.assertNotIn("just resolved", out[0]["content"].lower())

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
        # No real .m2 jar in this fixture -- proves the ABSTAIN half.
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
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")], tools_present=False)
        self.assertEqual(out[0]["content"], "build output")


class MultiRequestReplayTests(_WorkspaceCase):
    """The exact shape independent review asked for: a genuine multi-request replay where requests 2
    and 3 are the harness's OWN unmodified history (never cria's rewrite -- the harness does not
    store it) plus a new tool result each turn. The note must be present on the ANCHOR message in all
    three requests, byte-identical, and present exactly once per request."""

    def test_the_note_persists_byte_identical_across_three_requests_on_the_same_anchor(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")

        # Request 1: the coder's first build result.
        req1 = [tool("go build ./... succeeded", call_id="c1")]
        out1 = self.represent(req1)
        anchor_text = out1[0]["content"]
        self.assertIn(ANCHOR_TEXT, anchor_text)
        self.assertEqual(anchor_text.count(ANCHOR_TEXT), 1)

        # Request 2: the HARNESS's own unmodified history -- the RAW turn-1 message (never touched by
        # cria's rewrite, since the harness keeps its own transcript), plus a new, unrelated result.
        req2 = [tool("go build ./... succeeded", call_id="c1"),
               tool("go vet ./... clean", call_id="c2")]
        out2 = self.represent(req2)
        self.assertEqual(out2[0]["content"], anchor_text)          # byte-identical re-render
        self.assertEqual(out2[0]["content"].count(ANCHOR_TEXT), 1)  # exactly once
        self.assertEqual(out2[1]["content"], "go vet ./... clean")  # not duplicated elsewhere

        # Request 3: again the harness's own unmodified history (both raw turns) plus one more result.
        req3 = [tool("go build ./... succeeded", call_id="c1"),
               tool("go vet ./... clean", call_id="c2"),
               tool("go test ./... ok", call_id="c3")]
        out3 = self.represent(req3)
        self.assertEqual(out3[0]["content"], anchor_text)           # still byte-identical, same anchor
        self.assertEqual(out3[0]["content"].count(ANCHOR_TEXT), 1)
        self.assertEqual(out3[1]["content"], "go vet ./... clean")
        self.assertEqual(out3[2]["content"], "go test ./... ok")
        full_text = "".join(m["content"] for m in out3)
        self.assertEqual(full_text.count(ANCHOR_TEXT), 1)   # present exactly once across the request

    def test_gather_runs_exactly_once_across_the_three_requests(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        calls = {"n": 0}
        real_gather = depsurface.gather

        def counting_gather(*a, **kw):
            calls["n"] += 1
            return real_gather(*a, **kw)

        depsurface.gather = counting_gather
        try:
            self.represent([tool("t1", call_id="c1")])
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2"),
                            tool("t3", call_id="c3")])
        finally:
            depsurface.gather = real_gather
        self.assertEqual(calls["n"], 1)


class AnchorLossTests(_WorkspaceCase):
    """Anchor loss (a harness compaction folds the anchor message out of history): re-anchor once on
    the newest qualifying tool result, replaying the SAME cached text."""

    def test_anchor_loss_re_anchors_on_the_newest_tool_result_with_identical_text(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out1 = self.represent([tool("build output", call_id="c1")])
        original_text = out1[0]["content"]
        added = original_text[len("build output"):]

        # A compaction happened: call_id "c1" is gone from history entirely, replaced by a rollup
        # message plus a fresh tool result the coder produced after resuming.
        out2 = self.represent([
            {"role": "user", "content": "⟦ctx:rollup⟧ (retrospective summary, no tool_call_id)"},
            tool("go build ./... succeeded", call_id="c9"),
        ])
        self.assertIn(added.strip(), out2[1]["content"])   # SAME cached text, re-anchored
        self.assertEqual(out2[1]["content"].count(ANCHOR_TEXT), 1)

    def test_re_anchor_text_stays_byte_identical_to_the_original(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out1 = self.represent([tool("build output", call_id="c1")])
        original_added = out1[0]["content"][len("build output"):]
        out2 = self.represent([tool("go test ./... ok", call_id="c9")])   # c1 vanished
        new_added = out2[0]["content"][len("go test ./... ok"):]
        self.assertEqual(original_added, new_added)   # not re-gathered, not re-worded -- identical

    def test_re_anchor_does_not_re_run_gather(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        self.represent([tool("build output", call_id="c1")])
        real_gather = depsurface.gather
        depsurface.gather = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("gather() must not run on anchor-loss re-anchor"))
        try:
            out2 = self.represent([tool("go test ./... ok", call_id="c9")])
        finally:
            depsurface.gather = real_gather
        self.assertIn(ANCHOR_TEXT, out2[0]["content"])


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
        rendered = out[0]["content"].count(ANCHOR_TEXT)
        self.assertGreater(rendered, 0)
        self.assertLessEqual(rendered, writeproxy._MAX_NOTES_PER_REQUEST)

    def test_delivered_state_is_checked_before_gather_no_repeated_disk_cost(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        first = self.represent([tool("build output", call_id="c1")])
        self.assertIn(ANCHOR_TEXT, first[0]["content"])

        real_gather = depsurface.gather

        def _boom(*a, **kw):
            raise AssertionError("gather() must not run for an already-anchored coordinate")

        depsurface.gather = _boom
        try:
            second = self.represent([tool("build output", call_id="c1"),
                                     tool("go vet ./... clean", call_id="c2")])
        finally:
            depsurface.gather = real_gather
        self.assertEqual(second[1]["content"], "go vet ./... clean")


class TotalByteBudgetTests(_WorkspaceCase):
    """Independent review round 3, R3, THEN round 4's regression fixes on top of it:
    individually-bounded notes are not collectively bounded once several real direct dependencies are
    anchored -- `_MAX_TOTAL_NOTE_BYTES_PER_REQUEST` caps the SUM. Round 4 fixed three problems in the
    round-3 shape: (1) budget was spent in manifest order, so a brand-new dependency could displace an
    already-anchored note; (2) a withheld coordinate was re-`gather()`ed every request; (3) the
    withheld wording promised a future delivery ('they will appear on a later turn') this design can
    never actually make happen."""

    def _many_dependencies(self, n=6, module_prefix="example.invalid/pkg", members=60):
        lines = ["module example.com/many\n\ngo 1.21\n"]
        for i in range(n):
            module = f"{module_prefix}{i}"
            lines.append(f"require {module} v1.0.0\n")
            d = os.path.join(self.home, "go", "pkg", "mod", f"{module}@v1.0.0")
            os.makedirs(d, exist_ok=True)
            # A body large enough that its OWN inline-budget-fitting note is a meaningful fraction of
            # the total budget -- makes the total-byte cap the binding constraint, not the count cap.
            body_lines = "\n\n".join(f"func Member{i}_{j}(x int) int {{\n\treturn x\n}}"
                                     for j in range(members))
            with open(os.path.join(d, "x.go"), "w") as fh:
                fh.write(f"package pkg{i}\n\n{body_lines}\n")
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("".join(lines))

    def test_many_anchored_coordinates_are_capped_by_total_bytes_and_labelled(self):
        self._many_dependencies(n=6)
        real_cap = writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST
        real_max_notes = writeproxy._MAX_NOTES_PER_REQUEST
        writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 4000   # force the budget to bind in this test
        writeproxy._MAX_NOTES_PER_REQUEST = 10                # let every dependency be attempted at once
        try:
            out = self.represent([tool("build output")])
        finally:
            writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = real_cap
            writeproxy._MAX_NOTES_PER_REQUEST = real_max_notes
        content = out[0]["content"]
        total_note_bytes = len(content.encode()) - len("build output".encode())
        self.assertLessEqual(total_note_bytes, 4000 + 1500)   # budget plus one pointer-list sentence
        # R3-3: the reworded line must not promise a delivery this design cannot make, and must name
        # a REAL way to read the withheld facts (the read_hint text, e.g. read_file/grep <path>).
        self.assertIn("will NOT appear automatically", content)
        self.assertNotIn("will appear on a later turn", content)
        self.assertIn("read_file or grep", content)

    def test_no_withheld_label_when_nothing_was_withheld(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")])
        self.assertNotIn("will NOT appear automatically", out[0]["content"])

    def test_anchored_notes_are_rendered_before_any_new_gather_R3_fix_1(self):
        """A coordinate anchored on an earlier request must not be displaced by a coordinate that is
        merely EARLIER in manifest order but has never been anchored yet."""
        self._write_go_mod(module="example.invalid/nonexistent")   # will be listed FIRST in go.mod
        self._write_module_cache(module="example.invalid/nonexistent")
        first = self.represent([tool("t1", call_id="c1")])
        self.assertIn(ANCHOR_TEXT, first[0]["content"])
        anchored_text = first[0]["content"]

        # Now a SECOND, brand-new dependency is declared -- inserted FIRST in go.mod, ahead of the
        # already-anchored one, with a large enough real surface that a manifest-order (not
        # anchored-first) pass would have let it consume the budget the anchored note needs.
        big_body = "\n\n".join(f"func Big{i}(x int) int {{\n\treturn x\n}}" for i in range(80))
        d = os.path.join(self.home, "go", "pkg", "mod", "example.invalid/newcomer@v1.0.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "x.go"), "w") as fh:
            fh.write(f"package newcomer\n\n{big_body}\n")
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("module example.com/cart\n\ngo 1.21\n\n"
                     "require example.invalid/newcomer v1.0.0\n"          # listed FIRST
                     "require example.invalid/nonexistent v1.4.0\n")      # already-anchored, listed SECOND

        real_cap = writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST
        writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = len(anchored_text.encode()) + 200
        try:
            second = self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
        finally:
            writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = real_cap
        # The already-anchored coordinate's text is untouched -- priority honoured.
        self.assertEqual(second[0]["content"], anchored_text)
        combined = "".join(m["content"] for m in second)
        self.assertIn("THE VERSION OF example.invalid/nonexistent", combined)
        # The newcomer, listed FIRST in the manifest, does not get to displace it -- it is either
        # withheld (budget exhausted by the priority pass) or simply not yet attempted this request.
        self.assertNotIn("THE VERSION OF example.invalid/newcomer", combined)

    def test_a_withheld_coordinate_is_never_gathered_again_R3_fix_2(self):
        self._many_dependencies(n=6)
        real_cap = writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST
        real_max_notes = writeproxy._MAX_NOTES_PER_REQUEST
        writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 4000
        writeproxy._MAX_NOTES_PER_REQUEST = 10
        calls = {"n": 0}
        real_gather = depsurface.gather

        def counting_gather(*a, **kw):
            calls["n"] += 1
            return real_gather(*a, **kw)

        depsurface.gather = counting_gather
        try:
            self.represent([tool("t1", call_id="c1")])
            after_first = calls["n"]
            self.assertGreater(after_first, 0)
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2"),
                            tool("t3", call_id="c3")])
        finally:
            depsurface.gather = real_gather
            writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = real_cap
            writeproxy._MAX_NOTES_PER_REQUEST = real_max_notes
        # Every coordinate was already attempted (anchored or withheld) on the first request (the cap
        # override lets all 6 be tried at once) -- later requests must not call gather() again at all.
        self.assertEqual(calls["n"], after_first,
                         "a withheld coordinate must never be re-gathered on a later request")

    def test_five_or_more_notes_the_withheld_set_and_gather_count_stay_fixed_across_requests(self):
        """Independent review round 4, item (4): 5+ real, anchored-size dependencies; across several
        requests the WITHHELD SET and the total `gather()` COUNT must both stay fixed once every
        coordinate has been attempted once."""
        self._many_dependencies(n=5, module_prefix="example.invalid/five", members=70)
        real_cap = writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST
        real_max_notes = writeproxy._MAX_NOTES_PER_REQUEST
        writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 5000   # binds well before all 5 fit
        writeproxy._MAX_NOTES_PER_REQUEST = 10                # let all 5 be attempted on request 1
        calls = {"n": 0}
        real_gather = depsurface.gather

        def counting_gather(*a, **kw):
            calls["n"] += 1
            return real_gather(*a, **kw)

        depsurface.gather = counting_gather
        try:
            reqs = [[tool("t1", call_id="c1")]]
            for i in range(2, 6):
                reqs.append(reqs[-1] + [tool(f"t{i}", call_id=f"c{i}")])

            outs = [self.represent(reqs[0])]
            withheld_after_1 = set(depsurface._WITHHELD.get(self.sess, {}).keys())
            gather_count_after_1 = calls["n"]
            self.assertTrue(withheld_after_1, "the fixture must actually force some withholding")

            for req in reqs[1:]:
                outs.append(self.represent(req))
                withheld_now = set(depsurface._WITHHELD.get(self.sess, {}).keys())
                self.assertEqual(withheld_now, withheld_after_1,
                                 "the withheld SET must stay fixed once every coordinate is attempted")
                self.assertEqual(calls["n"], gather_count_after_1,
                                 "the total gather() COUNT must stay fixed -- no re-gathering")
        finally:
            depsurface.gather = real_gather
            writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = real_cap
            writeproxy._MAX_NOTES_PER_REQUEST = real_max_notes

    def test_a_version_bump_or_removal_of_a_withheld_coordinate_stops_naming_it(self):
        """Independent review round 5: `withheld_pointers` must filter against the CURRENT
        `declared_coordinates`, the same set the anchor phases filter against -- otherwise a version
        bump leaves BOTH the old and new version listed, and a removed dependency is still named every
        turn: false present-tense facts about the project's current state."""
        self._many_dependencies(n=5, module_prefix="example.invalid/five", members=70)
        real_cap = writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST
        real_max_notes = writeproxy._MAX_NOTES_PER_REQUEST
        writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 5000
        writeproxy._MAX_NOTES_PER_REQUEST = 10
        try:
            out1 = self.represent([tool("t1", call_id="c1")])
            combined1 = "".join(m["content"] for m in out1)
            self.assertIn("example.invalid/five1 v1.0.0", combined1)
            self.assertIn("example.invalid/five2 v1.0.0", combined1)
            withheld_before = set(depsurface._WITHHELD.get(self.sess, {}).keys())
            self.assertIn(("go", "example.invalid/five1", "v1.0.0"), withheld_before)
            self.assertIn(("go", "example.invalid/five2", "v1.0.0"), withheld_before)

            # Bump five1 to v1.1.0 (same oversized body, so it is withheld again under the NEW
            # coordinate) and drop five2 from go.mod entirely.
            body_lines = "\n\n".join(f"func Member1_{j}(x int) int {{\n\treturn x\n}}" for j in range(70))
            d = os.path.join(self.home, "go", "pkg", "mod", "example.invalid/five1@v1.1.0")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "x.go"), "w") as fh:
                fh.write(f"package pkg1\n\n{body_lines}\n")
            manifest_lines = ["module example.com/many\n\ngo 1.21\n",
                              "require example.invalid/five0 v1.0.0\n",
                              "require example.invalid/five1 v1.1.0\n",   # bumped
                              # five2 removed entirely
                              "require example.invalid/five3 v1.0.0\n",
                              "require example.invalid/five4 v1.0.0\n"]
            with open(os.path.join(self.ws, "go.mod"), "w") as fh:
                fh.write("".join(manifest_lines))

            out2 = self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
            combined2 = "".join(m["content"] for m in out2)
            # The superseded version must not still be named as a present fact.
            self.assertNotIn("example.invalid/five1 v1.0.0", combined2)
            # The removed dependency must not still be named either.
            self.assertNotIn("example.invalid/five2", combined2)
            # The bumped coordinate's NEW version is real, was gathered fresh, and (still oversized)
            # is correctly withheld under ITS OWN key -- named as the current fact.
            self.assertIn("example.invalid/five1 v1.1.0", combined2)
        finally:
            writeproxy._MAX_TOTAL_NOTE_BYTES_PER_REQUEST = real_cap
            writeproxy._MAX_NOTES_PER_REQUEST = real_max_notes


class AbstainMemoizationTests(_WorkspaceCase):
    """Cheap item (ii): a coordinate `gather()` could not resolve is not re-probed every request for
    the rest of the session -- but is not blocked FOREVER either, since the local cache becoming
    populated mid-session is exactly the moment this candidate exists to catch."""

    def test_a_cache_miss_is_not_re_probed_every_request(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        # No module cache written -- gather() abstains every time it is actually called.
        calls = {"n": 0}
        real_gather = depsurface.gather

        def counting_gather(*a, **kw):
            calls["n"] += 1
            return real_gather(*a, **kw)

        depsurface.gather = counting_gather
        try:
            self.represent([tool("t1", call_id="c1")])
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
            self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2"),
                            tool("t3", call_id="c3")])
        finally:
            depsurface.gather = real_gather
        self.assertEqual(calls["n"], 1, "a cache miss must not re-run gather() every request")

    def test_a_later_successful_gather_is_not_permanently_blocked(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        out1 = self.represent([tool("t1", call_id="c1")])
        self.assertNotIn(ANCHOR_TEXT, out1[0]["content"])   # cache absent -- abstained

        # The coordinate's local cache appears mid-session (the coder's own `go get` finally
        # resolved it) -- forcing the retry countdown to zero simulates enough elapsed requests for
        # the bounded retry window to reopen.
        self._write_module_cache(module="example.invalid/nonexistent")
        coordinate = ("go", "example.invalid/nonexistent", "v1.4.0")
        depsurface._ABSTAINED.get(self.sess, {})[coordinate] = 1
        out2 = self.represent([tool("t1", call_id="c1"), tool("t2", call_id="c2")])
        combined = "".join(m["content"] for m in out2)
        self.assertIn(ANCHOR_TEXT, combined)


class CompletenessTests(_WorkspaceCase):
    """B3: the inline template's totality claim ("a member you don't see here does not exist") may
    only be used when the surface is provably complete."""

    def test_fallback_scan_never_uses_the_complete_template(self):
        self._write_go_mod(module="example.invalid/nonexistent")
        self._write_module_cache(module="example.invalid/nonexistent")
        out = self.represent([tool("build output")])
        content = out[0]["content"]
        self.assertNotIn("does not exist in this exact declared version", content)
        self.assertIn("PARTIAL", content)

    def test_jvm_never_uses_the_complete_template(self):
        surface = depsurface.DependencySurface(
            "jvm", "org.apache.commons:commons-csv:1.10.0", "/fake.jar", ("A",),
            ("public final class A {", "  public A();", "}"), read_hint="javap ...", complete=False)
        note = writeproxy._render_dependency_surface(surface, "jvm")
        self.assertNotIn("does not exist in this exact declared version", note)
        self.assertIn("PARTIAL", note)
        self.assertIn("pom.xml", note)

    def test_a_complete_surface_that_fits_uses_the_complete_template(self):
        surface = depsurface.DependencySurface(
            "go", "example.com/x v1.0.0", "/fake", ("go doc -all example.com/x@v1.0.0",),
            ("func Foo() int",), read_hint="run go doc yourself", complete=True)
        note = writeproxy._render_dependency_surface(surface, "go")
        self.assertIn("COMPLETE", note)
        self.assertIn("does not exist in this exact declared version", note)
        self.assertIn("go.mod", note)

    def test_a_complete_surface_that_overflows_the_budget_still_uses_partial_wording(self):
        many_lines = tuple(f"func Member{i}() int" for i in range(2000))
        surface = depsurface.DependencySurface(
            "go", "example.com/big v1.0.0", "/fake", ("go doc -all example.com/big@v1.0.0",),
            many_lines, read_hint="run go doc yourself", complete=True)
        note = writeproxy._render_dependency_surface(surface, "go")
        self.assertNotIn("does not exist in this exact declared version", note)
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
