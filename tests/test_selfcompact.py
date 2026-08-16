import unittest

from cria import selfcompact
from cria.selfcompact import CompactState, compact

# Small token budgets so tiny fixtures exercise the real token paths. boundary_keep_tail_tokens matches
# keep_tail here so the existing force tests behave as before; the boundary-vs-trigger test sets its own.
_KW = dict(trigger_tokens=100, keep_tail_tokens=30, recompact_tokens=20, boundary_keep_tail_tokens=30)


def _m(role, text):
    return {"role": role, "content": text}


def _msgs(n, anchor_at=None, anchor_text="⟦ctx:briefing⟧ prior"):
    out = [_m("system", "sys")]
    for i in range(n):
        if anchor_at is not None and i == anchor_at:
            out.append(_m("user", anchor_text))
        else:
            out.append(_m("assistant", f"turn-{i} " + "x" * 20))   # ~6 tokens each
    return out


class SelfCompactTests(unittest.TestCase):
    def test_noop_below_trigger(self):
        m = _msgs(3)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(1), "S")[1], CompactState(), **_KW)
        self.assertFalse(applied)
        self.assertIs(out, m)
        self.assertEqual(calls, [])

    def test_force_compacts_below_trigger_when_there_is_a_middle(self):
        # STEP BOUNDARY: force compacts the accumulated middle even BELOW the size trigger, so a just-
        # verified step's raw signals are rolled up now instead of lingering until the view crosses trigger.
        m = _msgs(10)                          # ~60 tokens: below trigger(100), but a middle beyond tail(30)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(mm), "ROLLUP")[1], CompactState(), force=True, **_KW)
        self.assertTrue(applied)                                    # forced despite being below trigger
        self.assertEqual(len(calls), 1)                             # summarized once
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(x.get("content")) for x in out))
        self.assertEqual(out[0], m[0]); self.assertEqual(out[-1], m[-1])  # system + most-recent kept

    def test_force_is_noop_when_view_fits_a_nonzero_boundary_tail(self):
        # With a NON-ZERO boundary tail, a view that wholly fits it is NOT force-compacted (folding a couple
        # of messages would only add length). _KW sets boundary_keep_tail_tokens=30 to exercise this; the
        # PRODUCTION default is 0 — see test_boundary_default_folds_all_work_to_the_rollup.
        m = _msgs(3)   # ~18 tokens < boundary tail (30)
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(), force=True, **_KW)
        self.assertFalse(applied)
        self.assertIs(out, m)   # unchanged, no rollup added

    def test_boundary_default_folds_all_work_to_the_rollup(self):
        # THE DEFAULT (BOUNDARY_KEEP_TAIL_TOKENS = 0): a step boundary keeps NO verbatim work tail — the
        # finished step's turns fold ENTIRELY into the rollup. Nothing survives verbatim but the system
        # message and the rollup (the caller supplies the next step in system, pins the task, and anchors
        # the facts — none present in this minimal fixture). This is "why keep a tail?" answered: we don't.
        m = _msgs(30)  # system + 29 work turns, no anchors, no pinned task
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(),
                                  trigger_tokens=100, keep_tail_tokens=120, recompact_tokens=20, force=True)
        self.assertTrue(applied)
        self.assertEqual(out[0], m[0])                                              # system kept
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(x.get("content")) for x in out))
        self.assertEqual(len(out), 2)                                              # system + rollup, no tail

    def test_empty_summary_folds_NOTHING(self):
        # FAIL SAFE: `summarize` returns "" on a failed/empty compactor call (a reasoning model can burn its
        # budget thinking and emit no content — captured 6/6 on one run). Adopting it would advance `covered`
        # to the tail and replace every folded turn with a rollup header that has NOTHING under it — at a
        # BOUNDARY (no verbatim tail) that is the whole work history destroyed by one bad model call, the
        # undetectable lie never-truncate exists to prevent. So an empty summary folds nothing at all.
        m = _msgs(30)
        for force in (True, False):
            out, state, applied = compact(m, lambda mm: "   ", CompactState(), force=force,
                                          trigger_tokens=100, keep_tail_tokens=120, recompact_tokens=20)
            self.assertFalse(applied, f"force={force}")
            self.assertEqual(out, m, f"force={force}")     # every turn kept VERBATIM — the floor sizes it
            self.assertEqual(state.summary, "")            # and no empty summary is latched into the state

    def test_boundary_pins_the_task_so_the_fold_cannot_lose_it(self):
        # A boundary keeps no tail, so the task MUST be pinned or it folds away. With pinned_task set, the
        # ⟦ctx:task⟧ anchor survives verbatim even as all the work folds.
        task = "Resolve an Ada Handle to its Cardano address via api.handle.me, with tests and a README"
        m = _msgs(30)
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(), pinned_task=task,
                                  trigger_tokens=100, keep_tail_tokens=120, recompact_tokens=20, force=True)
        self.assertTrue(applied)
        self.assertTrue(any(task in str(x.get("content")) for x in out))           # task survives the fold

    def test_boundary_folds_the_completed_step_not_just_lowers_the_trigger(self):
        # THE FIX: at a step boundary the finished step's work must FOLD, not linger in the working-set tail.
        # A boundary keeps only boundary_keep_tail (small); a size-trigger compaction keeps the full tail. So
        # the boundary view is LEANER — the ~14KB that grew between step 1 and step 2 rolls up instead.
        m = _msgs(60)  # ~360 tokens
        kw = dict(trigger_tokens=100, keep_tail_tokens=120, recompact_tokens=20, boundary_keep_tail_tokens=24)
        trig_out, _, a1 = compact(m, lambda mm: "R", CompactState(), **kw)             # size-trigger
        bnd_out, _, a2 = compact(m, lambda mm: "R", CompactState(), force=True, **kw)  # step boundary
        self.assertTrue(a1 and a2)
        self.assertLess(len(bnd_out), len(trig_out))   # boundary keeps a SMALLER verbatim tail → folds more

    def test_surfaced_spec_shape_is_anchored_not_folded(self):
        # A web_fetch result carrying cria's [API endpoints …] / [response shape …] blocks holds the API's
        # REAL endpoint + field names. It must survive folding VERBATIM — the summarizer drops identifier
        # names, so folding it would erase the exact fields and the coder would guess. Kept verbatim; NOT
        # fed to the summarizer.
        spec = "[response shape — GET /handles/{handle} → holder, resolved_addresses{ada, eth, btc}]"
        m = _msgs(40, anchor_at=3, anchor_text=spec)
        captured = []
        out, _, applied = compact(m, lambda mm: captured.append(mm) or "ROLLUP", CompactState(), force=True, **_KW)
        self.assertTrue(applied)
        self.assertTrue(any("resolved_addresses" in str(x.get("content")) for x in out))  # kept verbatim
        fed = captured[0] if captured else []
        self.assertFalse(any("resolved_addresses" in selfcompact._text(x) for x in fed))  # never summarized

    def test_triggers_on_tokens_not_message_count(self):
        # a FEW big messages (over the token trigger) compact even though the count is small
        big = [_m("system", "sys")] + [_m("assistant", "y" * 800) for _ in range(6)]  # ~1200 tokens
        out, _, applied = compact(big, lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(x.get("content")) for x in out))

    def test_compacts_old_middle_keeps_recent_tail(self):
        m = _msgs(40)
        calls = []
        out, st, applied = compact(m, lambda mm: (calls.append(mm), "ROLLUP")[1], CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertEqual(len(calls), 1)                 # summarized once
        self.assertLess(len(out), len(m))               # leaner
        self.assertEqual(out[0], m[0])                  # system kept
        self.assertEqual(out[-1], m[-1])               # most recent turn verbatim

    def test_throttled_reuse_then_recompact(self):
        state = CompactState()
        calls = []
        summ = lambda mm: (calls.append(1), f"S{len(calls)}")[1]
        _, state, _ = compact(_msgs(40), summ, state, **_KW)
        self.assertEqual(len(calls), 1)
        _, state, _ = compact(_msgs(42), summ, state, **_KW)     # tiny growth → reuse
        self.assertEqual(len(calls), 1)
        _, state, _ = compact(_msgs(80), summ, state, **_KW)     # band over recompact → re-summarize
        self.assertEqual(len(calls), 2)

    def test_anchor_kept_verbatim_not_summarized(self):
        m = _msgs(40, anchor_at=2, anchor_text="⟦ctx:briefing⟧ the earlier plan handoff")
        out, _, _ = compact(m, lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(any("the earlier plan handoff" in str(x.get("content")) for x in out))

    def test_anchor_markers_stay_in_sync(self):
        from cria.loop import BRIEFING_OPEN, CONTINUATION_MARKER
        from cria.probegate import SECTION_PREFIX
        from cria import webfetch
        self.assertIn(BRIEFING_OPEN, selfcompact._ANCHOR_MARKERS)
        self.assertIn(SECTION_PREFIX, selfcompact._ANCHOR_MARKERS)
        # cria's harness-compaction reframe is a cria-authored summary — it must be an anchor so the
        # next self-compaction never summarizes it (the rollup-of-rollup task-inversion footgun).
        self.assertIn(CONTINUATION_MARKER, selfcompact._ANCHOR_MARKERS)
        # the surfaced-spec markers must mirror webfetch's real emitters, so anchoring never drifts out of
        # sync with the block the coder actually receives (external field ground truth kept verbatim).
        self.assertEqual(selfcompact._SPEC_ROUTES_MARKER, webfetch.ROUTES_MARKER)
        self.assertEqual(selfcompact._SPEC_SHAPE_MARKER, webfetch.SHAPE_MARKER)
        self.assertIn(webfetch.ROUTES_MARKER, selfcompact._ANCHOR_MARKERS)
        self.assertIn(webfetch.SHAPE_MARKER, selfcompact._ANCHOR_MARKERS)
        # the durable fetch-ledger anchor the loop re-injects must be kept verbatim through a fold too.
        self.assertIn(selfcompact.FACTS_MARKER, selfcompact._ANCHOR_MARKERS)

    def test_continuation_reframe_is_not_fed_to_the_summarizer(self):
        # A ⟦ctx:continuation⟧ message in the middle must be kept verbatim, never summarized — so
        # cria's own reframed prior-summary can't compound into a rollup-of-a-rollup.
        from cria.loop import CONTINUATION_MARKER
        m = _msgs(40, anchor_at=2, anchor_text=f"{CONTINUATION_MARKER} your earlier work: built X")
        captured = []
        out, _, _ = compact(m, lambda mm: captured.append(mm) or "ROLLUP", CompactState(), **_KW)
        # kept verbatim in the compacted view
        self.assertTrue(any("your earlier work: built X" in str(x.get("content")) for x in out))
        # and NOT among the messages handed to the summarizer
        fed = captured[0] if captured else []
        self.assertFalse(any(CONTINUATION_MARKER in selfcompact._text(x) for x in fed))


class PinnedTaskTests(unittest.TestCase):
    """The conversation-root task is re-emitted verbatim as a ⟦ctx:task⟧ north-star header on every
    compacted view — so it can't erode into the summary across rounds. Without it a plan-off session
    lost its goal (only an impoverished one-line rollup survived) and drifted onto tangential work."""

    def test_task_header_pinned_after_system_before_rollup(self):
        m = _msgs(40)
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(),
                                  pinned_task="Build the Handle resolver", **_KW)
        self.assertTrue(applied)
        self.assertEqual(out[0], m[0])                                    # system still first
        self.assertIn(selfcompact.TASK_MARKER, str(out[1]["content"]))    # task header right after system
        self.assertIn("Build the Handle resolver", str(out[1]["content"]))
        contents = [str(x.get("content")) for x in out]
        ti = next(i for i, c in enumerate(contents) if selfcompact.TASK_MARKER in c)
        si = next(i for i, c in enumerate(contents) if selfcompact.SUMMARY_MARKER in c)
        self.assertLess(ti, si)                                          # task leads, rollup follows

    def test_task_survives_rounds_despite_impoverished_summary(self):
        task = "Resolve an Ada Handle to a Cardano address via api.handle.me"
        state = CompactState()
        for n in (40, 60, 90):   # summarizer returns a stale, task-less one-liner every round
            out, state, applied = compact(_msgs(n), lambda mm: "mocked requests.get in tests", state,
                                          pinned_task=task, **_KW)
            self.assertTrue(applied)
            self.assertTrue(any(task in str(x.get("content")) for x in out))   # never lost

    def test_no_pinned_task_no_header(self):
        out, _, applied = compact(_msgs(40), lambda mm: "ROLLUP", CompactState(), **_KW)
        self.assertTrue(applied)
        self.assertFalse(any(selfcompact.TASK_MARKER in str(x.get("content")) for x in out))

    def test_huge_task_is_kept_verbatim(self):
        # The pinned task is the north star on every compacted turn — it is NEVER clipped. The
        # summarizer's own request passes through the context floor, which is the one window-aware
        # place truncation may happen; a per-site clip here would be a lie the model can't detect.
        out, _, _ = compact(_msgs(40), lambda mm: "R", CompactState(), pinned_task="Z" * 5000, **_KW)
        header = next(str(x["content"]) for x in out if selfcompact.TASK_MARKER in str(x.get("content")))
        self.assertEqual(header.count("Z"), 5000)   # full task body, no clip


class EditSteerNotFossilizedTests(unittest.TestCase):
    """THE ROLLUP FOSSILIZED CRIA'S OWN WHOLE-FILE STEER (measured: 27 of 295 rollups). The
    edit-recovery steer's body is an "EXACT current content on disk" snapshot that goes stale by
    design; fed whole into the summarizer input, a weak model preserves it verbatim — one prompt
    (0728-m14 call 0281) carried TWO conflicting "EXACT content" claims, the rollup's stale copy
    beside the live re-injection. In summarizer input the steer is its HEADLINE only."""

    def test_edit_steer_body_is_headlined_in_summarizer_input(self):
        from cria.selfcompact import msg_digest
        steer = ("⟦ctx:edit⟧ test_x.py — you have failed to edit this file 5 times — STOP.\n"
                 "import pytest\nSTALE_CONTENT_LINE_1\nSTALE_CONTENT_LINE_2\n")
        out = msg_digest({"role": "tool", "content": steer})
        self.assertIn("failed to edit this file 5 times", out)   # the EVENT survives
        self.assertNotIn("STALE_CONTENT_LINE_1", out)            # the perishable payload does not

    def test_ordinary_tool_results_pass_whole(self):
        from cria.selfcompact import msg_digest
        result = "Chunk ID: abc\nline1\nline2"
        self.assertEqual(msg_digest({"role": "tool", "content": result}), result)

    def test_marker_literal_stays_in_sync_with_editrecovery(self):
        from cria.editrecovery import EDIT_MARK
        from cria.selfcompact import _EDIT_MARK
        self.assertEqual(EDIT_MARK, _EDIT_MARK)


class CompactedViewTests(unittest.TestCase):
    """Operator's compaction design (run 0728-m14, a 61K post-compaction prompt carrying one file's
    content SIX times): the compacted view carries what EXISTS — a files list — not the bytes; only
    the LAST tool call keeps its full arguments; the rollup must be a summary, not an echo of
    cria's own serialization frame."""

    def _write_call(self, path, content, cid="w1"):
        import json as j
        return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": path, "content": content})}}]}

    def test_frame_echo_lines_are_stripped_from_the_rollup(self):
        from cria.selfcompact import strip_frame_echo
        echo = ("The coder wrote the resolver and ran the tests.\n"
                "tool: Chunk ID: 0f2436\n"
                "Wall time: 0.5630 seconds\n"
                "assistant: <think>\n"
                "user: ⟦ctx:edit⟧ stale stuff\n"
                "Tests currently fail on the mock shape.")
        out = strip_frame_echo(echo)
        self.assertIn("wrote the resolver", out)
        self.assertIn("Tests currently fail", out)
        self.assertNotIn("Chunk ID", out)
        self.assertNotIn("Wall time", out)
        self.assertNotIn("⟦ctx:edit⟧", out)

    def test_all_echo_summary_comes_back_empty_so_compact_fails_safe(self):
        from cria.selfcompact import strip_frame_echo
        self.assertEqual(strip_frame_echo("tool: Chunk ID: x\nassistant: did things\n"), "")

    def test_older_write_args_become_on_disk_references_last_kept_whole(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        big = "x = 1\n" * 200                     # >400 chars
        from cria.writeproxy import _WROTE
        msgs = [self._write_call("old.py", big, "w1"),
                {"role": "tool", "tool_call_id": "w1", "content": _WROTE + " old.py"},
                self._write_call("new.py", big, "w2")]
        out = stub_old_write_args(msgs)
        old_args = j.loads(out[0]["tool_calls"][0]["function"]["arguments"])
        new_args = j.loads(out[2]["tool_calls"][0]["function"]["arguments"])
        self.assertIn("on disk at old.py", old_args["content"])   # older write → reference
        self.assertIn("read_file", old_args["content"])
        self.assertEqual(new_args["content"], big)                # the LAST tool call keeps content
        self.assertEqual(msgs[0]["tool_calls"][0]["function"]["arguments"],
                         j.dumps({"path": "old.py", "content": big}))  # originals never mutated

    def test_a_refused_write_is_never_claimed_to_be_on_disk(self):
        """Rule 5b. Walked on mellum2 1786196176: call 0182's REFUSED new_string was elided as
        'this exact content is on disk', two reasoner prompts repeated the claim, and the 0144
        steer told the coder the fix had landed — it believed that for ~30 calls."""
        import json as j
        from cria.selfcompact import stub_old_write_args
        from cria import editrecovery
        big = "x = 1\n" * 200
        msgs = [self._write_call("f.py", big, "e1"),
                {"role": "tool", "tool_call_id": "e1",
                 "content": editrecovery.EDITFAIL + "eyJtb2RlIjogIndvdWxkX2JyZWFrIn0="},
                self._write_call("new.py", big, "w2")]
        out = stub_old_write_args(msgs)
        stub = j.loads(out[0]["tool_calls"][0]["function"]["arguments"])["content"]
        self.assertIn("REFUSED", stub)
        self.assertIn("never reached disk", stub)
        self.assertNotIn("on disk at", stub)

    def test_a_write_with_no_paired_result_keeps_its_content(self):
        # no result in the span → cria cannot claim landed OR refused; the full text stays
        import json as j
        from cria.selfcompact import stub_old_write_args
        big = "x = 1\n" * 200
        msgs = [self._write_call("f.py", big, "orphan"),
                self._write_call("new.py", big, "w2")]
        out = stub_old_write_args(msgs)
        self.assertEqual(j.loads(out[0]["tool_calls"][0]["function"]["arguments"])["content"], big)

    def test_stub_head_matches_writeproxys_confirm_token(self):
        # the landed/refused split keys on writeproxy's confirm head — they must never drift apart
        from cria import selfcompact, writeproxy
        self.assertEqual(selfcompact._WROTE_HEAD, writeproxy._WROTE)

    def test_the_model_facing_confirm_counts_as_landed_too(self):
        # transcripts carry the RENDERED confirm ("Wrote t.py"), not the raw heredoc token
        from cria import selfcompact
        self.assertTrue(selfcompact.write_landed("Wrote t.py"))
        self.assertTrue(selfcompact.write_landed("⟦ctx:wrote⟧ t.py"))
        self.assertFalse(selfcompact.write_landed("⟦ctx:edit⟧ t.py — your old_string is not an exact match"))
        self.assertFalse(selfcompact.write_landed("⟦ctx:denied⟧ that write left the workspace"))

    def test_tool_results_are_never_touched(self):
        from cria.selfcompact import stub_old_write_args
        big_read = "line\n" * 500
        msgs = [{"role": "tool", "tool_call_id": "r1", "content": big_read},
                self._write_call("new.py", "tiny")]
        out = stub_old_write_args(msgs)
        self.assertEqual(out[0]["content"], big_read)             # model-READ content: untouched

    def test_compacted_view_carries_exactly_one_fresh_files_list(self):
        from cria.selfcompact import CompactState, FILES_MARKER, compact
        pad = "words " * 60
        msgs = ([{"role": "system", "content": "sys"}]
                + [{"role": "user", "content": f"{FILES_MARKER} stale list"}]
                + [{"role": "user", "content": f"turn {i}: {pad}"} for i in range(40)])
        out, _, applied = compact(msgs, lambda mm: "did early work", CompactState(),
                                  trigger_tokens=100, keep_tail_tokens=80,
                                  pinned_task="build it",
                                  files_list=f"{FILES_MARKER} FRESH\n  a.py (10 B)")
        self.assertTrue(applied)
        lists = [m for m in out if str(m.get("content", "")).lstrip().startswith(FILES_MARKER)]
        self.assertEqual(len(lists), 1)                           # stale copy filtered
        self.assertIn("FRESH", lists[0]["content"])


class RollingSummaryTests(unittest.TestCase):
    """THE SUMMARY IS TRULY ROLLING (operator: a single replacing summary budget for a whole
    session's folded history is "ridiculously small" — and re-summarizing everything every round
    cost 13+ min at 27B speeds). Each round summarizes only the NEW band and APPENDS; earlier
    increments are never re-generated, and the total summary grows with the session."""

    def _msgs(self, n, tag):
        pad = "words " * 40
        return [{"role": "user", "content": f"{tag} turn {i}: {pad}"} for i in range(n)]

    def test_second_round_summarizes_only_the_new_band_and_appends(self):
        from cria.selfcompact import CompactState, compact
        seen = []

        def summ(mm):
            seen.append([m["content"][:12] for m in mm])
            return f"summary#{len(seen)}"

        msgs = [{"role": "system", "content": "sys"}] + self._msgs(30, "early")
        out, st, applied = compact(msgs, summ, CompactState(),
                                   trigger_tokens=100, keep_tail_tokens=60, pinned_task="t")
        self.assertTrue(applied)
        self.assertEqual(st.summary, "summary#1")
        # session grows: the SAME raw history plus new turns (the harness resends raw turns)
        msgs2 = msgs + self._msgs(30, "late")
        out2, st2, applied2 = compact(msgs2, summ, st,
                                      trigger_tokens=100, keep_tail_tokens=60, pinned_task="t",
                                      recompact_tokens=100)   # cross the re-summarize throttle
        self.assertTrue(applied2)
        self.assertEqual(st2.summary, "summary#1\n\nsummary#2")   # APPENDED, not replaced
        self.assertTrue(all(c.startswith("late") for c in seen[1]),
                        f"round 2 must see ONLY the new band, saw: {seen[1][:3]}...")

    def test_lost_state_falls_back_to_the_whole_middle(self):
        from cria.selfcompact import CompactState, compact
        seen = []

        def summ(mm):
            seen.append(len(mm))
            return "whole"

        msgs = [{"role": "system", "content": "sys"}] + self._msgs(30, "x")
        # covered index beyond the list = unusable state → whole-middle fallback
        out, st, applied = compact(msgs, summ, CompactState(summary="old", covered=9999),
                                   trigger_tokens=100, keep_tail_tokens=60, pinned_task="t")
        self.assertTrue(applied)
        self.assertEqual(st.summary, "whole")                     # replaced, not appended to stale


class SummaryRefoldTests(unittest.TestCase):
    """THE ACCUMULATED SUMMARY IS ITSELF BOUNDED (operator: append-only just moves the unbounded
    growth into the summary — it would eventually overtake the window, and the rollup is anchor-
    protected so nothing else ever shrinks it). When the accumulated increments cross REFOLD_TOKENS,
    the summary is folded ONCE by ``refold`` — deliberately rare, so degradation stays a handful of
    generations per session, never the every-round compounding the old rollup-of-a-rollup fear was
    about. A failed refold keeps the un-folded text: too long beats gone."""

    def _msgs(self, n, tag):
        pad = "words " * 40
        return [{"role": "user", "content": f"{tag} turn {i}: {pad}"} for i in range(n)]

    def test_a_summary_past_the_threshold_is_refolded_once(self):
        from cria.selfcompact import CompactState, compact
        big_summary = "earlier facts. " * 400          # ≈ 1500 tokens of prior increments
        msgs = ([{"role": "system", "content": "sys"}] + self._msgs(10, "early")
                + self._msgs(40, "new"))
        out, st, applied = compact(
            msgs, lambda mm: "increment", CompactState(summary=big_summary, covered=11),
            trigger_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
            refold=lambda text: "FOLDED: " + text[:20], refold_tokens=800)
        self.assertTrue(applied)
        self.assertTrue(st.summary.startswith("FOLDED:"))          # folded, not just appended
        self.assertLess(len(st.summary), len(big_summary))

    def test_below_threshold_no_refold(self):
        from cria.selfcompact import CompactState, compact
        calls = []
        msgs = ([{"role": "system", "content": "sys"}] + self._msgs(10, "early")
                + self._msgs(40, "new"))
        out, st, applied = compact(
            msgs, lambda mm: "increment", CompactState(summary="small prior", covered=11),
            trigger_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
            refold=lambda text: calls.append(1) or "FOLDED", refold_tokens=6000)
        self.assertTrue(applied)
        self.assertEqual(calls, [])                                # rare by design
        self.assertIn("small prior", st.summary)
        self.assertIn("increment", st.summary)

    def test_failed_refold_keeps_the_unfolded_summary(self):
        from cria.selfcompact import CompactState, compact
        big = "facts. " * 500
        msgs = ([{"role": "system", "content": "sys"}] + self._msgs(10, "early")
                + self._msgs(40, "new"))
        out, st, applied = compact(
            msgs, lambda mm: "increment", CompactState(summary=big, covered=11),
            trigger_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
            refold=lambda text: "", refold_tokens=800)             # refold model failed
        self.assertTrue(applied)
        self.assertIn("increment", st.summary)                     # too long beats gone
        self.assertIn("facts.", st.summary)


class EmptyRollupHeaderTests(unittest.TestCase):
    """A rollup header with nothing under it tells the coder it is reading a summary of its earlier
    turns — and to prefer the disk where the summary disagrees — over an empty body. The existing
    guard covers a compactor that ANSWERED with nothing; this is the other way in."""

    @staticmethod
    def _anchored(n):
        big = selfcompact._SPEC_ROUTES_MARKER + " /handles/{handle} " + "x " * 400
        return ([{"role": "system", "content": "sys"}]
                + [{"role": "user", "content": big} for _ in range(n)])

    def test_nothing_summarizable_ships_no_rollup_header(self):
        calls = []

        def summarize(ms):
            calls.append(ms)
            return "unreachable"

        out, state, applied = selfcompact.compact(
            self._anchored(4), summarize, selfcompact.CompactState(),
            pinned_task="do the thing", force=True)
        self.assertEqual(calls, [])                 # every message was anchored — nothing to fold
        self.assertEqual(state.summary, "")
        headers = [m for m in out
                   if (m.get("content") or "").startswith(selfcompact.SUMMARY_MARKER)]
        self.assertEqual(headers, [], "an empty ⟦ctx:rollup⟧ header was shipped")
        self.assertTrue(applied)                    # the tail still shrank; that part is real

    def test_a_real_summary_still_gets_its_header(self):
        msgs = ([{"role": "system", "content": "sys"}]
                + [{"role": "user", "content": "step " + "y " * 400} for _ in range(4)])
        out, state, _ = selfcompact.compact(
            msgs, lambda ms: "Built the resolver.", selfcompact.CompactState(),
            pinned_task="do the thing", force=True)
        self.assertEqual(state.summary, "Built the resolver.")
        self.assertTrue(any((m.get("content") or "").startswith(selfcompact.SUMMARY_MARKER)
                            for m in out))


if __name__ == "__main__":
    unittest.main()
