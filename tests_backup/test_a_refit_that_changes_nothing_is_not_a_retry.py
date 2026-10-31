"""cria re-sent 3.2 million prompt tokens to a 400 it had already been given.

A 400 "exceeds context" carries the server's REAL prompt count, and `_overflow_refit` turns that
into a density the floor can re-fit against. That is the right move for an ordinary coder turn: the
floor drops whole oldest turns and the body genuinely shrinks.

A COMPOSED two-message prompt has no turns to drop. `loop.py` says so in as many words: *"a COMPOSED
two-message prompt cannot be made to fit by the context floor: the floor's lever is dropping whole
oldest turns, and a two-message call has none to drop."* Re-prepping it against any density returns
the same bytes, and cria sent them anyway.

Measured over 12 days of `~/.cria/logs`: **59 `context.refit` events and 59 `upstream.error HTTP
Error 400` — an exact match**, with the re-run floor logging `msg_before == msg_after` and
`over_budget: true` on 59 of 59. Byte-identical proof in the captures: `20260820T133651-…/0005` and
`0006`, 379,391 bytes each, `cmp` clean; `20260813T180510-…` sent the same 167,617-byte prompt twelve
times in about seventy seconds. Episodes arrive in runs of six, which is the harness's own blind
retry on top.

The window the 400 taught is the durable half of the refit and is kept — it is what makes every
LATER turn fit. Only the re-send is dropped.
"""

import io
import json
import unittest
import urllib.error

from cria import upstream


class _Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _overflow(n_prompt_tokens=94788, n_ctx=49152):
    body = json.dumps({"error": {"n_prompt_tokens": n_prompt_tokens, "n_ctx": n_ctx,
                                 "message": "the request exceeds the available context size"}})
    return urllib.error.HTTPError("http://x/v1/chat/completions", 400, "Bad Request", {},
                                  io.BytesIO(body.encode()))


class _Up(upstream.Upstream):
    """A real Upstream whose prep is pinned and whose POST always overflows."""

    def __init__(self, *, shrinks):
        super().__init__("http://x", timeout_seconds=5, context_window=49152,
                         capture_dir=None, capture_rendered=False)
        self._window_final = False
        self._window_guessed = False
        self._shrinks = shrinks
        self.sent = []

    def _headers(self, sse=False):
        return {}

    def _prep(self, body, stream, rlog, safety_override=None):
        # The real question this test asks: does re-prepping produce different bytes?
        size = 100 if safety_override is None or not self._shrinks else 50
        # Real _prep supplies an OpenAI JSON object at this boundary. Keep the
        # controlled byte equality/shrink without bypassing that wire contract.
        payload = {**body, "messages": [{"role": "user", "content": "x" * size}],
                   "stream": stream}
        return json.dumps(payload).encode("utf-8"), 1000, None


class ABodyThatCannotShrinkIsNotResentTests(unittest.TestCase):
    def _run(self, shrinks):
        up = _Up(shrinks=shrinks)
        rlog = _Rlog()
        opened = []

        def _urlopen(req, timeout=None):
            opened.append(req.data)
            raise _overflow()

        real = upstream.urllib.request.urlopen
        upstream.urllib.request.urlopen = _urlopen
        try:
            with self.assertRaises(upstream.UpstreamError):
                up._open_with_refit({"model": "m", "messages": []}, False, rlog)
        finally:
            upstream.urllib.request.urlopen = real
        return opened, rlog

    def test_the_identical_body_is_never_put_on_the_wire_twice(self):
        opened, rlog = self._run(shrinks=False)
        self.assertEqual(len(opened), 1)
        self.assertIn("upstream.refit_no_change", rlog.kinds())

    def test_a_body_that_really_shrinks_is_still_retried(self):
        """The refit is right for an ordinary turn — this must not become a blanket no-retry."""
        opened, rlog = self._run(shrinks=True)
        self.assertEqual(len(opened), 2)
        self.assertNotEqual(opened[0], opened[1])
        self.assertLess(len(opened[1]), len(opened[0]))
        self.assertEqual([json.loads(wire)["messages"][0]["content"] for wire in opened],
                         ["x" * 100, "x" * 50])
        self.assertNotIn("upstream.refit_no_change", rlog.kinds())

    def test_the_window_the_server_stated_is_kept_either_way(self):
        """The durable half of the refit: the 400 named the real n_ctx, and that is what makes every
        later turn fit. Dropping the re-send must not drop the lesson."""
        up = _Up(shrinks=False)
        rlog = _Rlog()

        def _urlopen(req, timeout=None):
            raise _overflow(n_ctx=32768)

        real = upstream.urllib.request.urlopen
        upstream.urllib.request.urlopen = _urlopen
        try:
            with self.assertRaises(upstream.UpstreamError):
                up._open_with_refit({"model": "m", "messages": []}, False, rlog)
        finally:
            upstream.urllib.request.urlopen = real
        self.assertEqual(up._window, 32768)
        self.assertTrue(up._window_final)

    def test_the_failure_still_reaches_the_caller_as_the_real_status(self):
        """classify_failure keys on `err.code`; a short-circuit must not turn a 400 into a None."""
        up = _Up(shrinks=False)

        posted = []
        def _urlopen(req, timeout=None):
            posted.append(bytes(req.data))
            raise _overflow()

        real = upstream.urllib.request.urlopen
        upstream.urllib.request.urlopen = _urlopen
        try:
            with self.assertRaises(upstream.UpstreamError) as caught:
                up._open_with_refit({"model": "m", "messages": []}, False, _Rlog())
        finally:
            upstream.urllib.request.urlopen = real
        self.assertEqual(caught.exception.code, 400)
        self.assertIsInstance(caught.exception, upstream.ContextRefitNoChange)
        self.assertEqual(len(posted), 1)
        self.assertEqual(caught.exception.final_wire, posted[0])
        self.assertEqual(json.loads(posted[0]), {
            "model": "m", "messages": [{"role": "user", "content": "x" * 100}], "stream": False})


if __name__ == "__main__":
    unittest.main()
