"""nemotron-nano 1786243834, call 0072: the step-2 opening frame was ONE 61,424-char user message
carrying the same 7,216-char ⟦ctx:denied⟧ block SIX times ('API endpoints (33)' ×7 counting the
facts anchor). The coder answered it with the whole deliverable as chat prose and no tool call.

How six copies survived a boundary compaction that keeps NO verbatim tail: each denial re-embeds
the spilled spec digest, the digest contains `[API endpoints (` and `[response shape —` — the
_SPEC_*_MARKER anchor markers — so every denial classified as an ANCHOR and anchors are kept
verbatim, never folded. Six byte-identical messages, each individually "protected".

The anchor guarantee is one VERBATIM copy surviving compaction — models rely on that (the digest
is what they code against). Byte-identical copies beyond the first carry zero information, so
they collapse. Nothing else changes: distinct anchors, in order, verbatim.
"""
import unittest

from cria import selfcompact

DIGEST = ("[API endpoints (33): /, /handles/{handle}, /holders/{address}]\n"
          "[response shape — the fields each endpoint MAY return]\n" + "x" * 400)
DENIAL = ("⟦ctx:denied⟧ ./tmp/reference/spec.json is a large reference document — reading it "
          "whole gets truncated, so you would miss the middle.\n" + DIGEST +
          "\nRead it deliberately instead: grep the file for what you need.")


def _msgs():
    out = [{"role": "system", "content": "coder system"},
           {"role": "user", "content": "the task"},
           {"role": "assistant", "content": "working on it " + "y" * 2000}]
    for i in range(6):
        out.append({"role": "tool", "tool_call_id": f"c{i}", "content": DENIAL})
        out.append({"role": "assistant", "content": f"turn {i} " + "z" * 1500})
    return out


class IdenticalAnchorsCollapseTests(unittest.TestCase):
    def _compact(self, msgs):
        out, state, applied = selfcompact.compact(
            msgs, lambda mm: "the coder read the spec and looped on re-reading it",
            selfcompact.CompactState(), force=True, pinned_task="the task")
        self.assertTrue(applied)
        return out

    def test_six_identical_denials_become_one(self):
        out = self._compact(_msgs())
        n = sum(str(m.get("content", "")).count("large reference document") for m in out)
        self.assertEqual(n, 1)

    def test_the_one_copy_is_verbatim(self):
        out = self._compact(_msgs())
        kept = [m for m in out if "large reference document" in str(m.get("content", ""))]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["content"], DENIAL)   # never trimmed, never paraphrased

    def test_distinct_anchors_all_survive(self):
        msgs = _msgs()
        other = DENIAL.replace("spec.json", "openapi.yaml")
        msgs.insert(4, {"role": "tool", "tool_call_id": "cx", "content": other})
        out = self._compact(msgs)
        texts = "\n".join(str(m.get("content", "")) for m in out)
        self.assertIn("spec.json is a large reference document", texts)
        self.assertIn("openapi.yaml is a large reference document", texts)

class TheKeyCoversTheToolCallTests(unittest.TestCase):
    """Keying on TEXT alone would fold two anchors that differ only in their tool_calls, and the
    survivor's sibling call would vanish from the view entirely — anchors are excluded from the
    summarizer input, so nothing downstream would carry it. Prevalence of that shape today is zero
    (no anchor message in 17,912 captured coder bodies carries tool_calls), but the failure is
    silent, so the key is msg_digest, which covers the call."""

    def _two_anchors_differing_only_by_call(self):
        base = {"role": "assistant", "content": DIGEST}
        mk = lambda i, path: {**base, "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "%s"}' % path}}]}
        return [{"role": "system", "content": "s"},
                mk(0, "a.py"), {"role": "user", "content": "x" * 4000},
                mk(1, "b.py"), {"role": "user", "content": "y" * 4000}]

    def test_both_calls_survive(self):
        out, _, applied = selfcompact.compact(
            self._two_anchors_differing_only_by_call(), lambda mm: "summary",
            selfcompact.CompactState(), force=True, pinned_task="t")
        self.assertTrue(applied)
        calls = [tc["function"]["arguments"] for m in out for tc in (m.get("tool_calls") or [])]
        self.assertTrue(any("a.py" in c for c in calls), calls)
        self.assertTrue(any("b.py" in c for c in calls), calls)

    def test_the_drop_is_reported(self):
        events = []
        selfcompact.compact(_msgs(), lambda mm: "summary", selfcompact.CompactState(),
                            force=True, pinned_task="t",
                            rlog=type("R", (), {"emit": lambda self, k, **kw: events.append((k, kw))})())
        self.assertIn(("context.anchor_dedup", {"dropped": 5}), events)

if __name__ == "__main__":
    unittest.main()
