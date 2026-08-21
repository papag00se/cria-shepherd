"""cria writes the search pointer as `./tmp/reference/x.txt`; the model calls read_file with
`/tmp/reference/x.txt`. Both patterns accept either spelling, and a dict keyed on the raw capture
made them two different files.

Walked on ada-handles_mellum2_codex_poff_1785686596: the query lookup missed, so cria told the
relevance judge `THE SEARCH QUERY THE AGENT USED: (none)`. The judge answered on that basis — "the
search was effectively a null query and the results were noise" — and cria PERMANENTLY DELETED the
file. It held github.com/koralabs/handles-public-api (the API behind the host the task named) and
the docs page on resolving handles to addresses. The model gave up in the same turn.
"""
import os
import tempfile
import unittest

from cria import loop
from cria.config import Role


class SearchKeyTests(unittest.TestCase):
    SPELLINGS = ("./tmp/reference/search-ada_handles_api.txt",
                 "/tmp/reference/search-ada_handles_api.txt",
                 "tmp/reference/search-ada_handles_api.txt")

    def test_every_spelling_is_one_key(self):
        self.assertEqual(len({loop._search_key(p) for p in self.SPELLINGS}), 1)

    def test_different_files_stay_different(self):
        self.assertNotEqual(loop._search_key("./tmp/reference/search-a.txt"),
                            loop._search_key("/tmp/reference/search-b.txt"))

    def test_it_survives_empty_and_none(self):
        self.assertEqual(loop._search_key(""), "/")
        self.assertEqual(loop._search_key(None), "/")

    def test_the_query_is_found_from_the_readers_spelling(self):
        # The exact miss: cria writes the file one way, the model reads it the other.
        from cria import webfetch
        webfetch.clear_cache()
        webfetch.note_search_spill("s1", "ada handles api")
        q_of = {loop._search_key(f): q
                for f, q in webfetch.spilled_search_files("s1").items()}
        self.assertEqual(q_of.get(loop._search_key("/tmp/reference/search-ada_handles_api.txt")),
                         "ada handles api")

    def test_the_query_is_the_one_the_model_typed(self):
        """Not the lowercased key cria dedupes searches by — the judge rules on what was asked."""
        from cria import webfetch
        webfetch.clear_cache()
        webfetch.note_search_spill("s1", "Ruby Gem EU Membership")
        self.assertEqual(list(webfetch.spilled_search_files("s1").values()), ["Ruby Gem EU Membership"])

    def test_a_file_cria_never_spilled_has_no_query(self):
        """And so is never judged — the floor under a destructive verdict."""
        from cria import webfetch
        webfetch.clear_cache()
        self.assertEqual(webfetch.spilled_search_files("s1"), {})
        self.assertEqual(webfetch.spilled_search_files(None), {})

    def test_every_call_site_uses_the_key(self):
        """The whole incident, end to end: drive the REAL `Loop._judge_search_reads` with the
        pointer written one spelling (`./tmp/reference/...`) and read with another
        (`/tmp/reference/...`) — the exact mismatch from run 1785686596. A source-text count of
        `_search_key(` call sites can drift out of sync with the code (the right count today isn't
        necessarily the right count after an unrelated edit); actually running the lookup either
        finds the query or it doesn't."""
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, "tmp", "reference"), exist_ok=True)
        with open(os.path.join(ws, "tmp", "reference", "search-ada_handles_api.txt"), "w") as f:
            f.write("koralabs/handles-public-api\nhttps://api.handle.me/openapi.json\n")

        captured = {}

        def fake_judge_search(reasoner_chat, reasoner_role, task, query, results, rlog, coder_tools=""):
            captured["query"] = query
            captured["results"] = results
            return True, True, ""

        class _Ctx:
            reasoner_chat = object()
            reasoner_role = Role(name="reasoner", backend="local")

        class _Rlog:
            def emit(self, *a, **k):
                pass

        from cria import webfetch
        webfetch.clear_cache()
        webfetch.note_search_spill("s-key", "ada handles api")   # cria spilled it, and knows the query
        saved = loop.judge_search
        loop.judge_search = fake_judge_search
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx = _Ctx()
            sess = loop.PlanSession(plan=None)
            sess.workspace_root = ws
            sess.web_session = "s-key"
            body = {"messages": [
                {"role": "user", "content": "resolve an ada handle"},
                {"role": "tool", "content": ('web_search "ada handles api" — results saved to '
                                             './tmp/reference/search-ada_handles_api.txt')},
                {"role": "assistant", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {
                        "name": "read_file",
                        "arguments": '{"path": "/tmp/reference/search-ada_handles_api.txt"}'}}]},
                {"role": "tool", "tool_call_id": "c1",
                 "content": "search-ada_handles_api.txt is a large reference document — grep it instead"},
            ], "tools": []}
            lp._judge_search_reads(sess, body, _Rlog())
        finally:
            loop.judge_search = saved
        self.assertEqual(captured.get("query"), "ada handles api",
                         "the judge was handed a query it could not find — the exact walked defect")
        self.assertTrue(captured.get("results"), "the judge must see the REAL on-disk results")


if __name__ == "__main__":
    unittest.main()
