"""An empty workspace settles a completion claim without asking anyone.

From the full walk of 20260801T160104 (mellum2, ada-handles, 0/4): the critic approved
"Write a CLI script `resolve_handle.py`" three times against an inventory reading
"the workspace has no files at judging time", once refuting itself inside its own reason.
"""
import os
import tempfile
import unittest

from cria import loop


class AbsentArtifactTests(unittest.TestCase):
    STEP = "Write a CLI script `resolve_handle.py` that accepts one argument"

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_empty_workspace_names_the_missing_artifact(self):
        self.assertEqual(loop.step_names_absent_artifact(self.STEP, self.d), "resolve_handle.py")

    def test_a_dotfile_only_workspace_still_counts_as_empty(self):
        # The measured run's listing was `.git/` and nothing else.
        os.mkdir(os.path.join(self.d, ".git"))
        self.assertEqual(loop.step_names_absent_artifact(self.STEP, self.d), "resolve_handle.py")

    def test_any_real_file_hands_the_call_back_to_the_reasoned_brake(self):
        # Deliberately narrow: with files present, a named file may be one the step merely mentions.
        open(os.path.join(self.d, "anything.py"), "w").close()
        self.assertEqual(loop.step_names_absent_artifact(self.STEP, self.d), "")

    def test_a_step_naming_no_file_is_not_blocked(self):
        for step in ("Research the API and note the endpoints",
                     "Determine which endpoint returns the holder address"):
            with self.subTest(step=step):
                self.assertEqual(loop.step_names_absent_artifact(step, self.d), "")

    def test_a_url_path_is_not_a_workspace_artifact(self):
        self.assertEqual(
            loop.step_names_absent_artifact("Fetch https://api.handle.me/openapi.json", self.d), "")

    def test_no_workspace_to_inspect_changes_nothing(self):
        self.assertEqual(loop.step_names_absent_artifact(self.STEP, ""), "")
        self.assertEqual(loop.step_names_absent_artifact(self.STEP, "/nonexistent/xyz"), "")


class ConfirmCompletionTests(unittest.TestCase):
    """The gate runs BEFORE the reasoner — it saves the call and cannot be talked out of it.
    The reasoned brake caught this twice and then flipped to `consistent: true` on the third try."""

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_it_refuses_and_never_calls_the_reasoner(self):
        calls = []

        def reasoner(*a, **k):
            calls.append(a)
            raise AssertionError("the reasoner must not be consulted when disk already answers")

        class L:
            def emit(self, *a, **k): pass

        ok, why = loop._confirm_completion(
            "Write a CLI script `resolve_handle.py`", "the coder says it wrote it",
            self.d, reasoner, None, L(), phase="critic-confirm")
        self.assertFalse(ok)
        self.assertIn("resolve_handle.py", why)
        self.assertEqual(calls, [])
