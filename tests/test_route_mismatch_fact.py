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
        # only the classes cria can DIAGNOSE fire; the matcher itself reads all runtime forms
        for s in ("urllib.error.HTTPError: HTTP Error 403: Forbidden from https://api.handle.me/x",
                  "403 Client Error: Forbidden for url: https://api.handle.me/x"):
            self.assertTrue(self._fires(s), s)
        for shape in ("HTTP Error 403: Forbidden", "403 Client Error: Forbidden",
                      "HTTP/1.1 500 Internal Server Error"):
            self.assertTrue(loop._CODER_HTTP_FAIL.search(shape), shape)

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


class TheStatusDecidesTheDiagnosisTests(unittest.TestCase):
    """The first cut named the User-Agent whatever the code was.

    mellum2 1786064398 got a REAL 404 — `Error: 404 Client Error: Not Found for url:
    https://api.handle.me/v1/handles/goose` — because it invented a `/v1/handles` route the API does
    not have. cria told it 23 times that the difference was its User-Agent. A 404 is a wrong path; a
    401/403/429 is a rejected request. One cause for both sent the coder at its headers while the
    path stayed broken. Everything else gets silence — cria has no cause it can name."""

    L = {"https://api.handle.me/openapi.json": ("HTTP 200", "", "", "")}

    def _fact(self, out):
        return loop._route_mismatch_fact(self.L, [{"role": "tool", "content": "Output:\n" + out}], "")

    def test_a_404_names_the_two_PATHS_and_never_the_user_agent(self):
        f = self._fact("Error: 404 Client Error: Not Found for url: "
                       "https://api.handle.me/v1/handles/goose")
        self.assertIn("DIFFERENT PATHS", f)
        self.assertIn("https://api.handle.me/v1/handles/goose", f)
        self.assertIn("https://api.handle.me/openapi.json", f)
        self.assertNotIn("User-Agent", f)
        self.assertIn("not your headers", f)

    def test_a_403_still_names_the_user_agent(self):
        f = self._fact("urllib.error.HTTPError: HTTP Error 403: Forbidden\n"
                       "from https://api.handle.me/handles/goose")
        self.assertIn("User-Agent", f)
        self.assertNotIn("DIFFERENT PATHS", f)

    def test_a_class_cria_cannot_diagnose_says_nothing(self):
        self.assertEqual(self._fact("HTTP/1.1 500 Internal Server Error https://api.handle.me/x"), "")
        self.assertEqual(self._fact("HTTP Error 418: I am a teapot https://api.handle.me/x"), "")

    def test_a_404_on_the_SAME_url_cria_fetched_is_not_a_path_difference(self):
        f = self._fact("404 Client Error: Not Found for url: https://api.handle.me/openapi.json")
        self.assertEqual(f, "")


class _Sess:
    def __init__(self, fetched_pages, workspace_root):
        self.fetched_pages = fetched_pages
        self.workspace_root = workspace_root


class WiringTests(unittest.TestCase):
    """``_fetch_ground_truth`` is the caller `_route_mismatch_fact` actually runs behind in
    production (loop.py's coder frame) — it must fold the mismatch fact into the ledger text it
    hands the coder, and it must carry the session's REAL ``workspace_root`` through (not a blank
    one), since the mismatch only fires once the coder's own source names the host."""

    def test_the_fetch_ground_truth_carries_the_mismatch_and_the_workspace_root(self):
        with _WS(("resolve_handle.py", 'API_BASE = "https://api.handle.me"\n')) as ws:
            out = loop._fetch_ground_truth(CODER_403, _Sess(dict(LEDGER), ws))
        self.assertIn("User-Agent", out)
        self.assertIn("HTTP 403", out)
        self.assertIn("api.handle.me", out)

    def test_a_blank_workspace_root_never_fires_the_mismatch(self):
        # Proves workspace_root really travels: with none passed, `_fetch_ground_truth` cannot
        # tie the bare 403 to a host, so the mismatch fact must be absent from its output.
        out = loop._fetch_ground_truth(CODER_403, _Sess(dict(LEDGER), ""))
        self.assertNotIn("User-Agent", out)


if __name__ == "__main__":
    unittest.main()
