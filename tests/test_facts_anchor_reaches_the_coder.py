"""The same-host mismatch fact must reach the CODER, not only cria's own readers.

`_fetched_facts_anchor` called `_fetch_ground_truth([], sess, …)` with an EMPTY message list.
`_route_mismatch_fact` finds the coder's HTTP failure by scanning those messages, so `[]` always
yielded "". Every other caller of `_fetch_ground_truth` passes real messages and every one of them
is cria-INTERNAL: the step critic, the steer author, the blames-the-service guard.

Walked on mellum2 1786137318: the diagnosis appears in reasoner prompts 0037, 0038, 0045 and 0046
and in ZERO coder prompts, while the coder spent 24 calls concluding the sandbox had no network and
cria's steers hardened that into "the test runner's DNS is broken". The fact's own docstring says it
exists because "four separate steers instead told the coder the sandbox blocked the network" — and
from this call site it could never have prevented that.
"""
import json
import unittest

from cria import loop
from tests.test_loop import _SHELL, _Recorder, _Rlog, _ctx, _plan, _single_loop, _synth, _toolcall


class _Sess:
    workspace_root = ""
    fetched_pages = {"https://api.handle.me": ("HTTP 200", "", "", "")}


CODER_403 = [{"role": "tool",
              "content": "Chunk ID: aa\nProcess exited with code 1\nOutput:\n"
                         "urllib.error.HTTPError: HTTP Error 403: Forbidden\n"
                         "from https://api.handle.me/handles/goose\n"}]


class TheAnchorCarriesTheMismatchTests(unittest.TestCase):

    def test_with_the_messages_the_coder_is_told(self):
        anchor = loop._fetched_facts_anchor(_Sess(), CODER_403)
        self.assertIsNotNone(anchor)
        self.assertIn("SAME HOST", anchor["content"])
        self.assertIn("User-Agent", anchor["content"])

    def test_without_them_it_cannot_be_told(self):
        """The old behaviour, pinned so the regression is visible if the argument is ever dropped."""
        anchor = loop._fetched_facts_anchor(_Sess(), [])
        self.assertIsNotNone(anchor)              # the ledger still rides
        self.assertNotIn("SAME HOST", anchor["content"])

    def test_both_coder_call_sites_pass_the_messages(self):
        """Both real driver call sites — not just the function in isolation — must hand it the
        coder's OWN turn history, or the mismatch fact this file exists for reaches only cria's
        internal readers (reasoner prompts) and never the coder that needs it. Drive both."""
        rec = _Recorder([_toolcall()])
        l = loop.Loop(_ctx(rec, None))
        sess = loop.PlanSession(plan=_plan(2))
        sess.fetched_pages = _Sess.fetched_pages
        item = sess.plan.items[0]
        l._work_item(sess, "k", {"messages": CODER_403 + [{"role": "user", "content": "go"}],
                                 "tools": [_SHELL]}, _Rlog(), item, 1)
        sent = json.dumps(rec.bodies[-1]["messages"], ensure_ascii=False)
        self.assertIn("SAME HOST", sent)

        rec2 = _Recorder([_toolcall()])
        l2 = _single_loop(rec2)
        sess2 = _synth()
        sess2.fetched_pages = _Sess.fetched_pages
        body2 = {"messages": CODER_403 + [{"role": "user", "content": "go"}],
                "tools": [_SHELL], "stream": True}
        l2._drive_single_item(sess2, body2, "sid:x", _Rlog())
        sent2 = json.dumps(rec2.bodies[-1]["messages"], ensure_ascii=False)
        self.assertIn("SAME HOST", sent2)

    def test_the_ledger_itself_is_unaffected(self):
        anchor = loop._fetched_facts_anchor(_Sess(), CODER_403)
        self.assertIn("api.handle.me", anchor["content"])
        self.assertIn("HTTP 200", anchor["content"])


if __name__ == "__main__":
    unittest.main()
