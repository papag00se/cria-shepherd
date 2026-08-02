"""cria writes the search pointer as `./tmp/read-only/x.txt`; the model calls read_file with
`/tmp/read-only/x.txt`. Both patterns accept either spelling, and a dict keyed on the raw capture
made them two different files.

Walked on ada-handles_mellum2_codex_poff_1785686596: the query lookup missed, so cria told the
relevance judge `THE SEARCH QUERY THE AGENT USED: (none)`. The judge answered on that basis — "the
search was effectively a null query and the results were noise" — and cria PERMANENTLY DELETED the
file. It held github.com/koralabs/handles-public-api (the API behind the host the task named) and
the docs page on resolving handles to addresses. The model gave up in the same turn.
"""
import unittest

from cria import loop


class SearchKeyTests(unittest.TestCase):
    SPELLINGS = ("./tmp/read-only/search-ada.txt",
                 "/tmp/read-only/search-ada.txt",
                 "tmp/read-only/search-ada.txt")

    def test_every_spelling_is_one_key(self):
        self.assertEqual(len({loop._search_key(p) for p in self.SPELLINGS}), 1)

    def test_different_files_stay_different(self):
        self.assertNotEqual(loop._search_key("./tmp/read-only/search-a.txt"),
                            loop._search_key("/tmp/read-only/search-b.txt"))

    def test_it_survives_empty_and_none(self):
        self.assertEqual(loop._search_key(""), "/")
        self.assertEqual(loop._search_key(None), "/")

    def test_the_pointer_query_is_found_from_the_readers_spelling(self):
        # The exact miss: pointer written one way, read the other.
        import re
        m = loop._SEARCH_POINTER_RE.search(
            'web_search "ada handles api" — results saved to ./tmp/read-only/search-ada.txt')
        self.assertIsNotNone(m)
        q_of = {loop._search_key(m.group(2)): m.group(1)}
        self.assertEqual(q_of.get(loop._search_key("/tmp/read-only/search-ada.txt")),
                         "ada handles api")

    def test_the_judge_is_never_handed_a_none_query_for_a_pointer_it_holds(self):
        m = loop._SEARCH_POINTER_RE.search(
            'web_search "resolve ada handle" — results saved to ./tmp/read-only/search-r.txt')
        q_of = {loop._search_key(m.group(2)): m.group(1)}
        self.assertNotEqual(q_of.get(loop._search_key("/tmp/read-only/search-r.txt"), ""), "")

    def test_every_call_site_uses_the_key(self):
        import inspect
        src = inspect.getsource(loop.Loop._judge_search_reads)
        self.assertNotIn("q_of.get(f,", src)                  # the raw-path lookup is gone
        self.assertEqual(src.count("_search_key("), 6)   # q_of key+lookup, judged x2, poisoned x2


if __name__ == "__main__":
    unittest.main()
