"""The nemotron-nano 1786243834 walk: asked to author ONE reading step, the model echoed cria's
own authoring instruction back, mangled — and `step_defect` had no arm for it, so the echo became
step 1 of the plan:

    Read the external source named "api.handle.me" and instruct the coder to identify the
    task-specific names, structures, and requirements needed before coding. Do not include any
    other information or invent additional paths, files, URLs, or endpoints not named in the
    task. Output nothing else.

Every later coder turn carried a step that (a) casts the executing model as NOT-the-coder and
(b) orders it to output nothing. The coder's replies tracked the poison exactly: "I need to know
the specific task" → "outside the capabilities of this environment" → "it involves verifying the
completion of a task created by another model" → seven consecutive silent calls.

MEASURED before building (principle 15), over all 106 research-step responses in ~/.cria/calls:
third-person "the coder" appears ONLY in the two nemotron echo steps; the instruction's closing
clause ("output nothing else") ONLY in three echoes (the two nemotron runs + maple 1786068407,
which shipped "…and output nothing else" plus a literal unresolved "(named below)"). Zero of the
~100 legitimate steps trip either arm — including the many that legitimately borrow the
instruction's vocabulary ("identify the task-specific names, structures, and requirements needed
before coding"), which MUST stay accepted: models that scored 4/4 authored exactly those.
"""
import unittest

from cria import prompts, research
from cria.research import _instruction_tail, step_defect

TASK = ("I would like you to write a Python script that accepts an Ada Handle as input and "
        "resolves it to the Cardano address using the Ada Handles API (api.handle.me).")

KNOWN = prompts.load("research_step_known")
BLIND = prompts.load("research_step")

# verbatim, nemotron-nano 1786243834 call 0002 — the walked run
NEMO_ECHO = ('Read the external source named "api.handle.me" and instruct the coder to identify '
             "the task-specific names, structures, and requirements needed before coding. Do not "
             "include any other information or invent additional paths, files, URLs, or endpoints "
             "not named in the task. Output nothing else.")
# verbatim, the earlier nemotron run's retry (20260808T185545 call 0003)
NEMO_THIRD_PERSON = ("The coder must first read the API documentation at api.handle.me to "
                     "understand the available endpoints, required parameters, and response "
                     "structures.")
# verbatim head of maple-preview 1786068407 call 0002 (scored 2/4 with this step in place)
MAPLE_ECHO = ("Please read the external source (named below) and identify the task-specific "
              "names, structures, and requirements needed before coding; do not invent paths, "
              "files, URLs, or endpoints not named in the task, and output nothing else.")

# verbatim from the corpus — steps real models authored and ran to real scores
GOOD_STEPS = (
    "Read the api.handle.me documentation to learn how to use the Handles API and retrieve the "
    "resolved Cardano address, holder address, and total handles for the given Ada Handle.",
    "Read the external source named 'api.handle.me' and identify the task-specific names, "
    "structures, and requirements before coding.",
    "Read api.handle.me and identify the task-specific names, structures, and requirements "
    "needed before coding.",
    "Read api.handle.me to learn the request shape, endpoint, query parameters, and JSON "
    "response structure for resolving an Ada Handle to a Cardano address.",
    # 20260808T173411 call 0003 — the RETRY the auth-guess arm produced; 0002 was rightly refused
    "Read the Ada Handles API documentation at api.handle.me to identify the endpoint for "
    "resolving a handle, the request and response formats, and any rate-limiting requirements "
    "before writing the script.",
)


class TheEchoIsADefectTests(unittest.TestCase):
    def test_the_walked_echo_is_refused(self):
        d = step_defect(NEMO_ECHO, TASK, instruction=KNOWN)
        self.assertIsNotNone(d)
        self.assertIn("third person", d)

    def test_a_step_about_the_coder_is_refused_even_without_the_tail(self):
        d = step_defect(NEMO_THIRD_PERSON, TASK, instruction=KNOWN)
        self.assertIsNotNone(d)
        self.assertIn("third person", d)

    def test_the_maple_echo_is_refused_by_the_instruction_tail(self):
        d = step_defect(MAPLE_ECHO, TASK, instruction=KNOWN)
        self.assertIsNotNone(d)
        self.assertIn("output nothing else", d)

    def test_the_blind_variants_own_closer_is_also_a_defect(self):
        d = step_defect("Read the data file and learn its schema. Output only that sentence or "
                        "NONE.", TASK, instruction=BLIND)
        self.assertIsNotNone(d)


class LegitimateStepsStayAcceptedTests(unittest.TestCase):
    """Models that scored 4/4 authored steps that BORROW the instruction's vocabulary — the near-echo
    'Read X and identify the task-specific names…' is the step the instruction dictates, and it must
    never be refused. Only the author-facing clauses are poison."""

    def test_real_corpus_steps_pass(self):
        for s in GOOD_STEPS:
            with self.subTest(step=s[:60]):
                self.assertIsNone(step_defect(s, TASK, instruction=KNOWN))

    def test_no_instruction_no_tail_arm(self):
        self.assertIsNone(step_defect(GOOD_STEPS[0], TASK))


class TheRetryContractStillHoldsTests(unittest.TestCase):
    def test_echo_then_good_retry_yields_the_retry(self):
        answers = iter([NEMO_ECHO, GOOD_STEPS[0]])
        out = research.authored_research_step(lambda s, u: next(answers), TASK,
                                              domain="api.handle.me")
        self.assertEqual(out, GOOD_STEPS[0])

    def test_the_retry_is_told_the_defect(self):
        seen = []
        answers = iter([NEMO_ECHO, GOOD_STEPS[0]])

        def ask(system, user):
            seen.append(user)
            return next(answers)

        research.authored_research_step(ask, TASK, domain="api.handle.me")
        self.assertIn("third person", seen[1])

    def test_echo_twice_yields_no_step(self):
        self.assertEqual(research.authored_research_step(lambda s, u: NEMO_ECHO, TASK,
                                                         domain="api.handle.me"), "")


class ThePromptAndTheMatcherStaySyncedTests(unittest.TestCase):
    """The arms compare the answer against cria's OWN strings. If the prompt files stop saying
    'the coder' or stop closing on a constraint clause, these fail loudly so the arms are
    re-derived rather than left matching vocabulary cria no longer uses."""

    def test_the_instruction_still_says_the_coder(self):
        self.assertIn("the coder", KNOWN)

    def test_both_instruction_tails_are_derivable(self):
        self.assertEqual(_instruction_tail(KNOWN), "output nothing else")
        self.assertGreaterEqual(len(_instruction_tail(BLIND).split()), 3)

    def test_a_short_tail_disarms_rather_than_matching_everything(self):
        self.assertEqual(_instruction_tail("Do it."), "")
        self.assertEqual(_instruction_tail(""), "")


if __name__ == "__main__":
    unittest.main()
