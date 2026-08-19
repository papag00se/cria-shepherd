"""Two fixes from the full walk of ada-handles_mellum2_codex_pon_1785628543."""
import inspect
import json
import unittest
import unittest.mock

from dataclasses import replace

from cria import loop, rumination


class _RLog:
    """Minimal rlog stub — records nothing, just satisfies ``.emit(...)``."""

    def emit(self, *a, **kw):
        pass


def _plan_with_one_step():
    from cria.plan import Plan, PlanItem
    return Plan(id="20260707T0000-abcd1234", task="build it", created="2026-07-07T00:00:00+00:00",
                items=[PlanItem("step 1")])


def _low_trigger_ctx(reasoner_chat=None, compactor_chat=None):
    from cria.loop import LoopContext
    return replace(LoopContext(planner=None, coder_chat=None, reasoner_chat=reasoner_chat,
                               runs_dir="", compactor_chat=compactor_chat),
                   trigger_compaction=100)  # low trigger so the fixture's tail actually rolls up


def _big_transcript():
    # total must exceed the 6000-token default tail so there's a middle to roll up (~50 * 250 tok)
    return [{"role": "system", "content": "sys"}] + [
        {"role": "assistant", "content": "y" * 1000} for _ in range(50)]


class SelfCompactionAskTests(unittest.TestCase):
    """cria's ask must go LAST on BOTH compaction paths.

    Without it the transcript handed to the compactor ends on the coder's own step — "Do ONLY this
    step (2 of 4), then stop: Write test_resolve_handle.py ..." — and the compactor obeys that
    instead of summarizing. Call 25 of that run emitted `write_file({"path": ...` and degenerated to
    `v5v5v5...` until the token cap; call 26 produced a whole unittest file. cria then presented it
    as "⟦ctx:rollup⟧ Summary of your earlier turns this session" — a file that had never been
    written and was not on disk. The coder believed it: "The user has given me a test suite."

    da35f4e fixed exactly this on the harness path and never reached the self-compaction sibling.
    """

    def test_exactly_ONE_place_composes_the_request(self):
        # Fixing the sibling by copying the two lines would leave a third place to forget. It was
        # the duplication that let the two paths drift apart in the first place. STRUCTURAL: "only
        # one module may even name the ask" has no black-box input — a second owner that never runs
        # is exactly what this must catch, so there's nothing to drive.
        from cria import selfcompact, server
        owners = [m for m in (server, loop, selfcompact)
                  if "compact_closing_ask" in inspect.getsource(m)]
        self.assertEqual(owners, [selfcompact], "only selfcompact may name the ask")

    def test_both_paths_delegate_to_the_one_composer_and_none_hand_composes(self):
        """There were THREE compaction paths, not two — the third (plan-off's since-removed
        _summarize_single) was found only because the other two were unified, and it shipped no
        closing ask at all. A caller that reimplemented the composition by hand (its own
        ``selfcompact.serialize(probegate.clean_gate_results(...))``) would never call the real
        composer — so patch the composer and drive both surviving entry points; the patch must
        fire from each, or one of them is still hand-assembling the transcript."""
        from cria import selfcompact, server
        from cria.loop import Loop

        calls = []

        def fake_compaction_request(messages, files_list="", gate_plan=None):
            calls.append(len(messages))
            return "COMPOSED"

        with unittest.mock.patch.object(selfcompact, "compaction_request", fake_compaction_request):
            # the harness-compaction path (server.py)
            out = server._compaction_transcript([{"role": "user", "content": "hi"}])
            self.assertEqual(out, "COMPOSED")

            # the self-compaction path (loop.py)
            def reasoner(body, rlog):
                return json.dumps({"choices": [{"message": {"content": "ROLLUP"}}]}).encode()

            from cria.loop import PlanSession
            ctx = _low_trigger_ctx(reasoner_chat=reasoner)
            sess = PlanSession(plan=_plan_with_one_step())
            Loop(ctx)._self_compact(_big_transcript(), sess, 1, _RLog())

        self.assertEqual(len(calls), 2, "both entry points must delegate to the one composer")

    def test_the_evidence_comes_first_and_the_ask_last(self):
        from cria import prompts, selfcompact
        out = selfcompact.compaction_request(
            [{"role": "user", "content": "do ONLY this step, then stop: write the file"}])
        ask = prompts.load("compact_closing_ask")
        self.assertTrue(out.endswith(ask), "nothing may out-recency cria's ask")
        self.assertLess(out.index("write the file"), out.index(ask))

    def test_the_ask_forbids_code_and_tool_calls(self):
        from cria import prompts
        ask = prompts.load("compact_closing_ask")
        self.assertIn("no tool call", ask.lower())
        self.assertIn("no code", ask.lower())


class DegenerateUnitTests(unittest.TestCase):
    """The backstop tested for a single repeated CHARACTER. The real streams were two characters
    wide — `y8y8y8...` for 40,759 tokens, five minutes of a fifteen-minute run, and `v5v5v5...`
    inside the compactor. Neither was caught."""

    W = rumination.DEGENERATE_RUN_CHARS

    def test_the_measured_two_char_streams_are_caught(self):
        for unit in ("y8", "v5"):
            with self.subTest(unit=unit):
                self.assertTrue(rumination.degenerate_tail(unit * self.W))

    def test_a_single_repeated_character_still_is(self):
        self.assertTrue(rumination.degenerate_tail("y" * (self.W + 10)))

    def test_any_repeating_period_is_caught_not_just_a_short_one(self):
        """The bound used to be an 8-character unit. Walked on run 1785714194 call 0014: a repeating
        run with a period of 260 burned 40,138 tokens over 255 seconds — 66% of all model time in an
        eight-minute run — and the guard returned False the whole way. It ran inside a write_file
        ARGUMENT, which the rumination watcher excludes on purpose, so nothing else could see it."""
        for size in (2, 3, 8, 64, 255, 260):
            unit = "".join(chr(97 + (i % 26)) for i in range(size))
            with self.subTest(period=size):
                self.assertTrue(rumination.degenerate_tail(unit * (self.W * 2 // size)))

    def test_a_period_needing_fewer_than_three_repeats_is_left_alone(self):
        unit = "x" + "".join(chr(97 + (i % 26)) for i in range(900))
        self.assertFalse(rumination.degenerate_tail(unit * 3))

    def test_real_output_is_NOT_flagged(self):
        # Never block a run that is genuinely producing text.
        for text in ("".join(f"the {i} quick brown foxes jumped over {i * 3} lazy dogs. "
                             for i in range(200)),
                     "".join(f"line {i}: value = {i * 7}\n" for i in range(400)),
                     "".join(f"    self.assertEqual(result[{i}], {i})\n" for i in range(300))):
            with self.subTest(text=text[:30]):
                self.assertFalse(rumination.degenerate_tail(text))

    def test_short_input_is_never_flagged(self):
        self.assertFalse(rumination.degenerate_tail("y8" * 10))


class NoHandComposedTranscriptTests(unittest.TestCase):
    """There were THREE compaction paths, not two — the third — plan-off's _summarize_single — was
    found only because the other two were unified, and it shipped no closing ask at all.
    Every path must go through the one composer."""

    def test_the_composer_cleans_raw_gate_plumbing(self):
        """``compaction_request`` must clean gate plumbing itself rather than trust a caller to have
        done it first — the composer is the ONE place, so it can't assume its input is already
        clean."""
        from cria import probegate, selfcompact
        raw = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
               "x.py:5: undefined name 'foo'\nEXIT:1\n")
        out = selfcompact.compaction_request([{"role": "user", "content": "go"},
                                               {"role": "tool", "content": raw}])
        self.assertNotIn(probegate.SECTION_PREFIX, out, "raw gate plumbing must not reach the model")
        self.assertIn("undefined name 'foo'", out, "the real finding must survive the cleaning")

    def test_the_summarizer_input_stubs_superseded_write_bodies(self):
        """compact() already stubs the transcript it EMITS; the summarizer's INPUT did not, so the
        model writing the briefing read every old version of every file and put them in it — and the
        briefing is prompt-leading content in the next turn. Measured on nemotron orders-api-py
        0049, where the prompt opens with a full superseded orders/db.py body and the model then
        described two different versions as "current"."""
        from cria import prompts, selfcompact
        old_body = "OLD_CONTENT_" * 40
        new_body = "NEW_CONTENT_" * 40
        confirm = lambda p: prompts.render("write_confirm", path=p)
        msgs = [
            {"role": "user", "content": "write app.py"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": old_body})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": confirm("app.py")},
            {"role": "assistant", "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "app.py", "content": new_body})}}]},
            {"role": "tool", "tool_call_id": "c2", "content": confirm("app.py")},
        ]
        out = selfcompact.compaction_request(msgs)
        self.assertNotIn(old_body, out, "the superseded body must not reach the model verbatim")
        self.assertIn(new_body, out, "the live/current body must still be there in full")

    def test_the_plan_off_fold_is_gone_and_the_adapter_delegates(self):
        # `_summarize_single` is gone. The plan-off driver had a whole second copy of the compaction —
        # its own summarizer, its own refold, its own pinned task — and the two copies had each drifted
        # to hold something the other needed. There is ONE now, and the plan-off adapter delegates to
        # it rather than reimplementing it.
        self.assertFalse(hasattr(loop.Loop, "_summarize_single"),
                         "the second compaction copy must stay removed")

        from cria.loop import Loop, PlanSession
        sentinel = [{"role": "user", "content": "SENTINEL FROM _self_compact"}]
        with unittest.mock.patch.object(Loop, "_self_compact",
                                        lambda self, msgs, sess, idx, rlog, **kw: sentinel):
            ctx = _low_trigger_ctx()
            sess = PlanSession(plan=_plan_with_one_step())
            framed = {"messages": [{"role": "user", "content": "hi"}], "tools": []}
            out = Loop(ctx)._self_compact_single(framed, sess, _RLog(), root_task="do it")
        # the adapter's output IS whatever _self_compact returned — proof it delegates rather than
        # running its own (now-deleted) copy of the fold
        self.assertIs(out["messages"], sentinel)

    def test_the_one_fold_uses_the_compactor_ENDPOINT_not_just_its_role(self):
        # The plan-ON copy selected the compactor ROLE and then sent the call to `reasoner_chat`, so a
        # configured compactor endpoint was ignored on that path. The plan-OFF copy had this right.
        from cria.loop import Loop, PlanSession

        def reasoner(body, rlog):
            return json.dumps({"choices": [{"message": {"content": "FROM REASONER"}}]}).encode()

        def compactor(body, rlog):
            return json.dumps({"choices": [{"message": {"content": "FROM COMPACTOR"}}]}).encode()

        ctx = _low_trigger_ctx(reasoner_chat=reasoner, compactor_chat=compactor)
        sess = PlanSession(plan=_plan_with_one_step())
        out = Loop(ctx)._self_compact(_big_transcript(), sess, 1, _RLog())
        rollup = next(m["content"] for m in out if "⟦ctx:rollup⟧" in str(m.get("content")))
        self.assertIn("FROM COMPACTOR", rollup, "a configured compactor endpoint must be used")
        self.assertNotIn("FROM REASONER", rollup, "the reasoner endpoint must not be used instead")

    def test_the_one_fold_keeps_the_gate_ground_truth_override(self):
        # The plan-OFF copy never appended this — the override that stops a rollup laundering an
        # unverified "the tests pass" claim past cria's real last check state.
        from cria.loop import Loop, PlanSession

        def reasoner(body, rlog):
            return json.dumps({"choices": [{"message": {"content": "all 7 tests now pass"}}]}).encode()

        ctx = _low_trigger_ctx(reasoner_chat=reasoner)
        sess = PlanSession(plan=_plan_with_one_step())
        sess.last_gate_red = True
        sess.last_gate_flag = "⟦ctx:checks⟧ test_x.py:1: AssertionError: 400 != 200"
        rollup = next(m["content"] for m in Loop(ctx)._self_compact(_big_transcript(), sess, 1, _RLog())
                      if "⟦ctx:rollup⟧" in str(m.get("content")))
        self.assertIn("all 7 tests now pass", rollup)    # the laundered claim is still there...
        self.assertIn("currently FAIL", rollup)          # ...but so is the real gate state, which wins
        self.assertIn("400 != 200", rollup)
