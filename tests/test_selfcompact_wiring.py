import json
import unittest

from cria import selfcompact
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from cria.selfcompact import msg_digest as _msg_digest


class _Rlog:
    def emit(self, *a, **k):
        pass


def _loop(self_compact=True, chat_reply="ROLLUP SUMMARY", trigger=100):
    # The single-item self-compaction rides the COMPACTOR endpoint (compactor_chat), same summarize
    # primitive the loop's completion compaction uses.
    chat = lambda body, rlog: json.dumps({"choices": [{"message": {"content": chat_reply}}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat, compactor_chat=chat,
                      compactor_role=None, coder_role=None, planner_enabled=False, runs_dir="",
                      self_compact=self_compact, trigger_compaction=trigger)
    return Loop(ctx, LoopStore())


def _synth():
    return PlanSession(plan=Plan(id="x", task="t", created="c", items=[PlanItem(text="t")]), synthetic=True)


def _big(n):
    # ~1000 chars/message so the token budgets (tail 6000) leave a compactable middle
    return {"messages": [{"role": "system", "content": "sys"}]
            + [{"role": "assistant", "content": f"turn-{i} " + "x" * 1000} for i in range(n)]}


class SelfCompactWiringTests(unittest.TestCase):
    """The single-item (plan-off) path rolls the old coder-history middle into a ⟦ctx:rollup⟧ via
    Loop._self_compact_single, using sess.compact_state (per-session — no cross-conversation leak;
    an unstable-key session is ephemeral anyway). Cross-session isolation is now enforced upstream
    (unstable task: keys are never persisted), not by a stable-key gate inside the compactor."""

    def test_compacts_a_long_session(self):
        loop = _loop()
        framed = _big(150)                                     # 151 msgs, over the trigger
        out = loop._self_compact_single(framed, _synth(), _Rlog())
        self.assertLess(len(out["messages"]), len(framed["messages"]))
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(m.get("content")) for m in out["messages"]))
        self.assertIn("ROLLUP SUMMARY", " ".join(str(m.get("content")) for m in out["messages"]))

    def test_skips_short_history(self):
        loop = _loop()
        small = {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]}
        self.assertIs(loop._self_compact_single(small, _synth(), _Rlog()), small)   # under the token trigger

    def test_disabled_by_config(self):
        loop = _loop(self_compact=False)
        big = _big(150)
        self.assertIs(loop._self_compact_single(big, _synth(), _Rlog()), big)

    def test_msg_digest_captures_tool_calls(self):
        d = _msg_digest({"role": "assistant", "content": "writing",
                         "tool_calls": [{"function": {"name": "write_file", "arguments": '{"path":"x.py"}'}}]})
        self.assertIn("writing", d)
        self.assertIn("write_file", d)


if __name__ == "__main__":
    unittest.main()
