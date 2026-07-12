import unittest

from cria import planner_tools as pt


class SearchGate400Tests(unittest.TestCase):
    """The hard nudge: a repeated web_search is refused as an HTTP 400 so a small model
    can't burn the gather re-searching the same terms."""

    def test_first_proceeds_repeat_is_blocked_as_400(self):
        recent = []
        self.assertIsNone(pt.gate_search(recent, "api.handle.me get_handle endpoint"))  # runs
        blocked = pt.gate_search(recent, "get_handle endpoint on api.handle.me")        # reorder = same
        self.assertIsNotNone(blocked)
        self.assertIn("HTTP 400", blocked)
        self.assertIn("searched this before", blocked)

    def test_domain_repeat_steers_to_fetch_it_directly(self):
        recent = []
        pt.gate_search(recent, "api.handle.me handles response schema")
        blocked = pt.gate_search(recent, "handles response schema api.handle.me")
        self.assertIn("web_fetch https://api.handle.me", blocked)  # stop searching, go fetch

    def test_genuine_new_direction_proceeds(self):
        recent = []
        pt.gate_search(recent, "api.handle.me get_handle endpoint")
        self.assertIsNone(pt.gate_search(recent, "cardano staking rewards calculation"))

    def test_refinement_is_allowed(self):
        recent = []
        pt.gate_search(recent, "rust async trait")
        # longer, keeps the whole prior + adds specificity → a narrowing, not a re-hunt
        self.assertIsNone(pt.gate_search(recent, "rust async trait object safety dyn"))

    def test_anchor_dominated_reword_is_caught(self):
        recent = []
        pt.gate_search(recent, "api.handle.me handles/goose JSON response example")
        self.assertIsNotNone(pt.gate_search(recent, "api.handle.me handles/goose response"))


class ReadOnlyGuardTests(unittest.TestCase):
    def test_reads_allowed(self):
        for cmd in ("ls -la", "cat handler.py", "grep -r foo .", "git status", "git log --oneline",
                    "curl https://api.handle.me/v1/handles/goose", "find . -name '*.py'", "head -20 x.py"):
            self.assertTrue(pt.is_read_only_command(cmd), cmd)

    def test_writes_refused(self):
        for cmd in ("echo x > f", "rm -rf .", "sed -i s/a/b/ f", "git commit -m x",
                    "curl -o f https://x", "python setup.py build", "mkdir d", "cat a | tee b"):
            self.assertFalse(pt.is_read_only_command(cmd), cmd)


class DomainDetectTests(unittest.TestCase):
    def test_domains_not_filenames(self):
        self.assertEqual(pt.first_domain_in("api.handle.me handles endpoint"), "api.handle.me")
        self.assertEqual(pt.first_domain_in("docs on example.com"), "example.com")
        self.assertIsNone(pt.first_domain_in("read handler.py and config.json"))
        self.assertIsNone(pt.first_domain_in("cardano staking rewards"))


class SearchFormatTests(unittest.TestCase):
    def test_format_results(self):
        out = pt.format_results("q", [{"title": "T1", "url": "https://e.com/1", "description": "D1."}])
        self.assertIn("Search results for: q", out)
        self.assertIn("T1", out)
        self.assertIn("https://e.com/1", out)

    def test_no_key_web_search_is_graceful(self):
        # gate proceeds (records), then the missing key is reported — no network, no crash
        msg = pt.execute_tool("web_search", {"query": "x y z"}, ".", "", [], _Rlog())
        self.assertIn("no search API key", msg)


class _Rlog:
    def emit(self, *a, **k):
        pass


if __name__ == "__main__":
    unittest.main()
