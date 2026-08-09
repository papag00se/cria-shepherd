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
DENIAL = ("⟦ctx:denied⟧ ./tmp/read-only/spec.json is a large reference document — reading it "
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


if __name__ == "__main__":
    unittest.main()
