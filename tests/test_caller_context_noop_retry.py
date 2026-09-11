"""A caller may suppress exactly one retry only after the wire proves it is identical.

The historical caller repeated a compactor request after the inner refit had already parsed a
context error and declined to resend identical bytes.  This test drives real Role.apply, normal
Upstream._prep, capture, context state, chat_watched, summarize, and both evidence builders.  The
fake is transport only; it supplies model discovery, a server context error, and tiny SSE replies.
"""

from __future__ import annotations

import io
import json
import tempfile
import types
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest import mock

from cria import bodykeys, loop, tokenratio
from cria.config import Backend, Role
from cria.plan import Plan
from cria.upstream import Upstream


WINDOW = 49_152
MODEL = "fixture-local-model"
BACKEND = Backend(name="local", transport="http", base_url="http://fixture.invalid")
OFF = Role(name="compactor", backend="local", think_protocol="chat_template",
           reasoning="off", temperature=0.0)


class _Rlog:
    def __init__(self, session):
        self.session, self.turn, self.phase = session, "context-retry", ""
        self.events = []

    def emit(self, kind, **kwargs):
        self.events.append((kind, kwargs))

    def named(self, kind):
        return [kwargs for name, kwargs in self.events if name == kind]


class _BytesResponse:
    def __init__(self, value):
        self._raw = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self):
        return self._raw


class _SSE:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass


def _sse(value):
    return b"data: " + json.dumps(value).encode("utf-8") + b"\n"


def _reply(text):
    return _SSE([_sse({"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}),
                 b"data: [DONE]\n"])


def _context(url):
    return urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(json.dumps({"error": {
        "n_prompt_tokens": 90_000, "n_ctx": WINDOW,
        "message": "request exceeds available context",
    }}).encode("utf-8")))


def _other_400(url):
    return urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(json.dumps({"error": {
        "message": "malformed request",
    }}).encode("utf-8")))


class _Transport:
    """Only the HTTP boundary is fake; request construction belongs to real owners."""

    def __init__(self, mode):
        self.mode, self.posts, self.calls = mode, [], 0

    def open(self, req, timeout=None):
        url = req.full_url
        if url.endswith("/v1/models"):
            return _BytesResponse({"data": [{"id": MODEL}]})
        if url.endswith("/props"):
            return _BytesResponse({"default_generation_settings": {}})
        if not url.endswith("/v1/chat/completions"):
            raise AssertionError(url)
        self.posts.append(bytes(req.data or b""))
        self.calls += 1
        if self.mode == "context":
            raise _context(url)
        if self.mode == "context_then_summary":
            if self.calls == 1:
                raise _context(url)
            return _reply("recovered summary")
        if self.mode == "context_refit_empty_then_outer_summary":
            # Initial outer POST overflows.  Real _open_with_refit sends a changed
            # inner body after normal floor state evolves; its empty successful
            # answer makes summarize open the ordinary same-role outer retry.
            if self.calls == 1:
                raise _context(url)
            if self.calls == 2:
                return _reply("")
            if self.calls == 3:
                return _reply("recovered summary")
            raise AssertionError("unexpected post after successful outer retry")
        if self.mode == "empty_then_summary":
            return _reply("") if self.calls == 1 else _reply("recovered summary")
        if self.mode == "transient_then_summary":
            if self.calls == 1:
                raise urllib.error.URLError("temporary fixture failure")
            return _reply("recovered summary")
        if self.mode == "other_400_then_summary":
            if self.calls == 1:
                raise _other_400(url)
            return _reply("recovered summary")
        if self.mode == "summary":
            return _reply("recovered summary")
        raise AssertionError(self.mode)


def _messages():
    return [
        {"role": "assistant", "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "exec_command", "arguments": '{"cmd":"inspect"}'},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": "x" * 60_001},
    ]


class CallerContextNoopRetryTests(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()
        self.captures = Path(tempfile.mkdtemp(prefix="cria-context-retry-"))

    def tearDown(self):
        tokenratio.reset()

    def _upstream(self):
        return Upstream(BACKEND.base_url, timeout_seconds=1, context_window=None,
                        capture_dir=self.captures, capture_rendered=False, engagement_level=5)

    def _satisfaction(self, up, tr, rlog, role=OFF):
        with mock.patch("cria.upstream.urllib.request.urlopen", tr.open):
            return loop._satisfaction_evidence(_messages(), rlog=rlog,
                                               chat_fn=up.chat_watched, role=role)

    def _grounded(self, up, tr, rlog):
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = types.SimpleNamespace(reasoner_chat=up.chat_watched,
                                        reasoner_role=Role(name="reasoner", backend="local"),
                                        compactor_role=OFF)
        sess = loop.PlanSession(plan=Plan(id="p", task="t", created="now", items=[]))
        sess.workspace_root = ""
        with mock.patch("cria.upstream.urllib.request.urlopen", tr.open):
            return lp._grounded_evidence(sess, {"messages": _messages()}, rlog)

    def _captured_bodies(self):
        return [json.loads(path.read_text(encoding="utf-8"))["body"]
                for path in sorted(self.captures.rglob("*.json"))
                if not path.name.endswith(".response.json")]

    def _assert_suppressed_context(self, evidence, tr, rlog):
        self.assertEqual(len(tr.posts), 1)
        self.assertIn("x" * 60_001, evidence)  # unavailable remains the whole original evidence
        self.assertTrue(rlog.named("context.refit"))
        self.assertTrue(rlog.named("upstream.refit_no_change"))
        self.assertTrue(rlog.named("upstream.caller_retry_no_change"))
        self.assertTrue(rlog.named("summarize.context_retry_no_change"))
        self.assertEqual(len(rlog.named("upstream.error")), 1)  # original rejected POST remains recorded
        self.assertEqual(len(rlog.named("summarize.error")), 1)
        bodies = self._captured_bodies()
        self.assertGreaterEqual(len(bodies), 2)  # sent initial + unsent inner/outer preflights
        self.assertTrue(all(bodykeys.CONTEXT_REFIT_NO_CHANGE not in body for body in bodies))
        self.assertEqual(json.loads(tr.posts[0]), bodies[0])

    def test_satisfaction_suppresses_only_the_typed_same_wire_outer_retry(self):
        up, tr, rlog = self._upstream(), _Transport("context"), _Rlog("satisfaction")
        evidence = self._satisfaction(up, tr, rlog)
        self._assert_suppressed_context(evidence, tr, rlog)

    def test_grounded_evidence_uses_the_same_shared_suppression_owner(self):
        up, tr, rlog = self._upstream(), _Transport("context"), _Rlog("grounded")
        evidence = self._grounded(up, tr, rlog)
        self._assert_suppressed_context(evidence, tr, rlog)

    def test_changed_forced_off_final_wire_after_context_still_posts_and_recovers(self):
        up, tr, rlog = self._upstream(), _Transport("context_then_summary"), _Rlog("changed")
        evidence = self._satisfaction(up, tr, rlog, replace(OFF, reasoning="on"))
        self.assertEqual(len(tr.posts), 2)
        self.assertNotEqual(tr.posts[0], tr.posts[1])
        self.assertTrue(rlog.named("context.refit"))
        self.assertTrue(rlog.named("upstream.refit_no_change"))
        self.assertFalse(rlog.named("upstream.caller_retry_no_change"))
        self.assertIn("recovered summary", evidence)

    def test_same_role_state_changed_final_wire_after_context_refit_still_retries(self):
        """Normal floor state, not role fields, can make the later final wire different.

        The composed-evidence path supplies two legal middle evidence messages.  A real server
        context error makes the actual owner learn window/density; normal floor fitting first drops
        two blocks for the inner refit, then one for the same-role outer retry.  The candidate must
        not suppress that different final wire.
        """
        up = self._upstream()
        tr = _Transport("context_refit_empty_then_outer_summary")
        rlog = _Rlog("same-role-state-change")
        blocks = [
            "historical evidence alpha\n" + "A" * 36_000,
            "historical evidence beta\n" + "B" * 36_000,
        ]
        with mock.patch("cria.upstream.urllib.request.urlopen", tr.open):
            evidence = loop.summarize(
                up.chat_watched, OFF,
                "Summarize the supplied historical evidence without adding facts.",
                "Return a concise retrospective summary.",
                rlog, phase="compactor", evidence_blocks=blocks,
            )

        self.assertEqual(len(tr.posts), 3)
        requests = rlog.named("upstream.request")
        self.assertEqual([event["refit"] for event in requests], [False, True, False])
        self.assertNotEqual(tr.posts[0], tr.posts[1])
        self.assertNotEqual(tr.posts[0], tr.posts[2])
        self.assertNotEqual(tr.posts[1], tr.posts[2])
        self.assertTrue(rlog.named("context.refit"))
        self.assertFalse(rlog.named("upstream.refit_no_change"))
        self.assertFalse(rlog.named("upstream.caller_retry_no_change"))
        self.assertTrue(rlog.named("context.floor_skipped"))
        self.assertTrue(any(event.get("source") == "server-error"
                            for event in rlog.named("context.window")))
        self.assertEqual([event["turns_dropped"] for event in rlog.named("context.floor")], [2, 1])
        self.assertIn("recovered summary", evidence)
        final_bodies = [json.loads(post) for post in tr.posts]
        self.assertEqual(final_bodies, self._captured_bodies())
        self.assertTrue(all(body["chat_template_kwargs"]["enable_thinking"] is False
                            for body in final_bodies))
        self.assertTrue(all(body["temperature"] == 0.0 for body in final_bodies))

    def test_empty_transient_and_noncontext_failures_retain_existing_retries(self):
        for mode in ("empty_then_summary", "transient_then_summary", "other_400_then_summary"):
            with self.subTest(mode=mode):
                up, tr, rlog = self._upstream(), _Transport(mode), _Rlog(mode)
                evidence = self._satisfaction(up, tr, rlog)
                self.assertEqual(len(tr.posts), 2)
                self.assertEqual(tr.posts[0], tr.posts[1])
                self.assertFalse(rlog.named("upstream.caller_retry_no_change"))
                self.assertIn("recovered summary", evidence)

    def test_typed_hint_is_single_retry_lifetime_not_cross_invocation_state(self):
        up = self._upstream()
        first, first_log = _Transport("context"), _Rlog("first")
        first_evidence = self._satisfaction(up, first, first_log)
        self._assert_suppressed_context(first_evidence, first, first_log)

        second, second_log = _Transport("summary"), _Rlog("second")
        second_evidence = self._satisfaction(up, second, second_log)
        self.assertEqual(len(second.posts), 1)
        self.assertFalse(second_log.named("upstream.caller_retry_no_change"))
        self.assertIn("recovered summary", second_evidence)


if __name__ == "__main__":
    unittest.main()
