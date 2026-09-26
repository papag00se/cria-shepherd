"""preflight's stale-install check must look where suite workspaces actually live.

`stale_suite_installs` flags a user-site `.pth` whose target is a run workspace: a `--yolo` model's
`pip install -e .` leaves one behind, and every later Python process on the box then imports the
dead run's code (found live 2026-08-01). It recognised a run workspace only by a `/tmp/` prefix.
Workspaces moved to the durable `RUNS_DIR` (`~/suite-runs`, or `SUITE_RUNS_DIR`), so the same leak
into a current workspace was invisible to it (found 2026-09-26 during the /tmp cleanup).
"""

import importlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

SUITE = pathlib.Path(__file__).resolve().parent.parent / "suite"
sys.path.insert(0, str(SUITE))


class StaleInstallsSeeRunsDirTests(unittest.TestCase):
    def setUp(self):
        self.pf = importlib.import_module("preflight")
        self.user_site = tempfile.mkdtemp()

    def _found(self, target: str) -> list[dict]:
        pathlib.Path(self.user_site, "__editable__.handle_resolver-0.1.0.pth").write_text(target + "\n")
        with mock.patch.object(self.pf.site, "getusersitepackages", return_value=self.user_site):
            return [f for f in self.pf.stale_suite_installs() if f["target"] == target]

    def test_a_pth_into_a_current_run_workspace_is_flagged(self):
        target = os.path.join(str(self.pf.RUNS_DIR), "suite-handles-cli-node_x_codex_pon_1-abcd1234")
        self.assertEqual(len(self._found(target)), 1)

    def test_a_pth_into_a_temp_workspace_is_still_flagged(self):
        self.assertEqual(len(self._found("/tmp/suite-old-run-abcd1234")), 1)

    def test_a_durable_project_install_is_not_flagged(self):
        self.assertEqual(self._found("/home/someone/src/my-project"), [])

    def test_a_sibling_that_only_shares_the_prefix_is_not_flagged(self):
        self.assertEqual(self._found(str(self.pf.RUNS_DIR) + "-elsewhere/pkg"), [])


if __name__ == "__main__":
    unittest.main()
