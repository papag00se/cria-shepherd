"""A path template's VARIABLE NAME is not part of the route."""
import unittest

from cria.urlgrounding import URL_RE, ungrounded_urls

# Verbatim from both zaya1 runs (2026-08-01). cria's own evidence block listed
# /holders/{address} as fetched and verified; the plan wrote /holders/{holder_address}.
EVIDENCE = ("every route and field below came out of a source you fetched. "
            "GET https://api.handle.me/handles/{handle} -> holder(string), resolved_addresses{ada}. "
            "GET https://api.handle.me/holders/{address} -> total_handles(integer), address(string).")


class TemplateExtractionTests(unittest.TestCase):
    def test_a_balanced_template_is_not_truncated_at_the_brace(self):
        self.assertEqual(URL_RE.findall("fetch https://api.handle.me/holders/{holder_address} now"),
                         ["https://api.handle.me/holders/{holder_address}"])

    def test_an_ordinary_url_still_ends_cleanly(self):
        for text, want in (("see https://api.handle.me/openapi.json, then", "https://api.handle.me/openapi.json"),
                           ('{"url": "https://api.handle.me/x"}', "https://api.handle.me/x"),
                           ("(https://api.handle.me/y)", "https://api.handle.me/y")):
            with self.subTest(text=text):
                self.assertEqual(URL_RE.findall(text)[0].rstrip("`.,:;'\"*)]}> "), want)


class GroundingTests(unittest.TestCase):
    """The measured failure: this fired on BOTH zaya1 runs, told the model its own verified route was
    UNVERIFIED, and instructed it to "go fetch EACH of them now with your own tools" during a phase
    whose only tool was submit_plan. One wasted planner round each, on a model decoding at 40 tok/s
    against a 15-minute wall."""

    def test_the_same_route_under_a_different_variable_name_is_GROUNDED(self):
        self.assertEqual(
            ungrounded_urls("Step 2: GET https://api.handle.me/holders/{holder_address}", EVIDENCE), [])

    def test_several_spellings_of_one_route_all_ground(self):
        for spelling in ("{address}", "{addr}", "{holder}", "{stake_address}"):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    ungrounded_urls(f"GET https://api.handle.me/holders/{spelling}", EVIDENCE), [])

    def test_an_INVENTED_route_is_still_caught(self):
        # The whole point of the guard survives: a route the evidence never defines is still flagged.
        self.assertTrue(ungrounded_urls("GET https://api.handle.me/resolve/{handle}", EVIDENCE))

    def test_an_invented_HOST_is_still_caught(self):
        self.assertTrue(ungrounded_urls("GET https://evil.example/holders/{address}", EVIDENCE))

    def test_a_real_route_with_no_template_still_grounds(self):
        self.assertEqual(ungrounded_urls("GET https://api.handle.me/handles/{handle}", EVIDENCE), [])
