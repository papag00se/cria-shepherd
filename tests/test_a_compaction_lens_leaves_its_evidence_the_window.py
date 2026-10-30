"""A compaction lens answers ONE word, so the window it reserves for its reply is small.

The lens keeps ``JUDGE_MAX_TOKENS`` as its cap (a smaller cap deletes verdicts — see classify.py), but
the floor reserved ``max_tokens`` of window for the reply, so 16,384 of the 49,152-token window never
reached the lens's evidence — the whole transcript. In the ornith-java campaign captures (2026-10-26..28)
33 judge-shaped floor reductions dropped 53-215 evidence turns for the fidelity lens, which then judged a
"⟦ctx:compacted⟧" digest; 21 of the 33 requests fit whole with a 2,048-token reserve
(ornith-java-overnight-c7dd… session, call 0038: msg_before 34,844, safety 1.22, 69 turns dropped).
"""
import unittest

from cria import contextfloor, loop, selfcompact
from cria.classify import JUDGE_MAX_TOKENS
from cria.config import Role

WINDOW = 49152


class _Rlog:
    phase = ""

    def emit(self, *_a, **_k):
        pass


class _Chat:
    def __init__(self, word):
        self.word, self.bodies = word, []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        import json
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": self.word}}]}).encode()


def _evidence(turns=70, chars=1800):
    return [("MIDDLE BEING REPLACED (work to summarize):\ntool: " + f"{i} " + "x" * chars) for i in range(turns)]


class CompactionLensReserveTests(unittest.TestCase):
    def _bodies(self, word):
        chat = _Chat(word)
        loop.validate_compaction_briefing(
            chat, Role(name="reasoner", backend="local"), "A retrospective briefing.", files="", checks="",
            transcript_blocks=_evidence(2), rlog=_Rlog(), task="the task")
        return chat.bodies

    def test_every_lens_keeps_the_generous_cap_and_a_one_word_reserve(self):
        bodies = self._bodies("RETROSPECTIVE")
        self.assertTrue(bodies)
        for body in bodies:
            self.assertEqual(body["max_tokens"], JUDGE_MAX_TOKENS)
            self.assertEqual(contextfloor.reserve_for(body), loop.COMPACTION_VERDICT_RESERVE)

    def test_the_fidelity_lens_evidence_that_fits_the_window_is_not_digested(self):
        # ~34K estimated tokens at the learned density 1.22: fits 49,152 less a small reserve, not less 16,384.
        # Built as production builds them: producer-marked internal evidence, not caller user turns.
        blocks = ([{"role": "system", "content": "judge"}, selfcompact.internal_evidence_message("intro")]
                  + [selfcompact.internal_evidence_message(b) for b in _evidence()]
                  + [{"role": "user", "content": "Classify now."}])
        by_cap = contextfloor.fit(blocks, None, window=WINDOW, reserve=JUDGE_MAX_TOKENS, safety=1.22)[2]
        by_reserve = contextfloor.fit(blocks, None, window=WINDOW, reserve=loop.COMPACTION_VERDICT_RESERVE,
                                      safety=1.22)[2]
        self.assertGreater(by_cap.turns_dropped, 0, "fixture must overflow under the cap-sized reserve")
        self.assertEqual(by_reserve.turns_dropped, 0)

    def test_other_closed_judges_are_unchanged(self):
        chat = _Chat("YES")
        loop.ask_closed(chat, Role(name="reasoner", backend="local"), "Q?", _Rlog(), phase="x",
                        max_tokens=JUDGE_MAX_TOKENS)
        self.assertEqual(contextfloor.reserve_for(chat.bodies[0]), JUDGE_MAX_TOKENS)


if __name__ == "__main__":
    unittest.main()
