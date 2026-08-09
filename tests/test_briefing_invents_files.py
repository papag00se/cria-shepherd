"""nemotron-nano 1786243834, call 0071: the self-compact briefing FABRICATED state — "The real
files created so far are `script.py` and `tests.py`." — over a workspace containing nothing. The
next coder turn absorbed it ("the user mentioned that the script is in progress") and produced the
deliverable as chat prose instead of write_file calls.

`_briefing_disk_truth` refuted the mirror-image fault (a briefing DENYING files the disk shows)
but had no arm for invention. The arm is #8-shaped because a lexical rule alone fails the
prevalence test: swept over all 459 captured briefings, file-shaped tokens that are NOT files ride
constantly — `requests.get` 408×, the API field `resolved_addresses.ada` 204×, `unittest.mock`
108×, `sys.argv` 58×. Whether a name is claimed AS AN EXISTING FILE is a judgment, so code gathers
the candidates and ONE closed question selects. The reasoner may only pick from cria's list; NONE,
prose, or an unreadable reply appends nothing.
"""
import unittest

from cria import loop, prompts

# the walked fabrication, verbatim shape
BRIEFING = ("The openapi.json spec has been read. The real files created so far are `script.py` "
            "and `tests.py`. The script is in the `tmp` directory. Use requests.get(url) to call "
            "the API and read resolved_addresses.ada from the response. Next, create README.md.")
FILES = "tmp/read-only/api.handle.me_openapi.json (96221 B)"
TASK = ("Write a Python script using the Ada Handles API (api.handle.me). When you're done, "
        "add a README that explains how to run it.")


class CandidateGatheringTests(unittest.TestCase):
    def test_the_fabricated_files_are_candidates(self):
        c = loop._briefing_files_absent(BRIEFING, FILES, TASK)
        self.assertIn("script.py", c)
        self.assertIn("tests.py", c)
        self.assertIn("README.md", c)   # planned, not claimed — the JUDGE separates those, not code

    def test_a_call_shape_is_not_a_candidate(self):
        self.assertNotIn("requests.get", loop._briefing_files_absent(BRIEFING, FILES, TASK))

    def test_a_field_path_still_reaches_the_judge(self):
        """`resolved_addresses.ada` is file-shaped; code cannot know it is an API field. It stays a
        candidate — the judge prompt names exactly this class as not-a-file."""
        self.assertIn("resolved_addresses.ada", loop._briefing_files_absent(BRIEFING, FILES, TASK))

    def test_a_file_on_disk_is_not_a_candidate(self):
        c = loop._briefing_files_absent("openapi.json was saved. api.handle.me_openapi.json too.",
                                        FILES, TASK)
        self.assertNotIn("api.handle.me_openapi.json", c)

    def test_a_name_the_task_uses_is_not_a_candidate(self):
        self.assertNotIn("api.handle.me", loop._briefing_files_absent(
            "The api.handle.me source is the authority.", FILES, TASK))

    def test_prose_fragments_are_not_candidates(self):
        self.assertEqual(loop._briefing_files_absent("Files exist (e.g. in tmp).", FILES, TASK), [])


class TheJudgeSelectsNeverAuthorsTests(unittest.TestCase):
    CANDS = ["script.py", "tests.py", "README.md", "resolved_addresses.ada"]

    def test_whole_line_picks_are_taken(self):
        self.assertEqual(loop._select_named("script.py\ntests.py", self.CANDS),
                         ["script.py", "tests.py"])

    def test_decorated_picks_are_taken(self):
        self.assertEqual(loop._select_named("- `script.py`\n* tests.py", self.CANDS),
                         ["script.py", "tests.py"])

    def test_a_name_not_in_the_candidates_is_ignored(self):
        self.assertEqual(loop._select_named("evil.py\nscript.py", self.CANDS), ["script.py"])

    def test_none_and_prose_select_nothing(self):
        for ans in ("NONE", "none.", "", None,
                    "The summary claims script.py exists so I would say that one."):
            with self.subTest(ans=str(ans)[:30]):
                self.assertEqual(loop._select_named(ans, self.CANDS), [])


class TheAppendTests(unittest.TestCase):
    def test_a_confirmed_invention_is_refuted_additively(self):
        out = loop._briefing_disk_truth(BRIEFING, FILES, ask=lambda q: "script.py\ntests.py",
                                        task=TASK)
        self.assertTrue(out.startswith(BRIEFING))          # never deletes
        self.assertIn("do NOT exist on disk", out)
        self.assertIn("script.py, tests.py", out)
        self.assertNotIn("README.md", out.split("do NOT exist")[1])  # only the judge's picks

    def test_the_judge_sees_the_briefing_and_only_the_candidates(self):
        seen = {}
        loop._briefing_disk_truth(BRIEFING, FILES, ask=lambda q: seen.setdefault("q", q) and "NONE",
                                  task=TASK)
        self.assertIn("The real files created so far", seen["q"])
        self.assertIn("script.py", seen["q"])
        self.assertNotIn("requests.get", seen["q"].rsplit("CANDIDATES", 1)[1])

    def test_no_ask_means_todays_behavior(self):
        self.assertEqual(loop._briefing_disk_truth(BRIEFING, FILES), BRIEFING)

    def test_none_appends_nothing(self):
        self.assertEqual(loop._briefing_disk_truth(BRIEFING, FILES, ask=lambda q: "NONE",
                                                   task=TASK), BRIEFING)

    def test_both_arms_compose(self):
        b = "resolver.py has not been written. The real files created so far are `tests.py`."
        out = loop._briefing_disk_truth(b, "resolver.py (100 B)", ask=lambda q: "tests.py")
        self.assertIn("DO exist on disk", out)      # denial arm: resolver.py is real
        self.assertIn("do NOT exist on disk", out)  # invention arm: tests.py is not

    def test_no_candidates_means_no_call(self):
        calls = []
        loop._briefing_disk_truth("All work is described in prose with no file names.",
                                  FILES, ask=lambda q: calls.append(q) or "NONE", task=TASK)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
