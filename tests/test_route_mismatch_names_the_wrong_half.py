"""The SAME HOST anchor asserted which half of the URL was wrong. It got mellum's backwards.

The routing-class anchor used to end:

    The host answers, so this is about the path, not the network and not your headers.
    Compare the two URLs against the routes the fetched document actually defines.

True of a route that does not exist. False of a real route handed a bad parameter — and
mellum2 1786167643 was the second kind. `/holders/{address}` IS defined; the coder had put the
payment address where the spec asks for the holder's STAKE address. Sent to compare the URLs against
the route list, it did, and concluded:

    So /holders/{address} is not a valid endpoint. The API doesn't have a /holders/{address} endpoint.

then caught cria contradicting itself in the same prompt:

    Wait, I see /holders, /holders/{address}… The fetch record says /holders/{address} returns 404,
    but the endpoint list shows it. That's confusing. Maybe the fetch record is from a different run?

The mirror of the fault the operator found in the ledger's own note on 2026-08-08 — cria naming one
cause for every failure. `_failed_fetch_diagnosis` already answers this from the parsed route list;
this anchor now asks it instead of guessing, so the two places cannot drift apart.

Also gone from both anchors: the project name. Verified in maple coder prompts 0034/0035/0037, the
model was reading "cria's own fetch of https://api.handle.me/openapi.json returned HTTP 200" — a
distinctive proper noun in front of a weak model (principle 17), and a claim about WHO fetched it
that cria has no need to make. The substance is unchanged: `web_fetch` really is cria's own tool
(writeproxy synthesizes it, webfetch sends a browser User-Agent), so the User-Agent difference the
rejection-class anchor names is real and stays.
"""
import unittest

from cria import loop, prompts

ROUTES = "/, /handles, /handles/{handle}, /holders, /holders/{address}, /stats, /health"
SHAPES = ("GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) returns:\n"
          "GET /holders/{address} (replace in the URL path: {address} = The stake/enterprise/script/"
          "other address of the Holder) returns:")
LEDGER = {"https://api.handle.me/openapi.json": ("HTTP 200", ROUTES, SHAPES, "")}

# verbatim coder tool output from the two walked runs
MELLUM = ("Error resolving handle: 404 Client Error: Not Found for url: "
          "https://api.handle.me/holders/addr1qxsfzsmy6y2seduagp")
MAPLE = ("urllib.error.HTTPError: HTTP Error 404: Not Found for url: "
         "https://api.handle.me/handle/goose")


def _fact(text, ledger=LEDGER):
    return loop._route_mismatch_fact(ledger, [{"role": "tool", "content": text}])


class ItNamesTheHalfThatIsActuallyWrongTests(unittest.TestCase):
    def test_a_real_route_with_a_bad_value(self):
        fact = _fact(MELLUM)
        self.assertIn("This route exists, so the path is right", fact)
        self.assertIn("stake/enterprise/script/other address of the Holder", fact)  # the spec's words
        self.assertNotIn("this is about the path", fact)

    def test_a_route_that_does_not_exist(self):
        fact = _fact(MAPLE)
        self.assertIn("No such route", fact)
        self.assertIn("/handles/{handle}", fact)          # the near miss, named
        self.assertNotIn("what you put in it is what to check", fact)

    def test_with_no_parsed_routes_it_asserts_neither(self):
        """Silence over a guess — and the rest of the anchor, which cria DID observe, still ships."""
        fact = _fact(MAPLE, {"https://api.handle.me/x": ("HTTP 200", "", "", "")})
        self.assertIn("The host answers", fact)
        for guess in ("No such route", "This route exists", "about the path"):
            self.assertNotIn(guess, fact)

    def test_one_owner(self):
        """The clause is `_failed_fetch_diagnosis` re-punctuated, never a second wording."""
        d = loop._failed_fetch_diagnosis("https://api.handle.me/handle/goose", LEDGER)
        clause = loop._diagnosis_clause("https://api.handle.me/handle/goose", LEDGER)
        self.assertEqual(clause.strip().lower(), d.lstrip(" —-").strip().lower())


class TheRejectionClassIsUnchangedInSubstanceTests(unittest.TestCase):
    def test_the_user_agent_difference_is_real_and_still_named(self):
        fact = _fact("urllib.error.HTTPError: HTTP Error 403: Forbidden for url: "
                     "https://api.handle.me/handles/goose")
        self.assertIn("User-Agent", fact)
        self.assertIn("python-urllib", fact)
        self.assertNotIn("No such route", fact)   # a 403 is not a routing verdict


class NeitherAnchorNamesTheProjectTests(unittest.TestCase):
    def test_the_model_never_reads_it(self):
        for name in ("fetch_route_mismatch", "fetch_route_mismatch_path"):
            self.assertNotIn("cria", prompts.load(name).lower(), name)


if __name__ == "__main__":
    unittest.main()
