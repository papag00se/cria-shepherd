"""A rung gate is proven at the CALL SITE, not by hoping a fixture triggers the mechanism.

WHY THIS FILE EXISTS. `test_engagement_levels.py` reads a real server's event log, so it can only
see mechanisms that actually FIRE during one short request. Three leaks got past it that way: the
periodic gate (due every N acting turns), the wheel-spin detector (needs a repeated write) and
compaction reframing (needs the harness to compact, which needs a long session). Each ran at a rung
below its own for several cells while that file stayed green.

So these tests replace the mechanism with a recorder and assert whether the CALL happens, which does
not depend on the conditions that would make it fire. A mechanism that cannot be provoked in a
fixture can still be proven gated.
"""
from __future__ import annotations

import unittest
from unittest import mock

from cria import config as cfgmod
from cria import server as srv
from cria.config import Config, RoutingConfig


class _Rlog:
    phase = "test"

    def __init__(self):
        self.events = []

    def emit(self, name, **k):
        self.events.append((name, k))


def _handler(level: int):
    h = srv.CriaHandler.__new__(srv.CriaHandler)
    h.headers = {}
    h.server = type("S", (), {"cfg": Config(routing=RoutingConfig(engagement_level=level))})()
    return h


COMPACTION = [
    {"role": "user", "content": "<<<LOCAL_COMPACT>>>\nSummarize the thread for continuation."},
    {"role": "assistant", "content": "Earlier the coder edited lib/rates.rb and ran the suite."},
]


class CompactionReframingIsLevelThree(unittest.TestCase):
    """Reattributing the harness's compaction turn REWRITES a message the harness wrote. That is
    surgery on the context, so it belongs to CONTEXT_FIXES — not to the pure proxy, where it ran
    until 2026-08-25 because a level-0 session is too short for the harness to ever compact."""

    def _calls_at(self, level: int) -> int:
        seen = []

        def _recorder(msgs):
            seen.append(msgs)
            return msgs, 0

        h = _handler(level)
        with mock.patch.object(srv, "reframe_compaction", _recorder):
            with mock.patch.object(srv, "strip_history", lambda m: (m, 0)):
                with mock.patch.object(h, "_bind_workspace_view", lambda *a, **k: None):
                    body = {"messages": list(COMPACTION)}
                    srv.CriaHandler._strip_and_reframe_inbound(h, body, "sid:test", _Rlog())
        return len(seen)

    def test_it_does_not_run_below_context_fixes(self):
        for level in range(cfgmod.PURE_PROXY, cfgmod.CONTEXT_FIXES):
            with self.subTest(level=level):
                self.assertEqual(self._calls_at(level), 0,
                                 f"compaction reframing ran at level {level}")

    def test_it_runs_at_context_fixes_and_above(self):
        for level in range(cfgmod.CONTEXT_FIXES, cfgmod.MAX_ENGAGEMENT_LEVEL + 1):
            with self.subTest(level=level):
                self.assertEqual(self._calls_at(level), 1,
                                 f"compaction reframing did NOT run at level {level}")



class OutputMassagesAreLevelOne(unittest.TestCase):
    """The output massage chain — dialect recovery, fused-tail trimming, tool-name normalisation,
    argument repair — is TOOL_CALL_FIXES. It ran at every level until 2026-08-25, and gemma4 never
    exposed it because it emits six of these in a whole campaign. qwen35's first level-0 cell logged
    66 `massage.reasoning_call_recovered`: level 1's headline mechanism, in the arm defined as being
    without it. Running more than one model is what found it."""

    def _leaky(self):
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "",
            "reasoning_content": "<|tool_call_start|>[read_file(path=\"a.py\")]<|tool_call_end|>"}}]}

    TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "read",
                                               "parameters": {"type": "object",
                                                              "properties": {"path": {"type": "string"}}}}}]

    def test_the_chain_is_inert_when_tool_call_fixes_is_off(self):
        from cria import massage
        out = massage.apply(self._leaky(), self.TOOLS, None, tool_call_fixes=False)
        self.assertNotIn("tool_calls", out["choices"][0]["message"],
                         "a dialect leak was promoted at a level that has no dialect repair")

    def test_the_chain_runs_when_it_is_on(self):
        from cria import massage
        out = massage.apply(self._leaky(), self.TOOLS, None, tool_call_fixes=True)
        self.assertIn("tool_calls", out["choices"][0]["message"],
                      "level 1 must still recover a call the model left in the reasoning channel")

    def test_the_server_sets_it_from_the_level(self):
        """One process-wide flag, set at construction — not threaded through seven call sites."""
        from cria import massage
        for level, want in ((cfgmod.PURE_PROXY, False), (cfgmod.TOOL_CALL_FIXES, True),
                            (cfgmod.MAX_ENGAGEMENT_LEVEL, True)):
            with self.subTest(level=level):
                massage.set_tool_call_fixes(Config(routing=RoutingConfig(
                    engagement_level=level)).routing.tool_call_fixes)
                out = massage.apply(self._leaky(), self.TOOLS, None)
                self.assertEqual("tool_calls" in out["choices"][0]["message"], want)
        massage.set_tool_call_fixes(True)   # leave the process as we found it

if __name__ == "__main__":
    unittest.main()
