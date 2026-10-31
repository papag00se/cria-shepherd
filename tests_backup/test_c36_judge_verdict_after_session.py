"""C36: a judge whose user turn is a generic "Answer the question above." must not have the raw
coder SESSION/transcript as the very last thing before it — that shape invites a coder-role
continuation instead of a verdict token.

Evidence: independent review replayed P26 `0068-module-state` after the C35 scrub (0ee35ea7) and
found the prompt still ends `...{{SESSION}}` (a transcript ending in a failing `go test`) followed
only by `user: "Answer the question above."`. 0068's reasoning ("We need to respond with final
answer…") is exactly that continuation. `runner_reset_judge_user.txt` already restates its
one-token contract ("Return exactly `RESET` or `ON_TRACK`.") after `{{SESSION}}`;
`module_state_judge_user.txt` did not restate its own ("REANCHOR`/`ON_TRACK`) contract at all.

Root cause: the prompt template, not the loop code — `module_state_judge_user.txt` put
`{{SESSION}}` last with no trailing instruction. Fixed by restating the instruction after SESSION,
matching the runner-reset shape.
"""

from __future__ import annotations

import unittest

from cria import prompts


class C36JudgeVerdictAfterSessionTests(unittest.TestCase):
    def test_module_state_judge_question_ends_with_the_one_token_instruction_after_session(self):
        question = prompts.render(
            "module_state_judge_user", TASK="Implement the cart billing endpoint.",
            TESTS="go test ./... exited 1", CHECKS="billing/money.go:8: missing go.sum entry",
            SESSION="assistant: Added the decimal rounding helper.\ntool: go test ./... FAILED")
        self.assertIn("assistant: Added the decimal rounding helper.", question)
        # The session is not the last thing the judge reads — its own one-token contract is.
        self.assertTrue(
            question.rstrip().endswith("Return exactly `REANCHOR` or `ON_TRACK`."),
            f"module-state judge question does not restate its verdict contract after the "
            f"session; ends with: {question.rstrip()[-120:]!r}")
        # The session content still comes before that instruction, not truncated or reordered away.
        session_idx = question.index("go test ./... FAILED")
        instruction_idx = question.index("Return exactly `REANCHOR` or `ON_TRACK`.")
        self.assertLess(session_idx, instruction_idx)

    def test_runner_reset_judge_question_already_restates_the_contract_after_session(self):
        """Unchanged reference shape — the runner-reset prompt this fix was matched to."""
        question = prompts.render(
            "runner_reset_judge_user", task="Build the CLI.", runner="npm run test",
            node_modules="node_modules is absent.", checks="ReferenceError: test is not defined",
            session="assistant: changed the test package.\ntool: npm run test FAILED")
        self.assertTrue(
            question.rstrip().endswith("Return exactly `RESET` or `ON_TRACK`."),
            f"runner-reset judge question does not restate its verdict contract after the "
            f"session; ends with: {question.rstrip()[-120:]!r}")


if __name__ == "__main__":
    unittest.main()
