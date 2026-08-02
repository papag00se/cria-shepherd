"""An authoring step must stop saying "Write X" once X exists and is failing."""
import tempfile
import unittest
from pathlib import Path

from cria import loop


def ws(**files) -> str:
    d = tempfile.mkdtemp()
    for name, body in files.items():
        p = Path(d) / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


# Verbatim from run ada-handles_mellum2_codex_pon_1785625253, step 4 of 7 — sent unchanged in 33
# consecutive prompts while the file it names sat on disk failing two assertions.
MELLUM_STEP = ("Write unit tests in `test_resolve_handle.py` that mock the API responses using "
               "`unittest.mock` or `responses`. Test `resolve_handle` with a mock response "
               "containing `resolved_addresses.ada`, `holder`, and `total_handles` fields as "
               "defined in the OpenAPI spec. Test `get_holder_total` similarly.")


class ArtifactDetectionTests(unittest.TestCase):
    def test_finds_a_backticked_file_that_exists(self):
        d = ws(**{"test_resolve_handle.py": "x = 1\n"})
        self.assertEqual(loop.step_artifacts_on_disk(MELLUM_STEP, d), ["test_resolve_handle.py"])

    def test_a_file_the_step_names_but_that_does_NOT_exist_is_not_reported(self):
        self.assertEqual(loop.step_artifacts_on_disk(MELLUM_STEP, ws()), [])

    def test_paths_and_other_languages(self):
        d = ws(**{"src__main.go": "package main\n", "README.md": "# x\n"})
        got = loop.step_artifacts_on_disk("Write src/main.go and README.md", d)
        self.assertEqual(sorted(got), ["README.md", "src/main.go"])

    def test_no_workspace_root_reports_nothing(self):
        self.assertEqual(loop.step_artifacts_on_disk(MELLUM_STEP, None), [])

    def test_prose_without_filenames_is_quiet(self):
        d = ws(**{"a.py": "x\n"})
        self.assertEqual(loop.step_artifacts_on_disk("Investigate the API and plan the work", d), [])


class RepairNoteTests(unittest.TestCase):
    def note(self, step, d, red):
        return loop._repair_note(step, d, red)

    def test_the_mellum2_case_now_reframes(self):
        d = ws(**{"test_resolve_handle.py": "assert False\n"})
        note = self.note(MELLUM_STEP, d, True)
        self.assertIn("test_resolve_handle.py", note)
        self.assertIn("already", note)
        self.assertIn("smallest change", note)

    def test_SILENT_when_the_checks_are_green(self):
        # principle 3 — speak only on an actionable signal. A passing repo gets nothing.
        d = ws(**{"test_resolve_handle.py": "x = 1\n"})
        self.assertEqual(self.note(MELLUM_STEP, d, False), "")

    def test_SILENT_when_the_file_does_not_exist_yet(self):
        # principle 2 — never block the FIRST attempt at something. Authoring stays authoring.
        self.assertEqual(self.note(MELLUM_STEP, ws(), True), "")

    def test_both_conditions_required(self):
        self.assertEqual(self.note(MELLUM_STEP, ws(), False), "")

    def test_singular_and_plural_read_correctly(self):
        one = self.note("Write `a.py`", ws(**{"a.py": "x\n"}), True)
        two = self.note("Write `a.py` and `b.py`", ws(**{"a.py": "x\n", "b.py": "y\n"}), True)
        self.assertIn("The file named in this step already exists on disk", one)
        self.assertIn("The files named in this step already exist on disk", two)

    def test_it_claims_nothing_about_what_the_step_ASKED_FOR(self):
        # step_artifacts_on_disk matches EVERY filename token, so the list is "names that appear",
        # not "files this step authors". 14% of 1,052 delivered notes named more than one file.
        # The old wording asserted "this step's wording asks you to WRITE them" over that list.
        note = self.note("Write `a.py` documenting how to run `b.py`",
                         ws(**{"a.py": "x\n", "b.py": "y\n"}), True)
        self.assertNotIn("asks you to WRITE", note)

    def test_it_OVERRIDES_a_contradicting_claim_rather_than_sitting_beside_it(self):
        # Live, run 20260801T232511 call 0097: the step was a critic's essay asserting the files
        # "are not in the workspace", and three lines below cria listed them as present. Both
        # claims stood. cria's disk read is the ground truth and now says so.
        step = ("So the task is NOT satisfied because: 1. a.py and b.py are not in the workspace "
                "2. No README.md exists")
        note = self.note(step, ws(**{"a.py": "x\n", "b.py": "y\n", "README.md": "z\n"}), True)
        self.assertIn("GROUND TRUTH", note)
        self.assertIn("trust it over anything above that says otherwise", note)

    def test_no_broken_grammar_in_any_arity(self):
        # "but them are already written" shipped in 145 captured prompts.
        for files in ({"a.py": "x\n"}, {"a.py": "x\n", "b.py": "y\n"},
                      {"a.py": "x\n", "b.py": "y\n", "c.py": "z\n"}):
            note = self.note(" ".join(f"`{n}`" for n in files), ws(**files), True)
            with self.subTest(n=len(files)):
                self.assertNotIn("them are", note)
                self.assertNotIn("it are", note)
                self.assertNotIn("them is", note)


class ItemPromptTests(unittest.TestCase):
    def test_the_step_text_itself_is_never_altered(self):
        # cria does not AUTHOR work (principle 2 corollary) — the step is passed through verbatim
        # and the note is APPENDED.
        d = ws(**{"test_resolve_handle.py": "assert False\n"})
        out = loop._item_prompt(MELLUM_STEP, "", 4, 7, d, True)
        self.assertIn(MELLUM_STEP, out)
        self.assertIn("Do ONLY this step (4 of 7)", out)
        self.assertIn("smallest change", out)

    def test_green_prompt_is_byte_identical_to_the_old_behaviour(self):
        d = ws(**{"test_resolve_handle.py": "x = 1\n"})
        self.assertEqual(loop._item_prompt(MELLUM_STEP, "", 4, 7, d, False),
                         loop._item_prompt(MELLUM_STEP, "", 4, 7))

    def test_default_args_keep_every_existing_caller_unchanged(self):
        self.assertEqual(loop._item_prompt("Write a.py", "", 1, 1),
                         loop._item_prompt("Write a.py", "", 1, 1, None, False))
