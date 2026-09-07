"""The on-target query judge must not bless a package as viable on the strength of an HTTP 200 on its
registry PAGE while the same package has repeatedly failed to INSTALL or LOAD.

Walked on ornith15 x shipping-rates-rb (…88df7462ef0c) call 0045. The judge saw `eu_countries -> HTTP
200` in the fetch record and reasoned, in its own words: "eu_countries did NOT fail (it returned 200).
So I can recommend it." But the gem's `require` failed on every run — its transitive `iso3166`
dependency does not exist on rubygems — so the judge kept the coder chained to an unloadable gem. The
"already tried and failed" rule the judge applies keyed "failed" off HTTP status only; the authoritative
RefusalLedger already held the install/load refusal, and it was never handed to the judge.

`_unresolved_deps` renders that ledger's ACTIVE (unsuperseded) refusals as a block the judge reads, and
the judge's prompt now names the case. A page that answers is not a package that loads.
"""

import unittest

from cria import loop, prompts, refusalledger


def _refusal(coord, ecosystem="rubygems", seq=1, outcome=refusalledger.REFUSED):
    return refusalledger.RefusalEvent(
        ecosystem=ecosystem, raw_coordinate=coord, package=coord, version="",
        outcome=outcome, evidence="cannot load such file -- iso3166", sequence=seq)


class _Sess:
    def __init__(self, ledger=None):
        self.refusal_events = ledger


class UnresolvedDepsBlockTests(unittest.TestCase):
    def test_an_active_refusal_becomes_a_labelled_block(self):
        led = refusalledger.RefusalLedger([_refusal("eu_countries")])
        out = loop._unresolved_deps(_Sess(led))
        self.assertIn("eu_countries", out)
        self.assertIn("could not install or load", out.lower())
        # The narrow lever: an answering page does not make the package viable.
        self.assertIn("http 200", out.lower())

    def test_a_success_supersedes_and_the_block_is_empty(self):
        """The RefusalLedger supersedes a refusal on an observed exact success — a transient failure
        the coder later fixed must NOT keep condemning a now-viable package (the adversarial case)."""
        led = refusalledger.RefusalLedger([
            _refusal("eu_countries", seq=1),
            _refusal("eu_countries", seq=2, outcome=refusalledger.SUCCEEDED),
        ])
        self.assertEqual(loop._unresolved_deps(_Sess(led)), "")

    def test_no_ledger_and_no_refusals_send_the_judge_nothing(self):
        self.assertEqual(loop._unresolved_deps(_Sess(None)), "")
        self.assertEqual(loop._unresolved_deps(_Sess(refusalledger.RefusalLedger([]))), "")

    def test_the_judge_prompt_names_the_install_or_load_case(self):
        rule = prompts.load("search_query_judge")
        self.assertIn("could not install or load", rule.lower())
        # …and it must not rest the viability finding on the page merely answering.
        self.assertIn("http 200", rule.lower())


if __name__ == "__main__":
    unittest.main()
