"""The engagement ladder: each level turns on exactly its own rung, and nothing above it.

WHY THIS TEST IS THE CONTRACT. The suite spent a campaign calling `[engagement] drive = false` "the
model on its own" while tool-menu curation fired 1,011 times inside those very runs, context
focus-trim 514, and the drop-oldest context floor 54. Nothing caught it because nothing asserted
what a level is allowed to do — the claim lived in a docstring, and a docstring cannot fail.

So the contract is stated as OBSERVED BEHAVIOUR, not as configuration: drive a real cria server at
each level and read its own event log. A mechanism that ran, logged. A level that lets something
above it through fails here, and the campaign never starts against a contaminated arm.

The families below are keyed to `cria.config` levels. Adding a mechanism means adding its event
kind to the rung that owns it; a kind nobody claims is a failure, not a pass, so a new mechanism
cannot slip in unassigned (see `test_every_logged_mechanism_is_claimed_by_a_rung`).
"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.request

from cria import config as cfgmod
from cria.config import (Backend, Config, ContextConfig, IndicatorsConfig, LoggingConfig,
                         PlannerConfig, Role, RoutingConfig, ServerConfig, UpstreamConfig)
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream

from test_server import _FakeUpstream, _serve   # the established end-to-end harness

# --- What each rung owns -------------------------------------------------------------------
# Prefixes, matched against the event `kind`. Everything at or below the running level may appear;
# anything above it appearing is the failure this file exists to catch.
RUNG_KINDS: dict[int, tuple[str, ...]] = {
    cfgmod.PURE_PROXY: (
        # Transport and OBSERVATION only. Measuring the context is not surgery on it; counting a cut
        # the harness already made is not making one.
        "http.access", "request.recv", "response.sent", "server.", "env.", "capture.",
        "upstream.", "usage.", "ctx.estimate", "context.window", "context.calibrated",
        "decision", "route.classify", "compat.", "harness.truncated_a_result",
        "config.warn",   # cria reporting on its OWN configuration; not a change to anything
    ),
    cfgmod.TOOL_CALL_FIXES: (
        # Making dialects homogeneous. NOT permission to change the toolset.
        "massage.", "indicators.stripped",
        # An orphaned `tool` message 400s a strict template every turn; converting it to `user` is
        # structural repair of a tool call, not surgery on what the conversation says.
        "context.deorphaned",
    ),
    cfgmod.SIMPLE_TOOLS: (
        "toolmenu.", "writeproxy.",
    ),
    cfgmod.CONTEXT_FIXES: (
        "context.floor", "context.focus_trim", "context.repeat_dedup", "context.ledger_dedup",
        "loop.compaction_reframed", "summarize.",
    ),
    cfgmod.DONE_REFUSALS_ENABLED: (
        # The driver EXISTING is level 4: below this rung there is no loop at all, so its start,
        # its per-step bookkeeping and its completion verdict all belong here.
        "loop.start", "loop.step_incomplete", "loop.item", "loop.drive",
        "loop.done_critic", "loop.completion_probe", "loop.task_complete",
        "loop.satisfaction_confirm", "loop.verdict_by_tool",
    ),
    cfgmod.ASSISTS_ENABLED: (
        "loop.",   # everything else the driver does
        "plan.",   # the planner and its rounds — decomposition is an assist
    ),
}


def allowed_prefixes(level: int) -> tuple[str, ...]:
    out: list[str] = []
    for rung in range(cfgmod.PURE_PROXY, level + 1):
        out.extend(RUNG_KINDS[rung])
    return tuple(out)


def owning_rung(kind: str) -> int | None:
    """The LOWEST rung whose prefixes claim this kind — level 5's bare `loop.` prefix would
    otherwise swallow the level-4 kinds that name themselves explicitly."""
    for rung in range(cfgmod.PURE_PROXY, cfgmod.MAX_ENGAGEMENT_LEVEL + 1):
        if any(kind.startswith(p) for p in RUNG_KINDS[rung]):
            return rung
    return None


class _Harness:
    """A real cria server in front of a fake upstream, at one level, planner on or off."""

    def __init__(self, level: int, planner: bool):
        self.tmp = TemporaryDirectory()
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        port = self.fake.server_address[1]
        # A coder AND a reasoner role, both pointed at the fake upstream, because the loop is only
        # built when a coder exists (and, with the planner on, a reasoner too). Without these the
        # top two rungs are unreachable and the test would pass by never running them — which is the
        # failure mode this whole file exists to prevent.
        base = f"http://127.0.0.1:{port}"
        backend = Backend(name="local", transport="http", base_url=base)
        # A classifier too: without one `_classify` returns None and a fresh turn never enters the
        # loop, so levels 4 and 5 would silently measure the proxy and report "this rung adds
        # nothing" about code that never ran.
        roles = {"coder": Role(name="coder", backend="local"),
                 "reasoner": Role(name="reasoner", backend="local"),
                 "classifier": Role(name="classifier", backend="local")}
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=base),
            logging=LoggingConfig(dir=self.tmp.name, capture_dir=self.tmp.name, console=False),
            indicators=IndicatorsConfig(enabled=False),
            planner=PlannerConfig(enabled=planner),
            # The periodic satisfaction check starts at drive 100 in production. A fixture that
            # cannot reach it would report "level 5 adds nothing" about the rung's most characteristic
            # mechanism, so the cadence is pulled to the first drive — the knob is operator-tunable
            # for exactly this reason.
            context=ContextConfig(satisfaction_check_start=1, satisfaction_check_every=1),
            routing=RoutingConfig(engagement_level=level, backends={"local": backend},
                                  roles=roles, defaults_base_url=base),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        # Built the way __main__ builds it: the level rides INTO the transport, because two rungs
        # (tool-call repair at 1, the context floor at 3) live on that path.
        self.cria = CriaServer(cfg, self.log,
                               Upstream(cfg.upstream.base_url, engagement_level=level))
        _serve(self.cria)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def close(self):
        for shut in (self.cria.shutdown, self.cria.server_close,
                     self.fake.shutdown, self.fake.server_close, self.log.close, self.tmp.cleanup):
            try:
                shut()
            except Exception:
                pass

    def post(self, body: dict, session: str = "sess-lvl"):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Cria-Session-Id": session})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def kinds(self) -> set[str]:
        assert self.log.path is not None
        return {json.loads(l)["kind"]
                for l in Path(self.log.path).read_text().splitlines() if l.strip()}


# A body that gives every rung something to do: tools to curate, a duplicate tool result to fold,
# and a completion claim to weigh.
def exercise_body() -> dict:
    return {
        "model": "m",
        "tools": [
            {"type": "function", "function": {"name": "shell", "description": "run a command",
                                              "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "read_file", "description": "read",
                                              "parameters": {"type": "object", "properties": {}}}},
        ],
        "messages": [
            {"role": "user", "content": "Fix the failing test in the repo, then stop."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "shell", "arguments": '{"command":"ls"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "a.py\nb.py"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c2", "type": "function",
                 "function": {"name": "shell", "arguments": '{"command":"ls"}'}}]},
            {"role": "tool", "tool_call_id": "c2", "content": "a.py\nb.py"},
            # A malformed tool_call in REPLAYED history: over-escaped nested quotes, the shape that
            # 500s a strict template on every later turn. Level 1 repairs it; level 0 must not.
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c3", "type": "function",
                 "function": {"name": "shell", "arguments": '{"command":"echo \\"hi\\" > x"'}}]},
            # …and an ORPHAN tool result, whose assistant call is gone. Also level 1.
            {"role": "tool", "tool_call_id": "gone", "content": "orphaned output"},
            {"role": "assistant", "content": "I am done — everything is finished."},
            {"role": "user", "content": "continue"},
        ],
    }


class LadderTests(unittest.TestCase):
    maxDiff = None

    def _run(self, level: int, planner: bool) -> set[str]:
        h = _Harness(level, planner)
        self.addCleanup(h.close)
        h.post(exercise_body())
        return h.kinds()

    def test_no_level_lets_a_higher_rung_through(self):
        for level in range(cfgmod.PURE_PROXY, cfgmod.MAX_ENGAGEMENT_LEVEL + 1):
            for planner in (False, True):
                with self.subTest(level=level, planner=planner):
                    seen = self._run(level, planner)
                    ok = allowed_prefixes(level)
                    leaked = sorted(k for k in seen if not any(k.startswith(p) for p in ok))
                    self.assertEqual(leaked, [], f"level {level} let a higher rung run: {leaked}")

    def test_every_logged_mechanism_is_claimed_by_a_rung(self):
        """A kind no rung claims is unassigned, and an unassigned mechanism is one that has never
        been decided about — which is exactly how the old baseline arm acquired seven of them."""
        seen = self._run(cfgmod.MAX_ENGAGEMENT_LEVEL, planner=True)
        unclaimed = sorted(k for k in seen if owning_rung(k) is None)
        self.assertEqual(unclaimed, [], f"event kinds belong to no rung: {unclaimed}")

    def test_levels_zero_to_four_ignore_the_planner(self):
        """Levels 0-4 must be indistinguishable with the planner on and off. Replanning and step
        re-derivation exist only when there are steps, so level 5 is allowed to differ; below it,
        a difference means a level gate was written inside a plan-on/plan-off branch."""
        for level in range(cfgmod.PURE_PROXY, cfgmod.DONE_REFUSALS_ENABLED + 1):
            with self.subTest(level=level):
                off = self._run(level, planner=False)
                on = self._run(level, planner=True)
                self.assertEqual(sorted(off), sorted(on),
                                 f"level {level} behaves differently with the planner on")

    def test_each_rung_actually_does_something(self):
        """A level that goes quiet is a bug, not a result. Every rung above the proxy must add at
        least one mechanism its predecessor did not run, or the ladder has a dead step and the
        campaign would report 'this layer is worth nothing' about code that never executed."""
        prev: set[str] = set()
        for level in range(cfgmod.PURE_PROXY, cfgmod.MAX_ENGAGEMENT_LEVEL + 1):
            seen = self._run(level, planner=False)
            if level > cfgmod.PURE_PROXY:
                with self.subTest(level=level):
                    self.assertTrue(seen - prev, f"level {level} added no mechanism over {level - 1}")
            prev = seen


if __name__ == "__main__":
    unittest.main()
