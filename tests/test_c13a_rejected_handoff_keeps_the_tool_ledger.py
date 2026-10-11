"""C13-A. phi4 / Java A10: every harness-compaction briefing was rejected by the focused validators
(14 PLAN, 15 NARROWS) and each later window held only a workspace listing. The briefing prose is the
part that fabricates progress ("Parsing the Config File ... config.py"); what the tools did is a fact
cria owns. When prose is withheld, the handoff carries a deterministic ledger of the recorded tool
calls — cria's own wording over structured fields, never a sentence lifted from a tool's output.

The history is the real lifted compaction request of A10's first handoff
(~/.cria/calls/20261011T092745-01a12bca…/inbound-05c2944e)."""
import json
import os
import unittest

from cria import selfcompact, server
from cria.config import Role

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "c13a_a10_first_compaction_history.json")
IMPORTER = "src/main/java/pipeline/Importer.java"


def _history():
    return json.load(open(FIX))


class _Srv:
    class cfg:
        class routing:
            roles = {"reasoner": Role(name="reasoner", backend="local")}


class _Rlog:
    phase = "proxy"

    def emit(self, kind, **kw):
        return self


def _provider(plan_word):
    class P:
        @staticmethod
        def chat(pb, rlog):
            system = pb["messages"][0]["content"]
            text = plan_word if "PLAN or RETROSPECTIVE" in system else "PRESERVES"
            if "UNFAITHFUL or FAITHFUL" in system:
                text = "FAITHFUL"
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]})
    return P


def _harden(briefing, verdict, history=None):
    comp = {"choices": [{"message": {"role": "assistant", "content": briefing}}]}
    out = server._harden_compaction_reply(
        comp, {"messages": history or _history()}, _provider(verdict), _Srv, _Rlog())
    return out["choices"][0]["message"]["content"]


class RejectedHandoffTests(unittest.TestCase):
    def test_a_rejected_briefing_still_hands_over_what_the_tools_did(self):
        text = _harden("Add the import statement for AtomicInteger.", "PLAN")
        self.assertNotIn("Add the import statement", text)           # the prescription stays out
        self.assertIn(f"write_file ", text)
        self.assertIn(f"{IMPORTER}: confirmed written", text)
        self.assertIn("pom.xml: NOT written", text)                  # refused writes are named as refused

    def test_the_ledger_quotes_no_tool_output_and_carries_no_instruction(self):
        text = _harden("x", "PLAN")
        ledger = text[text.index("WHAT THE TOOLS DID"):]
        for tool_voice in ("STOP editing", "Fix the content", "REFUSED", "read it whole"):
            self.assertNotIn(tool_voice, ledger)

    def test_cria_own_gate_commands_are_not_the_coders_acts(self):
        ledger = selfcompact.work_ledger(server._compaction_messages(_history()))
        self.assertNotIn("__cria_gate", ledger)
        self.assertNotIn("ctx:gate", ledger)

    def test_an_accepted_briefing_ships_without_a_ledger(self):
        text = _harden("Importer.java was written.", "RETROSPECTIVE")
        self.assertTrue(text.startswith("Importer.java was written."))
        self.assertNotIn("WHAT THE TOOLS DID", text)

    def test_an_earlier_ledger_is_carried_into_the_next_one(self):
        first = selfcompact.work_ledger(server._compaction_messages(_history()))
        later = [{"role": "user", "content": "task"},
                 {"role": "user", "content": "Another language model started...\n" + first},
                 {"role": "assistant", "content": "", "tool_calls": [
                     {"id": "c1", "type": "function", "function": {
                         "name": "write_file", "arguments": json.dumps({"path": "REVIEW.md", "content": "x"})}}]},
                 {"role": "tool", "tool_call_id": "c1", "content": "Wrote REVIEW.md"},
                 {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize"}]
        ledger = selfcompact.work_ledger(server._compaction_messages(later))
        self.assertIn(f"{IMPORTER}: confirmed written", ledger)      # from the earlier handoff
        self.assertIn("pom.xml: NOT written (the tool refused or failed it) (x2)", ledger)
        self.assertIn("REVIEW.md: confirmed written", ledger)        # this span


if __name__ == "__main__":
    unittest.main()
