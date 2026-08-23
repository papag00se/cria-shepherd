"""What the coder read off disk survives compaction, the way what it fetched already did.

`⟦ctx:facts⟧` re-injects the fetch ledger from cria's own memory, so a compacted coder still knows
which URLs it has read. There was no equivalent for the workspace, so it kept its web history and lost
every file it had opened.

Walked twice. On shipping-rates-rb x nemotron-elastic 1787432916 the model had the gem's source open
at call 0091, was guessing gem names from memory by 0094 — "Could use `country` gem? Or
`libphonenumber`? … maybe use `geocoder`?" — and collapsed at 0097 into twenty repetitions of "there
is a gem called `eu` … I'm not sure", with that source on disk in its own workspace the whole time.
The same shape cost the go cell its API question.

Paths and sizes only. The contents are on disk and re-reading one is a single call; what compaction
destroys is not the bytes, it is the knowledge that it already looked."""
import json
import unittest

from cria import denial, loop


def _read(cid, path):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function",
         "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}]}


class _Sess:
    def __init__(self, read_files=None):
        self.read_files = read_files
        self.fetched_pages = None


class TheReadLedgerTests(unittest.TestCase):
    def test_a_read_that_returned_content_is_remembered(self):
        msgs = [_read("r1", "lib/shipping/rates.rb"),
                {"role": "tool", "tool_call_id": "r1", "content": "module Shipping\nend\n"}]
        self.assertIn("lib/shipping/rates.rb", loop._extract_reads(msgs))

    def test_a_refused_read_is_not(self):
        msgs = [_read("r1", "nope.rb"),
                {"role": "tool", "tool_call_id": "r1", "content": denial.mark("nope.rb is not there")}]
        self.assertEqual(loop._extract_reads(msgs), {})

    def test_a_claim_without_a_result_is_not(self):
        """TOOL RESULTS ONLY — the same rule the fetch ledger follows."""
        self.assertEqual(loop._extract_reads([_read("r1", "lib/x.rb")]), {})

    def test_the_tracker_accumulates_across_turns(self):
        sess = _Sess()
        loop._track_read_files(sess, [_read("r1", "a.rb"),
                                      {"role": "tool", "tool_call_id": "r1", "content": "x\n"}])
        loop._track_read_files(sess, [_read("r2", "b.rb"),
                                      {"role": "tool", "tool_call_id": "r2", "content": "y\n"}])
        self.assertEqual(sorted(sess.read_files), ["a.rb", "b.rb"])

    def test_the_block_names_the_files_and_no_contents(self):
        out = loop._read_ground_truth(_Sess({"lib/rates.rb": "986 bytes, 40 lines"}), [])
        self.assertIn("lib/rates.rb (986 bytes, 40 lines)", out)
        self.assertIn("read it again rather than working it out from memory", out)

    def test_nothing_read_says_nothing(self):
        self.assertEqual(loop._read_ground_truth(_Sess(), []), "")

    def test_a_long_ledger_counts_its_remainder(self):
        many = {f"f{i}.rb": "10 bytes, 1 lines" for i in range(loop._READ_LEDGER_CAP + 7)}
        out = loop._read_ground_truth(_Sess(many), [])
        self.assertIn("7 more file(s)", out)

    def test_it_rides_in_the_durable_facts_anchor(self):
        anchor = loop._fetched_facts_anchor(_Sess({"lib/rates.rb": "986 bytes, 40 lines"}), [])
        self.assertIsNotNone(anchor)
        self.assertIn("lib/rates.rb", anchor["content"])


if __name__ == "__main__":
    unittest.main()
