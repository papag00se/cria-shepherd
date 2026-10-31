"""A file the coder wrote by relative path and by absolute path is ONE file to the fold.

`_drop_superseded_writes` removes every write to a path except the newest, because only the newest
is what is on disk. It keyed on the path STRING the tool call carried, and a coder is free to spell
the same file either way — the tool resolves both against its own cwd and they land on the same
inode.

Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857. The coder wrote `Importer.java`
seven times by absolute path and once, at call 0043, as `src/main/java/pipeline/Importer.java`. Two
spellings, two dict keys, so neither run of writes ever superseded the other: the single largest
payload in the session went unfolded, and cria's own note listed the same file twice in one sentence
— which reads as two different files that both changed (#5b).

cria cannot resolve the relative spelling by path: the working directory belongs to the HARNESS, so
`abspath` here would anchor to cria's own cwd and name a file that does not exist. It is resolved by
SHAPE instead — a component-wise suffix match against the absolute paths the same session wrote —
and an ambiguous suffix does not fold at all, because the cost of folding wrongly is deleting a
file's only copy while the cost of not folding is a duplicate the model can still read.
"""

import json
import unittest

from cria import focustrim


BIG = focustrim._STUB_MIN_CHARS + 50
ABS = "/w/repo/src/main/java/pipeline/Importer.java"
REL = "src/main/java/pipeline/Importer.java"


def write(i, path, ch):
    return [{"role": "assistant", "tool_calls": [{"id": f"w{i}", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": path, "content": ch * BIG})}}]},
            # the write program's own typed `landed` outcome, as `represent_inbound` hands it on
            {"role": "tool", "tool_call_id": f"w{i}", "content": f"Wrote {path}", "cria_result_outcome": "landed"}]


def note_of(msgs):
    return next((m["content"] for m in msgs if m.get("role") == "user"), "")


class TheTwoSpellingsFoldTests(unittest.TestCase):
    def test_a_relative_write_is_superseded_by_a_later_absolute_write(self):
        msgs = write(0, ABS, "a") + write(1, REL, "b") + write(2, ABS, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 2)                  # was 0 for the relative one
        bodies = json.dumps(out)
        self.assertIn("c" * 40, bodies)               # the newest survives whole
        self.assertNotIn("b" * 40, bodies)

    def test_the_note_names_the_file_once_not_once_per_spelling(self):
        msgs = write(0, ABS, "a") + write(1, REL, "b") + write(2, ABS, "c")
        out, _ = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(note_of(out).count("Importer.java"), 1)

    def test_the_absolute_spelling_is_the_one_reported(self):
        # The relative form is meaningless without the harness's cwd; the note must not print it.
        msgs = write(0, REL, "a") + write(1, ABS, "b")
        out, _ = focustrim._drop_superseded_writes(msgs)
        self.assertIn(ABS, note_of(out))


class AmbiguityIsLeftAloneTests(unittest.TestCase):
    def test_a_suffix_matching_two_absolute_paths_does_not_fold(self):
        # `a/x.java` sits under both roots. Folding would drop a real file's only copy.
        one, two, rel = "/w/one/a/x.java", "/w/two/a/x.java", "a/x.java"
        msgs = write(0, one, "a") + write(1, two, "b") + write(2, rel, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIn("c" * 40, json.dumps(out))

    def test_two_genuinely_different_files_never_fold(self):
        msgs = write(0, "/w/a/x.java", "a") + write(1, "/w/b/y.java", "b")
        _out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)


class TheOldBehaviourIsUnchangedTests(unittest.TestCase):
    def test_repeated_absolute_writes_still_fold(self):
        msgs = write(0, ABS, "a") + write(1, ABS, "b") + write(2, ABS, "c")
        _out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 2)

    def test_a_single_write_is_untouched(self):
        msgs = write(0, ABS, "a")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIs(out, msgs)


class AnUnresolvedAliasIsAnUnknownFileNotADifferentOneTests(unittest.TestCase):
    """`_path_identity` refuses to fold a relative spelling that is a suffix of TWO absolute paths: the harness's cwd decides which,
    and cria cannot read it. "Not folded" is UNKNOWN. The candidate universe is every file the session tried to write — including a
    write whose result was cut, unknown, uncertain or unanswered — so that rival is never invisible.

    Incident (independent review, genuine producers): `s1/alias.rb` = A landed; `s2/alias.rb` = B real write but its first record
    arrived CUT (unknown); then a real relative `alias.rb` = C run in cwd s2 landed. The identity was built from LANDED writes only, so
    `s2` was invisible, C folded onto `s1`, the only copy of A was REMOVED and the note said "Nothing was lost" — while the disk held
    s1 = A, s2 = C."""

    A = "# A\n" + "a = 1\n" * 120
    B = "# B\n" + "b = 2\n" * 120
    C = "# C\n" + "c = 3\n" * 120

    @staticmethod
    def _bodies(msgs):
        return [json.loads(tc["function"]["arguments"]).get("content") for m in msgs for tc in (m.get("tool_calls") or [])]

    def _real(self, *, cut_second):
        import os
        import tempfile
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as root:
            root = os.path.realpath(root)
            s1, s2 = os.path.join(root, "s1"), os.path.join(root, "s2")
            os.mkdir(s1)
            os.mkdir(s2)
            first = genuine_call("write_file", {"path": os.path.join(s1, "alias.rb"), "content": self.A}, "w1", s1)
            second = genuine_call("write_file", {"path": os.path.join(s2, "alias.rb"), "content": self.B}, "w2", s2,
                                  cut_stdout=20 if cut_second else None)
            rel = genuine_call("write_file", {"path": "alias.rb", "content": self.C}, "w3", s2)     # cwd s2: overwrites s2/alias.rb
            with open(os.path.join(s1, "alias.rb")) as one, open(os.path.join(s2, "alias.rb")) as two:
                self.assertEqual((one.read(), two.read()), (self.A, self.C))                         # the real disk
        return first + second + rel

    def test_a_write_whose_result_was_cut_is_still_a_candidate_so_nothing_is_deleted_or_called_replaced(self):
        from cria import denial
        msgs = self._real(cut_second=True)
        self.assertNotEqual(denial.proof(msgs[3]), denial.LANDED)                      # w2's cut result cannot prove it landed (it did, on disk)
        out, report = focustrim.trim(msgs)
        self.assertEqual(self._bodies(out), [self.A, self.B, self.C])                 # every payload stays
        final = focustrim.superseded_writes_truth(out)
        self.assertFalse([m for m in final if m.get("role") == "user" and "removed from the history" in str(m.get("content"))])
        self.assertNotIn("Nothing was lost", json.dumps(final))

    def test_even_with_every_result_proven_an_ambiguous_relative_write_supersedes_nothing_and_is_not_dropped(self):
        msgs = self._real(cut_second=False)
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertEqual(self._bodies(out), [self.A, self.B, self.C])

    def test_an_older_ambiguous_alias_is_never_dropped_by_a_later_write_to_one_of_its_candidates(self):
        msgs = (write(0, "/r/s1/alias.rb", "a") + write(1, "/r/s2/alias.rb", "b") + write(2, "alias.rb", "c")
                + write(3, "/r/s1/alias.rb", "d"))
        out, dropped = focustrim._drop_superseded_writes(msgs)
        bodies = json.dumps(out)
        self.assertIn("c" * 40, bodies)                       # the alias's only copy stays: it may name either file
        self.assertEqual(dropped, 1)                          # only the resolved older write to s1 is superseded by w3
        self.assertNotIn("a" * 40, bodies)


class AReusedCallIdNeverTakesAnUnrelatedWriteWithIt(unittest.TestCase):
    """Removal deletes every call and every result carrying a dropped id. With a REUSED id that took an unrelated write along.

    Incident (independent review, genuine producers): `a.rb`=A (id `dup`), `b.rb`=B (id `dup`), then a unique-id landed `a.rb`=C.
    The shared pairing correctly treats `dup` as unpaired (which result answers which call is unknowable), but removal went by id
    membership: `a.rb`=A superseded, so BOTH `dup` calls and results were removed — `b.rb`=B, which nothing replaced and which the disk
    still holds, lost its only recorded payload, and the final note said "Nothing was lost"."""

    A = "# A\n" + "a = 1\n" * 120
    B = "# B\n" + "b = 2\n" * 120
    C = "# C\n" + "c = 3\n" * 120

    def _real(self, first_id="dup", second_id="dup"):
        import os
        import tempfile
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            a = genuine_call("write_file", {"path": "a.rb", "content": self.A}, first_id, cwd)
            b = genuine_call("write_file", {"path": "b.rb", "content": self.B}, second_id, cwd)
            c = genuine_call("write_file", {"path": "a.rb", "content": self.C}, "u1", cwd)
            with open(os.path.join(cwd, "a.rb")) as fa, open(os.path.join(cwd, "b.rb")) as fb:
                self.assertEqual((fa.read(), fb.read()), (self.C, self.B))
        return a + b + c

    @staticmethod
    def _bodies(msgs):
        return [json.loads(tc["function"]["arguments"]).get("content") for m in msgs for tc in (m.get("tool_calls") or [])]

    def test_the_genuine_reused_id_witness_loses_nothing_through_trim_and_the_final_settlement(self):
        msgs = self._real()
        out, _report = focustrim.trim(msgs)
        self.assertEqual(self._bodies(out), [self.A, self.B, self.C])                        # b.rb's only payload stays
        self.assertEqual([m.get("tool_call_id") for m in out if m.get("role") == "tool"], ["dup", "dup", "u1"])
        final = focustrim.superseded_writes_truth(out)
        text = json.dumps(final)
        self.assertNotIn("Nothing was lost", text)
        self.assertNotIn("removed from the history", text)

    def test_a_unique_id_older_write_is_still_superseded_beside_an_unrelated_reused_id_pair(self):
        msgs = self._real(first_id="u0", second_id="dup") + write(9, "/w/other/x.rb", "z") + write(9, "/w/other/y.rb", "y")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 1)                                                          # only the unique older a.rb=A
        bodies = self._bodies(out)
        self.assertNotIn(self.A, bodies)
        self.assertIn(self.B, bodies)
        self.assertIn(self.C, bodies)
        self.assertIn("z" * 40, json.dumps(out))                                              # the reused-id pair elsewhere stays whole
        self.assertIn("y" * 40, json.dumps(out))

    def test_two_reused_id_writes_to_one_file_are_both_kept(self):
        msgs = write(5, ABS, "a") + write(5, ABS, "b") + write(6, ABS, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIs(out, msgs)

    def test_a_write_answered_twice_is_kept(self):
        first = write(5, ABS, "a")
        msgs = first + [{"role": "tool", "tool_call_id": "w5", "content": "again", "cria_result_outcome": "landed"}] + write(6, ABS, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)


class AWriteThatHasNotProvablyFinishedIsNeverRemovedForALaterOne(unittest.TestCase):
    """Dispatch order is not execution order. An older write that is unanswered — or answered only after the replacement was sent —
    may still execute AFTER it, so removing it destroys the only record of what the disk will hold.

    Incident (independent review, genuine producers): a real lowered `pending.rb`=A dispatched first but blocked at the harness; a later
    genuine `pending.rb`=C landed; A then ran and landed (disk = A) but its receipt never reached the received history. Trim removed A's
    only payload and the settled note said C replaced it / "Nothing was lost". Also: a result delivered under `call_id` was invisible to
    the local counter (zero results → removable) and its output was left orphaned."""

    A = "# A\n" + "a = 1\n" * 120
    C = "# C\n" + "c = 3\n" * 120

    def _pair(self, a_id="pa", c_id="pc"):
        import os
        import tempfile
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            a = genuine_call("write_file", {"path": "pending.rb", "content": self.A}, a_id, cwd)
            c = genuine_call("write_file", {"path": "pending.rb", "content": self.C}, c_id, cwd)
        return a, c

    @staticmethod
    def _bodies(msgs):
        return [json.loads(tc["function"]["arguments"]).get("content") for m in msgs for tc in (m.get("tool_calls") or [])]

    def _assert_nothing_removed(self, msgs, expected):
        out, _report = focustrim.trim(msgs)
        self.assertEqual(self._bodies(out), expected)
        final = focustrim.superseded_writes_truth(out)
        text = json.dumps(final)
        self.assertNotIn("Nothing was lost", text)
        self.assertNotIn("removed from the history", text)
        self.assertEqual(len([m for m in final if m.get("role") == "tool"]), len([m for m in msgs if m.get("role") == "tool"]))

    def test_an_unanswered_older_write_is_kept_when_a_later_one_lands(self):
        a, c = self._pair()
        self._assert_nothing_removed([a[0]] + c, [self.A, self.C])              # A's receipt was never received

    def test_an_older_write_answered_only_after_the_replacement_was_dispatched_is_kept(self):
        a, c = self._pair()
        self._assert_nothing_removed([a[0]] + c + [a[1]], [self.A, self.C])      # A's result arrives after C's call AND result

    def test_an_older_write_answered_before_the_replacement_was_dispatched_is_still_removed(self):
        a, c = self._pair()
        out, dropped = focustrim._drop_superseded_writes(a + c)
        self.assertEqual(dropped, 1)
        self.assertEqual(self._bodies(out), [self.C])
        self.assertEqual([m.get("tool_call_id") for m in out if m.get("role") == "tool"], ["pc"])    # its result goes with it

    def test_a_result_delivered_under_call_id_is_paired_and_removed_with_its_call_leaving_no_orphan(self):
        a, c = self._pair()
        alias = {k: v for k, v in a[1].items() if k != "tool_call_id"}
        alias["call_id"] = "pa"
        out, dropped = focustrim._drop_superseded_writes([a[0], alias] + c)
        self.assertEqual(dropped, 1)
        self.assertEqual([m for m in out if m.get("role") == "tool" and (m.get("tool_call_id") or m.get("call_id")) == "pa"], [])

    def test_a_call_answered_under_both_spellings_is_ambiguous_and_kept_with_both_results(self):
        a, c = self._pair()
        alias = {k: v for k, v in a[1].items() if k != "tool_call_id"}
        alias["call_id"] = "pa"
        msgs = [a[0], a[1], alias] + c
        self._assert_nothing_removed(msgs, [self.A, self.C])


class AReplyThatArrivedIsNotACompletedWriteTests(unittest.TestCase):
    """Pairing and result arrival never prove completion. A lowered command's reply can be "still running" (it outlived the harness's
    yield window), cut, unframed or `uncertain` — none of those is terminal, so the write may still be executing and can neither be
    removed as "replaced" nor be ordered before a later write.

    Incident (independent review, genuine producers): A dispatched first, the harness answered "Process running …" (received BEFORE C was
    dispatched), C dispatched and landed, and A then ran to completion LAST — the disk held A. The pair positions made A look finished:
    trim deleted A's only payload and called C its replacement."""

    A = "# A\n" + "a = 1\n" * 120
    C = "# C\n" + "c = 3\n" * 120

    def _witness(self):
        import os
        import tempfile
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            c = genuine_call("write_file", {"path": "p.rb", "content": self.C}, "pc", cwd)                   # C executes first…
            a = genuine_call("write_file", {"path": "p.rb", "content": self.A}, "pa", cwd, running=True)     # …A completes last
            with open(os.path.join(cwd, "p.rb")) as fh:
                self.assertEqual(fh.read(), self.A)                                                          # disk = A
        return a, c

    @staticmethod
    def _bodies(msgs):
        return [json.loads(tc["function"]["arguments"]).get("content") for m in msgs for tc in (m.get("tool_calls") or [])]

    def test_a_still_running_reply_received_before_the_replacement_is_not_completion(self):
        from cria import denial
        a, c = self._witness()
        self.assertEqual(denial.proof(a[1]), denial.UNKNOWN)               # the reply proves neither landed nor refused
        msgs = a + c                                                       # A, "running", C, C landed — A's reply arrived BEFORE C was sent
        out, _report = focustrim.trim(msgs)
        self.assertEqual(self._bodies(out), [self.A, self.C])
        final = focustrim.superseded_writes_truth(out)
        self.assertNotIn("Nothing was lost", json.dumps(final))
        self.assertNotIn("removed from the history", json.dumps(final))
        self.assertEqual(len([m for m in final if m.get("role") == "tool"]), 2)

    def test_unknown_uncertain_and_native_replies_are_not_terminal_either(self):
        a, c = self._witness()
        for label, reply in (("unknown", {**a[1], "cria_result_outcome": "unknown"}),
                             ("uncertain", {**a[1], "cria_result_outcome": "uncertain"}),
                             ("native, unframed", {k: v for k, v in a[1].items() if not k.startswith("cria_")})):
            with self.subTest(label):
                out, dropped = focustrim._drop_superseded_writes([a[0], reply] + c)
                self.assertEqual(dropped, 0)
                self.assertEqual(self._bodies(out), [self.A, self.C])

    def test_a_known_terminal_result_before_the_replacement_is_still_removed(self):
        from cria import denial
        a, c = self._witness()
        landed = {**a[1], "cria_result_outcome": denial.LANDED}            # the same reply, but now the program's own landed record
        out, dropped = focustrim._drop_superseded_writes([a[0], landed] + c)
        self.assertEqual(dropped, 1)
        self.assertEqual(self._bodies(out), [self.C])


if __name__ == "__main__":
    unittest.main()
