"""A server declining to answer is not the same fact as a wrong URL, and cria said it was.

`client_error_note` appended one sentence under every 4xx: "the failure is on your side (a 4xx is a
client error — the URL, the path, or the version segment in it was wrong, not the service)". That is
what a 400 or a 404 means. It is false of a refusal — a 401 wants credentials, a 429 wants a wait,
and a 403 is very often a bot wall in front of a page that is exactly right.

Walked on the sub-40 pass: feed-pipeline-java x nemotron-elastic, scored 28. At call 0055 the coder
fetched opencsv's own apidocs page and got a 403 carrying Cloudflare's "Just a moment… Enable
JavaScript and cookies to continue". cria told it the address was wrong. That page holds the class
list the run spent the next 78 calls failing to guess; it was never fetched again, and the ledger
carried a bare "HTTP 403" to the end.

This does not reinstate a menu of causes — `fetched_facts_sections` records at length why that was
removed, and every word of it still applies. It withdraws a cause cria cannot support and states
only what the server did (#5b, #3).
"""

import unittest

from cria import webfetch


class ARefusalNamesNoFaultInTheUrlTests(unittest.TestCase):
    CHALLENGE = "Just a moment... Enable JavaScript and cookies to continue"

    def test_the_measured_case(self):
        out = webfetch.client_error_note(403, self.CHALLENGE)
        self.assertIn("REFUSED", out)
        self.assertIn("not the same as the address being wrong", out)
        self.assertNotIn("on your side", out)

    def test_every_refusal_status_reads_the_same_way(self):
        for code in (401, 403, 407, 429, 451):
            with self.subTest(status=code):
                out = webfetch.client_error_note(code, "body")
                self.assertIn(f"HTTP {code}", out)
                self.assertNotIn("on your side", out)

    def test_it_does_not_send_the_model_to_read_a_body_that_is_not_there(self):
        """The same rule the with_body/no_body split already follows."""
        out = webfetch.client_error_note(403, "")
        self.assertIn("sent nothing back", out)
        self.assertNotIn("read that first", out)

    def test_it_names_no_cause(self):
        """A menu of causes is a menu a stuck model orders from — the reason the old 401/403/429
        explanations were removed from the fetch ledger. Say what happened, not why."""
        out = webfetch.client_error_note(403, self.CHALLENGE).lower()
        for guess in ("credential", "rate limit", "authenticat", "javascript", "bot"):
            self.assertNotIn(guess, out)


class AWrongAddressStillReadsAsOneTests(unittest.TestCase):
    def test_a_missing_path_is_unchanged(self):
        self.assertIn("on your side", webfetch.client_error_note(404, "not found"))

    def test_a_malformed_request_is_unchanged(self):
        """400 means the request itself was wrong, which is exactly what the old sentence says."""
        out = webfetch.client_error_note(400, "Shorthand URLs (https://docs.rs/about/redirections)")
        self.assertIn("on your side", out)
        self.assertIn("how the URL should be formed", out)

    def test_a_server_error_is_still_silent(self):
        self.assertEqual(webfetch.client_error_note(503, "gateway down"), "")

    def test_a_url_cria_chose_still_says_so_first(self):
        """The `ours` case outranks both: blaming the coder for a request cria authored is the
        false fact this function was last fixed for."""
        out = webfetch.client_error_note(403, "challenge", ours=True)
        self.assertIn("was not yours", out)


if __name__ == "__main__":
    unittest.main()
