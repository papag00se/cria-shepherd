"""cria told 674 prompts a file did not exist because its last look predated the install that made it.

`workspace_inventory` closes with *"This list is complete — a file not listed here does not exist in
the workspace."* That clause is what makes the listing decisive for every judge, the planner, the
briefing writer and the coder. It was gated on whether the survey hit its own BOUND — `complete` and
`folded` — and on nothing about WHEN the survey ran.

A survey rides along only on a composed write/edit/list. A run of the coder's own shell commands
moves the disk while the view stands still, and `View.may_have_changed` has recorded exactly that
since 2026-08-22 — with one reader, in a different module, out of the five seats that make claims
about this disk.

Walked at `~/.cria/calls/20260822T231008-…/0102-proxy.prompt.txt`. Lines 1190-1196 of that prompt are
the coder's own `ls` of an installed gem tree. Lines 1199-1210 list ten files under
*"FILES ON DISK RIGHT NOW (gathered from the filesystem just now) … the transcript's file mentions
may be stale"* and close with the completeness clause. On disk at that moment: 95 files, including
`europe-0.0.28.gem` and seven directories under `vendor/bundle`. Measured over 253 sessions: the
clause shipped 674 times and its honest counterpart shipped 0 times.

Two different reasons produce two different sentences. A survey that hit a bound did not reach
everywhere (`partial`). A survey that reached everywhere and has been overtaken is not wrong about
what it saw — it is wrong about *now*, so its caveat must also withdraw the header's "right now" /
"just now" / "at judging time" (`stale`). #5b, #11b.
"""

import unittest

from cria import groundtruth, prompts, wsview

_L = prompts.load_map("workspace_inventory")


def _view(*, complete=True, mutator=False, folded=False):
    v = wsview.View("/ws", "s")
    tree = "D\t\nD\tlib\nF\t5\t100\tlib/shipping.rb\nF\t9\t20\tGemfile\n"
    if folded:
        tree += "X\t400\tvendor\n"
    v._ingest_tree(tree, complete=complete)
    if mutator:
        v.note_a_mutator_ran()
    return v


def _render(view, flavor=None):
    tok = wsview.bind(view)
    try:
        return (groundtruth.workspace_inventory("/ws", flavor=flavor) if flavor
                else groundtruth.workspace_inventory("/ws"))
    finally:
        wsview.unbind(tok)


FLAVORS = (None, "coder", "briefing", "planner")


class AFreshCompleteLookKeepsItsClauseTests(unittest.TestCase):
    def test_every_judging_seat_still_gets_the_decisive_sentence(self):
        for flavor in (None, "briefing", "planner"):
            with self.subTest(flavor=flavor):
                self.assertIn(_L["complete"], _render(_view(), flavor))

    def test_the_coder_keeps_its_own_closing_line(self):
        """The coder's listing closes with the read-file instruction, not the judge's clause."""
        out = _render(_view(), "coder")
        self.assertIn(_L["coder_note"], out)
        self.assertNotIn(_L["stale"], out)


class AnOvertakenListingWithdrawsTheClauseTests(unittest.TestCase):
    def test_no_seat_is_told_a_missing_file_does_not_exist(self):
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertNotIn(_L["complete"], _render(_view(mutator=True), flavor))

    def test_every_seat_is_told_why(self):
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertIn(_L["stale"], _render(_view(mutator=True), flavor))

    def test_the_files_it_did_see_are_still_named(self):
        """The listing is still worth having — only the claim about what is absent has to go."""
        out = _render(_view(mutator=True))
        self.assertIn("lib/shipping.rb", out)
        self.assertIn("Gemfile", out)

    def test_a_bound_and_an_overtaking_are_different_sentences(self):
        """`partial` says the survey did not reach everywhere. `stale` says it did, and has since
        been overtaken — and unlike `partial` it must also withdraw the header's freshness."""
        self.assertIn(_L["partial"], _render(_view(complete=False)))
        self.assertNotIn(_L["stale"], _render(_view(complete=False)))
        self.assertIn(_L["stale"], _render(_view(mutator=True)))
        self.assertNotIn(_L["partial"], _render(_view(mutator=True)))

    def test_a_folded_directory_is_still_a_bound_not_an_overtaking(self):
        self.assertIn(_L["partial"], _render(_view(folded=True)))


class TheReadFileInstructionIsNotTheClauseTests(unittest.TestCase):
    """"the disk is the only current version — do not reconstruct content from the summary" is true
    of a bounded or overtaken listing too. It shared a line with the completeness clause and was
    being dropped along with it."""

    def test_the_coder_keeps_it_when_the_listing_is_overtaken(self):
        self.assertIn(_L["coder_note"], _render(_view(mutator=True), "coder"))

    def test_the_coder_keeps_it_when_the_survey_hit_a_bound(self):
        self.assertIn(_L["coder_note"], _render(_view(complete=False), "coder"))


if __name__ == "__main__":
    unittest.main()
