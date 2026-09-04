import json
import unittest

from cria import selfcompact
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem
from cria.selfcompact import msg_digest as _msg_digest


class _Rlog:
    def emit(self, *a, **k):
        pass


def _validation_reply(system):
    if "PLAN or RETROSPECTIVE" in system:
        return "RETROSPECTIVE"
    if "NARROWS or PRESERVES" in system:
        return "PRESERVES"
    if "UNFAITHFUL or FAITHFUL" in system:
        return "FAITHFUL"
    return None


def _loop(self_compact=True, chat_reply="ROLLUP SUMMARY", trigger=100):
    # The single-item self-compaction rides the COMPACTOR endpoint (compactor_chat), same summarize
    # primitive the loop's completion compaction uses.
    def chat(body, rlog):
        text = _validation_reply(body["messages"][0]["content"]) or chat_reply
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat, compactor_chat=chat,
                      compactor_role=Role(name="compactor", backend="local"), coder_role=None,
                      planner_enabled=False, runs_dir="",
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

    def test_the_writer_and_scope_judge_receive_the_pinned_original_task(self):
        seen = []

        def chat(body, rlog):
            seen.append(body)
            text = (_validation_reply(body["messages"][0]["content"])
                    or "Retrospective session state.")
            return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

        ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat, compactor_chat=chat,
                          compactor_role=Role(name="compactor", backend="local"), coder_role=None,
                          planner_enabled=False, runs_dir="", self_compact=True,
                          trigger_compaction=100)
        loop = Loop(ctx, LoopStore())
        task = "Fix rounding, load discounts.json, use decimal money, and log totals."
        loop._self_compact_single(_big(150), _synth(), _Rlog(), root_task=task)

        rendered = ["\n".join(str(m.get("content") or "") for m in call["messages"])
                    for call in seen]
        self.assertIn(task, rendered[0], "the briefing writer must see the north-star task")
        self.assertTrue(any(task in text and "full unresolved scope" in text for text in rendered[1:]),
                        "an independent scope judgment must compare the candidate with the task")

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
