"""cria reached the host. The coder's code could not. cria never said so.

Run 1786047359: the ledger recorded `https://api.handle.me → HTTP 200` in every prompt while the
coder's script got `HTTP Error 403: Forbidden` from that same host eight times. The difference is the
User-Agent — cria's fetcher sends a browser one, urllib sends `Python-urllib/3.12`. cria's own tool
description warns about exactly this, and the reasoner's own prompt already carries the rule in prose
("that mismatch IS the diagnosis"). Prose is not a computation: four steers told the coder the sandbox
was blocking the network, a satisfaction judge certified it, and the coder wrote that falsehood into
two shipped documents. live_test MISS.
"""
import os
import tempfile
import unittest

from cria import loop

LEDGER = {"https://api.handle.me": ("HTTP 200", "", "", ""),
          "https://api.handle.me/openapi.json": ("HTTP 200", "GET /handles/{handle}", "x", "")}
# the coder's real failure line — note it carries NO url of its own
CODER_403 = [{"role": "tool",
              "content": "Chunk ID: 0fe1a1\nProcess exited with code 1\nOutput:\n"
                         "Error resolving handle: HTTP 403: Forbidden\n"}]


class _WS:
    def __init__(self, *files):
        self.d = tempfile.TemporaryDirectory()
        for name, body in files:
            open(os.path.join(self.d.name, name), "w").write(body)

    def __enter__(self):
        return self.d.name

    def __exit__(self, *a):
        self.d.cleanup()


class ItFiresOnTheRealShapeTests(unittest.TestCase):
    def test_a_bare_403_plus_the_host_in_the_coders_own_source(self):
        with _WS(("resolve_handle.py", 'API_BASE = "https://api.handle.me"\n')) as ws:
            fact = loop._route_mismatch_fact(LEDGER, CODER_403, ws)
        self.assertIn("api.handle.me", fact)
        self.assertIn("HTTP 200", fact)
        self.assertIn("HTTP 403", fact)
        self.assertIn("User-Agent", fact)

    def test_the_host_named_in_the_failure_itself_needs_no_disk_read(self):
        msgs = [{"role": "tool", "content": "Output:\n"
                 "urlopen('https://api.handle.me/handles/goose')\n"
                 "urllib.error.HTTPError: HTTP Error 403: Forbidden"}]
        self.assertIn("api.handle.me", loop._route_mismatch_fact(LEDGER, msgs, ""))

    def test_it_states_both_observations_and_prescribes_only_a_comparison(self):
        with _WS(("a.py", "https://api.handle.me")) as ws:
            fact = loop._route_mismatch_fact(LEDGER, CODER_403, ws)
        self.assertIn("Compare the two requests", fact)
        self.assertNotIn("sandbox", fact.lower())


class ItStaysSilentWithoutBothHalvesTests(unittest.TestCase):
    def test_no_host_cria_ever_reached(self):
        self.assertEqual(loop._route_mismatch_fact({}, CODER_403, ""), "")

    def test_a_host_cria_could_not_reach_either(self):
        self.assertEqual(loop._route_mismatch_fact(
            {"https://api.handle.me": ("HTTP 500", "", "", "")}, CODER_403, ""), "")

    def test_no_failure_in_the_coders_output(self):
        ok = [{"role": "tool", "content": "Output:\naddr1qxsfzsmy… resolved fine"}]
        self.assertEqual(loop._route_mismatch_fact(LEDGER, ok, ""), "")

    def test_a_failure_that_cannot_be_tied_to_the_host_is_never_guessed(self):
        """Attributing a bare 403 to 'the only host cria fetched' would be a guess, and a wrong
        attribution sends the coder at the wrong request."""
        with _WS(("a.py", "print('no url here')\n")) as ws:
            self.assertEqual(loop._route_mismatch_fact(LEDGER, CODER_403, ws), "")
        self.assertEqual(loop._route_mismatch_fact(LEDGER, CODER_403, ""), "")

    def test_crias_own_failed_fetch_is_not_the_coders_code_failing(self):
        """A `HTTP 500 err · <url>` line is cria's own fetcher reporting its attempt. The ledger
        already owns that outcome; reading it as the coder's failure would fire the mismatch against
        a host cria itself later reached at 200."""
        own = [{"role": "tool", "content": "HTTP 500 err · https://api.handle.me/openapi.json"}]
        self.assertEqual(loop._route_mismatch_fact(LEDGER, own, ""), "")

    def test_the_coders_own_prose_cannot_trigger_it(self):
        """Only tool results count — the same rule the ledger itself follows, so the coder cannot
        launder a claimed failure into cria's voice."""
        said = [{"role": "assistant", "content": "I got HTTP 403 from https://api.handle.me"}]
        self.assertEqual(loop._route_mismatch_fact(LEDGER, said, ""), "")


class OnlyARuntimeFailureCountsTests(unittest.TestCase):
    """The first cut matched a bare `HTTP 404` and shipped a false fact.

    Test files are full of status codes that were never received. Counted over maple-preview
    1786062317: `(HTTP 404)` appears 148 times and `HTTP 404` 24 times, ALL of them inside the test
    file — docstrings, `HTTPError("url", 404, ...)` mock constructors, `assertIn("404", ...)`. A cat
    or read_file of that file is a tool result, so the scraper read source as observation. cria told
    its own reasoner "Your code got HTTP 404 from that same host" in FOUR prompts. No request in
    that run ever returned 404; the real failures were 403. Rule 5b, broken by the check written to
    uphold it."""

    def _fires(self, text):
        return bool(loop._route_mismatch_fact(LEDGER, [{"role": "tool", "content": text}], ""))

    def test_the_runtime_forms_are_read(self):
        for s in ("urllib.error.HTTPError: HTTP Error 403: Forbidden · https://api.handle.me/x",
                  "403 Client Error: Forbidden for url: https://api.handle.me/x",
                  "HTTP/1.1 500 Internal Server Error from https://api.handle.me"):
            # the ` · ` render marks a cria fetch, so use a plain runtime line for the first case
            s = s.replace(" · ", " from ")
            self.assertTrue(self._fires(s), s)

    def test_source_code_mentioning_a_status_is_never_an_observation(self):
        for s in ('Output:\n    """Test handling when a handle is not found (HTTP 404)."""\n'
                  "    # https://api.handle.me/handles/x",
                  'Output:\n    http_error = HTTPError("https://api.handle.me/x", 404, "Not Found", {}, None)',
                  'Output:\n    self.assertIn("404", str(result))  # https://api.handle.me',
                  "Output:\n    # just check it contains HTTP 404 from https://api.handle.me"):
            self.assertFalse(self._fires(s), s)

    def test_a_programs_own_prose_still_counts_when_it_carries_the_reason(self):
        """The discriminator is the REASON PHRASE, so the original walked case survives:
        run 1786047359 printed `Error resolving handle: HTTP 403: Forbidden`."""
        self.assertTrue(self._fires("Output:\nError resolving handle: HTTP 403: Forbidden\n"
                                    "from https://api.handle.me"))
        self.assertTrue(self._fires("Output:\nError: Handle not found (HTTP 403): Forbidden\n"
                                    "at https://api.handle.me"))

    def test_a_status_with_no_reason_phrase_is_not_an_observation(self):
        for s in ("Output:\n    assert resp.status_code == 404  # https://api.handle.me",
                  "Output:\n    RETRY_ON = [500, 502, 503]  # https://api.handle.me"):
            self.assertFalse(self._fires(s), s)


class WiringTests(unittest.TestCase):
    def test_the_fetch_ground_truth_carries_it(self):
        import inspect
        src = inspect.getsource(loop._fetch_ground_truth)
        self.assertIn("_route_mismatch_fact", src)
        self.assertIn("workspace_root", src)


if __name__ == "__main__":
    unittest.main()
