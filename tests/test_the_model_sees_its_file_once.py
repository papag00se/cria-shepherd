"""The model was looking at six copies of its own file and synthesised a seventh, with a new bug.

Found by the targeted post-fix re-run of `rust-toml-cli × ternary-bonsai` — the cell that scores
100% unassisted. Every mechanism fixed for it behaved: the reading step cleared, no steer was killed,
no false nudge, no runaway, and the gate put the real `error[E0308]` into four coder prompts. It
still scored 0, so the cause was somewhere else.

It was in the prompt. The model rewrote a 6.6 KB `main.rs` WHOLE, five times, each version 99.1–99.9%
identical to the one before, and every copy stayed verbatim in the working tail:

    call 0010   5,223 prompt tokens   0 copies        0 bytes
    call 0014   8,309                 1           6,570
    call 0020  12,415                 3          13,195
    call 0021  14,478                 4          19,835
    call 0022  16,527                 5          26,462
    call 0023  21,009                 6          33,103

The prompt quadrupled, and every token of the growth is the model's own output handed back to it. It
then wrote a sixth version. NOTE, because the first write-up of this got it wrong: all five
versions were compiled afterwards and none of them builds — four fail `E0277: the trait bound
String: Borrow<&str> is not satisfied` at the same line, the last `E0308`. The rewriting did not
destroy working code; the same typing bug survived every attempt. What it did do is spend the run
and fill the prompt. Compare the unassisted arm, which wrote the file ONCE, made three ~285-byte
`edit_file` patches, and finished 4 of 4.

NOTHING FOLDED THEM BECAUSE NOTHING COULD. `_collapse_duplicates` needs byte-identical calls and
these differ by about 1%. `selfcompact` already has the right rule — `write_stub_superseded`, keyed
on PATH, not on content — but it runs over the compacted middle only, and all of these sat in the
verbatim tail after it.

#5 names this exception in its own words: *"De-duplication: repeated content may appear once with a
pointer to the original."* Only SUPERSEDED copies are stubbed; the newest write to each path stays
whole, because that one is what is on disk.

Replayed against the real call-0023 body: six copies to two, 33,103 bytes of payload to 7,493, and
35% off the whole prompt.
"""

import json
import unittest

from cria import focustrim


def write(cid, path, body):
    return {"role": "assistant", "tool_calls": [{
        "id": cid, "type": "function",
        "function": {"name": "write_file",
                     "arguments": json.dumps({"path": path, "content": body})}}]}


def result(cid, text="⟦ctx:wrote⟧"):
    return {"role": "tool", "tool_call_id": cid, "content": text}


BIG = "fn resolve_path(t: &Table) -> Result<Value, String> {\n" + ("    // work\n" * 200) + "}\n"
BIG2 = BIG.replace("// work", "// work v2", 1)
BIG3 = BIG.replace("// work", "// work v3", 1)


def bodies(msgs, path="src/main.rs"):
    n = 0
    for m in msgs:
        for tc in (m.get("tool_calls") or []) if m.get("role") == "assistant" else []:
            a = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            if a.get("path") == path and "fn resolve_path" in str(a.get("content") or ""):
                n += 1
    return n


class TheSupersededCopiesGoTests(unittest.TestCase):
    def test_only_the_newest_write_to_a_path_survives_whole(self):
        msgs = [write("1", "src/main.rs", BIG), result("1"),
                write("2", "src/main.rs", BIG2), result("2"),
                write("3", "src/main.rs", BIG3), result("3")]
        out, _ = focustrim.trim(msgs)
        self.assertEqual(bodies(out), 1)

    def test_the_survivor_is_the_LAST_one(self):
        """It is the only one that describes what is on disk."""
        msgs = [write("1", "src/main.rs", BIG), result("1"),
                write("2", "src/main.rs", BIG3), result("2")]
        out, _ = focustrim.trim(msgs)
        kept = [json.loads((tc.get("function") or {}).get("arguments"))["content"]
                for m in out for tc in (m.get("tool_calls") or [])]
        self.assertIn(BIG3, kept)

    def test_the_stub_points_at_the_disk(self):
        msgs = [write("1", "src/main.rs", BIG), result("1"),
                write("2", "src/main.rs", BIG2), result("2")]
        out, _ = focustrim.trim(msgs)
        blob = json.dumps(out)
        self.assertIn("read_file for what is actually on disk now", blob)
        self.assertIn("src/main.rs", blob)

    def test_near_identical_is_the_whole_point(self):
        """Byte-identical copies were already folded. These differ by ~1%, which is why they were not."""
        import difflib
        self.assertGreater(difflib.SequenceMatcher(None, BIG, BIG2).ratio(), 0.98)
        self.assertNotEqual(BIG, BIG2)


class WhatIsLeftAloneTests(unittest.TestCase):
    def test_writes_to_DIFFERENT_paths_all_survive(self):
        msgs = [write("1", "src/main.rs", BIG), result("1"),
                write("2", "Cargo.toml", BIG2), result("2")]
        out, _ = focustrim.trim(msgs)
        self.assertEqual(bodies(out, "src/main.rs"), 1)
        self.assertEqual(bodies(out, "Cargo.toml"), 1)

    def test_a_single_write_is_untouched(self):
        msgs = [write("1", "src/main.rs", BIG), result("1")]
        out, _ = focustrim.trim(msgs)
        self.assertEqual(out, msgs)

    def test_a_short_payload_is_not_worth_a_pointer(self):
        msgs = [write("1", "a.py", "x = 1\n"), result("1"),
                write("2", "a.py", "x = 2\n"), result("2")]
        out, _ = focustrim.trim(msgs)
        self.assertIn("x = 1", json.dumps(out))

    def test_tool_RESULTS_are_never_stubbed(self):
        """A tool result is ground truth, not a superseded payload of cria's own carrying."""
        msgs = [write("1", "src/main.rs", BIG), result("1", "here is the file:\n" + BIG),
                write("2", "src/main.rs", BIG2), result("2")]
        out, _ = focustrim.trim(msgs)
        tool_txt = "".join(str(m.get("content") or "") for m in out if m.get("role") == "tool")
        self.assertIn("fn resolve_path", tool_txt)


class ItIsTheSameRuleTheCompactorAlreadyHasTests(unittest.TestCase):
    def test_both_use_one_wording(self):
        from cria import prompts
        self.assertIn("write_stub_superseded", prompts.load_map("compact_view"))

    def test_keyed_on_path_not_on_content(self):
        import inspect
        src = inspect.getsource(focustrim._stub_superseded_writes)
        self.assertIn("last[path] = i", src)


if __name__ == "__main__":
    unittest.main()
