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


if __name__ == "__main__":
    unittest.main()


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
