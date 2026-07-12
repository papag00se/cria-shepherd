"""The harness-agnostic context floor: cria guarantees the request fits the window,
whatever the connected harness sends."""
import json
import unittest

from cria import contextfloor
from cria.content_reduce import est_tokens


def _u(text):
    return {"role": "user", "content": text}


def _a(text="", tool_calls=None):
    m = {"role": "assistant", "content": text}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tool(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _fat_tools(n, desc_len):
    return [{"type": "function", "function": {
        "name": f"connector_tool_{i}", "description": "D" * desc_len,
        "parameters": {"type": "object", "properties": {
            "arg": {"type": "string", "description": "P" * desc_len}}, "required": ["arg"]}}}
        for i in range(n)]


class TestFits(unittest.TestCase):
    def test_noop_when_it_already_fits(self):
        msgs = [{"role": "system", "content": "sys"}, _u("hi")]
        out, tools, rep = contextfloor.fit(msgs, None, window=49152, reserve=4096)
        self.assertEqual(out, msgs)
        self.assertFalse(rep.applied)
        self.assertEqual(rep.turns_dropped, 0)
        self.assertFalse(rep.over_budget)

    def test_drops_oldest_and_preserves_system_and_active_turn(self):
        msgs = [
            {"role": "system", "content": "SYSTEM PRELUDE"},
            _u("old task"),
            _a("X" * 12000),  # ~3000 est — the bulk
            _u("current task"),  # last user → the active turn, protected
        ]
        out, tools, rep = contextfloor.fit(msgs, None, window=4000, reserve=500)
        self.assertTrue(rep.applied)
        self.assertGreaterEqual(rep.turns_dropped, 1)
        roles = [m["role"] for m in out]
        self.assertIn("system", roles)  # system preserved
        self.assertEqual(out[-1]["content"], "current task")  # active turn preserved
        self.assertNotIn("X" * 12000, [m.get("content") for m in out])  # bulk dropped
        target = int((4000 - 500) / contextfloor.SAFETY_FACTOR)
        self.assertLessEqual(rep.msg_tokens_after, target)

    def test_compresses_fat_tool_schema_keeping_tools_callable(self):
        # 60 verbose connector tools (~big schema) must be compressed, not allowed to eat
        # the window — but every tool stays present and callable.
        tools = _fat_tools(60, 600)
        before = est_tokens(json.dumps(tools))
        msgs = [{"role": "system", "content": "s"}, _u("do a coding task")]
        out, new_tools, rep = contextfloor.fit(msgs, tools, window=20000, reserve=2000)
        self.assertGreater(rep.tools_compressed, 0)
        self.assertLess(rep.tool_tokens, rep.tool_tokens_before)
        self.assertEqual(rep.tool_tokens_before, before)
        # all 60 tools still there, names intact, params intact
        self.assertEqual(len(new_tools), 60)
        names = [t["function"]["name"] for t in new_tools]
        self.assertEqual(names, [f"connector_tool_{i}" for i in range(60)])
        self.assertIn("arg", new_tools[0]["function"]["parameters"]["properties"])
        # and the whole thing now fits the window
        self.assertFalse(rep.over_budget)

    def test_fat_tools_plus_big_protected_turn_still_fits(self):
        # The qwopus-9 failure: 34K-ish tools + a big protected system/active turn overflowed
        # because the schema was irreducible. With tool-schema bounding it must fit.
        tools = _fat_tools(120, 900)
        msgs = [
            {"role": "system", "content": "S" * 40000},  # ~10K est protected system prompt
            _u("resolve an Ada handle and write tests"),  # active turn, protected
        ]
        out, new_tools, rep = contextfloor.fit(msgs, tools, window=49152, reserve=4096)
        self.assertGreater(rep.tools_compressed, 0)
        final_est = (rep.msg_tokens_after + rep.tool_tokens) * contextfloor.SAFETY_FACTOR
        self.assertLessEqual(final_est, 49152 - 4096)
        self.assertFalse(rep.over_budget)
        self.assertEqual(len(new_tools), 120)

    def test_reduces_oversized_tool_output_before_dropping_turns(self):
        big = ("This is a long sentence of prose that repeats. " * 400)
        msgs = [
            _u("task"),
            _a("", [{"id": "c1", "function": {"name": "web_fetch", "arguments": "{}"}}]),
            _tool("c1", big),
        ]
        before = est_tokens(big)
        out, tools, rep = contextfloor.fit(msgs, None, window=3000, reserve=500)
        self.assertEqual(rep.outputs_reduced, 1)
        self.assertEqual(rep.turns_dropped, 0)
        reduced = [m for m in out if m.get("role") == "tool"][0]["content"]
        self.assertLess(est_tokens(reduced), before)

    def test_orphan_tool_result_removed_when_assistant_dropped(self):
        msgs = [
            _a("Y" * 12000, [{"id": "c1", "function": {"name": "n", "arguments": "{}"}}]),
            _u("current"),
            _tool("c1", "r"),
        ]
        out, tools, rep = contextfloor.fit(msgs, None, window=3000, reserve=500)
        self.assertGreaterEqual(rep.turns_dropped, 1)
        self.assertEqual(rep.orphans_removed, 1)
        self.assertFalse(any(m.get("role") == "tool" for m in out))
        self.assertEqual(out[-1]["content"], "current")

    def test_over_budget_when_protected_turn_alone_exceeds_window(self):
        # A single giant active turn that can't be dropped and can't be tool-compressed away.
        msgs = [_u("Z" * 40000)]  # ~10K est, protected, only message
        out, tools, rep = contextfloor.fit(msgs, None, window=4000, reserve=500)
        self.assertTrue(rep.over_budget)  # surfaced, not hidden
        self.assertEqual(out[-1]["content"], "Z" * 40000)  # still sent

    def test_higher_safety_trims_harder(self):
        # When the caller measures a dense request (real >> chars/4) and passes a bigger safety
        # factor, the floor must trim more aggressively so the REAL prompt still fits.
        msgs = [_u("task"), _a("A" * 16000), _u("more"), _a("B" * 16000), _u("current")]
        _, _, lo = contextfloor.fit([dict(m) for m in msgs], None, window=8000, reserve=500, safety=1.3)
        _, _, hi = contextfloor.fit([dict(m) for m in msgs], None, window=8000, reserve=500, safety=2.6)
        self.assertGreater(hi.turns_dropped, lo.turns_dropped)
        self.assertLess(hi.msg_tokens_after, lo.msg_tokens_after)

    def test_est_total_and_content_text(self):
        msgs = [_u("hello world"), _a("more text here")]
        self.assertGreater(contextfloor.est_total(msgs, None), 0)
        self.assertIn("hello world", contextfloor.content_text(msgs, None))

    def test_reserve_for(self):
        self.assertEqual(contextfloor.reserve_for({"max_tokens": 2048}), 2048)
        self.assertEqual(contextfloor.reserve_for({}), contextfloor.DEFAULT_GEN_RESERVE)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": 0}), contextfloor.DEFAULT_GEN_RESERVE)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": None}), contextfloor.DEFAULT_GEN_RESERVE)

    def test_reserve_for_output_reserve_wins_over_max_tokens(self):
        # The two-knob split: the role's output_reserve is the input-side reserve and takes
        # precedence — so the reserve is generous and INDEPENDENT of the (usually unset) hard cap.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192}), 8192)
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192, "max_tokens": 256}), 8192)
        # The subtlety: with output_reserve set, a tiny/unset max_tokens can't collapse the reserve
        # (which is what re-truncated codex-local on the overflow retry). Uncapped coder → 8192.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192, "max_tokens": None}), 8192)
        # A bad/zero output_reserve falls through to the existing max_tokens/default behavior.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 0, "max_tokens": 2048}), 2048)
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": None}), contextfloor.DEFAULT_GEN_RESERVE)

    def test_pure_does_not_mutate_inputs(self):
        msgs = [_u("task"), _a("Z" * 12000), _u("current")]
        tools = _fat_tools(40, 500)
        msnap, tsnap = json.dumps(msgs), json.dumps(tools)
        contextfloor.fit(msgs, tools, window=8000, reserve=500)
        self.assertEqual(json.dumps(msgs), msnap)   # messages untouched
        self.assertEqual(json.dumps(tools), tsnap)  # tools untouched


if __name__ == "__main__":
    unittest.main()
