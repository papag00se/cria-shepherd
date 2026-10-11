"""After a harness compaction the coder held the NAMES of the files it was working on, not their text.

phi4 / Java A7 (capture 20261011T051156, call 0022): the workspace's own check said
`Importer.java:25: illegal start of type`; the coder's prompt held the ⟦ctx:continuation⟧ reframe, the
checker output and a read ledger whose line said "src/main/java/pipeline/Importer.java (130 lines) — no read
result for it is in this conversation". It anchored an edit on a top of file it invented. Over A4/A6/A7,
45 of 100 edit_file/write_file calls named a file whose ledger line said exactly that. Every judge prompt of
the same run carried the same file's FULL text from the same workspace view.

The ⟦ctx:facts⟧ anchor now carries the current text of the files the coder read or wrote, when and only when
their text is not in the outgoing messages, from the view's trusted body — and says nothing it cannot back.
"""
import json
import unittest
from pathlib import Path

from cria import loop, wsview, writeproxy
from tests.test_a_judges_doubt_is_not_an_order import _session
from tests.wsfixture import survey

FX = json.loads((Path(__file__).parent / "fixtures" / "phi4_restore" / "a7_0022.json").read_text())
ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791720712-hs4fdm5h"
JAVA = "src/main/java/pipeline/Importer.java"
IMPORTER, POM = FX["importer"], FX["pom"]
# The real post-compaction coder body, less the facts anchor the previous turn happened to build.
MSGS = [m for m in FX["messages"] if "⟦ctx:facts⟧" not in str(m.get("content"))]


def _view(sess="restore", bodies=((JAVA, IMPORTER), ("pom.xml", POM)), extra_tree=""):
    sizes = dict((rel, len(text.encode())) for rel, text in bodies)
    tree = ("D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\n"
            + "".join(f"F\t1\t{n}\t{rel}\n" for rel, n in sizes.items()) + extra_tree)
    v = wsview.View(ROOT, sess)
    assert wsview.apply_survey(v, survey(tree.rstrip("\n"), root=ROOT))
    for rel, text in bodies:
        v.note_written(f"{ROOT}/{rel}", text)
    return v


class RestoredTextTests(unittest.TestCase):
    def bind(self, view):
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

    def sess(self):
        s = _session()
        s.workspace_root = ROOT
        s.read_files = {JAVA: (5157, "130 lines"), "pom.xml": (980, "29 lines")}
        return s

    def anchor(self, s, msgs=MSGS):
        a = loop._fetched_facts_anchor(s, msgs)
        return a["content"] if a else ""

    def test_the_real_a7_post_compaction_body_gets_the_exact_current_text(self):
        self.bind(_view())
        out = self.anchor(self.sess())
        self.assertIn("\n----- src/main/java/pipeline/Importer.java -----\n" + IMPORTER, out)
        self.assertIn("\n----- pom.xml -----\n" + POM, out)
        self.assertIn("CURRENT TEXT OF FILES YOU READ OR WROTE EARLIER", out)
        self.assertNotIn("cria", out.lower())

    def test_a_file_whose_whole_read_is_in_the_messages_is_not_repeated(self):
        read = [{"role": "assistant", "content": None, "tool_calls": [
                    {"id": "r1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": JAVA})}}]},
                {"role": "tool", "tool_call_id": "r1", "content": IMPORTER}]
        self.bind(_view())
        out = self.anchor(self.sess(), MSGS + read)
        self.assertNotIn("----- src/main/java/pipeline/Importer.java -----", out)
        self.assertIn("----- pom.xml -----", out)                      # the one that IS lost is still restored

    def test_a_file_the_session_never_touched_is_never_delivered(self):
        self.bind(_view(bodies=((JAVA, IMPORTER), ("pom.xml", POM), ("README.md", "# readme\n"))))
        self.assertNotIn("# readme", self.anchor(self.sess()))

    def test_a_command_that_could_have_changed_files_blocks_delivery_and_asks_afresh(self):
        v = _view()
        v.note_a_mutator_ran()
        self.bind(v)
        out = self.anchor(self.sess())
        self.assertNotIn("package pipeline;", out)
        self.assertNotIn("CURRENT TEXT OF FILES", out)
        self.assertIn("no read result for it is in this conversation", out)      # the ledger is unchanged
        bodies, _progs, _out = wsview.pending("restore")
        self.assertIn(JAVA, bodies)                                              # the harness is asked, not cria

    def test_a_body_the_view_does_not_hold_is_asked_for_not_claimed(self):
        self.bind(_view(bodies=()))
        out = self.anchor(self.sess())
        self.assertNotIn("CURRENT TEXT OF FILES", out)

    def test_an_unsurveyed_workspace_delivers_nothing_and_does_not_fail(self):
        self.bind(wsview.View(ROOT, "restore-unsurveyed"))
        self.assertNotIn("CURRENT TEXT OF FILES", self.anchor(self.sess()))

    def test_a_landed_edit_keeps_the_delivered_text_current(self):
        v = _view()
        old = "import java.util.Map;"
        self.assertIn(old, IMPORTER)
        self.assertTrue(v.note_edited(f"{ROOT}/{JAVA}", old, "import java.util.Map;\nimport java.util.Set;"))
        self.bind(v)
        out = self.anchor(self.sess())
        self.assertIn("import java.util.Map;\nimport java.util.Set;", out)

    def test_a_file_over_the_whole_read_limit_is_named_never_clipped(self):
        big = "x = 1\n" * (writeproxy.READ_INLINE_MAX // 6 + 50)
        self.bind(_view(bodies=((JAVA, big), ("pom.xml", POM))))
        out = self.anchor(self.sess())
        self.assertNotIn("x = 1\nx = 1", out)
        self.assertIn(f"NOT SHOWN HERE — {JAVA} ({len(big)} bytes)", out)
        self.assertIn("----- pom.xml -----", out)

    def test_the_block_is_bounded_by_one_reads_worth_and_names_what_it_omits(self):
        a = "a\n" * (writeproxy.READ_INLINE_MAX // 3)
        b = "b\n" * (writeproxy.READ_INLINE_MAX // 3)
        v = _view(bodies=(("A.txt", a), ("B.txt", b)))
        v.note_written(f"{ROOT}/B.txt", b)                       # newest write sorts first
        s = self.sess()
        s.read_files = {"A.txt": (len(a), "1 lines"), "B.txt": (len(b), "1 lines")}
        self.bind(v)
        out = self.anchor(s)
        shown = [n for n in ("A.txt", "B.txt") if f"----- {n} -----" in out]
        self.assertEqual(len(shown), 1)
        omitted = "B.txt" if shown == ["A.txt"] else "A.txt"
        self.assertIn(f"NOT SHOWN HERE — {omitted} (", out)

    def test_delivered_text_counts_as_a_whole_read_for_the_write_hold(self):
        v = _view()
        self.bind(v)
        s = self.sess()
        self.assertFalse(loop._coder_has_seen(v, JAVA, s, MSGS))
        self.anchor(s)
        self.assertTrue(loop._coder_has_seen(v, JAVA, s, MSGS))
        v.note_a_mutator_ran()                                   # the next turn restores nothing → no credit
        self.anchor(s)
        self.assertFalse(loop._coder_has_seen(v, JAVA, s, MSGS))

    def test_a_file_only_written_this_session_is_restored_too(self):
        s = _session()
        s.workspace_root = ROOT
        s.written_files = {JAVA: (len(IMPORTER), "130 lines")}
        self.bind(_view())
        out = self.anchor(s)
        self.assertIn("----- src/main/java/pipeline/Importer.java -----", out)
        self.assertNotIn("----- pom.xml -----", out)


if __name__ == "__main__":
    unittest.main()
