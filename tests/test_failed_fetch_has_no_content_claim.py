"""cria may not tell the model a failed fetch returned nothing. Often it returned the diagnosis.

api.handle.me answers a 404 with `{"error":"route_not_found","message":"Route not found:
/handle/goose"}` — the sentence that names the fault. cria's own code records catching itself on
this (webfetch.py): it replaced an 89-character 404 body, `{"error":"holder_not_found","message":
"Holder not found"}`, with a key list, "while cria told the model elsewhere 'you have no content
from them'. It had the content and threw it away."

The claim was removed from ONE string on that occasion and survived in two others — the paragraph
under the fetch ledger and the repeat-fetch guard — and a third was written in 2026-08-08. Operator's
ruling that day: drop the no-content claims rather than explain when they do not hold.

This test is the thing that stops it coming back a fourth time. It reads every model-facing prompt,
so a new file inherits the rule without anyone remembering it.
"""
import pathlib
import re
import unittest

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "cria" / "prompts"

# The claim in any of its shapes. Narrow on purpose: it must catch "you have no content from it"
# without catching a legitimate statement about an EMPTY body, which is a real and different thing
# (webfetch says "The response body was EMPTY" only when it actually was).
_NO_CONTENT = re.compile(
    r"(?i)\b(?:you|we)\s+(?:simply\s+)?have\s+no\s+content\b"
    r"|\bthey\s+returned\s+no\s+content\b"
    r"|\bno\s+content\s+from\s+(?:it|them)\b"
    r"|\bnothing\s+(?:came\s+back|here\s+to\s+code\s+against)\b")


class NoPromptClaimsAFailedFetchIsEmptyTests(unittest.TestCase):
    def test_every_prompt_file(self):
        offenders = []
        for f in sorted(PROMPTS.glob("*.txt")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue          # commentary may quote the old wording as history
                if _NO_CONTENT.search(line):
                    offenders.append(f"{f.name}:{n}: {line.strip()[:110]}")
        self.assertEqual(offenders, [], "a prompt claims a failed fetch returned nothing:\n"
                                        + "\n".join(offenders))

    def test_the_matcher_would_catch_all_three_removed_wordings(self):
        """Verbatim, the three that shipped — so the guard is proven, not merely green."""
        for old in ("Where an entry came back with an error, you simply have no content from it",
                    "it returned 404, so you have no content from it",
                    "THESE FETCHES FAILED — they returned no content, so there is nothing here to "
                    "code against"):
            self.assertTrue(_NO_CONTENT.search(old), old)

    def test_a_genuinely_empty_body_may_still_be_reported(self):
        """webfetch says this only when the body really was empty — that is a fact, not the claim."""
        self.assertIsNone(_NO_CONTENT.search("The response body was EMPTY. Retrying this exact URL "
                                             "returns the same empty result"))


class WhatReplacedItTests(unittest.TestCase):
    def test_the_three_now_send_the_model_to_read_what_came_back(self):
        from cria import prompts
        for text in (prompts.load_map("fetched_facts_sections")["failed"],
                     prompts.load("fetched_facts_anchor"),
                     prompts.load_map("webfetch_guards")["fetch_repeat_failed"]):
            self.assertIn("status", text.lower())
            self.assertRegex(text, r"(?i)anything|whatever")   # …and whatever came back with it


class NoPromptDefendsAFailedURLTests(unittest.TestCase):
    """A 404 sometimes IS proof the URL is wrong, and reassuring the model otherwise moves the blame.

    maple-preview 0014 fetched `/handle/goose` — singular, not a route. The anchor told it the error
    was "not proof the address is wrong". Its very next reasoning: "The goose handle returned 404, so
    it's not a valid Ada handle." One call later: "Confirmed live endpoints exist". It took cria's
    word that the endpoint was fine and moved the blame to the handle name; the reasoner inherited
    that at 0017 and shipped it as the steer that ended the run. `address` is doubly bad wording in a
    task whose subject noun is an address.

    The real fear — a coder abandoning a working service over one 404 — is covered exactly and
    without defending anything by "a failure on one URL says nothing about any other URL, and nothing
    about whether the service works". Route-vs-value is now settled per URL from the parsed route
    list, which is a fact rather than a reassurance."""

    _DEFENCE = re.compile(r"(?i)not\s+(?:by itself\s+)?proof\s+(?:that|the)\b")

    def test_every_prompt_file(self):
        offenders = []
        for f in sorted(PROMPTS.glob("*.txt")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if self._DEFENCE.search(line):
                    offenders.append(f"{f.name}:{n}: {line.strip()[:110]}")
        self.assertEqual(offenders, [], "a prompt tells the model a failed fetch does not mean the "
                                        "URL is wrong — sometimes it does:\n" + "\n".join(offenders))

    def test_the_matcher_catches_both_removed_wordings(self):
        for old in ("is a fact about that fetch, not proof the address is wrong",
                    "An error is not by itself proof that nothing is there."):
            self.assertTrue(self._DEFENCE.search(old), old)

    def test_the_scoping_fact_that_replaced_them_survives(self):
        from cria import prompts
        self.assertIn("says nothing about any other URL",
                      prompts.load_map("fetched_facts_sections")["failed"])


if __name__ == "__main__":
    unittest.main()
