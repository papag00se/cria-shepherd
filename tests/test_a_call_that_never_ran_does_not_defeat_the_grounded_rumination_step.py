"""One fact, one answer: a write-class call whose result says it never ran did not change the file.

ornith1.5_9b / Java 1792961160 (session 01a174d0, calls 0072 -> 0073). The coder had read
`Importer.java` (lines 219-351, covering the checker's flagged line), no edit had landed since the
check, and its last call was a shell redirect (`git show ... > /tmp/Importer_head.java`) that cria
refused: the harness answered with the `⟦ctx:denied⟧` text and nothing ran.

`gate_unedited` honours a refusal once the write registry has recorded it (`refused_write_ids`). The
grounded rumination step asks the same question about the file the coder READ, through
`_write_paths_after` -> `_mutation_targets`, and that path counted the refused redirect as `_ANY_PATH`
("any file may have changed") even with the refusal recorded: two owners of one fact, two answers.
`_write_paths_after` now skips the ids `loop._unlanded_call_ids` reports, the source the registry uses.

Scope: the fixtures here have the registry SETTLED (it has recorded the refusal, as it does on the next
forwarded turn). Whether it has recorded it yet when the abort turn is recovered is a separate question
about when results are observed, deliberately not covered or changed here.

This does not widen what dirguard proves read-only; a call that really ran and is not proven read-only
still counts as a possible mutation of any file."""
import json
import unittest
from collections import Counter

from cria import bodykeys, denial, editrecovery, loop, writeobservation

REL = "src/main/java/pipeline/Importer.java"
ABS = "/w/" + REL
FLAG = ("[GROUND TRUTH — the repo's own checks fail] The failures:\n"
        f"$ mvn -q compile — {ABS}:238: cannot find symbol")
READ_BODY = "\n".join(f"{i}: l{i}" for i in range(219, 352))
# A normalized minimal refusal fixture (shaped after call 0071's result, 0072's message 32; the text and
# paths are edited, not verbatim), marked where the refusal is authored.
DENIED = denial.mark(
    "Process exited with code 1\nOutput:\nWriting/reading outside the working directory is not permitted here "
    "for this path: '/tmp/Importer_head.java' is outside the project directory (/w). Writes must stay inside "
    "the project directory.")
LANDED = "Chunk ID: 1\nWall time: 0.0 seconds\nProcess exited with code 0\nOutput:\n"
REDIRECT = "cd /w && git show HEAD:src/main/java/pipeline/Importer.java > /tmp/Importer_head.java"


class _Log:
    def emit(self, *a, **k):
        pass


def _call(cid, name, args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}]}


def _result(cid, text, outcome=None):
    """A tool result as `represent_inbound` hands it on: the proven outcome rides as a message-level hint."""
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def _read():
    return [_call("r1", "read_file", {"path": REL, "start_line": 219, "end_line": 351}), _result("r1", READ_BODY)]


def _session(msgs):
    """A session whose gate named `Importer.java:238`, each call in `msgs` forwarded after it — through the real
    recorder, one registration per forwarded reply with the history that PRECEDED it — and the registry then SETTLED
    by observing the results already in `msgs` (refusals included)."""
    s = loop.PlanSession(plan=[])
    s.workspace_root = "/w"
    # an earlier, non-write call turns write tracking on, as any real session has before its first gate
    loop._record_dispatch(s, {"choices": [{"message": {"tool_calls": [
        {"id": "b0", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}}]}, [])
    loop.track_gate_progress(s, FLAG, [])
    for i, m in enumerate(msgs):
        if m.get("tool_calls"):
            loop._record_dispatch(s, {"choices": [{"message": {"tool_calls": m["tool_calls"]}}]}, msgs[:i])
    loop._record_dispatch(s, {"choices": []}, msgs)                     # the next turn observes the results
    return s


def _services(msgs):
    return loop._generation_grounding_services(_session(msgs), msgs)


class AWriteThatNeverRanDidNotChangeTheFile(unittest.TestCase):
    def test_a_refused_redirect_after_the_read_leaves_the_notice_standing(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", DENIED, denial.REFUSED)]
        out = loop.grounded_rumination_step(_session(msgs), msgs)
        self.assertIn(f"{ABS}:238: cannot find symbol", out)
        self.assertIn("line 238", out)

    def test_the_gate_state_and_the_mutation_test_give_one_answer_once_the_refusal_is_recorded(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", DENIED, denial.REFUSED)]
        svc = _services(msgs)
        self.assertTrue(svc.gate_unedited())
        self.assertFalse(svc.mutated_after(msgs, 1, REL))

    def test_an_edit_that_did_not_apply_did_not_change_the_file(self):
        msgs = _read() + [_call("e1", "edit_file", {"path": REL, "old_string": "a", "new_string": "b"}),
                          _result("e1", editrecovery.EDIT_MARK + " old_string was not found", denial.UNAPPLIED)]
        self.assertFalse(_services(msgs).mutated_after(msgs, 1, REL))


class ACallThatRanStillDefeatsIt(unittest.TestCase):
    def test_the_same_redirect_that_was_not_refused_still_counts(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", LANDED)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))
        self.assertEqual(loop.grounded_rumination_step(_session(msgs), msgs), "")

    def test_a_shell_call_that_failed_but_was_not_denied_still_counts(self):
        # A non-zero exit is a process failure, not "never ran": a shell may write before it fails.
        failed = "Chunk ID: 2\nWall time: 0.0 seconds\nProcess exited with code 1\nOutput:\ncp: cannot stat 'x'\n"
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", failed)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))
        self.assertEqual(loop.grounded_rumination_step(_session(msgs), msgs), "")

    def test_a_reused_call_id_is_ambiguous_so_the_refusal_is_not_assumed(self):
        # id `w1` names two calls: which one the proven result answers is unknowable. Withheld, never skipped.
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", DENIED, denial.REFUSED),
                          _call("w1", "write_file", {"path": REL, "content": "x"}), _result("w1", LANDED)]
        self.assertEqual(loop._unlanded_call_ids(msgs), set())
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))

    def test_a_marker_without_the_proven_hint_is_not_a_refusal(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", DENIED)]
        self.assertEqual(loop._unlanded_call_ids(msgs), set())
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))

    def test_a_call_with_no_result_yet_still_counts(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT})]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))

    def test_an_unproven_shell_command_that_ran_still_counts(self):
        msgs = _read() + [_call("s1", "exec_command", {"cmd": "git status 2>&1 | head -20"}), _result("s1", LANDED)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))

    def test_a_refusal_does_not_hide_a_later_real_edit_of_the_path(self):
        msgs = _read() + [_call("w1", "exec_command", {"cmd": REDIRECT}), _result("w1", DENIED, denial.REFUSED),
                          _call("e1", "edit_file", {"path": REL, "old_string": "a", "new_string": "b"}),
                          _result("e1", LANDED)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))
        self.assertEqual(loop.grounded_rumination_step(_session(msgs), msgs), "")

    def test_a_refusal_of_another_call_does_not_hide_a_real_write_in_the_same_turn(self):
        msgs = _read() + [
            {"role": "assistant", "tool_calls": [
                _call("w1", "exec_command", {"cmd": REDIRECT})["tool_calls"][0],
                _call("w2", "write_file", {"path": REL, "content": "x"})["tool_calls"][0]]},
            _result("w1", DENIED, denial.REFUSED), _result("w2", LANDED)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))



# ---- the REGISTRY'S STATE, progressing the way the driver feeds it -----------------------------------------------
#
# One owner (`writeobservation`), two facts: the ORDERED write dispatches (`write_call_ids`, duplicates allowed) and
# the exact multiplicity of EVERY dispatch by id (`call_counts`, non-writes included). An id that does not name
# exactly one dispatch is unknown: its refusal and its answer are filtered out AT USE, so anything stored before a
# collision is invalidated by it. Every test drives the production wrapper (`loop._record_dispatch`) and the real
# gate registrar (`loop.track_gate_progress`), with the gate taken AFTER the first settlement — the ordering in
# which a mark of 0 would hide the defect.

def _reply(*tcs):
    return {"choices": [{"message": {"tool_calls": list(tcs)}}]}


def _tc(cid, name, args):
    return _call(cid, name, args)["tool_calls"][0]


def _asst(*tcs):
    return {"role": "assistant", "tool_calls": list(tcs)}


class _Registry:
    """A session fed exactly like the driver: ``forward`` = one accepted reply; ``gate`` = a gate verdict."""
    def __init__(self):
        self.s = loop.PlanSession(plan=[])
        self.s.workspace_root = "/w"
        self.msgs = _read()
        loop._record_dispatch(self.s, _reply(_tc("r1", "read_file", {"path": REL})), [])   # tracking is live

    def forward(self, *tcs):
        loop._record_dispatch(self.s, _reply(*tcs), list(self.msgs))     # history = what PRECEDES the reply
        self.msgs.append(_asst(*tcs))

    def answer(self, cid, text, outcome=None):
        self.msgs.append(_result(cid, text, outcome))

    def gate(self):
        loop.track_gate_progress(self.s, FLAG, self.msgs)

    def unedited(self):
        return loop.gate_unedited(self.s)

    def services(self):
        return loop._generation_grounding_services(self.s, self.msgs)


REFUSED_W = _tc("w1", "write_file", {"path": REL, "content": "A"})
REAL_SAME_TOOL_TARGET = _tc("w1", "write_file", {"path": REL, "content": "B changed payload"})
REAL_IDENTICAL = _tc("w1", "write_file", {"path": REL, "content": "A"})
READ_W1 = _tc("w1", "read_file", {"path": REL})


class ASettledRefusalNeverHidesALaterDispatchReusingTheId(unittest.TestCase):
    def setUp(self):
        self.r = _Registry()
        self.r.forward(REFUSED_W)
        self.r.answer("w1", DENIED, denial.REFUSED)
        self.r.gate()                                  # the gate comes AFTER the refusal settled: mark=1, pending empty

    def test_the_unique_old_refusal_with_no_new_dispatch_is_unedited(self):
        self.assertEqual((self.r.s.gate_write_mark, self.r.s.gate_pending_write_ids), (1, set()))
        self.assertTrue(self.r.unedited())
        self.assertIn(f"{ABS}:238: cannot find symbol", loop.grounded_rumination_step(self.r.s, self.r.msgs))

    def _reuse(self, tc):
        self.r.forward(tc)

    def test_same_tool_and_target_with_a_changed_payload_is_a_real_dispatch(self):
        self._reuse(REAL_SAME_TOOL_TARGET)
        self.assertEqual(self.r.s.write_call_ids, ["w1", "w1"])        # one entry per ACTUAL write dispatch
        self.assertEqual(self.r.s.call_counts["w1"], 2)
        self.assertFalse(self.r.unedited())
        self.assertTrue(self.r.services().mutated_after(self.r.msgs, 1, REL))
        self.assertEqual(loop.grounded_rumination_step(self.r.s, self.r.msgs), "")

    def test_an_identical_call_reusing_the_id_is_just_as_real(self):
        self._reuse(REAL_IDENTICAL)
        self.assertEqual(self.r.s.write_call_ids, ["w1", "w1"])
        self.assertFalse(self.r.unedited())

    def test_it_stays_unknown_while_pending_after_every_kind_of_second_result_and_a_later_gate(self):
        self._reuse(REAL_SAME_TOOL_TARGET)
        for result in (_result("w1", LANDED), _result("w1", DENIED, denial.REFUSED), _result("w1", "ok")):
            self.r.msgs.append(result)
            self.r.gate()                              # a FRESH later gate
            self.assertFalse(self.r.unedited(), result)
            self.assertNotIn("w1", writeobservation.unlanded_ids(self.r.s))
            self.assertNotIn("w1", writeobservation.answered_ids(self.r.s, self.r.s.write_result_ids))

    def test_compaction_never_makes_the_id_unique_again(self):
        self._reuse(REAL_SAME_TOOL_TARGET)
        self.r.answer("w1", DENIED, denial.REFUSED)    # a proven-looking result for the NEW call only
        self.r.msgs = _read()                          # both w1 occurrences leave the window
        self.r.gate()
        self.assertEqual(self.r.s.call_counts["w1"], 2)
        self.assertFalse(self.r.unedited())

    def test_a_rescan_of_the_same_history_adds_nothing(self):
        self._reuse(REAL_SAME_TOOL_TARGET)
        before = (list(self.r.s.write_call_ids), dict(self.r.s.call_counts))
        for _ in range(3):
            self.r.gate()
        self.assertEqual((list(self.r.s.write_call_ids), dict(self.r.s.call_counts)), before)


class ADispatchByAnotherToolCannotAnswerOrClearAWrite(unittest.TestCase):
    def test_write_then_read_reusing_the_id_a_read_result_never_answers_the_pending_write(self):
        r = _Registry()
        r.forward(REFUSED_W)                           # the write is pending
        r.forward(READ_W1)                             # a NON-write dispatch reuses its id
        r.answer("w1", "file bytes")                   # the read's result arrives
        self.assertEqual(r.s.call_counts["w1"], 2)
        r.gate()                                       # a fresh gate while the write is still outstanding
        self.assertIn("w1", r.s.gate_pending_write_ids)
        self.assertFalse(r.unedited())

    def test_the_same_with_the_older_occurrence_compacted_away(self):
        r = _Registry()
        r.forward(REFUSED_W)
        r.forward(READ_W1)
        r.msgs = _read()                               # neither occurrence is in the window any more
        r.answer("w1", "orphan result")
        r.gate()
        self.assertEqual(r.s.call_counts["w1"], 2)
        self.assertIn("w1", r.s.gate_pending_write_ids)
        self.assertFalse(r.unedited())

    def test_read_then_write_reusing_the_id_with_the_read_already_in_the_initial_history(self):
        r = _Registry()
        r.msgs += [_asst(READ_W1)]                     # the history already holds an earlier read named w1 ...
        r.forward(REFUSED_W)                           # ... and a fresh WRITE named w1 is forwarded
        self.assertEqual(r.s.call_counts["w1"], 2)     # reconcile BEFORE the fresh increment: two, not one
        r.answer("w1", DENIED, denial.REFUSED)
        r.gate()
        self.assertEqual(r.s.write_call_ids, ["w1"])
        self.assertFalse(r.unedited())                 # the proof cannot say which of the two dispatches it belongs to

    def test_a_refusal_whose_call_left_the_window_stays_known_while_the_id_is_unique(self):
        r = _Registry()
        r.forward(REFUSED_W)
        r.answer("w1", DENIED, denial.REFUSED)
        r.gate()
        r.msgs = _read()                               # w1 compacted away: still ONE dispatch ever observed
        r.gate()
        self.assertEqual(r.s.call_counts["w1"], 1)
        self.assertTrue(r.unedited())


class AnUnknownRegistryAnswersNothing(unittest.TestCase):
    def test_missing_counts_or_dead_tracking_are_unknown_never_unique(self):
        s = loop.PlanSession(plan=[])
        s.refused_write_ids = {"w1"}
        s.write_result_ids = {"w1"}
        self.assertEqual(writeobservation.unlanded_ids(s), frozenset())
        self.assertEqual(writeobservation.answered_ids(s, s.write_result_ids), frozenset())
        s.call_counts = Counter({"w1": 1})
        self.assertEqual(writeobservation.unlanded_ids(s), frozenset())          # tracking not live
        s.write_tracking = True
        self.assertEqual(writeobservation.unlanded_ids(s), frozenset({"w1"}))

    def test_the_snapshot_never_exposes_an_ambiguous_id_as_settled(self):
        s = loop.PlanSession(plan=[])
        loop._record_dispatch(s, _reply(REFUSED_W), [])
        snap = loop._record_dispatch(s, _reply(REAL_SAME_TOOL_TARGET), [_asst(REFUSED_W), _result("w1", DENIED, denial.REFUSED)])
        self.assertEqual(snap.unlanded_ids, frozenset())


class AResultAnswersOnlyThroughTheOneOrderedCorrelationOwner(unittest.TestCase):
    def _answered(self, msgs):
        s = loop.PlanSession(plan=[])
        s.write_call_ids = ["w1"]
        loop._note_write_results(s, msgs)
        return s.write_result_ids

    def test_exactly_one_call_and_one_result_after_it_answers(self):
        self.assertEqual(self._answered(_read() + [_asst(REFUSED_W), _result("w1", LANDED)]), {"w1"})

    def test_an_orphan_a_result_before_its_call_and_a_duplicate_answer_nothing(self):
        self.assertEqual(self._answered(_read() + [_result("w1", LANDED)]), set())
        self.assertEqual(self._answered(_read() + [_result("w1", LANDED), _asst(REFUSED_W)]), set())
        self.assertEqual(self._answered(_read() + [_asst(REFUSED_W), _result("w1", LANDED), _result("w1", "again")]), set())

    def test_one_call_and_two_results_one_proven_one_not_is_withheld(self):
        msgs = _read() + [_asst(_tc("w1", "exec_command", {"cmd": REDIRECT})),
                          _result("w1", DENIED, denial.REFUSED), _result("w1", LANDED)]
        self.assertEqual(loop._unlanded_call_ids(msgs), set())
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))

    def test_a_result_that_precedes_its_call_gains_no_proof_from_a_later_call(self):
        msgs = _read() + [_result("w1", DENIED, denial.REFUSED), _asst(_tc("w1", "exec_command", {"cmd": REDIRECT}))]
        self.assertEqual(loop._unlanded_call_ids(msgs), set())

    def test_the_proven_pair_in_order_still_counts(self):
        msgs = _read() + [_asst(_tc("w1", "exec_command", {"cmd": REDIRECT})), _result("w1", DENIED, denial.REFUSED)]
        self.assertEqual(loop._unlanded_call_ids(msgs), {"w1"})


class AForwardedReplyIsRecordedExactlyOnce(unittest.TestCase):
    def test_observation_and_the_stalled_guards_never_register_a_dispatch(self):
        s = loop.PlanSession(plan=[])
        reply = _reply(REFUSED_W, READ_W1)
        snap = loop._record_dispatch(s, reply, [])
        once = (list(s.write_call_ids), dict(s.call_counts))
        self.assertEqual(once, (["w1"], {"w1": 2}))
        for _ in range(3):                                        # repeated observation / measurement is pure
            loop._stalled_observation(s, [], _Log(), observed=snap).measure()
        self.assertEqual((list(s.write_call_ids), dict(s.call_counts)), once)
        with self.assertRaises(TypeError):                        # no hidden recording fallback exists
            loop._stalled_observation(s, [], _Log())

    def test_the_explicit_shim_registers_once_per_forwarded_reply(self):
        s = loop.PlanSession(plan=[])
        loop.guard_track_refusals(s, _reply(REFUSED_W), _Log(), step=1, messages=[])
        loop.guard_track_refusals(s, _reply(REAL_IDENTICAL), _Log(), step=1, messages=[_asst(REFUSED_W)])
        self.assertEqual((s.write_call_ids, s.call_counts["w1"]), (["w1", "w1"], 2))

    def test_a_driven_reply_is_one_registration_streamed_or_not(self):
        from tests.test_a_write_to_a_file_never_seen_says_what_cria_measured import (
            _Recorder, _ctx, _Rlog as _DriveLog, ROOT)
        from cria.loop import _plan_off_session, _synthetic_plan
        from tests.test_loop import _body
        for stream in (True, False):
            reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [
                _tc("d1", "write_file", {"path": "A.java", "content": "x"}), _tc("d2", "read_file", {"path": "A.java"})]},
                "finish_reason": "tool_calls"}]}
            lp = loop.Loop(_ctx(_Recorder([reply]), None))
            sess = _plan_off_session(_synthetic_plan("fix the importer"), "")
            sess.workspace_root = ROOT
            lp._store.put("sid:once", sess)
            body = _body()
            body["stream"] = stream
            body["messages"].insert(0, {"role": "user", "content": f"Working environment — cwd: {ROOT}"})
            lp.drive(body, "sid:once", None, _DriveLog())
            self.assertEqual((sess.write_call_ids, dict(sess.call_counts)), (["d1"], {"d1": 1, "d2": 1}), stream)


class AnAbortedGenerationStillSeesTheRefusalThatArrivedWithItsRequest(unittest.TestCase):
    """PUBLIC LIFECYCLE through `Loop.drive`, no pre-settled registry: a write is forwarded in one request, its own
    refusal arrives with the next, and the generation of that next request is ABORTED (nothing is forwarded, so the
    forwarded-reply record never runs). The recovery notice is built before any record could settle the refusal, so
    the accepted-request evidence owner must have folded the incoming history in already."""

    def _drive(self):
        from tests.test_a_write_to_a_file_never_seen_says_what_cria_measured import _Recorder, _ctx, _Rlog as _Lg, ROOT
        from tests.test_loop import _body, _ruminating
        from cria.loop import _plan_off_session, _synthetic_plan
        write_reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "w1", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": REDIRECT})}}]},
            "finish_reason": "tool_calls"}]}
        retry = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "n1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": REL})}}]},
            "finish_reason": "tool_calls"}]}
        rec = _Recorder([write_reply, _ruminating(), retry])
        lp = loop.Loop(_ctx(rec, None))
        sess = _plan_off_session(_synthetic_plan("fix the importer"), "")
        sess.workspace_root = ROOT
        lp._store.put("sid:abort", sess)
        env = {"role": "user", "content": f"Working environment — cwd: {ROOT}"}
        first = _body()
        first["messages"].insert(0, env)
        lp.drive(first, "sid:abort", None, _Lg())                         # request 1: the write is FORWARDED (registered)
        self.assertEqual(sess.write_call_ids, ["w1"])
        flag = f"$ mvn -q compile — {ROOT}/{REL}:238: cannot find symbol"
        read = _read()
        history = [env, first["messages"][1], *read, _asst(_tc("w1", "exec_command", {"cmd": REDIRECT}))]
        loop.track_gate_progress(sess, flag, history)                      # the gate verdict: w1 has no result yet
        second = _body()
        second["messages"] = history + [_result("w1", DENIED, denial.REFUSED)]   # request 2: its own refusal arrives
        lp.drive(second, "sid:abort", None, _Lg())
        return rec, sess

    def test_the_grounded_notice_is_built_from_the_refusal_that_arrived_with_the_aborted_request(self):
        rec, sess = self._drive()
        notice = rec.bodies[2]["messages"][-1]["content"]                  # the recovery retry's final user message
        self.assertIn("None of your file edit/write tool calls has landed since that check", notice)
        self.assertEqual(sess.refused_write_ids, {"w1"})
        self.assertTrue(loop.gate_unedited(sess))                          # gate state and read freshness agree at once
        self.assertEqual(sess.call_counts["w1"], 1)                        # observed, never double-registered

    def test_other_unproven_shell_commands_still_block_the_notice(self):
        # UNCHANGED by the lifecycle fix: an unproven shell (sed/awk/git) after the read still counts as a possible
        # mutation, so the notice stays withheld for the original 0070/0073 contexts.
        msgs = _read() + [_asst(_tc("g1", "exec_command", {"cmd": "git status 2>&1 | head -20"})), _result("g1", LANDED)]
        self.assertTrue(_services(msgs).mutated_after(msgs, 1, REL))


class TheRegistryObservesTheCanonicalAcceptedHistoryNotTheFocusedCopy(unittest.TestCase):
    """Deterministic facts are gathered from the accepted request body BEFORE focus/trim discards anything. With
    focus ON, repeated failing calls (some sharing an id) are squashed out of what the coder sees; the registry must
    still count every one of them, before the first live record and after later compaction."""

    FAIL_CMD = "pytest -q tests/x.py"

    def _history(self, ids):
        from tests.test_a_write_to_a_file_never_seen_says_what_cria_measured import ROOT
        msgs = [{"role": "user", "content": f"Working environment — cwd: {ROOT}"}, {"role": "user", "content": "fix it"}]
        for i in ids:
            msgs += [_asst(_tc(i, "exec_command", {"cmd": self.FAIL_CMD})), _result(i, "boom\nEXIT:1")]
        return msgs

    def _drive(self, lp, sess, msgs, key="sid:focus"):
        from tests.test_loop import _body
        from tests.test_a_write_to_a_file_never_seen_says_what_cria_measured import _Rlog as _Lg
        body = _body()
        body["messages"] = msgs
        lp.drive(body, key, None, _Lg())

    def _loop(self):
        from tests.test_a_write_to_a_file_never_seen_says_what_cria_measured import _Recorder, _ctx, ROOT
        from cria.loop import _plan_off_session, _synthetic_plan
        reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "n1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}}]},
            "finish_reason": "tool_calls"}]}
        rec = _Recorder([reply])
        lp = loop.Loop(_ctx(rec, None))
        sess = _plan_off_session(_synthetic_plan("fix"), "")
        sess.workspace_root = ROOT
        lp._store.put("sid:focus", sess)
        return lp, sess, rec

    def test_every_dispatch_in_the_accepted_body_is_counted_even_when_focus_drops_it_from_the_prompt(self):
        lp, sess, rec = self._loop()
        ids = [f"f{i}" for i in range(14)] + ["dup", "dup"]
        self._drive(lp, sess, self._history(ids))
        shown = {tc["id"] for m in rec.bodies[0]["messages"] for tc in (m.get("tool_calls") or [])}
        self.assertLess(len([i for i in ids if i in shown]), len(set(ids)))            # focus REALLY discarded some
        self.assertEqual(sess.call_counts["dup"], 2)                                    # ... yet the registry kept both
        self.assertTrue(all(sess.call_counts[f"f{i}"] == 1 for i in range(14)))
        self.assertNotIn("dup", writeobservation.unique_ids(sess))
        self.assertIn("f0", writeobservation.unique_ids(sess))

    def test_a_refusal_proven_for_a_reused_id_is_unknown_before_the_first_live_record(self):
        lp, sess, rec = self._loop()
        msgs = self._history(["dup", "dup"]) + [_asst(_tc("w9", "write_file", {"path": REL, "content": "x"})),
                                                _result("w9", DENIED, denial.REFUSED)]
        msgs[3] = _result("dup", DENIED, denial.REFUSED)                                  # a refusal-looking result for dup
        self.assertFalse(sess.write_tracking)                                             # nothing forwarded yet
        self._drive(lp, sess, msgs)
        self.assertEqual(sess.call_counts["dup"], 2)
        self.assertNotIn("dup", writeobservation.unlanded_ids(sess))
        self.assertIn("w9", writeobservation.unlanded_ids(sess))                          # the unique refusal still counts

    def test_a_later_compacted_body_can_never_make_the_id_unique_again(self):
        lp, sess, rec = self._loop()
        self._drive(lp, sess, self._history(["dup", "dup"]))
        self.assertEqual(sess.call_counts["dup"], 2)
        self._drive(lp, sess, self._history([])[:2])                                      # compaction: both occurrences gone
        self.assertEqual(sess.call_counts["dup"], 2)
        self.assertNotIn("dup", writeobservation.unique_ids(sess))


class AReadsFreshnessScanUsesTheAcceptedBodyNotTheReshapedCopy(unittest.TestCase):
    def test_a_mutation_the_reshaped_copy_dropped_still_counts(self):
        seen = _read()                                                    # what the coder SEES: the read only
        accepted = _read() + [_asst(_tc("g1", "exec_command", {"cmd": "echo x > " + REL})), _result("g1", LANDED)]
        s = loop.PlanSession(plan=[])
        s.workspace_root = "/w"
        reshaped_only = loop._generation_grounding_services(s, seen).mutated_after(seen, 1, REL)
        with_accepted = loop._generation_grounding_services(s, seen, accepted).mutated_after(seen, 1, REL)
        self.assertFalse(reshaped_only)                                   # the copy alone would have said "unchanged"
        self.assertTrue(with_accepted)                                    # the accepted body says it may have changed
        self.assertTrue(loop._generation_grounding_services(s, seen, [_asst(_tc("g2", "read_file", {}))]
                                                           ).mutated_after(seen, 1, REL))   # a read it cannot locate: unknown


class _Log:
    phase = "coder"

    def emit(self, *a, **k):
        pass


if __name__ == "__main__":
    unittest.main()
