"""The live smoke's event trace must land in a durable cria dir, never in /tmp.

scripts/live_model.py hard-coded one old agent session's /tmp scratchpad as its log directory, so
every `swap_and_test.sh` run left cria artifacts in the shared tmpfs (found 2026-09-27).
"""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class LiveSmokeLogDirTests(unittest.TestCase):
    def test_the_trace_dir_is_under_the_cria_home_not_tmp(self):
        spec = importlib.util.spec_from_file_location("live_model", _ROOT / "scripts" / "live_model.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = mod.live_log_dir("phi4")
        self.assertFalse(str(d).startswith("/tmp"), d)
        self.assertEqual(d, Path.home() / ".cria" / "live-smoke" / "cria-live-phi4")


if __name__ == "__main__":
    unittest.main()
