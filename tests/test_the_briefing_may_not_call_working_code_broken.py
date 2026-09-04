"""Regression for the cart-billing briefing that called working code broken.

The former fix parsed error-ish words and symbol-shaped tokens, then authored a vouch in cria's
voice.  The Java walk proved that lexical judgment can contradict javac.  The replacement asks one
focused accept/reject question over the candidate and exact check facts and never authors a symbol
claim.
"""
import inspect
import json
import unittest

from cria import loop
from cria.config import Role


FINDINGS = ("$ go build ./... — ./cart.go:41:21: undefined: decimal.NewDecimal\n"
            "./cart.go:59:24: undefined: pct")
BRIEFING = ("The build fails with undefined symbols decimal.NewDecimal, decimal.NewFromString, and "
            "decimal.RoundingModeHalfUp. Next step: replace decimal.NewDecimal with "
            "decimal.NewFromFloat64 for numeric literals.")


class _Rlog:
    phase = ""
    def emit(self, *args, **kwargs):
        pass


class BriefingConflictUsesJudgmentTests(unittest.TestCase):
    def test_the_lexical_vouch_implementation_is_gone(self):
        self.assertFalse(hasattr(loop, "_briefing_denies_working_symbols"))
        self.assertFalse(hasattr(loop, "_briefing_symbol_truth"))
        self.assertNotIn("do NOT report a problem with", inspect.getsource(loop.Loop._self_compact))

    def test_the_focused_judge_sees_the_complete_dotted_names_and_checks(self):
        seen = []
        def chat(body, rlog):
            seen.append(body)
            verdict = "RETROSPECTIVE" if len(seen) == 1 else "UNFAITHFUL"
            return json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
        accepted = loop.validate_compaction_briefing(
            chat, Role(name="reasoner", backend="local"), BRIEFING, files="cart.go",
            checks=FINDINGS, transcript_blocks=["tool: " + FINDINGS], rlog=_Rlog())
        self.assertFalse(accepted)
        text = "\n".join(m["content"] for m in seen[-1]["messages"])
        self.assertIn("decimal.NewFromString", text)
        self.assertIn("decimal.NewDecimal", text)
        self.assertIn(FINDINGS, text)

    def test_no_check_output_is_explicitly_absent_not_lexically_inferred(self):
        seen = []
        def chat(body, rlog):
            seen.append(body)
            verdict = "RETROSPECTIVE" if len(seen) == 1 else "UNFAITHFUL"
            return json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()

        loop.validate_compaction_briefing(
            chat,
            Role(name="reasoner", backend="local"), BRIEFING, files="cart.go", checks="",
            transcript_blocks=[], rlog=_Rlog())
        text = "\n".join(m["content"] for m in seen[-1]["messages"])
        self.assertIn("LATEST CHECK FACTS: no authoritative fact was available", text)


if __name__ == "__main__":
    unittest.main()
