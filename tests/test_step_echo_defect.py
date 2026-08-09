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

MEASURED before building (principle 15), over all 106 research-step responses in ~/.cria/calls.
Third-person "the coder" appears in exactly two steps — nemotron-nano 20260808T195044 (the walked
run) and r1-llama 20260808T185545. The instruction's closing clause ("output nothing else") appears
in three — those two plus maple-preview 20260806T190731, which also shipped a literal unresolved
"(named below)". Zero of the ~100 legitimate steps trip either arm, including the many that
legitimately borrow the instruction's vocabulary ("identify the task-specific names, structures,
and requirements needed before coding"), which MUST stay accepted: models that scored 4/4 authored
exactly those. (The OTHER nemotron run, 20260808T193637, authored a clean step and is not an echo.)

cria's own prompt induced the surface form — it used to ask for "one sentence instructing the coder
to read the external source" — so it was reworded to ask for an imperative sentence. The arms stay:
r1-llama produced third person on the RETRY path, where that wording was never in front of it.
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
# verbatim, r1-llama's RETRY answer (20260808T185545 call 0003) — third person produced where
# cria's wording was never in front of the model, which is why the arm stands on its own
R1_THIRD_PERSON = ("The coder must first read the API documentation at api.handle.me to "
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


class TheTaskOwnsItsOwnWordsTests(unittest.TestCase):
    """Every sibling arm is silenced when the TASK's own words carry the match (a word the user
    wrote is a fact, not the model echoing cria). The third-person arm now makes that exemption
    too, so a task about a component literally called "the coder" still gets its reading step."""

    CODER_TASK = ("Our repo has two services, the coder and the runner. Read the shared schema "
                  "docs at schema.internal and update the coder to emit the new event fields.")

    def test_a_task_that_names_the_coder_keeps_its_step(self):
        self.assertIsNone(step_defect(
            "Read schema.internal to learn the event field names the coder must emit.",
            self.CODER_TASK, instruction=KNOWN))

    def test_an_ordinary_task_still_refuses_third_person(self):
        self.assertIsNotNone(step_defect(
            "Read schema.internal to learn what the coder must emit.", TASK, instruction=KNOWN))


class TheEchoIsADefectTests(unittest.TestCase):
    def test_the_walked_echo_is_refused(self):
        d = step_defect(NEMO_ECHO, TASK, instruction=KNOWN)
        self.assertIsNotNone(d)
        self.assertIn("third person", d)

    def test_a_step_about_the_coder_is_refused_even_without_the_tail(self):
        d = step_defect(R1_THIRD_PERSON, TASK, instruction=KNOWN)
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
    """The TAIL arm compares the answer against cria's OWN prompt text, so it must stay derivable.

    There is deliberately NO pin that the instruction says "the coder": an earlier draft asserted
    it, which would have blocked the upstream fix — the prompt used to ask for "one sentence
    instructing the coder to read the external source", modelling the very phrasing the walked run
    echoed back. The wording is gone; the arm stays, because a step written in the third person is
    unexecutable by the model holding it however it got there."""

    def test_the_instruction_no_longer_models_third_person(self):
        self.assertNotIn("instructing the coder", KNOWN)

    def test_both_instruction_tails_are_derivable(self):
        self.assertEqual(_instruction_tail(KNOWN), "output nothing else")
        self.assertGreaterEqual(len(_instruction_tail(BLIND).split()), 3)

    def test_a_short_tail_disarms_rather_than_matching_everything(self):
        self.assertEqual(_instruction_tail("Do it."), "")
        self.assertEqual(_instruction_tail(""), "")


if __name__ == "__main__":
    unittest.main()
