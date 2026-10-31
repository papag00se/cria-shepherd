"""Every context-sized bound scales with the window of the model that answers (cria/windowcaps.py).

The incident class: a bound tuned on the 49,152-token window was a third of it there and the WHOLE
window of a 16K model (a compaction lens reserved its whole 16,384-token cap as reply room — see
loop.COMPACTION_VERDICT_RESERVE), and a rounding error on a 262K one. The contract this file pins:

* at the 49,152-token reference window every cap is EXACTLY the value it had before (byte-identical
  behaviour for the model the numbers were tuned on) — the OLD table below is the old source, verbatim;
* at other windows it is a share of the window between a floor and a ceiling;
* an unknown (or only guessed) window is the old value, never a small one;
* an explicit operator/caller int is never rescaled.
"""
import copy
import json
import pickle
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from cria import (bodykeys, classify, config, contextfloor, evidencesummary, handoffdistill, loop,
                  planner, selfcompact, upstream, windowcaps)
from cria.config import Role
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem

# The constants as they stood before the owner existed, verbatim (HEAD 3e7a6418).
OLD = {
    "classify.JUDGE_MAX_TOKENS": (classify.JUDGE_MAX_TOKENS, 16384),
    "planner.ASK_MAX_TOKENS": (planner.ASK_MAX_TOKENS, 16384),
    "loop.SUMMARIZE_MAX_TOKENS": (loop.SUMMARIZE_MAX_TOKENS, 8192),
    "loop.ROLLUP_MAX_TOKENS": (loop.ROLLUP_MAX_TOKENS, 8192),
    "selfcompact.KEEP_TAIL_TOKENS": (selfcompact.KEEP_TAIL_TOKENS, 6000),
    "selfcompact.RECOMPACT_TOKENS": (selfcompact.RECOMPACT_TOKENS, 4000),
    "selfcompact.REFOLD_TOKENS": (selfcompact.REFOLD_TOKENS, 6000),
    "evidencesummary.EVIDENCE_BLOCK_CHARS": (evidencesummary.EVIDENCE_BLOCK_CHARS, 6000),
    "handoffdistill.EXTRACT_REPLY_TOKENS": (handoffdistill.EXTRACT_REPLY_TOKENS, 4096),
    "contextfloor.DEFAULT_GEN_RESERVE": (contextfloor.DEFAULT_GEN_RESERVE, 4096),
}
# The two bare literals the sweep found, which had no constant to compare: the planner's plan reply and
# the critic's default reply, both 8,192 before.
OLD_LITERALS = {"plan_reply": 8192, "critic_reply": 8192}

BY_NAME = {name: getattr(windowcaps, name.upper().replace("SELFCOMPACT_", "SELFCOMPACT_"))
           for name in windowcaps.NAMES}

# name -> {window: expected}. Written out, not recomputed, so a change to a spec shows up here.
EXPECTED = {
    16384: {"judge_reply": 6144, "summary_reply": 3072, "critic_reply": 3072, "plan_reply": 3072,
            "extract_reply": 2048, "gen_reserve": 2048,
            "selfcompact_keep_tail": 2000, "selfcompact_recompact": 1333, "selfcompact_refold": 2000,
            "dependency_surface": 4800, "dependency_notes": 8000,
            "evidence_block": 2000},
    32768: {"judge_reply": 10922, "summary_reply": 5461, "critic_reply": 5461, "plan_reply": 5461,
            "extract_reply": 2730, "gen_reserve": 2730,
            "selfcompact_keep_tail": 4000, "selfcompact_recompact": 2666, "selfcompact_refold": 4000,
            "dependency_surface": 4800, "dependency_notes": 16000,
            "evidence_block": 4000},
    131072: {"judge_reply": 32768, "summary_reply": 21845, "critic_reply": 21845, "plan_reply": 21845,
             "extract_reply": 10922, "gen_reserve": 10922,
             "selfcompact_keep_tail": 16000, "selfcompact_recompact": 10666, "selfcompact_refold": 16000,
             "dependency_surface": 12000, "dependency_notes": 64000,
             "evidence_block": 16000},
    262144: {"judge_reply": 32768, "summary_reply": 32768, "critic_reply": 32768, "plan_reply": 32768,
             "extract_reply": 16384, "gen_reserve": 16384,
             "selfcompact_keep_tail": 32000, "selfcompact_recompact": 21333, "selfcompact_refold": 32000,
             "dependency_surface": 12000, "dependency_notes": 96000,
             "evidence_block": 32000},
}


class _Rlog:
    session = None
    phase = None

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


class TheReferenceWindowIsUnchanged(unittest.TestCase):
    def test_every_constant_is_the_old_value_and_a_cap(self):
        for label, (now, old) in OLD.items():
            with self.subTest(label):
                self.assertEqual(now, old)
                self.assertEqual(json.dumps(now), json.dumps(old), "serializes as the old number")
        for label in ("classify.JUDGE_MAX_TOKENS", "loop.SUMMARIZE_MAX_TOKENS", "selfcompact.REFOLD_TOKENS",
                      "evidencesummary.EVIDENCE_BLOCK_CHARS", "contextfloor.DEFAULT_GEN_RESERVE"):
            self.assertIsInstance(OLD[label][0], windowcaps.Cap, label)

    def test_every_cap_equals_its_old_value_at_49152(self):
        for name, cap in BY_NAME.items():
            with self.subTest(name):
                self.assertEqual(windowcaps.scaled(cap, windowcaps.REFERENCE_WINDOW), int(cap))
        values = {name: windowcaps.scaled(cap, 49_152) for name, cap in BY_NAME.items()}
        old = {label: old for label, (_now, old) in OLD.items()}
        self.assertEqual(values["judge_reply"], old["classify.JUDGE_MAX_TOKENS"])
        self.assertEqual(values["summary_reply"], old["loop.SUMMARIZE_MAX_TOKENS"])
        self.assertEqual(values["extract_reply"], old["handoffdistill.EXTRACT_REPLY_TOKENS"])
        self.assertEqual(values["gen_reserve"], old["contextfloor.DEFAULT_GEN_RESERVE"])
        self.assertEqual(values["selfcompact_keep_tail"], old["selfcompact.KEEP_TAIL_TOKENS"])
        self.assertEqual(values["selfcompact_recompact"], old["selfcompact.RECOMPACT_TOKENS"])
        self.assertEqual(values["selfcompact_refold"], old["selfcompact.REFOLD_TOKENS"])
        self.assertEqual(values["evidence_block"], old["evidencesummary.EVIDENCE_BLOCK_CHARS"])
        # The two note budgets were the bare constants _SURFACE_INLINE_BUDGET = 6000 and
        # _MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 24_000 (HEAD f36f9d16), in returnedpolicies AND writeproxy.
        self.assertEqual(values["dependency_surface"], 6000)
        self.assertEqual(values["dependency_notes"], 24_000)
        for name, value in OLD_LITERALS.items():
            self.assertEqual(values[name], value, name)

    def test_the_reference_wire_body_is_byte_identical(self):
        """The same request, with the old int and with its Cap, serializes to the same bytes at 49,152."""
        def wire(max_tokens, reserve):
            up = upstream.Upstream("http://unused", context_window=49_152, engagement_level=5)
            body = {"model": "m", "stream": False, "max_tokens": max_tokens, bodykeys.OUTPUT_RESERVE: reserve,
                    "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]}
            return up._prep(body, False, _Rlog())[0]
        self.assertEqual(wire(windowcaps.JUDGE_REPLY, windowcaps.SELFCOMPACT_REFOLD), wire(16384, 6000))


class TheCapsScaleWithTheWindow(unittest.TestCase):
    def test_the_table_at_each_window(self):
        for window, expected in EXPECTED.items():
            for name, want in expected.items():
                with self.subTest(window=window, cap=name):
                    self.assertEqual(windowcaps.scaled(BY_NAME[name], window), want)

    def test_floors_ceilings_and_monotonic(self):
        windows = [1, 4096, 8192, 16384, 24576, 32768, 49152, 65536, 131072, 262144, 1_000_000]
        for name, cap in BY_NAME.items():
            _ref, floor, ceiling = windowcaps._SPECS[name]
            seen = [windowcaps.scaled(cap, w) for w in windows]
            with self.subTest(name):
                self.assertEqual(seen, sorted(seen), "a bigger window never gets a smaller cap")
                self.assertTrue(all(floor <= v <= ceiling for v in seen))
                self.assertEqual(seen[0], floor)
                self.assertEqual(seen[-1], ceiling)

    def test_a_judge_reply_is_never_the_whole_window_of_a_small_model(self):
        # Before: 16,384 of a 16,384-token window. The floor (6,144) is the p99 of a judge's reasoning plus
        # verdict, so a small window still gets a reply that is not cut to nothing.
        self.assertLessEqual(windowcaps.scaled(windowcaps.JUDGE_REPLY, 16384), 16384 * 0.4)
        self.assertLessEqual(windowcaps.scaled(windowcaps.JUDGE_REPLY, 32768), 32768 / 3)

    def test_an_unknown_window_is_the_old_value_never_a_small_one(self):
        for unknown in (None, 0, -1, "x", True, 1.5):
            for name, cap in BY_NAME.items():
                with self.subTest(window=unknown, cap=name):
                    self.assertEqual(windowcaps.scaled(cap, unknown), int(cap))

    def test_an_explicit_value_is_never_rescaled(self):
        for explicit in (16384, 100, 0, None):
            self.assertIs(windowcaps.resolve(explicit, 16384), explicit)

    def test_a_cap_survives_copy_and_pickle(self):
        for clone in (copy.deepcopy(windowcaps.JUDGE_REPLY), pickle.loads(pickle.dumps(windowcaps.JUDGE_REPLY)),
                      copy.copy(windowcaps.JUDGE_REPLY)):
            self.assertIsInstance(clone, windowcaps.Cap)
            self.assertEqual((int(clone), clone.name), (16384, "judge_reply"))
        body = copy.deepcopy({"max_tokens": windowcaps.JUDGE_REPLY})
        self.assertEqual(windowcaps.resolve_body(body, 16384)["max_tokens"], 6144)

    def test_a_body_without_a_cap_is_the_same_object(self):
        body = {"max_tokens": 4096, "messages": []}
        self.assertIs(windowcaps.resolve_body(body, 16384), body)
        resolved = windowcaps.resolve_body({"max_tokens": windowcaps.JUDGE_REPLY,
                                            bodykeys.OUTPUT_RESERVE: 2048}, 16384)
        self.assertEqual((resolved["max_tokens"], resolved[bodykeys.OUTPUT_RESERVE]), (6144, 2048))
        self.assertIs(type(resolved["max_tokens"]), int)


class TheWireSizesACapByTheAnsweringModelsWindow(unittest.TestCase):
    """A classifier/reasoner role may serve a different window than the coder: the cap is resolved in
    ``Upstream`` against ITS window, at the last point before serialization."""

    def _sent(self, window, body_fields, *, guessed=False):
        up = upstream.Upstream("http://unused", context_window=window, engagement_level=5)
        up._window_guessed = guessed
        body = {"model": "m", "stream": False, **body_fields,
                "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]}
        return json.loads(up._prep(body, False, _Rlog())[0])

    def test_one_judge_cap_is_a_different_number_on_each_server(self):
        sent = {w: self._sent(w, {"max_tokens": classify.JUDGE_MAX_TOKENS})["max_tokens"]
                for w in (16384, 32768, 49152, 262144)}
        self.assertEqual(sent, {16384: 6144, 32768: 10922, 49152: 16384, 262144: 32768})

    def test_the_reserve_hint_is_resolved_and_never_reaches_the_wire(self):
        data = self._sent(16384, {"max_tokens": windowcaps.JUDGE_REPLY,
                                  bodykeys.OUTPUT_RESERVE: windowcaps.SELFCOMPACT_RECOMPACT})
        self.assertEqual(data["max_tokens"], 6144)
        self.assertNotIn(bodykeys.OUTPUT_RESERVE, data)

    def test_a_guessed_window_is_not_read_as_small(self):
        data = self._sent(8192, {"max_tokens": classify.JUDGE_MAX_TOKENS}, guessed=True)
        self.assertEqual(data["max_tokens"], 16384)

    def test_an_explicit_role_max_tokens_is_left_alone(self):
        self.assertEqual(self._sent(16384, {"max_tokens": 9000})["max_tokens"], 9000)


class TheFloorsReplyReserveFollowsTheWindow(unittest.TestCase):
    def test_a_judge_cap_as_reserve_no_longer_takes_the_whole_window_of_a_16k_model(self):
        # Before: reserve_for({max_tokens: 16384}) was 16384 on a 16,384-token window.
        reserve = contextfloor.reserve_for({"max_tokens": classify.JUDGE_MAX_TOKENS}, 16384)
        self.assertEqual(reserve, 6144)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": classify.JUDGE_MAX_TOKENS}, 49152), 16384)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": classify.JUDGE_MAX_TOKENS}), 16384)

    def test_the_default_reserve_scales_and_explicit_values_win(self):
        self.assertEqual(contextfloor.reserve_for({}, 49152), 4096)
        self.assertEqual(contextfloor.reserve_for({}, None), 4096)
        self.assertEqual(contextfloor.reserve_for({}, 262144), 16384)
        self.assertEqual(contextfloor.reserve_for({}, 16384), 2048)
        self.assertEqual(contextfloor.reserve_for({bodykeys.OUTPUT_RESERVE: 16384}, 16384), 16384)
        self.assertEqual(contextfloor.reserve_for({bodykeys.OUTPUT_RESERVE: -1, "max_tokens": 700}, 16384), 700)


class TheDistillerAndEvidenceBlocksUseTheWindow(unittest.TestCase):
    def test_binder_sizes_the_reply_and_the_extraction_room_by_the_window(self):
        noop = lambda body: None
        wide = handoffdistill.binder(lambda b, r: b"", 262144, loop.ROLLUP_MAX_TOKENS, noop, _Rlog())
        self.assertIsNotNone(wide)
        # 16,384: summary reply 3,072 + two frames + extraction reply 2,048 fit; before, 8,192 + 5,120 + 4,096
        # = 17,408 > 16,384 and a 16K model got NO distillation at all.
        self.assertIsNotNone(handoffdistill.binder(lambda b, r: b"", 16384, loop.ROLLUP_MAX_TOKENS, noop, _Rlog()))
        self.assertIsNone(handoffdistill.binder(lambda b, r: b"", 8192, 8192, noop, _Rlog()))
        self.assertIsNone(handoffdistill.binder(lambda b, r: b"", None, loop.ROLLUP_MAX_TOKENS, noop, _Rlog()))

    def test_evidence_blocks_are_a_share_of_the_window(self):
        text = "".join(f"line {i:05d} " + "x" * 90 + "\n" for i in range(1000))
        ref = evidencesummary.blocks(text)
        self.assertEqual(ref, evidencesummary.blocks(text, window=49152))
        self.assertEqual(ref, evidencesummary.blocks(text, window=None))
        small = evidencesummary.blocks(text, window=16384)
        big = evidencesummary.blocks(text, window=262144)
        self.assertGreater(len(small), len(ref))
        self.assertLess(len(big), len(ref))
        for blocks in (ref, small, big):
            self.assertEqual("".join(blocks), text)
        self.assertEqual(evidencesummary.blocks(text, 700), evidencesummary.blocks(text, 700, window=16384))


class _Writer:
    def __init__(self):
        self.calls = 0

    def __call__(self, body, rlog):
        self.calls += 1
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "RETROSPECTIVE"}}]}).encode()


def _loop(window):
    def coder(body, rlog):
        return b""
    coder.upstream = SimpleNamespace(_resolve_window=lambda rlog: window, _window_guessed=window is None,
                                     loaded_model=lambda rlog: "m")
    ctx = LoopContext(planner=None, coder_chat=coder, reasoner_chat=_Writer(),
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(replace(ctx, coder_role=Role(name="coder", backend="local")))


class TheSelfCompactionWorkingSetFollowsTheCodersWindow(unittest.TestCase):
    """There is no trigger to scale (tests/test_compaction_room.py owns the predicate); the tail, recompact
    band and refold size are the window-sized caps."""

    def _sizes(self, window):
        seen = {}
        real = selfcompact.RollingInput

        def spy(*args, **kw):
            seen.update(kw)
            return real(*args, **kw)

        sess = PlanSession(plan=Plan(id="p", task="t", created="2026-10-30T00:00:00+00:00",
                                     items=[PlanItem("s")]))
        with patch.object(selfcompact, "RollingInput", spy):
            _loop(window)._self_compact([{"role": "system", "content": "s"},
                                         {"role": "user", "content": "t"}], sess, None, _Rlog(),
                                        pinned_task="t")
        self.assertNotIn("trigger_tokens", seen)
        return tuple(seen[k] for k in ("keep_tail_tokens", "recompact_tokens", "refold_tokens"))

    def test_the_three_sizes_at_each_window(self):
        self.assertEqual(self._sizes(49152), (6000, 4000, 6000))
        self.assertEqual(self._sizes(None), (6000, 4000, 6000))   # unknown/guessed
        self.assertEqual(self._sizes(16384), (2000, 1333, 2000))
        self.assertEqual(self._sizes(262144), (32000, 21333, 32000))

    def test_there_is_no_trigger_cap_left(self):
        self.assertNotIn("selfcompact_trigger", windowcaps.NAMES)
        self.assertFalse(hasattr(windowcaps, "SELFCOMPACT_TRIGGER"))
        self.assertFalse(hasattr(selfcompact, "TRIGGER_TOKENS_DEFAULT"))


class TheOwnerIsTheOnlyWindowReader(unittest.TestCase):
    def test_window_of_reads_the_answering_upstream_and_refuses_a_guess(self):
        owner = SimpleNamespace(_resolve_window=lambda rlog: 16384, _window_guessed=False)
        chat = lambda body, rlog: b""
        chat.upstream = owner
        self.assertEqual(windowcaps.window_of(chat, _Rlog()), 16384)
        owner._window_guessed = True
        self.assertIsNone(windowcaps.window_of(chat, _Rlog()))
        self.assertIsNone(windowcaps.window_of(lambda b, r: b"", _Rlog()))
        self.assertIsNone(windowcaps.window_of(None, _Rlog()))

    def test_a_loop_summary_call_reaches_the_server_sized_for_that_server(self):
        """End to end through the real Upstream: loop.summarize's default cap, served at 16,384."""
        import io
        sent = []

        def urlopen(req, **kwargs):
            sent.append(json.loads(req.data))
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "ok"}}]}).encode())

        up = upstream.Upstream("http://unused", context_window=16384, engagement_level=5)
        up._loaded_model = "m"
        with patch("cria.upstream.urllib.request.urlopen", side_effect=urlopen):
            loop.summarize(up.chat, None, "system", "user", _Rlog(), phase="compactor")
        self.assertEqual([b["max_tokens"] for b in sent], [3072])


if __name__ == "__main__":
    unittest.main()
