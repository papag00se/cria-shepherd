"""The suite's run workspaces must not carry the string `cria`/`shepherd` in their path.

Walked on cart-billing-go x nemotron-elastic 1788241229 call 0061: `RUNS_DIR` was `<repo>/runs`, so
every workspace path the model read (its cwd, every checker's file:line, every absolute path in a
tool result) contained `cria-shepherd` — and the model minted `github.com/jesse/creashepherd` from
it. #17 is that the model never sees the token; the suite's own run placement was leaking it. The
dir is now a neutral durable location outside the repo, SUITE_RUNS_DIR-overridable.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_SUITE = Path(__file__).resolve().parent.parent / "suite"
sys.path.insert(0, str(_SUITE))
_spec = importlib.util.spec_from_file_location("suite_run", _SUITE / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


class TheRunsDirIsNeutralAndDurableTests(unittest.TestCase):
    def test_no_cria_or_shepherd_token_in_the_path(self):
        p = str(run.RUNS_DIR).lower()
        self.assertNotIn("cria", p)
        self.assertNotIn("shepherd", p)

    def test_it_is_not_inside_the_repo(self):
        repo = _SUITE.parent.resolve()
        self.assertNotIn(repo, run.RUNS_DIR.resolve().parents)

    def test_it_is_not_under_tmp_or_cria_home(self):
        # /tmp is cleaned mid-run; ~/.cria has every write refused by writeproxy._targets_cria_home.
        r = run.RUNS_DIR.resolve()
        self.assertFalse(str(r).startswith("/tmp/"))
        self.assertNotIn((Path.home() / ".cria").resolve(), [r, *r.parents])


if __name__ == "__main__":
    unittest.main()
