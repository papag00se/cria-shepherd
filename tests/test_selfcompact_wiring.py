import types
import unittest

from cria import selfcompact
from cria.selfcompact import msg_digest as _msg_digest
from cria.server import CriaHandler


class _Rlog:
    def emit(self, *a, **k):
        pass


def _stub_server(self_compact=True, chat_reply="ROLLUP SUMMARY", trigger=100):
    import json
    cfg = types.SimpleNamespace(context=types.SimpleNamespace(self_compact=self_compact, trigger_compaction=trigger))
    upstream = types.SimpleNamespace(
        chat=lambda body, rlog: json.dumps({"choices": [{"message": {"content": chat_reply}}]}).encode())
    return types.SimpleNamespace(cfg=cfg, compact_states={}, coder_role=None,
                                 compactor_role=None, upstream=upstream)


def _handler(server):
    h = CriaHandler.__new__(CriaHandler)   # no socket
    h.server = server
    return h


def _big(n):
    # ~1000 chars/message so the token budgets (tail 6000) leave a compactable middle
    return {"messages": [{"role": "system", "content": "sys"}]
            + [{"role": "assistant", "content": f"turn-{i} " + "x" * 1000} for i in range(n)]}


class SelfCompactWiringTests(unittest.TestCase):
    def test_compacts_a_long_stable_session(self):
        h = _handler(_stub_server())
        framed = _big(150)                                     # 151 msgs, over the trigger
        out = h._maybe_self_compact(framed, "sid:abc", _Rlog())
        self.assertLess(len(out["messages"]), len(framed["messages"]))
        self.assertTrue(any(selfcompact.SUMMARY_MARKER in str(m.get("content")) for m in out["messages"]))
        self.assertIn("ROLLUP SUMMARY", " ".join(str(m.get("content")) for m in out["messages"]))

    def test_skips_unstable_session_and_short_history(self):
        h = _handler(_stub_server())
        big = _big(40)
        self.assertIs(h._maybe_self_compact(big, "task:hash", _Rlog()), big)   # unstable key → untouched
        small = {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]}
        self.assertIs(h._maybe_self_compact(small, "sid:abc", _Rlog()), small)  # under the token trigger

    def test_disabled_by_config(self):
        h = _handler(_stub_server(self_compact=False))
        big = _big(150)
        self.assertIs(h._maybe_self_compact(big, "sid:abc", _Rlog()), big)

    def test_msg_digest_captures_tool_calls(self):
        d = _msg_digest({"role": "assistant", "content": "writing",
                         "tool_calls": [{"function": {"name": "write_file", "arguments": '{"path":"x.py"}'}}]})
        self.assertIn("writing", d)
        self.assertIn("write_file", d)


if __name__ == "__main__":
    unittest.main()
