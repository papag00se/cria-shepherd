"""After a harness compaction the coder held the NAMES of the files it was working on, not their text.

phi4 / Java A7 (capture 20261011T051156, call 0022): the workspace's own check said
`Importer.java:25: illegal start of type`; the coder's prompt held the ⟦ctx:continuation⟧ reframe, the
checker output and a read ledger whose line said "src/main/java/pipeline/Importer.java (130 lines) — no read
result for it is in this conversation". It anchored an edit on a top of file it invented. Over A4/A6/A7,
45 of 100 edit_file/write_file calls named a file whose ledger line said exactly that. Every judge prompt of
the same run carried the same file's FULL text from the same workspace view.

The coder frame now carries the current text of the files the coder read or wrote, when and only when their
text is not in the outgoing messages, from the view's trusted body — as its OWN reducible message (⟦ctx:current⟧),
never inside the protected ⟦ctx:facts⟧ anchor (review c4a93ad1 B1: inside it the floor could not shed it and the
reply room fell from 1.7-2.3K tokens to 167-759 on real post-compaction bodies). What the claims about it mean is
settled on the body that is SENT.
"""
import json
import unittest
from pathlib import Path

from cria import bodykeys, contextfloor as cf, loop, modelview, prompts, upstream, wsview, writeproxy
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


def _anchor(s, msgs=MSGS):
    restore, offered = loop._restored_text_message(s, msgs)
    a = loop._fetched_facts_anchor(s, msgs, offered)
    return restore, (a["content"] if a else "")


class _Rlog:
    phase = "coder-s1"

    def emit(self, *a, **k):
        pass


class RestoredTextTests(unittest.TestCase):
    def bind(self, view):
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

    def sess(self):
        s = _session()
        s.workspace_root = ROOT
        s.read_files = {JAVA: (5157, "130 lines"), "pom.xml": (980, "29 lines")}
        return s

    def text(self, s, msgs=MSGS):
        restore, _ = _anchor(s, msgs)
        return restore["content"] if restore else ""

    def test_the_real_a7_post_compaction_body_gets_the_exact_current_text_in_its_own_message(self):
        self.bind(_view())
        restore, facts = _anchor(self.sess())
        out = restore["content"]
        self.assertTrue(out.startswith(modelview.RESTORED_MARKER))
        self.assertIn("\n----- src/main/java/pipeline/Importer.java -----\n" + IMPORTER, out)
        self.assertIn("\n----- pom.xml -----\n" + POM, out)
        self.assertEqual(set(restore[bodykeys.RESTORED_FILES]["offered"]), {JAVA, "pom.xml"})
        self.assertNotIn("package pipeline;", facts)                  # NOT inside the protected anchor (B1)
        self.assertNotIn("cria", out.lower())

    def test_the_ledger_line_points_at_the_text_instead_of_saying_it_is_absent(self):
        """B2: 'no read result for it is in this conversation' printed right above the exact text read as
        'you have no copy', against the rule that tells the coder to read what it has no copy of."""
        self.bind(_view())
        _restore, facts = _anchor(self.sess())
        self.assertIn(f"- {JAVA} (130 lines) — its current text is below", facts)
        self.assertNotIn("no read result for it is in this conversation", facts)

    def test_the_wording_pair_the_ledger_and_the_system_rule_agree(self):
        rule = next(l for l in prompts.load("coder_system").splitlines() if "already read a file" in l)
        self.assertIn("neither the result nor the file's current text is here any more", rule)
        self.assertIn("its current text is below", prompts.load_map("fetched_facts_sections")["read_restored"])

    def test_a_file_whose_whole_read_is_in_the_messages_is_not_repeated(self):
        read = [{"role": "assistant", "content": None, "tool_calls": [
                    {"id": "r1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": JAVA})}}]},
                {"role": "tool", "tool_call_id": "r1", "content": IMPORTER}]
        self.bind(_view())
        out = self.text(self.sess(), MSGS + read)
        self.assertNotIn("----- src/main/java/pipeline/Importer.java -----", out)
        self.assertIn("----- pom.xml -----", out)                      # the one that IS lost is still restored

    def test_a_file_the_session_never_touched_is_never_delivered(self):
        self.bind(_view(bodies=((JAVA, IMPORTER), ("pom.xml", POM), ("README.md", "# readme\n"))))
        self.assertNotIn("# readme", self.text(self.sess()))

    def test_a_command_that_could_have_changed_files_blocks_delivery_and_asks_afresh(self):
        v = _view()
        v.note_a_mutator_ran()
        self.bind(v)
        restore, facts = _anchor(self.sess())
        self.assertIsNone(restore)
        self.assertIn("no read result for it is in this conversation", facts)      # the ledger is unchanged
        bodies, _progs, _out = wsview.pending("restore")
        self.assertIn(JAVA, bodies)                                              # the harness is asked, not cria

    def test_a_body_the_view_does_not_hold_is_asked_for_not_claimed(self):
        self.bind(_view(bodies=()))
        self.assertEqual(self.text(self.sess()), "")

    def test_an_unsurveyed_workspace_delivers_nothing_and_does_not_fail(self):
        self.bind(wsview.View(ROOT, "restore-unsurveyed"))
        self.assertEqual(self.text(self.sess()), "")

    def test_a_landed_edit_keeps_the_delivered_text_current(self):
        v = _view()
        self.assertTrue(v.note_edited(f"{ROOT}/{JAVA}", "import java.util.Map;",
                                      "import java.util.Map;\nimport java.util.Set;"))
        self.bind(v)
        self.assertIn("import java.util.Map;\nimport java.util.Set;", self.text(self.sess()))

    def test_a_file_over_the_whole_read_limit_is_named_never_clipped(self):
        big = "x = 1\n" * (writeproxy.READ_INLINE_MAX // 6 + 50)
        self.bind(_view(bodies=((JAVA, big), ("pom.xml", POM))))
        out = self.text(self.sess())
        self.assertNotIn("x = 1\nx = 1", out)
        self.assertIn(f"NOT SHOWN HERE — {JAVA} ({len(big)} bytes)", out)
        self.assertIn("----- pom.xml -----", out)

    def test_the_block_is_bounded_by_one_reads_worth_and_names_what_it_omits(self):
        a = "a\n" * (writeproxy.READ_INLINE_MAX // 3)
        b = "b\n" * (writeproxy.READ_INLINE_MAX // 3)
        s = self.sess()
        s.read_files = {"A.txt": (len(a), "1 lines"), "B.txt": (len(b), "1 lines")}
        self.bind(_view(bodies=(("A.txt", a), ("B.txt", b))))
        out = self.text(s)
        shown = [n for n in ("A.txt", "B.txt") if f"----- {n} -----" in out]
        self.assertEqual(len(shown), 1)
        self.assertIn(f"NOT SHOWN HERE — {'B.txt' if shown == ['A.txt'] else 'A.txt'} (", out)

    def test_the_most_recently_edited_file_is_shown_first_and_survives_the_budget(self):
        """The view keeps a file's survey mtime across an edit, so recency comes from the session's own
        record of reads, writes and LANDED EDITS."""
        a = "a\n" * (writeproxy.READ_INLINE_MAX // 3)
        b = "b\n" * (writeproxy.READ_INLINE_MAX // 3)
        s = self.sess()
        s.read_files = {}
        for last, expect in (("A.txt", "A.txt"), ("B.txt", "B.txt")):
            s.file_touch, s.read_ledger_seen = {}, set()
            self.bind(_view(bodies=(("A.txt", a), ("B.txt", b))))
            order = [("A.txt", a), ("B.txt", b)]
            order.sort(key=lambda t: t[0] == last)                 # the file touched last goes last
            msgs = []
            for i, (name, body) in enumerate(order):
                msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"r{i}", "type": "function",
                           "function": {"name": "read_file", "arguments": json.dumps({"path": name})}}]},
                         {"role": "tool", "tool_call_id": f"r{i}", "content": body}]
            msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": "e1", "type": "function",
                       "function": {"name": "edit_file", "arguments": json.dumps(
                           {"path": last, "old_string": "x", "new_string": "y"})}}]},
                     {"role": "tool", "tool_call_id": "e1", "content": prompts.render("write_confirm", path=last)}]
            s.read_files = {n: (len(t), "1 lines") for n, t in order}
            loop._track_read_files(s, msgs)
            out = self.text(s, [])                                # the reads are not in the window
            self.assertIn(f"----- {expect} -----", out)
            self.assertIn(f"NOT SHOWN HERE — {'B.txt' if expect == 'A.txt' else 'A.txt'} (", out)

    def test_a_file_only_written_this_session_is_restored_too(self):
        s = _session()
        s.workspace_root = ROOT
        s.written_files = {JAVA: (len(IMPORTER), "130 lines")}
        self.bind(_view())
        out = self.text(s)
        self.assertIn("----- src/main/java/pipeline/Importer.java -----", out)
        self.assertNotIn("----- pom.xml -----", out)


# --- the floor and the wire -------------------------------------------------------------------------------

def _tools():
    return [{"type": "function", "function": {"name": "read_file", "description": "r" * 300,
                                              "parameters": {"type": "object", "properties": {}}}}]


def _full_body(s):
    """The real A7 0022 post-compaction body behind a harness-sized system message, with the restore block
    and the facts anchor placed as the plan-off driver places them."""
    restore, offered = loop._restored_text_message(s, MSGS)
    facts = loop._fetched_facts_anchor(s, MSGS, offered)
    system = {"role": "system", "content": "You are a coding agent. " + "Follow the project's rules. " * 700}
    return [system] + MSGS + [restore, facts], restore


class FloorAndWireTests(unittest.TestCase):
    def setUp(self):
        token = wsview.bind(_view())
        self.addCleanup(wsview.unbind, token)
        self.s = _session()
        self.s.workspace_root = ROOT
        self.s.read_files = {JAVA: (5157, "130 lines"), "pom.xml": (980, "29 lines")}

    def _window_for(self, msgs, room):
        base = [m for m in msgs if not cf._is_restored_text(m)]
        need = (cf._msgs_tokens(base) + cf.est_tokens(json.dumps(_tools()))) * 1.05
        return int(need) + room + 250

    def test_under_pressure_the_block_is_shed_with_a_label_and_the_reply_room_and_tail_survive(self):
        msgs, _ = _full_body(self.s)
        room = 1500
        window = self._window_for(msgs, room)
        out, _t, rep = cf.fit(msgs, _tools(), window=window, reserve=room, safety=1.05, pinned_task=self.s.plan.task)
        self.assertEqual(rep.restored_reduced, 1)
        self.assertFalse(rep.over_budget)
        *_y, without = cf.fit([m for m in msgs if not cf._is_restored_text(m)], _tools(), window=window,
                              reserve=room, safety=1.05, pinned_task=self.s.plan.task)
        self.assertEqual((rep.turns_dropped, rep.protected_dropped),                  # no live turn paid for it
                         (without.turns_dropped, without.protected_dropped))
        self.assertEqual(rep.reserve, room)                                          # the reply room is intact
        self.assertTrue(out[-1]["content"].startswith("⟦ctx:facts⟧"))                # the active tail is kept
        stand_in = next(m for m in out if (m["content"] or "").startswith(modelview.RESTORED_MARKER))
        self.assertIn("was here and was removed to fit the window: pom.xml, src/main/java/pipeline/Importer.java",
                      stand_in["content"])
        self.assertNotIn("package pipeline;", stand_in["content"])
        self.assertFalse(cf._is_restored_text(stand_in))

    def test_when_the_window_has_room_the_block_rides_whole(self):
        msgs, _ = _full_body(self.s)
        out, _t, rep = cf.fit(msgs, _tools(), window=32768, reserve=2000, safety=1.05, pinned_task=self.s.plan.task)
        self.assertEqual(rep.restored_reduced, 0)
        self.assertTrue(any(cf._is_restored_text(m) for m in out))

    def test_the_block_never_shrinks_the_reply_room(self):
        msgs, _ = _full_body(self.s)
        base = [m for m in msgs if not cf._is_restored_text(m)]
        window = self._window_for(msgs, 1500)
        *_x, with_block = cf.fit(msgs, _tools(), window=window, reserve=1500, safety=1.05, pinned_task=self.s.plan.task)
        *_y, without = cf.fit(base, _tools(), window=window, reserve=1500, safety=1.05, pinned_task=self.s.plan.task)
        self.assertEqual(with_block.reserve, without.reserve)

    def test_the_block_inside_the_protected_anchor_is_what_ate_the_reply_room(self):
        """The reviewed layout (B1), kept as the measurement: the same text inside ⟦ctx:facts⟧ cannot be shed
        and the reply reserve is squeezed (or the request goes over budget) at the window that fits the
        separate, reducible block with its full reserve."""
        msgs, restore = _full_body(self.s)
        room = 1500
        window = self._window_for(msgs, room)
        inside = [m for m in msgs if m is not restore]
        inside[-1] = {**inside[-1], "content": inside[-1]["content"] + "\n\n" + restore["content"]}
        *_x, rep = cf.fit(inside, _tools(), window=window, reserve=room, safety=1.05, pinned_task=self.s.plan.task)
        self.assertTrue(rep.reserve < room or rep.over_budget or rep.turns_dropped > 0 or rep.protected_dropped > 0)

    def test_a_floor_shed_block_grants_no_credit_and_the_ledger_stops_pointing_at_it(self):
        msgs, _ = _full_body(self.s)
        window = self._window_for(msgs, 1500)
        rlog = _Rlog()
        body = {"model": "m", "messages": msgs, "tools": _tools(), bodykeys.PINNED_TASK: self.s.plan.task,
                bodykeys.OUTPUT_RESERVE: 1500}
        raw, _e, _c = upstream.Upstream("http://unused", context_window=window)._prep(body, False, rlog, safety_override=1.05)
        self.assertEqual(rlog.restored_on_wire, {})
        wire = raw.decode()
        self.assertNotIn("its current text is below", wire)
        self.assertIn("no read result for it is in this conversation", wire)
        self.assertNotIn(bodykeys.RESTORED_FILES, wire)

    def test_a_block_that_reached_the_wire_earns_the_credit_and_the_hint_never_ships(self):
        msgs, restore = _full_body(self.s)
        rlog = _Rlog()
        body = {"model": "m", "messages": msgs, "tools": _tools(), bodykeys.PINNED_TASK: self.s.plan.task}
        raw, _e, _c = upstream.Upstream("http://unused", context_window=65536)._prep(body, False, rlog, safety_override=1.05)
        self.assertEqual(set(rlog.restored_on_wire), {JAVA, "pom.xml"})
        wire = raw.decode()
        self.assertIn("its current text is below", wire)
        self.assertIn("----- pom.xml -----", wire)
        self.assertNotIn(bodykeys.RESTORED_FILES, wire)

    def test_end_to_end_the_write_hold_lifts_only_for_delivered_text(self):
        """unread_target_check is what the write lowering asks: a blind whole-file write to Importer.java is
        answered with the measured fact — unless the whole text actually reached the model."""
        from tests.test_a_judges_doubt_is_not_an_order import _loop
        lp = _loop(None)
        lp._ctx.assists = True
        lp._store.get = lambda k: self.s
        check = lp.unread_target_check("k", MSGS, ROOT)
        self.assertIn("already exists on disk", check(JAVA))                       # nothing delivered yet
        self.s.restored_current = {}                                                # offered but shed by the floor
        self.assertIn("already exists on disk", check(JAVA))
        msgs, _ = _full_body(self.s)
        _m, on_wire = modelview.settle_restored_text(msgs)                          # delivered on the wire
        self.s.restored_current = dict(on_wire)
        self.assertEqual(check(JAVA), "")
        self.assertEqual(check("pom.xml"), "")
        self.s.restored_current = {}
        self.assertIn("already exists on disk", check(JAVA))


def test_the_literals_the_floor_and_the_wire_mirror_are_in_sync():
    assert cf._RESTORED_HINT == bodykeys.RESTORED_FILES
    assert modelview.RESTORED_MARKER == "⟦ctx:current⟧"
    assert prompts.load_map("fetched_facts_sections")["restore_header"].startswith(modelview.RESTORED_MARKER)
    assert prompts.load("restore_reduced").startswith(modelview.RESTORED_MARKER)


if __name__ == "__main__":
    unittest.main()
