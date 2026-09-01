"""The suite must measure cria, not whatever provider the operator's shell happened to select.

`run.py` launches `codex exec`, which is steered entirely by CODEX_HOME. If the child inherits an
ambient CODEX_HOME — a `.envrc` left active in the cwd, an export in a login profile — the harness
silently repoints and the run scores a different endpoint than the one its row names. So the suite
FORCES its own isolated Codex home onto the child env, and fails closed before a run if that home is
not set up. These tests pin both behaviours.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_SUITE = Path(__file__).resolve().parent.parent / "suite"
sys.path.insert(0, str(_SUITE))   # run.py imports its siblings (sampling, ...) by bare name
_spec = importlib.util.spec_from_file_location("suite_run", _SUITE / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


class CodexHomeIsForcedOntoTheChildEnv(unittest.TestCase):
    def test_it_points_at_the_cria_routing_home(self):
        env = run._codex_env({"PATH": "/x"})
        self.assertEqual(env["CODEX_HOME"], str(run.SUITE_CODEX_HOME))

    def test_an_ambient_codex_home_is_OVERRIDDEN_not_inherited(self):
        # the footgun: operator's shell already has CODEX_HOME set (e.g. a cria .envrc repo).
        env = run._codex_env({"CODEX_HOME": "/home/someone/.codex", "KEEP": "1"})
        self.assertEqual(env["CODEX_HOME"], str(run.SUITE_CODEX_HOME))
        self.assertEqual(env["KEEP"], "1")           # unrelated vars pass through

    def test_the_input_dict_is_not_mutated(self):
        base = {"CODEX_HOME": "/ambient"}
        run._codex_env(base)
        self.assertEqual(base["CODEX_HOME"], "/ambient")

    def test_the_home_lives_under_crias_own_dir(self):
        # cria artifacts stay in ~/.cria, never the workspace or the operator's ~/.codex
        self.assertEqual(run.SUITE_CODEX_HOME, Path.home() / ".cria" / "codex-home")


class TheRunFailsClosedWithoutASetUpHome(unittest.TestCase):
    def test_require_codex_home_raises_when_the_config_is_missing(self):
        orig = run.SUITE_CODEX_HOME
        try:
            run.SUITE_CODEX_HOME = Path("/no/such/cria/codex-home")
            with self.assertRaises(RuntimeError):
                run._require_codex_home()
        finally:
            run.SUITE_CODEX_HOME = orig


if __name__ == "__main__":
    unittest.main()
