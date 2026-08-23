"""The judge that decides whether research is on target can see the research already done.

Its prompt held the task and the query and nothing else. On cart-billing-go x nemotron-elastic
1787434778 it called a query for `github.com/oklog/decimal` on-target TWICE, while cria's own session
record held two `remote: Repository not found` and two `404: Not Found` for that exact repository.
cria then substituted a web_fetch of it for the coder's search, charged the coder 9.4KB of GitHub's
404 page, and appended "That request FAILED and the failure is on your side"."""
import unittest

from cria import prompts


class TheJudgeSeesTheRecordTests(unittest.TestCase):
    def test_the_user_prompt_carries_what_was_tried(self):
        out = prompts.render("search_query_judge_user", task="build a cart",
                             query="oklog decimal go module",
                             tried="PAGES ALREADY FETCHED:\n- https://github.com/oklog/decimal -> HTTP 404")
        self.assertIn("HTTP 404", out)
        self.assertIn("oklog decimal go module", out)

    def test_it_renders_cleanly_when_nothing_was_tried(self):
        out = prompts.render("search_query_judge_user", task="t", query="q", tried="")
        self.assertNotIn("{{TRIED}}", out)

    def test_the_system_prompt_forbids_recommending_what_already_404d(self):
        t = prompts.load("search_query_judge")
        self.assertIn("already tried and failed", t.lower())
        self.assertIn("do not recommend a different version of it", t)

    def test_the_judge_signature_accepts_the_record(self):
        import inspect

        from cria import loop
        self.assertIn("tried", inspect.signature(loop.judge_query).parameters)


if __name__ == "__main__":
    unittest.main()
