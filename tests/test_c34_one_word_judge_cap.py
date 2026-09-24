"""C34: a one-word closed judge answer never reaches the coder when capped at 16 output tokens.

Census over every capture with ``max_tokens: 16`` (nemotron-elastic, 2026-09-22..24, reasoning_effort
"none", temperature 0): 69 of 69 returned EMPTY content at ``finish_reason: length`` — the model still
emits a short reasoning preface even with reasoning off, and 16 tokens cuts it before the one-word
answer. The same questions at 1,024 answered 38/38. Every one of these captures a live consequence:
a support question that would have surfaced a correct negative diagnosis (P25, satisfaction-diagnosis)
was suppressed; self-compaction candidates were rejected because the validator never answered;
C10 module-state and the declared-JS runner-reset assist never fired.

Each test below replays that exact capture shape: a fake reasoner that emits a short reasoning
preface, then the verdict word ONLY if its token budget allows it — ``finish_reason: length`` with
empty content otherwise, precisely as ``finish_reason: length`` behaved in the captures.
"""

from __future__ import annotations

import json
import unittest

from cria import loop
from cria.classify import JUDGE_MAX_TOKENS
from cria.config import Role
from cria.probegate import GateOutcome
from cria.probeparse import ProbeResult
from cria.proberun import ProbeReport
from cria import probediscovery
from pathlib import Path


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [kind for kind, _fields in self.events]


class _CapSensitiveChat:
    """Capture-shaped reasoner: a reasoning preface first, then the verdict word — but ONLY if
    ``max_tokens`` in the body is large enough to hold both. At <= 16 (the old cap), the preface
    alone exhausts the budget and the reply comes back exactly as the captures show it:
    ``finish_reason: length`` with empty content."""

    REASONING = ("We need to decide if the task is supported given the evidence. "
                 "The task requirement")

    def __init__(self, words):
        # One word per call, in order; the last is reused for any further calls.
        self._words = list(words)
        self.bodies = []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        word = self._words.pop(0) if len(self._words) > 1 else self._words[0]
        max_tokens = body.get("max_tokens")
        if max_tokens is not None and max_tokens <= 16:
            message = {"reasoning_content": self.REASONING, "content": ""}
            return json.dumps({"choices": [{"finish_reason": "length",
                                            "message": message}]}).encode()
        message = {"reasoning_content": self.REASONING, "content": word}
        return json.dumps({"choices": [{"message": message}]}).encode()


ROLE = Role(name="reasoner", backend="local")


class NegativeDiagnosisSupportReachesCoderTests(unittest.TestCase):
    """(a) A correct negative diagnosis's support question must actually be answerable."""

    def _obj(self):
        task = "Resolve the handle to its address."
        return {
            "satisfied": False,
            "reason": "the test asserts resolved_address == 'goose'",
            "proposed_fix": "return the resolved address",
            "diagnosis_kind": "failed_check",
            "subject": "",
            "task_quote": task,
            "evidence_source": "checks",
            "evidence_quote": "resolved_address == 'goose'",
        }, task

    def _ask(self, chat, max_tokens):
        rlog = _Rlog()
        ask = lambda sysm: loop.ask_closed(  # noqa: E731
            chat, ROLE, sysm, rlog, phase="satisfaction-diagnosis",
            max_tokens=max_tokens, retry_off=False)
        obj, task = self._obj()
        out = loop._negative_diagnosis_nudge(
            obj, task=task, checks="resolved_address == 'goose'", ask=ask, rlog=rlog,
            phase="satisfaction-diagnosis")
        return out, rlog

    def test_capped_at_16_suppresses_the_correct_diagnosis(self):
        """Fails-before: the old bespoke 16-token cap never lets SUPPORTED land."""
        chat = _CapSensitiveChat(["SUPPORTED"])
        out, rlog = self._ask(chat, max_tokens=16)

        self.assertEqual(str(out), "")
        self.assertIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_judge_max_tokens_lets_the_diagnosis_through(self):
        """Passes-after: the call site's shared judge budget lets the same model answer."""
        chat = _CapSensitiveChat(["SUPPORTED"])
        out, rlog = self._ask(chat, max_tokens=JUDGE_MAX_TOKENS)

        self.assertIn("resolved_address == 'goose'", str(out))
        self.assertIn("loop.negative_diagnosis_supported", rlog.kinds())
        self.assertNotIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_loop_call_sites_no_longer_pin_the_16_token_cap(self):
        """The regression is the literal at the call site, not ask_closed's own default."""
        import inspect
        src = inspect.getsource(loop)
        self.assertNotIn("max_tokens=16,", src)
        self.assertNotIn("max_tokens=16)", src)


class CompactionValidationLensTests(unittest.TestCase):
    """(b) A compaction validation lens (retrospective/fidelity) must reach its verdict word."""

    def test_capped_at_16_the_validator_never_answers(self):
        chat = _CapSensitiveChat(["RETROSPECTIVE", "FAITHFUL"])
        rlog = _Rlog()

        def judge(lens, system_prompt, blocks, accepted_word):
            answer = loop.summarize(chat, ROLE, system_prompt, "Answer.", rlog,
                                    phase=f"compaction-validate-{lens}", max_tokens=16,
                                    retry_off=False, temperature=0.0, evidence_blocks=blocks)
            return answer.strip().upper() == accepted_word

        accepted = judge("retrospective", "Was this retrospective?", ["candidate"], "RETROSPECTIVE")
        self.assertFalse(accepted)

    def test_judge_max_tokens_the_briefing_is_accepted(self):
        chat = _CapSensitiveChat(["RETROSPECTIVE", "FAITHFUL"])
        rlog = _Rlog()

        accepted = loop.validate_compaction_briefing(
            chat, ROLE, "candidate briefing text", files="", checks="", transcript_blocks=[],
            rlog=rlog, task="")

        self.assertTrue(accepted)
        self.assertEqual(rlog.events[-1][1]["accepted"], True)
        for body in chat.bodies:
            self.assertEqual(body["max_tokens"], JUDGE_MAX_TOKENS)


def _go_outcome(exit_code=1):
    command = ["go", "test", "-mod=readonly", "-count=1", "-v", "./..."]
    candidate = probediscovery.ProbeCandidate(
        kind=probediscovery.ProbeKind.Test, command=command, working_dir=Path("."),
        confidence=90, expected_value=90, cost=probediscovery.ProbeCost.Moderate,
        mutates_code=False, may_hang=False, may_need_services=False,
        reason="go.mod found", ecosystem=probediscovery.Ecosystem.Go)
    result = ProbeResult(" ".join(command), exit_code, "billing/money.go:8: missing go.sum entry")
    return GateOutcome(ran=True, report=ProbeReport([], [candidate], [result]))


class ModuleStateAndRunnerResetTests(unittest.TestCase):
    """(c) module-state and runner-reset must reach their verdict, not silently no-op."""

    def _body(self):
        return {"messages": [
            {"role": "user", "content": "Implement the cart billing endpoint."},
            {"role": "assistant", "content": "Maybe another decimal package is needed."},
        ]}

    def test_capped_at_16_the_reasoning_preface_alone_exhausts_the_budget(self):
        """Fails-before, generic to any one-word judge call: the same fake reasoner used by
        module-state/runner-reset below returns nothing at the old 16-token cap."""
        chat = _CapSensitiveChat(["REANCHOR"])
        rlog = _Rlog()
        answer = loop.ask_closed(chat, ROLE, "Judge the module state.", rlog,
                                 phase="module-state", max_tokens=16, retry_off=False)
        self.assertEqual(answer, "")

    def test_module_state_reaches_reanchor_at_judge_max_tokens(self):
        from cria.loop import GuardState, module_state_steer
        chat = _CapSensitiveChat(["REANCHOR"])
        state = GuardState()
        steer = module_state_steer(state, _go_outcome(), self._body(), _Rlog(),
                                   reasoner_chat=chat, reasoner_role=ROLE)
        self.assertIsNotNone(steer)
        self.assertIn("missing go.sum entry", steer)
        for body in chat.bodies:
            self.assertEqual(body["max_tokens"], JUDGE_MAX_TOKENS)

    def test_runner_reset_reaches_reset_at_judge_max_tokens(self):
        from cria.loop import GuardState, runner_reset_steer
        from cria import wsview
        import tempfile
        root = tempfile.mkdtemp()
        token = wsview.bind(wsview.View(root, "runner-reset"))
        self.addCleanup(wsview.unbind, token)

        candidate = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=["npm", "run", "test"],
            working_dir=Path(root), confidence=96, expected_value=88,
            cost=probediscovery.ProbeCost.Moderate, mutates_code=False, may_hang=False,
            may_need_services=False, reason="package.json script `test`",
            declared_interface=True, ecosystem=probediscovery.Ecosystem.JsTs)
        result = ProbeResult("npm run test", 1, "ReferenceError: test is not defined")
        outcome = GateOutcome(ran=True, report=ProbeReport([], [candidate], [result]))
        body = {"messages": [
            {"role": "user", "content": (
                "Build the CLI. It must run with no node_modules directory present.")},
            {"role": "tool", "content": "ReferenceError: test is not defined"},
        ]}
        chat = _CapSensitiveChat(["RESET"])

        steer = runner_reset_steer(GuardState(), outcome, body, _Rlog(),
                                   reasoner_chat=chat, reasoner_role=ROLE,
                                   workspace_root=root)

        self.assertIsNotNone(steer)
        for sent in chat.bodies:
            self.assertEqual(sent["max_tokens"], JUDGE_MAX_TOKENS)


if __name__ == "__main__":
    unittest.main()
