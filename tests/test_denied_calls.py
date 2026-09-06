"""A call cria REFUSED must not be logged to a judge as something the coder's tool returned.

THE DEFECT. cria lowers a refused synthetic tool call to a ``printf`` of its own refusal text, so the
harness hands that text back as the tool's result and ``loop._work_log`` renders it ``  -> <text>`` —
byte-identical to a real result — while ``prompts/verify.txt`` tells the step critic in cria's own
voice that "each ``-> ...`` line is what it returned". Measured 2026-08-03 over the 127 captured
sessions in ~/.cria/calls, anchoring every refusal on cria's OWN prompt files rather than a copy of
their wording:

  * 216 of 537 step-critic prompts that carry an action log render at least one refusal that way
  * 140 of 370 satisfaction prompts (38%); 4 of 16 compaction prompts
  * 965 of 6,288 ``-> `` result bodies in critic prompts (15%)

WHAT THE LABEL MAY SAY, which is the whole of the design. It names the CALL — "this call did not
run" — and says NOTHING about the text beneath it. A refusal frequently CARRIES real ground truth:
``fetch_repeat_spilled`` embeds the document's own ``[API endpoints (33): …]`` block, the same block
``selfcompact`` anchors verbatim precisely because it is the API's real answer. An earlier attempt
labelled the BODY ("not content the tool returned") and landed on exactly that, telling the judge to
discard its only real evidence — a bigger false fact than the one being fixed. The tests below assert
both halves: the call IS labelled, and the body is passed through unqualified and verbatim.

MARKED WHERE REFUSED, NEVER MATCHED BY WORDING. ``cria.denial`` is applied at the sites that decide
to refuse (``writeproxy._refusal_command``, the two read-size guards, ``webfetch._guard_msg``'s
repeat-gate keys, the search-read denial). Nothing downstream asks what a result says.
"""
import os
import subprocess
import tempfile
import unittest

from cria import denial, loop, prompts, webfetch, writeproxy


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]

    def of(self, kind):
        return [kw for k, kw in self.events if k == kind]


# The measured shape this fix exists for, verbatim from run 20260802T214153 call 0053-critic: a
# repeat-fetch REFUSAL that carries the API's REAL endpoint list. The call did not run; every fact
# under it is true.
SPILLED_REFUSAL = denial.mark(
    "You already fetched web_fetch https://api.handle.me/openapi.json with these exact params. It "
    "was too large to inline, so it was saved IN FULL to ./tmp/reference/api.handle.me_openapi.json, "
    "and that file is still there.\n"
    "[API endpoints (33): /, /mcp, /openapi.json, /handles/{handle}, /holders/{address}, /stats]\n"
    "Read it — do NOT re-fetch the whole url.")

REAL_RESULT = ("HTTP 200 OK · https://api.handle.me/handles/goose\n"
               '{"name": "goose", "resolved_addresses": {"ada": "addr1..."}}')


def _turn(call_id, name, args, result):
    return [{"role": "assistant", "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": name, "arguments": args}}]},
            {"role": "tool", "tool_call_id": call_id, "content": result}]


class TheMarkTests(unittest.TestCase):
    def test_mark_prefixes_once_and_is_idempotent(self):
        once = denial.mark("nothing was run")
        self.assertTrue(once.startswith(denial.DENIED_MARKER))
        self.assertEqual(denial.mark(once), once)
        self.assertEqual(once.count(denial.DENIED_MARKER), 1)

    def test_empty_text_is_not_marked(self):
        # A bare marker would be a claim with nothing behind it.
        self.assertEqual(denial.mark(""), "")
        self.assertFalse(denial.is_denied(""))

    def test_the_marker_never_names_the_project(self):
        # #17 — model-facing markers use the ⟦ctx:…⟧ namespace, never the proper noun.
        self.assertTrue(denial.DENIED_MARKER.startswith("⟦ctx:"))
        self.assertNotIn("cria", denial.DENIED_MARKER)

    def test_a_real_result_is_never_denied(self):
        self.assertFalse(denial.is_denied(REAL_RESULT))


class RefusalsAreMarkedWhereTheyAreAuthoredTests(unittest.TestCase):
    def test_the_one_owner_marks_every_refusal_it_lowers(self):
        cmd = writeproxy._refusal_command("that path is outside the project directory")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertTrue(denial.is_denied(r.stdout))
        self.assertEqual(r.returncode, writeproxy.REFUSED_EXIT_CODE,
                         "a BLOCKED call did not run and must not report success")

    def test_the_SIZE_owner_marks_its_refusal_but_reports_no_failure(self):
        """The 2026-08-12 split. A read declined on size did not fail — and a non-zero exit on a
        read tells a small model the path is not there, which is a lie about the world."""
        cmd = writeproxy._oversize_command("that file is too large to return whole")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertTrue(denial.is_denied(r.stdout))
        self.assertEqual(r.returncode, 0)

    def test_the_WHOLE_READ_size_guard_refuses_and_says_so(self):
        # ADVERSARIAL PAIR, run for real: the same command must refuse a big file and READ a small
        # one. The guard decides in bash at run time, which is why the mark is written into the
        # refusing branch rather than derived from anything cria can see at lowering time.
        with tempfile.TemporaryDirectory() as d:
            big, small = os.path.join(d, "big.json"), os.path.join(d, "small.py")
            with open(big, "w") as fh:
                fh.write("x" * (writeproxy.READ_INLINE_MAX + 10))
            with open(small, "w") as fh:
                fh.write("print('hi')\n")
            rb = subprocess.run(["bash", "-c", writeproxy._read_command({"path": big})],
                                capture_output=True, text=True)
            rs = subprocess.run(["bash", "-c", writeproxy._read_command({"path": small})],
                                capture_output=True, text=True)
        self.assertTrue(denial.is_denied(rb.stdout))
        # Exit 0 since the 2026-08-12 ruling: a size refusal is not a failed call, and a non-zero
        # exit on a read tells a small model the file is not there. The DENIED MARK above is what
        # carries "no content came back" — that is the part this test exists for.
        self.assertEqual(rb.returncode, 0)
        self.assertFalse(denial.is_denied(rs.stdout))
        self.assertEqual(rs.stdout, "print('hi')\n")
        self.assertEqual(rs.returncode, 0)

    def test_the_RANGED_read_size_guard_refuses_and_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "spec.txt")
            with open(p, "w") as fh:
                fh.write(("y" * 200 + "\n") * 200)          # ~40 KB over 200 lines
            wide = subprocess.run(
                ["bash", "-c", writeproxy._read_command({"path": p, "start_line": 1, "end_line": 200})],
                capture_output=True, text=True)
            narrow = subprocess.run(
                ["bash", "-c", writeproxy._read_command({"path": p, "start_line": 1, "end_line": 2})],
                capture_output=True, text=True)
        self.assertTrue(denial.is_denied(wide.stdout))
        self.assertEqual(wide.returncode, 0)   # size refusal: declined, not failed
        self.assertFalse(denial.is_denied(narrow.stdout))
        self.assertEqual(narrow.returncode, 0)
        self.assertIn("1: yyy", narrow.stdout)

    def test_webfetch_marks_its_repeat_GATES_and_nothing_else(self):
        # The distinction that keeps a successful fetch from being called a refusal: `spill` and
        # `search_spill` are the results of a fetch that DID run.
        keys = prompts.load_map("webfetch_guards")
        for key in ("search_repeat", "search_repeat_inline", "fetch_repeat",
                    "fetch_repeat_failed", "fetch_repeat_spilled"):
            with self.subTest(key=key):
                self.assertTrue(denial.is_denied(webfetch._guard_msg(key)))
        for key in ("spill", "search_spill", "domain_steer", "guess_hint", "find_large"):
            with self.subTest(key=key):
                self.assertFalse(denial.is_denied(webfetch._guard_msg(key)),
                                 f"{key} is a real result, not a refused call")
        self.assertTrue(set(webfetch._REFUSAL_KEYS) <= set(keys),
                        "a refusal key was renamed in the prompt file and this set went stale")

    def test_the_search_repeat_gate_marks_through_its_real_entry_point(self):
        # Not the private renderer — the function the proxy actually calls.
        webfetch.set_visible("s-mark", [], ["ada handles api documentation"])
        msg = webfetch.gate_search("s-mark", "ada handles API documentation")
        self.assertIsNotNone(msg)
        self.assertTrue(denial.is_denied(msg))

    def test_a_real_search_is_not_marked(self):
        webfetch.set_visible("s-fresh", [], ["something else entirely"])
        self.assertIsNone(webfetch.gate_search("s-fresh", "ada handles API documentation"))


class WorkLogLabelsTheCallNotTheBodyTests(unittest.TestCase):
    def _log(self, msgs, rlog=None):
        return loop._work_log(msgs, rlog=rlog)

    def test_the_refused_CALL_is_labelled(self):
        log = self._log(_turn("c1", "web_fetch", '{"url":"https://api.handle.me/openapi.json"}',
                              SPILLED_REFUSAL))
        call = next(ln for ln in log.splitlines() if ln.startswith("$ web_fetch"))
        self.assertIn(prompts.load("work_log_denied"), call)

    def test_the_BODY_is_passed_through_verbatim_and_unqualified(self):
        # THE REGRESSION THIS FILE EXISTS FOR. The refusal carries the API's real endpoint list. The
        # label must appear on the call line ONLY — nothing may be said about these bytes, because
        # they are true and the judge needs them.
        log = self._log(_turn("c1", "web_fetch", '{"url":"…"}', SPILLED_REFUSAL))
        body = log.split("  -> ", 1)[1]
        self.assertEqual(body, SPILLED_REFUSAL)
        self.assertIn("[API endpoints (33): /, /mcp, /openapi.json, /handles/{handle},", body)
        label = prompts.load("work_log_denied")
        self.assertNotIn(label, body)

    def test_the_label_speaks_only_of_the_call(self):
        # The wording rule, asserted rather than trusted: the label may not characterise the text
        # below it. "returned" / "content" / "not real" are the words the rejected first attempt used.
        label = prompts.load("work_log_denied").lower()
        for banned in ("returned", "content", "not real", "ignore", "disregard", "cria"):
            self.assertNotIn(banned, label)

    def test_a_REAL_result_gets_no_label(self):
        # ADVERSARIAL — the input that must make it stay silent. A 200 with the page's real body.
        log = self._log(_turn("c1", "web_fetch", '{"url":"…"}', REAL_RESULT))
        self.assertNotIn(prompts.load("work_log_denied"), log)
        self.assertIn("resolved_addresses", log)

    def test_only_the_refused_call_of_a_MULTI_CALL_turn_is_labelled(self):
        # Why the pairing is by tool_call_id and not by position: one assistant turn, two calls, one
        # refused. Positional pairing would label the wrong one.
        msgs = [{"role": "assistant", "tool_calls": [
                    {"id": "a", "type": "function",
                     "function": {"name": "web_fetch", "arguments": '{"url":"https://x/ok"}'}},
                    {"id": "b", "type": "function",
                     "function": {"name": "web_fetch", "arguments": '{"url":"https://x/again"}'}}]},
                {"role": "tool", "tool_call_id": "a", "content": REAL_RESULT},
                {"role": "tool", "tool_call_id": "b", "content": SPILLED_REFUSAL}]
        lines = self._log(msgs).splitlines()
        label = prompts.load("work_log_denied")
        self.assertNotIn(label, next(ln for ln in lines if "https://x/ok" in ln))
        self.assertIn(label, next(ln for ln in lines if "https://x/again" in ln))

    def test_an_unpairable_result_is_left_alone_and_COUNTED(self):
        # ADVERSARIAL — the input that makes it silently not fire. A harness that sends no
        # tool_call_id cannot be attributed to a call, so nothing is labelled: exactly today's
        # behaviour, which is the safe direction. It is counted in the event rather than hidden.
        rlog = _Rlog()
        msgs = [{"role": "assistant", "tool_calls": [
                    {"id": "z", "type": "function",
                     "function": {"name": "web_fetch", "arguments": "{}"}}]},
                {"role": "tool", "content": SPILLED_REFUSAL}]
        log = self._log(msgs, rlog)
        self.assertNotIn(prompts.load("work_log_denied"), log)
        self.assertIn(SPILLED_REFUSAL, log)                       # still never destroyed
        self.assertEqual(rlog.of("loop.work_log_denied"), [{"level": "info", "labelled": 0,
                                                            "unpaired": 1}])

    def test_the_label_is_TRACED(self):
        rlog = _Rlog()
        self._log(_turn("c1", "read_file", '{"path":"spec.json"}', SPILLED_REFUSAL), rlog)
        self.assertEqual(rlog.of("loop.work_log_denied"),
                         [{"level": "info", "labelled": 1, "unpaired": 0}])

    def test_a_clean_log_emits_nothing(self):
        # #3 — on a clean signal, say nothing.
        rlog = _Rlog()
        self._log(_turn("c1", "web_fetch", "{}", REAL_RESULT), rlog)
        self.assertEqual(rlog.kinds(), [])

    def test_the_log_is_otherwise_byte_for_byte_what_it_was(self):
        # DIRECTION (#13): this fix only ever ADDS a label. Nothing is dropped, reordered or reworded,
        # so no step can advance and no task be approved that would not have been before.
        msgs = _turn("c1", "write_file", '{"path":"a.py"}', "wrote a.py") + \
            _turn("c2", "exec_command", '{"cmd":"pytest -q"}', "3 passed")
        self.assertEqual(self._log(msgs),
                         '$ write_file {"path":"a.py"}\n  -> wrote a.py\n'
                         '$ exec_command {"cmd":"pytest -q"}\n  -> 3 passed')


class TheSearchDenialIsLabelledNotDeletedTests(unittest.TestCase):
    """``_is_cria_scaffolding`` used to DELETE the search-read denial from the log. That removed the
    RESULT and kept the CALL, so the judge saw ``$ read_file …`` with no ``->`` line at all — a call
    that appears to have returned nothing, about a file still sitting on disk. Measured 2026-08-03 by
    replaying every captured coder turn through cria's own ``_work_log``: 229 turns across 9 runs,
    every one of them a hole."""

    NOTE = denial.mark("Those search results were off-target for this task, so they were removed. "
                       "Re-reading ./tmp/reference/search-x.txt is denied.")

    def test_the_call_keeps_a_result_line_and_gains_the_label(self):
        log = loop._work_log(_turn("r1", "read_file", '{"path":"./tmp/reference/search-x.txt"}',
                                   self.NOTE))
        lines = log.splitlines()
        self.assertIn(prompts.load("work_log_denied"), lines[0])
        self.assertTrue(lines[1].startswith("  -> "), "the call was left with no result line at all")
        self.assertIn("off-target", log)

    def test_the_denial_note_carries_the_shared_mark_not_a_private_one(self):
        rendered = prompts.render("search_read_denied", marker=denial.DENIED_MARKER,
                                  steer="", file="./tmp/reference/search-x.txt")
        self.assertTrue(denial.is_denied(rendered))

    def test_cria_gate_output_is_STILL_stripped(self):
        # The scaffolding filter kept its real job: cria's OWN probe run is not the coder's work.
        from cria import probegate, proberun
        self.assertTrue(loop._is_cria_scaffolding(probegate.SECTION_PREFIX + "probe-0"))
        self.assertTrue(loop._is_cria_scaffolding(proberun.PROBE_EXIT_SENTINEL + "0"))
        self.assertFalse(loop._is_cria_scaffolding(self.NOTE))


class TheJudgeSeesTheLabelTests(unittest.TestCase):
    """End to end through the evidence builders the judges actually read."""

    def test_the_step_critics_evidence_carries_it(self):
        sess = loop.PlanSession(plan=loop.Plan(id="p", task="t", created="c", items=[]))
        sess.workspace_root = ""
        lp = loop.Loop.__new__(loop.Loop)
        body = {"messages": _turn("c1", "web_fetch", '{"url":"https://api.handle.me/openapi.json"}',
                                  SPILLED_REFUSAL)}
        ev = lp._grounded_evidence(sess, body, _Rlog())
        self.assertIn(prompts.load("work_log_denied"), ev)
        self.assertIn("[API endpoints (33)", ev)

    def test_the_satisfaction_judges_evidence_carries_it(self):
        ev = loop._satisfaction_evidence(
            _turn("c1", "web_fetch", '{"url":"…"}', SPILLED_REFUSAL), rlog=_Rlog())
        self.assertIn(prompts.load("work_log_denied"), ev)


if __name__ == "__main__":
    unittest.main()
