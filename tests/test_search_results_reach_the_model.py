"""Every web_search was filed to disk and the model was handed a pointer. It never opened the file.

    nemotron-elastic/go. Coder: "Ok, I'm stuck. Let's search for a decimal library. Use web_search."
    The spill file's fourth line: "decimal package - github.com/shopspring/decimal - Go Packages".
    The go.mod it shipped: `require github.com/elliott/decimal v1.6.0` — a package that does not
    exist. Zero spill reads across 124 calls in that cell; the whole task failed on it.

This function's own comment already named the DESCRIPTIONS as the snippet poison, and that is the
entire special case: titles and links are short, and they are exactly the fact a model needs when it
is choosing a dependency. So the unconditional spill is deleted and search obeys the size rule cria
already owns for command output — inline when it fits under INLINE_RESULT_MAX_BYTES, spill when it
does not. The full results with descriptions are written to the spill file either way, so the grep
route and the ledger entry are unchanged.

These run the ACTUAL composed shell fragment against Brave-shaped JSON. A composed command is only
correct if it executes, and this one already shipped a quoting bug that a string assertion could not
have seen: the inline note contains "each page's description", and json.dumps does not escape an
apostrophe, so the `python3 -c '...'` body closed early and bash died on the remainder.
"""

import json
import os
import subprocess
import unittest
from uuid import uuid4

import pytest

from cria import assistruntime, content_reduce, writeproxy
from cria.loop import LoopStore


@pytest.fixture(autouse=True)
def isolated_search_workspace(tmp_path, monkeypatch):
    # Never create or remove ./tmp in the shared repository checkout.
    monkeypatch.chdir(tmp_path)


def run_search(body, query="go decimal library", *, cwd=None, session=None):
    """Lower through the selected public lifecycle, then run the real emitted parser.

    Only the provider/network leg is replaced with Brave-shaped stdin. Retention and
    storage are settled from the actual completion and actual harness result.
    """
    session = session or "sid:search-test-" + uuid4().hex
    store = LoopStore()
    owner = store.get_guard(session, create=True)
    completion = {"choices": [{"message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "search-call", "type": "function", "function": {
            "name": "web_search", "arguments": json.dumps({"query": query})}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=2)):
        lowered = writeproxy.translate_outbound(completion, shell, injected={"web_search"},
            brave_key="test-key", session=session, externalization_owner=owner)
        writeproxy.retain_externalizations(owner, lowered)
        command = json.loads(lowered["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["cmd"]
        # Execute the emitted shell quoting verbatim: an apostrophe in the note
        # once broke the command even though the Python program itself was valid.
        _, separator, parser = command.partition(" | ")
        parser, fallback, _ = parser.rpartition(" || printf")
        assert separator and fallback and parser.startswith("python3 -c "), "update emitted-parser adapter"
        result = subprocess.run(["bash", "-c", parser], input=body,
            capture_output=True, text=True, timeout=60, cwd=cwd)
        history = [lowered["choices"][0]["message"], {"role": "tool",
            "tool_call_id": "search-call", "content": result.stdout}]
        writeproxy.observe_externalization_results(owner, history)
        visible = writeproxy.represent_inbound(history, sess_key=session)
    return result.returncode, visible[-1]["content"], result.stderr


def brave(n, desc_len=200, title="decimal package - github.com/shopspring/decimal - Go Packages"):
    return json.dumps({"web": {"results": [
        {"title": f"{title} {i}", "url": f"https://pkg.go.dev/github.com/shopspring/decimal?i={i}",
         "description": "x" * desc_len} for i in range(n)]}})


def run(body, query="go decimal library"):
    return run_search(body, query)


class TheComposedCommandActuallyRunsTests(unittest.TestCase):
    def test_it_is_not_a_shell_syntax_error(self):
        rc, _, err = run(brave(3))
        self.assertEqual(rc, 0, err)
        self.assertNotIn("syntax error", err)

    def test_an_apostrophe_in_crias_own_note_does_not_end_the_quoting(self):
        """The measured bug in this change: "each page's description" closed `python3 -c '`."""
        self.assertIn("'", writeproxy.prompts.load("search_inline_note"))
        self.assertEqual(run(brave(3))[0], 0)


class ResultsTheModelCanActOnTests(unittest.TestCase):
    def test_the_titles_and_links_are_inline(self):
        rc, out, _ = run(brave(5))
        self.assertEqual(rc, 0)
        self.assertIn("shopspring", out)
        self.assertIn("https://pkg.go.dev", out)

    def test_the_count_is_stated(self):
        self.assertIn("5 results:", run(brave(5))[1])

    def test_the_descriptions_are_not_inline(self):
        """The noise this function was written to keep out stays out."""
        _, out, _ = run(brave(5, desc_len=400))
        self.assertNotIn("x" * 400, out)

    def test_the_inline_answer_stays_under_the_bound_cria_enforces(self):
        _, out, _ = run(brave(20, desc_len=900))
        self.assertLessEqual(len(out.encode()), content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_a_realistic_search_is_never_spilled_away_from_the_model(self):
        """20 results is Brave's per-request max, so in practice the model always gets the links."""
        _, out, _ = run(brave(20))
        self.assertIn("shopspring", out)
        self.assertNotIn("results saved to", out)


class WhenItGenuinelyDoesNotFitTests(unittest.TestCase):
    def huge(self):
        return json.dumps({"web": {"results": [
            {"title": "T" * 400, "url": "https://x/" + "u" * 300, "description": "d"}
            for _ in range(20)]}})

    def test_the_pointer_is_handed_back_instead(self):
        rc, out, _ = run(self.huge())
        self.assertEqual(rc, 0)
        self.assertIn("results saved to", out)

    def test_and_that_pointer_is_short(self):
        self.assertLess(len(run(self.huge())[1].encode()),
                        content_reduce.INLINE_RESULT_MAX_BYTES)


class TheSpillFileIsWrittenEitherWayTests(unittest.TestCase):
    def test_the_full_text_lands_on_disk_even_when_inlined(self):
        """The grep route and the ledger entry are unchanged — only what is SHOWN changed."""
        run(brave(5, desc_len=500))
        files = os.listdir("./tmp/reference")
        self.assertEqual(len(files), 1)
        body = open(os.path.join("./tmp/reference", files[0])).read()
        self.assertIn("x" * 500, body)          # descriptions kept on disk
        self.assertIn("shopspring", body)


class TheOtherOutcomesAreUnchangedTests(unittest.TestCase):
    def test_an_empty_result_set_says_no_results(self):
        self.assertEqual(run(json.dumps({"web": {"results": []}}))[1].strip(), "no results")

    def test_an_api_error_surfaces_its_own_text(self):
        """A 401/429 body is valid JSON; saying "no results" told the model the web held nothing."""
        _, out, _ = run(json.dumps({"error": {"code": "RATE_LIMITED"}}))
        self.assertIn("search API error", out)
        self.assertIn("RATE_LIMITED", out)

    def test_an_unparseable_body_exits_nonzero_so_the_fallback_fires(self):
        self.assertNotEqual(run("<html>429</html>")[0], 0)

    def test_an_empty_result_set_still_writes_the_file_cria_promised(self):
        """INVERTED 2026-09-18, deliberately. This assertion used to require the opposite — that an
        empty search leaves no file — which was true of the world cf827a9 (2026-08-13) shipped into:
        that change was about snippet poison and inline-vs-spill sizing, and nothing depended on the
        empty case either way, so the test simply pinned what the code then did.

        `note_search_spill` later made the empty case load-bearing. cria now RECORDS this query's
        spill path when it COMPOSES the search, and that record is the sole warrant for the re-hunt
        refusal telling the coder "its results were saved to <path> — READ THAT FILE". With no file
        written, cria promises an artifact that does not exist.

        Measured on cart-billing-go x ternary-bonsai-2 (session 01a0b6aa, calls 0008-0012): the
        coder obeyed the pointer, cria answered "is not there — nothing was read", and three tool
        calls went to a phantom before it re-ran the same dead query (#5b twice, #11b).

        cf827a9's actual intent is untouched: a zero-result file carries no descriptions, because
        there are none, so there is no snippet poison to inline or withhold.
        """
        run(json.dumps({"web": {"results": []}}))
        files = os.listdir("./tmp/reference") if os.path.isdir("./tmp/reference") else []
        self.assertEqual(len(files), 1, "cria recorded a spill path for this query; it must exist")
        self.assertTrue(open(os.path.join("./tmp/reference", files[0])).read().startswith("0 results:"))


if __name__ == "__main__":
    unittest.main()
