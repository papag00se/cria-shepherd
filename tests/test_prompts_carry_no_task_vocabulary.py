"""No model-facing prompt may speak the current benchmark task's vocabulary.

cria is harness- and task-agnostic; ada-handles is one row of the matrix. A prompt that teaches its
worked example in that task's nouns is overfit by construction — it reads as guidance on every OTHER
task, and on this one it hands the model an answer cria has not earned.

Found by the operator, 2026-08-08, in the exec probe: "If the request names an example input (a
handle, a file, a query)". Sweeping for it turned up three more — plan.txt's research example was
`/handles/{handle}`, selfcompact_summary's example accomplishment was "resolving a handle to an id",
and plan_step_outcome listed "handles" as a category of detail worth keeping.

The English verb ("whoever builds it will handle it there") is not the leak and is not matched. What
is matched is this task's PROPER vocabulary: its domain, its host, its example inputs, its routes and
field names. Comment lines are exempt — commentary cites the walked incident by name on purpose.
"""
import pathlib
import re
import unittest

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "cria" / "prompts"

# The ada-handles task's own words. Add a new task's here when one joins the matrix — the point is
# that NO single task's vocabulary reaches a prompt, not that this one is special.
_TASK_WORDS = re.compile(
    r"(?i)papagoose|goose|cardano|ada\s+handles?|api\.handle\.me"
    r"|resolved_addresses|total_handles|/handles|\{handle\}|handle_type"
    r"|\ba\s+handle\b|\bthe\s+handle\b|\bhandles\)")


class NoPromptSpeaksOneTasksVocabularyTests(unittest.TestCase):
    def test_every_prompt_file(self):
        offenders = []
        for f in sorted(PROMPTS.glob("*.txt")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue                     # commentary names the incident on purpose
                m = _TASK_WORDS.search(line)
                if m:
                    offenders.append(f"{f.name}:{n}: …{line.strip()[max(0, m.start() - 40):m.end() + 40]}…")
        self.assertEqual(offenders, [],
                         "a prompt teaches its example in the benchmark task's nouns:\n"
                         + "\n".join(offenders))

    def test_the_matcher_catches_all_four_that_shipped(self):
        for old in ("If the request names an example input (a handle, a file, a query), put",
                    "a hardcoded request to the endpoint it found, e.g. `/handles/{handle}`",
                    'e.g. "resolving a handle to an id now works — in auth.py"',
                    "(file names, endpoints, field names, handles)"):
            self.assertTrue(_TASK_WORDS.search(old), old)

    def test_the_english_verb_is_not_a_leak(self):
        for ok in ("whoever builds it will handle it there",
                   "the code must handle the error path",
                   "handling a timeout is not optional"):
            self.assertIsNone(_TASK_WORDS.search(ok), ok)


if __name__ == "__main__":
    unittest.main()
