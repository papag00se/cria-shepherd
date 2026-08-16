"""A write that a later write replaced is not stamped "this exact content is on disk".

`stub_old_write_args` replaces the big argument bodies of older write calls with an elision stub, so
the supervisor's session does not carry every historical version of a file. The stub for a write that
landed reads "[elided N chars — this exact content is on disk at PATH; read_file to view it]".

It chose that wording from ONE index for the whole span — the single newest write turn — so every
older write got the on-disk claim whatever path it touched. A coder that writes one file three times
produced three such stamps for that path, two of them false. Measured in a real prompt: **six stamps
for a single Ruby file at four different byte counts**, at most one of which could be true (#5b).

The claim is now made per PATH: the newest write to a path really is what is on disk; an earlier one
is named as an earlier version, pointing at `read_file` for what is actually there.
"""

import json
import unittest

from cria import selfcompact


BIG = selfcompact._STUB_MIN_CHARS + 50


def write(i, path, ch):
    return [{"role": "assistant", "tool_calls": [{"id": f"w{i}", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": path, "content": ch * BIG})}}]},
            {"role": "tool", "tool_call_id": f"w{i}", "content": f"Wrote {path}"}]


def rendered(msgs):
    return selfcompact.serialize(selfcompact.stub_old_write_args(msgs))


class OnlyTheCurrentVERSIONIsCalledOnDiskTests(unittest.TestCase):
    def test_three_writes_to_one_path_make_at_most_one_on_disk_claim(self):
        out = rendered(write(1, "a.rb", "x") + write(2, "a.rb", "y") + write(3, "a.rb", "z"))
        self.assertEqual(out.count("this exact content is on disk"), 0,
                         "the newest write is kept whole, so nothing should claim on-disk here")
        self.assertEqual(out.count("EARLIER version of a.rb"), 2)

    def test_the_newest_write_to_ANOTHER_path_still_claims_on_disk(self):
        """The claim is true for it, and losing it would be the opposite defect."""
        out = rendered(write(1, "a.rb", "x") + write(2, "a.rb", "y")
                       + write(3, "b.rb", "z") + write(4, "a.rb", "q"))
        self.assertEqual(out.count("this exact content is on disk at b.rb"), 1)
        self.assertEqual(out.count("EARLIER version of a.rb"), 2)
        self.assertIn("q" * 40, out, "the live working set is kept whole")

    def test_a_single_write_is_untouched(self):
        out = rendered(write(1, "a.rb", "x"))
        self.assertIn("x" * 40, out)
        self.assertNotIn("EARLIER version", out)


class TheOtherOutcomesAreUnchangedTests(unittest.TestCase):
    def test_a_refused_write_still_says_it_never_reached_disk(self):
        msgs = write(1, "a.rb", "x") + write(2, "a.rb", "y")
        msgs[1] = {"role": "tool", "tool_call_id": "w1",
                   "content": "⟦ctx:denied⟧ Nothing was run — the write was refused"}
        out = rendered(msgs)
        self.assertIn("never reached disk", out)
        self.assertNotIn("EARLIER version", out)

    def test_an_unpaired_write_makes_no_claim_in_either_direction(self):
        msgs = [m for m in write(1, "a.rb", "x") if m["role"] == "assistant"] + write(2, "a.rb", "y")
        out = rendered(msgs)
        self.assertNotIn("EARLIER version", out)
        self.assertNotIn("this exact content is on disk", out)


class TheWordingIsHonestTests(unittest.TestCase):
    def test_the_superseded_stub_points_at_the_real_file(self):
        from cria import prompts
        text = prompts.fill(prompts.load_map("compact_view")["write_stub_superseded"],
                            chars="512", path="lib/rates.rb")
        self.assertIn("EARLIER version of lib/rates.rb", text)
        self.assertIn("read_file", text)
        self.assertNotIn("is on disk", text.replace("actually on disk now", ""))
        self.assertNotIn("cria", text.lower())


if __name__ == "__main__":
    unittest.main()
