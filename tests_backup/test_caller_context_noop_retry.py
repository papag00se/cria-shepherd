"""A caller may suppress exactly one retry only after the wire proves it is identical.

The historical caller repeated a compactor request after the inner refit had already parsed a
context error and declined to resend identical bytes. Evidence builders now fold without
inference, but summarize's caller retry contract survives for actual summary work. Drive that
shared caller directly through real Role.apply, Upstream._prep, capture, context state and
chat_watched. Separate builder controls preserve source custody without entering transport.
The fake supplies only HTTP discovery, context errors and tiny SSE replies.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from memory_http import MemoryTransport, Reply, json_reply, stream_reply

from cria import assistruntime, bodykeys, evidencesummary, loop, tokenratio
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


def _sse(value):
    return b"data: " + json.dumps(value).encode("utf-8") + b"\n"


def _reply(text):
    return stream_reply([_sse({"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}),
                         b"data: [DONE]\n"])


def _context(url, real=45_000):
    # The input still fits; the backend can reject the combined generation request.
    # No-change controls must not depend on serializing known-oversized input.
    return json_reply({"error": {
        "n_prompt_tokens": real, "n_ctx": WINDOW,
        "message": "request exceeds available context",
    }}, status=400)


def _other_400(url):
    return json_reply({"error": {"message": "malformed request"}}, status=400)


class _Transport:
    """Only the HTTP boundary is fake; request construction belongs to real owners."""

    def __init__(self, mode):
        self.mode, self.posts, self.calls = mode, [], 0
        self.template_requests = []

    def open(self, req, timeout=None):
        url = req.full_url
        if url.endswith("/v1/models"):
            return json_reply({"data": [{"id": MODEL}]})
        if url.endswith("/props"):
            return json_reply({"default_generation_settings": {}})
        if url.endswith("/apply-template"):
            # Native capacity probes are legitimate after a server context error.
            # Model an endpoint without native templating, rather than accidentally
            # failing this fixture and accepting its unrelated AssertionError.
            self.template_requests.append(bytes(req.data or b""))
            return json_reply({"error": {"message": "native templating unavailable"}}, status=404)
        if not url.endswith("/v1/chat/completions"):
            raise AssertionError(url)
        self.posts.append(bytes(req.data or b""))
        self.calls += 1
        if self.mode == "context":
            return _context(url)
        if self.mode == "unfittable_context":
            return _context(url, real=90_000)
        if self.mode == "context_then_summary":
            if self.calls == 1:
                return _context(url)
            return _reply("recovered summary")
        if self.mode == "context_refit_empty_then_outer_summary":
            # Initial outer POST overflows.  Real _open_with_refit sends a changed
            # inner body after normal floor state evolves; its empty successful
            # answer makes summarize open the ordinary same-role outer retry.
            if self.calls == 1:
                return _context(url, real=90_000)
            if self.calls == 2:
                return _reply("")
            if self.calls == 3:
                return _reply("recovered summary")
            raise AssertionError("unexpected post after successful outer retry")
        if self.mode == "empty_then_summary":
            return _reply("") if self.calls == 1 else _reply("recovered summary")
        if self.mode == "transient_then_summary":
            if self.calls == 1:
                return Reply(b"", connect_error=OSError("temporary fixture failure"))
            return _reply("recovered summary")
        if self.mode == "other_400_then_summary":
            if self.calls == 1:
                return _other_400(url)
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
        self.captures = Path(tempfile.mkdtemp(prefix="context-retry-"))

    def tearDown(self):
        tokenratio.reset()

    def _upstream(self, *, expect_chat=True):
        transport = MemoryTransport()
        self.addCleanup(transport.assert_served if expect_chat else transport.assert_closed)
        return Upstream(BACKEND.base_url, timeout_seconds=1, context_window=None,
                        capture_dir=self.captures, capture_rendered=False, engagement_level=5,
                        open_request=transport)

    def _summary(self, up, tr, rlog, role=OFF):
        # The original repeated-compactor incident is now asserted at its surviving
        # shared caller, not resurrected through fold-only evidence selection.
        with up._receive_open.respond_with(tr.open):
            return loop.summarize(
                up.chat_watched, role,
                "Summarize the supplied historical evidence without adding facts.",
                loop._work_log(_messages()), rlog, phase="compactor")

    def _satisfaction(self, up, tr, rlog, role=OFF):
        with up._receive_open.respond_with(tr.open):
            return loop._satisfaction_evidence(_messages(), rlog=rlog,
                                               chat_fn=up.chat_watched, role=role)

    def _grounded(self, up, tr, rlog):
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = types.SimpleNamespace(reasoner_chat=up.chat_watched,
                                        reasoner_role=Role(name="reasoner", backend="local"),
                                        compactor_role=OFF)
        sess = loop.PlanSession(plan=Plan(id="p", task="t", created="now", items=[]))
        sess.workspace_root = ""
        with up._receive_open.respond_with(tr.open):
            return lp._grounded_evidence(sess, {"messages": _messages()}, rlog)

    def _captured_bodies(self, rlog):
        # Receive receipts are JSON too, but are not model request captures.
        # The authoritative dump event also includes unsent retry preflights.
        return [json.loads(Path(event["path"]).read_text(encoding="utf-8"))["body"]
                for event in rlog.named("upstream.dump")]

    def _assert_suppressed_context(self, evidence, tr, rlog):
        self.assertEqual(len(tr.posts), 1)
        self.assertEqual(evidence, "")  # unavailable summary cannot claim a result
        self.assertTrue(rlog.named("context.refit"))
        self.assertTrue(rlog.named("upstream.refit_no_change"))
        self.assertTrue(rlog.named("upstream.caller_retry_no_change"))
        self.assertTrue(rlog.named("summarize.context_retry_no_change"))
        self.assertEqual(len(rlog.named("upstream.error")), 1)  # original rejected POST remains recorded
        self.assertEqual(len(rlog.named("summarize.error")), 1)
        bodies = self._captured_bodies(rlog)
        self.assertGreaterEqual(len(bodies), 2)  # sent initial + unsent inner/outer preflights
        self.assertTrue(all(bodykeys.CONTEXT_REFIT_NO_CHANGE not in body for body in bodies))
        self.assertEqual(json.loads(tr.posts[0]), bodies[0])
        self.assertIn("x" * 60_001, bodies[0]["messages"][-1]["content"])
        self.assertTrue(all(bodykeys.CONTEXT_REFIT_NO_CHANGE not in json.loads(post)
                            for post in tr.posts))

    def test_shared_summary_suppresses_only_the_typed_same_wire_outer_retry(self):
        up, tr, rlog = self._upstream(), _Transport("context"), _Rlog("satisfaction")
        evidence = self._summary(up, tr, rlog)
        self._assert_suppressed_context(evidence, tr, rlog)

    def test_evidence_builders_keep_whole_source_without_entering_summary_transport(self):
        for kind in ("satisfaction", "grounded"):
            with self.subTest(kind=kind):
                up = self._upstream(expect_chat=False)
                tr, rlog = _Transport("summary"), _Rlog(kind)
                with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
                    evidence = getattr(self, "_" + kind)(up, tr, rlog)
                self.assertIn("x" * 60_001, evidence)
                self.assertIn('[tool call id: "call-1"]', evidence)
                self.assertIn('[tool result call id: "call-1"]', evidence)
                self.assertNotIn("recovered summary", evidence)
                self.assertEqual(tr.posts, [])
                self.assertEqual(up._receive_open.calls, [])
                self.assertEqual(self._captured_bodies(rlog), [])
                self.assertFalse(rlog.named("summarize.context_retry_no_change"))
                self.assertFalse(rlog.named("evidence.summarised"))


    def test_known_unfittable_protected_evidence_is_not_posted_again(self):
        up, tr, rlog = self._upstream(), _Transport("unfittable_context"), _Rlog("unfittable")
        evidence = self._summary(up, tr, rlog, replace(OFF, reasoning="on"))
        self.assertEqual(len(tr.posts), 1)
        self.assertEqual(evidence, "")
        self.assertIn("x" * 60_001, self._captured_bodies(rlog)[0]["messages"][-1]["content"])
        self.assertTrue(rlog.named("context.refit"))
        self.assertTrue(any(event["over_budget"] for event in rlog.named("context.floor")))
        self.assertEqual(len(self._captured_bodies(rlog)), 1)
        self.assertTrue(tr.template_requests)
        self.assertEqual([event["error"] for event in rlog.named("summarize.error")], [
            "Input cannot fit the context window without losing protected input",
            "Input cannot fit the context window without losing protected input",
        ])

    def test_changed_forced_off_final_wire_after_context_still_posts_and_recovers(self):
        up, tr, rlog = self._upstream(), _Transport("context_then_summary"), _Rlog("changed")
        evidence = self._summary(up, tr, rlog, replace(OFF, reasoning="on"))
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
        the introduction and two blocks for the inner refit, then the introduction and
        one block for the same-role outer retry. The candidate must not suppress that different final wire.
        """
        up = self._upstream()
        tr = _Transport("context_refit_empty_then_outer_summary")
        rlog = _Rlog("same-role-state-change")
        blocks = [
            "historical evidence alpha\n" + "A" * 36_000,
            "historical evidence beta\n" + "B" * 36_000,
        ]
        with up._receive_open.respond_with(tr.open):
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
        # The introduction is now producer-owned context, not a fake first USER
        # request. Its removal counts too; the actual POST/retry count is unchanged.
        self.assertEqual([event["turns_dropped"] for event in rlog.named("context.floor")], [3, 2])
        self.assertIn("recovered summary", evidence)
        final_bodies = [json.loads(post) for post in tr.posts]
        inner_text = '\n'.join(m.get('content', '') for m in final_bodies[1]['messages'])
        outer_text = '\n'.join(m.get('content', '') for m in final_bodies[2]['messages'])
        for block in blocks:
            self.assertNotIn(block, inner_text)
        self.assertNotIn(blocks[0], outer_text)
        self.assertIn(blocks[1], outer_text)
        self.assertEqual(final_bodies, self._captured_bodies(rlog))
        self.assertTrue(all(body["chat_template_kwargs"]["enable_thinking"] is False
                            for body in final_bodies))
        self.assertTrue(all(body["temperature"] == 0.0 for body in final_bodies))

    def test_empty_transient_and_noncontext_failures_retain_existing_retries(self):
        for mode in ("empty_then_summary", "transient_then_summary", "other_400_then_summary"):
            with self.subTest(mode=mode):
                up, tr, rlog = self._upstream(), _Transport(mode), _Rlog(mode)
                evidence = self._summary(up, tr, rlog)
                self.assertEqual(len(tr.posts), 2)
                self.assertEqual(tr.posts[0], tr.posts[1])
                self.assertFalse(rlog.named("upstream.caller_retry_no_change"))
                self.assertIn("recovered summary", evidence)

    def test_typed_hint_is_single_retry_lifetime_not_cross_invocation_state(self):
        up = self._upstream()
        first, first_log = _Transport("context"), _Rlog("first")
        first_evidence = self._summary(up, first, first_log)
        self._assert_suppressed_context(first_evidence, first, first_log)

        second, second_log = _Transport("summary"), _Rlog("second")
        second_evidence = self._summary(up, second, second_log)
        self.assertEqual(len(second.posts), 1)
        self.assertFalse(second_log.named("upstream.caller_retry_no_change"))
        self.assertIn("recovered summary", second_evidence)


    def test_fold_only_owner_retains_distinct_results_and_exact_raw_provenance(self):
        # The old tail clip lost the first action; the removed summary writer
        # could replace distinct results. Only identical repetitions may fold.
        block = '$ shell {"command":"inspect"}\n  -> ' + 'EXACT result 雪\n' * 4000
        distinct = '$ shell {"command":"check"}\n  -> FAIL distinct result 7\n'
        raw = "\n".join([block] * 3 + [distinct])
        calls, rlog = [], _Rlog("fold-only-owner")
        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("evidence selection attempted inference")
        value = evidencesummary.Input(raw, forbidden, forbidden, OFF, rlog)
        first = evidencesummary.select(value)
        second = evidencesummary.select(value)
        self.assertEqual(calls, [])
        self.assertIsNot(first, second)
        self.assertEqual(first.raw, raw)
        self.assertEqual(first.folded, first.selected)
        self.assertEqual(first.selected.count(block), 1)
        self.assertIn(distinct, first.selected)
        self.assertTrue(first.selected.startswith(block))
        self.assertEqual(first.folded_actions, 2)
        self.assertIs(first.selection, evidencesummary.Selection.FOLDED)
        self.assertIsNone(first.summary)
        accepted = evidencesummary.settle(first, first.selected)
        self.assertIs(accepted.result, first)
        self.assertTrue(accepted.selected_delivered)
        self.assertFalse(evidencesummary.settle(first, distinct).selected_delivered)

if __name__ == "__main__":
    unittest.main()
