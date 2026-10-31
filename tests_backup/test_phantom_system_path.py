"""A steer that names a path nothing on this box provides.

`_phantom_system_path` is what catches it: an absolute path outside the workspace that does not
exist is a fabrication, and a steer built on one sends the coder to read a file that isn't there.

This file used to also cover `research.step_defect`, which vetted cria's OWN authored reading step.
That channel was removed on 2026-08-19 (`docs/audits/base-vs-cria-footgun-patterns.md`) — cria no
longer authors a reading step, so there is nothing of its own left to vet. The steer channel, where
the author has real evidence and the shape is only a trigger, is unaffected and is what remains here.
"""
import unittest

from cria.loop import _phantom_system_path


class PhantomSystemPathTests(unittest.TestCase):
    def test_fabricated_home_path_is_caught(self):
        self.assertEqual(
            _phantom_system_path(
                "The real OpenAPI spec at /home/user1/.cache/api.handle.me/openapi.json contains it.",
                None),
            "/home/user1/.cache/api.handle.me/openapi.json")

    def test_existing_system_path_is_fine(self):
        self.assertEqual(_phantom_system_path("run /usr/bin/python3 against it", None), "")

    def test_workspace_internal_path_is_never_checked(self):
        # A create-target inside the workspace is legitimate even though it does not exist yet.
        self.assertEqual(
            _phantom_system_path("write /home/jesse/ws/brand_new.py with the resolver",
                                 "/home/jesse/ws"), "")

    def test_tmp_paths_are_out_of_scope(self):
        # Workspaces and spill files live under /tmp — the shape is deliberately not policed.
        self.assertEqual(
            _phantom_system_path("read /tmp/reference/api.handle.me_openapi.json", None), "")


if __name__ == "__main__":
    unittest.main()
