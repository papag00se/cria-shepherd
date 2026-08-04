"""The authored reading step may not bake in guessed routes or invented requirements — and a steer
may not name a system path that does not exist.

Walked 2026-08-04, run ada-handles_gemma4_codex_poff_1785860144 (0/4): call 0001's authored
reading step read "the result of an AUTHENTICATED GET request to api.handle.me/v1/handles/{handle}"
for a task naming only the bare domain. The run spent 38 of 61 calls chasing the invented /v1/
route, a login endpoint that does not exist, and the asserted auth scheme; a steer (0023) then
fabricated "/home/user1/.cache/api.handle.me/openapi.json" and the coder tried to read it. Both
holes were scope gaps in existing enforcement families (location tokens; URL/citation grounding).
"""

import unittest

from cria.loop import _phantom_system_path
from cria.research import step_defect

TASK = ("I would like you to write a Python script that accepts an Ada Handle as input and "
        "resolves it to the Cardano address using the Ada Handles API (api.handle.me).")


class StepGuessShapeTests(unittest.TestCase):
    def test_braced_template_is_refused(self):
        d = step_defect("Read the result of a GET request to api.handle.me/v1/handles/{handle}.", TASK)
        self.assertIsNotNone(d)
        self.assertIn("braced path template", d)

    def test_versioned_path_is_refused(self):
        d = step_defect("Read api.handle.me/v1/lookup to learn the response shape.", TASK)
        self.assertIsNotNone(d)
        self.assertIn("versioned API path", d)

    def test_invented_auth_requirement_is_refused(self):
        d = step_defect("Read the authenticated endpoint list to learn the schema.", TASK)
        self.assertIsNotNone(d)
        self.assertIn("authentication requirement", d)

    def test_clean_domain_only_step_passes(self):
        self.assertIsNone(step_defect(
            "Read api.handle.me to learn its request and response schemas for resolving a handle.",
            TASK))

    def test_task_named_facts_are_not_guesses(self):
        self.assertIsNone(step_defect(
            "Read the docs to learn the api key flow.",
            TASK + " Use the api key I gave you."))
        self.assertIsNone(step_defect(
            "Read api.handle.me/v2/spec to learn the shapes.",
            TASK + " The API lives under /v2/."))


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
            _phantom_system_path("read /tmp/read-only/api.handle.me_openapi.json", None), "")


if __name__ == "__main__":
    unittest.main()
