"""When cria refuses a cut-off call that was not a write, it does not tell the model its write failed.

`guard_truncation` has two closing messages, and both assert a WRITE: "[YOUR LAST WRITE WAS REFUSED]
… partway through writing the file". They are chosen by whether the response hit the output cap or
stopped itself — never by whether there was a write at all.

But the retry loop breaks at `path is None`, which is cria's own finding that `_truncated_write_path`
saw no write in the cut-off call. It then fell straight into the write wording.

Measured over five days: **all 17 truncations had `path is None`**, so 17 of 17 told the model its
last write was refused, and that it had stopped partway through writing a file it never wrote. A
false fact in cria's voice about the model's own turn (#5b) — and an actively misleading one, since
a model told it hit a limit shrinks its content, and a call that ended early is not fixed by being
shorter.
"""

import json
import unittest

from cria import prompts


class TheThreeWordingsAreDistinctTests(unittest.TestCase):
    def setUp(self):
        self.m = prompts.load_map("call_refused")

    def test_the_non_write_refusal_exists_and_says_so(self):
        t = self.m["truncated_call"]
        self.assertIn("TOOL CALL WAS REFUSED", t)
        self.assertIn("not a file write", t)
        self.assertNotIn("writing the file", t)

    def test_the_two_write_refusals_still_say_write(self):
        for key in ("truncated_write", "selfcut_write"):
            self.assertIn("WRITE WAS REFUSED", self.m[key], key)

    def test_the_cap_and_selfcut_wordings_still_differ(self):
        """A model told it hit a limit shrinks its content; one that ended early must not be."""
        self.assertIn("hit the output limit", self.m["truncated_write"])
        self.assertIn("did NOT hit any limit", self.m["selfcut_write"])

    def test_none_of_them_names_cria(self):
        for key, text in self.m.items():
            self.assertNotIn("cria", text.lower(), key)


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def wording(self):
        return next((kw["wording"] for k, kw in self.events if k == "loop.truncated_refused"), None)


def _cut(name, args, finish="length"):
    return {"choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "t1", "type": "function",
                        "function": {"name": name, "arguments": args}}]}}]}


class TheSelectionIsDrivenByWhetherThereWasAWriteTests(unittest.TestCase):
    """Driven, and readable in the log. The wording that ACTUALLY shipped was recorded nowhere, so
    the incident this branch exists for — 17 of 17 truncations calling a non-write a refused WRITE —
    was invisible in the events and had to be reconstructed from prompt captures (#12)."""

    def _run(self, coder):
        from cria import loop
        rlog = _Rlog()
        body = {"messages": [{"role": "user", "content": "do it"}]}
        out = loop.guard_truncation(coder, body, lambda b, r: json.dumps(coder).encode(), rlog, step=1)
        return out, rlog

    def test_a_cut_off_non_write_call_is_called_a_refused_CALL(self):
        _, rlog = self._run(_cut("exec_command", '{"cmd": "go test ./'))
        self.assertEqual(rlog.wording(), "truncated_call")

    def test_a_cut_off_write_is_still_called_a_refused_WRITE(self):
        _, rlog = self._run(_cut("write_file", '{"path": "cart.go", "content": "package cart'))
        self.assertEqual(rlog.wording(), "truncated_write")

    def test_a_self_cut_write_keeps_its_own_wording(self):
        _, rlog = self._run(_cut("write_file", '{"path": "cart.go", "content": "package cart',
                                 finish="tool_calls"))
        self.assertEqual(rlog.wording(), "selfcut_write")

    def test_the_event_agrees_with_the_message_the_model_got(self):
        from cria import prompts
        for coder, key in ((_cut("exec_command", '{"cmd": "go test ./'), "truncated_call"),
                           (_cut("write_file", '{"path": "x.go", "content": "p'), "truncated_write")):
            with self.subTest(key=key):
                body = {"messages": [{"role": "user", "content": "do it"}]}
                from cria import loop
                rlog = _Rlog()
                loop.guard_truncation(coder, body, lambda b, r: json.dumps(coder).encode(),
                                      rlog, step=1)
                sent = "\n".join(str(m.get("content") or "") for m in body["messages"])
                self.assertIn(prompts.load_map("call_refused")[key][:60], sent)
                self.assertEqual(rlog.wording(), key)

    def test_the_guard_consults_the_write_path_before_choosing(self):
        import inspect

        from cria import loop
        src = inspect.getsource(loop.guard_truncation)
        self.assertIn("was_write", src)
        self.assertIn('"truncated_call"', src)
        # the write wordings must be reachable only through was_write
        after = src[src.index("was_write ="):]
        self.assertIn('if was_write else "truncated_call"', after)

    def test_a_mid_write_cut_seen_on_any_pass_still_counts_as_a_write(self):
        """The retry can succeed at finding the path on pass 1 and lose it on pass 2 — the closing
        message must still describe what actually happened."""
        import inspect
        from cria import loop
        src = inspect.getsource(loop.guard_truncation)
        self.assertIn("_last_write_path_seen = _last_write_path_seen or path is not None", src)


if __name__ == "__main__":
    unittest.main()
