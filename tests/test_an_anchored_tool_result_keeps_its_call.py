"""An anchored tool result is kept TOGETHER with the call that produced it.

4d7dcc7f anchored the spec routes/shape block a web_fetch renders into its payload: the fields must stay
verbatim and the summarizer must never fold them. Only the RESULT was anchored, so the pair split:

- the writer read the call with no result -- 20261008T202854 0038 (ornith, Ada Handle CLI):
  ``assistant: web_fetch({"url": "https://api.handle.me/openapi.json"})`` followed directly by the
  coder's "The `/holders/{address}` endpoint returns `total_handles`"; 21 writer prompts in 20 sessions;
- once a fold was accepted the result rode on without its call and the coder read it re-roled as a user
  turn -- 20260813T015529 0009-coder-s2 index 4: "HTTP 200 OK · https://api.handle.me/openapi.json …"
  in the user's voice, its web_fetch call folded into the rollup; 20 sessions.

The anchor unit is now the exchange: the issuing assistant turn and every result of it. Driven through the
production owner ``Loop._self_compact`` (real rolling engine and validators) with the spec block produced by
the real renderer ``webfetch.spill_outline``; only model replies are fake.
"""
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from cria import contextfloor, selfcompact, tokenratio, webfetch
from cria.config import Role
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem

MODEL = "anchored-pair-test-model"
BIG = "w" * 4_000
URL = "https://api.example.invalid/openapi.json"
SPEC = {"openapi": "3.0.0", "paths": {
    "/handles/{handle}": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
        "type": "object", "required": ["name"], "properties": {
            "name": {"type": "string"},
            "resolved_addresses": {"type": "object", "properties": {"ada": {"type": "string"}}}}}}}}}}},
    "/holders/{address}": {"get": {}}}}
FETCH_PROSE = "The by-holder route returned 404. Let me find the correct endpoint."
LEDGER = "⟦ctx:facts⟧ PAGES YOU HAVE ALREADY FETCHED — " + URL + " -> 200"


def _spec_result() -> str:
    return (f"HTTP 200 OK · {URL}\nThis document is too large for the context — it was saved IN FULL to "
            f"./tmp/read-only/openapi.json.\n" + webfetch.spill_outline(SPEC, "./tmp/read-only/openapi.json"))


def _call(call_id, name, args, prose=""):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _exchange(call_id="f1", prose=FETCH_PROSE, url=URL, result=None, extra=()):
    calls = [_call(call_id, "web_fetch", {"url": url})] + [_call(c, n, a) for c, n, a, _ in extra]
    return ([{"role": "assistant", "content": prose, "tool_calls": calls},
             {"role": "tool", "tool_call_id": call_id, "content": result if result is not None else _spec_result()}]
            + [{"role": "tool", "tool_call_id": c, "content": out} for c, _, _, out in extra])


def _read_pair(call_id="r1"):
    return [{"role": "assistant", "content": "", "tool_calls": [_call(call_id, "read_file", {"path": "lookup.js"})]},
            {"role": "tool", "tool_call_id": call_id, "content": "const lookup = require('./lib/handle');"}]


def _turns(n, tag):
    return [{"role": "user" if i % 2 else "assistant", "content": f"{tag} {i} " + BIG} for i in range(n)]


def _reply(text):
    return json.dumps({"choices": [{"finish_reason": "stop",
                                    "message": {"role": "assistant", "content": text}}]}).encode()


class _Reasoner:
    def __init__(self):
        self.writer, self.fidelity = [], []

    def __call__(self, body, rlog):
        system = body["messages"][0]["content"]
        shown = "\n".join(m.get("content") or "" for m in body["messages"][1:])
        if "PLAN or RETROSPECTIVE" in system:
            return _reply("RETROSPECTIVE")
        if "NARROWS or PRESERVES" in system:
            return _reply("PRESERVES")
        if "CHANGED or NOT CHANGED" in system:
            return _reply("NONE")      # the change-claim lens: nothing here to list
        if "UNFAITHFUL or FAITHFUL" in system:
            self.fidelity.append(shown)
            return _reply("FAITHFUL")
        self.writer.append(shown)
        return _reply("The coder looked up the handle API.")


def _loop(reasoner) -> Loop:
    def coder(body, rlog):
        return _reply("")
    coder.upstream = SimpleNamespace(_resolve_window=lambda rlog: 10_000_000, _window_guessed=False,
                                     loaded_model=lambda rlog: MODEL)
    ctx = LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner,
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(replace(ctx, trigger_compaction=100, coder_role=Role(name="coder", backend="local")))


def _session():
    return PlanSession(plan=Plan(id="20261027T0000-abcd1234", task="build the CLI",
                                 created="2026-10-27T00:00:00+00:00", items=[PlanItem("step 1")]))


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _pairs_intact(view):
    return contextfloor.ensure_tool_integrity(view)[1] == 0


class TheExchangeIsTheAnchorUnit(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()
        self.addCleanup(tokenratio.reset)

    def test_writer_and_coder_view_keep_the_fetch_with_its_spec(self):
        msgs = ([{"role": "system", "content": "sys"}, {"role": "user", "content": "build the CLI"}]
                + _turns(4, "old") + _exchange() + [{"role": "user", "content": LEDGER}] + _read_pair()
                + _turns(4, "mid") + _turns(7, "tail"))
        reasoner = _Reasoner()
        view = _loop(reasoner)._self_compact(msgs, _session(), None, _Log(), pinned_task="build the CLI")

        self.assertEqual(len(reasoner.writer), 1)
        for seen in (reasoner.writer[0], reasoner.fidelity[0]):
            self.assertNotIn("web_fetch(", seen, "no call reaches a reader without its result")
            self.assertNotIn("resolved_addresses", seen, "the spec is never summarized")
            self.assertNotIn(LEDGER, seen, "cria's own anchor is still excluded")
            self.assertIn('read_file({"path": "lookup.js"})', seen, "an ordinary exchange is still summarized")
            self.assertIn("tool: const lookup", seen)

        call_at = next(i for i, m in enumerate(view) if any(
            c["id"] == "f1" for c in m.get("tool_calls") or []))
        self.assertEqual(view[call_at]["content"], FETCH_PROSE, "the coder's words beside the call stay")
        self.assertEqual(view[call_at + 1], {"role": "tool", "tool_call_id": "f1", "content": _spec_result()})
        self.assertIn(LEDGER, [m.get("content") for m in view])
        self.assertTrue(_pairs_intact(view), "nothing is re-roled or pruned at the wire")

    def test_a_step_boundary_fold_keeps_the_pair(self):
        # The 20260813T015529 0009-coder-s2 shape: a boundary keeps no verbatim tail.
        msgs = [{"role": "system", "content": "sys"}] + _turns(2, "a") + _exchange() + _turns(3, "b")
        out, _, applied = selfcompact.compact(msgs, lambda mm: "ROLLUP", selfcompact.CompactState(),
                                              force=True, pinned_task="build the CLI")
        self.assertTrue(applied)
        self.assertTrue(_pairs_intact(out))
        self.assertIn(_spec_result(), [m.get("content") for m in out])
        self.assertTrue(all(m["role"] != "user" or URL not in str(m.get("content")) or m.get("content") == LEDGER
                            for m in out), "the spec never rides as a user turn")


class UnitControls(unittest.TestCase):
    KW = dict(trigger_tokens=100, keep_tail_tokens=6_000, recompact_tokens=20)

    def _compact(self, msgs, log=None):
        fed = []
        out, _, applied = selfcompact.compact(msgs, lambda mm: fed.extend(mm) or "ROLLUP",
                                              selfcompact.CompactState(), rlog=log, **self.KW)
        self.assertTrue(applied)
        return out, fed

    def test_a_sibling_result_of_the_same_turn_stays_with_the_unit(self):
        sibling = ("r9", "read_file", {"path": "README.md"}, "# Handle CLI")
        msgs = [{"role": "system", "content": "sys"}] + _exchange(extra=[sibling]) + _turns(6, "a") + _turns(7, "t")
        out, fed = self._compact(msgs)
        self.assertNotIn("# Handle CLI", [m.get("content") for m in fed])
        self.assertIn({"role": "tool", "tool_call_id": "r9", "content": "# Handle CLI"}, out)
        self.assertTrue(_pairs_intact(out))

    def test_identical_exchanges_collapse_whole_and_logged(self):
        msgs = ([{"role": "system", "content": "sys"}] + _exchange("f1") + _turns(2, "a") + _exchange("f2")
                + _turns(4, "b") + _turns(7, "t"))
        log = _Log()
        out, _ = self._compact(msgs, log)
        self.assertEqual([m.get("content") for m in out].count(_spec_result()), 1)
        self.assertTrue(_pairs_intact(out))
        self.assertIn(("context.anchor_dedup", {"reshape": "dedup", "dropped": 2}), log.events)

    def test_identical_results_of_different_calls_both_keep_their_call(self):
        msgs = ([{"role": "system", "content": "sys"}] + _exchange("f1") + _turns(2, "a")
                + _exchange("f2", prose="Fetch the spec again.") + _turns(4, "b") + _turns(7, "t"))
        out, _ = self._compact(msgs)
        self.assertEqual([m.get("content") for m in out].count(_spec_result()), 2)
        self.assertTrue(_pairs_intact(out))

    def test_a_standalone_anchor_and_an_unanchored_exchange_are_unchanged(self):
        msgs = ([{"role": "system", "content": "sys"}, {"role": "user", "content": LEDGER}] + _read_pair()
                + _turns(6, "a") + _turns(7, "t"))
        out, fed = self._compact(msgs)
        self.assertIn(LEDGER, [m.get("content") for m in out])
        self.assertNotIn(LEDGER, [m.get("content") for m in fed])
        self.assertTrue(any(m.get("tool_call_id") == "r1" for m in fed))
        self.assertFalse(any(m.get("tool_call_id") == "r1" for m in out))


if __name__ == "__main__":
    unittest.main()
