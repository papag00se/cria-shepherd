"""C37: a harness's OWN compaction/summarize request (no `<<<LOCAL_COMPACT>>>` marker wired) was
never recognized, so `_harden_compaction_reply`'s validator, appendices, and empty-briefing retry
never ran on it — cria classified it as an ordinary coding task and proxied it raw.

Evidence: p27 shipping capture CALL0046 (Codex's default compaction prompt, `tools: []`) was
classified `engagement=task` and its reply invented a gem/API that the continuation carried forward
as fact (Candidate C37). The captured body is kept as tests/fixtures/codex_unmarked_compaction_call0046.json.

`server._recognize_compaction` is harness-agnostic recognition: the deterministic trigger (empty/
absent tool menu, LEVEL 3 enabled, a prior assistant/tool turn already in the transcript) narrows the
field for free; only a genuine remainder ever reaches ONE focused closed reasoner question. The
marker path (`_is_compaction_request`) is untouched and always wins for free.
"""

from __future__ import annotations

import json
import types
import unittest
from pathlib import Path

from cria import server
from cria.config import Backend, Config, IndicatorsConfig, LoggingConfig, Role, RoutingConfig, ServerConfig, UpstreamConfig


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [kind for kind, _fields in self.events]


class _WordChat:
    """A reasoner that answers a fixed word to any closed question, and records every call."""

    def __init__(self, word: str):
        self.word = word
        self.calls = 0

    def __call__(self, body, _rlog):
        self.calls += 1
        return json.dumps({"choices": [{"message": {"content": self.word}}]}).encode()


class _RaisingChat:
    """A reasoner that must never be called — proves the deterministic gates are truly free."""

    def __call__(self, body, _rlog):
        raise AssertionError("reasoner must not be called for this body")


_A_REASONER = Role(name="reasoner", backend="local")


def _server(*, context_fixes_level=None, reasoner_chat=None, reasoner_role=_A_REASONER):
    # `reasoner_role` defaults to a real role — a server with NO reasoner configured at all
    # (`reasoner_role=None`, B2) must be requested explicitly, since that is itself the fail-safe
    # case under test, not the default shape of a configured server.
    from cria.config import CONTEXT_FIXES
    lvl = context_fixes_level if context_fixes_level is not None else CONTEXT_FIXES
    cfg = types.SimpleNamespace(
        routing=types.SimpleNamespace(
            roles={}, context_fixes=lvl >= CONTEXT_FIXES))
    return types.SimpleNamespace(
        cfg=cfg,
        reasoner_upstream=types.SimpleNamespace(chat=reasoner_chat),
        reasoner_role=reasoner_role,
    )


CODEX_COMPACTION_ASK = (
    "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM "
    "that will resume the task.\n\nInclude:\n- Current progress and key decisions made\n- Important "
    "context, constraints, or user preferences\n- What remains to be done (clear next steps)\n- Any "
    "critical data, examples, or references needed to continue\n\nBe concise, structured, and "
    "focused on helping the next LLM seamlessly continue the work.\n"
)


def _mid_session_body(ask: str, *, tools=None) -> dict:
    msgs = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "build the shipping calculator"},
        {"role": "assistant", "content": "Working on it.",
         "tool_calls": [{"id": "c1", "type": "function",
                          "function": {"name": "write_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "wrote a.py"},
        {"role": "user", "content": ask},
    ]
    body = {"model": "codex", "messages": msgs}
    if tools is not None:
        body["tools"] = tools
    return body


class UnmarkedCompactionIsRecognizedTests(unittest.TestCase):
    """(a) An empty-tools compaction request with no marker IS recognized (and thus hardened)."""

    def test_empty_tools_absent_key_is_recognized_when_judge_says_yes(self):
        chat = _WordChat("YES")
        srv = _server(reasoner_chat=chat)
        body = _mid_session_body(CODEX_COMPACTION_ASK)  # no "tools" key at all, like the capture
        self.assertTrue(server._recognize_compaction(body, srv, _Rlog()))
        self.assertEqual(chat.calls, 1)

    def test_empty_tools_list_is_recognized_when_judge_says_yes(self):
        chat = _WordChat("YES")
        srv = _server(reasoner_chat=chat)
        body = _mid_session_body(CODEX_COMPACTION_ASK, tools=[])
        self.assertTrue(server._recognize_compaction(body, srv, _Rlog()))

    def test_recognized_unmarked_turn_routes_and_skips_the_classifier_like_the_marker_does(self):
        """The recognition result is not just a private answer — `_classify`/`_route` treat it
        exactly like the marker: no classifier call, straight to the compactor endpoint/role."""
        chat = _WordChat("YES")
        srv = _server(reasoner_chat=chat)
        srv.cfg.routing.roles = {"reasoner": Role(name="reasoner", backend="local")}
        compactor_up = object()
        srv.compactor_upstream = compactor_up
        srv.classifier = types.SimpleNamespace(
            classify=lambda *a, **k: (_ for _ in ()).throw(AssertionError("classifier must not run")))
        srv.upstream = object()

        h = server.CriaHandler.__new__(server.CriaHandler)
        h.server = srv
        rlog = _Rlog()
        body = _mid_session_body(CODEX_COMPACTION_ASK)

        compaction = server._recognize_compaction(body, srv, rlog)
        self.assertTrue(compaction)
        self.assertIsNone(h._classify(body, rlog, compaction))
        self.assertIn("classify.skipped", rlog.kinds())

        srv.cfg.indicators = types.SimpleNamespace(enabled=True, metrics=True, route=True, assists=True)
        srv.router = None
        provider, indic = h._route(body, None, rlog, compaction)
        self.assertIs(provider, compactor_up)
        self.assertEqual(indic.role, "reasoner")


class OrdinaryRequestsAreUnaffectedTests(unittest.TestCase):
    """(b) An ordinary request with tools present is byte-identical to before: no extra call."""

    def test_tools_present_never_asks_the_reasoner(self):
        srv = _server(reasoner_chat=_RaisingChat())
        body = _mid_session_body("add a --json flag to the CLI", tools=[{"type": "function",
                                                                          "function": {"name": "write_file"}}])
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))

    def test_fresh_session_first_turn_never_asks_the_reasoner(self):
        """No prior assistant/tool turn: structurally cannot be a checkpoint of nothing, so the
        cheap trigger alone excludes it — no call, however the lone turn is worded."""
        srv = _server(reasoner_chat=_RaisingChat())
        body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))

    def test_context_fixes_disabled_never_asks_the_reasoner(self):
        """Below LEVEL 3 the hardening this recognizer feeds is unreachable; asking would be a
        wasted call with no possible effect."""
        from cria.config import CONTEXT_FIXES
        srv = _server(context_fixes_level=CONTEXT_FIXES - 1, reasoner_chat=_RaisingChat())
        body = _mid_session_body(CODEX_COMPACTION_ASK)
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))

    def test_marker_path_is_unchanged_and_free(self):
        srv = _server(reasoner_chat=_RaisingChat())
        body = _mid_session_body("<<<LOCAL_COMPACT>>> Summarize the thread.")
        self.assertTrue(server._recognize_compaction(body, srv, _Rlog()))


class FailSafeDirectionTests(unittest.TestCase):
    """(c) A judge NO or an undecidable answer both mean "not recognized" — the turn proxies
    exactly as before this recognizer existed. The opposite failure (hardening an ordinary no-tool
    reply) is judged the greater footgun; see `_recognize_compaction`'s docstring."""

    def test_judge_no_is_not_recognized(self):
        srv = _server(reasoner_chat=_WordChat("NO"))
        body = _mid_session_body(CODEX_COMPACTION_ASK)
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))

    def test_judge_unreadable_answer_is_not_recognized(self):
        srv = _server(reasoner_chat=_WordChat("uh, maybe? unsure"))
        body = _mid_session_body(CODEX_COMPACTION_ASK)
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))

    def test_no_reasoner_configured_is_not_recognized(self):
        """B2 (independent review): `server.reasoner_role is None` (no [roles.reasoner] table at
        all) must short-circuit BEFORE any call — `server.reasoner_upstream` still resolves (it
        falls back to the shared/coder endpoint unconditionally), so without this guard the
        question would silently reach the CODER model instead of failing safe. A reasoner that
        WOULD answer YES proves the guard fires on the missing role, not on the answer."""
        chat = _WordChat("YES")
        srv = _server(reasoner_chat=chat, reasoner_role=None)
        body = _mid_session_body(CODEX_COMPACTION_ASK)
        self.assertFalse(server._recognize_compaction(body, srv, _Rlog()))
        self.assertEqual(chat.calls, 0, "the reasoner must not be called with no reasoner configured")


class P27Call0046ReplayTests(unittest.TestCase):
    """Offline replay of the real shipping capture (now a fixture) cited in the evidence: CALL0046, Codex's default
    compaction prompt, `tools` absent from the body entirely. No live model touched — the judge is a
    deterministic stand-in that says YES exactly as a working reasoner would for this turn."""

    CAPTURE = Path(__file__).parent / "fixtures" / "codex_unmarked_compaction_call0046.json"

    def test_call0046_body_is_recognized(self):
        captured = json.loads(self.CAPTURE.read_text())
        body = captured["body"]
        self.assertNotIn("tools", body)  # confirms the deterministic trigger the evidence cites

        chat = _WordChat("YES")
        srv = _server(reasoner_chat=chat)
        rlog = _Rlog()
        self.assertTrue(server._recognize_compaction(body, srv, rlog))
        self.assertEqual(chat.calls, 1)
        # Before this candidate, nothing distinguished this body from an ordinary task: it carried
        # no marker, so `_is_compaction_request` (the ONLY recognizer that existed) said False.
        self.assertFalse(server._is_compaction_request(body.get("messages", [])))


class Call0046HardeningEndToEndTests(unittest.TestCase):
    """B1 (independent review, a23a9ae6 REJECTED): Codex's own compaction instruction ("...What
    remains to be done (clear next steps)...") stayed in the WRITER evidence, the empty-briefing
    retry's evidence, and the validator's transcript, because `_compaction_messages` only ever
    dropped a request turn by matching `LOCAL_COMPACT_MARKER` text — the unmarked path (Codex's
    default `compact_prompt`) carries no marker at all. `_compaction_messages` now excludes the
    request turn BY POSITION (the latest user turn), so this replays the real p27 CALL0046 body
    through `_compaction_body` and `_harden_compaction_reply` with fake upstreams (no live model
    touched) and proves the ask is gone from every evidence channel and cria's own ask is last —
    exactly the invariant `tests/test_server.py::...ask_is_last_and_the_summarize_turn_is_not_
    evidence` already holds for the MARKED case (the g8 0187/0188 incident)."""

    CAPTURE = Path(__file__).parent / "fixtures" / "codex_unmarked_compaction_call0046.json"
    # "What remains to be done" alone is a bad needle: cria's OWN briefing prompt uses that exact
    # phrase too ("...requirements only, not a next-step plan)"). Codex's ask is distinctive in its
    # HEADING and its own parenthetical, which cria's prompt does not share.
    CODEX_ASK_NEEDLES = ("CONTEXT CHECKPOINT COMPACTION", "handoff summary for another LLM",
                        "(clear next steps)")

    class _Srv:
        class cfg:
            class routing:
                roles = {"reasoner": Role(name="reasoner", backend="local")}

    class _Rlog:
        phase = "proxy"

        def emit(self, kind, **kw):
            return self

    def _body(self) -> dict:
        return json.loads(self.CAPTURE.read_text())["body"]

    def test_writer_body_excludes_the_codex_ask_and_ends_on_crias_own_ask(self):
        from cria.server import _compaction_body, _proxy_body
        body = self._body()
        self.assertNotIn("tools", body)  # the deterministic trigger the evidence cites

        pb = _compaction_body(_proxy_body(body))

        blob = "\n".join(str(m.get("content", "") or "") for m in pb["messages"])
        for needle in self.CODEX_ASK_NEEDLES:
            self.assertNotIn(needle, blob, "Codex's ask leaked into the writer's evidence")
        self.assertIn("Write the briefing now", pb["messages"][-1]["content"])  # cria's ask IS last

    def test_retry_and_validator_evidence_both_exclude_the_codex_ask(self):
        from test_server import _compaction_validation_verdict

        from cria.server import _harden_compaction_reply

        body = self._body()
        calls: list[dict] = []

        class _Provider:
            @staticmethod
            def chat(pb, rlog):
                calls.append(pb)
                sysm = (pb.get("messages") or [{}])[0].get("content", "") or ""
                verdict = _compaction_validation_verdict(sysm)
                text = verdict or "Fixed the shipping module's EU detection."
                return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]})

        # Force the empty-briefing retry so its evidence is exercised too (the first pass's own
        # reply is deliberately empty — exactly the B3 0094 shape `_harden_compaction_reply`'s (1)
        # hardening exists for).
        empty_comp = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        comp = _harden_compaction_reply(empty_comp, body, provider=_Provider,
                                        server=self._Srv, rlog=self._Rlog())

        self.assertGreaterEqual(len(calls), 2, "neither the retry nor the validator ran")
        for pb in calls:
            blob = "\n".join(str(m.get("content", "") or "") for m in pb.get("messages", []))
            for needle in self.CODEX_ASK_NEEDLES:
                self.assertNotIn(needle, blob, "Codex's ask leaked into evidence cria sent")

        text = comp["choices"][0]["message"]["content"]
        for needle in self.CODEX_ASK_NEEDLES:
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
