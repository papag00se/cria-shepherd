import unittest

from cria import selfcompact
from cria.selfcompact import CompactState, compact

# Small token budgets so tiny fixtures exercise the real token paths. boundary_keep_tail_tokens matches
# keep_tail here so the existing force tests behave as before; the boundary-vs-trigger test sets its own.
_KW = dict(room_tokens=100, keep_tail_tokens=30, recompact_tokens=20, boundary_keep_tail_tokens=30)


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
                                  room_tokens=100, keep_tail_tokens=120, recompact_tokens=20, force=True)
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
                                          room_tokens=100, keep_tail_tokens=120, recompact_tokens=20)
            self.assertFalse(applied, f"force={force}")
            self.assertEqual(out, m, f"force={force}")     # every turn kept VERBATIM — the floor sizes it
            self.assertEqual(state.summary, "")            # and no empty summary is latched into the state

    def test_boundary_pins_the_task_so_the_fold_cannot_lose_it(self):
        # A boundary keeps no tail, so the task MUST be pinned or it folds away. With pinned_task set, the
        # ⟦ctx:task⟧ anchor survives verbatim even as all the work folds.
        task = "Resolve an Ada Handle to its Cardano address via api.handle.me, with tests and a README"
        m = _msgs(30)
        out, _, applied = compact(m, lambda mm: "ROLLUP", CompactState(), pinned_task=task,
                                  room_tokens=100, keep_tail_tokens=120, recompact_tokens=20, force=True)
        self.assertTrue(applied)
        self.assertTrue(any(task in str(x.get("content")) for x in out))           # task survives the fold

    def test_boundary_folds_the_completed_step_not_just_lowers_the_trigger(self):
        # THE FIX: at a step boundary the finished step's work must FOLD, not linger in the working-set tail.
        # A boundary keeps only boundary_keep_tail (small); a size-trigger compaction keeps the full tail. So
        # the boundary view is LEANER — the ~14KB that grew between step 1 and step 2 rolls up instead.
        m = _msgs(60)  # ~360 tokens
        kw = dict(room_tokens=100, keep_tail_tokens=120, recompact_tokens=20, boundary_keep_tail_tokens=24)
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
        from cria import bodykeys, denial
        out = msg_digest({"role": "tool", "content": steer, bodykeys.RESULT_OUTCOME: denial.UNAPPLIED})
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
        msgs = [self._write_call("old.py", big, "w1"),
                {"role": "tool", "tool_call_id": "w1", "content": "Wrote old.py", "cria_result_outcome": "landed"},
                self._write_call("new.py", big, "w2")]
        out = stub_old_write_args(msgs)
        old_args = j.loads(out[0]["tool_calls"][0]["function"]["arguments"])
        new_args = j.loads(out[2]["tool_calls"][0]["function"]["arguments"])
        # THE PAYLOAD LEAVES; the sentence about it is said in the turn's own prose, not in the
        # slot a file body occupies. (The stub used to replace the argument in place, and models
        # read it as content and wrote it back — see ThePointerIsNeverInTheContentSlotTests.)
        self.assertNotIn("content", old_args)
        self.assertIn("on disk at old.py", out[0]["content"])      # older write → reference
        self.assertIn("read_file", out[0]["content"])
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
                # the edit program's own typed `unapplied` record, as `represent_inbound` hands it on
                {"role": "tool", "tool_call_id": "e1", "cria_result_outcome": "unapplied",
                 "content": editrecovery.EDITFAIL + "eyJtb2RlIjogIndvdWxkX2JyZWFrIn0="},
                self._write_call("new.py", big, "w2")]
        out = stub_old_write_args(msgs)
        # CHANGED 2026-08-26: the bytes STAY. The 5b incident this test was written for was the
        # CLAIM — "this exact content is on disk" about a write that was refused — not the presence
        # of the content. A refused write's payload exists nowhere else, and deleting it is rule 5's
        # own subject; the note beside the call is what carries the truth about it.
        self.assertIn("content", j.loads(out[0]["tool_calls"][0]["function"]["arguments"]))
        stub = out[0]["content"]
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

    def test_the_stub_keys_on_the_typed_landed_fact_never_on_confirmation_wording(self):
        # the landed/refused split reads `denial.landed` (the write program's own typed record, stamped on the result by
        # `represent_inbound`); the rendered confirm and the raw tag are wording any command can print
        from cria import denial, selfcompact
        call = {"role": "assistant", "tool_calls": [{"id": "w1", "type": "function", "function": {
            "name": "write_file", "arguments": "{}"}}]}
        # WORDING PROVES NOTHING IN EITHER DIRECTION: a result that merely says "Wrote t.py" / carries the retired confirmation tag /
        # reads like an edit refusal is UNKNOWN — no entry at all (neither landed nor refused), so no claim is stamped on the call.
        for text in ("Wrote t.py", "⟦ctx:wrote⟧ t.py", "⟦ctx:edit⟧ t.py — your old_string is not an exact match"):
            self.assertEqual(selfcompact._write_outcomes([call, {"role": "tool", "tool_call_id": "w1", "content": text}]), {})
        landed = {"role": "tool", "tool_call_id": "w1", "content": "anything", "cria_result_outcome": denial.LANDED}
        self.assertEqual(selfcompact._write_outcomes([call, landed]), {"w1": True})
        for proven in (denial.REFUSED, denial.UNAPPLIED):                      # cria PROVED nothing changed
            self.assertEqual(selfcompact._write_outcomes([call, {"role": "tool", "tool_call_id": "w1", "content": "x",
                                                                  "cria_result_outcome": proven}]), {"w1": False})
        for unproven in (denial.UNCERTAIN, denial.UNKNOWN):                    # the program could not tell / could not be proven
            self.assertEqual(selfcompact._write_outcomes([call, {"role": "tool", "tool_call_id": "w1", "content": "x",
                                                                  "cria_result_outcome": unproven}]), {})

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
                                  room_tokens=100, keep_tail_tokens=80,
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
            # The whole label, not its first 12 characters: "early turn 2" is a prefix of BOTH
            # "early turn 2:" and "early turn 29:", which made the old capture ambiguous exactly
            # where the band boundary sits.
            seen.append([m["content"].split(":")[0] for m in mm])
            return f"summary#{len(seen)}"

        msgs = [{"role": "system", "content": "sys"}] + self._msgs(30, "early")
        out, st, applied = compact(msgs, summ, CompactState(),
                                   room_tokens=100, keep_tail_tokens=60, pinned_task="t")
        self.assertTrue(applied)
        self.assertEqual(st.summary, "summary#1")
        # session grows: the SAME raw history plus new turns (the harness resends raw turns)
        msgs2 = msgs + self._msgs(30, "late")
        out2, st2, applied2 = compact(msgs2, summ, st,
                                      room_tokens=100, keep_tail_tokens=60, pinned_task="t",
                                      recompact_tokens=100)   # cross the re-summarize throttle
        self.assertTrue(applied2)
        self.assertEqual(st2.summary, "summary#1\n\nsummary#2")   # APPENDED, not replaced
        # ONLY THE NEW BAND — tested as the property, not as a string prefix. It used to assert
        # every round-2 turn began "late", which held only because round 1 folded EVERY message
        # including the newest: `_tail_start` returned len(messages) for this very fixture, so the
        # coder was handed a rollup and nothing verbatim at all. The tail now keeps the turn the
        # model is answering, so the boundary sits one message earlier — and what matters is
        # unchanged: round 2 re-summarises nothing round 1 already covered.
        self.assertFalse(set(seen[0]) & set(seen[1]),
                         f"round 2 re-summarized turns round 1 had covered: {seen[1][:3]}...")
        self.assertTrue(any(c.startswith("late") for c in seen[1]), "round 2 saw none of the new turns")

    def test_lost_state_falls_back_to_the_whole_middle(self):
        from cria.selfcompact import CompactState, compact
        seen = []

        def summ(mm):
            seen.append(len(mm))
            return "whole"

        msgs = [{"role": "system", "content": "sys"}] + self._msgs(30, "x")
        # covered index beyond the list = unusable state → whole-middle fallback
        out, st, applied = compact(msgs, summ, CompactState(summary="old", covered=9999),
                                   room_tokens=100, keep_tail_tokens=60, pinned_task="t")
        self.assertTrue(applied)
        self.assertEqual(st.summary, "whole")                     # replaced, not appended to stale


class RejectedSummaryThrottleTests(unittest.TestCase):
    """A rejected briefing is unchanged evidence, not permission to ask again next turn."""

    @staticmethod
    def _msgs(n, tag="old"):
        return ([{"role": "system", "content": "sys"}]
                + [{"role": "assistant", "content": f"{tag}-{i} " + "x" * 400}
                   for i in range(n)])

    def test_rejected_span_is_not_retried_until_a_new_band_accumulates(self):
        calls = []

        def reject(ms):
            calls.append([m.get("content") for m in ms])
            return ""

        msgs = self._msgs(12)
        out, state, applied = selfcompact.compact(
            msgs, reject, selfcompact.CompactState(), room_tokens=100,
            keep_tail_tokens=120, recompact_tokens=100, pinned_task="task")
        self.assertFalse(applied)
        self.assertIs(out, msgs)
        self.assertEqual(len(calls), 1)
        self.assertGreater(state.attempted, 0)

        # One tiny new turn is not new evidence worth regenerating and re-judging the same briefing.
        slightly_newer = msgs + [{"role": "assistant", "content": "tiny update"}]
        out2, state2, applied2 = selfcompact.compact(
            slightly_newer, reject, state, room_tokens=100,
            keep_tail_tokens=120, recompact_tokens=100, pinned_task="task")
        self.assertFalse(applied2)
        self.assertIs(out2, slightly_newer)
        self.assertEqual(len(calls), 1)

        # A real new band reaches the existing recompact threshold and earns one fresh attempt.
        much_newer = slightly_newer + self._msgs(6, "new")[1:]
        _, state3, _ = selfcompact.compact(
            much_newer, reject, state2, room_tokens=100,
            keep_tail_tokens=120, recompact_tokens=100, pinned_task="task")
        self.assertEqual(len(calls), 2)
        self.assertGreater(state3.attempted, state2.attempted)


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
            room_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
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
            room_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
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
            room_tokens=100, keep_tail_tokens=60, recompact_tokens=100, pinned_task="t",
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



class ThePointerIsNeverInTheContentSlotTests(unittest.TestCase):
    """cria's own sentence sat where a file body sits, and models wrote it to disk.

    `_stub_write_args` replaced an older write's payload IN PLACE with
    `[elided 8031 chars — an EARLIER version of X, replaced by a later write…]`. That is the exact
    position a file's content occupies in a tool call, and weak models read it as content.

    `focustrim` records the incident and the ruling. feed-pipeline-java x qwen35, 2026-08-19, call
    0095: the coder emitted `write_file` with cria's stub as the content; javac answered
    `Importer.java:[1,20] illegal character: '\u2014'` — the em dash in cria's sentence — and the
    model's own reasoning read *"The file got corrupted with placeholder text."* A 357-line file
    became one line of cria's note. Reproduced across five more sessions and five languages
    (`20260819T122006` rust ×3, `20260819T063347` node, `20260819T012527` python,
    `20260817T200939` ruby). Operator, 2026-08-19: *"There is not supposed to be any elision. It's
    all or nothing."* `focustrim` was fixed by removing the call; this owner was not.

    The payload now leaves and the sentence is said in the assistant turn's own prose, beside the
    call — the same place `focustrim` puts its note, and a place no file body ever occupies."""

    def _msgs(self, big):
        import json as j
        call = {"role": "assistant", "tool_calls": [{"id": "w1", "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": "lib/app.rb", "content": big})}}]}
        later = {"role": "assistant", "tool_calls": [{"id": "w2", "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": "other.rb", "content": big})}}]}
        return [call, {"role": "tool", "tool_call_id": "w1", "content": "Wrote lib/app.rb", "cria_result_outcome": "landed"}, later]

    def test_no_argument_slot_holds_a_sentence_cria_wrote(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        out = stub_old_write_args(self._msgs("x = 1\n" * 200))
        raw = out[0]["tool_calls"][0]["function"]["arguments"]
        self.assertNotIn("elided", raw)
        self.assertNotIn("read_file", raw)
        self.assertNotIn("\u2014", raw)
        self.assertEqual(set(j.loads(raw)), {"path"})

    def test_what_cria_has_to_say_is_still_said(self):
        """Removal, not silence: the reader still learns the content is on disk and how to get it."""
        from cria.selfcompact import stub_old_write_args
        out = stub_old_write_args(self._msgs("x = 1\n" * 200))
        self.assertIn("lib/app.rb", out[0]["content"])
        self.assertIn("read_file", out[0]["content"])

    def test_an_existing_assistant_message_keeps_its_own_words(self):
        from cria.selfcompact import stub_old_write_args
        msgs = self._msgs("x = 1\n" * 200)
        msgs[0]["content"] = "Writing the shipping module now."
        out = stub_old_write_args(msgs)
        self.assertIn("Writing the shipping module now.", out[0]["content"])
        self.assertIn("lib/app.rb", out[0]["content"])

    def test_the_caller_s_messages_are_never_mutated(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        big = "x = 1\n" * 200
        msgs = self._msgs(big)
        stub_old_write_args(msgs)
        self.assertEqual(j.loads(msgs[0]["tool_calls"][0]["function"]["arguments"])["content"], big)


class TheStubClaimsOnlyWhatWasProvenTests(unittest.TestCase):
    """`stub_old_write_args` says one of three things about an older write: it LANDED (superseded / on disk), it was REFUSED (never
    reached disk), or NOTHING. The first two are claims about the world, so they may only come from cria's own typed proof
    (`denial.landed_call_ids` / `denial.unlanded_call_ids`, strictly paired). Unknown, cut, uncertain, ambiguous or merely
    worded evidence is the third case: the bytes stay and no claim is made.

    Incident: `_write_outcomes` mapped EVERY string result to `tid in landed_ids`, so all of those became False and the older
    write was stamped "this write was REFUSED … the content never reached disk" — a false fact about a write cria knew nothing about."""

    BIG = "x = 1\n" * 200

    @staticmethod
    def _call(path, content, cid):
        import json as j
        return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": path, "content": content})}}]}

    def _assert_no_claim(self, msgs):
        import json as j
        from cria.selfcompact import stub_old_write_args
        out = stub_old_write_args(msgs)
        args = j.loads(out[0]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args.get("content"), self.BIG)                      # the bytes are retained
        note = out[0].get("content") or ""
        for claim in ("REFUSED", "never reached disk", "on disk", "EARLIER version"):
            self.assertNotIn(claim, note)
        self.assertEqual(out[0]["tool_calls"], msgs[0]["tool_calls"])        # the call itself is untouched

    def test_unknown_cut_uncertain_and_worded_evidence_make_no_claim(self):
        from cria import denial
        from tests.resultshape import typed_result
        newest = [self._call("g.py", self.BIG, "w2")]
        cases = {
            "flat confirmation wording": typed_result("w1", "Wrote f.py"),
            "retired confirmation tag": typed_result("w1", "\u27e6ctx:wrote\u27e7 f.py"),
            "refusal-looking wording": typed_result("w1", "\u27e6ctx:denied\u27e7 Nothing was run \u2014 the write was refused"),
            "cria could not prove its own branch": typed_result("w1", "x", denial.UNKNOWN),
            "the program could not tell whether the target changed": typed_result("w1", "x", denial.UNCERTAIN),
        }
        for label, result in cases.items():
            with self.subTest(label):
                self._assert_no_claim([self._call("f.py", self.BIG, "w1"), result, *newest])

    def test_an_ambiguous_pairing_makes_no_claim_even_when_one_result_is_typed(self):
        from cria import denial
        from tests.resultshape import typed_result
        newest = [self._call("g.py", self.BIG, "w2")]
        # a second result for the same id: which call does the typed outcome answer? Unanswerable — so neither is believed.
        self._assert_no_claim([self._call("f.py", self.BIG, "w1"), typed_result("w1", "ok", denial.LANDED),
                               typed_result("w1", "ok", denial.REFUSED), *newest])
        # the same id issued twice
        self._assert_no_claim([self._call("f.py", self.BIG, "w1"), typed_result("w1", "ok", denial.LANDED),
                               self._call("h.py", self.BIG, "w1"), *newest])

    def test_genuine_producer_results_still_make_the_two_claims(self):
        """Real lowering, executed private programs, real typed representation — the positives the three-state split exists for."""
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            with open(os.path.join(cwd, "f.py"), "w") as fh:
                fh.write("print('real')\n" * 60)
            landed = genuine_call("write_file", {"path": "old.rb", "content": self.BIG}, "w1", cwd)
            refused = genuine_call("edit_file", {"path": "f.py", "old_string": "NOT THERE " * 80, "new_string": self.BIG}, "e1", cwd)
            newest = genuine_call("write_file", {"path": "old.rb", "content": self.BIG + "# v2\n"}, "w2", cwd)
        history = landed + refused + newest
        self.assertEqual(selfcompact._write_outcomes(history), {"w1": True, "e1": False, "w2": True})   # proven landed / proven unapplied
        out = stub_old_write_args(history)
        self.assertIn("EARLIER version of old.rb", out[0]["content"])         # proven landed, later replaced by a proven landed write
        self.assertNotIn("content", j.loads(out[0]["tool_calls"][0]["function"]["arguments"]))
        self.assertEqual(out[4]["tool_calls"], history[4]["tool_calls"])      # the newest write keeps its payload whole


class TheStubDescribesOnlyWhatLaterWritesProvablyDidTests(unittest.TestCase):
    """An older write that LANDED is described by what the LATER calls to the same path provably did to it.

    Incident (independent review, the §-final residual): the (since removed) `_last_write_index_by_path` advanced for EVERY attempted write, so a
    later write that was REFUSED, unanswered, uncertain or ambiguous still made the earlier real file "an EARLIER version …
    replaced by a later write" and removed its payload from the view — a claim (and a deletion) the evidence does not support.
    And a later partial EDIT that landed does not replace the file: "replaced" would claim a whole replacement nobody proved."""

    BIG = "x = 1\n" * 200

    @staticmethod
    def _call(path, content, cid, name="write_file"):
        import json as j
        args = {"path": path, "content": content} if name == "write_file" else {"path": path, "old_string": content, "new_string": "y" * 500}
        return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": j.dumps(args)}}]}

    def _older_then(self, *later, name="write_file"):
        """older landed `a.rb` write, then the given later messages (the LAST one is the live working set)."""
        from tests.resultshape import typed_result
        return [self._call("a.rb", self.BIG, "w1"), typed_result("w1", "Wrote a.rb", "landed"), *later]

    def _view(self, msgs):
        import json as j
        from cria.selfcompact import stub_old_write_args
        out = stub_old_write_args(msgs)
        return out, j.loads(out[0]["tool_calls"][0]["function"]["arguments"]), out[0].get("content") or ""

    def _assert_held(self, msgs):
        out, args, note = self._view(msgs)
        self.assertEqual(args.get("content"), self.BIG)                      # the real bytes are NOT removed…
        for claim in ("EARLIER version", "replaced by a later write", "changed by a later edit", "on disk", "REFUSED"):
            self.assertNotIn(claim, note)                                    # …and nothing is claimed about them
        self.assertEqual(out[-2:], msgs[-2:])                                # the live working set is untouched

    def test_a_later_write_with_unproven_evidence_neither_replaces_nor_erases_the_earlier_file(self):
        from cria import denial
        from tests.resultshape import typed_result
        later = self._call("a.rb", self.BIG + "# v2\n", "w2")
        cases = {
            "unanswered": [later],
            "worded confirmation": [later, typed_result("w2", "Wrote a.rb")],
            "refusal-looking wording": [later, typed_result("w2", "\u27e6ctx:denied\u27e7 Nothing was run")],
            "unknown": [later, typed_result("w2", "x", denial.UNKNOWN)],
            "uncertain": [later, typed_result("w2", "x", denial.UNCERTAIN)],
            "ambiguous (two results)": [later, typed_result("w2", "x", denial.LANDED), typed_result("w2", "x", denial.REFUSED)],
            "ambiguous (id reused)": [later, typed_result("w2", "x", denial.LANDED), self._call("b.rb", self.BIG, "w2")],
        }
        for label, tail in cases.items():
            with self.subTest(label):
                self._assert_held(self._older_then(*tail))

    def test_a_later_write_proven_not_to_have_changed_anything_leaves_the_earlier_file_current(self):
        from cria import denial
        from tests.resultshape import typed_result
        for proven in (denial.REFUSED, denial.UNAPPLIED):
            with self.subTest(proven):
                out, args, note = self._view(self._older_then(self._call("a.rb", self.BIG + "# v2\n", "w2"),
                                                              typed_result("w2", "no", proven)))
                self.assertIn("this exact content is on disk at a.rb", note)  # still what is on disk
                self.assertNotIn("EARLIER version", note)
                self.assertNotIn("content", args)

    def test_a_later_whole_file_write_that_landed_replaces_it(self):
        from tests.resultshape import typed_result
        out, args, note = self._view(self._older_then(self._call("a.rb", self.BIG + "# v2\n", "w2"),
                                                      typed_result("w2", "Wrote a.rb", "landed")))
        self.assertIn("EARLIER version of a.rb, replaced by a later write", note)
        self.assertNotIn("content", args)

    def test_a_later_partial_edit_that_landed_changed_it_in_part_and_is_not_called_a_replacement(self):
        from tests.resultshape import typed_result
        out, args, note = self._view(self._older_then(self._call("a.rb", "x = 1\n" * 100, "e2", name="edit_file"),
                                                      typed_result("e2", "edited", "landed")))
        self.assertIn("EARLIER version of a.rb, since changed by a later edit", note)
        self.assertNotIn("replaced by a later write", note)
        self.assertNotIn("content", args)

    def test_an_unproven_attempt_after_a_landed_whole_write_does_not_undo_the_proven_replacement(self):
        from tests.resultshape import typed_result
        out, args, note = self._view(self._older_then(self._call("a.rb", self.BIG + "# v2\n", "w2"),
                                                      typed_result("w2", "Wrote a.rb", "landed"),
                                                      self._call("a.rb", self.BIG + "# v3\n", "w3")))   # in flight, unanswered
        self.assertIn("replaced by a later write", note)

    def test_genuine_producer_results_drive_the_same_claims(self):
        """Real lowering, executed programs, real typed representation: refused/unapplied → still current; landed edit → "changed"."""
        import os
        import tempfile
        from tests.resultshape import genuine_call
        content = "# head\n" + self.BIG + "UNIQUE_MARK\n"
        with tempfile.TemporaryDirectory() as cwd:
            first = genuine_call("write_file", {"path": "a.rb", "content": content}, "w1", cwd)
            miss = genuine_call("edit_file", {"path": "a.rb", "old_string": "NOT THERE " * 40, "new_string": "z" * 500}, "e2", cwd)
            hit = genuine_call("edit_file", {"path": "a.rb", "old_string": "UNIQUE_MARK", "new_string": "UNIQUE_DONE"}, "e3", cwd)
            with open(os.path.join(cwd, "a.rb")) as fh:
                self.assertIn("UNIQUE_DONE", fh.read())
        from cria.selfcompact import stub_old_write_args
        after_miss = stub_old_write_args(first + miss + [self._call("z.rb", self.BIG, "w9")])
        self.assertIn("this exact content is on disk at a.rb", after_miss[0]["content"])        # a missed edit changed nothing
        self.assertNotIn("EARLIER version", after_miss[0]["content"])
        after_hit = stub_old_write_args(first + miss + hit + [self._call("z.rb", self.BIG, "w9")])
        self.assertIn("since changed by a later edit", after_hit[0]["content"])                 # a landed edit changed part of it
        self.assertNotIn("replaced by a later write", after_hit[0]["content"])


class TheStubNeverInventsAnOrderOrASecondFileTests(unittest.TestCase):
    """Genuine-producer witnesses (real lowering, executed private programs, real typed representation) for two ways a later write
    was mistaken for "the newer one": calls in ONE message (indexed by message, both looked current) and two SPELLINGS of one file
    (keyed by raw string, the older looked current though the disk held the newer).

    Calls in one message are dispatched together and may run concurrently; cria does not know their completion order and does not
    invent one. And one file is one file whether it was named relatively or absolutely (the shared `focustrim._path_identity`)."""

    A = "# version A\n" + "a = 1\n" * 120
    B = "# version B\n" + "b = 2\n" * 120

    @staticmethod
    def _one_message(*pairs):
        """one assistant message carrying every pair's call, followed by each pair's typed result."""
        calls = [c for p in pairs for c in p[0]["tool_calls"]]
        return [{"role": "assistant", "tool_calls": calls}, *[p[1] for p in pairs]]

    def _later(self):
        import json as j
        return {"role": "assistant", "tool_calls": [{"id": "z1", "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": "b.rb", "content": "z = 0\n" * 200})}}]}

    def test_two_landed_writes_in_one_message_are_neither_called_current_nor_removed(self):
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            w1 = genuine_call("write_file", {"path": "a.rb", "content": self.A}, "w1", cwd)
            w2 = genuine_call("write_file", {"path": "a.rb", "content": self.B}, "w2", cwd)
            with open(os.path.join(cwd, "a.rb")) as fh:
                self.assertEqual(fh.read(), self.B)                                  # one of them is on disk; the message cannot say which
        msgs = self._one_message(w1, w2) + [self._later()]
        out = stub_old_write_args(msgs)
        sent = [j.loads(tc["function"]["arguments"]) for tc in out[0]["tool_calls"]]
        self.assertEqual([a["content"] for a in sent], [self.A, self.B])             # neither payload leaves the view
        note = out[0].get("content") or ""
        for claim in ("on disk", "EARLIER version", "replaced by a later write"):
            self.assertNotIn(claim, note)                                            # and no order is invented

    def test_a_later_message_with_a_landed_whole_write_settles_a_same_turn_pair(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        pair = [{"role": "assistant", "tool_calls": [
            {"id": "w1", "type": "function", "function": {"name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.A})}},
            {"id": "w2", "type": "function", "function": {"name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.B})}}]},
            typed_result("w1", "ok", "landed"), typed_result("w2", "ok", "landed")]
        final = [{"role": "assistant", "tool_calls": [{"id": "w3", "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.A + "# final\n"})}}]},
            typed_result("w3", "ok", "landed"), self._later()]
        out = stub_old_write_args(pair + final)
        self.assertEqual((out[0].get("content") or "").count("EARLIER version of a.rb, replaced by a later write"), 2)

    def test_a_same_turn_sibling_that_was_proven_not_to_change_anything_does_not_hold_the_other(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        msgs = [{"role": "assistant", "tool_calls": [
            {"id": "w1", "type": "function", "function": {"name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.A})}},
            {"id": "w2", "type": "function", "function": {"name": "edit_file", "arguments": j.dumps({"path": "a.rb", "old_string": "NOPE" * 30, "new_string": "y"})}}]},
            typed_result("w1", "ok", "landed"), typed_result("w2", "no", "unapplied"), self._later()]
        out = stub_old_write_args(msgs)
        self.assertIn("this exact content is on disk at a.rb", out[0]["content"])

    def test_an_unanswered_same_turn_sibling_holds_the_landed_write(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        msgs = [{"role": "assistant", "tool_calls": [
            {"id": "w1", "type": "function", "function": {"name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.A})}},
            {"id": "w2", "type": "function", "function": {"name": "write_file", "arguments": j.dumps({"path": "a.rb", "content": self.B})}}]},
            typed_result("w1", "ok", "landed"), self._later()]
        out = stub_old_write_args(msgs)
        self.assertEqual(j.loads(out[0]["tool_calls"][0]["function"]["arguments"])["content"], self.A)
        self.assertNotIn("on disk", out[0].get("content") or "")

    def test_a_relative_and_an_absolute_spelling_of_one_file_are_one_file(self):
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            older = genuine_call("write_file", {"path": "alias.rb", "content": self.A}, "w1", cwd)
            newer = genuine_call("write_file", {"path": os.path.join(cwd, "alias.rb"), "content": self.B}, "w2", cwd)
            with open(os.path.join(cwd, "alias.rb")) as fh:
                self.assertEqual(fh.read(), self.B)
        out = stub_old_write_args(older + newer + [self._later()])
        self.assertIn("EARLIER version of alias.rb, replaced by a later write", out[0]["content"])   # the older A is not "current"
        self.assertIn("this exact content is on disk at", out[2]["content"])                          # the newer B is
        self.assertNotIn("EARLIER version", out[2]["content"])


class TheStubWithholdsWhatAnUnresolvedAliasCouldHaveTouchedTests(unittest.TestCase):
    """A relative spelling that is a suffix of TWO absolute paths names a file cria cannot identify: the harness's cwd decides which
    (`focustrim._path_identity` refuses to fold it — "not folded" is UNKNOWN, never "a different file"). Such a write is never
    called current, and no write it could have overwritten is called current either unless something later proved it replaced."""

    @staticmethod
    def _tw(call_id, path, content, name="write_file"):
        import json as j
        args = {"path": path, "content": content} if name == "write_file" else {"path": path, "old_string": content, "new_string": "y"}
        return {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": j.dumps(args)}}]}

    @staticmethod
    def _held(note):
        return not any(claim in note for claim in ("on disk", "EARLIER version", "replaced by a later write", "changed by a later edit", "REFUSED"))

    def test_a_real_relative_write_that_overwrote_one_of_two_candidate_files_is_not_called_current_or_superseded(self):
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        A, B, C = ("# A\n" + "a = 1\n" * 120, "# B\n" + "b = 2\n" * 120, "# C\n" + "c = 3\n" * 120)
        with tempfile.TemporaryDirectory() as root:
            root = os.path.realpath(root)
            s1, s2 = os.path.join(root, "s1"), os.path.join(root, "s2")
            os.mkdir(s1)
            os.mkdir(s2)
            first = genuine_call("write_file", {"path": os.path.join(s1, "alias.rb"), "content": A}, "w1", s1)
            second = genuine_call("write_file", {"path": os.path.join(s2, "alias.rb"), "content": B}, "w2", s2)
            rel = genuine_call("write_file", {"path": "alias.rb", "content": C}, "w3", s1)     # the harness cwd is s1: it overwrites s1/alias.rb
            with open(os.path.join(s1, "alias.rb")) as fh, open(os.path.join(s2, "alias.rb")) as other:
                self.assertEqual((fh.read(), other.read()), (C, B))                           # the real disk: A is gone, B stands
        live = self._tw("z1", "z.rb", "z = 0\n" * 200)
        out = stub_old_write_args(first + second + rel + [live])
        for index, body in ((0, A), (2, B), (4, C)):
            self.assertEqual(j.loads(out[index]["tool_calls"][0]["function"]["arguments"])["content"], body)   # every real payload stays
            self.assertTrue(self._held(out[index].get("content") or ""), out[index].get("content"))            # and none is claimed current / replaced

    def test_a_candidate_whose_result_was_cut_is_still_a_candidate_for_the_stub_too(self):
        """The same witness the focus trim was rejected on: s1/alias.rb = A landed; s2/alias.rb = B written for real but its first
        record arrived CUT (unknown); a real relative alias.rb run in s2 landed (disk: s1 = A, s2 = C). Nothing may be called
        current, replaced or removed — the unknown s2 write is part of the candidate universe, never filtered out for not landing."""
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        A, B, C = ("# A\n" + "a = 1\n" * 120, "# B\n" + "b = 2\n" * 120, "# C\n" + "c = 3\n" * 120)
        with tempfile.TemporaryDirectory() as root:
            root = os.path.realpath(root)
            s1, s2 = os.path.join(root, "s1"), os.path.join(root, "s2")
            os.mkdir(s1)
            os.mkdir(s2)
            first = genuine_call("write_file", {"path": os.path.join(s1, "alias.rb"), "content": A}, "w1", s1)
            second = genuine_call("write_file", {"path": os.path.join(s2, "alias.rb"), "content": B}, "w2", s2, cut_stdout=20)
            rel = genuine_call("write_file", {"path": "alias.rb", "content": C}, "w3", s2)
        out = stub_old_write_args(first + second + rel + [self._tw("z1", "z.rb", "z = 0\n" * 200)])
        for index, body in ((0, A), (2, B), (4, C)):
            self.assertEqual(j.loads(out[index]["tool_calls"][0]["function"]["arguments"])["content"], body)
            self.assertTrue(self._held(out[index].get("content") or ""), out[index].get("content"))

    def test_a_reused_call_id_makes_no_claim_about_either_occurrence(self):
        """Genuine producers: `a.rb`=A and `b.rb`=B share one call id, then a unique-id `a.rb`=C lands. Which result answers which call is
        unknowable for the shared id, so neither is called current or replaced, and nothing is removed; C (unique, newest) is untouched."""
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        A, B, C = ("# A\n" + "a = 1\n" * 120, "# B\n" + "b = 2\n" * 120, "# C\n" + "c = 3\n" * 120)
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            a = genuine_call("write_file", {"path": "a.rb", "content": A}, "dup", cwd)
            b = genuine_call("write_file", {"path": "b.rb", "content": B}, "dup", cwd)
            c = genuine_call("write_file", {"path": "a.rb", "content": C}, "u1", cwd)
        out = stub_old_write_args(a + b + c + [self._tw("z1", "z.rb", "z = 0\n" * 200)])
        for index, body in ((0, A), (2, B)):
            self.assertEqual(j.loads(out[index]["tool_calls"][0]["function"]["arguments"])["content"], body)
            self.assertTrue(self._held(out[index].get("content") or ""), out[index].get("content"))

    def test_a_write_answered_only_after_the_replacement_was_dispatched_is_not_called_replaced(self):
        """Dispatch order is not execution order: A's receipt arrives after C was already sent, so A may have run after C."""
        import json as j
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        A, C = "a = 1\n" * 120, "c = 3\n" * 120
        msgs = [self._tw("w1", "p.rb", A), self._tw("w2", "p.rb", C), typed_result("w2", "ok", "landed"),
                typed_result("w1", "ok", "landed"), self._tw("z1", "z.rb", "z = 0\n" * 200)]
        out = stub_old_write_args(msgs)
        self.assertEqual(j.loads(out[0]["tool_calls"][0]["function"]["arguments"])["content"], A)
        self.assertTrue(self._held(out[0].get("content") or ""))
        # control: answered BEFORE the replacement was dispatched -> replaced
        ordered = [self._tw("w1", "p.rb", A), typed_result("w1", "ok", "landed"), self._tw("w2", "p.rb", C),
                   typed_result("w2", "ok", "landed"), self._tw("z1", "z.rb", "z = 0\n" * 200)]
        self.assertIn("replaced by a later write", stub_old_write_args(ordered)[0]["content"])

    def test_an_unresolved_alias_that_was_proven_not_to_change_anything_holds_nothing(self):
        import json as j
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        A, B = "a = 1\n" * 120, "b = 2\n" * 120
        msgs = [self._tw("w1", "/r/s1/alias.rb", A), typed_result("w1", "ok", "landed"),
                self._tw("w2", "/r/s2/alias.rb", B), typed_result("w2", "ok", "landed"),
                self._tw("e3", "alias.rb", "NOPE" * 30, name="edit_file"), typed_result("e3", "no", "unapplied"),
                self._tw("z1", "z.rb", "z = 0\n" * 200)]
        out = stub_old_write_args(msgs)
        self.assertIn("this exact content is on disk at /r/s1/alias.rb", out[0]["content"])      # a missed edit changed nothing
        self.assertIn("this exact content is on disk at /r/s2/alias.rb", out[2]["content"])

    def test_a_later_proven_whole_write_to_a_resolved_file_still_supersedes_despite_an_unresolved_alias_elsewhere(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        body = "a = 1\n" * 120
        msgs = [self._tw("w1", "/r/s1/alias.rb", body), typed_result("w1", "ok", "landed"),
                self._tw("w2", "/r/s2/alias.rb", body), typed_result("w2", "ok", "landed"),
                self._tw("w3", "/r/s1/alias.rb", body + "# v2\n"), typed_result("w3", "ok", "landed"),
                self._tw("w4", "alias.rb", body + "# v3\n"), typed_result("w4", "ok", "landed"),
                self._tw("z1", "z.rb", "z = 0\n" * 200)]
        out = stub_old_write_args(msgs)
        self.assertIn("EARLIER version of /r/s1/alias.rb, replaced by a later write", out[0]["content"])   # w3 proved the replacement
        self.assertTrue(self._held(out[2].get("content") or ""))                                          # w2 could have been overwritten by w4
        self.assertTrue(self._held(out[4].get("content") or ""))
        self.assertTrue(self._held(out[6].get("content") or ""))


class TheStubNeverCallsAWriteCurrentWhileAnEarlierIssuedOneCouldStillFinishTests(unittest.TestCase):
    """Ordering is symmetric. Dispatch order is not execution order, so an EARLIER-issued write whose result has not arrived by the time a
    LATER write was dispatched may complete after it. Then the earlier one cannot be called replaced AND the later one cannot be called
    "what is on disk" — the earlier one may hold that title. Only results that arrived BEFORE the other call was dispatched order two calls.

    Incident (independent review, genuine producers): A dispatched first and finished LAST (disk = A); C dispatched second and landed in
    between. The view held A correctly but stubbed C as "this exact content is on disk" — the file held A."""

    A = "# A\n" + "a = 1\n" * 120
    C = "# C\n" + "c = 3\n" * 120

    @staticmethod
    def _call(cid, path, body):
        import json as j
        return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "write_file", "arguments": j.dumps({"path": path, "content": body})}}]}

    @staticmethod
    def _held(note):
        return not any(c in note for c in ("on disk", "EARLIER version", "replaced by a later write", "changed by a later edit", "REFUSED"))

    def _live(self):
        return self._call("z1", "z.rb", "z = 0\n" * 200)

    def test_genuine_earlier_dispatched_write_that_finishes_last_leaves_neither_claimed(self):
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            c = genuine_call("write_file", {"path": "p.rb", "content": self.C}, "pc", cwd)      # C EXECUTES first…
            a = genuine_call("write_file", {"path": "p.rb", "content": self.A}, "pa", cwd)      # …A last: the disk holds A
            with open(os.path.join(cwd, "p.rb")) as fh:
                self.assertEqual(fh.read(), self.A)
        msgs = [a[0], c[0], c[1], a[1], self._live()]                  # …but A was DISPATCHED first and answered after C landed
        out = stub_old_write_args(msgs)
        for index, body in ((0, self.A), (1, self.C)):
            self.assertEqual(j.loads(out[index]["tool_calls"][0]["function"]["arguments"])["content"], body)
            self.assertTrue(self._held(out[index].get("content") or ""), out[index].get("content"))

    def test_a_still_running_reply_received_before_the_later_dispatch_orders_nothing(self):
        """Genuine: A dispatched first and answered "Process running …" BEFORE C was sent; C landed; A then completed LAST (disk = A).
        The reply arrived but was not terminal, so A may still be executing: neither A nor C may be called current or replaced."""
        import json as j
        import os
        import tempfile
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import genuine_call
        with tempfile.TemporaryDirectory() as cwd:
            cwd = os.path.realpath(cwd)
            c = genuine_call("write_file", {"path": "p.rb", "content": self.C}, "pc", cwd)
            a = genuine_call("write_file", {"path": "p.rb", "content": self.A}, "pa", cwd, running=True)
            with open(os.path.join(cwd, "p.rb")) as fh:
                self.assertEqual(fh.read(), self.A)
        out = stub_old_write_args(a + c + [self._live()])
        for index, body in ((0, self.A), (2, self.C)):
            self.assertEqual(j.loads(out[index]["tool_calls"][0]["function"]["arguments"])["content"], body)
            self.assertTrue(self._held(out[index].get("content") or ""), out[index].get("content"))

    def test_unknown_uncertain_and_native_replies_before_the_later_dispatch_leave_it_unclaimed(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        for label, reply in (("unknown", typed_result("pa", "x", "unknown")), ("uncertain", typed_result("pa", "x", "uncertain")),
                             ("native", typed_result("pa", "ok"))):
            with self.subTest(label):
                msgs = [self._call("pa", "p.rb", self.A), reply, self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"),
                        self._live()]
                self.assertTrue(self._held(stub_old_write_args(msgs)[2].get("content") or ""))

    def test_sequential_completed_before_dispatch_is_still_ordered_and_current(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        msgs = [self._call("pa", "p.rb", self.A), typed_result("pa", "ok", "landed"),
                self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"), self._live()]
        out = stub_old_write_args(msgs)
        self.assertIn("EARLIER version of p.rb, replaced by a later write", out[0]["content"])
        self.assertIn("this exact content is on disk at p.rb", out[2]["content"])

    def test_an_overlapping_earlier_write_proven_to_change_nothing_does_not_unsettle_the_later_one(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        for proven in ("unapplied", "refused"):
            with self.subTest(proven):
                msgs = [self._call("pa", "p.rb", self.A), self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"),
                        typed_result("pa", "no", proven), self._live()]
                out = stub_old_write_args(msgs)
                self.assertIn("this exact content is on disk at p.rb", out[1]["content"])

    def test_an_unanswered_earlier_write_leaves_the_later_one_unclaimed(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        msgs = [self._call("pa", "p.rb", self.A), self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"), self._live()]
        out = stub_old_write_args(msgs)
        self.assertTrue(self._held(out[1].get("content") or ""))

    def test_an_earlier_write_with_an_ambiguous_id_leaves_the_later_one_unclaimed(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        msgs = [self._call("dup", "p.rb", self.A), self._call("dup", "q.rb", "q = 1\n" * 120),
                typed_result("dup", "ok", "landed"), self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"), self._live()]
        out = stub_old_write_args(msgs)
        self.assertTrue(self._held(out[3].get("content") or ""))          # which dup answered? unknowable: the earlier p.rb may still finish

    def test_a_result_under_call_id_is_ordered_by_the_same_positions(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result

        def alias(cid):
            m = typed_result(cid, "ok", "landed")
            m["call_id"] = m.pop("tool_call_id")
            return m
        settled = [self._call("pa", "p.rb", self.A), alias("pa"), self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"),
                   self._live()]
        self.assertIn("this exact content is on disk at p.rb", stub_old_write_args(settled)[2]["content"])
        overlapping = [self._call("pa", "p.rb", self.A), self._call("pc", "p.rb", self.C), typed_result("pc", "ok", "landed"),
                       alias("pa"), self._live()]
        self.assertTrue(self._held(stub_old_write_args(overlapping)[1].get("content") or ""))

    def test_an_earlier_unresolved_alias_still_running_leaves_a_candidate_file_unclaimed(self):
        from cria.selfcompact import stub_old_write_args
        from tests.resultshape import typed_result
        other = [self._call("o1", "/r/s2/alias.rb", self.A), typed_result("o1", "ok", "landed")]
        done_first = other + [self._call("ra", "alias.rb", self.C), typed_result("ra", "ok", "landed"),
                              self._call("x1", "/r/s1/alias.rb", self.A), typed_result("x1", "ok", "landed"), self._live()]
        still_running = other + [self._call("ra", "alias.rb", self.C), self._call("x1", "/r/s1/alias.rb", self.A),
                                 typed_result("x1", "ok", "landed"), typed_result("ra", "ok", "landed"), self._live()]
        # the relative alias (a suffix of s1 AND s2) was answered only AFTER x1 was dispatched: it may still have overwritten s1
        self.assertTrue(self._held(stub_old_write_args(still_running)[3].get("content") or ""))
        # answered BEFORE x1 was dispatched: it finished first, so x1 is ordered after it and is current
        self.assertIn("this exact content is on disk at /r/s1/alias.rb", stub_old_write_args(done_first)[4]["content"])


if __name__ == "__main__":
    unittest.main()
