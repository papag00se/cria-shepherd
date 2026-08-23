"""cria may not present a check result as current after something could have changed the workspace.

Two seats had the same hole: they abstain when NOTHING has ever been surveyed, and have no answer for
"surveyed once, a long time ago". A survey rides along on a cria-composed write/edit/list, so a run of
the coder's own shell commands moves the disk while the view stands still.

* shipping-rates-rb x ternary-bonsai 1787442206 — `bundle install` put four gems in vendor/bundle at
  16:56; cria told the coder `eu_countries` is "not installed anywhere — this project has no
  Gemfile.lock, no vendor/ and no .bundle/" six times after that, while the coder's own `ls` had just
  listed them and its own reasoning said the gem was installed.
* cart-billing-go x nemotron-elastic 1787434778 — `go mod download` created go.sum; the staleness
  ledger counts write_file/edit_file only, so the "these checks ran BEFORE your edit" note never
  rendered and the block asserted `missing go.sum entry` as present-tense ground truth for eleven
  more coder calls, with the on-disk annotation re-attached each time."""
import json
import unittest

from cria import probegate, probeparse, wsview


def _shell(cid, cmd):
    return {"role": "assistant", "tool_calls": [
        {"id": cid, "type": "function",
         "function": {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}


class TheViewKnowsItMayBeBehindTests(unittest.TestCase):
    def test_a_fresh_view_is_not_flagged(self):
        self.assertFalse(wsview.View(".").may_have_changed)

    def test_a_mutating_command_flags_it(self):
        v = wsview.View(".")
        v.note_a_mutator_ran()
        self.assertTrue(v.may_have_changed)

    def test_install_landed_abstains_rather_than_denying(self):
        v = wsview.View("/w")
        v.note_a_mutator_ran()
        tok = wsview.bind(v)
        self.addCleanup(wsview.unbind, tok)
        self.assertIsNone(probeparse.install_landed("ruby", "/w"))


class TheChecksSayWhenTheyMightBeBehindTests(unittest.TestCase):
    RAW = (probegate.SECTION_PREFIX + "0" + probegate.SECTION_SUFFIX
           + "\ncart.go:9:2: missing go.sum entry\nEXIT:1\n")

    def test_a_shell_command_that_writes_counts(self):
        msgs = [{"role": "tool", "tool_call_id": "g", "content": "gate"},
                _shell("c1", "go mod download github.com/shopspring/decimal")]
        self.assertTrue(probegate._a_command_could_have_changed_things_after(msgs, 0))

    def test_a_read_only_command_does_not(self):
        msgs = [{"role": "tool", "tool_call_id": "g", "content": "gate"},
                _shell("c1", "go build ./...")]
        self.assertFalse(probegate._a_command_could_have_changed_things_after(msgs, 0))

    def test_the_block_says_so_without_naming_files_it_cannot_name(self):
        out = probegate.clean_gate_output(self.RAW, a_command_ran_since=True)
        self.assertIn("ran BEFORE a command you ran that can change the workspace", out)
        self.assertIn("missing go.sum entry", out)      # the finding still ships

    def test_and_says_nothing_when_nothing_ran(self):
        self.assertNotIn("BEFORE a command", probegate.clean_gate_output(self.RAW))

    def test_the_note_is_separated_from_the_sentence_before_it(self):
        """It used to render as `…is not a fix.These checks ran BEFORE…`."""
        out = probegate.clean_gate_output(self.RAW, a_command_ran_since=True)
        self.assertNotIn("fix.These", out)


if __name__ == "__main__":
    unittest.main()
