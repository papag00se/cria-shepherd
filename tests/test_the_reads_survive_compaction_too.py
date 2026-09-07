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


def _read(cid, path, **args):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function",
         "function": {"name": "read_file", "arguments": json.dumps({"path": path, **args})}}]}


def _ledger(**paths):
    """The ledger's stored shape: path -> (nbytes, label). ``nbytes`` is the keep-largest key (real
    byte length of the read), kept internally; the LABEL no longer prints a byte count — the live
    ⟦ctx:files⟧ listing owns file size, so the ledger prints only its line count. Fixtures pass the
    label and a separate nbytes key."""
    return {p: (nbytes, label) for p, (nbytes, label) in paths.items()}


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
        out = loop._read_ground_truth(_Sess(_ledger(**{"lib/rates.rb": (986, "40 lines")})), [])
        self.assertIn("lib/rates.rb (40 lines)", out)

    def test_the_ledger_prints_no_byte_count(self):
        """Walked on ornith15 x shipping-rates-rb 2026-09-07: this ledger measured the read result
        (trailing newline stripped) as 984 bytes while the live ⟦ctx:files⟧ listing stat'd the same
        unchanged file at 985, in the same prompt. That 1-byte gap on every file read as cria
        fabricating. The listing owns byte size now; the ledger states no byte count that can
        collide with it."""
        out = loop._read_ground_truth(_Sess(_ledger(**{"lib/rates.rb": (985, "25 lines")})), [])
        self.assertIn("lib/rates.rb (25 lines)", out)
        self.assertNotIn("bytes", out)

    def test_the_header_does_not_contradict_the_system_prompt(self):
        """It used to close with "read it again rather than working it out from memory", while
        `coder_system.txt` line 16 says "do not read or run the same thing again". Both shipped in
        every prompt, and the ledger is the one the coder obeyed: twelve walkers on the 2026-08-28
        runs recorded repeat reads of files whose full text was in the same request, and in the java
        cell the third such read was swallowed by the repetition redirect, costing the whole turn."""
        from cria import prompts
        out = loop._read_ground_truth(_Sess(_ledger(**{"a.rb": (1, "1 lines")})), [])
        self.assertNotIn("read it again", out)
        self.assertIn("do not read or run the same thing again",
                      prompts.load("coder_system"))

    def test_it_does_not_claim_the_contents_are_absent(self):
        """"their contents are not repeated here" is a claim about the whole prompt, which this
        function cannot see. It was false in every run walked: the files it named were sitting in
        the same request, in full, further down."""
        out = loop._read_ground_truth(_Sess(_ledger(**{"a.rb": (1, "1 lines")})), [])
        self.assertNotIn("not repeated here", out)

    def test_a_write_supersedes_the_size_a_read_recorded(self):
        """`_keep_larger` is right between two READINGS and wrong against a write, which is the
        file's new state and may be smaller. go 0010 said `cart.go (894 bytes, 44 lines)` for a file
        rewritten at 0009; ruby 0036 said `rates.rb (984 bytes, 25 lines)` for one rewritten at
        0026, and there the stale number corroborated a stale copy in the transcript, so the coder
        sent an edit blending two versions of one file."""
        msgs = [_read("r1", "/w/c.go"),
                {"role": "tool", "tool_call_id": "r1", "content": "x" * 894},
                {"role": "assistant", "tool_calls": [{"id": "w1", "function": {
                    "name": "write_file",
                    "arguments": r'{"path":"/w/c.go","content":"package p\nfunc A(){}\n"}'}}]},
                {"role": "tool", "tool_call_id": "w1", "content": "Wrote /w/c.go"}]
        out = loop._read_ground_truth(_Sess(), msgs)
        self.assertIn("/w/c.go (3 lines)", out)
        self.assertNotIn("894", out)

    def test_a_refused_write_does_not_enter_the_ledger(self):
        """An attempted write is not a write — the same bar the read side already applies."""
        msgs = [{"role": "assistant", "tool_calls": [{"id": "w1", "function": {
                    "name": "write_file",
                    "arguments": '{"path":"/w/n.go","content":"nope"}'}}]},
                {"role": "tool", "tool_call_id": "w1",
                 "content": "\u27e6ctx:denied\u27e7 write_file REFUSED (not written)"}]
        self.assertEqual(loop._read_ground_truth(_Sess(), msgs), "")

    def test_nothing_read_says_nothing(self):
        self.assertEqual(loop._read_ground_truth(_Sess(), []), "")

    def test_a_long_ledger_names_every_file(self):
        """UNCAPPED 2026-08-26. It named 20 of an ALPHABETICALLY sorted list and counted the rest,
        so which files vanished was arbitrary — a `z*.py` read a moment ago always went first. The
        ledger's stated purpose is "the KNOWLEDGE THAT IT HAS ALREADY LOOKED", which is per-file and
        is not recoverable from a number (rule 5, as tightened 2026-08-16)."""
        many = _ledger(**{f"f{i}.rb": (10, "1 lines") for i in range(27)})
        out = loop._read_ground_truth(_Sess(many), [])
        for name in many:
            self.assertIn(name, out)
        self.assertNotIn("more file(s)", out)

    def test_it_rides_in_the_durable_facts_anchor(self):
        anchor = loop._fetched_facts_anchor(
            _Sess(_ledger(**{"lib/rates.rb": (986, "40 lines")})), [])
        self.assertIsNotNone(anchor)
        self.assertIn("lib/rates.rb", anchor["content"])


class ARangedReadIsNotTheFileTests(unittest.TestCase):
    """Walked on the sub-40 pass: feed-pipeline-java x nemotron-elastic, scored 16.

    `read_file` takes `start_line` / `end_line`, and the ledger recorded whatever came back under the
    file's own path. A 16-line window on a 237-line file was written down as "751 bytes, 16 lines",
    and the block above it says these are the files you have read. At call 0070 the coder acted on
    it. cria composed both halves of that sentence, so the false fact is cria's own (#5b)."""

    def _window(self, path, body, **rng):
        return [_read("r1", path, **rng),
                {"role": "tool", "tool_call_id": "r1", "content": body}]

    def test_the_window_is_named(self):
        got = loop._extract_reads(self._window("Importer.java", "x\n" * 16, start_line=1, end_line=16))
        self.assertIn("lines 1-16 only", got["Importer.java"][1])

    def test_a_whole_file_read_says_nothing_about_lines(self):
        got = loop._extract_reads(self._window("Importer.java", "x\n" * 16))
        self.assertNotIn("only", got["Importer.java"][1])

    def test_an_open_ended_window_is_still_a_window(self):
        for rng, want in (({"start_line": 200}, "from 200"), ({"end_line": 30}, "up to 30")):
            with self.subTest(rng=rng):
                got = loop._extract_reads(self._window("a.java", "x\n" * 5, **rng))
                self.assertIn(want, got["a.java"][1])

    def test_a_later_window_does_not_replace_the_whole_file(self):
        """The ledger answers "have I looked at this file", and a window read after a full read must
        not take the full reading away."""
        sess = _Sess()
        loop._track_read_files(sess, self._window("a.java", "x\n" * 200))
        loop._track_read_files(sess, [_read("r2", "a.java", start_line=1, end_line=5),
                                      {"role": "tool", "tool_call_id": "r2", "content": "x\n" * 5}])
        self.assertNotIn("only", sess.read_files["a.java"][1])

    def test_a_bigger_read_does_replace_a_smaller_one(self):
        sess = _Sess()
        loop._track_read_files(sess, [_read("r1", "a.java", start_line=1, end_line=5),
                                      {"role": "tool", "tool_call_id": "r1", "content": "x\n" * 5}])
        loop._track_read_files(sess, self._window("a.java", "x\n" * 200))
        self.assertNotIn("only", sess.read_files["a.java"][1])


if __name__ == "__main__":
    unittest.main()
